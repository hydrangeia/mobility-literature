# Mobility literature discovery

[English](README.md) | [简体中文](README.zh-CN.md)

This project builds a traceable discovery and data-completion pipeline for carrier mobility papers across five materials classes: COFs, MOFs, organic small-molecule/molecular semiconductors, hybrid perovskites, and inorganic 2D materials.

The first release covers literature discovery, metadata enrichment, deduplication, PDF matching, and import of existing mobility extraction results. See the [v1 run summary](V1_RUN_SUMMARY.md) for the current dataset and follow-up priorities.

Install the command from the project directory with `python -m pip install -e .`.

## Outputs

- `data/candidate_papers.csv` — deduplicated metadata candidates and screening state.
- `data/priority_missing_papers.csv` — papers that need full-text/data follow-up, with local-PDF match state kept explicit.
- `reports/coverage_report.md` — counts and coverage gaps by material class, provider, and evidence state.
- `data/imported/` — normalized copies of legacy extraction records; source files remain untouched.
- `data/cache/` and `data/checkpoints/` — provider response cache and resumable progress.

## Quick start

Python 3.10+ is sufficient; the first release uses the standard library. Set optional credentials in the process environment:

```powershell
$env:OPENALEX_API_KEY = "..."
$env:SEMANTIC_SCHOLAR_API_KEY = "..."
$env:CROSSREF_MAILTO = "you@example.org"
python -m pip install -e .
python -m mobility_literature discover
```

OpenAlex discovery can run without a key at a lower request budget. Semantic Scholar enrichment is optional when its key is absent. Crossref is queried politely with `CROSSREF_MAILTO` when supplied. Credentials are never written to project files, logs, or cache keys.

The initial `discover` command uses bounded query groups and caches pages. Re-running it resumes incomplete OpenAlex cursors and merges new metadata into the current candidate export by DOI, then by normalized title/year/first author.

Optional local inputs are explicit paths:

```powershell
mobility-literature import "path/to/extracted-results.csv" --output data/imported/normalized.csv
mobility-literature discover --max-results-per-query 100 --inventory "path/to/download-inventory.csv" --pdf-root "path/to/papers"
```

`--pdf-root` can be repeated. It matches PDF filenames to DOI/title metadata inside the designated folders, and records the checked roots, matching basis and timestamp. A filename match does not verify a numerical measurement. `not_found_in_scanned_roots` only refers to those folders.

Normalized imports in `data/imported/` are revalidated and merged automatically. For other destinations, supply `--imports file1.csv file2.jsonl`. Unmatched imported papers become candidates with their original source references. Multiple measurements of one paper remain separate observations. Existing import outputs are never replaced.

To rebuild exports from existing metadata without network calls, use `discover --max-results-per-query 0 --enrich-limit 0 --crossref-limit 0`. Discovery response history is retained; larger limits continue the cursors. Query revisions use a new cache identity. Semantic Scholar/Crossref response caches expire after seven days, or can be refreshed with `--refresh-enrichment`.

Run the regression checks with `python -m unittest discover -s tests -v`. They cover evidence promotion/exclusions, import persistence, duplicate bridges, exact result caps, query revision, partial cache recovery, null citation responses, and filename matching.

Audit generated output with `python scripts/audit_outputs.py --root .`. Optional `--source-manifest path/to/hash-manifest.json` checks the original extraction file hashes as well. The audit compares observations to retained raw source snapshots and reconciles candidate, priority and coverage counts.

## Evidence states

`candidate` → `likely_contains_mobility` → `confirmed_numeric_mobility` → `verified_evidence` track the available evidence. A paper reaches `confirmed_numeric_mobility` when a numerical electron/hole/ambipolar mobility value with unit is explicitly found. `verified_evidence` additionally requires a traceable source location and a reviewed value/context.

Conductivity, ionic/proton mobility, diffusion coefficients, and gas diffusion are not electronic carrier mobility. They may be retained as exclusion notes but cannot advance a record's mobility state.

Material classification is also a screening result. Explicit metadata cues, tentative query families, and ambiguous/mixed signals are retained separately. Broad halide-perovskite queries can retrieve all-inorganic materials, which are excluded from the hybrid class when that composition is explicit. The report distinguishes tentative class counts from metadata-supported counts and reports enrichment failures separately from empty database results.

## Existing assets

See `PROJECT_STATUS.md` for implementation status, `IMPLEMENTATION_PLAN.md` for the data contract, and `V1_RUN_SUMMARY.md` for the bounded discovery run and remaining evidence gaps. Source papers, extraction tables, private paths, response caches and generated data exports remain local.
