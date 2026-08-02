# Phase 4 — Map

Place every include on the grid, diagnose your own recall, then discriminate the empty
cells. This phase is where a survey either earns its gaps or invents them.

**Exit criteria:** `coverage.yml` written with every cell in a non-`undecided` state or
explicitly marked `undecided`; `recall_diagnostic` filled; every promoted gap in `gaps.yml`
has `evidence_of_absence` and `closes_if`.

---

## 1. Populate the grid

Every `screen: include` record has `axes`. Write one `cells` entry per grid coordinate,
listing the corpus keys that land there.

```yaml
cells:
  - coords: {method: iterative retrieval, control: fixed token budget, evaluation: 2-hop}
    occupants: [sample2025iterative, sample2025longcontext]
    state: occupied
  - coords: {method: iterative retrieval, control: fixed retrieval recall, evaluation: 2-hop}
    occupants: []
    state: undecided        # <- not yet a gap. Section 3 decides.
```

`undecided` is the honest default for every empty cell until you have discriminated it.

## 2. Recall self-diagnostic — do this before looking at gaps

Count includes by `found_via` mode:

```yaml
recall_diagnostic:
  includes_by_mode: {keyword: 44, citation_chain: 31, venue_author: 12}
  note: "Citation chaining contributed 31 includes, 19 of which keyword search never returned."
```

Read it honestly:

| Pattern | What it means |
|---|---|
| All three contribute meaningfully | Recall is probably fine. Proceed. |
| `citation_chain` ≈ 0 | **Your search was keyword-shaped.** Go back to Phase 1. Chaining is terminology-blind and normally finds papers keywords cannot. Near-zero means the seeds were wrong or the chains were never walked. |
| `keyword` ≈ 0 | Your query terms do not match how the field writes. Extract terminology from the papers chaining found, and re-run Mode A with it. |
| `venue_author` ≈ 0 | Either you did not sweep, or the work is genuinely scattered. Check which. |

**Do not proceed to gap analysis on a bad diagnostic.** Every gap you find will be an
artifact of the recall hole. This check costs a minute and it is the cheapest insurance in
the whole survey.

## 3. Discriminate the empty cells

An empty cell has three explanations and only one of them is a research gap:

- **unexplored** — nobody tried. A candidate gap.
- **abandoned** — people tried, it did not work or stopped mattering, the field moved on.
  Not a gap; a warning.
- **recall miss** — work exists and you did not find it. Not a gap; a bug.

Treating "unoccupied" as "unexplored" is how people pick dead topics. Run this for each
empty cell, in order.

### Step A — rule out a recall miss

Search for that exact combination directly, with at least three distinct phrasings, naming
the axis values in the query. Add a forward citation chain from the nearest occupied cell's
best paper.

If you find work → the cell was never empty. Add the record and move on. This happens more
often than you would expect, and it is the single highest-value check in the phase.

### Step B — unexplored or abandoned?

Take the neighbouring occupied cells (vary one axis value) and look at *when* their work
was published:

```
openalex → openalex_analyze_trends(
  entity_type: "works",
  group_by: "publication_year",
  filters: {"title_and_abstract.search": "<neighbour cell's characteristic terms>"}
)
```

| Neighbour trend | Reading |
|---|---|
| Rising through the current year | Area is live; this specific combination is plausibly **unexplored** |
| Peaked ≥3 years ago, now declining | Area was worked and left; likely **abandoned** — find out why before touching it |
| Flat and thin throughout | The axis value may be a dead end, or the grid is wrong |

Clamp future-dated buckets before reading a trend — OpenAlex records carry
publisher-declared dates and a `2028` bucket is a data artifact, not a prediction. Treat
the current year as partial.

Record the readout in `trend_evidence`. A cell called `unexplored` with no trend evidence is
a guess wearing a label.

### Step C — when you cannot tell, say `undecided`

`undecided` is a legitimate final state. It says: this cell is empty, and I could not
establish why. That is far more useful than a confident `unexplored` that sends someone
into an abandoned area.

## 4. Promote to gaps

Only `unexplored` cells become gaps. Write each into `gaps.yml`:

```yaml
gaps:
  - id: G1
    statement: "No work evaluates agentic retrieval against long-context baselines with
                retrieval recall held constant."
    type: unvalidated-comparison
    evidence_of_absence:
      queries_run:
        - 'abs:"retrieval recall" AND abs:"long context" AND abs:"multi-hop"'
        - 'ti:"controlled comparison" AND abs:"retrieval augmented"'
        - "matched retrieval budget long context agent QA"
      venues_swept: ["ICLR@2025-2026", "NeurIPS@2025", "ACL@2025-2026", "COLM@2025"]
      citation_chains: ["W2626778328:cites:1", "W4391234567:cited_by:1"]
      nearest_prior_work:
        - {key: sample2025iterative, why_not_it: "controls token budget, not retrieval recall"}
      last_checked: 2026-08-03
    confidence: medium
    closes_if: "Any paper reporting multi-hop QA with retrieval recall matched across
                agentic and long-context arms."
```

### `nearest_prior_work` is not optional in practice

A gap with **no** nearest prior work usually means the search was too narrow, not that the
gap is wide open. Real gaps sit next to something. If you cannot name the closest existing
work and say precisely why it does not close the gap, go back to Step A.

### `closes_if` — write the falsifier now

This is what `watch` re-tests against every new paper, forever. It must be decidable from a
title plus an abstract.

> ✓ "Any paper reporting multi-hop QA with retrieval recall matched across agentic and
>   long-context arms."
>
> ✗ "Any paper that solves this problem." — not decidable
> ✗ "Better multi-hop retrieval." — not decidable

Without a pre-registered falsifier a gap closes silently, and you find out at submission.

### Confidence

| Level | Requires |
|---|---|
| `high` | ≥3 distinct phrasings, ≥3 venue-years swept, forward chains from the nearest prior work, **and** a non-empty `nearest_prior_work` |
| `medium` | 3 phrasings, but an incomplete venue sweep or no identified nearest prior work |
| `low` | anything less — say so rather than rounding up |

`rs_validate` enforces the `high` bar. It will not let you claim it on thin evidence.

## Checkpoint

Report the filled grid, the recall diagnostic, and each candidate gap with its confidence.
State explicitly how many empty cells you left `undecided` — that number is a feature, and
hiding it is how a survey oversells itself.
