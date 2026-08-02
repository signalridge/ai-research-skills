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

## The three gates

Scored 1–5 each. Composite is a **3-gate AND** — any gate at 1–2 makes the candidate
`no-go`, regardless of how strong the others are.

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

The hardest gate, and the one people skip. An empty cell has two explanations: nobody tried,
or everybody tried and it did not matter.

Reads `coverage.yml` — the cell's `state` and `trend_evidence`.

| Score | Evidence |
|---|---|
| 5 | Cell is `unexplored`; neighbouring cells are high-volume and still growing; the gap sits on the path of active work |
| 3 | Cell is `unexplored` but neighbours are thin, or the trend is flat |
| 1 | Cell is `abandoned` — neighbours peaked years ago. Or the gap is real and nobody cares. |

A cell marked `undecided` in `coverage.yml` **caps G2 at 3**. You cannot score contribution
on a cell whose emptiness was never explained.

Ask the question that actually decides it: *if I closed this, who cites it?* If you cannot
name two groups from the corpus, that is a 2.

### G3 — Can you close it?

The only gate that depends on the researcher, so ask rather than infer.

| Dimension | What to check |
|---|---|
| Compute | What did the nearest prior work use? `numbers[]` and method sections usually say. Compare with what the user has. |
| Data | Are the datasets public? Gated? Does the baseline need something under licence? |
| Baselines | `code.status` and `code.runs` on the papers you would have to reproduce. Three baselines with `status: none` is a year of work before you start. |
| Time | Does it fit the horizon the user actually has? |

| Score | Evidence |
|---|---|
| 5 | Public data, official runnable code for every baseline, compute within reach |
| 3 | One significant obstacle with a known workaround |
| 1 | A baseline cannot be reproduced, data is inaccessible, or compute is out of range |

If the user has not told you their compute, data access, or horizon, **ask**. Do not assume
a lab GPU cluster and do not assume a laptop.

---

## Output

Write `.research/survey/<slug>/topic_dossier.md` and the `verdict` block back into
`gaps.yml`.

```markdown
# Topic dossier — <topic>
Survey: <slug> · gaps last checked <date> · dossier generated <date>

## Decision summary

| Candidate | G1 open | G2 contribution | G3 feasible | Composite |
|---|---|---|---|---|
| G1 Matched-recall comparison | 4 | 5 | 3 | **conditional** |
| G2 3-hop iterative retrieval | 2 | 4 | 4 | **no-go** (G1) |

Key uncertainty: <one line — the thing most likely to be wrong>

## Per candidate
### G1 — <plain-language name>
**Statement.** <from gaps.yml>
**Gate 1 — open?** Score 4. <evidence> · Risk: <…> · To raise: <action>
**Gate 2 — contribution?** Score 5. <trend evidence>
**Gate 3 — feasible?** Score 3. <obstacle> · To raise: <action>
**Closes if:** <falsifier>
**Kill test:** <the cheapest experiment that would tell you this is wrong>

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
