"""Filtres anti-bruit + détection de lot pour les listings eBay.

Trois rôles distincts :

1. ``listing_row(item)`` — normalise une réponse eBay (item summary OU
   variation d'item group) vers un dict commun consommé par les filtres.
2. ``accept_listing(row, face_value)`` — applique le filtre prix / devise /
   noise titre. Décide si on garde le listing.
3. ``is_lot_suspected(title)`` — D-26 niveau 1 : flag heuristique
   "ce listing semble vendre plusieurs pièces". Le listing est gardé
   (on a les images), mais routé vers ``review_queue.kind='lot'`` plus tard.

Largement extrait du legacy ``ml/market/scrape_ebay.py`` (NOISE_PATTERNS,
accept_listing, listing_row), avec une distinction sémantique nouvelle :
le legacy rejetait les lots en bloc ; ici on les **route**.
"""

from __future__ import annotations

import re
from typing import Any

# ── Patterns ─────────────────────────────────────────────────────────────────

# Mots-clefs qui indiquent qu'une annonce vend MULTIPLE pièces (lot,
# coffret, série, rouleau, set-of-N…). D-26 niveau 1.
LOT_PATTERNS = re.compile(
    r"\b("
    r"lot|coffret|s[eé]rie\b|collection\s*compl[eè]te|"
    r"rouleau|roll\b|set\s+of\b|set\b"
    r")\b",
    re.IGNORECASE,
)

# Mots-clefs qui indiquent une pièce hors-scope (variantes spéciales,
# erreurs de frappe, métaux précieux, colorisée). On rejette ces
# listings entièrement — pas de pieces standard 2€ là-dedans.
#
# Note (V-1 fix 2026-05-18) : on a retiré ``bu\b`` qui faisait rejeter
# des pièces standard parfaitement valides ("Andorre 2017 BU FDC"). En
# numismatique francophone, BU = Brillant Universel = qualité de frappe
# d'une pièce de circulation, pas une variante hors-scope. ``be\b``
# (Belle Épreuve = proof) reste rejeté à juste titre.
NOISE_PATTERNS = re.compile(
    r"\b("
    r"proof|[eé]preuve|belle\s*[eé]preuve|be\b|"
    r"argent|or\b|silver|gold|plaqu[eé]|"
    r"coloris[eé]e?|color|"
    r"erreur\s*de\s*frappe|faut[eé]e?"
    r")\b",
    re.IGNORECASE,
)

FACE_VALUE_FACTOR_LOW = 0.8
FACE_VALUE_FACTOR_HIGH = 500.0

# Years within sane range to accept as "year-of-coin" in the title.
YEAR_IN_TITLE_RE = re.compile(r"\b(19|20)\d{2}\b")


# ── Listing normalisation ────────────────────────────────────────────────────


def _listing_aspects(item: dict) -> dict[str, str]:
    aspects = item.get("localizedAspects") or []
    return {a.get("name", ""): a.get("value", "") for a in aspects if a.get("name")}


def _parse_percent(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).rstrip("%"))
    except ValueError:
        return None


def listing_row(item: dict) -> dict:
    """Aplatit un item summary (ou une variation de group) vers un dict commun."""
    price = item.get("price") or {}
    avail = (item.get("estimatedAvailabilities") or [{}])[0]
    seller = item.get("seller") or {}
    return {
        "item_id": item.get("itemId"),
        "title": item.get("title") or "",
        "price": float(price["value"]) if price.get("value") else None,
        "currency": price.get("currency"),
        "sold": int(avail.get("estimatedSoldQuantity") or 0),
        "origin_date": item.get("itemOriginDate"),
        "seller": seller.get("username"),
        "seller_fb_pct": _parse_percent(seller.get("feedbackPercentage")),
        "seller_fb_score": seller.get("feedbackScore"),
        "item_web_url": item.get("itemWebUrl"),
        "image_url": (item.get("image") or {}).get("imageUrl"),
        "additional_image_urls": [
            img.get("imageUrl")
            for img in (item.get("additionalImages") or [])
            if img.get("imageUrl")
        ],
        "primary_group_id": (item.get("primaryItemGroup") or {}).get("itemGroupId"),
        "aspects": _listing_aspects(item),
    }


# ── Filters ──────────────────────────────────────────────────────────────────


def is_lot_suspected(title: str | None) -> bool:
    """D-26 niveau 1 : titre suggère un lot/coffret/série."""
    if not title:
        return False
    return bool(LOT_PATTERNS.search(title))


def accept_listing(
    row: dict,
    face_value: float,
    *,
    expected_year: int | None = None,
    is_commemorative: bool = False,
) -> tuple[bool, str]:
    """Filtre prix / devise / noise / millésime. Retourne (kept, reason).

    Note : ``is_lot_suspected`` n'apparaît PAS ici — un lot est *gardé*
    (on veut ses images) mais flaggé. Cette fonction ne rejette que les
    noises hors-scope (proof, métaux précieux, fautées…) et, depuis le
    bloc 1 (2026-05-05), les listings commémoratifs dont le titre
    contient une année différente de celle attendue.

    Policy year-in-title : *accept-on-missing*. Si on ne trouve aucune
    année dans le titre, on accepte (les vendeurs n'écrivent pas tous
    l'année — éviter de crasher le recall sur ce pattern).
    """
    title = row.get("title") or ""
    if NOISE_PATTERNS.search(title):
        return False, "noise_title"
    price = row.get("price")
    if price is None:
        return False, "no_price"
    if row.get("currency") and row["currency"] != "EUR":
        return False, "non_eur"
    if price < face_value * FACE_VALUE_FACTOR_LOW:
        return False, "below_face"
    if price > face_value * FACE_VALUE_FACTOR_HIGH:
        return False, "above_extreme"
    if is_commemorative and expected_year is not None:
        years_in_title = {int(m.group(0)) for m in YEAR_IN_TITLE_RE.finditer(title)}
        if years_in_title and expected_year not in years_in_title:
            return False, "year_mismatch"
    return True, "ok"
