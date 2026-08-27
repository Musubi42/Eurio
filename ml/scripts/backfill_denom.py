"""Backfill C7 pilier 2 — gate dénomination « 2€ vs junk » sur l'existant.

Calcule ``image_assets.denom`` (+ ``denom_2eur_score`` audit) pour les crops 2€
encore NULL dont la photo source est un **LOT** (même périmètre que le gate live
dans `auto_validate` : titre lot / listing_kind='lot' / >1 crops — la pollution
non-2€ vient des lots, HANDOFF-C7 §1), via la probe DINO (`vision/denom_probe.py`).

La restriction LOT est **mesurée, pas supposée** (réplique, 2026-08-27, sur les
9 092 crops tranchés hors ``auto_dino``) : ``quality_reason='not_2eur'`` vaut
**42,8 %** des crops de lot (1 659 / 3 877) contre **0,2 %** des singles
(8 / 5 215). Scorer les singles coûterait 5 200 encodages pour ~8 rejets.

⚠️ Le périmètre porte sur l'**annonce 2€**, pas sur la présence d'une cible —
cf. le commentaire long au-dessus de la requête de `_score_phase`. Un JOIN
INNER sur ``target_eurio_id`` y excluait 3 333 crops, ceux-là mêmes que la
porte doit trier.

**Audit d'abord (défaut)** : AUCUN re-routage — denom + score seulement, pour
inspection dans le funnel/bench. Le rejet terminal se déclenche avec ``--reject``
APRÈS validation PO ; il lit ``denom='not_2eur'`` en base (pas les verdicts du
run courant), donc les deux passes peuvent être des invocations séparées :
  - les ``not_2eur`` encore ``needs_review`` sont REJETÉS (ré-ouvrables, comme
    à l'enqueue) ;
  - ``source_images.route_reason`` est recalculé → bucket « not_2eur » funnel.

Réutilise STRICTEMENT les helpers existants (auto_validate + enqueue + denom_probe)
— aucune logique dupliquée. Idempotent :
  - ``denom`` écrit seulement si NULL (anti-clobber labels humains/Claude) ;
  - rejet seulement si le crop est encore ``needs_review`` ET non /restore humain.

Usage :
    python -m scripts.backfill_denom [--run PREFIX] [--limit N] [--dry] [-v]
    python -m scripts.backfill_denom --reject   # après validation PO

OÙ ÇA TOURNE, OÙ ÇA ÉCRIT — et pourquoi ce n'est pas le même endroit
--------------------------------------------------------------------
Ce script tourne **sur la machine qui a l'encodeur** (Mac/PC) : la probe est
une régression logistique sur l'embedding DINOv2 vitl14 gelé, elle a besoin de
torch et des octets du crop. Il **écrit le canonique**, au VPS, qui n'a ni
torch ni les images — ``infra/eurio-api/Dockerfile:7`` : *« torch /
ultralytics : DÉLIBÉRÉMENT ABSENTS »*.

Le transport est ``POST /ingest/denoms`` (cf. ``store/denoms.py``). Il
remplace l'ancien ``guard_vps_only``, qui refusait de tourner ici parce
qu'aucune voie ne transportait cette écriture — même mouvement que
``backfill_quality_score`` le 2026-08-25. ``--no-push`` écrit la base locale,
et n'a de sens que **sur** le host canonique.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

# ⚠️ Les imports LOURDS (torch, cv2, numpy via `training.foundation` et
# `vision.denom_probe`) sont volontairement PARESSEUX, dans `_score_phase`.
#
# Ce module a deux phases aux besoins opposés : le SCORE a besoin de l'encodeur
# et des images — donc du Mac ; le REJET est du SQL pur et n'a besoin que de la
# base — donc du VPS, seul writer. Les tirer en tête d'un module ferait échouer
# `--reject` À L'IMPORT dans l'image lean, où torch est délibérément absent
# (`infra/eurio-api/Dockerfile:7`). C'est le défaut d'architecture rencontré
# trois fois le 2026-08-27 : une logique que le seul writer ne peut pas
# importer est une logique inexécutable, et l'échec est muet.
#
# Les trois helpers de rejet/routage, eux, vivent dans `store/review_routing.py`
# (SQL pur, lean-importable) depuis le 2026-08-27, pour cette raison exacte.
from store.review_routing import (  # noqa: E402
    kind_for_source_image as _kind_for_source_image,
    reject_crop_terminal as _reject_crop_terminal,
    route_decision_for_source_image as _route_decision_for_source_image,
)
from store import Store, resolve_db_path  # noqa: E402
# `shared.verdict_scope` et `review.review_lanes` sont stdlib-only : les
# importer ici ne réintroduit aucune dep lourde. Le SEUL littéral recopié est
# `_DENOM_ENGINE_VERSION`, parce que son module d'origine
# (`sources._base.steps.enqueue`) tire `training` — l'égalité est verrouillée
# par `tests/test_ingest_denoms.py`.
from shared.verdict_scope import SUGGESTIONS_ANCHORS_KIND  # noqa: E402

#: ⚠️ PAS `from review.review_lanes import DEFAULT_LANE` : ce module tire
#: `training.foundation.auto_validate` en TRANSITIF, et l'image lean n'a pas
#: `training`. Mesuré en prod le 2026-08-27 — `--reject` mourait à l'import,
#: après un déploiement où tous les tests locaux passaient. Un contrôle
#: STATIQUE des imports DIRECTS ne voit pas ça ; seul un import réel, avec
#: `training` bloqué, l'attrape. Le test le fait, en sous-process.
DEFAULT_LANE = "manual"

#: Miroir de `sources._base.steps.enqueue._DENOM_ENGINE_VERSION`.
_DENOM_ENGINE_VERSION = "denom@v1"

# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la
# machine lit (`EURIO_DB_PATH` — la réplique sous Direction A, le canonique
# sur le VPS), jamais un chemin codé en dur. Mesuré le 2026-08-19 :
# `state/eurio.db` porte 6205 `image_assets` (5466 prédictions `2eur_all`)
# contre 12454 / 12454 dans `state/eurio.replica.db` — la banque `2eur_all`
# avait été bâtie dessus pendant des semaines.
# Repli hors devShell : `state/eurio.replica.db`. La règle et son arbitrage
# (2026-08-19) sont dans la docstring de `store.resolve_db_path`.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")

#: Taille des lots poussés au canonique — même valeur que `backfill_quality_score`.
_PUSH_BATCH = 500


@dataclass(frozen=True)
class _Row:
    """Ligne de verdict, duck-typée pour `apply_ingest_denoms` (qui accepte
    pydantic OU dataclass). N'existe que pour le chemin `--no-push` : côté
    réseau, c'est le modèle pydantic de la route qui valide."""

    asset_id: str
    denom: str
    denom_2eur_score: float | None
    anchors_kind: str


logger = logging.getLogger("backfill_denom")


def _score_phase(store, *, run_prefix: str | None, limit: int | None,
                 dry: bool, push: bool) -> int:
    """Phase audit : score + verdict denom sur les crops lot encore NULL.

    C'est ICI que le lourd est tiré — jamais au niveau module (cf. le
    commentaire des imports)."""
    import cv2  # noqa: PLC0415
    from shared.storage.local_cache import local_path  # noqa: PLC0415
    from sources._base.steps.auto_validate import (  # noqa: PLC0415
        _get_bank, _get_encoder_singleton, _is_lot_source,
    )
    from training.foundation import (  # noqa: PLC0415
        SUGGESTIONS_ENCODER_VERSION, encode_image,
    )
    from vision.denom_probe import decide_denom, denom_score  # noqa: PLC0415

    conn = store._connection()  # noqa: SLF001
    all_bank = _get_bank(SUGGESTIONS_ANCHORS_KIND)
    if all_bank is None:
        sys.exit("Banque 2eur_all absente — go-task ml:dino-anchors:build -- --kind 2eur_all")
    enc, dev, tf = _get_encoder_singleton(SUGGESTIONS_ENCODER_VERSION)

    # Le JOIN sur `s.target_eurio_id` était INNER : il excluait silencieusement
    # tout crop dont le scrape n'a pas résolu de cible — 3 333 crops au
    # 2026-08-27, dont 1 676 dans la file ouverte. Or ce sont EXACTEMENT ceux
    # que la porte doit voir : ils tombent en verdict `unknown` (règle 3 de
    # `auto_validate_view`), personne ne les trie, et 82 % viennent de photos
    # de lot — le périmètre même de la pollution non-2€.
    #
    # Le JOIN passe donc en LEFT, et le prédicat « c'est bien une annonce 2€ »
    # retombe sur le premier CANDIDAT quand la cible manque. Mesuré sur la
    # réplique : les 17 501 `source_images` eBay résolues pointent toutes une
    # pièce à `face_value = 2.0`, et 3 319 des 3 333 crops sans cible ont un
    # premier candidat 2€ (les 14 autres n'ont aucun candidat, et sortent).
    # Le scrape est 2€-only : élargir n'ouvre pas la porte à une autre valeur.
    #
    # `eval_corpus IS NULL` : un crop réservé au corpus d'éval vit dans le
    # bucket `eval-corpus`, pas `enrichment-crops` — `local_path` le refusait
    # une fois par run, en WARNING, et son message nommait déjà ce prédicat.
    sql = """
        SELECT a.id AS asset_id, a.source_image_id, a.storage_path,
               s.is_lot_suspected
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins c  ON c.eurio_id = s.target_eurio_id
          LEFT JOIN coins cc ON cc.eurio_id = json_extract(
                                    a.candidate_eurio_ids_json, '$[0].eurio_id')
         WHERE a.denom IS NULL
           AND a.storage_status = 'present'
           AND a.storage_path IS NOT NULL
           AND a.eval_corpus IS NULL
           AND (c.face_value = 2.0 OR cc.face_value = 2.0)
    """
    params: list = []
    if run_prefix:
        sql += " AND s.run_id LIKE ?"
        params.append(f"{run_prefix}%")
    sql += " ORDER BY a.fetched_at ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, params).fetchall()

    # Périmètre LOT uniquement — même garde que le gate live (auto_validate).
    lot_cache: dict[str, bool] = {}
    lot_rows = [
        r for r in rows
        if _is_lot_source(
            conn, source_image_id=r["source_image_id"],
            is_lot_suspected=r["is_lot_suspected"], cache=lot_cache,
        )
    ]
    logger.info(
        "backfill_denom : %d crops lot à scorer (%d denom IS NULL, %d single skip)",
        len(lot_rows), len(rows), len(rows) - len(lot_rows),
    )

    # ── Phase 1 : score denom (vec vitl14 + bimétal) ─────────────────────
    verdicts: list[tuple[str, str, float]] = []  # (asset_id, denom, score)
    n_err = 0
    for i, r in enumerate(lot_rows):
        try:
            p = local_path("enrichment-crops", r["storage_path"])
            vec = encode_image(p, encoder=enc, device=dev, transform=tf)
            bgr = cv2.imread(str(p))
            if bgr is None:
                raise ValueError("cv2.imread None")
        except Exception as exc:  # noqa: BLE001
            logger.warning("encode/read failed asset=%s: %s", r["asset_id"], exc)
            n_err += 1
            continue
        s = denom_score(vec, bgr)
        verdicts.append((r["asset_id"], decide_denom(s), float(s)))
        if (i + 1) % 200 == 0:
            logger.info("  %d/%d scorés", i + 1, len(lot_rows))

    n_junk = sum(1 for _, d, _ in verdicts if d == "not_2eur")
    print(f"\nÉvalués : {len(verdicts)} crops lot (erreurs {n_err}) → "
          f"{n_junk} not_2eur / {len(verdicts) - n_junk} 2eur")

    if dry:
        print("DRY — rien écrit.")
        return 0

    # ── Phase 2 : écritures AUDIT (denom + score) — pas de re-routage ────
    #
    # Sous Direction A, la destination n'est PAS la base que ce process lit.
    # La probe a besoin de torch + de l'encodeur vitl14 + des octets du crop ;
    # le VPS — seul writer — n'a aucun des trois (`Dockerfile:7` : « torch /
    # ultralytics : DÉLIBÉRÉMENT ABSENTS »). Le calcul reste donc ici et
    # seules les lignes voyagent, par `POST /ingest/denoms`.
    rows = [
        {"asset_id": aid, "denom": d, "denom_2eur_score": s,
         "anchors_kind": SUGGESTIONS_ANCHORS_KIND}
        for aid, d, s in verdicts
    ]
    totals = {"updated": 0, "skipped": 0}
    missing: list[str] = []
    for i in range(0, len(rows), _PUSH_BATCH):
        lot = rows[i:i + _PUSH_BATCH]
        if push:
            from client.ingest import push_denoms  # noqa: PLC0415

            res = push_denoms(lot) or {}
        else:
            from store.denoms import apply_ingest_denoms  # noqa: PLC0415

            with store._writing() as wconn:  # noqa: SLF001
                res = apply_ingest_denoms(wconn, [_Row(**r) for r in lot])
        totals["updated"] += res.get("updated", 0)
        totals["skipped"] += res.get("skipped", 0)
        # Un `missing` non lu, c'est une écriture qu'on croit faite.
        missing.extend(res.get("missing") or [])

    dest = "canonique (POST /ingest/denoms)" if push else f"base locale {DB_PATH}"
    print(f"Écrit vers {dest} : {totals['updated']} denom posés, "
          f"{totals['skipped']} déjà étiquetés (garde anti-clobber), "
          f"{len(missing)} asset_id inconnus")
    if missing:
        logger.warning("asset_id absents du canonique : %s%s",
                       ", ".join(missing[:5]),
                       f" (+{len(missing) - 5})" if len(missing) > 5 else "")
    return 0


def _reject_phase(store, *, run_prefix: str | None, dry: bool) -> int:
    """Phase rejet (post-validation PO) : rejette les ``denom='not_2eur'``
    encore ``needs_review`` et re-route les listings touchés. Lit l'état DB,
    pas les verdicts d'un run de scoring — rejouable indépendamment."""
    conn = store._connection()  # noqa: SLF001
    sql = """
        SELECT a.id AS asset_id, a.source_image_id, s.is_lot_suspected
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.denom = 'not_2eur'
           AND a.resolution_status = 'needs_review'
    """
    params: list = []
    if run_prefix:
        sql += " AND s.run_id LIKE ?"
        params.append(f"{run_prefix}%")
    rows = conn.execute(sql, params).fetchall()
    print(f"Rejet : {len(rows)} crops not_2eur encore needs_review")
    if dry:
        print("DRY — rien écrit.")
        return 0

    lot_suspected_by_sid = {r["source_image_id"]: bool(r["is_lot_suspected"])
                            for r in rows}
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
                    wconn, source_image_id=sid,
                    is_lot_suspected=lot_suspected_by_sid[sid])
                wconn.execute(
                    "INSERT INTO review_queue (id, image_asset_id, priority, "
                    "candidate_eurio_ids_json, kind, lane) VALUES (?, ?, ?, ?, ?, ?)",
                    (review_id, aid, 100, None, kind, DEFAULT_LANE),
                )
            else:
                review_id = rq["id"]
            _reject_crop_terminal(
                wconn, asset_id=aid, review_id=review_id,
                quality_reason="not_2eur", decided_by="pipeline",
                state_reason="not_2eur", engine_version=_DENOM_ENGINE_VERSION,
                decision_payload={"reason": "not_2eur", "backfill": True},
                target_eurio_id=None, run_id=None,
            )
            affected_sids.add(sid)
            n_rejected += 1

        n_reroute = 0
        for sid in affected_sids:
            is_lot = lot_suspected_by_sid[sid]
            kind = _kind_for_source_image(
                wconn, source_image_id=sid, is_lot_suspected=is_lot)
            decision, reason = _route_decision_for_source_image(
                wconn, source_image_id=sid, kind=kind, is_lot_suspected=is_lot)
            wconn.execute(
                "UPDATE source_images SET route_decision=?, route_reason=? WHERE id=?",
                (decision, reason, sid),
            )
            n_reroute += 1

    print(f"Écrit : {n_rejected} not_2eur rejetés (ré-ouvrables) · "
          f"{n_reroute} listings re-routés")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default=None, help="préfixe run_id (filtre source_images)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reject", action="store_true",
                    help="rejette les denom='not_2eur' + re-route les listings "
                         "(post-validation PO ; défaut = audit seul)")
    ap.add_argument("--dry", action="store_true", help="Calcule + affiche, n'écrit rien.")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--no-push", action="store_true",
        help="écrit la base LOCALE au lieu de pousser au canonique "
             "(n'a de sens que SUR le host canonique)")
    args = ap.parse_args()

    # ── Où atterrissent les lignes ──────────────────────────────────────────
    # Remplace l'ancien `guard_vps_only`. Le garde refusait de tourner ici
    # parce qu'AUCUNE voie ne transportait cette écriture ; `/ingest/denoms`
    # l'ouvre, et un garde qui protège d'un danger disparu est un garde
    # décoratif — la règle est posée dans `scripts/_vps_only_guard.py`.
    from store import resolve_db_readonly  # noqa: PLC0415

    push = False
    # `--reject` n'a AUCUNE destination à résoudre : il écrit la base qu'il
    # lit, sur le VPS. Le faire passer par la résolution de push le faisait
    # mourir en "EURIO_API_URL absent" sur le canonique — mesuré le 2026-08-27.
    if not args.dry and not args.reject:
        if args.no_push:
            if resolve_db_readonly():
                print(
                    "DB en lecture seule (réplique Direction A) et --no-push : "
                    "aucune destination. Retire --no-push pour pousser au "
                    "canonique, ou lance ceci sur le host canonique avec "
                    "EURIO_DB_READONLY=0.", file=sys.stderr)
                return 2
        else:
            from client.http import sync_enabled  # noqa: PLC0415

            if not sync_enabled():
                print(
                    "EURIO_API_URL absent : impossible de pousser au canonique. "
                    "Charge le devShell, ou ajoute --no-push pour écrire en local.",
                    file=sys.stderr)
                return 2
            push = True

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    logging.getLogger("backfill_denom").setLevel(logging.INFO)

    store = Store(Path(args.db))
    if args.reject:
        # Phase SQL pure : ni probe, ni encodeur, ni images. Elle doit pouvoir
        # tourner sur le VPS — donc ne toucher AUCUN import lourd.
        return _reject_phase(store, run_prefix=args.run, dry=args.dry)

    from vision.denom_probe import denom_threshold  # noqa: PLC0415

    if denom_threshold() is None:
        sys.exit("Probe denom absente — state/denom_probe.npz (scripts.train_denom_probe --save)")
    print(f"seuil denom = {denom_threshold():.4f}")
    rc = _score_phase(store, run_prefix=args.run, limit=args.limit,
                      dry=args.dry, push=push)
    if rc == 0 and not args.dry:
        print("(audit only — relancer avec --reject après validation PO pour "
              "rejeter les not_2eur et re-router les listings)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
