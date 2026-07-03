"""Cycle de sync event-log machine ↔ canonique (local-sync).

``run_sync_cycle`` : push des ops pending de ``sync_outbox`` (lots de 500) →
pull paginé des events des autres machines (+ VPS) depuis le curseur → purge
des ops ``pushed`` d'avant le cycle (marge PO d'un sync complet). Orchestré en
continu par ``serving.sync_worker`` ; utilisable à la main via
``python -m client.sync`` (fallback CLI si l'API locale est down).

Destination = ``EURIO_API_URL`` (+ PAT ``EURIO_API_TOKEN``) — mêmes vars que
``push_run``/``pull_replica``. Sans ``EURIO_API_URL`` explicite, la sync est
considérée DÉSACTIVÉE (on ne pousse pas vers soi-même sur le défaut localhost).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field

from store import apply_remote, event_to_wire, machine_id
from store.hlc import hlc_merge

from . import http as _http

logger = logging.getLogger(__name__)

_PUSH_BATCH = 500
_PULL_LIMIT = 500
_PULL_MAX_PAGES = 200  # garde-fou : 100k events / cycle, largement au-delà du réel


def sync_enabled() -> bool:
    """La sync exige une cible explicite (jamais le défaut localhost:8042)."""
    return bool(os.environ.get("EURIO_API_URL", "").strip())


@dataclass
class SyncReport:
    ok: bool = False
    pushed: int = 0
    remote_orphaned: int = 0
    pulled_events: int = 0
    pulled_tombstones: int = 0
    purged: int = 0
    error: str | None = None
    details: list[str] = field(default_factory=list)


def _now(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT datetime('now')").fetchone()[0]


def _state_set(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _state_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key=?", (key,)
    ).fetchone()
    return row[0] if row is not None and row[0] is not None else default


def _pending_batch(conn: sqlite3.Connection) -> tuple[list[dict], list[dict], list[str]]:
    """Prochain lot pending → (events wire, tombstones wire, op_ids obsolètes).

    Un op de tombstone remplacé par un re-delete plus récent (l'UPSERT de
    ``record_tombstone`` change l'op_id de la row) est obsolète : rien à
    pousser, l'entrée outbox est soldée directement.
    """
    rows = conn.execute(
        "SELECT * FROM sync_outbox WHERE status='pending' "
        "ORDER BY created_at, op_id LIMIT ?",
        (_PUSH_BATCH,),
    ).fetchall()
    events: list[dict] = []
    tombstones: list[dict] = []
    stale: list[str] = []
    for ob in rows:
        if ob["kind"] == "event":
            ev = conn.execute(
                "SELECT * FROM image_state_events WHERE id=?",
                (ob["event_id"],),
            ).fetchone()
            if ev is None:
                stale.append(ob["op_id"])
                continue
            events.append(event_to_wire(ev))
        else:
            ts = conn.execute(
                "SELECT * FROM sync_tombstones WHERE asset_id=?",
                (ob["asset_id"],),
            ).fetchone()
            if ts is None or ts["op_id"] != ob["op_id"]:
                stale.append(ob["op_id"])
                continue
            tombstones.append({
                "op_id": ts["op_id"], "asset_id": ts["asset_id"],
                "machine": ts["machine"], "hlc": ts["hlc"],
                "storage_path": ts["storage_path"], "reason": ts["reason"],
                "created_at": ts["created_at"],
            })
    return events, tombstones, stale


def _push(conn: sqlite3.Connection, machine: str, report: SyncReport) -> None:
    while True:
        events, tombstones, stale = _pending_batch(conn)
        if stale:
            conn.executemany(
                "UPDATE sync_outbox SET status='pushed', pushed_at=datetime('now') "
                "WHERE op_id=?",
                [(op,) for op in stale],
            )
        if not events and not tombstones:
            return
        resp = _http.post_json(
            "/db/events/push",
            {"machine": machine, "events": events, "tombstones": tombstones},
        )
        accepted = set(resp.get("accepted") or [])
        orphaned = set(resp.get("orphaned") or [])
        if accepted:
            conn.executemany(
                "UPDATE sync_outbox SET status='pushed', pushed_at=datetime('now') "
                "WHERE op_id=?",
                [(op,) for op in accepted],
            )
            report.pushed += len(accepted)
        report.remote_orphaned += len(orphaned)
        server_hlc = resp.get("server_hlc")
        if server_hlc:
            hlc_merge(conn, server_hlc)
        sent = {e["op_id"] for e in events} | {t["op_id"] for t in tombstones}
        if not accepted or sent <= orphaned:
            # Tout le lot est orphelin côté serveur (runs pas encore ingérés) :
            # on s'arrête là, le prochain cycle retentera — sinon boucle infinie
            # sur le même lot.
            report.details.append(
                f"{len(orphaned)} op(s) orphelines côté serveur — repoussées au prochain cycle"
            )
            return


def _pull(conn: sqlite3.Connection, machine: str, report: SyncReport) -> None:
    cursor = _state_get(conn, "pull_cursor_hlc", "")
    for _page in range(_PULL_MAX_PAGES):
        resp = _http.get_json(
            f"/db/events/pull?machine={machine}"
            f"&since_hlc={cursor}&limit={_PULL_LIMIT}"
        )
        events = resp.get("events") or []
        tombstones = resp.get("tombstones") or []
        if events or tombstones:
            conn.execute("BEGIN IMMEDIATE")
            try:
                stats = apply_remote(conn, events=events, tombstones=tombstones)
                cursor = resp.get("max_hlc") or cursor
                _state_set(conn, "pull_cursor_hlc", cursor)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            report.pulled_events += stats.inserted
            report.pulled_tombstones += stats.tombstones_applied
            if stats.errors:
                report.details.extend(stats.errors)
        else:
            cursor = resp.get("max_hlc") or cursor
            _state_set(conn, "pull_cursor_hlc", cursor)
        if not resp.get("has_more"):
            return
    report.details.append("pull interrompu : _PULL_MAX_PAGES atteint")


def run_sync_cycle(conn: sqlite3.Connection) -> SyncReport:
    """Un cycle complet push → pull → purge. Toute erreur est capturée dans le
    rapport (le worker décide du backoff) ; ``sync_state`` reflète l'issue."""
    report = SyncReport()
    if not sync_enabled():
        report.error = "EURIO_API_URL non défini — sync désactivée"
        return report
    cycle_start = _now(conn)
    machine = machine_id(conn)
    try:
        _push(conn, machine, report)
        _pull(conn, machine, report)
        # Rétention : un op « pushed » survit toujours au moins UN cycle complet
        # réussi après son push (marge PO) — on ne purge que ceux d'avant ce cycle.
        cur = conn.execute(
            "DELETE FROM sync_outbox WHERE status='pushed' AND pushed_at < ?",
            (cycle_start,),
        )
        report.purged = cur.rowcount or 0
        report.ok = True
        _state_set(conn, "last_sync_at", _now(conn))
        _state_set(conn, "last_sync_ok", "1")
        _state_set(conn, "last_error", None)
    except Exception as exc:  # noqa: BLE001 — le worker gère le backoff
        report.error = f"{type(exc).__name__}: {exc}"
        report.ok = False
        _state_set(conn, "last_sync_at", _now(conn))
        _state_set(conn, "last_sync_ok", "0")
        _state_set(conn, "last_error", report.error)
        logger.warning("[sync] cycle en échec : %s", report.error)
    _state_set(conn, "last_push_count", str(report.pushed))
    _state_set(conn, "last_pull_count",
               str(report.pulled_events + report.pulled_tombstones))
    return report


def main() -> int:
    """CLI de secours : ``python -m client.sync`` (l'API locale n'est pas requise)."""
    import argparse

    from store import Store

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Cycle de sync event-log → canonique")
    parser.add_argument(
        "--db", default=os.environ.get("EURIO_DB_PATH", "state/eurio.db"),
        help="Chemin du SQLite local (défaut : EURIO_DB_PATH ou state/eurio.db)",
    )
    args = parser.parse_args()
    store = Store(args.db)
    report = run_sync_cycle(store._connection())  # noqa: SLF001
    print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
