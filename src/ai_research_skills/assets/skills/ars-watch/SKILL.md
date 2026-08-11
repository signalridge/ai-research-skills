---
name: ars-watch
description: >
  Keep a completed survey true over time — re-run its search protocol, diff against the
  existing corpus, and re-test every research gap's pre-registered falsifier against new
  papers. Use when the user asks to monitor a topic, set up alerts for new papers, check
  what is new since last time, see whether a gap has closed, or keep a survey current.
  Also use to arm a standing subscription. Requires a completed survey at phase 5.
---

# watch — the protocol is the subscription

A survey is a snapshot. In a field growing 3× a year, a snapshot is wrong within weeks.

`ars-watch` is not a new search. It is **re-running `protocol.yml`** and asking one question
that matters more than the rest: *has anything closed one of my gaps?*

## Two modes

```
/ars-watch arm      # register the standing subscription, once
/ars-watch check    # run a digest now  (also: "what's new on X")
```

## Preconditions

`protocol.yml` at `phase: 5` with a `last_searched_at`, and `gaps.yml` whose entries carry
`closes_if`. A gap without a falsifier cannot be watched — send it back to `ars-survey` Phase 4.
Watch is the only post-survey skill permitted to update `corpus.jsonl`, `protocol.yml`, or
`gaps.yml`, and it may do so only by replaying this frozen protocol; red-team discoveries go
back to survey rather than being appended here.

---

## Arm

Register the topic as a standing arXiv subscription:

```
arxiv → watch_topic(
  topic: "<the primary keyword query from protocol.recall_modes.keyword>",
  categories: ["cs.LG", "cs.CL", "cs.CV", "cs.AI", "cs.MA", "stat.ML"],
  max_results: 20
)
```

That is the default AI set — reuse whatever narrowing Phase 1 settled on rather than this
full list if the survey narrowed it.

Set the cadence from the survey's `saturation.baseline_growth`:

| Growth | Cadence |
|---|---|
| >2×/yr | weekly |
| ~1.5×/yr | monthly |
| flat | quarterly |

Then offer to schedule it — `/loop` for a session-length watch, or the `schedule` skill for
a cloud routine that survives the session. Do not schedule without asking; a recurring job
is the user's call.

## Check

### 1. New candidates

```
arxiv → check_alerts()                    # everything since the last check
```

Plus a bounded re-run of the protocol's own queries with a date floor:

```
arxiv → search_papers(query: <verbatim from protocol>, date_from: <last_searched_at>)

openalex → openalex_get_citation_graph(
  seed_id: <one seed>, direction: "cites",
  filters: {"from_publication_date": "<last_searched_at>"}, per_page: 100)
# Repeat one bounded call for each of the top three seeds; seed_id is singular.
```

Forward chains from the seeds are the highest-yield part. New work that engages your
question cites the same ancestors, whatever it calls itself.

Do not re-run the full venue sweep every check. Once a quarter is enough, and it is the
expensive one.

### 2. Test every `closes_if` — this is the point

For each open gap, evaluate its falsifier against every new paper from title + abstract.

```
G1 closes_if: "Any paper reporting multi-hop QA with retrieval recall matched
               across agentic and long-context arms."
```

Three outcomes, and be strict about the middle one:

| Outcome | Action |
|---|---|
| **Closed** | The falsifier is satisfied. Flag loudly. Set typed `closes_if_met: {key, date, rationale}` with the closing paper's key and date. |
| **Threatened** | Close but not decisive — a different benchmark, one arm only, a workshop abstract. Record `threats: [{key, date, unmet_clause}]` and say exactly which clause is unmet. |
| **Open** | No match. Update `evidence_of_absence.last_checked` to today. |

That last row is quiet but load-bearing: **a check with no findings still refreshes the
gap's freshness**, which is what keeps `ars-gap-gate` G1 scorable and the staleness hook silent.

With one qualifier: **only a zero-hit answer from a backend that responded refreshes
`last_checked`.** A query that failed — timeout, rate limit, backend unreachable — makes
this check inconclusive for that gap: say so plainly in the digest and leave the state
untouched. A failed search must not manufacture freshness; a gap whose last real check was
three months ago should look exactly three months old.

### 3. Corpus updates

- preprint → camera-ready (venue and year change; **numbers may change**)
- v2+ of a paper already in the corpus
- retractions and withdrawals

A number that changed between versions is worth more attention than a new paper, because a
draft may already be quoting the old one.

---

## Digest

Write `.research/survey/<slug>/digests/<date>.md`, three sections, this order:

```markdown
# Watch digest — <topic> — <date>
Since <last_searched_at> · <n> new candidates · OpenAlex spend $<x>

## 1. Gap movement          <- the alarm. Empty is a valid and common result.
**G1 CLOSED by [sample2026matched]** — reports multi-hop benchmark A with retrieval recall matched
across both arms (Table 2). The gap is closed; gap-gate G1 for this candidate is now 1.
**G2 threatened by [liu2026partial]** — matches on setting but evaluates 2-hop only;
the "3+-hop" clause is unmet.

## 2. Corpus updates
[sample2025iterative] preprint → ICLR 2026 camera-ready. EM 6.2 → 5.8. Any draft quoting
6.2 needs updating.

## 3. Adjacent
<on-topic, moves nothing. One line each. Do not pad this section.>
```

Section 1 empty is normal and worth stating plainly — "no gap movement" is information.

## Update state

Every check, without exception:

- append new records to `corpus.jsonl` (`found_via: "watch:<date>"`), scored the same way
  Phase 2 scores anything — a watch hit is not automatically an include
- set `protocol.yml.last_searched_at` to today (this silences the staleness hook)
- refresh `last_checked` on every gap you tested
- record OpenAlex spend

A check that finds nothing but does not update `last_searched_at` is worse than no check:
the survey looks stale when it is not, and the next reader distrusts a current artifact.

## When a gap closes

Say it plainly, immediately, and do not soften it. If the user is working on that gap, this
is the most valuable message this suite will ever send them.

Then offer: re-run `ars-gap-gate` to see whether a neighbouring candidate survives, or
`ars-survey` Phase 4 to re-map now that the closing paper is in the corpus.

## Handoffs

- **Upstream:** re-runs `protocol.yml` verbatim — the contract `ars-survey` froze at
  `phase: 5`.
- **Writes:** only at Phase 5: replays the frozen protocol, appends scored candidates to
  `corpus.jsonl`, updates `protocol.yml`/gap freshness and typed closure or threat state,
  and writes a digest. It does not freely discover a new corpus outside that replay.
- **Downstream:** keeps `ars-gap-gate` G1 scorable and the staleness hook silent by
  re-testing every gap's `closes_if` against each new paper.
- `/ars-watch` is the command form.
