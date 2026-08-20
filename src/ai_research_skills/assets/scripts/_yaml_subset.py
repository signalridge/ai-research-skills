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
    block: bool = False


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


@dataclass(frozen=True)
class _BlockHeader:
    """A parsed `|`/`>` header with its chomping and explicit indentation indicators."""

    style: str
    chomp: str = ""
    indent: int | None = None


_BLOCK_HEADER_RE = re.compile(r"([|>])([-+0-9]*)$")


def _block_header(text: str) -> _BlockHeader | None:
    """Parse a block scalar header such as `|`, `>-`, `|+` or `|2-`.

    Chomping (`-` strip, `+` keep) and an explicit indentation digit may appear in either
    order, which is what hand-written YAML uses far more often than a bare `|`.
    """
    value = text.strip()
    match = _BLOCK_HEADER_RE.search(value)
    if match is None:
        return None
    prefix = value[: match.start()].rstrip()
    if prefix and prefix != "-" and not prefix.endswith(":"):
        return None
    chomp = ""
    indent: int | None = None
    for char in match.group(2):
        if char in "-+":
            if chomp:
                return None
            chomp = char
        elif char in "123456789":
            if indent is not None:
                return None
            indent = int(char)
        else:  # `0` is not a legal indentation indicator.
            return None
    return _BlockHeader(match.group(1), chomp, indent)


def _bare_block_header(text: str | None) -> _BlockHeader | None:
    """Parse a header standing alone as a value, so `- note: |` stays a compact mapping."""
    if text is None:
        return None
    value = text.strip()
    if not value or value[0] not in "|>":
        return None
    return _block_header(value)


def _flow_start(text: str) -> int | None:
    """Return the offset of a value that actually opens a flow collection."""
    leading = len(text) - len(text.lstrip())
    stripped = text[leading:]
    if stripped.startswith(("[", "{")):
        return leading
    if stripped.startswith("- "):
        remainder = stripped[2:].lstrip()
        if remainder.startswith(("[", "{")):
            return text.index(remainder, leading + 2)
    colon = _find_block_colon(text)
    if colon >= 0:
        value = text[colon + 1 :]
        value_leading = len(value) - len(value.lstrip())
        if value[value_leading:].startswith(("[", "{")):
            return colon + 1 + value_leading
    return None


class _Fragment:
    """One logical line assembled from physical lines, reading each character once.

    Comment stripping and the quote/flow-depth scan used to be re-run over the whole
    joined fragment after *every* continuation line, so a flow collection or quoted
    scalar spread over N lines — or a single unclosed quote anywhere in a large file —
    cost O(N^2) to read.  All of that state depends only on the prefix, so it carries
    forward across appends instead.

    The one prefix-sensitive value is the flow origin, which `_flow_start` derives from
    the fragment's first block-mapping colon.  It is resolved with a single pass the
    first time the fragment is not sitting inside a quote, which is also the first moment
    the old code could have reached a different answer: while a quote is open the depth
    is unused (the loop continues on the quote alone), and once the origin is found the
    colon that fixed it can no longer move.
    """

    __slots__ = (
        "_depth",
        "_escaped",
        "_flow_start",
        "_out",
        "_previous",
        "_quote",
        "_resolved",
        "_started",
        "_within_comment",
    )

    def __init__(self) -> None:
        self._out: list[str] = []
        self._quote: str | None = None
        self._escaped = False
        self._within_comment = False
        self._previous = ""  # previous *input* character, for YAML's ` #` comment rule
        self._depth = 0
        self._flow_start: int | None = None
        self._resolved = False
        self._started = False

    def add(self, part: str) -> None:
        """Append one physical line, joined the way the old `"\\n".join(...)` did."""
        if self._started:
            self._feed("\n")
        self._started = True
        for char in part.strip():
            self._feed(char)
        if self._quote is None and not self._resolved:
            self._resolve()

    def is_open(self) -> bool:
        """Whether the fragment still needs a continuation line."""
        return self._quote is not None or self._depth > 0

    def text(self) -> str:
        return "".join(self._out).rstrip()

    def _feed(self, char: str) -> None:
        previous = self._previous
        self._previous = char
        if self._within_comment:
            if char == "\n":
                self._within_comment = False
                self._emit(" ")
            return
        if char == "#" and self._quote is None and (not previous or previous.isspace()):
            self._within_comment = True
            return
        self._emit(" " if char == "\n" else char)
        if self._escaped:
            self._escaped = False
        elif self._quote == "'":
            # A doubled `''` closes and immediately reopens, which leaves the same state
            # and the same two characters as the old lookahead did.
            if char == "'":
                self._quote = None
        elif self._quote == '"':
            if char == "\\":
                self._escaped = True
            elif char == '"':
                self._quote = None
        elif char in "'\"":
            self._quote = char

    def _emit(self, char: str) -> None:
        if (
            self._resolved
            and self._flow_start is not None
            and self._quote is None
            and len(self._out) >= self._flow_start
        ):
            if char in "[{":
                self._depth += 1
            elif char in "]}":
                self._depth -= 1
                if self._depth < 0:
                    raise YAMLSubsetError("unbalanced flow collection")
        self._out.append(char)

    def _resolve(self) -> None:
        text = "".join(self._out)
        self._flow_start = _flow_start(text)
        self._resolved = True
        if self._flow_start is None:
            self._depth = 0
            return
        depth = 0
        for index, char, before, _after in _scan(text):
            if before is not None or index < self._flow_start:
                continue
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
                if depth < 0:
                    raise YAMLSubsetError("unbalanced flow collection")
        self._depth = depth


def _logical_lines(text: str) -> list[_Line]:
    """Join quoted/flow fragments while preserving declared block scalar content.

    Block content is tagged on the logical line so document/tag checks do not inspect
    literal text as YAML structure.  A shallow line is still handed to the block parser;
    that parser decides whether it is a valid outer mapping/sequence sibling.
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
        builder = _Fragment()
        builder.add(raw.strip())
        index += 1
        while builder.is_open():
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
            builder.add(continuation.strip())
            index += 1
        fragment = builder.text()
        if not fragment:
            continue
        lines.append(_Line(start_number, indent, fragment.strip()))
        marker = _block_header(fragment)
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
                lines.append(_Line(index + 1, indent + 1, "", True))
                index += 1
                continue
            block_indent = len(block_raw) - len(block_raw.lstrip(" "))
            if block_indent <= indent:
                break
            lines.append(
                _Line(index + 1, block_indent, block_raw[block_indent:].rstrip(), True)
            )
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
        if char in "[{":
            depth += 1
        elif char in "]}":
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
    if value.startswith(("@", "`")):
        raise YAMLSubsetError(
            f"reserved YAML indicator cannot start a plain scalar: {value}"
        )
    if value[0] in "]},%|>":
        raise YAMLSubsetError(
            f"reserved YAML indicator cannot start a plain scalar: {value}"
        )
    if value[0] in "-?:" and (len(value) == 1 or value[1].isspace()):
        raise YAMLSubsetError(
            f"reserved YAML indicator cannot start a plain scalar: {value}"
        )
    if value.startswith("["):
        if not value.endswith("]"):
            raise YAMLSubsetError("unclosed flow sequence")
        items: list[Any] = []
        for part in _split_flow(value[1:-1]):
            # `[foo: bar]` is a single-pair mapping to YAML, not the string "foo: bar".
            # Reading it as a scalar is the one divergence shape that survives the
            # bundled-parser-is-authoritative rule: both parsers accept the file, and only
            # the bundled value reaches the schema.  Refuse it and ask for explicit braces
            # or quotes instead of guessing.
            if not part.startswith(("[", "{", "'", '"')) and _find_block_colon(part) >= 0:
                raise YAMLSubsetError(
                    "flow sequence item looks like a mapping; write it as "
                    f"{{{part}}} or quote it — {part}"
                )
            items.append(scalar(part))
        return items
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
            item_value = item[colon + 1 :]
            # A second `: ` in the value (`{a: b: c}`) is a nested-mapping construct YAML
            # rejects outright; keeping it as a plain scalar would accept a file PyYAML
            # refuses, which is exactly the disagreement this parser must not create.
            if (
                not item_value.lstrip().startswith(("[", "{", "'", '"'))
                and _find_block_colon(item_value) >= 0
            ):
                raise YAMLSubsetError(f"flow mapping value contains a second ':' — {item}")
            result[key] = scalar(item_value)
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
    if lowered in ("true", "yes", "on", "false", "no", "off"):
        return lowered in ("true", "yes", "on")
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
    # A second `key: value` delimiter inside a plain value is a nested mapping YAML does
    # not allow inline — PyYAML raises "mapping values are not allowed here".  Reading it
    # as the plain scalar "a: b" would accept a file the native parser refuses, making a
    # workspace's validity depend on whether PyYAML happens to be installed.  Flow
    # collections and quoted scalars carry their own delimiters and are unaffected.
    if (
        value
        and not value.startswith(("[", "{", "'", '"'))
        and _find_block_colon(value) >= 0
    ):
        raise YAMLSubsetError(
            f"line {number}: mapping values are not allowed here; quote the value or "
            f"use a block scalar — {value}"
        )
    return key, value if value else None


def _is_sequence_entry(text: str) -> bool:
    """Whether a logical line opens a block sequence entry.

    YAML requires whitespace after the indicator, so ``- item`` is a sequence entry while
    ``-item`` is not — the latter is a plain scalar, and PyYAML rejects it in the places
    this parser would otherwise accept it.  Matching on a bare ``"-"`` prefix instead made
    the bundled fallback disagree with PyYAML about whether a workspace file is valid,
    which is the one thing a fallback parser must never do.
    """
    return text == "-" or text.startswith("- ")


def _parse_block(lines: list[_Line], pos: int, indent: int) -> tuple[Any, int]:
    if pos >= len(lines) or lines[pos].indent < indent:
        return None, pos
    is_list = lines[pos].indent == indent and _is_sequence_entry(lines[pos].text)
    if not is_list and lines[pos].indent != indent:
        raise YAMLSubsetError(f"line {lines[pos].number}: unexpected indentation")
    if is_list:
        result: list[Any] = []
        while (
            pos < len(lines)
            and lines[pos].indent == indent
            and _is_sequence_entry(lines[pos].text)
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
            item_header = _bare_block_header(remainder)
            if item_header is not None:
                list_item, pos = _parse_multiline(lines, pos, indent, item_header)
                result.append(list_item)
                continue
            # A list mapping commonly starts `- name: value`; consume following mapping
            # fields at the next indentation level into the same item.
            if not remainder.startswith(("[", "{")) and _find_block_colon(remainder) >= 0:
                key, value_text = _key_value(remainder, line.number)
                # The first key in a compact list mapping starts after the dash and its
                # actual whitespace.  Sibling keys after a block scalar must return to
                # this exact column, not merely somewhere above the scalar content.
                key_indent = (
                    line.indent + 1 + len(line.text[1:]) - len(line.text[1:].lstrip(" "))
                )
                item: dict[str, Any] = {}
                header = _bare_block_header(value_text)
                if header is not None:
                    value, pos = _parse_multiline(lines, pos, key_indent, header)
                elif value_text is None:
                    if pos < len(lines) and lines[pos].indent > key_indent:
                        value, pos = _parse_block(lines, pos, lines[pos].indent)
                    elif (
                        pos < len(lines)
                        and lines[pos].indent == key_indent
                        and _is_sequence_entry(lines[pos].text)
                    ):
                        # The same indentationless block sequence the outer mapping branch
                        # allows, one level in:  - values:\n    - a\n    - b
                        value, pos = _parse_block(lines, pos, key_indent)
                    else:
                        value = None
                else:
                    value = scalar(value_text)
                item[key] = value
                if pos < len(lines) and lines[pos].indent > indent:
                    if lines[pos].indent != key_indent:
                        raise YAMLSubsetError(
                            f"line {lines[pos].number}: list mapping sibling is not aligned"
                        )
                    extra, pos = _parse_block(lines, pos, key_indent)
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
        and not _is_sequence_entry(lines[pos].text)
    ):
        line = lines[pos]
        key, value_text = _key_value(line.text, line.number)
        pos += 1
        header = _bare_block_header(value_text)
        if header is not None:
            value, pos = _parse_multiline(lines, pos, indent, header)
        elif value_text is None:
            if pos < len(lines) and lines[pos].indent > indent:
                value, pos = _parse_block(lines, pos, lines[pos].indent)
            elif (
                pos < len(lines)
                and lines[pos].indent == indent
                and _is_sequence_entry(lines[pos].text)
            ):
                # YAML lets a block sequence sit at its parent key's indent, and hand-written
                # protocol files commonly do:  scope:\n  in:\n  - multi-hop QA
                value, pos = _parse_block(lines, pos, indent)
            else:
                value = None
        else:
            value = scalar(value_text)
        result_map[key] = value
    return result_map, pos


def _chomp(body: str, trailing_blanks: int, chomp: str) -> str:
    """Apply YAML's clip (default), strip (`-`) or keep (`+`) trailing-newline rule."""
    if chomp == "-":
        return body
    if chomp == "+":
        return body + "\n" * (trailing_blanks + 1) if body else "\n" * trailing_blanks
    return body + "\n" if body else ""


def _parse_multiline(
    lines: list[_Line], pos: int, parent_indent: int, marker: _BlockHeader
) -> tuple[str, int]:
    raw_parts: list[tuple[int, str]] = []
    # An explicit indentation indicator counts from the parent node, and it fixes the
    # content column up front so leading spaces on the first line stay content.
    content_indent: int | None = (
        parent_indent + marker.indent if marker.indent is not None else None
    )
    while pos < len(lines) and (
        lines[pos].indent > parent_indent
        # A blank line inside a block scalar carries no indentation of its own — YAML
        # measures it against the content, not the node.  `_logical_lines` can only give
        # it a synthetic column relative to the *header* line, which sits left of a
        # compact `- key: |` mapping's real key column, so comparing it against
        # `parent_indent` truncated the block one line early and left the blank behind to
        # collide with the sibling-alignment check.
        or (lines[pos].block and not lines[pos].text)
    ):
        line = lines[pos]
        if line.text and content_indent is None:
            # YAML's implicit block indent is fixed by the first non-empty content line.
            content_indent = line.indent
        elif (
            line.text
            and content_indent is not None
            and parent_indent < line.indent < content_indent
        ):
            # A shallower mapping/sequence line can belong to the containing structure
            # (for example `other: value` after a list item's scalar).  Anything else is
            # an unassignable indentation error rather than silently becoming scalar text.
            if _is_sequence_entry(line.text) or _find_block_colon(line.text) >= 0:
                break
            raise YAMLSubsetError(
                f"line {line.number}: block scalar indentation is less than its content indent"
            )
        raw_parts.append((line.indent, line.text))
        pos += 1
    if content_indent is None:
        # No content line ever arrived, so every consumed line was blank.  They are still
        # trailing breaks as far as chomping is concerned: `|+` keeps them, and reporting
        # zero here dropped them and made an all-blank kept block come back as "".
        return _chomp("", len(raw_parts), marker.chomp), pos
    parts = [
        (" " * max(0, indent - content_indent) + text if text else "")
        for indent, text in raw_parts
    ]
    more_indented = [indent > content_indent for indent, text in raw_parts]
    trailing_blanks = 0
    while parts and not parts[-1]:
        parts.pop()
        more_indented.pop()
        trailing_blanks += 1
    if not parts:
        return _chomp("", trailing_blanks, marker.chomp), pos
    if marker.style == "|":
        return _chomp("\n".join(parts), trailing_blanks, marker.chomp), pos
    folded = ""
    blank_count = 0
    started = False
    previous_more_indented = False
    for index, part in enumerate(parts):
        if not part:
            blank_count += 1
            continue
        if not started:
            # Blank lines *opening* a folded scalar are literal newlines with nothing to
            # fold into; seeding the accumulator with `parts[0]` instead turned them into
            # the fold separator and produced a leading space where YAML wants "\n".
            folded = "\n" * blank_count
            started = True
        elif more_indented[index] or previous_more_indented:
            # A run of breaks touching a more-indented line is never folded, so all
            # `blank_count + 1` of them stay literal.  Comparing against `parts[index - 1]`
            # here read the *blank* line's synthetic indent instead of the previous content
            # line's, and dropped one newline from every blank-then-indented transition.
            folded += "\n" * (blank_count + 1)
        elif blank_count:
            # Between two normal lines, n+1 breaks fold down to n newlines...
            folded += "\n" * blank_count
        else:
            # ...and a lone break folds to a single space.
            folded += " "
        blank_count = 0
        previous_more_indented = more_indented[index]
        folded += part
    return _chomp(folded, trailing_blanks, marker.chomp), pos


def loads(text: str) -> Any:
    if not isinstance(text, str):
        raise YAMLSubsetError("YAML input must be text")
    # A UTF-8 BOM is an encoding marker, not content.  Left in place it silently became
    # part of the first key, so a BOM-prefixed file parsed into `﻿topic` and every
    # schema check for `topic` quietly looked at a key that was not there.
    if text.startswith("﻿"):
        text = text[1:]
    lines = _logical_lines(text)
    for line in lines:
        if not line.block and (
            line.text in ("---", "...") or line.text.startswith(("%YAML", "!"))
        ):
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
