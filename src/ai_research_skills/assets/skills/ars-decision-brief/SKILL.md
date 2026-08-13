---
name: ars-decision-brief
disable-model-invocation: true
description: >
  Prepare a user-requested build, adopt, skip, or revisit brief from supplied literature,
  experiments, notes, or an optional .research survey workspace. Compare claims to evidence,
  reproducibility, cost, and risk. Standalone and direct; it may search only when the user
  explicitly requests more evidence.
---

# ars-decision-brief — evidence for a technical choice

Use this skill for a bounded decision, not for managing a research process. It can work from a
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

With usable evidence, tie each recommendation to its sources and conditions; with partial evidence, narrow the recommendation and expose the decision risk. With zero usable evidence, do not invent citations, numbers, or a deterministic sourced brief: report attempts, limits, and the smallest decision-relevant test. Abstract-only material supports softened claims only. Ask only the smallest clarification when ambiguity materially changes the choice. This skill never invokes another skill or creates or repairs a workspace automatically.

## Integrity habits

Do not fabricate citations, numbers, or implementation status. Run scientific/numeric sanity
checks when relevant; before an expensive run, test one real small case. Snapshot and confirm
destructive changes, and perform a handoff check only when the user requests it.
