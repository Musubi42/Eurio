"""Backfill C7 — détection de face (avers vs revers commun 2€) sur l'existant.

Calcule ``image_assets.face`` pour les crops 2€ encore NULL, via le détecteur
zéro-training (sim aux 2 ancres du revers commun vs banque avers ``2eur_all``,
seuil ``FACE_REVERSE_TAU``). Puis, pour les crops détectés ``reverse`` :
  - les REJETTE (rejet terminal ré-ouvrable, comme à l'enqueue) ;
  - recalcule ``source_images.route_reason`` des listings touchés → le bucket
    « revers commun 2€ » apparaît dans le funnel bench.

Réutilise STRICTEMENT les helpers existants (auto_validate + enqueue) — aucune
logique dupliquée. Idempotent :
  - ``face`` écrit seulement si NULL (ne clobbe pas les labels humains/Claude) ;
  - rejet seulement si le crop est encore ``needs_review`` ET non /restore humain ;
  - recompute route_reason déterministe.

Usage :
    .venv/bin/python -m scripts.backfill_face [--limit N] [--dry] [-v]
    .venv/bin/python -m scripts.backfill_face --reject   # SUR LE VPS

OÙ ÇA TOURNE, OÙ ÇA ÉCRIT — et pourquoi ce n'est pas le même endroit
--------------------------------------------------------------------
Deux phases aux besoins opposés, comme ``backfill_denom`` :

- **SCORE** (défaut) — compare l'embedding vitl14 du crop aux ancres du revers
  commun. Besoin de torch, de l'encodeur et des octets : ça tourne sur le Mac.
  Les verdicts partent au canonique par ``POST /ingest/faces``, sims d'audit
  (``reverse_sim``/``face_margin``) comprises.
- **REJET** (``--reject``) — du SQL pur : lit ``face='reverse'`` en base,
  rejette ce qui est encore ``needs_review``, re-route les listings. Aucun
  besoin d'images ni de modèle : **ça tourne sur le VPS**, seul writer.

Les imports lourds sont donc PARESSEUX. Les tirer en tête du module ferait
échouer ``--reject`` à l'import dans l'image lean, où torch est délibérément
absent (``infra/eurio-api/Dockerfile:7``) — le défaut d'architecture rencontré
trois fois le 2026-08-27.

L'ancien ``guard_vps_only`` est retiré : il existait parce qu'aucune voie ne
transportait ces écritures. La voie existe maintenant pour les deux moitiés, et
un garde qui protège d'un danger disparu se contourne par réflexe.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

# ⚠️ Imports LOURDS volontairement PARESSEUX (dans `_score_phase`) — cf. la
# docstring. `store/review_routing.py` et `shared/verdict_scope.py` sont
# stdlib-only : les importer ici ne réintroduit rien.
from store.review_routing import (  # noqa: E402
    kind_for_source_image as _kind_for_source_image,
    reject_crop_terminal as _reject_crop_terminal,
    route_decision_for_source_image as _route_decision_for_source_image,
)
from shared.verdict_scope import SUGGESTIONS_ANCHORS_KIND  # noqa: E402

#: ⚠️ PAS `from review.review_lanes import DEFAULT_LANE` : ce module tire
#: `training.foundation.auto_validate` en TRANSITIF, et l'image lean n'a pas
#: `training`. Mesuré en prod le 2026-08-27 — `--reject` mourait à l'import,
#: après un déploiement où tous les tests locaux passaient. Un contrôle
#: STATIQUE des imports DIRECTS ne voit pas ça ; seul un import réel, avec
#: `training` bloqué, l'attrape. Le test le fait, en sous-process.
DEFAULT_LANE = "manual"
from store import Store, resolve_db_path  # noqa: E402

#: Miroir de `sources._base.steps.enqueue._FACE_ENGINE_VERSION` — son module
#: d'origine tire `training`. Égalité verrouillée par les tests.
_FACE_ENGINE_VERSION = "face@v1"

# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la
# machine lit (`EURIO_DB_PATH` — la réplique sous Direction A, le canonique
# sur le VPS), jamais un chemin codé en dur. Mesuré le 2026-08-19 :
# `state/eurio.db` porte 6205 `image_assets` (5466 prédictions `2eur_all`)
# contre 12454 / 12454 dans `state/eurio.replica.db` — la banque `2eur_all`
# avait été bâtie dessus pendant des semaines.
# Repli hors devShell : `state/eurio.replica.db`. La règle et son arbitrage
# (2026-08-19) sont dans la docstring de `store.resolve_db_path`.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")
logger = logging.getLogger("backfill_face")


#: Taille des lots poussés au canonique.
_PUSH_BATCH = 500


@dataclass(frozen=True)
class _FaceRow:
    """Verdict duck-typé pour `apply_ingest_faces` (chemin `--no-push`)."""

    asset_id: str
    face: str
    reverse_sim: float | None
    face_margin: float | None
    anchors_kind: str


def _score_phase(store, *, limit, dry, push) -> int:
    """Calcule la face et l'envoie au canonique. Le lourd est tiré ICI."""
    import numpy as np  # noqa: PLC0415
    from shared.storage.local_cache import local_path  # noqa: PLC0415
    from sources._base.steps.auto_validate import (  # noqa: PLC0415
        _decide_face, _get_bank, _get_encoder_singleton, _get_reverse_bank,
    )
    from training.foundation import (  # noqa: PLC0415
        SUGGESTIONS_ENCODER_VERSION, encode_image,
    )

    conn = store._connection()  # noqa: SLF001
    rev_bank = _get_reverse_bank()
    all_bank = _get_bank(SUGGESTIONS_ANCHORS_KIND)
    if rev_bank is None or all_bank is None:
        sys.exit("Banque revers ou 2eur_all absente — go-task ml:dino-anchors:build "
                 "-- --kind reverse_2eur (et --kind 2eur_all)")
    enc, dev, tf = _get_encoder_singleton(SUGGESTIONS_ENCODER_VERSION)

    # Même élargissement que `backfill_denom` : le JOIN INNER sur
    # `target_eurio_id` excluait les crops sans cible, qui sont précisément
    # ceux que personne ne trie. Repli sur le premier candidat.
    sql = """
        SELECT a.id AS asset_id, a.source_image_id, a.storage_path,
               p.top1_sim AS all_top1_sim
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins c  ON c.eurio_id = s.target_eurio_id
          LEFT JOIN coins cc ON cc.eurio_id = json_extract(
                                    a.candidate_eurio_ids_json, '$[0].eurio_id')
     LEFT JOIN image_asset_dino_predictions p
            ON p.asset_id = a.id AND p.anchors_kind = ?
         WHERE a.face IS NULL
           AND a.storage_status = 'present'
           AND a.storage_path IS NOT NULL
           AND a.eval_corpus IS NULL
           AND (c.face_value = 2.0 OR cc.face_value = 2.0)
         ORDER BY a.fetched_at ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, (SUGGESTIONS_ANCHORS_KIND,)).fetchall()
    logger.info("backfill_face : %d crops face IS NULL à évaluer", len(rows))

    faces: list[tuple[str, str, float, float]] = []
    n_err = 0
    for i, r in enumerate(rows):
        try:
            vec = encode_image(local_path("enrichment-crops", r["storage_path"]),
                               encoder=enc, device=dev, transform=tf)
        except Exception as exc:  # noqa: BLE001
            logger.warning("encode failed asset=%s: %s", r["asset_id"], exc)
            n_err += 1
            continue
        rev_sim = float(np.max(rev_bank.matrix @ vec))
        obv_sim = r["all_top1_sim"]
        if obv_sim is None:  # pas de prédiction 2eur_all → recompute top1 ici
            obv_sim = float(np.max(all_bank.matrix @ vec))
        faces.append((r["asset_id"], _decide_face(rev_sim, obv_sim),
                      rev_sim, rev_sim - float(obv_sim)))
        if (i + 1) % 200 == 0:
            logger.info("  %d/%d encodés", i + 1, len(rows))

    n_reverse = sum(1 for _, f, _, _ in faces if f == "reverse")
    print(f"\nÉvalués : {len(faces)} (erreurs {n_err}) → "
          f"{n_reverse} reverse / {len(faces) - n_reverse} obverse")
    if dry:
        print("DRY — rien écrit.")
        return 0

    payload = [
        {"asset_id": aid, "face": f, "reverse_sim": rs, "face_margin": m,
         "anchors_kind": SUGGESTIONS_ANCHORS_KIND}
        for aid, f, rs, m in faces
    ]
    totals = {"updated": 0, "skipped": 0}
    missing: list[str] = []
    for i in range(0, len(payload), _PUSH_BATCH):
        lot = payload[i:i + _PUSH_BATCH]
        if push:
            from client.ingest import push_faces  # noqa: PLC0415

            res = push_faces(lot) or {}
        else:
            from store.faces import apply_ingest_faces  # noqa: PLC0415

            with store._writing() as wconn:  # noqa: SLF001
                res = apply_ingest_faces(wconn, [_FaceRow(**r) for r in lot])
        totals["updated"] += res.get("updated", 0)
        totals["skipped"] += res.get("skipped", 0)
        missing.extend(res.get("missing") or [])

    dest = "canonique (POST /ingest/faces)" if push else f"base locale {DB_PATH}"
    print(f"Écrit vers {dest} : {totals['updated']} faces posées, "
          f"{totals['skipped']} déjà tranchées (garde de provenance), "
          f"{len(missing)} asset_id inconnus")
    if missing:
        logger.warning("asset_id absents du canonique : %s%s",
                       ", ".join(missing[:5]),
                       f" (+{len(missing) - 5})" if len(missing) > 5 else "")
    print("(les revers ne sont pas encore sortis de la file — "
          "relancer avec --reject SUR LE VPS)")
    return 0


def _reject_phase(store, *, dry: bool) -> int:
    """Sort les revers de la file et re-route leurs listings. SQL PUR.

    Lit l'état de la base (``face='reverse'``), pas les verdicts d'un run :
    les deux phases sont des invocations séparées, sur deux machines
    différentes. Rejouable seul.
    """
    conn = store._connection()  # noqa: SLF001
    rows = conn.execute("""
        SELECT a.id AS asset_id, a.source_image_id
          FROM image_assets a
         WHERE a.face = 'reverse'
           AND a.resolution_status = 'needs_review'
    """).fetchall()
    print(f"Rejet : {len(rows)} revers encore needs_review")
    if dry:
        print("DRY — rien écrit.")
        return 0

    affected_sids: set[str] = set()
    n_rejected = 0
    with store._writing() as wconn:  # noqa: SLF001
        for r in rows:
            aid, sid = r["asset_id"], r["source_image_id"]
            rq = wconn.execute(
                "SELECT id, status, decision_notes FROM review_queue "
                "WHERE image_asset_id=?", (aid,),
            ).fetchone()
            if rq is not None and (rq["status"] != "open"
                                   or rq["decision_notes"] == "restored"):
                continue  # décidé ou ré-ouvert à la main → sticky
            if rq is None:
                review_id = uuid.uuid4().hex
                kind = _kind_for_source_image(
                    wconn, source_image_id=sid, is_lot_suspected=False)
                wconn.execute(
                    "INSERT INTO review_queue (id, image_asset_id, priority, "
                    "candidate_eurio_ids_json, kind, lane) VALUES (?, ?, ?, ?, ?, ?)",
                    (review_id, aid, 100, None, kind, DEFAULT_LANE),
                )
            else:
                review_id = rq["id"]
            _reject_crop_terminal(
                wconn, asset_id=aid, review_id=review_id,
                quality_reason="face_reverse", decided_by="pipeline",
                state_reason="face_reverse", engine_version=_FACE_ENGINE_VERSION,
                decision_payload={"reason": "face_reverse", "backfill": True},
                target_eurio_id=None, run_id=None,
            )
            affected_sids.add(sid)
            n_rejected += 1

        n_reroute = 0
        for sid in affected_sids:
            kind = _kind_for_source_image(wconn, source_image_id=sid,
                                          is_lot_suspected=False)
            decision, reason = _route_decision_for_source_image(
                wconn, source_image_id=sid, kind=kind, is_lot_suspected=False)
            wconn.execute(
                "UPDATE source_images SET route_decision=?, route_reason=? WHERE id=?",
                (decision, reason, sid),
            )
            n_reroute += 1

    print(f"Écrit : {n_rejected} revers rejetés · {n_reroute} listings re-routés")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reject", action="store_true",
                    help="sort les revers de la file + re-route (SQL pur, à "
                         "lancer SUR LE VPS)")
    ap.add_argument("--dry", action="store_true", help="Calcule + affiche, n'écrit rien.")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--no-push", action="store_true",
        help="écrit la base LOCALE au lieu de pousser au canonique "
             "(n'a de sens que SUR le host canonique)")
    args = ap.parse_args()

    from store import resolve_db_readonly  # noqa: PLC0415

    push = False
    if not args.dry and not args.reject:
        if args.no_push:
            if resolve_db_readonly():
                print("DB en lecture seule (réplique Direction A) et --no-push : "
                      "aucune destination. Retire --no-push pour pousser au "
                      "canonique.", file=sys.stderr)
                return 2
        else:
            from client.http import sync_enabled  # noqa: PLC0415

            if not sync_enabled():
                print("EURIO_API_URL absent : impossible de pousser au canonique. "
                      "Charge le devShell, ou ajoute --no-push pour écrire en local.",
                      file=sys.stderr)
                return 2
            push = True

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    for n in ("backfill_face", "training.foundation", "sources._base.steps.auto_validate"):
        logging.getLogger(n).setLevel(logging.INFO)

    store = Store(Path(args.db))
    if args.reject:
        return _reject_phase(store, dry=args.dry)
    return _score_phase(store, limit=args.limit, dry=args.dry, push=push)


if __name__ == "__main__":
    raise SystemExit(main())
