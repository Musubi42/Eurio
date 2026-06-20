"""Domain `review_queue` — pattern layered (cf. ARCHITECTURE.md §2).

Phase 2c data-layer-unification : porte les endpoints READ depuis
`review/review_queue_routes.py` (fat-controller legacy, dépendant de
cv2 + sources._base + training.foundation au top-level) vers un module
mince qui ne dépend que de sqlite3 stdlib — montable sur l'image lean.

Ne confond pas avec :
- ``/review/*`` (C4 audit/validation, déjà présent — `review_routes.py`)
- ``/peer_arbitration/*`` (C4 aussi, séparé)
"""
from .router import router

__all__ = ["router"]
