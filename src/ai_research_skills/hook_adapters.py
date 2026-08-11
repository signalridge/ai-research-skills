"""Host hook dialects used by the installer and doctor.

The guards are host-neutral, but their configuration and their stdout contracts are not.
This module is the single place that describes event capabilities, command ownership and
config shape.  In particular, ownership is exact: a command mentioning a script name is
not enough to make a foreign handler ours.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

HOOK_SCRIPTS = (
    "_payload.py",
    "bib_provenance_guard.py",
    "absence_claim_guard.py",
    "survey_staleness.py",
    "stop_survey_peer.py",
)

# canonical event, matcher, script, timeout
_BASE_SPECS = (
    ("PreToolUse", "write", "bib_provenance_guard.py", 10),
    ("PostToolUse", "write", "absence_claim_guard.py", 10),
    ("SessionStart", None, "survey_staleness.py", 10),
    ("Stop", None, "stop_survey_peer.py", 15),
)
_CLAUDE_CONDITIONS = {
    "bib_provenance_guard.py": tuple(f"{tool}(*.bib)" for tool in ("Write", "Edit")),
    "absence_claim_guard.py": tuple(
        f"{tool}(*{suffix})"
        for suffix in (".md", ".tex", ".markdown", ".mdx")
        for tool in ("Write", "Edit")
    ),
}


@dataclass(frozen=True)
class HookAdapter:
    host_id: str
    style: str
    nested: bool = True
    event_names: tuple[tuple[str, str], ...] = ()
    config_extra: tuple[tuple[str, object], ...] = ()
    supports_session_start: bool = True
    supports_stop: bool = True
    absence_event: str | None = None

    def event(self, canonical: str) -> str:
        return dict(self.event_names).get(canonical, canonical)

    def specs(self) -> tuple[tuple[str, str | None, str, int], ...]:
        out: list[tuple[str, str | None, str, int]] = []
        for canonical_event, matcher, script, timeout in _BASE_SPECS:
            if canonical_event == "SessionStart" and not self.supports_session_start:
                continue
            if canonical_event == "Stop" and not self.supports_stop:
                continue
            event = (
                self.absence_event
                if script == "absence_claim_guard.py" and self.absence_event
                else canonical_event
            )
            out.append((event, matcher, script, timeout))
        return tuple(out)

    def omitted_events(self) -> tuple[str, ...]:
        omitted: list[str] = []
        if not self.supports_session_start:
            omitted.append("SessionStart")
        if not self.supports_stop:
            omitted.append("Stop")
        return tuple(omitted)


ADAPTERS: dict[str, HookAdapter] = {
    "claude": HookAdapter("claude", "grouped"),
    # Codex's official project file is {"hooks": {"PreToolUse": [...]}}.  Its
    # absence guard is deliberately on PreToolUse too: Codex does not accept a
    # Claude PostToolUse permission decision.
    "codex": HookAdapter("codex", "grouped", nested=True, absence_event="PreToolUse"),
    # Cursor's native entries are direct {command, matcher?, timeout?} definitions.
    # Its stop event only accepts a follow-up request, not a non-looping advisory, so
    # the stop guard is omitted and the installer reports that degradation.
    "cursor": HookAdapter(
        "cursor",
        "direct",
        nested=True,
        event_names=(
            ("PreToolUse", "preToolUse"),
            ("PostToolUse", "postToolUse"),
            ("SessionStart", "sessionStart"),
            ("Stop", "stop"),
        ),
        config_extra=(("version", 1),),
        supports_stop=False,
        absence_event="PreToolUse",
    ),
    "pi": HookAdapter("pi", "grouped"),
}


def for_host(host: Any) -> HookAdapter:
    """Return the adapter for a Host-like object without importing hosts."""
    try:
        return ADAPTERS[host.id]
    except (AttributeError, KeyError):
        return HookAdapter(str(getattr(host, "id", "unknown")), "grouped")


def _shell_path(path: str) -> str:
    # shlex.quote is intentionally used rather than interpolating a project path into
    # shell source.  Hook runners invoke this string as a command.
    return shlex.quote(path)


def command_for(host: Any, script: str, root: str | None = None) -> str:
    """Build the command installed for *host*.

    Claude owns the one documented project-root variable.  Every other host gets an
    absolute path because hooks may be launched while the agent's cwd is a subdirectory.
    The profile flag selects the stdout dialect in ``_payload.py``.
    """
    if host.id == "claude":
        return f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"'
    if root is None:
        # Kept for callers that only need a display/compatibility command.  Installer
        # mutation always passes root and therefore never depends on cwd.
        path = os.path.join(host.ownership_root, "hooks", script)
    else:
        path = os.path.join(os.path.abspath(root), host.ownership_root, "hooks", script)
    return f"python3 {_shell_path(path)} --host {shlex.quote(host.id)}"


def historical_command_forms(host: Any, script: str) -> tuple[str, ...]:
    """Exact commands emitted by the published pre-manifest 0.5 installer.

    These are migration fingerprints, not a substring heuristic.  They are intentionally
    small and stable so a foreign ``echo survey_staleness.py`` or ``*.backup`` remains
    foreign.
    """
    if host.id == "claude":
        return (
            f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"',
            f'python3 ".claude/hooks/{script}"',
            f"python3 .claude/hooks/{script}",
        )
    return (f'python3 "{host.ownership_root}/hooks/{script}"',)


def is_ours(command: object, host: Any | None = None, root: str | None = None) -> bool:
    """Recognise only an exact generated or published migration command."""
    if host is None:
        candidates: list[tuple[str, str]] = [
            ("claude", ".claude"),
            ("codex", ".codex"),
            ("cursor", ".cursor"),
            ("pi", ".pi"),
        ]
        for host_id, ownership in candidates:
            for script in HOOK_SCRIPTS:
                old = (
                    (
                        f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"',
                        f'python3 ".claude/hooks/{script}"',
                        f"python3 .claude/hooks/{script}",
                    )
                    if host_id == "claude"
                    else (f'python3 "{ownership}/hooks/{script}"',)
                )
                relative = os.path.join(ownership, "hooks", script)
                if command in old or (
                    host_id != "claude"
                    and command == f"python3 {_shell_path(relative)} --host {host_id}"
                ):
                    return True
                if root is not None:
                    absolute = os.path.join(
                        os.path.abspath(root), ownership, "hooks", script
                    )
                    if command == f"python3 {_shell_path(absolute)} --host {host_id}":
                        return True
        return False
    for script in HOOK_SCRIPTS:
        if command in historical_command_forms(host, script):
            return True
        if command == command_for(host, script, root):
            return True
    return False


def _matcher(host: Any, canonical_matcher: str | None) -> str | None:
    if canonical_matcher is None:
        return None
    tools = tuple(getattr(host, "write_tools", ()) or ())
    return "|".join(tools) if tools else canonical_matcher


def handler_definition(  # noqa: PLR0913, PLR0917
    host: Any,
    matcher: str | None,
    script: str,
    timeout: int,
    condition: str | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    """Build one native handler definition, not a whole event group."""
    adapter = for_host(host)
    definition: dict[str, Any] = {
        "command": command_for(host, script, root),
        "timeout": timeout,
    }
    if condition is not None:
        definition["if"] = condition
    match = _matcher(host, matcher)
    if match is not None:
        definition["matcher"] = match
    if adapter.style == "grouped":
        return {"type": "command", **definition}
    # Cursor rejects Claude's type/hooks wrapper.  Do not add even harmless-looking
    # fields: direct definitions are the native contract.
    return definition


def _command_tokens(command: object) -> list[str]:
    if not isinstance(command, str):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def command_runs_script(command: object, script: str) -> bool:
    """Recognise a Python hook command without basename substring matching."""
    tokens = _command_tokens(command)
    if not tokens or os.path.basename(tokens[0]) not in {"python", "python3"}:
        return False
    return any(os.path.basename(token) == script for token in tokens[1:])


def exact_script(command: object, host: Any, root: str | None = None) -> str | None:
    if not isinstance(command, str):
        return None
    for script in HOOK_SCRIPTS:
        if command in historical_command_forms(host, script) or command == command_for(
            host, script, root
        ):
            return script
    return None


def script_for_command(
    command: object,
    host: Any,
    root: str | None = None,
    *,
    allow_absolute_without_root: bool = False,
) -> str | None:
    """Identify a generated handler even when a user appended an option.

    Exact ownership still requires ``root`` (or a published historical form).  The
    optional root-less absolute mode exists only for diagnostics of an already-loaded
    config; mutation paths never use it to claim ownership.
    """
    exact = exact_script(command, host, root)
    if exact is not None:
        return exact
    tokens = _command_tokens(command)
    if len(tokens) < 2 or os.path.basename(tokens[0]) not in {"python", "python3"}:
        return None
    for script in HOOK_SCRIPTS:
        expected = _command_tokens(command_for(host, script, root))
        if (
            len(tokens) >= len(expected)
            and tokens[: len(expected)] == expected
            and (
                root is not None
                or (allow_absolute_without_root and os.path.isabs(tokens[1]))
            )
        ):
            return script
        if (
            allow_absolute_without_root
            and host.id != "claude"
            and len(expected) >= 4
            and len(tokens) >= 4
            and os.path.isabs(tokens[1])
            and tokens[2:4] == expected[2:4]
            and tokens[1].replace("\\", "/").endswith("/" + expected[1])
        ):
            return script
    return None


def _record_matches(
    item: dict[str, Any],
    event: str,
    script: str,
    group_matcher: object,
    expected: Iterable[dict[str, Any]],
) -> bool:
    actual_matcher = item.get("matcher", group_matcher)
    for wanted in expected:
        if wanted.get("script") != script or (event and wanted.get("event") != event):
            continue
        definition = wanted.get("definition")
        if isinstance(definition, dict):
            if definition == item and wanted.get("matcher") == actual_matcher:
                return True
            continue
        if all(
            wanted.get(key) == value
            for key, value in (
                ("command", item.get("command")),
                ("matcher", actual_matcher),
                ("timeout", item.get("timeout")),
            )
        ):
            return True
    return False


def _legacy_match(item: dict[str, Any], host: Any, script: str, root: str | None) -> bool:
    command = item.get("command")
    exact = set(historical_command_forms(host, script))
    return isinstance(command, str) and command in exact


def _current_match(  # noqa: PLR0913
    item: dict[str, Any],
    host: Any,
    event: str,
    script: str,
    root: str | None,
    *,
    group_matcher: object = None,
) -> bool:
    """Match a complete generated definition, never a command string alone."""
    adapter = for_host(host)
    for spec_event, matcher, spec_script, timeout in adapter.specs():
        if spec_script != script or adapter.event(spec_event) != event:
            continue
        if adapter.style == "grouped" and group_matcher != _matcher(host, matcher):
            continue
        conditions = _CLAUDE_CONDITIONS.get(script, ()) if host.id == "claude" else ()
        expected = [
            handler_definition(host, matcher, script, timeout, condition, root)
            for condition in (conditions or (None,))
        ]
        if item in expected:
            return True
    return False


def _should_remove(  # noqa: PLR0913, PLR0917
    item: Any,
    host: Any,
    event: str,
    script: str,
    group_matcher: object,
    owned_records: Iterable[dict[str, Any]] | None,
    root: str | None,
    allow_legacy: bool,
) -> bool:
    if not isinstance(item, dict):
        return False
    if owned_records is not None:
        return _record_matches(item, event, script, group_matcher, owned_records)
    if _current_match(item, host, event, script, root, group_matcher=group_matcher):
        return True
    return allow_legacy and _legacy_match(item, host, script, root)


def _strip_grouped(  # noqa: PLR0913, PLR0917
    entries: Iterable[Any],
    host: Any,
    event: str,
    script: str | None,
    owned_records: Iterable[dict[str, Any]] | None,
    root: str | None,
    allow_legacy: bool,
) -> list[Any]:
    kept: list[Any] = []
    for raw in entries:
        if not isinstance(raw, dict) or not isinstance(raw.get("hooks"), list):
            kept.append(deepcopy(raw))
            continue
        removed = False
        foreign: list[Any] = []
        for hook in raw["hooks"]:
            ours = script is not None and _should_remove(
                hook,
                host,
                event,
                script,
                raw.get("matcher"),
                owned_records,
                root,
                allow_legacy,
            )
            if ours:
                removed = True
            else:
                foreign.append(hook)
        if not removed:
            kept.append(deepcopy(raw))
        elif foreign:
            item = deepcopy(raw)
            item["hooks"] = foreign
            kept.append(item)
        elif any(key not in {"hooks", "matcher"} for key in raw):
            # Removing a handler must not erase unknown group metadata.
            item = deepcopy(raw)
            item["hooks"] = []
            kept.append(item)
        # An all-owned group without foreign metadata can be dropped.
    return kept


def strip_ours(  # noqa: PLR0913
    entries: Any,
    host: Any,
    owned_records: Iterable[dict[str, Any]] | None = None,
    *,
    root: str | None = None,
    allow_legacy: bool = False,
    event: str | None = None,
) -> list[Any]:
    """Remove only exact owned/migration handlers, preserving all foreign entries."""
    if not isinstance(entries, list):
        return []
    adapter = for_host(host)
    if adapter.style == "direct":
        kept: list[Any] = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept.append(deepcopy(entry))
                continue
            script = exact_script(entry.get("command"), host, root)
            ours = (
                script is not None
                and event is not None
                and _should_remove(
                    entry,
                    host,
                    event,
                    script,
                    None,
                    owned_records,
                    root,
                    allow_legacy,
                )
            )
            if not ours:
                kept.append(deepcopy(entry))
        return kept
    result: list[Any] = [deepcopy(entry) for entry in entries]
    # The grouped form has no single script at this API boundary.  Strip each known
    # script independently so exact ownership rules still apply.
    for script in HOOK_SCRIPTS:
        result = _strip_grouped(
            result,
            host,
            event or "",
            script,
            owned_records,
            root,
            allow_legacy,
        )
    return result


def _strip_script(  # noqa: PLR0913
    entries: Any,
    host: Any,
    script: str,
    *,
    event: str | None = None,
    owned_records: Iterable[dict[str, Any]] | None = None,
    root: str | None = None,
    allow_legacy: bool = False,
) -> list[Any]:
    """Remove one script's exact definitions (needed when two guards share an event)."""
    if not isinstance(entries, list):
        return []
    adapter = for_host(host)
    effective_event = event or ""
    if adapter.style == "direct":
        kept: list[Any] = []
        for entry in entries:
            ours = isinstance(entry, dict) and _should_remove(
                entry,
                host,
                effective_event,
                script,
                None,
                owned_records,
                root,
                allow_legacy,
            )
            if not ours:
                kept.append(deepcopy(entry))
        return kept
    return _strip_grouped(
        entries,
        host,
        effective_event,
        script,
        owned_records,
        root,
        allow_legacy,
    )


def _container(
    settings: dict[str, Any], host: Any, create: bool = False
) -> dict[str, Any] | None:
    adapter = for_host(host)
    if adapter.nested:
        value = settings.get("hooks")
        if isinstance(value, dict):
            return value
        if create:
            value = {}
            settings["hooks"] = value
            return value
        return None
    return settings


def _migrate_cursor_grouped(settings: dict[str, Any], host: Any, root: str | None) -> None:
    """Convert v0.5 grouped Cursor handlers to native direct entries.

    The old adapter used Claude's ``{matcher, hooks: [...]}`` groups.  Cursor's
    current event lists cannot contain those wrappers, so foreign handlers are
    copied as direct definitions while exact ARS commands are discarded.  Group
    metadata has no native direct slot; retain it in a dedicated top-level
    preservation record instead of silently dropping an unknown key.  Stop is
    included even though the current Cursor adapter intentionally omits it.
    """
    container = _container(settings, host)
    if not isinstance(container, dict):
        return
    adapter = for_host(host)
    preserved_metadata: list[dict[str, Any]] = []

    def convert(event: str, entries: object, script: str) -> list[Any]:
        if not isinstance(entries, list):
            return []
        converted: list[Any] = []
        for raw in entries:
            if not isinstance(raw, dict) or not isinstance(raw.get("hooks"), list):
                converted.append(deepcopy(raw))
                continue
            group_metadata = {
                key: deepcopy(value)
                for key, value in raw.items()
                if key not in {"hooks", "matcher"}
            }
            if group_metadata:
                preserved_metadata.append({"event": event, **group_metadata})
            matcher = raw.get("matcher")
            foreign_start = len(converted)
            for hook in raw["hooks"]:
                if not isinstance(hook, dict):
                    converted.append(deepcopy(hook))
                    continue
                command = hook.get("command")
                if isinstance(command, str) and command in historical_command_forms(
                    host, script
                ):
                    continue
                native = deepcopy(hook)
                # `type=command` is the grouped wrapper's discriminator, not a
                # Cursor direct-entry field.  Other foreign keys are retained.
                native.pop("type", None)
                if matcher is not None and "matcher" not in native:
                    native["matcher"] = deepcopy(matcher)
                converted.append(native)
            if group_metadata:
                for candidate in converted[foreign_start:]:
                    if isinstance(candidate, dict) and "command" in candidate:
                        for key, value in group_metadata.items():
                            candidate.setdefault(key, deepcopy(value))
                        break
        return converted

    for canonical_event, _matcher, script, _timeout in _BASE_SPECS:
        destination = adapter.event(canonical_event)
        merged: list[Any] = []
        for source_event in {canonical_event, destination}:
            if source_event not in container:
                continue
            source_entries = container.get(source_event)
            if source_event == destination:
                merged.extend(convert(source_event, source_entries, script))
            else:
                merged.extend(convert(source_event, source_entries, script))
                container.pop(source_event, None)
        if merged:
            container[destination] = merged
        else:
            container.pop(destination, None)

    if preserved_metadata:
        existing = settings.get("_ars_legacy_cursor_group_metadata")
        if isinstance(existing, list):
            existing.extend(preserved_metadata)
        elif existing is None:
            settings["_ars_legacy_cursor_group_metadata"] = preserved_metadata
        else:
            # Do not overwrite a foreign value at our preservation key.
            settings["_ars_legacy_cursor_group_metadata_1"] = preserved_metadata


def merge(  # noqa: PLR0913, PLR0917
    settings: dict[str, Any],
    uninstall: bool,
    host: Any,
    root: str | None = None,
    owned_records: list[dict[str, Any]] | None = None,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    """Merge/remove this suite's handlers without claiming the config file."""
    adapter = for_host(host)
    if host.id == "cursor" and allow_legacy:
        _migrate_cursor_grouped(settings, host, root)
    # Migrate old pre-adapter Codex output that put events at the JSON root.  Only exact
    # manifest definitions or exact published command forms are eligible.
    if host.id == "codex":
        old_root_specs = list(adapter.specs())
        # The pre-adapter installer placed absence on PostToolUse.  It is an exact
        # migration candidate, never a reason to remove an arbitrary PostToolUse entry.
        old_root_specs.append(("PostToolUse", "write", "absence_claim_guard.py", 10))
        for canonical_event, _matcher_value, script, _timeout in old_root_specs:
            if canonical_event not in settings:
                continue
            cleaned = _strip_script(
                settings.get(canonical_event),
                host,
                script,
                event=canonical_event,
                owned_records=owned_records,
                root=root,
                allow_legacy=allow_legacy,
            )
            if cleaned:
                settings[canonical_event] = cleaned
            else:
                settings.pop(canonical_event, None)

    container = _container(settings, host, create=not uninstall)
    if container is None:
        return settings

    for canonical_event, matcher, script, timeout in adapter.specs():
        event = adapter.event(canonical_event)
        current = container.get(event)
        entries = _strip_script(
            current,
            host,
            script,
            event=event,
            owned_records=owned_records,
            root=root,
            allow_legacy=allow_legacy,
        )
        if not uninstall:
            conditions = _CLAUDE_CONDITIONS.get(script, ()) if host.id == "claude" else ()
            definitions = [
                handler_definition(host, matcher, script, timeout, condition, root)
                for condition in (conditions or (None,))
            ]
            if adapter.style == "direct":
                entries.extend(definitions)
            else:
                group: dict[str, Any] = {"hooks": definitions}
                match = _matcher(host, matcher)
                if match is not None:
                    group["matcher"] = match
                entries.append(group)
        if entries:
            container[event] = entries
        else:
            container.pop(event, None)

    if not uninstall:
        for key, value in adapter.config_extra:
            settings.setdefault(key, value)

    if adapter.nested and not container:
        settings.pop("hooks", None)
    return settings


def _iter_event_handlers(
    settings: dict[str, Any], host: Any, event: str
) -> Iterable[tuple[dict[str, Any], object]]:
    adapter = for_host(host)
    container = _container(settings, host)
    if not isinstance(container, dict):
        return ()
    entries = container.get(event)
    if not isinstance(entries, list):
        return ()
    out: list[tuple[dict[str, Any], object]] = []
    for entry in entries:
        if adapter.style == "direct":
            if isinstance(entry, dict):
                out.append((entry, entry.get("matcher")))
        elif isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
            out.extend(
                (item, entry.get("matcher"))
                for item in entry["hooks"]
                if isinstance(item, dict)
            )
    return tuple(out)


def handler_records(
    settings: dict[str, Any], host: Any, root: str | None = None
) -> list[dict[str, Any]]:
    """Return only complete generated handler fingerprints."""
    adapter = for_host(host)
    records: list[dict[str, Any]] = []
    for canonical_event, _matcher_value, script, _timeout in adapter.specs():
        event = adapter.event(canonical_event)
        for item, group_matcher in _iter_event_handlers(settings, host, event):
            # A command path is only a candidate.  Ownership requires the complete
            # generated definition, including the host/event/group matcher, timeout,
            # and Claude condition.  This keeps same-command foreign handlers out of
            # the manifest and therefore out of later reinstall/uninstall mutations.
            if not _current_match(
                item, host, event, script, root, group_matcher=group_matcher
            ):
                continue
            records.append(
                {
                    "event": event,
                    "script": script,
                    "command": str(item.get("command", "")),
                    "matcher": item.get("matcher", group_matcher),
                    "timeout": item.get("timeout"),
                    "definition": deepcopy(item),
                }
            )
    return records


def all_config_commands(settings: object) -> list[str]:
    """Return command strings in a config, including old Codex root-event layouts."""
    out: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            command = value.get("command")
            if isinstance(command, str):
                out.append(command)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(settings)
    return out


def validate_config(settings: object, host: Any, root: str | None = None) -> list[str]:
    """Validate the actual host shape, not a string search through JSON text."""
    adapter = for_host(host)
    errors: list[str] = []
    if not isinstance(settings, dict):
        return ["config is not a JSON object"]
    if adapter.nested:
        container = settings.get("hooks")
        if not isinstance(container, dict):
            errors.append("missing top-level hooks object")
            return errors
    else:
        container = settings
    if adapter.style == "direct" and not (
        type(settings.get("version", 1)) is int and settings.get("version", 1) == 1
    ):
        errors.append("Cursor hooks.json version must be 1 when explicitly present")
    if host.id == "codex":
        root_events = {name for name, *_rest in adapter.specs() if name in settings}
        if root_events:
            errors.append("Codex events must be under top-level hooks, not at root")

    for canonical_event, matcher, script, _timeout in adapter.specs():
        event = adapter.event(canonical_event)
        entries = container.get(event)
        if not isinstance(entries, list):
            errors.append(f"missing {event} handler list")
            continue
        found = False
        for entry in entries:
            if adapter.style == "direct":
                if not isinstance(entry, dict) or "hooks" in entry:
                    if isinstance(entry, dict) and "hooks" in entry:
                        errors.append(f"{event} uses Claude hooks wrapper")
                    continue
                handler_list = [entry]
                group_matcher = entry.get("matcher")
            else:
                if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                    continue
                handler_list = entry["hooks"]
                group_matcher = entry.get("matcher")
            for handler in handler_list:
                if not isinstance(handler, dict):
                    continue
                if (
                    script_for_command(
                        handler.get("command"),
                        host,
                        root,
                        allow_absolute_without_root=root is None,
                    )
                    != script
                ):
                    continue
                found = True
                if not isinstance(handler.get("command"), str):
                    errors.append(f"{event}/{script} has no command")
                if adapter.style == "grouped" and handler.get("type") != "command":
                    errors.append(f"{event}/{script} is missing type=command")
                if adapter.style == "direct":
                    extra = set(handler) - {"command", "matcher", "timeout"}
                    if extra:
                        errors.append(
                            f"{event}/{script} has Cursor-only unknown fields: "
                            + ", ".join(sorted(extra))
                        )
                if root is not None and handler.get("command") != command_for(
                    host, script, root
                ):
                    errors.append(
                        f"{event}/{script} command is not the installed root/profile"
                    )
                effective_matcher = handler.get("matcher", group_matcher)
                if matcher is not None and effective_matcher is not None:
                    tools = getattr(host, "write_tools", ()) or ()
                    if tools and not any(tool in str(effective_matcher) for tool in tools):
                        errors.append(
                            f"{event}/{script} matcher does not cover write tools"
                        )
                if not isinstance(handler.get("timeout"), int):
                    errors.append(f"{event}/{script} has no integer timeout")
        if not found:
            errors.append(f"missing {event}/{script}")
    return errors


def caveat(host: Any) -> str:
    adapter = for_host(host)
    notes: list[str] = []
    if adapter.omitted_events():
        notes.append(
            "degraded: unsupported hook events omitted ("
            + ", ".join(adapter.omitted_events())
            + ")"
        )
    if host.id == "pi":
        notes.append(
            "configured-but-inactive until `pi install npm:@hsingjui/pi-hooks`; "
            "this installer cannot confirm that the Pi extension is loaded."
        )
    return " ".join(notes)
