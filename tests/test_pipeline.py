"""Regression checks for evidence safety, durable resume, and real API shapes."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mobility_literature.classify import screen
from mobility_literature.config import Settings
from mobility_literature.corpus import match_local_pdfs, match_remote_manifest
from mobility_literature.evidence import apply_local_imports, rescreen
from mobility_literature.importer import normalize_legacy_record, revalidate_normalized_record, import_legacy_results
from mobility_literature.materials import screen_material
from mobility_literature.normalize import merge_records
from mobility_literature.pipeline import _discover_query, _apply_enrichment, _coverage_report
from mobility_literature.providers.openalex import OpenAlexPage
from mobility_literature.providers.semantic_scholar import SemanticScholar
from mobility_literature.storage import append_jsonl, read_jsonl, read_csv, write_csv_atomic


class RegressionTests(unittest.TestCase):
    def test_mixed_ionic_conductivity_not_electronic_mobility(self):
        self.assertEqual(screen("Proton mobility and electronic conductivity in MOFs")["screening_state"], "candidate")
        self.assertEqual(screen("Proton mobility and hole mobility in MOFs")["screening_state"], "likely_contains_mobility")
        self.assertEqual(screen("Electronic conductivity of a COF")["screening_state"], "candidate")
        self.assertEqual(screen("Ionic carrier mobility in MOFs")["screening_state"], "candidate")

    def test_materials_hybrid_vs_inorganic(self):
        row = screen_material("Carrier mobility in all-inorganic CsPbBr3 perovskites", "", "hybrid_perovskite")
        self.assertNotIn("hybrid_perovskite", row["material_classes"])
        self.assertIn("hybrid_perovskite", row["query_material_classes"])
        self.assertEqual(screen_material("Mobility in methylammonium lead iodide perovskite")["material_class"], "hybrid_perovskite")

    def test_importer_selected_domain_and_units(self):
        def state(raw):
            return normalize_legacy_record(raw, "fixture.csv", 2)["status"]
        self.assertEqual(state({"electron_density": "1e18", "property": "mobility", "value": "3", "unit": "cm2/(V s)"}), "likely_contains_mobility")
        self.assertEqual(state({"electron_mobility": "3", "unit": "cm2/(V s)", "conductivity": "5"}), "confirmed_numeric_mobility")
        self.assertEqual(normalize_legacy_record({"electron_mobility":"3","unit":"cm2/(V s)"},"fixture.csv",2)["carrier_type"],"electron")
        self.assertEqual(state({"mobility": "3", "carrier": "electron", "unit": "cm2/s"}), "likely_contains_mobility")
        self.assertEqual(state({"property": "proton mobility", "value": "3", "unit": "cm2/(V s)"}), "candidate")

    def test_verified_requires_quote_value_and_location(self):
        raw = {"mobility": "3", "unit": "cm2/(V s)", "carrier": "electron", "status": "verified", "evidence_quote": "Electron mobility was 3 cm2/(V s).", "evidence_location": "Table S2"}
        self.assertEqual(normalize_legacy_record(raw, "fixture.csv", 2)["status"], "verified_evidence")
        raw["evidence_location"] = "SI"
        self.assertEqual(normalize_legacy_record(raw, "fixture.csv", 2)["status"], "confirmed_numeric_mobility")
        raw.update(mobility="3 x 10^5", evidence_quote="Electron mobility was 3 x 10^6 cm2/(V s).", evidence_location="Table S2")
        self.assertEqual(normalize_legacy_record(raw,"fixture.csv",2)["status"],"confirmed_numeric_mobility")
        raw["evidence_quote"]="Electron mobility was 3e5 cm2/(V s)."
        self.assertEqual(normalize_legacy_record(raw,"fixture.csv",2)["status"],"verified_evidence")

    def test_generic_source_carrier_revalidation_is_stable(self):
        raw={"mobility":"3","unit":"cm2/(V s)","quote":"The carrier mobility was 3 cm2/(V s)."}
        normalized=normalize_legacy_record(raw,"fixture.csv",2)
        self.assertEqual(normalized["carrier_type"],"carrier")
        self.assertEqual(revalidate_normalized_record(normalized)["status"],normalized["status"])

    def test_removed_import_clears_stale_generated_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            rows=[{"doi":"10.1234/a","screening_state":"candidate","evidence_state":"verified_evidence","mobility_value":"3","carrier_type":"electron","mobility_observations":[{"record_id":"old","status":"verified_evidence"}]}]
            apply_local_imports(Path(temp),rows)
            self.assertEqual(rows[0]["evidence_state"],"candidate")
            self.assertNotIn("mobility_value",rows[0])

    def test_metadata_rescreen_keeps_supported_likely_observation(self):
        row={"title":"Charge transport in a framework","evidence_state":"likely_contains_mobility","mobility_observations":[{"status":"likely_contains_mobility"}]}
        rescreen(row)
        self.assertEqual(row["evidence_state"],"likely_contains_mobility")

    def test_imported_evidence_persists_and_unmatched_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/"source.json"
            source.write_text(json.dumps([
                {"doi": "10.1234/a", "title": "Paper A", "mobility": "3", "carrier": "electron", "unit": "cm2/(V s)"},
                {"doi": "10.1234/b", "title": "Paper B", "mobility": "4", "carrier": "hole", "unit": "cm2/(V s)"},
            ]))
            dest = root/"data/imported/normalized.csv"
            import_legacy_results([source], dest)
            prior = [{"doi": "10.1234/a", "title": "Paper A", "evidence_state": "candidate"}]
            apply_local_imports(root, prior)
            merged = merge_records(prior)
            write_csv_atomic(root/"data/candidate_papers.csv", merged)
            saved = read_csv(root/"data/candidate_papers.csv")
            self.assertEqual(len(saved), 2)
            self.assertTrue(all(r["evidence_state"] == "confirmed_numeric_mobility" for r in saved))
            self.assertIn("| unassigned | 2 |", _coverage_report(saved, [], []))
            before = source.read_bytes()
            with self.assertRaises(FileExistsError):
                import_legacy_results([source], dest)
            self.assertEqual(before, source.read_bytes())

    def test_non_electronic_verified_cannot_promote(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); dest=root/"data/imported/normalized.csv"
            rows=[normalize_legacy_record({"doi":"10.1234/a","mobility":"3","carrier":"electron","unit":"cm2/(V s)"}, "one.csv", 2),
                  {"doi":"10.1234/a","mobility_value":"99","mobility_unit":"cm2/(V s)","carrier_type":"proton","is_electronic_mobility":"false","status":"verified_evidence","source_file":"bad.csv","source_row":1}]
            write_csv_atomic(dest,rows, list(dict.fromkeys(k for r in rows for k in r)))
            candidates=[{"doi":"10.1234/a","title":"Paper A"}]
            apply_local_imports(root,candidates)
            self.assertEqual(candidates[0]["evidence_state"],"confirmed_numeric_mobility")
            self.assertEqual(len(candidates[0]["mobility_observations"]),1)
            _apply_enrichment(candidates[0],{"abstract":"High electron mobility.", "provider_ids":{}},"crossref")
            self.assertEqual(candidates[0]["evidence_state"],"confirmed_numeric_mobility")

    def test_dedup_bridge_and_cross_class_provenance(self):
        rows=merge_records([{"doi":"10.1234/a","title":"A","material_class":"COF"},
                            {"openalex_id":"W1","title":"B"},
                            {"doi":"10.1234/a","openalex_id":"W1","material_class":"MOF"}])
        self.assertEqual(len(rows),1)
        self.assertEqual(set(rows[0]["material_classes"]),{"COF","MOF"})
        self.assertEqual(rows[0]["paper_id"],"doi:10.1234/a")
        self.assertEqual(len(merge_records([{"doi":"10.1234/a","title":"same","year":2000,"authors":["A"]},
                                            {"doi":"10.1234/b","title":"same","year":2000,"authors":["A"]}])),2)

    def test_truncated_tail_does_not_swallow_replayed_row(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"cache.jsonl"; p.write_text('{"doi":"10.')
            append_jsonl(p,[{"doi":"10.1234/a"}])
            self.assertEqual(read_jsonl(p),[{"doi":"10.1234/a"}])

    def test_resume_limit_and_query_revision(self):
        class Fake:
            def __init__(self): self.calls=[]
            def fetch_page(self,query,*,cursor,per_page,query_id):
                self.calls.append((query,cursor,per_page))
                start=int(cursor) if cursor!="*" else 0
                return OpenAlexPage(records=[{"doi":f"10.1234/{i}","title":f"Paper {i}"} for i in range(start,start+per_page)],cursor=cursor,next_cursor=str(start+per_page),total_count=1000)
        with tempfile.TemporaryDirectory() as temp, patch("mobility_literature.pipeline.time.sleep"):
            settings=Settings(root=Path(temp)); fake=Fake()
            rows,_,_=_discover_query(settings,fake,"COF","query","old query",150)
            self.assertEqual(len(rows),150)
            self.assertEqual([c[2] for c in fake.calls],[100,50])
            _discover_query(settings,fake,"COF","query","old query",150)
            self.assertEqual(len(fake.calls),2)
            rows,_,_=_discover_query(settings,fake,"COF","query","new query",1)
            self.assertEqual(len(rows),1)
            self.assertEqual(fake.calls[-1][1],"*")

    def test_s2_null_neighbors(self):
        class Fake:
            def get(self,*a,**k): return {"data":None}
        self.assertEqual(SemanticScholar(Fake()).neighbors("x","citations"),[])

    def test_csv_roundtrip_empty_collections_are_safe_on_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"candidates.csv"
            write_csv_atomic(p,[{"doi":"10.1234/a","title":"Paper A"}])
            rows=read_csv(p)
            merged=merge_records([*rows,{"doi":"10.1234/a","title":"Paper A revised"}])
            self.assertIsInstance(merged[0]["metadata_conflicts"],dict)
            self.assertIsInstance(merged[0]["mobility_observations"],list)
            _apply_enrichment(merged[0],{"title":"Another title"},"semantic_scholar")
            merged[0]["evidence_quote"]="Mobility source excerpt "*8000
            write_csv_atomic(p,merged)
            self.assertEqual(read_csv(p)[0]["evidence_quote"],merged[0]["evidence_quote"])

    def test_pdf_match_does_not_create_numeric_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/"10.1234_a.pdf").write_bytes(b"%PDF-placeholder")
            rows=[{"doi":"10.1234/a","title":"Paper A","evidence_state":"candidate"}]
            summary=match_local_pdfs(rows,[root])
            self.assertEqual(summary["matched_papers"],1)
            self.assertEqual(rows[0]["evidence_state"],"candidate")
            self.assertEqual(rows[0]["local_match_status"],"matched")

    def test_real_legacy_headers_and_ocr_review(self):
        raw={"mu_cm2Vs":"0.42","carrier":"hole","T_K":"300","exp_or_calc":"experimental","quote":"Hole mobility was 0.42 cm2/(V s)","location":"Table 2","verified":"Y","source_file":"/papers/paper.pdf"}
        good=normalize_legacy_record(raw,"results.csv",2)
        self.assertEqual(good["status"],"verified_evidence")
        self.assertEqual(good["temperature"],"300")
        self.assertEqual(good["source_pdf"],"/papers/paper.pdf")
        raw["审计_OCR或指数推断"]="Y"
        self.assertEqual(normalize_legacy_record(raw,"results.csv",2)["status"],"likely_contains_mobility")
        raw["carrier"]="unspecified"
        self.assertNotIn(normalize_legacy_record(raw,"results.csv",2)["status"],{"confirmed_numeric_mobility","verified_evidence"})

    def test_remote_manifest_availability_and_no_numeric_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"manifest.jsonl"
            append_jsonl(p,[{"server":"s141","root":"/papers","path":"/papers/10.1234_a.pdf"}])
            rows=[{"doi":"10.1234/a","evidence_state":"candidate","local_match_status":"not_checked"}]
            self.assertEqual(match_remote_manifest(rows,p)["matched_papers"],1)
            self.assertEqual(rows[0]["evidence_state"],"candidate")
            self.assertEqual(rows[0]["remote_pdf_paths"],["s141:/papers/10.1234_a.pdf"])


if __name__ == "__main__": unittest.main()
