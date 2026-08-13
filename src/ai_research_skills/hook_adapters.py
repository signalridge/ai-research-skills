"""Legacy hook recognizers and cleanup helpers.

ARS 0.8 does not generate, install, or validate runtime governance hooks.  This module is
kept for one compatibility period so an upgrade or explicit doctor run can remove an
exact, unchanged ARS handler from an older install.  It deliberately has no desired
handler builder: fresh installs never touch host hook configuration.
"""

from __future__ import annotations

import copy
import os
import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

HOOK_SCRIPTS = (
    "_payload.py",
    "bib_provenance_guard.py",
    "absence_claim_guard.py",
    "survey_staleness.py",
    "stop_survey_peer.py",
)

# Historical event/script metadata is intentionally data for recognition only.
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

# These are the exact write-tool matchers emitted by historical host adapters.  They
# are used only after the ordinary-file fingerprint proves an old ARS install; they are
# not a current host configuration contract.  A couple of hosts had more than one
# published spelling during the compatibility window, so keep those spellings explicit.
_LEGACY_WRITE_MATCHERS: dict[str, frozenset[str]] = {
    "claude": frozenset({"Write|Edit"}),
    "codex": frozenset({"apply_patch|Write|Edit", "Write|Edit"}),
    "cursor": frozenset({"Write|Edit"}),
    "pi": frozenset({"write|edit", "Write|Edit"}),
}
_LEGACY_HANDLER_HOSTS = frozenset(_LEGACY_WRITE_MATCHERS)


def legacy_handlers_required(host: Any) -> bool:
    """Whether the old host had an ARS hook layout to prove before cleanup."""
    return str(getattr(host, "id", "")) in _LEGACY_HANDLER_HOSTS


def legacy_config_supported(host: Any) -> bool:
    """Whether exact legacy hook configuration may be inspected for this host."""
    return legacy_handlers_required(host)


def _legacy_grouped_ownership_provened(
    settings: dict[str, Any],
    host: Any,
    root: str | None,
    owned_records: Iterable[dict[str, Any]] | None,
    allow_legacy: bool,
) -> bool:
    """Return whether grouped Cursor migration has complete ownership evidence."""
    return host.id == "cursor" and allow_legacy


def legacy_write_matcher_matches(host: Any, matcher: object) -> bool:
    """Return whether *matcher* is a published matcher for this old host."""
    return isinstance(matcher, str) and matcher in _LEGACY_WRITE_MATCHERS.get(
        str(getattr(host, "id", "")), frozenset()
    )


@dataclass(frozen=True)
class HookAdapter:
    host_id: str
    style: str = "grouped"
    nested: bool = True
    event_names: tuple[tuple[str, str], ...] = ()
    supports_session_start: bool = True
    supports_stop: bool = True
    absence_event: str | None = None

    def event(self, canonical: str) -> str:
        return dict(self.event_names).get(canonical, canonical)

    def specs(self) -> tuple[tuple[str, str | None, str, int], ...]:
        result: list[tuple[str, str | None, str, int]] = []
        for event, matcher, script, timeout in _BASE_SPECS:
            if event == "SessionStart" and not self.supports_session_start:
                continue
            if event == "Stop" and not self.supports_stop:
                continue
            result.append(
                (
                    self.absence_event
                    if script == "absence_claim_guard.py" and self.absence_event
                    else event,
                    matcher,
                    script,
                    timeout,
                )
            )
        return tuple(result)

    def omitted_events(self) -> tuple[str, ...]:
        omitted: list[str] = []
        if not self.supports_session_start:
            omitted.append("SessionStart")
        if not self.supports_stop:
            omitted.append("Stop")
        return tuple(omitted)


ADAPTERS: dict[str, HookAdapter] = {
    "claude": HookAdapter("claude"),
    "codex": HookAdapter("codex", absence_event="PreToolUse"),
    "cursor": HookAdapter(
        "cursor",
        style="direct",
        event_names=(
            ("PreToolUse", "preToolUse"),
            ("PostToolUse", "postToolUse"),
            ("SessionStart", "sessionStart"),
            ("Stop", "stop"),
        ),
        supports_stop=False,
        absence_event="PreToolUse",
    ),
    "pi": HookAdapter("pi"),
    "kimi": HookAdapter("kimi"),
}


def for_host(host: Any) -> HookAdapter:
    return ADAPTERS.get(str(getattr(host, "id", "")), HookAdapter("unknown"))


def _shell_path(path: str) -> str:
    return shlex.quote(path)


def _legacy_relative_command(host: Any, script: str) -> tuple[str, ...]:
    if host.id == "claude":
        return (
            f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"',
            f'python3 ".claude/hooks/{script}"',
            f"python3 .claude/hooks/{script}",
        )
    return (f'python3 "{host.ownership_root}/hooks/{script}"',)


def historical_command_forms(host: Any, script: str) -> tuple[str, ...]:
    """Commands emitted by pre-0.8 ARS versions, for exact cleanup only."""
    return _legacy_relative_command(host, script)


def _current_command(host: Any, script: str, root: str) -> str:
    if host.id == "claude":
        return f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"'
    path = os.path.join(os.path.abspath(root), host.ownership_root, "hooks", script)
    return f"python3 {_shell_path(path)} --host {shlex.quote(host.id)}"


def command_for(host: Any, script: str, root: str | None = None) -> str:
    """Return an old command fingerprint for compatibility callers.

    The installer never uses this to create a handler.  It exists so old manifests and
    migration tests can describe the command they are removing.
    """
    if root is None:
        return _legacy_relative_command(host, script)[0]
    return _current_command(host, script, root)


def _tokens(command: object) -> list[str]:
    if not isinstance(command, str):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _historical_prefix_script(command: object, host: Any) -> str | None:
    """Classify only a historical command with explicit trailing arguments."""
    actual = _tokens(command)
    if not actual:
        return None
    for script in HOOK_SCRIPTS:
        for form in historical_command_forms(host, script):
            expected = _tokens(form)
            if len(actual) > len(expected) and actual[: len(expected)] == expected:
                return script
    return None


def _command_matches(command: object, host: Any, script: str, root: str | None) -> bool:
    if not isinstance(command, str):
        return False
    if command in historical_command_forms(host, script):
        return True
    if root is None:
        return False
    expected = _tokens(_current_command(host, script, root))
    actual = _tokens(command)
    # A user-modified command remains identifiable for reporting, but only the exact
    # token sequence is eligible for removal.  Extra arguments are a modification, not
    # an exact match; script_for_command classifies that case for preservation/reporting.
    return actual == expected


def exact_script(command: object, host: Any, root: str | None = None) -> str | None:
    for script in HOOK_SCRIPTS:
        if _command_matches(command, host, script, root):
            return script
    return None


def script_for_command(
    command: object,
    host: Any,
    root: str | None = None,
    *,
    allow_absolute_without_root: bool = False,
) -> str | None:
    script = exact_script(command, host, root)
    if script is not None:
        return script
    script = _historical_prefix_script(command, host)
    if script is not None:
        return script
    if not isinstance(command, str) or not allow_absolute_without_root:
        return None
    actual = _tokens(command)
    if len(actual) < 2 or os.path.basename(actual[0]) not in {"python", "python3"}:
        return None
    for script in HOOK_SCRIPTS:
        marker = f"/hooks/{script}"
        if (
            os.path.isabs(actual[1])
            and actual[1].replace("\\", "/").endswith(marker)
            and (
                host.id == "claude"
                or (len(actual) >= 4 and actual[2:4] == ["--host", host.id])
            )
        ):
            return script
    return None


def is_ours(command: object, host: Any | None = None, root: str | None = None) -> bool:
    if host is not None:
        return exact_script(command, host, root) is not None
    for host_id in ADAPTERS:
        candidate = type("Host", (), {"id": host_id, "ownership_root": f".{host_id}"})()
        if exact_script(command, candidate, root) is not None:
            return True
    return False


def _container(settings: dict[str, Any], host: Any) -> dict[str, Any] | None:
    adapter = for_host(host)
    if adapter.nested:
        value = settings.get("hooks")
        return value if isinstance(value, dict) else None
    return settings


def _iter_handlers(
    settings: dict[str, Any], host: Any
) -> Iterable[tuple[str, Any, dict[str, Any], dict[str, Any] | None]]:
    """Yield event, raw entry, handler and grouped wrapper for old layouts.

    v0.5 had two layouts that are not the current native shape: Codex put event lists
    at the JSON root, and Cursor used Claude-style grouped entries.  Keep those paths
    visible to migration diagnostics without making either layout a fresh-install
    contract.
    """
    adapter = for_host(host)
    containers: list[dict[str, Any]] = []
    nested = _container(settings, host)
    if nested is not None:
        containers.append(nested)
    if host.id == "codex":
        # Codex v0.5 could have root-level events even when there is no top-level
        # ``hooks`` object.  If both shapes are present, the identity check below keeps
        # a shared container from being traversed twice.
        containers.append(settings)
    seen_containers: set[int] = set()
    for container in containers:
        if id(container) in seen_containers:
            continue
        seen_containers.add(id(container))
        for event, entries in list(container.items()):
            if not isinstance(event, str) or not isinstance(entries, list):
                continue
            if adapter.style == "direct":
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    if "command" in entry:
                        yield event, entry, entry, None
                    elif host.id == "cursor" and isinstance(entry.get("hooks"), list):
                        # Historical Cursor grouped handlers are candidates for
                        # cleanup only; the current adapter remains direct.
                        for handler in entry["hooks"]:
                            if isinstance(handler, dict) and "command" in handler:
                                yield event, entry, handler, entry
            else:
                for group in entries:
                    if not isinstance(group, dict) or not isinstance(
                        group.get("hooks"), list
                    ):
                        continue
                    for handler in group["hooks"]:
                        if isinstance(handler, dict) and "command" in handler:
                            yield event, group, handler, group


def _expected_event(host: Any, script: str) -> set[str]:
    adapter = for_host(host)
    expected: set[str] = set()
    # Include both the current adapter event and the canonical v0.5 event.  The latter
    # matters for events (notably Cursor Stop) that the current adapter intentionally
    # omits but the historical fingerprint can still contain.
    for event, _matcher, wanted, _timeout in _BASE_SPECS:
        if wanted == script:
            expected.update({event, adapter.event(event)})
    for event, _matcher, wanted, _timeout in adapter.specs():
        if wanted == script:
            expected.update({event, adapter.event(event)})
    if host.id == "codex" and script == "absence_claim_guard.py":
        # The old Codex absence hook lived on PostToolUse as well as PreToolUse.
        expected.update({"PostToolUse", "PreToolUse"})
    return expected


def _manifest_match(
    event: str,
    handler: dict[str, Any],
    wrapper: dict[str, Any] | None,
    script: str,
    records: Iterable[dict[str, Any]],
) -> bool:
    """Match a complete manifest-owned handler, including its effective group shape."""
    actual_matcher = handler.get("matcher", wrapper.get("matcher") if wrapper else None)
    actual_wrapper = (
        {key: copy.deepcopy(value) for key, value in wrapper.items() if key != "hooks"}
        if wrapper is not None
        else None
    )

    for record in records:
        if not isinstance(record, dict):
            continue
        # Every identifying field is part of the ownership proof.  In particular, a
        # matching inner definition is not enough when its surrounding event/group was
        # edited by the user.
        if (
            record.get("event") != event
            or record.get("script") != script
            or record.get("command") != handler.get("command")
            or record.get("timeout") != handler.get("timeout")
            or "definition" not in record
            or not isinstance(record.get("definition"), dict)
            or record["definition"] != handler
        ):
            continue
        if "matcher" not in record and "effective_matcher" not in record:
            continue
        expected_matcher = record.get("effective_matcher", record.get("matcher"))
        if expected_matcher != actual_matcher:
            continue
        if "matcher" in record and record.get("matcher") != actual_matcher:
            continue
        if wrapper is not None and ("matcher" in record or "group_matcher" in record):
            expected_group_matcher = record.get("group_matcher", record.get("matcher"))
            if wrapper.get("matcher") != expected_group_matcher:
                continue

        # Newer records may retain non-handler group metadata.  Compare it without the
        # mutable ``hooks`` list so a foreign sibling cannot make an owned handler look
        # like a different group (or vice versa).  The matcher above remains checked
        # even for older records that have no metadata field.
        for metadata_key in ("wrapper", "wrapper_metadata", "group", "group_metadata"):
            if metadata_key not in record:
                continue
            expected_wrapper = record.get(metadata_key)
            if isinstance(expected_wrapper, dict):
                expected_wrapper = {
                    key: copy.deepcopy(value)
                    for key, value in expected_wrapper.items()
                    if key != "hooks"
                }
            if expected_wrapper != actual_wrapper:
                break
        else:
            for matcher_key in ("wrapper_matcher", "group_matcher"):
                if matcher_key in record and record.get(matcher_key) != actual_matcher:
                    break
            else:
                return True
    return False


def _legacy_exact_shape(  # noqa: PLR0911
    event: str,
    handler: dict[str, Any],
    wrapper: dict[str, Any] | None,
    host: Any,
    script: str,
) -> bool:
    """Recognize a complete old handler definition, not a script substring."""
    command = handler.get("command")
    if not isinstance(command, str):
        return False
    if command not in historical_command_forms(host, script):
        return False
    timeout = {item[2]: item[3] for item in _BASE_SPECS}.get(script)
    if handler.get("timeout") != timeout:
        return False

    write_script = script in {"bib_provenance_guard.py", "absence_claim_guard.py"}
    inner_matcher = handler.get("matcher")
    if write_script and inner_matcher is not None:
        if not legacy_write_matcher_matches(host, inner_matcher):
            return False
    elif not write_script and "matcher" in handler:
        return False

    if wrapper is None:
        # Direct entries were introduced by the old Cursor adapter; command, timeout,
        # and an optional write matcher are the complete native definition.
        if any(key not in {"command", "timeout", "matcher"} for key in handler):
            return False
        expected_events = _expected_event(host, script)
        return event in expected_events

    if handler.get("type") != "command":
        return False
    if any(
        key not in {"type", "command", "timeout", "matcher"}
        and not (host.id == "claude" and key == "if")
        for key in handler
    ):
        return False
    if write_script:
        matcher = wrapper.get("matcher")
        if not legacy_write_matcher_matches(host, matcher):
            return False
    if host.id == "claude" and script in _CLAUDE_CONDITIONS:
        condition = handler.get("if")
        if condition not in _CLAUDE_CONDITIONS[script]:
            return False
    expected_events = _expected_event(host, script)
    if script == "absence_claim_guard.py":
        # Some pre-0.8 adapters placed this handler on PostToolUse; accept that
        # historical location only after the complete legacy fingerprint matched.
        expected_events.update({"PostToolUse", "postToolUse"})
    return event in expected_events


def _remove_from_group(group: dict[str, Any], keep: list[Any]) -> dict[str, Any] | None:
    if keep:
        result = copy.deepcopy(group)
        result["hooks"] = keep
        return result
    if any(key not in {"hooks", "matcher"} for key in group):
        result = copy.deepcopy(group)
        result["hooks"] = []
        return result
    return None


def _migrate_cursor_grouped(settings: dict[str, Any], host: Any, root: str | None) -> None:
    """Convert proven v0.5 Cursor groups to native direct entries."""
    container = _container(settings, host)
    if not isinstance(container, dict):
        return
    adapter = for_host(host)
    preserved_metadata: list[dict[str, Any]] = []

    def historical_script(
        event: str, handler: dict[str, Any], wrapper: dict[str, Any]
    ) -> str | None:
        command = handler.get("command")
        for script in HOOK_SCRIPTS:
            if command not in historical_command_forms(host, script):
                continue
            if _legacy_exact_shape(event, handler, wrapper, host, script):
                return script
        return None

    def convert(event: str, entries: object) -> list[Any]:
        if not isinstance(entries, list):
            return []
        converted: list[Any] = []
        for raw in entries:
            if not isinstance(raw, dict) or not isinstance(raw.get("hooks"), list):
                converted.append(copy.deepcopy(raw))
                continue
            group_metadata = {
                key: copy.deepcopy(value)
                for key, value in raw.items()
                if key not in {"hooks", "matcher", "type"}
            }
            if group_metadata:
                preserved_metadata.append({"event": event, **group_metadata})
            matcher = raw.get("matcher")
            for hook in raw["hooks"]:
                if not isinstance(hook, dict):
                    converted.append(copy.deepcopy(hook))
                    continue
                if historical_script(event, hook, raw) is not None:
                    continue
                native = copy.deepcopy(hook)
                native.pop("type", None)
                if matcher is not None and "matcher" not in native:
                    native["matcher"] = copy.deepcopy(matcher)
                converted.append(native)
        return converted

    # Cursor's old grouped adapter used canonical event names in some releases and
    # native camelCase names in others.  Merge both spellings before directifying every
    # grouped event, including foreign/custom events not emitted by ARS.
    for canonical_event, _matcher, _script, _timeout in _BASE_SPECS:
        destination = adapter.event(canonical_event)
        if destination == canonical_event or canonical_event not in container:
            continue
        source = container.get(canonical_event)
        existing = container.get(destination)
        if isinstance(source, list) and isinstance(existing, list):
            container[destination] = copy.deepcopy(source) + copy.deepcopy(existing)
            container.pop(canonical_event, None)
        elif destination not in container:
            container[destination] = copy.deepcopy(source)
            container.pop(canonical_event, None)

    for event, entries in list(container.items()):
        if not isinstance(entries, list) or not entries:
            continue
        converted = convert(event, entries)
        if converted:
            container[event] = converted
        else:
            container.pop(event, None)

    if preserved_metadata:
        key = "_ars_legacy_cursor_group_metadata"
        if key not in settings:
            settings[key] = preserved_metadata
        else:
            suffix = 1
            while f"{key}_{suffix}" in settings:
                suffix += 1
            settings[f"{key}_{suffix}"] = preserved_metadata


def cleanup(
    settings: dict[str, Any],
    host: Any,
    *,
    root: str | None = None,
    owned_records: Iterable[dict[str, Any]] | None = None,
    allow_legacy: bool = False,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Remove exact old handlers and return ``(settings, removed, modified)``.

    A command that looks like an ARS hook but differs from its manifest/legacy definition
    is reported as modified and left in place.  Unknown commands, groups, and config keys
    are copied untouched.  Both the historical Codex root layout and Cursor grouped
    layout are traversed here because this function is the migration boundary.
    """
    result = copy.deepcopy(settings)
    removed: list[str] = []
    modified: list[str] = []
    adapter = for_host(host)
    migrate_cursor_grouped = _legacy_grouped_ownership_provened(
        result, host, root, owned_records, allow_legacy
    )
    if migrate_cursor_grouped:
        _migrate_cursor_grouped(result, host, root)
    nested = _container(result, host)
    containers: list[dict[str, Any]] = []
    if nested is not None:
        containers.append(nested)
    if host.id == "codex":
        containers.append(result)
    seen: set[int] = set()
    records = list(owned_records) if owned_records is not None else None

    def inspect(
        event: str, handler: dict[str, Any], wrapper: dict[str, Any] | None
    ) -> tuple[str | None, bool]:
        script = exact_script(handler.get("command"), host, root)
        if script is None:
            script = script_for_command(
                handler.get("command"),
                host,
                root,
                allow_absolute_without_root=True,
            )
        if script is None:
            return None, False
        exact = (
            records is not None
            and _manifest_match(event, handler, wrapper, script, records)
        ) or (
            records is None
            and allow_legacy
            and _legacy_exact_shape(event, handler, wrapper, host, script)
        )
        return script, exact

    for container in containers:
        if id(container) in seen:
            continue
        seen.add(id(container))
        for event, raw_entries in list(container.items()):
            if not isinstance(raw_entries, list):
                continue
            new_entries: list[Any] = []
            for entry in raw_entries:
                is_direct = (
                    adapter.style == "direct"
                    and isinstance(entry, dict)
                    and "command" in entry
                )
                is_grouped = (
                    isinstance(entry, dict)
                    and isinstance(entry.get("hooks"), list)
                    and (
                        adapter.style != "direct"
                        or (host.id == "cursor" and not migrate_cursor_grouped)
                    )
                )
                if is_direct:
                    script, exact = inspect(event, entry, None)
                    if script is None:
                        new_entries.append(copy.deepcopy(entry))
                    elif exact:
                        removed.append(script)
                    else:
                        modified.append(script)
                        new_entries.append(copy.deepcopy(entry))
                    continue
                if not is_grouped:
                    new_entries.append(copy.deepcopy(entry))
                    continue

                keep: list[Any] = []
                for handler in entry["hooks"]:
                    if not isinstance(handler, dict):
                        keep.append(copy.deepcopy(handler))
                        continue
                    script, exact = inspect(event, handler, entry)
                    if script is None:
                        keep.append(copy.deepcopy(handler))
                    elif exact:
                        removed.append(script)
                    else:
                        modified.append(script)
                        keep.append(copy.deepcopy(handler))
                retained = _remove_from_group(entry, keep)
                if retained is not None:
                    new_entries.append(retained)
            if new_entries:
                container[event] = new_entries
            elif raw_entries:
                container.pop(event, None)
            else:
                # An empty foreign event list is not an ARS handler and must remain
                # represented in the host config.
                container[event] = copy.deepcopy(raw_entries)

    # Empty hooks objects are deliberately retained: they may have been supplied by a
    # foreign host configuration and their shape is not package ownership evidence.
    return result, sorted(set(removed)), sorted(set(modified))


def merge(  # noqa: PLR0913, PLR0917
    settings: dict[str, Any],
    uninstall: bool,
    host: Any,
    root: str | None = None,
    owned_records: list[dict[str, Any]] | None = None,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    """Compatibility wrapper: cleanup only; never add a desired handler."""
    if not uninstall:
        return copy.deepcopy(settings)
    cleaned, _removed, _modified = cleanup(
        settings,
        host,
        root=root,
        owned_records=owned_records,
        allow_legacy=allow_legacy,
    )
    return cleaned


def strip_ours(  # noqa: PLR0913
    entries: Any,
    host: Any,
    owned_records: Iterable[dict[str, Any]] | None = None,
    *,
    root: str | None = None,
    allow_legacy: bool = False,
    event: str | None = None,
) -> list[Any]:
    """Legacy list helper retained for callers that clean one event list."""
    if not isinstance(entries, list):
        return []
    wrapper = {"hooks": entries}
    settings = {"hooks": {event or "PreToolUse": wrapper}}
    cleaned, _removed, _modified = cleanup(
        settings, host, root=root, owned_records=owned_records, allow_legacy=allow_legacy
    )
    value = cleaned.get("hooks", {}).get(event or "PreToolUse", {})
    return (
        value.get("hooks", [])
        if isinstance(value, dict)
        else value
        if isinstance(value, list)
        else []
    )


def handler_records(
    settings: dict[str, Any], host: Any, root: str | None = None
) -> list[dict[str, Any]]:
    """Describe exact old generated handlers for migration diagnostics."""
    records: list[dict[str, Any]] = []
    for event, _wrapper_or_entry, handler, wrapper in _iter_handlers(settings, host):
        script = exact_script(handler.get("command"), host, root)
        if script is None:
            continue
        record: dict[str, Any] = {
            "event": event,
            "script": script,
            "command": handler.get("command"),
            "matcher": handler.get("matcher", wrapper.get("matcher") if wrapper else None),
            "timeout": handler.get("timeout"),
            "definition": copy.deepcopy(handler),
        }
        if wrapper is not None:
            record["wrapper"] = {
                key: copy.deepcopy(value)
                for key, value in wrapper.items()
                if key != "hooks"
            }
        records.append(record)
    return records


def all_config_commands(settings: object) -> list[str]:
    out: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            command = value.get("command")
            if isinstance(command, str):
                out.append(command)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(settings)
    return out


def validate_config(settings: object, host: Any, root: str | None = None) -> list[str]:
    """Validate only that an existing JSON value is an object.

    Runtime hook shape is intentionally no longer a package contract.  This helper is
    retained for callers inspecting old configs and never creates or requires handlers.
    """
    return [] if isinstance(settings, dict) else ["config is not a JSON object"]


def caveat(host: Any) -> str:
    return (
        "runtime governance hooks are not installed; invoke research skills and "
        "checks explicitly"
    )
