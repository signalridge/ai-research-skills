---
description: Start or resume a literature survey — the only stage that searches
argument-hint: "<topic or research question>"
---

Run the `ars-survey` skill for: **$ARGUMENTS**

Before anything else, check for existing state:

```bash
ls .research/survey/ 2>/dev/null
```

If a survey matching this topic exists, read its `protocol.yml`, report the current `phase`,
and **resume at `phase + 1`**. Do not restart a survey because the corpus looks unfamiliar —
read it.

If none exists, begin at Phase 0 (Scope). Follow `.claude/skills/ars-survey/SKILL.md` and load each
`references/0N-*.md` only when entering that phase.

Stop at the Phase 0 checkpoint and wait for confirmation before searching. Searching is the
expensive part and a wrong grid discovered at Phase 4 costs the whole survey.
