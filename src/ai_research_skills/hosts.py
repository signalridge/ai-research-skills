"""Host locations for installing the standalone research toolbox.

Skills and optional slash-command aliases are portable.  ARS no longer installs or
configures runtime governance hooks on any host.  The legacy hook location fields remain
so the installer can recognize and clean up an exact old ARS installation without claiming
or changing foreign host configuration; they are removed in 0.9.0 along with the rest of
the legacy hook path (see docs/DESIGN.md §4).
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
        detect_paths=(".kimi",),
        hooks_file="settings.json",
    ),
    # `.kimi-code` is a second on-disk layout, not a spelling of `.kimi`.  Listing it as a
    # detect path of the host above meant a project holding only `.kimi-code/` was detected
    # as kimi and then installed into a newly created `.kimi/`, leaving the directory the
    # user actually had untouched.  A separate id keeps the manifest and the ownership
    # allowlist unambiguous, and lets a project that somehow has both keep them apart.
    Host(
        id="kimi-code",
        skills_dir=".kimi-code/skills",
        ownership_root=".kimi-code",
        detect_paths=(".kimi-code",),
        hooks_file="settings.json",
    ),
)

DEFAULT_HOST = "claude"


def lookup(host_id: str) -> Host | None:
    """Resolve an id to a host.  Every on-disk layout is its own id, never an alias of
    another, so that a manifest path and the ownership allowlist stay unambiguous."""
    wanted = host_id.strip().lower()
    for host in HOSTS:
        if wanted == host.id:
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
