# Search log — retrieval-augmented-agents

Append-only. A search you cannot re-run is not a protocol.

| Date | Phase | Tool | Params | Results | Cost |
|---|---|---|---|---|---|
| 2026-07-20 | 0 | — | scope + axes declared before searching | — | — |
| 2026-07-20 | 1 | arxiv.search_papers | `ti:"multi-hop" AND abs:"retrieval augmented"`, cs.CL, n=50 | 50 | — |
| 2026-07-20 | 1 | openalex.search_entities | `"multi-hop" AND ("retrieval" OR "memory-augmented")`, per_page=100 | 100 | $0.001 |
| 2026-07-20 | 1 | openalex.get_citation_graph | seed W2626778328, cites, per_page=100 | 104 | $0.0001 |
| 2026-07-21 | 1 | openalex.search_entities | ICLR 2025-2026, title_and_abstract.search:retrieval | 58 | $0.001 |
| 2026-07-22 | 2 | — | scored 244 deduped candidates, threshold 6 | 4 above | — |
| 2026-07-25 | 4 | openalex.analyze_trends | group_by publication_year, RAG terms | 40 groups | $0.0001 |
| 2026-08-03 | 5 | — | round 3: 2 new pre-created on-topic (<5%) → frozen | — | — |

Notes:
- 2026-07-20: seed W2626778328 resolved via `openalex_resolve_name`; the arXiv DataCite
  DOI 404s against `/works/doi:`, so never pass it directly.
- 2026-07-25: trend buckets clamped to <= current year; a `2028` bucket was dropped as a
  publisher-date artifact.
