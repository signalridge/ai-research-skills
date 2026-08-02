# Worked example

`worked-survey/` is a complete survey state directory at the moment `survey` freezes it —
Phase 5, ready for any of the four exits.

> **The papers are synthetic.** Citation keys are deliberately unmistakable
> (`alpha2025iterative`, `beta2025longctx`) so nothing here can be mistaken for a real
> reference. The field-growth figures in `saturation.baseline_growth` *are* real, taken
> from `openalex_analyze_trends` on retrieval-augmented generation.

It doubles as a test fixture: `tests/run_tests.py` asserts it still passes `rs_validate`,
so the documentation cannot drift away from the schemas.

```bash
python3 scripts/rs_validate.py \
  examples/worked-survey/.research/survey/retrieval-augmented-agents
```

In a real project this tree lives at the root of whatever you are surveying, not inside
`examples/`.

## What to look at, and why

**`protocol.yml`** — `axes` are declared before `recall_modes`, which is the order they were
written in. That is the whole point: a taxonomy built after reading describes your sample,
not the field.

Note `counts`: `adjudicated: 244` equals `deduped: 244`. Every candidate was judged. Had it
been 150, the survey would still be valid — but it would have to say so, because an
unadjudicated tail is not an excluded one.

**`corpus.jsonl`** — five records covering every state worth seeing:

| Record | Shows |
|---|---|
| `alpha2025iterative` | A full include: `claim`, sourced `numbers`, `code.runs: verified`, `evidence_read: full` |
| `beta2025longctx` | The *disagreement*. Reports the opposite direction to alpha on an overlapping benchmark. Found only by citation chaining — keyword search never returned it, which is the case for running all three recall modes. |
| `gamma2026threehop` | An include read only to `intro+method`, with an empty `numbers` array. Honest partial depth. |
| `delta2024singlehop` | An exclude, with a reason naming the criterion it failed |
| `epsilon2026workshop` | **`screen: unsure`.** A two-page workshop abstract that might already close the gap and cannot be resolved. Forcing this into include/exclude is how a survey lies about its own coverage. |

**`coverage.yml`** — eight cells in three states. Two are `unexplored` *with*
`trend_evidence` explaining why they are not `abandoned`. Three are `undecided`: empty, and
the discrimination was not done. That is the honest default, and `gap-gate` caps G2 at 3 for
any cell in it.

**`gaps.yml`** — one gap at `confidence: medium`, not `high`, precisely because
`epsilon2026workshop` could not be resolved. The `closes_if` falsifier is decidable from a
title and abstract, which is what makes `watch` able to re-test it automatically.

**`log.md`** — the reproducibility record, including two hazards hit in real use: the arXiv
DataCite DOI that 404s against OpenAlex, and a `2028` bucket dropped from the trend
histogram as a publisher-date artifact.

**`notes/`** — only for full reads. `beta2025longctx.md` records why the alpha/beta
disagreement matters more than either result alone, and warns against smoothing it into
"several works have explored…" when drafting.

## Reading it as a story

The survey found two papers that disagree, and discovered that they disagree *because
neither controls the variable that would settle it*. The gap is not "nobody studied this
area" — it is "the comparison everyone is making is not the comparison that answers the
question." That is what a coverage grid is for, and it is why the axes had to exist before
the search did.
