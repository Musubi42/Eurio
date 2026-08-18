"""Modèles de contrat — lecture funnel « Jeu d'entraînement », état-DB-portable.

Source UNIQUE du contrat wire pour ``GET /lab/cohorts/{id}/training-crops``
servi sur l'image lean canonique du VPS (``serving/lab_read_routes.py``), miroir
lecture de ``serving/decision_models.py`` (C2a, les écritures).

⚠️ Volontairement LEAN : ni ``has_numista_ref``/``n_bce_ref`` (dérivé FS), ni
``r_at_1``/``confused_with``/``intruder_*`` (dérivé GPU). Ces champs vivent
dans l'overlay LOCAL (``serving/lab_routes._cohort_training_overlay``, full
server only) et se mergent côté front par ``asset_id``/``class_id``. Cf.
migration-direction-a.md (C3).
"""
from __future__ import annotations

from pydantic import BaseModel


class TrainingCropState(BaseModel):
    asset_id: str
    source: str
    file_url: str
    eurio_id: str | None = None
    face: str | None = None
    denom: str | None = None
    quality_score: float | None = None
    training_eligible: bool
    resolution_status: str
    routed: bool = False


class TrainingCropClassState(BaseModel):
    class_id: str
    class_kind: str
    member_eurio_ids: list[str]
    # « part au train » = training_eligible=1 ET face != 'reverse' (compté à
    # l'identique du bake, cf. lab_routes.TrainingCropClass).
    n_eligible: int
    n_unknown_face: int
    n_reverse_flagged: int
    n_rejected: int
    n_review_unrouted: int = 0
    n_obverse: int = 0
    underfed: bool = False
    crops: list[TrainingCropState]


class CohortTrainingCropsStateResponse(BaseModel):
    cohort_id: str
    cohort_name: str
    min_real: int
    # Les trois seuils résolus + la provenance de chacun ('code'/'global'/
    # 'cohort'/'class'). Le front n'en définit aucun : il lit celui-ci.
    thresholds: dict | None = None
    classes: list[TrainingCropClassState]
