"""Source LMDLP — La Monnaie de la Pièce (lamonnaiedelapiece.com).

Boutique communautaire FR ; on en tire un **prix boutique par qualité** pour
les 2 € commémoratives, via l'API WooCommerce Store (JSON). Scope strict :
prix + qualité → ``coin_market_quotes`` (1 row/qualité) + ``coin_source_refs``
(identité). Pas d'image, pas de tirage, pas d'observation (cf.
docs/sources-lmdlp/data-schema.md).
"""

from sources.lmdlp.adapter import LmdlpAdapter, LmdlpProduct

__all__ = ["LmdlpAdapter", "LmdlpProduct"]
