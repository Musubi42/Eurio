"""Ingest de verdicts de face — write-half SQL-pure (Direction A, C3).

Le scan Dino (GPU, local) résout la face obverse/reverse des crops. Sous
Direction A, ``face`` est une colonne CANONIQUE lue depuis le VPS par le funnel
(cf. store/funnel.py) → les verdicts du scan local doivent REMONTER au VPS, sinon
split (le funnel lit une face que le scan a écrite ailleurs). Ce helper applique
les verdicts au canonique via ``POST /ingest/faces`` (miroir de store/crops.py).

Même garde que le scan : n'écrit ``face`` que si elle est NULL ou ``'unknown'``
(jamais par-dessus un label humain/existant). Commit-free (le caller possède la
transaction). Idempotent. asset_id inconnus → ``missing`` (tolérant).
"""
from __future__ import annotations

from store.events import emit_field_event


def apply_ingest_faces(conn, faces) -> dict:
    """Applique des verdicts de face.

    ``faces`` = itérable d'objets avec .asset_id / .face (duck-typé : pydantic OU
    dataclass). Retourne ``{"updated": n, "skipped": m, "missing": [asset_id…]}``
    (``skipped`` = déjà labellisé, garde NULL/unknown).
    """
    updated = 0
    skipped = 0
    missing: list = []
    for f in faces:
        row = conn.execute(
            "SELECT face FROM image_assets WHERE id = ?", (f.asset_id,),
        ).fetchone()
        if row is None:
            missing.append(f.asset_id)
            continue
        cur = conn.execute(
            "UPDATE image_assets SET face = ? "
            "WHERE id = ? AND (face IS NULL OR face = 'unknown')",
            (f.face, f.asset_id),
        )
        if cur.rowcount:
            emit_field_event(
                conn, asset_id=f.asset_id, reason="face_ingest", actor="pipeline",
                fields={"image_assets.face": f.face},
            )
            updated += 1
        else:
            skipped += 1
    return {"updated": updated, "skipped": skipped, "missing": missing}
