"""Tirage du jeu d'or — 60 images, 4 strates, et la réserve pour les indécidables.

La requête est celle de `docs/work-in-progress/juge-du-crop/JEU-D-OR.md`, à la
lettre. Elle est **reproductible à l'octet** : la clé de tirage est
`substr(si.sha256 || ia.id, -8)`, il n'y a pas de `random()`. Rejouer ce script
sur la même réplique rend le même tirage.

Trois pièges y sont déjà désarmés, cf. JEU-D-OR.md :

* `image_assets.sha256` est NULL sur les 20 375 lignes — la clé passe par
  `source_images.sha256` ;
* 4 678 des 6 299 rejets portent `face_reverse` / `not_2eur` et **ne disent rien
  du cadrage** — les inclure apprendrait à détecter des revers ;
* `tilt_deg` est tronqué à 14,07° par construction — la strate « de face »
  s'écrit `axis_ratio >= 0,97`, jamais `tilt_deg`.

Sortie : `<out>/manifest.json` + `<out>/raws/<asset_id>.<ext>`. Le manifeste
porte, par image, le crop actuel (`hint`) et la pré-proposition d'ellipse de
`measure_tilt` — **le PO corrige une proposition, il ne part pas d'une page
blanche.**

    python -m bench.gold_crop.sample --out state/gold_crop/v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[2]

# Nombre de lignes par (strate, verdict). Le 8/7 n'est pas cosmétique : c'est ce
# qui permet d'exécuter RE-4 — vérifier que le juge prédit le verdict humain au
# lieu de se contenter d'être géométriquement cohérent.
N_ACCEPT, N_REJECT = 8, 7
# Réserve, pour remplacer un cas déclaré « indécidable » sans retirer le tirage.
# ⚠️ JEU-D-OR.md annonce « 8 images par strate » mais détaille `rn` 9-11 / 8-10,
# soit 6. On suit le détail, qui est le plus précis des deux.
N_ACCEPT_RESERVE, N_REJECT_RESERVE = 11, 10

REQUETE = """
WITH base AS (
  SELECT
    ia.id AS asset_id, si.id AS source_image_id, si.source, si.storage_path AS raw_path,
    si.width, si.height, ia.bbox_json,
    ia.tilt_deg, ia.axis_ratio, ia.tilt_trustworthy,
    si.n_crops_detected, si.is_lot_suspected,
    CASE WHEN ia.resolution_status='manual' THEN 'accept' ELSE 'reject' END AS verdict,
    ia.quality_reason,
    MAX(COALESCE(lts.is_lot,0))         AS is_lot,
    MAX(COALESCE(lts.listing_kind,'?')) AS listing_kind,
    MAX(CASE WHEN lts.rejected_markers_json LIKE '%proof%' THEN 1 ELSE 0 END) AS mk_proof,
    MAX(CASE WHEN lower(COALESCE(si.listing_title,'')) LIKE '%blister%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%capsule%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%proof%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%belle epreuve%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%pcgs%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%ngc%'
             THEN 1 ELSE 0 END)         AS mk_capsule,
    substr(si.sha256 || ia.id, -8)      AS draw_key
  FROM image_assets ia
  JOIN source_images si              ON si.id = ia.source_image_id
  LEFT JOIN listing_text_signals lts ON lts.source_image_id = si.id
  WHERE ia.resolution_status IN ('manual','rejected')
    AND si.storage_status = 'present'
    AND si.storage_path IS NOT NULL
    AND si.sha256       IS NOT NULL
    AND ia.bbox_json    IS NOT NULL
    -- un rejet « mauvaise face / mauvaise pièce » ne dit RIEN du crop
    AND (ia.resolution_status = 'manual'
         OR COALESCE(ia.quality_reason,'') NOT IN ('face_reverse','not_2eur'))
  GROUP BY ia.id
),
strat AS (
  SELECT base.*,
    CASE
      WHEN n_crops_detected >= 2 OR is_lot = 1 OR is_lot_suspected = 1
           OR listing_kind IN ('lot','coffret')      THEN 'S3_multi'
      WHEN tilt_trustworthy = 1 AND tilt_deg >= 20.0 THEN 'S4_oblique'
      WHEN mk_capsule = 1 OR mk_proof = 1            THEN 'S2_capsule'
      -- « quasi de face » : axis_ratio, JAMAIS tilt_deg (tronqué à 14,07°)
      WHEN n_crops_detected = 1 AND axis_ratio >= 0.97
           AND listing_kind = 'single'               THEN 'S1_facile'
      ELSE 'S0_hors_strate'
    END AS strate
  FROM base
),
ranked AS (
  SELECT strat.*,
         ROW_NUMBER() OVER (PARTITION BY strate, verdict
                            ORDER BY draw_key, asset_id) AS rn
  FROM strat WHERE strate <> 'S0_hors_strate'
)
SELECT strate, verdict, rn, asset_id, source_image_id, source, raw_path,
       width, height, bbox_json,
       ROUND(tilt_deg,1) AS tilt_deg, ROUND(axis_ratio,3) AS axis_ratio,
       n_crops_detected, listing_kind, quality_reason
FROM ranked
WHERE (verdict='accept' AND rn <= :n_accept) OR (verdict='reject' AND rn <= :n_reject)
ORDER BY strate, verdict, rn
"""


def hint_depuis_bbox(bbox_json: str) -> dict | None:
    """Le crop actuel, en cercle `{cx, cy, r}` — l'éditeur n'écrit que des carrés."""
    try:
        b = json.loads(bbox_json)
        x, y, w, h = float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"cx": x + w / 2.0, "cy": y + h / 2.0, "r": max(w, h) / 2.0}


def tirer(db: Path, avec_reserve: bool = True) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        params = {"n_accept": N_ACCEPT_RESERVE if avec_reserve else N_ACCEPT,
                  "n_reject": N_REJECT_RESERVE if avec_reserve else N_REJECT}
        rows = [dict(r) for r in con.execute(REQUETE, params)]
    finally:
        con.close()
    for r in rows:
        r["role"] = ("tirage" if (r["verdict"] == "accept" and r["rn"] <= N_ACCEPT)
                     or (r["verdict"] == "reject" and r["rn"] <= N_REJECT) else "reserve")
        r["hint"] = hint_depuis_bbox(r["bbox_json"])
    return rows


def prefill_ellipse(raw_path_local: Path, hint: dict | None) -> dict | None:
    """Pré-proposition `measure_tilt`. Import paresseux : cv2 n'est pas gratuit."""
    if hint is None:
        return None
    import cv2

    from vision.crop_detectors import measure_tilt

    img = cv2.imread(str(raw_path_local), cv2.IMREAD_COLOR)
    if img is None:
        return None
    m = measure_tilt(img, hint)
    if not m.get("ok"):
        return {"ok": False, "reason": m.get("reason")}
    return {"ok": True, "cx": m["cx"], "cy": m["cy"], "major": m["major"],
            "minor": m["minor"], "angle": m["angle"],
            "axis_ratio": m["axis_ratio"], "trustworthy": m["trustworthy"],
            "reason": m["reason"]}


def main(argv=None) -> int:
    from store import resolve_db_path

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ML_DIR / "state" / "gold_crop" / "v1"))
    ap.add_argument("--db", default=None, help="défaut : la réplique read-only")
    ap.add_argument("--sans-reserve", action="store_true")
    ap.add_argument("--sans-raws", action="store_true",
                    help="manifeste seul, ne copie pas les images")
    a = ap.parse_args(argv)

    db = Path(a.db) if a.db else resolve_db_path(ML_DIR / "state" / "eurio.replica.db")
    out = Path(a.out)
    (out / "raws").mkdir(parents=True, exist_ok=True)

    rows = tirer(db, avec_reserve=not a.sans_reserve)
    tirage = [r for r in rows if r["role"] == "tirage"]
    print(f"réplique : {db}")
    print(f"tirage : {len(tirage)} lignes  ·  réserve : {len(rows) - len(tirage)}")
    for s in sorted({r["strate"] for r in rows}):
        a_, r_ = (sum(1 for x in tirage if x["strate"] == s and x["verdict"] == v)
                  for v in ("accept", "reject"))
        print(f"   {s:12s} {a_} acceptés / {r_} rejetés")

    manquants = []
    if not a.sans_raws:
        from shared.storage.local_cache import local_path
        for r in rows:
            try:
                src = local_path("enrichment-raws", r["raw_path"])
            except Exception as exc:                       # noqa: BLE001
                manquants.append((r["asset_id"], str(exc)))
                r["fichier"] = None
                continue
            dst = out / "raws" / f'{r["asset_id"]}{src.suffix or ".jpg"}'
            if not dst.exists():
                shutil.copy2(src, dst)
            r["fichier"] = f'raws/{dst.name}'
            r["prefill"] = prefill_ellipse(dst, r["hint"])

    manifeste = {
        "version": "v1",
        "db": str(db),
        "requete_sha256": hashlib.sha256(REQUETE.encode()).hexdigest(),
        "n_tirage": len(tirage),
        "n_reserve": len(rows) - len(tirage),
        "images": rows,
    }
    (out / "manifest.json").write_text(json.dumps(manifeste, indent=1, ensure_ascii=False))
    print(f"manifeste → {out / 'manifest.json'}   (sha256 requête {manifeste['requete_sha256'][:12]}…)")
    if manquants:
        print(f"⚠️  {len(manquants)} raws introuvables :")
        for aid, exc in manquants[:5]:
            print(f"   {aid} — {exc}")
    prefills = [r for r in rows if (r.get("prefill") or {}).get("ok")]
    if not a.sans_raws:
        print(f"pré-proposition d'ellipse : {len(prefills)} / {len(rows)}")
    return 1 if manquants else 0


if __name__ == "__main__":
    raise SystemExit(main())
