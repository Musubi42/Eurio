"""Bench bimétal — chemin DEVICE (parité retrain) sur les 17 pièces cohort.

Complément de `bench_listing_bimetal.py` (qui couvre le chemin *listing* eBay).
Celui-ci cible le chemin **device** (`normalize_device`, mirroré bit-pour-bit
par `SnapNormalizer.kt`) — le seul qui touche directement la boucle de retrain
ArcFace, car les 17 pièces cohort sont **toutes des 2 € commémo = bimétal**.

Voir `docs/operations/crop-bimetal-harden-session.md` (Phase 1) et
`docs/operations/crop-bimetal-undercrop.md` pour le contexte.

Deux mesures indépendantes, read-only (pas d'écriture DB/MinIO/modèle) :

  Part A — distribution d'inférence (le chiffre qui compte pour le retrain).
    Sur les vraies captures device (`<pull>/eval_real/<class>/<step>_raw.jpg`),
    on lance `normalize_device` puis on flagge l'undercrop avec l'oracle Otsu
    indépendant `_probe_true_rim` (réutilisé du bench listing). ratio =
    r_device / r_oracle < 0.85 ⇒ undercrop.

  Part B — isolation du guard (apples-to-apples, identique-pixels).
    Sur le MÊME raw Numista (`ml/datasets/<numista_id>/obverse.jpg`), on lance
    `normalize_studio` (chemin training, guardé par fill_ratio) ET
    `normalize_device` (chemin mobile, non guardé). Sur les studio shots
    fond-blanc, le contour Otsu verrouille le rim externe de façon fiable ;
    là où le Hough device choisit un rayon plus petit, c'est exactement le
    misfire anneau-interne. Quantifie la dérive train↔inference sans oracle.

Sortie : `ml/state/device_bimetal_bench/`
  - `A_<class>__<step>.jpg`  — overlay raw + cercle device + cercle oracle + crop
  - `B_<numista>.jpg`        — overlay raw : cercle studio (vert) vs device (rouge)
  - `summary.md`             — tables récap + métriques agrégées

Usage :
    cd ml
    .venv/bin/python -m scripts.bench_device_bimetal \\
        --device-pull ../debug_pull/eval_real/20260529_162919 \\
        --cohort-csv state/cohort_csvs/mix-zone-17.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from vision.normalize_snap import (  # noqa: E402
    normalize_device,
    normalize_studio,
)
from scripts.bench_listing_bimetal import _probe_true_rim, _slugify  # noqa: E402

_OUT = _ML_DIR / "state" / "device_bimetal_bench"
_DATASETS = _ML_DIR / "datasets"
_BG = (24, 24, 24)
_OVERLAY_MAX_DIM = 700
_CROP_DISPLAY = 224
_UNDERCROP_TOLERANCE = 0.85  # même seuil que le bench listing


# ---------------------------------------------------------------------------
# Helpers d'overlay
# ---------------------------------------------------------------------------

def _label(text: str, w: int, h: int = 24) -> np.ndarray:
    strip = np.full((h, w, 3), _BG, dtype=np.uint8)
    cv2.putText(strip, text, (6, h - 7), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255, 255, 255), 1)
    return strip


def _downscale(img: np.ndarray, max_dim: int = _OVERLAY_MAX_DIM) -> np.ndarray:
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side <= max_dim:
        return img
    s = max_dim / long_side
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def _pad_to(img: np.ndarray, target_w: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w >= target_w:
        return img
    pad = np.full((h, target_w - w, 3), _BG, dtype=np.uint8)
    return np.concatenate([img, pad], axis=1)


def _stack(*rows: np.ndarray) -> np.ndarray:
    target_w = max(r.shape[1] for r in rows)
    return np.concatenate([_pad_to(r, target_w) for r in rows], axis=0)


def _crop_or_placeholder(img: np.ndarray | None, text: str) -> np.ndarray:
    if img is not None:
        return cv2.resize(img, (_CROP_DISPLAY, _CROP_DISPLAY),
                          interpolation=cv2.INTER_AREA)
    ph = np.full((_CROP_DISPLAY, _CROP_DISPLAY, 3), 40, dtype=np.uint8)
    cv2.putText(ph, text, (12, _CROP_DISPLAY // 2), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255, 255, 255), 1)
    return ph


# ---------------------------------------------------------------------------
# Part A — distribution d'inférence (captures device + oracle Otsu)
# ---------------------------------------------------------------------------

def _run_part_a(eval_real_dir: Path) -> list[dict]:
    rows: list[dict] = []
    classes = sorted(d for d in eval_real_dir.iterdir() if d.is_dir())
    for cls_dir in classes:
        cls = cls_dir.name
        for raw_path in sorted(cls_dir.glob("*_raw.jpg")):
            step = raw_path.name[: -len("_raw.jpg")]
            bgr = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
            if bgr is None:
                rows.append({"cls": cls, "step": step, "error": "unreadable"})
                continue
            res = normalize_device(bgr)
            if res.image is None:
                rows.append({"cls": cls, "step": step,
                             "error": res.debug.get("error", "no circle")})
                continue
            true_r = _probe_true_rim(bgr, res.cx, res.cy, res.r)
            if true_r is not None:
                ratio = res.r / true_r
                suspect = ratio < _UNDERCROP_TOLERANCE
            else:
                ratio = None
                suspect = False

            # Overlay : raw avec cercle device + cercle oracle, + crop 224.
            over = bgr.copy()
            dev_color = (0, 0, 220) if suspect else (0, 220, 0)
            cv2.circle(over, (res.cx, res.cy), res.r, dev_color, 3)
            cv2.circle(over, (res.cx, res.cy), 4, dev_color, -1)
            if true_r is not None:
                cv2.circle(over, (res.cx, res.cy), int(round(true_r)),
                           (0, 220, 220), 2)  # oracle = jaune
            over = _downscale(over)
            ovw = over.shape[1]
            crop = _crop_or_placeholder(res.image, "no crop")
            ratio_txt = f"{ratio:.2f}" if ratio is not None else "probe=n/a"
            flag = " ⚠ UNDERCROP" if suspect else ""
            header = f"A · {cls} · {step}"
            footer = (f"r_dev={res.r} r_oracle="
                      f"{int(true_r) if true_r else 'n/a'} "
                      f"ratio={ratio_txt}{flag} method={res.method}")
            crop_row = np.concatenate(
                [_label("DEVICE crop 224", _CROP_DISPLAY), crop], axis=0)
            composed = _stack(
                _label(header, max(ovw, _CROP_DISPLAY), 26),
                over,
                crop_row,
                _label(footer, max(ovw, _CROP_DISPLAY), 22),
            )
            out_name = f"A_{_slugify(cls, 40)}__{_slugify(step, 24)}.jpg"
            cv2.imwrite(str(_OUT / out_name), composed,
                        [cv2.IMWRITE_JPEG_QUALITY, 86])
            rows.append({
                "cls": cls, "step": step, "r_dev": res.r,
                "true_r": int(true_r) if true_r else None,
                "ratio": round(ratio, 3) if ratio is not None else None,
                "suspect": suspect, "method": res.method, "file": out_name,
            })
    return rows


# ---------------------------------------------------------------------------
# Part B — isolation du guard (studio vs device sur pixels identiques)
# ---------------------------------------------------------------------------

def _load_cohort(csv_path: Path) -> list[dict]:
    out: list[dict] = []
    with csv_path.open() as f:
        reader = csv.reader((ln for ln in f if not ln.startswith("#")),
                            delimiter=";")
        header = next(reader, None)  # eurio_id;numista_id;display_name
        for parts in reader:
            if len(parts) < 3:
                continue
            out.append({"eurio_id": parts[0].strip(),
                        "numista_id": parts[1].strip(),
                        "display_name": parts[2].strip()})
    return out


def _run_part_b(cohort: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for c in cohort:
        nid = c["numista_id"]
        raw_path = _DATASETS / nid / "obverse.jpg"
        if not raw_path.exists():
            rows.append({"numista_id": nid, "error": "obverse.jpg missing"})
            continue
        bgr = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
        if bgr is None:
            rows.append({"numista_id": nid, "error": "unreadable"})
            continue
        st = normalize_studio(bgr)
        dv = normalize_device(bgr)
        st_ok = st.image is not None
        dv_ok = dv.image is not None
        # Le guard studio est "actif et fiable" quand le contour a réussi
        # (method == "contour"). S'il a fallback ("contour_fallback:*"), le
        # studio == device → pas de divergence mesurable.
        guard_active = st.method == "contour"
        ratio = (dv.r / st.r) if (st_ok and dv_ok and st.r > 0) else None
        diverge = bool(guard_active and ratio is not None
                       and ratio < _UNDERCROP_TOLERANCE)

        over = bgr.copy()
        if st_ok:
            cv2.circle(over, (st.cx, st.cy), st.r, (0, 220, 0), 3)  # studio vert
            cv2.circle(over, (st.cx, st.cy), 4, (0, 220, 0), -1)
        if dv_ok:
            cv2.circle(over, (dv.cx, dv.cy), dv.r, (0, 0, 220), 2)  # device rouge
        over = _downscale(over)
        ovw = over.shape[1]
        crops = np.concatenate([
            _crop_or_placeholder(st.image, "studio fail"),
            np.full((_CROP_DISPLAY, 8, 3), _BG, dtype=np.uint8),
            _crop_or_placeholder(dv.image, "device fail"),
        ], axis=1)
        crop_labels = np.concatenate([
            _label("STUDIO (guardé)", _CROP_DISPLAY),
            np.full((24, 8, 3), _BG, dtype=np.uint8),
            _label("DEVICE (non guardé)", _CROP_DISPLAY),
        ], axis=1)
        ratio_txt = f"{ratio:.2f}" if ratio is not None else "n/a"
        flag = " ⚠ DIVERGE (device inner-ring)" if diverge else ""
        header = f"B · {nid} · {c['display_name'][:42]}"
        footer = (f"studio r={st.r} ({st.method})  device r={dv.r} ({dv.method})"
                  f"  device/studio={ratio_txt}{flag}")
        composed = _stack(
            _label(header, max(ovw, _CROP_DISPLAY * 2 + 8), 26),
            over,
            np.concatenate([crop_labels, crops], axis=0),
            _label(footer, max(ovw, _CROP_DISPLAY * 2 + 8), 22),
        )
        out_name = f"B_{nid}.jpg"
        cv2.imwrite(str(_OUT / out_name), composed,
                    [cv2.IMWRITE_JPEG_QUALITY, 86])
        rows.append({
            "numista_id": nid, "display_name": c["display_name"],
            "studio_r": st.r if st_ok else None,
            "studio_method": st.method,
            "device_r": dv.r if dv_ok else None,
            "device_method": dv.method,
            "ratio": round(ratio, 3) if ratio is not None else None,
            "guard_active": guard_active, "diverge": diverge, "file": out_name,
        })
    return rows


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _write_summary(a_rows: list[dict], b_rows: list[dict], when: str,
                   eval_real_dir: Path, csv_path: Path) -> None:
    a_valid = [r for r in a_rows if "error" not in r and r.get("ratio") is not None]
    a_judged = len(a_valid)
    a_suspect = sum(1 for r in a_valid if r["suspect"])
    a_fail = sum(1 for r in a_rows if "error" in r)
    a_probe_na = sum(1 for r in a_rows
                     if "error" not in r and r.get("ratio") is None)

    b_ok = [r for r in b_rows if "error" not in r]
    b_guarded = [r for r in b_ok if r["guard_active"] and r["ratio"] is not None]
    b_diverge = sum(1 for r in b_ok if r["diverge"])
    b_fallback = sum(1 for r in b_ok if not r["guard_active"])

    out = _OUT / "summary.md"
    with out.open("w") as f:
        f.write("# Bench bimétal — chemin DEVICE (baseline Phase 1)\n\n")
        f.write(f"Généré {when}\n\n")
        f.write(f"- Captures device : `{eval_real_dir}`\n")
        f.write(f"- Cohort CSV : `{csv_path}`\n\n")

        f.write("## Part A — distribution d'inférence (captures device + oracle Otsu)\n\n")
        f.write(f"- Captures avec détection device + oracle résolu : **{a_judged}**\n")
        f.write(f"- Undercrops suspects (r_dev/r_oracle < {_UNDERCROP_TOLERANCE}) : "
                f"**{a_suspect} ({100*a_suspect/max(1,a_judged):.0f} %)**\n")
        f.write(f"- Oracle Otsu non concluant : **{a_probe_na}**\n")
        f.write(f"- Échecs détection device (no circle / unreadable) : **{a_fail}**\n\n")
        ratios = [r["ratio"] for r in a_valid]
        if ratios:
            arr = np.array(ratios)
            f.write(f"**r_dev/r_oracle** : min={arr.min():.3f} "
                    f"p25={np.percentile(arr,25):.3f} med={np.median(arr):.3f} "
                    f"p75={np.percentile(arr,75):.3f} max={arr.max():.3f}\n\n")
        f.write("| class | step | r_dev | r_oracle | ratio | method | susp | file |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")

        def a_key(r):
            if "error" in r:
                return (2, 0.0)
            if r.get("ratio") is None:
                return (1, 0.0)
            return (0 if r["suspect"] else 1, r["ratio"])
        for r in sorted(a_rows, key=a_key):
            if "error" in r:
                f.write(f"| {r['cls']} | {r['step']} | — | — | — | — | err |"
                        f" {r['error']} |\n")
                continue
            ratio = f"{r['ratio']:.2f}" if r.get("ratio") is not None else "n/a"
            sus = "⚠" if r["suspect"] else ""
            f.write(f"| {r['cls']} | {r['step']} | {r.get('r_dev','—')} | "
                    f"{r.get('true_r') or '—'} | {ratio} | {r['method']} | "
                    f"{sus} | `{r['file']}` |\n")

        f.write("\n## Part B — isolation du guard (studio vs device, pixels identiques)\n\n")
        f.write(f"- Pièces cohort : **{len(b_rows)}**\n")
        f.write(f"- Studio contour fiable (guard actif) : **{len(b_guarded)}** "
                f"(les autres {b_fallback} ont fallback → device, divergence "
                f"non mesurable)\n")
        f.write(f"- Divergences device inner-ring "
                f"(device/studio < {_UNDERCROP_TOLERANCE} sur guard actif) : "
                f"**{b_diverge} / {len(b_guarded)}**"
                + (f" ({100*b_diverge/len(b_guarded):.0f} %)\n\n"
                   if b_guarded else "\n\n"))
        f.write("| numista | nom | studio_r | device_r | dev/studio | "
                "studio_method | device_method | diverge | file |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")

        def b_key(r):
            if "error" in r:
                return (2, 0.0)
            if r["ratio"] is None:
                return (1, 0.0)
            return (0 if r["diverge"] else 1, r["ratio"])
        for r in sorted(b_rows, key=b_key):
            if "error" in r:
                f.write(f"| {r['numista_id']} | — | — | — | — | — | — | err |"
                        f" {r['error']} |\n")
                continue
            ratio = f"{r['ratio']:.2f}" if r["ratio"] is not None else "n/a"
            dv = "⚠" if r["diverge"] else ""
            f.write(f"| {r['numista_id']} | {(r['display_name'] or '')[:34]} | "
                    f"{r.get('studio_r') or '—'} | {r.get('device_r') or '—'} | "
                    f"{ratio} | {r['studio_method']} | {r['device_method']} | "
                    f"{dv} | `{r['file']}` |\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--device-pull", required=True,
                   help="dossier pull contenant eval_real/ (ou directement eval_real/)")
    p.add_argument("--cohort-csv", required=True)
    args = p.parse_args()

    pull = Path(args.device_pull)
    # Tolère --device-pull <pull>, <pull>/eval_real, ou <pull>/eval_real/<ts>.
    if (pull / "eval_real").is_dir():
        eval_real_dir = pull / "eval_real"
    elif pull.name == "eval_real":
        eval_real_dir = pull
    else:
        # peut-être <pull> contient déjà les dossiers de classes
        eval_real_dir = pull
    if not eval_real_dir.is_dir():
        raise SystemExit(f"eval_real introuvable sous {pull}")

    csv_path = Path(args.cohort_csv)
    cohort = _load_cohort(csv_path)

    if _OUT.exists():
        shutil.rmtree(_OUT)
    _OUT.mkdir(parents=True, exist_ok=True)

    when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Part A — captures device sous {eval_real_dir} …")
    a_rows = _run_part_a(eval_real_dir)
    print(f"  {len(a_rows)} captures traitées")
    print(f"Part B — {len(cohort)} pièces cohort (studio vs device) …")
    b_rows = _run_part_b(cohort)

    _write_summary(a_rows, b_rows, when, eval_real_dir, csv_path)

    a_valid = [r for r in a_rows if "error" not in r and r.get("ratio") is not None]
    a_sus = sum(1 for r in a_valid if r["suspect"])
    b_div = sum(1 for r in b_rows if r.get("diverge"))
    print(f"\n→ {_OUT}/summary.md")
    print(f"  Part A : {a_sus}/{len(a_valid)} undercrops suspects (oracle-jugés)")
    print(f"  Part B : {b_div} divergences device inner-ring")


if __name__ == "__main__":
    main()
