from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .normalize import merge_records


CSV_FIELDS = [
    "paper_id", "doi", "openalex_id", "semantic_scholar_id", "title", "year",
    "venue", "authors", "abstract", "landing_url", "open_access_pdf_url",
    "material_class", "material_classes", "query_material_classes", "possible_duplicate_review",
    "screening_state", "screening_reason", "screening_confidence", "excluded_measure",
    "evidence_state", "mobility_value", "mobility_unit", "carrier_type", "method",
    "temperature", "direction", "evidence_quote", "evidence_location",
    "source_pdf", "material", "sample", "experimental_or_theoretical", "conditions",
    "mobility_observations", "import_references", "extraction_review_required", "citation_count", "citation_counts",
    "is_open_access", "provider_ids", "query_provenance", "source_provenance",
    "material_class_confidence", "review_material_class", "local_match_status",
    "metadata_conflicts",
    "material_screening_reason", "publication_type", "retrieved_at", "raw_source",
    "crossref_validation", "crossref_checked_at", "citation_relation", "citation_seed_id",
    "inventory_pdf_names", "legacy_download_status", "local_pdf_paths", "local_match_basis",
    "local_scanned_roots", "local_checked_at",
    "remote_pdf_paths", "remote_match_basis", "remote_scanned_roots", "remote_manifest_file",
]


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    temp.replace(path)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # A crash may leave an unfinished final line. Separate it from replayed
    # records so a valid first replay row is not swallowed by the corrupt tail.
    if path.exists() and path.stat().st_size:
        with path.open("rb+") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                handle.seek(0, os.SEEK_END)
                handle.write(b"\n")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    csv.field_size_limit(16 * 1024 * 1024)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    complex_fields = {
        "authors", "provider_ids", "query_provenance", "source_provenance",
        "metadata_conflicts", "citation_counts", "mobility_observations", "import_references",
        "material_classes", "query_material_classes", "publication_type", "raw_source", "local_pdf_paths", "local_scanned_roots", "remote_pdf_paths", "remote_scanned_roots"
    }
    for row in rows:
        for field in complex_fields:
            value = row.get(field)
            if not value:
                row[field] = {} if field in {"provider_ids", "metadata_conflicts", "citation_counts"} else []
                continue
            try:
                row[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        for field in ("review_material_class", "possible_duplicate_review", "is_open_access", "extraction_review_required"):
            if str(row.get(field, "")).casefold() in {"true", "false"}:
                row[field] = str(row[field]).casefold() == "true"
    return rows


def write_csv_atomic(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or CSV_FIELDS
    descriptor, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
        Path(temp_name).replace(path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)
        finally:
            raise


def save_candidates(root: Path, fresh_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    path = root / "data" / "candidate_papers.csv"
    prior = read_csv(path)
    merged = merge_records([*prior, *fresh_rows])
    merged.sort(key=_candidate_sort_key, reverse=True)
    write_csv_atomic(path, merged)
    return merged


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, int, int, str]:
    state = 2 if row.get("screening_state") == "likely_contains_mobility" else 1
    try:
        citations = int(row.get("citation_count") or 0)
    except (TypeError, ValueError):
        citations = 0
    class_confidence = 0 if row.get("material_class_confidence") == "seed_inherited" else 1
    return state, class_confidence, citations, str(row.get("title") or "")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
