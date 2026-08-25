"""Garde-fou C7 (migration Direction A) pour les migrations one-shot.

Sous Direction A (docs/work-in-progress/local-sync/migration-direction-a.md),
``eurio.db`` canonique n'existe qu'au VPS. Les scripts ``backfill_face.py`` et
``backfill_denom.py`` mutent des colonnes canoniques (``face``/``denom``) via
des ``UPDATE`` bruts, non transportés par aucune route ``/ingest`` (contrairement
aux writers §C4). Les lancer contre une réplique locale (Mac/PC) écrirait une
divergence invisible et jamais synchronisée.

⚠️ **Ce garde est conditionnel à l'absence de route, et pas à autre chose.**
``backfill_quality_score.py`` en est sorti le 2026-08-25 : sa colonne a
désormais un transport (``POST /ingest/quality-scores``), donc le garde n'y
protégeait plus de rien — et un garde qui protège d'un danger disparu est un
garde décoratif, qu'on finit par contourner par réflexe. Le jour où ``face`` et
``denom`` auront leur route, ce module doit disparaître, pas se durcir.

Signal de détection (réutilise l'infra existante, pas de heuristique fragile
sur le chemin du fichier) :
  - ``EURIO_DB_READONLY`` vrai (C5 : cette machine est une réplique read-only) ;
  - OU ``client.http.sync_enabled()`` vrai (``EURIO_API_URL`` configuré : cette
    machine est un CLIENT Direction A qui forward vers un VPS canonique — donc
    PAS elle-même le canonique).

Sur le VPS lui-même (aucun ``EURIO_API_URL`` local, aucun ``EURIO_DB_READONLY``)
le script tourne normalement. Sur un poste GPU (Mac/PC) qui doit exécuter ces
backfills torch/DINO, l'opérateur doit explicitement passer
``--i-know-this-is-canonical`` (ex. il pointe ``--db`` vers une copie VPS
synchronisée puis pousse le résultat — procédure documentée dans
``docs/work-in-progress/local-sync/vps-only-migrations.md``).
"""

from __future__ import annotations

import sys


def is_vps_only_blocked() -> bool:
    """Vrai si ce process tourne sur une machine cliente Direction A."""
    from store import resolve_db_readonly  # noqa: PLC0415 — évite import cycle au chargement

    if resolve_db_readonly():
        return True
    try:
        from client.http import sync_enabled  # noqa: PLC0415
    except ImportError:
        return False
    return sync_enabled()


def guard_vps_only(script_name: str, *, allow: bool) -> None:
    """Refuse (``sys.exit`` non-zéro) si machine cliente Direction A et pas
    ``--i-know-this-is-canonical``. No-op sinon (VPS, ou dev Model A pur sans
    EURIO_API_URL/EURIO_DB_READONLY)."""
    if allow:
        return
    if not is_vps_only_blocked():
        return
    print(
        f"MIGRATION VPS-ONLY sous Direction A — {script_name} écrit le canonique "
        "(UPDATE image_assets non transporté par /ingest). Cette machine est une "
        "réplique/cliente (EURIO_DB_READONLY ou EURIO_API_URL configuré) : refuse "
        "de tourner. Relancer sur le VPS, ou passer --i-know-this-is-canonical si "
        "--db pointe explicitement une copie canonique. "
        "Voir docs/work-in-progress/local-sync/vps-only-migrations.md.",
        file=sys.stderr,
    )
    sys.exit(1)
