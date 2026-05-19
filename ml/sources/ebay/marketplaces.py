"""Routage pays → marketplaces eBay pour le discover multi-mkt.

Source de vérité du mapping ISO2 → (primary marketplace, langue de query,
catch-all global = EBAY_GB). Le routage est explicite — chaque pays
eurozone (et `'eu'` joint-issues) a son entrée dictée par
``docs/sources-refacto/ebay-multi-marketplace/marketplace-map.md``.

Pourquoi un dict statique en code et pas une vue SQL : c'est de la
config produit qui doit être grep-able et reviewable en PR, pas un état
de DB qui mute. Toute évolution passe par une PR + un probe (cf.
``language-probe.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

EBAY_GB = "EBAY_GB"


@dataclass(frozen=True)
class MarketplaceRoute:
    """Marketplaces eBay à interroger pour un pays donné.

    Sémantique :

    - ``primary`` : marketplace natif si applicable, sinon fallback langue.
      ``None`` quand le pays n'a ni marketplace natif ni langue couverte
      (GB seul suffit alors).
    - ``global_`` : EBAY_GB, toujours présent (P1 — catch-all V1).
    - ``query_lang`` : langue dans laquelle on construit la query pour
      ``primary`` (cf. P3). Pour ``global_``, la query est toujours en EN.

    Quand ``primary is None``, un seul call discovery est effectué (GB).
    Sinon 2 calls (primary + GB), avec merge en mémoire (cf. schema.md
    §"Stratégie d'écriture").
    """

    primary: str | None
    global_: str = EBAY_GB
    query_lang: str = "en"  # langue de la query primary; "en" si GB-only


# Routage canonique. Ordre des entries = ordre alphabétique pour faciliter
# le grep et la review. Chaque entrée est justifiée dans marketplace-map.md.
#
# ⚠️ PT→ES est marqué provisoire (D-MM2) : à confirmer/retirer en V1 probe.
_ROUTES: dict[str, MarketplaceRoute] = {
    # Pays avec marketplace eBay natif
    "AT": MarketplaceRoute(primary="EBAY_AT", query_lang="de"),
    "BE": MarketplaceRoute(primary="EBAY_BE", query_lang="fr"),  # bilingue, FR V1
    "DE": MarketplaceRoute(primary="EBAY_DE", query_lang="de"),
    "ES": MarketplaceRoute(primary="EBAY_ES", query_lang="es"),
    "FR": MarketplaceRoute(primary="EBAY_FR", query_lang="fr"),
    "IE": MarketplaceRoute(primary="EBAY_IE", query_lang="en"),
    "IT": MarketplaceRoute(primary="EBAY_IT", query_lang="it"),
    "NL": MarketplaceRoute(primary="EBAY_NL", query_lang="nl"),

    # Fallback par langue principale (pas de marketplace natif)
    "AD": MarketplaceRoute(primary="EBAY_ES", query_lang="es"),
    "LU": MarketplaceRoute(primary="EBAY_FR", query_lang="fr"),
    "MC": MarketplaceRoute(primary="EBAY_FR", query_lang="fr"),
    # TODO(V1-probe): confirmer PT→ES vs GB-only. Si recall ES < ×2 GB,
    # basculer en MarketplaceRoute(primary=None). Cf. marketplace-map.md
    # §"Routage PT provisoire".
    "PT": MarketplaceRoute(primary="EBAY_ES", query_lang="es"),
    "SM": MarketplaceRoute(primary="EBAY_IT", query_lang="it"),
    "VA": MarketplaceRoute(primary="EBAY_IT", query_lang="it"),

    # GB-only (pas de marketplace natif, langue non couverte par les mkts EU)
    "BG": MarketplaceRoute(primary=None),
    "CY": MarketplaceRoute(primary=None),
    "EE": MarketplaceRoute(primary=None),
    "FI": MarketplaceRoute(primary=None),
    "GR": MarketplaceRoute(primary=None),
    "HR": MarketplaceRoute(primary=None),
    "LT": MarketplaceRoute(primary=None),
    "LV": MarketplaceRoute(primary=None),
    "MT": MarketplaceRoute(primary=None),  # en couvert par EBAY_GB
    "SI": MarketplaceRoute(primary=None),
    "SK": MarketplaceRoute(primary=None),

    # Joint issues (commémos communes émises par les 21 pays eurozone) —
    # GB catch-all suffit, tirer sur 21 mkts n'est pas tenable côté quota.
    "eu": MarketplaceRoute(primary=None),
}


class UnknownCountry(KeyError):
    """Pays absent du routage canonique."""


def route_for(country: str) -> MarketplaceRoute:
    """Renvoie la route pour le pays ISO2 (ou ``'eu'`` joint).

    Lève ``UnknownCountry`` plutôt que de retourner un fallback GB-only
    silencieux — un pays inconnu signale un bug en amont (référentiel,
    bootstrap), pas un cas à masquer.
    """
    try:
        return _ROUTES[country]
    except KeyError as exc:
        raise UnknownCountry(
            f"No marketplace route for country={country!r}. "
            "Add it to ml/sources/ebay/marketplaces.py after a probe."
        ) from exc


def all_routes() -> dict[str, MarketplaceRoute]:
    """Renvoie une copie du dict pour exposition front (cf. B5 API).

    Copie pour éviter qu'un caller mute le routage canonique.
    """
    return dict(_ROUTES)
