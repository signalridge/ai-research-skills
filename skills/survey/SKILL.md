---
name: survey
description: >
  Build a screened, provenance-tracked literature corpus with a coverage map, for CS/ML
  topics. Use when the user wants to survey a research area, find related work, map what
  has been done on a topic, check whether an idea is already taken, look for a research
  gap, or build the corpus behind a related-work section or a build/adopt/skip decision.
  Triggers on "survey X", "literature review", "related work on", "what's been done on",
  "is this idea taken", "find a research gap", "map the field", "調査", "文献调研",
  "有没有人做过". This is the ONLY skill permitted to search for literature — gap-gate,
  related-work, watch and decision-brief all read the state it writes.
---

# Survey — the only searcher

Four deliverables people want from literature work — a go/no-go on a topic, a related-work
section, a standing watch, a build/adopt/skip brief — are four **projections of one
object**: a screened, provenance-tracked, taxonomized corpus with a coverage map over it.

Build that object once, write it to disk, and let the exits be pure functions of it.

**You are the only skill allowed to search.** If `gap-gate`, `related-work`, `watch`, or
`decision-brief` needs a paper that isn't in the corpus, it comes back here.

---

## Phases

Six phases. Read the reference file when you enter the phase; do not preload them.

| Phase | Reference | Cannot advance until |
|---|---|---|
| 0 Scope | [references/00-scope.md](references/00-scope.md) | Question is interrogative and answerable; **taxonomy axes named before any search** |
| 1 Recall | [references/01-recall.md](references/01-recall.md) | All three recall modes executed and logged |
| 2 Score | [references/02-score.md](references/02-score.md) | Every candidate has `relevance` + `contextual_summary`; screened by threshold |
| 3 Extract | [references/03-extract.md](references/03-extract.md) | Every include has `claim`, `axes`, `code`, `evidence_read`, sourced `numbers` |
| 4 Map | [references/04-map.md](references/04-map.md) | Coverage matrix built; empty cells discriminated; gaps carry `closes_if` |
| 5 Saturate | [references/05-saturate.md](references/05-saturate.md) | A full round adds <5% new on-topic **net of field growth** |

Walk them in order. Each has its own exit criteria; do not advance until the current one
passes.

## Resuming

State lives on disk, so a survey survives context compaction, a new session, or a hand-off.

```bash
ls .research/survey/                      # which surveys exist
```

Read `.research/survey/<slug>/protocol.yml` and check `phase:`. Resume at `phase + 1`.
If `protocol.yml` does not exist, you are starting Phase 0.

Never restart a survey from scratch because the corpus looks unfamiliar. Read it.

## State written

```
.research/survey/<topic-slug>/
  protocol.yml      # the reproducible search contract — `watch` is just re-running this
  corpus.jsonl      # one record per candidate, provenance + score + screen decision
  coverage.yml      # taxonomy axes + cell occupancy + recall self-diagnostic
  gaps.yml          # candidate gaps + evidence-of-absence + falsifier
  refs.bib          # TOOL-GENERATED ONLY
  notes/<key>.md    # per-paper extraction, fulltext reads only
  log.md            # append-only: date, tool, params, counts, cost
```

Schemas are in `schemas/` at the plugin root. Validate any time:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rs_validate.py" .research/survey/<slug>
```

Run it at the end of every phase. It is fast and it catches the errors that are expensive
to find later.

---

## Backends

Three, each with a job it is genuinely best at. Do not substitute one for another.

| Need | Call |
|---|---|
| CS/ML keyword discovery, preprints | `arxiv` → `search_papers` |
| Read a named section without downloading | `arxiv` → `get_paper_latex_section` |
| **BibTeX** | `arxiv` → `export_citations` — **the only permitted source** |
| Standing subscription | `arxiv` → `watch_topic` / `check_alerts` |
| Citation graph, cursor-paginated | `openalex` → `openalex_get_citation_graph` |
| **Coverage matrix + field growth baseline** | `openalex` → `openalex_analyze_trends` |
| Anything → an ID | `openalex` → `openalex_resolve_name` |
| Valid field names before building a filter | `openalex` → `openalex_describe_fields` |
| Non-arXiv venues, workshop sites, blogs | `tavily` → `tavily_search` |

**Never parse a PDF when LaTeX or HTML exists.** `get_paper_latex_section` reads a named
section straight from source with equations intact. Reach for a PDF parser only for
proceedings-only papers or industry reports.

OpenAlex is metered. Always `per_page: 100` — cost is per call, not per result. Resolve an
ID once and reuse it; singleton lookups are free, search is the priciest call. Record spend
in `protocol.yml.budget`. See [SETUP.md](../../SETUP.md) for the verified failure modes —
arXiv DOIs that 404, six distinct works sharing one title, and year buckets in the future.

---

## Rules that apply in every phase

These are the ones that cost something when broken. The reference files carry the rest.

1. **Three orthogonal recall modes are mandatory** — keyword, citation chain, venue/author.
   Keyword-only search has poor recall in CS/ML because terminology drifts faster than it
   standardizes. Citation chaining finds the papers solving your problem under a name you
   never guessed.

2. **Record `evidence_read` honestly.** `abstract` means you read an abstract. An abstract
   tells you what the authors wanted to claim, not what they showed. On literature benchmark's literature QA task v2,
   frontier models score 0.06–0.35 at literature extraction *without* retrieval against
   0.70 for humans with search — memory is not a source, and neither is a title.

3. **Abstention is a state, not a failure.** `screen: unsure` is legitimate and tracked.
   Report coverage (`counts.adjudicated`) separately from what you decided. A survey that
   judged 40 of 200 candidates must not look like one that judged all 200.

4. **Score, then threshold — never judge include/exclude directly.** A binary call is
   irreversible and untunable; re-tuning means re-reading everything.

5. **Taxonomy axes are declared in Phase 0, before searching.** A post-hoc taxonomy
   describes your sample, not the field, and every empty cell in it is an artifact of what
   you happened to find.

6. **BibTeX is tool-generated, never written.** `export_citations` only. Fabricated
   citations — right-looking authors, adjacent year, journal that never published it — are
   the single most common failure of LLM literature work, and a hook will block you.

7. **Absence claims require typed evidence.** Every "nobody has done X" needs a `gaps.yml`
   entry with populated `evidence_of_absence`. A hook enforces this on any prose you write.

8. **Every gap carries a `closes_if` falsifier.** Written in advance, re-tested by `watch`.

9. **Extraction is open-response, never a checkbox.** Make yourself state what the paper
   actually claims in your own words. "Is this relevant? Y/N" will look far more competent
   than it is — that swap alone is most of literature benchmark v2's 26–46% difficulty jump over
   literature benchmark.

10. **A quoted number names its table and was looked at.** `numbers[].source` +
    `looked_at: true`. Finding the right table is harder than reading a given one.

## What this skill does not do

| Not this | Use instead |
|---|---|
| Decide whether a topic is worth pursuing | `gap-gate` — and it withholds the verdict too |
| Write related-work prose | `related-work` |
| Monitor a topic over time | `watch` |
| Make a build/adopt/skip call | `decision-brief` |
| Reproduce a paper's experiments | out of scope for this plugin |

Do not write prose deliverables here. The survey's output is state, not a document.

## Honest reporting

When you hand back, say plainly what the survey is and is not:

- how many candidates were retrieved, deduped, and **actually adjudicated**
- the `evidence_read` distribution across includes
- which recall mode contributed which fraction of includes
- which cells are `undecided` rather than confidently `unexplored`
- what the search did *not* cover

A survey that undersells its coverage is useful. One that oversells it is worse than none,
because someone will commit months to it.
