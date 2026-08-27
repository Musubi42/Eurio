"""Ingest de verdicts de dénomination — write-half SQL-pure (Direction A).

Pourquoi cette route existe, et pourquoi elle est le 4ᵉ cas du même patron.
--------------------------------------------------------------------------
La probe « 2€ vs junk » (``vision/denom_probe.py``) est une régression
logistique sur l'embedding DINOv2 vitl14 **gelé** ⊕ ``bimetal_score``. Elle a
donc besoin de torch, de l'encodeur, et des octets du crop.

Or ``infra/eurio-api/Dockerfile:7`` dit, en toutes lettres : *« torch /
ultralytics : DÉLIBÉRÉMENT ABSENTS »*. Le VPS est le SEUL writer du canonique
et il ne peut pas faire tourner la probe ; le Mac a l'encodeur et les images
mais lit une réplique read-only. Sans transport, ce calcul **n'a aucun endroit
où atterrir** — mot pour mot le constat qui a fait écrire ``/ingest/consensus``,
``/ingest/faces`` puis ``/ingest/quality-scores``.

C'est cette route qui remplace le ``guard_vps_only`` de
``scripts/backfill_denom.py``. Le garde existait parce qu'aucune voie ne
transportait cette écriture ; le laisser en place une fois la voie ouverte en
ferait un garde décoratif, protégeant d'un danger disparu — et l'on finit par
contourner par réflexe les gardes décoratifs. C'est la règle posée dans la
docstring de ``scripts/_vps_only_guard.py`` elle-même.

Le garde métier, lui, reste : ANTI-CLOBBER
------------------------------------------
``denom`` n'est écrit **que s'il est NULL**. La colonne porte aussi des labels
posés à la main ; un re-run de la probe ne doit jamais écraser un verdict
humain. C'est exactement la sémantique qu'avait déjà l'``UPDATE`` local
(``WHERE id=? AND denom IS NULL``), reprise ici sans changement pour que passer
par le réseau ne change pas la règle.

⚠️ ``denom_2eur_score``, lui, est de l'AUDIT et se réécrit librement : c'est la
sortie continue du modèle, pas un verdict. Le distinguer compte — c'est ce
score qui permettra demain de rebalayer un seuil sans re-encoder 2 222 crops.

Commit-free (le caller possède la transaction). Idempotent. ``asset_id``
inconnus → ``missing`` (tolérant, comme ``apply_ingest_faces``).
"""
from __future__ import annotations

from store.events import emit_field_event


def apply_ingest_denoms(conn, rows) -> dict:
    """Applique des verdicts de dénomination.

    ``rows`` = itérable d'objets avec ``.asset_id`` / ``.denom`` /
    ``.denom_2eur_score`` / ``.anchors_kind`` (duck-typé : pydantic OU
    dataclass). Retourne ``{"updated": n, "skipped": m, "missing": [asset_id…]}``
    — ``skipped`` = ``denom`` déjà posé (label humain ou run antérieur).

    Le score d'audit est écrit **même quand le verdict est skippé** : savoir ce
    que la probe pense d'un crop déjà étiqueté à la main est précisément ce qui
    permet de mesurer sa justesse.
    """
    updated = 0
    skipped = 0
    missing: list = []
    for r in rows:
        row = conn.execute(
            "SELECT denom FROM image_assets WHERE id = ?", (r.asset_id,),
        ).fetchone()
        if row is None:
            missing.append(r.asset_id)
            continue

        score = getattr(r, "denom_2eur_score", None)
        if score is not None:
            conn.execute(
                "UPDATE image_asset_dino_predictions SET denom_2eur_score = ? "
                "WHERE asset_id = ? AND anchors_kind = ?",
                (float(score), r.asset_id, r.anchors_kind),
            )

        cur = conn.execute(
            "UPDATE image_assets SET denom = ? WHERE id = ? AND denom IS NULL",
            (r.denom, r.asset_id),
        )
        if cur.rowcount:
            emit_field_event(
                conn, asset_id=r.asset_id, reason="denom_ingest", actor="pipeline",
                fields={"image_assets.denom": r.denom},
                detail={"denom_2eur_score": score} if score is not None else None,
            )
            updated += 1
        else:
            skipped += 1
    return {"updated": updated, "skipped": skipped, "missing": missing}
