# Credits and provenance

This plugin was designed after surveying existing research-skill suites. Some of what is
here is an idea taken from one of them and re-expressed for this architecture; some is a
deliberate departure. This file records which is which, and under what terms.

## Licensing position

**No text from any source below was copied into this repository.** Every idea adopted was
re-expressed from scratch against this plugin's own state model, terminology and phase
structure. That is a deliberate choice, not an accident of drafting, and it matters most
for one source:

> **methodology-reference-02 is CC BY-NC-SA 4.0** — NonCommercial and ShareAlike. Both
> clauses are incompatible with this repository's MIT licence: MIT permits commercial use,
> and ShareAlike would force derivative works onto CC BY-NC-SA. Copying its prose into an
> MIT repo would be a licence violation, and it would also silently relicense anything
> downstream that depends on this plugin.
>
> Individual skills in that repo carry per-file `license: CC-BY-4.0` frontmatter that
> conflicts with the repo-level LICENSE. Where terms conflict, this project assumes the
> more restrictive one and copies nothing.

Facts and methods are not copyrightable; particular expression is. Adopting "run a cheap
disqualifier check before the expensive scoring" is fine. Reproducing the paragraph that
explains it is not.

| Source | Licence | What was taken |
|---|---|---|
| [methodology-reference-02](methodology-reference-02) | CC BY-NC-SA 4.0 (repo); some skills CC-BY-4.0 | Ideas only, re-expressed — see below |
| [methodology-reference-03](methodology-reference-03) · [methodology reference 04](methodology-reference-04) | MIT | The 3-gate go/no-go structure and withheld verdict |
| [methodology-reference-01](methodology-reference-01) | MIT | Hooks-as-enforcement; per-stage reference files; every rule traces to a real failure |
| [catalog-reference-02](catalog-reference-02) | CC BY-NC (repo LICENSE; GitHub reports NOASSERTION) | Typed inter-stage handoffs; bounded revision loops |
| [catalog-reference-01](catalog-reference-01) | MIT | The habit of documenting how an API fails *quietly* |

---

## What came from where

### methodology reference 02 (HKUST DIAL, Yuyu Luo)

A handbook plus skills distilling a decade of supervision at SIGMOD/VLDB/ICML/NeurIPS. It
is strong exactly where this plugin was thin: **judgment criteria**, as opposed to process.
Five ideas were adopted and rewritten:

- **Disqualifier check before scoring** → `gap-gate` Gate 0. Their `idea-evaluator` runs a
  fatal-flaws audit ahead of its five-dimension scoring and short-circuits on a critical
  finding, on the grounds that scoring a dead idea is decoration on a rejection. The
  disqualifiers here are different — they read *this* plugin's survey state — but the
  ordering and the short-circuit are theirs.
- **Retrieval bounds what you may conclude** → Phase 2. Search results support
  metadata-level judgements (who, where, when); they are not a source for numbers or method
  detail. And "not found" is reported as *nothing retrieved under these keywords*, never as
  *nothing exists*.
- **Duplication needs a named differing axis** → `gaps.yml.nearest_prior_work.differing_axis`.
  A similar title never establishes that a gap is taken; failing to find even one differing
  axis establishes that it is.
- **Idea lifecycle versus capability** → `gap-gate` G3. Their handbook §2.1 tabulates idea
  types against lifecycles and student profiles, and asks about effective hours per week
  rather than calendar time. G3's shelf-life-versus-execution-window check is that idea
  applied to gaps.
- **The elephant in the room** → the `avoided` coverage state and a corrected G2 rubric.
  Their paradigm-shift probe asks whether an idea addresses a problem the community sees but
  avoids. This plugin had no way to express that: `avoided` and `abandoned` both collapsed
  to `abandoned`, which G2 scored 1 — so the gate would have systematically discarded the
  best gaps. The four probe questions were also kept as a **calibration** step in G2 rather
  than a scored gate, which follows their own guidance that the probe is not a gate.

Their `deep-research` skill also motivated **Mode D (contrarian)** in Phase 1: it searches
from adversarial perspectives — the critics, the methodology sceptics — where this plugin
had only mechanical modes. That turned out to close a real hole; see the note below.

Recommended reading in its own right, especially the handbook. It is a different kind of
artifact from this plugin and the two compose well.

### methodology reference 04 / ai-research-skills (Wenyu Chiou)

`gap-to-topic` is the origin of `gap-gate`: three gates AND-composed, and the verdict
deliberately withheld so the worth-it call stays with the researcher. Also the practice of
writing machine-readable state (`.research/`) so a later session need not re-derive
everything.

### methodology reference 01 (Fatih Cagatay Akyon)

The central lesson: prompts are advisory, hooks are enforcement. Also progressive
disclosure via per-stage reference files, and the discipline that every rule should trace
to a specific failure rather than to good intentions.

### research skills catalog (Cheng-I Wu)

`shared/handoff_schemas.md` — typed contracts between stages, with required fields and an
explicit incomplete-handoff path — is the ancestor of `schemas/`. Also revision loops capped
at two, with the remainder becoming acknowledged limitations rather than another lap.

### scientific-agent-skills (scientific skills catalog)

`paper-lookup` documents the ways scholarly APIs fail with HTTP 200 — a well-formed
response that is silently wrong. `SETUP.md`'s verified-failure-modes section exists because
of that example.

---

## Research cited in the design

Findings, not text. Full rationale in [DESIGN.md](DESIGN.md).

| Work | Used for |
|---|---|
| retrieval-summary benchmark / FutureHouse ([benchmark reference 01](benchmark-reference-01), Apache-2.0) | Re-ranking and contextual summarisation: score each candidate against the question and summarise in its context, rather than judging include/exclude directly |
| literature benchmark ([arXiv:2407.10362](https://arxiv.org/abs/2407.10362)) | Reporting accuracy, precision and coverage separately; the 0.06–0.35 vs 0.70 human gap on literature extraction without retrieval |
| literature benchmark v2 ([arXiv:2604.09554](https://arxiv.org/abs/2604.09554)) | Open-response over multiple-choice; the `retrieve` figure/table variants motivating `numbers[].source` |
| The experiment-generation benchmark ([arXiv:2504.08066](https://arxiv.org/abs/2504.08066)) | Its VLM figure-review loop; and its own reported success rates, which are why this plugin does **not** implement agentic tree search |
| document parser 01 ([arXiv:2501.17887](https://arxiv.org/abs/2501.17887)) | Table-versus-equation parsing trade-offs behind "never parse a PDF when LaTeX exists" |

---

## One thing worth stating plainly

Mode D exists because integrating methodology reference 02' adversarial search perspectives exposed
an inconsistency in what had already been built here: `red-team` checkpoint B asks whether
any corpus record contradicts a claim in the draft — but it can only find contradictions
**already in the corpus**. With three consensus-biased recall modes and no contrarian pass,
that check passed vacuously, and the survey would report a consensus manufactured by its own
search strategy.

The idea came from elsewhere. The bug it revealed was ours.

The same thing happened twice. The `avoided` state exists because their "elephant in the
room" probe had no expressible counterpart here — and working out why exposed that G2 would
have scored an acknowledged, routed-around problem identically to a dead end. Borrowed
vocabulary is useful mostly for the things it makes you notice you cannot say.
