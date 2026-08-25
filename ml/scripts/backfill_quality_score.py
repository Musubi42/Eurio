"""Calcule et pousse ``image_assets.quality_score`` (+ tilt) sur tout le parc.

Ce script était un **importeur de CSV figé** : il relisait
``state/crop_diag/results.csv`` (5 juin 2026) et écrivait le canonique par
``UPDATE`` brut. Deux conséquences, mesurées le 2026-08-25 sur la réplique :

    sqlite3 -readonly ml/state/eurio.replica.db \\
      "SELECT COUNT(*), SUM(quality_score IS NOT NULL) FROM image_assets;"
    -- 18730|1052      (5,6 % du parc)

    -- …et sur le pool éligible :
    -- WHERE training_eligible=1  →  2969|262|637   (8,8 % / tilt 21,5 %)

1. **la couverture était gelée** : toutes les lignes scorées sont antérieures au
   2026-06-03, et les 16 369 crops arrivés depuis n'ont jamais été touchés. La
   cause tenait en une constante — ``_MAX_SAMPLE = 2274`` en dur dans
   ``crop_quality_diag.py``, « tout le parc » au 5 juin ;
2. **il ne pouvait plus tourner nulle part** : son ``guard_vps_only`` refusait
   dès ``EURIO_DB_READONLY``/``EURIO_API_URL`` (donc toujours, sur Mac/PC), et
   le VPS — la seule machine que le garde autorisait — **n'a pas les 12 Go de
   raws** dont l'oracle a besoin.

Le geste que le dépôt a déjà fait deux fois pour ce problème exact (cf. les
docstrings de ``/ingest/consensus`` et ``/ingest/faces``) : **une route**. Le
calcul reste où sont les images, les LIGNES voyagent par ``POST
/ingest/quality-scores``. Le garde a donc été **retiré** : il existait parce
qu'aucune route ne transportait cette écriture ; le laisser en ferait un garde
décoratif protégeant d'un danger disparu — le motif exact de
``train_embedder.py:53``.

⚠️ **Limite de méthode — lire avant d'appeler cette colonne « qualité ».**
``quality_score`` mesure le **CADRAGE** : ``clamp(min(r, 2-r), 0, 1)`` où
``r = r_pipe / r_probe``, le rayon croppé rapporté au rim vrai trouvé par Otsu.
Ce n'est pas une mesure de qualité d'image, et ce n'est pas un détecteur d'erreur :

  - l'oracle **plafonne** — sur fond texturé Otsu n'isole pas le rim, ``r_ratio``
    reste ``None`` et **~35 % du parc restera NULL** = *non mesuré*, jamais
    *mauvais* (l'expert ``crop_quality`` s'abstient) ;
  - l'oracle est **AVEUGLE aux vraies pannes** — il re-probe autour du centre
    choisi par le pipeline, donc un crop sur le **mauvais objet** (capsule,
    coincard, tissu, pièce voisine, graphisme de numisbrief) est scoré « ok ».
    La vraie question (« est-ce seulement une pièce ? ») se lit avec le DINO
    ``top1_sim`` — cf. ``crop_quality_diag.py`` §oracle DINOv2.

Coût mesuré : ~0,025 s/crop de CPU, plus le téléchargement des raws absents du
cache (~78,6 % de hit sur le parc complet).

Usage ::

    python -m scripts.backfill_quality_score                 # dry-run (défaut)
    python -m scripts.backfill_quality_score --apply         # calcule et pousse
    python -m scripts.backfill_quality_score --scope eligible --apply
    python -m scripts.backfill_quality_score --from-csv --apply   # rejoue l'historique

``--from-csv`` relit le CSV figé pour **reproduire l'historique** ; ce n'est plus
le chemin nominal.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parent.parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from store import resolve_db_path  # noqa: E402

# Version du pipeline de score (oracle r_ratio v1 + tilt) — tracée pour
# invalidation. La bumper fait re-mesurer tout le parc au prochain passage ;
# l'anti-rétrogradation de ``store/quality.py`` empêche l'inverse.
QUALITY_PIPELINE_VERSION = 1

_DEFAULT_CSV = _ML_DIR / "state" / "crop_diag" / "results.csv"
_DEFAULT_DB = resolve_db_path(_ML_DIR / "state" / "eurio.replica.db")

#: Sélection : tout ce que le pipeline courant n'a pas encore examiné. Le
#: prédicat porte sur ``quality_pipeline_version``, PAS sur ``quality_score`` —
#: les crops que l'oracle ne sait pas mesurer gardent un score NULL et une
#: version posée, et ne doivent pas être re-téléchargés à chaque passage.
_SELECT = """
    SELECT a.id            AS asset_id,
           a.bbox_json     AS bbox_json,
           si.storage_path AS raw_path,
           si.source       AS source
      FROM image_assets a
      JOIN source_images si ON si.id = a.source_image_id
     WHERE a.storage_status = 'present'
       AND si.storage_status = 'present'
       AND (a.quality_pipeline_version IS NULL
            OR a.quality_pipeline_version < :version)
       {scope}
     ORDER BY si.storage_path, a.id
"""

_SCOPES = {
    # Décision du PO (2026-08-25) : le backfill porte sur TOUT LE PARC, pas
    # seulement sur le pool éligible à l'entraînement.
    "all": "",
    "eligible": "AND a.training_eligible = 1",
}


def quality_score_from_r_ratio(r_ratio: float) -> float:
    """closeness symétrique au rim vrai, clampée [0,1]. (Réexport : la
    définition vit avec l'oracle, dans ``crop_quality_diag``.)"""
    from scripts.crop_quality_diag import quality_score_from_r_ratio as _f

    return _f(r_ratio)


def _bucket(q: float) -> str:
    if q < 0.60:
        return "severe (<0.60)"
    if q < 0.85:
        return "penalised [0.60,0.85)"
    return "ok [0.85,1.0]"


def _open_ro(db: Path) -> sqlite3.Connection:
    """La sélection se fait en LECTURE SEULE, explicitement. Sous Direction A la
    base locale EST une réplique ; l'ouvrir en écriture ne produirait qu'une
    divergence que le prochain ``pull-replica`` effacerait."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_from_csv(csv_path: Path, version: int) -> list[dict]:
    """Payloads reconstruits depuis le CSV figé (reproduction de l'historique)."""
    out: list[dict] = []
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            raw = row.get("r_ratio")
            if not raw:
                continue
            out.append({
                "asset_id": row["asset_id"],
                "quality_pipeline_version": version,
                "quality_score": round(quality_score_from_r_ratio(float(raw)), 4),
            })
    return out


def _measure(rows, version: int, stats: Counter, *, verbose: bool = True):
    """**Générateur** de payloads : cède chaque mesure dès qu'elle est faite.

    Générateur et pas liste, délibérément : sur 17 678 crops la passe dure plus
    d'une heure, et tout accumuler en mémoire pour ne pousser qu'à la fin ferait
    d'une interruption (Ctrl-C, veille du Mac, coupure réseau) une perte TOTALE.
    En cédant au fil de l'eau, l'appelant pousse par lots et une interruption ne
    coûte que le lot en cours — les crops déjà écrits ressortent en ``skipped``
    au prochain passage.

    Un raw décodé sert à tous les crops de la même image source (la sélection est
    triée par ``storage_path``).
    """
    import cv2

    from scripts.crop_quality_diag import _raw_local_path, measure_crop_quality

    cache_key: str | None = None
    cache_img = None

    for i, r in enumerate(rows):
        if r["raw_path"] != cache_key:
            cache_key, cache_img = r["raw_path"], None
            try:
                p = _raw_local_path(r["raw_path"])
            except FileNotFoundError:
                stats["raw_absent_du_stockage"] += 1
                continue
            cache_img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if cache_img is None:
                stats["raw_illisible"] += 1
        if cache_img is None:
            stats["raw_indisponible"] += 1
            continue

        m = measure_crop_quality(cache_img, r["bbox_json"])
        payload = {"asset_id": r["asset_id"], "quality_pipeline_version": version}
        for k in ("quality_score", "tilt_deg", "axis_ratio", "tilt_trustworthy"):
            if m[k] is not None:
                payload[k] = m[k]
        stats["mesures"] += 1
        stats["score" if m["quality_score"] is not None else "oracle_muet"] += 1
        if m["quality_score"] is not None:
            stats[_bucket(m["quality_score"])] += 1
        if m["tilt_deg"] is not None:
            stats["tilt"] += 1
            stats["tilt_fiable"] += int(m["tilt_trustworthy"] or 0)
        if verbose and (i + 1) % 500 == 0:
            print(f"  … {i + 1}/{len(rows)} mesurés", flush=True)
        yield payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--scope", choices=sorted(_SCOPES), default="all")
    ap.add_argument("--apply", action="store_true", help="calcule ET pousse (défaut = dry-run)")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="explicite le défaut : n'écrit rien (ignoré si --apply)")
    ap.add_argument(
        "--limit", type=int, default=None,
        help="plafonne le nombre de crops traités (mise au point)")
    ap.add_argument(
        "--dry-run-sample", type=int, default=50,
        help="en dry-run, nombre de crops réellement mesurés pour montrer la "
             "distribution (0 = aucun calcul)")
    ap.add_argument("--batch", type=int, default=500, help="taille des lots poussés")
    ap.add_argument("--from-csv", dest="from_csv", action="store_true",
                    help="rejoue le CSV figé au lieu de mesurer (historique)")
    ap.add_argument("--csv", type=Path, default=_DEFAULT_CSV)
    ap.add_argument(
        "--no-push", action="store_true",
        help="écrit la base LOCALE au lieu de pousser au canonique "
             "(n'a de sens que SUR le host canonique)")
    args = ap.parse_args(argv)

    if args.dry_run and args.apply:
        print("--dry-run et --apply sont contradictoires.", file=sys.stderr)
        return 2

    # ── Où atterrissent les lignes ──────────────────────────────────────────
    from store import resolve_db_readonly

    push = False
    if args.apply:
        if args.no_push:
            if resolve_db_readonly():
                print(
                    "DB en lecture seule (réplique Direction A) et --no-push : "
                    "aucune destination. Retire --no-push pour pousser au "
                    "canonique, ou lance ceci sur le host canonique avec "
                    "EURIO_DB_READONLY=0.", file=sys.stderr)
                return 2
        else:
            from client.http import sync_enabled

            if not sync_enabled():
                print(
                    "EURIO_API_URL absent : impossible de pousser au canonique. "
                    "Charge le devShell, ou ajoute --no-push pour écrire en local.",
                    file=sys.stderr)
                return 2
            push = True

    stats: Counter = Counter()
    ro = _open_ro(args.db)
    rows: list = []
    depuis_csv: list[dict] = []
    if args.from_csv:
        connus = {r[0] for r in ro.execute("SELECT id FROM image_assets")}
        tous = _rows_from_csv(args.csv, QUALITY_PIPELINE_VERSION)
        depuis_csv = [p for p in tous if p["asset_id"] in connus]
        stats.update(mesures=len(depuis_csv), score=len(depuis_csv))
        for p_ in depuis_csv:
            stats[_bucket(p_["quality_score"])] += 1
        print(f"CSV figé : {args.csv} — {len(tous)} lignes, "
              f"{len(depuis_csv)} connues de la base")
    else:
        rows = ro.execute(
            _SELECT.format(scope=_SCOPES[args.scope]),
            {"version": QUALITY_PIPELINE_VERSION},
        ).fetchall()
        if args.limit:
            rows = rows[: args.limit]

    total_parc = ro.execute("SELECT COUNT(*) FROM image_assets").fetchone()[0]
    deja = ro.execute(
        "SELECT COUNT(*) FROM image_assets WHERE quality_score IS NOT NULL"
    ).fetchone()[0]
    ro.close()

    print(f"DB (lecture seule) : {args.db}")
    print(f"parc : {total_parc} crops, {deja} déjà scorés "
          f"({100 * deja / max(1, total_parc):.1f} %)")
    if not args.from_csv:
        print(f"scope={args.scope} · à examiner (pipeline v{QUALITY_PIPELINE_VERSION}) : "
              f"{len(rows)}")

    # ── Dry-run : on ne calcule qu'un échantillon, et on n'écrit rien ────────
    if not args.apply:
        if rows and args.dry_run_sample:
            ech = rows[: args.dry_run_sample]
            print(f"\nDRY-RUN — mesure d'un échantillon de {len(ech)} crops "
                  f"(--dry-run-sample) :")
            for _ in _measure(ech, QUALITY_PIPELINE_VERSION, stats, verbose=False):
                pass
            _print_stats(stats)
        print("\nDRY-RUN — rien écrit, rien poussé. Relancer avec --apply.")
        print(json.dumps({"updated": 0, "skipped": 0, "missing": 0,
                          "dry_run": True, "a_examiner": len(rows)}))
        return 0

    # ── Calcul ET écriture, EN FLUX ─────────────────────────────────────────
    #
    # Les deux sont entrelacés à dessein : mesurer 17 678 crops prend plus d'une
    # heure, et tout garder en mémoire pour ne pousser qu'à la fin ferait d'une
    # interruption une perte totale. Ici chaque lot part dès qu'il est plein.
    if args.from_csv:
        source = iter(depuis_csv)
        _print_stats(stats)
    else:
        print(f"\nmesure de {len(rows)} crops (~{0.025 * len(rows):.0f} s de CPU "
              "+ téléchargement des raws absents du cache), poussés par lots de "
              f"{args.batch}…")
        source = _measure(rows, QUALITY_PIPELINE_VERSION, stats)

    totaux = Counter()
    manquants: list[str] = []

    def _flush(lot: list[dict]) -> None:
        """Un ``missing`` non lu, c'est une écriture qu'on croit faite."""
        if not lot:
            return
        if push:
            from client.ingest import push_quality_scores

            res = push_quality_scores(lot) or {}
        else:
            from store import StoreBase
            from store.quality import apply_ingest_quality_scores

            conn = StoreBase(args.db, read_only=False)._connection()  # noqa: SLF001
            conn.execute("BEGIN")
            try:
                res = apply_ingest_quality_scores(conn, lot)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        totaux["updated"] += int(res.get("updated") or 0)
        totaux["skipped"] += int(res.get("skipped") or 0)
        manquants.extend(res.get("missing") or [])
        print(f"  … écrit {res.get('updated')}/{len(lot)} "
              f"(skipped={res.get('skipped')}, missing={len(res.get('missing') or [])})",
              flush=True)
        lot.clear()

    lot: list[dict] = []
    for payload in source:
        lot.append(payload)
        if len(lot) >= args.batch:
            _flush(lot)
    _flush(lot)

    if not args.from_csv:
        _print_stats(stats)
    dest = "canonique (POST /ingest/quality-scores)" if push else f"base locale {args.db}"
    print(f"\ndestination : {dest}")
    if manquants:
        print(f"⚠️  REFUSÉS (assets inconnus du canonique) : {len(manquants)} — "
              f"{manquants[:5]}{' …' if len(manquants) > 5 else ''}")
    print(json.dumps({
        "updated": totaux["updated"],
        "skipped": totaux["skipped"],
        "missing": len(manquants),
    }))
    return 0


def _print_stats(stats: Counter) -> None:
    if not stats.get("mesures"):
        return
    n = stats["mesures"]
    print(f"  mesurés          : {n}")
    print(f"  score obtenu     : {stats['score']} ({100 * stats['score'] / n:.1f} %) "
          f"— oracle muet : {stats['oracle_muet']} "
          f"({100 * stats['oracle_muet'] / n:.1f} %, NULL = NON MESURÉ)")
    if stats.get("tilt"):
        print(f"  tilt mesuré      : {stats['tilt']} "
              f"(fiable : {stats['tilt_fiable']})")
    if stats.get("raw_absent_du_stockage") or stats.get("raw_illisible"):
        print(f"  raws indisponibles : absents={stats['raw_absent_du_stockage']} "
              f"illisibles={stats['raw_illisible']}")
    total_scores = max(1, stats["score"])
    for k in ("ok [0.85,1.0]", "penalised [0.60,0.85)", "severe (<0.60)"):
        c = stats.get(k, 0)
        print(f"    {k:24} {c:5} ({100 * c / total_scores:.1f} %)")


if __name__ == "__main__":
    raise SystemExit(main())
