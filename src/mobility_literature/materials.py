from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any


MATERIAL_CLASSES = (
    "COF",
    "MOF",
    "organic_small_molecule",
    "hybrid_perovskite",
    "inorganic_2d",
)

_CLASS_ALIASES = {
    "cof": "COF",
    "cofs": "COF",
    "covalent organic framework": "COF",
    "mof": "MOF",
    "mofs": "MOF",
    "osm": "organic_small_molecule",
    "metal organic framework": "MOF",
    "organic": "organic_small_molecule",
    "organic semiconductor": "organic_small_molecule",
    "organic small molecule": "organic_small_molecule",
    "organic_small_molecule": "organic_small_molecule",
    "organic molecular semiconductor": "organic_small_molecule",
    "molecular crystal": "organic_small_molecule",
    "hybrid perovskite": "hybrid_perovskite",
    "hybrid_perovskite": "hybrid_perovskite",
    "pvsk": "hybrid_perovskite",
    "inorganic 2d": "inorganic_2d",
    "inorganic 2d material": "inorganic_2d",
    "inorganic_2d": "inorganic_2d",
    "2d": "inorganic_2d",
    "layered inorganic": "inorganic_2d",
}

_COF_PHRASE = re.compile(r"\bcovalent[-\s]+organic[-\s]+frameworks?\b", re.I)
_COF_ACRONYM = re.compile(r"\bCOFs?\b", re.I)
_COF_NAMED = re.compile(r"\bCOF[-\s]?\d+\b", re.I)
_FRAMEWORK_CONTEXT = re.compile(r"\b(framework|porous|covalent|conjugated|coordination)\b", re.I)

_MOF_PHRASE = re.compile(r"\bmetal[-\s]+organic[-\s]+frameworks?\b", re.I)
_MOF_ACRONYM = re.compile(r"\bMOFs?\b", re.I)
_MOF_NAMED = re.compile(r"\bMOF[-\s]?\d+\b", re.I)

_ORGANIC_MOLECULAR_PHRASE = re.compile(
    r"\b(?:organic\s+)?(?:small[-\s]+molecule|molecular)\s+"
    r"(?:organic\s+)?semiconductors?\b|"
    r"\borganic\s+molecular\s+semiconductors?\b|"
    r"\bsmall[-\s]+molecule\s+organic\s+semiconductors?\b",
    re.I,
)
_ORGANIC_NAMED_MATERIALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pentacene", re.compile(r"\bpentacene\b", re.I)),
    ("rubrene", re.compile(r"\brubrene\b", re.I)),
    ("tetracene", re.compile(r"\btetracene\b", re.I)),
    ("anthracene", re.compile(r"\banthracene\b", re.I)),
    ("perylene", re.compile(r"\bperylene\b", re.I)),
    ("DNTT", re.compile(r"\bDNTT\b", re.I)),
    ("C8-BTBT", re.compile(r"\bC8[-\s]?BTBT\b", re.I)),
    ("sexithiophene", re.compile(r"\bsexithiophene\b", re.I)),
    ("PCBM", re.compile(r"\bPCBM\b", re.I)),
)
_BROAD_ORGANIC = re.compile(
    r"\borganic\s+semiconductors?\b|\borganic\s+(?:single[-\s]+crystal|molecular\s+crystal)\b|"
    r"\bmolecular\s+crystals?\b|\bsmall[-\s]+molecule\b",
    re.I,
)

_PEROVSKITE = re.compile(r"\bperovskites?\b", re.I)
_HYBRID_PEROVSKITE_PHRASE = re.compile(
    r"\bhybrid\s+(?:organic[-\s]+inorganic\s+)?(?:halide\s+)?perovskites?\b|"
    r"\borganic[-\s]+inorganic\s+(?:halide\s+)?perovskites?\b|"
    r"\borganometal(?:lic)?\s+halide\s+perovskites?\b",
    re.I,
)
_ORGANIC_CATION = re.compile(
    r"\b(?:methylammonium|formamidinium|ethylammonium|guanidinium)\b|"
    r"\bCH\s*3\s*NH\s*3\s*Pb\s*(?:Cl|Br|I)\s*3\b|"
    r"\b(?:MA|FA)\s*Pb\s*(?:Cl|Br|I)\s*3\b",
    re.I,
)
_ALL_INORGANIC_PEROVSKITE = re.compile(
    r"\b(?:all[-\s]+inorganic|purely\s+inorganic|fully\s+inorganic)\b[\s\S]{0,50}\bperovskites?\b|"
    r"\binorganic\s+(?:lead[-\s]+)?halide\s+perovskites?\b|"
    r"\bCsPb\s*(?:Cl|Br|I)\s*_?\s*3\b|"
    r"\bcesium\s+lead\s+(?:chloride|bromide|iodide)\s+perovskites?\b|"
    r"\bcaesium\s+lead\s+(?:chloride|bromide|iodide)\s+perovskites?\b",
    re.I,
)
_BROAD_HALIDE_PEROVSKITE = re.compile(
    r"\b(?:halide|lead[-\s]+halide|metal[-\s]+halide)\s+perovskites?\b",
    re.I,
)

_TWO_D_DESCRIPTOR = re.compile(
    r"\b(?:2\s*[- ]?\s*d|two[-\s]+dimensional|mono[-\s]?layer|bi[-\s]?layer|"
    r"few[-\s]+layer|single[-\s]+layer)\b",
    re.I,
)
_INORGANIC_2D_MATERIALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("inorganic_2d_material", re.compile(r"\binorganic\s+2\s*[- ]?\s*d\s+(?:materials?|semiconductors?)\b", re.I)),
    ("transition_metal_dichalcogenide", re.compile(r"\btransition[-\s]+metal\s+dichalcogenides?\b", re.I)),
    ("TMD/TMDC", re.compile(r"\bTMDs?\b|\bTMDCs?\b", re.I)),
    ("MoS2", re.compile(r"\bMoS\s*_?\s*2\b", re.I)),
    ("WS2", re.compile(r"\bWS\s*_?\s*2\b", re.I)),
    ("WSe2", re.compile(r"\bWSe\s*_?\s*2\b", re.I)),
    ("MoSe2", re.compile(r"\bMoSe\s*_?\s*2\b", re.I)),
    ("MoTe2", re.compile(r"\bMoTe\s*_?\s*2\b", re.I)),
    ("ReS2", re.compile(r"\bReS\s*_?\s*2\b", re.I)),
    ("black_phosphorus", re.compile(r"\bblack\s+phosphorus\b", re.I)),
    ("phosphorene", re.compile(r"\bphosphorene\b", re.I)),
    ("graphene", re.compile(r"\bgraphene\b", re.I)),
    ("MXene", re.compile(r"\bMXenes?\b", re.I)),
    ("silicene", re.compile(r"\bsilicene\b", re.I)),
    ("germanene", re.compile(r"\bgermanene\b", re.I)),
    ("stanene", re.compile(r"\bstanene\b", re.I)),
    ("antimonene", re.compile(r"\bantimonene\b", re.I)),
    ("borophene", re.compile(r"\bborophene\b", re.I)),
    ("InSe", re.compile(r"\bInSe\b", re.I)),
    ("GaSe", re.compile(r"\bGaSe\b", re.I)),
)
_BROAD_2D = re.compile(r"\b(?:2\s*[- ]?\s*d|two[-\s]+dimensional)\s+(?:semiconductors?|materials?)\b", re.I)


def _query_classes(query_class: Any) -> list[str]:
    if query_class is None:
        values: list[Any] = []
    elif isinstance(query_class, str):
        values = [query_class]
    elif isinstance(query_class, Iterable):
        values = list(query_class)
    else:
        values = [query_class]

    normalized: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        label = _CLASS_ALIASES.get(raw.casefold(), raw)
        if label not in MATERIAL_CLASSES:
            continue
        if label not in normalized:
            normalized.append(label)
    return normalized


def _first_match(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> str:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return ""


def _class_signal(text: str) -> tuple[list[str], list[str], bool]:
    """Return explicit metadata classes, evidence reasons, and review requirement."""
    classes: list[str] = []
    reasons: list[str] = []
    needs_review = False

    if _COF_PHRASE.search(text):
        classes.append("COF")
        reasons.append("metadata_phrase:covalent_organic_framework")
    elif _COF_NAMED.search(text):
        classes.append("COF")
        reasons.append("metadata_named_material:COF_series")
    elif _COF_ACRONYM.search(text):
        classes.append("COF")
        if _FRAMEWORK_CONTEXT.search(text):
            reasons.append("metadata_acronym:COF_with_framework_context")
        else:
            reasons.append("metadata_acronym:COF_ambiguous_needs_review")
            needs_review = True

    if _MOF_PHRASE.search(text):
        classes.append("MOF")
        reasons.append("metadata_phrase:metal_organic_framework")
    elif _MOF_NAMED.search(text):
        classes.append("MOF")
        reasons.append("metadata_named_material:MOF_series")
    elif _MOF_ACRONYM.search(text):
        classes.append("MOF")
        if _FRAMEWORK_CONTEXT.search(text):
            reasons.append("metadata_acronym:MOF_with_framework_context")
        else:
            reasons.append("metadata_acronym:MOF_ambiguous_needs_review")
            needs_review = True

    if _ORGANIC_MOLECULAR_PHRASE.search(text):
        classes.append("organic_small_molecule")
        reasons.append("metadata_phrase:organic_molecular_semiconductor")
    else:
        named_organic = _first_match(text, _ORGANIC_NAMED_MATERIALS)
        if named_organic:
            classes.append("organic_small_molecule")
            reasons.append(f"metadata_named_material:{named_organic}")

    perovskite_mentioned = bool(_PEROVSKITE.search(text))
    hybrid_phrase = bool(_HYBRID_PEROVSKITE_PHRASE.search(text))
    organic_cation = bool(perovskite_mentioned and _ORGANIC_CATION.search(text))
    inorganic_perovskite = bool(_ALL_INORGANIC_PEROVSKITE.search(text))
    if hybrid_phrase or organic_cation:
        classes.append("hybrid_perovskite")
        reasons.append(
            "metadata_phrase:hybrid_perovskite" if hybrid_phrase else "metadata_composition:organic_cation_perovskite"
        )

    inorganic_material = _first_match(text, _INORGANIC_2D_MATERIALS)
    two_d = bool(_TWO_D_DESCRIPTOR.search(text))
    if two_d and inorganic_material:
        classes.append("inorganic_2d")
        reasons.append(f"metadata_2d_material:{inorganic_material}+2d_descriptor")

    # Preserve order while removing duplicates from repeated cues.
    return list(dict.fromkeys(classes)), list(dict.fromkeys(reasons)), needs_review


def screen_material(title: str = "", abstract: str = "", query_class: Any = None) -> dict[str, Any]:
    """Assign a tentative material family from query provenance and metadata cues.

    This function screens title/abstract metadata only. Even a precise signal is
    labeled ``metadata_signal`` rather than treated as verified material evidence.
    """
    text = unicodedata.normalize("NFKC", f"{title}\n{abstract}")
    query_classes = _query_classes(query_class)
    explicit_classes, evidence_reasons, acronym_review = _class_signal(text)
    inorganic_perovskite = bool(_ALL_INORGANIC_PEROVSKITE.search(text))

    all_inorganic_only = bool(
        inorganic_perovskite
        and not _HYBRID_PEROVSKITE_PHRASE.search(text)
        and not (_PEROVSKITE.search(text) and _ORGANIC_CATION.search(text))
    )
    if all_inorganic_only:
        other_explicit_classes = [label for label in explicit_classes if label != "hybrid_perovskite"]
        if other_explicit_classes:
            picked_class = next((label for label in query_classes if label in other_explicit_classes), other_explicit_classes[0])
            reason_parts = evidence_reasons + ["all_inorganic_perovskite_not_hybrid"]
            return {
                "material_class": picked_class,
                "material_classes": other_explicit_classes,
                "query_material_classes": query_classes,
                "material_class_confidence": "metadata_signal",
                "review_material_class": acronym_review or len(other_explicit_classes) > 1,
                "material_screening_reason": "; ".join(reason_parts),
            }
        formula = "CsPbX3" if re.search(r"\bCsPb\s*(?:Cl|Br|I)\s*_?\s*3\b", text, re.I) else "all-inorganic perovskite wording"
        return {
            "material_class": "unassigned",
            "material_classes": [],
            "query_material_classes": query_classes,
            "material_class_confidence": "metadata_signal",
            "review_material_class": False,
            "material_screening_reason": f"explicit_all_inorganic_perovskite:{formula}; not_hybrid_perovskite",
        }

    if explicit_classes:
        picked_class = next((label for label in query_classes if label in explicit_classes), explicit_classes[0])
        multiple_signals = len(explicit_classes) > 1
        review = acronym_review or multiple_signals
        reason_parts = evidence_reasons[:]
        if multiple_signals:
            reason_parts.append("multiple_explicit_material_signals_needs_review")
        if inorganic_perovskite and "hybrid_perovskite" in explicit_classes:
            review = True
            reason_parts.append("mixed_inorganic_and_hybrid_perovskite_cues_needs_review")
        return {
            "material_class": picked_class,
            "material_classes": explicit_classes,
            "query_material_classes": query_classes,
            "material_class_confidence": "metadata_signal",
            "review_material_class": review,
            "material_screening_reason": "; ".join(reason_parts),
        }

    broad_reasons: list[str] = []
    if _BROAD_ORGANIC.search(text):
        broad_reasons.append("broad_organic_or_molecular_label")
    if _BROAD_HALIDE_PEROVSKITE.search(text):
        broad_reasons.append("broad_halide_perovskite_label")
    if _BROAD_2D.search(text):
        broad_reasons.append("2d_label_without_inorganic_material_signal")
    if inorganic_perovskite:
        broad_reasons.append("inorganic_perovskite_without_hybrid_signal")

    if query_classes:
        assigned_class = query_classes[0]
        reason_parts = ["query_family_tentative"]
        if broad_reasons:
            reason_parts.extend(broad_reasons)
        elif assigned_class == "inorganic_2d" and _TWO_D_DESCRIPTOR.search(text):
            reason_parts.append("2d_descriptor_without_inorganic_material_signal")
        elif assigned_class == "hybrid_perovskite" and _PEROVSKITE.search(text):
            reason_parts.append("perovskite_without_hybrid_composition_signal")
        elif assigned_class == "organic_small_molecule" and _BROAD_ORGANIC.search(text):
            reason_parts.append("organic_material_not_specific_to_small_molecule")
        return {
            "material_class": assigned_class,
            "material_classes": query_classes,
            "query_material_classes": query_classes,
            "material_class_confidence": "query_family",
            "review_material_class": True,
            "material_screening_reason": "; ".join(reason_parts),
        }

    reason_parts = broad_reasons or ["no_material_family_signal"]
    return {
        "material_class": "unassigned",
        "material_classes": [],
        "query_material_classes": [],
        "material_class_confidence": "unassigned",
        "review_material_class": True,
        "material_screening_reason": "; ".join(reason_parts),
    }
