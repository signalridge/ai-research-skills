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

# event, matcher, script, timeout — mirrors what hooks/hooks.json used to declare.
HOOK_SPEC = (
    ("PreToolUse", "Edit|Write", "bib_provenance_guard.py", 10),
    ("PostToolUse", "Edit|Write", "absence_claim_guard.py", 10),
    ("SessionStart", None, "survey_staleness.py", 10),
    ("Stop", None, "stop_survey_peer.py", 15),
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


def hook_command(script: str) -> str:
    return f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"'


def is_ours(command: str) -> bool:
    """A hook command belongs to this suite if it runs one of our scripts."""
    return any(script in command for script in HOOK_SCRIPTS)


def copy_tree(src: str, dst: str) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)


def install_files(root: str) -> list[str]:
    claude = os.path.join(root, ".claude")
    done = []

    dst = os.path.join(claude, "commands")
    os.makedirs(dst, exist_ok=True)
    for name in COMMANDS:
        shutil.copy2(os.path.join(SRC_CLAUDE, "commands", name), dst)
    done.append(".claude/commands/")

    for skill in SKILLS:
        copy_tree(
            os.path.join(SRC_CLAUDE, "skills", skill),
            os.path.join(claude, "skills", skill),
        )
    done.append(".claude/skills/")

    dst = os.path.join(claude, "hooks")
    os.makedirs(dst, exist_ok=True)
    for name in HOOK_SCRIPTS:
        shutil.copy2(os.path.join(SRC_CLAUDE, "hooks", name), dst)
    done.append(".claude/hooks/")

    support = os.path.join(claude, "research-skills")
    os.makedirs(os.path.join(support, "scripts"), exist_ok=True)
    shutil.copy2(
        os.path.join(SRC_SCRIPTS, "rs_validate.py"),
        os.path.join(support, "scripts"),
    )
    copy_tree(SRC_SCHEMAS, os.path.join(support, "schemas"))
    done.append(".claude/research-skills/")

    return done


def remove_files(root: str) -> None:
    claude = os.path.join(root, ".claude")

    cmd_dir = os.path.join(claude, "commands")
    for name in COMMANDS:
        path = os.path.join(cmd_dir, name)
        if os.path.exists(path):
            os.remove(path)

    for skill in SKILLS:
        shutil.rmtree(os.path.join(claude, "skills", skill), ignore_errors=True)

    for name in HOOK_SCRIPTS:
        path = os.path.join(claude, "hooks", name)
        if os.path.exists(path):
            os.remove(path)

    shutil.rmtree(os.path.join(claude, "research-skills"), ignore_errors=True)


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


def merge_hooks(settings: dict, uninstall: bool) -> dict:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}

    for event, matcher, script, timeout in HOOK_SPEC:
        entries = strip_ours(hooks.get(event, []))
        if not uninstall:
            # Heterogeneous settings payload: a hook list under "hooks", a str under
            # "matcher" — the dict literal alone would pin the value type to the list.
            entry: dict[str, Any] = {
                "hooks": [
                    {"type": "command", "command": hook_command(script), "timeout": timeout}
                ]
            }
            if matcher is not None:
                entry["matcher"] = matcher
            entries.append(entry)
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)

    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)
    return settings


def save_settings(path: str, settings: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")


def install(root: str) -> int:
    for path in install_files(root):
        print(f"  installed {path}")
    settings_path = os.path.join(root, ".claude", "settings.json")
    save_settings(settings_path, merge_hooks(load_settings(settings_path), False))
    print("  hooks merged into .claude/settings.json")

    print(
        f"\nresearch-skills installed into {root}\n"
        "Commands: /rs-survey /rs-gate /rs-relwork /rs-brief /rs-watch /rs-audit /rs-help\n"
        "Search backends are configured separately — see SETUP.md "
        "(arxiv MCP required, openalex and tavily recommended)."
    )
    return 0


def uninstall(root: str) -> int:
    remove_files(root)
    settings_path = os.path.join(root, ".claude", "settings.json")
    if os.path.exists(settings_path):
        save_settings(settings_path, merge_hooks(load_settings(settings_path), True))
    print(f"research-skills removed from {root}")
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


def doctor(root: str) -> int:
    """Check an installation item by item. Exit 1 if anything is missing."""
    claude = os.path.join(root, ".claude")
    missing = 0

    def item(label: str, present: bool) -> None:
        nonlocal missing
        if not present:
            missing += 1
        print(f"  {'ok  ' if present else 'MISS'} {label}")

    print(f"research-skills doctor — {root}\n")
    print("suite files")
    for name in COMMANDS:
        item(
            f".claude/commands/{name}",
            os.path.isfile(os.path.join(claude, "commands", name)),
        )
    for skill in SKILLS:
        item(
            f".claude/skills/{skill}/SKILL.md",
            os.path.isfile(os.path.join(claude, "skills", skill, "SKILL.md")),
        )
    for name in HOOK_SCRIPTS:
        item(
            f".claude/hooks/{name}",
            os.path.isfile(os.path.join(claude, "hooks", name)),
        )
    support = os.path.join(claude, "research-skills")
    item(
        ".claude/research-skills/scripts/rs_validate.py",
        os.path.isfile(os.path.join(support, "scripts", "rs_validate.py")),
    )
    for name in SCHEMAS:
        item(
            f".claude/research-skills/schemas/{name}",
            os.path.isfile(os.path.join(support, "schemas", name)),
        )

    print("\nsettings.json hooks")
    settings = read_settings_quiet(os.path.join(claude, "settings.json"))
    if settings is None:
        item(".claude/settings.json is present and valid JSON", False)
        settings = {}
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for event, _matcher, script, _timeout in HOOK_SPEC:
        item(f"{event}: {script}", settings_has_hook(hooks, event, script))

    print("\nsearch backends")
    if os.environ.get("OPENALEX_API_KEY"):
        print("  ok   OPENALEX_API_KEY is set")
    else:
        print("  warn OPENALEX_API_KEY is not set — openalex needs it (see SETUP.md)")
    print("  hint run `claude mcp list` to check that the search backends are connected")

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
