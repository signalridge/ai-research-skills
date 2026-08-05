---
description: Draft a related-work section from a completed survey
argument-hint: "[survey slug]"
---

Run the `ars-related-work` skill for: **$ARGUMENTS**

Requires a completed survey with `corpus.jsonl` includes carrying `claim` and
`evidence_read`, plus a tool-generated `refs.bib`.

**Never search here.** A missing paper goes back to `/ars-survey`.

Organise by taxonomy axis, never one paragraph per paper. Check `evidence_read` before
characterising any paper — an `abstract` record supports what a paper addresses, never what
it showed.

Report the `evidence_read` distribution alongside the draft. That is the section's real
quality signal.
