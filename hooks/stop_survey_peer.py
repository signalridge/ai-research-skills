#!/usr/bin/env python3
"""Stop hook: what is this survey actually resting on?

Reads corpus.jsonl deterministically at the end of a turn and warns when the state does not
support the confidence a reader will assume: conclusions built on abstracts, an
unadjudicated tail presented as screened, gaps with no nearest prior work, or recall that
came from a single mode.

Advisory by design. It emits a user-visible warning and never blocks — a blocking Stop hook
that fires on a persistent condition loops forever.

Fails open.
"""

import contextlib
import json
import os
import re
import sys

ABSTRACT_SHARE_WARN = 0.5  # includes that are abstract-only
COVERAGE_WARN = 0.9  # adjudicated / deduped
SINGLE_MODE_WARN = 0.8  # share of includes from one recall mode


def load_corpus(path):
    records = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return records


def audit(survey_dir):
    findings = []
    slug = os.path.basename(survey_dir)

    includes = [
        r
        for r in load_corpus(os.path.join(survey_dir, "corpus.jsonl"))
        if r.get("screen") == "include"
    ]
    if not includes:
        return findings

    # 1. Depth — what are conclusions actually resting on?
    shallow = [r for r in includes if r.get("evidence_read") in (None, "abstract")]
    share = len(shallow) / len(includes)
    if share >= ABSTRACT_SHARE_WARN:
        findings.append(
            f"{slug}: {len(shallow)} of {len(includes)} includes ({share:.0%}) are "
            f"abstract-only. An abstract states what the authors wanted to claim, not what "
            f"they showed — anything characterising results is unsupported."
        )

    # 2. Coverage — was the tail adjudicated or quietly dropped?
    proto = os.path.join(survey_dir, "protocol.yml")
    try:
        with open(proto, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        dedup = re.search(r"^\s*deduped:\s*(\d+)", text, re.MULTILINE)
        adjud = re.search(r"^\s*adjudicated:\s*(\d+)", text, re.MULTILINE)
        if dedup and adjud:
            d, a = int(dedup.group(1)), int(adjud.group(1))
            if d > 0 and a / d < COVERAGE_WARN:
                findings.append(
                    f"{slug}: {a} of {d} candidates adjudicated ({a / d:.0%}). The "
                    f"unadjudicated tail is not an excluded one — say so in any handoff."
                )
    except OSError:
        pass

    # 3. Recall — how much would be lost if one mode had not run? Count includes that ONLY
    #    that mode surfaced; per-mode hit counts would double-count the healthy overlap.
    exclusive = {}
    for r in includes:
        found_modes = {fv.split(":", 1)[0] for fv in (r.get("found_via") or [])}
        if len(found_modes) == 1:
            m = found_modes.pop()
            exclusive[m] = exclusive.get(m, 0) + 1
    if exclusive:
        top, n = max(exclusive.items(), key=lambda kv: kv[1])
        if n / len(includes) >= SINGLE_MODE_WARN:
            findings.append(
                f"{slug}: {n} of {len(includes)} includes were surfaced by '{top}' and no "
                f"other mode. Recall rests on one mode; red-team checkpoint A2 covers this."
            )

    # 4. Gaps with no nearest prior work — usually too-narrow search, not open field.
    gaps_path = os.path.join(survey_dir, "gaps.yml")
    try:
        with open(gaps_path, encoding="utf-8", errors="replace") as fh:
            gaps_text = fh.read()
        n_gaps = len(re.findall(r"^\s*-\s*id:\s*G\d+", gaps_text, re.MULTILINE))
        n_near = len(
            re.findall(r"^\s*nearest_prior_work:\s*\n\s*-\s*\S", gaps_text, re.MULTILINE)
        )
        if n_gaps and n_near < n_gaps:
            findings.append(
                f"{slug}: {n_gaps - n_near} of {n_gaps} gaps have no nearest_prior_work. "
                f"Real gaps sit next to something; an empty one usually means the search "
                f"was too narrow, not that the field is open."
            )
    except OSError:
        pass

    return findings


def main() -> None:
    payload = json.load(sys.stdin)
    cwd = payload.get("cwd") or os.getcwd()

    root = os.path.join(cwd, ".research", "survey")
    if not os.path.isdir(root):
        return

    findings = []
    try:
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d):
                findings.extend(audit(d))
    except OSError:
        return

    if not findings:
        return

    msg = "research-skills — what this survey rests on:\n" + "\n".join(
        f"  · {f}" for f in findings
    )
    json.dump({"systemMessage": msg, "suppressOutput": True}, sys.stdout)


if __name__ == "__main__":
    # Fail open, always: a guard that raises inside the hook runner blocks real work,
    # which is strictly worse than the guard not existing.
    with contextlib.suppress(Exception):
        main()
    sys.exit(0)
