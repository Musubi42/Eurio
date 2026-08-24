"""Store — domaine dino (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass
class DinoPredictionRow:
    """One DINOv2 top-K result for a scraped crop, versioned by encoder + scope.

    Stored in `image_asset_dino_predictions` (PK composée). Allows multiple
    encoder versions / anchor scopes to coexist for the same asset. The
    asset's own `resolution_status` stays in `needs_review` — Dino is an
    aid signal, not a decision.
    """

    asset_id: str
    encoder_version: str
    anchors_kind: str
    anchors_count: int
    top_k: list[dict]
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    top2_eurio_id: str | None = None
    top2_sim: float | None = None
    spread: float | None = None
    # Country-restricted re-rank (chunk 3.5). Populated when the source
    # crop carries a target country signal (eBay query target). NULL on
    # rows without a country signal — front degrades gracefully.
    target_country: str | None = None
    country_anchors_count: int | None = None
    top_k_country: list[dict] | None = None
    top1_country_eurio_id: str | None = None
    top1_country_sim: float | None = None
    top2_country_eurio_id: str | None = None
    top2_country_sim: float | None = None
    country_spread: float | None = None
    # Face detection (C7) : sim max aux 2 ancres du revers commun 2€ et marge
    # reverse-ness − obverse-ness (= reverse_sim − top1_sim). Renseignées
    # seulement sur la row anchors_kind='2eur_all' (même encodeur vitl14 que
    # la banque revers). NULL ailleurs.
    reverse_sim: float | None = None
    face_margin: float | None = None
    # Gate dénomination (C7 pilier 2) : score 2€-ness ∈ [0,1] de la probe
    # DINO+bimétal (`vision/denom_probe.py`). Renseigné seulement sur la row
    # anchors_kind='2eur_all' (vitl14). NULL ailleurs. Ranker doux + le verdict
    # binaire vit sur image_assets.denom.
    denom_2eur_score: float | None = None
    duration_ms: int | None = None
    computed_at: str | None = None
    # Model B (C6b) : run_id du backfill DINO qui a produit cette prédiction.
    # NULL pour les prédictions du pipeline scrape normal (collectées par asset_id
    # via le run parent de l'asset). Renseigné par run_auto_validate_dino_backfill
    # → export_run collecte ces prédictions sur assets préexistants via run_id.
    run_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "encoder_version": self.encoder_version,
            "anchors_kind": self.anchors_kind,
            "anchors_count": self.anchors_count,
            "top_k": self.top_k,
            "top1_eurio_id": self.top1_eurio_id,
            "top1_sim": self.top1_sim,
            "top2_eurio_id": self.top2_eurio_id,
            "top2_sim": self.top2_sim,
            "spread": self.spread,
            "target_country": self.target_country,
            "country_anchors_count": self.country_anchors_count,
            "top_k_country": self.top_k_country,
            "top1_country_eurio_id": self.top1_country_eurio_id,
            "top1_country_sim": self.top1_country_sim,
            "top2_country_eurio_id": self.top2_country_eurio_id,
            "top2_country_sim": self.top2_country_sim,
            "country_spread": self.country_spread,
            "reverse_sim": self.reverse_sim,
            "face_margin": self.face_margin,
            "denom_2eur_score": self.denom_2eur_score,
            "duration_ms": self.duration_ms,
            "computed_at": self.computed_at,
            "run_id": self.run_id,
        }


def _row_to_dino_prediction(r: sqlite3.Row) -> DinoPredictionRow:
    cols = r.keys()

    def _maybe(name: str):
        return r[name] if name in cols else None

    raw_country_json = _maybe("top_k_country_json")
    return DinoPredictionRow(
        asset_id=r["asset_id"],
        encoder_version=r["encoder_version"],
        anchors_kind=r["anchors_kind"],
        anchors_count=r["anchors_count"],
        top_k=json.loads(r["top_k_json"]) if r["top_k_json"] else [],
        top1_eurio_id=r["top1_eurio_id"],
        top1_sim=r["top1_sim"],
        top2_eurio_id=r["top2_eurio_id"],
        top2_sim=r["top2_sim"],
        spread=r["spread"],
        target_country=_maybe("target_country"),
        country_anchors_count=_maybe("country_anchors_count"),
        top_k_country=json.loads(raw_country_json) if raw_country_json else None,
        top1_country_eurio_id=_maybe("top1_country_eurio_id"),
        top1_country_sim=_maybe("top1_country_sim"),
        top2_country_eurio_id=_maybe("top2_country_eurio_id"),
        top2_country_sim=_maybe("top2_country_sim"),
        country_spread=_maybe("country_spread"),
        reverse_sim=_maybe("reverse_sim"),
        face_margin=_maybe("face_margin"),
        denom_2eur_score=_maybe("denom_2eur_score"),
        duration_ms=r["duration_ms"],
        computed_at=r["computed_at"],
        run_id=_maybe("run_id"),
    )


def _upsert_dino_rows_sql(conn: sqlite3.Connection, rows: list[DinoPredictionRow]) -> None:
    """UPSERT bas-niveau, SQL-pur, commit-free (le caller possède la transaction).

    Factorisée entre ``DinoMixin.upsert_dino_predictions`` (écriture locale via
    ``self._writing()``) et ``apply_ingest_dino`` (write-half ``POST
    /ingest/dino``, Direction A C4d) — même contrat que ``store/crops.py`` /
    ``store/faces.py`` : un seul point de vérité pour le SQL.
    """
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO image_asset_dino_predictions (
                  asset_id, encoder_version, anchors_kind, anchors_count,
                  top_k_json, top1_eurio_id, top1_sim, top2_eurio_id,
                  top2_sim, spread,
                  target_country, country_anchors_count, top_k_country_json,
                  top1_country_eurio_id, top1_country_sim,
                  top2_country_eurio_id, top2_country_sim, country_spread,
                  reverse_sim, face_margin, denom_2eur_score,
                  computed_at, duration_ms, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?,
                          datetime('now'), ?, ?)
                ON CONFLICT(asset_id, encoder_version, anchors_kind) DO UPDATE SET
                  anchors_count          = excluded.anchors_count,
                  top_k_json             = excluded.top_k_json,
                  top1_eurio_id          = excluded.top1_eurio_id,
                  top1_sim               = excluded.top1_sim,
                  top2_eurio_id          = excluded.top2_eurio_id,
                  top2_sim               = excluded.top2_sim,
                  spread                 = excluded.spread,
                  target_country         = excluded.target_country,
                  country_anchors_count  = excluded.country_anchors_count,
                  top_k_country_json     = excluded.top_k_country_json,
                  top1_country_eurio_id  = excluded.top1_country_eurio_id,
                  top1_country_sim       = excluded.top1_country_sim,
                  top2_country_eurio_id  = excluded.top2_country_eurio_id,
                  top2_country_sim       = excluded.top2_country_sim,
                  country_spread         = excluded.country_spread,
                  reverse_sim            = excluded.reverse_sim,
                  face_margin            = excluded.face_margin,
                  denom_2eur_score       = excluded.denom_2eur_score,
                  duration_ms            = excluded.duration_ms,
                  computed_at            = datetime('now'),
                  -- Migration 0013 : le ré-encodage LÈVE la péremption posée par
                  -- un recadrage. Sans cette ligne, le cycle marquer → réencoder
                  -- → démarquer ne boucle pas, et les deux bouts pourrissent en
                  -- silence : l'écran continue d'annoncer « calculée avant ton
                  -- recadrage » sur une prédiction fraîche, et `_existing_keys`
                  -- la voit « absente » à CHAQUE backfill, donc la réencode
                  -- indéfiniment. C'est ICI qu'il faut l'écrire — ce SQL est le
                  -- point de passage réel (backfill via Store, et le write-half
                  -- de POST /ingest/dino).
                  stale_since            = NULL,
                  -- Model B : préserve l'attribution backfill (run_id) si la
                  -- nouvelle écriture est run_id NULL (pipeline scrape normal).
                  run_id                 = COALESCE(excluded.run_id,
                                                    image_asset_dino_predictions.run_id)
                """,
                [
                    (
                        r.asset_id,
                        r.encoder_version,
                        r.anchors_kind,
                        r.anchors_count,
                        json.dumps(r.top_k),
                        r.top1_eurio_id,
                        r.top1_sim,
                        r.top2_eurio_id,
                        r.top2_sim,
                        r.spread,
                        r.target_country,
                        r.country_anchors_count,
                        json.dumps(r.top_k_country) if r.top_k_country is not None else None,
                        r.top1_country_eurio_id,
                        r.top1_country_sim,
                        r.top2_country_eurio_id,
                        r.top2_country_sim,
                        r.country_spread,
                        r.reverse_sim,
                        r.face_margin,
                        r.denom_2eur_score,
                        r.duration_ms,
                        r.run_id,
                    )
                    for r in rows
                ],
    )


def apply_ingest_dino(conn: sqlite3.Connection, predictions) -> dict:
    """Écrit des prédictions Dino calculées client-side — write-half SQL-pure
    (Direction A, C4d). Miroir de ``store/crops.py::apply_ingest_crops`` /
    ``store/faces.py::apply_ingest_faces`` : commit-free (le caller possède la
    transaction), UPSERT idempotent, asset_id inconnus tolérés (``missing``).

    ``predictions`` = itérable d'objets duck-typés (pydantic OU dataclass) avec
    les mêmes champs que ``DinoPredictionRow`` (asset_id, encoder_version,
    anchors_kind, anchors_count, top_k, ...). Retourne
    ``{"updated": n, "missing": [asset_id…]}``.
    """
    valid_rows: list[DinoPredictionRow] = []
    missing: list = []
    for p in predictions:
        row = conn.execute(
            "SELECT id FROM image_assets WHERE id = ?", (p.asset_id,),
        ).fetchone()
        if row is None:
            missing.append(p.asset_id)
            continue
        valid_rows.append(
            DinoPredictionRow(
                asset_id=p.asset_id,
                encoder_version=p.encoder_version,
                anchors_kind=p.anchors_kind,
                anchors_count=p.anchors_count,
                top_k=p.top_k,
                top1_eurio_id=p.top1_eurio_id,
                top1_sim=p.top1_sim,
                top2_eurio_id=p.top2_eurio_id,
                top2_sim=p.top2_sim,
                spread=p.spread,
                target_country=p.target_country,
                country_anchors_count=p.country_anchors_count,
                top_k_country=p.top_k_country,
                top1_country_eurio_id=p.top1_country_eurio_id,
                top1_country_sim=p.top1_country_sim,
                top2_country_eurio_id=p.top2_country_eurio_id,
                top2_country_sim=p.top2_country_sim,
                country_spread=p.country_spread,
                reverse_sim=p.reverse_sim,
                face_margin=p.face_margin,
                denom_2eur_score=p.denom_2eur_score,
                duration_ms=p.duration_ms,
                run_id=p.run_id,
            )
        )
    _upsert_dino_rows_sql(conn, valid_rows)
    return {"updated": len(valid_rows), "missing": missing}


class DinoMixin:

    # ─── Dino predictions on scraped crops ───────────────────────────────

    def upsert_dino_predictions(self, rows: list[DinoPredictionRow]) -> int:
        if not rows:
            return 0
        with self._writing() as c:
            _upsert_dino_rows_sql(c, rows)
        return len(rows)

    def get_dino_prediction(
        self,
        asset_id: str,
        encoder_version: str,
        anchors_kind: str,
    ) -> DinoPredictionRow | None:
        row = self._connection().execute(
            """
            SELECT * FROM image_asset_dino_predictions
             WHERE asset_id = ? AND encoder_version = ? AND anchors_kind = ?
            """,
            (asset_id, encoder_version, anchors_kind),
        ).fetchone()
        return _row_to_dino_prediction(row) if row else None

    def list_dino_predictions_for_asset(
        self, asset_id: str
    ) -> list[DinoPredictionRow]:
        rows = self._connection().execute(
            "SELECT * FROM image_asset_dino_predictions WHERE asset_id = ? "
            "ORDER BY computed_at DESC",
            (asset_id,),
        ).fetchall()
        return [_row_to_dino_prediction(r) for r in rows]
