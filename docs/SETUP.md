# Setup — optional research sources

ARS installs skills, not a research runtime. Configure whichever source tools the current
question needs in the host you already use. No backend is required for a direct task from
supplied files, and no backend is checked or invoked by the installer or doctor.

## Source choices

Common choices include:

| Need | Possible source |
|---|---|
| preprints and structured metadata | an arXiv-compatible search tool |
| identifiers, related works, and citation metadata | OpenAlex or another identifier service |
| proceedings, web pages, and reports | a web search/fetch provider |
| local PDFs or HTML | a local converter already trusted in the project |

Use the tool's current documentation and keep secrets in its normal environment or secret
store. Do not put API keys in a workspace, prompt, or public report. Record the source/tool,
query, date, and any result boundary when the user asks for a reproducible search.

## Honest failure handling

A search service can be unavailable, rate-limited, stale, or incomplete. Report the exact
operation that was not checked and the resulting evidence limit. Do not silently substitute
memory, a title guess, or a placeholder citation. A failed update must not be described as “no
new work.”

When resolving an identifier, prefer a stable ID already supplied by the user or source. If
only a title is available, say that disambiguation is needed and use author/year/context before
attributing a result. Keep preprint and published versions distinct when numbers or metadata
differ.

## Optional workspace

A named `.research/survey/<slug>/` workspace can hold a question, source ledger, corpus, notes,
map, gaps, citations, and search log. Use only the files the task needs. Legacy `phase`,
counts, recall, saturation, and freshness fields remain readable but have no active meaning in
this toolbox.

The optional linter is explicit:

```bash
# persistent CLI (after `uv tool install`)
ai-research-skills lint .research/survey/<slug>
# one-shot CLI
uvx --from git+https://github.com/signalridge/ai-research-skills ai-research-skills lint .research/survey/<slug>
# or, from an installed host directory:
python3 .claude/ai-research-skills/scripts/rs_validate.py .research/survey/<slug>
```

It checks present files for parse/schema shape, duplicate keys or identifiers, dates, dangling
references, and explicit provenance. It allows absent artifacts and does not require a phase,
query count, full grid, saturation result, or every extraction field.
Use `--strict` only when you want warnings to affect the exit code.

## Optional evidence fields

A corpus can record `claim_locator` and `numbers[].locator` only when a user has a useful
location. Each supplied locator uses a non-empty `kind` and `value`, may include `detail`, and
may include extension fields; old `source`, `looked_at`, number fields, and old corpora remain
valid. A protocol can optionally record `search.status` (`not_attempted`, `success` for completed
searches with hits, `success_no_hits`, `partial_success`, `backend_failure`, or `unknown`)
together with a backend, queries, or note. Missing search status is simply unrecorded, not “no
results” and not a gate.

Use the stable corpus `key` for identity. A report may use temporary `[1]`/`[2]` display numbers,
assigning one number per key and reusing it, without adding those numbers to `corpus.jsonl`.
Full or partial evidence should be labelled as such; with no usable evidence, report attempts,
limits, and the smallest next step instead of fabricating citations, numbers, or a sourced
conclusion. Abstract-only evidence supports only an attributed, softened high-level direction or
conclusion; it does not support numeric results such as 4 points or 20% unless a named page,
table, figure, log, or section has been read and recorded. The worked example is a
compatibility sample, not a template to complete.

## Four small integrity checks

Keep the default integrity habits human-visible and task-sized:

1. fail loudly rather than silently falling back or using placeholders;
2. run one real small case before an expensive run;
3. snapshot and confirm before destructive changes; and
4. make one handoff check only when the user requests a handoff.

For literature, provenance and no fabricated citations are integrity guidelines. They do not
interrupt a user's work automatically.

## Host limitations

The installer provides skills on every registered host and slash-command aliases where the host
supports them, but ARS 0.8 installs no runtime governance hooks. Source skills and commands are
marked `disable-model-invocation: true`; hosts without that standard setting cannot enforce the
same user-only distinction, so invoke the named skill or command explicitly.

## LaTeX

Compile the requested document, read the compiler log, and fix the reported errors. Do not add
an unrelated documentation-validation pipeline.
