from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .config import Settings
from .importer import import_legacy_results
from .pipeline import discover


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        raw = record.getMessage()
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                payload.setdefault("level", record.levelname.lower())
                return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except json.JSONDecodeError:
            pass
        return json.dumps({"level": record.levelname.lower(), "logger": record.name,
                           "event": "log", "message": raw}, ensure_ascii=False)


def _logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mobility-literature", description="Find and organize carrier-mobility papers.")
    commands = parser.add_subparsers(dest="command", required=True)

    discover_parser = commands.add_parser("discover", help="search provider metadata and update candidate/report outputs")
    discover_parser.add_argument("--max-results-per-query", type=int, default=500)
    discover_parser.add_argument("--enrich-limit", type=int, default=25, help="balanced Semantic Scholar seed count; 0 disables it")
    discover_parser.add_argument("--neighbors-per-seed", type=int, default=10, help="per relation, per selected seed; 0 disables citation expansion")
    discover_parser.add_argument("--crossref-limit", type=int, default=100, help="maximum records to validate; 0 disables it")
    discover_parser.add_argument("--no-semantic-scholar", action="store_true")
    discover_parser.add_argument("--no-crossref", action="store_true")
    discover_parser.add_argument("--imports", nargs="+", type=Path, help="explicit normalized import files; otherwise data/imported files are used")
    discover_parser.add_argument("--inventory", nargs="+", type=Path, help="explicit existing download metadata CSVs")
    discover_parser.add_argument("--pdf-root", action="append", type=Path, help="match PDF filenames only in this designated root; repeat for multiple roots")
    discover_parser.add_argument("--remote-pdf-manifest", type=Path, help="read a filename-only remote PDF inventory from designated roots")
    discover_parser.add_argument("--refresh-enrichment", action="store_true", help="refresh cached Semantic Scholar/Crossref responses")

    import_parser = commands.add_parser("import", help="read explicit legacy extraction files into a new normalized file")
    import_parser.add_argument("inputs", nargs="+", help="explicit files or directories; source files are left untouched")
    import_parser.add_argument("--output", default="data/imported/normalized_mobility_import.csv")
    import_parser.add_argument("--format", choices=("csv", "jsonl"), default=None)

    status_parser = commands.add_parser("status", help="show existing exports and resume state without contacting APIs")
    status_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_environment(Path.cwd())
    try:
        if args.command == "discover":
            result = discover(
                settings,
                max_results_per_query=args.max_results_per_query,
                enrich_limit=args.enrich_limit,
                neighbors_per_seed=args.neighbors_per_seed,
                crossref_limit=args.crossref_limit,
                use_semantic_scholar=not args.no_semantic_scholar,
                use_crossref=not args.no_crossref,
                import_paths=args.imports,
                inventory_paths=args.inventory,
                pdf_roots=args.pdf_root,
                remote_pdf_manifest=args.remote_pdf_manifest,
                refresh_enrichment=args.refresh_enrichment,
            )
            return 0 if not result["failed_query_count"] else 2
        if args.command == "import":
            count = import_legacy_results(args.inputs, args.output, output_format=args.format)
            logging.getLogger("mobility_literature.cli").info(json.dumps({
                "event": "import_complete", "records": count, "output": str(Path(args.output).resolve())
            }, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "status":
            result = _status(settings)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
    except FileExistsError as exc:
        logging.getLogger("mobility_literature.cli").error(json.dumps({
            "event": "output_exists", "message": "Output already exists; choose a new path to preserve it.",
            "path": str(exc.filename or exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        logging.getLogger("mobility_literature.cli").error(json.dumps({
            "event": "command_failed", "error_type": type(exc).__name__,
            "message": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2
    parser.print_help()
    return 2


def _status(settings: Settings) -> dict[str, Any]:
    report = settings.reports_dir / "coverage_report.md"
    candidates = settings.data_dir / "candidate_papers.csv"
    priority = settings.data_dir / "priority_missing_papers.csv"
    checkpoints = list((settings.checkpoint_dir / "openalex").glob("*.json")) if (settings.checkpoint_dir / "openalex").exists() else []
    return {
        "project_root": str(settings.root),
        "candidate_csv_exists": candidates.exists(),
        "priority_csv_exists": priority.exists(),
        "coverage_report_exists": report.exists(),
        "openalex_query_checkpoints": len(checkpoints),
        "openalex_api_key_configured": bool(settings.openalex_api_key),
        "semantic_scholar_api_key_configured": bool(settings.semantic_scholar_api_key),
        "crossref_mailto_configured": bool(settings.crossref_mailto),
        "api_keys_written_to_disk": False,
    }
