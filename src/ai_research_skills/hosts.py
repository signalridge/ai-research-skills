"""Which agent hosts this suite can install into, and what each one can actually run.

Modelled on host-reference-01's adapter registry: one record per host naming where
its skills live, what the installer owns (so uninstall never touches a foreign file),
and how to detect that a project uses it.

Scope is deliberately narrow: a host earns a record by having a verified way to run the
guardrails, or by being one the author actually uses. Hosts that can only take skills
were dropped rather than shipped — the design rests on enforcement being real, and an
adapter that installs the methodology alone hands the user a false sense of it. The
removed six (qwen, opencode, windsurf, kilo, kiro, copilot) also needed thin invocation
stub files, and deleting them took that whole mechanism with them.

OpenCode is the one worth revisiting: it does have a blocking pre-tool hook
(`tool.execute.before`, blocks by throwing), but only through a TypeScript plugin in
.opencode/plugin/, so wiring it up means shipping a TS bridge that shells out to these
Python guards rather than a config file.

The honest part is `hooks`. Skills are portable — a SKILL.md body is the same text
everywhere. The four guardrails are not: they need a host that fires an event with the
path in the payload. Claude and Codex have grouped pre-tool surfaces; Cursor has native
pre-tool and stop events, but its stop response is a follow-up request rather than a safe
advisory channel, so this package omits that event; Pi depends on an extension whose
runtime this installer cannot confirm. A host that silently installs an unverified
methodology leaves the user believing they are protected, so adapters report configured
versus degraded rather than claiming active runtime enforcement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Host:
    id: str
    skills_dir: str
    """Where SKILL.md directories go, relative to the project root."""

    ownership_root: str
    """Everything the installer may create or remove lives under here."""

    detect_paths: tuple[str, ...]
    """If any of these exist in a project, the project uses this host."""

    hooks: bool = False
    """Whether the four guardrails can be wired up."""

    hooks_file: str = "settings.json"
    """Where the host reads hook config from, relative to ownership_root. Claude Code
    nests them under a `hooks` key in settings.json; Codex reads hooks.json with its own
    top-level `hooks` object."""

    hooks_nested: bool = True
    """True when the config wraps the events in a top-level `hooks` object."""

    event_names: dict[str, str] = field(default_factory=dict)
    """Rename Claude Code's event names to this host's. Cursor uses camelCase."""

    config_extra: dict[str, object] = field(default_factory=dict)
    """Keys the host requires at the top of its config. Cursor 3.x rejects a project
    hooks.json with no `version` and loads none of the hooks — silently."""

    write_tools: tuple[str, ...] = ()
    """Tool names this host uses for file writes, for the hook matcher. Empty means
    fall back to matching every tool — correct, just less efficient."""

    filter_conditions: bool = False
    """Whether to emit `if` pre-filters. Only where BOTH the tool names and the
    condition syntax are verified: a condition that never matches silently disables the
    guard, which is strictly worse than spawning a process that exits immediately."""

    commands_dir: str | None = None
    """Slash-command surface, if the host has one distinct from skills."""

    caveat: str = ""
    """What the user does not get here. Printed at install time when non-empty."""

    aliases: tuple[str, ...] = field(default_factory=tuple)


# No slash commands here either, so this must not name one: pointing a Kimi user at
# /ars-audit sends them to a command that was never installed, in the one message whose
# whole job is to say plainly what they did not get.
NO_GUARDS = (
    "skills only — no guardrails. Fabricated BibTeX and unsupported absence claims "
    "are not blocked on this host; ask for the `ars-red-team` and `ars-verify` skills "
    "by name before trusting a draft."
)

# Hook shape is kept in hook_adapters rather than guessed here. Claude/Codex use grouped
# handlers, Cursor uses direct definitions and only its pre-tool deny surface is safe to
# claim, and Pi's extension runtime remains configured-but-unconfirmed. Writing a config
# that parses but never fires leaves the user believing the guards are running, so doctor
# validates the actual tree and reports the remaining runtime caveat.

HOSTS: tuple[Host, ...] = (
    Host(
        id="claude",
        skills_dir=".claude/skills",
        commands_dir=".claude/commands",
        ownership_root=".claude",
        detect_paths=(".claude",),
        hooks=True,
        write_tools=("Write", "Edit"),
        filter_conditions=True,
    ),
    Host(
        id="codex",
        skills_dir=".codex/skills",
        ownership_root=".codex",
        detect_paths=(".codex",),
        # Codex reads project hooks from .codex/hooks.json and uses the same event
        # names and the same hookSpecificOutput.permissionDecision deny schema as
        # Claude Code, so the guards run unmodified. The difference is the write
        # payload: Codex routes writes through apply_patch, whose tool_input carries a
        # patch body rather than a file_path. hooks/_payload.py reads both shapes.
        hooks=True,
        hooks_file="hooks.json",
        # Codex's official project shape is {"hooks": {"PreToolUse": [...]}}.
        # The nested hook groups are handled by hook_adapters; never emit events at
        # the JSON root.
        hooks_nested=True,
        # Codex writes through apply_patch, so Write(...)/Edit(...) conditions would
        # never match and would turn the guards off without saying so. Whether Codex
        # accepts Claude's permission-rule condition syntax at all is unverified, so
        # it gets no pre-filter: the guards run on every tool call and check the
        # suffix themselves, which is what they did before the filter existed.
        write_tools=("apply_patch", "Write", "Edit"),
    ),
    Host(
        id="cursor",
        skills_dir=".cursor/skills",
        ownership_root=".cursor",
        detect_paths=(".cursor",),
        # Cursor's native project hook file uses camelCase event names and direct
        # {command, matcher?, timeout?} definitions.  Its stop event accepts a
        # follow-up request, not a non-looping advisory, so stop_survey_peer is omitted
        # deliberately; install reports that degradation.  Absence denial moves to
        # preToolUse.  Keep these layout facts in the adapter rather than making
        # installer code guess from a Claude-shaped group.
        hooks=True,
        hooks_file="hooks.json",
        hooks_nested=True,
        config_extra={"version": 1},
        event_names={
            "PreToolUse": "preToolUse",
            "PostToolUse": "postToolUse",
            "SessionStart": "sessionStart",
            "Stop": "stop",
        },
        write_tools=("Write", "Edit"),
    ),
    Host(
        id="pi",
        skills_dir=".pi/skills",
        ownership_root=".pi",
        detect_paths=(".pi",),
        # Pi's native extension API is TypeScript, but the @hsingjui/pi-hooks package
        # provides Claude-Code-compatible command hooks in .pi/settings.json using the
        # same nested shape, event names and deny schema. The config is written either
        # way; without the package it is inert, so the caveat says so rather than
        # letting an inert file read as protection.
        hooks=True,
        hooks_file="settings.json",
        write_tools=("write", "edit"),
        caveat=(
            "guardrails need `pi install npm:@hsingjui/pi-hooks` — the config is "
            "written but does nothing until that package is present."
        ),
    ),
    Host(
        id="kimi",
        skills_dir=".kimi/skills",
        ownership_root=".kimi",
        detect_paths=(".kimi", ".kimi-code"),
        caveat=NO_GUARDS,
        aliases=("kimi-code",),
    ),
)

DEFAULT_HOST = "claude"


def lookup(host_id: str) -> Host | None:
    wanted = host_id.strip().lower()
    for host in HOSTS:
        if wanted == host.id or wanted in host.aliases:
            return host
    return None


def known_ids() -> tuple[str, ...]:
    return tuple(host.id for host in HOSTS)


def detect(root: str) -> tuple[Host, ...]:
    """Hosts a project already uses, by the directories it carries."""
    found = [
        host
        for host in HOSTS
        if any(os.path.isdir(os.path.join(root, p)) for p in host.detect_paths)
    ]
    return tuple(found)


def resolve(root: str, requested: str | None) -> tuple[tuple[Host, ...], list[str]]:
    """(hosts to install into, unknown ids the caller asked for).

    An explicit --host wins. Otherwise install into every host the project already
    uses, falling back to Claude Code when the project uses none — a bare project
    should still get a working install rather than an empty one.
    """
    if requested:
        chosen, unknown = [], []
        for raw in requested.replace(",", " ").split():
            host = lookup(raw)
            if host is None:
                unknown.append(raw)
            elif host not in chosen:
                chosen.append(host)
        return tuple(chosen), unknown

    detected = detect(root)
    if detected:
        return detected, []
    fallback = lookup(DEFAULT_HOST)
    if fallback is None:  # pragma: no cover — DEFAULT_HOST is always in HOSTS
        raise RuntimeError(f"default host {DEFAULT_HOST!r} missing from registry")
    return (fallback,), []
