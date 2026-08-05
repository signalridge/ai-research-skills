---
description: Red-team plus citation/number integrity in one pass
argument-hint: "[survey slug or draft path]"
---

Run both audit skills over: **$ARGUMENTS**

1. `rs-red-team` — checkpoint A against the corpus and coverage map: terminology coverage,
   recall self-diagnostic, adjudication honesty, empty-cell interpretation, abstract-only
   conclusions. Then checkpoint B against whichever exit is being delivered.

2. `rs-verify` — BibTeX provenance, entry resolution, key consistency across draft/bib/corpus,
   number traceability, preprint-versus-published drift, retractions.

Also run the state validator:

```bash
python3 "$CLAUDE_PROJECT_DIR/.claude/research-skills/scripts/rs_validate.py" .research/survey/<slug>
```

Report critical findings first, each naming the artifact, the field, and the fix. Record the
refutation attempts that **failed** too — an attack that found nothing is evidence, and it
is what lets a reader calibrate the rest.
