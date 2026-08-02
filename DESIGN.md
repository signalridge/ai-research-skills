# research-skills — design

A lean, guarded research skill suite for CS/ML. **One survey engine, four exits.**

Domain: CS / ML / AI. Weight: lean + guarded (~7 skills, 4 hooks, 6 commands).

Revision 2 (2026-08-03) — folds in retrieval-summary benchmark's RCS scoring, literature benchmark's
accuracy/precision/coverage separation, and an OpenAlex backend. See §9 for what
changed and why.

---

## 0. Thesis

Four different deliverables — a go/no-go on a topic, a related-work section, a standing
watch, a build/adopt/skip brief — look like four workflows. They are not. They are four
**projections of one object**: a screened, provenance-tracked, taxonomized corpus with a
coverage map over it.

So the survey is built once and written to typed state on disk. Everything downstream is a
pure function of that state. The survey is the only stage that touches literature; no exit
skill is allowed to search.

This is the main departure from the four surveyed repos. ARS reaches literature at Phase 2
*after* the research question is frozen. methodology reference 01 has one flat `literature-research`
skill. scientific skills catalog has a PRISMA pipeline with no reusable output. None treat the corpus as a
durable, re-queryable artifact.

```
                        ┌─────────────────────────────┐
   topic ──────────────▶│  survey  (the only searcher)│
                        └──────────────┬──────────────┘
                                       │ writes .research/survey/<slug>/
                        ┌──────────────┴──────────────┐
                        ▼        ▼         ▼          ▼
                   gap-gate  related-work  watch  decision-brief
                   go/no-go    prose+bib   diffs    evidence matrix
```

---

## 1. State — the spine

Everything is a file. State survives context compaction, session restarts, and hand-off to
a teammate. `watch` is literally "re-run `protocol.yml`."

```
.research/survey/<topic-slug>/
  protocol.yml      # the reproducible search contract
  corpus.jsonl      # one record per candidate, with provenance + score + screen decision
  coverage.yml      # taxonomy axes + cell occupancy
  gaps.yml          # candidate gaps + evidence-of-absence + falsifier
  refs.bib          # TOOL-GENERATED ONLY — never hand-written
  notes/<key>.md    # per-paper extraction (only for fulltext-read papers)
  log.md            # append-only: date, query, tool, params, counts, cost
```

### 1.1 `protocol.yml`

```yaml
topic: retrieval-augmented-agents
question: "Do retrieval-augmented agents outperform long-context models on multi-hop QA
           when retrieval quality is held constant?"
created: 2026-08-03
last_searched_at: 2026-08-03          # staleness hook reads this
scope:
  in:  [multi-hop QA, agentic retrieval, long-context baselines]
  out: [single-hop QA, RAG for code, multimodal retrieval]
  window: 2023-01-01..
  venues: [NeurIPS, ICLR, ICML, ACL, EMNLP, COLM]

recall_modes:                          # ALL THREE REQUIRED — see §5 rule 1
  keyword:
    - {tool: arxiv.search_papers, q: 'ti:"multi-hop" AND abs:"retrieval"', cats: [cs.CL], n: 50}
    - {tool: openalex.search_entities, q: '"multi-hop" AND "retrieval"', per_page: 100}
    - {tool: tavily.search, q: "agentic retrieval vs long context multi-hop"}
  citation_chain:
    - {tool: openalex.get_citation_graph, seed: W..., direction: cites,    per_page: 100}
    - {tool: openalex.get_citation_graph, seed: W..., direction: cited_by, per_page: 100}
    - {tool: arxiv.citation_graph, seed: "arXiv:2401.xxxxx"}
  venue_author:
    - {tool: openalex.search_entities, filters: {"primary_location.source.id": S..., publication_year: "2025-2026"}}
    - {group: "<lab name>", via: openalex.resolve_name}

screen:
  include: ["evaluates >=2-hop", "reports retrieval quality ablation"]
  exclude: ["survey papers", "no empirical eval", "single-hop only"]
  relevance_threshold: 6              # see §1.2 — screening is a threshold, not a judgement

counts:
  retrieved: 312
  deduped: 244
  adjudicated: 244                    # coverage — how many you actually judged
  scored_at_or_above_threshold: 61
  unsure: 9                           # abstention is tracked, not forced — see §5 rule 3
  fulltext_kept: 23

saturation:
  rounds: 3
  new_on_topic_last_round: 2
  baseline_growth: "~3x/yr"           # sizes the watch interval, NOT the stop rule
  stop_rule: "<5% new on-topic published before protocol.created"

budget:                               # OpenAlex is metered — see §8
  openalex_usd_spent: 0.06
```

### 1.2 `corpus.jsonl` — one line per candidate

```json
{"key":"sample2025iterative","id":"arXiv:2503.01234","openalex_id":"W4391234567",
 "title":"...","year":2025,"venue":"ICLR 2026",
 "found_via":["citation_chain:W2626778328:cites","keyword:r2"],

 "relevance":8,
 "contextual_summary":"<=300 words, written against THIS question — not the paper's abstract",

 "screen":"include","exclude_reason":null,

 "code":{"url":"github.com/…","status":"official","runs":"unverified"},
 "axes":{"setting":"multi-hop QA","method":"iterative retrieval","supervision":"none","ctx":"8k"},
 "claim":"Iterative retrieval beats 128k long-context by 6.2 EM on multi-hop benchmark A at equal retrieval recall.",
 "numbers":[{"value":"6.2 EM","source":"Table 3, p.7","looked_at":true}],

 "evidence_read":"intro+method+results",
 "accessed":"2026-08-03"}
```

Five fields do disproportionate work:

- **`relevance` + `contextual_summary`** — from retrieval-summary benchmark's RCS. Rather than judging
  include/exclude directly, score 1–10 and write a summary *against the research question*
  (not a generic abstract), then screen by threshold. Two consequences: the threshold is
  re-tunable without re-reading anything, and the summary is a ~200–400 token artifact
  standing in for a ~2,000 token chunk. retrieval-summary benchmark's summariser prompt also injects source
  metadata (citation count, venue) so relevance is judged with credibility attached — do
  the same.
- **`evidence_read`** ∈ `abstract | intro+method | intro+method+results | full`. A survey
  where 90% of records are `abstract` is a *different object* than one where they are
  `full`. This makes depth auditable and lets the stop-hook refuse conclusions resting on
  abstracts alone. **No surveyed repo has this.**
- **`found_via`** — which recall mode surfaced it. If every include came from `keyword`,
  citation chaining did nothing and recall is probably bad. A free self-diagnostic.
- **`numbers[].source` + `looked_at`** — any figure quoted in an exit must name its table
  or figure and have been *looked at*, not merely parsed. literature benchmark v2's harder `retrieve`
  variants exist precisely because finding the right table is harder than reading a
  provided one.
- **`screen`** ∈ `include | exclude | unsure`. `unsure` is a first-class terminal state.

`code.status` ∈ `official | third-party | none`, `code.runs` ∈ `verified | unverified | fails`.
For CS/ML this is evidence, not metadata: a gap "closed" by a paper with no runnable code is
closed much more weakly than one closed by a reproduced result.

### 1.3 `gaps.yml` — absence as a typed claim

```yaml
gaps:
  - id: G1
    statement: "No work evaluates agentic retrieval against long-context baselines with
                retrieval recall held constant."
    type: unvalidated-comparison    # method-limitation | untried-combination
                                    # | unvalidated-comparison | missing-benchmark
    evidence_of_absence:
      queries_run:                  # verbatim, >=3 distinct phrasings
        - 'abs:"retrieval recall" AND abs:"long context" AND abs:"multi-hop"'
        - 'ti:"controlled comparison" AND abs:"retrieval augmented"'
        - "matched retrieval budget long context agent QA"
      venues_swept: ["ICLR@2025-2026", "NeurIPS@2025", "ACL@2025-2026", "COLM@2025"]
      citation_chains: ["W2626778328:cites:1", "W4391234567:cited_by:1"]
      nearest_prior_work:
        - {key: sample2025iterative, why_not_it: "compares at fixed token budget, not fixed recall"}
      last_checked: 2026-08-03
    confidence: medium              # high | medium | low — see §5 rule 6
    closes_if: "Any paper reporting multi-hop QA with retrieval recall matched across
                agentic and long-context arms."
```

**`closes_if` is the load-bearing field.** It is a falsifier, written in advance, that
`watch` re-tests automatically on every new paper. Without it a gap closes silently while
you spend six months on it. This is the bridge between "survey" and "standing awareness",
and it exists in none of the four surveyed repos — `gap-to-topic` gets closest with its 3
gates but has no re-check mechanism.

---

## 2. Skills (7)

| # | Skill | Reads | Writes | One-line job |
|---|---|---|---|---|
| 1 | `survey` | — | all of `.research/survey/<slug>/` | The only searcher. 6 phases. |
| 2 | `gap-gate` | coverage, gaps | `topic_dossier.md`, `.gaps.yml` verdicts | 3-gate go/no-go, **verdict withheld** |
| 3 | `related-work` | corpus, coverage | `related_work.md`, `refs.bib` | Thematic prose + verified BibTeX |
| 4 | `watch` | protocol, gaps | appends corpus, `digest.md` | Re-run protocol, diff, re-test `closes_if` |
| 5 | `decision-brief` | corpus | `brief.md` | Claim→evidence matrix, build/adopt/skip |
| 6 | `red-team` | everything | `challenge.md` | Adversarial pass at 2 checkpoints |
| 7 | `verify` | corpus, refs, drafts | `integrity.md` | Citation + number traceability |

### 2.1 `survey` — six phases, six reference files

Progressive disclosure, methodology reference 01 style: `SKILL.md` is a scannable table; each phase is a
separate `references/0N-*.md` loaded only when that phase runs. (Progressive disclosure is
a **Skills** property, not an MCP one — MCP's default is loading every tool definition
upfront, which is the problem Anthropic's *Code execution with MCP* post exists to solve.)

| Phase | File | Gate to advance |
|---|---|---|
| 0 Scope | `00-scope.md` | Question is interrogative + answerable; taxonomy axes named **before** searching |
| 1 Recall | `01-recall.md` | All three recall modes executed and logged |
| 2 Score | `02-score.md` | Every candidate has `relevance` + `contextual_summary`; screen by threshold |
| 3 Extract | `03-extract.md` | Every include has `claim`, `axes`, `code`, `evidence_read`, sourced `numbers` |
| 4 Map | `04-map.md` | Coverage matrix built; empty cells promoted to candidate gaps |
| 5 Saturate | `05-saturate.md` | A full round adds <5% new on-topic *published before `created`* → freeze protocol |

**Axes are declared in Phase 0, before searching.** If you build the taxonomy after reading
the papers, the taxonomy is a description of your sample, not of the field — and every
empty cell is an artifact of what you happened to find. This ordering is what makes the
coverage matrix mean something.

#### Tool routing

Three backends, each with a job it is actually best at:

| Backend | Use it for | Do not use it for |
|---|---|---|
| **arxiv MCP** | Primary CS/ML discovery. `search_papers` (field-prefixed queries), `get_paper_latex_section` (targeted extraction, no full download), `export_citations` (**the only** BibTeX source — authoritative metadata, deterministic keys), `watch_topic`/`check_alerts` (standing subscription) | Coverage histograms; non-arXiv venues |
| **openalex MCP** | `get_citation_graph` (`cites`/`cited_by`/`related_to`, cursor-paginated) — the highest-recall mode. `analyze_trends` (group-by) — **the coverage-matrix primitive**, and the source of the field-growth baseline. `resolve_name` — turn anything into an ID before filtering. `describe_fields` — call before building a query | BibTeX (use `export_citations`); full text |
| **tavily** | Proceedings pages, workshop sites, engineering blogs, anything not indexed | Anything the two above cover |

**Never parse a PDF when LaTeX or HTML exists.** For arXiv-dominated work this makes the
whole document parser 01/document parser 03 layer unnecessary — `get_paper_latex_section` reads a named
section straight from source, with equations intact. Reach for a PDF parser only for
non-arXiv proceedings-only papers or industry reports, and note that document parser 01 is *weak*
exactly where papers are hard: complex multi-line equations score <70% BLEU against
document parser 02's >90%. document parser 01's strength is tables (table-extraction component TEDS >91%), not maths.

### 2.2 `gap-gate` — 3-gate AND, verdict withheld

Adapted from `methodology reference 04/gap-to-topic`, the best single idea in the four repos.

| Gate | Question | Evidence it consumes |
|---|---|---|
| **G1 Open?** | Is the gap actually still open? | `gaps.yml.evidence_of_absence` + `last_checked` freshness |
| **G2 Contribution?** | If closed, does the field care? | `coverage.yml` centrality; `analyze_trends` on the neighbouring cells; is the empty cell empty *because it's uninteresting*? |
| **G3 Feasible?** | Can *you* close it? | compute, data access, `code.status` of baselines you'd need to reproduce |

Fail any gate → no-go. **The skill assembles the evidence and stops short of the verdict.**
The "is this worth doing" call goes back to you and your advisor/team.

G2 deserves emphasis: an empty cell in a coverage matrix has two explanations — nobody
tried, or everybody tried and it doesn't work / doesn't matter. Distinguishing them is the
whole game, and the failure mode is treating "unoccupied" as "unexplored." `analyze_trends`
grouped over the neighbouring cells is the cheapest available discriminator: a cell
surrounded by high-volume, still-growing neighbours is unexplored; one surrounded by
neighbours whose volume peaked three years ago is abandoned.

### 2.3 `related-work` — thematic, never paper-by-paper

- Organized by **axis**, not chronologically and not one-paragraph-per-paper. (A
  paper-by-paper related work section is a reading list, not a synthesis.)
- Every sentence making a claim about the literature carries a `corpus.jsonl` key.
- BibTeX from `arxiv.export_citations` only — deterministic keys, authoritative metadata.
- Refuses to characterize a paper whose record is `evidence_read: abstract` beyond what an
  abstract supports. Contribution claims require `intro+method` minimum.

### 2.4 `watch` — the protocol *is* the subscription

Re-runs `protocol.yml`'s keyword queries with `since = last_searched_at`, re-runs forward
citation chains from the top-k seeds, then does the thing that matters: **evaluates every
open gap's `closes_if` against the new papers.**

Digest is three sections, in priority order:
1. **Gap-closers** — new work matching a `closes_if`. Loud. This is the alarm.
2. **Corpus updates** — preprint → camera-ready, retractions, v2 with different numbers.
3. **Adjacent** — on-topic but doesn't move a gate.

Backed by `arxiv.watch_topic` / `check_alerts` for the standing subscription and
`openalex.get_citation_graph` for new citers of the seed set; `/loop` or a cron routine for
cadence. Updates `last_searched_at` on every run, which silences the staleness hook.

### 2.5 `decision-brief` — build / adopt / skip

Not academic prose. A claim→evidence matrix for a technical call.

| Column | Content |
|---|---|
| Claim | The specific thing you'd rely on |
| Support | corpus keys, with `evidence_read` shown |
| Maturity | preprint / peer-reviewed / reproduced-by-third-party |
| Code | `code.status` + `code.runs` |
| Risk | what breaks if the claim is wrong |
| Verdict | build / adopt / skip / revisit-after `<trigger>` |

`code.runs: verified` is weighted far above venue prestige. For an engineering decision, a
reproduced arXiv preprint beats an unreproduced NeurIPS oral.

### 2.6 `red-team` — two blocking checkpoints

ARS's devil's-advocate, cut from 3 checkpoints to 2 and given a CS/ML-specific attack list.

**Checkpoint A — after Phase 4 (Map), before any exit.** Attacks:
- *Terminology drift.* Name three plausible alternative phrasings for the core concept.
  Were they searched? (`content moderation` = `safety filtering` = `NSFW detection`.)
- *Recall self-diagnostic.* What fraction of includes came from each `found_via` mode? If
  citation chaining contributed ~nothing, recall is suspect.
- *Coverage.* What fraction of retrieved candidates were actually adjudicated? An
  unadjudicated tail is not the same as an excluded one.
- *Empty-cell interpretation.* For each candidate gap: unexplored, or explored and
  abandoned? Cite the trend evidence.
- *Abstract-only conclusions.* Any coverage-matrix cell filled from an abstract alone.

**Checkpoint B — before an exit is delivered.** Attacks the specific exit: for `gap-gate`,
the strongest case that the gap is already closed; for `related-work`, cherry-picking and
uncited counter-evidence; for `decision-brief`, the failure mode you're least prepared for.

Critical findings block. Revision loops **capped at 2** — leftovers become an explicit
"Acknowledged Limitations" section rather than looping forever. (Straight from ARS; it's
the right call.)

### 2.7 `verify` — citation and number integrity

- Every `refs.bib` entry resolves to a real record and was tool-generated.
- Every number quoted in a draft traces to a `numbers[]` entry with a `source` and
  `looked_at: true`.
- Preprint vs published mismatch flagged — arXiv v1 numbers routinely differ from
  camera-ready.
- Every corpus key cited in a draft exists in `corpus.jsonl`.

---

## 3. Hooks — the guardrails

methodology reference 01' central lesson: **prompts are advisory, hooks are enforcement.** Four, each
traceable to a specific failure.

| Hook | Event | Catches |
|---|---|---|
| `bib_provenance_guard` | PreToolUse `Edit\|Write` on `*.bib`, `*.tex` | Hand-written BibTeX. Requires provenance from `export_citations`/Crossref. **Fabricated citations are the #1 research failure mode of LLM assistance, and this closes it at the source rather than detecting it later.** |
| `absence_claim_guard` | PostToolUse `Edit\|Write` on `*.md`, `*.tex` | Regex for `no prior work`, `first to`, `to the best of our knowledge`, `has not been`, `unexplored`, `novel` → demands a matching `gaps.yml` entry with populated `evidence_of_absence`. **The signature guardrail of this design.** |
| `survey_staleness` | SessionStart + PreToolUse on exit skills | `last_searched_at` older than 30 days while writing a gap claim or related work. In a topic growing 3× a year, a six-week-old survey is a liability. |
| `stop_survey_peer` | Stop | Fresh-context peer re-reads the session's conclusions against `corpus.jsonl`. One question: *is any conclusion here resting on `evidence_read: abstract`, on an unadjudicated tail, or on a coverage cell with no occupant and no evidence-of-absence?* |

---

## 4. Commands (6)

```
/rs:survey <topic>    start or resume a survey (auto-detects phase from state)
/rs:gate              3-gate go/no-go dossier
/rs:relwork           related-work draft + verified bib
/rs:brief             build/adopt/skip decision brief
/rs:watch [arm|check] arm the subscription, or run a digest
/rs:audit             red-team + verify in one pass
```

Six, matching methodology reference 01. Everything else auto-triggers from description matching.

---

## 5. The eleven rules, and the failure each one traces to

methodology reference 01' discipline: no rule without a scar.

1. **Three orthogonal recall modes are mandatory** (keyword, citation chain, venue/author).
   ← Keyword-only search has poor recall in CS/ML because terminology drifts faster than it
   standardizes. Citation chaining finds papers that solve your problem under a name you
   never guessed.
2. **`evidence_read` on every record.** ← Surveys confidently built on abstracts. An
   abstract tells you what the authors want to claim, not what they showed. Empirical
   anchor: on literature benchmark's literature QA task v2, frontier models score **0.06–0.35 accuracy** at
   literature extraction without retrieval, against **0.70** for humans with search.
   Memory is not a source.
3. **Abstention is a tracked state; coverage is reported separately from precision.** ←
   literature benchmark reports accuracy, precision, and coverage as three numbers, and the reason is
   visible in its own results: Claude 3.5 Sonnet answered only **12%** of literature QA task v2 questions
   but was right on **47%** of those it answered — an accuracy of 0.06 that reads as
   "useless" and a precision of 0.47 that reads as "cautious and often right." A survey
   that judged 40 of 200 candidates and one that judged all 200 must not look identical.
4. **Score, then threshold — never judge include/exclude directly.** ← A binary call is
   irreversible and untunable; re-tuning means re-reading. retrieval-summary benchmark's RCS scores each
   candidate against the question and re-ranks, which also compresses ~2,000-token chunks
   into 200–400 token summaries at no measured loss of downstream quality.
5. **Saturation stops the search, not a count — and it is measured only on papers published
   before the survey started.** ← "Minimum 15 sources" (ARS) and "60 verified references"
   (scientific skills catalog) measure effort, not coverage. But raw "<5% new" is also wrong in a fast-moving
   field, because two different things hide inside "new": a paper published *before*
   `protocol.created` that you missed is a **recall failure**, fixable by another round; a
   paper published *after* it did not exist when you started and is **field growth**,
   fixable only by `watch`. Conflate them and a field growing 3× a year never converges —
   you search forever chasing publications that are simply appearing. Measure the ratio over
   the first population only; take the growth rate from `analyze_trends` to size the watch
   interval and the survey's shelf life, not the stop rule.
6. **Taxonomy axes declared before searching.** ← Post-hoc taxonomies describe your sample,
   not the field, and manufacture fake empty cells.
7. **BibTeX is tool-generated, never written.** ← LLMs generate plausible, wrong citations
   — right-looking authors, adjacent year, journal that never published it.
8. **Absence claims require typed evidence.** ← "No one has done this" is the highest-risk
   sentence in research, and the cheapest to say. `confidence: high` requires ≥3 phrasings,
   ≥3 venue-years swept, and forward chains from the nearest prior work.
9. **Every gap carries a `closes_if` falsifier.** ← Gaps close silently. Without a
   pre-registered falsifier there is nothing for `watch` to test, and you find out at
   submission.
10. **Extraction is open-response; never a checkbox.** ← literature benchmark v2's whole difficulty jump
    over literature benchmark (−26% to −46%) comes from replacing multiple choice with open answers.
    "Is this paper relevant? Y/N" will look far more competent than it is. Make the model
    state what the paper actually claims, in its own words.
11. **A quoted number names its table and was looked at.** ← literature benchmark v2 splits figure/table
    tasks into `img` / `pdf` / `retrieve` variants because *finding* the right table is
    much harder than reading a given one. Independently, methodology reference 01 ships a `visual_check`
    hook and experiment-generation benchmark added a VLM figure-review loop. Three systems converged here.
12. **The gate assembles evidence; the human renders the verdict.** ← From `gap-to-topic`.
    A go/no-go on months of your time is not a decision to delegate, and a confident
    machine verdict crowds out the judgment that should be doing the work.

---

## 6. What is deliberately not built

- **27 modes** (ARS). More than anyone holds in their head; modes that are never selected
  are dead weight that still has to be maintained and kept consistent.
- **~160 library-wrapper skills** (scientific skills catalog). `scanpy`, `rdkit`, `qiskit` — that is a
  package index, not a workflow, and it's 488 MB.
- **Mandated paid CLIs.** scientific skills catalog routes search through `paid search CLI` + hosted model router. The
  arxiv + OpenAlex MCPs already cover search, citation graphs, targeted section reads,
  authoritative BibTeX, coverage histograms, and standing alerts.
- **A 13-agent team for the survey.** Lean means the survey is phases-in-one-context with
  state on disk, not a fan-out. `red-team` is the one place a genuinely independent context
  earns its cost.
- **PRISMA compliance.** Right for biomedical, wrong here. The counts and the screening log
  are kept (they're just good practice); the formal apparatus is not.
- **Agentic tree search** (experiment-generation benchmark). the benchmark authors's own README is the reason: *"v2 doesn't
  necessarily produce better papers than v1… v2 takes a broader, more exploratory approach
  with **lower success rates**."* Its accepted paper scored 6.33 at a workshop with a **70%
  acceptance rate**, placing ~top-45% of submissions, and reported a negative result. An
  honest milestone, but multi-worker exploration plus `max_debug_depth` auto-repair costs far
  more than it returns at this scale. The one cheap idea — the VLM figure-review loop — is
  already absorbed as rule 11.
- **A document-parsing layer.** See §2.1: LaTeX beats every PDF parser, and for arXiv it is
  always available.

---

## 7. Build order

Each step is independently useful — stop anywhere and you have something that works.

| Step | Ship | Unlocks |
|---|---|---|
| 1 | `survey` phases 0–4 + state schemas | A real corpus you can query and hand off |
| 2 | `bib_provenance_guard` + `absence_claim_guard` | The two failures that actually cost you |
| 3 | `gap-gate` | Go/no-go — highest-leverage exit |
| 4 | `red-team` checkpoint A | Recall self-diagnostic; the survey starts checking itself |
| 5 | `watch` + `closes_if` re-testing | Standing awareness; survey becomes durable |
| 6 | `related-work` + `verify` | Manuscript path |
| 7 | `decision-brief`, `stop_survey_peer`, `survey_staleness` | Engineering path + the long tail |

Steps 1–3 are the minimum viable suite. Step 5 is what makes the whole thing compound:
once gaps carry falsifiers and `watch` re-tests them, the survey stops being a document you
wrote once and becomes a position you hold.

---

## 8. OpenAlex — budget and hazards

OpenAlex is **metered** as of 2026-02-13. This shapes how `survey` is allowed to query it.
Setup and verified failure modes are in [SETUP.md](SETUP.md); the design consequences:

**Pricing per 1,000 calls** — singleton (get by ID/DOI): **free** · list+filter: $0.10 ·
search: $1 · semantic search: $1 · content download: $10. Free allowance is **$1/day with a
key**, $0.10/day without.

Three rules fall out of this:

1. **Always `per_page: 100`.** The cost is per call, not per result. Paginating at the
   default 25 burns budget 4× faster for identical data.
2. **Resolve once, then use IDs.** Singleton lookups are free; search is the most expensive
   operation. `resolve_name` → cache the `W…` id in `corpus.jsonl.openalex_id` → every
   subsequent touch of that record costs nothing.
3. **Log spend in `protocol.yml.budget`.** The MCP reports what each call spent and what
   remains; a survey that dies mid-sweep on a 429 has corrupted its own saturation count.

A full survey round — ~20 searches plus a few hundred list/graph calls — costs roughly
**$0.04**. The budget is not a real constraint; running blind into it is.

---

## 9. Changelog

**Revision 2 (2026-08-03)** — after verifying an external survey report on the scientific
agent ecosystem. Adopted:

| Change | Source |
|---|---|
| `relevance` + `contextual_summary`; screening becomes a threshold (§1.2, rule 4) | retrieval-summary benchmark RCS |
| `screen: unsure`; `counts.adjudicated`; coverage as its own metric (§1.1, rule 3) | literature benchmark accuracy/precision/coverage split |
| Rule 2 gains its empirical anchor (0.06–0.35 vs 0.70 human) | literature benchmark literature QA task v2 |
| Rule 10 — extraction is open-response, never a checkbox | literature benchmark v2's −26%/−46% jump |
| Rule 11 — `numbers[].source` + `looked_at` | literature benchmark v2 `retrieve` variants; methodology reference 01 `visual_check`; experiment-generation benchmark VLM loop |
| Saturation measured only on pre-`created` publications (§1.1, rule 5) | `openalex.analyze_trends` on a live topic: 323 → 3,236 → 9,915 → 14,086 works/yr over 2023–2026 |
| OpenAlex backend: citation graph, `analyze_trends` as the coverage primitive (§2.1, §8) | — |
| "Never parse a PDF when LaTeX exists" (§2.1) | document parser 01 <70% BLEU on complex equations vs document parser 02 >90% |
| Tree search explicitly rejected (§6) | experiment-generation benchmark's own reported success rates |

Rejected from that report: document parser 01/document parser 03 as a general layer (LaTeX is better and
free), the full retrieval-summary benchmark RAG stack (bibliography parser + vector index — we want the RCS *idea*, not the
system), and `mailto=` polite-pool access to OpenAlex (removed by OpenAlex in Feb 2026; the
parameter is now silently ignored).
