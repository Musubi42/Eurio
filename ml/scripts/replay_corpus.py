"""Replay d'un candidat sur le corpus de scan rejouable (Lot 4 — cœur du funnel S0).

Spec : ``docs/work-in-progress/scan-quality/corpus-spec.md`` (§7 contrat de
replay, §8 scorecard, §8bis McNemar, §9 baseline épinglée).

Un **candidat** = un dossier contenant :
  - ``embeddings_v1.json``  (centroïdes)
  - un modèle ``*.tflite`` ou ``*.pth``
  - optionnel ``thresholds.json`` ``{"top1_min": float, "margin_min": float}``
    (abstention ; absent = répond toujours — parité avec le matcher Android
    actuel, top-k cosine pur sans seuil).

La **baseline est un candidat comme un autre** (§9) : passer ``--baseline`` ;
le script rejoue les deux sur les MÊMES frames et croise les prédictions
frame-par-frame (McNemar exact, paires discordantes) — jamais deux R@1
indépendants (§8bis, n petit).

Deux chemins (§7) :
  - ``--path fast``  (défaut) : crop.png → embed → cosine vs centroïdes.
  - ``--path full``  : raw.jpg → ``vision.normalize_snap.normalize_device``
    (port bit-for-bit de ``SnapNormalizer.kt``) → crop → embed → match.

Parité (§7, non négociable) : matching = ``match_topk`` + ``compute_hits`` de
``training.eval.evaluate_real_photos`` (mêmes règles que le matcher Android,
obverse-only) ; l'eq design_group est résolue via
``training.eval.equivalence.build_equivalence_map`` contre le canonique en
LECTURE SEULE (même source que le §5 / ``sync_live_tests``). La table
``scan_corpus`` ne joint jamais le canonique (§4).

Usage :
    python -m scripts.replay_corpus --candidate <dir> [--baseline <dir>]
        [--cohort-id b0299ca0252b] [--conditions bright,dim,tilt]
        [--iteration 5bf8edb0ad7d] [--path fast|full] [--out <dir>]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from shared.stats.paired import mcnemar_exact as _mcnemar_exact  # noqa: E402
from store.scan_corpus import ScanCapture, ScanCorpusStore, corpus_version  # noqa: E402

DEFAULT_RUNS_DIR = ML_DIR / "state" / "scan_corpus_runs"


# ─── Candidat ───────────────────────────────────────────────────────────────


@dataclass
class Candidate:
    label: str
    centroids_path: Path
    model_path: Path
    top1_min: float | None = None
    margin_min: float | None = None

    @property
    def has_thresholds(self) -> bool:
        return self.top1_min is not None or self.margin_min is not None


def load_candidate(dir_path: Path, label: str | None = None) -> Candidate:
    centroids = dir_path / "embeddings_v1.json"
    if not centroids.exists():
        found = sorted(dir_path.rglob("embeddings_v1.json"))
        if not found:
            raise SystemExit(f"{dir_path}: embeddings_v1.json introuvable")
        centroids = found[0]
    models = sorted(dir_path.rglob("*.tflite")) or sorted(dir_path.rglob("*.pth"))
    if not models:
        raise SystemExit(f"{dir_path}: aucun modèle *.tflite / *.pth")
    top1_min = margin_min = None
    thresholds = dir_path / "thresholds.json"
    if thresholds.exists():
        t = json.loads(thresholds.read_text(encoding="utf-8"))
        top1_min = t.get("top1_min")
        margin_min = t.get("margin_min")
    return Candidate(
        label=label or dir_path.name,
        centroids_path=centroids,
        model_path=models[0],
        top1_min=top1_min,
        margin_min=margin_min,
    )


# ─── Replay d'un candidat ───────────────────────────────────────────────────


@dataclass
class FramePrediction:
    capture_id: str
    eurio_id: str
    condition: str
    top5: list[tuple[str, float]]
    abstained: bool
    correct_strict_top1: bool
    correct_eq_top1: bool
    correct_eq_top5: bool
    error: str | None = None

    @property
    def answered_correct_eq(self) -> bool:
        """Verdict apparié McNemar : a répondu ET top-1 correct en maille eq."""
        return not self.abstained and self.error is None and self.correct_eq_top1

    def to_json(self) -> dict:
        return {
            "capture_id": self.capture_id,
            "eurio_id": self.eurio_id,
            "condition": self.condition,
            "top5": [[c, round(s, 6)] for c, s in self.top5],
            "abstained": self.abstained,
            "correct_strict_top1": self.correct_strict_top1,
            "correct_eq_top1": self.correct_eq_top1,
            "correct_eq_top5": self.correct_eq_top5,
            "error": self.error,
        }


def replay_candidate(
    candidate: Candidate,
    captures: list[ScanCapture],
    frames_root: Path,
    equivalence,
    path_mode: str = "fast",
) -> list[FramePrediction]:
    from PIL import Image

    from training.eval.evaluate_real_photos import (
        compute_hits,
        load_centroids,
        load_embedder,
        match_topk,
    )

    centroids = load_centroids(candidate.centroids_path)
    by_id = {c.class_id: c for c in centroids}
    embedder = load_embedder(candidate.model_path)

    preds: list[FramePrediction] = []
    for cap in captures:
        try:
            if path_mode == "full":
                image = _normalize_full(frames_root / cap.raw_path)
                if image is None:
                    preds.append(_error_pred(cap, "normalize_failed"))
                    continue
            else:
                image = Image.open(frames_root / cap.crop_path).convert("RGB")
        except (OSError, FileNotFoundError) as exc:
            preds.append(_error_pred(cap, f"load_failed: {exc}"))
            continue

        emb = embedder.embed(image)
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        top5 = match_topk(emb, centroids, k=5)
        hits, hits_eq = compute_hits(top5, cap.eurio_id, by_id, equivalence)

        abstained = False
        if candidate.has_thresholds and top5:
            top1_sim = top5[0][1]
            margin = top1_sim - (top5[1][1] if len(top5) > 1 else 0.0)
            if candidate.top1_min is not None and top1_sim < candidate.top1_min:
                abstained = True
            if candidate.margin_min is not None and margin < candidate.margin_min:
                abstained = True

        preds.append(
            FramePrediction(
                capture_id=cap.capture_id,
                eurio_id=cap.eurio_id,
                condition=cap.condition,
                top5=top5,
                abstained=abstained,
                correct_strict_top1=hits[1],
                correct_eq_top1=hits_eq[1],
                correct_eq_top5=hits_eq[5],
            )
        )
    return preds


def _error_pred(cap: ScanCapture, error: str) -> FramePrediction:
    return FramePrediction(
        capture_id=cap.capture_id,
        eurio_id=cap.eurio_id,
        condition=cap.condition,
        top5=[],
        abstained=True,
        correct_strict_top1=False,
        correct_eq_top1=False,
        correct_eq_top5=False,
        error=error,
    )


def _normalize_full(raw_path: Path):
    """Chemin complet §7 : raw → détection+normalisation parité SnapNormalizer."""
    from PIL import Image

    from vision.normalize_snap import normalize_device_path

    result = normalize_device_path(raw_path)
    if result.image is None:
        return None
    rgb = result.image[:, :, ::-1]  # BGR (OpenCV) → RGB (embedder)
    return Image.fromarray(np.ascontiguousarray(rgb))


# ─── Scorecard §8 ───────────────────────────────────────────────────────────


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def build_scorecard(
    candidate: Candidate,
    preds: list[FramePrediction],
    baseline_label: str | None,
    filter_desc: dict,
    version: str,
) -> dict:
    n = len(preds)
    answered = [p for p in preds if not p.abstained and p.error is None]
    by_condition: dict[str, dict] = {}
    for cond in sorted({p.condition for p in preds}):
        cp = [p for p in preds if p.condition == cond]
        by_condition[cond] = {
            "n": len(cp),
            "r_at_1_eq": _rate(sum(p.correct_eq_top1 for p in cp), len(cp)),
        }
    model_mb = round(candidate.model_path.stat().st_size / (1024 * 1024), 2)
    return {
        "candidate": candidate.label,
        "baseline": baseline_label,
        "corpus_version": version,
        "n_frames": n,
        "filter": filter_desc,
        "primary": {
            "r_at_1_eq": _rate(sum(p.correct_eq_top1 for p in preds), n),
            "r_at_5_eq": _rate(sum(p.correct_eq_top5 for p in preds), n),
            "r_at_1_strict": _rate(sum(p.correct_strict_top1 for p in preds), n),
        },
        "by_condition": by_condition,
        "abstention": {
            "coverage": _rate(len(answered), n),
            "precision_at_coverage": _rate(
                sum(p.correct_eq_top1 for p in answered), len(answered)
            ),
        },
        "latency_ms": {"p50": None, "p95": None, "tier": None},
        "size": {"model_mb": model_mb, "delta_vs_baseline_mb": None},
    }


# ─── McNemar §8bis ──────────────────────────────────────────────────────────


# ``mcnemar_exact`` a déménagé dans ``shared.stats.paired`` (paquet stdlib-only,
# importable par l'image lean du VPS) : le banc multi-encodeurs en a besoin sans
# tirer numpy ni torch. On le ré-exporte ici sous le même nom — les appelants et
# ``tests/test_replay_corpus.py`` continuent de faire
# ``from scripts.replay_corpus import mcnemar_exact`` et obtiennent le MÊME objet.
mcnemar_exact = _mcnemar_exact


def crossed_stats(
    baseline_preds: list[FramePrediction], candidate_preds: list[FramePrediction]
) -> dict:
    base_by_id = {p.capture_id: p for p in baseline_preds}
    cand_by_id = {p.capture_id: p for p in candidate_preds}
    common = sorted(base_by_id.keys() & cand_by_id.keys())
    both = base_only = cand_only = neither = 0
    gained: list[dict] = []
    lost: list[dict] = []
    for cid in common:
        bp, cp = base_by_id[cid], cand_by_id[cid]
        b_ok, c_ok = bp.answered_correct_eq, cp.answered_correct_eq
        if b_ok and c_ok:
            both += 1
        elif b_ok:
            base_only += 1
            lost.append(_flip(cid, bp, cp))
        elif c_ok:
            cand_only += 1
            gained.append(_flip(cid, bp, cp))
        else:
            neither += 1
    return {
        "n_paired": len(common),
        "contingency": {
            "both_correct": both,
            "baseline_only": base_only,
            "candidate_only": cand_only,
            "both_incorrect": neither,
        },
        "n_discordant": base_only + cand_only,
        "p_value": round(mcnemar_exact(base_only, cand_only), 6),
        "confusions": {"gained": gained, "lost": lost},
    }


def _flip(cid: str, bp: FramePrediction, cp: FramePrediction) -> dict:
    return {
        "capture_id": cid,
        "eurio_id": bp.eurio_id,
        "condition": bp.condition,
        "baseline_top1": bp.top5[0][0] if bp.top5 else None,
        "candidate_top1": cp.top5[0][0] if cp.top5 else None,
    }


# ─── Main ───────────────────────────────────────────────────────────────────


def _write_predictions(path: Path, preds: list[FramePrediction]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for p in preds:
            fh.write(json.dumps(p.to_json(), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--candidate", type=Path, required=True, help="dossier candidat")
    parser.add_argument("--candidate-label", default=None)
    parser.add_argument("--baseline", type=Path, default=None, help="dossier baseline (§9)")
    parser.add_argument("--baseline-label", default=None)
    parser.add_argument("--cohort-id", default=None)
    parser.add_argument("--conditions", default=None, help="csv, ex. bright,dim,tilt")
    parser.add_argument("--iteration", default=None, help="filtre source_iteration_id")
    parser.add_argument("--path", choices=("fast", "full"), default="fast")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None, help="override scan_corpus.db (tests)")
    parser.add_argument(
        "--eq-db",
        type=Path,
        default=None,
        help="DB canonique (RO) pour l'eq design_group ; défaut = résolution standard",
    )
    parser.add_argument(
        "--no-eq",
        action="store_true",
        help="sans map d'équivalence (eq=strict) — tests uniquement",
    )
    args = parser.parse_args()

    store = ScanCorpusStore(db_path=args.db)
    conditions = args.conditions.split(",") if args.conditions else None
    captures = store.list_captures(
        cohort_id=args.cohort_id,
        conditions=conditions,
        source_iteration_id=args.iteration,
    )
    if not captures:
        raise SystemExit("Corpus vide pour ce filtre — rien à rejouer.")
    version = corpus_version([c.capture_id for c in captures])
    filter_desc = {
        "cohort_id": args.cohort_id,
        "conditions": conditions,
        "source_iteration_id": args.iteration,
    }

    if args.no_eq:
        equivalence = None
    else:
        from training.eval.equivalence import build_equivalence_map

        equivalence = build_equivalence_map(db_path=args.eq_db)

    candidate = load_candidate(args.candidate, args.candidate_label)
    out_dir = args.out or (DEFAULT_RUNS_DIR / f"{candidate.label}__{version}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Corpus : {len(captures)} frames (version {version}) — chemin {args.path}")
    print(f"Candidat : {candidate.label} ({candidate.model_path.name})")
    cand_preds = replay_candidate(
        candidate, captures, store.frames_root, equivalence, args.path
    )
    _write_predictions(out_dir / "predictions.jsonl", cand_preds)

    baseline_label = None
    scorecard: dict
    if args.baseline:
        baseline = load_candidate(args.baseline, args.baseline_label)
        baseline_label = baseline.label
        print(f"Baseline : {baseline.label} ({baseline.model_path.name})")
        base_preds = replay_candidate(
            baseline, captures, store.frames_root, equivalence, args.path
        )
        _write_predictions(out_dir / "predictions.baseline.jsonl", base_preds)
        scorecard = build_scorecard(candidate, cand_preds, baseline_label, filter_desc, version)
        baseline_scorecard = build_scorecard(
            baseline, base_preds, None, filter_desc, version
        )
        scorecard["size"]["delta_vs_baseline_mb"] = round(
            scorecard["size"]["model_mb"] - baseline_scorecard["size"]["model_mb"], 2
        )
        scorecard["baseline_primary"] = baseline_scorecard["primary"]
        scorecard["baseline_by_condition"] = baseline_scorecard["by_condition"]
        scorecard["mcnemar"] = crossed_stats(base_preds, cand_preds)
    else:
        scorecard = build_scorecard(candidate, cand_preds, None, filter_desc, version)

    (out_dir / "scorecard.json").write_text(
        json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nScorecard → {out_dir / 'scorecard.json'}")
    print(json.dumps(scorecard["primary"], indent=2))
    if "mcnemar" in scorecard:
        m = scorecard["mcnemar"]
        print(
            f"McNemar : discordantes={m['n_discordant']} "
            f"(baseline_only={m['contingency']['baseline_only']}, "
            f"candidate_only={m['contingency']['candidate_only']}) "
            f"p={m['p_value']}"
        )


if __name__ == "__main__":
    main()
