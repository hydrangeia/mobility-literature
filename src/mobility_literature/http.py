from __future__ import annotations

import hashlib
import json
import logging
import math
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


class JsonHttpClient:
    """Small cached JSON client with bounded retries and credential-safe logs."""

    def __init__(
        self,
        cache_dir: Path,
        user_agent: str,
        timeout: int = 30,
        retries: int = 5,
        cache_ttl_seconds: float = 7 * 24 * 60 * 60,
    ):
        if retries < 1:
            raise ValueError("retries must be at least 1")
        if not math.isfinite(cache_ttl_seconds) or cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must be a finite non-negative number")
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.logger = logging.getLogger("mobility_literature.http")
        self._last_request: dict[str, float] = {}
        self.stats: dict[str, dict[str, Any]] = {}

    def get(
        self,
        provider: str,
        url: str,
        headers: dict[str, str] | None = None,
        *,
        refresh_cache: bool = False,
    ) -> Any:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / f"{hashlib.sha256((provider + '|' + url).encode()).hexdigest()}.json"
        if not refresh_cache and cache_path.exists():
            try:
                age_seconds = max(0.0, time.time() - cache_path.stat().st_mtime)
                if age_seconds <= self.cache_ttl_seconds:
                    with cache_path.open("r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    stats = self._provider_stats(provider)
                    stats["cache_hit"] += 1
                    stats["last_status"] = "cache_hit"
                    self.logger.info(_event(provider, "cache_hit", attempt=0))
                    return payload
            except (OSError, json.JSONDecodeError):
                self._provider_stats(provider)["last_status"] = "cache_read_error"
                self.logger.warning(_event(provider, "cache_read_error", attempt=0))

        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        request_headers.update(headers or {})
        for attempt in range(1, self.retries + 1):
            self._pace(provider)
            started = time.monotonic()
            stats = self._provider_stats(provider)
            stats["request_attempt"] += 1
            retry_after = None
            try:
                request = urllib.request.Request(url, headers=request_headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                status = f"http_{exc.code}"
                stats["last_status"] = status
                retry_after = exc.headers.get("Retry-After")
                if exc.code not in (429, 500, 502, 503, 504) or attempt >= self.retries:
                    stats["failure"] += 1
                    self.logger.error(_event(provider, status, attempt, time.monotonic() - started))
                    exc.close()
                    raise
                exc.close()
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                status = type(exc).__name__
                stats["last_status"] = status
                if attempt >= self.retries:
                    stats["failure"] += 1
                    self.logger.error(_event(provider, status, attempt, time.monotonic() - started))
                    raise
            else:
                try:
                    _write_json_atomic(cache_path, payload)
                except OSError:
                    stats["failure"] += 1
                    stats["last_status"] = "cache_write_error"
                    self.logger.error(_event(provider, "cache_write_error", attempt, time.monotonic() - started))
                    raise
                stats["success"] += 1
                stats["last_status"] = "ok"
                self.logger.info(_event(provider, "ok", attempt, time.monotonic() - started))
                return payload

            stats["retry"] += 1
            self.logger.warning(_event(provider, status, attempt, time.monotonic() - started))
            time.sleep(_delay(attempt, retry_after))
        raise RuntimeError(f"{provider} request failed after retries")

    def _provider_stats(self, provider: str) -> dict[str, Any]:
        if provider not in self.stats:
            self.stats[provider] = {
                "cache_hit": 0,
                "request_attempt": 0,
                "success": 0,
                "retry": 0,
                "failure": 0,
                "last_status": None,
            }
        return self.stats[provider]

    def _pace(self, provider: str) -> None:
        # Conservative per-client pacing, especially for the shared S2 pool.
        interval = {"semantic_scholar": 1.0, "crossref": 0.15}.get(provider, 0.0)
        previous = self._last_request.get(provider)
        if previous is not None:
            wait = interval - (time.monotonic() - previous)
            if wait > 0:
                time.sleep(wait)
        self._last_request[provider] = time.monotonic()


def _write_json_atomic(path: Path, data: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False)
    temp.replace(path)


def _delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return max(0.2, min(60.0, float(retry_after)))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.2, min(60.0, (parsed - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(30.0, 0.75 * (2 ** (attempt - 1)))


def _event(provider: str, status: str, attempt: int, elapsed: float = 0.0) -> str:
    return json.dumps(
        {"event": "provider_request", "provider": provider, "status": status,
         "attempt": attempt, "elapsed_ms": round(elapsed * 1000)},
        ensure_ascii=False,
        sort_keys=True,
    )
