"""Helpers partagés par les scripts apply_3a..3e d'application des audit decisions.

Module utilitaire — ne fait rien tout seul. Importé par :
  - apply_3a_new_types.py
  - apply_3b_rematch.py
  - apply_3c_move_to_variant.py
  - apply_3d_add_as_variant.py
  - apply_3e_review_queue.py

Contient :
  - chargement de l'audit JSON
  - cross-matching ORPHAN_NEW_TYPE ↔ IN_REF_WRONG par overlap thématique
  - détection joint-issue (Rome 2007, EMU 2009, Euro Cash 2012, EU Flag 2015,
    Erasmus 2022)
  - génération slug eurio_id depuis un nom catalog Numista
  - parser de variant suffix (cohérent avec l'audit)

Aucun appel Supabase ici — chaque script fait ses propres I/O.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.eurio_referential import slugify  # noqa: E402

AUDIT_JSON = ML_DIR / "datasets" / "audit_referential_v2.json"


# ─── Audit data ──────────────────────────────────────────────────────────────


def load_audit() -> list[dict]:
    """Return the full list of audit records."""
    return json.loads(AUDIT_JSON.read_text())["records"]


def by_classification(records: list[dict]) -> dict[str, list[dict]]:
    """Group audit records by their classification."""
    out: dict[str, list[dict]] = {}
    for r in records:
        out.setdefault(r["classification"], []).append(r)
    return out


# ─── Joint-issue detection ───────────────────────────────────────────────────


JOINT_ISSUES: list[tuple[str, str, int, str]] = [
    # (regex_to_match_name, theme_slug, year, designation)
    (r"\bTreaty of Rome\b|\b50th\s+Anniversary.*Rome\b", "rome", 2007,
     "Joint issue — 50e anniversaire du Traité de Rome"),
    (r"\bEconomic and Monetary Union\b|\bEMU\b|\b10th anniversary.*Economic\b",
     "emu", 2009, "Joint issue — 10 ans de l'Union économique et monétaire"),
    (r"\b10 Years.*Euro Cash\b|\bEuro Cash\b", "euro-cash", 2012,
     "Joint issue — 10 ans de la mise en circulation de l'euro"),
    (r"\b(?:30 Years.*)?European Union Flag\b|\b30 Years.*Flag\b",
     "eu-flag", 2015, "Joint issue — 30 ans du drapeau européen"),
    (r"\bErasmus\b", "erasmus", 2022,
     "Joint issue — 35 ans du programme Erasmus"),
]


def detect_joint_issue(catalog_name: str, year: int) -> tuple[str, str] | None:
    """Return (theme_slug, designation) if the catalog name matches a known joint
    issue *for the right year*, else None.

    The year guard avoids false positives (e.g. a "Treaty of Rome" coin minted
    in 2017 — not a joint issue, just a national commemo using the same theme).
    """
    for rx, theme, expected_year, designation in JOINT_ISSUES:
        if year != expected_year:
            continue
        if re.search(rx, catalog_name or "", re.IGNORECASE):
            return theme, designation
    return None


def joint_design_group_id(theme: str, year: int) -> str:
    """Build the canonical design_group id for a joint issue."""
    return f"eu-{theme}-{year}"


# ─── Cross-matching WRONG ↔ NEW_TYPE ─────────────────────────────────────────


_STOPWORDS = {
    # Pure stopwords
    "and", "the", "of", "to", "in", "on", "at", "a", "an", "for", "by",
    "with", "from", "is", "are", "was", "were", "be", "been", "being",
    # Generic time/anniversary noise that creates false equalities between
    # unrelated themes ("D-Day" vs "World AIDS Day" both share "day").
    "year", "years", "day", "days", "since", "anniversary", "th",
    "th",  # ordinal suffix that anyascii may leave
    "centenary", "celebrating", "celebration",
    # European-coin-specific noise (appears in 30%+ of names)
    "europe", "european", "eu", "union",
    # Currency / context filler
    "euro", "euros", "cent", "cents",
}

# Ruler/portrait noise that often appears in catalog names like
# "2 Euros - Albert II (Treaty of Rome)" — strip to focus on the design.
# WARNING: "euro" / "euros" is intentionally NOT in this list because it
# legitimately appears in valid themes ("10 Years of Euro Cash", "European
# Union Flag", "Euro Coast"). We only strip the leading "2 Euro(s) - …" prefix
# separately in _strip_value_prefix().
_NAME_NOISE_RX = re.compile(
    r"\b(albert\s+ii|philippe|henri\s+i|francis|"
    r"benedict\s+xvi|sede\s+vacante|willem-alexander|beatrix|felipe\s+vi)\b",
    re.IGNORECASE,
)

# Strip "2 Euro[s] [- Ruler]" prefix (always at start of catalog name).
_VALUE_PREFIX_RX = re.compile(
    r"^\s*\d+\s*(?:euros?|cent[s]?)\s*(?:-\s*[A-Z][a-zA-ZÀ-ſ\s]+?)?\s*",
)


def _strip_value_prefix(text: str) -> str:
    """Remove leading '2 Euros' or '2 Euros - Albert II' from a catalog name."""
    if not text:
        return text
    # Apply once on the raw text — if a paren block follows, the regex won't
    # cross into it because we stop at the next whitespace before '('.
    return _VALUE_PREFIX_RX.sub("", text, count=1).strip()


def _theme_text(catalog_name: str) -> str:
    """Extract the comparable theme text from a catalog name.

    Strategy:
      1. Strip "2 Euros [- Ruler]" prefix.
      2. If parenthesized text exists, use it (typical Numista format).
      3. Strip remaining ruler / portrait noise inside the theme.
      4. Lowercase, strip non-alphanum, collapse spaces.
    """
    if not catalog_name:
        return ""
    stripped = _strip_value_prefix(catalog_name)
    m = re.search(r"\(([^)]+)\)", stripped)
    raw = m.group(1) if m else stripped
    raw = _NAME_NOISE_RX.sub(" ", raw)
    raw = raw.lower()
    raw = re.sub(r"[^a-z0-9 ]", " ", raw)
    return " ".join(raw.split())


def theme_tokens(text: str) -> set[str]:
    """Tokenize a theme text into significant tokens (no stopwords, len > 2)."""
    return {t for t in text.split() if len(t) > 2 and t not in _STOPWORDS}


def overlap_score(catalog_name: str, ref_theme: str, ref_eurio_id: str) -> float:
    """Score how well a catalog name matches a ref entry's theme.

    Uses (inter / |cat_tokens|) with an expanded stopwords filter that drops
    generic time/europe/anniversary noise. After filtering, identical themes
    like "World AIDS Day" / "Aids Day" share substantive tokens (aids), while
    "D-Day" vs "World AIDS Day" don't share anything substantive.
    """
    cat_tokens = theme_tokens(_theme_text(catalog_name))
    if not cat_tokens:
        return 0.0
    ref_text = " ".join([ref_theme or "", ref_eurio_id or ""])
    ref_tokens = theme_tokens(_theme_text(ref_text))
    if not ref_tokens:
        return 0.0
    return len(cat_tokens & ref_tokens) / len(cat_tokens)


# Reassignment outcome: which NEW_TYPE nids will become rematch candidates
# for which WRONG eurio_ids (vs which stay as legit new types).


def cross_match_wrong_and_new_types(
    records: list[dict],
    min_overlap: float = 0.4,
    min_margin: float = 0.15,
) -> dict[str, Any]:
    """Pair each mis-matched ref entry with a candidate ORPHAN_NEW_TYPE nid in
    the same (country, year, is_commemorative) bucket.

    Three classes of mis-matches are considered:
      - IN_REF_WRONG         (theme overlap < 0.20, hard mismatch)
      - IN_REF_BUT_VARIANT   (currently matched to a variant nid — true classic
                              is often a NEW_TYPE)
      - IN_REF_UNCERTAIN     (0.20 ≤ overlap < 0.40, frontier)

    Returns a dict :
      {
        "rematches":            {eurio_id: candidate_nid},
        "absorbed_nids":        {nid: eurio_id},
        "unresolved_wrong":     [eurio_id],          # WRONG with no candidate
        "create_as_new_types":  [audit_record],      # NEW_TYPEs not absorbed
        "by_source_class":      {eurio_id: classification},  # provenance
        "old_nids":             {eurio_id: old_nid}, # nid currently in cross_refs
        "rematch_details":      {eurio_id: {"old": catalog_name, "new": catalog_name}},
      }
    """
    rematchable_classes = (
        "IN_REF_WRONG",
        "IN_REF_BUT_VARIANT",
        "IN_REF_UNCERTAIN",
    )
    rematchable = [r for r in records if r["classification"] in rematchable_classes]
    new_types = [r for r in records if r["classification"] == "ORPHAN_NEW_TYPE"]

    # Bucket new_types by (country, year, is_commemorative)
    buckets: dict[tuple, list[dict]] = {}
    for r in new_types:
        key = (r["country"], r["year"], r["is_commemorative"])
        buckets.setdefault(key, []).append(r)

    rematches: dict[str, str] = {}
    absorbed: dict[str, str] = {}
    unresolved: list[str] = []
    by_source_class: dict[str, str] = {}
    old_nids: dict[str, str] = {}
    rematch_details: dict[str, dict[str, str]] = {}

    claimed_nids: set[str] = set()

    # Iterate WRONG first (highest priority) then VARIANT then UNCERTAIN so a
    # WRONG never gets starved by a VARIANT claiming its best candidate.
    priority = {"IN_REF_WRONG": 0, "IN_REF_BUT_VARIANT": 1, "IN_REF_UNCERTAIN": 2}
    rematchable.sort(key=lambda r: priority[r["classification"]])

    for w in rematchable:
        key = (w["country"], w["year"], w["is_commemorative"])
        candidates = buckets.get(key, [])
        ref_eid = w["currently_matched_eurio_id"]

        # Score every available candidate against the WRONG's eurio_id text
        ref_theme_proxy = _theme_text(ref_eid.split("-", 3)[-1] if "-" in ref_eid else "")
        scored: list[tuple[float, dict]] = []
        for c in candidates:
            if c["numista_id"] in claimed_nids:
                continue
            sc = overlap_score(c["catalog_name"], ref_theme_proxy, ref_eid)
            scored.append((sc, c))

        scored.sort(reverse=True, key=lambda x: x[0])
        if not scored:
            if w["classification"] == "IN_REF_WRONG":
                unresolved.append(ref_eid)
                old_nids[ref_eid] = w["numista_id"]
                rematch_details[ref_eid] = {
                    "old": w["catalog_name"], "new": None,
                }
            # VARIANT/UNCERTAIN without candidate stay as-is (their own chunks
            # will handle them).
            continue

        best_sc, best_c = scored[0]
        second_sc = scored[1][0] if len(scored) > 1 else 0.0

        # VARIANT and UNCERTAIN need a strong match to claim a nid; we don't
        # want to silently rewrite an "almost OK" match for a marginal score.
        threshold = min_overlap
        if w["classification"] in ("IN_REF_BUT_VARIANT", "IN_REF_UNCERTAIN"):
            threshold = max(threshold, 0.5)

        if best_sc >= threshold and (best_sc - second_sc) >= min_margin:
            rematches[ref_eid] = best_c["numista_id"]
            absorbed[best_c["numista_id"]] = ref_eid
            claimed_nids.add(best_c["numista_id"])
            by_source_class[ref_eid] = w["classification"]
            old_nids[ref_eid] = w["numista_id"]
            rematch_details[ref_eid] = {
                "old": w["catalog_name"],
                "new": best_c["catalog_name"],
            }
        elif w["classification"] == "IN_REF_WRONG":
            unresolved.append(ref_eid)
            old_nids[ref_eid] = w["numista_id"]
            rematch_details[ref_eid] = {"old": w["catalog_name"], "new": None}

    create_as_new = [r for r in new_types if r["numista_id"] not in claimed_nids]

    return {
        "rematches": rematches,
        "absorbed_nids": absorbed,
        "unresolved_wrong": unresolved,
        "create_as_new_types": create_as_new,
        "by_source_class": by_source_class,
        "old_nids": old_nids,
        "rematch_details": rematch_details,
    }


# ─── eurio_id slug generation ────────────────────────────────────────────────


def eurio_id_from_catalog(country: str, year: int, face_value: float,
                          catalog_name: str) -> str:
    """Generate a canonical eurio_id from a catalog entry.

    Pattern: {country-lower}-{year}-{face_code}-{design-slug}

    face_code: 2eur for 2.0, 1eur for 1.0, Xc for cents.
    design-slug: extracted from parenthesized part if present, else from name
      after stripping "2 Euros" and ruler noise.
    """
    if face_value == 2.0:
        face_code = "2eur"
    elif face_value == 1.0:
        face_code = "1eur"
    else:
        cents_map = {0.01: "1c", 0.02: "2c", 0.05: "5c",
                     0.10: "10c", 0.20: "20c", 0.50: "50c"}
        face_code = cents_map.get(face_value, f"{face_value}eur")

    # Extract design slug
    stripped = _strip_value_prefix(catalog_name or "")
    m = re.search(r"\(([^)]+)\)", stripped)
    raw = m.group(1) if m else stripped
    raw = _NAME_NOISE_RX.sub(" ", raw)
    # Strip variant suffixes that might have leaked in (defensive)
    raw = re.sub(
        r"\b(coloured?|hologram|gilded|pattern|mule|mis-?strike)\b.*$",
        "", raw, flags=re.IGNORECASE,
    )
    slug = slugify(raw)
    if not slug:
        slug = "unnamed"
    return f"{country.lower()}-{year}-{face_code}-{slug}"
