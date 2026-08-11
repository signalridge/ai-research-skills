# Worked example

`worked-survey/` is a complete survey state directory at the moment `ars-survey` freezes it —
Phase 5, ready for any of the four exits.

> **The papers and trend baseline are synthetic.** Citation keys are deliberately
> unmistakable (`alpha2025iterative`, `beta2025longctx`) so nothing here can be mistaken for
> a real reference. `saturation.baseline_growth` is an illustrative stable snapshot, not a
> live OpenAlex measurement.

It doubles as a test fixture: `tests/run_tests.py` asserts it still passes `rs_validate`,
so the documentation cannot drift away from the schemas.

```bash
python3 src/ai_research_skills/assets/scripts/rs_validate.py \
  examples/worked-survey/.research/survey/retrieval-augmented-agents
```

In a real project this tree lives at the root of whatever you are surveying, not inside
`examples/`.

## What to look at, and why

**`protocol.yml`** — `axes` are declared before `recall_modes`, which is the order they were
written in. That is the whole point: a taxonomy built after reading describes your sample,
not the field.

Note `counts`: `adjudicated: 4` of `deduped: 5`; the fifth candidate is `screen: unsure`.
The fixture deliberately shows that an unadjudicated tail is not an excluded one.

**`corpus.jsonl`** — five records covering every state worth seeing:

| Record | Shows |
|---|---|
| `alpha2025iterative` | A full include: `claim`, sourced `numbers`, `code.runs: verified`, `evidence_read: full` |
| `beta2025longctx` | The *disagreement*. Reports the opposite direction to alpha on an overlapping benchmark. `found_via` is `contrarian:opposing-camp` **only** — keyword search used the field's own vocabulary and the citation chains never reached it, because the papers it contradicts do not cite it. This one record is the case for Mode D, and for all four modes being mandatory. |
| `gamma2026threehop` | An include read only to `intro+method`, with an empty `numbers` array. Honest partial depth. |
| `delta2024singlehop` | An exclude, with a reason naming the criterion it failed |
| `epsilon2026workshop` | **`screen: unsure`.** A two-page workshop abstract that might already close the gap and cannot be resolved. Forcing this into include/exclude is how a survey lies about its own coverage. |

**`coverage.yml`** — twelve cells in four states: three `occupied`, two `unexplored`, one
`avoided`, and six `undecided` in the complete 2×3×2 grid.

The two `unexplored` cells carry `trend_evidence` explaining why they are not `abandoned` —
the illustrative protocol treats neighbouring activity as live, so these controls are simply
untried.

The `avoided` cell is the one to study. In this synthetic fixture, the protocol says deeper
long-context evaluation is repeatedly named as future work without an attempted record. The
field is represented as routing around it, not proving it solved or failed; `abandoned` would
score 1 at G2 while `avoided` scores 5.

The two `undecided` cells are empty with the discrimination not done. That is the honest
default, and `ars-gap-gate` caps G2 at 3 for any cell in it.

**`gaps.yml`** — two gaps, both at `confidence: medium` rather than `high`. G1 is the
missing controlled comparison, held at medium precisely because `epsilon2026workshop` could
not be resolved and might already close it. G2 was promoted from the `avoided` cell, and its
contribution evidence *is* the future-work mentions — each is a group that would cite the
result. Both `closes_if` falsifiers are decidable from a title and abstract, which is what
makes `ars-watch` able to re-test them automatically.

**`log.md`** — the reproducibility record for the synthetic run. It preserves the arXiv
DataCite DOI hazard and a future-year bucket example as teaching notes; neither is a live
measurement from this fixture.

**`notes/`** — only for full reads. `beta2025longctx.md` records why the alpha/beta
disagreement matters more than either result alone, and warns against smoothing it into
"several works have explored…" when drafting.

## Reading it as a story

The survey found two papers that disagree, and discovered that they disagree *because
neither controls the variable that would settle it*. The gap is not "nobody studied this
area" — it is "the comparison everyone is making is not the comparison that answers the
question." That is what a coverage grid is for, and it is why the axes had to exist before
the search did.
