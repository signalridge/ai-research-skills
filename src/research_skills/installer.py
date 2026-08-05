"""Install research-skills into a project's .claude/ directory.

Copies commands, skills and hooks into <root>/.claude/, the validator and its
schemas into <root>/.claude/research-skills/, and merges the four guardrail
hooks into <root>/.claude/settings.json. Idempotent: re-running replaces this
suite's files and hook entries without touching anything else.

Standard library only — the installer runs in whatever python3 the user has.

The suite's assets are read from the package's bundled assets/ directory when
installed (uvx, pip); from a checkout they are read from the repository root,
two levels above this file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any

from research_skills import hosts

SKILLS = (
    "rs-survey",
    "rs-gap-gate",
    "rs-related-work",
    "rs-watch",
    "rs-decision-brief",
    "rs-red-team",
    "rs-verify",
)
HOOK_SCRIPTS = (
    "_payload.py",
    "bib_provenance_guard.py",
    "absence_claim_guard.py",
    "survey_staleness.py",
    "stop_survey_peer.py",
)
COMMANDS = (
    "rs-audit.md",
    "rs-brief.md",
    "rs-gate.md",
    "rs-help.md",
    "rs-relwork.md",
    "rs-survey.md",
    "rs-watch.md",
)
SCHEMAS = (
    "corpus.schema.json",
    "coverage.schema.json",
    "gaps.schema.json",
    "protocol.schema.json",
)

# Suffixes each write-time guard actually inspects. Kept here so the `if` conditions
# below cannot drift from what the guard checks internally — a condition narrower than
# the guard's own filter silently disables it, and nothing reports that.
BIB_SUFFIXES = (".bib",)
PROSE_SUFFIXES = (".md", ".tex", ".markdown", ".mdx")

# event, matcher, script, timeout, if-conditions
#
# The `if` conditions are a pre-filter Claude Code evaluates BEFORE spawning the
# process, so a write to an unrelated file costs nothing instead of ~22ms per guard.
# Verified empirically that the glob matches at depth: a .bib three directories down
# (.research/survey/<slug>/refs.bib — where they actually live) is still caught.
#
# The guards re-check the suffix themselves, so a condition that is too broad only
# costs a process that exits immediately. Too narrow is the dangerous direction, which
# is why the patterns are generated from the tuples above rather than typed out.
HOOK_SPEC = (
    (
        "PreToolUse",
        "Edit|Write",
        "bib_provenance_guard.py",
        10,
        tuple(
            f"{tool}(*{suffix})" for suffix in BIB_SUFFIXES for tool in ("Write", "Edit")
        ),
    ),
    (
        "PostToolUse",
        "Edit|Write",
        "absence_claim_guard.py",
        10,
        tuple(
            f"{tool}(*{suffix})" for suffix in PROSE_SUFFIXES for tool in ("Write", "Edit")
        ),
    ),
    ("SessionStart", None, "survey_staleness.py", 10, ()),
    ("Stop", None, "stop_survey_peer.py", 15, ()),
)


def asset_dirs() -> tuple[str, str, str]:
    """Locate (.claude, scripts, schemas): bundled assets, else the checkout root."""
    here = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(here, "assets")
    if os.path.isdir(assets):
        return (
            os.path.join(assets, ".claude"),
            os.path.join(assets, "research-skills", "scripts"),
            os.path.join(assets, "research-skills", "schemas"),
        )
    root = os.path.dirname(os.path.dirname(here))
    return (
        os.path.join(root, ".claude"),
        os.path.join(root, "scripts"),
        os.path.join(root, "schemas"),
    )


SRC_CLAUDE, SRC_SCRIPTS, SRC_SCHEMAS = asset_dirs()


def hook_command(script: str, host: hosts.Host) -> str:
    """Claude Code expands $CLAUDE_PROJECT_DIR; other hosts do not define it, so they
    get a path relative to the project root the agent already runs in."""
    if host.id == "claude":
        return f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"'
    return f'python3 "{host.ownership_root}/hooks/{script}"'


def is_ours(command: str) -> bool:
    """A hook command belongs to this suite if it runs one of our scripts."""
    return any(script in command for script in HOOK_SCRIPTS)


def copy_tree(src: str, dst: str) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)


# The skills are authored against Claude Code's layout, which is the richest surface.
# Every other host puts the same files under its own root and has no $CLAUDE_PROJECT_DIR,
# so a verbatim copy tells the agent to run a path that does not exist. Rewrite on the
# way in rather than authoring eleven variants.
CANONICAL_VALIDATOR = '"$CLAUDE_PROJECT_DIR/.claude/research-skills/scripts/rs_validate.py"'


def same_file(src: str, dst: str) -> bool:
    """Installing into the checkout the assets came from is a no-op, not an error.

    `research-skills install .` inside the repo is the natural way to dogfood the
    guards, and shutil raises SameFileError partway through — leaving settings.json
    half-merged, which is worse than either outcome.
    """
    try:
        return os.path.samefile(src, dst)
    except OSError:
        return False


def copy_file(src: str, dst: str) -> None:
    if not same_file(src, dst):
        shutil.copy2(src, dst)


def localise(text: str, host: hosts.Host) -> str:
    if host.id == "claude":
        return text
    return text.replace(
        CANONICAL_VALIDATOR,
        f'"{host.ownership_root}/research-skills/scripts/rs_validate.py"',
    )


def copy_skill(src: str, dst: str, host: hosts.Host) -> None:
    """copy_tree, but markdown gets host-local paths substituted in."""
    for dirpath, _dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        target_dir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(target_dir, exist_ok=True)
        for name in filenames:
            source = os.path.join(dirpath, name)
            target = os.path.join(target_dir, name)
            if same_file(source, target):
                continue
            if name.endswith(".md"):
                with open(source, encoding="utf-8") as fh:
                    body = fh.read()
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write(localise(body, host))
            else:
                shutil.copy2(source, target)


def install_files(root: str, host: hosts.Host) -> list[str]:
    """Copy the suite into one host's tree. Skills and support files everywhere;
    commands and hooks only where the host has a surface for them."""
    done = []

    for skill in SKILLS:
        copy_skill(
            os.path.join(SRC_CLAUDE, "skills", skill),
            os.path.join(root, host.skills_dir, skill),
            host,
        )
    done.append(f"{host.skills_dir}/")

    if host.commands_dir:
        dst = os.path.join(root, host.commands_dir)
        os.makedirs(dst, exist_ok=True)
        for name in COMMANDS:
            source = os.path.join(SRC_CLAUDE, "commands", name)
            target = os.path.join(dst, name)
            if same_file(source, target):
                continue
            with open(source, encoding="utf-8") as fh:
                body = fh.read()
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(localise(body, host))
        done.append(f"{host.commands_dir}/")

    if host.hooks:
        dst = os.path.join(root, host.ownership_root, "hooks")
        os.makedirs(dst, exist_ok=True)
        for name in HOOK_SCRIPTS:
            copy_file(os.path.join(SRC_CLAUDE, "hooks", name), os.path.join(dst, name))
        done.append(f"{host.ownership_root}/hooks/")

    # The validator and its schemas are host-neutral, but each host gets its own copy
    # so uninstalling one never breaks another.
    support = os.path.join(root, host.ownership_root, "research-skills")
    os.makedirs(os.path.join(support, "scripts"), exist_ok=True)
    copy_file(
        os.path.join(SRC_SCRIPTS, "rs_validate.py"),
        os.path.join(support, "scripts", "rs_validate.py"),
    )
    copy_tree(SRC_SCHEMAS, os.path.join(support, "schemas"))
    done.append(f"{host.ownership_root}/research-skills/")

    return done


def remove_files(root: str, host: hosts.Host) -> None:
    """Remove only what install_files wrote. Anything else under the host's tree
    belongs to the user."""
    for skill in SKILLS:
        shutil.rmtree(os.path.join(root, host.skills_dir, skill), ignore_errors=True)

    if host.commands_dir:
        for name in COMMANDS:
            path = os.path.join(root, host.commands_dir, name)
            if os.path.exists(path):
                os.remove(path)

    if host.hooks:
        for name in HOOK_SCRIPTS:
            path = os.path.join(root, host.ownership_root, "hooks", name)
            if os.path.exists(path):
                os.remove(path)

    shutil.rmtree(
        os.path.join(root, host.ownership_root, "research-skills"), ignore_errors=True
    )

    # Leave no empty shells behind, but never remove a directory the user put things in.
    for rel in (host.skills_dir, host.commands_dir, f"{host.ownership_root}/hooks"):
        if not rel:
            continue
        path = os.path.join(root, rel)
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)


def load_settings(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"error: {path} is not valid JSON, refusing to touch it: {exc}")
    if not isinstance(data, dict):
        sys.exit(f"error: {path} is not a JSON object, refusing to touch it")
    return data


def strip_ours(entries: list) -> list:
    """Drop hook entries that run this suite's scripts; keep everything else."""
    kept = []
    for entry in entries:
        hooks = entry.get("hooks") if isinstance(entry, dict) else None
        if isinstance(hooks, list) and any(
            isinstance(h, dict) and is_ours(str(h.get("command", ""))) for h in hooks
        ):
            continue
        kept.append(entry)
    return kept


def merge_hooks(settings: dict, uninstall: bool, host: hosts.Host) -> dict:
    hooks = settings.get("hooks") if host.hooks_nested else settings
    if not isinstance(hooks, dict):
        hooks = {}

    for claude_event, matcher, script, timeout, conditions in HOOK_SPEC:
        event = host.event_names.get(claude_event, claude_event)
        entries = strip_ours(hooks.get(event, []))
        if not uninstall:
            # One hook entry per condition: a write to foo.py then matches none of them
            # and no process is spawned at all. With no conditions (SessionStart, Stop)
            # the single unconditional entry is the whole point.
            base = {
                "type": "command",
                "command": hook_command(script, host),
                "timeout": timeout,
            }
            # Only pre-filter where both the tool names and the condition syntax are
            # verified. A condition that never matches disables the guard and reports
            # nothing; spawning a process that exits immediately merely costs 22ms.
            use = conditions if (conditions and host.filter_conditions) else ()
            hook_entries: list[dict[str, Any]] = (
                [dict(base, **{"if": cond}) for cond in use] if use else [base]
            )
            # Heterogeneous settings payload: a hook list under "hooks", a str under
            # "matcher" — the dict literal alone would pin the value type to the list.
            entry: dict[str, Any] = {"hooks": hook_entries}
            if matcher is not None:
                # Host-specific tool names: Codex writes via apply_patch, so a
                # Claude-shaped Edit|Write matcher would miss every write it makes.
                entry["matcher"] = (
                    "|".join(host.write_tools) if host.write_tools else matcher
                )
            entries.append(entry)
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)

    if not host.hooks_nested:
        return hooks
    if hooks:
        settings["hooks"] = hooks
        # Cursor 3.x refuses a project hooks.json without `version` and loads none of
        # the hooks, reporting only in its settings UI.
        for key, value in host.config_extra.items():
            settings.setdefault(key, value)
    else:
        settings.pop("hooks", None)
    return settings


def save_settings(path: str, settings: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")


def install(root: str, requested: str | None = None) -> int:
    selected, unknown = hosts.resolve(root, requested)
    for bad in unknown:
        print(f"unknown host {bad!r} — known: {', '.join(hosts.known_ids())}")
    if unknown:
        return 2

    for host in selected:
        print(f"{host.id}:")
        for path in install_files(root, host):
            print(f"  installed {path}")
        if host.hooks:
            settings_path = os.path.join(root, host.ownership_root, host.hooks_file)
            save_settings(
                settings_path, merge_hooks(load_settings(settings_path), False, host)
            )
            print(f"  hooks merged into {host.ownership_root}/{host.hooks_file}")
        if host.caveat:
            print(f"  note: {host.caveat}")

    names = ", ".join(host.id for host in selected)
    guarded = [host.id for host in selected if host.hooks]
    print(f"\nresearch-skills installed into {root} for: {names}")
    if guarded:
        print(f"Guardrails active on: {', '.join(guarded)}")
    else:
        print("Guardrails active on: none of these hosts — /rs-audit is your only check.")
    print(
        "Commands: /rs-survey /rs-gate /rs-relwork /rs-brief /rs-watch /rs-audit /rs-help\n"
        "Search backends are configured separately — see docs/SETUP.md "
        "(arxiv MCP required, openalex and tavily recommended)."
    )
    return 0


def uninstall(root: str, requested: str | None = None) -> int:
    selected, unknown = hosts.resolve(root, requested)
    for bad in unknown:
        print(f"unknown host {bad!r} — known: {', '.join(hosts.known_ids())}")
    if unknown:
        return 2

    for host in selected:
        remove_files(root, host)
        if host.hooks:
            settings_path = os.path.join(root, host.ownership_root, host.hooks_file)
            if os.path.exists(settings_path):
                save_settings(
                    settings_path, merge_hooks(load_settings(settings_path), True, host)
                )
    names = ", ".join(host.id for host in selected)
    print(f"research-skills removed from {root} for: {names}")
    return 0


def settings_has_hook(hooks: dict, event: str, script: str) -> bool:
    entries = hooks.get(event)
    if not isinstance(entries, list):
        return False
    for entry in entries:
        entry_hooks = entry.get("hooks") if isinstance(entry, dict) else None
        if isinstance(entry_hooks, list) and any(
            isinstance(h, dict) and script in str(h.get("command", "")) for h in entry_hooks
        ):
            return True
    return False


def read_settings_quiet(path: str) -> dict | None:
    """settings.json as a dict, or None when missing, unreadable or not an object."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def doctor(root: str, requested: str | None = None) -> int:
    """Check an installation item by item, per host. Exit 1 if anything is missing."""
    selected, unknown = hosts.resolve(root, requested)
    for bad in unknown:
        print(f"unknown host {bad!r} — known: {', '.join(hosts.known_ids())}")
    if unknown:
        return 2

    missing = 0
    any_installed = False

    def item(label: str, present: bool) -> None:
        nonlocal missing
        if not present:
            missing += 1
        print(f"  {'ok  ' if present else 'MISS'} {label}")

    print(f"research-skills doctor — {root}")
    print(f"hosts: {', '.join(host.id for host in selected)}\n")

    for host in selected:
        # A host the project uses but never installed into is not broken. Only count
        # missing files when something IS installed there — that means real breakage.
        installed_here = any(
            os.path.isfile(os.path.join(root, host.skills_dir, skill, "SKILL.md"))
            for skill in SKILLS
        )
        if not installed_here:
            print(f"{host.id} — not installed")
            print(f"  hint  research-skills install {root} --host {host.id}\n")
            continue
        any_installed = True

        print(f"{host.id} — suite files")
        for skill in SKILLS:
            item(
                f"{host.skills_dir}/{skill}/SKILL.md",
                os.path.isfile(os.path.join(root, host.skills_dir, skill, "SKILL.md")),
            )
        if host.commands_dir:
            for name in COMMANDS:
                item(
                    f"{host.commands_dir}/{name}",
                    os.path.isfile(os.path.join(root, host.commands_dir, name)),
                )
        if host.hooks:
            for name in HOOK_SCRIPTS:
                item(
                    f"{host.ownership_root}/hooks/{name}",
                    os.path.isfile(os.path.join(root, host.ownership_root, "hooks", name)),
                )
        support = os.path.join(root, host.ownership_root, "research-skills")
        item(
            f"{host.ownership_root}/research-skills/scripts/rs_validate.py",
            os.path.isfile(os.path.join(support, "scripts", "rs_validate.py")),
        )
        for name in SCHEMAS:
            item(
                f"{host.ownership_root}/research-skills/schemas/{name}",
                os.path.isfile(os.path.join(support, "schemas", name)),
            )

        if host.hooks:
            print(f"\n{host.id} — {host.hooks_file} hooks")
            settings_path = os.path.join(root, host.ownership_root, host.hooks_file)
            settings = read_settings_quiet(settings_path)
            if settings is None:
                item(f"{host.ownership_root}/{host.hooks_file} is valid JSON", False)
                settings = {}
            hooks_cfg = settings.get("hooks") if host.hooks_nested else settings
            if not isinstance(hooks_cfg, dict):
                hooks_cfg = {}
            for claude_event, _matcher, script, _timeout, _conditions in HOOK_SPEC:
                event = host.event_names.get(claude_event, claude_event)
                item(f"{event}: {script}", settings_has_hook(hooks_cfg, event, script))
        elif host.caveat:
            print(f"\n  note: {host.caveat}")
        print()

    print("search backends")
    if os.environ.get("OPENALEX_API_KEY"):
        print("  ok   OPENALEX_API_KEY is set")
    else:
        print("  warn OPENALEX_API_KEY is not set — openalex needs it (see docs/SETUP.md)")
    print("  hint run `claude mcp list` to check that the search backends are connected")

    if not any_installed:
        print("\nnot installed for any host here")
        return 1
    print(f"\n{missing} item(s) missing" if missing else "\nall checks passed")
    return 1 if missing else 0


def legacy_main(argv: list[str]) -> int:
    """The pre-packaging interface kept alive by the repo-root install.py shim.

    python3 install.py [project-root]     # default: current directory
    python3 install.py --uninstall [project-root]
    """
    ap = argparse.ArgumentParser(
        description="Install research-skills into a project's .claude/ directory."
    )
    ap.add_argument(
        "root", nargs="?", default=".", help="target project root (default: cwd)"
    )
    ap.add_argument(
        "--uninstall", action="store_true", help="remove the suite from the project"
    )
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if args.uninstall:
        return uninstall(root)
    return install(root)
