"""Import mobility extractions from legacy agent outputs.

The importer is intentionally conservative: it preserves source fields and
does not turn a conductivity, ionic/proton mobility, or diffusion result into
electronic carrier mobility. It writes to a new destination in exclusive mode
so an existing dataset is never silently replaced.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SUPPORTED_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".md", ".markdown", ".txt"}

OUTPUT_FIELDS = [
    "record_id",
    "paper_id",
    "identifier_type",
    "doi",
    "pmid",
    "openalex_id",
    "semantic_scholar_id",
    "title",
    "abstract",
    "year",
    "journal",
    "paper_url",
    "material",
    "material_domain",
    "sample",
    "material_class",
    "experimental_or_theoretical",
    "mobility_value",
    "mobility_value_numeric",
    "mobility_value_original",
    "mobility_value_low",
    "mobility_value_high",
    "mobility_value_normalized_cm2_Vs",
    "mobility_unit",
    "mobility_unit_original",
    "carrier_type",
    "mobility_domain",
    "is_electronic_mobility",
    "method",
    "conditions",
    "temperature",
    "direction",
    "evidence_quote",
    "evidence_location",
    "source_pdf",
    "status",
    "numeric_review_reason",
    "exclusion_reason",
    "source_file",
    "source_row",
    "raw_fields_json",
]

_ALIASES = {
    "doi": {"doi", "paperdoi", "digitalobjectidentifier"},
    "title": {"title", "papertitle", "articletitle", "publicationtitle"},
    "abstract": {"abstract", "summary"},
    "year": {"year", "publicationyear", "pubyear"},
    "journal": {"journal", "journalname", "venue"},
    "pmid": {"pmid", "pubmedid"},
    "openalex_id": {"openalex", "openalexid", "openalexworkid"},
    "semantic_scholar_id": {"semanticscholarid", "s2id", "s2paperid"},
    "paper_url": {"paperurl", "url", "landingpage", "articleurl"},
    "material": {"material", "materialname", "compound", "compoundname"},
    "material_domain": {"materialdomain"},
    "sample": {"sample", "samplename", "samplematerial", "sampleform", "specimen"},
    "material_class": {"materialclass", "materialcategory"},
    "experimental_or_theoretical": {
        "experimentalortheoretical", "exporcalc", "studytype", "researchtype", "approach", "studyapproach",
    },
    "mobility_value": {
        "mobility", "mobilityvalue", "mobilityvalues", "carriermobility",
        "electronmobility", "electronmobilityvalue", "holemobility", "holemobilityvalue",
        "ambipolarmobility", "ambipolarmobilityvalue", "electroncarriermobility", "holecarriermobility",
        "mobilityvalueoriginal", "mobilityvaluenormalizedcm2vs", "mucm2vs",
        "mu", "muvalue", "extractedmobility", "reportedmobility", "mobilityvalueraw",
    },
    "mobility_value_low": {"mulow", "mobilityvaluelow"},
    "mobility_value_high": {"muhigh", "mobilityvaluehigh"},
    "mobility_value_original": {"mobilityvalueoriginal"},
    "mobility_value_normalized_cm2_Vs": {"mobilityvaluenormalizedcm2vs"},
    "mobility_unit": {"mobilityunit", "mobilityunitoriginal", "mobilityunitnormalized", "unit", "units", "valueunit"},
    "mobility_unit_original": {"mobilityunitoriginal"},
    "carrier_type": {"carrier", "carriertype", "carrierspecies", "chargecarrier", "carrierpolarity"},
    "method": {"method", "measurementmethod", "calculationmethod", "mobilitymethod", "experimentalorcomputationalmethod", "technique"},
    "conditions": {"conditions", "measurementconditions", "calculationconditions", "experimentalconditions", "deviceconditions", "conditionthicknessphasepressuredoping", "environment"},
    "temperature": {"temperature", "temp", "measurementtemperature", "tk"},
    "direction": {"direction", "crystallographicdirection", "anisotropy", "transportdirection"},
    "evidence_quote": {"evidence", "evidencequote", "quote", "sourcequote", "supportingtext", "snippet"},
    "evidence_location": {
        "evidencelocation", "location", "page", "pages", "pdfpage", "sourcepage", "table", "tablename", "figure", "fig",
        "tableorfigure", "verbatimlocator",
        "sitable", "sitableid", "supplementarytable", "supplementaryfigure", "supportinginformationpage",
        "supportinginformationtable", "supportinginformationfigure", "supplementaryinformationpage",
        "supplementaryinformationtable", "supplementaryinformationfigure",
    },
    "source_pdf": {"sourcepdf", "pdffile", "pdfpath", "fulltextpath"},
}

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s<>\"']+", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_MOBILITY_RE = re.compile(r"\bmobilit(?:y|ies)\b", re.IGNORECASE)
_ELECTRONIC_RE = re.compile(r"\b(?:electron|electrons|hole|holes|ambipolar|electronic|electronic\s+carrier)\b", re.IGNORECASE)
_EXPLICIT_ELECTRONIC_MOBILITY_RE = re.compile(
    r"\b(?:electron|electrons|hole|holes|carrier|carriers|ambipolar|electronic)\s+"
    r"(?:charge\s+)?(?:carrier\s+)?mobilit(?:y|ies)\b"
    r"|\bmobilit(?:y|ies)\s+(?:of|for)\s+(?:electrons?|holes?|carriers?)\b",
    re.IGNORECASE,
)
_IONIC_RE = re.compile(
    r"\b(?:ionic|ion|ions|proton|protons|protonic|lithium|sodium|potassium|vacancy)\b",
    re.IGNORECASE,
)
_DIFFUSION_RE = re.compile(r"\b(?:diffusion|diffusivity|diffusion\s+coefficient|self[- ]diffusion)\b", re.IGNORECASE)
_CONDUCTIVITY_RE = re.compile(r"\b(?:electrical\s+)?conductivity\b|\bconductance\b", re.IGNORECASE)
_MOBILITY_UNIT_RE = re.compile(
    r"(?i)(?:cm|mm|m|um|μm|µm|nm)\s*(?:\^\s*2|²|2)\s*(?:/\s*\(?\s*v\s*(?:[·*]?\s*s)\s*\)?|\s*v\s*(?:\^\s*[-−⁻]?1|[-−⁻]?1)\s*s\s*(?:\^\s*[-−⁻]?1|[-−⁻]?1)?)"
)
_TRUTHY = {"1", "true", "yes", "y", "verified", "confirmed", "checked"}
_FALSEY = {"0", "false", "no", "n", "unverified", "not verified"}
_GENERIC_STUDY_TYPES = {
    "experimental", "experiment", "experimental study", "empirical", "measured", "measurement",
    "theoretical", "theory", "theoretical study", "computational", "computational study",
    "simulation", "simulated", "calculated", "first principles", "dft", "both",
    "experimental and theoretical", "theoretical and experimental", "experimental/theoretical",
    "theoretical/experimental", "experiment and theory", "experiment/theory",
}


def normalize_doi(value: Any) -> str:
    """Return a lowercase DOI without a resolver URL or trailing punctuation."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    match = _DOI_RE.search(text)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}").lower()


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _first(raw: Mapping[str, Any], aliases: set[str]) -> Any:
    for raw_key, value in raw.items():
        if _key(raw_key) in aliases and value not in (None, ""):
            return value
    return ""


def _canonical(raw: Mapping[str, Any], name: str) -> str:
    return _clean(_first(raw, _ALIASES[name]))


def _selected_mobility_value_field(raw: Mapping[str, Any]) -> tuple[str, str]:
    """Return the selected mobility value and its source header.

    Source-reported values take precedence over normalized derivatives. A
    unit-encoded legacy column is useful only when its cell is populated.
    """
    priority = (
        "mobilityvalueoriginal", "mucm2vs", "mobilityvalue", "mobility", "mobilityvalues",
        "electronmobilityvalue", "holemobilityvalue", "ambipolarmobilityvalue",
        "electronmobility", "holemobility", "ambipolarmobility", "carriermobility",
        "extractedmobility", "reportedmobility", "mobilityvalueraw",
        "mobilityvaluenormalizedcm2vs", "mu", "muvalue",
    )
    for desired in priority:
        for key, value in raw.items():
            if _key(key) == desired and value not in (None, ""):
                cleaned = _clean(value)
                if cleaned:
                    return cleaned, str(key)
    return "", ""


def _study_type_value(raw: Mapping[str, Any]) -> str:
    explicit = _canonical(raw, "experimental_or_theoretical")
    if explicit:
        return explicit
    for key in ("type", "category", "approach"):
        value = _clean(_first(raw, {_key(key)}))
        if value and " ".join(value.casefold().split()) in _GENERIC_STUDY_TYPES:
            return value
    return ""


def _material_class_value(raw: Mapping[str, Any]) -> str:
    explicit = _canonical(raw, "material_class")
    if explicit:
        return explicit
    # Generic category/class labels are ambiguous. Retain them as a material
    # class only when they are not a clear experimental/theoretical label.
    for key in ("category", "class"):
        value = _clean(_first(raw, {_key(key)}))
        if value and " ".join(value.casefold().split()) not in _GENERIC_STUDY_TYPES:
            return value
    return ""


def _direct_mobility_value(raw: Mapping[str, Any]) -> str:
    value, _header = _selected_mobility_value_field(raw)
    if value:
        return value
    # Some extraction tables pair a generic value column with a property label.
    property_value = _first(raw, {
        "property", "propertyname", "quantity", "quantityname", "metric", "observable",
        "observedproperty", "extractedproperty", "mobilityproperty", "valuetype",
    })
    if _MOBILITY_RE.search(_clean(property_value)):
        property_value = _clean(_first(raw, {"value", "result", "reportedvalue", "measurementvalue"}))
        if property_value:
            return property_value
    low = _clean(_first(raw, _ALIASES["mobility_value_low"]))
    high = _clean(_first(raw, _ALIASES["mobility_value_high"]))
    if low and high:
        return f"{low}–{high}"
    if low or high:
        return low or high
    return ""


def _numeric_tokens(value: str) -> list[str]:
    if not value:
        return []
    # Ignore powers in units such as cm^2 and V^-1. A range still produces
    # multiple value tokens and remains intact only in the raw value field.
    matches = []
    for match in _NUMBER_RE.finditer(value.replace(",", "")):
        prefix = value[max(0, match.start() - 2):match.start()]
        if "^" in prefix or "⁻" in prefix:
            continue
        matches.append(match.group(0))
    return matches


def _numeric_value(value: str) -> str:
    # Keep ranges and lists in their original field; expose a scalar only when
    # exactly one unambiguous number occurs in the dedicated mobility field.
    matches = _numeric_tokens(value)
    return matches[0] if len(matches) == 1 else ""


def _has_numeric(value: str) -> bool:
    return bool(_numeric_tokens(value))


def _normalize_unit(unit: str) -> str:
    text = unit.casefold()
    for old, new in (("²", "2"), ("¹", "1"), ("⁻", "-"), ("−", "-"), ("·", "*"), ("⋅", "*")):
        text = text.replace(old, new)
    return re.sub(r"[\s^(){}\[\]*]", "", text)


def _mobility_compatible_unit(unit: str) -> bool:
    normalized = _normalize_unit(unit)
    if not normalized:
        return False
    # Common equivalent forms: cm^2/(V s), cm^2 V^-1 s^-1, and their
    # SI/submultiple length variants. Diffusion units lack the voltage term.
    return bool(re.fullmatch(r"(?:cm|mm|m|um|μm|µm|nm)2(?:/v/?s|v-1s-1)", normalized))


def _selected_mobility_unit(raw: Mapping[str, Any], mobility_value: str) -> str:
    unit = _clean(_first(raw, {"mobilityunitoriginal"}))
    if not unit:
        unit = _clean(_first(raw, {"mobilityunit", "unit", "units", "valueunit", "mobilityunitnormalized"}))
    if unit:
        return unit
    _value, header = _selected_mobility_value_field(raw)
    normalized_header = _key(header)
    if normalized_header in {"mucm2vs", "mobilityvaluenormalizedcm2vs"}:
        return "cm^2/(V s)"
    match = _MOBILITY_UNIT_RE.search(mobility_value)
    return match.group(0).strip() if match else ""


def _has_precise_evidence_location(raw: Mapping[str, Any]) -> bool:
    # Structured locators are preferred. A PDF path or generic "SI" label is
    # not a precise location by itself.
    structured = {
        "page", "pages", "pdfpage", "sourcepage", "table", "tablename",
        "figure", "fig", "tableorfigure", "sitable", "sitableid", "supplementarytable",
        "supplementaryfigure", "supportinginformationpage", "supportinginformationtable",
        "supportinginformationfigure", "supplementaryinformationpage",
        "supplementaryinformationtable", "supplementaryinformationfigure",
    }
    locator_phrase = re.compile(
        r"\b(?:pages?|pp?\.?|tables?|tabs?\.?|figures?|figs?\.?|si\s+(?:pages?|tables?|figures?)|"
        r"supplementary\s+(?:pages?|tables?|figures?))\s*(?:#|:|no\.?\s*)?[sS]?\s*\d+\b",
        re.IGNORECASE,
    )
    for key, value in raw.items():
        normalized = _key(key)
        text = _clean(value)
        if not text:
            continue
        if normalized in structured and re.search(r"(?:\d+|[sS]\s*\d+)", text):
            if normalized == "tableorfigure" and not re.search(r"\b(?:table|tab\.?|figure|fig\.?|page|p\.)\b", text, re.IGNORECASE):
                continue
            return True
        if normalized in {"evidencelocation", "location", "verbatimlocator"} and locator_phrase.search(text):
            return True
    return False


def _evidence_location_value(raw: Mapping[str, Any]) -> str:
    parts: list[str] = []
    location_keys = {_key(alias) for alias in _ALIASES["evidence_location"]}
    for key, value in raw.items():
        if _key(key) not in location_keys or value in (None, ""):
            continue
        cleaned = _clean(value)
        if not cleaned:
            continue
        part = f"{key}={cleaned}"
        if part not in parts:
            parts.append(part)
    return "; ".join(parts)


def _meaningful_evidence_quote(raw: Mapping[str, Any], mobility_value: str) -> bool:
    quote = _canonical(raw, "evidence_quote")
    def numbers(text: str) -> set[Decimal]:
        text = _MOBILITY_UNIT_RE.sub(" ", text).replace("−", "-")
        pattern = r"(?<![A-Za-z0-9.^])([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(?:\s*[x×*]\s*10\s*\^\s*([-+]?\d+))?"
        values = set()
        for match in re.finditer(pattern, text):
            try:
                value = Decimal(match[1])
                if match[2] is not None:
                    value *= Decimal(10) ** int(match[2])
                if value.is_finite():
                    values.add(value)
            except (InvalidOperation, ValueError, OverflowError):
                continue
        return values
    value_numbers, quote_numbers = numbers(mobility_value), numbers(quote)
    shares_value = bool(value_numbers) and value_numbers.issubset(quote_numbers)
    has_measure_context = bool(
        _MOBILITY_RE.search(quote)
        or _EXPLICIT_ELECTRONIC_MOBILITY_RE.search(quote)
        or _MOBILITY_UNIT_RE.search(quote)
    )
    return shares_value and has_measure_context


def _quote_domain_for_selected_value(raw: Mapping[str, Any], mobility_value: str) -> str:
    """Classify quote wording only in the clause containing the selected value."""
    quote = _canonical(raw, "evidence_quote")
    if not quote:
        return "unknown"
    value_tokens = _numeric_tokens(mobility_value)
    clauses = re.split(r"[;.!?\n]+|\b(?:while|whereas|however)\b", quote, flags=re.IGNORECASE)
    specific = re.compile(
        r"\b(?:electron|electrons|hole|holes|ambipolar|electronic)\s+"
        r"(?:charge\s+)?(?:carrier\s+)?mobilit(?:y|ies)\b"
        r"|\bmobilit(?:y|ies)\s+(?:of|for)\s+(?:electrons?|holes?)\b",
        re.IGNORECASE,
    )
    generic = re.compile(r"\bcarrier\s+mobilit(?:y|ies)\b", re.IGNORECASE)
    ionic = re.compile(r"\b(?:ionic|ion|protonic|proton)\b", re.IGNORECASE)
    for clause in clauses:
        if value_tokens:
            clause_tokens = _numeric_tokens(clause)
            def number_key(token: str) -> str:
                try:
                    return str(float(token))
                except ValueError:
                    return token.casefold()
            if not ({number_key(token) for token in value_tokens} & {number_key(token) for token in clause_tokens}):
                continue
        has_specific = bool(specific.search(clause))
        has_ionic = bool(ionic.search(clause) and _MOBILITY_RE.search(clause))
        if has_specific and not has_ionic:
            return "electronic"
        if has_ionic and not has_specific:
            return "ionic"
        if has_specific and has_ionic:
            return "ambiguous"
        if generic.search(clause) and not has_ionic:
            return "generic"
        if has_ionic:
            return "ionic"
    if not value_tokens and specific.search(quote):
        return "electronic"
    return "unknown"


def _is_pdf_reference(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    path_part = re.split(r"[?#]", text, maxsplit=1)[0].rstrip()
    return bool(re.search(r"(?i)\.pdf$", path_part))


def _source_pdf_value(raw: Mapping[str, Any]) -> str:
    candidates = (
        _first(raw, _ALIASES["source_pdf"]),
        _first(raw, {"sourcefile", "sourcefileorurl", "fulltext", "pdf", "filename"}),
    )
    for value in candidates:
        cleaned = _clean(value)
        if _is_pdf_reference(cleaned):
            return cleaned
    return ""


def _paper_url_value(raw: Mapping[str, Any]) -> str:
    explicit = _clean(_first(raw, {"paperurl", "url", "landingpage", "articleurl"}))
    if explicit:
        return explicit
    for value in (_first(raw, {"sourcefileorurl", "sourcefile"}),):
        cleaned = _clean(value)
        if cleaned and not _is_pdf_reference(cleaned):
            return cleaned
    return ""


def _numeric_audit_flag(raw: Mapping[str, Any]) -> bool:
    """Detect an explicit OCR/exponent-inference audit flag conservatively."""
    false_values = _FALSEY | {"否", "无", "未涉及", "未推断", "未发现", "no ocr", "no inference"}
    true_values = _TRUTHY | {"是", "有", "需复核", "需要复核", "待复核", "有风险"}
    for key, value in raw.items():
        raw_key = str(key).casefold()
        normalized = _key(key)
        if not ("ocr" in normalized or "指数" in raw_key or "exponent" in normalized or "numericinference" in normalized):
            continue
        text = _clean(value).casefold()
        if not text or text in false_values:
            continue
        if text in true_values:
            return True
        if any(negative in text for negative in ("not ", "no ", "否", "无", "未")):
            continue
        if any(signal in text for signal in ("ocr", "指数", "推断", "infer", "review", "复核", "需核")):
            return True
    return False


def _numeric_review_reason(
    raw: Mapping[str, Any], mobility_value: str, mobility_unit: str, is_electronic: bool | None
) -> str:
    reasons: list[str] = []
    if _numeric_audit_flag(raw):
        reasons.append("OCR or exponent-inference audit flag requires numeric review")
    if mobility_value and _has_numeric(mobility_value):
        if is_electronic is not True:
            reasons.append("electronic carrier domain is ambiguous or unspecified")
        if not _mobility_compatible_unit(mobility_unit):
            reasons.append("mobility-compatible unit is missing or ambiguous")
        raw_status = _clean(_first(raw, {"status", "evidencestatus", "extractionstatus", "verificationstatus"})).casefold()
        verified_flag = _clean(_first(raw, {"verified", "evidenceverified", "sourcechecked", "pdfchecked"})).casefold()
        explicit_verified = raw_status in {"verified", "verified_evidence", "evidence verified"} or verified_flag in _TRUTHY
        if explicit_verified and not (
            _meaningful_evidence_quote(raw, mobility_value) and _has_precise_evidence_location(raw)
        ):
            reasons.append("verified flag lacks a numeric-matching quote and precise page/table/figure locator")
    return "; ".join(dict.fromkeys(reasons))


def _explicit_exclusion(raw: Mapping[str, Any], mobility_value: str) -> str:
    if _quote_has_selected_ionic_mobility(raw, mobility_value):
        return "quoted selected measurement is ionic/proton mobility"
    property_aliases = {
        "property", "propertyname", "quantity", "quantityname", "metric", "observable",
        "observedproperty", "extractedproperty", "mobilityproperty", "valuetype",
        "mobilitytype", "mobilitykind", "datatype",
    }
    # Inspect property labels and semantic fields, not every sentence in an
    # abstract: papers can discuss conductivity/diffusion while reporting mobility.
    measurement_label = _clean(_first(raw, property_aliases))
    normalized_keys = [_key(key) for key in raw]
    # If a dedicated mobility value is selected, a generic property label may
    # describe a different adjacent measurement. Keep mobility-type labels,
    # which still identify the selected mobility's domain.
    semantic_values = []
    if not mobility_value or _MOBILITY_RE.search(measurement_label):
        semantic_values.append(measurement_label)
    mobility_kind = _clean(_first(raw, {"mobilitytype", "mobilitykind"}))
    if mobility_kind:
        semantic_values.append(mobility_kind)
    for key, value in raw.items():
        normalized = _key(key)
        # A separate conductivity/diffusion column must not invalidate the
        # selected mobility measurement. Use such headers only when no direct
        # mobility column/value was selected.
        if not mobility_value and any(term in normalized for term in ("conductivity", "diffusion", "diffusivity", "ionicmobility", "protonmobility")):
            semantic_values.append(normalized + " " + _clean(value))
    for name in ("carrier_type",):
        semantic_values.append(_canonical(raw, name))
    semantic = " ".join(semantic_values)
    combined = semantic + " " + mobility_value
    has_diffusion_column = any("diffusion" in key or "diffusivity" in key for key in normalized_keys)
    has_conductivity_column = any("conductivity" in key or "conductance" in key for key in normalized_keys)
    ionic_mobility_columns = any(
        "mobility" in key and any(species in key for species in ("ionic", "ion", "proton", "lithium", "sodium", "potassium", "vacancy", "limobility", "namobility", "kmobility"))
        for key in normalized_keys
    )
    if _DIFFUSION_RE.search(semantic) or (has_diffusion_column and not mobility_value):
        return "diffusion coefficient/diffusivity is not carrier mobility"
    if _CONDUCTIVITY_RE.search(semantic) or (has_conductivity_column and not mobility_value):
        return "conductivity/conductance is not carrier mobility"
    if (ionic_mobility_columns and not mobility_value) or _IONIC_RE.search(mobility_kind) or (_IONIC_RE.search(semantic) and (_MOBILITY_RE.search(combined) or _canonical(raw, "carrier_type"))):
        return "ionic/proton/species mobility is not electronic carrier mobility"
    # Explicit domain/status columns can rule out electronic mobility.
    domain = _clean(_first(raw, {"mobilitydomain", "domain", "transportdomain", "carrierdomain"})).casefold()
    if domain and (_IONIC_RE.search(domain) or "ionic" in domain or "proton" in domain):
        return "source marks this as ionic/proton mobility"
    flag = _clean(_first(raw, {"iselectronicmobility", "electronicmobility", "iscarriermobility"})).casefold()
    if flag in _FALSEY:
        return "source explicitly marks this as non-electronic mobility"
    return ""


def _electronic_signal(raw: Mapping[str, Any]) -> bool:
    """Require an electronic cue tied to the selected mobility measurement."""
    carrier = _canonical(raw, "carrier_type")
    if carrier:
        allowed = re.findall(r"\b(?:electrons?|holes?|ambipolar)\b", carrier, re.IGNORECASE)
        remainder = re.sub(
            r"\b(?:electrons?|holes?|ambipolar|and|or|both|carrier|carriers)\b",
            "",
            carrier,
            flags=re.IGNORECASE,
        ).strip(" +-/,;()[]")
        # An explicit electron/hole/ambipolar value is usable. A populated
        # but ambiguous carrier field (for example unspecified, exciton, or
        # sum) blocks promotion from a generic quote or column name.
        if allowed and not remainder:
            return True
        return False

    # Only inspect the actual value column selected by _canonical. This avoids
    # combining an unrelated electron_density header with a generic mobility
    # column from the same table row.
    mobility_aliases = {_key(alias) for alias in _ALIASES["mobility_value"]}
    _, selected_header = _selected_mobility_value_field(raw)
    if selected_header and _EXPLICIT_ELECTRONIC_MOBILITY_RE.search(
        selected_header.replace("_", " ").replace("-", " ")
    ):
        return True

    property_fields = {
        "property", "propertyname", "quantity", "quantityname", "metric", "observable",
        "observedproperty", "extractedproperty", "mobilityproperty", "valuetype",
        "mobilitytype", "mobilitykind",
    }
    selected_property_values = [_clean(value) for key, value in raw.items() if _key(key) in property_fields and value not in (None, "")]
    if any(_EXPLICIT_ELECTRONIC_MOBILITY_RE.search(value) for value in selected_property_values):
        return True
    mobility_kind = _clean(_first(raw, {"mobilitytype", "mobilitykind"}))
    if mobility_kind and _ELECTRONIC_RE.search(mobility_kind) and not _IONIC_RE.search(mobility_kind):
        return True

    # A source quote can establish the carrier domain, but title/abstract and
    # unrelated column names cannot promote a numeric measurement by themselves.
    evidence_quote = _canonical(raw, "evidence_quote")
    quote_domain = _quote_domain_for_selected_value(raw, _direct_mobility_value(raw))
    if quote_domain == "electronic":
        return True
    if quote_domain == "generic" and not _IONIC_RE.search(evidence_quote):
        return True
    if not _direct_mobility_value(raw) and _EXPLICIT_ELECTRONIC_MOBILITY_RE.search(evidence_quote):
        return not _IONIC_RE.search(evidence_quote)
    return False


def _has_mobility_evidence(raw: Mapping[str, Any], mobility_value: str) -> bool:
    if mobility_value:
        return True
    for key in ("title", "abstract", "keywords", "notes", "evidence_quote"):
        value = _canonical(raw, key) if key in _ALIASES else _clean(_first(raw, {key}))
        if value and _MOBILITY_RE.search(value):
            return True
    for key, value in raw.items():
        if _key(key) in {
            "property", "propertyname", "quantity", "quantityname", "metric", "observable",
            "observedproperty", "extractedproperty", "mobilityproperty", "valuetype",
            "mobilitytype", "mobilitykind",
        }:
            if _MOBILITY_RE.search(_clean(value)):
                return True
        if _key(key) in {"electronmobility", "holemobility", "ambipolarmobility", "carriermobility"}:
            return True
    return False


def _quote_has_selected_ionic_mobility(raw: Mapping[str, Any], mobility_value: str) -> bool:
    """Catch a selected value explicitly tied to ionic/proton mobility.

    Generic "carrier mobility" wording does not establish electronic
    transport when the quoted measurement itself is ionic. A specific
    electron/hole/ambipolar/electronic mobility cue or selected carrier field
    can resolve a mixed-topic source.
    """
    quote = _canonical(raw, "evidence_quote")
    if not quote or not mobility_value:
        return False
    specific_cue = False
    carrier = _canonical(raw, "carrier_type")
    if carrier:
        allowed = re.findall(r"\b(?:electrons?|holes?|ambipolar)\b", carrier, re.IGNORECASE)
        remainder = re.sub(
            r"\b(?:electrons?|holes?|ambipolar|and|or|both|carrier|carriers)\b", "", carrier,
            flags=re.IGNORECASE,
        ).strip(" +-/,;()[]")
        specific_cue = bool(allowed and not remainder)
    if not specific_cue:
        value, header = _selected_mobility_value_field(raw)
        selected_header = header.replace("_", " ").replace("-", " ")
        specific_cue = bool(value and re.search(r"\b(?:electron|electrons|hole|holes|ambipolar|electronic)\b", selected_header, re.IGNORECASE))
    if not specific_cue:
        property_fields = {
            "property", "propertyname", "quantity", "quantityname", "metric", "observable",
            "observedproperty", "extractedproperty", "mobilityproperty", "valuetype",
            "mobilitytype", "mobilitykind",
        }
        specific_cue = any(
            re.search(r"\b(?:electron|electrons|hole|holes|ambipolar|electronic)\b", _clean(value), re.IGNORECASE)
            and _MOBILITY_RE.search(_clean(value))
            for key, value in raw.items() if _key(key) in property_fields
        )
    if specific_cue:
        return False
    quote_domain = _quote_domain_for_selected_value(raw, mobility_value)
    # Generic carrier-mobility wording cannot resolve ionic context. A
    # specific electronic phrase in the same value-bearing clause can.
    return quote_domain in {"ionic", "ambiguous"}


def _status(
    raw: Mapping[str, Any],
    mobility_value: str,
    mobility_unit: str,
    excluded: str,
    is_electronic: bool | None,
) -> str:
    if excluded:
        return "candidate"
    if not _has_mobility_evidence(raw, mobility_value):
        return "candidate"
    if not (_has_numeric(mobility_value) and is_electronic is True and _mobility_compatible_unit(mobility_unit)):
        return "likely_contains_mobility"
    if _numeric_audit_flag(raw):
        return "likely_contains_mobility"
    raw_status = _clean(_first(raw, {"status", "evidencestatus", "extractionstatus", "verificationstatus"})).casefold()
    verified_flag = _clean(_first(raw, {"verified", "evidenceverified", "sourcechecked", "pdfchecked"})).casefold()
    explicit_verified = raw_status in {"verified", "verified_evidence", "evidence verified"} or verified_flag in _TRUTHY
    quote = _canonical(raw, "evidence_quote")
    location = _canonical(raw, "evidence_location")
    source_pdf = _canonical(raw, "source_pdf")
    if explicit_verified and is_electronic is True and quote and _meaningful_evidence_quote(raw, mobility_value) and _has_precise_evidence_location(raw):
        return "verified_evidence"
    return "confirmed_numeric_mobility"


def _paper_identity(raw: Mapping[str, Any], doi: str, title: str, source_file: str, source_row: int) -> tuple[str, str]:
    if doi:
        return "doi:" + doi, "doi"
    for field, prefix in (("pmid", "pmid"), ("openalex_id", "openalex"), ("semantic_scholar_id", "s2")):
        value = _canonical(raw, field)
        if value:
            return prefix + ":" + value.strip(), field
    if title:
        compact = " ".join(title.casefold().split())
        return "title:" + compact, "title"
    source_pdf = _source_pdf_value(raw)
    if source_pdf:
        return "source-pdf:" + source_pdf, "source_pdf"
    # A deterministic source-row key is a local record handle, not a claimed
    # bibliographic identifier.
    local = hashlib.sha256(f"{source_file}\0{source_row}".encode("utf-8")).hexdigest()[:16]
    return "source-row:" + local, "source_row"


def normalize_legacy_record(raw_fields: Mapping[str, Any], source_file: str, source_row: int) -> dict[str, Any]:
    """Normalize one legacy row while retaining the untouched source fields."""
    raw = dict(raw_fields)
    doi = normalize_doi(_canonical(raw, "doi"))
    title = _canonical(raw, "title")
    mobility_value = _direct_mobility_value(raw)
    mobility_unit = _selected_mobility_unit(raw, mobility_value)
    mobility_value_low = _clean(_first(raw, _ALIASES["mobility_value_low"]))
    mobility_value_high = _clean(_first(raw, _ALIASES["mobility_value_high"]))
    mobility_value_original = _clean(_first(raw, _ALIASES["mobility_value_original"]))
    mobility_value_normalized = _clean(_first(raw, _ALIASES["mobility_value_normalized_cm2_Vs"]))
    mobility_unit_original = _clean(_first(raw, _ALIASES["mobility_unit_original"]))
    exclusion = _explicit_exclusion(raw, mobility_value)
    electronic_signal = _electronic_signal(raw)
    carrier_type = _canonical(raw, "carrier_type")
    if not carrier_type and electronic_signal:
        _, selected_header = _selected_mobility_value_field(raw)
        header_carriers = re.findall(r"\b(?:electron|hole|ambipolar)\b", selected_header.replace("_", " ").replace("-", " "), re.I)
        # The exact source header supplies polarity; otherwise retain the
        # source's generic carrier label without inventing electron/hole type.
        carrier_type = header_carriers[0].casefold() if len(set(header_carriers)) == 1 else "carrier"
    is_electronic: bool | None = False if exclusion else (True if electronic_signal else None)
    domain = "ionic_or_non_electronic" if exclusion else ("electronic" if electronic_signal else "unknown")
    paper_id, identifier_type = _paper_identity(raw, doi, title, source_file, source_row)
    review_reason = _numeric_review_reason(raw, mobility_value, mobility_unit, is_electronic)
    normalized: dict[str, Any] = {
        "record_id": hashlib.sha256(f"{source_file}\0{source_row}\0{paper_id}".encode("utf-8")).hexdigest()[:20],
        "paper_id": paper_id,
        "identifier_type": identifier_type,
        "doi": doi,
        "pmid": _canonical(raw, "pmid"),
        "openalex_id": _canonical(raw, "openalex_id"),
        "semantic_scholar_id": _canonical(raw, "semantic_scholar_id"),
        "title": title,
        "abstract": _canonical(raw, "abstract"),
        "year": _canonical(raw, "year"),
        "journal": _canonical(raw, "journal"),
        "paper_url": _paper_url_value(raw),
        "material": _canonical(raw, "material"),
        "material_domain": _canonical(raw, "material_domain"),
        "sample": _canonical(raw, "sample"),
        "material_class": _material_class_value(raw),
        "experimental_or_theoretical": _study_type_value(raw),
        "mobility_value": mobility_value,
        "mobility_value_numeric": _numeric_value(mobility_value),
        "mobility_value_original": mobility_value_original,
        "mobility_value_low": mobility_value_low,
        "mobility_value_high": mobility_value_high,
        "mobility_value_normalized_cm2_Vs": mobility_value_normalized,
        "mobility_unit": mobility_unit,
        "mobility_unit_original": mobility_unit_original,
        "carrier_type": carrier_type,
        "mobility_domain": domain,
        "is_electronic_mobility": is_electronic,
        "method": _canonical(raw, "method"),
        "temperature": _canonical(raw, "temperature"),
        "conditions": _canonical(raw, "conditions"),
        "direction": _canonical(raw, "direction"),
        "evidence_quote": _canonical(raw, "evidence_quote"),
        "evidence_location": _evidence_location_value(raw),
        "source_pdf": _source_pdf_value(raw),
        "status": _status(raw, mobility_value, mobility_unit, exclusion, is_electronic),
        "numeric_review_reason": review_reason,
        "exclusion_reason": exclusion,
        "source_file": str(source_file),
        "source_row": source_row,
        "raw_fields_json": json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str),
    }
    return normalized


def revalidate_normalized_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute mobility eligibility/state from a normalized import row.

    When retained ``raw_fields_json`` is available, it is the evidence source;
    derived status and electronic-mobility flags are recalculated. For a
    manually supplied normalized row without raw fields, the row's value,
    unit, carrier/property, quote, and location are rechecked, but its existing
    status label is not trusted as a verification marker.
    """
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    original = dict(record)
    raw: dict[str, Any] | None = None
    raw_blob = original.get("raw_fields_json")
    if isinstance(raw_blob, Mapping):
        raw = dict(raw_blob)
    elif isinstance(raw_blob, str) and raw_blob.strip():
        try:
            parsed = json.loads(raw_blob)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            raw = parsed

    if raw is None:
        derived_keys = {
            "recordid", "paperid", "identifiertype", "mobilityvaluenumeric", "mobilitydomain",
            "iselectronicmobility", "status", "evidencestatus", "extractionstatus", "verificationstatus",
            "numericreviewreason", "exclusionreason", "sourcefile", "sourcerow", "rawfieldsjson", "screeningstate", "evidencestate",
        }
        raw = {key: value for key, value in original.items() if _key(key) not in derived_keys}
    else:
        # Preserve searchable paper identity when an older raw-field snapshot
        # omitted a metadata column; do not import derived carrier/status flags.
        for canonical, aliases in (
            ("doi", _ALIASES["doi"]), ("title", _ALIASES["title"]), ("year", _ALIASES["year"]),
            ("pmid", _ALIASES["pmid"]), ("openalex_id", _ALIASES["openalex_id"]),
            ("semantic_scholar_id", _ALIASES["semantic_scholar_id"]),
            ("material", _ALIASES["material"]), ("material_domain", _ALIASES["material_domain"]),
            ("sample", _ALIASES["sample"]), ("material_class", _ALIASES["material_class"]),
            ("experimental_or_theoretical", _ALIASES["experimental_or_theoretical"]),
            ("mobility_value", _ALIASES["mobility_value"]),
            ("mobility_value_original", _ALIASES["mobility_value_original"]),
            ("mobility_value_low", _ALIASES["mobility_value_low"]),
            ("mobility_value_high", _ALIASES["mobility_value_high"]),
            ("mobility_value_normalized_cm2_Vs", _ALIASES["mobility_value_normalized_cm2_Vs"]),
            ("mobility_unit", _ALIASES["mobility_unit"]),
            ("mobility_unit_original", _ALIASES["mobility_unit_original"]),
            ("method", _ALIASES["method"]),
            ("conditions", _ALIASES["conditions"]), ("temperature", _ALIASES["temperature"]),
            ("direction", _ALIASES["direction"]), ("evidence_quote", _ALIASES["evidence_quote"]),
            ("evidence_location", _ALIASES["evidence_location"]),
            ("paper_url", _ALIASES["paper_url"]),
        ):
            if not _first(raw, aliases) and original.get(canonical) not in (None, ""):
                raw[canonical] = original[canonical]
        if not _first(raw, _ALIASES["source_pdf"]) and _is_pdf_reference(original.get("source_pdf")):
            raw["source_pdf"] = original["source_pdf"]

    source_file = _clean(original.get("source_file")) or "<normalized-import>"
    try:
        source_row = int(original.get("source_row") or 1)
    except (TypeError, ValueError):
        source_row = 1
    normalized = normalize_legacy_record(raw, source_file, source_row)

    # Preserve record identity/provenance values while keeping evidence state
    # and electronic-domain decisions derived from the retained source fields.
    for field in ("record_id", "paper_id", "identifier_type"):
        if original.get(field) not in (None, ""):
            normalized[field] = original[field]
    return normalized


def _records_from_json(value: Any) -> list[dict[str, Any]]:
    """Extract record-shaped dictionaries from common JSON containers."""
    records: list[dict[str, Any]] = []
    record_keys = {_key(alias) for aliases in _ALIASES.values() for alias in aliases}
    record_keys.update({"abstract", "property", "quantity", "metric", "value", "result", "mobility"})

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        keys = {_key(k) for k in item}
        if keys & record_keys:
            records.append(item)
            return
        # Common wrappers: records/results/data/papers/items; recurse only
        # structured values so unrelated scalar metadata is ignored.
        for child in item.values():
            if isinstance(child, (dict, list)):
                visit(child)

    visit(value)
    return records


def _split_markdown_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    # Markdown commonly escapes literal pipes within cells.
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if char == "|" and not escaped:
            cells.append("".join(current).replace("\\|", "|").strip())
            current = []
        else:
            current.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    cells.append("".join(current).replace("\\|", "|").strip())
    return cells


def _markdown_records(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    records: list[dict[str, Any]] = []
    # Pipe tables
    index = 0
    while index < len(lines):
        if "|" not in lines[index] or index + 1 >= len(lines) or not re.search(r"\|?\s*:?-{3,}", lines[index + 1]):
            index += 1
            continue
        headers = [_key(re.sub(r"\*\*|__|`", "", h)) for h in _split_markdown_row(lines[index])]
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            cells = _split_markdown_row(lines[index])
            if len(cells) == len(headers):
                records.append({headers[pos]: cell for pos, cell in enumerate(cells) if headers[pos]})
            index += 1

    # Key-value note blocks, often one paper per blank line or heading.
    current: dict[str, str] = {}
    pair_re = re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?([^:*`]+?)(?:\*\*)?\s*:\s*(.*?)\s*$")
    for line in lines + [""]:
        match = pair_re.match(line)
        if match:
            current[_key(match.group(1))] = match.group(2).strip().strip("`")
        elif line.lstrip().startswith("#"):
            if current:
                records.append(current)
                current = {}
        elif not line.strip():
            if current:
                records.append(current)
                current = {}
    return records


def parse_legacy_file(path: str | Path) -> list[dict[str, Any]]:
    """Parse one CSV/TSV/JSON/JSONL/Markdown-like legacy file."""
    file_path = Path(path)
    suffix = file_path.suffix.casefold()
    text = file_path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        if suffix == ".csv":
            sample = text[:8192]
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
            except csv.Error:
                pass
        return [dict(row) for row in csv.DictReader(text.splitlines(), delimiter=delimiter) if row]
    if suffix == ".json":
        return _records_from_json(json.loads(text))
    if suffix in {".jsonl", ".ndjson"}:
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {file_path}:{line_number}") from exc
            records.extend(_records_from_json(value))
        return records
    if suffix in {".md", ".markdown", ".txt"}:
        return _markdown_records(text)
    raise ValueError(f"Unsupported legacy file type: {file_path.suffix or '(no extension)'}")


def _expand_sources(source_paths: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(source_paths, (str, Path)):
        sources: Sequence[str | Path] = [source_paths]
    else:
        sources = list(source_paths)
    files: list[Path] = []
    for source in sources:
        path = Path(source)
        if path.is_dir():
            files.extend(child for child in path.rglob("*") if child.is_file() and child.suffix.casefold() in SUPPORTED_SUFFIXES)
        elif path.is_file():
            if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
                raise ValueError(f"Unsupported legacy file type: {path.suffix or '(no extension)'}")
            files.append(path)
        else:
            raise FileNotFoundError(path)
    # Keep explicit ordering while removing duplicate paths.
    unique: dict[str, Path] = {}
    for path in files:
        unique.setdefault(str(path.resolve()).casefold(), path)
    return list(unique.values())


def iter_legacy_records(source_paths: str | Path | Iterable[str | Path]) -> Iterator[dict[str, Any]]:
    """Yield normalized records from explicitly supplied files/directories."""
    for path in _expand_sources(source_paths):
        source_file = str(path)
        for row_number, raw in enumerate(parse_legacy_file(path), start=1):
            yield normalize_legacy_record(raw, source_file, row_number)


def import_legacy_results(
    source_paths: str | Path | Iterable[str | Path],
    output_path: str | Path,
    output_format: str | None = None,
) -> int:
    """Write imported records to a new CSV or JSONL file and return row count.

    The destination is opened with exclusive creation. If it already exists,
    ``FileExistsError`` is raised before any source records are written.
    """
    destination = Path(output_path)
    fmt = (output_format or destination.suffix.lstrip(".") or "csv").casefold()
    if fmt == "ndjson":
        fmt = "jsonl"
    if fmt not in {"csv", "jsonl"}:
        raise ValueError("output_format must be 'csv' or 'jsonl'")
    # Parse first so malformed sources cannot leave behind a partial-looking
    # output file. The exclusive open below still protects existing outputs.
    records = list(iter_legacy_records(source_paths))
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    if fmt == "csv":
        with destination.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                row = dict(record)
                row["is_electronic_mobility"] = "" if row["is_electronic_mobility"] is None else str(row["is_electronic_mobility"]).lower()
                writer.writerow(row)
                count += 1
    else:
        with destination.open("x", encoding="utf-8", newline="") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                count += 1
    return count


__all__ = [
    "OUTPUT_FIELDS",
    "import_legacy_results",
    "iter_legacy_records",
    "normalize_doi",
    "normalize_legacy_record",
    "parse_legacy_file",
    "revalidate_normalized_record",
]
