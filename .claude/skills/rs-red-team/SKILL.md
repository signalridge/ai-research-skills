---
name: rs-red-team
description: >
  Adversarially attack a survey before its conclusions are trusted — terminology coverage,
  recall self-diagnostic, empty-cell interpretation, abstract-only conclusions, and
  cherry-picking. Use when the user asks to challenge, stress-test, poke holes in, or
  sanity-check a survey or its gaps, and run it automatically before any exit is delivered.
  Reads .research/survey/<slug>/ and reports findings; may search only to attempt refutation.
context: fork
background: false
---

# red-team — try to break it

Two checkpoints. Neither is optional before a survey's conclusions leave the session.

| Checkpoint | When | Attacks |
|---|---|---|
| **A** | After `rs-survey` Phase 4, before any exit | The corpus and the coverage map |
| **B** | Before an exit is delivered | The specific claims that exit makes |

Findings are `critical` (blocks) or `advisory` (noted). Revision loops are **capped at 2** —
what remains after that becomes an explicit "Acknowledged limitations" section rather than
looping forever.

Unlike the other exits, this skill **may search** — but only to attempt refutation, never
to extend the corpus. Anything it finds that should be in the corpus goes back to `rs-survey`.

---

## Checkpoint A — attack the corpus

### A1. Terminology drift

Name **three plausible alternative phrasings** for the core concept, without looking at the
protocol. Then check whether they were searched.

Terminology in CS/ML drifts faster than it standardizes: *content moderation* = *safety
filtering* = *NSFW detection*; *chain-of-thought* = *scratchpad* = *intermediate
reasoning*; *retrieval-augmented* = *memory-augmented* = *tool-augmented*.

Run any unsearched phrasing now. **New on-topic results are a critical finding** — the
corpus has a terminology-shaped hole and every gap downstream is suspect.

### A2. Recall self-diagnostic

Read `coverage.yml.recall_diagnostic`.

| Finding | Severity |
|---|---|
| `citation_chain` contributed ~0 includes | **critical** — search was keyword-shaped; the mode that finds papers under names you did not guess never ran |
| `keyword` contributed ~0 | advisory — query terms do not match the field's language |
| One mode contributed >80% | advisory — recall rests on a single point of failure |

### A3. Coverage honesty

Compare `counts.adjudicated` against `counts.deduped`. An unadjudicated tail presented as
an excluded one is **critical** — it inflates apparent coverage, which is the one number
every downstream reader trusts.

### A4. Empty-cell interpretation

For every cell marked `unexplored`, demand the receipts:

- Was a targeted search run for that exact axis combination? (≥3 phrasings)
- Is there `trend_evidence` distinguishing unexplored from abandoned?
- Is `nearest_prior_work` non-empty?

**A gap with no nearest prior work is critical.** Real gaps sit next to something. An
empty `nearest_prior_work` almost always means the search was too narrow, not that the
field is wide open.

Then argue the opposite case explicitly: *make the strongest argument that this cell is
abandoned rather than unexplored.* If that argument is good, the label is wrong.

### A5. Abstract-only conclusions

Any coverage cell whose only occupants are `evidence_read: abstract` cannot support a
claim about what those papers showed. An abstract states what the authors wanted to claim.

Flag every cell in that state. If gaps depend on them, **critical**.

---

## Checkpoint B — attack the exit

### For `rs-gap-gate`

Build the **strongest possible case that the gap is already closed.** Search specifically
for it. Check preprints from the last 90 days — a gap surviving 12 months of literature can
close in a fortnight.

Then attack G2 directly: *who cites this if I do it?* If neither the dossier nor the corpus
names two plausible groups, G2 is inflated.

### For `rs-related-work`

- **Cherry-picking.** Does any corpus record contradict a claim in the draft? Uncited
  disagreement is **critical**. Two papers disagreeing is the most interesting sentence you
  can write — omitting it is the least honest.
- **Over-characterisation.** Cross-check every characterising sentence against its record's
  `evidence_read`. "X demonstrates that…" from an `abstract` record is critical. Then the
  two corroboration-anchored rules: "demonstrates/establishes" without two
  `agrees_with`-linked records behind it is critical, and prose stronger than the record's
  own `claim` sentence — a dropped qualifier counts as stronger — is an upgrade, not a
  summary.
- **Absence hedging.** Does phrasing strength match `gaps.yml` confidence? An unhedged
  "no prior work" from a `low`-confidence gap is critical.

### For `rs-decision-brief`

- **Weakest link.** Which claim has the thinnest support that the design still depends on?
  Is it flagged as such in the brief?
- **Reproducibility inversion.** Is any row leaning on venue prestige where `code.runs` is
  `unverified`?
- **The failure you are least prepared for.** Name the concrete scenario the brief does not
  cover.

---

## Verdict semantics — three buckets, no hardening

At either checkpoint, take the load-bearing claims (the ones the exit would collapse
without) and put each through one question: **what observation would force me to abandon
this claim?** That is its refutation-condition, and it must be written down.

Each claim lands in exactly one bucket:

| Bucket | Meaning | Action |
|---|---|---|
| **BROKEN** | The refutation-condition was tested and it fired | Fix the state or the claim; this is a `critical` finding |
| **CORROBORATED** | The condition was tested and the claim survived | Say what you tested — survival without a named test is not corroboration |
| **UNFALSIFIABLE** | No refutation-condition could be stated at all | **The worst outcome.** Demote the claim to conjecture in the exit, or strike it |

A claim you cannot imagine being wrong about is not a strong claim — it is one you have
stopped examining. Unfalsifiable is scored below broken, because broken at least tells you
where you stand.

And: **no hardening.** Findings lead to revise, demote, or acknowledge — never to a
stronger defense of the claim as written, and there is no resilience score. A survey that
survives red-teaming is not "robust"; it is "these specific attacks failed", which is a
list, not a grade.

---

## Output

Write `.research/survey/<slug>/challenge-<date>.md`:

```markdown
# Red-team — <slug> — checkpoint A — <date>

## Critical (blocks)
1. **[A2] Citation chaining contributed 2 of 61 includes.** The forward chains in
   protocol.recall_modes ran against a seed that 404s (arXiv DOI). Recall rests entirely
   on keyword search. → Re-run Phase 1 Mode B with resolved seed ids.

## Advisory
2. **[A5] Cell (iterative, fixed-recall, 3-hop) has two occupants, both abstract-only.**
   Any claim about what they showed is unsupported. → Read them or mark the cell undecided.

## Refutation attempts that failed
- Searched "memory-augmented multi-hop" and "tool-augmented QA": 0 new on-topic. The
  terminology coverage holds.

## Claim buckets
- "Iterative retrieval beats long-context at equal recall" — refutation-condition: a
  controlled benchmark with recall held constant shows parity or worse. Tested against
  sample2025iterative + sample2025longcontext → **CORROBORATED**.
- "The field has no fixed-recall baseline" — refutation-condition: any published
  fixed-recall baseline. Searched 3 phrasings, none found → **CORROBORATED** (weakly —
  contrarian pass covered English venues only).
- "Hybrid methods dominate by 2027" — no testable condition stated in the draft →
  **UNFALSIFIABLE**. Demoted to conjecture; removed from the exit's claims.

## Verdict: BLOCKED on 1 critical finding
```

**Record the refutation attempts that failed.** An attack that found nothing is evidence,
and it is the part a reader can use to calibrate how much to trust the rest.

## Posture

Be adversarial. The default failure mode is a survey that looks thorough because it is
well-formatted. Your job is to find the hole, not to bless the work.

But be specific: every finding names the artifact, the field, and the fix. "This could be
more rigorous" is not a finding.

## Handoffs

- **Upstream:** reads all of `.research/survey/<slug>/` — checkpoint A attacks what
  `rs-survey` Phase 4 produced.
- **Writes:** `challenge-<date>.md`.
- **Downstream:** gates every exit — checkpoint B must pass before `rs-gap-gate`,
  `rs-related-work` or `rs-decision-brief` output is delivered.
- `rs-verify` covers citation and number integrity, which this skill does not duplicate.
