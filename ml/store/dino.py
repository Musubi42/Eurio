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
    duration_ms: int | None = None
    computed_at: str | None = None

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
            "duration_ms": self.duration_ms,
            "computed_at": self.computed_at,
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
        duration_ms=r["duration_ms"],
        computed_at=r["computed_at"],
    )


class DinoMixin:

    # ─── Dino predictions on scraped crops ───────────────────────────────

    def upsert_dino_predictions(self, rows: list[DinoPredictionRow]) -> int:
        if not rows:
            return 0
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO image_asset_dino_predictions (
                  asset_id, encoder_version, anchors_kind, anchors_count,
                  top_k_json, top1_eurio_id, top1_sim, top2_eurio_id,
                  top2_sim, spread,
                  target_country, country_anchors_count, top_k_country_json,
                  top1_country_eurio_id, top1_country_sim,
                  top2_country_eurio_id, top2_country_sim, country_spread,
                  reverse_sim, face_margin,
                  computed_at, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?,
                          datetime('now'), ?)
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
                  duration_ms            = excluded.duration_ms,
                  computed_at            = datetime('now')
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
                        r.duration_ms,
                    )
                    for r in rows
                ],
            )
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
