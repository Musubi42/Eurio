"""Run-batch — export/ingest des écritures lourdes scopées par run (Modèle B, C1).

Un run de calcul (scraping / recrop / dino) produit 50K-300K lignes réparties sur
~9 tables, toutes rattachables à un ``run_id`` (``source_runs.id``) via le graphe
FK. Le compute tourne sur une réplique read-only locale puis pousse ces lignes au
serveur canonique (writer unique), qui les applique en UNE transaction idempotente.

    batch = export_run(replica_conn, run_id)   # côté workstation (lecture)
    ingest_run(canonical_conn, batch)          # côté serveur (écriture)

Idempotence — deux garde-fous complémentaires :
1. **UPSERT par clé naturelle** (PK introspectée via PRAGMA) pour les 8 tables à PK
   stable → ré-appliquer les mêmes lignes ne duplique rien.
2. **Garde ``batch_sha``** dans ``ingested_runs`` : un re-POST du même contenu est un
   no-op total. Couvre ``image_state_events`` (id AUTOINCREMENT non porté, pas de clé
   naturelle) ; ses lignes sont scopées par ``run_id`` et remplacées à l'apply.

Le fichier canonique n'est écrit QUE par ``ingest_run`` (côté serveur). ``export_run``
est lecture seule.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

# Tables transportées, dans l'ordre d'APPLICATION (parents avant enfants — FK ON).
# `image_state_events` est traité à part (pas de clé naturelle).
_TABLE_ORDER = [
    "source_runs",
    "source_images",
    "image_assets",
    "listing_text_signals",
    "image_asset_dino_predictions",
    "review_queue",
    "consensus_verdicts",
    "coin_market_quotes",
]
_EVENTS = "image_state_events"

# Limite de variables liées SQLite (défensif : < 999 sur les vieux builds).
_IN_CHUNK = 400


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _rows_in(conn: sqlite3.Connection, sql_tmpl: str, ids: list[str]) -> list[dict]:
    """``sql_tmpl`` contient un seul ``{ph}`` pour la clause IN. Chunké."""
    out: list[dict] = []
    for i in range(0, len(ids), _IN_CHUNK):
        chunk = ids[i : i + _IN_CHUNK]
        ph = ",".join("?" * len(chunk))
        out.extend(_rows(conn, sql_tmpl.format(ph=ph), tuple(chunk)))
    return out


def _pk_cols(conn: sqlite3.Connection, table: str) -> list[str]:
    """Colonnes de la PK, dans l'ordre (PRAGMA ``pk`` = position 1-based)."""
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk = sorted((r for r in info if r[5]), key=lambda r: r[5])
    return [r[1] for r in pk]


# ─── Export (lecture seule, côté workstation) ────────────────────────────────


def export_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """Collecte toutes les lignes d'un run sur le graphe de tables lourdes.

    Containment : ``source_runs`` par id ; ``source_images``/``coin_market_quotes``
    par ``run_id`` ; ``image_assets`` par ``run_id`` OU ``source_image_id`` du run
    (couvre scrape ET recrop) ; enfants par asset/source_image ;
    ``image_state_events`` par ``run_id`` (l'id AUTOINCREMENT est retiré).
    Toutes les requêtes sont ``ORDER BY`` → sérialisation déterministe (sha stable).
    """
    tables: dict[str, list[dict]] = {}
    tables["source_runs"] = _rows(
        conn, "SELECT * FROM source_runs WHERE id=? ORDER BY id", (run_id,)
    )
    tables["source_images"] = _rows(
        conn, "SELECT * FROM source_images WHERE run_id=? ORDER BY id", (run_id,)
    )
    si_ids = [r["id"] for r in tables["source_images"]]

    assets = _rows(
        conn, "SELECT * FROM image_assets WHERE run_id=? ORDER BY id", (run_id,)
    )
    if si_ids:
        extra = _rows_in(
            conn,
            "SELECT * FROM image_assets WHERE source_image_id IN ({ph}) ORDER BY id",
            si_ids,
        )
        seen = {a["id"] for a in assets}
        assets.extend(a for a in extra if a["id"] not in seen)
        assets.sort(key=lambda a: a["id"])
    tables["image_assets"] = assets
    asset_ids = [a["id"] for a in assets]

    tables["listing_text_signals"] = _rows_in(
        conn,
        "SELECT * FROM listing_text_signals WHERE source_image_id IN ({ph}) "
        "ORDER BY source_image_id",
        si_ids,
    ) if si_ids else []
    tables["image_asset_dino_predictions"] = _rows_in(
        conn,
        "SELECT * FROM image_asset_dino_predictions WHERE asset_id IN ({ph}) "
        "ORDER BY asset_id, encoder_version, anchors_kind",
        asset_ids,
    ) if asset_ids else []
    tables["review_queue"] = _rows_in(
        conn,
        "SELECT * FROM review_queue WHERE image_asset_id IN ({ph}) ORDER BY id",
        asset_ids,
    ) if asset_ids else []
    tables["consensus_verdicts"] = _rows_in(
        conn,
        "SELECT * FROM consensus_verdicts WHERE image_asset_id IN ({ph}) "
        "ORDER BY image_asset_id, rule_version",
        asset_ids,
    ) if asset_ids else []
    tables["coin_market_quotes"] = _rows(
        conn, "SELECT * FROM coin_market_quotes WHERE run_id=? ORDER BY id", (run_id,)
    )

    events = _rows(
        conn,
        "SELECT * FROM image_state_events WHERE run_id=? ORDER BY id",
        (run_id,),
    )
    for e in events:
        e.pop("id", None)  # AUTOINCREMENT : non porté (diffère d'une DB à l'autre)
    tables[_EVENTS] = events

    return {"run_id": run_id, "tables": tables}


def batch_sha(batch: dict[str, Any]) -> str:
    """Empreinte déterministe du contenu (tables ordonnées + clés triées)."""
    payload = json.dumps(batch["tables"], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


# ─── Ingest (écriture, côté serveur canonique) ───────────────────────────────


def _upsert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    pk = _pk_cols(conn, table)
    cols = list(rows[0].keys())
    placeholders = ",".join("?" * len(cols))
    conflict = ",".join(pk)
    non_pk = [c for c in cols if c not in pk]
    if non_pk:
        set_clause = ",".join(f"{c}=excluded.{c}" for c in non_pk)
        action = f"DO UPDATE SET {set_clause}"
    else:
        action = "DO NOTHING"  # toutes colonnes = PK
    sql = (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({conflict}) {action}"
    )
    conn.executemany(sql, [[r[c] for c in cols] for r in rows])
    return len(rows)


def push_run(conn: sqlite3.Connection, run_id: str, *, poster=None) -> dict[str, Any]:
    """Exporte un run depuis la réplique locale et le POST au serveur canonique.

    ``poster`` injectable (tests) : ``poster(path, payload) -> dict``. Défaut =
    ``client.http.post_json`` (import paresseux pour éviter le cycle).
    """
    batch = export_run(conn, run_id)
    if poster is None:
        from client import http  # noqa: PLC0415
        poster = http.post_json
    return poster("/ingest/run", batch)


def _rebuild_state_current(conn: sqlite3.Connection, asset_ids: list[str]) -> None:
    """Recale ``image_state_current`` sur le dernier event de chaque asset touché.

    ``image_state_current`` est une table DÉRIVÉE (état courant par asset) dont
    ``last_event_id`` pointe vers ``image_state_events.id``. Comme l'ingest
    remplace les events du run (delete + ré-insert avec de NOUVEAUX id autoinc),
    ces pointeurs deviennent pendants → on les reconstruit ici, en répliquant la
    sémantique de ``store.events.emit_state_event`` (COALESCE sur eurio_id/target).
    On lit l'historique RÉEL post-apply (dernier event par ``created_at`` puis
    ``id``), donc le résultat est correct même en ré-application out-of-order.
    """
    for i in range(0, len(asset_ids), _IN_CHUNK):
        chunk = asset_ids[i : i + _IN_CHUNK]
        ph = ",".join("?" * len(chunk))
        conn.execute(
            f"""
            INSERT INTO image_state_current
                (asset_id, current_state, eurio_id, target_eurio_id,
                 last_event_id, actor, state_since)
            SELECT e.asset_id, e.to_state, e.eurio_id, e.target_eurio_id,
                   e.id, e.actor, e.created_at
            FROM image_state_events e
            WHERE e.asset_id IN ({ph})
              AND e.id = (
                  SELECT x.id FROM image_state_events x
                  WHERE x.asset_id = e.asset_id
                  ORDER BY x.created_at DESC, x.id DESC LIMIT 1
              )
            ON CONFLICT(asset_id) DO UPDATE SET
                current_state=excluded.current_state,
                eurio_id=COALESCE(excluded.eurio_id, image_state_current.eurio_id),
                target_eurio_id=COALESCE(excluded.target_eurio_id,
                                         image_state_current.target_eurio_id),
                last_event_id=excluded.last_event_id,
                actor=excluded.actor,
                state_since=excluded.state_since
            """,
            chunk,
        )


def ingest_run(conn: sqlite3.Connection, batch: dict[str, Any]) -> dict[str, Any]:
    """Applique un run-batch au canonique en UNE transaction, idempotent.

    Suppose une connexion en autocommit (``isolation_level=None``, style ``Store``) :
    on ouvre une transaction explicite ``BEGIN IMMEDIATE`` (cf.
    [[feedback_store_autocommit_unique]]). Re-POST du même ``batch_sha`` = no-op.

    ``PRAGMA defer_foreign_keys`` reporte la vérification des FK au COMMIT : (1) le
    DELETE des events du run, référencés par ``image_state_current.last_event_id``,
    ne casse plus en cours de transaction (on recale ``image_state_current`` juste
    après, cf. ``_rebuild_state_current``) ; (2) les violations FK HISTORIQUES déjà
    présentes dans le canonique (orphelins de prune) ne sont pas comptées par le
    compteur deferred, donc elles ne bloquent pas un batch sain. Le serveur tourne
    ``foreign_keys=ON`` : un batch qui introduirait une VRAIE violation est bien
    rejeté au COMMIT.
    """
    run_id = batch["run_id"]
    tables = batch["tables"]
    sha = batch_sha(batch)

    prev = conn.execute(
        "SELECT batch_sha FROM ingested_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if prev is not None and prev[0] == sha:
        return {"run_id": run_id, "already_applied": True, "counts": {}}

    counts: dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("PRAGMA defer_foreign_keys=ON")
    try:
        for table in _TABLE_ORDER:
            counts[table] = _upsert(conn, table, tables.get(table, []))

        # image_state_events : pas de clé naturelle → on remplace les events DE CE
        # RUN (scopés par run_id, n'impacte pas les events de review postérieurs) et
        # on ré-insère sans l'id AUTOINCREMENT.
        events = tables.get(_EVENTS, [])
        conn.execute("DELETE FROM image_state_events WHERE run_id=?", (run_id,))
        if events:
            cols = [c for c in events[0].keys() if c != "id"]
            ph = ",".join("?" * len(cols))
            conn.executemany(
                f"INSERT INTO image_state_events ({','.join(cols)}) VALUES ({ph})",
                [[e[c] for c in cols] for e in events],
            )
        counts[_EVENTS] = len(events)

        # Les events viennent d'être ré-insérés avec de nouveaux id autoinc :
        # recale image_state_current (FK last_event_id) sur les assets touchés.
        affected_assets = sorted({e["asset_id"] for e in events})
        if affected_assets:
            _rebuild_state_current(conn, affected_assets)

        conn.execute(
            "INSERT INTO ingested_runs (run_id, batch_sha, counts_json) "
            "VALUES (?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET "
            "batch_sha=excluded.batch_sha, counts_json=excluded.counts_json, "
            "applied_at=datetime('now')",
            (run_id, sha, json.dumps(counts)),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {"run_id": run_id, "already_applied": False, "counts": counts}
