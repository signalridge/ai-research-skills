# Phase 2 — Score

Score every candidate against the question, then screen by threshold. Do not judge
include/exclude directly.

**Exit criteria:** every deduped candidate has `relevance` and `contextual_summary`;
`screen` is derived from the threshold; `counts.adjudicated`, `counts.unsure` and
`counts.scored_at_or_above_threshold` are written.

---

## Why score instead of decide

A binary include/exclude call is irreversible and untunable. Change your mind about the
boundary and you re-read everything.

Scoring separates *how relevant is this* (expensive, done once) from *where is the line*
(cheap, redone freely). retrieval-summary benchmark calls its retrieval/reranking/contextual-summarisation
pattern RCS. The transferable idea is question-conditioned evidence ranking, not the full
agentic-RAG system.

A contextual summary is a navigation aid, not a measured lossless replacement for the
source. Keep it bounded for ARS, but re-read the paper for any load-bearing claim, number,
figure or limitation.

## The scoring pass

For each candidate, from title + abstract (plus a figure if the abstract is uninformative),
produce two things.

### `relevance`: 1–10, against *this* question

Not general quality. Not citation count. **Relevance to the question in `protocol.yml`.**
A landmark paper that does not bear on your question scores low, and that is correct.

**Anchor at 5 and justify movement in both directions.** Starting from "probably relevant"
and adjusting down produces a corpus where everything scores 7. Starting at 5 forces you to
name what moved it. Two kinds of ground move a score up and both count: something the paper
demonstrably does (say which), or a structural reason it must bear on the question (say
which). A record with neither stays at 5.

| Score | Meaning |
|---|---|
| 9–10 | Directly answers the question, or is the obvious baseline any answer must beat |
| 7–8 | Bears on the question; would be cited in the related-work section |
| 5–6 | Adjacent — same problem family, different setting or a different question |
| 3–4 | Same keywords, different problem |
| 1–2 | False positive from search |

Judge with credibility attached: when you have them, factor in citation count and venue.
Not as a quality bar — as a prior on whether the field found the result load-bearing.

### Narrow questions score by method-family centrality

When the question is scoped to a specific method family — LLM agents, say, inside the
parent field of NLP — score by how central that family is to the paper's *contribution*,
not by how relevant the paper is to the parent field. A paper squarely about the parent
field that merely mentions the family scores 3–4 and may not take 5, however famous it is.
A 5 requires the family to be load-bearing: remove it and the paper's contribution
collapses. Otherwise the corpus fills with parent-field landmarks that outrank the work
the question is actually about.

### `contextual_summary`: ≤300 words, written *against the question*

This is not the paper's abstract restated. It answers: **what does this paper contribute to
my question?**

> ✗ "This paper proposes iterative retrieval method, a novel iterative retrieval framework, and demonstrates
>   strong results on several benchmarks."
>
> ✓ "Directly relevant: compares iterative retrieval against a 128k long-context baseline
>   on multi-hop benchmark A and multi-hop benchmark B. Crucially it controls for **token budget**, not
>   retrieval recall — so it does not settle our question, but it is the closest existing
>   design and the natural baseline to extend. Reports +6.2 EM for iterative retrieval;
>   ablation in §5.2 suggests the gain shrinks as the context window grows. No variance
>   over seeds reported."

The second one is useful six months from now. The first is not.

Note what is *missing* as well as what is present — absent ablations and unreported
variance are exactly what Phase 4 needs to discriminate an unexplored cell from an
abandoned one.

## Screen by threshold

```
relevance >= protocol.screen.relevance_threshold  AND  meets include criteria
    → screen: include
relevance <  threshold  OR  hits an exclude criterion
    → screen: exclude   (+ exclude_reason, always)
cannot tell from what you have read
    → screen: unsure
```

### `unsure` is a real answer

Use it when the abstract is uninformative, the full text is inaccessible, or the paper
might be relevant under an interpretation you cannot resolve alone. **Do not force a
binary.**

Cited literature benchmark/literature QA task v2 results illustrate this distinction under a particular model/tool
condition: one Claude 3.5 Sonnet row reportedly answered only **12%** of questions but was
correct on **47%** of those it answered (rounded accuracy **0.06**). The dedicated result
source was not locally re-verified in this audit, so treat it as qualified benchmark context,
not a universal model characteristic. Collapse coverage and precision into one number and
you lose the information that matters.

So report three numbers, not one:

```yaml
counts:
  retrieved: 312
  deduped: 244
  adjudicated: 244                    # coverage — how many you actually judged
  scored_at_or_above_threshold: 61
  unsure: 9
```

If `adjudicated < deduped`, say so explicitly. An unadjudicated tail is **not** the same as
an excluded one, and every downstream exit needs to know the difference.

## Tuning the threshold

After scoring, look at the distribution. Healthy shapes:

- **60 includes, long tail of 3–5s** — threshold is about right.
- **200 includes** — threshold too low, or the question is too broad. Raise to 7 first; if
  that does not help, the scope is the problem.
- **6 includes** — threshold too high, or recall failed in Phase 1. Check `found_via`
  before lowering: if everything came from keyword search, go back to Phase 1 rather than
  loosening the bar.

Re-thresholding is free. Re-reading is not. That is why this phase exists.

## What a search result may and may not tell you

You are working from titles, abstracts and search snippets in this phase. That bounds what
you are entitled to conclude from them.

**Retrieval supports metadata-level judgements only** — that this work exists, who wrote it,
where and when it appeared, and roughly what it addresses. It does **not** support method
details or numbers. A snippet containing "improves accuracy by 6.2 points" is not a source
for 6.2; it is evidence that a number exists somewhere in the paper. Numbers enter the
corpus in Phase 3, from a named table, with `looked_at: true`.

This is the same discipline as `evidence_read`, applied one step earlier. Writing a
`numbers[]` entry in this phase is the concrete mistake it prevents.

**"Not found" is not "does not exist."** If a search for something returns nothing, the
finding is *no work retrieved under these keywords* — never *no such work exists*. That
distinction is the whole of `evidence_of_absence`, and Phase 4 will hold you to it.

## Cost discipline

Scoring reads abstracts, not papers. Use what search already returned. Fetch full text only
in Phase 3, and only for includes.

For an abstract OpenAlex returns as an inverted index, the MCP server reconstructs plaintext
for you — do not try to decode `abstract_inverted_index` by hand.

## Checkpoint

Report the score distribution, the three counts, and the current threshold. Show the user
the 5 highest-scoring records with their summaries — if those look wrong, the scoring rubric
is wrong and everything downstream inherits it.
