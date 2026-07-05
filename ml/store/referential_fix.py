"""Application canonique d'un fix référentiel (shape B) — write-half SQL-pure.

Direction A / décision D3 : la mutation `coins`/`coin_canonical_images` d'un
``POST /referential/fix-proposals/{id}/apply`` doit atteindre le writer canonique
VPS. Or le router `referential` est SKIPPÉ sur l'image lean (PIL absent) et
écrivait un ``ml/state/eurio.db`` local inexistant sur le VPS. Ce module porte la
partie **purement DB** (lean-safe : ``sqlite3`` + ``json``, aucun cv2/PIL/httpx),
appelée depuis la route always-mounted ``POST /ingest/referential-fix``.

Le CLIENT (image complète, a PIL + l'arbre canonical_images + les clés Numista)
calcule le diff sur la réplique — payloads, move FS des sidecars BCE, fetch image
Numista — puis POSTe le diff. Le SERVEUR re-vérifie le preflight (la réplique
cliente peut être en retard) et applique les 2 rows ``coins`` + les re-parents
``coin_canonical_images``. Miroir SQL exact de ``serving.referential_fix_apply``
(``_preflight`` / ``_mutate_db`` / ``_move_bce_sidecar`` / ``_step_fetch_numista``).

Contrat transactionnel : prend ``conn``, ne fait NI ``BEGIN`` NI ``COMMIT`` (le
caller possède la transaction). Idempotence naturelle par UPSERT-clé (``eurio_id``).
"""
from __future__ import annotations

import json


class ReferentialFixConflict(Exception):
    """Preflight divergent (état canonique ≠ proposition) → la route renvoie 409."""


def preflight_coins(
    conn, *, existing_eurio_id: str, current_numista_id: int,
    new_row_eurio_id: str, new_row_numista_id: int, swap_new_numista_id: int,
) -> None:
    """Vérifie que ``coins`` est dans un état compatible avec le fix.

    Lève ``ReferentialFixConflict`` sinon. Partagé client (fail-fast sur la
    réplique) ET serveur (autorité sur le canonique). Miroir de l'ancien
    ``serving.referential_fix_apply._preflight`` (checks coins uniquement).
    """
    row = conn.execute(
        "SELECT numista_id FROM coins WHERE eurio_id = ?", (existing_eurio_id,)
    ).fetchone()
    if row is None:
        raise ReferentialFixConflict(
            f"existing eurio_id={existing_eurio_id!r} not found in coins"
        )
    current = row[0]
    if current != current_numista_id:
        raise ReferentialFixConflict(
            f"{existing_eurio_id} has numista_id={current}, expected "
            f"{current_numista_id} (canonique divergé de la proposition)"
        )
    if conn.execute(
        "SELECT 1 FROM coins WHERE eurio_id = ?", (new_row_eurio_id,)
    ).fetchone():
        raise ReferentialFixConflict(
            f"target eurio_id={new_row_eurio_id!r} already exists"
        )
    for nid, expected_owner in (
        (swap_new_numista_id, existing_eurio_id),
        (new_row_numista_id, new_row_eurio_id),
    ):
        for (other,) in conn.execute(
            "SELECT eurio_id FROM coins WHERE numista_id = ?", (nid,)
        ).fetchall():
            if other != expected_owner and other != existing_eurio_id:
                raise ReferentialFixConflict(
                    f"numista_id={nid} already linked to {other!r}"
                )


_COINS_INSERT_SQL = """
    INSERT INTO coins (
        eurio_id, country, country_name, year, face_value,
        is_commemorative, theme, numista_id, raw_payload_json,
        ref_source, ref_native_id, currency, collector_only,
        design_description, status, needs_review, updated_at
    )
    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'numista', ?, 'EUR', 0, ?, 'referenced', 0, ?)
"""


def apply_referential_fix(conn, diff: dict) -> dict:
    """Applique le diff calculé client-side (shape B). Ni BEGIN ni COMMIT.

    ``diff`` = ``{preflight, coins_insert, coins_update, canonical_images}`` :
    - ``preflight`` : dict des attendus (voir ``preflight_coins``).
    - ``coins_insert`` : colonnes de la nouvelle row commémo (``raw_payload_json``
      déjà construit côté client). Colonnes fixes (is_commemorative=1,
      ref_source='numista', currency='EUR', collector_only=0, status='referenced',
      needs_review=0) posées ici.
    - ``coins_update`` : ``{eurio_id, numista_id, ref_native_id, raw_payload_json,
      updated_at}`` — le swap de la row existante.
    - ``canonical_images`` : liste d'ops ``{op:'reparent'|'upsert', ...}`` (les
      binaires sont déjà sur la clé partagée ; seules les rows DB voyagent).

    Retourne ``{applied, coins_inserted, coins_updated, canonical_rows}``. Lève
    ``ReferentialFixConflict`` (→ 409) si le preflight canonique diverge.
    """
    preflight_coins(conn, **diff["preflight"])

    ci = diff["coins_insert"]
    conn.execute(_COINS_INSERT_SQL, (
        ci["eurio_id"], ci["country"], ci["country_name"], ci["year"],
        ci["face_value"], ci.get("theme"), ci["numista_id"], ci["raw_payload_json"],
        ci["ref_native_id"], ci.get("design_description"), ci["updated_at"],
    ))

    cu = diff["coins_update"]
    conn.execute(
        "UPDATE coins SET numista_id = ?, ref_native_id = ?, raw_payload_json = ?, "
        "updated_at = ? WHERE eurio_id = ?",
        (cu["numista_id"], cu["ref_native_id"], cu["raw_payload_json"],
         cu["updated_at"], cu["eurio_id"]),
    )

    canonical_rows = 0
    for op in diff.get("canonical_images") or []:
        if op["op"] == "reparent":
            # DELETE défensif de la cible + re-parent de la row existante.
            conn.execute(
                "DELETE FROM coin_canonical_images WHERE eurio_id = ? AND source = ? AND role = ?",
                (op["to_eurio_id"], op["source"], op["role"]),
            )
            cur = conn.execute(
                "UPDATE coin_canonical_images SET eurio_id = ?, local_path = ?, url = NULL "
                "WHERE eurio_id = ? AND source = ? AND role = ?",
                (op["to_eurio_id"], op["local_path"], op["from_eurio_id"],
                 op["source"], op["role"]),
            )
            canonical_rows += cur.rowcount
        elif op["op"] == "upsert":
            conn.execute(
                "INSERT OR REPLACE INTO coin_canonical_images "
                "(eurio_id, source, role, url, local_path) VALUES (?, ?, ?, NULL, ?)",
                (op["eurio_id"], op["source"], op.get("role", "obverse"), op["local_path"]),
            )
            canonical_rows += 1
        else:
            raise ValueError(f"canonical_images op inconnu: {op.get('op')!r}")

    return {
        "applied": True,
        "coins_inserted": 1,
        "coins_updated": 1,
        "canonical_rows": canonical_rows,
    }
