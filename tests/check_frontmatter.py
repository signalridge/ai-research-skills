#!/usr/bin/env python3
"""The frontmatter contract for the shipped skills and commands, in one place.

This check used to exist three times — once in ``justfile``, once inline in the CI
workflow, and not at all in the test suite, where the only skill assertion was
``"user" in text.lower()``.  Two of the three parsed frontmatter with PyYAML, which the
shipped code deliberately does not require.  This module is the single implementation:
stdlib-only, run from ``just skills``, from CI, and from ``tests/run_tests.py``.

It parses with the bundled ``_yaml_subset`` loader rather than PyYAML.  That is not only
about dependencies: the fallback parser is what an installed user's ``python3`` reaches
for, so pointing it at the frontmatter we ship is a standing check that the parser can
read our own files.

Field rules follow the Agent Skills specification (``docs/specification.mdx`` in
agentskills/agentskills).  The one deliberate deviation is recorded in ``ARS_EXTENSIONS``
below, with its cost.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "ai_research_skills" / "assets"

sys.path.insert(0, str(ASSETS / "scripts"))
from _yaml_subset import YAMLSubsetError, safe_load  # noqa: E402

# Agent Skills specification, "Frontmatter" table.
SPEC_FIELDS = frozenset(
    {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
)

# `disable-model-invocation` is absent from that table, and the reference validator
# (`skills-ref validate`) rejects unexpected fields outright — so every ARS skill fails
# spec validation on this one key, and that is a known, accepted cost.  It is kept because
# the same spec repository's client-implementation guide names this exact flag as how a
# skill opts out of model-driven activation, and because Claude Code enforces it and acts
# on nothing else: it does not read `metadata`.  Dropping the key would make "user-invoked
# only" — the project's whole position — unenforced on every host rather than one.
#
# Keep this set at exactly one entry.  Each addition is another reason a spec-conformant
# catalogue can refuse the whole suite.
ARS_EXTENSIONS = frozenset({"disable-model-invocation"})

# Slash commands are a host feature, not an Agent Skills one, so they have their own
# small field set.  `description` is required: without it a host renders the raw heading
# in its command list, which is how nine commands once shipped showing "# /ars-survey".
COMMAND_FIELDS = frozenset(
    {
        "description",
        "argument-hint",
        "allowed-tools",
        "disable-model-invocation",
        "model",
    }
)

MAX_NAME = 64
MAX_DESCRIPTION = 1024
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


def _frontmatter(path: pathlib.Path) -> tuple[dict[str, object] | None, str | None]:
    match = FRONTMATTER_RE.match(path.read_text())
    if match is None:
        return None, "has no YAML frontmatter"
    try:
        parsed = safe_load(match.group(1))
    except YAMLSubsetError as exc:
        return None, f"frontmatter does not parse: {exc}"
    if not isinstance(parsed, dict):
        return None, "frontmatter is not a mapping"
    return parsed, None


def check_skill(path: pathlib.Path) -> list[str]:
    frontmatter, error = _frontmatter(path)
    if frontmatter is None:
        return [f"{path}: {error}"]

    problems: list[str] = []

    def bad(message: str) -> None:
        problems.append(f"{path}: {message}")

    unexpected = sorted(set(frontmatter) - SPEC_FIELDS - ARS_EXTENSIONS)
    if unexpected:
        bad(f"unexpected frontmatter field(s) {unexpected}; not in the Agent Skills spec")

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        bad("`name` is missing or not a non-empty string")
    else:
        if len(name) > MAX_NAME:
            bad(f"`name` is {len(name)} characters, over the {MAX_NAME} cap")
        if not NAME_RE.match(name):
            bad(f"`name` {name!r} is not kebab-case")
        if name != path.parent.name:
            bad(f"`name` {name!r} does not match its directory {path.parent.name!r}")

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        bad("`description` is missing or not a non-empty string")
    else:
        collapsed = " ".join(description.split())
        if len(collapsed) > MAX_DESCRIPTION:
            bad(
                f"`description` is {len(collapsed)} characters, over the "
                f"{MAX_DESCRIPTION} cap"
            )
        if "<" in collapsed or ">" in collapsed:
            bad("`description` contains angle brackets, which the spec disallows")

    # The two halves of the user-invoked declaration have to agree.  The flag is what
    # Claude Code acts on; the metadata entry is what survives on hosts that drop
    # unrecognised keys.  A skill carrying one without the other is a silent downgrade.
    if frontmatter.get("disable-model-invocation") is not True:
        bad("`disable-model-invocation: true` is missing")
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        bad("`metadata` is missing; the portable invocation declaration lives there")
    else:
        if metadata.get("ars-invocation") != "user-invoked":
            bad("`metadata.ars-invocation` is not `user-invoked`")
        for key, value in metadata.items():
            if not isinstance(key, str) or not isinstance(value, str):
                bad(f"`metadata.{key}` is not a string; the spec allows string values only")

    return problems


def check_command(path: pathlib.Path) -> list[str]:
    frontmatter, error = _frontmatter(path)
    if frontmatter is None:
        return [f"{path}: {error}"]

    problems: list[str] = []
    unexpected = sorted(set(frontmatter) - COMMAND_FIELDS)
    if unexpected:
        problems.append(f"{path}: unexpected command frontmatter field(s) {unexpected}")
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        problems.append(
            f"{path}: `description` is missing; hosts fall back to the raw heading"
        )
    return problems


def problems() -> list[str]:
    found: list[str] = []
    for path in sorted((ASSETS / "skills").glob("*/SKILL.md")):
        found.extend(check_skill(path))
    for path in sorted((ASSETS / "commands").glob("*.md")):
        found.extend(check_command(path))
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(f"::error::{problem}" if os.environ.get("CI") else problem)
    if found:
        return 1
    skills = len(list((ASSETS / "skills").glob("*/SKILL.md")))
    commands = len(list((ASSETS / "commands").glob("*.md")))
    print(f"frontmatter: ok ({skills} skills, {commands} commands)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
