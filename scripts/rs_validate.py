#!/usr/bin/env python3
"""Validate a survey's state directory.

    python3 scripts/rs_validate.py .research/survey/<slug>
    python3 scripts/rs_validate.py .research/survey/<slug> --strict   # warnings fail too

Two layers:

  1. Structural — each file against schemas/*.json, when `jsonschema` is importable.
     Install with `uv run --with jsonschema scripts/rs_validate.py ...` if you want it.

  2. Semantic — the checks a JSON Schema cannot express, and the ones that actually catch
     broken surveys: a taxonomy that drifted after searching, a `high`-confidence gap
     resting on two queries, counts that claim more coverage than the corpus supports.

Exit 0 clean, 1 on errors.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "rs_validate needs PyYAML.\n"
        "  uv run --with pyyaml scripts/rs_validate.py <dir>\n"
        "  or: pip install pyyaml\n"
    )
    sys.exit(2)

try:
    import jsonschema
except ImportError:
    jsonschema = None

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas")
MAX_GRID_CELLS = 40

errors: list[str] = []
warnings: list[str] = []


def err(where: str, msg: str, fix: str = "") -> None:
    errors.append(f"{where}: {msg}" + (f"\n    fix: {fix}" if fix else ""))


def warn(where: str, msg: str, fix: str = "") -> None:
    warnings.append(f"{where}: {msg}" + (f"\n    fix: {fix}" if fix else ""))


# --------------------------------------------------------------------------- loading


def _iso_dates(obj):
    """PyYAML turns bare ISO dates into datetime.date; JSON Schema wants strings.

    Normalise so a correctly-written `last_searched_at: 2026-08-03` does not read as a
    type error. Quoting the date in YAML would also work, but nobody should have to.
    """
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _iso_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_iso_dates(v) for v in obj]
    return obj


def load_yaml(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return _iso_dates(yaml.safe_load(fh))
    except Exception as exc:
        err(os.path.basename(path), f"unparseable YAML — {exc}")
        return None


def load_jsonl(path):
    if not os.path.exists(path):
        return None
    out = []
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                err("corpus.jsonl", f"line {n} is not valid JSON — {exc}")
    return out


MAX_SCHEMA_ERRORS = 12


def check_schema(data, schema_name: str, label: str) -> None:
    """Report every schema violation in a document, not just the first.

    jsonschema.validate raises on the first error, which turns fixing a file into a
    fix-one-rerun-find-the-next loop and hides later problems behind earlier ones.
    iter_errors surfaces them all at once.
    """
    if jsonschema is None or data is None:
        return
    path = os.path.join(SCHEMA_DIR, schema_name)
    try:
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
    except FileNotFoundError:
        warn(label, f"schema {schema_name} not found")
        return

    validator = jsonschema.Draft202012Validator(schema)
    found = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    for exc in found[:MAX_SCHEMA_ERRORS]:
        loc = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        err(label, f"schema violation at {loc} — {exc.message}")
    if len(found) > MAX_SCHEMA_ERRORS:
        warn(label, f"{len(found) - MAX_SCHEMA_ERRORS} further schema violations not shown")


# --------------------------------------------------------------------------- checks


def check_protocol(proto):
    if proto is None:
        err("protocol.yml", "missing", "run `survey` Phase 0")
        return

    q = proto.get("question", "")
    if not q.strip().endswith("?"):
        err(
            "protocol.yml",
            "`question` is not interrogative",
            "a topic wearing a question mark is still a topic — see references/00-scope.md",
        )

    modes = proto.get("recall_modes") or {}
    fixes = {
        "keyword": "all four modes are mandatory; each is blind to what the others find",
        "citation_chain": "all four modes are mandatory; citation chaining is "
        "terminology-blind and finds work keyword search cannot",
        "venue_author": "all four modes are mandatory; venue sweeps catch work too "
        "recent to be cited",
        "contrarian": "the other three modes are all biased toward consensus. Without a "
        "contrarian pass, red-team's cherry-picking check can only find contradictions "
        "already in the corpus — see references/01-recall.md Mode D",
    }
    for mode, fix in fixes.items():
        if not modes.get(mode):
            err("protocol.yml", f"recall mode `{mode}` is empty", fix)

    axes = proto.get("axes") or []
    if not axes:
        err(
            "protocol.yml",
            "no `axes` declared",
            "axes must be declared in Phase 0 BEFORE searching, or every empty cell "
            "is an artifact of what the search happened to find",
        )
    else:
        cells = 1
        for a in axes:
            cells *= max(1, len(a.get("values") or []))
        if cells > MAX_GRID_CELLS:
            warn(
                "protocol.yml",
                f"grid has {cells} cells (>{MAX_GRID_CELLS})",
                "most will be empty and every empty one looks like a gap — drop an axis "
                "or collapse values",
            )

    c = proto.get("counts") or {}
    ret, ded, adj = c.get("retrieved"), c.get("deduped"), c.get("adjudicated")
    if ded is not None and ret is not None and ded > ret:
        err("protocol.yml", f"deduped ({ded}) > retrieved ({ret})")
    if adj is not None and ded is not None:
        if adj > ded:
            err("protocol.yml", f"adjudicated ({adj}) > deduped ({ded})")
        elif ded and adj / ded < 0.9:
            warn(
                "protocol.yml",
                f"only {adj}/{ded} ({adj / ded:.0%}) adjudicated",
                "report this explicitly — an unadjudicated tail is not an excluded one",
            )


def check_corpus(records, proto):
    if records is None:
        err("corpus.jsonl", "missing", "run `survey` Phase 1")
        return

    for r in records:
        check_schema(r, "corpus.schema.json", f"corpus.jsonl[{r.get('key', '?')}]")

    seen = set()
    for r in records:
        k = r.get("key")
        if not k:
            err("corpus.jsonl", "a record has no `key`")
            continue
        if k in seen:
            err(
                "corpus.jsonl",
                f"duplicate key `{k}`",
                "merge the records; dedup missed one",
            )
        seen.add(k)

    declared = {
        a["name"]: set(a.get("values") or [])
        for a in ((proto or {}).get("axes") or [])
        if a.get("name")
    }

    includes = [r for r in records if r.get("screen") == "include"]
    for r in includes:
        k = r.get("key", "?")
        for field in ("claim", "evidence_read", "contextual_summary"):
            if not r.get(field):
                err(
                    f"corpus.jsonl[{k}]",
                    f"include is missing `{field}`",
                    "an include with no claim is an un-read paper wearing a decision",
                )

        if r.get("evidence_read") == "abstract" and r.get("claim"):
            warn(
                f"corpus.jsonl[{k}]",
                "has a `claim` but evidence_read is `abstract`",
                "a claim needs intro+method — an abstract states intent, not results",
            )

        for num in r.get("numbers") or []:
            if not num.get("looked_at"):
                warn(
                    f"corpus.jsonl[{k}]",
                    f"number {num.get('value', '?')!r} has looked_at=false",
                    "`verify` will block it; read the table or drop the number",
                )

        for axis, val in (r.get("axes") or {}).items():
            if declared and axis not in declared:
                err(
                    f"corpus.jsonl[{k}]",
                    f"axis `{axis}` is not declared in protocol.yml",
                )
            elif val is not None and declared and val not in declared.get(axis, set()):
                warn(
                    f"corpus.jsonl[{k}]",
                    f"axis `{axis}` value {val!r} is not a declared value",
                )

    for r in records:
        if r.get("screen") == "exclude" and not r.get("exclude_reason"):
            err(f"corpus.jsonl[{r.get('key', '?')}]", "exclude has no `exclude_reason`")

    if includes:
        shallow = sum(1 for r in includes if r.get("evidence_read") in (None, "abstract"))
        if shallow / len(includes) >= 0.5:
            warn(
                "corpus.jsonl",
                f"{shallow}/{len(includes)} ({shallow / len(includes):.0%}) of includes "
                f"are abstract-only",
                "lead with this in any handoff — it is the survey's real quality signal",
            )

        # What would be lost if one mode had not been run: count includes that ONLY that
        # mode surfaced. Counting per-mode hits instead double-counts any record two modes
        # both found — which is exactly the healthy case.
        exclusive: dict[str, int] = {}
        for r in includes:
            found_modes = {fv.split(":", 1)[0] for fv in (r.get("found_via") or [])}
            if len(found_modes) == 1:
                m = found_modes.pop()
                exclusive[m] = exclusive.get(m, 0) + 1
        if exclusive:
            top, n = max(exclusive.items(), key=lambda kv: kv[1])
            if n / len(includes) >= 0.8:
                warn(
                    "corpus.jsonl",
                    f"{n}/{len(includes)} ({n / len(includes):.0%}) of includes were "
                    f"surfaced by `{top}` and no other mode",
                    "recall rests on one mode — see red-team checkpoint A2",
                )


def check_coverage(cov, proto):
    if cov is None:
        return  # Phase 4 not reached yet
    check_schema(cov, "coverage.schema.json", "coverage.yml")

    p_axes = [
        (a.get("name"), tuple(a.get("values") or []))
        for a in ((proto or {}).get("axes") or [])
    ]
    c_axes = [
        (a.get("name"), tuple(a.get("values") or [])) for a in (cov.get("axes") or [])
    ]
    if p_axes and c_axes and p_axes != c_axes:
        err(
            "coverage.yml",
            "axes differ from protocol.yml",
            "the taxonomy was changed after searching — every empty cell is now an "
            "artifact of what you happened to find, not a finding",
        )

    for cell in cov.get("cells") or []:
        coords = cell.get("coords") or {}
        label = ",".join(f"{k}={v}" for k, v in coords.items()) or "?"
        state = cell.get("state")
        if state in ("unexplored", "avoided") and not cell.get("trend_evidence"):
            err(
                f"coverage.yml[{label}]",
                "marked `unexplored` with no `trend_evidence`",
                "an unoccupied cell is not automatically unexplored — it may be "
                "abandoned or avoided, which score at opposite ends of G2. Run the "
                "neighbour trend check in references/04-map.md Steps B-C, or mark it "
                "undecided",
            )
        if state == "occupied" and not cell.get("occupants"):
            err(f"coverage.yml[{label}]", "marked `occupied` with no occupants")
        if state != "occupied" and cell.get("occupants"):
            err(f"coverage.yml[{label}]", f"has occupants but state is `{state}`")
        if state == "abandoned" and cell.get("gap_id"):
            err(
                f"coverage.yml[{label}]",
                f"marked `abandoned` but promoted to gap {cell['gap_id']}",
                "abandoned means the field tried and it did not hold up — read that "
                "failure first. If the field never actually tried, the cell is "
                "`avoided`, not `abandoned`; see references/04-map.md Step C",
            )


def check_gaps(gaps):
    if gaps is None:
        return
    check_schema(gaps, "gaps.schema.json", "gaps.yml")

    for g in gaps.get("gaps") or []:
        gid = g.get("id", "?")
        ev = g.get("evidence_of_absence") or {}
        queries = ev.get("queries_run") or []
        venues = ev.get("venues_swept") or []
        near = ev.get("nearest_prior_work") or []
        conf = g.get("confidence")

        if not g.get("closes_if"):
            err(
                f"gaps.yml[{gid}]",
                "no `closes_if` falsifier",
                "without it `watch` cannot re-test the gap and it closes silently",
            )

        if len(queries) < 3:
            err(
                f"gaps.yml[{gid}]",
                f"only {len(queries)} query phrasings recorded",
                "an absence claim needs >=3 distinct phrasings; rewording one is not three",
            )

        if not near:
            warn(
                f"gaps.yml[{gid}]",
                "`nearest_prior_work` is empty",
                "real gaps sit next to something — an empty one usually means the search "
                "was too narrow, not that the field is open",
            )

        if conf == "high":
            unmet = []
            if len(queries) < 3:
                unmet.append(">=3 phrasings")
            if len(venues) < 3:
                unmet.append(">=3 venue-years")
            if not ev.get("citation_chains"):
                unmet.append("forward citation chains")
            if not near:
                unmet.append("nearest_prior_work")
            if unmet:
                err(
                    f"gaps.yml[{gid}]",
                    "confidence `high` but missing: " + ", ".join(unmet),
                    "downgrade to medium, or complete the evidence",
                )


def check_refs(survey_dir, records):
    path = os.path.join(survey_dir, "refs.bib")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    if re.search(r"^\s*@\w+\s*\{", text, re.MULTILINE) and not re.search(
        r"%\s*(rs-provenance:|Generated by|arxiv-mcp-server|export_citations)",
        text,
        re.IGNORECASE,
    ):
        err(
            "refs.bib",
            "has entries but no tool-provenance header",
            "regenerate with arxiv export_citations — hand-written BibTeX is the most "
            "common source of fabricated citations",
        )

    bib_keys = set(re.findall(r"^\s*@\w+\s*\{\s*([^,\s]+)", text, re.MULTILINE))
    if records:
        missing = [
            r["key"]
            for r in records
            if r.get("screen") == "include" and r.get("key") not in bib_keys
        ]
        if missing:
            warn(
                "refs.bib",
                f"{len(missing)} include(s) have no BibTeX entry: "
                + ", ".join(sorted(missing)[:5])
                + ("…" if len(missing) > 5 else ""),
                "export them before drafting",
            )


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a research-skills survey state dir.")
    ap.add_argument("survey_dir")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args()

    d = args.survey_dir
    if not os.path.isdir(d):
        sys.stderr.write(f"not a directory: {d}\n")
        return 2

    proto = load_yaml(os.path.join(d, "protocol.yml"))
    check_schema(proto, "protocol.schema.json", "protocol.yml")
    records = load_jsonl(os.path.join(d, "corpus.jsonl"))
    cov = load_yaml(os.path.join(d, "coverage.yml"))
    gaps = load_yaml(os.path.join(d, "gaps.yml"))

    check_protocol(proto)
    check_corpus(records, proto)
    check_coverage(cov, proto)
    check_gaps(gaps)
    check_refs(d, records)

    name = os.path.basename(os.path.abspath(d))
    print(f"survey: {name}")
    if jsonschema is None:
        print(
            "  note: `jsonschema` not installed — structural checks skipped, semantic "
            "checks ran.\n        uv run --with jsonschema,pyyaml scripts/rs_validate.py "
            "<dir>"
        )

    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")

    if not errors and not warnings:
        print("  clean")

    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
