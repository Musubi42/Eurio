"""Shim de compatibilité — l'implémentation vit désormais dans ``ml/store/``.

Le split (refacto ML chunk 5) a déplacé Store + ses rows + helpers vers le
package plat ``store/``. Ce module ré-exporte tout pour garder
``from state.store import …`` vert jusqu'à la migration des imports (chunk 7).
Le nouveau code importe directement ``from store import …``.
"""

from __future__ import annotations

from store import *  # noqa: F401,F403  (ré-export de l'API publique)

# Noms à underscore : non couverts par ``import *``, mais importés ailleurs
# (ex. enqueue_orphan_crops, recrop_cohort_census) → ré-export explicite.
from store import (  # noqa: F401
    StoreBase,
    _SCHEMA_PATH,
    _register_phash_udfs,
)
