---
name: ars-verify
disable-model-invocation: true
description: >
  Perform a user-invoked check of citation, provenance, numeric, and source consistency in a user-supplied research
  draft or optional .research survey workspace. Resolve identifiers or inspect original
  sources when the user asks; report limits instead of fabricating or silently repairing
  evidence. Standalone and advisory.
---

# ars-verify — make evidence traceable

Use this skill for an explicit integrity check. It can inspect a draft, BibTeX file, corpus,
notes, links, or a named workspace. No completed survey, phase, profile, or output artifact is
required.

## Checks

1. **Citation chain:** every citation in the draft should map to a BibTeX entry or supplied
   source, and every key used in a BibTeX/corpus pair should be consistent.
2. **Provenance:** retain the stable identifier, source/tool, access or export date, and what
   was actually inspected. Treat an attestation as a useful record, not cryptographic proof.
3. **Numbers:** trace quoted values to a table, figure, page, log, or other precise location;
   check units, rounding, conditions, and whether a later version changed them.
4. **Source status:** distinguish preprint, published version, replication, retraction, and
   unresolved infrastructure failure. Do not delete a source because a resolver is temporarily
   unavailable.
5. **Absence claims:** report the search scope and date behind any claim about what does not
   exist. Provenance is a guideline, not a hidden workflow gate.

Resolve identifiers externally only when the user asks or provides an allowed source tool. A
missing identifier is an explicit limitation, not permission to guess by title.

## Evidence states and boundaries

With supplied evidence, report clean and inconsistent links precisely; with partial evidence, separate checked items from unresolved ones. With zero usable evidence, do not invent citations, numbers, or a deterministic sourced verification: report attempts, limits, and the smallest next check. Abstract-only material supports softened claims about what was verified. Ask only the smallest clarification when ambiguity materially changes the check. This skill never invokes another skill or creates or repairs a workspace automatically.

## Output

Return a concise table of clean items, critical inconsistencies, and follow-up actions. If the
user asks for a file, write `integrity-<date>.md` or the named path and do not overwrite an
existing report without confirmation. For LaTeX, compile and read the log; make edits to fix
reported errors only when the user explicitly asks or authorizes writing, rather than adding a
documentation-validation pipeline.
