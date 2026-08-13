---
name: ars-red-team
disable-model-invocation: true
description: >
  Perform a user-requested adversarial review of a research question, source set, draft,
  gap assessment, or decision brief. Try alternative terminology, counterexamples, citation
  errors, weak numbers, and unsupported conclusions. It is standalone, reports findings, and
  may search when the user explicitly asks for a refutation search.
---

# ars-red-team — try to break the answer

Use this skill when the user asks for a challenge or sanity check. It accepts a direct claim,
draft, files, supplied corpus, or optional `.research/survey/<slug>/` workspace. There is no
checkpoint schedule and no blocking phase. Choose the smallest review that answers the user's
request.

## Review lenses

- **Question and terminology:** list plausible alternate names and ask whether the evidence
  covers them.
- **Counterevidence:** identify the strongest result, source, or experiment that would change
  the conclusion. Search for it only when requested.
- **Selection:** look for excluded, unsure, contradictory, or unexamined sources that could
  change the synthesis.
- **Numbers and methods:** trace important numbers to a source location and check units,
  controls, baselines, sample size, and uncertainty.
- **Citations and wording:** find claims stronger than their sources, fabricated or dangling
  citations, and absence claims whose scope is wider than the search.
- **Decision risk:** name the concrete failure mode least prepared for and a cheap test.

Classify findings as critical, material, or advisory for the user's convenience. Do not turn
that classification into an automatic delivery block. If a finding changes the answer, show
the smallest correction or follow-up search.

## Evidence states and boundaries

With external evidence, tie each finding to a source or artifact; with partial evidence, mark which refutations remain unchecked. With zero external sources, this skill may still perform a logic review, but it must label the findings as unverified and must not invent citations, numbers, or a deterministic sourced conclusion. Abstract-only material supports softened challenges only. Ask only the smallest clarification when ambiguity materially changes the review. This skill never invokes another skill or creates or repairs a workspace automatically.

## Output

Write a new challenge note only when requested; otherwise return the review directly. Name the
artifact and location for each finding, include refutation attempts that found nothing, and
finish with unresolved limits. Preserve the original files unless the user explicitly asks for
edits.

Remember the four simple integrity habits: fail loudly rather than using placeholders, run one
real small case before expensive work, snapshot/confirm destructive changes, and perform a
handoff check only when requested.
