# V1 implementation plan

## 1. Scope and order

1. Discover candidate papers across all five materials classes.
2. Enrich DOI/title/abstract/year/venue/citation metadata and bounded citation neighbors.
3. Deduplicate while retaining identifiers and source provenance.
4. Apply transparent screening rules and assign evidence states without guessing values.
5. Export the candidate table, a follow-up queue, and a coverage report.
6. Import existing mobility extraction results into a separate normalized destination.

Full-text acquisition, automatic PDF extraction, a database UI, and LLM-based numeric extraction are outside v1.

## 2. Pipeline components

```text
query families
  └─ OpenAlex search (cursor paging, cache, checkpoints)
       └─ normalize and deduplicate
            ├─ Semantic Scholar metadata + bounded references/citations
            ├─ Crossref DOI/title validation
            └─ transparent title/abstract screening
                 ├─ data/candidate_papers.csv
                 ├─ data/priority_missing_papers.csv
                 └─ reports/coverage_report.md

existing extraction outputs (read-only)
  └─ importer ──> data/imported/normalized_mobility_import.csv
```

Citation expansion is seeded from high-priority candidates or papers supplied by the user, limited by a configurable hop count and per-seed result cap, and deduplicated before enrichment. It is not an unrestricted crawl.

## 3. Search design

Each material class gets multiple query families combining class names/aliases with carrier mobility, charge transport, and method terms. Search both experimental vocabulary (FET/OFET, Hall, time-of-flight, SCLC, TRMC where applicable) and theoretical vocabulary (deformation potential, BTE/Boltzmann, electron-phonon, Fröhlich/polaron, Marcus hopping, kinetic Monte Carlo).

Do not require the word `mobility` in every query: some records describe charge transport or report a mobility under notation such as μ. Keep query provenance on each result so recall can be compared by query family. `QUERY_STRATEGY.md` contains the initial terms and exclusions.

### False-positive policy

- Exclude proton/ion/vacancy mobility and ionic conduction from electronic-carrier evidence.
- Exclude conductivity-only records unless a distinct electronic mobility is explicitly reported.
- Exclude diffusion coefficients unless a source explicitly converts them to electronic carrier mobility with stated assumptions and units; retain the conversion as a separate evidence record for review.
- Exclude gas diffusion and molecular diffusion.
- Do not infer that a paper has a number from title, abstract, model name, or a high citation count.

## 4. Record schema

Every candidate row should retain:

- stable local `paper_id`, DOI (normalized), provider IDs, canonical title, year, venue, authors, abstract, landing URL;
- material class and query/source provenance;
- publication type, citation count, OA metadata if returned by a provider;
- `screening_state`, `screening_reason`, `screening_confidence`, and an `excluded_measure` note when applicable;
- mobility observations as separate rows/fields: value, unit, electron/hole/ambipolar, experiment/theory, method, temperature, direction, material/sample, and conditions;
- evidence quote or exact source text and page/table/figure/SI location;
- local PDF match state (`not_checked`, `matched`, `not_found_in_scanned_roots`) plus scanned root and timestamp;
- provider timestamps, fetch errors, and raw-source references.

Missing numeric/evidence fields stay blank/null. The importer preserves source values and raw text alongside normalized values; it does not synthesize a measurement.

## 5. Deduplication and conflict handling

1. Normalize DOI case and remove DOI URL/prefix wrappers.
2. Merge identical DOI records.
3. Without DOI, merge by stable provider ID or normalized title + year + first author. Retain unresolved title matches as separate records and flag them for manual duplicate review when those identifiers are unavailable.
4. Preserve every provider ID and query provenance.
5. Prefer DOI-resolved Crossref fields for bibliographic validation, while retaining disagreements and original provider values for review.
6. Never overwrite imported source files. Export updates should merge idempotently and use a temporary file plus atomic replace.

## 6. Reliability and credentials

- `OPENALEX_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, and `CROSSREF_MAILTO` are read from environment variables. No secret is committed, printed, put in a cache key, or written to logs.
- Cache provider responses by canonical request with secrets removed; record retrieval time and provider.
- Retry transient connection/5xx/429 responses with bounded exponential backoff and respect `Retry-After` when present.
- Save OpenAlex cursor state after each page and resume on restart. Keep per-query checkpoints separate.
- Emit one structured event per request/error/run summary with provider, query ID, status, retry count, and elapsed time; do not include credentials.
- Keep a user-agent/contact value configurable and honor provider rate limits.

OpenAlex supports cursor paging beyond its basic 10,000-result page limit and recommends bounded, selective retrieval rather than downloading the full corpus ([OpenAlex paging](https://help.openalex.org/api/paging/)). OpenAlex accepts API keys via bearer authorization or the `api_key` parameter; use the header to avoid putting secrets in URLs ([OpenAlex authentication](https://help.openalex.org/api/authentication/)). Crossref recommends the polite pool, response caching, a descriptive user agent, and backoff after rate limits ([Crossref REST API access](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)). Semantic Scholar's official Academic Graph API documents paper search and citation/reference endpoints ([Semantic Scholar API](https://api.semanticscholar.org/api-docs/)).

## 7. Output behavior

- `candidate_papers.csv`: one row per deduplicated paper. The project pipeline owns this export; manual and imported evidence is kept in separate inputs and merged only through explicit import.
- `priority_missing_papers.csv`: likely/high-priority candidates lacking confirmed numeric mobility evidence in the currently imported records. It is a follow-up queue, not proof that the user has no PDF elsewhere.
- `coverage_report.md`: counts by material class, query family, provider, screening state, mobility evidence state, and local-match state. Report zero/unknown separately from not scanned.
- `data/cache`, `data/checkpoints`, and `data/raw_metadata`: reproducibility and resume state; none are source PDFs.

## 8. Milestones

### M1 — Inventory and contract

Complete: the target folder was inventoried, the record/output contract was documented, and credentials are read only from the environment.

### M2 — Minimal runnable discovery

Implemented: OpenAlex queries, resilient paging/checkpoints, normalization/deduplication, candidate and priority exports, and report generation. The first bounded API run is complete across 45 queries; caches and final exports are present and audited.

### M3 — Enrichment and importer

Implemented: optional Semantic Scholar metadata/citation expansion, Crossref DOI checks, and an explicit-path importer that leaves source files untouched and refuses to replace an existing import output.

### M4 — Scoped corpus matching

Complete for the user-designated local paper folder and six remote paper roots, using filename inventories. Inventory only those supplied roots, match filenames/DOIs against candidates, and populate local-match state. Do not traverse entire disks or servers.

### M5 — Coverage review

Complete: bounded discovery ran across all five classes, existing extraction results were integrated, and the coverage report and follow-up queue record outstanding class, access and evidence gaps. Independent source rereading remains a research follow-up.
