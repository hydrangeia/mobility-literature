from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .classify import EVIDENCE_STATES, screen
from .importer import revalidate_normalized_record
from .materials import screen_material
from .normalize import normalize_doi, normalize_title
from .storage import read_csv, read_jsonl

RANK = {state: rank for rank, state in enumerate(EVIDENCE_STATES)}


def rescreen(row: dict[str, Any]) -> None:
    """Recompute metadata screening while retaining separately supported evidence."""
    old_evidence = max(["candidate"] + [o.get("status", "candidate") for o in row.get("mobility_observations", [])], key=lambda s: RANK.get(s, 0))
    screened = screen(row.get("title") or "", row.get("abstract") or "")
    row.update({k: v for k, v in screened.items() if k != "evidence_state"})
    row["evidence_state"] = max((old_evidence, screened["evidence_state"]), key=lambda s: RANK.get(s, 0))
    query_classes = row.get("query_material_classes") or [
        q.get("material_class") for q in row.get("query_provenance", []) if isinstance(q, dict) and q.get("material_class")
    ]
    # Older caches recorded only the singular query family.
    if not query_classes and row.get("material_class_confidence") in {"query_family", "seed_inherited"}:
        query_classes = row.get("material_classes") or [row.get("material_class")]
    materials = [row.get("material") or ""] + [o.get("material") or "" for o in row.get("mobility_observations", [])]
    row.update(screen_material(row.get("title") or "", (row.get("abstract") or "") + "\n" + "\n".join(materials), query_classes))


def _identity_keys(row: dict[str, Any]) -> list[str]:
    keys = []
    doi = normalize_doi(row.get("doi"))
    if doi:
        keys.append("doi:" + doi)
    ids = row.get("provider_ids") or {}
    for provider in ("openalex", "semantic_scholar", "pmid"):
        value = row.get("pmid") if provider == "pmid" else row.get(provider + "_id") or ids.get(provider)
        if value:
            value = str(value).rstrip("/").split("/")[-1].casefold()
            keys.append(provider + ":" + value)
    return keys


def apply_local_imports(root: Path, candidates: list[dict[str, Any]], paths: list[Path] | None = None) -> dict[str, int]:
    # Generated exports are not an evidence input. Rebuild observations from
    # normalized source snapshots so revised/excluded rows cannot leave stale
    # numeric states or selected-value fields behind on a later run.
    for candidate in candidates:
        candidate["mobility_observations"] = []
        candidate["import_references"] = []
        candidate["extraction_review_required"] = False
        candidate["evidence_state"] = candidate.get("screening_state", "candidate")
        for key in ("mobility_value", "mobility_unit", "carrier_type", "method", "temperature", "direction",
                    "material", "sample", "experimental_or_theoretical", "conditions", "evidence_quote",
                    "evidence_location", "source_pdf"):
            candidate.pop(key, None)
    if paths is None:
        imported_dir = root / "data" / "imported"
        paths = sorted(imported_dir.glob("*.csv")) + sorted(imported_dir.glob("*.jsonl"))
    imported = []
    for path in paths:
        rows = read_jsonl(path) if path.suffix.casefold() == ".jsonl" else read_csv(path)
        for source in rows:
            if "mobility_value" not in source or "source_file" not in source:
                raise ValueError(f"Not a normalized mobility import: {path}")
            record = revalidate_normalized_record(source)
            record["normalized_import_file"] = str(path.resolve())
            imported.append(record)

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    def index(candidate: dict[str, Any]) -> None:
        for key in _identity_keys(candidate):
            by_key[key].append(candidate)
        title = normalize_title(candidate.get("title"))
        if title:
            by_title[title].append(candidate)
    for candidate in candidates:
        index(candidate)
    matched, added = 0, 0
    for record in imported:
        matches = []
        for key in _identity_keys(record):
            for candidate in by_key.get(key, []):
                if candidate not in matches:
                    matches.append(candidate)
        if not matches:
            title = normalize_title(record.get("title"))
            matches = [c for c in by_title.get(title, [])
                       if not (record.get("doi") and c.get("doi") and normalize_doi(c["doi"]) != record["doi"])
                       and (not record.get("year") or not c.get("year") or str(record["year"]) == str(c["year"]))]
        if len(matches) == 1:
            target = matches[0]
            matched += 1
        else:
            target = {key: record.get(key, "") for key in ("doi", "title", "year", "abstract", "openalex_id", "semantic_scholar_id", "paper_id")}
            target.update({"venue": record.get("journal"), "landing_url": record.get("paper_url"),
                           "source_provenance": ["legacy_import"], "provider_ids": {},
                           "local_match_status": "not_checked", "possible_duplicate_review": len(matches) > 1,
                           "query_material_classes": [record["material_class"]] if record.get("material_class") else []})
            for provider in ("openalex", "semantic_scholar"):
                if record.get(provider + "_id"):
                    target["provider_ids"][provider] = record[provider + "_id"]
            rescreen(target)
            candidates.append(target)
            index(target)
            added += 1
        reference = {key: record.get(key) for key in ("record_id", "source_file", "source_row", "normalized_import_file", "status", "exclusion_reason")}
        reference["numeric_review_reason"] = record.get("numeric_review_reason") or ""
        if reference["numeric_review_reason"] and not record.get("exclusion_reason") and record.get("mobility_value"):
            target["extraction_review_required"] = True
        refs = target.setdefault("import_references", [])
        if reference not in refs:
            refs.append(reference)
        provenance = target.setdefault("source_provenance", [])
        if "legacy_import" not in provenance:
            provenance.append("legacy_import")
        # Every evidence state is re-derived from its selected measurement.
        observations = target.setdefault("mobility_observations", [])
        observations[:] = [o for o in observations if o.get("record_id") != record["record_id"]]
        if record.get("is_electronic_mobility") is not True or record.get("exclusion_reason"):
            target["evidence_state"] = max([target.get("screening_state", "candidate")] + [o.get("status", "candidate") for o in observations], key=lambda s: RANK.get(s, 0))
            continue
        observation = {key: record.get(key) for key in (
            "record_id", "mobility_value", "mobility_value_numeric", "mobility_unit", "carrier_type",
            "method", "temperature", "direction", "material", "sample", "experimental_or_theoretical",
            "conditions", "evidence_quote", "evidence_location", "source_file", "source_row", "source_pdf",
            "status", "normalized_import_file",
            "mobility_value_original", "mobility_value_low", "mobility_value_high", "numeric_review_reason",
        )}
        observation["verification_origin"] = "legacy_source_declared" if record["status"] == "verified_evidence" else "normalized_import"
        observations.append(observation)
        best = max(observations, key=lambda o: RANK.get(o.get("status"), 0))
        target["evidence_state"] = max((target.get("screening_state", "candidate"), best["status"]), key=lambda s: RANK.get(s, 0))
        for key in ("mobility_value", "mobility_unit", "carrier_type", "method", "temperature", "direction",
                    "material", "sample", "experimental_or_theoretical", "conditions", "evidence_quote", "evidence_location", "source_pdf"):
            target[key] = best.get(key)
    return {"files": len(paths), "records": len(imported), "matched_records": matched, "added_papers": added}
