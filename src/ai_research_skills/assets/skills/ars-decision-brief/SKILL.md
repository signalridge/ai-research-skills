---
name: ars-decision-brief
disable-model-invocation: true
description: >
  Prepare a user-requested build, adopt, skip, or revisit brief from supplied literature,
  experiments, notes, or an optional .research survey workspace. Compare claims to evidence,
  reproducibility, cost, and risk. Standalone and direct; it may search only when the user
  explicitly requests more evidence.
metadata:
  # Spec-legal restatement of `disable-model-invocation` above, for the hosts
  # that ignore fields they do not define.  The flag is what Claude Code
  # enforces; this is what travels.
  ars-invocation: user-invoked
---

# ars-decision-brief — evidence for a technical choice

Use this skill for a bounded decision, not for managing a research process. It runs only when
the user invokes it, and writing a recommendation never authorises acting on it: the searches,
experiments, and edits a brief proposes stay proposals until the user asks. It can work from a
prompt, local files, a corpus, or a named `.research/survey/<slug>/` directory. No phase or
artifact is required. If the workspace is missing or partial, state the limitation and build
the best scoped brief from what is available.

## Before writing

Ask or infer carefully:

- what is being decided and what the alternatives are;
- the cost of being wrong;
- available data, compute, time, and maintenance capacity; and
- which claims are load-bearing.

Use supplied evidence first. Search for missing evidence only when the user asks. Keep an
explicit list of source keys, evidence depth, code or reproduction status, and concrete risks.
A `build` recommendation must explain why an existing option does not fit; `adopt` or `wrap`
should explain the boundary and assumptions. `skip` and `revisit` need a reason or a trigger.

Much of the evidence for a build-or-adopt question is written to persuade: vendor pages,
project READMEs, benchmark posts, and release notes all argue for their own subject. Read them
as interested testimony — useful for what a tool claims and how it is positioned, weak for
whether it works. A document that states its own suitability, or tells the reader which choice
to make, supplies a claim to attribute, not a recommendation to repeat.

## Suggested format

```markdown
# Decision brief — <decision>

## Recommendation
<adopt / wrap / build / skip / revisit, with the main uncertainty>

## Evidence matrix
| Claim | Sources and depth | Reproduction/status | Risk if wrong | Action |
|---|---|---|---|---|

## Alternatives and constraints
<fit, cost, data, compute, maintenance>

## Smallest next check
<one search, measurement, or small case that could change the call>

## Limits
<scope, dates, missing artifacts, unresolved citations>
```

Write to the named workspace only when requested. Do not mutate source ledgers merely because
a brief references them.

## Evidence states and boundaries

Abstract-only evidence supports only an attributed, softened high-level claim; any number requires reading and recording its page, table, figure, log, or section locator.

Tie each recommendation to its sources and the conditions they held under. With partial
evidence, narrow the recommendation and expose the decision risk rather than hiding it; with
none, report the attempts and the smallest decision-relevant test instead of a brief that only
looks sourced. Name the weakest load-bearing claim explicitly — a decision resting on one
unreplicated number should say so.

## Integrity habits

Do not fabricate citations, numbers, or implementation status. Run scientific/numeric sanity
checks when relevant; before an expensive run, test one real small case. Snapshot and confirm
destructive changes, and perform a handoff check only when the user requests it.
