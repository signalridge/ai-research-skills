# ai-research-skills — design

ARS is a small, skills-driven research toolbox for a single researcher. It helps turn a
question and evidence into useful notes or decisions without pretending that literature work
has a universal lifecycle.

## 1. Core model

Every research skill is a peer and is invoked by the user for a concrete task. A skill accepts
direct prompt text, local files, links, or supplied sources. It may optionally read or write a
named `.research/survey/<slug>/` workspace when the user requests that explicitly.

The workspace is an interoperability format, not a required process:

```text
.research/survey/<slug>/
  protocol.yml       # optional question, scope, search notes, or legacy fields
  corpus.jsonl       # optional source records
  coverage.yml      # optional comparison/map notes
  gaps.yml          # optional gap and falsifier notes
  refs.bib          # optional citations
  notes/            # optional source notes
  log.md            # optional search log
```

Older workspaces may contain `phase`, counts, recall modes, saturation, or other historical
fields. ARS reads them when useful and leaves them intact. It does not migrate, delete, or
backfill them automatically.

## 2. Skills are composed by the researcher

- **`ars-survey`** is the comprehensive convenience skill. The user can ask for discovery,
  screening, extraction, mapping, synthesis, or any combination in one request.
- **`ars-gap-gate`** assesses whether a proposed gap appears open, useful, and feasible.
- **`ars-related-work`** turns supplied or requested evidence into thematic prose.
- **`ars-decision-brief`** compares evidence for a build/adopt/skip/revisit choice.
- **`ars-watch`** runs an explicit update or alert check and reports change.
- **`ars-red-team`** looks for counterevidence, unsupported wording, and weak assumptions.
- **`ars-verify`** checks citations, provenance, numbers, and source consistency.

No skill owns another skill's phase or artifact. A focused skill can search when the user
explicitly asks it to, and it reports exactly what it searched. A missing workspace or source
is a limitation and a follow-up suggestion, not a workflow failure.

## 3. Evidence discipline

The toolbox keeps a few durable habits:

- keep stable identifiers, source/tool, access date, and what was actually read;
- do not fabricate citations, numbers, quotes, or source status;
- distinguish a source's claim from our synthesis and from uncertainty;
- preserve disagreement and identify the conditions behind it;
- bind absence statements to the search scope and date; and
- quote numbers only after reading the named table, figure, page, or log.

These are integrity guidelines. They are not hidden workflow gates. An optional linter checks
only artifacts present in a directory for parse/schema shape, duplicate keys and identifiers,
malformed dates, dangling references, and explicit provenance. It does not assess task
completion or research quality.

### Optional evidence traceability

Corpus records may add `claim_locator` and each number may add `locator`. A locator is optional;
when present it has non-empty `kind` and `value`, an optional `detail`, and may carry extra
extension fields. Page, section, table, figure, appendix, URL fragment, code line, and timestamp
are useful conventions. Existing `source`, `looked_at`, legacy number fields, and old records
remain valid. The linter validates supplied locator shape only; it does not require locators,
measure coverage, parse prose, or enforce citations.

A protocol may also carry an optional `search` object. Its status can be `not_attempted`,
`success` (completed with hits), `success_no_hits`, `partial_success`, `backend_failure`, or
`unknown`, with optional
`backend`, `queries`, and `note`. This records search state when the user chooses to record it;
absence is unknown and is not a completion or ready gate. Reports use the corpus `key` as the
stable identity and may assign temporary `[1]`/`[2]` numbers for display, reusing one number per
key without writing those numbers back to the corpus.

With full evidence, reports distinguish sourced facts from synthesis; with partial evidence,
they narrow claims and name the unchecked portion. With zero usable evidence, they report what
was attempted, the limits, and the smallest next step rather than inventing citations, numbers,
or a deterministic sourced report. Abstract-only evidence gets softened wording. The full
worked-survey directory is a compatibility sample, not a required template.

## 4. Installer and host boundary

Fresh installs put standalone skills and, where available, user-invoked command aliases into
host skill directories. They install no hooks and never modify host hook settings for research
validation. The manifest records package-owned ordinary files; atomic transactions, path
checks, locks, and sealed journals protect upgrades and rollbacks.
Current manifests use format 2, which older hook-enabled installers reject closed; the current
installer accepts format 1 only to migrate package-owned state. The committed legacy fingerprint
remains format 1 and is a separate compatibility boundary.

For one compatibility period, `hook_adapters.py` recognizes old ARS handler fingerprints. An
upgrade or doctor run may remove an exact unchanged ARS-owned handler and obsolete hook file.
It leaves foreign or unknown configuration untouched. A modified ARS-looking handler or file
is preserved and reported. No desired handler definitions are generated by the adapter, and no
installer, command, skill, or doctor path runs the linter automatically.

The source/license ledger remains neutral: this repository is MIT; any local architecture
review is re-expressed as original design, and no external source code, prompts, data, or
assets are shipped.

## 5. Optional recipes

A user may choose a recipe such as:

```text
Search X using two query families and one citation walk. Screen the supplied results, extract
claims and table locations, and write a concise synthesis plus search limits.
```

Or:

```text
Read this corpus and draft a decision brief. Do not search or change the corpus; identify the
weakest claim and the smallest experiment that could change the recommendation.
```

These are examples, not a controller or sequence. A researcher can start with a draft review,
verify one citation, or run a watch update without constructing a survey first.

## 6. Deliberately not built

ARS does not include PRISMA/RAG/Zotero catalog management, an agentic orchestration layer, a
product-development pipeline, automatic hooks, automatic audits, fixed recall recipes,
coverage/saturation completion rules, or a large skill catalog. The goal is a small toolbox
that stays useful when the user's question changes.
