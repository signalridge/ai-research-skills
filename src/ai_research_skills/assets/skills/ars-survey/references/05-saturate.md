# Phase 5 — Saturate

Decide whether the search is done, then freeze the protocol.

**Exit criteria:** `saturation` block written with a growth baseline; `phase: 5`;
`last_searched_at` current. The survey is now a durable artifact that `ars-watch` can maintain.

---

## The stop rule is not a count

"Minimum 15 sources" and "60 verified references" measure effort, not coverage. The
question is not *have I read enough* but *would another round change anything*.

## Separate the two kinds of "new"

This is the part that fixed-threshold stop rules get wrong.

Run another full round — all four recall modes, fresh queries. The new on-topic papers it
returns split into two populations, and they mean opposite things:

| Population | Meaning | Fixed by |
|---|---|---|
| **Published before `protocol.created`** | You *missed* these. Recall failure. | More rounds — this is what saturation measures |
| **Published after `protocol.created`** | These did not exist when you started. Field growth. | `ars-watch`, not more rounds |

**Saturation is measured only on the first population.**

```
saturation_ratio = (new on-topic papers published BEFORE protocol.created)
                 / (total includes)
```

Stop when this is under ~5%. If you compute it over all new papers, a fast-moving field can
never converge and you will search forever chasing publications that are simply appearing.

## Get the growth baseline

You still need the growth rate — not for the stop rule, but to size the watch interval and
to date the survey's shelf life.

```
openalex → openalex_analyze_trends(
  entity_type: "works",
  group_by: "publication_year",
  filters: {"title_and_abstract.search": "<core topic terms>"}
)
```

Reading the output:

- **Drop future-dated buckets.** A `2028: 2` bucket is a data artifact. Records carry
  publisher-declared dates that can be wrong.
- **The current year is partial.** If it is August and the current year already exceeds
  last year's total, growth is *understated*, not overstated. Do not annualize naively; just
  note it.

A real example, on "retrieval augmented generation":

```
2023: 323   2024: 3,236   2025: 9,915   2026: 14,086 (partial year)
```

Roughly 3× per year. Write it down:

```yaml
saturation:
  rounds: 3
  new_on_topic_last_round: 2          # pre-`created` only
  baseline_growth: "~3x/yr (2023→2025), 2026 partial"
  stop_rule: "<5% new on-topic published before protocol.created"
```

## What growth implies

| Growth | Watch interval | Survey shelf life |
|---|---|---|
| >2×/yr | weekly | ~4 weeks |
| ~1.5×/yr | monthly | ~3 months |
| flat | quarterly | ~1 year |

At 3×/yr, a six-week-old survey has missed a meaningful slice of the field. The
`survey_staleness` hook warns at 30 days for exactly this reason. In a field like that,
`ars-watch` is not a nice-to-have — it is what keeps the artifact true.

## If you are not saturated

Run another round. But first, diagnose *where* the misses came from — the `found_via` on
the newly-found papers tells you which mode was weak, and that is where to spend the next
round rather than repeating all four uniformly.

If three rounds have not converged, stop anyway and say so. Either the scope is too broad
(go back to Phase 0) or the grid is wrong (Phase 4's diagnostic will show it). Endless
rounds are a symptom, not a solution.

## Freeze

Set `phase: 5` and `last_searched_at` to today. Validate:

```bash
python3 "$CLAUDE_PROJECT_DIR/.claude/ai-research-skills/scripts/rs_validate.py" .research/survey/<slug>
```

The protocol is now the subscription. `ars-watch` re-runs this file verbatim, diffs against
`corpus.jsonl`, and re-tests every gap's `closes_if`.

## Hand back honestly

Report, in this order:

1. **Counts** — retrieved, deduped, **adjudicated**, includes, unsure.
2. **Depth** — the `evidence_read` distribution across includes. If most are `abstract`,
   lead with that.
3. **Recall** — includes by mode, and which mode found what the others missed.
4. **Coverage** — occupied / unexplored / abandoned / **undecided** cell counts.
5. **Gaps** — each with confidence, and the `undecided` count alongside.
6. **Not covered** — venues not swept, paywalled work, languages, date floor.
7. **Shelf life** — growth rate and when this needs re-running.

Then name the exits: `ars-gap-gate` for go/no-go, `ars-related-work` for prose, `ars-decision-brief`
for a build/adopt/skip call, `ars-watch` to keep it alive.

A survey that undersells its coverage is useful. One that oversells it is worse than
nothing, because someone will commit months to it.
