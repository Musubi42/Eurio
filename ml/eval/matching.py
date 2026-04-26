"""Shared multi-stage matcher used by all source scrapers.

Consumes a canonical referential + per-product identity (country, year, theme
slug) and returns a decision dict. Stage 1 (exact cross-ref) is the caller's
responsibility — it's source-specific (Numista id vs JOUE code vs KM number).
This module implements Stages 2, 3 and the escalation to Stage 5. Stage 4
(visual ArcFace) is a future addition.

Spec: docs/research/data-referential-architecture.md §5.
"""

from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

ReferentialIndex = dict[tuple[str, int, float], list[dict]]


def index_referential(
    referential: dict[str, dict],
    face_value: float = 2.0,
) -> ReferentialIndex:
    """Group commemorative entries by (country, year, face_value) for fast lookup."""
    idx: ReferentialIndex = defaultdict(list)
    for entry in referential.values():
        ident = entry["identity"]
        if not ident.get("is_commemorative"):
            continue
        if ident.get("face_value") != face_value:
            continue
        key = (ident["country"], ident["year"], face_value)
        idx[key].append(entry)
    return idx


def candidates_for(
    idx: ReferentialIndex,
    country_iso2: str,
    year: int,
    face_value: float = 2.0,
) -> list[dict]:
    """Return commemo candidates for a given country/year, including eu-* joint
    issues when the country is listed in `identity.national_variants`."""
    direct = list(idx.get((country_iso2, year, face_value), []))
    joint = [
        e
        for e in idx.get(("eu", year, face_value), [])
        if country_iso2 in (e["identity"].get("national_variants") or [])
    ]
    return direct + joint


def slug_score(a: str, b: str) -> float:
    """Hybrid kebab-slug similarity: token coverage + char-level ratio.

    Token coverage handles reordered-but-matching themes; char ratio rescues
    cross-language partial substring matches ('francois-dassise' vs
    'francis-of-assisi'). We return the max of (coverage, ratio * 0.7) so the
    coverage path dominates when it applies but ratio kicks in otherwise.
    """
    if not a or not b:
        return 0.0
    src_tokens = {t for t in a.split("-") if t}
    cand_tokens = {t for t in b.split("-") if t}
    coverage = (len(src_tokens & cand_tokens) / len(src_tokens)) if src_tokens else 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    return max(coverage, ratio * 0.7)


def best_slug_match(
    source_slug: str, candidates: list[dict]
) -> tuple[dict | None, float, dict | None, float]:
    """Return (best, best_score, runner_up, runner_score)."""
    if not candidates:
        return None, 0.0, None, 0.0
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        cand_slug = "-".join(c["eurio_id"].split("-")[3:])
        scored.append((slug_score(source_slug, cand_slug), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if len(scored) > 1:
        runner_score, runner = scored[1]
    else:
        runner_score, runner = 0.0, None
    return best, best_score, runner, runner_score


def match(
    idx: ReferentialIndex,
    country: str | None,
    year: int | None,
    theme_slug: str,
    face_value: float = 2.0,
    score_floor: float = 0.25,
    gap_ratio: float = 1.4,
) -> dict[str, Any]:
    """Run Stages 2/3 of the matcher and return a decision dict.

    The returned dict always contains `stage` (one of '2', '3', '5', 'skip')
    and `eurio_id` (the canonical id when matched, else None). Stage '5' means
    escalation to human review; 'skip' means the product lacks enough identity
    to be matchable (missing country or year).
    """
    base = {
        "country": country,
        "year": year,
        "theme_slug": theme_slug,
    }
    if not country or not year:
        return {**base, "stage": "skip", "reason": "missing_country_or_year", "eurio_id": None}

    cands = candidates_for(idx, country, year, face_value)
    if not cands:
        return {
            **base,
            "stage": "5",
            "reason": "no_candidate",
            "eurio_id": None,
            "candidates": [],
        }

    if len(cands) == 1:
        return {
            **base,
            "stage": "2",
            "reason": "structural_unique",
            "eurio_id": cands[0]["eurio_id"],
            "confidence": 0.95,
        }

    best, score, runner, runner_score = best_slug_match(theme_slug, cands)
    has_gap = runner_score == 0 or score >= runner_score * gap_ratio
    if best and score >= score_floor and has_gap:
        return {
            **base,
            "stage": "3",
            "reason": "fuzzy_slug",
            "eurio_id": best["eurio_id"],
            "confidence": round(score, 3),
            "runner_up": runner["eurio_id"] if runner else None,
            "runner_up_score": round(runner_score, 3),
        }

    return {
        **base,
        "stage": "5",
        "reason": "ambiguous_fuzzy",
        "eurio_id": None,
        "candidates": [c["eurio_id"] for c in cands],
        "best_score": round(score, 3),
        "runner_up_score": round(runner_score, 3),
    }
