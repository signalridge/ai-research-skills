# ai-research-skills

A survey-first research suite for AI/ML. **One survey engine, four exits.**

A go/no-go on a topic, a related-work section, a standing watch, and a build/adopt/skip
brief look like four workflows. They are four projections of one object — a screened,
provenance-tracked, taxonomized corpus with a coverage map over it.

So the survey is built once and written to disk as typed state. Everything downstream is a
pure function of it, and **only the survey is allowed to search**.

```
                        ┌─────────────────────────────┐
   topic ──────────────▶│  ars-survey (only searcher) │
                        └──────────────┬──────────────┘
                                       │ .research/survey/<slug>/
             ┌───────────────┬─────────┴────┬──────────────┐
             ▼               ▼              ▼              ▼
        ars-gap-gate  ars-related-work  ars-watch  ars-decision-brief
         go/no-go        prose+bib        diffs     evidence matrix
```

## Install

Into any project you want to run a survey in:

```bash
uvx --from git+https://github.com/signalridge/ai-research-skills ai-research-skills install .
```

It installs into whichever agents the project already uses — **claude, codex, cursor,
pi, kimi** — or Claude Code if it uses none. Scope it with `--host claude,codex`. `uninstall` removes only manifest-owned files and handlers, leaves foreign hooks alone, and refuses modified ownership state; `doctor` checks each host item by item.

**Write-time guardrails are configured on four hosts; runtime trust differs.** A host earns
a place here by having a documented enforcement surface, not just a skills directory.
Cursor has no end-of-turn safety equivalent, and Pi cannot be declared active until its
extension is confirmed; the installer and doctor say configured/degraded rather than
claiming runtime activity. Kimi remains skills-only.

| Host | Config written for you | Slash commands | Note |
|---|---|---|---|
| claude | `.claude/settings.json` | yes | |
| codex | `.codex/hooks.json` | — | top-level `hooks` object; foreign groups preserved |
| cursor | `.cursor/hooks.json` | — | camelCase events; native direct entries; stop advisory omitted |
| pi | `.pi/settings.json` | — | inert until `pi install npm:@hsingjui/pi-hooks` |
| kimi | — | — | skills only; no verified hook contract |

The guards emit both deny dialects — `hookSpecificOutput` for Claude/Codex, a flat
`permission` field for Cursor — so one implementation covers the configured write-time
surfaces. Kimi gets the methodology without the enforcement, and the installer says so.
Cursor has no safe stop/end-of-turn equivalent, so its `stop_survey_peer` advisory is not
installed and the degraded capability is reported. Pi is reported as configured-but-inactive
unless its extension runtime is independently confirmed.

Two things only Claude Code gives you. **Slash commands** are a Claude-only surface;
elsewhere the same skills trigger from their descriptions or by name ("run `ars-survey` on
X"), and the installer reports that per host rather than announcing commands it did not
write. **`disallowed-tools`**, which makes the four read-only exits structurally unable to
search, is a Claude Code frontmatter extension rather than part of the Agent Skills
standard — and even there it lapses on your next message. So the "never search here" rule
stays written into every one of those skills as the real backstop.

Claude's hook uses `$CLAUDE_PROJECT_DIR`; non-Claude installs use an absolute project path so
the command remains anchored when the agent runs from a subdirectory. Payload-relative paths
still depend on the host's event contract, which is why the installer reports degraded
capabilities instead of promising identical runtime behavior.

Search backends are configured separately — see **[docs/SETUP.md](docs/SETUP.md)**. The
`arxiv` MCP server is required; `openalex` and `tavily` are strongly recommended.

## Use

```
/ars-survey <topic>      start or resume a survey — the only stage that searches
/ars-gate                3-gate go/no-go dossier, verdict withheld
/ars-relwork             related-work draft + verified bib
/ars-brief <decision>    build/adopt/skip evidence matrix
/ars-watch [arm|check]   arm the subscription, or run a digest
/ars-audit               red-team + citation/number integrity
/ars-help                where you are in a survey right now
```

Skills auto-trigger too — "survey retrieval-augmented agents", "has anyone compared X to Y".

## What it enforces

### Honest permissions and ownership

`ars-survey` is the only skill that may freely construct or discover the corpus. `ars-watch`
may update `corpus.jsonl`, `protocol.yml`, and `gaps.yml` only at Phase 5 while replaying the
frozen protocol. `ars-red-team` may search only for refutation and never appends discoveries
to the corpus. `ars-gap-gate`, `ars-related-work`, and `ars-decision-brief` are read-only
projections of survey state; `ars-verify` performs identifier lookup, not discovery. Missing
evidence goes back to `ars-survey`.

The installer writes `.ai-research-skills/manifest.json`, sealed with SHA256, and owns only
listed ordinary files plus exact hook handlers. Same-name conflicts, symlinks, invalid JSON,
and modified manifests are rejected before any mutation. Unknown or edited pre-v0.5 `rs-*`
assets are preserved with a migration notice.

Prompts are advisory; configured hooks are enforcement where the host runtime dispatches
them. Pi remains unconfirmed and Cursor is missing end-of-turn advisory coverage. All
shipped guards fail open.

| Hook | Verdict | Catches |
|---|---|---|
| `bib_provenance_guard` | **denies** | A `.bib` gaining or changing entries without a per-entry `rs-provenance` attestation binding key, stable id, tool and date. A legacy file header only grandfathers unchanged old entries. |
| `absence_claim_guard` | Claude PostToolUse block; Cursor/Codex pre-write deny | "No prior work…", "first to…" in prose, with no `gaps.yml` entry carrying ≥3 query phrasings behind it. |
| `survey_staleness` | advisory | Session start: a corpus older than 30 days being reasoned from. |
| `stop_survey_peer` | advisory | End of turn: abstract-only includes, unadjudicated tails, single-mode recall, gaps with no nearest prior work, zero corroboration. |

The BibTeX attestation is a tamper-evident tripwire, not cryptographic proof: attestations
can be forged. `ars-verify` must still resolve identifiers externally. The absence guard is project-scoped, not matched to the sentence you wrote — no regex can
tell which gap a claim rests on, so it names the gap to check rather than pretending to
have found it. `stop_survey_peer` is a deterministic read of state, not a second model: it
tells you what the corpus rests on, not what you concluded from it. That is `ars-red-team`.

Survey state lives in `.research/survey/<slug>/` and is schema-checked:

```bash
uv run --group dev python .claude/ai-research-skills/scripts/rs_validate.py .research/survey/<slug>
```

`phase` is required and validation is phase-aware: low phases are not penalised for future
artifacts, while later phases reconcile explicit counts, typed closures, the complete unique
Cartesian grid and saturation freshness.

## Docs

- **[docs/DESIGN.md](docs/DESIGN.md)** — the architecture, the seventeen rules and the
  failure each one traces to, and what is deliberately not built.
- **[docs/SETUP.md](docs/SETUP.md)** — backend configuration, OpenAlex budget, and API
  failure modes verified against the live service.
- **[examples/](examples/README.md)** — a complete survey state directory at the moment it
  freezes, annotated with what each record demonstrates.

## Develop

The suite is package data. Skills, commands, hooks, schemas and the validator all live
under **`src/ai_research_skills/assets/`** — one tree, the same one a checkout reads and a wheel
carries. `.claude/` in this repo is not source: it is what `ai-research-skills install .`
writes when the repo dogfoods its own guardrails, and it is gitignored. Edit under
`assets/`, then re-run the install to see the change take effect here.

```bash
uv sync                                   # dev toolchain (pinned by uv.lock) + dogfood install
just test                                 # or: uv run --group dev python tests/run_tests.py
just check                                # ruff + basedpyright + plugin-shape tests
just install                              # re-install into this checkout after editing assets/
```

Tests also run on a bare interpreter with no packages installed, because the hooks must
work in whatever `python3` the user already has:

```bash
uv run --no-project python tests/run_tests.py
```

## License

MIT
