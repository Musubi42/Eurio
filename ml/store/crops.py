"""Ingest de géométrie de recrop — write-half SQL-pure (Direction A, C2b).

Le calcul lourd (cv2 : détection/recrop du cercle, phash) tourne côté Mac/PC (le
VPS n'a pas de GPU) ; seules les COLONNES résultantes voyagent vers le canonique
via ``POST /ingest/crops``. Le binaire PNG est ré-uploadé sur la MÊME clé MinIO
(``storage_path`` inchangé) → un hint ``cache_invalidate`` dit aux répliques de
purger leur PNG périmé (v1 : purge manuelle au re-scan ; v1.1 : purge auto).

Miroir de la partie DB de ``serving/crop_edit.apply_manual_crop`` (lignes ~304-322),
sans cv2/MinIO. Contrat transactionnel identique à ``store.decisions`` : prend
``conn``, ne fait NI ``BEGIN`` NI ``COMMIT`` (le caller possède la transaction).

Idempotent : ré-appliquer une géométrie identique laisse la ligne identique. Les
asset_id inconnus sont collectés dans ``missing`` (tolérant, pas de 404 global)
→ un retry partiel réussit toujours.
"""
from __future__ import annotations

from datetime import datetime, timezone

from store.events import emit_field_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def apply_exclude_crops(conn, run_id: str, asset_ids) -> dict:
    """Exclut des crops du training (trop inclinés ou raison éditoriale) — miroir
    DB de l'ancien handler ``POST /bench/runs/{id}/crops/exclude``.

    Seuls ``training_eligible=0``, ``quality_reason='too_tilted'`` et
    ``resolved_at`` changent (réversible : ``training_eligible=1,
    quality_reason=NULL``). Garde d'appartenance canonique : les asset_ids qui
    n'appartiennent pas au run vont dans ``skipped`` (le serveur reste autoritaire
    même si la réplique cliente est en retard). Ni BEGIN ni COMMIT (le caller
    possède la transaction). Retourne ``{"excluded": n, "skipped": [asset_id…]}``.
    """
    run_asset_ids = {
        row[0]
        for row in conn.execute(
            "SELECT id FROM image_assets WHERE run_id = ?", (run_id,)
        ).fetchall()
    }
    to_update = [aid for aid in asset_ids if aid in run_asset_ids]
    skipped = [aid for aid in asset_ids if aid not in run_asset_ids]
    if to_update:
        now = _now_iso()
        conn.executemany(
            "UPDATE image_assets SET training_eligible = 0, "
            "quality_reason = 'too_tilted', resolved_at = ? WHERE id = ?",
            [(now, aid) for aid in to_update],
        )
    return {"excluded": len(to_update), "skipped": skipped}


def apply_ingest_crops(conn, crops) -> dict:
    """Applique une géométrie de recrop par asset.

    ``crops`` = itérable d'objets avec .asset_id/.bbox_json/.detection_method/
    .width/.height/.phash (opt)/.storage_status (opt) — duck-typé (pydantic OU
    dataclass). Retourne ``{"updated": n, "missing": [asset_id…]}``.
    """
    updated = 0
    missing: list = []
    for c in crops:
        row = conn.execute(
            "SELECT storage_path FROM image_assets WHERE id = ?", (c.asset_id,),
        ).fetchone()
        if row is None:
            missing.append(c.asset_id)
            continue
        conn.execute(
            "UPDATE image_assets SET bbox_json = ?, detection_method = ?, "
            "width = ?, height = ?, phash = COALESCE(?, phash), "
            "storage_status = COALESCE(?, storage_status) WHERE id = ?",
            (c.bbox_json, c.detection_method, c.width, c.height,
             c.phash, c.storage_status, c.asset_id),
        )
        fields = {
            "image_assets.bbox_json": c.bbox_json,
            "image_assets.detection_method": c.detection_method,
            "image_assets.width": c.width,
            "image_assets.height": c.height,
        }
        if c.phash is not None:
            fields["image_assets.phash"] = c.phash
        if c.storage_status is not None:
            fields["image_assets.storage_status"] = c.storage_status
        emit_field_event(
            conn, asset_id=c.asset_id, reason="recrop_ingest", actor="pipeline",
            fields=fields,
            detail={"cache_invalidate": row["storage_path"]},
        )
        updated += 1
    return {"updated": updated, "missing": missing}


def apply_delete_assets(conn, asset_ids) -> dict:
    """Supprime des rows ``image_assets`` du canonique (Direction A, delete
    propagé). Le ``ON DELETE CASCADE`` du schéma purge ``review_queue`` +
    prédictions Dino + ``image_state_events`` (la connexion Store a
    ``PRAGMA foreign_keys=ON``). SQL-pur : le binaire MinIO est supprimé par le
    client qui a initié le delete (``delete_asset_cascade``), pas ici.

    Même contrat transactionnel que ``apply_ingest_crops`` : ni BEGIN ni COMMIT
    (le caller possède la transaction). Idempotent : un asset_id déjà absent va
    dans ``missing`` (un retry après succès partiel réussit). Retourne
    ``{"deleted": n, "missing": [asset_id…]}``.
    """
    deleted = 0
    missing: list = []
    for asset_id in asset_ids:
        cur = conn.execute("DELETE FROM image_assets WHERE id = ?", (asset_id,))
        if cur.rowcount:
            deleted += 1
        else:
            missing.append(asset_id)
    return {"deleted": deleted, "missing": missing}
