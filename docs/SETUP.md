# Setup — search backends

The `ars-survey` skill routes across three backends (see [DESIGN.md §2.1](DESIGN.md)). This
file covers installing and verifying them, plus the failure modes each one has that produce
**confident wrong answers rather than errors**.

---

## 1. Installed

This section records the audited environment and gives a reproducible arXiv baseline. The
Tavily entry is intentionally provider/client-specific; it is optional and must not be
silently treated as verified evidence when unavailable.

| Backend | Status | Config |
|---|---|---|
| `arxiv-mcp-server` | already present; reviewed baseline 0.6.2 | user scope, `uv tool run --from arxiv-mcp-server==0.6.2 arxiv-mcp-server` |
| `tavily` | already present | user scope |
| **`openalex`** | **added 2026-08-03** | user scope, pinned `@cyanheads/openalex-mcp-server@0.7.8` |

Runtime baselines from the audited packages: OpenAlex MCP 0.7.8 requires Node ≥24 or Bun
≥1.3; arXiv MCP 0.6.2 requires Python ≥3.11. Optional `[pdf]` and `[pro]` extras are
separate from the core arXiv install.

For a fresh arXiv baseline, use the reviewed PyPI package and an explicit server name:

```bash
claude mcp add arxiv --scope user -- \
  uvx --from arxiv-mcp-server==0.6.2 arxiv-mcp-server
```

When LaTeX source is unavailable, replace the command with the optional local PDF fallback:

```bash
uvx --from 'arxiv-mcp-server[pdf]==0.6.2' arxiv-mcp-server
```

The `[pro]` extra is not required; it adds a heavier local semantic index. A configured
`markitdown-mcp` (`uvx markitdown-mcp`) is another optional PDF/Office/HTML fallback, not an
ARS package dependency.

The OpenAlex server was added with:

```bash
claude mcp add openalex --scope user -- npx -y @cyanheads/openalex-mcp-server@0.7.8
```

The audited existing arXiv entry may still resolve `uv tool run arxiv-mcp-server` without a
version constraint; use the explicit 0.6.2 command above when reproducing or reconfiguring it.
Do not silently treat an unpinned executable as the reviewed baseline.

Written to `~/.claude.json`. Version is **pinned** deliberately — an MCP server is a
software distribution channel, and `@latest` means an unreviewed upgrade lands silently.
Bump it consciously.

Verify the configured entries:

```bash
claude mcp list      # arxiv/openalex: … - ✔ Connected; Tavily if configured
```

For Tavily, use the provider's current MCP configuration and keep its API key in the
client's secret/env mechanism. This document does not pin a hosted transport that could
change independently of ARS.

Tools exposed: `openalex_resolve_name`, `openalex_search_entities`,
`openalex_analyze_trends`, `openalex_get_citation_graph`, `openalex_describe_fields`.

> Do **not** use the project's public hosted instance (`openalex.caseyjhand.com/mcp`).
> It works, but it routes every query through a third party. Local stdio costs nothing extra.

---

## 2. OpenAlex API key

An API key is **optional for ordinary OpenAlex requests**. A live REST smoke test on
2026-08-11 succeeded without a key, accepted `mailto`, and returned cost/budget headers.
The `/rate-limit` endpoint is different: the same no-key test returned **HTTP 401
Unauthorized**. Use a key when you need account/rate-limit inspection or the higher keyed
allowance; do not make it a hidden prerequisite for the core survey path.

`mailto` remains an optional courtesy identifier. It is not authentication, quota management,
or a replacement for `api_key`; do not claim that it unlocks a special pool.

### Get one

1. Create an account at <https://openalex.org>
2. Copy the key from <https://openalex.org/settings/api>

### Wire it in

Preferred — keep the key in your shell/secret manager, put only a reference in the config:

```bash
# in ~/.zshenv or your secret manager
export OPENALEX_API_KEY='your-key-here'
```

```bash
claude mcp remove openalex --scope user
claude mcp add openalex --scope user \
  --env OPENALEX_API_KEY='${OPENALEX_API_KEY}' \
  -- npx -y @cyanheads/openalex-mcp-server@0.7.8
```

Fallback if the `${VAR}` expansion does not resolve in your setup: substitute the literal key
only if you accept that it will sit in plaintext in `~/.claude.json`. An entry with no
`OPENALEX_API_KEY` remains valid but uses the anonymous allowance; inspect the actual client
configuration rather than assuming the keyed budget.

Confirm the key and endpoint status (the payload/headers, not a hardcoded daily number, are
the authority):

```bash
curl -i -s "https://api.openalex.org/rate-limit?api_key=$OPENALEX_API_KEY"
```

---

## 3. Budget

Cost is **per call, not per result**, but response headers remain authoritative. The current
schedule observed during this audit is: ID singleton **$0**, list/filter **$0.0001**,
keyword or semantic search **$0.001**, with a **$0.10/day anonymous** allowance and a
**$1/day keyed** allowance. Content download is separately metered; avoid it unless needed.

A nominal round of 20 keyword searches plus 200 list/filter calls is about **$0.04** under
that schedule, not a promise for every protocol. Record returned `meta.cost_usd` when
present, budget headers, query shape, server version and date.

| Operation | Current observed category |
|---|---|
| Singleton (get by OpenAlex ID, DOI, PMID…) | $0 in the current schedule |
| List + filter | $0.0001/call |
| Keyword or semantic search | $0.001/call; semantic page cap is smaller |
| Content download | separately metered; inspect response |

Three habits keep spend bounded:

1. **Use the largest legal page size.** `per_page: 100` is appropriate for keyword/exact/list
   and citation-graph calls. Semantic search is capped at **50** and is rate-limited to about
   one request per second; follow the tool schema rather than forcing 100.
2. **Resolve once, reuse the ID.** Cache the `W…` id in `corpus.jsonl.openalex_id`; later
   singleton/graph operations can avoid another search.
3. **Watch the meter.** Record spend in `protocol.yml.budget`. A sweep that dies on a 429
   halfway through has corrupted its own saturation count.

---

## 4. Verified failure modes

These are failure modes reproduced against the live API (the identifier/graph probes ran on
2026-08-03; key/budget behavior was rechecked on 2026-08-11). Response counts are snapshots,
not current catalog facts. Each mode can produce a wrong or empty answer that **looks like a
real answer** unless you check.

### 4.1 arXiv DOIs do not resolve

```
/works/doi:10.48550/arXiv.1706.03762  →  404
```

The arXiv DataCite DOI is not the identifier OpenAlex indexes the work under. `resolve_name`
first, always. The MCP server catches this correctly — it validates the seed with a singleton
lookup before walking a citation graph, and returns a `NotFound` with a recovery hint rather
than an empty edge list. The raw REST API does not protect you here.

### 4.2 Titles are not identifiers

`resolve_name("Attention Is All You Need", entity_type=works)` returns **six** distinct works:

| OpenAlex ID | Citations | What it is |
|---|---|---|
| `W2626778328` | 6,599 | the Vaswani et al. paper |
| `W4415754031` | 5 | a book chapter by Bishop & Seiberth |
| `W6906434615` | 1 | an unrelated piece by Krönke |
| `W7124757452` … | 0 | Zenodo uploads reusing the title |

Disambiguate by **citation count + author**, never by title match alone. This is exactly the
failure `resolve_name` exists to prevent, so use it — do not pass a title into a filter.

### 4.3 You cannot guess IDs

A plausible-looking `W2963403868` → 404. OpenAlex IDs are opaque. Every ID in
`corpus.jsonl` must come from a resolve call, never from the model.

### 4.4 Citation counts are not comparable across sources

The probe reported 6,599 OpenAlex citations for *Attention Is All You Need* while Google
Scholar reported six figures. These are snapshots from different corpora, not stable current
counts; OpenAlex can also split a work across records. **Never mix citation counts from two
sources in one table**, and never use an absolute count as a quality threshold — use it only
to rank within the same OpenAlex response.

### 4.5 The year histogram contains future dates

A prior `analyze_trends` probe returned at least one future-dated year bucket. Records carry
publisher-declared dates that can be wrong or forward-dated. Clamp to `<= current year`
before computing a growth baseline, and store the raw response with the protocol if the
series matters. The current year is always partial; do not compare its count directly with a
complete prior year. This matters for [DESIGN.md rule 5](DESIGN.md#5-the-seventeen-rules-and-the-failure-each-one-traces-to): trend growth sizes the watch interval, not the saturation stop rule.

### 4.6 Deprecated fields still appear in old guides

| Don't use | Use |
|---|---|
| `host_venue`, `alternate_host_venues` | `primary_location`, `locations` |
| `concepts`, `x_concepts` | `topics` |
| `grants` | `funders` / `awards` |
| `has_ngrams` | `has_fulltext` |
| `mailto=` | optional courtesy metadata; not authentication |
| `api_key=` | account/rate-limit authentication when required |

`openalex_describe_fields` returns the currently valid field names for an entity type — call
it before constructing a filter rather than trusting a remembered schema.

---

## 5. Division of labour

Not interchangeable. Each backend has one job it is genuinely best at:

| Need | Backend |
|---|---|
| AI/ML keyword discovery, preprints | `arxiv.search_papers` |
| Read a named section without downloading a paper | `arxiv.get_paper_latex_section` |
| **BibTeX** | Prefer `arxiv.export_citations`; add strict per-entry `rs-provenance` (key/id/tool/date). This is not cryptographic proof; `ars-verify` resolves identifiers externally. |
| Standing subscription | `arxiv.watch_topic` / `check_alerts` |
| Citation graph at scale, cursor-paginated | `openalex.get_citation_graph` |
| **Coverage matrix / field growth baseline** | `openalex.analyze_trends` |
| Anything → an ID | `openalex.resolve_name` |
| Non-arXiv venues, workshop sites, blogs | `tavily.search` |
| HF Papers feed, model/dataset cards | `tavily.search` with `site:huggingface.co`, or fetch the page directly |

**Prefer LaTeX or HTML when it is complete, but do not assume it exists.** For arXiv papers,
try `get_paper_latex_section` first. If source is missing, use the arXiv MCP's optional
`[pdf]` extra (`download_paper`/`read_paper`, HTML first), then a configured local
`markitdown-mcp` or another pinned parser for proceedings-only, image-only or malformed PDFs.
Record the parser/version and what was visually checked. No universal document parser 01-versus-document parser 02
quality claim is established here.
