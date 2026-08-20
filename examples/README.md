# Worked example

`worked-survey/` is a synthetic optional `.research/survey/<slug>/` workspace. It shows how a
small corpus, source notes, a comparison map, gap notes, citations, and a search log can work
together. The files are interoperable evidence, not a required lifecycle.

The records and trend text are synthetic and deliberately use unmistakable citation keys. The
legacy `phase`, counts, recall, and saturation fields remain in the example to demonstrate that
new skills can read an older workspace without migrating it.

```bash
python3 src/ai_research_skills/assets/scripts/rs_validate.py \
  examples/worked-survey/.research/survey/retrieval-augmented-agents
```

The optional linter checks the artifacts that are present. It does not require every file,
complete a grid, count search modes, or declare a result ready.

This complete worked-survey directory is a compatibility sample for old and new readers, not
a required template or a completion target. The optional `search` status and locator fields may
be added independently; their absence does not mean that a search had no results. Reports keep
stable corpus keys and may use temporary display numbers without writing those numbers back to
records. Full, partial, and zero-evidence outputs should say what was actually checked; zero
evidence is not a reason to invent citations or numbers. Abstract-only records support only
an attributed, softened high-level direction or conclusion, not numeric results such as 4 points
or 20% unless a named page, table, figure, log, or section has been read and recorded.

## What to explore

- `protocol.yml` records the question, scope, query notes, and historical fields.
- `corpus.jsonl` contains included, excluded, and unresolved synthetic records with source
  identifiers, discovery provenance, evidence depth, and a disagreement.
- `coverage.yml` shows that a map can be partial and can label unknown areas honestly.
- `gaps.yml` records candidate gaps, nearby work, and falsifiers without making them automatic
  decisions.
- `refs.bib` and `notes/` show how citation keys and source reads can be carried forward.
- `log.md` records what the synthetic researcher searched and what the example cannot support.

Try composing the skills in any order: ask `ars-related-work` to draft from the corpus, ask
`ars-gap-gate` to assess one gap, ask `ars-red-team` to attack the disagreement, or ask
`ars-verify` to trace a citation. Missing or partial artifacts should be reported as limits,
not repaired automatically.
