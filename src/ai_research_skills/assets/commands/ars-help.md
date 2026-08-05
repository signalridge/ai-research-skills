---
description: What ai-research-skills does, and where you are in a survey right now
disable-model-invocation: true
---

Show the user this, adapted to whatever state actually exists.

First, look:

```bash
ls .research/survey/*/protocol.yml 2>/dev/null && \
  grep -H -E "^(topic|phase|last_searched_at):" .research/survey/*/protocol.yml
```

If a survey exists, lead with **where they are** — topic, phase, when it was last searched,
and the single next action. Then the reference below. If none exists, skip straight to it.

---

## ai-research-skills

One survey engine, four exits. The survey is the only stage that searches; every exit is a
pure function of the state it wrote.

```
/ars-survey <topic>      start or resume — six phases, stops at the Phase 0 checkpoint
/ars-gate                3-gate go/no-go dossier; assembles evidence, withholds the verdict
/ars-relwork             related-work draft, organised by taxonomy axis
/ars-brief <decision>    build/adopt/skip evidence matrix
/ars-watch [arm|check]   re-run the protocol; re-test every gap's falsifier
/ars-audit               red-team + citation and number integrity
```

Skills auto-trigger too — "survey X", "has anyone compared X to Y", "is this idea taken".

### The six phases

| Phase | Gate to advance |
|---|---|
| 0 Scope | Question is interrogative; **axes declared before any search** |
| 1 Recall | All four recall modes run: keyword, citation chain, venue/author, contrarian |
| 2 Score | Every candidate scored 1–10 with a summary written against the question |
| 3 Extract | Every include has a claim, code status, and sourced numbers |
| 4 Map | Coverage grid built; empty cells discriminated; gaps carry a falsifier |
| 5 Saturate | A round adds <5% new work *published before the survey started* |

### Guardrails that will interrupt you

| When | What |
|---|---|
| Writing a `.bib` by hand | **Blocked.** Generate with `export_citations`. |
| "No prior work…" with no `gaps.yml` evidence | **Blocked.** Back it or soften it. |
| Session start, corpus >30 days old | Warning. Run `/ars-watch check`. |
| End of turn | Audit: abstract-only conclusions, unadjudicated tail, single-mode recall. |

### State

`.research/survey/<slug>/` — `protocol.yml`, `corpus.jsonl`, `coverage.yml`, `gaps.yml`,
`refs.bib`, `notes/`, `log.md`. Check it any time:

```bash
python3 "$CLAUDE_PROJECT_DIR/.claude/ai-research-skills/scripts/rs_validate.py" .research/survey/<slug>
```

A worked example lives in `examples/` — read `examples/README.md` for what each record in
it demonstrates and why.

Design rationale is in `DESIGN.md`; backend setup and verified API failure modes are in
`SETUP.md`.
