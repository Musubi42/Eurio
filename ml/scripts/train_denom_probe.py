"""Probe DINO « 2€ vs junk » — entraînement + bench (C7 pilier 2, H11bis).

Une *seule* probe logistique sur embeddings vitl14 gelés pour rejeter, per-crop,
tout ce qui n'est pas un 2€ unique : autres dénominations (cents, 1€), médailles/
jetons, mires de couleur, sets multi-pièces. Subsume coin-ness + dénomination pour
le problème de pollution de lot (cf. C7 §H10, gold `denom_gold.jsonl`).

Protocole (benchmark-first, R0) :
  - **train/éval = gold `conf=hi` uniquement** (ancres sûres ; `unk` exclus) ;
  - éval honnête par **cross-val 5-fold stratifiée** (`cross_val_predict` →
    scores out-of-fold, jamais de score in-sample pour juger) ;
  - **courbe de seuils** : grille → (vrais 2€ perdus, junk capturé) = LA table
    de décision (cf. HANDOFF-C7 §1 : le seuil sur la similarité aux ancres
    perdait 4–16 % des vrais 2€) ;
  - baselines comparées sur le même gold : (a) `max(obverse-ness, reverse-ness)`
    banques `2eur_all` + `reverse_2eur`, (b) `bimetal_score` seul, (c) probe
    dino seule, (d) dino ⊕ bimetal ;
  - les rows `conf=lo` (pos+neg, hors unk) servent de **sanity hold-out bruité**
    (reportées séparément, jamais pour choisir le seuil) ;
  - seuil opérationnel : max de junk capturé sous la contrainte
    **vrais 2€ perdus ≤ 2 %** (out-of-fold).

Artefacts (`--save` pour la probe prod) :
  - `ml/state/denom_probe.npz` — probe finale fittée sur tout le `conf=hi`
    (clés : coef (1,1025), intercept, bm_mean, bm_std, encoder, threshold —
    format attendu par `vision/denom_probe.py`) ;
  - `ml/state/denom_bench/probe_eval.json` — toutes les métriques + courbes ;
  - `ml/state/denom_bench/probe_threshold_curve.csv` — la table de décision ;
  - `ml/state/denom_bench/probe_curves.png` — courbes junk-capté vs 2€-perdus ;
  - `ml/state/denom_bench/probe_report.md` — rapport regénérable.

Usage : python -m scripts.train_denom_probe [--save]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from shared.storage.local_cache import local_path  # noqa: E402
from training.foundation.anchors import (  # noqa: E402
    REVERSE_ANCHORS_KIND,
    SUGGESTIONS_ANCHORS_KIND,
    load_anchors,
)
from training.foundation.encoder import build_transform, load_encoder  # noqa: E402
from vision.denom_geometry import bimetal_score  # noqa: E402
import cv2  # noqa: E402

GOLD = ML_DIR / "state" / "denom_bench" / "denom_gold.jsonl"
EMB_CACHE = ML_DIR / "state" / "denom_bench" / "gold_vitl14.npz"
BENCH_DIR = ML_DIR / "state" / "denom_bench"
PROBE_OUT = ML_DIR / "state" / "denom_probe.npz"

ENCODER_VERSION = "dinov2-vitl14"
MAX_TRUE2EUR_LOSS = 0.02  # R0 : ≤ 2 % de vrais 2€ perdus au seuil opérationnel
N_FOLDS = 5
SEED = 0


def _make_clf() -> LogisticRegression:
    return LogisticRegression(max_iter=2000, C=0.5, class_weight="balanced")


@torch.no_grad()
def _embed(paths: list[Path], model, device, tf) -> np.ndarray:
    vecs = []
    for i in range(0, len(paths), 16):
        ims = [Image.open(p).convert("RGB") for p in paths[i:i + 16]]
        batch = torch.stack([tf(im) for im in ims]).to(device)
        feat = torch.nn.functional.normalize(model(batch), dim=1)
        vecs.append(feat.cpu().numpy())
    return np.concatenate(vecs).astype(np.float32)


def _load_gold() -> list[dict]:
    rows = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    # ordre jsonl préservé : le cache npz est aligné sur les rows non-unk.
    return [r for r in rows if r["label"] in ("pos", "neg")]


def _load_embeddings(rows: list[dict], paths: list[Path]) -> np.ndarray:
    emb = None
    if EMB_CACHE.exists():
        cached = np.load(EMB_CACHE)["emb"]
        if len(cached) == len(rows):
            emb = cached
    if emb is None:
        model, device = load_encoder(encoder_version=ENCODER_VERSION)
        emb = _embed(paths, model, device, build_transform())
        np.savez_compressed(EMB_CACHE, emb=emb)
    return emb


def _anchor_max_sim(emb: np.ndarray) -> np.ndarray | None:
    """Baseline (a) : max(obverse-ness, reverse-ness) — banques vitl14.

    obverse-ness = top1 cosine vs `2eur_all` (546 avers canoniques) ;
    reverse-ness = top1 cosine vs `reverse_2eur` (2 cartes communes).
    """
    obv = load_anchors(SUGGESTIONS_ANCHORS_KIND)
    rev = load_anchors(REVERSE_ANCHORS_KIND)
    if obv is None or obv.encoder_version != ENCODER_VERSION:
        return None
    sims = (emb @ obv.matrix.T).max(axis=1)
    if rev is not None and rev.encoder_version == ENCODER_VERSION:
        sims = np.maximum(sims, (emb @ rev.matrix.T).max(axis=1))
    return sims.astype(np.float64)


def _curve(y: np.ndarray, score: np.ndarray, thresholds: np.ndarray) -> list[dict]:
    """Pour chaque seuil : vrais 2€ perdus (FN rate) et junk capturé (TN rate)."""
    pos, neg = y == 1, y == 0
    out = []
    for t in thresholds:
        rej = score < t
        out.append({
            "threshold": round(float(t), 4),
            "true2eur_loss": round(float((rej & pos).sum() / max(1, pos.sum())), 4),
            "junk_capture": round(float((rej & neg).sum() / max(1, neg.sum())), 4),
        })
    return out


def _operating_point(y: np.ndarray, score: np.ndarray,
                     max_loss: float = MAX_TRUE2EUR_LOSS) -> dict | None:
    """Seuil opérationnel : max junk capturé sous contrainte loss ≤ max_loss.

    Balaye les seuils candidats = scores observés (loss et capture sont tous
    deux croissants en seuil → on prend le plus grand seuil admissible).
    """
    cands = np.unique(score)
    best = None
    for t in cands:
        pt = _curve(y, score, np.array([t]))[0]
        if pt["true2eur_loss"] <= max_loss:
            if best is None or pt["junk_capture"] > best["junk_capture"]:
                best = pt
    return best


def _capture_by_kind(y: np.ndarray, score: np.ndarray, kinds: list,
                     threshold: float) -> dict[str, str]:
    from collections import defaultdict
    tot, hit = defaultdict(int), defaultdict(int)
    for i, k in enumerate(kinds):
        if y[i] == 0:
            kk = k or "?"
            tot[kk] += 1
            hit[kk] += int(score[i] < threshold)
    return {k: f"{hit[k]}/{tot[k]}" for k in sorted(tot)}


def _eval_scorer(name: str, y: np.ndarray, score: np.ndarray, kinds: list,
                 grid: np.ndarray) -> dict:
    op = _operating_point(y, score)
    res = {
        "name": name,
        "auc": round(float(roc_auc_score(y, score)), 4),
        "curve": _curve(y, score, grid),
        "operating_point": op,
        "capture_by_kind": (_capture_by_kind(y, score, kinds, op["threshold"])
                            if op else None),
    }
    print(f"\n[{name}] AUC={res['auc']:.3f}")
    if op:
        print(f"  seuil={op['threshold']:.3f} → 2€ perdus={op['true2eur_loss']:.1%} "
              f"junk capté={op['junk_capture']:.1%}")
        print(f"  junk capté / kind : {res['capture_by_kind']}")
    else:
        print(f"  (aucun seuil ne tient 2€ perdus ≤ {MAX_TRUE2EUR_LOSS:.0%})")
    return res


def _plot(results: list[dict], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 5))
    for r in results:
        xs = [p["true2eur_loss"] for p in r["curve"]]
        ys = [p["junk_capture"] for p in r["curve"]]
        order = np.argsort(xs)
        ax.plot(np.array(xs)[order], np.array(ys)[order],
                marker=".", label=f"{r['name']} (AUC {r['auc']:.3f})")
        if r["operating_point"]:
            ax.scatter([r["operating_point"]["true2eur_loss"]],
                       [r["operating_point"]["junk_capture"]], s=80, zorder=5)
    ax.axvline(MAX_TRUE2EUR_LOSS, ls="--", c="grey", lw=1,
               label=f"contrainte loss ≤ {MAX_TRUE2EUR_LOSS:.0%}")
    ax.set_xlabel("vrais 2€ perdus (out-of-fold, conf=hi)")
    ax.set_ylabel("junk capturé")
    ax.set_title("Gate dénomination « 2€ vs junk » — trade-off par scorer")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def _write_report(payload: dict, out: Path) -> None:
    p = payload
    lines = [
        "# Probe denom « 2€ vs junk » — bench (généré par train_denom_probe.py)",
        "",
        f"_Généré : {p['generated_at']} · gold : {p['gold']['n_hi_pos']} pos hi / "
        f"{p['gold']['n_hi_neg']} neg hi (train+CV) · {p['gold']['n_lo']} lo "
        f"(sanity) · {p['gold']['n_unk']} unk exclus_",
        "",
        "## Protocole",
        "",
        "- Features : embedding DINOv2 vitl14 gelé (1024-d, L2-norm) ± "
        "`bimetal_score` normalisé (z-score sur le train hi).",
        f"- Éval : StratifiedKFold k={N_FOLDS} (seed {SEED}), scores "
        "**out-of-fold uniquement** ; `conf=lo` jamais vu à l'entraînement.",
        f"- Seuil opérationnel : max junk capturé sous **vrais 2€ perdus ≤ "
        f"{MAX_TRUE2EUR_LOSS:.0%}**.",
        "",
        "## Résultats (conf=hi, out-of-fold)",
        "",
        "| scorer | AUC | seuil@loss≤2% | 2€ perdus | junk capturé | par kind |",
        "|---|---|---|---|---|---|",
    ]
    for r in p["results"]:
        op = r["operating_point"]
        if op:
            lines.append(
                f"| {r['name']} | {r['auc']:.3f} | {op['threshold']:.3f} | "
                f"{op['true2eur_loss']:.1%} | {op['junk_capture']:.1%} | "
                f"{r['capture_by_kind']} |")
        else:
            lines.append(f"| {r['name']} | {r['auc']:.3f} | — | — | — | — |")
    lines += ["", f"## Courbe de seuils — {p['final']['name']} (modèle retenu)", "",
              "| seuil | 2€ perdus | junk capturé |", "|---|---|---|"]
    for pt in p["final"]["curve"]:
        lines.append(f"| {pt['threshold']:.2f} | {pt['true2eur_loss']:.1%} | "
                     f"{pt['junk_capture']:.1%} |")
    lo = p["lo_holdout"]
    lines += [
        "",
        "## Sanity hold-out conf=lo (bruité — ne sert PAS à choisir le seuil)",
        "",
        f"- {lo['n_pos']} pos / {lo['n_neg']} neg, scorés par le modèle final "
        f"(fit sur tout le hi) au seuil {p['final']['threshold']:.3f} :",
        f"- vrais 2€ perdus = {lo['true2eur_loss']:.1%} · junk capturé = "
        f"{lo['junk_capture']:.1%} · par kind : {lo['capture_by_kind']}",
        "",
        "## Référence HANDOFF-C7 §1",
        "",
        "Le seuil naïf sur `max(obverse-ness, reverse-ness)` perdait 4–16 % des "
        "vrais 2€ pour 25–68 % de junk capturé (run AT-2005). La baseline (a) "
        "ci-dessus le reproduit sur ce gold ; la probe doit faire nettement mieux.",
    ]
    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true",
                    help="fit final sur tout le conf=hi + write state/denom_probe.npz")
    args = ap.parse_args()

    rows = _load_gold()
    paths = [local_path("enrichment-crops", r["sp"]) for r in rows]
    emb = _load_embeddings(rows, paths)
    assert len(emb) == len(rows), "cache npz désaligné — supprimer gold_vitl14.npz"

    y_all = np.array([1 if r["label"] == "pos" else 0 for r in rows])
    conf = np.array([r.get("conf") for r in rows])
    kinds = [r.get("kind") for r in rows]
    hi, lo = conf == "hi", conf == "lo"
    n_unk = sum(1 for l in GOLD.read_text().splitlines()
                if l.strip() and json.loads(l)["label"] == "unk")
    print(f"gold : hi {int(y_all[hi].sum())} pos / {int((y_all[hi] == 0).sum())} neg"
          f" · lo {int(y_all[lo].sum())} pos / {int((y_all[lo] == 0).sum())} neg"
          f" · {n_unk} unk exclus")

    # bimetal feature (cheap, recalculée)
    bm = np.array([(bimetal_score(cv2.imread(str(p))) or {}).get("score", 0.0)
                   for p in paths], dtype=np.float32)
    bm_mean, bm_std = float(bm[hi].mean()), float(bm[hi].std())
    bm_n = (bm - bm_mean) / (bm_std + 1e-6)
    X_both = np.concatenate([emb, bm_n[:, None]], axis=1)

    y_hi, kinds_hi = y_all[hi], [k for k, h in zip(kinds, hi) if h]
    grid = np.round(np.arange(0.05, 1.0, 0.05), 2)
    cv = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    results = []

    # (a) baseline ancres : max(obverse-ness, reverse-ness), score brut (cosine)
    anchor = _anchor_max_sim(emb)
    if anchor is not None:
        a_grid = np.round(np.arange(0.30, 0.96, 0.05), 2)
        results.append(_eval_scorer("anchor max-sim (baseline)", y_hi,
                                    anchor[hi], kinds_hi, a_grid))
    else:
        print("\n[anchor max-sim] banque 2eur_all vitl14 absente — baseline sautée")

    # (b) bimetal seul, score brut
    b_grid = np.round(np.arange(0.0, 40.0, 2.0), 1)
    results.append(_eval_scorer("bimetal (baseline)", y_hi, bm[hi].astype(np.float64),
                                kinds_hi, b_grid))

    # (c) probe dino seule — out-of-fold
    s_dino = cross_val_predict(_make_clf(), emb[hi], y_hi, cv=cv,
                               method="predict_proba")[:, 1]
    results.append(_eval_scorer("probe dino", y_hi, s_dino, kinds_hi, grid))

    # (d) probe dino ⊕ bimetal — out-of-fold
    s_both = cross_val_predict(_make_clf(), X_both[hi], y_hi, cv=cv,
                               method="predict_proba")[:, 1]
    results.append(_eval_scorer("probe dino+bm", y_hi, s_both, kinds_hi, grid))

    # modèle retenu : dino+bm si gain de junk capturé au point opérationnel,
    # sinon dino seule (sérialisée en 1025-d avec coef bimetal = 0 → format prod).
    op_dino = results[-2]["operating_point"]
    op_both = results[-1]["operating_point"]
    use_both = bool(op_both and (not op_dino or
                                 op_both["junk_capture"] >= op_dino["junk_capture"]))
    chosen = results[-1] if use_both else results[-2]
    op = chosen["operating_point"]
    if op is None:
        print("\nAUCUN scorer ne tient la contrainte R0 — pas de probe sauvée.")
        return 1
    oof = s_both if use_both else s_dino
    print(f"\nmodèle retenu : {chosen['name']} · seuil={op['threshold']:.3f} "
          f"(2€ perdus {op['true2eur_loss']:.1%}, junk capté {op['junk_capture']:.1%})")

    # fit final sur tout le conf=hi + sanity hold-out conf=lo
    final = _make_clf().fit(X_both[hi] if use_both else emb[hi], y_hi)
    s_lo = final.predict_proba(X_both[lo] if use_both else emb[lo])[:, 1]
    y_lo = y_all[lo]
    kinds_lo = [k for k, l_ in zip(kinds, lo) if l_]
    lo_pt = _curve(y_lo, s_lo, np.array([op["threshold"]]))[0]
    lo_holdout = {
        "n_pos": int(y_lo.sum()), "n_neg": int((y_lo == 0).sum()),
        "true2eur_loss": lo_pt["true2eur_loss"],
        "junk_capture": lo_pt["junk_capture"],
        "capture_by_kind": _capture_by_kind(y_lo, s_lo, kinds_lo, op["threshold"]),
    }
    print(f"sanity lo : 2€ perdus={lo_holdout['true2eur_loss']:.1%} "
          f"junk capté={lo_holdout['junk_capture']:.1%} "
          f"({lo_holdout['n_pos']} pos / {lo_holdout['n_neg']} neg)")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol": {"cv": f"StratifiedKFold k={N_FOLDS} seed={SEED}",
                     "train": "conf=hi only", "encoder": ENCODER_VERSION,
                     "max_true2eur_loss": MAX_TRUE2EUR_LOSS},
        "gold": {"n_hi_pos": int(y_hi.sum()), "n_hi_neg": int((y_hi == 0).sum()),
                 "n_lo": int(lo.sum()), "n_unk": n_unk},
        "results": results,
        "final": {"name": chosen["name"], "threshold": op["threshold"],
                  "true2eur_loss": op["true2eur_loss"],
                  "junk_capture": op["junk_capture"],
                  "curve": _curve(y_hi, oof, grid)},
        "lo_holdout": lo_holdout,
    }
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / "probe_eval.json").write_text(json.dumps(payload, indent=2))
    with (BENCH_DIR / "probe_threshold_curve.csv").open("w") as f:
        f.write("scorer,threshold,true2eur_loss,junk_capture\n")
        for r in results:
            for pt in r["curve"]:
                f.write(f"{r['name']},{pt['threshold']},{pt['true2eur_loss']},"
                        f"{pt['junk_capture']}\n")
    _plot(results, BENCH_DIR / "probe_curves.png")
    _write_report(payload, BENCH_DIR / "probe_report.md")
    print(f"\nartefacts → {BENCH_DIR}/probe_eval.json, probe_threshold_curve.csv, "
          f"probe_curves.png, probe_report.md")

    if args.save:
        coef = final.coef_.astype(np.float32)
        if not use_both:  # pad au format prod 1025-d (coef bimetal = 0)
            coef = np.concatenate([coef, np.zeros((1, 1), np.float32)], axis=1)
        np.savez(PROBE_OUT, coef=coef,
                 intercept=final.intercept_.astype(np.float32),
                 bm_mean=bm_mean, bm_std=bm_std, encoder=ENCODER_VERSION,
                 threshold=float(op["threshold"]))
        print(f"probe ({chosen['name']}, fit sur {int(hi.sum())} hi) → {PROBE_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
