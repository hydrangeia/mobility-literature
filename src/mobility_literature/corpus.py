from __future__ import annotations

import csv
import hashlib
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .normalize import normalize_doi, normalize_title
from .storage import read_jsonl

CLASS_MAP = {"COF": "COF", "MOF": "MOF", "OSM": "organic_small_molecule", "PVSK": "hybrid_perovskite", "2D": "inorganic_2d"}


def load_inventory(path: Path) -> list[dict[str, Any]]:
    """Read the user's download inventory as metadata candidates only."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    rows = []
    for index, raw in enumerate(records, 2):
        doi = normalize_doi(raw.get("doi"))
        title = raw.get("title") or ""
        if not doi and not title:
            continue
        year = raw.get("year") or ""
        try:
            year = str(int(float(year))) if year else ""
        except ValueError:
            pass
        material = CLASS_MAP.get(str(raw.get("class") or "").upper(), "unassigned")
        rows.append({"doi": doi, "title": title, "year": year, "authors": (raw.get("authors") or "").split(";"),
                     "venue": raw.get("source") or "", "citation_count": raw.get("times_cited") or "",
                     "paper_id": "inventory:" + hashlib.sha256(f"{path.resolve()}:{index}".encode()).hexdigest()[:20],
                     "source_provenance": ["local_inventory"], "query_material_classes": [material] if material != "unassigned" else [],
                     "query_provenance": [{"provider": "local_inventory", "query": "legacy_metadata", "material_class": material}],
                     "raw_source": [{"file": str(path.resolve()), "row": index}],
                     "local_match_status": "not_checked", "inventory_pdf_names": raw.get("pdf_names") or "",
                     "legacy_download_status": raw.get("outcome") or raw.get("dl_status") or "",
                     "metadata_conflicts": {"doi": [raw.get("doi")]} if raw.get("doi") and not doi else {}})
    return rows


def match_local_pdfs(candidates: list[dict[str, Any]], roots: list[Path]) -> dict[str, Any]:
    """Match filenames within explicit roots; no PDF text or numeric evidence is inferred."""
    resolved = [root.resolve(strict=True) for root in roots]
    for root in resolved:
        if not root.is_dir():
            raise NotADirectoryError(root)
    by_name: dict[str, list[str]] = defaultdict(list)
    by_title: dict[str, list[str]] = defaultdict(list)
    by_doi: dict[str, list[str]] = defaultdict(list)
    errors: list[str] = []
    def error(exc: OSError) -> None:
        errors.append(str(exc.filename or "unreadable directory"))
    count = 0
    for root in resolved:
        for directory, subdirs, names in os.walk(root, followlinks=False, onerror=error):
            subdirs[:] = [name for name in subdirs if not name.startswith(".") and name not in {"node_modules", "__pycache__", "cache", "venv"}
                          and not Path(directory, name).is_symlink() and not (hasattr(Path, "is_junction") and Path(directory, name).is_junction())]
            for name in names:
                if not name.casefold().endswith(".pdf"):
                    continue
                path = str(Path(directory, name))
                count += 1
                by_name[name.casefold()].append(path)
                stem = Path(name).stem
                by_title[normalize_title(stem)].append(path)
                if re.match(r"^10\.\d{4,9}_", stem):
                    doi = normalize_doi(stem.replace("_", "/", 1))
                    if doi:
                        by_doi[doi].append(path)
    matched = 0
    timestamp = datetime.now(timezone.utc).isoformat()
    for row in candidates:
        matches = []
        basis = ""
        doi = normalize_doi(row.get("doi"))
        if doi and by_doi.get(doi):
            matches = by_doi[doi]
            basis = "doi_encoded_filename"
        if not matches:
            names = re.split(r"[;|]", row.get("inventory_pdf_names") or "")
            matches = [p for name in names for p in by_name.get(name.strip().casefold(), [])]
            if matches:
                basis = "inventory_filename"
        if not matches and row.get("title"):
            matches = by_title.get(normalize_title(row["title"]), [])
            if matches:
                basis = "exact_title_filename"
        row["local_match_status"] = "matched" if matches else ("scan_incomplete" if errors else "not_found_in_scanned_roots")
        row["local_pdf_paths"] = sorted(set(matches))
        row["local_match_basis"] = basis
        row["local_scanned_roots"] = [str(root) for root in resolved]
        row["local_checked_at"] = timestamp
        matched += bool(matches)
    return {"pdf_files": count, "matched_papers": matched, "scanned_roots": [str(r) for r in resolved], "unreadable_paths": errors}


def match_remote_manifest(candidates: list[dict[str, Any]], manifest: Path) -> dict[str, Any]:
    """Read a filename inventory created from explicit remote paper roots."""
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    records = read_jsonl(manifest)
    by_doi: dict[str, list[str]] = defaultdict(list)
    by_title: dict[str, list[str]] = defaultdict(list)
    by_path: dict[str, list[str]] = defaultdict(list)
    roots = set()
    for record in records:
        path = str(record.get("path") or "")
        if not path.casefold().endswith(".pdf"):
            continue
        server = str(record.get("server") or "remote")
        reference = server + ":" + path
        roots.add(server + ":" + str(record.get("root") or ""))
        by_path[path].append(reference)
        stem = Path(path).stem
        by_title[normalize_title(stem)].append(reference)
        if re.match(r"^10\.\d{4,9}_", stem):
            doi = normalize_doi(stem.replace("_", "/", 1))
            if doi:
                by_doi[doi].append(reference)
    matched = 0
    for row in candidates:
        paths = list(by_doi.get(normalize_doi(row.get("doi")), []))
        basis = "remote_doi_encoded_filename" if paths else ""
        source_paths = [row.get("source_pdf")] + [o.get("source_pdf") for o in row.get("mobility_observations", [])]
        for source_path in source_paths:
            if not source_path:
                continue
            if source_path in by_path:
                paths.extend(by_path[source_path])
                basis = "remote_exact_source_path"
        if not paths and row.get("title"):
            paths = by_title.get(normalize_title(row["title"]), [])
            if paths:
                basis = "remote_exact_title_filename"
        row["remote_pdf_paths"] = sorted(set(paths))
        row["remote_scanned_roots"] = sorted(roots)
        row["remote_match_basis"] = basis
        row["remote_manifest_file"] = str(manifest.resolve())
        if paths:
            row["local_match_status"] = "matched"
            matched += 1
        elif row.get("local_match_status") == "not_checked":
            row["local_match_status"] = "not_found_in_scanned_roots"
    return {"manifest": str(manifest.resolve()), "pdf_paths": len(by_path), "matched_papers": matched,
            "roots": sorted(roots), "deduplicated_by_content": False}
