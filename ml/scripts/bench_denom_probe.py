"""Bench C7 pilier 2 — replay du gate dénomination déployé sur le gold.

Rejoue la probe PROD (`ml/state/denom_probe.npz`, seuil embarqué) sur le gold
`denom_gold.jsonl`, via le **chemin d'inférence réel** (`vision.denom_probe
.denom_score` : vec vitl14 ⊕ bimetal_score normalisé → sigmoïde → seuil), et
sort précision/rappel du gate :

  - rappel 2€       = vrais 2€ qui PASSENT le gate (R0 : les pertes doivent
                      rester ≤ 2 % sur le conf=hi) ;
  - capture junk    = non-2€ rejetés (rappel du rejet `not_2eur`) ;
  - précision rejet = parmi les rejetés, part de vrais non-2€ ;
  - détail par conf (hi / lo) et capture par kind (cent / medal / chart / …).

⚠️ Les rows conf=hi sont le TRAIN de la probe → leurs scores sont in-sample
(optimistes). L'éval honnête (cross-val out-of-fold, baselines, choix du
seuil) reste `scripts/train_denom_probe.py` ; CE bench est le **test de
régression du gate déployé** — rejouable après chaque re-train de la probe ou
enrichissement du gold (le cache d'embeddings se régénère si désaligné).

Pattern maison : gold fini (pas de mining DB, contrairement à
`bench_face_detection.py` qui mine ses candidats), artefact JSON dans
`ml/state/denom_bench/gate_replay.json`.

Usage : python -m scripts.bench_denom_probe [--threshold T]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from shared.storage.local_cache import local_path  # noqa: E402
from scripts.train_denom_probe import (  # noqa: E402
    MAX_TRUE2EUR_LOSS,
    _capture_by_kind,
    _load_embeddings,
    _load_gold,
)
from vision.denom_probe import denom_score, denom_threshold  # noqa: E402

BENCH_DIR = ML_DIR / "state" / "denom_bench"
REPLAY_OUT = BENCH_DIR / "gate_replay.json"


def _gate_metrics(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    """Métriques du gate binaire `score < threshold → not_2eur`."""
    rej = scores < threshold
    pos, neg = y == 1, y == 0
    n_rej = int(rej.sum())
    return {
        "n": int(len(y)),
        "n_pos": int(pos.sum()),
        "n_neg": int(neg.sum()),
        "n_rejected": n_rej,
        "recall_2eur": round(float((~rej & pos).sum() / max(1, pos.sum())), 4),
        "true2eur_loss": round(float((rej & pos).sum() / max(1, pos.sum())), 4),
        "junk_capture": round(float((rej & neg).sum() / max(1, neg.sum())), 4),
        "reject_precision": (
            round(float((rej & neg).sum() / n_rej), 4) if n_rej else None
        ),
    }


def _print_metrics(label: str, m: dict, by_kind: dict | None = None) -> None:
    print(f"\n[{label}] {m['n_pos']} pos / {m['n_neg']} neg → "
          f"{m['n_rejected']} rejetés")
    print(f"  rappel 2€       = {m['recall_2eur']:.1%} "
          f"(perdus {m['true2eur_loss']:.1%})")
    print(f"  capture junk    = {m['junk_capture']:.1%}")
    prec = m["reject_precision"]
    print(f"  précision rejet = {prec:.1%}" if prec is not None
          else "  précision rejet = — (aucun rejet)")
    if by_kind:
        print(f"  junk capté / kind : {by_kind}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=float, default=None,
                    help="seuil à auditer (défaut : celui embarqué dans "
                         "state/denom_probe.npz)")
    args = ap.parse_args()

    artifact_threshold = denom_threshold()  # exige l'artefact (denom_score aussi)
    if artifact_threshold is None:
        sys.exit("Probe denom absente — state/denom_probe.npz "
                 "(scripts.train_denom_probe --save)")
    threshold = args.threshold if args.threshold is not None else artifact_threshold

    rows = _load_gold()  # non-unk, ordre jsonl (= alignement du cache npz)
    paths = [local_path("enrichment-crops", r["sp"]) for r in rows]
    emb = _load_embeddings(rows, paths)
    assert len(emb) == len(rows), "cache npz désaligné — supprimer gold_vitl14.npz"

    # Chemin d'inférence prod : denom_score(vec, bgr) — bimetal recalculé +
    # normalisé avec les stats embarquées dans l'artefact, comme en pipeline.
    scores = np.empty(len(rows), dtype=np.float64)
    n_err = 0
    for i, (r, p) in enumerate(zip(rows, paths)):
        bgr = cv2.imread(str(p))
        if bgr is None:
            scores[i] = np.nan
            n_err += 1
            continue
        scores[i] = denom_score(emb[i], bgr)
    ok = ~np.isnan(scores)
    if n_err:
        print(f"⚠️ {n_err} crops illisibles (exclus)")

    y = np.array([1 if r["label"] == "pos" else 0 for r in rows])
    conf = np.array([r.get("conf") for r in rows])
    kinds = [r.get("kind") for r in rows]

    print(f"gate replay : seuil = {threshold:.4f} · gold non-unk = {int(ok.sum())}")

    sections: dict[str, dict] = {}
    for label, mask in (
        ("tous (hi+lo)", ok),
        ("conf=hi (in-sample — train de la probe)", ok & (conf == "hi")),
        ("conf=lo (jamais vu à l'entraînement)", ok & (conf == "lo")),
    ):
        m = _gate_metrics(y[mask], scores[mask], threshold)
        by_kind = _capture_by_kind(
            y[mask], scores[mask], [k for k, mm in zip(kinds, mask) if mm],
            threshold,
        )
        m["capture_by_kind"] = by_kind
        sections[label] = m
        _print_metrics(label, m, by_kind)

    hi_loss = sections["conf=hi (in-sample — train de la probe)"]["true2eur_loss"]
    if hi_loss > MAX_TRUE2EUR_LOSS:
        print(f"\n⚠️ RÉGRESSION R0 : {hi_loss:.1%} de vrais 2€ perdus sur le "
              f"conf=hi (> {MAX_TRUE2EUR_LOSS:.0%}) — re-vérifier la probe / "
              f"le seuil avant tout backfill --reject.")

    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    REPLAY_OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threshold": float(threshold),
        "threshold_source": ("cli" if args.threshold is not None
                             else "state/denom_probe.npz"),
        "n_gold_non_unk": int(ok.sum()),
        "n_read_errors": n_err,
        "sections": sections,
        "caveat": "conf=hi est le train de la probe (scores in-sample) ; "
                  "l'éval honnête out-of-fold est train_denom_probe.py",
    }, indent=2, ensure_ascii=False))
    print(f"\nartefact → {REPLAY_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
