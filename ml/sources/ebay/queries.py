"""Build eBay Browse API queries from a canonical eurio_id.

Reads coin metadata from the SQLite ``coins`` table (D-20, bootstrappée
via ``go-task ml:bootstrap-coins``). Returns the search query string,
the aspect filter, and the theme keyword tokens used for ambiguity
resolution.

Largement extrait du legacy ``ml/market/scrape_ebay.py`` (build_search_query,
_theme_keywords, STOP_WORDS) avec deux changements :
- la source des métadonnées passe de JSON à SQLite (table ``coins``)
- on retourne aussi la category eBay pour faciliter le câblage adapter
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

CATEGORY_EURO_COINS = "32650"

# Country ISO2 → French name (used in the search query because EBAY_FR
# titles are mostly in French). Mirror of ml/referential/eurio_referential.py
# pour éviter un import cross-module sur un dict statique.
ISO2_TO_NAME_FR: dict[str, str] = {
    "AD": "Andorre",
    "AT": "Autriche",
    "BE": "Belgique",
    "BG": "Bulgarie",
    "CY": "Chypre",
    "DE": "Allemagne",
    "EE": "Estonie",
    "ES": "Espagne",
    "FI": "Finlande",
    "FR": "France",
    "GR": "Grèce",
    "HR": "Croatie",
    "IE": "Irlande",
    "IT": "Italie",
    "LT": "Lituanie",
    "LU": "Luxembourg",
    "LV": "Lettonie",
    "MC": "Monaco",
    "MT": "Malte",
    "NL": "Pays-Bas",
    "PT": "Portugal",
    "SI": "Slovénie",
    "SK": "Slovaquie",
    "SM": "Saint-Marin",
    "VA": "Vatican",
    "eu": "zone euro",
}

# Stop words dropped when extracting theme tokens from the eurio_id slug.
# Adding country-specific filler words keeps theme matching crisp.
STOP_WORDS = {
    "of", "the", "in", "and", "a", "an", "to", "for", "with", "on",
    "de", "la", "le", "les", "du", "des", "et", "au", "aux",
    "anniversary", "years", "since", "birth", "death", "founding",
    "th", "st", "nd", "rd",
}

# Country slug tokens that can appear inside an eurio_id slug
# (eurio_id format: ``<iso2>-<year>-<denom>-<theme...>``). Numista
# often repeats the country name inside the theme — e.g.
# ``ad-2017-2eur-100-years-of-the-anthem-of-andorra``. These tokens
# describe WHERE the coin is from, not WHAT the commemo celebrates,
# so they don't discriminate sibling commemos within the same
# (country, year). Dropping them avoids accepting a "Pays des Pyrénées"
# listing under an "anthem" target just because both titles mention
# Andorre (V-1 anomaly A4, 2026-05-18).
COUNTRY_SLUG_TOKENS: set[str] = {
    "andorra", "austria", "belgium", "bulgaria", "croatia", "cyprus",
    "estonia", "finland", "france", "germany", "greece", "ireland",
    "italy", "latvia", "lithuania", "luxembourg", "malta", "monaco",
    "netherlands", "portugal", "slovakia", "slovenia", "spain",
    "vatican",
    # San Marino is hyphenated → its components appear as separate tokens.
    "san", "marino",
}

# eurio_id slugs are English; eBay FR titles are French. Without a
# bilingual matcher, theme tokens like ``anthem`` never match titles
# like ``"100 ans de l'hymne d'Andorre"`` → 80%+ false reject rate
# measured V-1 (2026-05-18). Map English theme tokens to a list of
# French aliases (substring-matched, case-insensitive). Add new
# entries as we encounter coins where matching fails — keep narrow.
THEME_TOKEN_FR_ALIASES: dict[str, list[str]] = {
    # Toponymes / pays (utiles quand le pays apparaît aussi dans le thème)
    "andorra":   ["andorre"],
    "germany":   ["allemagne"],
    "france":    ["france"],
    "italy":     ["italie"],
    "spain":     ["espagne"],
    "belgium":   ["belgique"],
    "austria":   ["autriche"],
    "portugal":  ["portugal"],
    "greece":    ["grèce", "grece"],
    "ireland":   ["irlande"],
    "finland":   ["finlande"],
    "luxembourg": ["luxembourg"],
    "monaco":    ["monaco"],
    "vatican":   ["vatican"],

    # Concepts récurrents sur les commémos 2€
    "anthem":    ["hymne"],
    "world":     ["monde", "mondiale", "mondial"],
    "cup":       ["coupe"],
    "alpine":    ["alpin", "alpine"],
    "peace":     ["paix"],
    "treaty":    ["traité", "traite"],
    "history":   ["histoire", "historique"],
    "museum":    ["musée", "musee"],
    "century":   ["siècle", "siecle"],
    "olympic":   ["olympique"],
    "olympics":  ["olympiques", "olympique"],
    "king":      ["roi"],
    "queen":     ["reine"],
    "republic":  ["république", "republique"],
    "constitution": ["constitution"],
    "independence": ["indépendance", "independance"],
    "european":  ["européen", "europeen", "européenne", "europeenne"],
    "europe":    ["europe"],
    "union":     ["union"],
    "flag":      ["drapeau"],
    "national":  ["national", "nationale"],
    "centenary": ["centenaire"],
    "bicentenary": ["bicentenaire"],
    "millennium": ["millénaire", "millenaire"],
    "founding":  ["fondation"],
    "death":     ["mort", "décès", "deces"],
    "birth":     ["naissance"],
}


@dataclass(frozen=True)
class CoinIdentity:
    """Subset of `coins` columns needed to build an eBay query."""

    eurio_id: str
    country: str
    country_name: str | None
    year: int
    face_value: float
    is_commemorative: bool


@dataclass(frozen=True)
class EbayQuery:
    q: str                              # search keyword string
    aspect_filter: str                  # eBay aspect filter
    theme_tokens: list[str]             # keywords for title disambiguation
    category_id: str = CATEGORY_EURO_COINS


class CoinNotFound(KeyError):
    """Raised when an eurio_id has no row in the ``coins`` table."""


def load_coin(conn: sqlite3.Connection, eurio_id: str) -> CoinIdentity:
    row = conn.execute(
        """
        SELECT eurio_id, country, country_name, year, face_value, is_commemorative
          FROM coins
         WHERE eurio_id = ?
        """,
        (eurio_id,),
    ).fetchone()
    if row is None:
        raise CoinNotFound(
            f"No coin row for eurio_id={eurio_id!r}. "
            "Bootstrap referential first (`go-task ml:bootstrap-coins`)."
        )
    return CoinIdentity(
        eurio_id=row["eurio_id"],
        country=row["country"],
        country_name=row["country_name"],
        year=int(row["year"]),
        face_value=float(row["face_value"]),
        is_commemorative=bool(row["is_commemorative"]),
    )


def _theme_keywords(eurio_id: str, max_words: int = 4) -> list[str]:
    """Extract theme tokens from the slug part of an eurio_id.

    eurio_id format: ``<country>-<year>-<denom>-<theme...>``. We drop
    the first 3 segments (country/year/denom) and filter out stop words
    and ordinal/year noise (`100th`, stray `1992`).
    """
    slug_tokens = eurio_id.split("-")[3:]
    kept: list[str] = []
    for tok in slug_tokens:
        if not tok:
            continue
        if tok in STOP_WORDS:
            continue
        if tok in COUNTRY_SLUG_TOKENS:
            continue
        if re.match(r"^\d+th$", tok) or re.match(r"^\d{3,4}$", tok):
            continue
        kept.append(tok)
        if len(kept) >= max_words:
            break
    # Only words ≥ 4 chars are useful for title-matching (avoids "war"
    # matching "warm" etc.). 3-char tokens stay in `q` but not in the
    # discriminator list.
    return [t for t in kept if len(t) >= 4]


def build_query(coin: CoinIdentity) -> EbayQuery:
    """Build (q, aspect_filter, theme_tokens) for a coin search on EBAY_FR.

    We cast a wide net with country + year only — adding full theme
    keywords crushes recall because eBay titles are short and use
    different phrasings. The theme tokens are returned separately so
    the caller can apply a title keyword filter on the response when
    multiple commemos share the same (country, year).
    """
    iso2 = coin.country
    name_fr = ISO2_TO_NAME_FR.get(iso2, coin.country_name or iso2)
    denom_label = "2 euro" if coin.face_value == 2.0 else f"{coin.face_value} euro"
    q = f"{denom_label} {name_fr} {coin.year}".strip()
    # Note (bloc 1, 2026-05-05) : on a drop le segment `Année:{...}` du
    # aspect_filter — beaucoup de vendeurs ne remplissent pas l'aspect année,
    # ce qui crashait le recall (×16-50 sur AD/FR mesurés en probe S3). Le
    # tagging year vit désormais en post-filter applicatif côté
    # `accept_listing` (cf. filters.py).
    aspect_filter = f"categoryId:{CATEGORY_EURO_COINS}"
    return EbayQuery(
        q=q,
        aspect_filter=aspect_filter,
        theme_tokens=_theme_keywords(coin.eurio_id, max_words=4),
    )


def title_matches_theme(title: str, theme_tokens: list[str]) -> bool:
    """Return True if any theme token is found in the title (case-insensitive).

    Used only when the query is ambiguous (multiple commemos for the
    same country/year). When `theme_tokens` is empty (only theme is
    "standard" or there's a single commemo), the function permissively
    returns True — the aspect filter alone is enough to pin the coin.

    Bilingual matching (V-1 fix 2026-05-18) : tokens come from the
    English eurio_id slug, but EBAY_FR titles are French. We also
    check each token's French aliases via ``THEME_TOKEN_FR_ALIASES``.
    """
    if not theme_tokens:
        return True
    low = title.lower()
    for tok in theme_tokens:
        if tok in low:
            return True
        for alias in THEME_TOKEN_FR_ALIASES.get(tok, ()):
            if alias in low:
                return True
    return False
