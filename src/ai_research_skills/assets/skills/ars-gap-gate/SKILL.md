---
name: ars-gap-gate
disable-model-invocation: true
description: >
  Give a user-invoked, standalone assessment of a research gap or proposed topic. Examine
  whether the question is open, useful, and feasible, using a direct prompt, supplied
  sources, or an optional .research survey workspace. Return evidence, uncertainty, and
  next tests; do not impose a prerequisite or make the researcher's decision for them.
---

# ars-gap-gate — assess a gap, not a workflow

Use this skill when the user asks whether an idea is already covered, worth investigating,
or feasible. The name is retained for command compatibility; this is an advisory assessment,
not a gate that controls another skill.

## Inputs

Accept any of:

- a direct gap or topic description;
- a source list, draft, notes, or corpus supplied in the prompt;
- an optional `.research/survey/<slug>/` workspace named by the user; or
- an explicit request to search for counterexamples or nearby work.

If a workspace, `gaps.yml`, or `coverage.yml` is absent, continue with the available inputs
and say what that limits. Do not require a phase, complete grid, minimum query count, or
freshness field. Existing phase fields are context only.

## Assessment

Answer these questions with citations or file references:

1. **Open?** What is the strongest nearby or directly matching prior work? Distinguish a
   genuinely different claim from a relabelled version.
2. **Useful?** Who would use the result, what assumption or comparison would it change, and
   what evidence supports that importance?
3. **Feasible?** What data, compute, access, baseline, time, or evaluation constraint could
   stop the work? Ask rather than assume personal resources.
4. **What would change the assessment?** State a cheap falsifying search or small experiment.

Search only when the user explicitly asks or supplies permission in the request. Search results
may be kept in the optional workspace when the user asks; otherwise return a direct report.
Never present an empty cell or missing record as proof of absence.

## Evidence states and boundaries

With evidence, distinguish nearby source claims from the assessment; with partial evidence, keep the verdict bounded and state what is unchecked. With zero usable evidence, do not invent citations, numbers, or a deterministic sourced report: report attempts, limits, and the smallest next test. Abstract-only material supports softened high-level wording. Ask only the smallest clarification when ambiguity materially changes the assessment. This skill never invokes another skill or creates or repairs a workspace automatically.

## Output

A useful report can be short:

```markdown
# Gap assessment — <topic>

## Current reading
Open / partly covered / likely covered — <why, with sources>

## Contribution case
<who benefits and what would change>

## Feasibility and risks
<concrete constraints and assumptions>

## Cheapest next test
<the search or small experiment that could change the answer>

## Limits
<what was supplied or searched, dates, and unresolved uncertainty>
```

If the user requests a file, write only that file. A verdict belongs to the researcher; make a
recommendation only when the user explicitly asks for one and label it as advice.

## Integrity habits

Be explicit about uncertainty, do not fabricate citations or numbers, and do not silently
substitute memory for missing evidence. If you use a workspace, snapshot/confirm before any
destructive edit and report the handoff only when requested.
