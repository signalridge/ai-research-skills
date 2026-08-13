---
name: ars-survey
disable-model-invocation: true
description: >
  A user-invoked, standalone literature-research toolbox for discovering sources, screening
  evidence, extracting findings, mapping a field, or synthesising an answer. Use when the
  user asks to survey a topic, find related work, investigate a gap, compare approaches, or
  build a research corpus. Accepts a direct question, files, links, or supplied sources;
  optionally uses a named .research workspace when the user asks.
---

# ars-survey — compose the research you need

Use this skill when the user asks for literature research. It is a convenience skill, not a
workflow controller. The user chooses any combination of:

- **discover** — search requested backends or inspect supplied sources;
- **screen** — decide which sources answer the question and explain uncertainty;
- **extract** — record claims, methods, numbers, limitations, and provenance;
- **synthesise** — compare evidence, disagreements, trends, and open questions.

Start from the user's prompt, files, links, or source list. A `.research/survey/<slug>/`
directory is optional interoperability storage, not a prerequisite. If the user names a
workspace, read its existing files without assuming that any one field or artifact is
complete. Preserve older `phase` values and other legacy fields when editing; do not migrate,
backfill, or delete them unless the user asks.

## Direct use

1. Restate the question and the requested output in one or two sentences.
2. Ask for a missing scope boundary, date range, audience, or source constraint only when it
   changes the answer materially.
3. Search when the user asks for discovery, using the available backend best suited to the
   requested source type. If a backend is unavailable, say what was not searched; never fill
   the gap from memory.
4. Keep a small source ledger while working: stable identifier or URL, title, access date,
   how it was found, and what was actually read.
5. Separate source claims, your comparison, and unresolved uncertainty. Do not fabricate a
   citation, number, quote, experiment, or source status.
6. Return the requested answer even when evidence is partial, with a concise limitations note.

## Optional workspace

When the user asks to use `.research/survey/<slug>/`, use only the artifacts useful for the
requested task. Common files are `protocol.yml`, `corpus.jsonl`, `coverage.yml`, `gaps.yml`,
`refs.bib`, `notes/`, and `log.md`; all are optional. New records should carry explicit
provenance such as `found_via`, a stable identifier, and an access date. A workspace can be
started with only a protocol, only a corpus, or a short notes file. Do not require a complete
set of files before producing a scoped result.

A simple user-composed recipe might be:

```text
Search for recent work on X using two independent query families. Screen the first 30
results, extract the claims and evaluation conditions into the named corpus, then write a
short comparison and list what the search did not cover.
```

Another might be:

```text
Read the supplied corpus and two PDFs, extract only numbers used in the decision brief, and
write the brief to .research/survey/my-topic/brief.md. Do not broaden the search.
```

These are examples, not a required sequence. The user can invoke another skill directly for
one focused result.

## Reference cards and report keys

The six optional reference cards are [00-scope](references/00-scope.md),
[01-recall](references/01-recall.md), [02-score](references/02-score.md),
[03-extract](references/03-extract.md), [04-map](references/04-map.md), and
[05-saturate](references/05-saturate.md). Their numeric prefixes are stable filenames,
not an execution order or required sequence. Keep each corpus record's `key` as its stable
identity; if a report uses temporary `[1]`/`[2]` display numbers, assign one number per key,
reuse it for every mention, and never write those temporary numbers back into the corpus.

## Evidence notes

- Treat an abstract as support for what a paper says it studies, not proof of every result.
- Quote numbers only after reading the named table, figure, or source location.
- Carry disagreements instead of averaging them into an unsupported consensus.
- For absence statements, state the search scope and date and use careful wording. A gap note
  with queries and nearest prior work is useful provenance, not an automatic gate.
- If the user requests BibTeX, keep keys stable and bind each entry to the supplied or
  resolved identifier and export date. `ars-verify` can be invoked separately for a deeper
  check.


## Evidence states and boundaries

With usable evidence, separate sourced facts from synthesis; with partial evidence, narrow the
answer and state what remains unchecked. With zero usable evidence, do not invent citations,
numbers, or a deterministic sourced report: report what was attempted, the limits, and the
smallest next step. Abstract-only records support softened high-level wording only. Ask one
minimal clarification only when ambiguity materially changes the answer. This skill never
invokes another skill or creates or repairs a workspace automatically.

## LaTeX and files

For LaTeX, compile the document, read the log, and fix the reported errors. Do not invent a
documentation-validation pipeline. Save only files the user requested; report every file
written.

## Optional integrity habits

The default research-integrity habits are short and human-visible:

1. fail loudly rather than silently falling back or inserting placeholders;
2. run one real small case before an expensive run;
3. snapshot and confirm before destructive changes; and
4. do one handoff check only when the user requests a handoff.

Scientific and numeric sanity checks are useful when they fit the task. They are reminders,
not hidden workflow gates.

## Output

Report the sources searched or supplied, the selection or extraction scope, the main answer,
and the evidence limits. If the workspace or an expected artifact is missing, say so and offer
the smallest useful follow-up; do not label the research unready.
