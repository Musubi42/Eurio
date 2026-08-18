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

# ── LES TROIS SEUILS D'ENTRAÎNEMENT ────────────────────────────────────────
# Ce ne sont plus « les » seuils mais leurs DÉFAUTS : la valeur qui s'applique
# est résolue en base (``store/thresholds.py`` : classe → cohorte → global →
# ces constantes). Elles restent le filet — l'image lean et le préflight doivent
# démarrer sur une base qui n'a pas encore reçu la migration 0006.
#
# Trois notions distinctes, jamais fusionnées (cf.
# docs/work-in-progress/refacto-page-cohorte/DECISIONS.md §D5) :

# Plancher de sources eBay RÉELLES en-dessous duquel une classe est flaggée
# pauvre (badge « underfed » / P4). Source unique avec le bake
# (training/iteration_augmentations.py, via training/foundation/enrichment.py).
# CHOIX PRODUIT : c'est celui qu'on fait bouger à la lumière des benchmarks.
MIN_REAL = 10

# Cible d'images APRÈS augmentation. Le facteur est dérivé : ceil(cible / seed).
# PARAMÈTRE DE BAKE. Vivait dans training/foundation/enrichment.py ; relocalisé
# ici pour la même raison que MIN_REAL (stdlib-only, lisible sur l'image lean),
# et ré-exporté là-bas pour ne casser aucun usage.
TRAINING_TARGET = 100

# Plancher MÉCANIQUE dur : sous ce nombre de sources réelles, MPerClassSampler
# rééchantillonne avec remise et la classe s'entraîne sur des doublons — le run
# est refusé. SEUIL TECHNIQUE, imposé par la composition d'un batch : il ne se
# règle pas « au feeling », il suit m_per_class du run.
M_PER_CLASS = 4

# Réfs canoniques officielles utilisables comme sources de training (avers).
# numista_api est exclu : pas de local_path (l'avers Numista est lu sur le FS,
# cf. `_has_obverse` — dérivé FILESYSTEM, hors état-DB-portable, posé en
# overlay LOCAL par C3, JAMAIS exposé par store/funnel.py).
CANONICAL_REF_SOURCES = ("bce_official", "eurlex_jo")
