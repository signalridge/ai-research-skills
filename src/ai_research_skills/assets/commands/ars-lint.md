---
disable-model-invocation: true
---
# /ars-lint

Run the optional, user-invoked structural/evidence linter on a named artifact directory:

```bash
# persistent CLI (after `uv tool install`)
ai-research-skills lint .research/survey/<slug>
# one-shot CLI
uvx --from git+https://github.com/signalridge/ai-research-skills ai-research-skills lint .research/survey/<slug>
# or run the installed local script directly
python3 .claude/ai-research-skills/scripts/rs_validate.py .research/survey/<slug>
```

It checks only files that are present: parsing/schema shape, duplicate keys or identifiers,
dates, dangling references, and explicit provenance. Missing protocol, corpus, coverage, gaps,
or references are allowed. It does not decide task completion, count search modes, require a grid,
or advance a research phase. Run it when you ask; the installer and doctor do not invoke it.
