"""Safe, stdlib-only installer for the standalone research toolbox.

The installer owns individual ordinary suite files, never an entire host configuration.
Fresh operations install no runtime hooks. Legacy hook handlers/files are recognized only
for exact, transactional cleanup during upgrade, doctor, or uninstall.
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
from collections.abc import Generator, Iterable
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

# Names from the pre-v0.5 distribution are retained as migration diagnostics only.  An
# unknown or edited legacy asset is user data; silently deleting it is not a migration.
LEGACY_SKILLS = tuple(name.removeprefix("a") for name in SKILLS)
LEGACY_COMMANDS = tuple(name.removeprefix("a") for name in COMMANDS)

# Kept as an empty compatibility constant.  Version 0.8 has no desired hook handlers;
# old handlers are recognized only by hook_adapters during upgrade/doctor cleanup.
HOOK_SPEC: tuple[object, ...] = ()

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
JOURNAL_FORMAT = 1

CLAUDE_ROOT = ".claude"
CLAUDE_PROJECT_DIR = "$CLAUDE_PROJECT_DIR/"


def _installed_hook_scripts(host: hosts.Host) -> tuple[str, ...]:
    """Return no desired hooks; the name remains for legacy callers."""
    return ()


class InstallerError(RuntimeError):
    pass


def _project_path_identity(root: str) -> str:
    """Return the lock identity that remains stable before and after creation."""
    absolute = os.path.abspath(root)
    canonical = os.path.normcase(os.path.realpath(absolute)).casefold()
    return f"path:{canonical}"


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
    if stat.S_ISLNK(info.st_mode):
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


def hook_command(script: str, host: hosts.Host, root: str | None = None) -> str:
    """Compatibility view of the centralized host adapter command builder."""
    return hook_adapters.command_for(host, script, root)


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
    supplied = data.get("manifest_sha256")
    if not isinstance(supplied, str):
        return False
    unsigned = dict(data)
    unsigned.pop("manifest_sha256", None)
    return supplied == _sha256(_canonical(unsigned))


def _relative(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _safe_path(root: str, relative: str, *, allow_root: bool = False) -> str:
    """Resolve a target and reject symlink components and traversal."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise InstallerError(f"target root is not an existing directory: {root}")
    root_stat = os.lstat(root)
    if stat.S_ISLNK(root_stat.st_mode):
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
        if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):
            raise InstallerError(
                f"symlink target/ancestor refused: {_relative(root, current)}"
            )
    if not parts and not allow_root:
        raise InstallerError("empty managed path")
    candidate = os.path.abspath(os.path.join(root, *parts))
    if os.path.commonpath((root, candidate)) != root:
        raise InstallerError(f"path escapes target root: {relative}")
    return candidate


def _read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallerError(f"cannot read {path}: {exc}") from exc


def _atomic_write(path: str, data: bytes, mode: int = 0o644) -> None:
    """Write atomically, fsyncing the file and best-effort destination directory."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ars-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            # File fsync is part of the replace guarantee and remains required on
            # every platform.  Directory fsync is a separate capability below.
            os.fsync(fh.fileno())
            os.chmod(temporary, stat.S_IMODE(mode))
        os.replace(temporary, path)
        _fsync_directory(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: str, data: dict[str, Any], mode: int = 0o644) -> None:
    _atomic_write(
        path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(), mode
    )


def _load_json(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallerError(
            f"{path} is not valid JSON; refusing to mutate it: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise InstallerError(f"{path} is not a JSON object; refusing to mutate it")
    return value


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


def _read_manifest(root: str) -> dict[str, Any] | None:
    path = _manifest_path(root)
    if not os.path.exists(path):
        return None
    data = _load_json(path)
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
        if not isinstance(record, dict) or not isinstance(record.get("files"), dict):
            raise InstallerError(f"manifest host {host_id!r} is malformed")
        for relative, digest in record["files"].items():
            if not isinstance(relative, str) or not isinstance(digest, str):
                raise InstallerError(f"manifest file record for {host_id!r} is malformed")
            _safe_path(root, relative)
        handlers = record.get("handlers", [])
        if not isinstance(handlers, list):
            raise InstallerError(f"manifest host {host_id!r} handlers is not a list")
        for handler in handlers:
            if not isinstance(handler, dict):
                raise InstallerError(f"manifest host {host_id!r} handler is malformed")
    # File bytes are intentionally checked by the selected mutation/doctor paths rather
    # than here.  A manifest with five changed files must produce five doctor items, not
    # fail while reading the first one and hide the rest.
    return data


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


def remove_legacy(root: str, host: hosts.Host) -> list[str]:
    """Compatibility/migration report; legacy assets are never deleted."""
    return _legacy_notice(os.path.abspath(root), host)


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


def _handler_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if "definition" in left:
        return left.get("definition") == right.get("definition") and all(
            left.get(key) == right.get(key) for key in ("event", "script", "matcher")
        )
    return all(
        left.get(key) == right.get(key)
        for key in ("event", "script", "command", "matcher", "timeout")
    )


def _check_handlers(
    settings: dict[str, Any],
    host: hosts.Host,
    record: dict[str, Any] | None,
    *,
    root: str | None = None,
    uninstall: bool = False,
) -> list[str]:
    """Report old modified handlers without blocking the standalone upgrade.

    Hook handlers are obsolete package state.  Exact manifest definitions may be removed;
    a recognizable ARS command with any user edit is retained and reported instead of
    being overwritten or silently deleted.
    """
    if record is None:
        return []
    _cleaned, _removed, modified = hook_adapters.cleanup(
        settings,
        host,
        root=root,
        owned_records=_record_handlers(record),
        allow_legacy=False,
    )
    return modified


def _manifest_digest_for(manifest: dict[str, Any] | None, relative: str) -> str | None:
    for record in ((manifest or {}).get("hosts") or {}).values():
        if isinstance(record, dict):
            files = record.get("files")
            if isinstance(files, dict) and isinstance(files.get(relative), str):
                return files[relative]
    return None


def _preflight_file_conflicts(
    root: str,
    desired: dict[str, bytes],
    *,
    manifest: dict[str, Any] | None,
    old_record: dict[str, Any] | None = None,
    legacy_hashes: dict[str, str] | None = None,
) -> None:
    """Reject unknown files, but allow an old owned hash to receive new source bytes."""
    old_files = (old_record or {}).get("files", {})
    if not isinstance(old_files, dict):
        old_files = {}
    legacy_hashes = legacy_hashes or {}
    for path, data in desired.items():
        # Repeat the ancestor check immediately before preflight/mutation.  It is a
        # static-workspace boundary, not a claim of resistance to a privileged TOCTOU.
        relative = _relative(root, path)
        _safe_path(root, relative)
        if not os.path.lexists(path):
            continue
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise InstallerError(f"target file is a symlink: {relative}")
        if not os.path.isfile(path):
            raise InstallerError(f"same-name target is not a regular file: {relative}")
        current = _read_bytes(path)
        if current == data:
            continue
        old_digest = old_files.get(relative)
        if not isinstance(old_digest, str):
            old_digest = _manifest_digest_for(manifest, relative)
        if old_digest and _sha256(current or b"") == old_digest:
            continue
        if legacy_hashes.get(relative) == _sha256(current or b""):
            continue
        raise InstallerError(f"same-name unknown/conflicting file: {relative}")


def _is_obsolete_hook_path(host: hosts.Host, relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    prefix = f"{host.ownership_root}/hooks/"
    return normalized.startswith(prefix) and normalized.rsplit("/", 1)[-1] in HOOK_SCRIPTS


def _modified_handler_paths(
    root: str,
    host: hosts.Host,
    modified_handlers: Iterable[str],
    *,
    owned_relatives: Iterable[str] = (),
) -> set[str]:
    """Return legacy scripts and owned shared dependencies kept with retained handlers."""
    modified = {script for script in modified_handlers if script in HOOK_SCRIPTS}
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


def _managed_file_changes(
    root: str,
    old_record: dict[str, Any] | None,
    desired: dict[str, bytes],
    *,
    uninstall: bool,
    host: hosts.Host | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(unchanged stale paths, modified paths)``.

    Ordinary package files retain the old zero-overwrite safety rule.  Obsolete hook
    files are different: an upgrade must leave a user-modified hook in place and report
    it, while an unchanged one is safely removable.
    """
    if not isinstance(old_record, dict) or not isinstance(old_record.get("files"), dict):
        return [], []
    desired_rel = {_relative(root, path) for path in desired}
    stale: list[str] = []
    modified: list[str] = []
    for relative, digest in old_record["files"].items():
        target = _safe_path(root, relative)
        if not os.path.lexists(target):
            continue
        if stat.S_ISLNK(os.lstat(target).st_mode):
            raise InstallerError(f"manifest-managed path is a symlink: {relative}")
        if not os.path.isfile(target):
            raise InstallerError(f"manifest-managed path is not a regular file: {relative}")
        current = _read_bytes(target) or b""
        unchanged = isinstance(digest, str) and _sha256(current) == digest
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


def _legacy_fingerprint_files(root: str, host: hosts.Host) -> tuple[bool, dict[str, str]]:
    """Verify only the ordinary/legacy files, without reading host configuration."""
    data = _load_legacy_fingerprint().get("hosts", {}).get(host.id)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return False, {}
    hashes: dict[str, str] = {}
    for relative, digest in data["files"].items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            return False, {}
        target = _safe_path(root, relative)
        if not os.path.isfile(target) or stat.S_ISLNK(os.lstat(target).st_mode):
            return False, {}
        if _sha256(_read_bytes(target) or b"") != digest:
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
    root: str, desired: dict[str, bytes], legacy_hashes: dict[str, str]
) -> list[str]:
    """Return exact old assets that the current host deliberately no longer owns."""
    desired_rel = {_relative(root, path) for path in desired}
    stale: list[str] = []
    for relative, digest in legacy_hashes.items():
        if relative in desired_rel:
            continue
        target = _safe_path(root, relative)
        if os.path.isfile(target) and _sha256(_read_bytes(target) or b"") == digest:
            stale.append(target)
    return stale


def strip_ours(entries: list[Any], host: hosts.Host | None = None) -> list[Any]:
    return hook_adapters.strip_ours(entries, host or hosts.lookup("claude"))


def merge_hooks(  # noqa: PLR0913, PLR0917
    settings: dict[str, Any],
    uninstall: bool,
    host: hosts.Host,
    root: str | None = None,
    owned_records: list[dict[str, Any]] | None = None,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    return hook_adapters.merge(settings, uninstall, host, root, owned_records, allow_legacy)


def save_settings(path: str, settings: dict[str, Any]) -> None:
    mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else 0o644
    _atomic_json(path, settings, mode)


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


def _journal_unsigned(
    root: str, backups: dict[str, tuple[bool, bytes | None, int]]
) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for path, (existed, data, mode) in sorted(backups.items()):
        relative = _relative(root, path)
        targets[relative] = {
            "exists": existed,
            "mode": mode,
            "data": (
                base64.b64encode(data).decode("ascii")
                if existed and data is not None
                else None
            ),
        }
    return {
        "format": JOURNAL_FORMAT,
        "root": os.path.abspath(root),
        "targets": targets,
    }


def _seal_journal(unsigned: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(unsigned)
    result["journal_sha256"] = _sha256(_canonical(result))
    return result


def _journal_valid(data: object) -> bool:
    if not isinstance(data, dict) or data.get("format") != JOURNAL_FORMAT:
        return False
    supplied = data.get("journal_sha256")
    if not isinstance(supplied, str):
        return False
    unsigned = dict(data)
    unsigned.pop("journal_sha256", None)
    return supplied == _sha256(_canonical(unsigned))


def _remove_journal(root: str, *, strict: bool = False) -> None:
    path = _journal_path(root)
    if not os.path.lexists(path):
        return
    if stat.S_ISLNK(os.lstat(path).st_mode):
        raise InstallerError("transaction journal is a symlink")
    directory = os.path.dirname(path)
    original = _read_bytes(path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    # Establish the directory state before and after unlink.  If the post-unlink
    # fsync fails, put the sealed bytes back so the recovery record is not lost.
    _fsync_directory(directory, strict=strict)
    try:
        os.unlink(path)
        _fsync_directory(directory, strict=strict)
    except Exception:
        if original is not None and not os.path.lexists(path):
            with contextlib.suppress(Exception):
                _atomic_write(path, original, mode)
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
                        _atomic_write(path, original, mode)
                raise


def _recover_journal(root: str) -> None:
    """Restore an interrupted transaction before reading or mutating project state."""
    root = os.path.abspath(root)
    path = _journal_path(root)
    if not os.path.lexists(path):
        return
    data = _load_json(path)
    if not _journal_valid(data) or data.get("root") != root:
        raise InstallerError(
            "transaction journal is modified or has an invalid integrity seal"
        )
    targets = data.get("targets")
    if not isinstance(targets, dict):
        raise InstallerError("transaction journal targets are malformed")

    failures: list[str] = []
    directories: set[str] = {root, os.path.dirname(path)}
    for relative, snapshot in sorted(targets.items(), key=lambda item: item[0].count("/")):
        target_label = str(relative)
        try:
            if not isinstance(relative, str) or not isinstance(snapshot, dict):
                raise InstallerError("transaction journal target is malformed")
            target = _safe_path(root, relative)
            _safe_path(root, relative)  # immediately before every recovery mutation
            directory = os.path.dirname(target)
            directories.add(directory)
            if os.path.lexists(target) and stat.S_ISLNK(os.lstat(target).st_mode):
                raise InstallerError(f"cannot recover through symlink: {relative}")
            exists_value = snapshot.get("exists")
            if not isinstance(exists_value, bool):
                raise InstallerError("transaction journal snapshot exists is not boolean")
            existed = exists_value
            if existed:
                encoded = snapshot.get("data")
                mode = snapshot.get("mode", 0o644)
                if not isinstance(encoded, str) or not isinstance(mode, int):
                    raise InstallerError("transaction journal snapshot is malformed")
                try:
                    original = base64.b64decode(encoded.encode("ascii"), validate=True)
                except (ValueError, TypeError) as exc:
                    raise InstallerError(
                        "transaction journal contains invalid bytes"
                    ) from exc
                _safe_path(root, _relative(root, directory), allow_root=True)
                os.makedirs(directory, exist_ok=True)
                _safe_path(root, relative)
                _atomic_write(target, original, mode)
                _fsync_directory(directory, strict=True)
            elif os.path.lexists(target):
                if stat.S_ISLNK(os.lstat(target).st_mode):
                    raise InstallerError(f"cannot remove recovered symlink: {relative}")
                os.unlink(target)
                _fsync_directory(directory, strict=True)
        except Exception as exc:
            failures.append(f"{target_label}: {exc}")

    # A successful atomic replace is not enough: all affected directories and the
    # project root must be synced before the sealed journal may be removed.
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
    def __init__(self, root: str, targets: Iterable[str]) -> None:
        self.root = os.path.abspath(root)
        self.backups: dict[str, tuple[bool, bytes | None, int]] = {}
        self.created_dirs: list[str] = []
        self.done = False
        for raw_path in targets:
            path = _safe_path(self.root, _relative(self.root, raw_path))
            if path in self.backups:
                continue
            if os.path.lexists(path) and stat.S_ISLNK(os.lstat(path).st_mode):
                raise InstallerError(
                    f"transaction target is a symlink: {_relative(self.root, path)}"
                )
            if os.path.isfile(path):
                self.backups[path] = (
                    True,
                    _read_bytes(path),
                    stat.S_IMODE(os.stat(path).st_mode),
                )
            elif os.path.lexists(path):
                raise InstallerError(
                    "transaction target is not a regular file: "
                    f"{_relative(self.root, path)}"
                )
            else:
                self.backups[path] = (False, None, 0o644)
        journal = _seal_journal(_journal_unsigned(self.root, self.backups))
        _atomic_json(_journal_path(self.root), journal)

    def _verify(self, path: str) -> str:
        relative = _relative(self.root, path)
        _safe_path(self.root, relative)
        return relative

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
        existed, old_data, mode = self.backups[path]
        self.mkdirs(os.path.dirname(path) or self.root)
        self._verify(path)  # repeat after directory creation, immediately before write
        if existed and old_data == data:
            return
        _atomic_write(path, data, mode)

    def remove(self, path: str) -> None:
        self._verify(path)
        if not os.path.lexists(path):
            return
        self._verify(path)
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise InstallerError(f"refusing to remove symlink: {path}")
        os.unlink(path)
        _fsync_directory(os.path.dirname(path))

    def rollback(self) -> list[str]:
        """Restore every snapshot and report, rather than hide, rollback failures."""
        failures: list[str] = []
        journal_dir = os.path.dirname(_journal_path(self.root))
        directories: set[str] = {self.root, journal_dir}
        # Restore in reverse target order.  Each file uses the same atomic replace
        # path as normal writes; a failed restore leaves the sealed journal intact.
        for path, (existed, data, mode) in reversed(list(self.backups.items())):
            relative = _relative(self.root, path)
            directory = os.path.dirname(path)
            directories.add(directory)
            try:
                self._verify(path)
                if existed:
                    if data is None:
                        raise InstallerError(f"snapshot for {relative} has no bytes")
                    self.mkdirs(directory)
                    self._verify(path)
                    _atomic_write(path, data, mode)
                    _fsync_directory(directory, strict=True)
                elif os.path.lexists(path):
                    if stat.S_ISLNK(os.lstat(path).st_mode):
                        raise InstallerError(
                            f"refusing to remove recovered symlink: {relative}"
                        )
                    os.unlink(path)
                    _fsync_directory(directory, strict=True)
            except Exception as exc:
                failures.append(f"{relative}: {exc}")
        for directory in sorted(set(self.created_dirs), key=len, reverse=True):
            try:
                if os.path.isdir(directory) and not os.path.islink(directory):
                    os.rmdir(directory)
            except OSError as exc:
                failures.append(f"directory {directory}: {exc}")
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


def _apply(root: str, plan: dict[str, Any], uninstall: bool) -> None:
    targets: list[str] = []
    for host_plan in plan["hosts"]:
        targets.extend(host_plan.get("desired", {}).keys())
        targets.extend(host_plan.get("stale_paths", []))
        targets.extend(host_plan.get("remove_paths", []))
        config_path = host_plan.get("config_path")
        if config_path:
            targets.append(config_path)
    targets.append(_manifest_path(root))
    transaction = _Transaction(root, targets)
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
                transaction.write(
                    config_path,
                    (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode(),
                )
        manifest_path = _manifest_path(root)
        if plan["manifest"] is None:
            transaction.remove(manifest_path)
        else:
            transaction.write(
                manifest_path,
                (
                    json.dumps(plan["manifest"], indent=2, ensure_ascii=False) + "\n"
                ).encode(),
            )
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
    manifest = _read_manifest(root)
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

        config_path: str | None = None
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
                if os.path.exists(config_candidate):
                    config_path = config_candidate
                    settings = load_settings(config_path)
                owned_records = (
                    _record_handlers(old_record) if isinstance(old_record, dict) else None
                )
        else:
            # Prove the complete ordinary-file fingerprint before opening any host config.
            # This keeps a fresh skills-only install independent of malformed foreign JSON.
            files_complete, candidate_hashes = _legacy_fingerprint_files(root, host)
            if files_complete:
                legacy_hashes = candidate_hashes
                if hook_adapters.legacy_config_supported(host):
                    config_relative = os.path.join(host.ownership_root, host.hooks_file)
                    config_candidate = _safe_path(root, config_relative)
                    if os.path.exists(config_candidate):
                        config_path = config_candidate
                        settings = load_settings(config_path)
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
        )
        if legacy_complete:
            stale_paths.extend(_legacy_stale_paths(root, desired, legacy_hashes))

        new_settings = None
        modified_handlers: list[str] = []
        if config_path:
            cleaned, _removed, modified_handlers = hook_adapters.cleanup(
                settings,
                host,
                root=root,
                owned_records=owned_records,
                allow_legacy=legacy_complete,
            )
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
        )
        stale_paths = [path for path in stale_paths if path not in protected_scripts]

        if uninstall:
            if old_record is not None:
                remove_paths: list[str] = []
                for relative, digest in old_record.get("files", {}).items():
                    target = _safe_path(root, relative)
                    if not os.path.lexists(target):
                        continue
                    if _sha256(_read_bytes(target) or b"") == digest:
                        remove_paths.append(target)
                remove_paths = [
                    path for path in remove_paths if path not in protected_scripts
                ]
            else:
                # Without a manifest, only exact current source files or a complete
                # fingerprinted legacy install may be adopted for removal.
                _preflight_file_conflicts(
                    root,
                    desired,
                    manifest=None,
                    legacy_hashes=legacy_hashes if legacy_complete else None,
                )
                remove_paths = [
                    path
                    for path in desired
                    if os.path.isfile(path)
                    and (
                        _sha256(_read_bytes(path) or b"") == _sha256(desired[path])
                        or legacy_hashes.get(_relative(root, path))
                        == _sha256(_read_bytes(path) or b"")
                    )
                ]
                if legacy_complete:
                    remove_paths.extend(_legacy_stale_paths(root, desired, legacy_hashes))
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
                "new_settings": new_settings,
                "remove_paths": remove_paths,
                "stale_paths": [] if uninstall else stale_paths,
                "modified_files": modified_files,
                "modified_handlers": modified_handlers,
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
    return {"hosts": host_plans, "manifest": next_manifest}


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


def _selected(root: str, requested: str | None) -> tuple[tuple[hosts.Host, ...], int]:
    chosen, unknown = hosts.resolve(root, requested)
    for bad in unknown:
        print(f"unknown host {bad!r} — known: {', '.join(hosts.known_ids())}")
    return chosen, 2 if unknown or not chosen else 0


def _ensure_install_root(root: str) -> bool:
    root = os.path.abspath(root)
    if os.path.lexists(root):
        if stat.S_ISLNK(os.lstat(root).st_mode) or not os.path.isdir(root):
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
            selected, rc = _selected(root, requested)
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
                print("  note: no runtime governance hooks installed")
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
            print("Search backends are configured separately — see docs/SETUP.md.")
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
            print(
                f"ai-research-skills removed from {root} for: "
                f"{', '.join(host.id for host in selected)}"
            )
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def install_files(root: str, host: hosts.Host) -> list[str]:
    """Compatibility helper: install one host through the same safe transaction."""
    root = os.path.abspath(root)
    with _install_lock(root, create_root=True):
        _recover_journal(root)
        plan = _build_plan(root, (host,), False)
        _apply(root, plan, False)
        return list(plan["hosts"][0]["desired"])


def remove_files(root: str, host: hosts.Host) -> None:
    root = os.path.abspath(root)
    with _install_lock(root, create_root=False):
        if not os.path.lexists(root):
            return
        _recover_journal(root)
        plan = _build_plan(root, (host,), True)
        _apply(root, plan, True)


def settings_has_hook(
    hooks: dict[str, Any],
    event: str,
    script: str,
    host: hosts.Host | None = None,
    root: str | None = None,
) -> bool:
    host = host or hosts.lookup("claude")
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get(event)
    if not isinstance(entries, list):
        return False
    if hook_adapters.for_host(host).style == "direct":
        return any(
            isinstance(entry, dict)
            and hook_adapters.script_for_command(
                entry.get("command"), host, root, allow_absolute_without_root=root is None
            )
            == script
            for entry in entries
        )
    return any(
        isinstance(entry, dict)
        and any(
            hook_adapters.script_for_command(
                handler.get("command"), host, root, allow_absolute_without_root=root is None
            )
            == script
            for handler in entry.get("hooks", [])
            if isinstance(handler, dict)
        )
        for entry in entries
    )


def read_settings_quiet(path: str) -> dict[str, Any] | None:
    try:
        return _load_json(path)
    except InstallerError:
        return None


def doctor(root: str, requested: str | None = None) -> int:
    """Diagnose without repairing ordinary files; clean only proven legacy hook state."""
    root = os.path.abspath(root)
    try:
        with _install_lock(root, create_root=False):
            if not os.path.lexists(root):
                selected, rc = _selected(root, requested)
                if not rc:
                    print(f"ai-research-skills doctor — {root}\\n  not installed")
                    rc = 1
                return rc
            _recover_journal(root)
            selected, rc = _selected(root, requested)
            if rc:
                return rc
            manifest = _read_manifest(root)
            if manifest is None:
                # A host directory is not evidence that the standalone suite is
                # installed.  Only a complete legacy fingerprint permits config parsing
                # or transactional cleanup; ordinary assets are never copied here.
                legacy_state: list[dict[str, Any]] = []
                for host in selected:
                    _legacy_guard(root, host)
                    legacy_config_path: str | None = None
                    legacy_settings: dict[str, Any] = {}
                    complete = False
                    hashes: dict[str, str] = {}
                    files_complete, candidate_hashes = _legacy_fingerprint_files(root, host)
                    if files_complete:
                        hashes = candidate_hashes
                        if hook_adapters.legacy_config_supported(host):
                            config_candidate = _safe_path(
                                root, os.path.join(host.ownership_root, host.hooks_file)
                            )
                            if os.path.exists(config_candidate):
                                legacy_config_path = config_candidate
                                legacy_settings = load_settings(legacy_config_path)
                            complete, hashes = _legacy_adoption(
                                root, host, legacy_settings, hashes=candidate_hashes
                            )
                        else:
                            complete, hashes = _legacy_adoption(
                                root, host, {}, hashes=candidate_hashes
                            )
                    candidates: list[str] = []
                    if complete and legacy_config_path:
                        _unchanged, _removed, candidates = hook_adapters.cleanup(
                            legacy_settings,
                            host,
                            root=root,
                            allow_legacy=False,
                        )
                    legacy_state.append(
                        {
                            "host": host,
                            "config_path": legacy_config_path,
                            "settings": legacy_settings,
                            "complete": complete,
                            "hashes": hashes,
                            "candidates": candidates,
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
                    cleaned, _removed, modified = hook_adapters.cleanup(
                        legacy_settings,
                        host,
                        root=root,
                        allow_legacy=True,
                    )
                    protected = _modified_handler_paths(
                        root,
                        host,
                        modified,
                        owned_relatives=state["hashes"].keys(),
                    )
                    legacy_stale_paths: list[str] = []
                    for relative, digest in state["hashes"].items():
                        if not _is_obsolete_hook_path(host, relative):
                            continue
                        target = _safe_path(root, relative)
                        if (
                            os.path.isfile(target)
                            and not os.path.islink(target)
                            and _sha256(_read_bytes(target) or b"") == digest
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
                            "new_settings": new_settings,
                            "remove_paths": [],
                            "stale_paths": legacy_stale_paths,
                            "modified_files": [],
                            "modified_handlers": modified,
                        }
                    )

                if any(
                    plan["stale_paths"] or plan["new_settings"] is not None
                    for plan in legacy_plans
                ):
                    _apply(root, {"hosts": legacy_plans, "manifest": None}, False)
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
                    status = "ok"
                    if not os.path.lexists(target):
                        status = "MISS"
                    elif (
                        stat.S_ISLNK(os.lstat(target).st_mode)
                        or not os.path.isfile(target)
                        or not isinstance(digest, str)
                        or _sha256(_read_bytes(target) or b"") != digest
                    ):
                        status = "MODIFIED"
                    status_items.append((relative, status))
                for relative, digest in record_files.items():
                    if not isinstance(relative, str) or not _is_obsolete_hook_path(
                        host, relative
                    ):
                        continue
                    target = _safe_path(root, relative)
                    if not os.path.lexists(target):
                        continue
                    if (
                        not os.path.isfile(target)
                        or stat.S_ISLNK(os.lstat(target).st_mode)
                        or not isinstance(digest, str)
                        or _sha256(_read_bytes(target) or b"") != digest
                    ):
                        hook_modified.append(relative)

                config_path: str | None = None
                settings: dict[str, Any] = {}
                owned_config = record.get("config")
                if isinstance(owned_config, str):
                    config_candidate = _safe_path(root, owned_config)
                    if os.path.exists(config_candidate):
                        config_path = config_candidate
                        settings = load_settings(config_path)
                cleaned = settings
                modified_handlers: list[str] = []
                if config_path:
                    cleaned, _removed, modified_handlers = hook_adapters.cleanup(
                        settings,
                        host,
                        root=root,
                        owned_records=_record_handlers(record),
                        allow_legacy=False,
                    )
                stale_paths: list[str] = []
                for relative, digest in record_files.items():
                    if not isinstance(relative, str) or not _is_obsolete_hook_path(
                        host, relative
                    ):
                        continue
                    target = _safe_path(root, relative)
                    if (
                        os.path.isfile(target)
                        and not os.path.islink(target)
                        and isinstance(digest, str)
                        and _sha256(_read_bytes(target) or b"") == digest
                    ):
                        stale_paths.append(target)
                protected = _modified_handler_paths(
                    root,
                    host,
                    modified_handlers,
                    owned_relatives=record_files.keys(),
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
                        "new_settings": new_settings,
                        "remove_paths": [],
                        "stale_paths": stale_paths,
                        "modified_files": hook_modified,
                        "modified_handlers": modified_handlers,
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
                _apply(root, {"hosts": host_plans, "manifest": next_manifest}, False)

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
