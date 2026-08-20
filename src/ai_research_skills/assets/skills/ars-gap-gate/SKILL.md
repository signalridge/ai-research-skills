---
name: ars-gap-gate
disable-model-invocation: true
description: >
  Give a user-invoked, standalone assessment of a research gap or proposed topic. Examine
  whether the question is open, useful, and feasible, using a direct prompt, supplied
  sources, or an optional .research survey workspace. Return evidence, uncertainty, and
  next tests; do not impose a prerequisite or make the researcher's decision for them.
metadata:
  # Spec-legal restatement of `disable-model-invocation` above, for the hosts
  # that ignore fields they do not define.  The flag is what Claude Code
  # enforces; this is what travels.
  ars-invocation: user-invoked
---

# ars-gap-gate — assess a gap, not a workflow

Use this skill when the user asks whether an idea is already covered, worth investigating,
or feasible. The name is retained for command compatibility; this is an advisory assessment,
not a gate that controls another skill. It runs only when the user invokes it, and a verdict
of "open" is an answer, not a trigger — do not follow it with a survey or a draft.

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

A retrieved source is evidence about the field, not a ruling on the question. This assessment's
whole output is a verdict, which makes the verdict the thing a source is most likely to assert:
a page announcing that a problem is solved, wide open, or already claimed is a claim to weigh
against the rest of the evidence like any other, and one to attribute rather than adopt.

### Naming the nearest prior work

The difference between a real gap and an unsearched one is usually visible in a single move:
name the closest existing work and say precisely why it is not the answer, and on which axis it
differs. "Nothing covers this" is weak; "the closest work is X, which controls token budget
rather than retrieval recall — a different problem setting" is checkable, and a reader who
disagrees knows exactly where to look. Two or three of these are usually enough. A workspace
records them as `nearest_prior_work` entries with `why_not_it` and `differing_axis`.

If no nearest work can be named at all, that is more often a search limit than an open field;
say which angles were tried before reading absence as evidence.

### Stating what would close it

Write the falsifier as a claim someone could go and find, not as a topic. "Any paper reporting
multi-hop QA with retrieval recall matched across both arms" is a falsifier; "more work on
retrieval" is not. It gives the assessment a shelf life and makes a later `ars-watch` run
cheap. A workspace records this as `closes_if` on the gap.

## Evidence states and boundaries

Abstract-only evidence supports only an attributed, softened high-level claim; any number requires reading and recording its page, table, figure, log, or section locator.

Distinguish what a nearby source claims from what the assessment concludes. Keep the verdict
bounded by the search behind it — "no overlapping work was retrieved under these queries and
dates" is supportable; "this is novel" is not. With nothing usable, report the attempts and the
smallest next test rather than an assessment that only looks sourced.

## Output

A useful report can be short:

```markdown
# Gap assessment — <topic>

## Current reading
Open / partly covered / likely covered — <why, with sources>

## Nearest prior work
<the closest 2-3 sources, each with why it is not the answer and the axis it differs on>

## Contribution case
<who benefits and what would change>

## Feasibility and risks
<concrete constraints and assumptions>

## What would close this
<the finding that would settle it, stated so someone could go and look for it>

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
