# Changelog

## 0.2.0 — 2026-08-04

Integrates ideas from [methodology-reference-02](methodology-reference-02)
alongside a re-read of methodology reference 01 and ai-research-skills. That project is CC BY-NC-SA 4.0
and this one is MIT, so every idea was re-expressed and no text was copied — see
[CREDITS.md](CREDITS.md).

### Added

- **Mode D: contrarian recall.** A fourth mandatory recall mode that searches for
  counter-evidence — negative results, failed replications, the opposing camp, method
  critiques. The other three modes are all biased toward consensus, and without this one
  `red-team`'s cherry-picking check could only find contradictions already in the corpus.
- **`gap-gate` Gate 0.** Cheap disqualifiers run before any scoring and short-circuit on a
  hit. Scoring a candidate that was dead on arrival manufactures a document that looks
  considered when it was moot.
- **`avoided` coverage state, and a corrected G2 rubric.** `avoided` and `abandoned` both
  mean the work stopped, and they score at opposite ends: `abandoned` is a dead end,
  `avoided` is an acknowledged problem the field routes around because it is hard.
  Previously both collapsed to `abandoned`, which G2 scored 1 — so the gate would have
  systematically discarded the highest-value class of gap. Phase 4 gains Step C, which
  discriminates them by counting papers that name the problem as future work without
  attempting it.
- **G2 shape probe** — four calibration questions (hidden assumption, known-and-avoided,
  newly possible, so-what). No score attaches; it exists so the dossier's framing matches
  reality in both directions, since dressing an incremental gap as a paradigm shift invites
  a reviewer to puncture it and burying a structural one wastes it.
- **Shelf life versus execution window** in G3. An open, worthwhile, technically reachable
  gap is still a no-go if it closes before you finish. Asks for effective hours per week,
  not calendar time.
- **`differing_axis`** on `nearest_prior_work` — object-acted-on, mechanism,
  input-granularity, problem-setting, or `none`. A similar title never establishes that a
  gap is taken; failing to find one differing axis establishes that it is.
- **Retrieval-bounds rule** in Phase 2. Search results support metadata-level judgements
  only; numbers and method details come from Phase 3 with a named source. "Not found" is
  reported as nothing retrieved under these keywords, never as nothing exists.
- **Anchor-at-5 scoring.** Starting from "probably relevant" produces a corpus where
  everything scores 7.
- **Capability gate.** If the search backends are unreachable, `survey` says so and stops
  rather than writing from memory.

### Fixed

- `rs_validate` reported only the **first** schema violation per document, hiding later
  ones behind earlier ones and turning a fix into a fix-rerun-repeat loop. It now reports
  all of them.
- The `found_via` pattern rejected `watch:<date>`, which `watch` already emitted. Any
  record added by a watch run would have failed validation.


## 0.1.0 — 2026-08-03

First release. Survey-first research suite for CS/ML: one survey engine, four exits.

### Architecture

- **`survey`** is the only skill permitted to search. Six phases — scope, recall, score,
  extract, map, saturate — each in its own `references/0N-*.md`, loaded on entry.
- **Four exits** are pure functions of the state the survey wrote: `gap-gate` (3-gate
  go/no-go, verdict withheld), `related-work`, `watch`, `decision-brief`.
- **Two cross-cutting audits**: `red-team` (adversarial, two checkpoints) and `verify`
  (citation and number integrity).
- State lives in `.research/survey/<slug>/`, typed by four JSON Schemas, so it survives
  context compaction, a new session, or a hand-off.

### Decisions worth knowing about

- **Taxonomy axes are declared in Phase 0, before searching.** A taxonomy built after
  reading describes your sample, not the field, and every empty cell in it is an artifact
  of what the search happened to find.
- **Score, then threshold** — never a direct include/exclude call. The boundary stays
  re-tunable without re-reading anything. Adapted from retrieval-summary benchmark's RCS.
- **`screen: unsure` is a terminal state** and coverage is reported separately from what
  was decided. literature benchmark reports accuracy, precision and coverage as three numbers for a
  reason: a model answering 12% of questions at 47% precision scores 0.06 accuracy, and
  collapsing that into one number destroys the information that matters.
- **Saturation is measured only on papers published before the survey started.** A paper
  published after that did not exist when you began; it is field growth, and it belongs to
  `watch`, not to another round. Conflate the two and a field growing 3× a year never
  converges.
- **An empty cell is not automatically a gap.** `unexplored` requires trend evidence
  distinguishing it from `abandoned`; `undecided` is the honest default.
- **Every gap carries a `closes_if` falsifier**, written in advance, re-tested by `watch`
  against every new paper.

### Guardrails

Four hooks, all fail open — a guard that crashes and blocks real work is worse than no
guard.

- `bib_provenance_guard` blocks `.bib` writes with no tool provenance.
- `absence_claim_guard` blocks absence claims with no backing `gaps.yml` evidence.
  Silent outside a survey project.
- `survey_staleness` surfaces corpus age at session start.
- `stop_survey_peer` audits the corpus at end of turn: abstract-only conclusions,
  unadjudicated tails, single-mode recall, gaps with no nearest prior work.

The no-search invariant is also enforced structurally: `gap-gate`, `related-work`,
`decision-brief` and `verify` carry `disallowed-tools`, so search tools are removed from
the pool while they are active.

### Backends

`arxiv` for discovery, targeted LaTeX section reads, authoritative BibTeX and standing
alerts. `openalex` for citation graphs and `analyze_trends` as the coverage-matrix
primitive. `tavily` for what neither indexes. Never parse a PDF when LaTeX or HTML exists.

OpenAlex has required an API key since 2026-02-13; the `mailto=` polite pool is now
silently ignored. See [SETUP.md](SETUP.md), which also records failure modes verified
against the live API.

### Tests

61 assertions, standard library only. Twelve of them feed each hook malformed input to
assert it fails open. Ten assert `rs_validate` catches every defect planted in
`tests/fixtures/broken-survey`. The worked example in `examples/` is validated by the
suite, so the documentation cannot drift from the schemas.
