"""Which agent hosts this suite can install into, and what each one can actually run.

Modelled on host-reference-01's adapter registry: one record per host naming where
its skills live, what the installer owns (so uninstall never touches a foreign file),
and how to detect that a project uses it.

The honest part is `hooks`. Skills are portable — a SKILL.md body is the same text
everywhere. The four guardrails are not: they need a host that fires an event *before*
a file is written, with the path in the payload. Claude Code has that. Cursor's hook set
(beforeSubmitPrompt / stop / sessionEnd) has no file-write event at all, so the two
guards that matter most have nowhere to attach. A host that silently installs the
methodology without the enforcement leaves the user believing they are protected, which
is worse than not installing — so `hooks` is recorded per host and reported at install.
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
    """Whether the four guardrails can be wired up. Only Claude Code today."""

    commands_dir: str | None = None
    """Slash-command surface, if the host has one distinct from skills."""

    caveat: str = ""
    """What the user does not get here. Printed at install time when non-empty."""

    aliases: tuple[str, ...] = field(default_factory=tuple)

    invocation_dir: str | None = None
    """Hosts that do not make a skills/ directory directly callable need a thin file
    here that points back at the SKILL.md. Formats differ; see `include`."""

    include: str = "@{path}"
    """How the invocation file references the skill body. Kiro uses its own syntax."""

    invocation_suffix: str = ".md"


NO_GUARDS = (
    "skills only — no guardrails. Fabricated BibTeX and unsupported absence claims "
    "are not blocked on this host; run /rs-audit manually before trusting a draft."
)

HOSTS: tuple[Host, ...] = (
    Host(
        id="claude",
        skills_dir=".claude/skills",
        commands_dir=".claude/commands",
        ownership_root=".claude",
        detect_paths=(".claude",),
        hooks=True,
    ),
    Host(
        id="codex",
        skills_dir=".codex/skills",
        ownership_root=".codex",
        detect_paths=(".codex",),
        # Codex has hooks in config.toml since v0.124.0, but the payload contract
        # differs from Claude Code's. Porting the guards is tracked, not done.
        caveat=NO_GUARDS + " Codex hooks exist but use a different contract.",
    ),
    Host(
        id="cursor",
        skills_dir=".cursor/skills",
        ownership_root=".cursor",
        detect_paths=(".cursor",),
        # Verified against ~/.cursor/hooks.json: beforeSubmitPrompt, stop, sessionEnd.
        # None of them carry a file path, so the write-time guards cannot be attached.
        caveat=NO_GUARDS + " Cursor has no file-write hook event to attach them to.",
    ),
    Host(
        id="qwen",
        skills_dir=".qwen/skills",
        ownership_root=".qwen",
        detect_paths=(".qwen",),
        caveat=NO_GUARDS,
    ),
    Host(
        id="opencode",
        skills_dir=".opencode/skills",
        ownership_root=".opencode",
        detect_paths=(".opencode",),
        invocation_dir=".opencode/command",
        caveat=NO_GUARDS,
    ),
    Host(
        id="windsurf",
        skills_dir=".windsurf/skills",
        ownership_root=".windsurf",
        detect_paths=(".windsurf",),
        invocation_dir=".windsurf/workflows",
        caveat=NO_GUARDS,
    ),
    Host(
        id="kilo",
        skills_dir=".kilocode/skills",
        ownership_root=".kilocode",
        detect_paths=(".kilo", ".kilocode"),
        invocation_dir=".kilo/commands",
        caveat=NO_GUARDS,
        aliases=("kilocode",),
    ),
    Host(
        id="kiro",
        skills_dir=".kiro/skills",
        ownership_root=".kiro",
        detect_paths=(".kiro",),
        invocation_dir=".kiro/steering",
        include="#[[file:{path}]]",
        caveat=NO_GUARDS,
    ),
    Host(
        id="copilot",
        # Copilot has no skills concept; each capability is one self-contained agent file.
        skills_dir=".github/skills",
        ownership_root=".github/copilot",
        detect_paths=(".github/agents", ".github/copilot", ".github/prompts"),
        invocation_dir=".github/agents",
        invocation_suffix=".agent.md",
        caveat=NO_GUARDS,
    ),
    Host(
        id="pi",
        skills_dir=".pi/skills",
        ownership_root=".pi",
        detect_paths=(".pi",),
        caveat=NO_GUARDS,
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
