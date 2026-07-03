"""Replay déterministe des events de sync distants (local-sync).

``apply_remote`` insère les events/tombstones reçus (push côté VPS, pull côté
machines) puis matérialise l'état par LWW-par-champ ordonné HLC. Déterministe :
deux bases qui ont vu le même ENSEMBLE d'events convergent vers le même état,
quel que soit l'ordre d'application des lots.

Décisions de design (docs/work-in-progress/local-sync/) :
- Idempotence par ``op_id`` (re-push/re-pull = no-op).
- Tombstone TERMINAL : tout event d'un asset tombstoné est ignoré, delete gagne.
- Insertion verbatim (op_id/machine/hlc/created_at d'origine) SANS passer par
  ``emit_state_event`` → pas d'entrée outbox (pas d'écho), pas de re-traversée
  des gardes métier (_LEGAL_TRANSITIONS, CHECK actor).
- Events d'assets inconnus : parkés dans ``sync_orphan_events``, re-tentés à
  chaque passe (l'asset arrive par /ingest/run ou pull-replica) — SAUF si
  l'event porte un row_op upsert image_assets (snapshot add-crop) qui suffit
  à créer la row.
- Matérialisation : dernière valeur par ``(asset, "table.colonne")`` dans
  l'ordre (hlc NULLS FIRST, created_at, id) — les events legacy sans hlc
  comptent comme plus anciens.

S'exécute dans la transaction du CALLER (pas de BEGIN/COMMIT ici), comme
``emit_state_event``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field

from .hlc import hlc_merge

logger = logging.getLogger(__name__)

# Tables adressables par la convention "table.colonne" (clé = asset).
_FIELD_TABLES = {
    "image_assets": ("id", "strict"),
    "review_queue": ("image_asset_id", "upsert"),
    "cohort_training_scan_results": ("image_asset_id", "best_effort"),
}
# Tables autorisées en row_ops (clé explicite portée par l'op).
_ROW_OP_TABLES = frozenset(("image_assets", "review_queue", "dino_class_references"))

_EVENT_ORDER = "(hlc IS NOT NULL), hlc, created_at, id"


@dataclass
class ReplayStats:
    inserted: int = 0
    duplicates: int = 0
    orphaned: int = 0
    orphans_retried: int = 0
    tombstones_applied: int = 0
    assets_materialized: int = 0
    skipped_dead: int = 0
    errors: list[str] = field(default_factory=list)


def _ident_ok(name: str) -> bool:
    return name.replace("_", "").isalnum()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _op_known(conn: sqlite3.Connection, op_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM image_state_events WHERE op_id=?", (op_id,)
        ).fetchone() is not None
        or conn.execute(
            "SELECT 1 FROM sync_orphan_events WHERE op_id=?", (op_id,)
        ).fetchone() is not None
    )


def _asset_exists(conn: sqlite3.Connection, asset_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM image_assets WHERE id=?", (asset_id,)
    ).fetchone() is not None


def _is_dead(conn: sqlite3.Connection, asset_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sync_tombstones WHERE asset_id=?", (asset_id,)
    ).fetchone() is not None


def _row_ops_of(event: dict) -> list[dict]:
    detail = event.get("detail_json")
    if not detail:
        return []
    try:
        body = json.loads(detail)
    except (json.JSONDecodeError, TypeError):
        return []
    ops = body.get("row_ops")
    return ops if isinstance(ops, list) else []


def _apply_row_op(conn: sqlite3.Connection, op: dict, stats: ReplayStats) -> None:
    """UPSERT/DELETE générique par égalité de clé. Colonnes inconnues ignorées
    (payload d'une version plus récente → forward-compat, loggé)."""
    table = op.get("table")
    if table not in _ROW_OP_TABLES:
        stats.errors.append(f"row_op table refusée : {table}")
        return
    key = op.get("key") or {}
    if not key or not all(_ident_ok(k) for k in key):
        stats.errors.append(f"row_op clé invalide sur {table}")
        return
    cols = _table_columns(conn, table)
    if op.get("op") == "delete":
        where = " AND ".join(f"{k}=?" for k in key)
        conn.execute(f"DELETE FROM {table} WHERE {where}", list(key.values()))  # noqa: S608
        return
    values = {
        k: v for k, v in (op.get("values") or {}).items()
        if _ident_ok(k) and k in cols
    }
    unknown = set(op.get("values") or {}) - set(values)
    if unknown:
        logger.warning("row_op %s : colonnes ignorées %s", table, sorted(unknown))
    row = {**key, **values}
    placeholders = ",".join("?" * len(row))
    col_list = ",".join(row)
    updates = ",".join(f"{c}=excluded.{c}" for c in values) or None
    key_list = ",".join(key)
    if updates:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "  # noqa: S608
            f"ON CONFLICT({key_list}) DO UPDATE SET {updates}"
        )
    else:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "  # noqa: S608
            f"ON CONFLICT({key_list}) DO NOTHING"
        )
    conn.execute(sql, list(row.values()))


def _insert_event_verbatim(conn: sqlite3.Connection, ev: dict) -> None:
    conn.execute(
        "INSERT INTO image_state_events "
        "(asset_id, from_state, to_state, actor, reason, eurio_id, "
        " target_eurio_id, run_id, detail_json, created_at, op_id, machine, hlc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ev["asset_id"], ev.get("from_state"), ev["to_state"], ev["actor"],
         ev.get("reason"), ev.get("eurio_id"), ev.get("target_eurio_id"),
         ev.get("run_id"), ev.get("detail_json"), ev["created_at"],
         ev["op_id"], ev["machine"], ev["hlc"]),
    )


def _materialize_asset(
    conn: sqlite3.Connection, asset_id: str, stats: ReplayStats,
) -> None:
    """LWW-par-champ : dernière valeur par ``table.colonne`` dans l'ordre HLC.

    Relit TOUS les events porteurs de ``fields`` de l'asset (locaux + reçus,
    déjà fusionnés dans le log) → le résultat ne dépend pas de l'ordre
    d'arrivée des lots. Les row_ops, déjà appliqués à l'insertion, ne sont pas
    rejoués ici (un row_op est un INSERT/DELETE ponctuel, pas un champ LWW).
    """
    rows = conn.execute(
        f"SELECT detail_json FROM image_state_events "  # noqa: S608
        f"WHERE asset_id=? AND detail_json IS NOT NULL "
        f"ORDER BY {_EVENT_ORDER}",
        (asset_id,),
    ).fetchall()
    winners: dict[str, object] = {}
    for r in rows:
        try:
            body = json.loads(r["detail_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        fields = body.get("fields")
        if not isinstance(fields, dict):
            continue
        winners.update(fields)
    if not winners:
        return

    by_table: dict[str, dict[str, object]] = {}
    for key, value in winners.items():
        table, _, column = key.partition(".")
        if table not in _FIELD_TABLES or not _ident_ok(column):
            stats.errors.append(f"field refusé : {key}")
            continue
        by_table.setdefault(table, {})[column] = value

    for table, cols in by_table.items():
        key_col, mode = _FIELD_TABLES[table]
        valid = _table_columns(conn, table)
        cols = {c: v for c, v in cols.items() if c in valid}
        if not cols:
            continue
        assigns = ",".join(f"{c}=?" for c in cols)
        params = [*cols.values(), asset_id]
        cur = conn.execute(
            f"UPDATE {table} SET {assigns} WHERE {key_col}=?",  # noqa: S608
            params,
        )
        if cur.rowcount == 0 and mode == "upsert":
            # review_queue : la machine distante n'a pas encore de row pour ce
            # crop (elle n'a pas vu l'enqueue) → on la crée depuis les fields.
            # enqueued_at NOT NULL : défaut porté par le schéma ? Non — posé ici.
            insert_cols = {"id": uuid.uuid4().hex, "image_asset_id": asset_id}
            if "enqueued_at" in valid and "enqueued_at" not in cols:
                insert_cols["enqueued_at"] = None  # remplacé sous peu
            row = {**insert_cols, **cols}
            if row.get("enqueued_at") is None and "enqueued_at" in row:
                row["enqueued_at"] = conn.execute(
                    "SELECT datetime('now')"
                ).fetchone()[0]
            col_list = ",".join(row)
            ph = ",".join("?" * len(row))
            conn.execute(
                f"INSERT INTO {table} ({col_list}) VALUES ({ph}) "  # noqa: S608
                f"ON CONFLICT(image_asset_id) DO NOTHING",
                list(row.values()),
            )
    stats.assets_materialized += 1


def _rebuild_current(conn: sqlite3.Connection, asset_id: str) -> None:
    """Recale ``image_state_current`` sur le dernier event ORDRE HLC (variante
    multi-machine de ``client.runbatch._rebuild_state_current`` qui ordonne par
    created_at/id — insuffisant quand deux machines écrivent)."""
    conn.execute(
        f"""
        INSERT INTO image_state_current
            (asset_id, current_state, eurio_id, target_eurio_id,
             last_event_id, actor, state_since)
        SELECT e.asset_id, e.to_state, e.eurio_id, e.target_eurio_id,
               e.id, e.actor, e.created_at
        FROM image_state_events e
        WHERE e.asset_id = ?
          AND e.id = (
              SELECT x.id FROM image_state_events x
              WHERE x.asset_id = e.asset_id
              ORDER BY (x.hlc IS NOT NULL) DESC, x.hlc DESC,
                       x.created_at DESC, x.id DESC LIMIT 1
          )
        ON CONFLICT(asset_id) DO UPDATE SET
            current_state=excluded.current_state,
            eurio_id=COALESCE(excluded.eurio_id, image_state_current.eurio_id),
            target_eurio_id=COALESCE(excluded.target_eurio_id,
                                     image_state_current.target_eurio_id),
            last_event_id=excluded.last_event_id,
            actor=excluded.actor,
            state_since=excluded.state_since
        """,  # noqa: S608
        (asset_id,),
    )


def apply_remote(
    conn: sqlite3.Connection,
    *,
    events: list[dict],
    tombstones: list[dict] | None = None,
) -> ReplayStats:
    """Applique un lot d'events/tombstones distants + matérialise. Idempotent."""
    stats = ReplayStats()
    tombstones = tombstones or []

    # 0. Re-tente les orphelins parkés dont l'asset est apparu depuis.
    retried: list[dict] = []
    for row in conn.execute(
        "SELECT op_id, payload_json FROM sync_orphan_events ORDER BY received_at"
    ).fetchall():
        ev = json.loads(row["payload_json"])
        if _asset_exists(conn, ev["asset_id"]) or _is_dead(conn, ev["asset_id"]):
            retried.append(ev)
    if retried:
        conn.executemany(
            "DELETE FROM sync_orphan_events WHERE op_id=?",
            [(e["op_id"],) for e in retried],
        )
        stats.orphans_retried = len(retried)

    # 1. Tombstones d'abord (terminal — delete gagne).
    max_hlc: str | None = None
    for ts in tombstones:
        max_hlc = max(max_hlc or ts["hlc"], ts["hlc"])
        exists = conn.execute(
            "SELECT op_id FROM sync_tombstones WHERE asset_id=?",
            (ts["asset_id"],),
        ).fetchone()
        if exists is not None and exists["op_id"] == ts["op_id"]:
            stats.duplicates += 1
            continue
        conn.execute(
            "INSERT INTO sync_tombstones "
            "(asset_id, op_id, machine, hlc, storage_path, reason, created_at) "
            "VALUES (?,?,?,?,?,?,COALESCE(?, datetime('now'))) "
            "ON CONFLICT(asset_id) DO UPDATE SET "
            "  op_id=excluded.op_id, machine=excluded.machine, "
            "  hlc=MAX(excluded.hlc, sync_tombstones.hlc), "
            "  storage_path=COALESCE(excluded.storage_path, sync_tombstones.storage_path), "
            "  reason=COALESCE(excluded.reason, sync_tombstones.reason)",
            (ts["asset_id"], ts["op_id"], ts["machine"], ts["hlc"],
             ts.get("storage_path"), ts.get("reason"), ts.get("created_at")),
        )
        conn.execute("DELETE FROM image_assets WHERE id=?", (ts["asset_id"],))
        conn.execute(
            "DELETE FROM sync_orphan_events "
            "WHERE json_extract(payload_json, '$.asset_id')=?",
            (ts["asset_id"],),
        )
        stats.tombstones_applied += 1

    # 2. Events (reçus + orphelins rejoués).
    touched: set[str] = set()
    for ev in [*retried, *events]:
        if ev.get("hlc"):
            max_hlc = max(max_hlc or ev["hlc"], ev["hlc"])
        if _op_known(conn, ev["op_id"]):
            stats.duplicates += 1
            continue
        if _is_dead(conn, ev["asset_id"]):
            stats.skipped_dead += 1
            continue
        if not _asset_exists(conn, ev["asset_id"]):
            # Snapshot add-crop : le row_op upsert image_assets crée la row.
            creators = [
                op for op in _row_ops_of(ev)
                if op.get("op") == "upsert" and op.get("table") == "image_assets"
            ]
            if not creators:
                conn.execute(
                    "INSERT OR IGNORE INTO sync_orphan_events (op_id, payload_json) "
                    "VALUES (?, ?)",
                    (ev["op_id"], json.dumps(ev)),
                )
                stats.orphaned += 1
                continue
        for op in _row_ops_of(ev):
            _apply_row_op(conn, op, stats)
        if not _asset_exists(conn, ev["asset_id"]):
            # Le row_op n'a pas suffi (FK source_image absente…) → parke.
            conn.execute(
                "INSERT OR IGNORE INTO sync_orphan_events (op_id, payload_json) "
                "VALUES (?, ?)",
                (ev["op_id"], json.dumps(ev)),
            )
            stats.orphaned += 1
            continue
        _insert_event_verbatim(conn, ev)
        stats.inserted += 1
        touched.add(ev["asset_id"])

    # 3. Matérialisation + état courant, par asset touché.
    for asset_id in sorted(touched):
        _materialize_asset(conn, asset_id, stats)
        _rebuild_current(conn, asset_id)

    # 4. Causalité : tout event local futur ordonne après ce qu'on vient de voir.
    if max_hlc:
        hlc_merge(conn, max_hlc)
    return stats


def event_to_wire(row: sqlite3.Row) -> dict:
    """Sérialise une row ``image_state_events`` pour le transport push/pull."""
    return {
        "op_id": row["op_id"],
        "asset_id": row["asset_id"],
        "from_state": row["from_state"],
        "to_state": row["to_state"],
        "actor": row["actor"],
        "reason": row["reason"],
        "eurio_id": row["eurio_id"],
        "target_eurio_id": row["target_eurio_id"],
        "run_id": row["run_id"],
        "detail_json": row["detail_json"],
        "created_at": row["created_at"],
        "machine": row["machine"],
        "hlc": row["hlc"],
    }


def tombstone_to_wire(row: sqlite3.Row) -> dict:
    return {
        "op_id": row["op_id"],
        "asset_id": row["asset_id"],
        "machine": row["machine"],
        "hlc": row["hlc"],
        "storage_path": row["storage_path"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    }
