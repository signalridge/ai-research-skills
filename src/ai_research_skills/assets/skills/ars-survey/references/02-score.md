# Screening card — optional

When the user asks to screen sources, define relevance against the question and explain each
selection briefly.

## Screening annotates; it does not delete

Keep `include`, `exclude`, and `unsure` distinct when those fields exist in the workspace, and
keep the excluded records with their reason rather than dropping them. A reader who disagrees
with a judgement can then see what was set aside and why, which a shortened list cannot show.
Do not force an unresolved source into a binary decision — `unsure` is a real answer, and so is
"too few candidates so far to judge relative relevance".

## If a numeric score helps

The corpus `relevance` field is an integer from 1 to 10. It is optional, but a score only helps
later if the bands mean something stable, so say what they mean when the run starts. One
workable reading:

| Band | Meaning |
|---|---|
| 9–10 | directly answers the question, or is the closest existing attempt at it |
| 7–8 | changes the answer's confidence, conditions, or framing |
| 5–6 | relevant background; cite-able but not load-bearing |
| 3–4 | adjacent topic, retained only for coverage or terminology |
| 1–2 | matched the query but not the question |

A threshold is a knob the user sets, not a property of the field. State the threshold used, so
raising or lowering it later is a re-read of the same ledger rather than a new screen.

## What to report

Say how many candidates were retrieved, how many were inspected, and how many were not — an
unscreened remainder is a coverage limit worth naming, and it is the number that tells a reader
how much the selection could still change. Exclusion reasons are most useful when they name a
criterion ("no empirical evaluation", "single-hop only") rather than a verdict ("not relevant").
Preserve the query and source provenance on every record either way.
