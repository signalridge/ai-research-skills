# broken-survey fixture

An optional workspace that deliberately fails the scoped linter, used to prove the checks
still fire. It is incomplete on purpose: the linter must report the defects that are present
without demanding a complete research lifecycle.

The defects below are asserted individually by
`test_broken_fixture_reports_every_claimed_defect` in `tests/run_tests.py`, in both the
installed-dependency and bare-interpreter paths. Listing them here is not enough on its own —
this file once advertised five defect classes while the linter detected one, and the CI step
that only asks "does the fixture fail?" stayed green throughout. Change the fixture and you
must change that test.

| Artifact | Defect |
|---|---|
| `corpus.jsonl[4]` | `relevance` is a string, not an integer (schema) |
| `corpus.jsonl[4]` | `screen` is outside the enum (schema) |
| `corpus.jsonl` | `beta2025noreason` is used as the key of two records |
| `corpus.jsonl` | one identifier claimed by two records, moved between `id` and `openalex_id` |
| `corpus.jsonl[4]` | `corroboration.agrees_with` names a key that is not in the corpus |
| `gaps.yml[G1]` | `nearest_prior_work` names a key that is not in the corpus |
| `coverage.yml.cells[2]` | `revivable_by` names a key that is not in the corpus |
| `coverage.yml.cells[3]` | duplicates the coordinate of `cells[0]` |
| `coverage.yml.cells[3]` | an occupant names a key that is not in the corpus |
| `coverage.yml.cells[3]` | `gap_id: G9` names a gap that `gaps.yml` does not define |
| `refs.bib` | the last entry is truncated and never closed |
| `refs.bib` | a provenance attestation names an entry that does not exist |
| `refs.bib` | one complete entry has no corpus record |
| `refs.bib` | two complete entries have no provenance attestation (warning, not error) |

Total: 13 errors, 2 warnings.
