"""Host locations for installing the standalone research toolbox.

Skills and optional slash-command aliases are portable.  ARS no longer installs or
configures runtime governance hooks on any host.  The legacy hook location fields remain
so the installer can recognize and clean up an exact old ARS installation during one
compatibility period without claiming or changing foreign host configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Host:
    id: str
    skills_dir: str
    """Where skill directories go, relative to the project root."""

    ownership_root: str
    """The host directory containing files owned by this package."""

    detect_paths: tuple[str, ...]
    """Directories that indicate this host is already used by the project."""

    hooks: bool = False
    """Compatibility field: fresh installs never enable runtime hooks."""

    hooks_file: str = "settings.json"
    """Historical hook configuration filename, used only for legacy cleanup."""

    hooks_nested: bool = True
    event_names: dict[str, str] = field(default_factory=dict)
    config_extra: dict[str, object] = field(default_factory=dict)
    write_tools: tuple[str, ...] = ()
    filter_conditions: bool = False
    commands_dir: str | None = None
    caveat: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


HOSTS: tuple[Host, ...] = (
    Host(
        id="claude",
        skills_dir=".claude/skills",
        ownership_root=".claude",
        detect_paths=(".claude",),
        hooks_file="settings.json",
        commands_dir=".claude/commands",
    ),
    Host(
        id="codex",
        skills_dir=".codex/skills",
        ownership_root=".codex",
        detect_paths=(".codex",),
        hooks_file="hooks.json",
    ),
    Host(
        id="cursor",
        skills_dir=".cursor/skills",
        ownership_root=".cursor",
        detect_paths=(".cursor",),
        hooks_file="hooks.json",
        config_extra={"version": 1},
    ),
    Host(
        id="pi",
        skills_dir=".pi/skills",
        ownership_root=".pi",
        detect_paths=(".pi",),
        hooks_file="settings.json",
    ),
    Host(
        id="kimi",
        skills_dir=".kimi/skills",
        ownership_root=".kimi",
        detect_paths=(".kimi", ".kimi-code"),
        hooks_file="settings.json",
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
    """Return hosts whose normal project directory is already present."""
    return tuple(
        host
        for host in HOSTS
        if any(os.path.isdir(os.path.join(root, path)) for path in host.detect_paths)
    )


def resolve(root: str, requested: str | None) -> tuple[tuple[Host, ...], list[str]]:
    """Resolve explicit hosts or detect the hosts already used by a project."""
    if requested:
        chosen: list[Host] = []
        unknown: list[str] = []
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
    if fallback is None:  # pragma: no cover
        raise RuntimeError(f"default host {DEFAULT_HOST!r} missing from registry")
    return (fallback,), []
