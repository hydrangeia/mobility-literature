# Project status

Snapshot: 2026-10-13. Repository: `mobility-literature`.

## Completed v1 scope

The pipeline discovers metadata across five material classes through 45 bounded OpenAlex queries; enriches selected papers and one-hop citation/reference neighbors with Semantic Scholar; checks DOI/bibliographic metadata with Crossref; deduplicates DOI/provider identities while retaining provenance; screens electronic carrier mobility and tentative material families; and exports candidates, a numerical-evidence follow-up queue and a coverage report.

An explicit-path importer supports CSV, TSV, JSON, JSONL and Markdown/TXT extraction results. It retains raw fields, numerical expressions, carrier, method, temperature/direction, material/sample, conditions, quote/locator and source references. The current run integrates five existing extraction tables from user-designated workspaces and a bibliographic download inventory. Source file hashes are preserved.

The implementation includes cache expiry/refresh, bounded retries and Retry-After handling, per-query resume checkpoints, exact result caps, query-revision cache identities, structured request/run logs, and filename matching only in designated local or remote paper roots.

## Current result

17,235 candidates, 2,303 follow-up papers, 406 papers with confirmed numerical mobility, 4 papers carrying imported verified evidence, and 1,644 papers matched to a PDF path. See `V1_RUN_SUMMARY.md` for class counts, provider limits and interpretation.

## Collaboration

The coordinator owns integration, provider orchestration, evidence-state policy and coverage outputs. Parallel workers covered OpenAlex/reliability, legacy importer mappings, query/material screening, source-result inventory and scoped remote PDF discovery. Cursor Agent CLI/Grok was not available on this host, so no work was delegated through it.

## Next research work

Continue capped queries and citation expansion; resolve missing bibliographic identifiers; review tentative material assignments; and independently check numerical evidence against the original PDFs and SI. Provider throttling, missing units/carriers, OCR audit flags and overlapping corpus paths are reported as remaining gaps. These are research follow-ups beyond the completed runnable v1 setup.

## Research priority — 2026-10-14

Experimental mobility is now the primary target, with all five material classes progressing together. The first batch targets up to four original research papers per class, prioritizing existing PDF matches and explicit measurement-method cues. Experimental/theoretical labels and material membership are checked against the title and abstract before full-text review.

For each experimental observation, record the material and sample, measured quantity, carrier type, mobility expression and unit, measurement method, temperature, direction, device or sample conditions, and the supporting text with its page/table/figure/SI location. Multiple methods or sample conditions remain separate observations.

Full-text follow-up starts with existing local and remote PDFs, then uses publisher OA links, repository copies and Supporting Information. Additional DOI-based OA lookup, including Unpaywall, is a next-stage extension. Record the document version and source alongside each extracted observation; papers awaiting full text stay in the follow-up queue.
