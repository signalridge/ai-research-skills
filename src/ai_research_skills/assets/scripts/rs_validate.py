#!/usr/bin/env python3
"""Validate a survey state directory without runtime dependencies.

The validator uses PyYAML/jsonschema when available for development differential checks,
but the installed asset has a small, explicit stdlib-only YAML/JSON-Schema profile.  The
profile is intentionally not a general parser; unsupported syntax is reported as an
error rather than silently accepted.

Validation is phase-aware.  A Phase 0 protocol is not penalised for files that only exist
after Phase 3 or 4, while a later phase reconciles the ledgers it owns:

0 protocol; 1 corpus/log/recall/retrieved+deduped; 2 adjudication and score counts;
3 refs and include extraction; 4 coverage/gaps/full grid; 5 saturation and freshness.
"""

from __future__ import annotations

import argparse
import datetime
import itertools
import json
import os
import re
import sys
from typing import Any

# ``python -I path/to/rs_validate.py`` removes the script directory from sys.path on
# some interpreters.  Re-add only this trusted sibling directory so the bundled fallback
# remains usable in the exact isolated command users hit after installation.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_FORCE_FALLBACK = os.environ.get("ARS_FORCE_FALLBACK") == "1"

try:
    if _FORCE_FALLBACK:
        raise ImportError
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by clean-interpreter tests
    try:
        from _yaml_subset import YAMLSubsetError
        from _yaml_subset import safe_load as _safe_load
    except ImportError as exc:  # pragma: no cover
        sys.stderr.write(f"cannot load bundled YAML subset: {exc}\n")
        sys.exit(2)
    yaml = None
else:
    YAMLSubsetError = ValueError
    _safe_load = None

try:
    if _FORCE_FALLBACK:
        raise ImportError
    import jsonschema  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by clean-interpreter tests
    try:
        from _schema_subset import SchemaSubsetError
        from _schema_subset import iter_errors as _schema_errors
    except ImportError as exc:  # pragma: no cover
        sys.stderr.write(f"cannot load bundled schema subset: {exc}\n")
        sys.exit(2)
    jsonschema = None
else:
    SchemaSubsetError = ValueError
    _schema_errors = None


def _bundled_yaml_load(stream: Any) -> Any:
    if _safe_load is None:
        raise RuntimeError("bundled YAML loader is unavailable")
    return _safe_load(stream)


def _bundled_schema_errors(data: Any, schema: dict[str, Any]) -> list[Any]:
    if _schema_errors is None:
        raise RuntimeError("bundled schema checker is unavailable")
    return _schema_errors(data, schema)


SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas")
MAX_GRID_CELLS = 40
MAX_SCHEMA_ERRORS = 12
MODES = ("keyword", "citation_chain", "venue_author", "contrarian")
FULLTEXT_LEVELS = {"intro+method", "intro+method+results", "full"}

errors: list[str] = []
warnings: list[str] = []


def err(where: str, msg: str, fix: str = "") -> None:
    errors.append(f"{where}: {msg}" + (f"\n    fix: {fix}" if fix else ""))


def warn(where: str, msg: str, fix: str = "") -> None:
    warnings.append(f"{where}: {msg}" + (f"\n    fix: {fix}" if fix else ""))


# --------------------------------------------------------------------------- loading


def _iso_dates(obj: Any) -> Any:
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _iso_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_iso_dates(v) for v in obj]
    return obj


def load_yaml(path: str) -> Any:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            value = yaml.safe_load(fh) if yaml is not None else _bundled_yaml_load(fh)
        return _iso_dates(value)
    except Exception as exc:
        err(os.path.basename(path), f"unparseable YAML — {exc}")
        return None


def load_jsonl(path: str) -> list[dict[str, Any]] | None:
    if not os.path.exists(path):
        return None
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for number, raw in enumerate(fh, 1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    err("corpus.jsonl", f"line {number} is not valid JSON — {exc}")
                    continue
                if not isinstance(value, dict):
                    err("corpus.jsonl", f"line {number} is not a JSON object")
                    continue
                out.append(value)
    except OSError as exc:
        err("corpus.jsonl", f"cannot read — {exc}")
    return out


def check_schema(data: Any, schema_name: str, label: str) -> None:
    if data is None:
        return
    path = os.path.join(SCHEMA_DIR, schema_name)
    try:
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        err(label, f"cannot load schema {schema_name} — {exc}")
        return
    try:
        if jsonschema is not None:
            validator = jsonschema.Draft202012Validator(
                schema, format_checker=jsonschema.FormatChecker()
            )
            found = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
            messages = [(tuple(exc.absolute_path), exc.message) for exc in found]
        else:
            messages = _bundled_schema_errors(data, schema)
    except Exception as exc:
        err(label, f"schema profile unsupported — {exc}")
        return
    for location, message in messages[:MAX_SCHEMA_ERRORS]:
        loc = "/".join(str(part) for part in location) or "(root)"
        err(label, f"schema violation at {loc} — {message}")
    if len(messages) > MAX_SCHEMA_ERRORS:
        warn(
            label,
            f"{len(messages) - MAX_SCHEMA_ERRORS} further schema violations not shown",
        )


def _date_ok(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _parse_date(value: Any) -> datetime.date | None:
    if not _date_ok(value):
        return None
    return datetime.date.fromisoformat(value)


def _phase(proto: dict[str, Any] | None) -> int:
    value = (proto or {}).get("phase")
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


# --------------------------------------------------------------------------- protocol and ledger counts


def check_protocol(proto: Any) -> int:
    if proto is None:
        err("protocol.yml", "missing", "run `ars-survey` Phase 0")
        return -1
    if not isinstance(proto, dict):
        err("protocol.yml", "must be a mapping")
        return -1
    phase = _phase(proto)
    if phase not in range(6):
        err("protocol.yml", "`phase` must be an integer from 0 through 5")
        phase = -1
    question = proto.get("question")
    if not isinstance(question, str) or not question.strip().endswith("?"):
        err(
            "protocol.yml",
            "`question` is not interrogative",
            "write one answerable sentence ending in '?'",
        )
    axes = proto.get("axes") or []
    if not isinstance(axes, list) or len(axes) < 2:
        err("protocol.yml", "at least two `axes` must be declared in Phase 0")
    else:
        names: set[str] = set()
        cells = 1
        for axis in axes:
            if not isinstance(axis, dict) or not isinstance(axis.get("name"), str):
                continue
            name = axis["name"]
            values = axis.get("values") or []
            if name in names:
                err("protocol.yml", f"duplicate axis `{name}`")
            names.add(name)
            if (
                not isinstance(values, list)
                or len(values) < 2
                or len(set(values)) != len(values)
            ):
                err("protocol.yml", f"axis `{name}` must have unique values (at least two)")
            cells *= max(1, len(values)) if isinstance(values, list) else 1
        if cells > MAX_GRID_CELLS:
            warn("protocol.yml", f"grid has {cells} cells (>{MAX_GRID_CELLS})")
    if phase >= 1:
        modes = proto.get("recall_modes")
        if not isinstance(modes, dict):
            err("protocol.yml", "`recall_modes` is required from Phase 1")
        else:
            for mode in MODES:
                if not isinstance(modes.get(mode), list) or not modes.get(mode):
                    err("protocol.yml", f"recall mode `{mode}` is empty")
        if not isinstance(proto.get("last_searched_at"), str) and phase >= 5:
            err("protocol.yml", "`last_searched_at` is required in Phase 5")
    if phase >= 2:
        screen = proto.get("screen")
        if not isinstance(screen, dict):
            err("protocol.yml", "`screen` is required from Phase 2")
        else:
            for screen_key in ("include", "exclude"):
                values = screen.get(screen_key)
                if not isinstance(values, list) or not values:
                    err("protocol.yml", f"screen.{screen_key} is required from Phase 2")
            threshold = screen.get("relevance_threshold")
            if not isinstance(threshold, int) or isinstance(threshold, bool):
                err("protocol.yml", "screen.relevance_threshold is required")
    today = datetime.date.today()
    created = proto.get("created")
    created_date = _parse_date(created)
    if created_date is not None and created_date > today:
        err(
            "protocol.yml",
            "created cannot be in the future",
            "use the calendar date on which this protocol was created",
        )
    last_searched = proto.get("last_searched_at")
    if last_searched is not None:
        last_date = _parse_date(last_searched)
        if last_date is None:
            err("protocol.yml", "last_searched_at is not a real ISO calendar date")
        else:
            if created_date is not None and created_date > last_date:
                err(
                    "protocol.yml",
                    "created must be on or before last_searched_at",
                    "advance the watch date or correct the protocol creation date",
                )
            if last_date > today:
                err(
                    "protocol.yml",
                    (
                        "Phase 5 last_searched_at cannot be in the future"
                        if phase >= 5
                        else "last_searched_at cannot be in the future"
                    ),
                    "watch updates must use today's date or an earlier date",
                )
    if phase >= 5:
        saturation = proto.get("saturation")
        if not isinstance(saturation, dict):
            err("protocol.yml", "`saturation` is required in Phase 5")
        else:
            for key in ("rounds", "new_on_topic_last_round", "stop_rule"):
                if key not in saturation:
                    err("protocol.yml", f"saturation.{key} is required in Phase 5")
    return phase


def _corpus_index(records: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Index unique keys only; a duplicate must never resolve by last-write wins."""
    out: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for record in records or []:
        key = record.get("key")
        if not isinstance(key, str) or not key:
            continue
        if key in out or key in duplicates:
            out.pop(key, None)
            duplicates.add(key)
        else:
            out[key] = record
    return out


def _records_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    # The threshold is injected by check_counts; this helper is intentionally just the
    # terminal-state ledger so its definitions remain visible in one place.
    return {
        "deduped": len({r.get("key") for r in records if r.get("key")}),
        "adjudicated": sum(r.get("screen") in ("include", "exclude") for r in records),
        "unsure": sum(r.get("screen") == "unsure" for r in records),
        "fulltext_kept": sum(
            r.get("screen") == "include" and r.get("evidence_read") in FULLTEXT_LEVELS
            for r in records
        ),
    }


def check_counts(
    proto: dict[str, Any], records: list[dict[str, Any]] | None, phase: int
) -> None:
    counts = proto.get("counts")
    if not isinstance(counts, dict):
        err("protocol.yml", "counts is required for this phase")
        return
    if records is None:
        return
    actual = _records_counts(records)
    declared_deduped = counts.get("deduped")
    declared_retrieved = counts.get("retrieved")
    if phase >= 1:
        if declared_retrieved is None or declared_deduped is None:
            err(
                "protocol.yml",
                "counts.retrieved and counts.deduped are required in Phase 1",
            )
        elif not isinstance(declared_retrieved, int) or not isinstance(
            declared_deduped, int
        ):
            err("protocol.yml", "retrieved and deduped must be integers")
        else:
            if declared_retrieved < declared_deduped:
                err(
                    "protocol.yml",
                    f"retrieved ({declared_retrieved}) < deduped ({declared_deduped})",
                )
            if declared_deduped != actual["deduped"]:
                err(
                    "protocol.yml",
                    f"deduped ({declared_deduped}) != unique corpus records ({actual['deduped']})",
                )
    if phase >= 2:
        for key in ("adjudicated", "unsure", "scored_at_or_above_threshold"):
            if key not in counts:
                err("protocol.yml", f"counts.{key} is required in Phase 2")
        if counts.get("adjudicated") != actual["adjudicated"]:
            err(
                "protocol.yml",
                f"adjudicated ({counts.get('adjudicated')}) != terminal include/exclude records ({actual['adjudicated']})",
            )
        if counts.get("unsure") != actual["unsure"]:
            err(
                "protocol.yml",
                f"unsure ({counts.get('unsure')}) != screen=unsure records ({actual['unsure']})",
            )
        threshold = (proto.get("screen") or {}).get("relevance_threshold")
        if isinstance(threshold, int):
            scored = sum(
                isinstance(r.get("relevance"), int) and r["relevance"] >= threshold
                for r in records
            )
            if counts.get("scored_at_or_above_threshold") != scored:
                err(
                    "protocol.yml",
                    f"scored_at_or_above_threshold ({counts.get('scored_at_or_above_threshold')}) != records at threshold ({scored})",
                )
    if phase >= 3:
        if "fulltext_kept" not in counts:
            err("protocol.yml", "counts.fulltext_kept is required in Phase 3")
        elif counts.get("fulltext_kept") != actual["fulltext_kept"]:
            err(
                "protocol.yml",
                f"fulltext_kept ({counts.get('fulltext_kept')}) != included records read beyond abstract ({actual['fulltext_kept']})",
            )


# --------------------------------------------------------------------------- corpus


def check_corpus(
    records: list[dict[str, Any]] | None, proto: dict[str, Any], phase: int
) -> None:
    if records is None:
        err("corpus.jsonl", "missing", "run `ars-survey` Phase 1")
        return
    created = proto.get("created")
    created_date = _parse_date(created)
    today = datetime.date.today()
    for record in records:
        key = record.get("key", "?")
        check_schema(record, "corpus.schema.json", f"corpus.jsonl[{key}]")
        accessed = record.get("accessed")
        accessed_date = _parse_date(accessed)
        if accessed_date is not None:
            if accessed_date > today:
                err(
                    f"corpus.jsonl[{key}]",
                    "accessed cannot be in the future",
                    "record the date on which the source was actually accessed",
                )
            if created_date is not None and accessed_date < created_date:
                err(
                    f"corpus.jsonl[{key}]",
                    "accessed cannot be earlier than protocol.created",
                    "correct the access date or the protocol creation date",
                )
    seen: set[str] = set()
    for record in records:
        key = record.get("key")
        if not isinstance(key, str) or not key:
            err("corpus.jsonl", "a record has no `key`")
            continue
        if key in seen:
            err("corpus.jsonl", f"duplicate key `{key}`")
        seen.add(key)
    if phase < 2:
        return
    declared_axes = {
        axis.get("name"): set(axis.get("values") or [])
        for axis in (proto.get("axes") or [])
        if isinstance(axis, dict) and isinstance(axis.get("name"), str)
    }
    for record in records:
        key = record.get("key", "?")
        screen = record.get("screen")
        relevance = record.get("relevance")
        if not isinstance(relevance, int) or isinstance(relevance, bool):
            err(f"corpus.jsonl[{key}]", "missing integer `relevance`")
        threshold = (proto.get("screen") or {}).get("relevance_threshold")
        if (
            screen == "include"
            and isinstance(relevance, int)
            and not isinstance(relevance, bool)
            and isinstance(threshold, int)
            and not isinstance(threshold, bool)
            and relevance < threshold
        ):
            err(
                f"corpus.jsonl[{key}]",
                f"screen=include relevance ({relevance}) is below screen.relevance_threshold ({threshold})",
                "raise the relevance score with evidence or screen the record as exclude/unsure",
            )
        if not isinstance(record.get("contextual_summary"), str) or not record.get(
            "contextual_summary"
        ):
            err(f"corpus.jsonl[{key}]", "missing `contextual_summary`")
        if screen == "exclude" and not record.get("exclude_reason"):
            err(f"corpus.jsonl[{key}]", "exclude has no `exclude_reason`")
        if screen not in ("include", "exclude", "unsure"):
            err(f"corpus.jsonl[{key}]", "screen must be include, exclude, or unsure")
        if screen == "include" and phase >= 3:
            for field in ("claim", "evidence_read", "contextual_summary", "axes", "code"):
                if not record.get(field):
                    err(f"corpus.jsonl[{key}]", f"include is missing `{field}`")
            if record.get("evidence_read") == "abstract":
                warn(f"corpus.jsonl[{key}]", "has a claim but evidence_read is abstract")
        for axis, value in (record.get("axes") or {}).items():
            if axis not in declared_axes:
                err(
                    f"corpus.jsonl[{key}]", f"axis `{axis}` is not declared in protocol.yml"
                )
            elif value is not None and value not in declared_axes[axis]:
                err(
                    f"corpus.jsonl[{key}]", f"axis `{axis}` value {value!r} is not declared"
                )
        for number in record.get("numbers") or []:
            if not number.get("looked_at"):
                warn(
                    f"corpus.jsonl[{key}]",
                    f"number {number.get('value', '?')!r} has looked_at=false",
                )

    for record in records:
        key = record.get("key", "?")
        for field in ("agrees_with", "conflicts_with"):
            refs = (record.get("corroboration") or {}).get(field) or []
            for ref in refs:
                if ref == key:
                    err(f"corpus.jsonl[{key}]", f"corroboration.{field} references itself")
                elif ref not in seen:
                    err(
                        f"corpus.jsonl[{key}]",
                        f"corroboration.{field} references unknown key `{ref}`",
                    )

    includes = [r for r in records if r.get("screen") == "include"]
    if includes:
        shallow = sum(r.get("evidence_read") in (None, "abstract") for r in includes)
        if shallow / len(includes) >= 0.5:
            warn(
                "corpus.jsonl",
                f"{shallow}/{len(includes)} ({shallow / len(includes):.0%}) of includes are abstract-only",
            )
        exclusive: dict[str, int] = {}
        for record in includes:
            modes = {str(value).split(":", 1)[0] for value in record.get("found_via") or []}
            modes &= set(MODES)
            if len(modes) == 1:
                mode = next(iter(modes))
                exclusive[mode] = exclusive.get(mode, 0) + 1
        if exclusive:
            mode, number = max(exclusive.items(), key=lambda item: item[1])
            if number / len(includes) >= 0.8:
                warn(
                    "corpus.jsonl",
                    f"{number}/{len(includes)} ({number / len(includes):.0%}) of includes were surfaced only by `{mode}`",
                )


def _axis_tuples(
    axes: Any,
) -> tuple[list[tuple[str, tuple[str, ...]]], set[tuple[tuple[str, str], ...]]]:
    result: list[tuple[str, tuple[str, ...]]] = []
    names: set[str] = set()
    for axis in axes or []:
        if not isinstance(axis, dict) or not isinstance(axis.get("name"), str):
            continue
        name = axis["name"]
        raw_values = axis.get("values") or []
        if not isinstance(raw_values, list) or not all(
            isinstance(value, str) for value in raw_values
        ):
            continue
        values = tuple(raw_values)
        if name in names or len(values) != len(set(values)):
            continue
        names.add(name)
        result.append((name, values))
    expected: set[tuple[tuple[str, str], ...]] = set()
    if result:
        for combo in itertools.product(*(values for _name, values in result)):
            expected.add(
                tuple((result[index][0], combo[index]) for index in range(len(result)))
            )
    return result, expected


def check_coverage(
    cov: Any,
    proto: dict[str, Any],
    records: list[dict[str, Any]] | None,
    gaps: dict[str, Any] | None,
) -> None:
    if cov is None:
        err("coverage.yml", "missing", "run `ars-survey` Phase 4")
        return
    check_schema(cov, "coverage.schema.json", "coverage.yml")
    if not isinstance(cov, dict):
        return
    p_axes, expected = _axis_tuples(proto.get("axes"))
    coverage_axes_raw = cov.get("axes") or []
    coverage_names = [
        axis.get("name")
        for axis in coverage_axes_raw
        if isinstance(axis, dict) and isinstance(axis.get("name"), str)
    ]
    if len(coverage_names) != len(set(coverage_names)):
        err("coverage.yml", "coverage axes must be unique")
    for axis in coverage_axes_raw:
        if isinstance(axis, dict):
            values = axis.get("values") or []
            if (
                isinstance(values, list)
                and all(isinstance(value, str) for value in values)
                and len(values) != len(set(values))
            ):
                err(
                    "coverage.yml",
                    f"coverage axis `{axis.get('name', '?')}` has duplicate values",
                )
    c_axes, _ = _axis_tuples(coverage_axes_raw)
    if p_axes != c_axes:
        err("coverage.yml", "axes differ from protocol.yml")
    corpus = _corpus_index(records)
    includes = {
        key: record for key, record in corpus.items() if record.get("screen") == "include"
    }
    gap_ids: set[str] = set()
    raw_gaps = gaps.get("gaps", []) if isinstance(gaps, dict) else []
    for raw_gap in raw_gaps:
        if isinstance(raw_gap, dict):
            gap_id = raw_gap.get("id")
            if isinstance(gap_id, str):
                gap_ids.add(gap_id)
    referenced_gaps: set[str] = set()
    seen_cells: set[tuple[tuple[str, str], ...]] = set()
    include_occurrences: dict[str, int] = {key: 0 for key in includes}
    cells = cov.get("cells") or []
    if len(cells) != len(expected):
        err(
            "coverage.yml",
            f"grid has {len(cells)} cells but protocol axes require {len(expected)}",
        )
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            err(f"coverage.yml.cells[{index}]", "cell must be a mapping")
            continue
        coords = cell.get("coords") or {}
        if not isinstance(coords, dict):
            err(f"coverage.yml.cells[{index}]", "coords must be a mapping")
            continue
        coordinate = tuple((name, str(coords.get(name))) for name, _values in p_axes)
        label = ",".join(f"{key}={value}" for key, value in coordinate)
        if set(coords) != {name for name, _values in p_axes}:
            err(
                f"coverage.yml[{label or index}]",
                "coords keys must match every protocol axis exactly",
            )
        legal = True
        for name, values in p_axes:
            if coords.get(name) not in values:
                err(
                    f"coverage.yml[{label or index}]",
                    f"coordinate {name}={coords.get(name)!r} is not a protocol value",
                )
                legal = False
        if legal and coordinate in seen_cells:
            err(f"coverage.yml[{label}]", "duplicate grid cell")
        if legal:
            seen_cells.add(coordinate)
        state = cell.get("state")
        occupants = cell.get("occupants") or []
        if state == "occupied" and not occupants:
            err(f"coverage.yml[{label or index}]", "occupied cell has no occupants")
        if state != "occupied" and occupants:
            err(f"coverage.yml[{label or index}]", f"has occupants but state is `{state}`")
        if state in ("unexplored", "abandoned", "avoided") and not cell.get(
            "trend_evidence"
        ):
            err(
                f"coverage.yml[{label or index}]",
                f"marked `{state}` with no `trend_evidence`",
            )
        gap_id = cell.get("gap_id")
        if gap_id is not None and (not isinstance(gap_id, str) or gap_id not in gap_ids):
            err(
                f"coverage.yml[{label or index}]",
                f"gap_id `{gap_id}` is not in gaps.yml",
            )
        revivable = cell.get("revivable_by")
        if revivable is not None:
            if not isinstance(revivable, str) or revivable not in corpus:
                err(
                    f"coverage.yml[{label or index}]",
                    f"revivable_by `{revivable}` is not a corpus key",
                )
            elif corpus[revivable].get("screen") != "include":
                err(
                    f"coverage.yml[{label or index}]",
                    f"revivable_by `{revivable}` is not an include",
                )
            if state != "abandoned":
                err(
                    f"coverage.yml[{label or index}]",
                    "revivable_by is only meaningful for an abandoned cell",
                )
        if state == "abandoned" and gap_id is not None:
            if not isinstance(revivable, str) or not revivable:
                err(
                    f"coverage.yml[{label or index}]",
                    "an abandoned cell promoted with gap_id requires a non-empty revivable_by successor",
                )
            elif revivable in corpus and corpus[revivable].get("screen") != "include":
                err(
                    f"coverage.yml[{label or index}]",
                    f"revivable_by `{revivable}` successor is not an include",
                )
        if gap_id is not None:
            promotable = state in {"unexplored", "avoided"} or (
                state == "abandoned"
                and isinstance(revivable, str)
                and revivable in includes
            )
            if state in {"occupied", "undecided"} or not promotable:
                err(
                    f"coverage.yml[{label or index}]",
                    f"gap_id `{gap_id}` must reference an empty promotable cell "
                    "(unexplored/avoided, or abandoned with an included revivable_by)",
                )
            elif isinstance(gap_id, str) and not occupants:
                referenced_gaps.add(gap_id)
        for key in occupants:
            if not isinstance(key, str) or key not in includes:
                err(
                    f"coverage.yml[{label or index}]", f"occupant `{key}` is not an include"
                )
                continue
            if includes[key].get("evidence_read") == "abstract":
                err(
                    f"coverage.yml[{label or index}]",
                    f"occupant `{key}` is abstract-only and cannot establish coverage",
                    "read at least intro+method before placing an include on the coverage grid",
                )
            include_occurrences[key] += 1
            record_axes = includes[key].get("axes") or {}
            if any(record_axes.get(name) != coords.get(name) for name, _values in p_axes):
                err(
                    f"coverage.yml[{label or index}]",
                    f"occupant `{key}` axes do not match cell coords",
                )
    missing = expected - seen_cells
    if missing:
        err("coverage.yml", f"missing {len(missing)} Cartesian-product cell(s)")
    for key, number in include_occurrences.items():
        if number != 1:
            err(
                "coverage.yml",
                f"include `{key}` appears {number} times; every include must appear exactly once",
            )
    for gap_id in sorted(gap_ids - referenced_gaps):
        err(
            "coverage.yml",
            f"gap `{gap_id}` has no legal empty promotable cell reference",
            "add gap_id to one or more unexplored/avoided cells, or an abandoned cell with an included revivable_by",
        )

    diagnostic = cov.get("recall_diagnostic")
    if not isinstance(diagnostic, dict) or not isinstance(
        diagnostic.get("includes_by_mode"), dict
    ):
        err("coverage.yml", "recall_diagnostic.includes_by_mode is required")
    else:
        actual: dict[str, int] = {mode: 0 for mode in MODES}
        for record in includes.values():
            modes = {str(found).split(":", 1)[0] for found in record.get("found_via") or []}
            for mode in modes & set(actual):
                actual[mode] += 1
        declared = diagnostic["includes_by_mode"]
        if set(declared) != set(MODES):
            err(
                "coverage.yml",
                "includes_by_mode keys must be exactly the four recall modes",
            )
        for mode in MODES:
            if declared.get(mode) != actual[mode]:
                err(
                    "coverage.yml",
                    f"includes_by_mode.{mode} ({declared.get(mode)}) != found_via count ({actual[mode]})",
                )
        unsure_declared = diagnostic.get("unsure_by_mode")
        if unsure_declared is not None:
            if set(unsure_declared) != set(MODES):
                err(
                    "coverage.yml",
                    "unsure_by_mode keys must be exactly the four recall modes",
                )
            actual_unsure = {mode: 0 for mode in MODES}
            for record in corpus.values():
                if record.get("screen") != "unsure":
                    continue
                modes = {
                    str(found).split(":", 1)[0] for found in record.get("found_via") or []
                }
                for mode in modes & set(actual_unsure):
                    actual_unsure[mode] += 1
            for mode in MODES:
                if unsure_declared.get(mode) != actual_unsure[mode]:
                    err(
                        "coverage.yml",
                        f"unsure_by_mode.{mode} ({unsure_declared.get(mode)}) != found_via count ({actual_unsure[mode]})",
                    )


def _normalised_queries(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {
        " ".join(value.split()).casefold()
        for value in values
        if isinstance(value, str) and value.strip()
    }


def check_gaps(
    gaps: Any, records: list[dict[str, Any]] | None, proto: dict[str, Any] | None = None
) -> None:
    if gaps is None:
        err("gaps.yml", "missing", "run `ars-survey` Phase 4")
        return
    check_schema(gaps, "gaps.schema.json", "gaps.yml")
    if not isinstance(gaps, dict):
        return
    corpus = _corpus_index(records)
    today = datetime.date.today()
    last_searched = (proto or {}).get("last_searched_at")
    last_searched_date = _parse_date(last_searched)
    ids: set[str] = set()
    for gap in gaps.get("gaps") or []:
        if not isinstance(gap, dict):
            continue
        gid = gap.get("id", "?")
        if gid in ids:
            err(f"gaps.yml[{gid}]", "duplicate gap id")
        ids.add(gid)
        evidence = gap.get("evidence_of_absence") or {}
        queries = evidence.get("queries_run") or []
        distinct_queries = _normalised_queries(queries)
        venues = evidence.get("venues_swept") or []
        nearest = evidence.get("nearest_prior_work") or []
        if not gap.get("closes_if"):
            err(f"gaps.yml[{gid}]", "no `closes_if` falsifier")
        if len(queries) < 3 or len(distinct_queries) < 3:
            err(
                f"gaps.yml[{gid}]",
                f"only {len(distinct_queries)} distinct query phrasings recorded",
            )
        last_checked = evidence.get("last_checked")
        checked_date = _parse_date(last_checked)
        if checked_date is not None and checked_date > today:
            err(
                f"gaps.yml[{gid}]",
                "evidence_of_absence.last_checked cannot be in the future",
                "record the date on which the gap evidence was actually checked",
            )
        if not nearest:
            warn(f"gaps.yml[{gid}]", "nearest_prior_work is empty")
        for prior in nearest:
            key = prior.get("key") if isinstance(prior, dict) else None
            if key not in corpus:
                err(
                    f"gaps.yml[{gid}]",
                    f"nearest_prior_work key `{key}` is not a corpus key",
                )
        closure = gap.get("closes_if_met")
        if closure is not None:
            if last_searched_date is None:
                err(
                    f"gaps.yml[{gid}]",
                    "closes_if_met requires protocol.last_searched_at",
                    "ars-watch must update the protocol date with the closure",
                )
            if not isinstance(closure, dict):
                err(f"gaps.yml[{gid}]", "closes_if_met must be an object")
            else:
                for field in ("key", "date", "rationale"):
                    if not closure.get(field):
                        err(f"gaps.yml[{gid}]", f"closes_if_met.{field} is required")
                if closure.get("key") not in corpus:
                    err(
                        f"gaps.yml[{gid}]",
                        f"closes_if_met.key `{closure.get('key')}` is not a corpus key",
                    )
                closure_date = closure.get("date")
                if not _date_ok(closure_date):
                    err(
                        f"gaps.yml[{gid}]",
                        "closes_if_met.date is not a real ISO calendar date",
                    )
                else:
                    closure_day = _parse_date(closure_date)
                    if closure_day is not None and closure_day > today:
                        err(
                            f"gaps.yml[{gid}]", "closes_if_met.date cannot be in the future"
                        )
                    if (
                        closure_day is not None
                        and last_searched_date is not None
                        and closure_day > last_searched_date
                    ):
                        err(
                            f"gaps.yml[{gid}]",
                            "closes_if_met.date is after protocol.last_searched_at",
                            "update last_searched_at when ars-watch records the closure",
                        )
        threats = gap.get("threats") or []
        if not isinstance(threats, list):
            err(f"gaps.yml[{gid}]", "threats must be a list")
        else:
            if threats and last_searched_date is None:
                err(
                    f"gaps.yml[{gid}]",
                    "threats require protocol.last_searched_at",
                    "ars-watch must update the protocol date with the threat",
                )
            for threat in threats:
                if not isinstance(threat, dict):
                    err(f"gaps.yml[{gid}]", "each threat must be an object")
                    continue
                if threat.get("key") not in corpus:
                    err(
                        f"gaps.yml[{gid}]",
                        f"threats.key `{threat.get('key')}` is not a corpus key",
                    )
                threat_date = threat.get("date")
                if not _date_ok(threat_date):
                    err(f"gaps.yml[{gid}]", "threats.date is not a real ISO calendar date")
                else:
                    threat_day = _parse_date(threat_date)
                    if threat_day is not None and threat_day > today:
                        err(f"gaps.yml[{gid}]", "threats.date cannot be in the future")
                    if (
                        threat_day is not None
                        and last_searched_date is not None
                        and threat_day > last_searched_date
                    ):
                        err(
                            f"gaps.yml[{gid}]",
                            "threats.date is after protocol.last_searched_at",
                            "update last_searched_at when ars-watch records the threat",
                        )
                if not threat.get("unmet_clause"):
                    err(f"gaps.yml[{gid}]", "threats.unmet_clause is required")
        if gap.get("confidence") == "high":
            unmet = []
            if len(distinct_queries) < 3:
                unmet.append(">=3 phrasings")
            if len(venues) < 3:
                unmet.append(">=3 venue-years")
            if not evidence.get("citation_chains"):
                unmet.append("forward citation chains")
            if not nearest:
                unmet.append("nearest_prior_work")
            if unmet:
                err(
                    f"gaps.yml[{gid}]", "confidence `high` but missing: " + ", ".join(unmet)
                )


# --------------------------------------------------------------------------- BibTeX

_ENTRY_RE = re.compile(
    r"^\s*@(?!(?:string|preamble|comment)\b)\w+\s*[\{\(]\s*([^,\s]+)",
    re.IGNORECASE | re.MULTILINE,
)
_STRICT_ATTESTATION_RE = re.compile(
    r"^\s*%\s*rs-provenance:\s*key=(?P<key>\S+)\s+id=(?P<id>\S+)\s+"
    r"tool=(?P<tool>\S+)\s+date=(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _bib_entries(text: str) -> list[tuple[str, str]]:
    matches = list(_ENTRY_RE.finditer(text))
    return [
        (
            match.group(1),
            text[
                match.start() : (
                    matches[index + 1].start() if index + 1 < len(matches) else len(text)
                )
            ],
        )
        for index, match in enumerate(matches)
    ]


def _bib_attestations(text: str) -> dict[int, list[dict[str, str]]]:
    entries = list(_ENTRY_RE.finditer(text))
    out: dict[int, list[dict[str, str]]] = {}
    for attestation in _STRICT_ATTESTATION_RE.finditer(text):
        for index, entry in enumerate(entries):
            if entry.start() > attestation.end():
                out.setdefault(index, []).append(attestation.groupdict())
                break
    return out


def check_refs(survey_dir: str, records: list[dict[str, Any]] | None) -> None:
    """Validate ordered entries; comments are attestations, not cryptographic proof."""
    path = os.path.join(survey_dir, "refs.bib")
    if not os.path.exists(path):
        err(
            "refs.bib",
            "missing",
            "run the authorised citation export in ars-survey Phase 3",
        )
        return
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        err("refs.bib", f"cannot read — {exc}")
        return
    entries = _bib_entries(text)
    corpus = _corpus_index(records)
    attached = _bib_attestations(text)
    seen: set[str] = set()
    bib_keys: set[str] = set()
    for index, (key, _body) in enumerate(entries):
        bib_keys.add(key)
        if key in seen:
            err(f"refs.bib[{key}]", "duplicate citation key")
        seen.add(key)
        values = attached.get(index, [])
        if len(values) != 1:
            if not values:
                err(
                    f"refs.bib[{key}]",
                    "entry lacks a strict per-entry rs-provenance attestation",
                    "export it with key, stable id, tool and date; attestations are integrity tripwires, not cryptographic provenance",
                )
            else:
                err(f"refs.bib[{key}]", "one entry has multiple attestations")
            continue
        attestation = values[0]
        if attestation.get("key") != key:
            err(f"refs.bib[{key}]", "attestation key does not match entry key")
        record = corpus.get(key)
        if record is None:
            err(f"refs.bib[{key}]", "attestation key is not a unique corpus.jsonl key")
        else:
            expected = record.get("id") or record.get("openalex_id")
            if attestation.get("id") != expected:
                err(
                    f"refs.bib[{key}]",
                    f"attestation id {attestation.get('id')!r} does not match corpus identifier {expected!r}",
                )
        if not attestation.get("tool") or not _date_ok(attestation.get("date")):
            err(f"refs.bib[{key}]", "attestation needs a non-empty tool and real ISO date")
    for record in records or []:
        if record.get("screen") == "include" and record.get("key") not in bib_keys:
            warn("refs.bib", f"include {record.get('key')} has no BibTeX entry")


# --------------------------------------------------------------------------- main


def _self_test() -> int:
    """Tiny installed-runtime check used by doctor and clean-interpreter smoke tests."""
    try:
        sample = "a: 1\nb: [x, y]\n"
        value = yaml.safe_load(sample) if yaml is not None else _bundled_yaml_load(sample)
        if value != {"a": 1, "b": ["x", "y"]}:
            raise ValueError(f"unexpected YAML subset result: {value!r}")
        schema = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}},
        }
        if jsonschema is not None:
            jsonschema.Draft202012Validator(
                schema, format_checker=jsonschema.FormatChecker()
            ).validate(value)
        elif _bundled_schema_errors(value, schema):
            raise ValueError("schema subset rejected its own sample")
    except Exception as exc:
        print(f"validator self-test failed: {exc}")
        return 1
    print("validator self-test passed")
    return 0


def main() -> int:
    errors.clear()
    warnings.clear()
    ap = argparse.ArgumentParser(
        description="Validate an ai-research-skills survey state dir."
    )
    ap.add_argument("survey_dir", nargs="?")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument(
        "--self-test", action="store_true", help="check the installed fallback runtime"
    )
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not args.survey_dir:
        ap.error("survey_dir is required unless --self-test is used")
    survey_dir = os.path.abspath(args.survey_dir)
    if not os.path.isdir(survey_dir):
        sys.stderr.write(f"not a directory: {args.survey_dir}\n")
        return 2

    protocol = load_yaml(os.path.join(survey_dir, "protocol.yml"))
    phase = check_protocol(protocol)
    phase = max(phase, 0)
    if isinstance(protocol, dict):
        check_schema(protocol, "protocol.schema.json", "protocol.yml")
    records = load_jsonl(os.path.join(survey_dir, "corpus.jsonl")) if phase >= 1 else None
    if phase >= 1:
        check_corpus(records, protocol if isinstance(protocol, dict) else {}, phase)
        log_path = os.path.join(survey_dir, "log.md")
        if not os.path.isfile(log_path):
            err("log.md", "missing", "record every Phase 1 query and its result")
        else:
            try:
                with open(log_path, encoding="utf-8") as log_file:
                    log_text = log_file.read()
                for mode in MODES:
                    if mode not in log_text:
                        err("log.md", f"no logged execution for recall mode `{mode}`")
            except OSError as exc:
                err("log.md", f"cannot read — {exc}")
        if isinstance(protocol, dict):
            check_counts(protocol, records, phase)
    if phase >= 3 and isinstance(protocol, dict):
        check_refs(survey_dir, records)
    coverage = load_yaml(os.path.join(survey_dir, "coverage.yml")) if phase >= 4 else None
    gaps = load_yaml(os.path.join(survey_dir, "gaps.yml")) if phase >= 4 else None
    if phase >= 4 and isinstance(protocol, dict):
        check_coverage(coverage, protocol, records, gaps)
        check_gaps(gaps, records, protocol)
    if phase >= 5 and isinstance(protocol, dict):
        if not _date_ok(protocol.get("last_searched_at")):
            err("protocol.yml", "last_searched_at is not an ISO date")
        saturation = protocol.get("saturation") or {}
        if not isinstance(saturation.get("rounds"), int) or saturation.get("rounds", 0) < 1:
            err("protocol.yml", "saturation.rounds must be a positive integer")
        if (
            not isinstance(saturation.get("new_on_topic_last_round"), int)
            or saturation.get("new_on_topic_last_round", -1) < 0
        ):
            err("protocol.yml", "saturation.new_on_topic_last_round must be non-negative")

    name = os.path.basename(survey_dir)
    print(f"survey: {name}")
    if jsonschema is None:
        print("  note: jsonschema unavailable — bundled schema subset ran")
    if yaml is None:
        print("  note: PyYAML unavailable — bundled YAML subset ran")
    for warning in warnings:
        print(f"  WARN  {warning}")
    for error in errors:
        print(f"  ERROR {error}")
    if not errors and not warnings:
        print("  clean")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
