"""Ingest des mesures de cadrage de crop — write-half SQL-pure (Direction A).

Pourquoi cette route/ce helper existent : l'oracle de qualité (Otsu
``_probe_true_rim`` + ``measure_tilt``) a besoin des **raws en cache local**
(~12 Go côté Mac). Le VPS, lui, est le seul writer canonique — mais il n'a pas
les images. Le Mac a le moteur et les images, et lit une **réplique read-only**.
Sans transport, ce calcul n'a littéralement **aucun endroit où atterrir** :
c'est exactement le constat qui a fait écrire ``/ingest/consensus`` (2026-08-24)
puis ``/ingest/faces``. Le calcul reste où sont les images, les **lignes**
voyagent.

⚠️ **Ce que « quality » veut dire ici, et ce qu'il ne dit pas.**
``quality_score`` mesure le **CADRAGE** — la distance du rayon croppé au rim
vrai — pas la qualité de l'image ni la justesse du crop. L'oracle Otsu re-probe
**autour du centre choisi par le pipeline** : un crop pris sur le **mauvais
objet** (capsule, coincard, tissu, pièce voisine, graphisme de numisbrief) est
scoré « ok ». Il **plafonne** aussi : sur fond texturé Otsu n'isole pas le rim,
``r_ratio`` reste ``None`` et ~35 % du parc reste NULL = *non mesuré*, jamais
*mauvais*. La vraie question (« est-ce seulement une pièce ? ») se lit avec le
DINO ``top1_sim`` (cf. ``scripts/crop_quality_diag.py`` §oracle DINOv2).

Deux gardes, et elles sont le cœur du contrat :

1. **Jamais de rétrogradation.** Une ligne déjà écrite par un
   ``quality_pipeline_version`` supérieur ou égal n'est pas retouchée
   (``skipped``). C'est ce qui rend le backfill relançable sans détruire une
   mesure plus récente — et idempotent : rejouer la même version ne change rien.
2. **``quality_reason`` n'est JAMAIS touchée.** Elle porte des labels
   **humains** et des états de review (``rejected_in_review``,
   ``vision_standard_gate``, ``too_tilted`` venu du banc). Un oracle
   géométrique n'a pas qualité à les écraser.

SQL pur (aucun import de ``cv2``/``numpy``/``training`` : l'image lean du VPS ne
les a pas, et un routeur qui les importe est skippé au boot, en silence).
Commit-free : le caller possède la transaction. Idempotent. ``asset_id`` inconnu
→ ``missing`` (tolérant, jamais écrit).
"""
from __future__ import annotations

from store.events import emit_field_event

#: Colonnes écrites par ce helper. ``quality_reason`` en est ABSENTE, et c'est
#: délibéré (cf. garde 2 du module) : c'est la colonne des labels humains.
_MEASURE_COLUMNS = ("quality_score", "tilt_deg", "axis_ratio", "tilt_trustworthy")


def apply_ingest_quality_scores(conn, scores) -> dict:
    """Applique des mesures de cadrage à ``image_assets``.

    ``scores`` = itérable de dicts ``{asset_id, quality_pipeline_version,
    quality_score?, tilt_deg?, axis_ratio?, tilt_trustworthy?}``. Les champs de
    mesure absents ou ``None`` ne sont **pas** écrits (pas de NULL par-dessus une
    mesure existante) ; ``quality_pipeline_version``, lui, est toujours posé.

    Poser la version même quand l'oracle est muet est **voulu** : elle signifie
    « ce crop A ÉTÉ examiné par le pipeline vN », pas « il a un score ». Sans ça,
    les ~35 % que l'oracle ne sait pas mesurer seraient re-téléchargés et
    re-calculés à chaque passage, pour aboutir au même NULL.

    Retourne ``{"updated": n, "skipped": m, "missing": [asset_id…]}``.
    """
    updated = 0
    skipped = 0
    missing: list = []
    for s in scores:
        asset_id = s["asset_id"]
        version = int(s["quality_pipeline_version"])

        row = conn.execute(
            "SELECT quality_pipeline_version FROM image_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            missing.append(asset_id)
            continue

        existante = row[0] if not hasattr(row, "keys") else row["quality_pipeline_version"]
        if existante is not None and int(existante) >= version:
            # Anti-rétrogradation : une mesure d'une version >= fait autorité.
            skipped += 1
            continue

        mesures = {c: s.get(c) for c in _MEASURE_COLUMNS if s.get(c) is not None}
        colonnes = [*mesures, "quality_pipeline_version"]
        valeurs = [*mesures.values(), version]
        conn.execute(
            f"UPDATE image_assets SET {', '.join(f'{c} = ?' for c in colonnes)} "  # noqa: S608
            "WHERE id = ?",
            (*valeurs, asset_id),
        )
        emit_field_event(
            conn, asset_id=asset_id, reason="quality_ingest", actor="pipeline",
            fields={f"image_assets.{c}": v for c, v in zip(colonnes, valeurs)},
        )
        updated += 1
    return {"updated": updated, "skipped": skipped, "missing": missing}
