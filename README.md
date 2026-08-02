# research-skills

A survey-first research suite for CS/ML. **One survey engine, four exits.**

A go/no-go on a topic, a related-work section, a standing watch, and a build/adopt/skip
brief look like four workflows. They are four **projections of one object** — a screened,
provenance-tracked, taxonomized corpus with a coverage map over it.

So the survey is built once and written to disk as typed state. Everything downstream is a
pure function of it, and only the survey is allowed to search.

```
                        ┌─────────────────────────────┐
   topic ──────────────▶│  survey  (the only searcher)│
                        └──────────────┬──────────────┘
                                       │ .research/survey/<slug>/
                        ┌──────────────┴──────────────┐
                        ▼        ▼         ▼          ▼
                   gap-gate  related-work  watch  decision-brief
                   go/no-go    prose+bib   diffs    evidence matrix
```

## Install

```bash
claude plugin marketplace add signalridge/research-skills
claude plugin install research-skills@research-skills
```

Or point Claude Code at a local checkout with `/plugin`.

Search backends are configured separately — see **[SETUP.md](SETUP.md)**. You need the
`arxiv` MCP server; `openalex` and `tavily` are strongly recommended. OpenAlex has required
an API key since 2026-02-13 (the old `mailto=` polite pool is silently ignored now).

## Use

```
/rs:survey <topic>          start or resume a survey — the only stage that searches
/rs:gate                    3-gate go/no-go dossier
/rs:relwork                 related-work draft + verified bib
/rs:brief <decision>        build/adopt/skip evidence matrix
/rs:watch [arm|check]       arm the subscription, or run a digest
/rs:audit                   red-team + citation/number integrity
```

Skills also auto-trigger from description, so "survey retrieval-augmented agents" or
"has anyone compared X to Y" reaches the same place.

## The pieces

| Skill | Job |
|---|---|
| **survey** | Six phases: scope → recall → score → extract → map → saturate. Writes all state. |
| **gap-gate** | Is the gap open? Would closing it be a contribution? Can *you* close it? 3-gate AND, **verdict withheld**. |
| **related-work** | Thematic prose by taxonomy axis, every claim carrying a corpus key. |
| **watch** | Re-runs the protocol, diffs the corpus, and re-tests every gap's falsifier. |
| **decision-brief** | Claim→evidence matrix weighted by reproducibility, not venue. |
| **red-team** | Adversarial pass at two checkpoints. Attacks recall, not just conclusions. |
| **verify** | BibTeX provenance, key consistency, number traceability, preprint drift. |

## Guardrails

Prompts are advisory; hooks are enforcement. Four, each fails open.

| Hook | Catches |
|---|---|
| `bib_provenance_guard` | Hand-written BibTeX. **Blocks** `.bib` writes with no tool provenance — fabricated citations closed at the source rather than detected later. |
| `absence_claim_guard` | "No prior work…", "first to…", "据我们所知…" with no `gaps.yml` entry backing it. Silent outside a survey project. |
| `survey_staleness` | A corpus older than 30 days being reasoned from. In a field tripling annually, that is a liability. |
| `stop_survey_peer` | End of turn: conclusions resting on abstracts, an unadjudicated tail, single-mode recall, gaps with no nearest prior work. |

## State

```
.research/survey/<topic-slug>/
  protocol.yml      # the reproducible search contract — `watch` just re-runs this
  corpus.jsonl      # one record per candidate: provenance, score, screen decision
  coverage.yml      # taxonomy grid + cell occupancy + recall self-diagnostic
  gaps.yml          # candidate gaps + evidence-of-absence + falsifier
  refs.bib          # tool-generated only
  notes/<key>.md    # per-paper extraction, full reads only
  log.md            # append-only: date, tool, params, counts, cost
```

Validate any time — JSON Schemas live in `schemas/`:

```bash
python3 scripts/rs_validate.py .research/survey/<slug>
uv run --with pyyaml --with jsonschema python3 scripts/rs_validate.py .research/survey/<slug>
```

The second form adds structural checks. Both run the semantic checks, which are the ones
that catch broken surveys: a taxonomy that drifted after searching, a `high`-confidence gap
resting on two queries, counts claiming more coverage than the corpus supports.

## Four fields that carry the design

**`evidence_read`** on every record (`abstract` … `full`). A survey that is 90%
abstract-only is a different object from one that is full-text, and nothing else makes that
visible. Empirical anchor: without retrieval, frontier models score 0.06–0.35 at literature
extraction where humans with search get 0.70.

**`found_via`** — which recall mode surfaced each paper. If citation chaining contributed
nothing, the search was keyword-shaped and every gap downstream is suspect. A free
self-diagnostic.

**`closes_if`** on every gap — a falsifier written in advance, re-tested by `watch` against
every new paper. Without it a gap closes silently while you spend six months closing it
yourself. This is the bridge from "survey" to "standing awareness".

**`screen: unsure`** plus `counts.adjudicated` — abstention is a tracked state. literature benchmark
reports accuracy, precision and coverage separately for a reason: a model answering 12% of
questions at 47% precision scores 0.06 accuracy, and collapsing those into one number
destroys the information that matters.

## Design notes

- **[DESIGN.md](DESIGN.md)** — the full design, the eleven rules and the failure each traces
  to, what is deliberately not built, and a changelog of what was folded in from elsewhere.
- **[SETUP.md](SETUP.md)** — backend configuration, OpenAlex budget, and verified failure
  modes (arXiv DOIs that 404, six works sharing one title, year buckets in the future).

Built after surveying [scientific skills catalog/scientific-agent-skills](catalog-reference-01),
[catalog-reference-02](catalog-reference-02),
[methodology-reference-03](methodology-reference-03), and
[methodology-reference-01](methodology-reference-01) — and folding in retrieval-summary benchmark's RCS
scoring, literature benchmark's accuracy/precision/coverage split, and `gap-to-topic`'s 3-gate dossier.

## License

MIT
