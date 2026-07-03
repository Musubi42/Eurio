"""Constantes du funnel « Jeu d'entraînement » — source unique, stdlib-only.

Relocalisées ici (C3, Direction A) pour que ``store/funnel.py`` (lecture
autoritative servie sur l'image lean du VPS) puisse les importer SANS tirer
numpy/torch :

- ``TRIAGE_STATUSES`` vivait dans ``training/training_set_scan.py``, qui fait
  ``import numpy`` en tête de module.
- ``MIN_REAL``/``CANONICAL_REF_SOURCES`` vivaient dans
  ``training/foundation/enrichment.py`` ; importer ce module tire aussi
  ``training.foundation.__init__`` → anchors/encoder/matcher (numpy ET torch).

Ce module ne dépend QUE du stdlib. Les deux modules d'origine ré-exportent
désormais ces noms (``from store.funnel_constants import ...``) pour préserver
tous les usages full-server existants sans duplication ni drift.

Cf. docs/work-in-progress/local-sync/migration-direction-a.md (C3).
"""
from __future__ import annotations

# Statuts de crops exposés au triage du Jeu d'entraînement : le pool résolu
# (candidats train) + les rejetés (pour pouvoir restaurer). Même périmètre que
# le scan Dino local (training/training_set_scan.py réexporte ce nom).
TRIAGE_STATUSES = ("auto_name", "auto_phash", "manual", "needs_review", "rejected")

# Plancher de sources eBay RÉELLES en-dessous duquel une classe est flaggée
# pauvre (badge « underfed » / P4). Source unique avec le bake
# (training/iteration_augmentations.py, via training/foundation/enrichment.py).
MIN_REAL = 10

# Réfs canoniques officielles utilisables comme sources de training (avers).
# numista_api est exclu : pas de local_path (l'avers Numista est lu sur le FS,
# cf. `_has_obverse` — dérivé FILESYSTEM, hors état-DB-portable, posé en
# overlay LOCAL par C3, JAMAIS exposé par store/funnel.py).
CANONICAL_REF_SOURCES = ("bce_official", "eurlex_jo")
