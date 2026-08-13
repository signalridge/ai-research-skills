# broken-survey fixture

This optional workspace deliberately contains structural/evidence defects for the scoped
linter. The fixture is expected to fail without requiring a complete research lifecycle.

It includes malformed or incomplete records, duplicate/unknown references, a map that names
missing coordinates, an invalid gap reference, and a BibTeX entry without explicit provenance.
The linter should report the present defects while allowing unrelated artifacts to be absent.
