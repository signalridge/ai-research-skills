#!/usr/bin/env python3
"""PostToolUse guard: absence claims need typed evidence.

"No one has done this" is the highest-risk sentence in research and the cheapest to say.
This fires when prose asserts an absence and no gaps.yml entry backs it with a populated
evidence_of_absence block.

Only active inside a project that has a survey (.research/survey/). Elsewhere it is silent
— it should not nag someone writing a blog post.

Fails open.
"""

import contextlib
import json
import os
import re
import sys

ABSENCE_PATTERNS = [
    r"\bno prior work\b",
    r"\bno existing work\b",
    r"\bno previous work\b",
    r"\bfirst to (?:propose|show|demonstrate|study|explore|introduce|evaluate|address)\b",
    r"\bto (?:the best of )?our knowledge\b",
    (
        r"\b(?:has|have) not been (?:studied|explored|investigated|addressed|evaluated|"
        r"examined|attempted|reported)\b"
    ),
    r"\bremains? (?:largely )?unexplored\b",
    r"\b(?:has|have) never been\b",
    r"\bno one has\b",
    r"\bnobody has\b",
    r"\bunder-?explored\b",
    # CJK
    r"据我们所知",
    r"據我們所知",
    r"尚无(?:相关)?(?:研究|工作)",
    r"尚未有(?:人|研究)",
    r"首次(?:提出|证明|验证|系统)",
]

PATTERN_RE = re.compile("|".join(ABSENCE_PATTERNS), re.IGNORECASE)

WATCHED_SUFFIXES = (".md", ".tex", ".markdown", ".mdx")

REASON = """Unsupported absence claim (research-skills: absence_claim_guard).

{path} asserts an absence:
{quotes}

{diagnosis}

An absence claim is the highest-risk sentence in a paper and the cheapest to write. Back it
or soften it:

  Back it   -> add a gaps.yml entry with evidence_of_absence: >=3 distinct query phrasings
               (verbatim), >=3 venue-years swept, and nearest_prior_work naming the closest
               existing work and why it does not close the gap. `rs-survey` Phase 4 does
               this.

  Soften it -> match the hedging to what you can support:
               high confidence   "To our knowledge, no prior work evaluates X under Y."
               medium confidence "We are not aware of work that evaluates X under Y."
               low confidence    "Existing work on X typically assumes Y."
                                 (assert the pattern, not the absence)
"""


def find_surveys(cwd: str):
    root = os.path.join(cwd, ".research", "survey")
    if not os.path.isdir(root):
        return []
    out = []
    try:
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d):
                out.append(d)
    except OSError:
        pass
    return out


def gaps_evidence_state(survey_dirs):
    """(any gaps.yml found, any with a populated evidence_of_absence)."""
    found = backed = False
    for d in survey_dirs:
        p = os.path.join(d, "gaps.yml")
        if not os.path.exists(p):
            continue
        found = True
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        # Populated means the key exists and at least one query is recorded under it.
        if "evidence_of_absence:" in text and re.search(
            r"queries_run:\s*\n(\s*-\s*\S)", text
        ):
            backed = True
    return found, backed


def main() -> None:
    payload = json.load(sys.stdin)
    cwd = payload.get("cwd") or os.getcwd()
    tool_input = payload.get("tool_input") or {}

    path = tool_input.get("file_path") or ""
    if not path.endswith(WATCHED_SUFFIXES):
        return

    text = tool_input.get("content")
    if text is None:
        text = tool_input.get("new_string") or ""
    if not text:
        return

    surveys = find_surveys(cwd)
    if not surveys:
        return  # not a survey project — stay quiet

    hits = []
    for line in text.splitlines():
        m = PATTERN_RE.search(line)
        if m:
            snippet = line.strip()
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            hits.append(f'  "{snippet}"')
        if len(hits) >= 4:
            break
    if not hits:
        return

    found, backed = gaps_evidence_state(surveys)
    if backed:
        return  # evidence exists; trust it and stay out of the way

    diagnosis = (
        "No gaps.yml exists in this project's survey, so nothing supports the claim."
        if not found
        else "gaps.yml exists but no entry has a populated evidence_of_absence.queries_run."
    )

    json.dump(
        {
            "decision": "block",
            "reason": REASON.format(path=path, quotes="\n".join(hits), diagnosis=diagnosis),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    # Fail open, always: a guard that raises inside the hook runner blocks real work,
    # which is strictly worse than the guard not existing.
    with contextlib.suppress(Exception):
        main()
    sys.exit(0)
