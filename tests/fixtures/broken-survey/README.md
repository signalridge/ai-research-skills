# broken-survey fixture

Every defect here is deliberate. `tests/run_tests.py` asserts that `rs_validate` catches
each one; if a check regresses, this fixture stops failing and the test goes red.

| # | Defect | Caught by |
|---|---|---|
| 1 | `question` is a noun phrase, not interrogative | protocol check |
| 2 | `recall_modes.citation_chain` is empty | protocol check |
| 2b | `recall_modes.contrarian` absent entirely | protocol check |
| 3 | `counts.adjudicated` far below `deduped` | coverage warning |
| 4 | include has no `claim` | corpus check |
| 5 | exclude has no `exclude_reason` | corpus check |
| 6 | `coverage.yml` axes drifted from `protocol.yml` | coverage check |
| 7 | cell `unexplored` with no `trend_evidence` | coverage check |
| 8 | gap claims `confidence: high` on 2 queries, 1 venue-year, no nearest prior work | gaps check |
| 9 | `refs.bib` has entries and no provenance header | refs check |
| 10 | every include from a single recall mode | recall warning |
| 11 | `nearest_prior_work` omits `differing_axis` | schema check (structural layer only) |
