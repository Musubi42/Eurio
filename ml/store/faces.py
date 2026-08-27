"""Ingest de verdicts de face — write-half SQL-pure (Direction A, C3).

Le scan Dino (GPU, local) résout la face obverse/reverse des crops. Sous
Direction A, ``face`` est une colonne CANONIQUE lue depuis le VPS par le funnel
(cf. store/funnel.py) → les verdicts du scan local doivent REMONTER au VPS, sinon
split (le funnel lit une face que le scan a écrite ailleurs). Ce helper applique
les verdicts au canonique via ``POST /ingest/faces`` (miroir de store/crops.py).

Même garde que le scan, et il porte désormais sur la PROVENANCE et non sur la
présence (migration 0017) : une face posée par la MACHINE (``face_source`` NULL
ou ``'pipeline'``) se recalcule, un verdict HUMAIN (``'human'``) ne bouge pour
personne. L'ancienne règle ``face IS NULL OR face='unknown'`` protégeait bien
l'humain, mais gelait aussi la machine — or le seuil de face dérive avec la
taille de la banque des avers (cf. ``FACE_REVERSE_TAU``), donc une étiquette
machine fausse le restait à jamais. Commit-free (le caller possède la
transaction). Idempotent. asset_id inconnus → ``missing`` (tolérant).
"""
from __future__ import annotations

from store.events import emit_field_event


def apply_ingest_faces(conn, faces) -> dict:
    """Applique des verdicts de face.

    ``faces`` = itérable d'objets avec .asset_id / .face, et optionnellement
    .reverse_sim / .face_margin / .anchors_kind (duck-typé : pydantic OU
    dataclass). Retourne ``{"updated": n, "skipped": m, "missing": [asset_id…]}``
    (``skipped`` = verdict humain, épargné par le garde de provenance).

    ⚠️ Les sims d'AUDIT (``reverse_sim`` / ``face_margin``) s'écrivent **même
    quand le verdict est skippé**, et pour la même raison que
    ``denom_2eur_score`` dans ``store/denoms.py`` : savoir ce que le détecteur
    pense d'un crop déjà tranché par un humain est exactement ce qui permet de
    mesurer sa dérive. C'est cette dérive — 73,3 % → 40,0 % de rappel entre
    juin et août, à seuil inchangé — qui a été trouvée le 2026-08-27.
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
        rs = getattr(f, "reverse_sim", None)
        fm = getattr(f, "face_margin", None)
        if rs is not None or fm is not None:
            conn.execute(
                "UPDATE image_asset_dino_predictions SET reverse_sim = ?, "
                "face_margin = ? WHERE asset_id = ? AND anchors_kind = ?",
                (rs, fm, f.asset_id, getattr(f, "anchors_kind", "2eur_all")),
            )
        cur = conn.execute(
            "UPDATE image_assets SET face = ?, face_source = 'pipeline' "
            "WHERE id = ? AND (face_source IS NULL OR face_source = 'pipeline')",
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
