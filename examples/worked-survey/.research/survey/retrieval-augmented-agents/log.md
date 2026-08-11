# Search log — retrieval-augmented-agents

Append-only. A search you cannot re-run is not a protocol.

| Date | Phase | Tool | Params | Results | Cost |
|---|---|---|---|---|---|
| 2026-07-20 | 0 | — | scope + axes declared before searching | — | — |
| 2026-07-20 | 1 | keyword / arxiv.search_papers | `query=ti:"multi-hop" AND abs:"retrieval augmented"`, `categories=[cs.CL]`, `max_results=50` | 2 | — |
| 2026-07-20 | 1 | citation_chain / openalex.get_citation_graph | `seed_id=W2626778328`, `direction=cites`, `per_page=100` | 1 | — |
| 2026-07-20 | 1 | venue_author / openalex.search_entities | `entity_type=works`, `query=retrieval`, `publication_year=2025-2026` | 1 | — |
| 2026-07-20 | 1 | contrarian / arxiv.search_papers | `query=abs:"long context is sufficient"`, `categories=[cs.CL]`, `max_results=50` | 1 | — |
| 2026-07-22 | 2 | — | threshold 6 | deduped=5, 4 above | — |
| 2026-07-25 | 4 | openalex.analyze_trends | group_by publication_year, illustrative RAG terms | 40 groups | recorded fixture value $0.0001 |
| 2026-08-03 | 5 | — | round 3: 0 new on-topic synthetic records (<5%) → frozen | — | — |

Notes:
- 2026-07-20: seed W2626778328 resolved via `openalex_resolve_name`; the arXiv DataCite
  DOI 404s against `/works/doi:`, so never pass it directly.
- 2026-07-25: the fixture demonstrates clamping future-dated buckets; its `2028` example is
  synthetic and is not a live OpenAlex result.
