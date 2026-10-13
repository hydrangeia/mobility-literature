from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    openalex_api_key: str = ""
    semantic_scholar_api_key: str = ""
    crossref_mailto: str = ""
    user_agent: str = "MobilityLiterature/0.1 (research metadata client)"
    timeout_seconds: int = 30
    retries: int = 5
    per_page: int = 100
    max_results_per_query: int = 500
    max_s2_enrich: int = 25
    max_s2_neighbors_per_seed: int = 10

    @classmethod
    def from_environment(cls, root: Path | None = None) -> "Settings":
        return cls(
            root=(root or Path.cwd()).resolve(),
            openalex_api_key=os.environ.get("OPENALEX_API_KEY", "").strip(),
            semantic_scholar_api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip(),
            crossref_mailto=os.environ.get("CROSSREF_MAILTO", "").strip(),
            user_agent=os.environ.get(
                "MOBILITY_LITERATURE_USER_AGENT",
                "MobilityLiterature/0.1 (research metadata client)",
            ).strip(),
        )

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def checkpoint_dir(self) -> Path:
        return self.data_dir / "checkpoints"

    @property
    def raw_metadata_dir(self) -> Path:
        return self.data_dir / "raw_metadata"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"
