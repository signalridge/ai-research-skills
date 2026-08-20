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

### How "user-invoked" is declared, and where it is actually enforced

Each skill declares the same thing three times, because no single declaration reaches every
host:

| Declaration | Read by | Effect |
|---|---|---|
| `disable-model-invocation: true` | Claude Code | Enforced: the skill is not auto-loaded, not preloaded into subagents, not fired by a scheduled task |
| `metadata.ars-invocation: user-invoked` | Any spec-conformant reader | Declarative: survives on hosts that drop fields they do not define |
| A sentence in the skill body | Any model that loads the skill | Behavioural: says what not to chain into |

The flag is the only one with teeth, and it works on the host clients that support it. It is
also not in the Agent Skills frontmatter table, so `skills-ref validate` rejects every ARS
skill on that one key — a known cost, accepted because the spec's own client-implementation
guidance names this exact flag for opting out of model-driven activation, and because Claude
Code acts on nothing else (it explicitly does not read `metadata`). Dropping it would make the
project's central claim unenforced everywhere rather than somewhere.
`tests/check_frontmatter.py` pins the deviation to that single key.

### Retrieved text is evidence, not instruction

These skills read papers, PDFs, and pages that nobody in the conversation wrote. Such a
document can contain sentences addressed to whatever is reading it. The rule throughout is
that retrieved content is summarised and attributed, never obeyed: a source asking for a tool
call, a file write, a credential, or a change of scope is reported as something the source
says. Instructions come from the user only. `01-recall` states this in full; the skills that
ingest external documents each restate the part that applies to them.

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
or a deterministic sourced report. Abstract-only evidence supports an attributed, softened
high-level direction or conclusion, but not numeric results such as 4 points or 20% unless a
named page, table, figure, log, or section has been read and recorded. The full
worked-survey directory is a compatibility sample, not a required template.

## 4. Installer and host boundary

Fresh installs put standalone skills and, where available, user-invoked command aliases into
host skill directories. The current registry has six separate layouts: Claude, Codex, Cursor,
Pi, Kimi, and Kimi Code. They install no hooks and never modify host hook settings for research
validation. The manifest records package-owned ordinary files; atomic transactions, path
checks, locks, and sealed journals protect upgrades and rollbacks.
Current manifests use format 2, which older hook-enabled installers reject closed; the current
installer accepts format 1 only to migrate package-owned state. The committed legacy fingerprint
remains format 1 and is a separate compatibility boundary.

### What the manifest seal does and does not prove

The manifest carries a SHA-256 over its own contents. That detects corruption and truncation.
It is **not** proof of ownership: anyone who can write the file can re-seal it, so a manifest
that nominates `README.md` would otherwise have `README.md` deleted on the next install or
uninstall. Ownership is therefore re-derived from the host layout on every read — a recorded
path must be one exact current asset path or one exact path listed in the committed legacy
fingerprint for that host. Shared `skills/`, `commands/`, and `hooks/` namespaces are not
owned by prefix, and an arbitrary descendant of `ai-research-skills/` is not accepted. A
record for a host id the installer does not recognise is carried forward untouched and never
acted on. A recorded path that is *not* in that inventory is dropped from the record and
reported, not treated as an error: this reader cannot distinguish a forged claim from a record
written by a version whose assets have since been renamed, and failing closed on the second
case would wedge install, doctor and uninstall together, leaving no way out but deleting the
manifest by hand. Dropping is the safe half of the ambiguity — nothing may write or delete a
path whose ownership is unproven — and the file itself is left on disk for a person to judge.

The transaction journal uses the same exact inventory: current or explicitly published
legacy assets, each host's one historical config path, and the manifest. It records where each
target started *and* the complete regular-file state (bytes and mode) it was meant to end in.
Format 1 is compatibility-only and is cleared only when every target still equals its before
state; any difference is retained as a possible post-crash edit. Format 2 restores only the
two explainable states; a third state or mode change fails closed, leaves the file alone, and
keeps the sealed journal for a person to resolve.

Recovery is the one path that writes bytes named by a file inside the project, so its trust
boundary is stated rather than assumed. The seal is a keyless digest: it proves the record was
not corrupted, never that this installer wrote it, because anyone who can write the file can
re-seal it. A format-2 journal therefore also carries the absolute canonical path *and* the
device/inode of the root it was written for, and both must match. Relative spellings are
rejected outright — resolving one against the working directory is what would let a journal
committed to a repository authorize itself on every clone, since users run from the root — and
a journal claiming that a shared host configuration was deleted is refused, because this
installer writes that file and never removes it. What remains is an attacker who can already
read the root's inode and write into the project; they can write the same file directly, so
recovery grants them nothing they lack.

### Why files are copied rather than linked

Each host gets its own copy of every asset. Two cheaper designs exist and are worth naming,
because a reader who knows the alternatives will ask: a central library with symlinks per host
gets `update` for free, and a native per-host manifest avoids copying content at all. Both were
rejected for the same reason — neither can answer "is this file still the one we wrote?" A
symlink farm makes an edit to one host's copy an edit to every host's, silently; a manifest of
names without digests cannot tell a file the user edited from one we still own, so uninstall
has to either delete it anyway or never delete anything. Copies plus per-file digests are what let the
installer refuse to touch a modified file and say which one.

The cost is real: roughly the shipped markdown set is duplicated per host, and the transaction
journal, two-level locking, and path checks exist to make copying safe. That machinery is the
price of the ownership guarantee, not of the copying.

### The legacy hook compatibility window ends at 0.9.0

`hook_adapters.py` recognizes old ARS handler fingerprints so an upgrade or doctor run can
remove an exact unchanged ARS-owned handler and its obsolete hook file. It leaves foreign or
unknown configuration untouched; a modified ARS-looking handler or file is preserved and
reported. No desired handler definitions are generated, and no installer, command, skill, or
doctor path runs the linter automatically.

**This code is removed in 0.9.0.** That covers `hook_adapters.py`, `assets/hooks/`, the
legacy fingerprint at `assets/legacy/v0.5.0.json`, the legacy branches in `doctor`, and
manifest format 1 support — together around 2,600 lines, or two fifths of the Python in the
project, none of which a fresh install can produce. "One compatibility period" without an end
date is how dead code becomes permanent, so the date is the version: anyone still on a
pre-0.8 install must upgrade through 0.8.x, which cleans the old handlers, before 0.9.0.

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
