"""Pont eurio.db ↔ service review (publish / reconcile).

    python -m review.publish_cli publish [--limit N]
    python -m review.publish_cli reconcile

`publish`  : pousse les items review_queue (status='open', lane manuel) de
             eurio.db vers le service review (enrichis : crop key MinIO,
             candidats avec vignettes ABSOLUES, dino top-1).
`reconcile`: tire les décisions des amis → staging eurio.db.peer_review_decisions
             (INSERT OR IGNORE = idempotent), puis les ack côté service.

À lancer quand le lease eurio.db est détenu (Mac). Le service review reste
indépendant du lease. cf. docs/work-in-progress/collaborative-review/07-reconciliation.md
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_ML_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ML_ROOT / "state" / "eurio.db"

_SERVICE_URL = os.environ.get("REVIEW_SERVICE_URL", "http://127.0.0.1:8048").rstrip("/")
_ADMIN_TOKEN = os.environ.get("REVIEW_ADMIN_TOKEN", "")
_PUBLISH_CHUNK = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ─── HTTP (stdlib, zéro dépendance) ──────────────────────────────────────────


def _headers() -> dict:
    if not _ADMIN_TOKEN:
        raise SystemExit("REVIEW_ADMIN_TOKEN absent de l'env (secrets/dev.env).")
    return {"Content-Type": "application/json", "X-Admin-Token": _ADMIN_TOKEN}


def _post_json(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{_SERVICE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers=_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (URL interne)
        return json.loads(resp.read())


def _get_json(path: str) -> dict:
    req = urllib.request.Request(f"{_SERVICE_URL}{path}", headers=_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return json.loads(resp.read())


# ─── Résolution des candidats (vignettes ABSOLUES pour le front distant) ─────


def _resolve_candidate(conn: sqlite3.Connection, eurio_id: str, score: float) -> dict | None:
    """Construit un candidat affichable à distance : label + vignette http absolue.

    La vignette doit être publiquement joignable (le front tourne sur le VPS,
    pas en local) → on ne garde que les URLs externes Numista/BCE (http*). Les
    chemins locaux /referential/… sont écartés (non servis par le VPS)."""
    from serving._coin_helpers import canonical_obverse_url

    row = conn.execute(
        "SELECT eurio_id, country, country_name, year, theme, face_value, numista_id "
        "FROM coins WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    label_bits = [row["country_name"], str(row["year"]) if row["year"] else None, row["theme"]]
    thumb = canonical_obverse_url(conn, eurio_id) or ""
    if not thumb.startswith("http"):
        thumb = ""  # local-only → non servable au front distant
    return {
        "eurio_id": row["eurio_id"],
        "score": float(score),
        "label": " · ".join(b for b in label_bits if b) or row["eurio_id"],
        "country": row["country"] or "",
        "denomination": (
            f"{float(row['face_value']):.2f} EUR" if row["face_value"] is not None else ""
        ),
        "year": row["year"],
        "thumb_url": thumb,
    }


def _build_item(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    candidates: list[dict] = []
    seen: set[str] = set()

    def _add(eurio_id: str | None, score: float) -> None:
        if not eurio_id or eurio_id in seen:
            return
        cand = _resolve_candidate(conn, eurio_id, score)
        if cand is not None:
            candidates.append(cand)
            seen.add(eurio_id)

    # 1) cible pré-attribuée (prior fort) ; 2) candidats stockés au crop ;
    # 3) top-1 Dino (country-band > global).
    _add(r["target_eurio_id"], 1.0)
    if r["candidate_eurio_ids_json"]:
        try:
            for c in json.loads(r["candidate_eurio_ids_json"]) or []:
                if isinstance(c, dict) and c.get("eurio_id"):
                    _add(c["eurio_id"], float(c.get("score", 0)))
        except (json.JSONDecodeError, TypeError):
            pass

    dino_eid = r["top1_country_eurio_id"] or r["top1_eurio_id"]
    dino_sim = r["top1_country_sim"] if r["top1_country_eurio_id"] else r["top1_sim"]
    dino_top1 = None
    if dino_eid and dino_sim is not None:
        dino_top1 = _resolve_candidate(conn, dino_eid, float(dino_sim))

    return {
        "id": r["id"],
        "image_asset_id": r["image_asset_id"],
        "storage_path": r["storage_path"],
        "source": r["source"],
        "listing_title": r["listing_title"],
        "candidates_json": json.dumps(candidates),
        "target_eurio_id": r["target_eurio_id"],
        "dino_top1_json": json.dumps(dino_top1) if dino_top1 else None,
        "priority": r["priority"] if r["priority"] is not None else 100,
    }


# ─── Commandes ───────────────────────────────────────────────────────────────


def publish(limit: int) -> int:
    from store import Store  # bootstrap schema (garantit peer_review_decisions)

    store = Store(_DB_PATH)
    conn = store._connection()  # noqa: SLF001
    rows = conn.execute(
        """
        SELECT rq.id, rq.image_asset_id, rq.priority,
               a.storage_path, a.candidate_eurio_ids_json,
               s.source, s.listing_title, s.target_eurio_id,
               p.top1_country_eurio_id, p.top1_country_sim,
               p.top1_eurio_id, p.top1_sim
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = a.id
                AND p.encoder_version = 'dinov2-vits14'
                AND p.anchors_kind = '2eur_commemo'
         WHERE rq.status = 'open'
           AND (rq.lane = 'manual' OR rq.lane IS NULL)
         ORDER BY rq.priority, rq.enqueued_at
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        print("Aucun item open (lane manuel) à publier.")
        return 0

    items = [_build_item(conn, r) for r in rows]
    total_pub = total_skip = 0
    for i in range(0, len(items), _PUBLISH_CHUNK):
        chunk = items[i : i + _PUBLISH_CHUNK]
        res = _post_json("/admin/publish", {"items": chunk})
        total_pub += res.get("published", 0)
        total_skip += res.get("skipped", 0)
    print(f"Publish : {total_pub} publiés, {total_skip} ignorés (en cours/décidés) "
          f"→ {_SERVICE_URL}")
    return 0


def reconcile() -> int:
    from store import Store

    store = Store(_DB_PATH)
    conn = store._connection()  # noqa: SLF001

    data = _get_json("/admin/decisions?unreconciled=1")
    decisions = data.get("decisions", [])
    if not decisions:
        print("Aucune décision à réconcilier.")
        return 0

    imported = 0
    with store._writing() as wconn:  # noqa: SLF001
        for d in decisions:
            cur = wconn.execute(
                """
                INSERT OR IGNORE INTO peer_review_decisions
                  (id, image_asset_id, review_item_id, reviewer_token, reviewer_name,
                   action, decided_eurio_id, decided_face, decided_variant_kind,
                   quality_reason, notes, decided_at, imported_at, arbitration_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    d["id"], d.get("item_image_asset_id"), d.get("review_item_id"),
                    d["reviewer_token"], d.get("reviewer_name", d["reviewer_token"]),
                    d["action"], d.get("decided_eurio_id"), d.get("decided_face"),
                    d.get("decided_variant_kind"), d.get("quality_reason"),
                    d.get("notes"), d["decided_at"], _now_iso(),
                ),
            )
            imported += cur.rowcount

    ack = _post_json("/admin/decisions/ack", {"ids": [d["id"] for d in decisions]})
    print(f"Reconcile : {imported} nouvelles décisions en staging "
          f"(arbitrage admin), {ack.get('acked', 0)} ackées côté service.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m review.publish_cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_pub = sub.add_parser("publish", help="pousse les items open vers le service review")
    p_pub.add_argument("--limit", type=int, default=500)
    sub.add_parser("reconcile", help="tire les décisions des amis → staging eurio.db")
    args = parser.parse_args(argv)

    if args.cmd == "publish":
        return publish(args.limit)
    if args.cmd == "reconcile":
        return reconcile()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
