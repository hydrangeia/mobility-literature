from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from ..http import JsonHttpClient


BASE = "https://api.crossref.org/works"


class Crossref:
    def __init__(self, client: JsonHttpClient, mailto: str = ""):
        self.client = client
        self.mailto = mailto

    def by_doi(self, doi: str) -> dict[str, Any] | None:
        doi = str(doi or "").strip()
        if not doi:
            return None
        url = self._url(f"{BASE}/{quote(doi, safe='')}")
        try:
            payload = self.client.get("crossref", url)
        except Exception:
            return None
        item = (payload.get("message") or {}) if isinstance(payload, dict) else {}
        return _normalize(item) if item.get("title") else None

    def search_title(self, title: str) -> dict[str, Any] | None:
        title = str(title or "").strip()
        if not title:
            return None
        params: dict[str, str] = {"query.bibliographic": title, "rows": "1"}
        if self.mailto:
            params["mailto"] = self.mailto
        url = f"{BASE}?{urlencode(params)}"
        try:
            payload = self.client.get("crossref", url)
        except Exception:
            return None
        items = (payload.get("message") or {}).get("items", []) if isinstance(payload, dict) else []
        return _normalize(items[0]) if items else None

    def _url(self, base: str) -> str:
        return base + ("?" + urlencode({"mailto": self.mailto}) if self.mailto else "")


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    authors = item.get("author") or []
    title = item.get("title") or [""]
    container = item.get("container-title") or [""]
    published = (
        item.get("published-print") or item.get("published-online")
        or item.get("issued") or item.get("published") or {}
    )
    date_parts = published.get("date-parts") or [[None]]
    return {
        "doi": item.get("DOI", ""),
        "title": title[0] if title else "",
        "year": (date_parts[0][0] if date_parts and date_parts[0] else None),
        "venue": container[0] if container else "",
        "abstract": item.get("abstract", ""),
        "authors": [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in authors],
        "citation_count": item.get("is-referenced-by-count"),
        "landing_url": item.get("URL", ""),
        "provider_ids": {"crossref": item.get("DOI", "")},
        "source_provenance": ["crossref"],
    }
