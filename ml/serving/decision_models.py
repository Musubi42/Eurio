"""Modèles de contrat (requête/réponse) des décisions de review — SQL-free,
cv2-free, pydantic pur. Source UNIQUE du contrat wire, partagée par :

- les routes lourdes locales (`serving/lab_routes.py`, `review/review_queue_routes.py`),
- l'image lean canonique du VPS (`serving/funnel_writes.py`).

Un seul owner du contrat = pas de dérive local ↔ VPS (le front envoie/reçoit la
même forme quelle que soit la cible). Cf. migration-direction-a.md (C2a).
"""
from __future__ import annotations

from pydantic import BaseModel


# ── Funnel « Jeu d'entraînement » ────────────────────────────────────────────
class SetTrainingEligiblePayload(BaseModel):
    eligible: bool


class ReassignAssetPayload(BaseModel):
    eurio_id: str


class AcceptTrainingResult(BaseModel):
    asset_id: str
    eurio_id: str | None
    resolution_status: str
    training_eligible: bool


class ReopenReviewResult(BaseModel):
    asset_id: str
    eurio_id: str | None
    review_id: str


# ── Décision de lot ──────────────────────────────────────────────────────────
class LotAssignment(BaseModel):
    asset_id: str
    eurio_id: str | None = None
    face: str | None = None
    variant_kind: str | None = None
    reject_reason: str | None = None
    skip: bool = False


class LotDecidePayload(BaseModel):
    assignments: list[LotAssignment]


class LotDecideResponse(BaseModel):
    done: int
    rejected: int
    skipped: int
    errors: list[str]
