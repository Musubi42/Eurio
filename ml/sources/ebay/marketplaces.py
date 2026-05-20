"""Marketplaces eBay interrogés en discovery.

**Décision actée 2026-05-21** (benchmark routing itération 3, cf.
``docs/sources-refacto/ebay-multi-marketplace/research/marketplace-routing-benchmark.md``) :
le discovery interroge ``{EBAY_DE, EBAY_ES}`` pour **toutes** les
origines — plus de routage per-pays.

Pourquoi un routage uniforme et non une table per-origine :

- Le marketplace est un **canal de découverte**, pas un segment de prix
  ni d'images : les rows sont dédupliquées par ``item_id`` en aval.
- Le benchmark (24 origines × 9 marketplaces × 112 coins, theme-match)
  a montré que ``{DE, ES}`` est le **top-2 de recall sur ~22/24
  origines**. Une table per-origine hand-maintenue n'apporterait qu'un
  gain marginal sur 2 niches bruitées (MC, PT), au prix d'une
  maintenance et d'un risque de drift.
- ``EBAY_GB`` est **retiré** : 0 listing EUR exploitable (annonces
  eBay.co.uk en GBP, rejetées par le filtre ``non_eur``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketplaceCall:
    """Un appel discovery : un marketplace eBay + la langue de sa query.

    Chaque marketplace est interrogé dans **sa langue native** — la
    configuration sous laquelle ``{DE, ES}`` a gagné le benchmark. Les
    vendeurs titrent dans la langue de leur marketplace.

    À ne pas confondre avec ``MARKETPLACE_ACTIVE_LANGS`` : ``query_lang``
    construit la requête envoyée à eBay, ``MARKETPLACE_ACTIVE_LANGS``
    couvre les langues contre lesquelles ``title_matches_theme`` matche
    les titres seller retournés. Deux réglages séparés.
    """

    marketplace: str
    query_lang: str


# Routage discovery — uniforme, toutes origines confondues.
# Ordre : EBAY_DE d'abord (meilleur recall sur 13/24 origines au
# benchmark → c'est ce premier marketplace qui sert le fetch HD image
# first-seen), EBAY_ES ensuite.
DISCOVERY_MARKETPLACES: tuple[MarketplaceCall, ...] = (
    MarketplaceCall("EBAY_DE", "de"),
    MarketplaceCall("EBAY_ES", "es"),
)


# Langues servies par chaque marketplace, pour matcher des titres
# sellers multi-langues (cf. I2 — ``theme_tokens.py`` + ``title_matches_theme``).
# Distinct de ``query_lang`` (qui construit la query côté discovery) :
# - ``query_lang`` choisit la langue de la requête envoyée à eBay
# - ``MARKETPLACE_ACTIVE_LANGS`` couvre les langues qu'on peut voir
#   apparaître dans les titres de listings retournés par ce marketplace
#
# Ordre des langues = priorité du matcher (langue native d'abord, EN
# en fallback). Le matcher s'arrête au premier hit, donc l'ordre influence
# le coût SQLite mais pas la sémantique.
#
# Seuls EBAY_DE et EBAY_ES sont interrogés en discovery (cf.
# DISCOVERY_MARKETPLACES) ; les autres entrées restent comme référence
# de calibration (probe V1 2026-05-20, scripts/probe_marketplace_languages.py)
# au cas où le routage évoluerait.
# - EBAY_ES : +it (vendeurs italiens cross-listent, ~19 % des titres)
# - EBAY_IE : +it (~16 %)
# - EBAY_NL : +fr (DOMINANT à ~44 %, eBay.nl est Benelux) +it (~14 %)
# `en` conservé partout même quand mesuré < 10 % : sous-détecté par le
# classifieur et coût quasi nul (titre i18n EN canon toujours présent).
MARKETPLACE_ACTIVE_LANGS: dict[str, list[str]] = {
    "EBAY_AT": ["de", "en"],
    "EBAY_BE": ["fr", "nl", "en"],
    "EBAY_DE": ["de", "en"],
    "EBAY_ES": ["es", "en", "it"],
    "EBAY_FR": ["fr", "en"],
    "EBAY_GB": ["en", "fr", "de", "it", "es", "nl"],
    "EBAY_IE": ["en", "it"],
    "EBAY_IT": ["it", "en"],
    "EBAY_NL": ["nl", "fr", "en", "it"],
}


def discovery_marketplaces() -> tuple[MarketplaceCall, ...]:
    """Renvoie les marketplaces à interroger en discovery (DE puis ES).

    Routage uniforme : la même paire pour toutes les origines. Le pays
    du coin n'entre plus dans la décision (cf. docstring du module).
    """
    return DISCOVERY_MARKETPLACES
