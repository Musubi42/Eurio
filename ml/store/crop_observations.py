"""Observation de recadrage manuel — write-half SQL-pure (Direction A).

Ce module transforme un geste de review en MESURE. Le delta entre le crop
proposé et le crop final est l'étiquette ; on ne demande à l'humain de
qualifier rien. Contexte complet : `serving/migrations/0018_…sql` et
[ADR-017](docs/adr/017-le-crop-d-enrichissement-est-decouple-du-scan.md).

⚠️ **STDLIB + `store.*` UNIQUEMENT.** Ni `cv2`, ni `torch`, ni `training`, et
surtout **pas `review.review_lanes`** — ce dernier a l'air inoffensif et tire
`training.foundation.auto_validate` en TRANSITIF. C'est le défaut qui a tué
`backfill_denom --reject` en prod le 2026-08-27 : le module échouait à l'import
dans l'image lean, avant d'avoir rien tenté. Un contrôle statique des imports
DIRECTS ne le voit pas ; `tests/test_crop_observations.py` fait l'import réel
avec `training` bloqué, en sous-process.

Contrat transactionnel identique à `store/crops.py` : prend `conn`, ne fait NI
`BEGIN` NI `COMMIT` (le caller possède la transaction). `asset_id` inconnu →
`missing`, jamais de 404 global.
"""
from __future__ import annotations

import math

#: Seuils d'étiquetage, calibrés sur les 2 181 paires reconstituables
#: (`scripts/backfill_crop_observations.py`, mesuré le 2026-08-27) :
#: `d_r_ratio` médiane 0,976 · p10 0,808 · p90 1,123 ;
#: `d_center_norm` médiane 0,067 · p90 0,277.
#:
#: 10 % de rayon est au-dessus du bruit de la main ET sous les p10/p90 : le
#: seuil sépare donc deux populations au lieu de couper au milieu d'une.
_R_GROW = 1.10
_R_SHRINK = 0.90
#: 0,15·r : au-delà du p50 (0,067), en deçà du p90 (0,277).
_CENTER_MOVE = 0.15
#: 0,70·r — le MÊME seuil que `_plausible_suggestion` (`serving/crop_edit.py`)
#: utilise pour dire « ce n'est plus la même pièce ». Deux seuils pour la même
#: notion seraient deux vérités.
_CENTER_REPLACE = 0.70

VALID_OUTCOMES = (
    "inchange", "agrandi", "retreci", "recentre", "remplace", "abandonne",
)
VALID_ORIGINS = ("hint", "suggestion", "default")


def compute_deltas(start_cx, start_cy, start_r, after_cx, after_cy, after_r):
    """(d_r_ratio, d_cx_norm, d_cy_norm, d_center_norm) — tous None si le geste
    n'a pas eu lieu ou si la référence est inexploitable.

    Référence = `start_*`, **jamais** `before_*`. Le delta doit mesurer ce que
    L'HUMAIN a fait ; partir de `before_*` lui attribuerait le déplacement que
    la suggestion Hough a produit avant qu'il ne touche à quoi que ce soit.
    """
    if after_cx is None or after_cy is None or after_r is None:
        return (None, None, None, None)
    if not start_r or start_r <= 0 or start_cx is None or start_cy is None:
        return (None, None, None, None)
    dx = (after_cx - start_cx) / start_r
    dy = (after_cy - start_cy) / start_r
    return (after_r / start_r, dx, dy, math.hypot(dx, dy))


def classify(d_r_ratio, d_center_norm, *, touched: bool, saved: bool) -> str:
    """L'étiquette. Ordre : remplace > agrandi/retreci > recentre > inchange.

    `saved=False` (l'éditeur a été fermé sans sauvegarder) rend soit
    `inchange` — l'humain n'a rien touché, c'est un ACCORD, l'étiquette
    positive dont le jeu d'or ne peut pas se passer — soit `abandonne`, qui
    n'est ni un accord ni un désaccord et sort du jeu d'or.
    """
    if not saved:
        return "abandonne" if touched else "inchange"
    if d_center_norm is not None and d_center_norm > _CENTER_REPLACE:
        return "remplace"
    if d_r_ratio is not None and d_r_ratio > _R_GROW:
        return "agrandi"
    if d_r_ratio is not None and d_r_ratio < _R_SHRINK:
        return "retreci"
    if d_center_norm is not None and d_center_norm > _CENTER_MOVE:
        return "recentre"
    return "inchange"


def apply_crop_observation(conn, obs) -> dict:
    """Enregistre UNE observation de recadrage.

    `obs` = objet avec `.asset_id`, `.actor`, `.start_origin`, `.touched`,
    `.saved`, et optionnellement `.review_id`, `.start_{cx,cy,r}`,
    `.after_{cx,cy,r}`, `.suggestion_{cx,cy,r}`, `.suggestion_reason`,
    `.editor_version` (duck-typé : pydantic OU dataclass).

    L'AVANT n'est pas pris du client : il est relu ici, dans `image_assets`.
    Un client peut se tromper ou mentir ; la base, non.

    Retourne `{"written": bool, "outcome": str|None, "missing": [asset_id…]}`.
    """
    row = conn.execute(
        "SELECT bbox_json, detection_method FROM image_assets WHERE id = ?",
        (obs.asset_id,),
    ).fetchone()
    if row is None:
        return {"written": False, "outcome": None, "missing": [obs.asset_id]}

    before_cx = before_cy = before_r = None
    bbox = row["bbox_json"] if not isinstance(row, tuple) else row[0]
    if bbox:
        import json  # noqa: PLC0415 — stdlib, gardé local pour la lisibilité

        try:
            b = json.loads(bbox)
            # Le cercle inscrit de la bbox — `_hint_from_bbox` fait le même
            # calcul côté serveur ; on ne réinvente pas une convention.
            before_r = (float(b["w"]) + float(b["h"])) / 4.0
            before_cx = float(b["x"]) + float(b["w"]) / 2.0
            before_cy = float(b["y"]) + float(b["h"]) / 2.0
        except (ValueError, KeyError, TypeError):
            before_cx = before_cy = before_r = None

    g = lambda n, d=None: getattr(obs, n, d)  # noqa: E731
    start_cx = g("start_cx", before_cx)
    start_cy = g("start_cy", before_cy)
    start_r = g("start_r", before_r)
    after_cx, after_cy, after_r = g("after_cx"), g("after_cy"), g("after_r")

    d_r, d_cx, d_cy, d_c = compute_deltas(
        start_cx, start_cy, start_r, after_cx, after_cy, after_r)
    touched = bool(g("touched", False))
    saved = bool(g("saved", after_cx is not None))
    outcome = classify(d_r, d_c, touched=touched, saved=saved)

    conn.execute(
        """
        INSERT INTO crop_edit_observations (
          asset_id, review_id, actor,
          before_cx, before_cy, before_r, before_method,
          after_cx, after_cy, after_r,
          start_origin, start_cx, start_cy, start_r,
          suggestion_cx, suggestion_cy, suggestion_r, suggestion_reason,
          d_r_ratio, d_cx_norm, d_cy_norm, d_center_norm,
          outcome, touched, editor_version
        ) VALUES (?,?,?, ?,?,?,?, ?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?)
        """,
        (
            obs.asset_id, g("review_id"), obs.actor,
            before_cx, before_cy, before_r,
            row["detection_method"] if not isinstance(row, tuple) else row[1],
            after_cx, after_cy, after_r,
            obs.start_origin, start_cx, start_cy, start_r,
            g("suggestion_cx"), g("suggestion_cy"), g("suggestion_r"),
            g("suggestion_reason"),
            d_r, d_cx, d_cy, d_c,
            outcome, 1 if touched else 0, g("editor_version", "v1"),
        ),
    )
    return {"written": True, "outcome": outcome, "missing": []}
