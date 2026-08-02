#!/usr/bin/env python3
"""SessionStart notice: a stale survey is a liability.

In a field growing ~3x a year, a six-week-old corpus has missed a meaningful slice of the
literature — and the gaps it reports may already be closed. This surfaces the age of every
survey in the project at session start, so nobody reasons from a stale snapshot without
knowing it.

Advisory only: emits context, never blocks. Fails open.
"""

import contextlib
import datetime
import json
import os
import re
import sys

STALE_DAYS = 30

DATE_RE = re.compile(r"^\s*last_searched_at:\s*['\"]?(\d{4}-\d{2}-\d{2})", re.MULTILINE)
TOPIC_RE = re.compile(r"^\s*topic:\s*['\"]?([A-Za-z0-9._-]+)", re.MULTILINE)
GROWTH_RE = re.compile(r"^\s*baseline_growth:\s*['\"]?([^'\"\n]+)", re.MULTILINE)


def scan(cwd: str):
    root = os.path.join(cwd, ".research", "survey")
    if not os.path.isdir(root):
        return []

    today = datetime.date.today()
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []

    for name in names:
        path = os.path.join(root, name, "protocol.yml")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue

        m = DATE_RE.search(text)
        if not m:
            continue
        try:
            last = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue

        topic_m = TOPIC_RE.search(text)
        growth_m = GROWTH_RE.search(text)
        out.append(
            {
                "topic": topic_m.group(1) if topic_m else name,
                "age": (today - last).days,
                "last": m.group(1),
                "growth": growth_m.group(1).strip() if growth_m else None,
            }
        )
    return out


def main() -> None:
    payload = json.load(sys.stdin)
    cwd = payload.get("cwd") or os.getcwd()

    surveys = scan(cwd)
    if not surveys:
        return

    stale = [s for s in surveys if s["age"] > STALE_DAYS]
    if not stale:
        return

    lines = [
        "research-skills: stale survey state in this project.",
        "",
    ]
    for s in sorted(stale, key=lambda x: -x["age"]):
        growth = f" · field growth {s['growth']}" if s["growth"] else ""
        lines.append(
            f"  {s['topic']}: last searched {s['last']} ({s['age']} days ago){growth}"
        )
    lines += [
        "",
        "Gaps recorded in a stale survey may already be closed, and its",
        "evidence_of_absence is dated. Before writing an absence claim, drafting",
        "related work, or scoring gap-gate G1 against this state, run `watch` to",
        "refresh it — a check that finds nothing still updates last_searched_at and",
        "re-dates every gap.",
    ]

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n".join(lines),
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    # Fail open, always: a guard that raises inside the hook runner blocks real work,
    # which is strictly worse than the guard not existing.
    with contextlib.suppress(Exception):
        main()
    sys.exit(0)
