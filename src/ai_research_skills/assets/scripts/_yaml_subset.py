"""Small YAML subset used by the shipped validator.

It supports the YAML profile ARS writes: indentation-based mappings and lists, quoted and
plain scalars, JSON-like flow arrays/objects (including continuations), and literal/folded
block scalars.  Anchors, tags, aliases and multiple documents are rejected explicitly.
It is not a general YAML parser.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


class YAMLSubsetError(ValueError):
    pass


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    text: str


def _scan(text: str) -> Iterator[tuple[int, str, str | None, str | None]]:
    """Yield characters with YAML quote state before and after each character."""
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        before = quote
        if escaped:
            escaped = False
        elif quote == "'":
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    yield index, char, before, quote
                    index += 2
                    continue
                quote = None
        elif quote == '"':
            if char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif char in "'\"":
            quote = char
        yield index, char, before, quote
        index += 1


def _strip_comment(text: str) -> str:
    for i, char, before, _after in _scan(text):
        if char == "#" and before is None and (i == 0 or text[i - 1].isspace()):
            return text[:i].rstrip()
    return text.rstrip()


def _strip_fragment_comments(parts: list[str]) -> str:
    """Strip comments after joining a quoted/flow fragment across lines."""
    text = "\n".join(part.strip() for part in parts)
    out: list[str] = []
    quote: str | None = None
    escaped = False
    comment = False
    index = 0
    while index < len(text):
        char = text[index]
        if comment:
            if char == "\n":
                comment = False
                out.append(" ")
            index += 1
            continue
        before = quote
        if char == "#" and before is None and (index == 0 or text[index - 1].isspace()):
            comment = True
            index += 1
            continue
        out.append(" " if char == "\n" else char)
        if escaped:
            escaped = False
        elif quote == "'":
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    out.append("'")
                    index += 2
                    continue
                quote = None
        elif quote == '"':
            if char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif char in "'\"":
            quote = char
        index += 1
    return "".join(out).rstrip()


def _block_marker(text: str) -> str | None:
    value = text.strip()
    if not value.endswith(("|", ">")):
        return None
    prefix = value[:-1].rstrip()
    if not prefix or prefix == "-" or prefix.endswith(":"):
        return value[-1]
    return None


def _fragment_state(text: str) -> tuple[str | None, int]:
    """Return open quote and flow depth for one logical YAML fragment."""
    quote: str | None = None
    depth = 0
    for _i, char, before, after in _scan(text):
        quote = after
        if before is not None:
            continue
        if char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
            if depth < 0:
                raise YAMLSubsetError("unbalanced flow collection")
    return quote, depth


def _logical_lines(text: str) -> list[_Line]:
    """Join quoted/flow fragments while preserving declared block scalar content.

    The supported profile uses multiline quoted/flow values and bare ``|``/``>``
    scalars.  Comments must be evaluated against the complete quoted fragment: a
    continuation line can still be inside a quote opened on the previous line.
    Block scalar lines are kept raw because ``#`` and blank lines are their value.
    """
    physical = text.splitlines()
    lines: list[_Line] = []
    index = 0
    while index < len(physical):
        raw = physical[index]
        leading = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in leading:
            raise YAMLSubsetError(
                f"line {index + 1}: tabs are not supported for indentation"
            )
        if not raw.strip():
            index += 1
            continue
        start_number = index + 1
        indent = len(raw) - len(raw.lstrip(" "))
        parts = [raw.strip()]
        fragment = _strip_fragment_comments(parts)
        index += 1
        quote, depth = _fragment_state(fragment)
        while quote is not None or depth > 0:
            if index >= len(physical):
                raise YAMLSubsetError(
                    f"line {start_number}: unclosed quote or flow collection"
                )
            continuation = physical[index]
            continuation_leading = continuation[
                : len(continuation) - len(continuation.lstrip())
            ]
            if "\t" in continuation_leading:
                raise YAMLSubsetError(
                    f"line {index + 1}: tabs are not supported for indentation"
                )
            parts.append(continuation.strip())
            index += 1
            fragment = _strip_fragment_comments(parts)
            quote, depth = _fragment_state(fragment)
        if not fragment:
            continue
        lines.append(_Line(start_number, indent, fragment.strip()))
        marker = _block_marker(fragment)
        if marker is None:
            continue
        while index < len(physical):
            block_raw = physical[index]
            block_leading = block_raw[: len(block_raw) - len(block_raw.lstrip())]
            if "\t" in block_leading:
                raise YAMLSubsetError(
                    f"line {index + 1}: tabs are not supported for indentation"
                )
            if not block_raw.strip():
                lines.append(_Line(index + 1, indent + 1, ""))
                index += 1
                continue
            block_indent = len(block_raw) - len(block_raw.lstrip(" "))
            if block_indent <= indent:
                break
            lines.append(_Line(index + 1, block_indent, block_raw[block_indent:].rstrip()))
            index += 1
    return lines


def _split_flow(text: str, separator: str = ",") -> list[str]:
    out: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for i, char, before, after in _scan(text):
        quote = after
        if before is not None:
            continue
        if char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
            if depth < 0:
                raise YAMLSubsetError("unbalanced flow collection")
        elif char == separator and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    if quote is not None or depth != 0:
        raise YAMLSubsetError("unbalanced quote or flow collection")
    out.append(text[start:].strip())
    return [part for part in out if part]


def _find_flow_colon(text: str) -> int:
    depth = 0
    for i, char, before, _after in _scan(text):
        if before is not None:
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0:
            return i
    return -1


def _find_block_colon(text: str) -> int:
    """Find a block-mapping delimiter, not a colon inside a plain scalar.

    YAML block mappings require the delimiter colon to be followed by whitespace or the
    end of the line.  Values such as ``W123:cites:1``, URLs and DOIs therefore remain
    strings, while ``name: value`` and ``name:`` still start mappings.
    """
    depth = 0
    for i, char, before, _after in _scan(text):
        if before is not None:
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1].isspace()):
            return i
    return -1


def _single_quoted(value: str) -> str:
    if len(value) < 2 or value[-1] != "'":
        raise YAMLSubsetError(f"invalid quoted scalar: {value}")
    inner = value[1:-1]
    out: list[str] = []
    index = 0
    while index < len(inner):
        char = inner[index]
        if char == "'":
            if index + 1 >= len(inner) or inner[index + 1] != "'":
                raise YAMLSubsetError(f"invalid quoted scalar: {value}")
            out.append("'")
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def scalar(text: str) -> Any:
    value = _strip_comment(text.strip())
    if not value:
        return None
    if value.startswith(("&", "*", "!")):
        raise YAMLSubsetError(f"unsupported YAML anchor, alias or tag: {value}")
    if value.startswith("["):
        if not value.endswith("]"):
            raise YAMLSubsetError("unclosed flow sequence")
        return [scalar(part) for part in _split_flow(value[1:-1])]
    if value.startswith("{"):
        if not value.endswith("}"):
            raise YAMLSubsetError("unclosed flow mapping")
        result: dict[str, Any] = {}
        for item in _split_flow(value[1:-1]):
            colon = _find_flow_colon(item)
            if colon < 0:
                raise YAMLSubsetError(f"flow mapping item lacks ':' — {item}")
            key = scalar(item[:colon])
            if not isinstance(key, str):
                raise YAMLSubsetError("flow mapping keys must be strings")
            result[key] = scalar(item[colon + 1 :])
        return result
    if value[0:1] in ("'", '"'):
        try:
            if value[0] == '"':
                return json.loads(value)
            return _single_quoted(value)
        except (ValueError, SyntaxError, json.JSONDecodeError) as exc:
            raise YAMLSubsetError(f"invalid quoted scalar: {value}") from exc
    lowered = value.lower()
    if lowered in ("null", "~"):
        return None
    if lowered in ("true", "false"):
        return lowered == "true"
    if re.fullmatch(r"[-+]?\d+", value):
        try:
            return int(value)
        except ValueError:
            pass
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?", value):
        try:
            return float(value)
        except ValueError:
            pass
    return value


def _key_value(text: str, number: int) -> tuple[str, str | None]:
    colon = _find_block_colon(text)
    if colon < 0:
        raise YAMLSubsetError(f"line {number}: expected mapping key ':'")
    key = scalar(text[:colon].strip())
    if not isinstance(key, str) or not key:
        raise YAMLSubsetError(f"line {number}: mapping keys must be non-empty strings")
    value = text[colon + 1 :].strip()
    return key, value if value else None


def _parse_block(lines: list[_Line], pos: int, indent: int) -> tuple[Any, int]:
    if pos >= len(lines) or lines[pos].indent < indent:
        return None, pos
    is_list = lines[pos].indent == indent and lines[pos].text.startswith("-")
    if not is_list and lines[pos].indent != indent:
        raise YAMLSubsetError(f"line {lines[pos].number}: unexpected indentation")
    if is_list:
        result: list[Any] = []
        while (
            pos < len(lines)
            and lines[pos].indent == indent
            and lines[pos].text.startswith("-")
        ):
            line = lines[pos]
            remainder = line.text[1:].strip()
            pos += 1
            if not remainder:
                if pos < len(lines) and lines[pos].indent > indent:
                    list_item, pos = _parse_block(lines, pos, lines[pos].indent)
                else:
                    list_item = None
                result.append(list_item)
                continue
            if remainder in ("|", ">"):
                list_item, pos = _parse_multiline(lines, pos, indent, remainder)
                result.append(list_item)
                continue
            # A list mapping commonly starts `- name: value`; consume following mapping
            # fields at the next indentation level into the same item.
            if not remainder.startswith(("[", "{")) and _find_block_colon(remainder) >= 0:
                key, value_text = _key_value(remainder, line.number)
                item: dict[str, Any] = {}
                if value_text in ("|", ">"):
                    value, pos = _parse_multiline(lines, pos, indent, value_text)
                elif value_text is None:
                    if pos < len(lines) and lines[pos].indent > indent:
                        value, pos = _parse_block(lines, pos, lines[pos].indent)
                    else:
                        value = None
                else:
                    value = scalar(value_text)
                item[key] = value
                if pos < len(lines) and lines[pos].indent > indent:
                    extra_indent = lines[pos].indent
                    extra, pos = _parse_block(lines, pos, extra_indent)
                    if not isinstance(extra, dict):
                        raise YAMLSubsetError(
                            f"line {line.number}: list item fields must be a mapping"
                        )
                    item.update(extra)
                result.append(item)
            else:
                result.append(scalar(remainder))
        return result, pos

    result_map: dict[str, Any] = {}
    while (
        pos < len(lines)
        and lines[pos].indent == indent
        and not lines[pos].text.startswith("-")
    ):
        line = lines[pos]
        key, value_text = _key_value(line.text, line.number)
        pos += 1
        if value_text in ("|", ">"):
            value, pos = _parse_multiline(lines, pos, indent, value_text)
        elif value_text is None:
            if pos < len(lines) and lines[pos].indent > indent:
                value, pos = _parse_block(lines, pos, lines[pos].indent)
            else:
                value = None
        else:
            value = scalar(value_text)
        result_map[key] = value
    return result_map, pos


def _parse_multiline(
    lines: list[_Line], pos: int, parent_indent: int, marker: str
) -> tuple[str, int]:
    raw_parts: list[tuple[int, str]] = []
    content_indent: int | None = None
    while pos < len(lines) and lines[pos].indent > parent_indent:
        line = lines[pos]
        if line.text and content_indent is None:
            content_indent = line.indent
        raw_parts.append((line.indent, line.text))
        pos += 1
    if content_indent is None:
        return "", pos
    parts = [
        (" " * max(0, indent - content_indent) + text if text else "")
        for indent, text in raw_parts
    ]
    more_indented = [indent > content_indent for indent, text in raw_parts]
    while parts and not parts[-1]:
        parts.pop()
        more_indented.pop()
    if not parts:
        return "", pos
    if marker == "|":
        return "\n".join(parts) + "\n", pos
    folded = parts[0]
    blank_count = 0
    for index in range(1, len(parts)):
        part = parts[index]
        if not part:
            blank_count += 1
            continue
        if blank_count:
            folded += "\n" * blank_count
            blank_count = 0
        elif more_indented[index] or more_indented[index - 1]:
            folded += "\n"
        else:
            folded += " "
        folded += part
    return folded + "\n", pos


def loads(text: str) -> Any:
    if not isinstance(text, str):
        raise YAMLSubsetError("YAML input must be text")
    lines = _logical_lines(text)
    for line in lines:
        if line.text in ("---", "...") or line.text.startswith(("%YAML", "!")):
            raise YAMLSubsetError(
                f"line {line.number}: multi-document YAML and tags are unsupported"
            )
    if not lines:
        return None
    value, pos = _parse_block(lines, 0, lines[0].indent)
    if pos != len(lines):
        raise YAMLSubsetError(
            f"line {lines[pos].number}: unsupported or inconsistent indentation"
        )
    return value


def safe_load(stream: Any) -> Any:
    if hasattr(stream, "read"):
        return loads(stream.read())
    return loads(str(stream))
