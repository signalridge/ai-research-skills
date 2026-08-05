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
  includes_by_mode: {keyword: 44, citation_chain: 31, venue_author: 12, contrarian: 6}
  note: "Citation chaining contributed 31 includes, 19 of which keyword search never returned. The contrarian pass found 6, including the two that disagree with the majority result."
```

Read it honestly:

| Pattern | What it means |
|---|---|
| All four contribute meaningfully | Recall is probably fine. Proceed. |
| `citation_chain` ≈ 0 | **Your search was keyword-shaped.** Go back to Phase 1. Chaining is terminology-blind and normally finds papers keywords cannot. Near-zero means the seeds were wrong or the chains were never walked. |
| `keyword` ≈ 0 | Your query terms do not match how the field writes. Extract terminology from the papers chaining found, and re-run Mode A with it. |
| `venue_author` ≈ 0 | Either you did not sweep, or the work is genuinely scattered. Check which. |
| `contrarian` ≈ 0 | Either the result is genuinely uncontested, or you searched the consensus vocabulary a fourth time. **Say which you believe** — a survey that found no disagreement because it never looked reports a consensus it manufactured. |

**Do not proceed to gap analysis on a bad diagnostic.** Every gap you find will be an
artifact of the recall hole. This check costs a minute and it is the cheapest insurance in
the whole survey.

### Read the excludes before the gaps

The `screen: exclude` records are a blind-spot signal, not waste. If the excludes cluster
on a theme the protocol never stated — nine papers excluded as "retrieval for code" when
`scope.out` says nothing about code — Phase 0 missed an axis the field actually varies
along. Go back to Phase 0 and declare it. The alternatives are both worse: forcing those
papers into a grid they do not fit, or leaving a cluster of same-reason excludes that
silently marks where your taxonomy stops.

## 3. Discriminate the empty cells

An empty cell has four explanations and they point in opposite directions:

- **unexplored** — nobody tried. A candidate gap.
- **abandoned** — people tried, it did not hold up, the field moved on. A warning.
- **avoided** — the field keeps *naming* it as an open problem and nobody attempts it,
  usually because it is hard. Often the **highest-value** target you will find.
- **recall miss** — work exists and you did not find it. Not a gap; a bug.

Two of these are traps in opposite directions. Treating "unoccupied" as "unexplored" is how
people pick dead topics. Treating "avoided" as "abandoned" is how they walk past the best
one — an old, large, acknowledged problem that everyone routes around is not evidence that
nobody cares; it is usually evidence that it is difficult, which is a different thing
entirely.

Run this for each empty cell, in order.

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
| Peaked ≥3 years ago, now declining | The work stopped. Go to Step C — stopping has two opposite causes |
| Flat and thin throughout | The axis value may be a dead end, or the grid is wrong |

**Temporal silence is not a verdict.** "The work stopped" has two readings — abandoned,
or *solved*, and those point in opposite directions. A peaked-and-declining neighbourhood
never convicts on its own: before reading it as abandonment, run one targeted search for
the paper that declares success (`"<gap phrasing>" achieves`, `outperforms`, `solves`).
Find one and the cell is not empty in any useful sense — the problem was closed, not
dropped. Find none and Step C's discrimination proceeds.

Clamp future-dated buckets before reading a trend — OpenAlex records carry
publisher-declared dates and a `2028` bucket is a data artifact, not a prediction. Treat
the current year as partial.

Record the readout in `trend_evidence`. A cell called `unexplored` with no trend evidence is
a guess wearing a label.

### Step C — the work stopped: abandoned, or avoided?

Only for cells where Step B says activity stopped or never started despite a live
neighbourhood. This is the step that separates a dead end from the best gap in the grid,
and there is a directly searchable signal.

**Count who names it without attempting it.** A problem the field has given up on stops
being mentioned. A problem the field is avoiding gets named over and over — in future-work
sections, in limitations, in "we leave this to subsequent work".

```
arxiv → search_papers(query: 'abs:"<the gap phrasing>" AND abs:"future work"')
arxiv → search_papers(query: 'abs:"<the gap phrasing>" AND abs:"remains an open"')
tavily → tavily_search(query: "<gap phrasing> open challenge limitation")
```

Then read what those papers do about it:

| Signal | Reading |
|---|---|
| Several papers across ≥2 years name it as future work or a known limitation, none attempt it | **avoided** — and each of those papers is a citer waiting for you |
| Papers explicitly report trying and failing, or a later method supersedes the whole approach | **abandoned** — read the failure before you repeat it |
| Nobody mentions it at all | **unexplored** — back to Step B's reading |

**Filter motivated framing before counting failure language.** "X fails, therefore we
propose Y" is a paper selling its own attempt, not the field rendering a verdict —
authors dramatise the failure their method exists to fix. Failure wording counts as
`abandoned` evidence only when it is a *retrospective* judgement on the gap topic itself:
a survey, a post-mortem, a third party's limitations section. When the same paper goes on
to propose the fix, it is an attempt — record it as one and track how the attempt ended,
do not count it as a verdict.

An `avoided` cell inverts the usual G2 reading: the repeated future-work mentions *are* the
contribution evidence, because each one names a group that would cite the result. Record
them in `trend_evidence` with keys — `rs-gap-gate` G2 reads exactly this.

Be careful in one direction: "hard" and "not worth doing" both produce avoidance. If every
paper naming it also explains *why* it is intractable, and that reason still holds, you have
found a wall rather than a gap. Say which you believe and on what basis.

**An `abandoned` verdict gets one more question: what exactly failed?** When the failure
evidence names a specific tool or method as the blocker — the approach died *because* X
could not do Y — search the corpus for a documented successor that removes the blocker.

- Found, and the key is a real `corpus.jsonl` key (never a plausible one from memory) →
  record it as `revivable_by`. The cell is now promotable (§4): this is the "newly
  possible" shape, a gap that was intractable and quietly became tractable — the highest
  reward-to-risk opening on the grid.
- Not found → `revivable_by: null`, and the cell stays `abandoned`, unpromoted. The null
  is load-bearing: it is what stops a dead end being optimistically relabelled.

### Step D — when you cannot tell, say `undecided`

`undecided` is a legitimate final state. It says: this cell is empty, and I could not
establish why. That is far more useful than a confident `unexplored` that sends someone
into an abandoned area.

## 4. Promote to gaps

Only `unexplored` and `avoided` cells become gaps. `abandoned` does not — with one
exception: an `abandoned` cell carrying a non-null `revivable_by` is promotable, because
its failure is attributed to a specific tool and the corpus documents the successor. The
gap statement names that successor; `rs-gap-gate` reads the cell as the "newly possible"
shape. An `abandoned` cell with `revivable_by: null` stays a warning. Write each into
`gaps.yml`:

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
        - {key: sample2025iterative, why_not_it: "controls token budget, not retrieval recall",
           differing_axis: problem-setting}
      last_checked: 2026-08-03
    confidence: medium
    closes_if: "Any paper reporting multi-hop QA with retrieval recall matched across
                agentic and long-context arms."
```

### `nearest_prior_work` is not optional in practice

A gap with **no** nearest prior work usually means the search was too narrow, not that the
gap is wide open. Real gaps sit next to something. If you cannot name the closest existing
work and say precisely why it does not close the gap, go back to Step A.

**Name the axis that differs.** "Why it is not the same" has to resolve to a specific
difference, and there are only four kinds worth recording:

| `differing_axis` | The prior work differs in |
|---|---|
| `object-acted-on` | what the method operates on |
| `mechanism` | how it achieves the effect |
| `input-granularity` | the resolution or unit it consumes |
| `problem-setting` | the conditions or assumptions of the task |
| `none` | **nothing. It closes the gap.** |

The rule cuts both ways, and the second direction is the one people skip: a similar title
never establishes that your gap is taken, and failing to find even one differing axis
establishes that it is. If you work through all four and none of them differ, record
`none` and drop the gap. Do not go looking for a fifth axis — reaching for a distinction
after the first four came up empty is how a closed gap survives to become a wasted quarter.

### `closes_if` — write the falsifier now

This is what `rs-watch` re-tests against every new paper, forever. It must be decidable from a
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
