#!/usr/bin/env python3
"""Explicit, scoped linter for optional ARS research artifacts.

This tool is not a workflow validator. It does not know a required phase or completion
floor, recall recipe, coverage target, saturation rule, or deliverable dependency.  A
researcher may lint any subset of the interoperable files in
``.research/survey/<slug>/``; absent files are reported as absent, not as failures.

Checks are deliberately small and useful:

* parse and schema shape for files that are present;
* duplicate corpus keys/identifiers and duplicate gap/citation keys;
* malformed dates (and future dates as warnings);
* references that point at missing corpus/gap keys when those artifacts are present; and
* explicit provenance where a record or BibTeX entry supplies it.

The bundled YAML and schema subsets keep this script usable from a bare interpreter.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from typing import Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_FORCE_FALLBACK = os.environ.get("ARS_FORCE_FALLBACK") == "1"
try:
    from _yaml_subset import safe_load as _fallback_yaml_load
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(f"cannot load bundled YAML parser: {exc}\n")
    raise SystemExit(2) from exc
try:
    if _FORCE_FALLBACK:
        raise ImportError
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by bare tests
    yaml = None

try:
    if _FORCE_FALLBACK:
        raise ImportError
    import jsonschema  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by bare tests
    try:
        from _schema_subset import iter_errors as _fallback_schema_errors
    except ImportError as exc:  # pragma: no cover
        sys.stderr.write(f"cannot load bundled schema checker: {exc}\n")
        raise SystemExit(2) from exc
    jsonschema = None
else:
    _fallback_schema_errors = None

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas")
MAX_SCHEMA_ERRORS = 12
# Only the date-typed fields the schemas actually declare.  `check_dates` walks nested
# structures, and every schema is `additionalProperties: true`, so a bare `date` here made
# the linter police a key no schema defines: a number annotated
# `{"value": "6.2 EM", "date": "August 2026"}` was reported as a malformed ISO date even
# though the field is the user's own extension. Provenance dates in refs.bib are matched by
# the `rs-provenance` regex instead and are unaffected by this set.
DATE_FIELDS = {
    "created",
    "last_searched_at",
    "last_checked",
    "accessed",
}

errors: list[str] = []
warnings: list[str] = []

# ``None`` means a missing artifact to the structural checks.  A separate sentinel keeps
# an existing empty/null YAML document from silently becoming absent.
_YAML_NULL = object()


def err(where: str, message: str) -> None:
    errors.append(f"{where}: {message}")


def warn(where: str, message: str) -> None:
    warnings.append(f"{where}: {message}")


def _iso_dates(value: Any) -> Any:
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _iso_dates(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_iso_dates(item) for item in value]
    return value


def load_yaml(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        err(os.path.basename(path), f"unreadable YAML — {exc}")
        return None

    try:
        bundled = _fallback_yaml_load(text)
    except Exception as exc:
        # The bundled parser defines the supported ARS YAML profile.  Native PyYAML is
        # never allowed to widen that profile (anchors, tags, aliases, and other general
        # YAML constructs stay rejected in both environments).
        err(os.path.basename(path), f"unparseable YAML — {exc}")
        return None
    if yaml is not None:
        try:
            # PyYAML is an additional syntax-rejection oracle only.  Its YAML 1.1
            # implicit typing is intentionally not compared with the subset's values.
            yaml.safe_load(text)
        except Exception as exc:
            err(
                os.path.basename(path), f"unparseable YAML — native parser disagrees: {exc}"
            )
            return None
    bundled_normalized = _iso_dates(bundled)
    if bundled_normalized is None:
        return _YAML_NULL
    return bundled_normalized


def load_jsonl(path: str) -> list[dict[str, Any]] | None:
    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, 1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError as exc:
                    err("corpus.jsonl", f"line {line_number} is not valid JSON — {exc}")
                    continue
                if not isinstance(value, dict):
                    err("corpus.jsonl", f"line {line_number} is not an object")
                    continue
                records.append(value)
    except FileNotFoundError:
        return None
    except OSError as exc:
        err("corpus.jsonl", f"cannot read — {exc}")
    return records


def check_schema(data: Any, schema_name: str, label: str) -> None:
    path = os.path.join(SCHEMA_DIR, schema_name)
    try:
        with open(path, encoding="utf-8") as handle:
            schema = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        err(label, f"cannot load {schema_name} — {exc}")
        return
    try:
        if jsonschema is not None:
            validator = jsonschema.Draft202012Validator(
                schema, format_checker=jsonschema.FormatChecker()
            )
            found = sorted(
                validator.iter_errors(data), key=lambda item: list(item.absolute_path)
            )
            messages = [(tuple(item.absolute_path), item.message) for item in found]
        else:
            if _fallback_schema_errors is None:
                raise RuntimeError("bundled schema checker is unavailable")
            messages = _fallback_schema_errors(data, schema)
    except Exception as exc:
        err(label, f"schema check unavailable — {exc}")
        return
    for location, message in messages[:MAX_SCHEMA_ERRORS]:
        path_text = "/".join(str(part) for part in location) or "(root)"
        err(label, f"schema violation at {path_text} — {message}")
    if len(messages) > MAX_SCHEMA_ERRORS:
        warn(
            label,
            f"{len(messages) - MAX_SCHEMA_ERRORS} further schema violations not shown",
        )


def _parse_date(value: Any) -> datetime.date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def check_dates(value: Any, where: str = "artifact") -> None:
    """Check date-shaped fields without imposing freshness or ordering rules."""
    today = datetime.date.today()
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{where}.{key}"
            if key in DATE_FIELDS and item is not None:
                date_value = _parse_date(item)
                if date_value is None:
                    err(child, "must be a real ISO date (YYYY-MM-DD)")
                elif date_value > today:
                    warn(child, "date is in the future")
            check_dates(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            check_dates(item, f"{where}[{index}]")


def _within(directory: str, path: str) -> bool:
    """Whether *path* is still inside *directory* once every symlink is resolved."""
    root = os.path.realpath(directory)
    target = os.path.realpath(path)
    try:
        return os.path.commonpath((root, target)) == root
    except ValueError:  # different drives on Windows
        return False


def _unique(values: list[Any], label: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            err(label, f"duplicate `{value}`")
        seen.add(value)
    return seen


def check_protocol(protocol: Any) -> dict[str, Any]:
    if protocol is _YAML_NULL:
        err("protocol.yml", "must be a mapping; empty/null YAML is not allowed")
        return {}
    if protocol is None:
        return {}
    if not isinstance(protocol, dict):
        err("protocol.yml", "must be a mapping")
        return {}
    check_schema(protocol, "protocol.schema.json", "protocol.yml")
    check_dates(protocol, "protocol.yml")
    phase = protocol.get("phase")
    if phase is not None and (
        not isinstance(phase, int) or isinstance(phase, bool) or phase < 0 or phase > 5
    ):
        err("protocol.yml.phase", "must be an integer from 0 through 5 when present")
    axes = protocol.get("axes")
    if axes is not None:
        if not isinstance(axes, list):
            err("protocol.yml.axes", "must be a list when present")
        else:
            names: list[Any] = []
            for axis in axes:
                if isinstance(axis, dict):
                    names.append(axis.get("name"))
                    values = axis.get("values")
                    if isinstance(values, list):
                        _unique(
                            values, f"protocol.yml.axes[{axis.get('name', '?')}].values"
                        )
            _unique(names, "protocol.yml.axes")
    return protocol


def check_corpus(records: list[dict[str, Any]] | None, directory: str) -> set[str]:
    if records is None:
        return set()
    keys: list[Any] = []
    # One identifier belongs to one paper regardless of which field carries it, so the
    # duplicate check has to span the fields rather than run once per field: checking
    # `id` and `openalex_id` separately misses the record pair that writes the same
    # identifier into different fields, which is the shape a merge usually produces.
    identifier_owners: dict[str, set[int]] = {}
    for index, record in enumerate(records):
        label = f"corpus.jsonl[{index}]"
        check_schema(record, "corpus.schema.json", label)
        check_dates(record, label)
        key = record.get("key")
        keys.append(key)
        for identifier_field in ("id", "openalex_id"):
            identifier = record.get(identifier_field)
            if isinstance(identifier, str) and identifier:
                identifier_owners.setdefault(identifier, set()).add(index)
        # `notes_path` is the only reference in the workspace that names a file on disk
        # rather than another record's key, and it was the one dangling class nothing
        # checked.  A warning rather than an error: a record may legitimately be written
        # before its note is, and this toolbox treats an absent artifact as a limitation.
        notes_path = record.get("notes_path")
        if isinstance(notes_path, str) and notes_path.strip():
            parts = [
                p for p in notes_path.replace("\\", "/").split("/") if p not in ("", ".")
            ]
            if not parts or ".." in parts or os.path.isabs(notes_path):
                err(label, f"notes_path must stay inside the workspace: `{notes_path}`")
            elif not os.path.exists(os.path.join(directory, *parts)):
                warn(label, f"notes_path points at a missing file: `{notes_path}`")
            elif not _within(directory, os.path.join(directory, *parts)):
                # Spelling the path without `..` is not the same as staying inside the
                # workspace: a symlink under the survey directory can still name a file
                # anywhere on the machine, and the literal check above reads it as clean.
                err(
                    label,
                    f"notes_path resolves outside the workspace: `{notes_path}`",
                )
        if "found_via" not in record:
            warn(label, "recommended `found_via` provenance is missing")
        else:
            found_via = record.get("found_via")
            if not isinstance(found_via, list) or not found_via:
                err(label, "supplied `found_via` provenance must be a non-empty list")
            elif not all(isinstance(item, str) and item.strip() for item in found_via):
                err(label, "found_via provenance entries must be non-empty strings")
    key_set = _unique(keys, "corpus.jsonl.key")
    for identifier, owners in sorted(identifier_owners.items()):
        if len(owners) > 1:
            err(
                "corpus.jsonl",
                f"duplicate identifier `{identifier}` is claimed by "
                f"{len(owners)} records: {', '.join(str(i) for i in sorted(owners))}",
            )
    for record in records:
        key = record.get("key", "?")
        corroboration = record.get("corroboration")
        if not isinstance(corroboration, dict):
            continue
        for field in ("agrees_with", "conflicts_with"):
            refs = corroboration.get(field, [])
            if not isinstance(refs, list):
                err(f"corpus.jsonl[{key}].corroboration.{field}", "must be a list")
                continue
            for ref in refs:
                if ref == key:
                    err(f"corpus.jsonl[{key}]", f"{field} references itself")
                elif ref not in key_set:
                    err(f"corpus.jsonl[{key}]", f"{field} references missing key `{ref}`")
    return key_set


def _gap_ids(gaps: Any) -> set[str]:
    if not isinstance(gaps, dict) or not isinstance(gaps.get("gaps"), list):
        return set()
    values = [item.get("id") for item in gaps["gaps"] if isinstance(item, dict)]
    return _unique(values, "gaps.yml.id")


def check_gaps(
    gaps: Any,
    corpus_keys: set[str],
    *,
    corpus_present: bool = True,
) -> set[str]:
    if gaps is _YAML_NULL:
        err("gaps.yml", "must be a mapping; empty/null YAML is not allowed")
        return set()
    if gaps is None:
        return set()
    if not isinstance(gaps, dict):
        err("gaps.yml", "must be a mapping")
        return set()
    check_schema(gaps, "gaps.schema.json", "gaps.yml")
    check_dates(gaps, "gaps.yml")
    ids = _gap_ids(gaps)

    def check_corpus_reference(where: str, key: Any, relation: str) -> None:
        if corpus_present:
            if key not in corpus_keys:
                err(where, f"{relation} references missing key `{key}`")
        else:
            warn(
                where,
                f"{relation} references `{key}`, but corpus.jsonl is absent; "
                "reference was not resolved",
            )

    for gap in gaps.get("gaps", []):
        if not isinstance(gap, dict):
            continue
        gid = gap.get("id", "?")
        evidence = gap.get("evidence_of_absence")
        if isinstance(evidence, dict):
            queries = evidence.get("queries_run")
            if queries is not None and not isinstance(queries, list):
                err(f"gaps.yml[{gid}].evidence_of_absence.queries_run", "must be a list")
            nearest = evidence.get("nearest_prior_work", [])
            if isinstance(nearest, list):
                for prior in nearest:
                    if isinstance(prior, dict):
                        check_corpus_reference(
                            f"gaps.yml[{gid}]",
                            prior.get("key"),
                            "nearest_prior_work",
                        )
        closure = gap.get("closes_if_met")
        if isinstance(closure, dict):
            check_corpus_reference(
                f"gaps.yml[{gid}]",
                closure.get("key"),
                "closes_if_met",
            )
        threats = gap.get("threats", [])
        if isinstance(threats, list):
            for threat in threats:
                if isinstance(threat, dict):
                    check_corpus_reference(
                        f"gaps.yml[{gid}]",
                        threat.get("key"),
                        "threat",
                    )
    return ids


def check_coverage(
    coverage: Any,
    corpus_keys: set[str],
    gap_ids: set[str],
    *,
    corpus_present: bool = True,
    gaps_present: bool = True,
) -> None:
    if coverage is _YAML_NULL:
        err("coverage.yml", "must be a mapping; empty/null YAML is not allowed")
        return
    if coverage is None:
        return
    if not isinstance(coverage, dict):
        err("coverage.yml", "must be a mapping")
        return
    check_schema(coverage, "coverage.schema.json", "coverage.yml")
    check_dates(coverage, "coverage.yml")
    cells = coverage.get("cells", [])
    if not isinstance(cells, list):
        return
    seen: set[tuple[tuple[str, str], ...]] = set()

    def check_corpus_reference(where: str, key: Any, relation: str) -> None:
        if corpus_present:
            if key not in corpus_keys:
                err(where, f"{relation} references missing corpus key `{key}`")
        else:
            warn(
                where,
                f"{relation} references `{key}`, but corpus.jsonl is absent; "
                "reference was not resolved",
            )

    def check_gap_reference(where: str, key: Any) -> None:
        if gaps_present:
            if key not in gap_ids:
                err(where, f"gap_id references missing gap `{key}`")
        else:
            warn(
                where,
                f"gap_id references `{key}`, but gaps.yml is absent; "
                "reference was not resolved",
            )

    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        coords = cell.get("coords")
        if isinstance(coords, dict):
            coordinate = tuple(
                sorted((str(key), str(value)) for key, value in coords.items())
            )
            if coordinate in seen:
                err(f"coverage.yml.cells[{index}]", "duplicate coordinate")
            seen.add(coordinate)
        occupants = cell.get("occupants", [])
        if isinstance(occupants, list):
            for key in occupants:
                check_corpus_reference(f"coverage.yml.cells[{index}]", key, "occupant")
        gap_id = cell.get("gap_id")
        if gap_id is not None:
            check_gap_reference(f"coverage.yml.cells[{index}]", gap_id)
        successor = cell.get("revivable_by")
        if successor is not None:
            check_corpus_reference(
                f"coverage.yml.cells[{index}]", successor, "revivable_by"
            )


_ENTRY_START_RE = re.compile(r"^[ \t]*@", re.MULTILINE)
# Standard types are recognised as entry starts even when their opening delimiter is
# malformed.  A line-start `@name` in ordinary prose is otherwise left alone unless it
# has an entry-looking delimiter, avoiding false positives for email-style text.
_BIB_ENTRY_TYPES = frozenset(
    {
        "article",
        "book",
        "booklet",
        "conference",
        "dataset",
        "inbook",
        "incollection",
        "inproceedings",
        "manual",
        "mastersthesis",
        "misc",
        "online",
        "phdthesis",
        "proceedings",
        "software",
        "techreport",
        "unpublished",
    }
)
_BIB_DIRECTIVES = frozenset({"comment", "preamble", "string"})
_BIB_KNOWN_NAMES = _BIB_ENTRY_TYPES | _BIB_DIRECTIVES
_BIB_TYPE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_:+-]*")
# Kept as a compatibility name for callers that imported the old recognizer; validation
# itself deliberately uses `_ENTRY_START_RE` plus the structural scanner below.
_ENTRY_RE = _ENTRY_START_RE


def _bib_scan(
    text: str, open_index: int, limit: int | None = None, *, find_comma: bool = False
) -> tuple[int | None, int | None]:
    """Scan one BibTeX entry without confusing value atoms for outer delimiters."""
    if open_index >= len(text) or text[open_index] not in "{(":
        return None, None
    opener = text[open_index]
    limit = len(text) if limit is None else min(limit, len(text))
    braces = 0
    parens = 0
    quoted = False
    quoted_braces = 0
    after_header = False
    comma: int | None = None
    index = open_index + 1
    while index < limit:
        char = text[index]

        # BibTeX comments can contain a closing delimiter or a header comma.  A backslash
        # escapes the percent sign; comments inside a braced atom are data owned by that
        # atom and cannot affect the outer entry either way.
        if (
            char == "%"
            and not quoted
            and braces == 0
            and (index == 0 or text[index - 1] != "\\")
        ):
            newline = text.find("\n", index, limit)
            index = limit if newline < 0 else newline + 1
            continue

        if quoted:
            if char == "\\":
                index += 2
                continue
            if char == "{":
                quoted_braces += 1
            elif char == "}" and quoted_braces:
                quoted_braces -= 1
            elif char == '"' and quoted_braces == 0:
                quoted = False
            index += 1
            continue

        if braces:
            # A braced atom protects its quotes and parentheses.  Escaped braces are
            # literal TeX data rather than nesting changes.
            if char == "\\":
                index += 2
                continue
            if char == "{":
                braces += 1
            elif char == "}":
                braces -= 1
            index += 1
            continue

        if char == "\\":
            index += 2
            continue
        if char == "{":
            braces = 1
            index += 1
            continue
        if after_header and char == '"':
            quoted = True
            quoted_braces = 0
            index += 1
            continue
        if opener == "(" and char == "(":
            parens += 1
            index += 1
            continue
        if opener == "(" and char == ")":
            if parens:
                parens -= 1
                index += 1
                continue
            return index, comma
        if opener == "{" and char == "}":
            return index, comma
        if not after_header and char == "," and parens == 0:
            comma = index
            after_header = True
            if find_comma:
                return None, comma
        index += 1
    return None, comma


def _entry_end(text: str, open_index: int) -> int | None:
    """Index of the outer delimiter closing the entry opened at *open_index*."""
    end, _comma = _bib_scan(text, open_index)
    return end


def _header_comma(text: str, open_index: int, limit: int) -> int | None:
    """Find the key/value comma before *limit*, ignoring nested values."""
    _end, comma = _bib_scan(text, open_index, limit, find_comma=True)
    return comma


def _skip_inline_space(text: str, cursor: int) -> int:
    """Advance over spaces and tabs, stopping at the end of the line."""
    while cursor < len(text) and text[cursor] in " \t\f\v":
        cursor += 1
    return cursor


def _splits_header(text: str, cursor: int) -> bool:
    """Whether a plausible entry header continues on a later line."""
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    type_match = _BIB_TYPE_RE.match(text, cursor)
    if type_match is None:
        return cursor < len(text) and text[cursor] in "{("
    following = _skip_inline_space(text, type_match.end())
    return type_match.group(0).lower() in _BIB_KNOWN_NAMES or (
        following < len(text) and text[following] in "{("
    )


def _scan_bib_entries(text: str) -> tuple[list[str], list[str]]:
    """Scan plausible line-start entries and validate their complete structure."""
    keys: list[str] = []
    problems: list[str] = []
    position = 0
    while True:
        match = _ENTRY_START_RE.search(text, position)
        if match is None:
            break
        at = match.end() - 1
        cursor = _skip_inline_space(text, at + 1)
        type_match = _BIB_TYPE_RE.match(text, cursor)
        if type_match is None:
            # `@` followed by a delimiter is an unmistakable malformed entry; a lone
            # at-sign in a prose line is not.  A header wrapped onto the next line is
            # reported rather than skipped, so no real entry leaves the key list silently.
            if cursor < len(text) and text[cursor] in "{(":
                problems.append("entry type is missing after `@`")
            elif _splits_header(text, cursor):
                problems.append("entry header is split across lines after `@`")
            position = max(match.end(), at + 1)
            continue
        entry_type = type_match.group(0)
        lowered = entry_type.lower()
        cursor = _skip_inline_space(text, type_match.end())
        opener = text[cursor] if cursor < len(text) else None
        plausible = (
            lowered in _BIB_ENTRY_TYPES
            or lowered in _BIB_DIRECTIVES
            or (opener is not None and opener in "{(")
        )
        if not plausible:
            position = max(match.end(), at + 1)
            continue
        if opener is None or opener not in "{(":
            problems.append(f"entry `@{entry_type}` has no opening `{{` or `(` delimiter")
            position = max(match.end(), at + 1)
            continue

        end = _entry_end(text, cursor)
        limit = end if end is not None else len(text)
        if lowered in _BIB_DIRECTIVES:
            if end is None:
                problems.append(f"directive `@{entry_type}` is never closed")
            position = end + 1 if end is not None else max(match.end(), at + 1)
            continue

        comma = _header_comma(text, cursor, limit)
        key_text = text[cursor + 1 : comma if comma is not None else limit].strip()
        if comma is None or not key_text or re.search(r"\s", key_text):
            problems.append(f"entry `@{entry_type}` has an invalid key/comma header")
        elif end is not None:
            keys.append(key_text)
        if end is None:
            problems.append(
                f"entry `{key_text or '<unknown>'}` is never closed; the file is "
                "truncated or its delimiters are unbalanced"
            )
        position = end + 1 if end is not None else max(match.end(), at + 1)
    # A malformed opening can be rediscovered while scanning the remainder of a
    # truncated entry; report that diagnosis once rather than multiplying one defect.
    return keys, list(dict.fromkeys(problems))


_ATTESTATION_RE = re.compile(
    r"^\s*%\s*rs-provenance:\s*key=(?P<key>\S+)\s+id=(?P<id>\S+)\s+"
    r"tool=(?P<tool>\S+)\s+date=(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def check_refs(
    path: str,
    corpus: dict[str, dict[str, Any]],
    *,
    corpus_present: bool = True,
) -> None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        err("refs.bib", f"cannot read — {exc}")
        return
    keys, structural_problems = _scan_bib_entries(text)
    for problem in structural_problems:
        err("refs.bib", problem)
    bib_keys = _unique(keys, "refs.bib.key")
    attestations = list(_ATTESTATION_RE.finditer(text))
    for match in attestations:
        key = match.group("key")
        if key not in bib_keys:
            err("refs.bib", f"provenance attestation names missing entry `{key}`")
        record = corpus.get(key)
        if record is not None:
            identifiers = tuple(
                record.get(field) for field in ("id", "openalex_id") if record.get(field)
            )
            if identifiers and match.group("id") not in identifiers:
                err(
                    "refs.bib",
                    f"provenance id for `{key}` does not match corpus identifier",
                )
        elif not corpus_present:
            warn(
                "refs.bib",
                f"provenance id for `{key}` cannot be checked because corpus.jsonl "
                "is absent",
            )
        if _parse_date(match.group("date")) is None:
            err("refs.bib", f"provenance date for `{key}` is invalid")
    for key in bib_keys:
        if corpus_present and key not in corpus:
            err("refs.bib", f"entry `{key}` has no corpus record")
        elif not corpus_present:
            warn(
                "refs.bib",
                f"entry `{key}` cannot be cross-checked because corpus.jsonl is absent",
            )
        if not any(match.group("key") == key for match in attestations):
            warn("refs.bib", f"entry `{key}` has no explicit rs-provenance attestation")


def _self_test() -> int:
    try:
        sample = "a: 1\nb: [x, y]\n"
        if yaml is not None:
            value = yaml.safe_load(sample)
        else:
            if _fallback_yaml_load is None:
                raise RuntimeError("bundled YAML parser is unavailable")
            value = _fallback_yaml_load(sample)
        if value != {"a": 1, "b": ["x", "y"]}:
            raise ValueError(f"unexpected YAML result: {value!r}")
        schema = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}},
        }
        if jsonschema is not None:
            jsonschema.Draft202012Validator(schema).validate(value)
        elif _fallback_schema_errors is None:
            raise RuntimeError("bundled schema checker is unavailable")
        elif _fallback_schema_errors(value, schema):
            raise ValueError("fallback schema rejected its own sample")
    except Exception as exc:
        print(f"linter self-test failed: {exc}")
        return 1
    print("linter self-test passed")
    return 0


def main() -> int:
    errors.clear()
    warnings.clear()
    parser = argparse.ArgumentParser(
        description="Explicitly lint present ARS research artifacts; absent files are optional."
    )
    parser.add_argument("survey_dir", nargs="?")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    # Compatibility only. It is intentionally ignored and never creates a prerequisite;
    # old command recipes can migrate without reintroducing governance.
    parser.add_argument("--profile", help=argparse.SUPPRESS)
    parser.add_argument(
        "--self-test", action="store_true", help="check bundled fallback parsers"
    )
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    if not args.survey_dir:
        parser.error("survey_dir is required unless --self-test is used")
    directory = os.path.abspath(args.survey_dir)
    if not os.path.isdir(directory):
        sys.stderr.write(f"not a directory: {args.survey_dir}\n")
        return 2

    protocol_path = os.path.join(directory, "protocol.yml")
    protocol_present = os.path.exists(protocol_path)
    protocol = load_yaml(protocol_path) if protocol_present else None
    check_protocol(protocol)

    corpus_path = os.path.join(directory, "corpus.jsonl")
    corpus_present = os.path.exists(corpus_path)
    records = load_jsonl(corpus_path) if corpus_present else None
    corpus_records = {
        str(record.get("key")): record
        for record in (records or [])
        if isinstance(record.get("key"), str) and record.get("key")
    }
    corpus_keys = check_corpus(records, directory)

    gaps_path = os.path.join(directory, "gaps.yml")
    gaps_present = os.path.exists(gaps_path)
    gaps = load_yaml(gaps_path) if gaps_present else None
    gap_ids = check_gaps(gaps, corpus_keys, corpus_present=corpus_present)

    coverage_path = os.path.join(directory, "coverage.yml")
    coverage_present = os.path.exists(coverage_path)
    coverage = load_yaml(coverage_path) if coverage_present else None
    check_coverage(
        coverage,
        corpus_keys,
        gap_ids,
        corpus_present=corpus_present,
        gaps_present=gaps_present,
    )

    refs_path = os.path.join(directory, "refs.bib")
    refs_present = os.path.exists(refs_path)
    if refs_present:
        check_refs(refs_path, corpus_records, corpus_present=corpus_present)

    present = [
        name
        for name in ("protocol.yml", "corpus.jsonl", "coverage.yml", "gaps.yml", "refs.bib")
        if os.path.exists(os.path.join(directory, name))
    ]
    print(
        f"artifacts: {', '.join(present) if present else 'none (optional workspace is empty)'}"
    )
    if args.profile:
        print(
            "  note: --profile is deprecated and ignored; this linter has no prerequisite checks"
        )
    if yaml is None:
        print("  note: PyYAML unavailable — no second opinion on YAML syntax")
    if jsonschema is None:
        print("  note: jsonschema unavailable — bundled schema subset ran")
    for message in warnings:
        print(f"  WARN  {message}")
    for message in errors:
        print(f"  ERROR {message}")
    if not errors and not warnings:
        print("  clean")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
