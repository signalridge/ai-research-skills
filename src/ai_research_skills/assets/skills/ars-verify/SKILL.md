---
name: ars-verify
description: >
  Check citation and number integrity across a survey and anything drafted from it — every
  BibTeX entry attested and externally resolvable, every cited key present in the corpus, every
  quoted number traceable to a named table or figure, and preprint-versus-published drift
  flagged. Use when the user asks to check citations, verify references, confirm numbers,
  or audit a draft before submission.
disallowed-tools:
  # Verification may inspect only identifiers already present in state. Search, graph,
  # trend and alert tools remain denied; missing evidence goes back to ars-survey.
  - WebSearch
  - WebFetch
  - mcp__tavily
  - mcp__arxiv__search_papers
  - mcp__arxiv__semantic_search
  - mcp__arxiv__citation_graph
  - mcp__arxiv__watch_topic
  - mcp__arxiv__check_alerts
  - mcp__openalex__search_entities
  - mcp__openalex__analyze_trends
  - mcp__openalex__get_citation_graph
---

# verify — citations and numbers

Mechanical, deterministic, and the cheapest insurance in the suite. Fabricated citations
are the most common failure of LLM literature work; wrong numbers are the most damaging.

Scope: **integrity, not quality or discovery.** Resolve only a stable identifier already
present in the corpus (ID, DOI, PMID or PMCID); never turn a missing identifier into a title
search or citation-graph walk. If state lacks a resolvable identifier, route the gap back to
`ars-survey`; argument quality is `ars-red-team`'s job.

---

## 1. BibTeX provenance

Every `.bib` entry in scope must carry a strict `rs-provenance` attestation binding its
corpus key, stable identifier, tool and date. This is not cryptographic proof and cannot
establish which process wrote the bytes; external identifier lookup below is the real check.

```bash
head -3 .research/survey/<slug>/refs.bib     # expect an rs-provenance line
```

A `.bib` entry without a strict per-entry attestation is **critical**. A legacy file-level
marker may grandfather unchanged old entries only; it cannot authorise appended or modified
entries. This check is a defensive tripwire, not proof of tool origin — attestations can be
forged — so fix by regenerating and then resolving identifiers externally:

```
arxiv → export_citations(paper_ids: [...])
```

## 2. Every entry resolves

For each entry, confirm the work exists and the metadata matches:

```
arxiv → get_abstract(paper_id: "2503.01234")             # arXiv works
openalex → openalex_resolve_name(query: "10.1145/…")     # DOI works — singleton; record returned cost
```

Check title, first author, year, venue. Flag any mismatch. A title that is close but not
identical is the classic signature of a fabricated entry.

A failed resolution splits two ways, and the split decides the severity:

| Outcome | Meaning | Severity |
|---|---|---|
| `unresolved` | The resolver answered and the work is not there — a definite "not found" on a well-formed id | **critical** — fabrication signal |
| `unverifiable-now` | The resolver itself failed — unreachable, rate-limited, timed out | advisory — re-run when the backend recovers |

An infrastructure hiccup never deletes a real citation. `unverifiable-now` is not
fabrication evidence and must not be treated as such: report it, re-run later, and leave
the entry alone. Deleting or "fixing" a citation because a backend hiccuped is how real
references get destroyed.

> Do not resolve by title. Six distinct works share the title "Attention Is All You Need";
> only one is the transformer paper. Resolve by identifier, and if you must use a title,
> disambiguate on citation count and author.

## 3. Keys are consistent across three files

```
draft \cite{key}  →  refs.bib entry  →  corpus.jsonl record
```

All three must agree. This lookup is read-only; do not use it to add a new record. Missing
records go back to `ars-survey`. Report:

- **cited but not in corpus** — critical. The claim rests on a paper the survey never
  screened.
- **cited but not in refs.bib** — critical. Compilation breaks, or worse, silently does not.
- **in corpus, never cited** — informational. Often fine; occasionally a paper you meant to
  discuss.

## 4. Numbers trace to a location

Every figure quoted in a draft must map to a `numbers[]` entry with a `source` and
`looked_at: true`.

| Finding | Severity |
|---|---|
| Number in draft, no `numbers[]` entry | **critical** — untraceable |
| Entry exists, `looked_at: false` | **critical** — parsed out of text, never seen in the table |
| `source` too vague to locate (`"results section"`) | advisory — tighten to a table or figure number |

The risk is not misreading a table; it is reading the **wrong** table. That is why `source`
must name one.

## 5. Preprint versus published drift

For any record with both an arXiv id and a published venue, check whether the quoted number
survived review.

```
arxiv → get_paper_latex_section(paper_id: "…", section_id: "Experiments")
```

v1 numbers routinely differ from camera-ready. A draft quoting the preprint figure for a
now-published paper is a citation a reviewer will check. Flag every case, even when the
numbers match — knowing they match is worth recording.

## 6. Retractions and withdrawals

Check the OpenAlex record for `is_retracted`. Rare, but unrecoverable if missed.

---

## Output

Write `.research/survey/<slug>/integrity-<date>.md`:

```markdown
# Integrity check — <slug> — <date>
Scope: refs.bib (34 entries) · related_work.md (41 citations) · corpus.jsonl (61 includes)

## Critical (3)
1. `wang2024retrofit` cited in related_work.md §2 — **no corpus.jsonl record.** The claim
   at line 47 rests on a paper the survey never screened. Remove it or run it through
   `ars-survey` Phase 2–3.
2. "+8.1 EM" (related_work.md §3) — no `numbers[]` entry on `sample2025longcontext`.
3. `sample2025multi` — refs.bib says NeurIPS 2025; OpenAlex says the work is a 2025 arXiv
   preprint with no published location. Venue appears fabricated.

## Advisory (2)
4. `sample2025iterative` numbers taken from arXiv v1 (6.2 EM); ICLR camera-ready reports 5.8.
5. `sun2025iter` — source recorded as "results section"; name the table.

## Clean
- 31 of 34 entries resolved with matching metadata
- 38 of 41 citations traced end to end
- No retractions

## Verdict: 3 critical — do not submit
```

Be exact. A finding that does not name the file, the line, and the fix is not actionable.

## Handoffs

- **Upstream:** reads `refs.bib` (generated by `ars-survey` Phase 3), `corpus.jsonl`, and
  the drafts produced by `ars-related-work` and `ars-decision-brief`.
- **Writes:** `integrity.md`.
- **Downstream:** findings block delivery until resolved — the mechanical half of the
  audit pair. `ars-red-team` covers argument quality, which this deliberately does not.
