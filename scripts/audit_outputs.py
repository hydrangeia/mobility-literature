"""Audit generated v1 outputs against normalized source snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mobility_literature.evidence import RANK
from mobility_literature.importer import revalidate_normalized_record
from mobility_literature.materials import MATERIAL_CLASSES
from mobility_literature.storage import read_csv, read_json


def audit(root: Path, source_manifest: Path | None = None) -> dict:
    candidates = read_csv(root / "data/candidate_papers.csv")
    priority = read_csv(root / "data/priority_missing_papers.csv")
    assert candidates, "Candidate export is missing or empty"
    assert len(candidates) == len({r["paper_id"] for r in candidates}), "Duplicate paper IDs"
    doi_counts = Counter(r["doi"] for r in candidates if r.get("doi"))
    assert all(n == 1 for n in doi_counts.values()), "Duplicate DOI records"
    normalized = {}
    normalized_count = 0
    for path in sorted((root / "data/imported").glob("*.csv")):
        for raw in read_csv(path):
            checked = revalidate_normalized_record(raw)
            assert checked["status"] == raw["status"], f"Stale normalized state: {raw['record_id']}"
            normalized[raw["record_id"]] = checked
            normalized_count += 1
    for row in candidates:
        assert row["evidence_state"] in RANK, "Unknown evidence state"
        observations = row.get("mobility_observations") or []
        for observation in observations:
            source = normalized[observation["record_id"]]
            assert source["is_electronic_mobility"] is True and not source["exclusion_reason"]
            assert observation["status"] == source["status"]
            assert observation["mobility_value"] == source["mobility_value"]
            assert observation["mobility_unit"] == source["mobility_unit"]
            assert observation["carrier_type"] == source["carrier_type"]
        expected = max([row["screening_state"]] + [o["status"] for o in observations], key=RANK.get)
        assert row["evidence_state"] == expected, f"Unsupported state: {row['paper_id']}"
        if RANK[row["evidence_state"]] >= 2:
            assert all(row.get(k) for k in ("mobility_value", "mobility_unit", "carrier_type", "mobility_observations"))
    expected_priority = {
        r["paper_id"] for r in candidates
        if (r["screening_state"] == "likely_contains_mobility" or r["evidence_state"] == "likely_contains_mobility" or r.get("extraction_review_required") is True)
        and RANK[r["evidence_state"]] < 2
    }
    assert expected_priority == {r["paper_id"] for r in priority}, "Priority export disagrees with evidence state"
    report = (root / "reports/coverage_report.md").read_text(encoding="utf8")
    for material in (*MATERIAL_CLASSES, "unassigned"):
        members = [r for r in candidates if material in (r.get("material_classes") or [r.get("material_class") or "unassigned"])]
        supported = sum(material in MATERIAL_CLASSES and r.get("material_class_confidence") == "metadata_signal" and r.get("review_material_class") is not True for r in members)
        likely = sum(r["screening_state"] == "likely_contains_mobility" or RANK[r["evidence_state"]] >= 1 for r in members)
        expected_row = f"| {material} | {len(members)} | {supported} | {likely} | {sum(r['evidence_state']=='confirmed_numeric_mobility' for r in members)} | {sum(r['evidence_state']=='verified_evidence' for r in members)} | {sum(r['local_match_status']=='matched' for r in members)} | {sum(r['local_match_status'] in {'matched','not_found_in_scanned_roots'} for r in members)} |"
        assert expected_row in report, f"Coverage counts disagree for {material}"
    source_hashes_checked = 0
    if source_manifest:
        manifest = read_json(source_manifest, {})
        assert manifest.get("source_sha256"), "Source hash manifest is empty"
        for name, expected_hash in manifest["source_sha256"].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected_hash, "Source file changed"
            source_hashes_checked += 1
    summary = read_json(root / "reports/run_summary.json", {})
    assert summary["candidate_count"] == len(candidates)
    assert summary["priority_missing_count"] == len(priority)
    return {"passed": True, "candidate_count": len(candidates), "priority_count": len(priority),
            "evidence_states": dict(Counter(r["evidence_state"] for r in candidates)),
            "normalized_records_checked": normalized_count, "source_hashes_checked": source_hashes_checked,
            "pdf_matched_papers": sum(r["local_match_status"] == "matched" for r in candidates),
            "provider_record_counts": dict(Counter(p for r in candidates for p in r["source_provenance"]))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.root.resolve(), args.source_manifest), ensure_ascii=False, indent=2))
