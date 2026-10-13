from __future__ import annotations

import difflib
import json
import logging
import math
import re
import hashlib
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .classify import screen
from .config import Settings
from .http import JsonHttpClient
from .evidence import apply_local_imports, rescreen
from .corpus import load_inventory, match_local_pdfs, match_remote_manifest
from .materials import MATERIAL_CLASSES, screen_material
from .normalize import merge_records, normalize_doi, normalize_title
from .providers.crossref import Crossref
from .providers.openalex import OpenAlexClient
from .providers.semantic_scholar import SemanticScholar
from .queries import all_queries
from .storage import append_jsonl, read_csv, read_json, read_jsonl, write_csv_atomic, write_json_atomic


LOGGER = logging.getLogger("mobility_literature.pipeline")


def discover(
    settings: Settings,
    *,
    max_results_per_query: int | None = None,
    enrich_limit: int | None = None,
    neighbors_per_seed: int | None = None,
    crossref_limit: int | None = None,
    use_semantic_scholar: bool = True,
    use_crossref: bool = True,
    import_paths: list[Path] | None = None,
    refresh_enrichment: bool = False,
    inventory_paths: list[Path] | None = None,
    pdf_roots: list[Path] | None = None,
    remote_pdf_manifest: Path | None = None,
) -> dict[str, Any]:
    max_results = settings.max_results_per_query if max_results_per_query is None else max(0, max_results_per_query)
    enrich_count = settings.max_s2_enrich if enrich_limit is None else max(0, enrich_limit)
    neighbor_count = settings.max_s2_neighbors_per_seed if neighbors_per_seed is None else max(0, neighbors_per_seed)
    cr_limit = 100 if crossref_limit is None else max(0, crossref_limit)
    openalex = OpenAlexClient(
        api_key=settings.openalex_api_key,
        timeout=settings.timeout_seconds,
        max_retries=settings.retries,
        user_agent=settings.user_agent,
        event_callback=lambda event: LOGGER.info(json.dumps(dict(event), ensure_ascii=False, sort_keys=True)),
    )

    fetched_rows: list[dict[str, Any]] = []
    failed_queries: list[dict[str, str]] = []
    query_summaries = []
    for material_class, query_id, query in all_queries():
        rows, summary, error = _discover_query(
            settings, openalex, material_class, query_id, query, max_results
        )
        fetched_rows.extend(rows)
        query_summaries.append(summary)
        if error:
            failed_queries.append({"query_id": query_id, "error": error})

    inventory_rows = [row for path in inventory_paths or [] for row in load_inventory(path)]
    candidates = merge_records([*read_csv(settings.root / "data" / "candidate_papers.csv"), *inventory_rows, *fetched_rows])
    for row in candidates:
        rescreen(row)

    http = JsonHttpClient(
        settings.cache_dir,
        settings.user_agent,
        timeout=settings.timeout_seconds,
        retries=settings.retries,
        cache_ttl_seconds=0 if refresh_enrichment else 7 * 24 * 60 * 60,
    )
    if use_semantic_scholar and enrich_count:
        s2 = SemanticScholar(http, settings.semantic_scholar_api_key)
        s2_summary = _enrich_semantic_scholar(candidates, s2, enrich_count, neighbor_count)
    else:
        s2_summary = {"seeds": 0, "enriched": 0, "neighbors": 0}
    if use_crossref and cr_limit:
        crossref = Crossref(http, settings.crossref_mailto)
        _enrich_crossref(candidates, crossref, cr_limit)

    candidates = merge_records(candidates)
    for row in candidates:
        rescreen(row)
    import_summary = apply_local_imports(settings.root, candidates, import_paths)
    candidates = merge_records(candidates)
    for row in candidates:
        rescreen(row)
    candidates.sort(key=_priority, reverse=True)
    local_summary = match_local_pdfs(candidates, pdf_roots) if pdf_roots else {}
    if remote_pdf_manifest:
        local_summary["remote"] = match_remote_manifest(candidates, remote_pdf_manifest)
    write_csv_atomic(settings.data_dir / "candidate_papers.csv", candidates)
    priority_rows = [
        row for row in candidates
        if (row.get("screening_state") == "likely_contains_mobility" or row.get("evidence_state") == "likely_contains_mobility" or row.get("extraction_review_required") is True)
        and row.get("evidence_state") not in {"confirmed_numeric_mobility", "verified_evidence"}
    ]
    write_csv_atomic(settings.data_dir / "priority_missing_papers.csv", priority_rows)
    report = _coverage_report(candidates, query_summaries, failed_queries, http.stats, import_summary, s2_summary, local_summary)
    report_path = settings.reports_dir / "coverage_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(candidates),
        "priority_missing_count": len(priority_rows),
        "query_count": len(query_summaries),
        "failed_query_count": len(failed_queries),
        "provider_stats": http.stats,
        "semantic_scholar": s2_summary,
        "imports": import_summary,
        "local_matching": local_summary,
        "candidates_path": str(settings.data_dir / "candidate_papers.csv"),
        "priority_path": str(settings.data_dir / "priority_missing_papers.csv"),
        "report_path": str(report_path),
    }
    LOGGER.info(json.dumps({"event": "run_complete", **summary}, ensure_ascii=False, sort_keys=True))
    write_json_atomic(settings.reports_dir / "run_summary.json", summary)
    append_jsonl(settings.data_dir / "run_history.jsonl", [summary])
    return summary


def _discover_query(
    settings: Settings,
    client: OpenAlexClient,
    material_class: str,
    query_id: str,
    query: str,
    max_results: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    state_path = settings.checkpoint_dir / "openalex" / f"{query_id}.json"
    cache_path = settings.raw_metadata_dir / "openalex" / f"{query_id}.jsonl"
    checkpoint = read_json(state_path, {}) or {}
    if checkpoint and (checkpoint.get("query") != query or checkpoint.get("material_class") != material_class):
        # Keep the old response history intact when a query is revised.
        revision = hashlib.sha256((material_class + "|" + query).encode()).hexdigest()[:12]
        state_path = state_path.with_name(f"{query_id}-{revision}.json")
        cache_path = cache_path.with_name(f"{query_id}-{revision}.jsonl")
        checkpoint = read_json(state_path, {}) or {}
    rows: list[dict[str, Any]] = []
    error_text = None
    page_size = max(1, min(100, settings.per_page))
    cached_count = len(merge_records(read_jsonl(cache_path)))
    remaining_results = max(0, max_results - cached_count)
    completed = bool(checkpoint.get("complete"))
    pages_this_run = 0

    if not completed and remaining_results > 0:
        cursor = checkpoint.get("cursor") or "*"
        try:
            # OpenAlex supports at most 100 results per page. Requests are kept
            # sequential to respect provider rate limits.
            seen_cursors = set()
            while remaining_results > 0 and cursor:
                if cursor in seen_cursors:
                    raise RuntimeError("OpenAlex repeated its cursor")
                seen_cursors.add(cursor)
                page = client.fetch_page(query, cursor=cursor, per_page=min(page_size, remaining_results), query_id=query_id)
                normalized = [
                    _openalex_candidate(work, material_class, query_id, query)
                    for work in page.records
                ]
                append_jsonl(cache_path, normalized)
                for item in normalized:
                    item["raw_source"] = [str(cache_path.relative_to(settings.root))]
                pages_this_run += 1
                next_cursor = page.next_cursor
                completed = next_cursor is None or not page.records
                remaining_results -= len(normalized)
                write_json_atomic(
                    state_path,
                    {
                        "provider": "openalex",
                        "query_id": query_id,
                        "query": query,
                        "material_class": material_class,
                        "cursor": next_cursor,
                        "complete": completed,
                        "result_limit": max_results,
                        "total_count": page.total_count,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                if completed:
                    break
                cursor = next_cursor
                if remaining_results > 0:
                    time.sleep(0.2)
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            LOGGER.error(json.dumps({"event": "query_failed", "provider": "openalex", "query_id": query_id,
                                     "error_type": type(exc).__name__}, sort_keys=True))
    rows = read_jsonl(cache_path)
    for row in rows:
        row["raw_source"] = [str(cache_path.relative_to(settings.root))]
        row["query_material_classes"] = [material_class]
        rescreen(row)
    summary = {
        "query_id": query_id,
        "material_class": material_class,
        "material_classes": [material_class],
        "pages_this_run": pages_this_run,
        "cached_records": len(rows),
        "total_count": read_json(state_path, {}).get("total_count"),
        "complete": completed,
        "reached_page_limit": not completed and not error_text,
    }
    return rows, summary, error_text


def _openalex_candidate(work: dict[str, Any], material_class: str, query_id: str, query: str) -> dict[str, Any]:
    doi = normalize_doi(work.get("doi"))
    primary = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    oa = work.get("open_access") if isinstance(work.get("open_access"), dict) else {}
    authors = work.get("author_names") or []
    row = {
        "doi": doi,
        "openalex_id": work.get("openalex_id", ""),
        "title": work.get("title", ""),
        "year": work.get("publication_year"),
        "venue": primary.get("source_name", ""),
        "authors": authors,
        "abstract": work.get("abstract", ""),
        "landing_url": primary.get("landing_page_url") or "",
        "open_access_pdf_url": primary.get("pdf_url") or oa.get("url") or "",
        "is_open_access": oa.get("is_oa"),
        "citation_count": work.get("cited_by_count"),
        "provider_ids": {"openalex": work.get("openalex_id", "")},
        "source_provenance": ["openalex"],
        "query_provenance": [{"provider": "openalex", "query_id": query_id, "query": query, "material_class": material_class}],
        "material_class": material_class,
        "material_class_confidence": "query_family",
        "local_match_status": "not_checked",
        "query_material_classes": [material_class],
        "publication_type": [work.get("work_type")] if work.get("work_type") else [],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    screened = screen(row["title"], row["abstract"] or "")
    row.update(screened)
    row.update(screen_material(row["title"] or "", row["abstract"] or "", material_class))
    return row


def _enrich_semantic_scholar(
    candidates: list[dict[str, Any]], s2: SemanticScholar, limit: int, neighbor_limit: int
) -> dict[str, int]:
    eligible = sorted(candidates, key=_priority, reverse=True)
    seeds: list[dict[str, Any]] = []
    by_class: Counter[str] = Counter()
    per_class_cap = max(1, math.ceil(limit / 5))
    for row in eligible:
        material_class = str(row.get("material_class") or "unknown")
        if material_class not in MATERIAL_CLASSES:
            continue
        if by_class[material_class] >= per_class_cap or len(seeds) >= limit:
            continue
        if row.get("screening_state") != "likely_contains_mobility" and not row.get("doi"):
            continue
        seeds.append(row)
        by_class[material_class] += 1

    additions: list[dict[str, Any]] = []
    enriched_count = 0
    for index, row in enumerate(seeds, start=1):
        doi = normalize_doi(row.get("doi"))
        enriched = s2.get_paper("DOI:" + doi) if doi else None
        if enriched is None and row.get("title"):
            matches = s2.search_title(str(row["title"]), limit=5)
            enriched = _best_title_match(row, matches)
        if enriched:
            enriched_count += 1
            _apply_enrichment(row, enriched, "semantic_scholar")
            s2id = (enriched.get("provider_ids") or {}).get("semantic_scholar")
            if s2id and neighbor_limit:
                for relation in ("citations", "references"):
                    for neighbor in s2.neighbors(str(s2id), relation, limit=neighbor_limit):
                        neighbor["material_class"] = row.get("material_class") or ""
                        neighbor["material_classes"] = row.get("material_classes") or ([row.get("material_class")] if row.get("material_class") else [])
                        neighbor["material_class_confidence"] = "seed_inherited"
                        neighbor["query_material_classes"] = row.get("query_material_classes") or row.get("material_classes") or []
                        neighbor["review_material_class"] = True
                        neighbor["query_provenance"] = [{
                            "provider": "semantic_scholar",
                            "query_id": "citation-expansion",
                            "query": relation,
                            "seed_doi": row.get("doi", ""),
                        }]
                        neighbor.update(screen(neighbor.get("title", ""), neighbor.get("abstract", "")))
                        rescreen(neighbor)
                        additions.append(neighbor)
        if index % 10 == 0:
            LOGGER.info(json.dumps({"event": "semantic_scholar_progress", "processed_seeds": index,
                                    "seed_limit": len(seeds)}, sort_keys=True))
    candidates.extend(additions)
    return {"seeds": len(seeds), "enriched": enriched_count, "neighbors": len(additions)}


def _best_title_match(candidate: dict[str, Any], matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    expected = normalize_title(candidate.get("title"))
    if not expected:
        return None
    scored = []
    for match in matches:
        if candidate.get("year") and match.get("year") and _year_distance(candidate["year"], match["year"]) > 1:
            continue
        if candidate.get("doi") and match.get("doi") and normalize_doi(candidate["doi"]) != normalize_doi(match["doi"]):
            continue
        score = difflib.SequenceMatcher(None, expected, normalize_title(match.get("title"))).ratio()
        scored.append((score, match))
    score, best = max(scored, default=(0.0, None), key=lambda item: item[0])
    return best if score >= 0.95 else None


def _enrich_crossref(candidates: list[dict[str, Any]], crossref: Crossref, limit: int) -> None:
    selected = sorted(candidates, key=_priority, reverse=True)[:limit]
    for index, row in enumerate(selected, start=1):
        doi = normalize_doi(row.get("doi"))
        found = crossref.by_doi(doi) if doi else None
        if found is None and not doi and row.get("title"):
            found = crossref.search_title(str(row["title"]))
            if found and (_title_similarity(row.get("title"), found.get("title")) < 0.95 or
                          (row.get("year") and found.get("year") and _year_distance(row["year"], found["year"]) > 1)):
                found = None
        if found:
            _apply_enrichment(row, found, "crossref")
            row["crossref_validation"] = "doi_resolved" if doi else "title_matched_needs_review"
        else:
            row["crossref_validation"] = "unresolved_or_request_failed"
        row["crossref_checked_at"] = datetime.now(timezone.utc).isoformat()
        if index % 25 == 0:
            LOGGER.info(json.dumps({"event": "crossref_progress", "processed": index, "limit": len(selected)}, sort_keys=True))


def _apply_enrichment(target: dict[str, Any], source: dict[str, Any], provider: str) -> None:
    target_ids = target.get("provider_ids") if isinstance(target.get("provider_ids"), dict) else {}
    source_ids = source.get("provider_ids") if isinstance(source.get("provider_ids"), dict) else {}
    target["provider_ids"] = {**target_ids, **{k: v for k, v in source_ids.items() if v}}
    target["source_provenance"] = list(dict.fromkeys([*(target.get("source_provenance") or []), provider]))
    conflicts = target.get("metadata_conflicts")
    if not isinstance(conflicts, dict):
        conflicts = target["metadata_conflicts"] = {}
    for key in ("doi", "title", "year", "venue", "abstract", "authors", "landing_url", "open_access_pdf_url", "is_open_access", "publication_type"):
        incoming = source.get(key)
        if incoming in (None, "", [], {}):
            continue
        current = target.get(key)
        comparable_current = normalize_doi(current) if key == "doi" else (
            normalize_title(current) if key == "title" else str(current or "").strip()
        )
        comparable_incoming = normalize_doi(incoming) if key == "doi" else (
            normalize_title(incoming) if key == "title" else str(incoming or "").strip()
        )
        if not current:
            target[key] = incoming
        elif comparable_current != comparable_incoming:
            conflict = {"provider_value": incoming, "provider": provider}
            if conflict not in conflicts.setdefault(key, []):
                conflicts[key].append(conflict)
            if provider == "crossref" and key in {"title", "year", "venue"} and normalize_doi(source.get("doi")) == normalize_doi(target.get("doi")):
                original = {"provider_value": current, "provider": "pre_crossref"}
                if original not in conflicts[key]:
                    conflicts[key].append(original)
                target[key] = incoming
    if source.get("citation_count") is not None:
        counts = target.setdefault("citation_counts", {})
        counts[provider] = source["citation_count"]
        target["citation_count"] = max(int(v or 0) for v in counts.values())
    if target.get("doi"):
        target["doi"] = normalize_doi(target["doi"])
    rescreen(target)


def _priority(row: dict[str, Any]) -> tuple[int, int, int, str]:
    state_score = 2 if row.get("screening_state") == "likely_contains_mobility" else 1
    try:
        citations = int(float(row.get("citation_count") or 0))
    except (TypeError, ValueError):
        citations = 0
    material = str(row.get("material_class") or "")
    confidence = 2 if row.get("material_class_confidence") == "metadata_signal" and not row.get("review_material_class") else 0
    return state_score, confidence, citations, str(row.get("title") or "")


def _title_similarity(left: Any, right: Any) -> float:
    return difflib.SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def _year_distance(left: Any, right: Any) -> int:
    try:
        return abs(int(float(left)) - int(float(right)))
    except (TypeError, ValueError, OverflowError):
        return 0  # Unknown years are left for metadata review rather than guessed.


def _coverage_report(candidates: list[dict[str, Any]], query_summaries: list[dict[str, Any]], failures: list[dict[str, str]],
                     provider_stats: dict[str, Any] | None = None, import_summary: dict[str, int] | None = None,
                     s2_summary: dict[str, int] | None = None, local_summary: dict[str, Any] | None = None) -> str:
    by_material: dict[str, Counter[str]] = defaultdict(Counter)
    by_provider: Counter[str] = Counter()
    for row in candidates:
        materials = row.get("material_classes")
        if not isinstance(materials, list) or not materials:
            materials = [row.get("material_class") or "unassigned"]
        for material in dict.fromkeys(str(item) for item in materials if item):
            by_material[material][str(row.get("screening_state") or "candidate")] += 1
            by_material[material]["total"] += 1
            if material in MATERIAL_CLASSES and row.get("review_material_class") is not True and row.get("material_class_confidence") == "metadata_signal":
                by_material[material]["metadata_supported"] += 1
            if row.get("screening_state") == "likely_contains_mobility" or row.get("evidence_state") in {"likely_contains_mobility", "confirmed_numeric_mobility", "verified_evidence"}:
                by_material[material]["likely_or_stronger"] += 1
            by_material[material][f"evidence:{row.get('evidence_state') or 'candidate'}"] += 1
            by_material[material][f"local:{row.get('local_match_status') or 'not_checked'}"] += 1
        for provider in row.get("source_provenance") or []:
            by_provider[str(provider)] += 1
    lines = [
        "# Mobility literature coverage report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- Deduplicated candidate papers: **{len(candidates)}**",
        f"- Query families: **{len(query_summaries)}**",
        f"- Failed query families this run: **{len(failures)}**",
        f"- Local PDF matching this run: `{local_summary or 'not requested'}`.",
        "",
        "## Counts by material class",
        "",
        "| Material class | Candidates | Metadata-supported class | Likely or stronger mobility | Confirmed numeric | Verified evidence | PDF matched | Local match checked |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for material in ("COF", "MOF", "organic_small_molecule", "hybrid_perovskite", "inorganic_2d", "unassigned"):
        counts = by_material.get(material, Counter())
        lines.append(
            f"| {material} | {counts.get('total', 0)} | {counts.get('metadata_supported', 0)} | {counts.get('likely_or_stronger', 0)} | "
            f"{counts.get('evidence:confirmed_numeric_mobility', 0)} | {counts.get('evidence:verified_evidence', 0)} | "
            f"{counts.get('local:matched', 0)} | "
            f"{counts.get('local:matched', 0) + counts.get('local:not_found_in_scanned_roots', 0)} |"
        )
    lines += ["", "## Query families", "", "| Query ID | Material class | Cached candidates | Complete | Pages this run |", "|---|---|---:|---|---:|"]
    for query in query_summaries:
        lines.append(
            f"| {query['query_id']} | {query['material_class']} | {query['cached_records']} | "
            f"{'yes' if query['complete'] else 'no'} | {query['pages_this_run']} |"
        )
    lines += ["", "## Failed query families", ""]
    if failures:
        lines.extend(f"- `{item['query_id']}`: {item['error']}" for item in failures)
    else:
        lines.append("None reported.")
    lines += ["", "## Candidate records by metadata provider", ""]
    if by_provider:
        lines += ["| Provider | Candidate records |", "|---|---:|"]
        lines.extend(f"| {provider} | {count} |" for provider, count in sorted(by_provider.items()))
    else:
        lines.append("No provider provenance recorded yet.")
    lines += [
        "",
        "## Enrichment and import outcomes", "",
        f"- Semantic Scholar seeds/enriched/neighbors: `{s2_summary or {}}`.",
        f"- Normalized extraction imports: `{import_summary or {}}`.",
        "",
        "| Provider | Cache hits | Requests | Successes | Retries | Failed requests |", "|---|---:|---:|---:|---:|---:|",
        *[f"| {p} | {s['cache_hit']} | {s['request_attempt']} | {s['success']} | {s['retry']} | {s['failure']} |" for p, s in sorted((provider_stats or {}).items())],
        "",
        "## Interpretation",
        "",
        "A query hit is only a candidate. Counts under confirmed or verified evidence come from imported extraction records and require explicit electronic mobility values; abstract screening alone does not create them. `not_checked` means no designated local PDF roots were examined, not that the PDF is absent.",
        "Material classes are metadata screening labels. Query-only and citation-inherited classes need review; metadata-supported class counts require explicit class cues and no ambiguous/mixed signals. A paper can belong to multiple classes, so class counts can overlap. OpenAlex search can match full-text terms absent from its title/abstract.",
        "Uncompleted query families were capped for this run; the candidate set is not an exhaustive literature census. Provider failures are reported separately from papers absent in a database. Without designated extraction results, zero confirmed/verified values is an evidence gap, not evidence that the literature has no mobility data.",
        "Verified import evidence is a source-declared review state supported by a matching numerical quote and precise locator. It does not represent a new independent PDF review in this discovery run. Filename inventories confirm availability only; overlapping remote roots are not counted as unique publications.",
        "",
    ]
    return "\n".join(lines)
