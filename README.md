# research-skills

A survey-first research suite for AI/ML. **One survey engine, four exits.**

A go/no-go on a topic, a related-work section, a standing watch, and a build/adopt/skip
brief look like four workflows. They are four projections of one object — a screened,
provenance-tracked, taxonomized corpus with a coverage map over it.

So the survey is built once and written to disk as typed state. Everything downstream is a
pure function of it, and **only the survey is allowed to search**.

```
                        ┌─────────────────────────────┐
   topic ──────────────▶│  rs-survey  (only searcher) │
                        └──────────────┬──────────────┘
                                       │ .research/survey/<slug>/
                        ┌──────────────┴──────────────┐
                        ▼        ▼         ▼          ▼
                  rs-gap-gate  rs-related-  rs-watch  rs-decision-
                   go/no-go      work        diffs      brief
```

## Install

Into any project you want to run a survey in:

```bash
uvx --from ~/ghq/github.com/signalridge/research-skills research-skills install .
```

It installs into whichever agents the project already uses — **claude, codex, cursor,
pi, kimi** — or Claude Code if it uses none. Scope it with `--host claude,codex`. `uninstall` removes only what it wrote and leaves hooks you
added yourself alone; `doctor` checks each host item by item.

**Four of the five hosts run the guardrails.** A host earns a place here by having a
verified way to enforce, not just to read skills — adapters that could only drop
markdown into a directory were removed, because the design rests on enforcement being
real and a skills-only install hands you a false sense of it.

| Host | Config written for you | Note |
|---|---|---|
| claude | `.claude/settings.json` | |
| codex | `.codex/hooks.json` | events at top level, not nested |
| cursor | `.cursor/hooks.json` | camelCase events; `version` is required or none load |
| pi | `.pi/settings.json` | inert until `pi install npm:@hsingjui/pi-hooks` |
| kimi | — | skills only; no verified hook contract |

The guards emit both deny dialects — `hookSpecificOutput` for Claude/Codex, a flat
`permission` field for Cursor — so one implementation covers all four. Kimi gets the
methodology without the enforcement, and the installer says so.

Search backends are configured separately — see **[docs/SETUP.md](docs/SETUP.md)**. The
`arxiv` MCP server is required; `openalex` and `tavily` are strongly recommended.

## Use

```
/rs-survey <topic>      start or resume a survey — the only stage that searches
/rs-gate                3-gate go/no-go dossier, verdict withheld
/rs-relwork             related-work draft + verified bib
/rs-brief <decision>    build/adopt/skip evidence matrix
/rs-watch [arm|check]   arm the subscription, or run a digest
/rs-audit               red-team + citation/number integrity
/rs-help                where you are in a survey right now
```

Skills auto-trigger too — "survey retrieval-augmented agents", "has anyone compared X to Y".

## What it enforces

Prompts are advisory; hooks are enforcement. Four, all fail open.

| Hook | Catches |
|---|---|
| `bib_provenance_guard` | Hand-written BibTeX. **Blocks** `.bib` writes with no tool provenance. |
| `absence_claim_guard` | "No prior work…", "first to…" with no `gaps.yml` evidence behind it. |
| `survey_staleness` | A corpus older than 30 days being reasoned from. |
| `stop_survey_peer` | End of turn: abstract-only conclusions, unadjudicated tails, single-mode recall. |

Survey state lives in `.research/survey/<slug>/` and is schema-checked:

```bash
uv run --group dev python .claude/research-skills/scripts/rs_validate.py .research/survey/<slug>
```

## Docs

- **[docs/DESIGN.md](docs/DESIGN.md)** — the architecture, the seventeen rules and the
  failure each one traces to, and what is deliberately not built.
- **[docs/SETUP.md](docs/SETUP.md)** — backend configuration, OpenAlex budget, and API
  failure modes verified against the live service.
- **[examples/](examples/README.md)** — a complete survey state directory at the moment it
  freezes, annotated with what each record demonstrates.

## Develop

```bash
uv sync                                   # dev toolchain, pinned by uv.lock
just test                                 # or: uv run --group dev python tests/run_tests.py
just check                                # ruff + basedpyright + plugin-shape tests
```

Tests also run on a bare interpreter with no packages installed, because the hooks must
work in whatever `python3` the user already has:

```bash
uv run --no-project python tests/run_tests.py
```

## License

MIT
