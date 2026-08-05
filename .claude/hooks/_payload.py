"""Shared payload reading for the write-time guards.

Claude Code and Codex use the same hook schema for the deny decision, but not for the
write payload itself. Claude Code sends `tool_input.file_path` plus `content` or
`new_string`. Codex routes file writes through `apply_patch`, whose `tool_input`
carries a `command` holding the patch body instead.

A guard that only reads `file_path` sees nothing on Codex and returns early — silently
not protecting, which is the failure this whole suite exists to prevent. So both shapes
are read here, once, rather than in four places.
"""

import re

# apply_patch bodies name their targets on marker lines:
#   *** Add File: docs/refs.bib
#   *** Update File: .research/survey/x/refs.bib
_PATCH_TARGET = re.compile(
    r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$", re.MULTILINE
)


def targets(tool_input: dict) -> list[str]:
    """Every path this tool call would write. Empty when the payload names none."""
    direct = tool_input.get("file_path")
    if direct:
        return [str(direct)]
    command = tool_input.get("command") or ""
    if isinstance(command, str) and command:
        return _PATCH_TARGET.findall(command)
    return []


def _added_lines(patch: str) -> str:
    """The content an apply_patch body would add, with diff markers removed.

    Added lines arrive prefixed with '+', so a guard matching '^@article{' against the
    raw body finds nothing and lets the write through. Strip the markers here so every
    downstream pattern sees the text as it will land on disk.
    """
    out = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:])
        elif not line.startswith(("-", "@@", "***", "diff ", "--- ")):
            out.append(line)
    return "\n".join(out)


def written_text(tool_input: dict) -> str:
    """The text this call would put on disk, across both hosts' payload shapes."""
    for key in ("content", "new_string"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    command = tool_input.get("command")
    if isinstance(command, str) and command:
        return _added_lines(command)
    return ""
