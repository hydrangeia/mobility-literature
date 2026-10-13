from __future__ import annotations

import re
import unicodedata
import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable


def normalize_doi(value: Any) -> str:
    if not value:
        return ""
    doi = str(value).strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi\s*:\s*", "", doi, flags=re.I)
    doi = doi.rstrip(" .;,)").lower()
    return doi if re.fullmatch(r"10\.\d{4,9}/\S+", doi) else ""


def normalize_title(value: Any) -> str:
    if not value:
        return ""
    title = unicodedata.normalize("NFKC", str(value)).casefold()
    title = re.sub(r"[^\w]+", " ", title, flags=re.UNICODE)
    return " ".join(title.split())


def first_author(authors: Any) -> str:
    if not authors:
        return ""
    if isinstance(authors, str):
        return authors.split(";")[0].split(",")[0].strip()
    if isinstance(authors, Iterable):
        first = next(iter(authors), "")
        if isinstance(first, dict):
            return str(first.get("name") or first.get("display_name") or first.get("author") or "")
        return str(first)
    return str(authors)


def paper_key(record: dict[str, Any]) -> str:
    """Return the strongest available identity; avoid merging on title alone."""
    keys = _paper_keys(record)
    return keys[0] if keys else ""


def _paper_keys(record: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    doi = normalize_doi(record.get("doi"))
    if doi:
        keys.append(f"doi:{doi}")

    provider_ids = record.get("provider_ids") if isinstance(record.get("provider_ids"), dict) else {}
    for provider in ("openalex", "semantic_scholar", "crossref"):
        value = record.get(f"{provider}_id") or provider_ids.get(provider)
        if value:
            keys.append(f"{provider}:{str(value).strip().casefold()}")

    title = normalize_title(record.get("title"))
    year = str(record.get("year") or "").strip()
    author = normalize_title(first_author(record.get("authors")))
    if title and year and author:
        keys.append(f"tya:{title}|{year}|{author}")
    if not keys and record.get("paper_id"):
        keys.append(str(record["paper_id"]))
    if not keys and title:
        # Keep unresolved title-only records distinct unless their full metadata
        # fingerprint is identical; a title by itself is not a safe identity.
        fingerprint_source = {
            key: value for key, value in record.items()
            if key not in {"query_provenance", "source_provenance", "metadata_conflicts"}
        }
        fingerprint = json.dumps(fingerprint_source, ensure_ascii=False, sort_keys=True, default=str)
        keys.append("unresolved:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest())
    return list(dict.fromkeys(keys))


def merge_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for source in records:
        row = deepcopy(source)
        row["doi"] = normalize_doi(row.get("doi"))
        if "material_classes" not in row and row.get("material_class") not in (None, "", "unassigned"):
            row["material_classes"] = [row["material_class"]]
        row_keys = _paper_keys(row)
        provider_ids = row.get("provider_ids") if isinstance(row.get("provider_ids"), dict) else {}
        has_provider_id = any(row.get(f"{provider}_id") or provider_ids.get(provider)
                              for provider in ("openalex", "semantic_scholar", "crossref"))
        has_title_author_key = bool(normalize_title(row.get("title")) and row.get("year") and first_author(row.get("authors")))
        if not row["doi"] and not has_provider_id and not has_title_author_key and row.get("title"):
            row["possible_duplicate_review"] = True
        if not row_keys:
            continue
        matches = list(dict.fromkeys(aliases[key] for key in row_keys if key in aliases))
        # Distinct DOI records stay distinct even if their titles/authors match.
        matches = [key for key in matches if not (row["doi"] and merged[key].get("doi")
                   and row["doi"] != merged[key]["doi"])]
        canonical_key = matches[0] if matches else row_keys[0]
        if canonical_key not in merged:
            merged[canonical_key] = row
            for key in row_keys:
                aliases[key] = canonical_key
            continue
        target = merged[canonical_key]
        # A bridging provider record may connect two previously separate rows.
        for other_key in matches[1:]:
            _merge_into(target, merged.pop(other_key))
            for alias, owner in list(aliases.items()):
                if owner == other_key:
                    aliases[alias] = canonical_key
        _merge_into(target, row)
        for key in _paper_keys(target) + row_keys:
            aliases[key] = canonical_key
    result = list(merged.values())
    for row in result:
        row["paper_id"] = paper_key(row)
    return result


def _merge_into(target: dict[str, Any], row: dict[str, Any]) -> None:
    state_rank = {"candidate": 0, "likely_contains_mobility": 1,
                  "confirmed_numeric_mobility": 2, "verified_evidence": 3}
    incoming_rank = state_rank.get(row.get("evidence_state"), 0)
    current_rank = state_rank.get(target.get("evidence_state"), 0)
    for name, value in row.items():
        if value in (None, "", [], {}):
            continue
        if name == "provider_ids" and isinstance(value, dict):
            ids = dict(target.get(name) or {}) if isinstance(target.get(name), dict) else {}
            for provider, provider_id in value.items():
                if provider_id and not ids.get(provider):
                    ids[provider] = provider_id
            target[name] = ids
        elif name in ("query_provenance", "source_provenance", "material_classes", "query_material_classes",
                      "mobility_observations", "import_references", "publication_type", "raw_source"):
            target[name] = _union(target.get(name), value)
        elif name in ("evidence_state", "screening_state"):
            if state_rank.get(value, 0) > state_rank.get(target.get(name), 0):
                target[name] = value
        elif name in ("mobility_value", "mobility_unit", "carrier_type", "method", "temperature", "direction",
                      "evidence_quote", "evidence_location", "source_pdf", "material", "sample",
                      "experimental_or_theoretical", "conditions") and incoming_rank > current_rank:
            target[name] = value
        elif name in ("citation_counts", "metadata_conflicts") and isinstance(value, dict):
            existing = target.get(name) if isinstance(target.get(name), dict) else {}
            target[name] = {**existing, **value}
        elif not target.get(name):
            target[name] = value
        elif target[name] != value and name in ("title", "year", "venue", "doi"):
            conflicts = target.get("metadata_conflicts")
            if not isinstance(conflicts, dict):
                conflicts = target["metadata_conflicts"] = {}
            conflicts[name] = _union(conflicts.get(name), [target[name], value])


def _union(current: Any, incoming: Any) -> list[Any]:
    values = []
    for value in [*(current if isinstance(current, list) else ([current] if current else [])),
                  *(incoming if isinstance(incoming, list) else [incoming])]:
        if value not in values:
            values.append(value)
    return values
