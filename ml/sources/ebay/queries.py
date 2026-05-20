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

# Country ISO2 → noms localisés. Utilisé pour construire la query eBay
# dans la langue native du marketplace ciblé (cf. vision.md §P3 :
# "EBAY_DE → `2 euro Deutschland 2024`, EBAY_IT → `2 euro Germania 2024`,
# etc."). 6 langues alignées sur SUPPORTED_MARKETPLACES + Numista
# sub-domains.
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

ISO2_TO_NAME_EN: dict[str, str] = {
    "AD": "Andorra", "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria",
    "CY": "Cyprus", "DE": "Germany", "EE": "Estonia", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GR": "Greece", "HR": "Croatia",
    "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "MC": "Monaco", "MT": "Malta", "NL": "Netherlands",
    "PT": "Portugal", "SI": "Slovenia", "SK": "Slovakia",
    "SM": "San Marino", "VA": "Vatican", "eu": "eurozone",
}

ISO2_TO_NAME_DE: dict[str, str] = {
    "AD": "Andorra", "AT": "Österreich", "BE": "Belgien", "BG": "Bulgarien",
    "CY": "Zypern", "DE": "Deutschland", "EE": "Estland", "ES": "Spanien",
    "FI": "Finnland", "FR": "Frankreich", "GR": "Griechenland", "HR": "Kroatien",
    "IE": "Irland", "IT": "Italien", "LT": "Litauen", "LU": "Luxemburg",
    "LV": "Lettland", "MC": "Monaco", "MT": "Malta", "NL": "Niederlande",
    "PT": "Portugal", "SI": "Slowenien", "SK": "Slowakei",
    "SM": "San Marino", "VA": "Vatikan", "eu": "Eurozone",
}

ISO2_TO_NAME_IT: dict[str, str] = {
    "AD": "Andorra", "AT": "Austria", "BE": "Belgio", "BG": "Bulgaria",
    "CY": "Cipro", "DE": "Germania", "EE": "Estonia", "ES": "Spagna",
    "FI": "Finlandia", "FR": "Francia", "GR": "Grecia", "HR": "Croazia",
    "IE": "Irlanda", "IT": "Italia", "LT": "Lituania", "LU": "Lussemburgo",
    "LV": "Lettonia", "MC": "Monaco", "MT": "Malta", "NL": "Paesi Bassi",
    "PT": "Portogallo", "SI": "Slovenia", "SK": "Slovacchia",
    "SM": "San Marino", "VA": "Vaticano", "eu": "Eurozona",
}

ISO2_TO_NAME_ES: dict[str, str] = {
    "AD": "Andorra", "AT": "Austria", "BE": "Bélgica", "BG": "Bulgaria",
    "CY": "Chipre", "DE": "Alemania", "EE": "Estonia", "ES": "España",
    "FI": "Finlandia", "FR": "Francia", "GR": "Grecia", "HR": "Croacia",
    "IE": "Irlanda", "IT": "Italia", "LT": "Lituania", "LU": "Luxemburgo",
    "LV": "Letonia", "MC": "Mónaco", "MT": "Malta", "NL": "Países Bajos",
    "PT": "Portugal", "SI": "Eslovenia", "SK": "Eslovaquia",
    "SM": "San Marino", "VA": "Vaticano", "eu": "Eurozona",
}

ISO2_TO_NAME_NL: dict[str, str] = {
    "AD": "Andorra", "AT": "Oostenrijk", "BE": "België", "BG": "Bulgarije",
    "CY": "Cyprus", "DE": "Duitsland", "EE": "Estland", "ES": "Spanje",
    "FI": "Finland", "FR": "Frankrijk", "GR": "Griekenland", "HR": "Kroatië",
    "IE": "Ierland", "IT": "Italië", "LT": "Litouwen", "LU": "Luxemburg",
    "LV": "Letland", "MC": "Monaco", "MT": "Malta", "NL": "Nederland",
    "PT": "Portugal", "SI": "Slovenië", "SK": "Slowakije",
    "SM": "San Marino", "VA": "Vaticaan", "eu": "Eurozone",
}

NAMES_BY_LANG: dict[str, dict[str, str]] = {
    "fr": ISO2_TO_NAME_FR,
    "en": ISO2_TO_NAME_EN,
    "de": ISO2_TO_NAME_DE,
    "it": ISO2_TO_NAME_IT,
    "es": ISO2_TO_NAME_ES,
    "nl": ISO2_TO_NAME_NL,
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


def build_query(coin: CoinIdentity, query_lang: str = "fr") -> EbayQuery:
    """Build (q, aspect_filter, theme_tokens) for a coin search.

    `query_lang` choisit la table de noms-pays utilisée — il doit
    correspondre à la langue native du marketplace ciblé (cf. vision.md
    §P3). Défaut "fr" pour compat avec le code legacy mono-marketplace ;
    l'adapter multi-mkt (B4) passe la lang explicite.

    On cast a wide net with country + year only — adding full theme
    keywords crushes recall because eBay titles are short and use
    different phrasings. The theme tokens are returned separately so
    the caller can apply a title keyword filter on the response when
    multiple commemos share the same (country, year).
    """
    iso2 = coin.country
    names = NAMES_BY_LANG.get(query_lang, ISO2_TO_NAME_FR)
    country_name = names.get(iso2, coin.country_name or iso2)
    denom_label = "2 euro" if coin.face_value == 2.0 else f"{coin.face_value} euro"
    q = f"{denom_label} {country_name} {coin.year}".strip()
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


def _legacy_title_matches_theme(title: str, theme_tokens: list[str]) -> bool:
    """Legacy matcher : tokens issus du slug EN + aliases FR hand-curated.

    Conservé pour le **fallback compat** quand ``coin_names_i18n`` est
    vide pour un eurio_id (run avant I1, ou couverture incomplète).
    Sera **retiré en V2** (cutover) une fois la couverture i18n
    confirmée > 95 % et le matcher multilingue validé empiriquement.

    Quand ``theme_tokens`` est vide (standard ou commémo unique pour
    (country, year)), retourne ``True`` permissivement — l'aspect
    filter seul suffit à épingler le coin.
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


def title_matches_theme(
    title: str,
    eurio_id: str,
    *,
    marketplace: str,
    conn: sqlite3.Connection,
) -> bool:
    """Theme-match multilingue conscient du marketplace courant.

    Pour chaque langue active du marketplace (cf.
    ``MARKETPLACE_ACTIVE_LANGS``), charge le titre Numista localisé
    et extrait des tokens discriminants (cf. ``theme_tokens``). Match
    si ≥ 1 token apparaît dans le titre seller normalisé.

    Fallback compat (deprecated, retiré en V2) : si aucun titre i18n
    n'est dispo pour ``(eurio_id, langs actives)``, retombe sur
    ``_legacy_title_matches_theme`` avec les tokens issus du slug EN.

    Sémantique permissive :
    - Si au moins un titre i18n est trouvé MAIS qu'aucun ne produit
      de tokens (cas standard avec titre court), retourne ``True`` —
      même comportement que legacy quand ``theme_tokens=[]``.
    - Si aucun titre i18n n'est trouvé pour aucune lang active,
      fallback complet sur le matcher legacy.
    """
    from .marketplaces import MARKETPLACE_ACTIVE_LANGS
    from .theme_tokens import extract_tokens, load_i18n_title, normalize

    active_langs = MARKETPLACE_ACTIVE_LANGS.get(marketplace, ["en"])
    title_norm = normalize(title)

    any_title_found = False
    any_token_extracted = False

    for lang in active_langs:
        numista_title = load_i18n_title(conn, eurio_id, lang)
        if numista_title is None:
            continue
        any_title_found = True
        tokens = extract_tokens(numista_title, lang)
        if tokens:
            any_token_extracted = True
        for tok in tokens:
            if tok in title_norm:
                return True

    if not any_title_found:
        # Fallback compat : pas de couverture i18n → matcher legacy.
        return _legacy_title_matches_theme(title, _theme_keywords(eurio_id))

    if not any_token_extracted:
        # i18n présent mais tokens vides partout (standard ou titre
        # trop court). Permissif comme le legacy sur theme_tokens=[].
        return True

    return False
