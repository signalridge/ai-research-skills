# ai-research-skills — design

A lean, guarded research skill suite for AI/ML. **One survey engine, four exits.**

Domain: CS / ML / AI. Weight: lean + guarded (~7 skills, 4 hooks, 7 commands).

Revision 7 (2026-08-11) — a source-ledger reconciliation and adversarial evidence repair over
revisions 4–6. See §11 for the full history and the four-category survey ledger. Ideas from
other suites were re-expressed, not copied; no source code, prompts, datasets or assets are
vendored. methodology reference 02 is CC BY-NC-SA 4.0, research skills catalog is CC BY-NC 4.0,
the experiment-generation benchmark has its own restricted source license, and this repo is MIT.

---

## 0. Thesis

Four different deliverables — a go/no-go on a topic, a related-work section, a standing
watch, a build/adopt/skip brief — look like four workflows. They are not. They are four
**projections of one object**: a screened, provenance-tracked, taxonomized corpus with a
coverage map over it.

So the survey is built once and written to typed state on disk. Everything downstream is a
pure function of that state. The survey is the only skill that freely discovers and constructs
the corpus. `ars-watch` may replay the frozen Phase 5 protocol and update corpus/protocol/gaps;
`ars-red-team` may search only for refutation and never extends the corpus. Gap-gate,
related-work and decision-brief are read-only projections; verify performs identifier lookup
only. Missing evidence goes back to `ars-survey`.

This is the main departure from the specific surveyed designs, not a claim that durable
state is unique. ARS reaches literature at Phase 2 *after* the research question is frozen
and makes one typed corpus the sole input to four exits. methodology reference 01 has one flat
`literature-research` skill; scientific skills catalog has a much broader PRISMA-oriented collection; and
methodology-reference-03 already preserves `.research`/`.paper` manifests and handoff
schemas. ARS's narrower distinction is a single corpus with phase-owned writes and
recomputed ledgers, not persistence by itself.

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
  refs.bib          # per-entry rs-provenance attestations; external resolution still required
  notes/<key>.md    # per-paper extraction (only for fulltext-read papers)
  log.md            # append-only: date, query, tool, params, counts, cost
```

### 1.1 `protocol.yml`

`phase` is required and gates validation: Phase 0 validates only the protocol contract;
Phase 1 adds corpus/log, four recall modes and `retrieved >= deduped`; Phase 2 adds
terminal adjudication and score ledgers; Phase 3 adds refs and include extraction; Phase 4
requires gaps plus the complete unique Cartesian coverage grid; Phase 5 adds saturation and
`last_searched_at`. Lower phases are not rejected for future files they do not own.
The count definitions are fixed: `deduped` is the number of unique corpus keys;
`adjudicated` is terminal `include` + `exclude` records (not `unsure`); `unsure` is the
number of `screen: unsure` records; `scored_at_or_above_threshold` counts corpus records
whose relevance reaches `screen.relevance_threshold`; and `fulltext_kept` counts includes
read beyond `abstract`. The validator recomputes these ledgers and requires equality.

```yaml
topic: retrieval-augmented-agents
question: "Do retrieval-augmented agents outperform long-context models on multi-hop QA
           when retrieval quality is held constant?"
created: 2026-08-03
phase: 5                              # required; validation owns fields by phase
last_searched_at: 2026-08-03          # staleness hook reads this
scope:
  in:  [multi-hop QA, agentic retrieval, long-context baselines]
  out: [single-hop QA, RAG for code, multimodal retrieval]
  window: 2023-01-01..
  venues: [NeurIPS, ICLR, ICML, ACL, EMNLP, COLM]

recall_modes:                          # ALL FOUR REQUIRED — see §5 rule 1
  keyword:
    - {tool: arxiv.search_papers, query: 'ti:"multi-hop" AND abs:"retrieval"', categories: [cs.CL], max_results: 50}
    - {tool: openalex.search_entities, entity_type: works, query: '"multi-hop" AND "retrieval"', search_mode: keyword, per_page: 100}
    - {tool: tavily.search, query: "agentic retrieval vs long context multi-hop"}
  citation_chain:
    - {tool: openalex.get_citation_graph, seed_id: W..., direction: cites,    per_page: 100}
    - {tool: openalex.get_citation_graph, seed_id: W..., direction: cited_by, per_page: 100}
  venue_author:
    - {tool: openalex.search_entities, entity_type: works, query: retrieval, filters: {"primary_location.source.id": S..., publication_year: "2025-2026"}, per_page: 100}
    - {group: "<lab name>", via: openalex.resolve_name}
  contrarian:                          # the only mode that hunts disagreement on purpose
    - {tool: arxiv.search_papers, query: 'ti:"rethinking" OR ti:"revisiting"'}
    - {tool: tavily.search, query: "<method> does not improve negative results"}

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
  openalex_usd_spent: 0.06             # illustrative cumulative run total; not a per-call price
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

- **`relevance` + `contextual_summary`** — inspired by retrieval-summary benchmark's RCS. Rather than judging
  include/exclude directly, score 1–10 and write a summary *against the research question*
  (not a generic abstract), then screen by threshold. retrieval-summary benchmark demonstrates metadata-aware
  reranking and contextual summarisation; it does **not** establish a universal
  2,000-to-200-token lossless compression ratio. The `≤300 words` field and the rule that
  load-bearing claims require a source re-read are ARS choices, not a replacement for the
  paper.
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

A prospective `closes_if` remains the watch falsifier. When a Phase 5 watch finds a closing
record it may add typed `closes_if_met: {key, date, rationale}`; a partial match is recorded
as `threats: [{key, date, unmet_clause}]`. Both references are checked against corpus keys.

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

The permission boundary is deliberate: survey is the only free discovery/corpus builder;
watch is the only later updater and only replays the frozen Phase 5 protocol; red-team is a
refutation search and never directly adds results; gap-gate, related-work and decision-brief
are read-only state projections; verify does identifier lookup only.

| # | Skill | Reads | Writes | One-line job |
|---|---|---|---|---|
| 1 | `ars-survey` | — | all of `.research/survey/<slug>/` | The only searcher. 6 phases. |
| 2 | `ars-gap-gate` | corpus, coverage, gaps | `topic_dossier.md` | 3-gate go/no-go, **verdict withheld** |
| 3 | `ars-related-work` | corpus, coverage, refs | `related_work.md` | Thematic prose from verified BibTeX |
| 4 | `ars-watch` | corpus, protocol, gaps | updates corpus, protocol, gaps, and `digests/<date>.md` | Re-run frozen protocol, diff, refresh freshness, re-test `closes_if` |
| 5 | `ars-decision-brief` | corpus, gaps | `brief.md` | Claim→evidence matrix, build/adopt/skip |
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
| **arxiv MCP** | Primary CS/ML discovery. `search_papers` (field-prefixed queries), `get_abstract` (ID→metadata), `get_paper_latex_section` (targeted extraction, no full download), `export_citations` (preferred BibTeX source; authoritative metadata and deterministic keys, followed by per-entry attestation), `watch_topic`/`check_alerts` (standing subscription), and optional `download_paper`/`read_paper` for the PDF fallback | Coverage histograms; non-arXiv venues |
| **openalex MCP** | `get_citation_graph` (`cites`/`cited_by`/`related_to`, cursor-paginated) — ARS's intended high-recall complement to keywords, not a measured recall guarantee. `analyze_trends` (group-by) — **the coverage-matrix primitive**, and the source of the field-growth baseline. `resolve_name` — turn anything into an ID before filtering. `describe_fields` — call before building a query | BibTeX (use `export_citations`); full text |
| **tavily** | Proceedings pages, workshop sites, engineering blogs, anything not indexed | Anything the two above cover |

**Prefer LaTeX or HTML when it is complete and renderable.** For arXiv-dominated work,
`get_paper_latex_section` reads a named section straight from source, with equations intact,
so a parser is often unnecessary—but LaTeX source is not guaranteed. If the source is absent,
launch the arXiv MCP with its optional `[pdf]` extra and use its HTML-first
`download_paper`/`read_paper` path. For proceedings-only papers, image-only tables,
supplements, malformed or unavailable source, use a configured local converter such as
MarkItDown or another pinned parser, then record its version and visual checks. The earlier
document parser 01/document parser 02 BLEU and TEDS figures were removed: they mixed component and end-to-end
metrics without pinned versions, languages or evaluators, and no local apples-to-apples
parser benchmark was run; current document benchmarks also use changing metric families.

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
- Prefer `arxiv.export_citations` for BibTeX and require a per-entry `rs-provenance`
  attestation binding key, stable identifier, tool and date. This is not cryptographic
  proof: an attestation can be forged; `ars-verify` performs the real external lookup.
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
  Were they searched? For example, test whether a retrieval question also appears under
  *multi-stage retrieval*, *retrieval loop* or *iterative search*.
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

- Every `refs.bib` entry has a strict per-entry `rs-provenance` attestation reconciled to
  corpus key/id; external identifier resolution is an `ars-verify` responsibility, and
  attestations are not cryptographic provenance.
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
| `bib_provenance_guard` | PreToolUse on writes to `*.bib` | **denies** | New or modified entries without strict per-entry `rs-provenance` (key, stable id, tool, date). A legacy file-level marker only preserves unchanged old entries. Attestations can be forged; `ars-verify` must resolve the identifier externally. |
| `absence_claim_guard` | PostToolUse on writes to `*.md`, `*.tex`, `*.markdown`, `*.mdx` | Claude PostToolUse block; Cursor/Codex pre-write deny | Regex for `no prior work`, `first to …`, `to the best of our knowledge`, `has not been …`, `remains unexplored`, `no one has`, plus CJK equivalents → demands a `gaps.yml` entry whose `evidence_of_absence.queries_run` carries ≥3 phrasings. **The signature guardrail of this design.** |
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
  rests on; it cannot tell you what you concluded from it. methodology reference 01 does provide a fresh
  Stop peer, but ARS intentionally omits that loop/cost here; `ars-red-team` is the place a
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
   anchor: the cited literature QA task v2 results are commonly reported in the **0.06–0.35** range under
   a no-retrieval condition, versus **0.70** for humans with search. The dedicated result
   source was not available for local re-verification in this audit, so these are retained
   only as qualified benchmark context, not a universal model limit. Memory is not a source.
3. **Abstention is a tracked state; coverage is reported separately from precision.** ←
   literature benchmark defines accuracy, precision and coverage separately. A commonly cited literature QA task v2
   result gives a Claude 3.5 Sonnet row with **12%** answered and **47%** correct among
   answered items (rounded accuracy **0.06**), but that result was not locally re-verified
   here. Treat it as qualified benchmark context, not a claim about Claude in every setup.
   A survey that judged 40 of 200 candidates and one that judged all 200 must not look
   identical.
4. **Score, then threshold — never judge include/exclude directly.** ← A binary call is
   irreversible and untunable; re-tuning means re-reading. retrieval-summary benchmark's RCS scores or
   reranks evidence against the question and adds contextual summaries with metadata. ARS
   does not treat those summaries as lossless substitutes for the source.
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
7. **BibTeX entries carry strict provenance attestations.** ← The current hook contract cannot
   cryptographically prove which tool produced bytes. Require per-entry key/id/tool/date,
   reconcile with the corpus, and be explicit that `ars-verify` performs external resolution;
   do not promise “tool-generated” or “no hand-written” as a guarantee.
8. **Absence claims require typed evidence.** ← "No one has done this" is the highest-risk
   sentence in research, and the cheapest to say. `confidence: high` requires ≥3 phrasings,
   ≥3 venue-years swept, and forward chains from the nearest prior work.
9. **Every gap carries a `closes_if` falsifier.** ← Gaps close silently. Without a
   pre-registered falsifier there is nothing for `ars-watch` to test, and you find out at
   submission.
10. **Extraction is open-response; never a checkbox.** ← literature benchmark v2 reports model-specific
    accuracy differences of **−26% to −46%** across corresponding task families. Its paper
    attributes that gap jointly to open-response answers and more realistic
    retrieval/file/context framing, not to one isolated ablation. The result still warns
    against reducing extraction to "Is this paper relevant? Y/N". Make the model state what
    the paper actually claims, in its own words.
11. **A quoted number names its table and was looked at.** ← literature benchmark v2 splits figure/table
    tasks into `img` / `pdf` / `retrieve` variants because *finding* the right table is
    much harder than reading a given one. Independently, methodology reference 01 ships a `visual_check`
    hook and the experiment-generation benchmark added a VLM figure-review loop. Three systems converged here.
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
  package index, not a workflow. The inspected checkout is roughly half a gigabyte, but the
  exact size is revision-dependent and not a design metric.
- **Mandated paid CLIs.** scientific skills catalog routes search through a paid search CLI + hosted model router. The
  arxiv + OpenAlex MCPs already cover search, citation graphs, targeted section reads,
  authoritative BibTeX, coverage histograms, and standing alerts.
- **A 13-agent team for the survey.** Lean means the survey is phases-in-one-context with
  state on disk, not a fan-out. `ars-red-team` is the one place a genuinely independent context
  earns its cost.
- **PRISMA compliance.** Right for biomedical, wrong here. The counts and the screening log
  are kept (they're just good practice); the formal apparatus is not.
- **Agentic tree search** (experiment-generation benchmark). The benchmark README says v2 does not necessarily
  beat the template-driven v1 and explores more broadly with lower success rates. The paper's
  workshop result is a selected, best-of-run experiment rather than a run-level success-rate
  estimate; its acceptance-rate context is not a sound base rate for this suite. Multi-worker
  exploration plus `max_debug_depth` auto-repair costs more than it returns at this scale, so
  tree search remains rejected on complexity, evidence denominator and fit—not on an invented
  success statistic. The one cheap idea — inspecting figures with a VLM — is already
  re-expressed as rule 11; no benchmark code or prompt is reused.
- **A mandatory document-parsing layer.** See §2.1: prefer author source, but keep an
  optional fallback chain for documents whose usable evidence exists only as PDF or image.
  The fallback is on demand; document parser 01, document parser 02, document parser 03 and MarkItDown are not core ARS
  dependencies.

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

OpenAlex is metered. This shapes how `ars-survey` is allowed to query it. Setup and
verified failure modes are in [SETUP.md](SETUP.md); the API and the MCP server report the
actual cost and remaining budget in response metadata/headers, and quotas can vary by account
and operation.

Three rules fall out of this:

1. **Use the largest legal page size.** Use `per_page: 100` for keyword/exact/list and
   citation-graph calls; OpenAlex semantic search is capped at **50** and is rate-limited
   to roughly one request per second. The cost is per call, not per result.
2. **Resolve once, then use IDs.** Singleton lookups are free in the current pricing model;
   search is more expensive. `resolve_name` → cache the `W…` id in
   `corpus.jsonl.openalex_id` → every later touch can use the ID path.
3. **Log spend in `protocol.yml.budget`.** The MCP reports what each call spent and what
   remains when upstream supplies the accounting headers; a survey that dies mid-sweep on a
   429 has corrupted its own saturation count.

Do not hardcode a full-round price. Record the returned cost, query shape, cursor, account
condition and date; the live service and server version are the evidence for that run.

---

## 9. Hosts — where this can actually run

Revision 4's distribution rework. The suite installs into five agent hosts, and the
selection rule is the same one §3 rests on: a host needs a documented hook surface, not
merely a skills directory. Installer output says configured rather than asserting runtime
activity; doctor reports Pi as configured-but-inactive when its extension cannot be checked.

| Host | Skills | Commands | Guardrails | Config written |
|---|---|---|---|---|
| claude | `.claude/skills` | `.claude/commands` | yes | `.claude/settings.json` |
| codex | `.codex/skills` | — | yes | `.codex/hooks.json` (`hooks` object at top level; foreign groups preserved) |
| cursor | `.cursor/skills` | — | write-time only | `.cursor/hooks.json` (camelCase, `version: 1`, direct definitions; stop omitted because only follow-up responses are safe there) |
| pi | `.pi/skills` | — | configured\* | `.pi/settings.json` |
| kimi | `.kimi/skills` | — | no | — |

\* configured but not claimably active until `pi install npm:@hsingjui/pi-hooks`; the
installer/doctor says so rather than letting an inert config read as protection. Cursor's
`stop_survey_peer` is not installed: Cursor has a native `stop` event, but its follow-up
response would turn this advisory into a continuation loop, so the adapter reports it as
intentionally degraded.

Three consequences worth stating, because each one fails silently:

1. **Skills-only adapters were removed, not shipped.** Six hosts (qwen, opencode, windsurf,
   kilo, kiro, copilot) previously received the methodology with none of the enforcement.
   Kimi remains explicitly skills-only; Cursor and Pi carry honest degraded/runtime caveats.
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

## 10. Installer integrity boundary

The installer writes a sealed manifest and a small, fsynced transaction journal before its
first project mutation. A new invocation restores an unfinished journal before planning;
normal completion removes it only after the metadata directory is synced. Upgrades accept
new package bytes only when the current bytes equal the selected host's old manifest
record, remove unmodified stale records, and refuse modified managed files. Uninstall
preserves modified files and modified hook definitions while continuing with the exact
owned remainder.

Hook ownership is an exact handler definition (or an exact published v0.5 command during
manifest adoption), never a basename substring. Non-Claude commands contain a securely
quoted absolute project path and an explicit host profile, so launching an agent from a
subdirectory does not redirect a hook to the wrong project. Claude deliberately retains
`$CLAUDE_PROJECT_DIR`.

The symlink checks run again immediately before every write/remove and reject symlinked
ancestors. This is a static ordinary-local-workspace boundary: without platform-specific
`dir_fd`/`openat` transactions, the installer does **not** claim to resist a privileged
concurrent process replacing a directory between that check and the filesystem call.

---

## 11. Changelog

**Revision 7 (2026-08-11)** — local-source audit, license reconciliation, and second-read
correction of methodology, benchmark, tool and runtime claims. This is a decision ledger, not
a claim that every source is compatible with MIT. The controlling repository license governs
source expression; ideas below are independently phrased, and no source code, prompt,
benchmark asset or image was copied.

### 11.1 Methodology

| Source and license | First read | Second read / recheck | ARS decision |
|---|---|---|---|
| `methodology-reference-01` — MIT | Flat literature workflow, progressive disclosure, and visual-check hook; its literature file has a relevance column but no developed scoring rubric | Second read separated the genuine hook/workflow evidence from ARS's own relevance rubric and centrality rule | **Adopted:** progressive disclosure, visual/figure inspection, and the rule that a claim must name what was actually read. **ARS-owned:** relevance scoring and method-family centrality. |
| `methodology-reference-02` — CC BY-NC-SA 4.0 (some files carry conflicting metadata) | Idea-evaluator, pre-submission integrity gates, paradigm-shift/lifecycle prompts, synthesis and hedge calibration | The repository license is non-commercial/share-alike; per-file metadata does not relax the repository license. The second read found that weaving, `not reported`, hedge levels and blind-spot checks belong here, not under methodology reference 07/methodology reference 05 | **Idea-only, independently re-expressed:** integrity gates, successor checks, lifecycle matching, evidence weaving and calibrated absence language. **No text, prompt, code or asset copied.** |
| `methodology-reference-03` — MIT; `methodology-reference-04` — MIT | Handoff-oriented skills; `.research`/`.paper` artifacts; `gap-to-topic` with open/contribution/feasibility gates | Durable manifests and handoffs were missed in the first pass; `gap-to-topic` has gates but not ARS's `closes_if` re-test loop | **Adopted with distinction:** typed state, handoffs, three-gate structure and salvage paths. ARS keeps one corpus and phase-owned writes; it does not claim persistence is unique. |
| `host-reference-01` — BSD-3-Clause | Project-local `.claude` layout, install/upgrade boundary and distinctive skill prefix | Second read confirmed this is distribution/host methodology, not research evidence; it does not justify copying implementation into ARS | **Adopted:** layout/prefix and honest host capability reporting. **Omitted:** host distribution reference runtime code and unrelated adapters. |
| Current `ars-*` reference surface — this MIT repository | First pass used shorthand tool arguments and a legacy arXiv server name in examples/frontmatter | Second read reconciled examples to `query`/`categories`/`max_results`, singular `seed_id`, schema-legal page sizes, and the registered `arxiv` deny name; verification now denies broad search/graph tools and routes missing identifiers back to survey | **Rechecked and corrected:** docs and skill metadata now describe the one-survey-engine/no-search boundary rather than relying on an alias or an invalid replay contract. |
| `methodology-reference-05` — MIT; `methodology-reference-06` — MIT; `methodology-reference-09` — Apache-2.0 | Handoffs, claim confidence, falsification-first framing, dependency closure and explicit truth-seeking buckets | Re-read confirmed these are methodology patterns, not permission to import implementation; the falsification reference's four-layer hierarchy and 500-line checkpoints are scale-heavy, and the exact infrastructure-vs-claim split is ARS-owned | **Adopted:** claim corroboration, refutation conditions, untrusted retrieval, dependency checks and an oracle-needed/honest-residue state. **Rejected/omitted:** hierarchy/checkpoint bulk. |
| scientific skills catalog — MIT; `catalog-reference-02` — CC BY-NC 4.0 | Broad skill/catalog approach, PRISMA, multiple databases and eval registry | scientific skills catalog advertises 161 skills/100+ databases, but its `research-lookup` skill also emits a durable packet with evidence, coverage and search ledgers; catalog reference 02's registry is a catalog, not evidence that ARS should grow | **Rejected/omitted:** full RAG/PRISMA, external bibliography application state, 160+ skills, paid search CLI/hosted model router and a multi-agent survey team. **Kept selectively:** explicit screening counts, source breadth and the packet/state idea, while narrowing ARS's uniqueness claim to one corpus/four exits. |
| `catalog-reference-03`, `catalog-reference-04`, and `catalog-reference-05` — comparison catalogs; no source license relied upon | Broad research/Claude skill catalogs and generic task prompts | Second read found no ARS-specific evidence or runtime need beyond ideas already covered above; catalog breadth is not a quality measure | **Omitted:** no prompts, assets, license-dependent text or code adopted. These repositories remain pointers for future review, not ARS dependencies. |
| `methodology-reference-07` — MIT; `methodology-reference-08` — repository skill metadata reviewed | Research contract, source trust and calibrated claim wording | Useful controls are compatible with ARS; second read found that the weaving, `not reported` and hedge-ladder ideas are better attributed to methodology reference 02, not methodology reference 07; no license exception was assumed for copied wording | **Adopted:** abstract-only limits, dated/bounded absence language and source-trust ordering, independently written. **Not credited here:** synthesis/weaving rules sourced to methodology reference 02. |

**Reviewed but intentionally omitted in Revision 7:** a five-grade citation verdict with a
paywall metadata-only bucket, `quote_verified` enforcement, a data-refuted-mechanism Gate 0,
a separate A/B counter-signal check, an oracle-required red-team bucket, a six-fold quality
gate matrix, a fresh-context Stop peer, and PreCompact transcript capture. These are useful
future candidates, but they would alter schemas/hooks or add cost beyond this source-ledger
pass. The same applies to a corpus-presence validator for `revivable_by`; the field is
retained as a methodology idea, while implementation hardening remains separate.

**Source identity and attribution correction:** the audited methodology, benchmark and tool
snapshots are represented only by neutral aliases in this public tree; exact repository
identities, URLs and commit pins are intentionally omitted. License categories and the
independent-expression boundary remain recorded, but no source text, code, prompt,
benchmark asset or image is bundled. The second read corrected which neutral alias owns each
idea: the gap-analysis reference owns `revivable_by`/dead-end and misclassification machinery;
the integrity-gate reference owns synthesis, hedge and blind-spot antecedents; the
literature-workflow reference supplies the pointer and visual-check/workflow evidence; the
scientific-skills catalog supplies durable research-lookup packets, not "no reusable output";
and the host-distribution reference supplies a naming/layout convention, not ARS's installer
or hook merge. A few overly close re-expressions in the shipped skills were rewritten during
this revision.

**Methodology recheck outcome:** preserve the one-survey-engine/no-search invariant and the
`ars-*` namespace. Search, citation traversal and corpus construction remain owned by
`ars-survey`; exits are projections or refutation/verification passes. Do not turn an idea
borrowed from a non-MIT source into a copied prompt or bundled asset.

### 11.2 Benchmarks and empirical claims

| Source and license | First read | Second read / recheck | Decision and qualification |
|---|---|---|---|
| `benchmark-reference-02`, CC BY-SA 4.0; [paper](https://arxiv.org/abs/2407.10362) | README reports 8 categories and 30 subtasks; the inspected checkout snapshot is a 2025 snapshot with a public multiple-choice literature QA task v2 harness. | The cited literature QA task v2 results are commonly reported as roughly 0.06–0.35 under a no-retrieval condition and 0.70 for humans with search, but the dedicated result source was not available for local re-verification in this audit. | **Retained only as qualified motivation** for evidence reading, abstention and retrieval; not a universal model bound or a locally verified acceptance criterion. The public harness is not open-answer evidence. |
| `benchmark-reference-03`, CC BY-SA 4.0; [paper](https://arxiv.org/abs/2604.09554) | README describes nearly 1,900 tasks and paired `img`/`pdf`/`retrieve` variants. | Paper §3.1/Table 1 confirms the −26% to −46% figures are model/task-family differences, not a one-factor ablation. | **Retained with correction:** open-response, retrieval, file and context realism jointly affect difficulty; open-response alone is not established as the cause. |
| `benchmark-reference-01` / retrieval-summary benchmark, Apache-2.0; [paper](https://arxiv.org/abs/2409.13740) | README describes RCS, reranking/contextual summaries and metadata-aware retrieval. | Paper §8.1.1 reports 200–400-token summaries against a 2,250-token chunk baseline and no decrease in summarization efficacy across tested chunk sizes; that is not a universal downstream lossless-compression result. | **Adopted selectively:** score-then-threshold and question-conditioned summaries. **Rejected:** full bibliography parser/vector RAG and any claim that summaries replace source re-reading. Summaries are pointers; load-bearing claims are re-read. |
| `benchmark-reference-04`, custom restricted license | README says v2 explores more broadly and can have lower success. | Paper §4.1–§4.2 reports a selected/best-of-run result and supplies no denominator for a general run-level success rate. | **Rejected:** tree search, auto-repair and broad parallel exploration. **Adopted only as an independently phrased idea:** inspect figures/plots before trusting a quoted number. No source code, prompt or asset is used. |

**Benchmark recheck outcome:** exact benchmark numbers are tagged by benchmark, model/tool
condition and source status; the literature QA task v2 accuracy/coverage figures remain an unverified
transcription in this environment and are not normative. literature benchmark v2's paper and README also
use different dataset identifiers; cite the exact source/version rather than assuming one
canonical URL, and do not copy the dataset. SourceQualQA and the Image→Paper→Retrieval
visual-difficulty ladder are useful future evaluation anchors, but no benchmark task assets
are copied and ARS's own tests remain the implementation check. No local claim uses a
multiple-choice result as proof of open-answer performance, or a selected experiment-generation paper
as a base rate. A benchmark is methodology motivation, not a runtime dependency or a
substitute for ARS's own tests.

### 11.3 Tool comparisons

| Tool/source and license | First read / second read | ARS decision |
|---|---|---|
| `runtime-reference-01` — Apache-2.0 | The local `get_paper_latex_section` path is bounded and preserves source equations; package is 0.6.2, Python ≥3.11, with optional `pdf` and `pro` extras. The installed tool also has `get_abstract`, `download_paper`/`read_paper` and a external citation-provider-backed `citation_graph`. | **Adopted:** targeted LaTeX reads, ID metadata, and `export_citations`; pin/document the package. **PDF extra remains fallback-only; `pro` semantic search and a second citation-search path are not required.** |
| `parser-reference-01` — MIT; `parser-reference-02` — Apache-2.0 plus additional terms | Readme capabilities are not a controlled head-to-head quality study for this suite. Standalone table-extraction TEDS results survive as component-model evidence, but earlier BLEU/TEDS prose did not identify that distinction or pin an end-to-end evaluator. document parser 02's additional commercial/service terms were also noted. | **Omitted as runtime dependencies.** Keep parser fallback by document fit, not a universal superiority claim; any future document parser 02 use requires reviewing those additional terms separately. |
| `parser-reference-03` — MIT client in the inspected legacy checkout; hosted service is separate | The old repository is deprecated/archived in favor of the current LlamaIndex distribution; cloud pricing/network/API state would be a separate dependency | **Rejected as a dependency and as evidence.** A deprecated checkout cannot support a current superiority claim; author-source and local fallback paths are sufficient. |
| `bibliography-reference-01` — AGPLv3 | external bibliography application supplies useful user-managed bibliography state, but it is an external application/database and introduces licensing/state coupling | **Rejected:** no external bibliography application state dependency, connector or copied assets. `arxiv.export_citations` plus per-entry `rs-provenance` is sufficient. |
| `markitdown-mcp` — optional user-level converter; no license dependency adopted | A local `uvx markitdown-mcp` entry is available in the audited environment; it converts PDF/Office/HTML to Markdown without adding ARS package state | **Adopted only as a named, on-demand fallback.** It is not installed by ARS, not used for discovery, and must be version-recorded with visual checks; no code or asset is vendored. |
| PDF comparison as an experiment | No local apples-to-apples run fixed parser version, corpus, language, table/equation mix and evaluator; current external benchmarks have also moved from BLEU toward other metrics | **Omitted, explicitly.** The design says when to fall back, not which parser always wins. |

**Tool recheck outcome:** prefer arXiv LaTeX/HTML when complete; then use the optional arXiv
`[pdf]` fallback or configured MarkItDown/parser only when the source needed for evidence is
otherwise inaccessible or malformed. retrieval-summary benchmark's relevant-seed citation traversal was
reviewed but not added as a second search policy; the existing bounded OpenAlex/arXiv split
remains the single survey engine. Do not silently introduce document parser 01, document parser 02, document parser 03,
MarkItDown or external bibliography application as core dependencies through examples or install metadata.

### 11.4 Runtime dependencies and live checks

| Dependency or claim | Recheck | Decision |
|---|---|---|
| OpenAlex MCP / REST — inspected server Apache-2.0 | A live REST smoke test on 2026-08-11 succeeded without a key; `mailto` was accepted; responses exposed `meta.cost_usd: 0.001` and budget headers. `/rate-limit` without a valid key returned HTTP 401. The current schedule was also checked: ID singleton $0, list/filter $0.0001, keyword/semantic search $0.001, with $0.10 anonymous and $1 keyed daily limits. | **Corrected:** ordinary requests do not require an API key in this test; a key is needed for the rate-limit endpoint/account inspection. `mailto` remains optional courtesy metadata, not a quota replacement. Singleton bodies may omit `meta`; response headers/MCP budget enrichment are authoritative. The schedule and a nominal ~$0.04 round are not a promise for every query mix. |
| OpenAlex runtime, pagination and search modes | Package 0.7.8 requires Node ≥24 or Bun ≥1.3. Current server schema distinguishes keyword/exact/list/citation page sizes from semantic search; semantic search is capped at 50 and rate-limited | **Corrected:** use 100 only where the tool schema permits it; never emit unconditional `per_page: 100`. Resolve IDs before graph walks and call `describe_fields` before unfamiliar filters. |
| arXiv MCP package | Inspected `pyproject.toml`: version 0.6.2, Python ≥3.11, optional `pdf` and `pro` extras; LaTeX section and citation tools are the needed surface | **Adopted as the documented baseline:** pin 0.6.2 in setup examples; do not require PDF or semantic extras for the core suite. |
| Setup and worked-example contracts | First read presented an existing-environment inventory and a synthetic fixture with stale real-count prose/legacy argument names | Second read added an arXiv install baseline, labeled Tavily as optional/provider-specific, and corrected fixture counts, synthetic trend wording and replay argument shapes | **Rechecked and corrected:** examples teach state/schema behavior without pretending their papers, trends or spend are live evidence. |
| Tavily and other hosted search | Local web verification was unavailable (Tavily returned HTTP 432 during this audit); local clones and direct APIs were used instead | **Optional only:** no hosted search result is treated as verified evidence when the service fails. The one-survey engine may stop rather than silently write from memory. |
| Host adapter runtime caveats | The integration audit found host-specific hardening follow-ups (Pi's absence guard is post-write/advisory until its extension supplies a pre-write event; Cursor payload/ownership edge cases need separate regression work). No live host session was claimed as verification. | **Recorded, not folded into this source-adaptation change.** README/DESIGN continue to label Pi unconfirmed, Cursor degraded, and hooks fail-open; these are implementation follow-ups, not new runtime dependencies. |
| Full RAG, vector stores, hosted parsers and external bibliography state | Rechecked against current `ars-*` imports, setup, tests and package assets | **Not runtime dependencies.** Preserve the minimal backend split: arXiv for preprints/source/BibTeX/alerts, OpenAlex for graph/trends/IDs, optional web search for non-indexed material. |

**Runtime recheck outcome:** documentation now distinguishes methodology references from
runtime requirements and benchmarks from implementation. `ars-*` remains the package
architecture; no external state or second survey/search engine is introduced.

**Revision 6 (2026-08-07)** — adversarial distribution and state-integrity repair.

| Change | Why |
|---|---|
| Host hook adapters | Codex now emits `{hooks: {...}}`; Cursor receives native direct definitions, puts absence denial on `preToolUse`, and omits its unsafe stop advisory. Pi is reported configured-but-unconfirmed. |
| Payload operations | Claude `file_path`, Pi `path`/`edits[].newText`, and Codex Add/Update/Delete/Move patches are parsed as isolated per-file operations. |
| Ownership transaction | A root manifest seals ordinary-file hashes and exact handlers. Preflight covers every host before atomic fsync/replace writes; rollback, symlink rejection, conflict refusal and legacy preservation prevent partial or destructive upgrades. |
| Phase-aware ledgers | `phase` is required; counts, full Cartesian coverage, occupant/found-via reconciliation and typed gap closures are recomputed only when their phase owns them. |
| Stdlib validator | `_yaml_subset.py` and `_schema_subset.py` are copied into every install. Clean isolated Python validates worked state and rejects broken state without PyYAML/jsonschema. |
| Provenance honesty | New/modified BibTeX entries need per-entry `rs-provenance` key/id/tool/date and corpus reconciliation. This is a forgeable tripwire, not cryptographic proof; external resolution remains `ars-verify`. |
| Permission boundary | Survey alone freely discovers; Phase 5 watch alone replays and updates state; red-team refutes without appending; the other exits are read-only projections and verify only looks up identifiers. |

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
| `.claude/` layout + ARS's `install.py` (skills/commands/hooks install into a project's `.claude/`, hooks merged into `settings.json`); plugin distribution dropped | host distribution reference's per-host skills-directory layout; the installer and hook merge are ARS-owned, not host distribution reference behavior |
| Skills and commands `rs-`-prefixed; commands flat under `.claude/commands/` | host distribution reference's distinctive prefixed naming convention; the `rs-`/`ars-` choice is ARS-owned |
| AI venue universe + default arXiv category set + AI taxonomy axes; Hugging Face routed as a first-class source | orientation, not a source |
| `ars-red-team` truth-seeking verdicts (three buckets, refutation-conditions, no hardening) | methodology reference 06 falsification-first skills |
| `## Handoffs` contracts + closure check in `run_tests.py` | methodology reference 05 handoff sections; the dependency-closure reference's verifier |
| `corroboration` on corpus records | methodology reference 05 claim-level confidence metadata |
| Source trust ranking; abstract-only never supports a conclusion; conditional outputs (intake note over thin section) | methodology reference 07 research-contract |
| `ars-gap-gate` integrity gate with [inspection]/[attestation] classes, run silently | methodology reference 02 idea-evaluator / pre-submission-reviewer integrity gates — missed on the first read |
| Opening-type classification (method-limitation vs unoccupied-application) shaping the kill test | methodology reference 04 gap-to-topic §0 — missed on the first read |
| Count reconciliation in Phase 1 (expected vs retrieved, reported page size) | The gap-analysis reference's screening ledger; scientific skills catalog source-breadth discipline was a secondary influence |
| `revivable_by` on `abandoned` cells — a failure attributed to a specific tool, with a documented successor in the corpus, is promotable; the "newly possible" shape was being filtered out before it could become a gap | methodology reference 04 `gap-to-topic` dead-end-history; methodology reference 02 supplied the adjacent paradigm-shift framing |
| Step B/C misclassification filters — "X fails, therefore we propose Y" is an attempt, not a verdict; temporal silence needs a success-paper check before `abandoned` | methodology reference 04 `gap-to-topic` dead-end-history; independently re-expressed |
| `ars-verify` splits `unresolved` from `unverifiable-now`; `ars-watch` refreshes `last_checked` only on answered zero-hit queries — an infrastructure hiccup never manufactures freshness or deletes a citation | the falsification reference's oracle-needed/honest-residue bucket plus ARS's own state model; not a claim that methodology reference 09 defines this exact distinction |
| Retrieved-content-is-untrusted discipline in Phase 1, pointed back to from Phase 3 extraction | scientific skills catalog research-lookup and broader agent-research prompt-injection guidance; independently re-expressed |
| Reference links follow progressive disclosure and are checked by the current layout suite | the dependency-closure reference's idea, extended in ARS; the old changelog wording overstated a dedicated one-level test |
| Wording ladder anchored on `corroboration`; survey records support field-level statements only; comparison weaving; "not reported" table cells; bounded absence claims; dated time words | methodology reference 02 deep-research synthesis/hedge calibration, with methodology reference 07's source-trust contract; independently re-expressed |
| Excludes read as a blind-spot signal before gap analysis — a clustered exclude reason is an undeclared Phase 0 axis | methodology reference 02 deep-research search-strategy discard check; independently re-expressed |
| Zero-corroboration stop-hook check; full reads scan limitations and "we found" sentences for author-stated caveats | methodology reference 05 claim-level confidence, second read |
| Gate 0 baseline-recency disqualifier — a >12-month-old strongest baseline in a >2×/yr field means the real baseline is unpublished | methodology reference 02 lifecycle matching, second read |
| Method-family centrality scoring for narrow questions — parent-field relevance caps at 3–4 when the family is only mentioned | ARS's own narrow-question scoring design; methodology reference 01 supplied literature-workflow structure, not this rubric |
| Salvage path on every no-go; an unoccupied-application opening is not automatically incremental | methodology reference 04 gap-to-topic, second read |
| awesome-lists as pointers, never records | methodology reference 01 literature-research Step 2d; independently re-expressed |

Rejected this round: the falsification reference's four-layer hierarchy and ≥500-line checkpoints (scale-driven
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
| Mode D contrarian recall; rule 1 now four modes | methodology reference 02 `deep-research` adversarial-search perspective; methodology reference 01 supplies the keyword/citation/venue mode shape and methodology reference 04 supplies the failure-term query vocabulary |
| `ars-gap-gate` Gate 0 disqualifiers with short-circuit (rule 12) | methodology reference 02 `idea-evaluator` fatal-flaws-before-scoring |
| Retrieval-bounds rule in Phase 2 (rule 13) | methodology reference 02 `idea-evaluator` novelty-grounding discipline |
| `differing_axis` on `nearest_prior_work` (rule 14) | same |
| G3 shelf life vs execution window (rule 16) | methodology reference 02 handbook §2.1 lifecycle/capability matching |
| `avoided` coverage state; G2 rubric corrected (rule 14) | methodology reference 02 paradigm-shift probe, "elephant in the room" |
| G2 shape probe — four calibration questions, with ARS intentionally dropping the source's Yes/Partial/No score | methodology reference 02 paradigm-shift probe; its source scores 0–8 but says the result is not a gate, while ARS keeps qualitative calibration only |
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
| Rule 2 gains a qualified literature QA task v2 anchor (0.06–0.35 vs 0.70 human) | Cited literature benchmark/literature QA task v2 results under stated model/tool conditions; dedicated result source was not locally re-verified in Revision 7 |
| Rule 10 — extraction is open-response, never a checkbox | literature benchmark v2's model-specific −26%/−46% differences; the paper attributes them jointly to answer format and realistic retrieval/file/context framing |
| Rule 11 — `numbers[].source` + `looked_at` | literature benchmark v2 `retrieve` variants; methodology reference 01 `visual_check`; the experiment-generation benchmark's VLM loop |
| Saturation measured only on pre-`created` publications (§1.1, rule 5) | Earlier live `openalex.analyze_trends` probe; exact response not preserved, so its year series is not a normative benchmark |
| OpenAlex backend: citation graph, `analyze_trends` as the coverage primitive (§2.1, §8) | Current tool schemas and live budget headers |
| Prefer LaTeX/HTML when complete (§2.1) | arXiv MCP's bounded LaTeX-section read; no local parser head-to-head experiment |
| Tree search explicitly rejected (§6) | the experiment-generation benchmark's qualitative lower-success warning and complexity/scale mismatch; no general success rate claimed |

Rejected from that report: document parser 01/document parser 03 as a mandatory general layer (author source
is preferred when usable, but parser fallback remains), the full retrieval-summary benchmark RAG stack (bibliography parser
+ vector index — we want the RCS *idea*, not the system), and treating `mailto=` as an
OpenAlex quota mechanism. The current OpenAlex server accepts `mailto` as optional courtesy
metadata; it is not a substitute for `api_key`, and budget headers are authoritative for a
run.
