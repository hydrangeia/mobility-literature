# V1 run summary

Snapshot: 2026-10-13. Discovery was bounded to 100 results per query, across 45 query families covering COF, MOF, organic molecular semiconductors, hybrid perovskites and inorganic 2D materials.

## Current outputs

- Deduplicated paper candidates: **17,235**.
- Papers requiring numerical evidence completion or extraction review: **2,303**.
- Papers with confirmed numerical mobility: **406**.
- Papers with imported verified evidence: **4**.
- Existing normalized extraction records checked: **2,144**, from five read-only source tables.
- Candidates with a PDF filename/path match in the designated local or remote roots: **1,644**.

## Provider coverage

| Source | Candidate records carrying provenance |
|---|---:|
| crossref | 25 |
| legacy_import | 645 |
| local_inventory | 13,896 |
| openalex | 3,480 |
| semantic_scholar | 13 |

Provider counts overlap after deduplication. The local inventory contributes bibliographic candidates, not numerical mobility observations. OpenAlex completed all 45 bounded searches without a query failure; **5** reached the end of their result sets, while **40** remain capped and can continue from saved cursors.

The live Semantic Scholar pass enriched 3 of 5 seeds and added 10 citation/reference neighbors. The anonymous API exhausted retries for 5 requests. Crossref successfully checked 25 records. Later rebuilds used the existing caches and performed no further enrichment requests.

## Counts by screened material class

| Material class | Candidates | Metadata-supported class | Likely or stronger mobility | Confirmed numeric | Verified evidence | PDF matched | Local match checked |
|---|---:|---:|---:|---:|---:|---:|---:|
| COF | 695 | 409 | 108 | 13 | 0 | 55 | 695 |
| MOF | 1085 | 547 | 91 | 29 | 0 | 129 | 1085 |
| organic_small_molecule | 8796 | 1132 | 1233 | 129 | 1 | 563 | 8796 |
| hybrid_perovskite | 5206 | 1019 | 438 | 23 | 1 | 496 | 5206 |
| inorganic_2d | 1142 | 592 | 639 | 152 | 2 | 323 | 1142 |
| unassigned | 448 | 0 | 102 | 63 | 0 | 98 | 448 |

Class counts can overlap. A tentative query family is not proof of a material's membership; metadata-supported counts require explicit class cues without ambiguous or mixed signals. Older organic inventories can include polymers, and 2D searches can retrieve electron-gas heterostructures rather than atomically thin materials. These remain review candidates.

## Evidence interpretation and remaining gaps

Confirmed numerical evidence requires an explicitly selected electronic carrier mobility value and compatible voltage/time units. Conductivity, ionic/proton mobility and diffusion cannot promote a record. Unspecified/exciton carriers, missing units, OCR/exponent-inference audit flags, or insufficient source context are retained for review. Missing information is left blank.

Imported verified evidence requires a source-declared checked state, a quote that contains the selected numerical expression, and a precise page/table/figure/SI locator. Its `verification_origin` is `legacy_source_declared`; this run has not independently reread every source PDF. Before using a value in a final research dataset, check the cited original source and its measurement/calculation conditions.

The designated local inventory contained 1,663 PDF files. The remote filename manifest contained 3,796 paths in six paper roots; two COF roots may overlap. Filename/path matches establish availability, not PDF content or unique publications. No whole-disk/server scan or source-file modification was performed.

Literature coverage remains incomplete at the per-query cap and the small citation-expansion budget. A missing DOI, abstract, file match or API response is an explicit gap, not proof that a paper or mobility value does not exist. No API keys were configured for the initial run. Keys can be supplied through environment variables to improve future provider access.

## Verification

The regression suite passes 17 tests covering exclusions, import state validation, source preservation, evidence persistence, rescreening, DOI/provider deduplication, query revisions, result caps, truncated cache recovery, real legacy headers, null citation lists and PDF matching. The package builds as a wheel and the installed command launches successfully in an isolated target directory.

The output audit checks all paper IDs/DOIs for duplicates, reconciles the priority queue and every class count, verifies every observation against its normalized source snapshot, and confirms the SHA-256 hashes of all five original extraction tables remain unchanged. It passes on the current dataset. Source tables, PDF paths, quotes and generated data exports remain local; the public repository contains code and aggregate summaries.
