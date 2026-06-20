"""Domain `sources` — pattern layered (cf. ARCHITECTURE.md §2).

Phase 2b data-layer-unification : porte les endpoints READ depuis
`serving/sources_routes.py` (fat-controller legacy, dépendant des modules
ML lourds `sources._base.*`) vers un module mince qui ne dépend que de
sqlite3 stdlib — montable sur l'image lean du VPS.
"""
from .router import router

__all__ = ["router"]
