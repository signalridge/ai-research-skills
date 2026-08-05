# Setup — search backends

The `ars-survey` skill routes across three backends (see [DESIGN.md §2.1](DESIGN.md)). This
file covers installing and verifying them, plus the failure modes each one has that produce
**confident wrong answers rather than errors**.

---

## 1. Installed

| Backend | Status | Config |
|---|---|---|
| `arxiv-mcp-server` | already present | user scope, `uv tool run arxiv-mcp-server` |
| `tavily` | already present | user scope |
| **`openalex`** | **added 2026-08-03** | user scope, pinned `@cyanheads/openalex-mcp-server@0.7.8` |

The OpenAlex server was added with:

```bash
claude mcp add openalex --scope user -- npx -y @cyanheads/openalex-mcp-server@0.7.8
```

Written to `~/.claude.json`. Version is **pinned** deliberately — an MCP server is a
software distribution channel, and `@latest` means an unreviewed upgrade lands silently.
Bump it consciously.

Verify:

```bash
claude mcp list      # openalex: … - ✔ Connected
```

Tools exposed: `openalex_resolve_name`, `openalex_search_entities`,
`openalex_analyze_trends`, `openalex_get_citation_graph`, `openalex_describe_fields`.

> Do **not** use the project's public hosted instance (`openalex.caseyjhand.com/mcp`).
> It works, but it routes every query through a third party. Local stdio costs nothing extra.

---

## 2. OpenAlex API key

**As of 2026-02-13 OpenAlex requires an API key.** The old `mailto=` polite pool is gone —
the parameter is now *silently ignored*, so any guide (or MCP server README) still
recommending it is stale. Most OpenAlex MCP servers on GitHub still document `mailto`;
that is why this one was chosen.

The server works **without** a key right now, at the $0.10/day anonymous allowance — enough
for testing, not enough for a survey sweep. A free key raises that 10×.

### Get one

1. Create a free account at <https://openalex.org> (~30 seconds)
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

Fallback if the `${VAR}` expansion doesn't resolve in your setup, substitute the literal key
— but note it then sits in plaintext in `~/.claude.json`.

Confirm the key is live:

```bash
curl -s "https://api.openalex.org/rate-limit?api_key=$OPENALEX_API_KEY" | python3 -m json.tool
# daily_budget_usd should read 1, not 0.1
```

---

## 3. Budget

Cost is **per call, not per result**.

| Operation | Cost / 1,000 calls |
|---|---|
| Singleton (get by OpenAlex ID, DOI, PMID…) | **free** |
| List + filter | $0.10 |
| Keyword search | $1 |
| Semantic search | $1 |
| Content download (cached PDF) | $10 |

Free allowance: **$1/day with a key**, $0.10/day without. A full survey round (~20 searches
plus a few hundred list/graph calls) runs about **$0.04**.

Three habits keep it that way:

1. **Always `per_page: 100`.** Paginating at the default 25 costs 4× for identical data.
2. **Resolve once, reuse the ID.** Singletons are free; search is the priciest call. Cache
   the `W…` id in `corpus.jsonl.openalex_id` and every later touch is free.
3. **Watch the meter.** Every tool call reports what it spent and what remains. Record it in
   `protocol.yml.budget` — a sweep that dies on a 429 halfway through has corrupted its own
   saturation count.

Every API response also carries `meta.cost_usd` if you're calling the REST API directly.

---

## 4. Verified failure modes

These were reproduced against the live API on 2026-08-03. Each one produces a wrong or empty
answer that **looks like a real answer** unless you check.

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

OpenAlex reports 6,599 citations for *Attention Is All You Need*; Google Scholar reports
six figures. Different corpora, different counting, and OpenAlex sometimes splits a work
across records. **Never mix citation counts from two sources in one table**, and never use
an absolute count as a quality threshold — use it only to rank within OpenAlex.

### 4.5 The year histogram contains future dates

`analyze_trends` grouped by `publication_year` on a live topic returned a `2028: 2` bucket.
Records carry publisher-declared dates that can be wrong or forward-dated. Clamp to
`<= current year` before computing a growth baseline.

Also: the current year is always **partial**. The same query gave
`2023: 323 → 2024: 3,236 → 2025: 9,915 → 2026: 14,086`, and 2026 was only two-thirds
elapsed — so the real growth rate is *understated*, not overstated. This matters for
[DESIGN.md rule 5](DESIGN.md#5-the-seventeen-rules-and-the-failure-each-one-traces-to): in a
field tripling annually, "<5% new results this round" is stasis, not saturation.

### 4.6 Deprecated fields still appear in old guides

| Don't use | Use |
|---|---|
| `host_venue`, `alternate_host_venues` | `primary_location`, `locations` |
| `concepts`, `x_concepts` | `topics` |
| `grants` | `funders` / `awards` |
| `has_ngrams` | `has_fulltext` |
| `mailto=` | `api_key=` |

`openalex_describe_fields` returns the currently valid field names for an entity type — call
it before constructing a filter rather than trusting a remembered schema.

---

## 5. Division of labour

Not interchangeable. Each backend has one job it is genuinely best at:

| Need | Backend |
|---|---|
| AI/ML keyword discovery, preprints | `arxiv.search_papers` |
| Read a named section without downloading a paper | `arxiv.get_paper_latex_section` |
| **BibTeX** | `arxiv.export_citations` — **the only** permitted source |
| Standing subscription | `arxiv.watch_topic` / `check_alerts` |
| Citation graph at scale, cursor-paginated | `openalex.get_citation_graph` |
| **Coverage matrix / field growth baseline** | `openalex.analyze_trends` |
| Anything → an ID | `openalex.resolve_name` |
| Non-arXiv venues, workshop sites, blogs | `tavily.search` |
| HF Papers feed, model/dataset cards | `tavily.search` with `site:huggingface.co`, or fetch the page directly |

**Never parse a PDF when LaTeX or HTML exists.** For arXiv-dominated work this removes the
need for a document-parsing layer entirely. If you do hit a proceedings-only PDF: document parser 01 is
strong on tables (table-extraction component TEDS >91%) and weak on maths (<70% BLEU on complex equations,
against document parser 02's >90%) — pick by what the paper's content actually is.
