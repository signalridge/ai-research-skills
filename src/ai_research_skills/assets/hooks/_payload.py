"""Shared, host-neutral parsing and stdout dialects for shipped hooks.

The command line selects one host profile (Claude is the backwards-compatible default):
``--host codex|cursor|pi``.  A hook must never emit a union of host dialects.  Claude,
Codex and the Pi compatibility extension use the official ``hookSpecificOutput`` shape;
Cursor uses its flat response fields.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any

HOST_PROFILES = frozenset({"claude", "codex", "cursor", "pi"})
_PROFILE = "claude"


def _argv_profile() -> str:
    for index, value in enumerate(sys.argv):
        if value == "--host" and index + 1 < len(sys.argv):
            candidate = sys.argv[index + 1].strip().lower()
            return candidate if candidate in HOST_PROFILES else "claude"
        if value.startswith("--host="):
            candidate = value.partition("=")[2].strip().lower()
            return candidate if candidate in HOST_PROFILES else "claude"
    return "claude"


_PROFILE = _argv_profile()


def set_host_profile(host: str) -> None:
    """Set the profile for in-process tests; installed hooks use ``--host``."""
    global _PROFILE  # noqa: PLW0603
    candidate = host.strip().lower()
    if candidate not in HOST_PROFILES:
        raise ValueError(f"unknown hook host profile: {host}")
    _PROFILE = candidate


def host_profile() -> str:
    return _PROFILE


@dataclass(frozen=True)
class WriteOperation:
    """One file mutation represented by a hook payload."""

    path: str
    text: str = ""
    kind: str = "write"
    old_path: str | None = None


_PATCH_MARKER = re.compile(r"^\*\*\*\s+(Add|Update|Delete)\s+File:\s*(.+?)\s*$")
_MOVE_MARKER = re.compile(r"^\*\*\*\s+Move\s+to:\s*(.+?)\s*$")


def _patch_operations(patch: str) -> list[WriteOperation]:
    """Parse Add/Update/Delete/Move-to blocks without sharing added text."""
    operations: list[WriteOperation] = []
    current_kind: str | None = None
    current_path: str | None = None
    current_old_path: str | None = None
    added: list[str] = []

    def finish() -> None:
        nonlocal current_kind, current_path, current_old_path, added
        if current_kind is None or current_path is None:
            return
        operations.append(
            WriteOperation(
                path=current_path,
                text="\n".join(added),
                kind=current_kind.lower(),
                old_path=current_old_path,
            )
        )
        current_kind = None
        current_path = None
        current_old_path = None
        added = []

    for raw in patch.splitlines():
        marker = _PATCH_MARKER.match(raw)
        if marker:
            finish()
            current_kind = marker.group(1)
            current_path = marker.group(2).strip()
            continue
        move = _MOVE_MARKER.match(raw)
        if move and current_path is not None:
            # A move follows the source Update/Add block.  The destination is the path
            # a guard must inspect; retain the source for old-file reconstruction.
            current_old_path = current_path
            current_path = move.group(1).strip()
            current_kind = "Move"
            continue
        if current_kind is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added.append(raw[1:])
        # Context/deletion lines are not new text.  In particular, do not carry a
        # previous file's additions into the next operation.
    finish()
    return operations


def _direct_operations(tool_input: dict[str, Any]) -> list[WriteOperation]:
    path_value = tool_input.get("file_path")
    if path_value is None:
        path_value = tool_input.get("path")
    if not isinstance(path_value, str) or not path_value:
        return []

    old_path = tool_input.get("old_path")
    old_path = old_path if isinstance(old_path, str) and old_path else None
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        texts: list[str] = []
        for item in edits:
            if isinstance(item, dict):
                new_text = item.get("newText")
                if isinstance(new_text, str):
                    texts.append(new_text)
        if texts:
            return [
                WriteOperation(
                    path=path_value,
                    text="\n".join(texts),
                    kind="move" if old_path else "edit",
                    old_path=old_path,
                )
            ]

    for key, kind in (("content", "write"), ("new_string", "edit"), ("newText", "edit")):
        value = tool_input.get(key)
        if isinstance(value, str):
            return [
                WriteOperation(
                    path=path_value,
                    text=value,
                    kind="move" if old_path else kind,
                    old_path=old_path,
                )
            ]
    return [
        WriteOperation(
            path=path_value,
            kind="move" if old_path else "edit",
            old_path=old_path,
        )
    ]


def _added_lines(patch: str) -> str:
    """Compatibility view of all patch additions after per-file parsing."""
    return "\n".join(
        operation.text for operation in _patch_operations(patch) if operation.text
    )


def operations(tool_input: object) -> list[WriteOperation]:
    """Return every file mutation in a tool input."""
    if not isinstance(tool_input, dict):
        return []
    command = tool_input.get("command")
    if isinstance(command, str) and command:
        parsed = _patch_operations(command)
        if parsed:
            return parsed
    return _direct_operations(tool_input)


def targets(tool_input: dict[str, Any]) -> list[str]:
    """Backward-compatible path view; callers should prefer :func:`operations`."""
    return [op.path for op in operations(tool_input)]


def written_text(tool_input: dict[str, Any]) -> str:
    """Backward-compatible text view, joined only after per-file parsing."""
    return "\n".join(op.text for op in operations(tool_input) if op.text)


def deny(reason: str) -> dict[str, Any]:
    """Return exactly the selected host's PreToolUse deny schema."""
    if _PROFILE == "cursor":
        return {
            "permission": "deny",
            "user_message": reason,
            "agent_message": reason,
        }
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def block(reason: str) -> dict[str, Any]:
    """Return a post-write block in the selected host's schema.

    Codex has no safe PostToolUse permission response.  Its absence guard is installed
    on PreToolUse, but this defensive branch still emits no Cursor/Claude top-level keys
    if a stale config invokes it.
    """
    if _PROFILE == "cursor":
        return {
            "permission": "deny",
            "user_message": reason,
            "agent_message": reason,
        }
    if _PROFILE == "codex":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    return {"decision": "block", "reason": reason}


def session_context(event: str, message: str) -> dict[str, Any]:
    """Format advisory SessionStart/Stop context without mixing host dialects."""
    if _PROFILE == "cursor":
        return {"additional_context": message}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def stop_warning(message: str) -> dict[str, Any]:
    """Format supported stop advisories; Cursor omits Stop entirely."""
    if _PROFILE == "cursor":
        # Cursor's stop surface is intentionally not installed; keep a defensive
        # invocation silent rather than accidentally requesting a follow-up loop.
        return {}
    if _PROFILE == "codex":
        # Codex Stop accepts common output fields, not a PreToolUse hook-specific
        # object.  The adapter keeps this event only because this is its real schema.
        return {"systemMessage": message, "suppressOutput": True}
    return {"systemMessage": message, "suppressOutput": True}
