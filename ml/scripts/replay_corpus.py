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

⚠️ **Sur le corpus device, la notation se fait en ``--path full``.** Les crops
stockés des pulls d'avril et de juin 2026 ont été produits par DEUX normaliseurs
différents (``hough_tight`` puis ``hough_strict``, lisible dans
``quality_json.normalize.method``). En ``--path fast`` on comparerait des crops
incomparables et l'écart mesuré serait celui des normaliseurs, pas des modèles.

Le protocole se filtre avec ``--bundle-source`` (csv) — pas avec
``--conditions`` : les deux protocoles partagent ``bright_plain`` et
``bright_textured``.

🔴 **Les captures écartées à la main ne sont PAS notées** (``eval_decision =
'exclude'``, posé depuis la fiche pièce de ``studio-local``). C'est le défaut,
et c'est le sens du geste : une photo que le PO a jugée inexploitable ne doit
pas juger. ``--include-rejected`` les remet dans le jeu, pour diagnostic
seulement.

⚠️ Ce que ça implique, et que la scorecard doit porter : l'ensemble noté dépend
d'une décision humaine **mutable**. ``corpus_version`` est donc calculée sur
l'ensemble RÉELLEMENT noté (après exclusion), jamais sur le pool brut — sinon
deux runs à deux jours d'écart porteraient la même version en ayant noté des
jeux différents, exactement le défaut que ``review.bench_gold`` a été écrit
pour tuer. Et le bloc ``excluded`` de la scorecard dit combien de captures ont
été écartées et pourquoi : un ``n`` qui baisse sans explication est un ``n``
qui inquiète.

Parité (§7, non négociable) : matching = ``match_topk`` + ``compute_hits`` de
``training.eval.evaluate_real_photos`` (mêmes règles que le matcher Android,
obverse-only) ; l'eq design_group est résolue via
``training.eval.equivalence.build_equivalence_map`` contre le canonique en
LECTURE SEULE (même source que le §5 / ``sync_live_tests``). La table
``scan_corpus`` ne joint jamais le canonique (§4).

Une **itération du lab** n'est pas un dossier de candidat : elle range ses deux
pièces dans deux sous-dossiers (``checkpoints/best_model.pth`` et
``embeddings/embeddings_v1.json``). ``--iteration <iid>`` construit le candidat
depuis ces chemins **explicites** — on n'assouplit pas ``load_candidate``, dont
le contrat « un dossier = un candidat » reste intact. Bénéfice mesuré : les
chemins explicites ne traversent pas ``dataset/train``, qui est un symlink mort
sur certaines itérations anciennes.

Usage :
    python -m scripts.replay_corpus --candidate <dir> [--baseline <dir>]
        [--cohort-id b0299ca0252b] [--conditions bright,dim,tilt]
        [--bundle-source device_pull_20260601]
        [--source-iteration-id 5bf8edb0ad7d]
        [--path fast|full] [--out <dir>]

    python -m scripts.replay_corpus --iteration caf98145032c --path full \\
        --bundle-source device_pull_20260601
"""
from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_LAB_ITERATIONS_DIR = ML_DIR / "lab" / "iterations"


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


ITERATION_MODEL_KINDS = ("checkpoint", "tflite")


def _iteration_model_path(iter_dir: Path, kind: str) -> Path:
    if kind == "checkpoint":
        return iter_dir / "checkpoints" / "best_model.pth"
    if kind == "tflite":
        found = sorted((iter_dir / "tflite").glob("*.tflite"))
        if not found:
            raise SystemExit(f"{iter_dir}: aucun *.tflite dans tflite/")
        return found[0]
    raise SystemExit(f"kind de modèle inconnu : {kind}")


def candidate_from_iteration(
    iteration_id: str,
    lab_root: Path | None = None,
    label: str | None = None,
    model_kind: str = "checkpoint",
) -> Candidate:
    """Construit un ``Candidate`` depuis une itération du lab.

    Une itération range ses artefacts dans deux sous-dossiers
    (``checkpoints/`` et ``embeddings/``) : ce n'est PAS un dossier de
    candidat au sens de ``load_candidate``, et on ne relâche pas ce
    contrat — on nomme l'intention ici, avec des chemins explicites.
    """
    root = lab_root or DEFAULT_LAB_ITERATIONS_DIR
    iter_dir = root / iteration_id
    if not iter_dir.is_dir():
        raise SystemExit(f"Itération introuvable : {iter_dir}")
    centroids = iter_dir / "embeddings" / "embeddings_v1.json"
    if not centroids.exists():
        raise SystemExit(
            f"{iteration_id}: {centroids} introuvable — l'itération n'a pas "
            "produit ses centroïdes (compute_embeddings non joué ?)"
        )
    model = _iteration_model_path(iter_dir, model_kind)
    if not model.exists():
        raise SystemExit(
            f"{iteration_id}: {model} introuvable "
            "(fichier absent, ou symlink cassé — vérifie `ls -la`)"
        )
    top1_min = margin_min = None
    thresholds = iter_dir / "thresholds.json"
    if thresholds.exists():
        t = json.loads(thresholds.read_text(encoding="utf-8"))
        top1_min = t.get("top1_min")
        margin_min = t.get("margin_min")
    return Candidate(
        label=label or iteration_id,
        centroids_path=centroids,
        model_path=model,
        top1_min=top1_min,
        margin_min=margin_min,
    )


def centroid_class_ids(centroids_path: Path) -> set[str]:
    """Les ``class_id`` d'un fichier de centroïdes — stdlib seule.

    Sert au garde d'espace de labels (§8 de ``corpus-spec``) : il doit pouvoir
    refuser AVANT de charger le moindre modèle.
    """
    data = json.loads(Path(centroids_path).read_text(encoding="utf-8"))
    return set(data.get("coins", {}))


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
    coverable: bool = True
    """La bonne réponse existe-t-elle dans l'espace de labels du candidat ?

    Faux = la frame est fausse PAR CONSTRUCTION : aucun centroïde ne peut la
    satisfaire. Elle compte quand même dans ``n_frames`` (c'est le corpus
    demandé), et c'est exactement pourquoi le r@1 global ne se lit jamais seul.
    """

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
            "coverable": self.coverable,
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
        # Calculée AVANT toute lecture d'image : une frame illisible dont la
        # classe n'est pas dans le modèle reste non couvrable, et le dire
        # sépare les deux causes au lieu de les fondre.
        coverable = is_coverable(cap.eurio_id, centroids, equivalence)
        try:
            if path_mode == "full":
                image = _normalize_full(frames_root / cap.raw_path)
                if image is None:
                    preds.append(_error_pred(cap, "normalize_failed", coverable))
                    continue
            else:
                image = Image.open(frames_root / cap.crop_path).convert("RGB")
        except (OSError, FileNotFoundError) as exc:
            preds.append(_error_pred(cap, f"load_failed: {exc}", coverable))
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
                coverable=coverable,
            )
        )
    return preds


def is_coverable(ground_truth: str, centroids, equivalence) -> bool:
    """Un centroïde du candidat peut-il seulement être juste sur cette frame ?

    Parité stricte avec ``compute_hits`` : un centroïde compte s'il ``covers``
    la vérité terrain, ou s'il lui est équivalent en ``design_group``. Si aucun
    ne le fait, ``correct_eq_top1`` est faux quoi que fasse le modèle — la
    frame est perdue par construction, pas par erreur de prédiction.
    """
    for c in centroids:
        if c.covers(ground_truth):
            return True
        if equivalence is not None and equivalence.are_equivalent(
            c.class_id, ground_truth
        ):
            return True
    return False


def _error_pred(
    cap: ScanCapture, error: str, coverable: bool = True
) -> FramePrediction:
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
        coverable=coverable,
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


def excluded_block(rejected: list[ScanCapture], active: bool) -> dict:
    """Ce que le juge a REFUSÉ de noter, et pourquoi — à côté de ``label_space``.

    Un ``n`` qui baisse sans explication est un ``n`` qui inquiète. La scorecard
    doit donc porter le compte des captures écartées par un humain, leur raison,
    et le fait que l'exclusion était **active** — sinon deux scorecards de
    tailles différentes sont indiscernables d'un corpus qui aurait bougé.
    """
    by_reason: dict[str, int] = {}
    for c in rejected:
        key = c.eval_decision_reason or "∅ (sans raison)"
        by_reason[key] = by_reason.get(key, 0) + 1
    return {
        # ``active`` faux = --include-rejected : les captures ci-dessous ONT été
        # notées. Le bloc reste rendu, il ne disparaît pas quand on désarme le
        # filtre — c'est justement là qu'il faut le voir.
        "active": active,
        "n": len(rejected),
        "by_reason": dict(sorted(by_reason.items())),
        "capture_ids": sorted(c.capture_id for c in rejected),
    }


def build_scorecard(
    candidate: Candidate,
    preds: list[FramePrediction],
    baseline_label: str | None,
    filter_desc: dict,
    version: str,
    candidate_class_ids: set[str] | None = None,
    excluded: dict | None = None,
    equivalence=None,
) -> dict:
    n = len(preds)
    answered = [p for p in preds if not p.abstained and p.error is None]
    # ⚠️ Le dénominateur du r@1 global compte des frames dont la bonne réponse
    # n'est PAS dans le candidat. Elles sont fausses par construction : le
    # nombre reste plausible et devient faux. On rend donc TOUJOURS les deux —
    # global et sur-couvrables — et jamais l'un sans l'autre.
    covered = [p for p in preds if p.coverable]
    by_condition: dict[str, dict] = {}
    for cond in sorted({p.condition for p in preds}):
        cp = [p for p in preds if p.condition == cond]
        cc = [p for p in cp if p.coverable]
        by_condition[cond] = {
            "n": len(cp),
            "r_at_1_eq": _rate(sum(p.correct_eq_top1 for p in cp), len(cp)),
            "n_covered": len(cc),
            "r_at_1_on_covered": _rate(sum(p.correct_eq_top1 for p in cc), len(cc)),
        }
    gt_classes = {p.eurio_id for p in preds}
    covered_classes = {p.eurio_id for p in covered}
    uncoverable_classes = sorted(gt_classes - covered_classes)
    # ── L'espace de labels s'inscrit dans l'ARTEFACT, pas seulement dans le
    # garde. Le garde `assert_same_label_space` ne s'exécute que sous
    # `--baseline` : deux runs notés SÉPARÉMENT puis comparés à la main
    # passaient sans un mot — le garde se contournait en ne l'appelant pas.
    # Une empreinte gravée dans chaque scorecard rend l'espace vérifiable
    # après coup, par `assert_comparable_runs` (et par l'œil).
    cand_mesh = (
        label_mesh(candidate_class_ids, equivalence)
        if candidate_class_ids is not None else None
    )
    label_space = {
        "n_candidate_classes": (
            len(candidate_class_ids) if candidate_class_ids is not None else None
        ),
        "mesh_basis": "design_group" if equivalence is not None else "eurio_id",
        "n_mesh_classes": len(cand_mesh) if cand_mesh is not None else None,
        "mesh_digest": mesh_digest(cand_mesh) if cand_mesh is not None else None,
        "n_ground_truth_classes": len(gt_classes),
        "n_covered_classes": len(covered_classes),
        "n_uncoverable_classes": len(uncoverable_classes),
        "uncoverable_classes": uncoverable_classes,
        "n_frames_covered": len(covered),
        "n_frames_uncoverable": n - len(covered),
        "frame_coverage": _rate(len(covered), n),
    }
    # ``coverage`` seul confond deux choses : une abstention (le candidat a vu
    # la frame et s'est tu) et un échec (la frame n'a jamais atteint le
    # modèle). Un run où tout le raw échoue à se normaliser sortirait
    # ``r@1 = 0.0`` sans qu'aucune clé ne le dise. On le dit.
    errored = [p for p in preds if p.error is not None]
    errors_by_kind: dict[str, int] = {}
    for p in errored:
        kind = str(p.error).split(":")[0]
        errors_by_kind[kind] = errors_by_kind.get(kind, 0) + 1
    model_mb = round(candidate.model_path.stat().st_size / (1024 * 1024), 2)
    return {
        "candidate": candidate.label,
        "baseline": baseline_label,
        "corpus_version": version,
        "n_frames": n,
        "filter": filter_desc,
        "label_space": label_space,
        "excluded": excluded if excluded is not None else excluded_block([], True),
        "primary": {
            "r_at_1_eq": _rate(sum(p.correct_eq_top1 for p in preds), n),
            "r_at_5_eq": _rate(sum(p.correct_eq_top5 for p in preds), n),
            "r_at_1_strict": _rate(sum(p.correct_strict_top1 for p in preds), n),
            "r_at_1_on_covered": _rate(
                sum(p.correct_eq_top1 for p in covered), len(covered)
            ),
            "n_on_covered": len(covered),
        },
        "by_condition": by_condition,
        "errors": {
            "n": len(errored),
            "rate": _rate(len(errored), n),
            "by_kind": errors_by_kind,
        },
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


def label_mesh(class_ids: set[str], equivalence) -> set[str]:
    """Les ``class_id`` ramenés à la maille où la correction est jugée.

    ``COALESCE(design_group, eurio_id)`` : deux candidats entraînés l'un en
    ``eurio_id`` et l'autre en ``design_group`` ne sont pas différents pour
    autant. Sans équivalence chargée, la maille EST ``eurio_id``.
    """
    if equivalence is None:
        return set(class_ids)
    return {equivalence.coalesce(i) or i for i in class_ids}


def mesh_digest(mesh: set[str]) -> str:
    """Empreinte stable d'un espace de labels — 16 hex de SHA-256.

    Pourquoi une empreinte et pas un compte : deux candidats à 60 classes
    CHACUN peuvent porter deux ensembles de 60 classes différents. Un compte
    les déclarerait comparables. C'est précisément la confusion qui rend un
    McNemar illisible, et elle est invisible à l'œil.
    """
    joint = "\n".join(sorted(mesh)).encode("utf-8")
    return hashlib.sha256(joint).hexdigest()[:16]


def assert_same_label_space(
    candidate: Candidate, baseline: Candidate, equivalence
) -> None:
    """Refuse de comparer deux candidats qui ne jouent pas au même jeu.

    Un McNemar apparié croise des verdicts frame par frame : si une classe est
    dans l'espace de l'un et pas de l'autre, chaque frame de cette classe est
    perdue d'avance pour un seul des deux. Le test reste « valide » et mesure
    en réalité l'écart des cohortes, pas l'écart des modèles. **Un garde qui
    refuse vaut mieux qu'un p-value qu'on ne saura pas relire.**

    La comparaison se fait sur la maille où la correction est jugée
    (``COALESCE(design_group, eurio_id)``) : deux candidats entraînés l'un en
    ``eurio_id`` et l'autre en ``design_group`` ne sont PAS différents pour
    autant.
    """
    def mesh(cand: Candidate) -> set[str]:
        return label_mesh(centroid_class_ids(cand.centroids_path), equivalence)

    cand_mesh, base_mesh = mesh(candidate), mesh(baseline)
    if cand_mesh == base_mesh:
        return
    only_cand = sorted(cand_mesh - base_mesh)
    only_base = sorted(base_mesh - cand_mesh)

    def sample(ids: list[str]) -> str:
        head = ", ".join(ids[:5])
        return head + (f", … (+{len(ids) - 5})" if len(ids) > 5 else "")

    raise SystemExit(
        "Espaces de labels différents — comparaison REFUSÉE.\n"
        f"  candidat {candidate.label} : {len(cand_mesh)} classes\n"
        f"  baseline {baseline.label} : {len(base_mesh)} classes\n"
        f"  {len(only_cand)} seulement chez le candidat : {sample(only_cand)}\n"
        f"  {len(only_base)} seulement chez la baseline : {sample(only_base)}\n"
        "Le McNemar croiserait alors l'écart des COHORTES, pas celui des "
        "modèles. Recalcule les centroïdes des deux candidats sur le même "
        "ensemble de classes, puis relance."
    )


# ─── Comparer DEUX runs déjà notés — le trou du garde, et sa fermeture ──────
#
# `assert_same_label_space` ne s'exécute que si `--baseline` est passé. Deux
# runs notés séparément, puis comparés à la main, passaient donc sans un mot :
# le garde se contournait en ne l'appelant pas. Ce n'est pas un oubli qu'on
# corrige par de la discipline — une comparaison à la main N'A PAS de garde,
# quelle que soit la bonne volonté de celui qui la fait.
#
# La fermeture a deux moitiés, et il faut les deux :
#
#   1. chaque scorecard porte désormais l'EMPREINTE de son espace de labels
#      (`label_space.mesh_digest`) — l'écart devient visible dans l'artefact,
#      même six mois plus tard, même sans relancer quoi que ce soit ;
#   2. `--compare A B` donne un chemin de comparaison qui, lui, PASSE par le
#      garde, et rend le McNemar apparié. Tant qu'il n'existait pas, la
#      comparaison à la main était la seule option — donc la contourner
#      n'était pas une négligence, c'était le seul geste disponible.


def load_predictions(path: Path) -> list[FramePrediction]:
    """Relit un ``predictions.jsonl`` écrit par un run précédent."""
    preds: list[FramePrediction] = []
    with Path(path).open(encoding="utf-8") as fh:
        for ligne in fh:
            ligne = ligne.strip()
            if not ligne:
                continue
            d = json.loads(ligne)
            preds.append(FramePrediction(
                capture_id=d["capture_id"],
                eurio_id=d["eurio_id"],
                condition=d["condition"],
                top5=[(c, s) for c, s in d.get("top5", [])],
                abstained=bool(d["abstained"]),
                correct_strict_top1=bool(d["correct_strict_top1"]),
                correct_eq_top1=bool(d["correct_eq_top1"]),
                correct_eq_top5=bool(d["correct_eq_top5"]),
                error=d.get("error"),
                coverable=bool(d.get("coverable", True)),
            ))
    return preds


def assert_comparable_runs(a: dict, b: dict, *, a_nom: str, b_nom: str) -> None:
    """Refuse de croiser deux scorecards qui ne notent pas la même chose.

    Trois refus, et chacun a coûté une mesure illisible quelque part :

    * **espace de labels différent** — un McNemar apparié croise des verdicts
      frame par frame ; une classe présente chez l'un seulement rend chaque
      frame de cette classe perdue d'avance pour un seul des deux. Le test
      reste « valide » et mesure l'écart des COHORTES ;
    * **corpus différent** — même modèle, deux jeux : le delta ne dit rien ;
    * **filtre différent** — `include_rejected`, les conditions, la cohorte…
      ce sont les réglages qui CHANGENT le jeu noté.

    Et un quatrième, moins évident : une scorecard **sans empreinte** (notée
    avant que le garde n'existe) n'est pas « probablement compatible », elle
    est **non vérifiable**. On refuse aussi — sinon la seule scorecard qu'on
    ne peut pas contrôler serait la seule à passer.
    """
    ecarts: list[str] = []

    da = (a.get("label_space") or {}).get("mesh_digest")
    db = (b.get("label_space") or {}).get("mesh_digest")
    if da is None or db is None:
        manquants = [n for n, d in ((a_nom, da), (b_nom, db)) if d is None]
        ecarts.append(
            "empreinte d'espace de labels ABSENTE de "
            f"{', '.join(manquants)} — scorecard notée avant le garde. "
            "Non vérifiable n'est pas compatible : rejoue le run."
        )
    elif da != db:
        la = a.get("label_space") or {}
        lb = b.get("label_space") or {}
        ecarts.append(
            f"espaces de labels DIFFÉRENTS : {a_nom} {da} "
            f"({la.get('n_mesh_classes')} classes, maille "
            f"{la.get('mesh_basis')}) ≠ {b_nom} {db} "
            f"({lb.get('n_mesh_classes')} classes, maille "
            f"{lb.get('mesh_basis')})"
        )

    if a.get("corpus_version") != b.get("corpus_version"):
        ecarts.append(
            f"corpus DIFFÉRENTS : {a_nom} version "
            f"{a.get('corpus_version')} ≠ {b_nom} version "
            f"{b.get('corpus_version')}"
        )

    if a.get("filter") != b.get("filter"):
        ecarts.append(
            f"filtres DIFFÉRENTS :\n      {a_nom} : {a.get('filter')}\n"
            f"      {b_nom} : {b.get('filter')}"
        )

    if not ecarts:
        return
    raise SystemExit(
        "Comparaison REFUSÉE — ces deux runs ne notent pas la même chose.\n"
        + "".join(f"  · {e}\n" for e in ecarts)
        + "Un McNemar croiserait alors l'écart des CONDITIONS, pas celui des "
          "modèles. Rejoue les deux runs sur le même corpus, le même filtre et "
          "le même ensemble de classes."
    )


def compare_runs(dir_a: Path, dir_b: Path) -> dict:
    """Croise deux runs déjà notés — APRÈS le garde, jamais avant.

    ``dir_a`` est la baseline, ``dir_b`` le candidat (même orientation que
    ``crossed_stats``). Rend le bloc McNemar, et le grave à côté.
    """
    card_a = json.loads((dir_a / "scorecard.json").read_text(encoding="utf-8"))
    card_b = json.loads((dir_b / "scorecard.json").read_text(encoding="utf-8"))
    assert_comparable_runs(
        card_a, card_b,
        a_nom=card_a.get("candidate") or dir_a.name,
        b_nom=card_b.get("candidate") or dir_b.name,
    )
    preds_a = load_predictions(dir_a / "predictions.jsonl")
    preds_b = load_predictions(dir_b / "predictions.jsonl")
    stats = crossed_stats(preds_a, preds_b)
    res = {
        "baseline": card_a.get("candidate"),
        "candidate": card_b.get("candidate"),
        "corpus_version": card_a.get("corpus_version"),
        "label_space": (card_a.get("label_space") or {}).get("mesh_digest"),
        "baseline_primary": card_a.get("primary"),
        "candidate_primary": card_b.get("primary"),
        "mcnemar": stats,
    }
    # La trace appartient à l'OPÉRATION, pas à la CLI : une comparaison faite
    # depuis un notebook doit laisser le même artefact qu'une comparaison faite
    # au terminal, sinon elle n'est relisible que par celui qui l'a lancée.
    (dir_b / "comparison.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return res


# ─── Main ───────────────────────────────────────────────────────────────────


def _write_predictions(path: Path, preds: list[FramePrediction]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for p in preds:
            fh.write(json.dumps(p.to_json(), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate", type=Path, default=None, help="dossier candidat")
    source.add_argument(
        "--compare",
        type=Path,
        nargs=2,
        metavar=("RUN_BASELINE", "RUN_CANDIDAT"),
        default=None,
        help=(
            "croise DEUX runs déjà notés (deux dossiers de sortie), en passant "
            "par le garde d'espace de labels. C'est le chemin à prendre quand "
            "les deux runs ont été notés séparément : sans lui, la comparaison "
            "se fait à la main et AUCUN garde ne s'exécute."
        ),
    )
    source.add_argument(
        "--iteration",
        default=None,
        help=(
            "id d'itération du lab (ml/lab/iterations/<iid>) : le candidat est "
            "construit depuis checkpoints/best_model.pth + "
            "embeddings/embeddings_v1.json. Pour filtrer le CORPUS par "
            "provenance, c'est --source-iteration-id."
        ),
    )
    parser.add_argument(
        "--iteration-model",
        choices=ITERATION_MODEL_KINDS,
        default="checkpoint",
        help="artefact de l'itération à noter (défaut : checkpoint = best_model.pth)",
    )
    parser.add_argument(
        "--lab-root",
        type=Path,
        default=None,
        help="override de ml/lab/iterations (tests)",
    )
    parser.add_argument("--candidate-label", default=None)
    parser.add_argument("--baseline", type=Path, default=None, help="dossier baseline (§9)")
    parser.add_argument("--baseline-label", default=None)
    parser.add_argument("--cohort-id", default=None)
    parser.add_argument("--conditions", default=None, help="csv, ex. bright,dim,tilt")
    parser.add_argument(
        "--bundle-source",
        default=None,
        help=(
            "csv de protocoles de prise de vue, ex. "
            "device_pull_20260429,device_pull_20260601. Deux protocoles partagent "
            "des noms d'étape : c'est le SEUL filtre qui les sépare."
        ),
    )
    parser.add_argument(
        "--source-iteration-id",
        dest="source_iteration_id",
        default=None,
        help=(
            "filtre du CORPUS sur scan_corpus.source_iteration_id (provenance "
            "des frames). Ne construit aucun candidat — cf. --iteration."
        ),
    )
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
    parser.add_argument(
        "--include-rejected",
        action="store_true",
        help=(
            "note AUSSI les captures écartées à la main (eval_decision="
            "'exclude'). DIAGNOSTIC uniquement : le défaut est de ne pas les "
            "noter — c'est le sens du geste du PO."
        ),
    )
    args = parser.parse_args()

    if args.compare:
        # Chemin de comparaison PURE : aucune inférence, aucun modèle chargé.
        # Le garde s'exécute en premier — refuser après coup laisserait sur
        # l'écran des chiffres qu'on serait tenté de lire quand même.
        dir_a, dir_b = args.compare
        res = compare_runs(dir_a, dir_b)
        mc = res["mcnemar"]
        print(f"baseline  : {res['baseline']}")
        print(f"candidat  : {res['candidate']}")
        print(f"corpus    : version {res['corpus_version']} · "
              f"espace de labels {res['label_space']}")
        print(f"r@1 (eq)  : {res['baseline_primary'].get('r_at_1_eq')} → "
              f"{res['candidate_primary'].get('r_at_1_eq')}")
        print(f"McNemar   : n_paired={mc['n_paired']} "
              f"discordants={mc['n_discordant']} p={mc['p_value']}")
        print(f"            {mc['contingency']}")
        print(f"écrit     : {dir_b / 'comparison.json'}")
        return

    store = ScanCorpusStore(db_path=args.db)
    conditions = args.conditions.split(",") if args.conditions else None
    bundle_sources = args.bundle_source.split(",") if args.bundle_source else None
    common = dict(
        cohort_id=args.cohort_id,
        conditions=conditions,
        source_iteration_id=args.source_iteration_id,
        bundle_sources=bundle_sources,
    )
    # DEUX lectures du MÊME filtre, et la différence est DÉRIVÉE, jamais
    # ré-implémentée : le prédicat « écartée » vit dans le SQL du store et
    # nulle part ailleurs. Le rejouer ici en Python le ferait dériver le jour
    # où la colonne gagne une troisième valeur.
    pool = store.list_captures(**common)
    kept = store.list_captures(**common, exclude_rejected=True)
    kept_ids = {c.capture_id for c in kept}
    rejected = [c for c in pool if c.capture_id not in kept_ids]
    captures = pool if args.include_rejected else kept

    if not captures:
        raise SystemExit(
            "Corpus vide pour ce filtre — rien à rejouer."
            + (
                f" ({len(rejected)} capture(s) écartée(s) à la main ; "
                "--include-rejected pour les noter quand même)"
                if rejected
                else ""
            )
        )

    # 🔴 LA VERSION PORTE L'ENSEMBLE RÉELLEMENT NOTÉ, jamais le pool brut.
    # Exclure des captures rend le jeu noté dépendant d'une décision humaine
    # MUTABLE : deux runs à deux jours d'écart peuvent noter des ensembles
    # différents. C'est exactement le défaut que ``review.bench_gold`` a été
    # écrit pour tuer. Si ``corpus_version`` était calculée sur ``pool``, deux
    # scorecards porteraient la même version en ayant noté des jeux
    # différents — et ce serait INDÉTECTABLE.
    version = corpus_version([c.capture_id for c in captures])
    excluded = excluded_block(rejected, active=not args.include_rejected)
    # Un filtre qui n'apparaît pas dans la scorecard est un filtre qu'on
    # oubliera : ``bundle_source`` y figure au même titre que les autres, et
    # ``include_rejected`` avec eux — c'est LE réglage qui change le jeu noté.
    filter_desc = {
        "cohort_id": args.cohort_id,
        "conditions": conditions,
        "source_iteration_id": args.source_iteration_id,
        "bundle_sources": bundle_sources,
        "include_rejected": bool(args.include_rejected),
    }
    if rejected:
        verbe = "notée(s) QUAND MÊME" if args.include_rejected else "NON notée(s)"
        print(
            f"⚖️  {len(rejected)} capture(s) écartée(s) à la main → {verbe} "
            f"({len(captures)} frames au total)"
        )

    if args.no_eq:
        equivalence = None
    else:
        from training.eval.equivalence import build_equivalence_map

        equivalence = build_equivalence_map(db_path=args.eq_db)

    if args.iteration:
        candidate = candidate_from_iteration(
            args.iteration,
            lab_root=args.lab_root,
            label=args.candidate_label,
            model_kind=args.iteration_model,
        )
    else:
        candidate = load_candidate(args.candidate, args.candidate_label)
    cand_class_ids = centroid_class_ids(candidate.centroids_path)

    # Le garde d'espace de labels s'exécute AVANT la première inférence : il ne
    # lit que deux JSON de centroïdes. Refuser après 20 s de replay laisserait
    # sur disque des prédictions qu'on serait tenté de lire quand même.
    baseline = load_candidate(args.baseline, args.baseline_label) if args.baseline else None
    if baseline is not None:
        assert_same_label_space(candidate, baseline, equivalence)

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
    if baseline is not None:
        baseline_label = baseline.label
        print(f"Baseline : {baseline.label} ({baseline.model_path.name})")
        base_preds = replay_candidate(
            baseline, captures, store.frames_root, equivalence, args.path
        )
        _write_predictions(out_dir / "predictions.baseline.jsonl", base_preds)
        scorecard = build_scorecard(
            candidate, cand_preds, baseline_label, filter_desc, version,
            cand_class_ids, excluded, equivalence=equivalence,
        )
        baseline_scorecard = build_scorecard(
            baseline,
            base_preds,
            None,
            filter_desc,
            version,
            centroid_class_ids(baseline.centroids_path),
            excluded,
            equivalence=equivalence,
        )
        scorecard["size"]["delta_vs_baseline_mb"] = round(
            scorecard["size"]["model_mb"] - baseline_scorecard["size"]["model_mb"], 2
        )
        scorecard["baseline_primary"] = baseline_scorecard["primary"]
        scorecard["baseline_by_condition"] = baseline_scorecard["by_condition"]
        scorecard["mcnemar"] = crossed_stats(base_preds, cand_preds)
    else:
        scorecard = build_scorecard(
            candidate, cand_preds, None, filter_desc, version, cand_class_ids,
            excluded, equivalence=equivalence,
        )

    (out_dir / "scorecard.json").write_text(
        json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nScorecard → {out_dir / 'scorecard.json'}")
    print(json.dumps(scorecard["primary"], indent=2))
    ls = scorecard["label_space"]
    print(
        f"Espace de labels : {ls['n_candidate_classes']} classes au candidat, "
        f"{ls['n_ground_truth_classes']} en vérité terrain, "
        f"{ls['n_covered_classes']} couvertes."
    )
    ex = scorecard["excluded"]
    if ex["n"]:
        etat = "NON notées" if ex["active"] else "notées (--include-rejected)"
        print(f"⚖️  Écartées à la main : {ex['n']} capture(s), {etat}.")
        for raison, n in ex["by_reason"].items():
            print(f"      {n}× {raison}")
    if ls["n_uncoverable_classes"]:
        print(
            f"⚠️  {ls['n_frames_uncoverable']}/{scorecard['n_frames']} frames sont "
            f"FAUSSES PAR CONSTRUCTION ({ls['n_uncoverable_classes']} classes hors "
            "du candidat) : lis r_at_1_on_covered, pas r_at_1_eq."
        )
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
