# ai-research-skills — design

A lean, guarded research skill suite for AI/ML. **One survey engine, four exits.**

Domain: CS / ML / AI. Weight: lean + guarded (~7 skills, 4 hooks, 7 commands).

Revision 5 (2026-08-06) — a review pass over revision 4's distribution rework: four defects
fixed and the skill prefix renamed `rs-` → `ars-`. See §10 for the full history. Ideas from
other suites were re-expressed, not copied — methodology reference 02 is CC BY-NC-SA 4.0 and this
repo is MIT.

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
a teammate. `ars-watch` is literally "re-run `protocol.yml`."

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

recall_modes:                          # ALL FOUR REQUIRED — see §5 rule 1
  keyword:
    - {tool: arxiv.search_papers, q: 'ti:"multi-hop" AND abs:"retrieval"', cats: [cs.CL], n: 50}
    - {tool: openalex.search_entities, q: '"multi-hop" AND "retrieval"', per_page: 100}
    - {tool: tavily.search, q: "agentic retrieval vs long context multi-hop"}
  citation_chain:
    - {tool: openalex.get_citation_graph, seed: W..., direction: cites,    per_page: 100}
    - {tool: openalex.get_citation_graph, seed: W..., direction: cited_by, per_page: 100}
  venue_author:
    - {tool: openalex.search_entities, filters: {"primary_location.source.id": S..., publication_year: "2025-2026"}}
    - {group: "<lab name>", via: openalex.resolve_name}
  contrarian:                          # the only mode that hunts disagreement on purpose
    - {tool: arxiv.search_papers, q: 'ti:"rethinking" OR ti:"revisiting"', angle: method-critique}
    - {tool: tavily.search, q: "<method> does not improve negative results", angle: negative-results}

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
 "corroboration":{"agrees_with":["sample2025longcontext"],"conflicts_with":["sample2025multi"]},
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
  the other three modes did nothing and recall is probably bad. A free self-diagnostic, and
  the one that told us Mode D was missing.
- **`numbers[].source` + `looked_at`** — any figure quoted in an exit must name its table
  or figure and have been *looked at*, not merely parsed. literature benchmark v2's harder `retrieve`
  variants exist precisely because finding the right table is harder than reading a
  provided one.
- **`screen`** ∈ `include | exclude | unsure`. `unsure` is a first-class terminal state.
- **`corroboration`** (optional) — `agrees_with` / `conflicts_with` by citation key.
  Disagreement between papers is carried into every consumer instead of being averaged
  into a consensus the corpus does not contain.

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
        - {key: sample2025iterative, why_not_it: "compares at fixed token budget, not fixed recall",
           differing_axis: problem-setting}   # `none` here means the gap is closed
      last_checked: 2026-08-03
    confidence: medium              # high | medium | low — see §5 rule 6
    closes_if: "Any paper reporting multi-hop QA with retrieval recall matched across
                agentic and long-context arms."
```

**`closes_if` is the load-bearing field.** It is a falsifier, written in advance, that
`ars-watch` re-tests automatically on every new paper. Without it a gap closes silently while
you spend six months on it. This is the bridge between "survey" and "standing awareness",
and it exists in none of the four surveyed repos — `gap-to-topic` gets closest with its 3
gates but has no re-check mechanism.

---

## 2. Skills (7)

| # | Skill | Reads | Writes | One-line job |
|---|---|---|---|---|
| 1 | `ars-survey` | — | all of `.research/survey/<slug>/` | The only searcher. 6 phases. |
| 2 | `ars-gap-gate` | coverage, gaps | `topic_dossier.md`, `.gaps.yml` verdicts | 3-gate go/no-go, **verdict withheld** |
| 3 | `ars-related-work` | corpus, coverage | `related_work.md`, `refs.bib` | Thematic prose + verified BibTeX |
| 4 | `ars-watch` | protocol, gaps | appends corpus, `digest.md` | Re-run protocol, diff, re-test `closes_if` |
| 5 | `ars-decision-brief` | corpus | `brief.md` | Claim→evidence matrix, build/adopt/skip |
| 6 | `ars-red-team` | everything | `challenge.md` | Adversarial pass at 2 checkpoints |
| 7 | `ars-verify` | corpus, refs, drafts | `integrity.md` | Citation + number traceability |

### 2.1 `ars-survey` — six phases, six reference files

Progressive disclosure, methodology reference 01 style: `SKILL.md` is a scannable table; each phase is a
separate `references/0N-*.md` loaded only when that phase runs. (Progressive disclosure is
a **Skills** property, not an MCP one — MCP's default is loading every tool definition
upfront, which is the problem Anthropic's *Code execution with MCP* post exists to solve.)

| Phase | File | Gate to advance |
|---|---|---|
| 0 Scope | `00-scope.md` | Question is interrogative + answerable; taxonomy axes named **before** searching |
| 1 Recall | `01-recall.md` | All four recall modes executed and logged, contrarian included |
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

### 2.2 `ars-gap-gate` — 3-gate AND, verdict withheld

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

Before delivery the dossier passes a silent **integrity gate** — every score cites state,
the composite agrees with its own gates, and each check is tagged `[inspection]` (verifiable
from the dossier) or `[attestation]` (the user confirms). Failures surface as corrections
inside the affected section, never as a gate report.

### 2.3 `ars-related-work` — thematic, never paper-by-paper

- Organized by **axis**, not chronologically and not one-paragraph-per-paper. (A
  paper-by-paper related work section is a reading list, not a synthesis.)
- Every sentence making a claim about the literature carries a `corpus.jsonl` key.
- BibTeX from `arxiv.export_citations` only — deterministic keys, authoritative metadata.
- Refuses to characterize a paper whose record is `evidence_read: abstract` beyond what an
  abstract supports. Contribution claims require `intro+method` minimum.

### 2.4 `ars-watch` — the protocol *is* the subscription

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

### 2.5 `ars-decision-brief` — build / adopt / skip

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

### 2.6 `ars-red-team` — two blocking checkpoints

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

**Checkpoint B — before an exit is delivered.** Attacks the specific exit: for `ars-gap-gate`,
the strongest case that the gap is already closed; for `ars-related-work`, cherry-picking and
uncited counter-evidence; for `ars-decision-brief`, the failure mode you're least prepared for.

Critical findings block. Revision loops **capped at 2** — leftovers become an explicit
"Acknowledged Limitations" section rather than looping forever. (Straight from ARS; it's
the right call.)

Verdicts follow truth-seeking semantics: every load-bearing claim carries a written
refutation-condition and lands in **BROKEN / CORROBORATED / UNFALSIFIABLE**, with
unfalsifiable scored *below* broken — a claim you cannot imagine being wrong about is one
you have stopped examining. No hardening, no resilience score: surviving red-teaming is a
list of attacks that failed, not a grade.

### 2.7 `ars-verify` — citation and number integrity

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

| Hook | Event | Verdict | Catches |
|---|---|---|---|
| `bib_provenance_guard` | PreToolUse on writes to `*.bib` | **denies** | Hand-written BibTeX: a `.bib` gaining entries with no tool-provenance header. **Fabricated citations are the #1 research failure mode of LLM assistance, and this closes it at the source rather than detecting it later.** |
| `absence_claim_guard` | PostToolUse on writes to `*.md`, `*.tex`, `*.markdown`, `*.mdx` | objects | Regex for `no prior work`, `first to …`, `to the best of our knowledge`, `has not been …`, `remains unexplored`, `no one has`, plus CJK equivalents → demands a `gaps.yml` entry whose `evidence_of_absence.queries_run` carries ≥3 phrasings. **The signature guardrail of this design.** |
| `survey_staleness` | SessionStart | advisory | `last_searched_at` older than 30 days on any survey in the project. In a topic growing 3× a year, a six-week-old survey is a liability. |
| `stop_survey_peer` | Stop | advisory | Reads `corpus.jsonl` deterministically at end of turn: abstract-only includes, an unadjudicated tail, single-mode recall, gaps with no nearest prior work, zero corroboration on a deeply-read corpus. |

Two limits are worth stating plainly, because a guardrail believed to be stronger than it
is does more harm than one known to be weak:

- **The absence guard is project-scoped, not claim-matched.** No regex can tell which gap a
  given sentence rests on, so it answers the weaker question honestly — does this project
  contain an absence claim worked out to the standard — and names the gap to check rather
  than pretending to have found it.
- **`stop_survey_peer` is not a peer.** It is a deterministic read of state, not a
  fresh-context model re-reading the session's conclusions. It can tell you what the corpus
  rests on; it cannot tell you what you concluded from it. `ars-red-team` is the place a
  genuinely independent context earns its cost.

---

## 4. Commands (7)

```
/ars-survey <topic>    start or resume a survey (auto-detects phase from state)
/ars-gate              3-gate go/no-go dossier
/ars-relwork           related-work draft + verified bib
/ars-brief             build/adopt/skip decision brief
/ars-watch [arm|check] arm the subscription, or run a digest
/ars-audit             red-team + verify in one pass
/ars-help              where you are in a survey right now
```

Seven. Everything else auto-triggers from description matching.

Slash commands are a **Claude Code surface only** — it is the sole host in §9 with a
`commands_dir`. On the other four the same skills install and trigger from their
descriptions, or by name ("run `ars-survey` on X"), and the installer says so per host
rather than announcing seven commands it did not write.

---

## 5. The seventeen rules, and the failure each one traces to

methodology reference 01' discipline: no rule without a scar.

1. **Four orthogonal recall modes are mandatory** (keyword, citation chain, venue/author,
   contrarian). ← Keyword-only search has poor recall in CS/ML because terminology drifts
   faster than it standardizes. But the deeper problem is that the first three modes are all
   biased toward *consensus*: keyword search returns the field's own vocabulary, citation
   chains follow what authors chose to acknowledge, venue sweeps return what got accepted. A
   paper refuting the mainstream shares none of those. Without a contrarian pass, `ars-red-team`'s
   cherry-picking check passes vacuously — it can only find contradictions already in the
   corpus — and the survey reports a consensus manufactured by its own search strategy.
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
   fixable only by `ars-watch`. Conflate them and a field growing 3× a year never converges —
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
   pre-registered falsifier there is nothing for `ars-watch` to test, and you find out at
   submission.
10. **Extraction is open-response; never a checkbox.** ← literature benchmark v2's whole difficulty jump
    over literature benchmark (−26% to −46%) comes from replacing multiple choice with open answers.
    "Is this paper relevant? Y/N" will look far more competent than it is. Make the model
    state what the paper actually claims, in its own words.
11. **A quoted number names its table and was looked at.** ← literature benchmark v2 splits figure/table
    tasks into `img` / `pdf` / `retrieve` variants because *finding* the right table is
    much harder than reading a given one. Independently, methodology reference 01 ships a `visual_check`
    hook and experiment-generation benchmark added a VLM figure-review loop. Three systems converged here.
12. **Disqualify before scoring.** ← A careful three-gate assessment of a candidate that
    was dead on arrival is not thoroughness; it is decoration on a rejection, and it
    manufactures a document that *looks* considered. `ars-gap-gate` Gate 0 reads state it
    already has, and stops.

13. **Retrieval bounds what you may conclude from it.** ← A search snippet establishes that
    a work exists and roughly what it addresses. It is not a source for a number or a
    method detail, and "nothing retrieved under these keywords" is not "nothing exists."
    Both halves are routinely collapsed, and both collapses produce confident errors.

14. **`avoided` and `abandoned` are opposite states that look identical.** ← Both mean
    "the work stopped." One is a dead end; the other is an old, large, acknowledged problem
    the field routes around because it is hard — usually the best target on the grid. Until
    revision 3 the coverage map had no way to express the difference, so `ars-gap-gate` G2
    scored both at 1 and would have systematically discarded the highest-value class of
    gap. The discriminator is searchable: count papers naming it as future work without
    attempting it.

15. **A gap is only taken if no axis differs.** ← A similar title establishes nothing.
    Duplication is failing to find even one differing axis among object-acted-on,
    mechanism, input-granularity and problem-setting. The rule cuts both ways: if all four
    come up the same, record it and drop the gap rather than reaching for a fifth.

16. **A gap has a shelf life, and it is a feasibility criterion.** ← An open, worthwhile,
    technically reachable gap is still a no-go if it will close before you finish. Ten
    focused hours a week against a six-month shelf life is a deadline set by strangers.
    G3 compares the two explicitly.

17. **The gate assembles evidence; the human renders the verdict.** ← From `gap-to-topic`.
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
  state on disk, not a fan-out. `ars-red-team` is the one place a genuinely independent context
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
| 1 | `ars-survey` phases 0–4 + state schemas | A real corpus you can query and hand off |
| 2 | `bib_provenance_guard` + `absence_claim_guard` | The two failures that actually cost you |
| 3 | `ars-gap-gate` | Go/no-go — highest-leverage exit |
| 4 | `ars-red-team` checkpoint A | Recall self-diagnostic; the survey starts checking itself |
| 5 | `ars-watch` + `closes_if` re-testing | Standing awareness; survey becomes durable |
| 6 | `ars-related-work` + `ars-verify` | Manuscript path |
| 7 | `ars-decision-brief`, `stop_survey_peer`, `survey_staleness` | Engineering path + the long tail |

Steps 1–3 are the minimum viable suite. Step 5 is what makes the whole thing compound:
once gaps carry falsifiers and `ars-watch` re-tests them, the survey stops being a document you
wrote once and becomes a position you hold.

---

## 8. OpenAlex — budget and hazards

OpenAlex is **metered** as of 2026-02-13. This shapes how `ars-survey` is allowed to query it.
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

## 9. Hosts — where this can actually run

Revision 4's distribution rework. The suite installs into five agent hosts, and the
selection rule is the same one §3 rests on: **a host earns a record by having a verified
way to enforce, not merely to read.**

| Host | Skills | Commands | Guardrails | Config written |
|---|---|---|---|---|
| claude | `.claude/skills` | `.claude/commands` | yes | `.claude/settings.json` |
| codex | `.codex/skills` | — | yes | `.codex/hooks.json` (events at top level) |
| cursor | `.cursor/skills` | — | yes | `.cursor/hooks.json` (camelCase events, `version` required) |
| pi | `.pi/skills` | — | yes\* | `.pi/settings.json` |
| kimi | `.kimi/skills` | — | no | — |

\* inert until `pi install npm:@hsingjui/pi-hooks`; the installer says so at install time
rather than letting an inert config read as protection.

Three consequences worth stating, because each one fails silently:

1. **Skills-only adapters were removed, not shipped.** Six hosts (qwen, opencode, windsurf,
   kilo, kiro, copilot) previously received the methodology with none of the enforcement.
   That hands the user a false sense of protection, which is worse than not installing —
   the whole design rests on rule 7 and rule 8 being *enforced*, not advised.
2. **Paths are rewritten per host, not authored per host.** Skills are written against
   Claude Code's layout — `$CLAUDE_PROJECT_DIR`, `.claude/` — and `installer.localise`
   rewrites both forms on the way in. A missed rewrite points the agent at a directory
   the host does not have, and nothing reports it, so the test suite asserts that no
   Claude-only path survives an install to any other host.
3. **`disallowed-tools` is a Claude Code extension, not part of the Agent Skills
   standard.** The four read-only exits declare it so that "never search here" is
   structural rather than advisory — but only on Claude Code, and only for the turn that
   invokes the skill; the restriction clears on the user's next message. Everywhere else
   it is ignored. That is why the prose rule stays in every one of those skills as the
   real backstop, and why it is not counted as a guardrail in the table above.

---

## 10. Changelog

**Revision 5 (2026-08-06)** — a full review pass. No new methodology; four defects and a
prefix rename.

| Change | Why |
|---|---|
| Skills and commands renamed `rs-` → `ars-` | `rs-` was short for `research-skills`, the name this repo carried before it became `ai-research-skills`. Skill and command names share one flat namespace per project, so the prefix has to be distinctive and has to trace back to the thing that installed it. `rs_validate.py` and the `rs-provenance` header are **not** renamed: the header is a file-format marker already written into users' `refs.bib` files and matched by `bib_provenance_guard`, so renaming it would fail every existing bibliography. Install and uninstall now sweep the old names, because two generations of the same skill both stay live and match the same requests |
| `installer.localise` rewrites bare `.claude/…` paths, not just the `$CLAUDE_PROJECT_DIR`-qualified one | The schemas paragraph in `ars-survey` named `.claude/` with no variable in front of it and so survived the rewrite verbatim, telling a Codex agent to read a directory that host does not have. The test suite now asserts no Claude-only path survives an install to any other host, rather than checking one known string |
| Install reports commands per host | Every host was told about seven slash commands, but only Claude Code has a `commands_dir`. The Kimi caveat compounded it by naming `/rs-audit` — a command that host never receives — inside the one message whose job is to say what you did not get |
| `absence_claim_guard` holds the same ≥3-phrasing floor as `rs_validate` | It accepted one `queries_run` item anywhere in the project. A guard laxer than the rule it enforces teaches the rule wrong, because the author who gets through learns that one phrasing was enough. Queries are now counted within a single `evidence_of_absence`, not pooled across the file |
| `rs_validate` names the state a cell actually carries | An `avoided` cell missing `trend_evidence` was told it was marked `unexplored`. The two score at opposite ends of G2, so the message pointed the fix at the wrong field |
| §9 Hosts added; §3 hook table corrected | The hook table claimed a `.tex` matcher, a `novel` pattern, a `PreToolUse` staleness event and a "fresh-context peer" — none of which exist. Revision 4's headline change (multi-host distribution) had no section at all |
| `unsure_by_mode` on `coverage.recall_diagnostic` | The worked example credited `venue_author` with an include that was actually `unsure`. A mode whose only hits are unresolved did contribute recall, and that is a different situation from one that contributed nothing |

**Revision 4 (2026-08-04)** — distribution rework plus a second survey round over
methodology reference 06, methodology reference 07 and methodology reference 05, and a fresh
re-read of the six original sources. Adopted:

| Change | Source |
|---|---|
| `.claude/` layout + `install.py` (skills/commands/hooks install into a project's `.claude/`, hooks merged into `settings.json`); plugin distribution dropped | host distribution reference's layout |
| Skills and commands `rs-`-prefixed; commands flat under `.claude/commands/` | host distribution reference's `golang-` prefix convention |
| AI venue universe + default arXiv category set + AI taxonomy axes; Hugging Face routed as a first-class source | orientation, not a source |
| `ars-red-team` truth-seeking verdicts (three buckets, refutation-conditions, no hardening) | methodology reference 06 falsification-first skills |
| `## Handoffs` contracts + closure check in `run_tests.py` | methodology reference 05 handoff sections; methodology reference 09's dependency closure verifier |
| `corroboration` on corpus records | methodology reference 05 claim-level confidence metadata |
| Source trust ranking; abstract-only never supports a conclusion; conditional outputs (intake note over thin section) | methodology reference 07 research-contract |
| `ars-gap-gate` integrity gate with [inspection]/[attestation] classes, run silently | methodology reference 02 idea-evaluator / pre-submission-reviewer integrity gates — missed on the first read |
| Opening-type classification (method-limitation vs unoccupied-application) shaping the kill test | methodology reference 04 gap-to-topic §0 — missed on the first read |
| Count reconciliation in Phase 1 (expected vs retrieved, reported page size) | scientific skills catalog paper-lookup pagination discipline |
| `revivable_by` on `abandoned` cells — a failure attributed to a specific tool, with a documented successor in the corpus, is promotable; the "newly possible" shape was being filtered out before it could become a gap | methodology reference 02 paradigm-shift probe, second read |
| Step B/C misclassification filters — "X fails, therefore we propose Y" is an attempt, not a verdict; temporal silence needs a success-paper check before `abandoned` | methodology reference 07 research-contract source criticism |
| `ars-verify` splits `unresolved` from `unverifiable-now`; `ars-watch` refreshes `last_checked` only on answered zero-hit queries — an infrastructure hiccup never manufactures freshness or deletes a citation | methodology reference 09 failure taxonomy: infrastructure failure is not claim failure |
| Retrieved-content-is-untrusted discipline in Phase 1, pointed back to from Phase 3 extraction | prompt-injection posture across the agent repos |
| Layout test pins progressive disclosure: every `references/` link resolves, exactly one level deep | methodology reference 09 dependency-closure verifier, extended to references |
| Wording ladder anchored on `corroboration`; survey records support field-level statements only; ≥2-papers-per-paragraph weaving; "not reported" table cells; bounded absence claims; dated time words | methodology reference 07 research-contract claim calibration |
| Excludes read as a blind-spot signal before gap analysis — a clustered exclude reason is an undeclared Phase 0 axis | methodology reference 05 intake diagnostics |
| Zero-corroboration stop-hook check; full reads scan limitations and "we found" sentences for author-stated caveats | methodology reference 05 claim-level confidence, second read |
| Gate 0 baseline-recency disqualifier — a >12-month-old strongest baseline in a >2×/yr field means the real baseline is unpublished | methodology reference 02 lifecycle matching, second read |
| Method-family centrality scoring for narrow questions — parent-field relevance caps at 3–4 when the family is only mentioned | methodology reference 01 relevance rubric, second read |
| Salvage path on every no-go; an unoccupied-application opening is not automatically incremental | methodology reference 04 gap-to-topic, second read |
| awesome-lists as pointers, never records | scientific skills catalog source breadth |

Rejected this round: methodology reference 09's four-layer hierarchy and ≥500-line checkpoints (scale-driven
ceremony), external bibliography application as a backend (a stateful external dependency for what `.research/`
already does), methodology reference 05's empirical-lifecycle skills (a different loop),
behavioral eval harnesses like ARS's `evals/` (worthwhile, not lean), an auto-threshold
for screening (the threshold is the judgement point Phase 2 exists to keep human), and a
crystals-style cache layer (an isomorphic store — the `.research/` state files already are
the cache).


**Revision 3 (2026-08-04)** — after surveying methodology-reference-02 alongside a
re-read of methodology reference 01 and the original research-skills reference. The `avoided` state is the most consequential
item: it corrects a rubric that would have discarded the best gaps. Adopted:

| Change | Source |
|---|---|
| Mode D contrarian recall; rule 1 now four modes | methodology reference 02 `deep-research` adversarial search perspectives |
| `ars-gap-gate` Gate 0 disqualifiers with short-circuit (rule 12) | methodology reference 02 `idea-evaluator` fatal-flaws-before-scoring |
| Retrieval-bounds rule in Phase 2 (rule 13) | methodology reference 02 `idea-evaluator` novelty-grounding discipline |
| `differing_axis` on `nearest_prior_work` (rule 14) | same |
| G3 shelf life vs execution window (rule 16) | methodology reference 02 handbook §2.1 lifecycle/capability matching |
| `avoided` coverage state; G2 rubric corrected (rule 14) | methodology reference 02 paradigm-shift probe, "elephant in the room" |
| G2 shape probe — four calibration questions, no score | same probe, kept as calibration because their own guidance is that it is not a gate |
| Anchor scoring at 5 and justify movement | methodology reference 02 five-dimension scoring discipline |
| `rs_validate` reports every schema violation, not the first | found while testing the above |
| `found_via` accepted `watch:` — it did not, and `ars-watch` already emitted it | found while testing the above |

Nothing was copied. methodology reference 02 is CC BY-NC-SA 4.0 and this repo is MIT, so every
idea taken from it was re-expressed against this suite's own state model and terminology.


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
