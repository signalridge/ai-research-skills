---
name: ars-survey
description: >
  Build a screened, provenance-tracked literature corpus with a coverage map, for AI/ML
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

**You are the only skill allowed to freely discover and construct the corpus.** `ars-watch` is
the sole later updater, and only at Phase 5 while replaying this frozen protocol. `ars-red-team`
may search only to refute and never appends results. Gap-gate, related-work and decision-brief
are read-only projections; verify performs identifier lookup only. Missing evidence comes back
here rather than being discovered by an exit.

---

## Phases

Six phases. Read the reference file when you enter the phase; do not preload them.

| Phase | Reference | Cannot advance until |
|---|---|---|
| 0 Scope | [references/00-scope.md](references/00-scope.md) | Question is interrogative and answerable; **taxonomy axes named before any search** |
| 1 Recall | [references/01-recall.md](references/01-recall.md) | All four recall modes executed and logged, contrarian included |
| 2 Score | [references/02-score.md](references/02-score.md) | Every candidate has `relevance` + `contextual_summary`; screened by threshold |
| 3 Extract | [references/03-extract.md](references/03-extract.md) | Every include has `claim`, `axes`, `code`, `evidence_read`, sourced `numbers` |
| 4 Map | [references/04-map.md](references/04-map.md) | Coverage matrix built; empty cells discriminated; gaps carry `closes_if` |
| 5 Saturate | [references/05-saturate.md](references/05-saturate.md) | A full round adds <5% new on-topic **published before `created`** |

Walk them in order. Each has its own exit criteria; do not advance until the current one
passes. `phase` is required: Phase 0 is protocol only; Phase 1 owns corpus/log/recall and
retrieved-vs-deduped; Phase 2 owns terminal adjudication and score counts; Phase 3 owns
refs and include extraction; Phase 4 owns gaps and the complete unique Cartesian grid; and
Phase 5 owns saturation plus `last_searched_at`. The validator recomputes `deduped` as
unique keys, `adjudicated` as include+exclude (not unsure), `unsure` as unsure records,
`scored_at_or_above_threshold` from relevance, and `fulltext_kept` as includes read beyond
abstract.

## Resuming

State lives on disk, so a survey survives context compaction, a new session, or a hand-off.

```bash
ls .research/survey/                      # which surveys exist
```

Read `.research/survey/<slug>/protocol.yml` and check `phase:`. Resume at `phase + 1`
while `phase < 5`; Phase 5 is the terminal survey-construction phase, so a frozen survey
resumes through `ars-watch`, not a nonexistent Phase 6. If `protocol.yml` does not exist,
you are starting Phase 0.

Never restart a survey from scratch because the corpus looks unfamiliar. Read it.

## State written

```
.research/survey/<topic-slug>/
  protocol.yml      # the reproducible search contract — `ars-watch` is just re-running this
  corpus.jsonl      # one record per candidate, provenance + score + screen decision
  coverage.yml      # taxonomy axes + cell occupancy + recall self-diagnostic
  gaps.yml          # candidate gaps + evidence-of-absence + falsifier
  refs.bib          # per-entry rs-provenance attestations; external resolution still required
  notes/<key>.md    # per-paper extraction, fulltext reads only
  log.md            # append-only: date, tool, params, counts, cost
```

Schemas are installed at `.claude/ai-research-skills/schemas/`. Validate any time:

```bash
python3 "$CLAUDE_PROJECT_DIR/.claude/ai-research-skills/scripts/rs_validate.py" .research/survey/<slug>
```

Run it at the end of every phase. It is fast and it catches the errors that are expensive
to find later.

---

## Backends

**Check they are reachable before Phase 1.** A backend that has silently dropped is the one
condition under which this skill must refuse to run rather than degrade — see rule 2. If
`arxiv` is unavailable, `openalex` covers discovery and citation graphs but **not** BibTeX
export or `ars-watch` alerts; say which capability is missing and what that costs the survey.

Three backends, each with a job it is genuinely best at. Do not substitute one for another.

| Need | Call |
|---|---|
| AI/ML keyword discovery, preprints | `arxiv` → `search_papers` |
| Read a named section without downloading | `arxiv` → `get_paper_latex_section` |
| **BibTeX** | Prefer `arxiv` → `export_citations`; every entry needs `rs-provenance: key=… id=… tool=… date=…`. This is a defensive tripwire, not cryptographic proof; `ars-verify` resolves identifiers externally. |
| Standing subscription | `arxiv` → `watch_topic` / `check_alerts` |
| Citation graph, cursor-paginated | `openalex` → `openalex_get_citation_graph` |
| **Coverage matrix + field growth baseline** | `openalex` → `openalex_analyze_trends` |
| Anything → an ID | `openalex` → `openalex_resolve_name` |
| Valid field names before building a filter | `openalex` → `openalex_describe_fields` |
| Non-arXiv venues, workshop sites, blogs | `tavily` → `tavily_search` |
| HF Papers feed, model/dataset cards | `tavily` `site:huggingface.co` or fetch the page |

**Prefer complete LaTeX or HTML, but do not assume it exists.** `get_paper_latex_section`
reads a named section straight from source with equations intact. If arXiv source is absent,
use the optional `[pdf]` extra's HTML-first `download_paper`/`read_paper` path; for
proceedings-only papers or industry reports, use a configured local converter such as
`markitdown-mcp` or another pinned parser. Record the converter/version and visual checks.

OpenAlex is metered. Use the largest page size the selected tool and mode permits: normally
`per_page: 100` for keyword/exact/list and citation-graph calls, but semantic search is capped
at 50 and rate-limited to about one request per second. Resolve an ID once and reuse it;
singleton lookups are commonly free, while search is metered. Record the returned cost,
budget headers, query shape and date in `protocol.yml.budget`; do not hardcode a round price.
See [SETUP.md](https://github.com/signalridge/ai-research-skills/blob/main/docs/SETUP.md) for
verified failure modes — arXiv DOIs that 404, six distinct works sharing one title, and
future-dated year buckets.

---

## Rules that apply in every phase

These are the ones that cost something when broken. The reference files carry the rest.

1. **Four orthogonal recall modes are mandatory** — keyword, citation chain, venue/author,
   contrarian. The first three are all biased toward consensus: keyword search returns the
   field's own vocabulary, citation chains follow what authors chose to acknowledge, venue
   sweeps return what got accepted. Only the contrarian pass goes looking for the work that
   would embarrass a naive answer.

2. **No retrieval, no survey.** If the search backends are unreachable, say so and stop.
   Never fall back to writing a survey from memory — that is precisely the failure the
   whole design exists to prevent, and it is indistinguishable from a real survey until
   someone checks a citation.

3. **Record `evidence_read` honestly.** `abstract` means you read an abstract. An abstract
   tells you what the authors wanted to claim, not what they showed. Cited literature QA task v2 results
   are commonly reported in the 0.06–0.35 range under a no-retrieval condition, versus
   0.70 for humans with search, but the dedicated result source was not locally re-verified
   in this audit. Treat them as qualified benchmark context, not universal model limits.
   Memory is not a source, and neither is a title.

4. **Abstention is a state, not a failure.** `screen: unsure` is legitimate and tracked.
   Report coverage (`counts.adjudicated`) separately from what you decided. A survey that
   judged 40 of 200 candidates must not look like one that judged all 200.

5. **Score, then threshold — never judge include/exclude directly.** A binary call is
   irreversible and untunable; re-tuning means re-reading everything.

6. **Taxonomy axes are declared in Phase 0, before searching.** A post-hoc taxonomy
   describes your sample, not the field, and every empty cell in it is an artifact of what
   you happened to find.

7. **BibTeX entries require strict per-entry attestations.** Bind key, stable identifier,
   exporting tool and date, and reconcile the entry with the corpus. The current hook contract
   cannot prove which process produced bytes; attestations can be forged, so `ars-verify` must
   perform the real external identifier lookup.

8. **Absence claims require typed evidence.** Every "nobody has done X" needs a `gaps.yml`
   entry with populated `evidence_of_absence`. A hook enforces this on any prose you write.

9. **Every gap carries a `closes_if` falsifier.** Written in advance, re-tested by `ars-watch`.

10. **Extraction is open-response, never a checkbox.** Make yourself state what the paper
    actually claims in your own words. "Is this relevant? Y/N" will look far more competent
    than it is. literature benchmark v2 reports model-specific 26–46% accuracy differences across task
    families and attributes them jointly to open-response answers and more realistic
    retrieval/file/context framing; do not treat the gap as a single-cause estimate.

11. **A quoted number names its table and was looked at.** `numbers[].source` +
    `looked_at: true`. Finding the right table is harder than reading a given one.

## What this skill does not do

| Not this | Use instead |
|---|---|
| Decide whether a topic is worth pursuing | `ars-gap-gate` — and it withholds the verdict too |
| Write related-work prose | `ars-related-work` |
| Monitor a topic over time | `ars-watch` |
| Make a build/adopt/skip call | `ars-decision-brief` |
| Reproduce a paper's experiments | out of scope for this suite |

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

## Handoffs

- **Writes:** all of `.research/survey/<slug>/` while building the survey — `protocol.yml`,
  `corpus.jsonl`, `coverage.yml`, `gaps.yml`, `refs.bib`, `notes/`, `log.md`. It is the only
  free discovery/corpus builder; Phase 5 watch is the narrowly-scoped later updater.
- **Downstream:** `ars-gap-gate`, `ars-related-work` and `ars-decision-brief` consume the
  state; `ars-watch` re-runs the frozen protocol; `ars-red-team` and `ars-verify` audit it.
- **Upstream:** none. A missing paper anywhere comes back here — never the reverse.
