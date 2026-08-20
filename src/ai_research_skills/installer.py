"""Safe, stdlib-only installer for the standalone research toolbox.

The installer owns individual ordinary suite files, never an entire host configuration.
Fresh operations install no runtime hooks. Legacy hook handlers/files are recognized only
for exact, transactional cleanup during upgrade, doctor, or uninstall; that recognition is
removed in 0.9.0 (see docs/DESIGN.md §4).

Ownership is re-derived from the host layout on every manifest read rather than trusted
from the manifest itself: the SHA-256 seal proves the record was not corrupted, not that
the recorded paths were ever ours.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import errno
import hashlib
import json
import os
import stat
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Generator, Iterable
from typing import Any

try:  # Unix file locks
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows file locks
    import msvcrt
except ImportError:  # pragma: no cover - exercised on Unix
    msvcrt = None  # type: ignore[assignment]

from ai_research_skills import __version__, hook_adapters, hosts

SKILLS = (
    "ars-survey",
    "ars-gap-gate",
    "ars-related-work",
    "ars-watch",
    "ars-decision-brief",
    "ars-red-team",
    "ars-verify",
)
COMMANDS = (
    "ars-audit.md",
    "ars-brief.md",
    "ars-gate.md",
    "ars-help.md",
    "ars-lint.md",
    "ars-relwork.md",
    "ars-survey.md",
    "ars-watch.md",
    "ars-verify.md",
)
HOOK_SCRIPTS = (
    "_payload.py",
    "absence_claim_guard.py",
    "bib_provenance_guard.py",
    "stop_survey_peer.py",
    "survey_staleness.py",
)

_PAYLOAD_DEPENDENT_HANDLERS = frozenset(
    {
        "absence_claim_guard.py",
        "bib_provenance_guard.py",
        "stop_survey_peer.py",
        "survey_staleness.py",
    }
)
SCHEMAS = (
    "corpus.schema.json",
    "coverage.schema.json",
    "gaps.schema.json",
    "protocol.schema.json",
)

# Names from the pre-v0.5 distribution.  Nothing in this package reads them: recognition
# of old assets goes through the ``rs-`` prefix in `_legacy_notice` and `_OWNED_PREFIXES`
# below.  They are kept as published constants for the 0.8 compatibility window and go
# away with the rest of the legacy path in 0.9.0.
LEGACY_SKILLS = tuple(name.removeprefix("a") for name in SKILLS)
LEGACY_COMMANDS = tuple(name.removeprefix("a") for name in COMMANDS)

# Ownership is an exact inventory, not a namespace reservation.  The current inventory
# is derived from `_desired_files`; the only historical additions come from the committed
# v0.5 fingerprint.  In particular, a future/private `ars-*` name is not ours merely
# because it shares a directory with a current asset.


ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
SRC_SKILLS = os.path.join(ASSETS, "skills")
SRC_COMMANDS = os.path.join(ASSETS, "commands")
SRC_SCRIPTS = os.path.join(ASSETS, "scripts")
SRC_SCHEMAS = os.path.join(ASSETS, "schemas")
MANIFEST_REL = ".ai-research-skills/manifest.json"
JOURNAL_REL = ".ai-research-skills/transaction.json"
LEGACY_FINGERPRINT_REL = os.path.join("legacy", "v0.5.0.json")
# Format 1 was emitted by the pre-0.8 installer.  Keep accepting it long enough to
# migrate package-owned state, but never emit it again: an older installer treats format 1
# as a live hook-enabled manifest and can reinstall governance handlers during downgrade.
LEGACY_MANIFEST_FORMAT = 1
MANIFEST_FORMAT = 2
# Format 1 journals recorded only the pre-transaction snapshot, so recovery had to trust
# that whatever it found on disk was the interrupted write.  Format 2 also records the
# state each target was meant to end in, which lets recovery tell "the transaction was
# interrupted" from "somebody edited this file after the crash" and refuse the second.
LEGACY_JOURNAL_FORMAT = 1
JOURNAL_FORMAT = 2

CLAUDE_ROOT = ".claude"
CLAUDE_PROJECT_DIR = "$CLAUDE_PROJECT_DIR/"


class InstallerError(RuntimeError):
    pass


def _posix_modes() -> bool:
    """Whether this runtime has reliable POSIX permission semantics."""
    return os.name == "posix"


def _canonical_project_path(root: str) -> str:
    """Return a realpath identity while retaining POSIX case for samefile safety."""
    return os.path.normcase(os.path.realpath(os.path.abspath(root)))


def _project_path_identity(root: str) -> str:
    """Return the lock identity that remains stable before and after creation."""
    return f"path:{_canonical_project_path(root).casefold()}"


def _journal_root_matches(  # noqa: PLR0911
    root: str,
    recorded: object,
    recorded_path: object = None,
    recorded_inode: object = None,
) -> bool:
    """Accept canonical and pre-canonical journal roots without widening identity.

    Every accepted spelling is absolute.  A relative one such as ``"."`` resolves against
    the current working directory instead of anything tied to the journal, so a journal
    committed to a repository would authorize itself the moment a user ran from that
    repository's root.  Format 2 additionally pins the root's device/inode, which a
    journal shipped inside a repository cannot predict for another machine's clone.
    """
    if not isinstance(recorded, str):
        return False
    current_path = _canonical_project_path(root)
    if recorded_inode is not None and (
        not isinstance(recorded_inode, str)
        or recorded_inode != _project_root_identity(root)
    ):
        return False
    if isinstance(recorded_path, str):
        # New journals retain the lock identity and a case-preserving canonical path.  The
        # latter prevents two case-distinct POSIX roots from sharing the folded lock name.
        if recorded != _project_path_identity(root) or not os.path.isabs(recorded_path):
            return False
        try:
            if os.path.samefile(recorded_path, root):
                return True
        except (OSError, ValueError):
            pass
        return (
            os.path.normcase(os.path.realpath(os.path.abspath(recorded_path)))
            == current_path
        )
    if recorded == _project_path_identity(root):
        return True
    # Format 1/early format 2 stored an absolute spelling.  samefile handles aliases
    # on filesystems whose case rules are not represented by normcase; realpath keeps
    # equivalent symlink spellings compatible without accepting a different root.
    if not os.path.isabs(recorded):
        return False
    try:
        if os.path.samefile(recorded, root):
            return True
    except (OSError, ValueError):
        pass
    return _canonical_project_path(recorded) == current_path


def _project_root_identity(root: str) -> str:
    """Return an inode identity for an existing project root.

    Existing roots can use the filesystem's device/inode pair, which also handles
    symlink and case aliases without assuming the host's spelling rules.  Filesystems
    that do not provide a usable inode fall back to the normalized real path.  A root
    that does not exist yet uses the same canonical path identity as the stable path
    lock, including realpath resolution through existing ancestors.
    """
    absolute = os.path.abspath(root)
    try:
        root_stat = os.stat(absolute)
    except OSError:
        return _project_path_identity(absolute)

    device = getattr(root_stat, "st_dev", None)
    inode = getattr(root_stat, "st_ino", None)
    if device is not None and inode not in (None, 0):
        return f"stat:{device}:{inode}"
    return _project_path_identity(absolute)


def _lock_directory_path() -> str:
    """Return the stable per-user directory used for inter-process locks."""
    if os.name == "nt":  # pragma: no cover - Windows path
        # Windows' temp directory is normally already private to the user.  Keep
        # this fallback there so the existing msvcrt byte-range lock remains usable.
        return os.path.join(tempfile.gettempdir(), "ai-research-skills")
    return os.path.join(os.path.sep, "tmp", f"ai-research-skills-{os.getuid()}")


def _ensure_lock_directory() -> None:
    """Create and validate the private POSIX lock directory."""
    directory = _lock_directory_path()
    if os.name == "nt":  # pragma: no cover - Windows path
        os.makedirs(directory, mode=0o700, exist_ok=True)
        return

    uid = os.getuid()
    try:
        info = os.lstat(directory)
    except FileNotFoundError:
        with contextlib.suppress(FileExistsError):
            os.mkdir(directory, 0o700)
        info = os.lstat(directory)
    if _is_redirect(info):
        raise InstallerError(f"lock directory is a symlink: {directory}")
    if not stat.S_ISDIR(info.st_mode):
        raise InstallerError(f"lock path is not a directory: {directory}")
    if info.st_uid != uid:
        raise InstallerError(
            f"lock directory is not owned by the current user: {directory}"
        )
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise InstallerError(f"lock directory has unsafe permissions: {directory}")


class _ProjectLock:
    """Blocking OS lock keyed by a normalized project identity.

    The lock file lives in a stable per-user directory rather than in the project.
    That keeps a conflict/no-op preflight byte-for-byte non-mutating, while the stable
    name still serialises all processes operating on one project.  The file may remain
    after a crash; the OS lock itself cannot.
    """

    def __init__(self, root: str, *, identity: str | None = None) -> None:
        self.identity = identity if identity is not None else _project_root_identity(root)
        digest = hashlib.sha256(self.identity.encode()).hexdigest()
        self.path = os.path.join(
            _lock_directory_path(), f"ai-research-skills-{digest}.lock"
        )
        self.fd: int | None = None

    def __enter__(self) -> _ProjectLock:
        _ensure_lock_directory()
        flags = os.O_RDWR | os.O_CREAT
        if os.name != "nt":
            flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            self.fd = os.open(self.path, flags, 0o600)
            if os.name != "nt":
                info = os.fstat(self.fd)
                if not stat.S_ISREG(info.st_mode):
                    raise InstallerError(f"lock path is not a regular file: {self.path}")
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                    raise InstallerError(
                        f"lock file has unsafe ownership or permissions: {self.path}"
                    )
                if stat.S_IMODE(info.st_mode) != 0o600:
                    os.fchmod(self.fd, 0o600)
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_EX)
            elif msvcrt is not None:  # pragma: no cover - Windows path
                if os.path.getsize(self.path) == 0:
                    os.write(self.fd, b"0")
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_LOCK, 1)
            else:  # pragma: no cover - every supported platform has one
                raise InstallerError("no stdlib OS file-lock implementation is available")
        except Exception:
            if self.fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self.fd)
                self.fd = None
            raise
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self.fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows path
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(self.fd)
            self.fd = None


def _project_path_lock(root: str) -> _ProjectLock:
    """Return the lock shared by every operation for this root spelling."""
    absolute = os.path.abspath(root)
    return _ProjectLock(absolute, identity=_project_path_identity(absolute))


def _project_lock(root: str) -> _ProjectLock:
    """Return the lock for the root inode currently named by ``root``."""
    return _ProjectLock(os.path.abspath(root))


def is_ours(command: str, host: hosts.Host | None = None, root: str | None = None) -> bool:
    """Return true only for an exact generated or published migration command."""
    return hook_adapters.is_ours(command, host, root)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _seal_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result["manifest_sha256"] = _sha256(_canonical(result))
    return result


def _manifest_valid(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    format_number = data.get("format")
    if not isinstance(format_number, int) or isinstance(format_number, bool):
        return False
    supplied = data.get("manifest_sha256")
    if not isinstance(supplied, str):
        return False
    unsigned = dict(data)
    unsigned.pop("manifest_sha256", None)
    return supplied == _sha256(_canonical(unsigned))


def _relative(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _is_redirect(info: os.stat_result) -> bool:
    """Whether this entry redirects elsewhere in the filesystem.

    A POSIX symlink sets `S_IFLNK`.  On Windows a directory junction is a reparse point
    that CPython reports as an ordinary directory — `S_ISLNK` is false for it — so a
    junction planted at `.claude` would have passed the symlink check and let writes and
    deletions land outside the project root.  Every name-surrogate reparse tag redirects
    the same way, so the tag is what decides when the platform exposes one.
    """
    if stat.S_ISLNK(info.st_mode):
        return True
    tag = getattr(info, "st_reparse_tag", 0)
    return bool(tag) and bool(tag & 0x2000_0000)  # IsNameSurrogate bit


def _safe_path(root: str, relative: str, *, allow_root: bool = False) -> str:
    """Resolve a target and reject symlink components and traversal."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise InstallerError(f"target root is not an existing directory: {root}")
    root_stat = os.lstat(root)
    if _is_redirect(root_stat):
        raise InstallerError(f"target root is a symlink: {root}")
    if os.path.isabs(relative):
        raise InstallerError(f"absolute path is not allowed: {relative}")
    parts = [
        part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")
    ]
    if any(part == ".." for part in parts):
        raise InstallerError(f"path escapes target root: {relative}")
    current = root
    for part in parts:
        current = os.path.join(current, part)
        if os.path.lexists(current) and _is_redirect(os.lstat(current)):
            raise InstallerError(
                f"symlink target/ancestor refused: {_relative(root, current)}"
            )
    if not parts and not allow_root:
        raise InstallerError("empty managed path")
    candidate = os.path.abspath(os.path.join(root, *parts))
    if os.path.commonpath((root, candidate)) != root:
        raise InstallerError(f"path escapes target root: {relative}")
    return candidate


def _relative_parts(value: str) -> list[str]:
    return [part for part in value.replace("\\", "/").split("/") if part not in ("", ".")]


def _canonical_relative(value: object) -> str | None:
    """Return a canonical relative path, rejecting aliases rather than normalising them.

    Every alias is rejected by the segment check: a leading, trailing or doubled
    separator leaves an empty segment, and `.`/`..` are named outright.  A final
    `"/".join(value.split("/")) == value` comparison used to stand here as if it were a
    second gate, but it holds for every string, so it only made the real check look
    optional.
    """
    if not isinstance(value, str) or not value or os.path.isabs(value):
        return None
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return normalized


def _published_legacy_paths(host: hosts.Host) -> frozenset[str]:
    """Read only the explicit old file paths published in the v0.5 fingerprint."""
    path = os.path.join(ASSETS, LEGACY_FINGERPRINT_REL)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return frozenset()
    host_data = data.get("hosts", {}).get(host.id) if isinstance(data, dict) else None
    files = host_data.get("files") if isinstance(host_data, dict) else None
    if not isinstance(files, dict):
        return frozenset()
    root_parts = _relative_parts(host.ownership_root)
    allowed: set[str] = set()
    for relative in files:
        canonical = _canonical_relative(relative)
        if canonical is None:
            continue
        parts = _relative_parts(canonical)
        if parts[: len(root_parts)] != root_parts:
            continue
        rest = parts[len(root_parts) :]
        # The committed legacy inventory contains only these package asset namespaces;
        # this extra shape check keeps a damaged fingerprint from authorising a root file.
        if not rest or rest[0] not in {"skills", "commands", "hooks", "ai-research-skills"}:
            continue
        allowed.add(canonical)
    return frozenset(allowed)


def _desired_relative_paths(host: hosts.Host) -> frozenset[str]:
    """Return the exact relative paths `_desired_files` can generate for *host*."""
    desired: set[str] = set()
    for skill in SKILLS:
        source_root = os.path.join(SRC_SKILLS, skill)
        for source in _source_files(source_root):
            desired.add(
                os.path.join(
                    host.skills_dir,
                    skill,
                    os.path.relpath(source, source_root),
                ).replace(os.sep, "/")
            )
    if host.commands_dir:
        desired.update(
            os.path.join(host.commands_dir, name).replace(os.sep, "/")
            for name in COMMANDS
            if os.path.isfile(os.path.join(SRC_COMMANDS, name))
        )
    for source_root, directory in (
        (SRC_SCRIPTS, "scripts"),
        (SRC_SCHEMAS, "schemas"),
    ):
        for source in _source_files(source_root):
            desired.add(
                os.path.join(
                    host.ownership_root,
                    "ai-research-skills",
                    directory,
                    os.path.relpath(source, source_root),
                ).replace(os.sep, "/")
            )
    return frozenset(desired)


def _owned_asset_paths(host: hosts.Host) -> frozenset[str]:
    return _desired_relative_paths(host) | _published_legacy_paths(host)


def _historical_config_path(host: hosts.Host) -> str:
    return os.path.join(host.ownership_root, host.hooks_file).replace(os.sep, "/")


def owned_manifest_path(host: hosts.Host, relative: str) -> bool:
    """Whether *relative* is an exact generated or published legacy asset path.

    The manifest's SHA-256 seal proves the record was not corrupted in transit; it does
    not prove the recorded paths were ever ours, because anyone who can write the file can
    re-seal it.  Ownership is therefore re-derived from this exact inventory on every
    read.  Unknown future/private names and arbitrary namespace descendants are rejected.
    """
    canonical = _canonical_relative(relative)
    return canonical is not None and canonical in _owned_asset_paths(host)


def _assert_owned(host: hosts.Host, relative: str, context: str) -> None:
    if not owned_manifest_path(host, relative):
        raise InstallerError(
            f"{context} claims {relative!r}, which is not an ai-research-skills asset "
            f"path for host {host.id!r}; refusing to treat it as package-owned"
        )


def _read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallerError(f"cannot read {path}: {exc}") from exc


FileState = tuple[str, str | None, int | None]
FileSnapshot = tuple[FileState, bytes | None]


def _inode_identity(info: os.stat_result) -> tuple[int, int]:
    """Identify the inode behind a stat result.

    Platforms without meaningful inode numbers report the same placeholder for every
    file, which degrades the comparisons below to the file-type and mode checks.
    """
    return info.st_dev, info.st_ino


def _content_identity(info: os.stat_result) -> tuple[int, int, int]:
    """Detect in-place modification of an open file, which keeps its inode."""
    return info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _capture_file(path: str) -> FileSnapshot:
    """Read one regular-file snapshot from a descriptor, or classify its path.

    The digest and mode come from the same descriptor read.  A path replacement or
    mode change during that read is retried rather than turned into an approved state:
    an editor that saves by writing a new inode and renaming it over this path would
    otherwise let a digest of the replaced inode stand in for the file now at *path*,
    and every caller here uses that digest as a compare-and-set token before it
    overwrites or unlinks the very same path.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if os.name != "nt":
        flags |= getattr(os, "O_NOFOLLOW", 0)
    for _attempt in range(3):
        try:
            path_info = os.lstat(path)
        except FileNotFoundError:
            try:
                fd = os.open(path, flags)
            except FileNotFoundError:
                return ("absent", None, None), None
            else:
                os.close(fd)
                continue
        except OSError as exc:
            raise InstallerError(f"cannot stat {path}: {exc}") from exc
        if stat.S_ISLNK(path_info.st_mode):
            return ("symlink", None, None), None
        if not stat.S_ISREG(path_info.st_mode):
            return ("other", None, None), None
        path_mode = stat.S_IMODE(path_info.st_mode) if _posix_modes() else None
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise InstallerError(f"cannot read {path}: {exc}") from exc
        try:
            descriptor_info = os.fstat(fd)
            if not stat.S_ISREG(descriptor_info.st_mode):
                continue
            if _posix_modes() and stat.S_IMODE(descriptor_info.st_mode) != path_mode:
                continue
            if _inode_identity(descriptor_info) != _inode_identity(path_info):
                # The path was replaced between the stat above and this open.
                continue
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            final_info = os.fstat(fd)
        finally:
            os.close(fd)
        try:
            final_path_info = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(final_path_info.st_mode) or not stat.S_ISREG(
            final_path_info.st_mode
        ):
            continue
        if _content_identity(final_info) != _content_identity(descriptor_info):
            # The bytes just read were rewritten in place, so the digest may be torn.
            continue
        if _inode_identity(final_path_info) != _inode_identity(descriptor_info):
            # The digest describes an inode that this path no longer names, and the
            # caller is about to use it to authorize replacing or unlinking the path.
            continue
        if _posix_modes() and (
            stat.S_IMODE(final_info.st_mode) != stat.S_IMODE(descriptor_info.st_mode)
            or stat.S_IMODE(final_path_info.st_mode)
            != stat.S_IMODE(descriptor_info.st_mode)
        ):
            continue
        data = b"".join(chunks)
        return (
            "regular",
            _sha256(data),
            stat.S_IMODE(descriptor_info.st_mode) if _posix_modes() else None,
        ), data
    raise InstallerError(f"file changed while reading {path}")


def _json_object_from_bytes(path: str, data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerError(
            f"{path} is not valid JSON; refusing to mutate it: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise InstallerError(f"{path} is not a JSON object; refusing to mutate it")
    return value


def _atomic_write(
    path: str,
    data: bytes,
    mode: int | None = 0o644,
    *,
    before_replace: Callable[[], None] | None = None,
) -> None:
    """Write and fsync a temp file, then run the final target CAS before replace."""
    directory = os.path.dirname(path) or "."
    # Callers create and revalidate the destination directory before this point.
    fd, temporary = tempfile.mkstemp(prefix=".ars-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            # File fsync is part of the replace guarantee and remains required on
            # every platform.  Directory fsync is a separate capability below.
            os.fsync(fh.fileno())
            if _posix_modes() and mode is not None:
                os.chmod(temporary, stat.S_IMODE(mode))
                # Include the permission metadata in the durable temp-file state before
                # the caller's last-moment target CAS.
                os.fsync(fh.fileno())
        if before_replace is not None:
            before_replace()
        os.replace(temporary, path)
        _fsync_directory(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json_bytes(data: Any) -> bytes:
    """Serialise exactly as the transaction writes it, so digests cannot drift."""
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def _atomic_json(path: str, data: dict[str, Any], mode: int | None = 0o644) -> None:
    _atomic_write(path, _json_bytes(data), mode)


def _load_json(path: str) -> dict[str, Any]:
    state, data = _capture_file(path)
    if state[0] == "absent":
        raise InstallerError(
            f"{path} is not valid JSON; refusing to mutate it: file not found"
        )
    if state[0] != "regular" or data is None:
        raise InstallerError(f"{path} is not a regular JSON file; refusing to mutate it")
    return _json_object_from_bytes(path, data)


def load_settings(path: str) -> dict[str, Any]:
    return _load_json(path) if os.path.exists(path) else {}


def _source_files(directory: str) -> list[str]:
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        for filename in filenames:
            if filename.endswith(".pyc"):
                continue
            result.append(os.path.join(dirpath, filename))
    return sorted(result)


def localise(text: str, host: hosts.Host) -> str:
    if host.id == "claude":
        return text
    return (
        text.replace(f"{CLAUDE_PROJECT_DIR}{CLAUDE_ROOT}/", f"{host.ownership_root}/")
        .replace(f"{CLAUDE_ROOT}/", f"{host.ownership_root}/")
        .replace(CLAUDE_PROJECT_DIR, "")
    )


def _desired_files(root: str, host: hosts.Host) -> dict[str, bytes]:
    """Build all ordinary files before the transaction starts."""
    desired: dict[str, bytes] = {}

    def add_file(relative: str, source: str, localise_markdown: bool = False) -> None:
        path = _safe_path(root, relative)
        if localise_markdown and source.endswith(".md"):
            with open(source, encoding="utf-8") as fh:
                data = localise(fh.read(), host).encode()
        else:
            with open(source, "rb") as fh:
                data = fh.read()
        desired[path] = data

    for skill in SKILLS:
        source_root = os.path.join(SRC_SKILLS, skill)
        # `_source_files` walks the directory, and `os.walk` on a path that does not exist
        # yields nothing at all.  Without this check a skill renamed or mistyped in SKILLS
        # produced a wheel that installed a silently incomplete suite — the worst failure
        # mode for a distribution tool, and the asymmetric one, since COMMANDS opens its
        # files directly and would already have raised.
        if not os.path.isdir(source_root):
            raise InstallerError(
                f"packaged skill {skill!r} has no source directory at {source_root}; "
                "the SKILLS list and the shipped assets have diverged"
            )
        for source in _source_files(source_root):
            relative_inside = os.path.relpath(source, source_root)
            add_file(
                os.path.join(host.skills_dir, skill, relative_inside),
                source,
                localise_markdown=True,
            )
    if host.commands_dir:
        for name in COMMANDS:
            add_file(
                os.path.join(host.commands_dir, name),
                os.path.join(SRC_COMMANDS, name),
                True,
            )
    for source in _source_files(SRC_SCRIPTS):
        add_file(
            os.path.join(
                host.ownership_root,
                "ai-research-skills",
                "scripts",
                os.path.relpath(source, SRC_SCRIPTS),
            ),
            source,
        )
    for source in _source_files(SRC_SCHEMAS):
        add_file(
            os.path.join(
                host.ownership_root,
                "ai-research-skills",
                "schemas",
                os.path.relpath(source, SRC_SCHEMAS),
            ),
            source,
        )
    return desired


def _manifest_path(root: str) -> str:
    return _safe_path(root, MANIFEST_REL)


def _journal_path(root: str) -> str:
    return _safe_path(root, JOURNAL_REL)


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == hashlib.sha256().digest_size * 2
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _validate_handler_record(host_id: str, handler: object) -> None:
    if not isinstance(handler, dict):
        raise InstallerError(f"manifest host {host_id!r} handler is malformed")
    required = {"event", "script", "command", "matcher", "timeout", "definition"}
    optional = {
        "effective_matcher",
        "group_matcher",
        "wrapper_matcher",
        "wrapper",
        "wrapper_metadata",
        "group",
        "group_metadata",
    }
    if not required.issubset(handler) or set(handler) - required - optional:
        raise InstallerError(f"manifest host {host_id!r} handler shape is invalid")
    if not isinstance(handler["event"], str) or not handler["event"]:
        raise InstallerError(f"manifest host {host_id!r} handler event is invalid")
    if handler["script"] not in HOOK_SCRIPTS:
        raise InstallerError(f"manifest host {host_id!r} handler script is invalid")
    if not isinstance(handler["command"], str) or not handler["command"]:
        raise InstallerError(f"manifest host {host_id!r} handler command is invalid")
    matcher = handler["matcher"]
    if matcher is not None and not isinstance(matcher, str):
        raise InstallerError(f"manifest host {host_id!r} handler matcher is invalid")
    timeout = handler["timeout"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
        raise InstallerError(f"manifest host {host_id!r} handler timeout is invalid")
    if not isinstance(handler["definition"], dict):
        raise InstallerError(f"manifest host {host_id!r} handler definition is invalid")
    for key in optional:
        if key not in handler:
            continue
        value = handler[key]
        if key.endswith("matcher"):
            if value is not None and not isinstance(value, str):
                raise InstallerError(f"manifest host {host_id!r} handler {key} is invalid")
        elif not isinstance(value, dict):
            raise InstallerError(f"manifest host {host_id!r} handler {key} is invalid")


def _read_manifest_snapshot(
    root: str,
) -> tuple[dict[str, Any] | None, FileState, bytes | None]:
    metadata = os.path.join(os.path.abspath(root), ".ai-research-skills")
    if os.path.lexists(metadata):
        _ensure_metadata_directory(root, create=False)
    path = _manifest_path(root)
    state, raw = _capture_file(path)
    if state[0] == "absent":
        return None, state, None
    if state[0] != "regular" or raw is None:
        raise InstallerError(".ai-research-skills/manifest.json is not a regular file")
    data = _json_object_from_bytes(path, raw)
    if not _manifest_valid(data):
        raise InstallerError(
            ".ai-research-skills/manifest.json was modified or has an invalid "
            "integrity seal"
        )
    if (
        data.get("format") not in {LEGACY_MANIFEST_FORMAT, MANIFEST_FORMAT}
        or data.get("package") != "ai-research-skills"
    ):
        raise InstallerError("manifest format/package is not owned by this installer")
    if not isinstance(data.get("hosts"), dict):
        raise InstallerError("manifest hosts is not an object")
    for host_id, record in data["hosts"].items():
        if not isinstance(host_id, str):
            raise InstallerError("manifest host id is not a string")
        record_host = hosts.lookup(host_id)
        if record_host is None:
            # Future host records are opaque compatibility data.  They are carried
            # byte-for-byte in the next manifest and never authorize current operations.
            continue
        if not isinstance(record, dict) or not isinstance(record.get("files"), dict):
            raise InstallerError(f"manifest host {host_id!r} is malformed")
        retired: list[str] = []
        for relative, digest in record["files"].items():
            if not isinstance(relative, str) or not _valid_digest(digest):
                raise InstallerError(f"manifest file record for {host_id!r} is malformed")
            canonical = _canonical_relative(relative)
            if canonical is None:
                raise InstallerError(f"manifest path for {host_id!r} is not canonical")
            _safe_path(root, relative)
            if not owned_manifest_path(record_host, relative):
                # A path this build no longer generates is a stale record, not a fatal
                # one.  Renaming or retiring any asset would otherwise wedge install,
                # doctor and uninstall alike, leaving deleting the manifest by hand as
                # the only way forward.  Ownership stays enforced where it decides an
                # action: nothing below may write or delete a path dropped here.
                retired.append(relative)
        for relative in retired:
            del record["files"][relative]
        config = record.get("config")
        if config is not None:
            if config != _historical_config_path(record_host):
                raise InstallerError(
                    f"manifest host {host_id!r} config is not its exact historical path"
                )
            _safe_path(root, config)
        handlers = record.get("handlers", [])
        if not isinstance(handlers, list):
            raise InstallerError(f"manifest host {host_id!r} handlers is not a list")
        for handler in handlers:
            _validate_handler_record(host_id, handler)
    # File bytes are intentionally checked by the selected mutation/doctor paths rather
    # than here.  A manifest with five changed files must produce five doctor items, not
    # fail while reading the first one and hide the rest.
    return data, state, raw


def _read_manifest(root: str) -> dict[str, Any] | None:
    data, _state, _raw = _read_manifest_snapshot(root)
    return data


def retired_manifest_paths(raw: bytes | None) -> list[str]:
    """List recorded paths this build no longer generates, for reporting.

    `_read_manifest_snapshot` drops these records so no later step can act on a path it
    cannot prove it owns; the files themselves stay on disk.  Recomputing from the raw
    bytes keeps that pruning invisible to every caller except the ones that report it.
    """
    if raw is None:
        return []
    try:
        data = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("hosts"), dict):
        return []
    found: list[str] = []
    for host_id, record in data["hosts"].items():
        record_host = hosts.lookup(host_id) if isinstance(host_id, str) else None
        if record_host is None or not isinstance(record, dict):
            continue
        files = record.get("files")
        if not isinstance(files, dict):
            continue
        found.extend(
            relative
            for relative in files
            if isinstance(relative, str) and not owned_manifest_path(record_host, relative)
        )
    return sorted(set(found))


def _report_retired(paths: list[str]) -> None:
    """Report records dropped by the read above, which leave their files behind."""
    for relative in paths:
        print(
            f"  preserved {relative}  "
            "(recorded by another version of this package; remove the file by hand)"
        )


def _legacy_notice(root: str, host: hosts.Host) -> list[str]:
    """List direct pre-v0.5 ``rs-*`` assets without inspecting or deleting them."""
    found: list[str] = []
    skills_root = _safe_path(root, host.skills_dir, allow_root=True)
    if os.path.isdir(skills_root) and not os.path.islink(skills_root):
        for name in sorted(os.listdir(skills_root)):
            if not name.startswith("rs-"):
                continue
            path = _safe_path(root, os.path.join(host.skills_dir, name), allow_root=True)
            if os.path.isdir(path) and not os.path.islink(path):
                found.append(f"{host.skills_dir}/{name}/")
    if host.commands_dir:
        commands_root = _safe_path(root, host.commands_dir, allow_root=True)
        if os.path.isdir(commands_root) and not os.path.islink(commands_root):
            for name in sorted(os.listdir(commands_root)):
                if not name.startswith("rs-"):
                    continue
                path = _safe_path(root, os.path.join(host.commands_dir, name))
                if os.path.isfile(path) and not os.path.islink(path):
                    found.append(f"{host.commands_dir}/{name}")
    return found


def _legacy_guard(root: str, host: hosts.Host) -> None:
    found = _legacy_notice(root, host)
    if found:
        raise InstallerError(
            "pre-v0.5 rs-* assets cannot coexist with ars-* automatically: "
            + ", ".join(found)
            + "; migrate or rename them manually. No legacy asset was deleted."
        )


def _manifest_host_record(
    root: str, host: hosts.Host, desired: dict[str, bytes], settings: dict[str, Any]
) -> dict[str, Any]:
    """Record only files installed by the standalone 0.8 toolbox.

    Hook configuration is deliberately absent from new manifests.  ``settings`` remains
    in the signature for callers from older versions, but it is never inspected or
    written into a fresh manifest.
    """
    files = {_relative(root, path): _sha256(data) for path, data in sorted(desired.items())}
    return {
        "files": files,
        "config": None,
        "handlers": [],
        "adapter": "none",
    }


def _record_handlers(record: dict[str, Any]) -> list[dict[str, Any]]:
    value = record.get("handlers")
    return value if isinstance(value, list) else []


def _manifest_digest_for(
    manifest: dict[str, Any] | None, relative: str, host_id: str | None = None
) -> str | None:
    """Return only the selected host's canonical manifest digest.

    Records for hosts introduced by a future release are carried through the manifest,
    but they are never evidence that this host owns a path.
    """
    if not isinstance(host_id, str):
        return None
    records = (manifest or {}).get("hosts")
    if not isinstance(records, dict):
        return None
    record = records.get(host_id)
    if not isinstance(record, dict):
        return None
    canonical = _canonical_relative(relative)
    files = record.get("files")
    if canonical is None or not isinstance(files, dict):
        return None
    digest = files.get(canonical)
    return digest if isinstance(digest, str) else None


def _preflight_file_conflicts(  # noqa: PLR0913
    root: str,
    desired: dict[str, bytes],
    *,
    manifest: dict[str, Any] | None,
    old_record: dict[str, Any] | None = None,
    legacy_hashes: dict[str, str] | None = None,
    host_id: str | None = None,
    observed_before: dict[str, FileSnapshot] | None = None,
) -> dict[str, FileSnapshot]:
    """Reject unknown files and retain each decision's exact observed snapshot."""
    old_files = (old_record or {}).get("files", {})
    if not isinstance(old_files, dict):
        old_files = {}
    legacy_hashes = legacy_hashes or {}
    observed_before = observed_before if observed_before is not None else {}
    for path, data in desired.items():
        relative = _relative(root, path)
        _safe_path(root, relative)
        snapshot = _capture_file(path)
        observed_before[path] = snapshot
        state, current = snapshot
        if state[0] == "absent":
            continue
        if state[0] == "symlink":
            raise InstallerError(f"target file is a symlink: {relative}")
        if state[0] != "regular" or current is None:
            raise InstallerError(f"same-name target is not a regular file: {relative}")
        if current == data:
            continue
        old_digest = old_files.get(relative)
        if not isinstance(old_digest, str):
            old_digest = _manifest_digest_for(manifest, relative, host_id)
        if old_digest and state[1] == old_digest:
            continue
        if legacy_hashes.get(relative) == state[1]:
            continue
        raise InstallerError(f"same-name unknown/conflicting file: {relative}")
    return observed_before


def _is_obsolete_hook_path(host: hosts.Host, relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    prefix = f"{host.ownership_root}/hooks/"
    return normalized.startswith(prefix) and normalized.rsplit("/", 1)[-1] in HOOK_SCRIPTS


def _referenced_hook_scripts(settings: dict[str, Any] | None, host: hosts.Host) -> set[str]:
    """Hook scripts a surviving command still names, whatever its exact spelling.

    Recognition is deliberately exact, so a command this installer does not recognise —
    a variant spelling, an added interpreter flag, a wrapper — is left in the host's
    configuration untouched.  Deleting the script behind it would leave the host firing a
    handler whose program is gone, which is worse than either keeping both or removing
    both.  Substring matching is the right test here precisely because it does not
    require the command to be one of ours.
    """
    if not isinstance(settings, dict):
        return set()
    prefix = f"{host.ownership_root}/hooks/"
    referenced: set[str] = set()
    for command in hook_adapters.all_config_commands(settings):
        if not isinstance(command, str):
            continue
        normalized = command.replace("\\", "/")
        referenced.update(
            script for script in HOOK_SCRIPTS if f"{prefix}{script}" in normalized
        )
    return referenced


def _modified_handler_paths(
    root: str,
    host: hosts.Host,
    modified_handlers: Iterable[str],
    *,
    owned_relatives: Iterable[str] = (),
    settings: dict[str, Any] | None = None,
) -> set[str]:
    """Return legacy scripts and owned shared dependencies kept with retained handlers."""
    modified = {script for script in modified_handlers if script in HOOK_SCRIPTS}
    modified |= _referenced_hook_scripts(settings, host)
    protected = {
        _safe_path(root, os.path.join(host.ownership_root, "hooks", script))
        for script in modified
    }
    owned = {
        relative.replace("\\", "/")
        for relative in owned_relatives
        if isinstance(relative, str)
    }
    payload_relative = os.path.join(host.ownership_root, "hooks", "_payload.py").replace(
        os.sep, "/"
    )
    if modified & _PAYLOAD_DEPENDENT_HANDLERS and payload_relative in owned:
        protected.add(_safe_path(root, payload_relative))
    return protected


def _legacy_metadata_record(  # noqa: PLR0913, PLR0917
    root: str,
    host: hosts.Host,
    base: dict[str, Any],
    old_record: dict[str, Any] | None,
    settings: dict[str, Any],
    config_path: str | None,
    legacy_hashes: dict[str, str],
    modified_files: list[str],
    modified_handlers: list[str],
    protected_paths: set[str],
) -> dict[str, Any]:
    """Carry proven modified legacy state so later cleanup remains safe."""
    if not modified_handlers and not any(
        _is_obsolete_hook_path(host, relative) for relative in modified_files
    ):
        return base
    result = copy.deepcopy(base)
    if config_path is not None:
        result["config"] = _relative(root, config_path)
    records = _record_handlers(old_record) if isinstance(old_record, dict) else []
    if not records and config_path is not None:
        records = hook_adapters.handler_records(settings, host, root)
    modified_scripts = set(modified_handlers)
    result["handlers"] = [
        record
        for record in records
        if isinstance(record, dict) and record.get("script") in modified_scripts
    ]
    old_files = old_record.get("files", {}) if isinstance(old_record, dict) else {}
    files = result.get("files", {})
    if not isinstance(files, dict):
        files = {}
    candidate_relatives = set(modified_files)
    candidate_relatives.update(_relative(root, path) for path in protected_paths)
    for relative in candidate_relatives:
        if not _is_obsolete_hook_path(host, relative):
            continue
        digest = old_files.get(relative) if isinstance(old_files, dict) else None
        if not isinstance(digest, str):
            digest = legacy_hashes.get(relative)
        if isinstance(digest, str):
            files[relative] = digest
    # A retained payload dependency is part of the migrated legacy ownership record even
    # when the shared file itself was not modified.  This lets uninstall preserve it
    # alongside the handler, rather than orphaning a script import.
    result["files"] = files
    return result


def _managed_file_changes(  # noqa: PLR0913
    root: str,
    old_record: dict[str, Any] | None,
    desired: dict[str, bytes],
    *,
    uninstall: bool,
    host: hosts.Host | None = None,
    observed_before: dict[str, FileSnapshot] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(unchanged stale paths, modified paths)`` and retain observations."""
    if not isinstance(old_record, dict) or not isinstance(old_record.get("files"), dict):
        return [], []
    observed_before = observed_before if observed_before is not None else {}
    desired_rel = {_relative(root, path) for path in desired}
    stale: list[str] = []
    modified: list[str] = []
    for relative, digest in old_record["files"].items():
        if host is not None:
            _assert_owned(host, relative, "manifest-managed record")
        target = _safe_path(root, relative)
        state, current = _capture_file(target)
        if state[0] == "absent":
            continue
        observed_before[target] = (state, current)
        if state[0] == "symlink":
            raise InstallerError(f"manifest-managed path is a symlink: {relative}")
        if state[0] != "regular" or current is None:
            raise InstallerError(f"manifest-managed path is not a regular file: {relative}")
        unchanged = isinstance(digest, str) and state[1] == digest
        obsolete_hook = host is not None and _is_obsolete_hook_path(host, relative)
        if not unchanged:
            modified.append(relative)
            if not uninstall and not obsolete_hook:
                raise InstallerError(f"manifest-managed file was modified: {relative}")
        elif relative not in desired_rel:
            stale.append(target)
    return stale, modified


def _load_legacy_fingerprint() -> dict[str, Any]:
    path = os.path.join(ASSETS, LEGACY_FINGERPRINT_REL)
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallerError(f"cannot load legacy fingerprint data: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("hosts"), dict):
        raise InstallerError("legacy fingerprint data is malformed")
    return value


def _legacy_fingerprint_files(
    root: str,
    host: hosts.Host,
    observed_before: dict[str, FileSnapshot] | None = None,
) -> tuple[bool, dict[str, str]]:
    """Verify legacy files and retain the snapshots used for that decision."""
    data = _load_legacy_fingerprint().get("hosts", {}).get(host.id)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return False, {}
    hashes: dict[str, str] = {}
    published = _published_legacy_paths(host)
    for relative, digest in data["files"].items():
        if (
            not isinstance(relative, str)
            or relative not in published
            or not _valid_digest(digest)
        ):
            return False, {}
        target = _safe_path(root, relative)
        snapshot = _capture_file(target)
        if observed_before is not None:
            observed_before[target] = snapshot
        state, _raw = snapshot
        if state[0] != "regular" or state[1] != digest:
            return False, {}
        hashes[relative] = digest
    return True, hashes


def _legacy_event_for(host: hosts.Host, canonical_event: str) -> str:
    """Return the event name emitted by the pre-manifest v0.5 adapter."""
    # Codex was root-level in v0.5; Cursor already used camelCase, but both used
    # Claude-shaped grouped handler entries.  Keep this historical description
    # separate from the current adapter so a layout change cannot widen adoption.
    if host.id == "cursor":
        return {
            "PreToolUse": "preToolUse",
            "PostToolUse": "postToolUse",
            "SessionStart": "sessionStart",
            "Stop": "stop",
        }.get(canonical_event, canonical_event)
    return canonical_event


def _legacy_handler_shape(  # noqa: PLR0911
    settings: dict[str, Any],
    host: hosts.Host,
    expected_commands: list[str],
) -> bool:
    """Check the complete grouped v0.5 config, not just command substrings."""
    if not hook_adapters.legacy_handlers_required(host):
        return False
    if not all(isinstance(command, str) for command in expected_commands):
        return False
    if host.id == "cursor" and not (
        type(settings.get("version", 1)) is int and settings.get("version", 1) == 1
    ):
        return False
    # Codex's v0.5 project layout was root-level; Claude, Cursor, and Pi used a
    # top-level hooks object.  This is historical recognition data, not a fresh config
    # contract, and the host-specific matcher table below keeps the layouts narrow.
    nested = host.id in {"claude", "cursor", "pi"}
    container: object = settings.get("hooks") if nested else settings
    if not isinstance(container, dict):
        return False

    expected: Counter[str] = Counter(expected_commands)
    actual: Counter[str] = Counter()
    conditions: Counter[tuple[str, str]] = Counter()
    locations: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    timeout_by_script = {
        script: timeout for _event, _matcher, script, timeout in hook_adapters._BASE_SPECS
    }
    event_by_script: dict[str, set[str]] = {}
    for event, _matcher, script, _timeout in hook_adapters._BASE_SPECS:
        wanted_events = {
            _legacy_event_for(host, event),
            event,
            *hook_adapters._expected_event(host, script),
        }
        if script == "absence_claim_guard.py":
            # v0.5 Codex builds existed both before and after its adapter selected
            # PreToolUse; accept either historical event only with the full fingerprint.
            wanted_events.update({"PreToolUse", "PostToolUse", "preToolUse", "postToolUse"})
        event_by_script[script] = wanted_events
    expected_scripts: dict[str, str] = {}
    for command in expected:
        for script in hook_adapters.HOOK_SCRIPTS:
            if command in hook_adapters.historical_command_forms(host, script):
                expected_scripts[command] = script
                break
        else:
            return False

    for raw_event, raw_entries in container.items():
        if not isinstance(raw_event, str) or not isinstance(raw_entries, list):
            continue
        for group in raw_entries:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            matcher = group.get("matcher")
            for handler in group["hooks"]:
                if not isinstance(handler, dict):
                    continue
                command = handler.get("command")
                if not isinstance(command, str):
                    continue
                script = expected_scripts.get(command)
                if script is None:
                    continue
                actual[command] += 1
                locations.setdefault(command, []).append((raw_event, handler, group))
                if handler.get("type") != "command":
                    return False
                if handler.get("timeout") != timeout_by_script.get(script):
                    return False
                if script in {"bib_provenance_guard.py", "absence_claim_guard.py"}:
                    inner_matcher = handler.get("matcher")
                    if inner_matcher is not None and not (
                        hook_adapters.legacy_write_matcher_matches(host, inner_matcher)
                    ):
                        return False
                elif "matcher" in handler:
                    return False
                if script in {"bib_provenance_guard.py", "absence_claim_guard.py"}:
                    if not hook_adapters.legacy_write_matcher_matches(host, matcher):
                        return False
                    if host.id == "claude":
                        condition = handler.get("if")
                        if not isinstance(condition, str):
                            return False
                        conditions[(script, condition)] += 1

    if actual != expected:
        return False
    if host.id == "claude":
        expected_conditions: Counter[tuple[str, str]] = Counter()
        for script, values in hook_adapters._CLAUDE_CONDITIONS.items():
            for condition in values:
                expected_conditions[(script, condition)] += 1
        if conditions != expected_conditions:
            return False
    # An exact historical command outside a grouped handler is not a complete
    # fingerprint either; treating it as ours could delete a foreign direct entry.
    all_exact = Counter(
        command
        for command in hook_adapters.all_config_commands(settings)
        if command in expected
    )
    if all_exact != expected:
        return False
    for command, entries in locations.items():
        script = expected_scripts[command]
        wanted_events = event_by_script[script]
        if any(event not in wanted_events for event, _h, _g in entries):
            return False
    return True


def _legacy_adoption(
    root: str,
    host: hosts.Host,
    settings: dict[str, Any],
    *,
    hashes: dict[str, str] | None = None,
) -> tuple[bool, dict[str, str]]:
    """Recognise a complete exact no-manifest v0.5 install, never a partial one.

    File evidence is deliberately separable from host configuration.  In particular,
    Kimi's published legacy layout has no hook files and must be recognized from its
    exact ordinary files without parsing or changing an unrelated settings file.
    """
    complete, fingerprint_hashes = (
        (True, hashes) if hashes is not None else _legacy_fingerprint_files(root, host)
    )
    if not complete:
        return False, {}
    if not hook_adapters.legacy_handlers_required(host):
        return True, dict(fingerprint_hashes)
    data = _load_legacy_fingerprint().get("hosts", {}).get(host.id)
    if not isinstance(data, dict):
        return False, {}
    expected_commands = data.get("handler_commands")
    if (
        not isinstance(expected_commands, list)
        or not expected_commands
        or not _legacy_handler_shape(settings, host, expected_commands)
    ):
        return False, {}
    return True, dict(fingerprint_hashes)


def _legacy_stale_paths(
    root: str,
    desired: dict[str, bytes],
    legacy_hashes: dict[str, str],
    observed_before: dict[str, FileSnapshot] | None = None,
) -> list[str]:
    """Return exact old assets that the current host deliberately no longer owns."""
    desired_rel = {_relative(root, path) for path in desired}
    stale: list[str] = []
    for relative, digest in legacy_hashes.items():
        if relative in desired_rel:
            continue
        target = _safe_path(root, relative)
        snapshot = _capture_file(target)
        if observed_before is not None:
            observed_before[target] = snapshot
        state, _raw = snapshot
        if state[0] == "regular" and state[1] == digest:
            stale.append(target)
    return stale


def strip_ours(entries: list[Any], host: hosts.Host | None = None) -> list[Any]:
    return hook_adapters.strip_ours(entries, host or hosts.lookup("claude"))


_DIRECTORY_SYNC_ERRNOS = frozenset(
    {
        errno.EBADF,
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
)


def _directory_sync_unsupported(exc: OSError) -> bool:
    """Whether an error means this platform cannot sync directory metadata."""
    # Windows generally cannot open a directory as a normal file descriptor.  A
    # missing errno is also common in capability probes and should not turn an
    # otherwise atomic file operation into a failed transaction.
    return os.name == "nt" or exc.errno is None or exc.errno in _DIRECTORY_SYNC_ERRNOS


def _fsync_directory(path: str, *, strict: bool = False) -> None:
    """Best-effort directory durability without weakening atomic file replacement.

    ``strict`` still reports ordinary I/O errors during recovery, but capability
    failures (including Windows directory-open/fsync errors) are intentionally
    ignored.  The helper is kept separate so callers and tests can probe this
    platform boundary without touching the replacement path.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as exc:
        if strict and not _directory_sync_unsupported(exc):
            raise InstallerError(f"cannot open directory for fsync {path}: {exc}") from exc
        return
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if strict and not _directory_sync_unsupported(exc):
                raise InstallerError(f"cannot fsync directory {path}: {exc}") from exc
    finally:
        try:
            os.close(fd)
        except OSError as exc:
            if strict and not _directory_sync_unsupported(exc):
                raise InstallerError(
                    f"cannot close directory for fsync {path}: {exc}"
                ) from exc


def _metadata_directory_path(root: str) -> str:
    return os.path.join(os.path.abspath(root), ".ai-research-skills")


def _holds_metadata_state(directory: str) -> bool:
    """Whether this directory holds state this installer wrote."""
    return any(
        os.path.lexists(os.path.join(directory, os.path.basename(relative)))
        for relative in (MANIFEST_REL, JOURNAL_REL)
    )


def _ensure_metadata_directory(root: str, *, create: bool) -> str:
    """Use a private metadata directory without chmod'ing a foreign path."""
    directory = _metadata_directory_path(root)
    created = False
    if not os.path.lexists(directory):
        if not create:
            return directory
        with contextlib.suppress(FileExistsError):
            os.mkdir(directory, 0o700)
        created = True
    info = os.lstat(directory)
    if _is_redirect(info):
        raise InstallerError(".ai-research-skills metadata directory is a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise InstallerError(".ai-research-skills metadata path is not a directory")
    if os.name != "nt" and info.st_uid != os.getuid():
        raise InstallerError(
            ".ai-research-skills metadata directory is not owned by the current user"
        )
    if _posix_modes() and stat.S_IMODE(info.st_mode) != 0o700:
        if info.st_uid != os.getuid():
            raise InstallerError(
                ".ai-research-skills metadata directory has unsafe ownership"
            )
        if not (created or _holds_metadata_state(directory)):
            # Nothing here is evidence that this directory is ours.  Narrowing it to
            # 0700 anyway would let a read-only diagnostic revoke other users' access to
            # a directory another tool owns, so leave the mode to whoever set it.
            #
            # `create` used to appear in this condition, which meant an install did the
            # narrowing that the rest of the function exists to avoid: a pre-existing
            # 0755 `.ai-research-skills/` was silently changed to 0700, and nothing
            # restored it if the transaction then rolled back.  Intending to write here
            # is not evidence of owning the directory.  Integrity does not depend on the
            # mode either — the uid check above already refuses a directory owned by
            # someone else, and only the owner can add or remove entries in an 0755
            # directory, so the manifest stays tamper-resistant at the mode we found.
            return directory
        os.chmod(directory, 0o700)
        info = os.lstat(directory)
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise InstallerError(
                ".ai-research-skills metadata directory has unsafe permissions"
            )
    return directory


def _ensure_journal_file(path: str) -> None:
    if not os.path.lexists(path):
        return
    info = os.lstat(path)
    if _is_redirect(info):
        raise InstallerError("transaction journal is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise InstallerError("transaction journal is not a regular file")
    if _posix_modes() and info.st_uid != os.getuid():
        raise InstallerError("transaction journal is not owned by the current user")
    if _posix_modes() and stat.S_IMODE(info.st_mode) != 0o600:
        if info.st_uid != os.getuid():
            raise InstallerError("transaction journal has unsafe ownership")
        os.chmod(path, 0o600)
        if stat.S_IMODE(os.stat(path).st_mode) != 0o600:
            raise InstallerError("transaction journal has unsafe permissions")


def _file_state(path: str) -> FileState:
    """Return kind, digest, and regular-file mode from one stable file snapshot."""
    return _capture_file(path)[0]


def _backup_state(existed: bool, data: bytes | None, mode: int | None) -> FileState:
    if not existed:
        return "absent", None, None
    return "regular", _sha256(data or b""), mode if _posix_modes() else None


def _expected_after(
    path: str,
    backup: tuple[bool, bytes | None, int | None],
    expected: dict[str, object] | None,
) -> tuple[str, str | None, int | None]:
    before = _backup_state(*backup)
    if expected is None or path not in expected:
        return before
    value = expected[path]
    digest: str | None
    mode: int | None = backup[2] if backup[0] else (0o644 if _posix_modes() else None)
    if isinstance(value, tuple) and len(value) == 2:
        digest_value, mode_value = value
        digest = digest_value if isinstance(digest_value, str) else None
        mode = mode_value if isinstance(mode_value, int) else mode
    elif isinstance(value, dict):
        digest_value = value.get("sha256")
        digest = digest_value if isinstance(digest_value, str) else None
        mode_value = value.get("mode")
        mode = mode_value if isinstance(mode_value, int) else mode
    else:
        digest = value if isinstance(value, str) else None
    if digest is None:
        return "absent", None, None
    return "regular", digest, mode if _posix_modes() else None


def _journal_unsigned(
    root: str,
    backups: dict[str, tuple[bool, bytes | None, int | None]],
    expected: dict[str, object] | None = None,
) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for path, (existed, data, mode) in sorted(backups.items()):
        relative = _relative(root, path)
        after_kind, after_digest, after_mode = _expected_after(
            path, (existed, data, mode), expected
        )
        targets[relative] = {
            "exists": existed,
            "mode": mode if _posix_modes() and existed else None,
            "data": (
                base64.b64encode(data).decode("ascii")
                if existed and data is not None
                else None
            ),
            "after": {
                "exists": after_kind == "regular",
                "sha256": after_digest,
                "mode": after_mode if _posix_modes() else None,
            },
        }
    return {
        "format": JOURNAL_FORMAT,
        "root": _project_path_identity(root),
        "root_path": _canonical_project_path(root),
        # Binds the journal to the filesystem object it was written for, not merely to a
        # path spelling that anything able to write into the project could reproduce.
        "root_inode": _project_root_identity(root),
        "targets": targets,
    }


def _seal_journal(unsigned: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(unsigned)
    result["journal_sha256"] = _sha256(_canonical(result))
    return result


def _journal_valid(data: object) -> bool:  # noqa: PLR0911
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("root"), str):
        return False
    format_number = data.get("format")
    if (
        not isinstance(format_number, int)
        or isinstance(format_number, bool)
        or format_number not in {LEGACY_JOURNAL_FORMAT, JOURNAL_FORMAT}
    ):
        return False
    if format_number == JOURNAL_FORMAT:
        # Required, not optional: an omitted field would otherwise let a forged journal
        # downgrade itself to the weakest identity check this reader still accepts.
        if not isinstance(data.get("root_path"), str):
            return False
        if not isinstance(data.get("root_inode"), str):
            return False
    elif "root_path" in data and not isinstance(data.get("root_path"), str):
        return False
    supplied = data.get("journal_sha256")
    if not isinstance(supplied, str):
        return False
    unsigned = dict(data)
    unsigned.pop("journal_sha256", None)
    if supplied != _sha256(_canonical(unsigned)):
        return False
    targets = data.get("targets")
    if not isinstance(targets, dict):
        return False
    for relative, snapshot in targets.items():
        if not isinstance(relative, str) or not isinstance(snapshot, dict):
            return False
        exists = snapshot.get("exists")
        if not isinstance(exists, bool):
            return False
        mode = snapshot.get("mode", 0o644 if _posix_modes() else None)
        if format_number == JOURNAL_FORMAT and "mode" not in snapshot:
            return False
        if exists:
            valid_mode = (
                isinstance(mode, int) and not isinstance(mode, bool) and 0 <= mode <= 0o7777
            )
            if (
                (_posix_modes() and not valid_mode)
                or (not _posix_modes() and mode is not None and not valid_mode)
                or not isinstance(snapshot.get("data"), str)
            ):
                return False
            try:
                base64.b64decode(snapshot["data"].encode("ascii"), validate=True)
            except (ValueError, TypeError, UnicodeEncodeError):
                return False
        elif snapshot.get("data") is not None or snapshot.get("mode") is not None:
            return False
        if format_number == JOURNAL_FORMAT:
            after = snapshot.get("after")
            if not isinstance(after, dict):
                return False
            after_exists = after.get("exists")
            after_digest = after.get("sha256")
            after_mode = after.get("mode")
            if not isinstance(after_exists, bool):
                return False
            if after_exists != (isinstance(after_digest, str)):
                return False
            if after_digest is not None and not _valid_digest(after_digest):
                return False
            if after_exists:
                valid_after_mode = (
                    isinstance(after_mode, int)
                    and not isinstance(after_mode, bool)
                    and 0 <= after_mode <= 0o7777
                )
                if (_posix_modes() and not valid_after_mode) or (
                    not _posix_modes() and after_mode is not None and not valid_after_mode
                ):
                    return False
            if not after_exists and after_mode is not None:
                return False
    return True


def _remove_journal(root: str, *, strict: bool = False) -> None:
    _ensure_metadata_directory(root, create=False)
    path = _journal_path(root)
    if not os.path.lexists(path):
        return
    _ensure_journal_file(path)
    directory = os.path.dirname(path)
    original_state, original = _capture_file(path)
    if original_state[0] != "regular" or original is None:
        raise InstallerError("transaction journal changed before removal")

    def restore_journal() -> None:
        def before_replace() -> None:
            _safe_path(root, JOURNAL_REL)
            if _file_state(path)[0] != "absent":
                raise InstallerError("transaction journal appeared during restore")

        _atomic_write(
            path,
            original,
            0o600,
            before_replace=before_replace,
        )

    # Establish the directory state before and after unlink.  If the post-unlink
    # fsync fails, put the sealed bytes back so the recovery record is not lost.
    _fsync_directory(directory, strict=strict)
    try:
        _safe_path(root, JOURNAL_REL)
        if _capture_file(path)[0] != original_state:
            raise InstallerError("transaction journal changed before unlink")
        os.unlink(path)
        _fsync_directory(directory, strict=strict)
    except Exception:
        if original is not None and not os.path.lexists(path):
            with contextlib.suppress(Exception):
                restore_journal()
        raise
    metadata_dir = directory
    if os.path.isdir(metadata_dir) and not os.listdir(metadata_dir):
        try:
            _fsync_directory(root, strict=strict)
            os.rmdir(metadata_dir)
            _fsync_directory(root, strict=strict)
        except Exception:
            # If the final project-directory fsync failed, restore the sealed
            # journal before propagating the error.  A journal must not be lost
            # merely because cosmetic metadata-directory cleanup was attempted.
            if strict:
                if original is not None and not os.path.lexists(path):
                    with contextlib.suppress(Exception):
                        restore_journal()
                raise


def _snapshot_before_state(
    snapshot: dict[str, Any], *, legacy: bool
) -> tuple[tuple[str, str | None, int | None], bytes | None]:
    exists = snapshot.get("exists")
    if not isinstance(exists, bool):
        raise InstallerError("transaction journal snapshot exists is not boolean")
    if not exists:
        if snapshot.get("data") is not None:
            raise InstallerError("transaction journal absent snapshot contains bytes")
        return ("absent", None, None), None
    encoded = snapshot.get("data")
    mode = snapshot.get("mode", 0o644 if legacy and _posix_modes() else None)
    valid_mode = (
        isinstance(mode, int) and not isinstance(mode, bool) and 0 <= mode <= 0o7777
    )
    if (
        not isinstance(encoded, str)
        or (_posix_modes() and not valid_mode)
        or (not _posix_modes() and mode is not None and not valid_mode)
    ):
        raise InstallerError("transaction journal snapshot is malformed")
    try:
        original = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise InstallerError("transaction journal contains invalid bytes") from exc
    return (
        "regular",
        _sha256(original),
        mode if _posix_modes() else None,
    ), original


def _snapshot_after_state(
    snapshot: dict[str, Any], *, required: bool
) -> tuple[str, str | None, int | None] | None:
    after = snapshot.get("after")
    if not isinstance(after, dict):
        if required:
            raise InstallerError("format-2 journal target is missing complete after state")
        return None
    exists = after.get("exists")
    digest = after.get("sha256")
    mode = after.get("mode")
    if not isinstance(exists, bool) or exists != (isinstance(digest, str)):
        raise InstallerError("transaction journal end state is malformed")
    if digest is not None and not _valid_digest(digest):
        raise InstallerError("transaction journal end state digest is malformed")
    if exists:
        valid_mode = (
            isinstance(mode, int) and not isinstance(mode, bool) and 0 <= mode <= 0o7777
        )
        if (_posix_modes() and not valid_mode) or (
            not _posix_modes() and mode is not None and not valid_mode
        ):
            raise InstallerError("transaction journal end state mode is malformed")
        return "regular", digest, mode if _posix_modes() else None
    if mode is not None:
        raise InstallerError("transaction journal absent end state has a mode")
    return "absent", None, None


def _journal_target_allowed(relative: object) -> bool:
    canonical = _canonical_relative(relative)
    if canonical is None:
        return False
    if canonical == MANIFEST_REL:
        return True
    for host in hosts.HOSTS:
        if canonical == _historical_config_path(host):
            return True
        if canonical in _owned_asset_paths(host):
            return True
    return False


def _is_host_config_path(relative: object) -> bool:
    """Whether a journal target is a host's shared configuration file."""
    canonical = _canonical_relative(relative)
    return canonical is not None and any(
        canonical == _historical_config_path(host) for host in hosts.HOSTS
    )


def _recover_journal(root: str) -> None:
    """Restore an interrupted transaction with a per-target recovery CAS.

    Recovery is the one path that writes bytes chosen by a file inside the project, so
    its trust boundary is stated rather than assumed.  The seal is keyless and proves
    only integrity; authenticity comes from the root binding in `_journal_root_matches`,
    which a journal committed to a repository cannot satisfy on someone else's clone.
    What remains is an attacker who can already both read the project root's inode and
    write into the project: that attacker can write the same file directly, so recovery
    grants no capability they lack.
    """
    root = os.path.abspath(root)
    metadata = _metadata_directory_path(root)
    if not os.path.lexists(metadata):
        return
    _ensure_metadata_directory(root, create=False)
    path = _journal_path(root)
    if not os.path.lexists(path):
        return
    _ensure_journal_file(path)
    data = _load_json(path)
    if not _journal_valid(data) or not _journal_root_matches(
        root, data.get("root"), data.get("root_path"), data.get("root_inode")
    ):
        # The seal proves only that the file was not corrupted; anyone able to write it
        # can re-seal it.  Recovery therefore restores caller-supplied bytes only for a
        # journal this project's own interrupted run could have produced, and a journal
        # that fails that test is left in place for a person to inspect.
        raise InstallerError(
            f"transaction journal does not belong to this project or has an invalid "
            f"integrity seal; inspect and remove {JOURNAL_REL} to continue"
        )
    targets = data.get("targets")
    if not isinstance(targets, dict):
        raise InstallerError("transaction journal targets are malformed")
    format_number = data.get("format")

    # Parse and authorize the entire journal before touching any target.  Current target
    # states are deliberately not cached here: recovery rechecks each one immediately
    # before its own unlink/replace, so restoring target A cannot make a stale check for B
    # authoritative.
    prepared: list[
        tuple[
            str,
            str,
            FileState,
            FileState | None,
            bytes | None,
        ]
    ] = []
    directories: set[str] = {root, os.path.dirname(path)}
    failures: list[str] = []
    for relative, snapshot in sorted(
        targets.items(), key=lambda item: str(item[0]).count("/")
    ):
        target_label = str(relative)
        try:
            if (
                not isinstance(relative, str)
                or not isinstance(snapshot, dict)
                or not _journal_target_allowed(relative)
            ):
                raise InstallerError(
                    f"journal target {target_label!r} is outside the exact "
                    "transaction inventory"
                )
            target = _safe_path(root, relative)
            before, original = _snapshot_before_state(
                snapshot, legacy=format_number == LEGACY_JOURNAL_FORMAT
            )
            after = _snapshot_after_state(
                snapshot, required=format_number == JOURNAL_FORMAT
            )
            if _is_host_config_path(relative) and (after is None or after[0] != "regular"):
                # This installer writes a shared host configuration and never deletes
                # one, so no interrupted transaction of ours can end with it absent.
                # Without this, a journal recovered on a machine that has no such file
                # would create one from bytes the journal itself supplied.
                raise InstallerError(
                    "journal claims a shared host configuration was removed, which this "
                    "installer never does"
                )
            directories.add(os.path.dirname(target))
            prepared.append((relative, target, before, after, original))
        except Exception as exc:
            failures.append(f"{target_label}: {exc}")
    if failures:
        raise InstallerError(
            "transaction recovery failed; sealed journal retained: " + "; ".join(failures)
        )

    if format_number == LEGACY_JOURNAL_FORMAT:
        for relative, target, before, _after, _original in prepared:
            try:
                if _file_state(target) != before:
                    # A format-1 journal predates the recorded after-state, so there is
                    # nothing here that can tell an interrupted write apart from an edit
                    # made after the crash, and guessing would silently revert the edit.
                    # Refusing is right; refusing without naming the way out is not,
                    # because this runs first in install, uninstall and doctor alike, so
                    # the project stays wedged until the file is dealt with by hand.
                    raise InstallerError(
                        "format-1 journal target differs from before state; refusing to "
                        "overwrite a possible post-crash edit. This journal predates the "
                        f"after-state record and cannot be resolved automatically: "
                        f"compare the file against your backups, then remove "
                        f"{JOURNAL_REL} to continue"
                    )
            except Exception as exc:
                failures.append(f"{relative}: {exc}")
                break
        if failures:
            raise InstallerError(
                "transaction recovery failed; sealed journal retained: "
                + "; ".join(failures)
            )
        _remove_journal(root, strict=True)
        return

    for relative, target, before, after, original in prepared:
        try:
            _safe_path(root, relative)
            current = _file_state(target)
            if current == before:
                continue
            if after is None or current != after:
                raise InstallerError(
                    "file no longer matches the interrupted transaction; it was changed "
                    "after the interruption and recovery would overwrite that change"
                )
            directory = os.path.dirname(target)
            if before[0] == "regular":
                if original is None or (_posix_modes() and before[2] is None):
                    raise InstallerError("regular snapshot has no bytes or mode")
                _safe_path(root, _relative(root, directory), allow_root=True)
                os.makedirs(directory, exist_ok=True)

                # Directory creation is not an authorization event.  The callback runs
                # only after the replacement temp is fully written and fsynced, making
                # this the last target/ancestor/CAS check before os.replace.
                def before_replace(
                    target: str = target,
                    relative: str = relative,
                    after: FileState = after,
                ) -> None:
                    _safe_path(root, relative)
                    if _file_state(target) != after:
                        raise InstallerError(
                            "transaction recovery observed a concurrent edit; "
                            "sealed journal retained"
                        )

                _atomic_write(
                    target,
                    original,
                    before[2],
                    before_replace=before_replace,
                )
            else:
                # The interrupted operation created this regular file; remove it only
                # after a fresh regular-file/ancestor CAS immediately before unlink.
                _safe_path(root, relative)
                current = _file_state(target)
                if current != after or current[0] != "regular":
                    raise InstallerError(
                        f"cannot remove recovered non-regular target: {relative}"
                    )
                _safe_path(root, relative)
                if _file_state(target) != after:
                    raise InstallerError(
                        "transaction recovery observed a concurrent edit; "
                        "sealed journal retained"
                    )
                os.unlink(target)
            if _file_state(target) != before:
                raise InstallerError(
                    f"recovery did not restore the approved before state: {relative}"
                )
            _fsync_directory(directory, strict=True)
        except Exception as exc:
            failures.append(f"{relative}: {exc}")
            break

    if failures:
        raise InstallerError(
            "transaction recovery failed; sealed journal retained: " + "; ".join(failures)
        )
    for directory in sorted(directories):
        if not os.path.isdir(directory) or os.path.islink(directory):
            continue
        try:
            _fsync_directory(directory, strict=True)
        except Exception as exc:
            failures.append(f"directory {directory}: {exc}")
    if failures:
        raise InstallerError(
            "transaction recovery failed; sealed journal retained: " + "; ".join(failures)
        )
    try:
        _remove_journal(root, strict=True)
    except Exception as exc:
        raise InstallerError(
            f"transaction recovery could not remove sealed journal; journal retained: {exc}"
        ) from exc


class _Transaction:
    def __init__(
        self,
        root: str,
        targets: Iterable[str],
        *,
        expected: dict[str, object] | None = None,
        approved_before: dict[str, FileSnapshot] | None = None,
    ) -> None:
        """Journal exact plan snapshots without promoting a later read to baseline."""
        self.root = os.path.abspath(root)
        _ensure_metadata_directory(self.root, create=True)
        self.backups: dict[str, tuple[bool, bytes | None, int | None]] = {}
        self.states: dict[str, FileState] = {}
        self.created_dirs: list[str] = []
        self.done = False
        approved_before = approved_before or {}
        for raw_path in targets:
            relative = _relative(self.root, raw_path)
            if not _journal_target_allowed(relative):
                raise InstallerError(
                    f"transaction target {relative!r} is outside the exact "
                    "transaction inventory"
                )
            path = _safe_path(self.root, relative)
            if path in self.backups:
                continue
            approved = approved_before.get(path)
            approved_state: FileState | None = None
            approved_data: bytes | None = None
            if isinstance(approved, tuple) and len(approved) == 3:
                # Compatibility for callers that supplied only the complete state.  The
                # state still gates the capture; the capture is never promoted to a new
                # baseline when it disagrees.
                approved_state = approved  # type: ignore[assignment]
            elif (
                isinstance(approved, tuple)
                and len(approved) == 2
                and isinstance(approved[0], tuple)
            ):
                approved_state, approved_data = approved
            elif approved is not None:
                raise InstallerError(
                    f"transaction target {relative} has no complete approved snapshot"
                )
            if approved_state is not None:
                if (
                    not isinstance(approved_state, tuple)
                    or len(approved_state) != 3
                    or approved_state[0] not in {"absent", "regular"}
                ):
                    raise InstallerError(
                        f"transaction target {relative} has an invalid approved state"
                    )
                if approved_state[0] == "regular" and (
                    approved_data is not None and not isinstance(approved_data, bytes)
                ):
                    raise InstallerError(
                        f"transaction target {relative} has invalid approved bytes"
                    )
                if approved_state[0] != "regular" and approved_data is not None:
                    raise InstallerError(
                        f"transaction target {relative} has bytes for a non-file state"
                    )
                state, data = _capture_file(path)
                if state != approved_state or (
                    approved_data is not None and data != approved_data
                ):
                    raise InstallerError(
                        f"concurrent edit detected before transaction target {relative}"
                    )
            else:
                state, data = _capture_file(path)
            if state[0] not in {"absent", "regular"}:
                raise InstallerError(
                    f"transaction target is not a regular file: {relative}"
                )
            if state[0] == "regular":
                mode = state[2]
                if data is None or (_posix_modes() and mode is None):
                    raise InstallerError(f"cannot snapshot transaction target: {relative}")
                self.backups[path] = (True, data, mode)
            else:
                self.backups[path] = (False, None, 0o644 if _posix_modes() else None)
            self.states[path] = state
        journal = _seal_journal(_journal_unsigned(self.root, self.backups, expected))
        _atomic_json(_journal_path(self.root), journal, 0o600)

    def _verify(self, path: str) -> str:
        relative = _relative(self.root, path)
        if not _journal_target_allowed(relative):
            raise InstallerError(
                f"transaction target {relative!r} is outside the exact "
                "transaction inventory"
            )
        _safe_path(self.root, relative)
        if path not in self.backups:
            raise InstallerError(f"transaction target was not snapshotted: {relative}")
        return relative

    def _check_cas(self, path: str) -> FileState:
        expected = self.states[path]
        current = _file_state(path)
        if current != expected:
            raise InstallerError(
                f"concurrent edit detected for transaction target "
                f"{_relative(self.root, path)}"
            )
        return current

    def mkdirs(self, path: str) -> None:
        relative = _relative(self.root, path)
        _safe_path(self.root, relative, allow_root=True)
        missing: list[str] = []
        current = path
        while not os.path.exists(current):
            missing.append(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        os.makedirs(path, exist_ok=True)
        _safe_path(self.root, relative, allow_root=True)
        self.created_dirs.extend(reversed(missing))

    def write(self, path: str, data: bytes) -> None:
        self._verify(path)
        self.mkdirs(os.path.dirname(path) or self.root)
        # Directory creation is not an authorization event; the final target CAS lives
        # in before_replace, after the replacement temp is complete and fsynced.
        self._verify(path)
        existed, old_data, mode = self.backups[path]
        if existed and old_data == data:
            self._check_cas(path)
            return
        write_mode = mode if existed else (0o644 if _posix_modes() else None)
        expected = ("regular", _sha256(data), write_mode if _posix_modes() else None)

        def before_replace() -> None:
            # This runs after the temp is complete and fsynced, immediately before
            # os.replace; recheck the target and every ancestor at that last moment.
            self._verify(path)
            self._check_cas(path)

        try:
            _atomic_write(
                path,
                data,
                write_mode,
                before_replace=before_replace,
            )
        except BaseException:
            # An injected failure may happen after os.replace.  Record that fact so
            # rollback can restore the transaction state, while a pre-replace failure
            # leaves the approved before state in place.
            if _file_state(path) == expected:
                self.states[path] = expected
            raise
        current = _file_state(path)
        if current != expected:
            raise InstallerError(
                f"transaction write did not produce the approved state for "
                f"{_relative(self.root, path)}"
            )
        self.states[path] = expected

    def remove(self, path: str) -> None:
        self._verify(path)
        self._check_cas(path)
        if not os.path.lexists(path):
            return
        # Do not let the existence/regular-file check drift away from the unlink CAS.
        self._verify(path)
        current = self._check_cas(path)
        if current[0] != "regular":
            raise InstallerError(f"refusing to remove non-regular target: {path}")
        removed: FileState = ("absent", None, None)

        def before_unlink() -> None:
            self._verify(path)
            current_state = self._check_cas(path)
            if current_state[0] != "regular":
                raise InstallerError(f"refusing to remove non-regular target: {path}")

        try:
            # Keep the final safe-path/existence/digest/mode check adjacent to unlink.
            before_unlink()
            os.unlink(path)
            _fsync_directory(os.path.dirname(path))
        except BaseException:
            if _file_state(path) == removed:
                self.states[path] = removed
            raise
        current = _file_state(path)
        if current != removed:
            raise InstallerError(
                f"transaction removal did not produce an absent state for "
                f"{_relative(self.root, path)}"
            )
        self.states[path] = removed

    def rollback(self) -> list[str]:
        """Restore only transaction-written states; preserve any third state."""
        failures: list[str] = []
        journal_dir = os.path.dirname(_journal_path(self.root))
        directories: set[str] = {self.root, journal_dir}
        for path in self.backups:
            directories.add(os.path.dirname(path))

        # Each target is checked and, if needed, restored in one iteration.  There is no
        # batch of stale observations that can authorize a later mutation of another
        # target; a third state stops rollback and leaves the sealed journal in place.
        for path, backup in reversed(list(self.backups.items())):
            existed, data, mode = backup
            before = _backup_state(*backup)
            relative = _relative(self.root, path)
            directory = os.path.dirname(path)
            try:
                self._verify(path)
                current = self._check_cas(path)
                if current == before:
                    continue
                if not existed and current[0] != "regular":
                    raise InstallerError(
                        f"refusing to remove non-regular recovered target: {relative}"
                    )
                if existed:
                    if data is None:
                        raise InstallerError(f"snapshot for {relative} has no bytes")
                    self.mkdirs(directory)
                    self._verify(path)
                    if _posix_modes() and mode is None:
                        raise InstallerError(f"snapshot for {relative} has no mode")

                    def before_replace(path: str = path) -> None:
                        self._verify(path)
                        self._check_cas(path)

                    # The final CAS/ancestor check is performed by _atomic_write after
                    # the replacement temp is complete and fsynced.
                    _atomic_write(
                        path,
                        data,
                        mode,
                        before_replace=before_replace,
                    )
                else:
                    # The CAS immediately adjacent to unlink; any third state remains
                    # untouched and the journal remains available for retry.  Only
                    # adjacency buys anything here: `_verify` and `_check_cas` are pure
                    # predicates over the same state, so the two extra rounds that used
                    # to sit above this one re-read the same answer without narrowing the
                    # window they appeared to be guarding.
                    self._verify(path)
                    if self._check_cas(path)[0] != "regular":
                        raise InstallerError(
                            f"refusing to remove non-regular recovered target: {relative}"
                        )
                    os.unlink(path)
                if _file_state(path) != before:
                    raise InstallerError(
                        f"rollback did not restore the approved before state: {relative}"
                    )
                self.states[path] = before
                _fsync_directory(directory, strict=True)
            except Exception as exc:
                failures.append(f"{relative}: {exc}")
                break

        if failures:
            return failures
        for directory in sorted(set(self.created_dirs), key=len, reverse=True):
            try:
                if os.path.isdir(directory) and not os.path.islink(directory):
                    os.rmdir(directory)
            except OSError as exc:
                failures.append(f"directory {directory}: {exc}")
        if failures:
            return failures
        for directory in sorted(directories):
            if not os.path.isdir(directory) or os.path.islink(directory):
                continue
            try:
                _fsync_directory(directory, strict=True)
            except Exception as exc:
                failures.append(f"directory {directory}: {exc}")
        if failures:
            return failures
        try:
            _remove_journal(self.root, strict=True)
        except Exception as exc:
            failures.append(f"journal: {exc}")
        return failures

    def commit(self) -> None:
        _remove_journal(self.root, strict=True)
        self.done = True


def _expected_states(root: str, plan: dict[str, Any], uninstall: bool) -> dict[str, object]:
    """Digest each target is meant to hold once committed; ``None`` means absent.

    This mirrors the write/remove decisions made in ``_apply`` below, so that a crashed
    run leaves behind enough information to tell an interrupted write from a later edit.
    Keep the two in step: a path written here but not there (or the reverse) would make
    recovery refuse a state it should accept.
    """
    expected: dict[str, object] = {}
    for host_plan in plan["hosts"]:
        if uninstall:
            for path in host_plan.get("remove_paths", []):
                expected[path] = None
        else:
            for path in host_plan.get("stale_paths", []):
                expected[path] = None
            for path, data in host_plan.get("desired", {}).items():
                expected[path] = _sha256(data)
        config_path = host_plan.get("config_path")
        settings = host_plan.get("new_settings")
        if config_path and settings is not None:
            expected[config_path] = _sha256(_json_bytes(settings))
    manifest = plan["manifest"]
    expected[_manifest_path(root)] = (
        None if manifest is None else _sha256(_json_bytes(manifest))
    )
    return expected


def _apply(root: str, plan: dict[str, Any], uninstall: bool) -> None:
    targets: list[str] = []
    for host_plan in plan["hosts"]:
        if not uninstall:
            targets.extend(host_plan.get("desired", {}).keys())
            targets.extend(host_plan.get("stale_paths", []))
        targets.extend(host_plan.get("remove_paths", []))
        config_path = host_plan.get("config_path")
        settings = host_plan.get("new_settings")
        if isinstance(config_path, str) and settings is not None:
            targets.append(config_path)
    targets.append(_manifest_path(root))
    approved_before = plan.get("approved_before")
    if not isinstance(approved_before, dict):
        raise InstallerError("transaction plan has no approved before-state map")
    missing = [path for path in targets if path not in approved_before]
    if missing:
        raise InstallerError(
            "transaction plan is missing approved before state for "
            + ", ".join(_relative(root, path) for path in missing)
        )
    transaction = _Transaction(
        root,
        targets,
        expected=_expected_states(root, plan, uninstall),
        approved_before=approved_before,
    )
    try:
        for host_plan in plan["hosts"]:
            desired: dict[str, bytes] = host_plan["desired"]
            if uninstall:
                for path in host_plan["remove_paths"]:
                    transaction.remove(path)
            else:
                for path in host_plan.get("stale_paths", []):
                    transaction.remove(path)
                for path, data in desired.items():
                    transaction.write(path, data)
            config_path = host_plan.get("config_path")
            settings = host_plan.get("new_settings")
            if config_path and settings is not None:
                transaction.write(config_path, _json_bytes(settings))
        manifest_path = _manifest_path(root)
        if plan["manifest"] is None:
            transaction.remove(manifest_path)
        else:
            transaction.write(manifest_path, _json_bytes(plan["manifest"]))
        transaction.commit()
    except Exception as original:
        rollback_errors = transaction.rollback()
        if rollback_errors:
            detail = "; ".join(rollback_errors)
            raise InstallerError(
                f"transaction failed: {original}; rollback failed: {detail}"
            ) from original
        raise


def _build_plan(
    root: str, selected: tuple[hosts.Host, ...], uninstall: bool
) -> dict[str, Any]:
    manifest, manifest_state, manifest_raw = _read_manifest_snapshot(root)
    manifest_path = _manifest_path(root)
    manifest_before: FileSnapshot = (manifest_state, manifest_raw)
    existing_hosts = dict((manifest or {}).get("hosts") or {})
    host_plans: list[dict[str, Any]] = []
    next_hosts = dict(existing_hosts)

    for host in selected:
        # Legacy rs-* skill names remain an explicit migration boundary.  They are user
        # data and are never silently deleted.
        _legacy_guard(root, host)
        desired = _desired_files(root, host)
        old_record = existing_hosts.get(host.id)
        if old_record is not None and not isinstance(old_record, dict):
            raise InstallerError(f"manifest host {host.id!r} is malformed")

        observed_before: dict[str, FileSnapshot] = {}
        config_path: str | None = None
        config_before: FileSnapshot | None = None
        settings: dict[str, Any] = {}
        owned_records: list[dict[str, Any]] | None = None
        legacy_complete = False
        legacy_hashes: dict[str, str] = {}

        if manifest is not None:
            # A manifest's explicit config field is ownership evidence.  A format-2
            # record with config=None must not cause a foreign settings file to be read.
            owned_config = (
                old_record.get("config") if isinstance(old_record, dict) else None
            )
            if isinstance(owned_config, str):
                config_candidate = _safe_path(root, owned_config)
                snapshot = _capture_file(config_candidate)
                if snapshot[0][0] != "absent":
                    if snapshot[0][0] != "regular" or snapshot[1] is None:
                        raise InstallerError(
                            f"owned config is not a regular file: {owned_config}"
                        )
                    config_before = snapshot
                    config_path = config_candidate
                    observed_before[config_path] = snapshot
                    settings = _json_object_from_bytes(config_path, snapshot[1])
                owned_records = (
                    _record_handlers(old_record) if isinstance(old_record, dict) else None
                )
        else:
            # Prove the complete ordinary-file fingerprint before opening any host config.
            # This keeps a fresh skills-only install independent of malformed foreign JSON.
            files_complete, candidate_hashes = _legacy_fingerprint_files(
                root, host, observed_before
            )
            if files_complete:
                legacy_hashes = candidate_hashes
                if hook_adapters.legacy_config_supported(host):
                    config_relative = os.path.join(host.ownership_root, host.hooks_file)
                    config_candidate = _safe_path(root, config_relative)
                    snapshot = _capture_file(config_candidate)
                    if snapshot[0][0] != "absent":
                        if snapshot[0][0] != "regular" or snapshot[1] is None:
                            raise InstallerError(
                                f"legacy config is not a regular file: {config_relative}"
                            )
                        config_before = snapshot
                        config_path = config_candidate
                        observed_before[config_path] = snapshot
                        settings = _json_object_from_bytes(config_path, snapshot[1])
                    legacy_complete, legacy_hashes = _legacy_adoption(
                        root, host, settings, hashes=candidate_hashes
                    )
                else:
                    # Hosts such as Kimi have ordinary legacy assets but no supported
                    # hook surface.  Recognition intentionally does not inspect settings.
                    legacy_complete, legacy_hashes = _legacy_adoption(
                        root, host, {}, hashes=candidate_hashes
                    )

        stale_paths, modified_files = _managed_file_changes(
            root,
            old_record,
            desired,
            uninstall=uninstall,
            host=host,
            observed_before=observed_before,
        )
        if legacy_complete:
            stale_paths.extend(
                _legacy_stale_paths(root, desired, legacy_hashes, observed_before)
            )

        new_settings = None
        modified_handlers: list[str] = []
        if config_path:
            cleaned, _removed, modified_handlers, missing_handlers = hook_adapters.cleanup(
                settings,
                host,
                root=root,
                owned_records=owned_records,
                allow_legacy=legacy_complete,
            )
            modified_handlers = sorted(set(modified_handlers) | set(missing_handlers))
            if cleaned != settings:
                new_settings = cleaned

        # A modified retained handler still points at its old script.  Never remove the
        # script merely because v0.8 no longer desires hook files.
        owned_relatives = (
            old_record.get("files", {}).keys()
            if isinstance(old_record, dict) and isinstance(old_record.get("files"), dict)
            else legacy_hashes.keys()
        )
        protected_scripts = _modified_handler_paths(
            root,
            host,
            modified_handlers,
            owned_relatives=owned_relatives,
            # The configuration as it will be once cleanup has run, so a handler this
            # run is about to remove does not keep its script alive, and one it leaves
            # behind does.
            settings=new_settings if new_settings is not None else settings,
        )
        stale_paths = [path for path in stale_paths if path not in protected_scripts]

        not_installed = False
        if uninstall:
            if old_record is not None:
                remove_paths: list[str] = []
                for relative, digest in old_record.get("files", {}).items():
                    _assert_owned(host, relative, "manifest-managed record")
                    target = _safe_path(root, relative)
                    snapshot = observed_before.get(target)
                    if snapshot is None:
                        snapshot = _capture_file(target)
                        observed_before[target] = snapshot
                    state, _current = snapshot
                    if state[0] == "regular" and state[1] == digest:
                        remove_paths.append(target)
                remove_paths = [
                    path for path in remove_paths if path not in protected_scripts
                ]
            elif manifest is not None:
                # A manifest exists but has no record for this host, so this host was
                # never installed by us.  Content-matching adoption is only sound when
                # there is no manifest at all: here, a foreign file that happens to be
                # byte-identical to a current ARS asset is somebody else's file, and
                # the manifest is positive evidence that we did not put it there.
                not_installed = True
                remove_paths = []
            else:
                # Without a manifest, only exact current source files or a complete
                # fingerprinted legacy install may be adopted for removal.
                _preflight_file_conflicts(
                    root,
                    desired,
                    manifest=None,
                    legacy_hashes=legacy_hashes if legacy_complete else None,
                    host_id=host.id,
                    observed_before=observed_before,
                )
                remove_paths = [
                    path
                    for path in desired
                    if (
                        observed_before[path][0][0] == "regular"
                        and (
                            observed_before[path][0][1] == _sha256(desired[path])
                            or legacy_hashes.get(_relative(root, path))
                            == observed_before[path][0][1]
                        )
                    )
                ]
                if legacy_complete:
                    remove_paths.extend(
                        _legacy_stale_paths(root, desired, legacy_hashes, observed_before)
                    )
                remove_paths = [
                    path for path in remove_paths if path not in protected_scripts
                ]
            next_hosts.pop(host.id, None)
        else:
            _preflight_file_conflicts(
                root,
                desired,
                manifest=manifest,
                old_record=old_record,
                legacy_hashes=legacy_hashes if legacy_complete else None,
                host_id=host.id,
                observed_before=observed_before,
            )
            next_record = _manifest_host_record(root, host, desired, settings)
            next_hosts[host.id] = _legacy_metadata_record(
                root,
                host,
                next_record,
                old_record,
                settings,
                config_path,
                legacy_hashes,
                modified_files,
                modified_handlers,
                protected_scripts,
            )
            remove_paths = []

        host_plans.append(
            {
                "host": host,
                "desired": desired,
                "config_path": config_path,
                "config_before": config_before,
                "new_settings": new_settings,
                "remove_paths": remove_paths,
                "stale_paths": [] if uninstall else stale_paths,
                "modified_files": modified_files,
                "modified_handlers": modified_handlers,
                "not_installed": not_installed,
                "before_states": observed_before,
            }
        )

    # All manifests and all configs were read/validated before any mutation.  Preserve
    # foreign hosts in a multi-host manifest; selected hosts are the only records changed.
    next_manifest = None
    if next_hosts:
        next_manifest = _seal_manifest(
            {
                "format": MANIFEST_FORMAT,
                "package": "ai-research-skills",
                "version": __version__,
                "hosts": next_hosts,
            }
        )
    approved_before: dict[str, FileSnapshot] = {manifest_path: manifest_before}
    for host_plan in host_plans:
        states = host_plan.get("before_states")
        if isinstance(states, dict):
            for path, snapshot in states.items():
                if (
                    isinstance(path, str)
                    and isinstance(snapshot, tuple)
                    and len(snapshot) == 2
                ):
                    approved_before[path] = snapshot
    return {
        "hosts": host_plans,
        "manifest": next_manifest,
        "approved_before": approved_before,
        "retired_paths": retired_manifest_paths(manifest_raw),
    }


def _prune_empty(root: str, host: hosts.Host) -> None:
    """Prune only package-owned skills/command directories, never hook directories."""
    for relative in (
        os.path.join(host.skills_dir),
        os.path.join(host.commands_dir or ""),
    ):
        if not relative:
            continue
        try:
            path = _safe_path(root, relative, allow_root=True)
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
        except (InstallerError, OSError):
            pass


def _manifest_host_ids(root: str) -> frozenset[str]:
    """Host ids the on-disk manifest records, or an empty set if there is no manifest."""
    manifest_path = os.path.join(os.path.abspath(root), MANIFEST_REL)
    try:
        state, raw = _capture_file(manifest_path)
    except InstallerError:
        # The normal manifest reader provides the authoritative corruption error.
        return frozenset()
    if state[0] != "regular" or raw is None:
        return frozenset()
    try:
        records = _json_object_from_bytes(manifest_path, raw).get("hosts")
    except InstallerError:
        return frozenset()
    if not isinstance(records, dict):
        return frozenset()
    return frozenset(key for key, value in records.items() if isinstance(value, dict))


def _has_installation(root: str, host: hosts.Host, manifest_ids: frozenset[str]) -> bool:
    """Whether this project actually holds an ARS installation for *host*.

    Ownership evidence, not the mere presence of the host's directory: every Kimi user
    has a `.kimi/`, so keying the migration diagnostic on the directory blocked all of
    them from ever reaching the new `.kimi-code` layout.
    """
    if host.id in manifest_ids:
        return True
    try:
        candidates = _desired_relative_paths(host)
    except Exception:  # pragma: no cover - a damaged asset tree is reported elsewhere
        return False
    return any(
        os.path.lexists(os.path.join(os.path.abspath(root), *_relative_parts(relative)))
        for relative in candidates
    )


def _kimi_layout_state(root: str) -> tuple[bool, bool]:
    """Return whether `.kimi` and `.kimi-code` each hold an ARS installation."""
    old = hosts.lookup("kimi")
    canonical = hosts.lookup("kimi-code")
    if old is None or canonical is None:  # pragma: no cover - registry is static
        return False, False
    manifest_ids = _manifest_host_ids(root)
    return (
        _has_installation(root, old, manifest_ids),
        _has_installation(root, canonical, manifest_ids),
    )


def _kimi_code_alias_diagnostic(
    root: str, requested: str | None, *, installing: bool
) -> str | None:
    """Refuse only the `kimi-code` operation that would otherwise be a misleading no-op.

    An `install` is never refused.  Naming `kimi-code` explicitly is a complete
    instruction, the two layouts coexist by design, and the old condition keyed on the
    mere existence of `.kimi/` — which every Kimi user has — so the first attempt to use
    the new layout failed for all of them, ARS installation or not.

    `uninstall` and `doctor` still stop, because they name an installation that is not
    where they are looking: reporting success reads as "the old install is gone" while it
    sits untouched in `.kimi/`.
    """
    if installing:
        return None
    if not requested or not any(
        raw.strip().lower() == "kimi-code" for raw in requested.replace(",", " ").split()
    ):
        return None
    if not os.path.isdir(os.path.abspath(root)):
        return None
    old_install, canonical_install = _kimi_layout_state(root)
    if old_install and not canonical_install:
        return (
            "explicit host 'kimi-code' is a separate .kimi-code layout, and this project's "
            "ai-research-skills installation is in the older 'kimi'/.kimi layout; nothing "
            "here belongs to kimi-code, so no files were moved, merged or removed. Use "
            "`--host kimi` to operate on the installation you have"
        )
    return None


def _kimi_duplicate_notice(root: str, adding: tuple[str, ...] = ()) -> str | None:
    """Warn when both Kimi layouts hold an installation, however they were selected.

    The cohort this split affects — an old `--host kimi-code` run that landed in `.kimi/`
    beside the `.kimi-code/` the user actually uses — reaches this through a bare
    `install` with no `--host` at all, where the explicit-request diagnostic above never
    fires.  Detection then legitimately installs into both, and nothing said so.

    *adding* names hosts this run is about to install, so the run that first creates the
    pair reports it rather than leaving it for whatever command the user happens to type
    next.
    """
    if not os.path.isdir(os.path.abspath(root)):
        return None
    old_install, canonical_install = _kimi_layout_state(root)
    if (old_install or "kimi" in adding) and (canonical_install or "kimi-code" in adding):
        return (
            "this project holds ai-research-skills in both .kimi/ and .kimi-code/; they "
            "are separate layouts and both are kept up to date. Remove whichever you do "
            "not use with `ai-research-skills uninstall --host kimi` or "
            "`--host kimi-code`"
        )
    return None


def _selected(
    root: str, requested: str | None, *, installing: bool = False
) -> tuple[tuple[hosts.Host, ...], int]:
    diagnostic = _kimi_code_alias_diagnostic(root, requested, installing=installing)
    if diagnostic:
        print(f"error: {diagnostic}", file=sys.stderr)
        return (), 2
    chosen, unknown = hosts.resolve(root, requested)
    for bad in unknown:
        print(f"unknown host {bad!r} — known: {', '.join(hosts.known_ids())}")
    notice = _kimi_duplicate_notice(
        root, tuple(host.id for host in chosen) if installing else ()
    )
    if notice:
        print(f"warning: {notice}", file=sys.stderr)
    return chosen, 2 if unknown or not chosen else 0


def _ensure_install_root(root: str) -> bool:
    root = os.path.abspath(root)
    if os.path.lexists(root):
        if _is_redirect(os.lstat(root)) or not os.path.isdir(root):
            raise InstallerError(f"target root is not a real directory: {root}")
        return False
    os.makedirs(root)
    return True


@contextlib.contextmanager
def _install_lock(root: str, create_root: bool = True) -> Generator[bool, None, None]:
    """Hold the stable path lock, then the current root-inode lock.

    The path lock is acquired before looking at or creating the root and remains held
    until the mutation (and any exception cleanup) is complete.  An inode lock is
    acquired only for an existing root, and its identity is checked again after the
    blocking acquisition so a deleted/recreated root can never enter with a stale
    lock.
    """
    root = os.path.abspath(root)
    path_lock = _project_path_lock(root)
    with path_lock:
        while True:
            created = _ensure_install_root(root) if create_root else False
            if not create_root and not os.path.lexists(root):
                # The path lock made a concurrent creator finish (or clean up) before
                # this no-op observes the missing root.
                yield False
                return

            cleanup_created = created
            try:
                inode_lock = _project_lock(root)
                with contextlib.ExitStack() as inode_locks:
                    # On filesystems without usable inode numbers, the inode helper
                    # deliberately falls back to the path identity.  The path lock is
                    # then already the required lock; opening it a second time would
                    # self-deadlock with flock/msvcrt.
                    if inode_lock.identity != path_lock.identity:
                        inode_locks.enter_context(inode_lock)
                    # inode_lock may have waited while an external/legacy operation
                    # removed or replaced the root.  Still holding path_lock, retry
                    # from the new filesystem state instead of yielding under a stale
                    # identity.
                    if _project_root_identity(root) != inode_lock.identity:
                        cleanup_created = False
                        continue
                    try:
                        yield created
                    except BaseException:
                        if cleanup_created:
                            with contextlib.suppress(OSError):
                                os.rmdir(root)
                            cleanup_created = False
                        raise
                    return
            except BaseException:
                if cleanup_created:
                    with contextlib.suppress(OSError):
                        os.rmdir(root)
                raise


def install(root: str, requested: str | None = None) -> int:
    root = os.path.abspath(root)
    try:
        with _install_lock(root, create_root=True) as created_root:
            _recover_journal(root)
            selected, rc = _selected(root, requested, installing=True)
            if rc:
                # An unknown-host early return is still inside both locks.  Otherwise a
                # waiter could observe the just-created empty root before it is removed.
                if created_root:
                    with contextlib.suppress(OSError):
                        os.rmdir(root)
                return rc
            plan = _build_plan(root, selected, False)
            _apply(root, plan, False)
            for host in selected:
                print(f"{host.id}:")
                legacy = _legacy_notice(root, host)
                for path in legacy:
                    print(
                        f"  preserved {path}  "
                        "(unknown pre-v0.5 rs-* asset; migrate manually)"
                    )
                for path in _desired_files(root, host):
                    print(
                        "  configured "
                        + path.removeprefix(root + os.sep).replace(os.sep, "/")
                    )
                modified_files = next(
                    plan_host.get("modified_files", [])
                    for plan_host in plan["hosts"]
                    if plan_host["host"] == host
                )
                modified_handlers = next(
                    plan_host.get("modified_handlers", [])
                    for plan_host in plan["hosts"]
                    if plan_host["host"] == host
                )
                for path in modified_files:
                    print(f"  preserved {path}  (legacy file was modified)")
                for script in modified_handlers:
                    print(f"  preserved handler {script}  (legacy handler was modified)")
                if modified_handlers:
                    # A preserved handler is still wired into the host's own config and
                    # will still fire.  Printing the unqualified note next to it read as
                    # "nothing runs", which is the opposite of what was just decided.
                    print(
                        "  note: this run installed no runtime governance hooks, but the "
                        "preserved handler(s) above stay configured and your host will "
                        "still run them; remove them by hand to stop that"
                    )
                else:
                    print("  note: no runtime governance hooks installed")
            _report_retired(plan.get("retired_paths", []))
            print(
                f"\nai-research-skills configured for: "
                f"{', '.join(host.id for host in selected)}"
            )
            print("Ownership manifest: .ai-research-skills/manifest.json (SHA256 sealed)")
            commanded = [host.id for host in selected if host.commands_dir]
            if commanded:
                print(
                    f"Commands ({', '.join(commanded)}): /ars-survey /ars-gate "
                    "/ars-relwork /ars-brief /ars-watch /ars-audit /ars-verify "
                    "/ars-help /ars-lint"
                )
            uncommanded = [host.id for host in selected if not host.commands_dir]
            if uncommanded:
                print(
                    f"No slash commands on: {', '.join(uncommanded)} — invoke the "
                    "installed skills by name."
                )
            print(
                "Search backends are configured separately — see docs/SETUP.md in "
                "https://github.com/signalridge/ai-research-skills."
            )
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def uninstall(root: str, requested: str | None = None) -> int:
    root = os.path.abspath(root)
    try:
        with _install_lock(root, create_root=False):
            if not os.path.lexists(root):
                print(f"ai-research-skills removed from {root} (nothing installed)")
                return 0
            _recover_journal(root)
            selected, rc = _selected(root, requested)
            if rc:
                return rc
            plan = _build_plan(root, selected, True)
            _apply(root, plan, True)
            for host_plan in plan["hosts"]:
                host = host_plan["host"]
                if host_plan.get("not_installed"):
                    print(
                        f"  {host.id}: not installed (the manifest has no record for "
                        "this host); nothing removed"
                    )
                for path in host_plan.get("modified_files", []):
                    print(f"  preserved {path}  (managed file was modified)")
                for script in host_plan.get("modified_handlers", []):
                    print(
                        f"  preserved handler {script}  (managed definition was modified)"
                    )
                legacy = _legacy_notice(root, host)
                for path in legacy:
                    print(
                        f"  preserved {path}  (pre-v0.5 rs-* asset; no deletion performed)"
                    )
                _prune_empty(root, host)
            _report_retired(plan.get("retired_paths", []))
            print(
                f"ai-research-skills removed from {root} for: "
                f"{', '.join(host.id for host in selected)}"
            )
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def doctor(root: str, requested: str | None = None) -> int:
    """Diagnose without repairing ordinary files; clean only proven legacy hook state."""
    root = os.path.abspath(root)
    try:
        with _install_lock(root, create_root=False):
            if not os.path.lexists(root):
                selected, rc = _selected(root, requested)
                if not rc:
                    print(f"ai-research-skills doctor — {root}\n  not installed")
                    rc = 1
                return rc
            _recover_journal(root)
            selected, rc = _selected(root, requested)
            if rc:
                return rc
            manifest, manifest_state, manifest_raw = _read_manifest_snapshot(root)
            manifest_before: FileSnapshot = (manifest_state, manifest_raw)
            if manifest is None:
                # A host directory is not evidence that the standalone suite is
                # installed.  Only a complete legacy fingerprint permits config parsing
                # or transactional cleanup; ordinary assets are never copied here.
                legacy_state: list[dict[str, Any]] = []
                for host in selected:
                    _legacy_guard(root, host)
                    legacy_config_path: str | None = None
                    legacy_config_before: FileSnapshot | None = None
                    legacy_settings: dict[str, Any] = {}
                    legacy_before_states: dict[str, FileSnapshot] = {}
                    complete = False
                    hashes: dict[str, str] = {}
                    files_complete, candidate_hashes = _legacy_fingerprint_files(
                        root, host, legacy_before_states
                    )
                    if files_complete:
                        hashes = candidate_hashes
                        if hook_adapters.legacy_config_supported(host):
                            config_candidate = _safe_path(
                                root, os.path.join(host.ownership_root, host.hooks_file)
                            )
                            snapshot = _capture_file(config_candidate)
                            if snapshot[0][0] != "absent":
                                if snapshot[0][0] != "regular" or snapshot[1] is None:
                                    raise InstallerError(
                                        "legacy config is not a regular file: "
                                        f"{config_candidate}"
                                    )
                                legacy_config_before = snapshot
                                legacy_config_path = config_candidate
                                legacy_before_states[config_candidate] = snapshot
                                legacy_settings = _json_object_from_bytes(
                                    config_candidate, snapshot[1]
                                )
                            complete, hashes = _legacy_adoption(
                                root, host, legacy_settings, hashes=candidate_hashes
                            )
                        else:
                            complete, hashes = _legacy_adoption(
                                root, host, {}, hashes=candidate_hashes
                            )
                    candidates: list[str] = []
                    if complete and legacy_config_path:
                        _unchanged, _removed, candidates, missing = hook_adapters.cleanup(
                            legacy_settings,
                            host,
                            root=root,
                            allow_legacy=False,
                        )
                        candidates = sorted(set(candidates) | set(missing))
                    legacy_state.append(
                        {
                            "host": host,
                            "config_path": legacy_config_path,
                            "config_before": legacy_config_before,
                            "settings": legacy_settings,
                            "complete": complete,
                            "hashes": hashes,
                            "candidates": candidates,
                            "before_states": legacy_before_states,
                        }
                    )

                print(f"ai-research-skills doctor — {root}")
                print(f"hosts: {', '.join(host.id for host in selected)}")
                if not all(state["complete"] for state in legacy_state):
                    for state in legacy_state:
                        host = state["host"]
                        if state["complete"]:
                            print(f"{host.id} — complete legacy install recognized")
                        else:
                            print(f"{host.id} — not installed (manifest missing)")
                        for script in state["candidates"]:
                            print(
                                f"  preserved candidate handler {script} "
                                "(legacy ownership was not proven)"
                            )
                    print("  no suite files installed or repaired")
                    return 1

                legacy_plans: list[dict[str, Any]] = []
                for state in legacy_state:
                    host = state["host"]
                    legacy_settings = state["settings"]
                    cleaned, _removed, modified, missing = hook_adapters.cleanup(
                        legacy_settings,
                        host,
                        root=root,
                        allow_legacy=True,
                    )
                    modified = sorted(set(modified) | set(missing))
                    protected = _modified_handler_paths(
                        root,
                        host,
                        modified,
                        owned_relatives=state["hashes"].keys(),
                        settings=cleaned,
                    )
                    legacy_stale_paths: list[str] = []
                    legacy_before_states = state["before_states"]
                    for relative, digest in state["hashes"].items():
                        if not _is_obsolete_hook_path(host, relative):
                            continue
                        target = _safe_path(root, relative)
                        snapshot = legacy_before_states.get(target)
                        if snapshot is None:
                            snapshot = _capture_file(target)
                            legacy_before_states[target] = snapshot
                        current_state, _raw = snapshot
                        if (
                            current_state[0] == "regular"
                            and current_state[1] == digest
                            and target not in protected
                        ):
                            legacy_stale_paths.append(target)
                    new_settings = cleaned if cleaned != legacy_settings else None
                    legacy_plans.append(
                        {
                            "host": host,
                            "desired": {},
                            "config_path": (
                                state["config_path"] if new_settings is not None else None
                            ),
                            "config_before": state.get("config_before"),
                            "new_settings": new_settings,
                            "remove_paths": [],
                            "stale_paths": legacy_stale_paths,
                            "modified_files": [],
                            "modified_handlers": modified,
                            "before_states": legacy_before_states,
                        }
                    )

                if any(
                    plan["stale_paths"] or plan["new_settings"] is not None
                    for plan in legacy_plans
                ):
                    approved_before = {_manifest_path(root): manifest_before}
                    for plan in legacy_plans:
                        for path, snapshot in plan["before_states"].items():
                            approved_before[path] = snapshot
                    _apply(
                        root,
                        {
                            "hosts": legacy_plans,
                            "manifest": None,
                            "approved_before": approved_before,
                        },
                        False,
                    )
                failures = 0
                for plan in legacy_plans:
                    host = plan["host"]
                    print(f"{host.id} — complete legacy install recognized")
                    for path in plan["stale_paths"]:
                        print(f"  removed {_relative(root, path)}")
                    for script in plan["modified_handlers"]:
                        print(f"  preserved handler {script} (legacy handler was modified)")
                        failures += 1
                    _prune_empty(root, host)
                print("  no suite files installed or repaired")
                return 1 if failures else 0

            records = manifest.get("hosts")
            if not isinstance(records, dict):
                raise InstallerError("manifest hosts is not an object")
            host_plans: list[dict[str, Any]] = []
            statuses: list[dict[str, Any]] = []
            cleanup_required = manifest.get("format") == LEGACY_MANIFEST_FORMAT
            for host in selected:
                record = records.get(host.id)
                if not isinstance(record, dict):
                    statuses.append({"host": host, "record": None, "items": []})
                    continue
                record_files = record.get("files", {})
                if not isinstance(record_files, dict):
                    raise InstallerError(f"manifest host {host.id!r} files is malformed")
                expected = _desired_files(root, host)
                before_states: dict[str, FileSnapshot] = {}
                status_items: list[tuple[str, str]] = []
                all_relatives = {_relative(root, path) for path in expected}
                all_relatives.update(
                    relative
                    for relative in record_files
                    if isinstance(relative, str)
                    and not _is_obsolete_hook_path(host, relative)
                )
                hook_modified: list[str] = []
                for relative in sorted(all_relatives):
                    target = _safe_path(root, relative)
                    digest = record_files.get(relative)
                    snapshot = _capture_file(target)
                    before_states[target] = snapshot
                    state, _raw = snapshot
                    if state[0] == "absent":
                        status = "MISS"
                    elif (
                        state[0] != "regular"
                        or not isinstance(digest, str)
                        or state[1] != digest
                    ):
                        status = "MODIFIED"
                    else:
                        status = "ok"
                    status_items.append((relative, status))
                for relative, digest in record_files.items():
                    if not isinstance(relative, str) or not _is_obsolete_hook_path(
                        host, relative
                    ):
                        continue
                    target = _safe_path(root, relative)
                    snapshot = _capture_file(target)
                    before_states[target] = snapshot
                    state, _raw = snapshot
                    if state[0] != "absent" and (
                        state[0] != "regular"
                        or not isinstance(digest, str)
                        or state[1] != digest
                    ):
                        hook_modified.append(relative)

                config_path: str | None = None
                config_before: FileSnapshot | None = None
                settings: dict[str, Any] = {}
                owned_config = record.get("config")
                if isinstance(owned_config, str):
                    config_candidate = _safe_path(root, owned_config)
                    snapshot = _capture_file(config_candidate)
                    if snapshot[0][0] != "absent":
                        if snapshot[0][0] != "regular" or snapshot[1] is None:
                            raise InstallerError(
                                f"owned config is not a regular file: {owned_config}"
                            )
                        config_before = snapshot
                        config_path = config_candidate
                        before_states[config_path] = snapshot
                        settings = _json_object_from_bytes(config_path, snapshot[1])
                cleaned = settings
                modified_handlers: list[str] = []
                if config_path:
                    cleaned, _removed, modified_handlers, missing_handlers = (
                        hook_adapters.cleanup(
                            settings,
                            host,
                            root=root,
                            owned_records=_record_handlers(record),
                            allow_legacy=False,
                        )
                    )
                    modified_handlers = sorted(
                        set(modified_handlers) | set(missing_handlers)
                    )
                stale_paths: list[str] = []
                for relative, digest in record_files.items():
                    if not isinstance(relative, str) or not _is_obsolete_hook_path(
                        host, relative
                    ):
                        continue
                    target = _safe_path(root, relative)
                    snapshot = before_states.get(target)
                    if snapshot is None:
                        snapshot = _capture_file(target)
                        before_states[target] = snapshot
                    state, _raw = snapshot
                    if (
                        state[0] == "regular"
                        and isinstance(digest, str)
                        and state[1] == digest
                    ):
                        stale_paths.append(target)
                protected = _modified_handler_paths(
                    root,
                    host,
                    modified_handlers,
                    owned_relatives=record_files.keys(),
                    settings=cleaned,
                )
                stale_paths = [path for path in stale_paths if path not in protected]
                new_settings = cleaned if cleaned != settings else None
                if stale_paths or new_settings is not None:
                    cleanup_required = True
                host_plans.append(
                    {
                        "host": host,
                        "desired": {},
                        "config_path": config_path if new_settings is not None else None,
                        "config_before": config_before,
                        "new_settings": new_settings,
                        "remove_paths": [],
                        "stale_paths": stale_paths,
                        "modified_files": hook_modified,
                        "modified_handlers": modified_handlers,
                        "before_states": before_states,
                    }
                )
                statuses.append(
                    {
                        "host": host,
                        "record": record,
                        "items": status_items,
                        "hook_modified": hook_modified,
                        "modified_handlers": modified_handlers,
                        "config_path": config_path,
                        "config_before": config_before,
                        "settings": settings,
                    }
                )

            next_manifest = None
            if cleanup_required:
                migrated = copy.deepcopy(manifest)
                migrated.pop("manifest_sha256", None)
                migrated["format"] = MANIFEST_FORMAT
                migrated["version"] = __version__
                migrated_hosts = migrated.get("hosts", {})
                status_by_host = {state["host"].id: state for state in statuses}
                for host in selected:
                    record = migrated_hosts.get(host.id)
                    if not isinstance(record, dict):
                        continue
                    old_record = copy.deepcopy(record)
                    files = record.get("files", {})
                    if isinstance(files, dict):
                        record["files"] = {
                            relative: digest
                            for relative, digest in files.items()
                            if not (
                                isinstance(relative, str)
                                and _is_obsolete_hook_path(host, relative)
                            )
                        }
                    record["config"] = None
                    record["handlers"] = []
                    record["adapter"] = "none"
                    state = status_by_host.get(host.id, {})
                    state_settings = state.get("settings", {})
                    if not isinstance(state_settings, dict):
                        state_settings = {}
                    state_config = state.get("config_path")
                    if not isinstance(state_config, str):
                        state_config = None
                    state_modified_files = state.get("hook_modified", [])
                    if not isinstance(state_modified_files, list):
                        state_modified_files = []
                    state_modified_handlers = state.get("modified_handlers", [])
                    if not isinstance(state_modified_handlers, list):
                        state_modified_handlers = []
                    protected = _modified_handler_paths(
                        root,
                        host,
                        state_modified_handlers,
                        owned_relatives=old_record.get("files", {}).keys()
                        if isinstance(old_record.get("files"), dict)
                        else (),
                    )
                    migrated_hosts[host.id] = _legacy_metadata_record(
                        root,
                        host,
                        record,
                        old_record,
                        state_settings,
                        state_config,
                        {},
                        state_modified_files,
                        state_modified_handlers,
                        protected,
                    )
                next_manifest = _seal_manifest(migrated)
                approved_before = {_manifest_path(root): manifest_before}
                for plan in host_plans:
                    for path, snapshot in plan["before_states"].items():
                        approved_before[path] = snapshot
                _apply(
                    root,
                    {
                        "hosts": host_plans,
                        "manifest": next_manifest,
                        "approved_before": approved_before,
                    },
                    False,
                )

            failures = 0
            any_installed = False
            print(f"ai-research-skills doctor — {root}")
            print(f"hosts: {', '.join(host.id for host in selected)}")
            for state in statuses:
                host = state["host"]
                record = state["record"]
                installed = isinstance(record, dict)
                any_installed = any_installed or installed
                print(f"{host.id} — standalone skills")
                if not installed:
                    print("  MISS manifest host record")
                    failures += 1
                    continue
                for relative, status in state["items"]:
                    print(f"  {'ok  ' if status == 'ok' else status} {relative}")
                    failures += int(status != "ok")
                for relative in state.get("hook_modified", []):
                    print(f"  preserved {relative} (legacy file was modified)")
                    failures += 1
                for script in state.get("modified_handlers", []):
                    print(f"  preserved handler {script} (legacy handler was modified)")
                    failures += 1
                print("  note  no runtime governance hooks are managed")
                print()
            for relative in retired_manifest_paths(manifest_raw):
                # Reported rather than fatal: the record is stale, its file is real, and
                # only a person can decide what to do with a file this build cannot claim.
                print(f"  stale {relative} (recorded by another version; file left alone)")
                failures += 1
            if not any_installed:
                failures += 1
            if failures:
                print(f"{failures} item(s) need attention")
            else:
                print("all structural checks passed")
            return 1 if failures else 0
    except Exception as exc:
        print(f"error: {exc}")
        return 1


def legacy_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Install ai-research-skills safely into a project"
    )
    ap.add_argument("root", nargs="?", default=".", help="target project root")
    ap.add_argument(
        "--uninstall", action="store_true", help="remove only manifest-owned suite files"
    )
    ap.add_argument("--host", metavar="IDS", help="comma-separated host ids")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    return uninstall(root, args.host) if args.uninstall else install(root, args.host)
