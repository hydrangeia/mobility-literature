from __future__ import annotations

import re
import math
from typing import Any


EVIDENCE_STATES = (
    "candidate",
    "likely_contains_mobility",
    "confirmed_numeric_mobility",
    "verified_evidence",
)

IONIC_ONLY = re.compile(
    r"\b(protons?|protonic|ionic|ions?|vacanc(?:y|ies)|lithium|sodium|oxygen[- ]ion)"
    r"(?:[- ]\w+){0,2}\s+(?:mobilit(?:y|ies)|conductivity|transport|migration|diffusion)\b|"
    r"\b(?:ion|proton)[- ](?:conducting|conduction|migration)\b",
    re.I,
)
DIFFUSION_ONLY = re.compile(r"\b(diffusion|diffusivity|diffusion length)\b", re.I)
CONDUCTIVITY_ONLY = re.compile(r"\b(conductivity|conductive|conductance)\b", re.I)
ELECTRONIC_SIGNAL = re.compile(
    r"\b(electron|electronic|hole|carrier|charge carrier|ambipolar|OFET|FET|field[- ]effect transistor)\b",
    re.I,
)
MOBILITY_SIGNAL = re.compile(
    r"\b(mobilit(?:y|ies)|charge transport|carrier transport|charge[- ]transport)\b|\bμ\s*=?",
    re.I,
)
EXPLICIT_ELECTRONIC_MOBILITY = re.compile(
    r"\b(electrons?|holes?|charge[- ]carriers?|carriers?|ambipolar|electronic)\s+mobilit(?:y|ies)\b|"
    r"\bmobilit(?:y|ies)\s+(?:of|for)\s+(?:electrons?|holes?|carriers?)\b",
    re.I,
)
METHOD_MOBILITY = re.compile(
    r"\b(?:OFET|FET|Hall|field[- ]effect(?: transistor)?)\s+mobilit(?:y|ies)\b|"
    r"\b(?:OFET|FET|field[- ]effect transistor)\b.{0,120}\bmobilit(?:y|ies)\b",
    re.I,
)
STRICT_ELECTRONIC_MOBILITY = re.compile(
    r"\b(?:electrons?|holes?|ambipolar|electronic)\s+(?:carrier\s+)?mobilit(?:y|ies)\b|"
    r"\bmobilit(?:y|ies)\s+(?:of|for)\s+(?:electrons?|holes?)\b", re.I,
)
VALUE_UNIT = re.compile(
    r"(?P<value>\d+(?:\.\d+)?(?:\s*[×x]\s*10\s*(?:\^\s*)?[-−]?\d+)?)\s*"
    r"(?P<unit>cm\s*(?:\^?\s*2|²)\s*(?:/|\s*V\s*[-−]?1\s*s\s*[-−]?1)|"
    r"m\s*(?:\^?\s*2|²)\s*(?:/|\s*V\s*[-−]?1\s*s\s*[-−]?1))",
    re.I,
)


def screen(title: str = "", abstract: str = "") -> dict[str, Any]:
    text = f"{title}\n{abstract}"
    has_electronic = bool(ELECTRONIC_SIGNAL.search(text))
    has_mobility = bool(MOBILITY_SIGNAL.search(text))
    explicit_mobility = bool(EXPLICIT_ELECTRONIC_MOBILITY.search(text))
    method_mobility = bool(METHOD_MOBILITY.search(text))
    has_ionic = bool(IONIC_ONLY.search(text))
    if has_ionic and not STRICT_ELECTRONIC_MOBILITY.search(text):
        explicit_mobility = False

    reason = "metadata_hit"
    excluded_measure = ""
    state = "candidate"
    if explicit_mobility:
        state = "likely_contains_mobility"
        reason = "explicit_electronic_mobility_term"
    elif method_mobility and not has_ionic:
        state = "likely_contains_mobility"
        reason = "electronic_measurement_mobility_term"
    elif has_ionic:
        reason, excluded_measure = "ionic_without_explicit_electronic_mobility", "ionic_or_proton_mobility"
    elif any(ELECTRONIC_SIGNAL.search(clause) and MOBILITY_SIGNAL.search(clause)
             and not DIFFUSION_ONLY.search(clause)
             for clause in re.split(r"(?<=[.!?;])\s+|\n", text)):
        state = "likely_contains_mobility"
        reason = "electronic_transport_and_mobility_signal"
    elif DIFFUSION_ONLY.search(text) and not explicit_mobility:
        reason, excluded_measure = "diffusion_without_explicit_mobility", "diffusion"
    elif CONDUCTIVITY_ONLY.search(text) and not has_mobility:
        reason, excluded_measure = "conductivity_without_explicit_mobility", "conductivity"
    elif has_mobility and not has_electronic:
        reason = "mobility_term_needs_manual_screen"

    # Abstract values can be false positives or refer to another property. Numeric
    # confirmation therefore requires an explicit normalized observation from the
    # importer or a later evidence review; screening text never promotes the state.
    return {
        "screening_state": state,
        "screening_reason": reason,
        "screening_confidence": "metadata_rule" if state == "likely_contains_mobility" else "unreviewed",
        "excluded_measure": excluded_measure,
        "numeric_mobility_pattern_seen": bool(VALUE_UNIT.search(text) and explicit_mobility),
        "evidence_state": state,
    }


def is_valid_carrier_mobility(observation: dict[str, Any]) -> bool:
    carrier = str(observation.get("carrier") or "").casefold()
    measure = str(observation.get("property") or observation.get("measure") or "mobility").casefold()
    unit = str(observation.get("unit") or "").casefold()
    try:
        value = float(observation.get("value"))
    except (TypeError, ValueError):
        return False
    if not math.isfinite(value) or value < 0 or not unit:
        return False
    if carrier not in {"electron", "hole", "ambipolar", "electronic", "carrier"}:
        return False
    forbidden = ("conductivity", "diffusion", "proton", "ionic", "ion ")
    if any(word in measure for word in forbidden):
        return False
    unit = unit.replace("²", "2").replace("⁻", "-").replace("¹", "1").replace("−", "-")
    unit = re.sub(r"[\s^(){}\[\]*·⋅]", "", unit)
    return bool(re.fullmatch(r"(?:cm|mm|m|um|μm|µm|nm)2(?:/v/?s|v-1s-1)", unit))
