---
name: ars-related-work
description: >
  Draft a related-work or literature-review section from a completed survey — organised
  thematically by taxonomy axis, every claim carrying a corpus key, every citation
  tool-generated. Use when the user asks to write related work, a literature review
  section, a background section, or to turn a survey into prose. Requires a completed
  survey; reads .research/survey/<slug>/ and never searches on its own.
disallowed-tools:
  # This exit is a pure function of survey state. The "never search here" rule in the
  # body is advisory; this makes it structural. A missing paper goes back to `ars-survey`.
  # Server names follow SETUP.md; a differently-named server silently escapes the
  # restriction, so the prose rule stays as the backstop.
  - WebSearch
  - WebFetch
  - mcp__tavily
  - mcp__arxiv-mcp-server
  - mcp__openalex
---

# related-work — corpus to prose

The survey did the work. This turns it into a section without adding a single claim the
corpus does not support.

## Preconditions

`protocol.yml` at `phase >= 4`, `corpus.jsonl` with includes carrying `claim` and
`evidence_read`, `coverage.yml` populated, `refs.bib` present and tool-generated.

**Never search here.** If a paper is missing, go back to `ars-survey`. A related-work section
that quietly grew its own citations cannot be audited against anything.

---

## Structure: by axis, never by paper

A paragraph per paper is a reading list. The axes in `coverage.yml` are already the
thematic structure — use them.

```
## Related work

### Retrieval strategies for multi-hop questions        <- axis: method
Single-shot retrieval [a, b] establishes the baseline… Iterative approaches [c, d, e]
instead re-query… The distinction matters because…

### Controlling for retrieval quality                    <- axis: control
Most comparisons hold the token budget fixed [c, f]. Only [g] varies retrieval recall
directly, and only at a single operating point…

### Evaluation depth                                     <- axis: evaluation
```

Within a section: **group by what papers claim, contrast where they disagree.** Two papers
reporting opposite results on the same benchmark is the most interesting sentence you can
write; do not smooth it into "several works have explored…".

**Every thematic paragraph compares at least two papers inside one sentence.** A paragraph
that cites a single paper is a summary, not a synthesis — merge it into a neighbour or cut
it. This is mechanically checkable, so check it before handing off: count citations per
paragraph.

If the coverage grid has a conspicuous empty cell that became a gap, that cell is your
final paragraph — it is what motivates the work.

## Every claim carries a key

While drafting, keep the mapping explicit:

```
Iterative retrieval improves multi-hop EM by 4–7 points over single-shot [sample2025iterative,
sample2025longcontext], though neither controls retrieval recall [sample2025iterative §5.2].
```

Strip the keys to `\cite{}` at the end. `ars-verify` checks every one resolves to a
`corpus.jsonl` record and a `refs.bib` entry.

## Survey records support field-level statements only

A survey or review record can carry "this direction has drawn attention recently" —
nothing finer. A method-level or number-level claim must resolve to the corpus record of
the *original* study. When all you hold is the survey's say-so, the claim goes on the
to-read queue; it does not enter the draft wearing the survey's citation. Citing a review
for a result it is reporting second-hand attributes the claim to the one venue that did
not test it.

## Do not exceed your evidence

Check `evidence_read` before characterising a paper.

| `evidence_read` | You may write |
|---|---|
| `abstract` | that the paper exists and what it claims to address. **Nothing about how it works or how well.** |
| `intro+method` | what the approach is |
| `intro+method+results` | what it showed, with numbers — if they are in `numbers[]` with a `source` |
| `full` | limitations, ablations, caveats |

An abstract tells you what the authors wanted to claim. Writing "X demonstrates that…" from
an abstract alone is how a section acquires claims nobody verified.

Three promotion rules, checked per sentence:

- **Strength never exceeds the strongest supporting record.** If the best record behind a
  sentence is `intro+method`, the sentence describes an approach, not a result. Promotion
  requires naming the record that justifies it — "the evidence got stronger" is not a
  reason.
- **A `conflicts_with` link caps the wording.** Where two records disagree, the sentence
  carries both sides and the likely reason (usually different controlled variables).
  "X works" from a split corpus is a fabrication of consensus.
- **Forbidden stronger wording is written down.** For each load-bearing claim, note the
  stronger phrasing you deliberately did not use ("outperforms" → "outperforms under
  matched recall"). `ars-red-team` checks the gap between the two.

Plus two anchored on `corroboration`:

- **"Demonstrates" and "establishes" need two independent records** whose
  `corroboration.agrees_with` point at each other. A single record tops out at
  "suggests" / "indicates" — one group's result is their claim, not the field's fact.
- **Paraphrase never upgrades the record's `claim`.** If the `claim` sentence says
  "suggests", the prose does not say "shows" — and quietly dropping the original
  qualifier ("under matched recall") is an upgrade. The `claim` sentence is the ceiling.

If most includes are `abstract`, the honest move is a shorter, vaguer section — and telling
the user why. If even that is not supportable, **write an intake note instead of a
section**: what the corpus has, what is missing, and which records to read first. A thin
section dressed as a finished one is the worst of the three options.

## Numbers

Only from `numbers[]`, only with `source` and `looked_at: true`. Attribute in text:

> iterative retrieval method reports +6.2 EM on multi-hop benchmark A (Table 3).

Note preprint versus camera-ready when they differ — v1 numbers routinely do.

A comparison table's missing value is written **not reported**. An empty cell invites the
reader to assume the worst or the best; an invented value is a fabrication. Both are
defects, and `ars-verify` has no way to tell a blank from a guess — so neither may ship.

## Citations

`refs.bib` is already tool-generated by `ars-survey` via `export_citations`. **Do not add
entries by hand** — a PreToolUse hook blocks `.bib` writes without tool provenance, and it
is right to.

Missing citation → go back to `ars-survey` and export it properly.

## Absence claims

If the section says "no prior work has…", "we are the first to…", "to the best of our
knowledge…", it needs a matching `gaps.yml` entry with populated `evidence_of_absence`. A
PostToolUse hook enforces this.

Match the hedging to the confidence:

| `gaps.yml` confidence | Phrasing |
|---|---|
| `high` | "To our knowledge, no prior work evaluates X under Y." |
| `medium` | "We are not aware of work that evaluates X under Y." |
| `low` | "Existing work on X typically assumes Y." — assert the pattern, not the absence |

Never write an unhedged absence claim from a `low`-confidence gap.

A backed absence claim still carries its bounds in the sentence: *as of* the gap's
`last_checked`, with the search scope readable in `gaps.yml` — "no prior work evaluates X
under Y (as of 2026-08-03; protocol in `gaps.yml`)". An unbounded "no prior work" asserts
forever-and-everywhere, and no search supports that.

## Time words carry dates

Never write `currently`, `recently`, `latest`, or `state-of-the-art` without a date
anchor. The draft is a snapshot of a moving field: write `as of <last_searched_at>` or a
concrete year. An unanchored "recently" is wrong within months, and nobody can tell when
it was last true.

## Output

Write `.research/survey/<slug>/related_work.md`. Markdown by default; LaTeX if the user is
working in a `.tex` project.

Then hand back:

- word count and section structure
- **the `evidence_read` distribution behind it** — this is the section's real quality signal
- any claim you softened for lack of evidence, and which one you would strengthen first
- papers in the corpus you deliberately left out, and why

## Handoffs

- **Upstream:** reads `corpus.jsonl`, `coverage.yml` and the tool-generated `refs.bib`
  written by `ars-survey`.
- **Writes:** `related_work.md`.
- **Downstream:** `ars-verify` checks every citation and number; `ars-red-team` checkpoint B
  attacks cherry-picking and uncited counter-evidence before the draft leaves the session.
- Never searches. A missing citation goes back to `ars-survey` and `export_citations`.
