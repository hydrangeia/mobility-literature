from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from ..http import JsonHttpClient


BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = (
    "paperId,externalIds,title,year,abstract,venue,publicationDate,citationCount,"
    "referenceCount,isOpenAccess,openAccessPdf,url,publicationTypes,authors"
)


class SemanticScholar:
    def __init__(self, client: JsonHttpClient, api_key: str = ""):
        self.client = client
        self.api_key = api_key

    def get_paper(self, identifier: str) -> dict[str, Any] | None:
        key = str(identifier or "").strip()
        if not key:
            return None
        query = urlencode({"fields": FIELDS})
        url = f"{BASE}/paper/{quote(key, safe='') }?{query}"
        try:
            payload = self.client.get("semantic_scholar", url, self._headers())
        except Exception:
            return None
        return _normalize(payload) if isinstance(payload, dict) and payload.get("paperId") else None

    def search_title(self, title: str, limit: int = 5) -> list[dict[str, Any]]:
        title = str(title or "").strip()
        if not title:
            return []
        query = urlencode({"query": title, "limit": max(1, min(10, int(limit))), "fields": FIELDS})
        url = f"{BASE}/paper/search?{query}"
        try:
            payload = self.client.get("semantic_scholar", url, self._headers())
        except Exception:
            return []
        rows = []
        for paper in (payload.get("data") or []) if isinstance(payload, dict) else []:
            if isinstance(paper, dict) and paper.get("paperId"):
                normalized = _normalize(paper)
                normalized["title_match_query"] = title
                rows.append(normalized)
        return rows

    def neighbors(self, paper_id: str, relation: str, limit: int = 30) -> list[dict[str, Any]]:
        if relation not in {"citations", "references"}:
            raise ValueError("relation must be citations or references")
        limit = max(1, min(100, int(limit)))
        query = urlencode({"fields": FIELDS, "limit": limit, "offset": 0})
        url = f"{BASE}/paper/{quote(str(paper_id), safe='')}/{relation}?{query}"
        try:
            payload = self.client.get("semantic_scholar", url, self._headers())
        except Exception:
            return []
        rows = []
        for item in (payload.get("data") or []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            record = item.get("citingPaper" if relation == "citations" else "citedPaper") or {}
            normalized = _normalize(record)
            if normalized.get("title"):
                normalized["citation_relation"] = relation
                normalized["citation_seed_id"] = paper_id
                rows.append(normalized)
        return rows

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}


def _normalize(paper: dict[str, Any]) -> dict[str, Any]:
    ids = paper.get("externalIds") or {}
    authors = paper.get("authors") or []
    return {
        "doi": ids.get("DOI", ""),
        "title": paper.get("title", ""),
        "year": paper.get("year"),
        "venue": paper.get("venue", ""),
        "abstract": paper.get("abstract", ""),
        "authors": [a.get("name", "") for a in authors if isinstance(a, dict)],
        "citation_count": paper.get("citationCount"),
        "reference_count": paper.get("referenceCount"),
        "is_open_access": paper.get("isOpenAccess"),
        "open_access_pdf_url": (paper.get("openAccessPdf") or {}).get("url", ""),
        "landing_url": paper.get("url", ""),
        "provider_ids": {"semantic_scholar": paper.get("paperId", "")},
        "source_provenance": ["semantic_scholar"],
        "publication_type": paper.get("publicationTypes") or [],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
