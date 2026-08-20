---
description: List the ARS research skills and when to use each
disable-model-invocation: true
---
# /ars-help

This package is a small, user-invoked research toolbox. Pick one skill for the task:

- `ars-survey` — compose discovery, screening, extraction, and synthesis;
- `ars-gap-gate` — assess whether a gap is open, useful, and feasible;
- `ars-related-work` — write a source-grounded literature section;
- `ars-decision-brief` — compare evidence for a technical choice;
- `ars-watch` — run a deliberate literature update;
- `ars-red-team` / `ars-audit` (legacy-compatible alias) — challenge an answer or draft;
- `ars-verify` — trace citations, provenance, and numbers; and
- `ars-lint` — explicitly lint present workspace artifacts.

A `.research/survey/<slug>/` workspace is optional. Ask for the files or sources you need,
report missing evidence honestly, and save only requested artifacts. `/ars-audit` and
`/ars-verify` are explicit, non-chaining aliases. Nothing runs automatically at install, session
start, turn end, or phase transition.
