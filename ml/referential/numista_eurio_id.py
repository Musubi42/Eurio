"""Pure function : Numista payload → eurio_id Eurio (+ aux derivation info).

Voir docs/research/numista-clean-refetch-kickoff.md §5 et
docs/research/numista-clean-refetch-progress.md.

CONTRAT (à lire avant toute modification)
─────────────────────────────────────────
1. Ce module est une **fonction pure** du payload Numista. Même payload →
   même résultat, toujours. Aucune connaissance externe (BCE, Wikipedia,
   intuition) ne doit influencer le slug — sauf via `MANUAL_NID_SLUG_OVERRIDES`,
   keyé par `numista_id` (stable Numista-side) avec citation de source en
   commentaire.

2. Le slug est **gelé à la création** d'un Type. Si Numista renomme
   `catalog_name` plus tard, l'orchestrateur update les métadonnées mais
   NE touche PAS l'eurio_id. Le binding survit aux renames côté Numista.

3. Out-of-scope = None. Ce module ne traite que 2€ (Phase 1 du refetch
   greenfield). Le caller doit gérer ce cas.

4. **Joint-issues** : la détection émet `design_group_id = 'eu-{theme}-{year}'`
   pour permettre à l'orchestrateur de bootstrap les `design_groups`. Le slug
   eurio_id lui-même est dérivé du parens content normal (typique Numista
   "(Treaty of Rome)"), donc chaque pays a son eurio_id distinct partageant le
   même design_group.

5. **Variants** (coloured/hologram/gilded/pattern/mule) : on détecte le suffix,
   on strip pour produire le slug du **parent classic**, et on signale
   `is_variant=True` + `variant_finish` pour que l'orchestrateur crée le row
   coin_variants au lieu (ou en plus) d'un coin de type Type.

Voir tests/test_numista_eurio_id.py pour la suite de fixtures.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.eurio_referential import slugify  # noqa: E402


# ─── Manual overrides (escape hatch) ─────────────────────────────────────────
#
# Keyed by Numista `id` (str). Each entry MUST cite an authoritative external
# source in the comment above it. Empty for the greenfield refetch start —
# entries are added a posteriori via the admin review queue when an ambiguity
# is found that justifies freezing a specific slug.

MANUAL_NID_SLUG_OVERRIDES: dict[str, str] = {
    # Template — leave commented unless adding a real override:
    # "105616": "francis-2nd-map",  # VA 2017 — source: Wikipedia <url>
}


# ─── Joint-issue detection ───────────────────────────────────────────────────
#
# Year guard is essential : a coin named "Treaty of Rome" minted in 2017 is
# NOT the 2007 joint-issue, just a national commemo reusing the theme.

JOINT_ISSUES: list[tuple[str, str, int, str]] = [
    # (regex, theme_slug, expected_year, designation)
    (r"\bTreaty of Rome\b|\b50th\s+Anniversary.*Rome\b", "rome", 2007,
     "Joint issue — 50e anniversaire du Traité de Rome"),
    (r"\bEconomic and Monetary Union\b|\bEMU\b|\b10th anniversary.*Economic\b",
     "emu", 2009,
     "Joint issue — 10 ans de l'Union économique et monétaire"),
    (r"\b10 Years.*Euro Cash\b|\bEuro Cash\b", "euro-cash", 2012,
     "Joint issue — 10 ans de la mise en circulation de l'euro"),
    (r"\b(?:30 Years.*)?European Union Flag\b|\b30 Years.*Flag\b",
     "eu-flag", 2015,
     "Joint issue — 30 ans du drapeau européen"),
    (r"\bErasmus\b", "erasmus", 2022,
     "Joint issue — 35 ans du programme Erasmus"),
]


def detect_joint_issue(catalog_name: str, year: int) -> tuple[str, str] | None:
    """Return (theme_slug, designation) if the catalog name matches a known
    joint issue *for the right year*, else None."""
    for rx, theme, expected_year, designation in JOINT_ISSUES:
        if year != expected_year:
            continue
        if re.search(rx, catalog_name or "", re.IGNORECASE):
            return theme, designation
    return None


def joint_design_group_id(theme: str, year: int) -> str:
    """Build the canonical design_group id for a joint issue."""
    return f"eu-{theme}-{year}"


# ─── Variant detection ───────────────────────────────────────────────────────
#
# Variants are finishes that don't change the canonical design : the parent
# Type covers the obverse + reverse engraving, the variant covers the finish
# (coloured, hologram, gilded, pattern, mule).
#
# The Numista catalog_name pattern is typically :
#   "2 Euros - Albert II (Treaty of Rome) [coloured]"
#   "2 Euros (Erasmus, hologram)"
#   "2 Euros - Albert II (gilded, pattern)"
# Detection is conservative — we only match well-known finishes to avoid
# false positives. Unknown ones partent en `needs_review`.

_VARIANT_FINISHES = ("coloured", "colored", "hologram", "gilded", "pattern", "mule",
                     "mis-strike", "misstrike", "miscoin")
_VARIANT_RX = re.compile(
    r"\b(" + "|".join(_VARIANT_FINISHES) + r")\b",
    re.IGNORECASE,
)


def detect_variant(catalog_name: str) -> tuple[bool, str | None]:
    """Detect variant finish suffix.

    Returns (is_variant, finish_slug or None). `finish_slug` is normalized
    (e.g. 'colored' → 'coloured', 'misstrike' → 'mis-strike').
    """
    if not catalog_name:
        return False, None
    m = _VARIANT_RX.search(catalog_name)
    if not m:
        return False, None
    raw = m.group(1).lower()
    normalized = {
        "colored": "coloured",
        "misstrike": "mis-strike",
        "miscoin": "mis-strike",
    }.get(raw, raw)
    return True, normalized


# ─── Commemo vs Standard ─────────────────────────────────────────────────────


def is_commemorative_payload(payload: dict) -> bool:
    """Detect commemorative status from a raw Numista payload.

    Precedence :
      1. `commemorated_topic` populated → commemorative
      2. title contains 'commemorative' → commemorative
      3. else → standard
    """
    if payload.get("commemorated_topic"):
        return True
    title = (payload.get("title") or "").lower()
    if "commemorative" in title:
        return True
    return False


# ─── Slug extractors ─────────────────────────────────────────────────────────
#
# Ruler/portrait noise stripped from commemos (the ruler is irrelevant to the
# design — Albert II 2008 and Albert II 2009 are different commemos).
# For standards, the ruler IS the design (Philippe vs Albert II vs Sede Vacante
# are distinct design types), so we keep it.

_NAME_NOISE_RX = re.compile(
    r"\b(albert\s+ii|philippe|henri\s+i|francis|"
    r"benedict\s+xvi|sede\s+vacante|willem-alexander|beatrix|felipe\s+vi)\b",
    re.IGNORECASE,
)
_VALUE_PREFIX_RX = re.compile(
    r"^\s*\d+\s*(?:euros?|cent[s]?)\s*(?:-\s*)?",
    re.IGNORECASE,
)


def _strip_variant_suffix(text: str) -> str:
    """Remove variant finish tokens from text so the parent slug isn't polluted.

    Matches Numista's typical pattern : '[coloured]', '(... hologram)',
    ', gilded', etc. We strip the whole bracketed/parenthesized chunk if it's
    *exclusively* a variant marker; otherwise we strip just the token.
    """
    if not text:
        return text
    # Remove standalone "[coloured]" / "[hologram]" trailing markers
    text = re.sub(r"\s*\[(?:" + "|".join(_VARIANT_FINISHES) + r")\]\s*$",
                  "", text, flags=re.IGNORECASE)
    # Strip embedded tokens
    text = _VARIANT_RX.sub("", text)
    # Clean up leftover delimiters
    text = re.sub(r"\(\s*,?\s*\)", "", text)        # empty parens
    text = re.sub(r"\(\s*,\s*", "(", text)          # leading comma in parens
    text = re.sub(r",\s*\)", ")", text)             # trailing comma in parens
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;-")
    return text


def commemo_slug(catalog_name: str) -> str:
    """Slug for a commemorative coin.

    Strategy : use parenthesized theme if present, else the leading text after
    stripping '2 Euros [- Ruler]' prefix. Ruler/portrait noise removed.
    """
    if not catalog_name:
        return "unnamed"
    cleaned = _strip_variant_suffix(catalog_name)
    stripped = _VALUE_PREFIX_RX.sub("", cleaned, count=1).strip()
    m = re.search(r"\(([^)]+)\)", stripped)
    raw = m.group(1) if m else stripped
    raw = _NAME_NOISE_RX.sub(" ", raw)
    slug = slugify(raw)
    return slug or "unnamed"


def standard_slug(catalog_name: str) -> str:
    """Slug for a standard (circulation, non-commemorative) coin.

    Strategy : keep ruler name AND parenthesized qualifier — both are valid
    distinguishers for standards. Fallback `1st-type` if nothing extractable.
    """
    if not catalog_name:
        return "1st-type"
    cleaned = _strip_variant_suffix(catalog_name)
    text = _VALUE_PREFIX_RX.sub("", cleaned, count=1).strip()
    paren_match = re.search(r"\(([^)]+)\)", text)
    paren_content = paren_match.group(1).strip() if paren_match else ""
    leading = re.sub(r"\([^)]*\)", "", text).strip(" -;,")
    combined = " ".join(filter(None, [leading, paren_content]))
    if not combined:
        return "1st-type"
    return slugify(combined) or "1st-type"


# ─── Main pure function ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class NumistaSlugResult:
    eurio_id: str                       # canonical Eurio ID (Type level)
    country: str                        # ISO2 uppercase
    year: int
    face_value: float                   # 2.0 for Phase 1
    is_commemorative: bool
    is_variant: bool                    # True → this nid is a finish variant
    variant_finish: str | None          # 'coloured'|'hologram'|'gilded'|'pattern'|'mule'|'mis-strike'
    is_joint_issue: bool
    design_group_id: str | None         # 'eu-{theme}-{year}' if joint
    joint_theme: str | None             # 'rome'|'emu'|'euro-cash'|'eu-flag'|'erasmus'
    joint_designation: str | None       # human-readable for design_groups.designation
    theme: str | None                   # human-readable theme (parens content) for coins.theme
    catalog_name: str                   # echo back for traceability
    used_override: bool                 # True if MANUAL_NID_SLUG_OVERRIDES matched


def _extract_theme(catalog_name: str) -> str | None:
    """Human-readable theme = leading ruler + parens content joined by em-dash.

    Same convention as apply_3f_standards._extract_theme.
    """
    if not catalog_name:
        return None
    cleaned = _strip_variant_suffix(catalog_name)
    text = _VALUE_PREFIX_RX.sub("", cleaned, count=1).strip()
    paren = re.search(r"\(([^)]+)\)", text)
    paren_content = paren.group(1).strip() if paren else ""
    leading = re.sub(r"\([^)]*\)", "", text).strip(" -;,")
    if leading and paren_content:
        return f"{leading} — {paren_content}"
    return leading or paren_content or None


# Numista issuer.code → ISO2 (modern eurozone + micro-states). The Numista
# code is a slug (often French) — `allemagne` = Germany, `lituanie` = Lithuania
# etc. Curated 2026-05-16 from GET /v3/issuers, cross-checked against actual
# 2€ coin payloads. ⚠ Numista issuer.name uses long forms ("Germany, Federal
# Republic of") that don't match short ISO2 names, so we MUST resolve via code.
_NUMISTA_CODE_TO_ISO2: dict[str, str] = {
    "andorre": "AD",      "austria": "AT",     "belgium": "BE",
    "bulgarie": "BG",     "croatia": "HR",     "chypre": "CY",
    "estonie": "EE",      "finlande": "FI",    "france": "FR",
    "allemagne": "DE",    "greece": "GR",      "irlande": "IE",
    "italy": "IT",        "lettonie": "LV",    "lituanie": "LT",
    "luxembourg": "LU",   "malte": "MT",       "monaco": "MC",
    "netherlands": "NL",  "portugal": "PT",    "saint-marin": "SM",
    "slovaquie": "SK",    "slovenie": "SI",    "spain": "ES",
    "vatican": "VA",
}


def _extract_country_iso2(payload: dict) -> str | None:
    """Resolve ISO2 country code from Numista issuer block.

    Order:
      1. `issuer.code` is a 2-char string → use as-is (defensive, rare)
      2. `issuer.code` matches `_NUMISTA_CODE_TO_ISO2` → translate
      3. `issuer.name` matches a name fallback → translate (last resort)
    """
    issuer = payload.get("issuer") or {}
    code = (issuer.get("code") or "").strip().lower()
    if code in _NUMISTA_CODE_TO_ISO2:
        return _NUMISTA_CODE_TO_ISO2[code]
    if len(code) == 2:
        return code.upper()
    # Fallback: name-based (in case Numista adds a new issuer code we haven't
    # mapped yet, but issuer.name is recognizable).
    name = (issuer.get("name") or "").strip()
    name_map = {
        "Andorra": "AD", "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG",
        "Croatia": "HR", "Cyprus": "CY", "Estonia": "EE", "Finland": "FI",
        "France": "FR", "Germany": "DE", "Greece": "GR", "Ireland": "IE",
        "Italy": "IT", "Latvia": "LV", "Lithuania": "LT", "Luxembourg": "LU",
        "Malta": "MT", "Monaco": "MC", "Netherlands": "NL", "Portugal": "PT",
        "San Marino": "SM", "Slovakia": "SK", "Slovenia": "SI",
        "Spain": "ES", "Vatican City": "VA",
        # Long forms Numista uses occasionally:
        "Germany, Federal Republic of": "DE",
    }
    return name_map.get(name)


def eurio_id_from_numista_payload(payload: dict) -> NumistaSlugResult | None:
    """Pure function : Numista payload → Eurio Type-level slug + derivation info.

    Returns None if the payload is out of scope (not a 2€ coin, or missing
    required fields like country/year). The caller is responsible for
    propagating None to the orchestrator's skip list.
    """
    if not payload:
        return None

    # 1. Scope filter — 2€ EUR only for Phase 1
    value = payload.get("value") or {}
    if value.get("numeric_value") != 2:
        return None
    currency_name = ((value.get("currency") or {}).get("name") or "").lower()
    if "euro" not in currency_name:
        return None

    # 2. Canonical fields
    country = _extract_country_iso2(payload)
    year = payload.get("min_year")
    nid = payload.get("id")
    catalog_name = payload.get("title") or ""

    if not country or not year or not nid:
        return None

    nid_str = str(nid)
    country_lower = country.lower()

    # 3. Manual override (escape hatch — fully bypasses computation)
    if nid_str in MANUAL_NID_SLUG_OVERRIDES:
        slug = MANUAL_NID_SLUG_OVERRIDES[nid_str]
        return NumistaSlugResult(
            eurio_id=f"{country_lower}-{year}-2eur-{slug}",
            country=country,
            year=int(year),
            face_value=2.0,
            is_commemorative=is_commemorative_payload(payload),
            is_variant=False,
            variant_finish=None,
            is_joint_issue=False,
            design_group_id=None,
            joint_theme=None,
            joint_designation=None,
            theme=_extract_theme(catalog_name),
            catalog_name=catalog_name,
            used_override=True,
        )

    # 4. Variant detection — variant nids slug to PARENT's slug; caller binds
    is_variant, finish = detect_variant(catalog_name)

    # 5. Joint-issue detection
    ji = detect_joint_issue(catalog_name, int(year))
    joint_theme = ji[0] if ji else None
    joint_designation = ji[1] if ji else None
    design_group_id = joint_design_group_id(joint_theme, int(year)) if ji else None

    # 6. Commemo vs Standard → slug strategy
    is_commemo = is_commemorative_payload(payload)
    if is_commemo or ji:  # joint-issues are always commemo
        slug = commemo_slug(catalog_name)
        eurio_id = f"{country_lower}-{year}-2eur-{slug}"
        is_commemo = True
    else:
        slug = standard_slug(catalog_name)
        eurio_id = f"{country_lower}-{year}-2eur-standard-{slug}"

    return NumistaSlugResult(
        eurio_id=eurio_id,
        country=country,
        year=int(year),
        face_value=2.0,
        is_commemorative=is_commemo,
        is_variant=is_variant,
        variant_finish=finish,
        is_joint_issue=bool(ji),
        design_group_id=design_group_id,
        joint_theme=joint_theme,
        joint_designation=joint_designation,
        theme=_extract_theme(catalog_name),
        catalog_name=catalog_name,
        used_override=False,
    )
