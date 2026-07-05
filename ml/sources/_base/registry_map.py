"""Mapping pipeline source IDs → registry source IDs.

Doctrine cf. docs/coin-richness/ROADMAP-DB.md §3.4 :

- **Tables d'infra** (`source_runs`, `source_images`, `image_assets`,
  `discovery_*`, `pending_quotes`) gardent une colonne `source TEXT` libre.
  Leur source est le **pipeline d'enrichissement** (ex: 'ebay', 'bce') ;
  l'adapter Python expose son `source_id` qui s'écrit tel quel.

- **Tables data-aware** (`coin_observations`, `coin_market_quotes`,
  `referential_catalog`, `coin_canonical_images`) ont une FK `source →
  source_registry(id) ON DELETE RESTRICT`. Toute écriture utilise un id du
  registry (`ebay_browse`, `bce_official`, `numista_api`, ...).

Cette indirection permet aux requêtes existantes filtrant
`WHERE source='ebay'` sur les infra tables de continuer à fonctionner
post-doctrine — seul le moment de l'écriture dans une table data-aware
traduit via `to_registry_source()`.

La FK est enforced **dès aujourd'hui** (`StoreBase` active `PRAGMA
foreign_keys=ON`) et `source_registry` est seedé au bootstrap du Store
(`store/source_registry_seed.py`, appelé par `connection._bootstrap`). Tout
producer doit donc écrire le vocabulaire registry (`to_registry_source()`),
sinon l'INSERT lève une FK violation immédiate.
"""

from __future__ import annotations


# Pipeline source_id (clé dans source_runs.source, source_images.source, ...)
# → registry id (source_registry.id, utilisé en data-aware writes).
#
# Quand on ajoute une nouvelle source pipeline : ajouter ici ET dans
# `ml/store/source_registry_seed.py` (SEED). Sinon `to_registry_source()`
# lèvera une KeyError ou l'INSERT lèvera une FK violation immédiate.
PIPELINE_TO_REGISTRY: dict[str, str] = {
    # Adapters actifs
    "ebay":     "ebay_browse",
    "bce":      "bce_official",
    "jo":       "eurlex_jo",
    # Mock adapter (sources/mock — utilisé en tests). Mappé vers 'manual'
    # plutôt que d'ajouter une row 'mock' au registry réel.
    "mock":     "manual",
    # Scripts producers
    "numista":  "numista_api",
    # Sources historiques observées en `coin_observations.source` (avant wipe).
    # Conservés pour compat des consumers qui traversent l'ancienne donnée
    # — disparaîtront au wipe P.6.
    "ebay_market":     "ebay_browse",
    "mdp_issue":       "mdp",
    "mdp_skus":        "mdp",
    "mdp_urls":        "mdp",
    "lmdlp_variants":  "lmdlp",
    "lmdlp_mintage":   "lmdlp",
    "lmdlp_skus":      "lmdlp",
    "lmdlp_url":       "lmdlp",
    "wikipedia":       "wikipedia",
    "wikipedia_url":   "wikipedia",
    "bce_comm_url":    "bce_official",
    # Identité (un id registry → lui-même pour les callers déjà alignés)
    "ebay_browse":     "ebay_browse",
    "bce_official":    "bce_official",
    "numista_api":     "numista_api",
    "mdp":             "mdp",
    "lmdlp":           "lmdlp",
    "2euros_org":      "2euros_org",
    "eurio_derived":   "eurio_derived",
    "manual":          "manual",
    "bundesbank":      "bundesbank",
    "eurlex_jo":       "eurlex_jo",
}


def to_registry_source(pipeline_id: str) -> str:
    """Translate a pipeline source id to a registry id.

    Raises:
        ValueError: if `pipeline_id` has no registry mapping. Fail loud
            rather than silently writing an FK-incompatible value.
    """
    try:
        return PIPELINE_TO_REGISTRY[pipeline_id]
    except KeyError as e:
        raise ValueError(
            f"Pipeline source '{pipeline_id}' has no registry mapping. "
            f"Add it to ml/sources/_base/registry_map.py PIPELINE_TO_REGISTRY "
            f"AND seed it in ml/scripts/seed_source_registry.py."
        ) from e
