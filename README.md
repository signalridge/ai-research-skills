# ai-research-skills

A small, user-invoked research toolbox for AI/ML. Each skill is a standalone peer: use only
what the current question needs, with a prompt, files, links, supplied sources, or an optional
`.research/survey/<slug>/` workspace.

## Install

For a persistent CLI, install the tool once and then install into a project:

```bash
uv tool install --from git+https://github.com/signalridge/ai-research-skills ai-research-skills
ai-research-skills install .
```

For a one-shot install without adding a persistent command:

```bash
uvx --from git+https://github.com/signalridge/ai-research-skills ai-research-skills install .
```

The installer detects existing `claude`, `codex`, `cursor`, `pi`, and `kimi` directories, or
falls back to Claude Code. Use `--host claude,codex` to choose explicitly.

Installs contain skills, Claude command aliases, the optional structural linter, and schemas.
Fresh installs install **no runtime hooks** and do not create or modify host hook settings.
The ownership manifest and transaction journal protect package files without claiming foreign
files or configuration.

```bash
ai-research-skills install .
ai-research-skills doctor .
ai-research-skills lint .research/survey/my-topic
ai-research-skills uninstall .
```

These commands use the persistent `uv tool install` route above. With the one-shot route,
run the same subcommand through `uvx --from git+https://github.com/signalridge/ai-research-skills ai-research-skills ...`.

`doctor` is structural and user-invoked. During an upgrade or doctor run it can remove exact,
unchanged ARS-owned legacy hook handlers and obsolete hook files from older installations.
Modified handlers/files and unknown configuration are preserved and reported. It never runs
the research linter automatically.

## Use the toolbox

| Skill | Use it for |
|---|---|
| `ars-survey` | any chosen combination of discovery, screening, extraction, comparison, and synthesis |
| `ars-gap-gate` | an advisory assessment of whether a gap is open, useful, and feasible |
| `ars-related-work` | a thematic, source-grounded related-work section |
| `ars-decision-brief` | build/adopt/skip/revisit evidence for a technical choice |
| `ars-watch` | a deliberate literature update or alert check |
| `ars-red-team` | counterevidence and unsupported-claim review |
| `ars-verify` | citation, provenance, and number traceability |

Claude users also get `/ars-survey`, `/ars-gate`, `/ars-relwork`, `/ars-brief`, `/ars-watch`,
`/ars-audit` (legacy-compatible red-team alias), `/ars-verify`, `/ars-help`, and `/ars-lint`.
Aliases are explicit and do not chain skills. Other hosts use the installed skills by name.
Nothing runs at install, session start, turn end, or an imagined phase transition.
The skills and command aliases declare user-only invocation where the host supports that field. A host that does not expose a standard auto-invocation switch cannot enforce this distinction; invoke the named skill or command explicitly. No hook is used to simulate one.

A workspace is optional. Existing `.research/survey/<slug>/` corpora remain useful, including
legacy `phase` fields and artifacts. Skills read and write named files only when the user asks;
missing files yield an explicit limitation or follow-up suggestion, not a workflow error.

A corpus record may add an optional `claim_locator` or `numbers[].locator` with a non-empty
`kind` and `value` (for example `table`, `page`, `section`, or `url_fragment`); legacy records
and number fields remain valid. A protocol may likewise add an optional `search` status with
`not_attempted`, `success` (completed with hits), `success_no_hits`, `partial_success`,
`backend_failure`, or `unknown`, plus backend/query/note context. These fields describe what was recorded, not
completion or readiness.

Example recipes:

```text
Search two query families for X, screen the supplied results, extract only claims used in a
short comparison, and save the source ledger under .research/survey/x/.
```

```text
Use the existing corpus and these PDFs to draft related work. Do not search, and list what the
abstract-only records cannot support.
```

With usable evidence, reports separate sourced facts from synthesis; with partial evidence,
they narrow claims and state the limit. With zero usable evidence, they do not invent citations,
numbers, or a deterministic sourced report: they state attempts, constraints, and the smallest
next step. Abstract-only records support only softened high-level wording. The complete
`examples/worked-survey/` directory is a compatibility sample, not a required template.

## Optional integrity tooling

Run the linter explicitly when useful:

```bash
python3 .claude/ai-research-skills/scripts/rs_validate.py .research/survey/<slug>
# persistent CLI (after `uv tool install` above)
ai-research-skills lint .research/survey/<slug>
# one-shot CLI
uvx --from git+https://github.com/signalridge/ai-research-skills ai-research-skills lint .research/survey/<slug>
```

It checks present artifacts for parsing/schema shape, duplicate keys or identifiers, malformed
dates, dangling references, and explicit provenance. Missing artifacts are allowed. It does
not impose phases, recall modes, counts, grids, saturation, or extraction quotas.

Keep the human-visible integrity habits short:

1. fail loudly instead of silently falling back or using placeholders;
2. run one real small case before an expensive run;
3. snapshot and confirm before destructive changes; and
4. do one handoff check only when requested.

For literature, do not fabricate citations or numbers. Provenance and careful absence wording
are guidelines, not hidden workflow gates. For LaTeX, compile, read the log, and fix errors.

## Develop

```bash
uv sync
just test
just check
just test-bare
```

The assets live under `src/ai_research_skills/assets/`; `.claude/` is install output and is
ignored. Tests also run with a bare interpreter because the optional linter must work without
third-party packages.

See [docs/DESIGN.md](docs/DESIGN.md), [docs/SETUP.md](docs/SETUP.md), and
[examples/README.md](examples/README.md).

## License

MIT
