---
description: Arm or run a standing watch over a completed survey
argument-hint: "[arm|check] [survey slug]"
---

Run the `watch` skill: **$ARGUMENTS**

Default to `check` if no mode is given.

- `arm` — register the standing arXiv subscription and set cadence from
  `saturation.baseline_growth`. Offer to schedule, but do not schedule without asking.
- `check` — re-run the protocol since `last_searched_at`, diff against `corpus.jsonl`, and
  **test every open gap's `closes_if`**. That last part is the point of the whole skill.

Whatever the outcome, update `protocol.yml.last_searched_at` and refresh `last_checked` on
every gap tested. A check that finds nothing but does not update those dates is worse than
no check — the survey looks stale when it is current.

If a gap closed, say so first, plainly, and do not soften it.
