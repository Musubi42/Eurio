"""Connexion du rail `jobs/` — la DB LOCALE inscriptible, jamais le canonique.

Un job est du **bookkeeping de machine** : un PID, un chemin de log, un
compteur d'avancement. Rien de tout cela n'a de sens sur une autre machine, et
rien ne doit voyager au canonique. La table `jobs` est d'ailleurs
domaine-agnostique — aucune FK, aucun JOIN avec une table canonique.

Elle vivait pourtant dans le SQLite canonique. Sous le flip Direction A / C5
(``EURIO_DB_READONLY=1``, le local devient une réplique read-only), ouvrir un
job levait donc ``attempt to write a readonly database`` : le bake du lab
répondait 503 et l'UI restait figée à ``0/600`` sans jamais dire pourquoi.

`local_state_store()` est la place prévue — elle porte déjà `cohort_jobs`,
`cohort_training_scans` et `cohort_training_scan_results`, avec la même
sémantique « observabilité locale », et reste writable sous le flip.

Passer par cette fonction plutôt que par ``store._connection()`` garantit que
le parent (l'API) et l'enfant (le subprocess détaché) écrivent bien dans le
MÊME fichier — sans quoi la progression du bake n'atteindrait jamais l'écran.
"""

from __future__ import annotations

import sqlite3


def connection() -> sqlite3.Connection:
    """Connexion à la DB de bookkeeping des jobs (locale, inscriptible)."""
    from store import local_state_store  # noqa: PLC0415 — évite un cycle d'import

    return local_state_store()._connection()  # noqa: SLF001
