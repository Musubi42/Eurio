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

from store.events import emit_field_event


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
