"""Small OpenAlex works client for resumable literature discovery.

The provider returns bibliographic candidate records only. OpenAlex search
matches are not evidence that a paper reports a numerical carrier mobility;
that decision belongs to the later screening and evidence-extraction stages.

Cursor state is query-specific. Persist ``OpenAlexPage.next_cursor`` together
with the search/filter parameters and pass it back as ``cursor`` to resume.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping, Sequence


LOGGER = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://api.openalex.org/works"
_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class OpenAlexError(RuntimeError):
    """A request or response failure with machine-readable context."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        endpoint: str = DEFAULT_BASE_URL,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        # Keep request details out of errors so credentials never appear there.
        self.endpoint = endpoint

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": "openalex",
            "message": str(self),
            "status_code": self.status_code,
            "retryable": self.retryable,
            "endpoint": self.endpoint,
        }


@dataclass(frozen=True)
class OpenAlexPage:
    """One normalized page and the cursor needed to request the next page."""

    records: list[dict[str, Any]]
    cursor: str
    next_cursor: str | None
    total_count: int | None


EventCallback = Callable[[Mapping[str, Any]], None]
CheckpointCallback = Callable[[str | None], None]


def _abstract_from_inverted_index(index: Any) -> str | None:
    """Rebuild OpenAlex's abstract representation when available."""
    if not isinstance(index, dict):
        return None

    positioned_words: list[tuple[int, str]] = []
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                positioned_words.append((position, word))

    if not positioned_words:
        return None
    positioned_words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned_words)


def _canonical_doi(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    doi = value.strip()
    prefixes = (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    )
    for prefix in prefixes:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip().lower() or None


def _compact_author(ship: Any) -> dict[str, Any] | None:
    if not isinstance(ship, dict):
        return None
    author = ship.get("author") if isinstance(ship.get("author"), dict) else {}
    institutions = ship.get("institutions")
    normalized_institutions: list[dict[str, Any]] = []
    if isinstance(institutions, list):
        for institution in institutions:
            if not isinstance(institution, dict):
                continue
            normalized_institutions.append(
                {
                    "id": institution.get("id"),
                    "name": institution.get("display_name"),
                    "ror": institution.get("ror"),
                    "country_code": institution.get("country_code"),
                }
            )
    return {
        "id": author.get("id"),
        "name": author.get("display_name"),
        "orcid": author.get("orcid"),
        "author_position": ship.get("author_position"),
        "institutions": normalized_institutions,
    }


def normalize_work(work: Mapping[str, Any], *, search_query: str | None = None) -> dict[str, Any]:
    """Normalize an OpenAlex work without assigning unsupported evidence claims."""
    ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
    doi_value = ids.get("doi") or work.get("doi")
    primary_location = work.get("primary_location")
    if not isinstance(primary_location, dict):
        primary_location = {}
    source = primary_location.get("source")
    if not isinstance(source, dict):
        source = {}
    open_access = work.get("open_access")
    if not isinstance(open_access, dict):
        open_access = {}

    authorships = work.get("authorships")
    authors: list[dict[str, Any]] = []
    if isinstance(authorships, list):
        for ship in authorships:
            author = _compact_author(ship)
            if author is not None:
                authors.append(author)

    topics = work.get("topics") if isinstance(work.get("topics"), list) else []
    normalized_topics = [
        {
            "id": topic.get("id"),
            "name": topic.get("display_name"),
            "score": topic.get("score"),
            "domain": (topic.get("domain") or {}).get("display_name")
            if isinstance(topic.get("domain"), dict)
            else None,
            "field": (topic.get("field") or {}).get("display_name")
            if isinstance(topic.get("field"), dict)
            else None,
        }
        for topic in topics
        if isinstance(topic, dict)
    ]

    keywords_raw = work.get("keywords")
    keywords = []
    if isinstance(keywords_raw, list):
        for keyword in keywords_raw:
            if isinstance(keyword, dict):
                keywords.append(
                    {
                        "id": keyword.get("id"),
                        "name": keyword.get("display_name"),
                        "score": keyword.get("score"),
                    }
                )
            elif isinstance(keyword, str):
                keywords.append({"id": None, "name": keyword, "score": None})

    raw_abstract = work.get("abstract")
    abstract = (
        raw_abstract
        if isinstance(raw_abstract, str)
        else _abstract_from_inverted_index(work.get("abstract_inverted_index"))
    )
    location_source = source or {}

    return {
        "source": "openalex",
        "openalex_id": work.get("id"),
        "doi": _canonical_doi(doi_value),
        "title": work.get("display_name") or work.get("title"),
        "abstract": abstract,
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "work_type": work.get("type"),
        "language": work.get("language"),
        "authors": authors,
        "author_names": [author["name"] for author in authors if author.get("name")],
        "primary_location": {
            "landing_page_url": primary_location.get("landing_page_url"),
            "pdf_url": primary_location.get("pdf_url"),
            "source_id": location_source.get("id"),
            "source_name": location_source.get("display_name"),
            "source_type": location_source.get("type"),
            "is_oa": primary_location.get("is_oa"),
        },
        "open_access": {
            "is_oa": open_access.get("is_oa"),
            "status": open_access.get("oa_status"),
            "url": open_access.get("oa_url"),
        },
        "topics": normalized_topics,
        "keywords": keywords,
        "cited_by_count": work.get("cited_by_count"),
        "referenced_work_count": work.get("referenced_works_count"),
        "referenced_works": work.get("referenced_works") if isinstance(work.get("referenced_works"), list) else [],
        "biblio": work.get("biblio") if isinstance(work.get("biblio"), dict) else {},
        "search_query": search_query,
        # Search results remain unreviewed candidates; no mobility value is inferred.
        "screening_state": "candidate",
        "screening_confidence": None,
        "mobility_evidence_status": "candidate",
        "evidence_locations": [],
    }


class OpenAlexClient:
    """Dependency-light client for OpenAlex Works search and cursor pagination."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "OPENALEX_API_KEY",
        mailto_env: str = "OPENALEX_MAILTO",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 4,
        backoff_base_seconds: float = 0.75,
        backoff_cap_seconds: float = 30.0,
        user_agent: str = "mobility-literature/0.1 (OpenAlex discovery provider)",
        event_callback: EventCallback | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        parsed_base_url = urllib.parse.urlsplit(base_url)
        if parsed_base_url.query or parsed_base_url.fragment:
            raise ValueError("base_url must not include query parameters or a fragment")
        configured_api_key = os.environ.get(api_key_env, "") if api_key is None else api_key
        self.api_key = str(configured_api_key).strip() or None
        self.mailto = os.environ.get(mailto_env, "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base_seconds = max(0.0, backoff_base_seconds)
        self.backoff_cap_seconds = max(0.0, backoff_cap_seconds)
        self.user_agent = user_agent
        self.event_callback = event_callback

    def _emit(self, name: str, **fields: Any) -> None:
        safe_event = {"provider": "openalex", "event": name, **fields}
        LOGGER.info("OpenAlex %s", name, extra={"event": name, "provider": "openalex", "fields": fields})
        if self.event_callback is not None:
            try:
                self.event_callback(safe_event)
            except Exception:
                LOGGER.exception("OpenAlex event callback failed", extra={"event": "openalex.callback_failed"})

    @staticmethod
    def _format_filters(filters: str | Sequence[str] | Mapping[str, Any] | None) -> str | None:
        if filters is None:
            return None
        if isinstance(filters, str):
            return filters.strip() or None
        if isinstance(filters, Mapping):
            parts = [f"{key}:{value}" for key, value in filters.items() if value is not None]
            return ",".join(parts) or None
        return ",".join(str(value) for value in filters if str(value).strip()) or None

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value.strip()))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def _wait_before_retry(self, retry_number: int, retry_after: str | None = None) -> float:
        exponential = self.backoff_base_seconds * (2 ** max(0, retry_number - 1))
        delay = min(self.backoff_cap_seconds, exponential)
        if delay > 0:
            delay = min(self.backoff_cap_seconds, delay + random.uniform(0.0, min(0.5, delay * 0.25)))
        advertised = self._parse_retry_after(retry_after)
        if advertised is not None:
            delay = max(delay, advertised)
        time.sleep(delay)
        return delay

    def _report_error(self, error: OpenAlexError, *, attempt: int, **fields: Any) -> None:
        details = error.as_dict()
        self._emit("request_failed", attempt=attempt, error=details, **fields)

    @staticmethod
    def _make_query_id(params: Mapping[str, Any]) -> str:
        identity_params = {key: value for key, value in params.items() if key not in {"cursor", "per-page"}}
        safe_query_string = urllib.parse.urlencode(identity_params, doseq=True)
        return hashlib.sha256(safe_query_string.encode("utf-8")).hexdigest()[:16]

    def _request_json(self, params: Mapping[str, Any], *, query_id: str | None = None) -> dict[str, Any]:
        request_params: dict[str, Any] = dict(params)
        if self.mailto:
            request_params["mailto"] = self.mailto
        query_string = urllib.parse.urlencode(request_params, doseq=True)
        resolved_query_id = query_id or self._make_query_id(request_params)
        request_headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.api_key:
            # Keep credentials out of URLs, logs, cache keys, and exception text.
            request_headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}?{query_string}",
            headers=request_headers,
            method="GET",
        )

        for attempt in range(1, self.max_retries + 2):
            started_at = time.monotonic()
            self._emit(
                "request_started",
                attempt=attempt,
                query_id=resolved_query_id,
                query=params.get("search"),
                cursor=params.get("cursor"),
                per_page=params.get("per-page"),
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                try:
                    decoded = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    error = OpenAlexError("OpenAlex returned invalid JSON", endpoint=self.base_url)
                    self._report_error(
                        error,
                        attempt=attempt,
                        query_id=resolved_query_id,
                        retry_count=attempt - 1,
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                    )
                    raise error from None
                if not isinstance(decoded, dict):
                    error = OpenAlexError("OpenAlex response was not a JSON object", endpoint=self.base_url)
                    self._report_error(
                        error,
                        attempt=attempt,
                        query_id=resolved_query_id,
                        retry_count=attempt - 1,
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                    )
                    raise error
                self._emit(
                    "request_succeeded",
                    attempt=attempt,
                    query_id=resolved_query_id,
                    retry_count=attempt - 1,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                )
                return decoded
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                retryable = status in _RETRYABLE_STATUS_CODES
                if retryable and attempt <= self.max_retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    exc.close()
                    delay = self._wait_before_retry(attempt, retry_after)
                    self._emit(
                        "retry_scheduled",
                        attempt=attempt,
                        query_id=resolved_query_id,
                        status_code=status,
                        delay_seconds=delay,
                    )
                    continue
                error = OpenAlexError(
                    f"OpenAlex request failed with HTTP {status}",
                    status_code=status,
                    retryable=retryable,
                    endpoint=self.base_url,
                )
                self._report_error(
                    error,
                    attempt=attempt,
                    query_id=resolved_query_id,
                    retry_count=attempt - 1,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                )
                exc.close()
                raise error from None
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
                if attempt <= self.max_retries:
                    delay = self._wait_before_retry(attempt)
                    self._emit(
                        "retry_scheduled",
                        attempt=attempt,
                        query_id=resolved_query_id,
                        error_type=type(exc).__name__,
                        delay_seconds=delay,
                    )
                    continue
                error = OpenAlexError(
                    f"OpenAlex request failed after {attempt} attempt(s): {type(exc).__name__}",
                    retryable=True,
                    endpoint=self.base_url,
                )
                self._report_error(
                    error,
                    attempt=attempt,
                    query_id=resolved_query_id,
                    retry_count=attempt - 1,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                )
                raise error from None

        # The loop either returns or raises; this is a defensive guard.
        raise OpenAlexError("OpenAlex request exhausted retries", retryable=True, endpoint=self.base_url)

    def fetch_page(
        self,
        query: str | None = None,
        *,
        filters: str | Sequence[str] | Mapping[str, Any] | None = None,
        cursor: str = "*",
        per_page: int = 100,
        params: Mapping[str, Any] | None = None,
        query_id: str | None = None,
    ) -> OpenAlexPage:
        """Fetch and normalize one page. OpenAlex supports up to 100/page."""
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("cursor must be a non-empty string; use '*' for a new search")
        request_params: dict[str, Any] = {"per-page": per_page, "cursor": cursor}
        if query and query.strip():
            request_params["search"] = query.strip()
        filter_value = self._format_filters(filters)
        if filter_value:
            request_params["filter"] = filter_value
        for key, value in (params or {}).items():
            if key in {"api_key", "mailto", "cursor", "per-page", "search", "filter"}:
                raise ValueError(f"params may not override reserved OpenAlex parameter: {key}")
            if value is not None:
                request_params[key] = value

        resolved_query_id = query_id or self._make_query_id(request_params)
        payload = self._request_json(request_params, query_id=resolved_query_id)
        results = payload.get("results")
        if not isinstance(results, list):
            error = OpenAlexError("OpenAlex response did not contain a results list", endpoint=self.base_url)
            self._report_error(error, attempt=1, query_id=resolved_query_id, retry_count=0)
            raise error
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        next_cursor = meta.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            next_cursor = None
        count = meta.get("count")
        total_count = count if isinstance(count, int) and not isinstance(count, bool) else None
        records = [normalize_work(work, search_query=query) for work in results if isinstance(work, dict)]
        self._emit(
            "page_received",
            query_id=resolved_query_id,
            cursor=cursor,
            next_cursor_available=next_cursor is not None,
            record_count=len(records),
            total_count=total_count,
        )
        return OpenAlexPage(records=records, cursor=cursor, next_cursor=next_cursor, total_count=total_count)

    def iter_pages(
        self,
        query: str | None = None,
        *,
        filters: str | Sequence[str] | Mapping[str, Any] | None = None,
        cursor: str = "*",
        per_page: int = 100,
        params: Mapping[str, Any] | None = None,
        query_id: str | None = None,
        checkpoint_callback: CheckpointCallback | None = None,
        max_pages: int | None = None,
    ) -> Iterable[OpenAlexPage]:
        """Yield pages in cursor order and optionally persist resume checkpoints.

        ``checkpoint_callback`` runs after the consumer has handled a yielded
        page, so applications can commit its records before saving the next
        cursor. A crash before the checkpoint may replay a page, so downstream
        storage should deduplicate by DOI/OpenAlex ID.
        """
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1 when provided")
        active_cursor = cursor
        seen_cursors: set[str] = set()
        page_number = 0
        while active_cursor:
            if active_cursor in seen_cursors:
                raise OpenAlexError("OpenAlex repeated a cursor; stopping to prevent an infinite loop", endpoint=self.base_url)
            seen_cursors.add(active_cursor)
            page = self.fetch_page(
                query,
                filters=filters,
                cursor=active_cursor,
                per_page=per_page,
                params=params,
                query_id=query_id,
            )
            page_number += 1
            yield page
            if checkpoint_callback is not None:
                checkpoint_callback(page.next_cursor)
            if page.next_cursor is None:
                break
            if page.next_cursor in seen_cursors:
                raise OpenAlexError("OpenAlex repeated a cursor; stopping to prevent an infinite loop", endpoint=self.base_url)
            if max_pages is not None and page_number >= max_pages:
                break
            active_cursor = page.next_cursor

    def iter_records(self, *args: Any, **kwargs: Any) -> Iterable[dict[str, Any]]:
        """Yield normalized candidate records; use ``iter_pages`` to persist cursors."""
        for page in self.iter_pages(*args, **kwargs):
            yield from page.records
