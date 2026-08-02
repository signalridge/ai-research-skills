---
description: 3-gate go/no-go dossier for a surveyed research gap (verdict withheld)
argument-hint: "[survey slug or gap id]"
---

Run the `gap-gate` skill for: **$ARGUMENTS**

Requires a completed survey. Verify first:

```bash
ls .research/survey/*/gaps.yml .research/survey/*/coverage.yml 2>/dev/null
```

If `gaps.yml` is missing or `protocol.yml` has `phase < 4`, stop and say the survey must
reach Phase 4 first. **Do not search to fill the hole.**

Check `evidence_of_absence.last_checked` on every gap before scoring G1. If it is more than
30 days old, offer `/rs:watch check` first — G1 scored against stale evidence is the single
most expensive error this plugin can make.

Assemble the evidence for all three gates and **stop short of the verdict**.
