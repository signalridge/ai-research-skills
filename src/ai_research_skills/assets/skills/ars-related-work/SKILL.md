---
name: ars-related-work
disable-model-invocation: true
description: >
  Draft a user-requested related-work or literature-review section from supplied sources,
  direct searches, notes, or an optional .research survey workspace. Organise by meaningful
  themes, cite claims precisely, preserve disagreement, and state evidence limits. It is a
  standalone writing skill and may search when the user explicitly asks.
---

# ars-related-work — sources to synthesis

Use this skill when the user wants related work, background, or a literature-review section.
It does not require a completed survey. Start from the supplied corpus or search directly if
the request includes discovery. If `.research/survey/<slug>/` is named, read whichever files
are present; missing `coverage.yml`, `refs.bib`, or other artifacts are limitations, not
prerequisite failures.

## Drafting method

1. Clarify the target audience, length, citation style, and central question.
2. Group work by the distinctions that matter to that question (method, setting, data,
   evaluation, or another explicit theme), not by a mechanical paper-per-paragraph list.
3. Attach a stable source key or citation to each factual claim while drafting.
4. Compare conditions and disagreements. Do not turn one paper's claim into a field-wide fact.
5. Match wording to what was read: an abstract supports less detail than a methods/results
   read. Quote a number only with a table, figure, page, or other precise location.
6. Mark missing sources, unresolved identifiers, and unsupported claims plainly. Search for a
   missing source only when the user asks; otherwise leave an intake note.

A source record may have `phase`, `screen`, or other legacy fields. Use them as notes, not as
permission checks. If the user asks to write into a named workspace, preserve existing files
and write only the requested draft.

## Citations and absence language

Use the project's citation format. If generating BibTeX, keep stable keys and record the
identifier, tool/source, and date as explicit provenance. `ars-verify` can be invoked by the
user for identifier and number checks; this skill does not treat a provenance comment as proof.

For "no prior work" statements, bound the claim by the searched sources and date, and prefer
careful wording such as "we did not find" when the search is narrow. Provenance is an
integrity guideline, not an automatic workflow gate.

## LaTeX

If the requested output is LaTeX, compile it, read the log, and fix errors. Do not add a
separate documentation validation pipeline or placeholder citations.

## Evidence states and boundaries

With usable sources, tie factual prose to stable keys and locations; with partial sources, narrow the section and state unresolved coverage. With zero usable evidence, do not invent citations, numbers, or a deterministic sourced report: report the attempted scope, limits, and smallest next reading. Abstract-only records require softened wording. Ask only the smallest clarification when ambiguity materially changes the section. This skill never invokes another skill or creates or repairs a workspace automatically.

## Output

Return or write the requested section, followed by:

- themes used and source scope;
- evidence depth and unresolved disagreements;
- claims softened or left out; and
- the smallest follow-up search or reading that would improve it.
