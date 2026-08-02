# Phase 0 — Scope

Turn a topic into a question, and a question into a grid. Nothing is searched in this phase.

**Exit criteria:** `protocol.yml` exists with an interrogative `question`, `scope.in`,
`scope.out`, and `axes` — and the axes were written **before** any search ran.

---

## 1. Topic → question

A topic is a noun phrase. A question ends in `?` and has an answer that could come out
either way.

| Topic (not enough) | Question (workable) |
|---|---|
| "RAG for agents" | "Do retrieval-augmented agents outperform long-context models on multi-hop QA when retrieval recall is held constant?" |
| "efficient attention" | "Which sub-quadratic attention variants retain full-attention quality at ≥32k context on retrieval-heavy tasks?" |
| "LLM evaluation" | "Do LLM-judge scores agree with human preference rankings on open-ended generation, and where do they diverge?" |

Ask the user for the question if the topic is all you have. Do not invent it — a question
you made up will produce a survey that answers something they did not ask.

Then apply one test: **what result would change the answer?** If you cannot name a finding
that would flip it, the question is a topic wearing a question mark.

## 2. In and out of scope

Write both. `scope.out` is the more useful half — it is what stops the corpus sprawling.

```yaml
scope:
  in:  [multi-hop QA, agentic retrieval, long-context baselines]
  out: [single-hop QA, RAG for code, multimodal retrieval]
  window: 2023-01-01..
  venues: [NeurIPS, ICLR, ICML, ACL, EMNLP, COLM]
```

Pick `window` from when the *technique* became possible, not from a round number. For
anything post-dating instruction-tuned LLMs, 2023 is usually the real floor; going back to
2018 mostly adds papers you will exclude.

## 3. Axes — declare them now

**This is the load-bearing step of the whole survey.**

The axes are the dimensions along which papers in this area differ. They come from the
*structure of the question*, not from reading papers.

For "do agentic retrieval methods beat long-context models on multi-hop QA at equal
retrieval recall", the question already names its own axes:

```yaml
axes:
  - name: method
    values: [single-shot retrieval, iterative retrieval, long-context, hybrid]
  - name: control
    values: [no control, fixed token budget, fixed retrieval recall]
  - name: evaluation
    values: [single-hop, 2-hop, 3+-hop]
```

### Why before, not after

If you build the taxonomy after reading, the taxonomy describes *your sample*, not the
field. Every empty cell is then an artifact of what you happened to find — and empty cells
are what you will later call research gaps. A post-hoc taxonomy manufactures fake gaps and
hides real ones.

### Sizing rule

Total cells = product of all axis value counts. **Keep it under ~40.**

- 3 axes × (4, 3, 3) values = 36 cells. Workable.
- 4 axes × (5, 4, 4, 3) = 240 cells. Almost all empty — and every empty one looks like a
  gap. This is a broken grid, not a discovery.

If you exceed ~40, either drop an axis (it is probably a property, not a dimension) or
collapse values. A grid whose cells are mostly empty tells you nothing; a grid where most
cells are occupied makes the empty ones mean something.

### Sanity check

Name a well-known paper in the area and place it on the grid. If it does not fit any cell,
an axis is wrong. If it fits several, the values overlap.

## 4. Seeds

Ask for 1–3 papers the user already trusts. Seeds matter more than keywords: Phase 1's
citation chaining runs from them, and that mode routinely outperforms keyword search on
recall.

If the user has none, find them in Phase 1 with a keyword pass first, pick the 2–3
highest-cited on-topic results, and record them as seeds.

Resolve each seed to an OpenAlex ID *now* and store it — everything downstream reuses it,
and singleton lookups are free.

```
openalex_resolve_name(query: "<paper title>", entity_type: "works")
```

Disambiguate by **citation count + author**, never title alone. Six distinct works share
the title "Attention Is All You Need"; only one is the transformer paper. And do not pass
an arXiv DOI (`10.48550/arXiv.…`) — OpenAlex does not index works under it and you get a
404.

## 5. Screening criteria and threshold

```yaml
screen:
  include: ["evaluates >=2-hop", "reports a retrieval-quality ablation"]
  exclude: ["survey papers", "no empirical evaluation", "single-hop only"]
  relevance_threshold: 6
```

Criteria must be checkable from a title + abstract + one figure. "High quality" is not a
criterion; "reports variance over ≥3 seeds" is.

Start `relevance_threshold` at 6. It is tunable later without re-reading anything — that is
the entire point of scoring rather than judging (Phase 2).

## 6. Write protocol.yml

Fill everything except `recall_modes` (Phase 1 writes it), `counts`, and `saturation`. Set
`phase: 0` and `created` / `last_searched_at` to today.

Then validate before moving on:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rs_validate.py" .research/survey/<slug>
```

## Checkpoint

Show the user the question, the scope boundaries, and the grid. **Wait for confirmation
before Phase 1.** Searching is the expensive part; a wrong grid discovered at Phase 4 costs
the whole survey, and this is the cheapest moment to be wrong.
