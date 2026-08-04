---
name: gap-gate
description: >
  Turn a surveyed research gap into a go/no-go decision dossier — three gates (is the gap
  open? would closing it be a contribution? is it feasible for you?) with the evidence laid
  out, and the final worth-it call deliberately handed back to the researcher. Use when the
  user asks "is this gap worth pursuing", "should I commit to this topic", "is this idea
  already taken", "help me pick a thesis topic", "vet this before I start", "这个方向值不
  值得做". Requires a completed survey; reads .research/survey/<slug>/ and never searches
  on its own.
disallowed-tools:
  # This exit is a pure function of survey state. The "never search here" rule in the
  # body is advisory; this makes it structural. A missing paper goes back to `survey`.
  # Server names follow SETUP.md; a differently-named server silently escapes the
  # restriction, so the prose rule stays as the backstop.
  - WebSearch
  - WebFetch
  - mcp__tavily
  - mcp__arxiv-mcp-server
  - mcp__openalex
---

# gap-gate — evidence for a decision you make

Choosing what to work on is not a literature review. It is a decision under uncertainty:
*given everything already known, what should I do next, and why is it defensible?*

This skill assembles the evidence for that decision across three gates and **stops short of
the verdict**. A go/no-go on months of your time is not a call to delegate.

## Preconditions

```bash
ls .research/survey/<slug>/gaps.yml .research/survey/<slug>/coverage.yml
```

If either is missing, or `protocol.yml` has `phase < 4`, stop and run `survey` first.
**Never search to fill a hole here** — a gap assessed against a corpus that was never
screened is worse than no assessment.

Check `evidence_of_absence.last_checked` on every gap. Older than 30 days in a fast-moving
field means G1 is being scored against stale evidence; say so, and offer `watch` first.

---

## Gate 0 — disqualifiers, before any scoring

Run this first. It is cheap, it reads state you already have, and it exists to stop you
producing a careful three-gate assessment of something that was dead on arrival.

| Disqualifier | Read from | Why it ends the assessment |
|---|---|---|
| A corpus record closes the gap — `nearest_prior_work.differing_axis: none`, or a `closes_if` already satisfied | `gaps.yml` | The gap is not open. Nothing downstream can change that. |
| The cell is `undecided` in `coverage.yml` | `coverage.yml` | Its emptiness was never explained. You would be scoring contribution on an unexamined hole. |
| `recall_diagnostic` shows the contrarian or citation-chain mode contributed nothing | `coverage.yml` | The evidence of absence rests on a search that structurally could not have found the counterexample. |
| Every baseline you would have to reproduce has `code.status: none` | `corpus.jsonl` | This is a year of reimplementation before the actual contribution starts. |
| `evidence_of_absence.last_checked` is older than the field's doubling time | `gaps.yml` + `saturation.baseline_growth` | G1 would be scored against evidence that has expired. |

If any fires: **emit the verdict and stop.** Report Gate 0, the specific disqualifier, and
the concrete action that would clear it. Do not score G1, G2 or G3.

Scoring a disqualified candidate is not thoroughness — it is decoration on a rejection, and
worse, it manufactures a document that *looks* like a considered assessment. A reader
skimming three scores will not notice that the whole thing was moot.

The first three disqualifiers are all repairable. Say which action clears each: re-run
`survey` Phase 4 Step B to discriminate the cell, re-run Phase 1 Mode D, run `/rs:watch
check` to re-date the evidence.

---

## The three gates

Reached only if Gate 0 is clear. Scored 1–5 each. Composite is a **3-gate AND** — any gate
at 1–2 makes the candidate `no-go`, regardless of how strong the others are.

### G1 — Is the gap actually open?

Reads `gaps.yml.evidence_of_absence`.

| Score | Evidence |
|---|---|
| 5 | ≥3 distinct phrasings, ≥3 venue-years, forward chains from nearest prior work, `nearest_prior_work` named with a precise reason it does not close the gap, checked within 30 days |
| 3 | Searched adequately but the sweep is partial or `last_checked` is stale |
| 1 | Prior work exists that closes it, or evidence of absence is thin enough that the gap may be an artifact of poor recall |

Check the survey's `recall_diagnostic` before scoring this. If `citation_chain` contributed
near-zero includes, **G1 cannot exceed 3** — the absence evidence rests on a keyword-shaped
search, and the thing that would have found the counterexample was never run.

### G2 — Would closing it be a contribution?

The hardest gate, and the one people skip. Reads `coverage.yml` — the cell's `state` and
`trend_evidence`.

| Cell state | Score | Reading |
|---|---|---|
| `avoided` | 5 | The field names this as an open problem repeatedly and nobody attempts it. Every paper that listed it as future work is a citer waiting for the result. |
| `unexplored`, live neighbourhood | 5 | Neighbouring cells are high-volume and still growing; the gap sits on the path of active work |
| `unexplored`, thin neighbourhood | 3 | Nobody tried, but nobody is nearby either |
| `undecided` | **cap at 3** | Emptiness was never explained. You cannot score contribution on an unexamined hole. |
| `abandoned` | 1 | People tried and it did not hold up. Read the failure before considering repeating it. |

**`avoided` and `abandoned` both mean "the work stopped", and they score at opposite ends.**
An old, large, acknowledged problem that everyone routes around is not evidence that nobody
cares — usually the opposite. If `coverage.yml` does not distinguish them, send it back to
`survey` Phase 4 Step C rather than guessing; guessing here is how the best gap in the grid
gets scored 1 and discarded.

Then the question that actually decides it: *if I closed this, who cites it?* Name two
groups from the corpus or score 2. For an `avoided` cell this is easy and the answer is
already in `trend_evidence` — that is what makes the state worth so much.

#### Shape probe — calibration, not a gate

Four questions about what *kind* of contribution this is. **No score attaches.** Incremental
work is the backbone of a research career and reaches top venues routinely; the probe exists
so the framing matches the reality rather than to filter.

1. **Hidden assumption.** Does closing this gap require the field to give up something it
   currently takes for granted? A specific assumption, nameable in one sentence — not "we
   use a better method."
2. **Known and avoided.** Has the field been describing this problem for years without
   attacking it? (If `coverage.yml` says `avoided`, this is already a yes and the evidence
   is recorded.)
3. **Newly possible.** Did some capability that did not exist two years ago make this
   answerable now? A gap that was intractable and quietly became tractable is the highest
   reward-to-risk shape available.
4. **So what.** If this resolved itself overnight, would anything downstream actually
   change? If nothing does, the gap may be real and still not worth closing.

Two or more yes answers means the gap is structural rather than incremental. Say so in the
dossier and frame it that way. Zero or one is fine — say *that*, and frame it as the solid
incremental contribution it is. **The failure this catches is framing drift in both
directions**: dressing an incremental gap as a paradigm shift invites a reviewer to
puncture it, and burying a structural gap in incremental language wastes it.

### G3 — Can you close it?

The only gate that depends on the researcher, so ask rather than infer.

| Dimension | What to check |
|---|---|
| Compute | What did the nearest prior work use? `numbers[]` and method sections usually say. Compare with what the user has. |
| Data | Are the datasets public? Gated? Does the baseline need something under licence? |
| Baselines | `code.status` and `code.runs` on the papers you would have to reproduce. |
| Time | Does the gap's shelf life exceed the user's realistic execution window? See below. |

#### Shelf life versus execution window

The gate people get wrong. A gap can be open, worth closing, technically within reach —
and still a no-go, because it will close before you finish.

Every gap has a shelf life. In a field publishing 3× more each year, a gap of the "apply a
known technique to a new setting" shape has months, not years, because it is visible to
everyone who reads the same papers. A gap requiring new theory has longer, because fewer
people can attempt it.

Estimate both sides and compare:

| Gap shape | Rough shelf life | Needs |
|---|---|---|
| Apply an existing method to a new setting | 3–6 months | Fast execution; the bottleneck is engineering throughput |
| Controlled comparison nobody has run | 6–9 months | Careful experimental design; the contribution *is* the rigour |
| New method for a known problem | 6–12 months | Depth in the method family |
| Missing benchmark or evaluation | 6–12 months | Data access and sustained curation effort |
| New theory or a reframing | 12+ months | Sustained deep work; short-shelf-life competition matters less |

Then ask for the other side plainly: **effective hours per week, not calendar time.** Ten
focused hours a week against a six-month shelf life is roughly 260 hours of work against a
deadline set by strangers. Say so if that is the situation.

**Mismatch is a G3 failure even when everything else is green.** A short-shelf-life gap
handed to a part-time execution window is how people spend a year producing something that
gets scooped at month eight. That is a worse outcome than a no-go, because the no-go costs
a day.

| Score | Evidence |
|---|---|
| 5 | Public data, official runnable code for every baseline, compute within reach, execution window comfortably inside the shelf life |
| 3 | One significant obstacle with a known workaround, or the window is tight but feasible |
| 1 | A baseline cannot be reproduced, data is inaccessible, compute is out of range, or the execution window exceeds the shelf life |

If the user has not told you their compute, data access, or **weekly hours**, ask. Do not
assume a lab GPU cluster, do not assume a laptop, and do not assume full-time.

---

## Output

Write `.research/survey/<slug>/topic_dossier.md` and the `verdict` block back into
`gaps.yml`.

```markdown
# Topic dossier — <topic>
Survey: <slug> · gaps last checked <date> · dossier generated <date>

## Decision summary

| Candidate | Gate 0 | G1 open | G2 contribution | G3 feasible | Composite |
|---|---|---|---|---|---|
| G1 Matched-recall comparison | clear | 4 | 5 | 3 | **conditional** |
| G2 3-hop iterative retrieval | clear | 2 | 4 | 4 | **no-go** (G1) |
| G3 Cross-domain transfer | **disqualified** | — | — | — | **no-go** (cell undecided) |

Key uncertainty: <one line — the thing most likely to be wrong>

## Per candidate
### G1 — <plain-language name>
**Statement.** <from gaps.yml>
**Gate 0.** Clear.
**Gate 1 — open?** Score 4. <evidence> · Risk: <…> · To raise: <action>
**Gate 2 — contribution?** Score 5. <trend evidence>
**Gate 3 — feasible?** Score 3. <obstacle> · To raise: <action>
**Closes if:** <falsifier>
**Shelf life vs window:** <estimate> vs <user's stated hours/week>
**Kill test:** <the cheapest experiment that would tell you this is wrong>

### G3 — <plain-language name>
**Gate 0. DISQUALIFIED** — coverage.yml marks this cell `undecided`; its emptiness was
never discriminated. Not scored. To clear: run `survey` Phase 4 Step B on this cell.

## What this dossier does not tell you
<...>

## Appendix — search protocol
<verbatim from protocol.yml: queries, venues, dates, counts, coverage>
```

### Two sections that carry the weight

**Kill test.** For each `conditional` candidate: the cheapest thing that would reveal the
idea is wrong. A week-long experiment that kills a bad topic is the best trade in research.

**Appendix.** The verbatim protocol. It is what lets an advisor check the reasoning rather
than trust it — and what lets you re-run the assessment in three months.

---

## Withhold the verdict

State the composite. Do **not** write "you should do this" or "I recommend G1."

The composite is a summary of assembled evidence. Whether it is worth *your* months
depends on your funding, your advisor, your job market, what you actually enjoy — none of
which is in the corpus. Say that plainly and hand it back.

Close with the honest limits: which gates rest on `undecided` cells, which on stale
evidence, what the survey did not cover.

## Related

`survey` builds the corpus · `watch` re-tests `closes_if` so G1 stays current ·
`red-team` should run before this dossier is trusted
