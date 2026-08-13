---
name: ars-watch
disable-model-invocation: true
description: >
  Run a user-invoked literature watch or update for a topic. Use supplied queries, alerts,
  sources, or an optional .research survey workspace to report what changed, what may close
  an open question, and what was not checked. A saved protocol is useful context but never a
  required phase or prerequisite; ask before writing persistent updates.
---

# ars-watch — a deliberate update, not a background controller

Use this skill when the user asks what is new, wants an alert checked, or wants to keep a
research question current. It is always invoked by the user. It does not run on session start,
at turn end, or installation.

## Inputs and modes

- With a direct topic, ask for a date window and preferred source types, then search if the
  user requested discovery.
- With supplied alerts/results, deduplicate and compare them to the question.
- With `.research/survey/<slug>/protocol.yml`, reuse its queries when useful, while treating
  `phase`, `last_searched_at`, counts, and saturation fields as historical context only.
- With no workspace, return a digest without creating one unless the user asks to save it.

A failed, partial, or rate-limited source check is reported as inconclusive. It does not
advance a date or manufacture a result. A new paper is a candidate until the user asks for
screening or incorporation into a corpus; do not silently rewrite `corpus.jsonl`, `gaps.yml`,
or a protocol.

## Evidence states and boundaries

With usable updates, separate confirmed changes from context; with partial evidence, report the checked sources and unresolved backend limits. With zero usable evidence, do not invent citations, numbers, or a deterministic sourced digest: report attempts, failures, and the smallest next check. Abstract-only updates support softened high-level wording. Ask only the smallest clarification when ambiguity materially changes the watch. This skill never invokes another skill or creates or repairs a workspace automatically.

## Digest

Prioritise:

1. direct changes to the question or a stated falsifier;
2. updates to existing sources (versions, corrections, retractions, changed numbers); and
3. adjacent work that is useful context but does not change the answer.

For each item include a stable identifier, source/date, why it matters, and confidence. State
which queries or alerts were checked and what they could not cover. If the user asks to save a
digest, use a dated file such as `digests/YYYY-MM-DD.md` and confirm the write.

## Integrity habits

No silent fallback or placeholder sources. For a destructive cleanup or rewrite, snapshot and
ask for confirmation. Do one small real check before an expensive recurring setup, and do a
handoff check only when requested.
