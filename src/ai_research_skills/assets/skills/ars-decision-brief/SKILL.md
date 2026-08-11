---
name: ars-decision-brief
description: >
  Turn a completed survey into a build/adopt/skip engineering decision — a claim-to-evidence
  matrix weighted by reproducibility rather than venue prestige. Use when the user asks
  whether to adopt a technique, whether an approach is production-ready, what the evidence
  says before building something, or wants a technical decision brief from the literature.
  Requires a completed survey; reads .research/survey/<slug>/ and never searches on its own.
disallowed-tools:
  # This exit is a pure function of survey state. The "never search here" rule in the
  # body is advisory; this makes it structural. A missing paper goes back to `ars-survey`.
  # Server names follow SETUP.md; a differently-named server silently escapes the
  # restriction, so the prose rule stays as the backstop.
  - WebSearch
  - WebFetch
  - mcp__tavily
  - mcp__arxiv
  - mcp__arxiv-mcp-server  # legacy registration name
  - mcp__openalex
---

# decision-brief — evidence for an engineering call

Not a paper section. The question is not *what does the literature say* but **what would I
be betting on, and what breaks if it is wrong?**

## Preconditions

`protocol.yml` at `phase >= 3`, includes carrying `claim`, `code`, and `numbers`.

**Never search here.** This is a read-only projection of survey state; it must not append
corpus records or mutate protocol/coverage/gaps. Missing evidence goes back to `ars-survey`.

Ask the user for the decision context first — what they are building, what the alternative
is, what the cost of being wrong is. A brief written without it answers a question nobody
asked.

---

## The inversion

Academic ranking and engineering ranking are different orders, and this is the whole skill:

> **A reproduced arXiv preprint beats an unreproduced NeurIPS oral.**

Venue prestige is a proxy for novelty and rigour of argument. Neither is what you need. You
need *will this work in my system*, and the strongest available evidence for that is
somebody having run it.

Weight in this order:

1. `code.runs: verified` — someone ran it and got the number
2. `code.status: official` with a maintained repo
3. Independent replication in another paper in the corpus
4. Peer review
5. Citation count — weakest. Popular ≠ reproducible.

## The matrix

One row per claim you would actually rely on. Not one row per paper.

```markdown
| Claim | Support | Depth | Maturity | Code | Risk if wrong | Verdict |
|---|---|---|---|---|---|---|
| Iterative retrieval beats 128k long-context on 2-hop QA | sample2025iterative, sample2025longcontext | full, i+m+r | ICLR 2026, NeurIPS 2025 | official, **verified** | Latency budget blown for no accuracy gain | **adopt** |
| The gain holds above 64k context | sample2025iterative §5.2 | full | preprint v2 | official, unverified | Design assumption fails at our context size | **skip — revisit if replicated** |
| Retrieval recall is the binding constraint | *(no direct support)* | — | — | — | Whole architecture premised on an untested claim | **skip — this is a gap, not a finding** |
```

Columns that do work:

- **Depth** — `evidence_read` per supporting record. A claim supported only by
  `abstract`-level records is not supported.
- **Code** — `status` + `runs`, verbatim.
- **Risk if wrong** — the concrete failure in *their* system. "Reduced accuracy" is not a
  risk; "we ship a 3× slower pipeline for a gain that does not exist at our context length"
  is.

### Rows with no support

The most valuable row in the table is often the one with an empty Support column: a claim
the design depends on that **nobody has established**. Cross-reference `gaps.yml` — if it
matches a gap, say so. That is a research risk sitting inside an engineering plan, and it
is exactly what a literature survey is for.

## Verdicts

| Verdict | Means |
|---|---|
| `build` | Evidence supports it, no off-the-shelf option — implement |
| `adopt` | Evidence supports it and something exists — use that |
| `skip` | Evidence does not support it, or the risk exceeds the gain |
| `revisit after <trigger>` | Not decidable yet. **Name the trigger.** |

`revisit` must be falsifiable and watchable: "revisit if an independent replication at
≥64k context appears." Record that proposed trigger in `brief.md` and hand it back to
`ars-survey`, which may register it in `gaps.yml` as a `closes_if`. Once registered,
`ars-watch` tests it automatically. This is how an engineering decision stays connected
to the literature instead of being re-litigated from memory in six months.

## Output

Write `.research/survey/<slug>/brief.md`:

```markdown
# Decision brief — <question>
Survey <slug> · corpus frozen <date> · <n> includes · brief generated <date>

## Recommendation
<2–3 sentences. The call, and the single biggest uncertainty.>

## Evidence matrix
<the table>

## What we would be betting on
<the claims with weakest support that the design still depends on>

## What to watch
<proposed triggers; `ars-survey` registers accepted ones in `gaps.yml` as `closes_if`>

## Coverage and limits
<adjudicated vs retrieved; evidence_read distribution; what the survey did not cover>
```

Lead with the recommendation. This document gets read in five minutes by someone deciding.

Unlike `ars-gap-gate`, **do** make a recommendation here — an engineering call is reversible,
bounded, and yours to advise on. But state the uncertainty in the same breath, and make the
evidence auditable underneath it.

## Handoffs

- **Upstream:** reads `corpus.jsonl` and `gaps.yml` — claims, code status, sourced numbers
  and existing gaps — written by `ars-survey`.
- **Writes:** `brief.md` only — the claim→evidence matrix and proposed revisit triggers. It
  is a read-only projection and never edits the source ledgers or performs discovery.
- **Downstream:** proposed triggers go back to `ars-survey` for registration; after that,
  `ars-watch` tests the registered `closes_if`. `ars-verify` checks that every number in
  the matrix traces to a table.
- Never searches. Missing evidence goes back to `ars-survey`.
