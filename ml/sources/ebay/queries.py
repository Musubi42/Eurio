"""Build eBay Browse API queries from a canonical eurio_id.

Reads coin metadata from the SQLite ``coins`` table (D-20, bootstrappée
via ``go-task ml:bootstrap-coins``). Returns the search query string +
l'aspect filter eBay.

La désambiguïsation des commémos-sœurs (même pays/année) ne se fait plus
sur des tokens de slug : elle vit dans ``title_matches_theme`` (matcher
multilingue I2 adossé à ``coin_names_i18n``). Le matcher legacy par
slug EN + aliases FR a été retiré au cutover V2 (2026-05-21).
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


# ── Limite de résultats variable selon la taille du groupe ───────────────
# eBay Browse `item_summary/search` plafonne `limit` à 200 par appel.
# On vise ~25 résultats/pièce : un groupe de K coins partage la même
# requête, donc plus K est grand, plus on veut large pour ne pas noyer
# une commémo-sœur rare. Au-delà de 200 → pagination (V2).
SEARCH_LIMIT_MIN = 75
SEARCH_LIMIT_MAX = 200
SEARCH_LIMIT_PER_COIN = 25


def search_limit_for_group(n_coins: int) -> int:
    """Limite de résultats eBay pour un groupe de `n_coins` pièces."""
    return max(
        SEARCH_LIMIT_MIN,
        min(SEARCH_LIMIT_MAX, SEARCH_LIMIT_PER_COIN * max(n_coins, 1)),
    )


def build_group_query(
    denomination: float,
    country: str,
    year: int | None,
    query_lang: str = "fr",
) -> EbayQuery:
    """Build (q, aspect_filter) for a discovery group.

    `query_lang` choisit la table de noms-pays utilisée — il doit
    correspondre à la langue native du marketplace ciblé (cf. vision.md
    §P3). La requête ratisse large (denom + pays [+ année]) ; l'attribution
    de chaque listing à une pièce du groupe se fait en aval.

    ``year=None`` → **groupe STANDARD** : pas de millésime dans la requête
    (« 2 euro Spanien »). Le design d'un standard ne dépend pas de l'année ;
    une recherche large couvre toutes les ères, attribuées en aval par
    appartenance de plage (``sources/ebay/standards.py``). On n'ajoute PAS de
    mot-clé « Kursmünze » : il filtrerait le recall (même leçon que l'aspect
    année). Le tri standard/commémo vit dans l'attribution, pas la requête.

    Note (bloc 1, 2026-05-05) : le segment `Année:{...}` de l'aspect_filter
    a été drop — beaucoup de vendeurs ne remplissent pas l'aspect année, ce
    qui crashait le recall (×16-50 sur AD/FR en probe S3). Le tagging year
    vit désormais en post-filter applicatif côté ``accept_listing``.
    """
    names = NAMES_BY_LANG.get(query_lang, ISO2_TO_NAME_FR)
    country_name = names.get(country, country)
    denom_label = "2 euro" if denomination == 2.0 else f"{denomination} euro"
    year_token = "" if year is None else f" {year}"
    q = f"{denom_label} {country_name}{year_token}".strip()
    return EbayQuery(q=q, aspect_filter=f"categoryId:{CATEGORY_EURO_COINS}")


def build_query(coin: CoinIdentity, query_lang: str = "fr") -> EbayQuery:
    """Build (q, aspect_filter) for the discovery group containing `coin`."""
    return build_group_query(coin.face_value, coin.country, coin.year, query_lang)


def load_group_coins(
    conn: sqlite3.Connection,
    denomination: float,
    country: str,
    year: int,
) -> list[CoinIdentity]:
    """Toutes les commémos d'un groupe (denomination, pays, année).

    Le groupe est l'unité de découverte eBay : une recherche, K pièces.
    Périmètre identique à la freshness queue — commémos uniquement
    (``is_commemorative=1``).
    """
    rows = conn.execute(
        """
        SELECT eurio_id, country, country_name, year, face_value, is_commemorative
          FROM coins
         WHERE face_value = ? AND country = ? AND year = ?
           AND is_commemorative = 1
         ORDER BY eurio_id
        """,
        (denomination, country, year),
    ).fetchall()
    return [
        CoinIdentity(
            eurio_id=row["eurio_id"],
            country=row["country"],
            country_name=row["country_name"],
            year=int(row["year"]),
            face_value=float(row["face_value"]),
            is_commemorative=bool(row["is_commemorative"]),
        )
        for row in rows
    ]


def theme_match_state(
    title: str,
    eurio_id: str,
    *,
    conn: sqlite3.Connection,
) -> str:
    """État du theme-match d'un titre seller vs un eurio_id.

    Renvoie l'un de :
    - ``"hit"`` : un token discriminant (toutes langues poolées) apparaît
      dans le titre seller ;
    - ``"undiscriminable"`` : aucun titre i18n trouvé, OU titres trouvés
      mais zéro token discriminant (commémo à titre court / standard) —
      on ne peut pas trancher ;
    - ``"miss"`` : des tokens discriminants existent, aucun n'apparaît.

    Pool de toutes les langues de ``coin_names_i18n`` (et pas seulement
    la langue native du marketplace) : couvre le cross-listing et le
    faux rejet quand la couverture i18n est partielle.

    F.1 (chantier D follow-up, 2026-05-26) : on pool aussi ``coin_topics``
    (commemorated_topic Numista verbeux + feature BCE). Le topic apporte
    des tokens distinctifs ("100", "anniversaire", "1917", "armistice",
    "kniefall") absents du titre court — bump recall sur les listings
    sellers verbeux.
    """
    from .theme_tokens import (
        extract_tokens, load_aliases, load_i18n_title, load_topic, normalize,
    )

    title_norm = normalize(title)

    # Alias de thème (acronymes, termes de marché — chunk C2a). Match en
    # limite de mot : un acronyme court (« emi ») ne doit pas matcher en
    # sous-chaîne (« akademie »).
    aliases = load_aliases(conn, eurio_id)
    for alias in aliases:
        if re.search(rf"\b{re.escape(alias)}\b", title_norm):
            return "hit"

    any_source_found = False
    any_token_extracted = bool(aliases)

    for lang in NAMES_BY_LANG:
        # Numista title court (canon i18n)
        numista_title = load_i18n_title(conn, eurio_id, lang)
        if numista_title is not None:
            any_source_found = True
            tokens = extract_tokens(numista_title, lang)
            if tokens:
                any_token_extracted = True
            for tok in tokens:
                if tok in title_norm:
                    return "hit"

        # commemorated_topic verbeux (Numista + BCE poolés par lang)
        topic = load_topic(conn, eurio_id, lang)
        if topic is not None:
            any_source_found = True
            tokens = extract_tokens(topic, lang)
            if tokens:
                any_token_extracted = True
            for tok in tokens:
                if tok in title_norm:
                    return "hit"

    if not any_source_found or not any_token_extracted:
        return "undiscriminable"
    return "miss"


def title_matches_theme(
    title: str,
    eurio_id: str,
    *,
    conn: sqlite3.Connection,
) -> bool:
    """Vrai si le titre seller n'est PAS un non-match franc de l'eurio_id.

    Sémantique permissive : ``True`` sur ``"hit"`` et ``"undiscriminable"``
    (on ne filtre pas tant qu'on ne peut pas trancher), ``False`` seulement
    sur un vrai ``"miss"``.
    """
    return theme_match_state(title, eurio_id, conn=conn) != "miss"


@dataclass(frozen=True)
class GroupMatch:
    """Attribution d'un listing aux commémos d'un groupe de découverte.

    - ``matched`` : eurio_ids retenus (ordre catalogue).
    - ``verdict`` :
        - ``"single"``  : 1 pièce — attribution nette.
        - ``"lot"``     : ≥2 pièces touchées — listing multi-pièces.
        - ``"ambiguous"``: aucun hit franc — le theme-match ne tranche pas
          (titre court indiscriminable OU thème non reconnu, ex. vocab de
          marché absent de l'i18n). ``matched`` est vide : pas de cible
          auto, le listing part en review. **Jamais jeté** (chunk C1) :
          le listing a déjà passé ``accept_listing`` (millésime/prix/
          devise OK) → il est cohérent avec le groupe.
        - ``"no_match"``: **contradiction franche** — le titre contredit
          un axe dur du groupe (pays / année / dénomination). Discard
          légitime : c'est une contradiction *positive*, pas une absence
          d'évidence (cf. garde-fou de contradiction, ``compare_to_group``).
          ``contradictions`` porte le(s) axe(s) fautif(s).

    - ``contradictions`` : axes en contradiction franche quand
      ``verdict == "no_match"`` ; vide sinon.
    """

    matched: tuple[str, ...]
    verdict: str
    contradictions: tuple[str, ...] = ()

    @property
    def target_eurio_id(self) -> str | None:
        """Pièce à pré-attribuer au listing (1ʳᵉ du set ; None si ambigu)."""
        return self.matched[0] if self.matched else None


def _group_contradiction(
    title: str,
    group_eurio_id: str,
    *,
    conn: sqlite3.Connection,
) -> tuple[str, ...]:
    """Axes durs (pays/année/dénom) où le titre seller contredit le groupe.

    Charge l'identité du groupe depuis ``coins`` — les sœurs la partagent,
    donc n'importe quel eurio_id du groupe suffit — extrait les signaux du
    titre et délègue à ``compare_to_group`` (source de vérité des axes,
    partagée avec le step pipeline ``text_signal``). Tuple vide si
    l'identité du groupe est introuvable (défensif).
    """
    from sources.text_signals import (
        GroupIdentity,
        compare_to_group,
        extract_listing_text_signals,
    )

    row = conn.execute(
        "SELECT country, year, face_value FROM coins WHERE eurio_id=?",
        (group_eurio_id,),
    ).fetchone()
    if row is None:
        return ()
    group = GroupIdentity(
        country=(row["country"] or "").lower(),
        year=int(row["year"]),
        face_value=float(row["face_value"]),
    )
    return compare_to_group(extract_listing_text_signals(title), group)


def match_listing_to_group(
    title: str,
    group_eurio_ids: list[str],
    *,
    conn: sqlite3.Connection,
) -> GroupMatch:
    """Route un listing eBay vers une (ou des) commémo(s) de son groupe.

    Un groupe de 1 seule pièce est trivial : la recherche eBay scope déjà
    le pays/année, donc tout listing retenu EST cette pièce — pas de
    discrimination de thème nécessaire.

    Chunk C1 — verdict ∈ {single, lot, ambiguous} quand le thème ne
    tranche pas : « évidence absente ≠ contradiction », le listing a
    passé ``accept_listing``, on ne le jette pas.

    Garde-fou de contradiction — AVANT le theme-match, on confronte le
    titre aux axes durs du groupe (pays / année / dénomination) via
    ``compare_to_group``. Une contradiction franche (« 2,5 Euro »,
    « Eslovenia ») → ``no_match`` (discard) : c'est une contradiction
    *positive*, pas une absence d'évidence. Tourne aussi sur les groupes
    mono-pièce (le junk hors-scope y arrive aussi).
    """
    ids = list(group_eurio_ids)
    if not ids:
        return GroupMatch((), "ambiguous")

    contradictions = _group_contradiction(title, ids[0], conn=conn)
    if contradictions:
        return GroupMatch((), "no_match", contradictions=contradictions)

    if len(ids) == 1:
        return GroupMatch((ids[0],), "single")

    hits = [
        eid for eid in ids
        if theme_match_state(title, eid, conn=conn) == "hit"
    ]
    if len(hits) == 1:
        return GroupMatch((hits[0],), "single")
    if len(hits) >= 2:
        return GroupMatch(tuple(hits), "lot")
    return GroupMatch((), "ambiguous")
