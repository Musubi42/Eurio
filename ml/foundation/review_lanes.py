"""Routage des items de review vers une LANE persistée — source de vérité UNIQUE.

Avant (WS1) : les 3 « queues » manuel / auto-accept / ccproxy n'existaient pas en
base. C'était une heuristique Dino recalculée à chaque affichage (triage-stats),
et l'écran de review ne filtrait sur rien → le compteur d'une lane ne bougeait
jamais. Désormais la lane est figée en base (``review_queue.lane``) par CE module,
et chaque compteur / écran filtre dessus.

Règle de routage (à partir du verdict d'auto-validation Dino, cf.
``foundation/auto_validate.py``) — UN SEUL endroit, documenté :

    ┌────────────────┬───────────────┬─────────────────────────────────────────┐
    │ verdict Dino   │ lane          │ pourquoi                                  │
    ├────────────────┼───────────────┼─────────────────────────────────────────┤
    │ auto_candidate │ auto_accept   │ machine confiante → review humaine rapide │
    │                │               │ (tout présélectionné, on décoche)         │
    │ partial        │ ccproxy       │ Dino penche bon mais pas assez sûr →      │
    │                │               │ arbitrage Claude vision en masse          │
    │ divergent      │ ccproxy       │ Dino contredit la cible → idem (signal à  │
    │                │               │ arbitrer)                                 │
    │ unknown        │ manual        │ Dino aveugle (pas de prédiction / pas de  │
    │                │               │ cible) → seul un humain peut décider      │
    └────────────────┴───────────────┴─────────────────────────────────────────┘

Override humain (``review_queue.lane_source='human'``) : un déplacement manuel
vers ``manual`` est STICKY — aucun recalcul Dino ne le ré-route (cf. la garde
``AND lane_source='auto'`` dans l'enqueue / le re-route post-Dino).

Future session : pour retravailler le tri, ne toucher QUE ``VERDICT_TO_LANE`` ici.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from foundation.auto_validate import (
    AutoValidateVerdict,
    compute_auto_validate_verdict,
)

Lane = Literal["manual", "auto_accept", "ccproxy"]

# Les 3 lanes valides (CHECK miroir du schéma review_queue.lane).
LANES: tuple[Lane, ...] = ("manual", "auto_accept", "ccproxy")

# Lane par défaut des items legacy (lane NULL avant backfill) et fallback de tout
# verdict inconnu : l'humain est le filet de sécurité.
DEFAULT_LANE: Lane = "manual"

# Règle de routage verdict → lane. SOURCE DE VÉRITÉ UNIQUE.
VERDICT_TO_LANE: dict[str, Lane] = {
    "auto_candidate": "auto_accept",
    "partial": "ccproxy",
    "divergent": "ccproxy",
    "unknown": "manual",
}


def verdict_to_lane(level: str | None) -> Lane:
    """Mappe un niveau de verdict d'auto-validation vers sa lane (fallback manual)."""
    return VERDICT_TO_LANE.get(level or "", DEFAULT_LANE)


def compute_lane(
    conn: sqlite3.Connection,
    image_asset_id: str,
    *,
    encoder_version: str = "dinov2-vits14",
    anchors_kind: str = "2eur_commemo",
) -> tuple[AutoValidateVerdict, Lane]:
    """``(verdict, lane)`` pour un image_asset — réutilise le verdict Dino
    existant (pas de duplication de la logique de seuils). Utilisé par l'enqueue,
    le re-route post-Dino et le backfill."""
    verdict = compute_auto_validate_verdict(
        conn, image_asset_id,
        encoder_version=encoder_version, anchors_kind=anchors_kind,
    )
    return verdict, verdict_to_lane(verdict.level)
