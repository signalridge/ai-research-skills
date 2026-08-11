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

import _payload

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

REASON = """Unsupported absence claim (ai-research-skills: absence_claim_guard).

{path} asserts an absence:
{quotes}

{diagnosis}

An absence claim is the highest-risk sentence in a paper and the cheapest to write. Back it
or soften it:

  Back it   -> add a gaps.yml entry with evidence_of_absence: >=3 distinct query phrasings
               (verbatim), >=3 venue-years swept, and nearest_prior_work naming the closest
               existing work and why it does not close the gap. `ars-survey` Phase 4 does
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


MIN_QUERIES = 3
"""The floor rs_validate already enforces on an absence claim. A guard laxer than the rule
it exists to enforce does not just miss cases — it teaches the rule wrong, because the
author who gets through learns that one phrasing was enough."""

# Parse only the queries_run list inside each top-level gap.  The guard deliberately
# supports the small YAML shape it needs rather than pooling matching list lines from
# unrelated gaps or accepting arbitrary prose as evidence.
GAP_START_RE = re.compile(r"^(?P<indent>[ \t]*)-[ \t]+id\s*:")
KEY_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>evidence_of_absence|queries_run)\s*:\s*(?P<value>.*)$"
)
LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)-[ \t]+(?P<value>\S.*)$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _normalise_query(value: str) -> str:
    value = value.strip()
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
        elif character in "'\"":
            quote = character
        elif character == "#" and (index == 0 or value[index - 1].isspace()):
            value = value[:index].rstrip()
            break
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return re.sub(r"\s+", " ", value).strip().casefold()


def _inline_queries(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    chunks: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for character in value[1:-1]:
        if quote is not None:
            current.append(character)
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
        elif character in "'\"":
            quote = character
            current.append(character)
        elif character == ",":
            chunks.append("".join(current))
            current = []
        else:
            current.append(character)
    if quote is not None:
        return []
    chunks.append("".join(current))
    return [query for chunk in chunks if (query := _normalise_query(chunk))]


def _gap_blocks(text: str) -> list[list[str]]:
    lines = text.splitlines()
    starts = [
        (index, _indent(line))
        for index, line in enumerate(lines)
        if GAP_START_RE.match(line)
    ]
    blocks: list[list[str]] = []
    for position, (start, gap_indent) in enumerate(starts):
        end = len(lines)
        for candidate, candidate_indent in starts[position + 1 :]:
            if candidate_indent == gap_indent:
                end = candidate
                break
        blocks.append(lines[start:end])
    return blocks


def _gap_queries(block: list[str]) -> list[str]:
    if not block:
        return []
    for index, line in enumerate(block):
        evidence = KEY_RE.match(line)
        if not evidence or evidence.group("key") != "evidence_of_absence":
            continue
        evidence_indent = _indent(line)
        end = len(block)
        for candidate in range(index + 1, len(block)):
            if block[candidate].strip() and _indent(block[candidate]) <= evidence_indent:
                end = candidate
                break
        for query_index in range(index + 1, end):
            query = KEY_RE.match(block[query_index])
            if not query or query.group("key") != "queries_run":
                continue
            query_indent = _indent(block[query_index])
            inline = query.group("value").strip()
            if inline:
                return _inline_queries(inline)
            values: list[str] = []
            for item_line in block[query_index + 1 : end]:
                if not item_line.strip():
                    continue
                if _indent(item_line) <= query_indent:
                    break
                item = LIST_ITEM_RE.match(item_line)
                if not item:
                    break
                value = _normalise_query(item.group("value"))
                if value:
                    values.append(value)
            return values
    return []


def gaps_evidence_state(survey_dirs):
    """(any gaps.yml found, any single entry whose evidence clears the query floor).

    Deliberately project-scoped, not matched to the sentence being written: no regex can
    tell which gap a given claim rests on. So this answers the weaker question honestly —
    does this project contain an absence claim worked out to the standard — and the
    reason text says which gap to check rather than pretending to have found it.
    """
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
        if any(len(set(_gap_queries(block))) >= MIN_QUERIES for block in _gap_blocks(text)):
            backed = True
    return found, backed


def main() -> None:
    payload = json.load(sys.stdin)
    cwd = payload.get("cwd") or os.getcwd()
    tool_input = payload.get("tool_input") or {}

    surveys = find_surveys(cwd)
    if not surveys:
        return  # not a survey project — stay quiet

    found, backed = gaps_evidence_state(surveys)
    if backed:
        return  # evidence exists; trust it and stay out of the way

    diagnosis = (
        "No gaps.yml exists in this project's survey, so nothing supports the claim."
        if not found
        else f"gaps.yml exists, but no entry records the {MIN_QUERIES} distinct query "
        f"phrasings an absence claim needs under evidence_of_absence.queries_run."
    )

    # A tool call may contain several Pi edits or a multi-file apply_patch.  Inspect every
    # operation independently; using paths[0] lets a safe first file hide a prose claim in
    # a later file and using one joined text lets evidence from one file authorise another.
    for operation in _payload.operations(tool_input):
        if not operation.path.endswith(WATCHED_SUFFIXES) or not operation.text:
            continue
        hits = []
        for line in operation.text.splitlines():
            m = PATTERN_RE.search(line)
            if m:
                snippet = line.strip()
                if len(snippet) > 160:
                    snippet = snippet[:157] + "..."
                hits.append(f'  "{snippet}"')
            if len(hits) >= 4:
                break
        if hits:
            json.dump(
                _payload.block(
                    REASON.format(
                        path=operation.path,
                        quotes="\n".join(hits),
                        diagnosis=diagnosis,
                    )
                ),
                sys.stdout,
            )
            return


if __name__ == "__main__":
    # Fail open, always: a guard that raises inside the hook runner blocks real work,
    # which is strictly worse than the guard not existing.
    with contextlib.suppress(Exception):
        main()
    sys.exit(0)
