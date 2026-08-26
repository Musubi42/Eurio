"""Bench encodeurs zero-shot sur un GOLD FIGÉ (offline).

Ré-encode une banque d'ancres (on reprend ses ``source_paths``) ET les crops
d'un gold figé avec chaque encodeur, puis mesure recall@1/@5 global et bande
pays sur les crops in-scope.

DEUX COUPLES (gold, banque) AUJOURD'HUI — ET ILS VONT ENSEMBLE
---------------------------------------------------------------
==================================== =============== ==========================
--gold                                --anchors-kind  ce qu'on mesure
==================================== =============== ==========================
``encoder_bench_gold.jsonl`` (défaut) ``2eur_all``    tout ce que la review a
                                                      tranché, contre la banque
                                                      SERVIE (1 958 crops,
                                                      188 classes / 671)
``matrice_eval_gold.jsonl``           ``matrice60``   le hold-out de la matrice
                                                      d'encodeurs (300 crops,
                                                      60 classes / 60)
==================================== =============== ==========================

🔴 **Les deux arguments se choisissent ENSEMBLE.** Une banque qui ne couvre pas
les classes du gold ferait partir ses crops en ``n_out_of_scope`` : le recall
serait calculé sur un dénominateur que personne n'a choisi, et il resterait
parfaitement plausible. Mesuré sur le mauvais couple (gold de review contre
``matrice60``) : **822 frames sur 1 958, soit 42 %**, disparaîtraient. D'où
``assert_gold_covered_by_bank``, qui refuse **avant le premier encodage** —
refuser après vingt minutes de calcul laisserait sur disque des chiffres qu'on
serait tenté de lire quand même.

CE QUE CE BANC LIT, ET CE QU'IL N'ÉCRIT PAS
-------------------------------------------
* Il lit le **gold figé et versionné** ``state/validation_gold/
  encoder_bench_gold.jsonl`` + son sidecar. Il ne rejoue **plus** sa propre
  requête SQL de sélection : deux définitions concurrentes du jeu
  d'évaluation, c'était la seule contradiction inter-modules du chantier
  (D5). Le jeu bouge maintenant en un seul endroit, et son ``gold_version``
  part avec chaque run.
* Il ne lit **aucune prédiction stockée** : la banque et les crops sont
  ré-encodés à chaque run. Conséquence directe, et c'est le cœur du câblage
  de la bannière ci-dessous : **le classement des encodeurs (recall@1/@5) ne
  dépend PAS du backfill P3**. Seule la CALIBRATION DES SEUILS en dépend.
* Il n'écrit ni en base locale ni dans les ``.npz``. La trace du run monte au
  canonique par ``POST /ingest/encoder-bench`` (Direction A : la base locale
  est une réplique en lecture seule — cf. skill ``eurio-data-writes``).

LA BANNIÈRE (D4)
----------------
``store.encoder_bench.calibration_blockers`` mesure en SQL ce qui interdit de
promouvoir un seuil (P3 : prédictions périmées ou fraîcheur non prouvable ;
P1 : banque amputée ; échantillon : run sur une partie du gold). Tant qu'un
bloqueur subsiste :

* la bannière ``⚠ CALIBRATION PROVISOIRE`` est imprimée **en tête ET en pied**
  de la sortie, et recopiée dans le rapport Markdown ;
* le seuil n'est **pas** proposé (``propose_threshold`` lève
  ``CalibrationBlocked``) sauf ``--allow-provisional``, qui le rend marqué ;
* le run est poussé avec ``provisional=1`` et sa raison.

L'avertissement vivait dans le ``desc:`` de la tâche go-task, que ``go-task``
n'imprime pas à l'exécution. Un garde qu'on ne voit pas n'est pas un garde.

CE QUE LE BANC REFUSE DE TAIRE (N1, N2)
---------------------------------------
* **N1 — un crop soumis et non encodé n'est pas un crop évalué.** Les images
  présentes en cache mais rejetées par ``encode_paths`` (JPEG tronqué, EXIF
  cassé, OOM) sont comptées (``n_not_encoded``), imprimées, portées au rapport
  et **retirées de la couverture du gold** : le run devient un échantillon, donc
  ``provisional=1``. Le chemin voisin (crops absents du cache) l'était déjà —
  les deux chemins de perte sont alignés.
* **N2 — un encodeur qui explose n'est pas un succès.** Son échec est journalisé
  sur stderr, **recopié dans le rapport et dans la bannière de pied** (stderr
  n'est pas capturé par ``--out``), il disparaît de la table des résultats, et
  le banc sort en **code 1**. Un banc de nuit sur 4 encodeurs dont 3 tombent ne
  doit pas rendre ``exit=0`` et un rapport à une ligne.

Deux familles de specs :
  - noms torch.hub DINOv2 (``dinov2_vits14``, ``dinov2_vitl14``…) —
    transform foundation (224, ImageNet) ;
  - ``timm:<model_name>`` — n'importe quel backbone timm pré-entraîné
    (TinyViT, EfficientFormer, MobileViT, RepViT…), avec SA transform
    recommandée (résolution/normalisation par modèle). Sert au bench des
    candidats STUDENTS ArcFace on-device : le ranking zero-shot est un
    proxy du potentiel post-fine-tune (cf. phase1-delivery.md).

Usage:
    .venv/bin/python -m scripts.bench_encoder_dino
    .venv/bin/python -m scripts.bench_encoder_dino --models dinov2_vits14 timm:tiny_vit_21m_224.dist_in22k_ft_in1k
    .venv/bin/python -m scripts.bench_encoder_dino --limit 200 --no-push --out bench.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from training.foundation import (  # noqa: E402
    DINOV2_REPO,
    AnchorBank,
    anchor_path,
    build_transform,
    encode_paths,
    encoder_slug,
    load_anchors,
    pick_device,
    top_k_match,
    top_k_match_country,
)
from review.bench_gold import (  # noqa: E402
    DEFAULT_GOLD,
    GoldCrop,
    load_gold,
    load_meta,
    resolve_local_paths,
)
from shared.stats import (  # noqa: E402
    CalibrationBlocked,
    curve_to_json,
    paired_compare,
    precision_coverage_curve,
    propose_threshold,
)
from store import resolve_db_path  # noqa: E402
from store.encoder_bench import (  # noqa: E402
    EncoderBenchPrediction,
    EncoderBenchRun,
    calibration_blockers,
)


def default_db() -> Path:
    """La base à LIRE pour les bloqueurs, ``EURIO_DB_PATH`` d'abord.

    N6 — le repli quand l'env est absent (shell hors direnv) est la
    **réplique**, pas ``state/eurio.db``. Cette dernière est une base de
    travail pré-flip qui peut être périmée de plusieurs milliers de lignes :
    mesurée le 2026-08-19, 6205 ``image_assets`` contre 12454 dans la
    réplique ::

        for f in state/eurio.db state/eurio.replica.db; do
          echo -n "$f "; sqlite3 "file:$f?mode=ro" \
            "SELECT COUNT(*) FROM image_assets"; done

    Un bloqueur mesuré sur la base périmée est un bloqueur mesuré sur le
    mauvais monde — c'est exactement le défaut D-racine du jour
    (``build_dino_anchors``). Même convention que
    ``scripts/build_scan_prescription.default_db()`` (D12) : **tout lecteur
    seul se replie sur la réplique**, qui est par construction le miroir du
    canonique ; seuls les écrivains locaux visent une base inscriptible.

    Résolu à l'appel, pas à l'import : un test qui pose ``EURIO_DB_PATH``
    doit être entendu.
    """
    return resolve_db_path(ML_DIR / "state" / "eurio.replica.db")


BENCH_KIND = "2eur_all"
TOP_K = 5

#: Où atterrit un run que la sync n'a pas pu remonter. Un fichier local, jamais
#: une écriture en base : sous Direction A elle échouerait à la dernière ligne,
#: après tout le calcul.
PENDING_DIR = ML_DIR / "state" / "encoder_bench_pending"

_RULE = "=" * 78


# ─── Identité de l'encodeur ──────────────────────────────────────────────────


def encoder_version_of(spec: str) -> str:
    """La spec CLI → le nom canonique stocké dans les ``.npz`` et en base.

    ``dinov2_vitl14`` (nom torch.hub, souligné) est stocké ``dinov2-vitl14``
    (cf. ``training.foundation.encoder.SUGGESTIONS_ENCODER_VERSION``) ; une
    spec ``timm:…`` se stocke telle quelle. Sans cette traduction, les
    bloqueurs seraient mesurés pour un ``encoder_version`` qui n'existe dans
    aucune table — donc « aucun build tracé », donc un faux bloqueur qui
    masquerait le vrai.
    """
    spec = spec.strip()
    if spec.startswith("timm:"):
        return spec
    return spec.replace("_", "-", 1)


def _slug(spec: str) -> str:
    """Fragment de ``run_id`` sûr pour une spec d'encodeur."""
    return encoder_slug(encoder_version_of(spec))


# ─── Le jeu d'évaluation : le gold figé, et rien d'autre ─────────────────────


def _hash_rank(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12], 16)


def select_sample(
    rows: Sequence[tuple[GoldCrop, Path]], limit: int | None
) -> list[tuple[GoldCrop, Path]]:
    """Sous-échantillon DÉTERMINISTE (hash de l'``asset_id``), retrié par id.

    Un échantillon tiré par ``[:limit]`` sur une liste triée par ``asset_id``
    prendrait toujours les mêmes pays (l'``asset_id`` n'est pas indépendant de
    la classe) ; le hash casse cette corrélation sans introduire de hasard non
    reproductible. Rejouer la commande rend le même échantillon.
    """
    ordered = sorted(rows, key=lambda t: t[0].asset_id)
    if limit is None or limit >= len(ordered):
        return ordered
    picked = sorted(ordered, key=lambda t: _hash_rank("sample", t[0].asset_id))[:limit]
    return sorted(picked, key=lambda t: t[0].asset_id)


# ─── La bannière (D4) ────────────────────────────────────────────────────────


def blocker_banner(
    blockers_by_model: dict[str, list[str]],
    failures: Sequence[tuple[str, str]] | None = None,
) -> list[str]:
    """Les lignes à imprimer en tête ET en pied. Jamais vide.

    Le cas « rien à signaler » rend lui aussi une ligne : l'absence de
    bannière ne doit pas pouvoir se confondre avec une bannière oubliée.

    ``failures`` (N2) — les encodeurs qui ont **levé** pendant le bench. Un
    banc amputé ne peut pas se déclarer promouvable : le message d'échec ne
    vivait que sur stderr, le flux que ``--out`` ne capture pas, et la
    bannière — calculée avant le bench sur ``args.models`` — continuait de
    nommer le tombé comme s'il avait été évalué.
    """
    failures = list(failures or [])
    blocked = {m: b for m, b in blockers_by_model.items() if b}
    if not blocked and not failures:
        return [
            "✔ CALIBRATION PROMOUVABLE — aucun bloqueur mesuré "
            f"(store.encoder_bench.calibration_blockers, kind={BENCH_KIND})."
        ]
    lines = [
        _RULE,
        "⚠ CALIBRATION PROVISOIRE — NE PAS RECOPIER CES SEUILS DANS dino_thresholds",
        "",
    ]
    if failures:
        lines.append("  ENCODEURS TOMBÉS — non évalués, absents de la table :")
        lines.extend(f"    - {model} : {err}" for model, err in failures)
        lines.append("")
    for model, blockers in blocked.items():
        lines.append(f"  {model} :")
        lines.extend(f"    - {b}" for b in blockers)
    lines += [
        "",
        "  Ce qui reste VALIDE malgré ces bloqueurs : le classement des",
        "  encodeurs (recall@1/@5, bande pays). Le banc ré-encode la banque et",
        "  les crops à chaque run, il ne lit aucune prédiction stockée — P3 ne",
        "  peut donc pas le fausser.",
        "  Ce qui est BLOQUÉ : la proposition de seuil (spread_at_p97), qui se",
        "  lit sur des prédictions et une banque dont la fraîcheur n'est pas",
        "  prouvée. --allow-provisional rend le chiffre, marqué provisoire.",
        _RULE,
    ]
    return lines


# ─── Le bench proprement dit ─────────────────────────────────────────────────


def _load_model(spec: str, device) -> tuple[Any, Any, int, int]:
    """Charge un encodeur d'après sa spec → (model, transform, n_params, input_px).

    ``timm:<name>`` charge via timm avec la transform recommandée du modèle
    (num_classes=0 → features poolées) ; sinon torch.hub DINOv2 + transform
    foundation (224).
    """
    if spec.startswith("timm:"):
        import timm
        name = spec[len("timm:"):]
        model = timm.create_model(name, pretrained=True, num_classes=0)
        cfg = timm.data.resolve_model_data_config(model)
        transform = timm.data.create_transform(**cfg, is_training=False)
        input_px = cfg["input_size"][-1]
    else:
        model = torch.hub.load(DINOV2_REPO, spec, pretrained=True)
        transform = build_transform()
        input_px = 224
    model.eval()
    model.to(device)
    n_params = sum(p.numel() for p in model.parameters())
    return model, transform, n_params, input_px


def score_crops(
    bank: AnchorBank,
    crops: Sequence[tuple[GoldCrop, Path]],
    kept_index: dict[str, int],
    crop_matrix: np.ndarray,
) -> tuple[list[EncoderBenchPrediction], dict[str, Any]]:
    """Note chaque crop du gold contre ``bank`` → (prédictions, agrégats).

    La vérité comparée au top-1 est ``GoldCrop.class_id``, **pas**
    ``GoldCrop.truth_eurio_id`` : la banque indexe une pièce sous le représentant
    de son ``design_group`` quand il en existe un (cf. ``review.bench_gold.
    _bank_class_id``). Comparer au ``truth_eurio_id`` compterait faux toutes
    les pièces représentées par un frère. La colonne persistée s'appelle donc
    ``EncoderBenchPrediction.truth_class_id`` (renommée le 2026-08-19, D5) :
    elle doit rester comparable à ``top1_eurio_id``, qui sort de la banque.

    La bande pays vient de ``GoldCrop.truth_country`` — l'ISO2 de la décision
    de review, pas celui de la cible du listing eBay (D6).
    """
    bank_ids = set(bank.eurio_ids)
    preds: list[EncoderBenchPrediction] = []
    n_in_scope = 0
    n_out_of_scope = 0
    n_not_encoded = 0
    g1 = g5 = 0
    c_total = c1 = c5 = 0
    for crop, path in crops:
        idx = kept_index.get(str(path))
        if idx is None:
            n_not_encoded += 1
            continue
        if crop.class_id not in bank_ids:
            n_out_of_scope += 1
            continue
        n_in_scope += 1
        vec = crop_matrix[idx]
        matches = top_k_match(vec, bank, top_k=TOP_K)
        ranked = [m.eurio_id for m in matches]
        correct = bool(ranked and ranked[0] == crop.class_id)
        in_top5 = crop.class_id in ranked
        g1 += int(correct)
        g5 += int(in_top5)
        top1_sim = float(matches[0].sim) if matches else None
        top2_sim = float(matches[1].sim) if len(matches) > 1 else None
        spread = (
            top1_sim - top2_sim
            if top1_sim is not None and top2_sim is not None
            else None
        )
        country_top1 = None
        country_correct = None
        cm = top_k_match_country(
            vec, bank, target_country=crop.truth_country, top_k=TOP_K
        )
        if cm:
            c_total += 1
            cranked = [m.eurio_id for m in cm]
            country_top1 = cranked[0]
            country_correct = int(cranked[0] == crop.class_id)
            c1 += country_correct
            c5 += int(crop.class_id in cranked)
        preds.append(
            EncoderBenchPrediction(
                asset_id=crop.asset_id,
                truth_class_id=crop.class_id,
                correct=int(correct),
                in_top5=int(in_top5),
                top1_eurio_id=ranked[0] if ranked else None,
                top1_sim=top1_sim,
                top2_sim=top2_sim,
                spread=spread,
                country_top1_eurio_id=country_top1,
                country_correct=country_correct,
            )
        )
    agg = {
        "n_in_scope": n_in_scope,
        "n_out_of_scope": n_out_of_scope,
        "n_not_encoded": n_not_encoded,
        "g1": g1,
        "g5": g5,
        "c_total": c_total,
        "c1": c1,
        "c5": c5,
    }
    return preds, agg


def _bench_model(
    spec: str,
    anchor_eids: list[str],
    anchor_paths: list[Path],
    crops: Sequence[tuple[GoldCrop, Path]],
    anchors_kind: str = BENCH_KIND,
) -> dict:
    device = pick_device()
    print(f"\n=== {spec} on {device} ===", file=sys.stderr)
    t0 = time.perf_counter()
    encoder, transform, n_params, input_px = _load_model(spec, device)
    t_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    kept_anchor_paths, anchor_matrix = encode_paths(
        anchor_paths, encoder=encoder, device=device, transform=transform
    )
    t_anchors = time.perf_counter() - t0
    kept_set = {str(p) for p in kept_anchor_paths}
    eids = [e for e, p in zip(anchor_eids, anchor_paths) if str(p) in kept_set]
    bank = AnchorBank(
        eurio_ids=eids,
        matrix=anchor_matrix,
        encoder_version=encoder_version_of(spec),
        anchors_kind=anchors_kind,
        built_at="bench",
    )

    t0 = time.perf_counter()
    crop_paths = [p for _c, p in crops]
    kept_crop_paths, crop_matrix = encode_paths(
        crop_paths, encoder=encoder, device=device, transform=transform
    )
    t_crops = time.perf_counter() - t0
    kept_index = {str(p): i for i, p in enumerate(kept_crop_paths)}

    preds, agg = score_crops(bank, crops, kept_index, crop_matrix)

    n_imgs = len(kept_anchor_paths) + len(kept_crop_paths)
    return {
        "model": spec,
        "encoder_version": bank.encoder_version,
        "anchors": bank.count,
        "n_bank_classes": len(set(bank.eurio_ids)),
        "dim": bank.dim,
        "params_m": n_params / 1e6,
        "input_px": input_px,
        "device": str(device),
        "preds": preds,
        "t_load": t_load,
        "t_encode": t_anchors + t_crops,
        "ms_per_img": 1000 * (t_anchors + t_crops) / max(n_imgs, 1),
        **agg,
    }


# ─── Trace du run ────────────────────────────────────────────────────────────


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ML_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def resolve_bank(kind: str):
    """La banque d'un ``kind``, sans jamais DEVINER sa version d'encodeur.

    Deux nommages coexistent : ``foundation_anchors_<kind>.npz`` (la banque
    servie du kind) et ``foundation_anchors_<kind>__<encodeur>.npz`` (les
    artefacts scopés). On essaie le premier, puis on RÉSOUT le second en
    listant ce qui est sur disque.

    Pourquoi cette fonction existe : la version précédente se repliait sur
    ``DEFAULT_ENCODER_VERSION``. Elle vaut ``dinov2-vits14`` — or la
    sous-banque de la matrice porte ``dinov2-vitl14``, celui de la banque
    source. Le repli cherchait donc un fichier qui n'a jamais existé et le
    banc rendait « banque introuvable » alors qu'elle était là, à côté.
    Deviner une version d'encodeur ne marche que par coïncidence.

    Plusieurs artefacts scopés → on REFUSE en les nommant : en choisir un
    ferait noter contre une banque que l'appelant n'a pas demandée, et le
    chiffre serait plausible.
    """
    bank = load_anchors(kind)
    if bank is not None:
        return bank

    scopes = sorted(anchor_path(kind, "x").parent.glob(
        f"foundation_anchors_{kind}__*.npz"))
    if not scopes:
        return None
    if len(scopes) > 1:
        raise SystemExit(
            f"Plusieurs artefacts pour le kind `{kind}` et aucun fichier "
            f"servi — impossible de choisir sans deviner :\n"
            + "".join(f"  · {p.name}\n" for p in scopes)
            + f"Rebâtis la banque servie du kind, ou passe le fichier voulu "
              f"en le renommant `foundation_anchors_{kind}.npz`."
        )
    from training.foundation.anchors import _peek_meta  # noqa: PLC0415

    meta = _peek_meta(scopes[0])
    return load_anchors(kind, meta.get("encoder_version"))


def assert_gold_covered_by_bank(gold, bank, *, gold_name: str, kind: str) -> None:
    """Refuse d'apparier un manifeste et une banque qui ne se recouvrent pas.

    ``score_crops`` écarte silencieusement un crop dont la classe n'est pas
    dans la banque (``n_out_of_scope``). C'est le bon comportement au moment de
    noter — mais si la MOITIÉ du gold y passe, le recall est calculé sur un
    dénominateur que personne n'a choisi, et il reste parfaitement plausible.

    Le garde s'exécute **avant le premier encodage**, comme
    ``assert_same_label_space`` : refuser après vingt minutes de calcul
    laisserait sur disque des chiffres qu'on serait tenté de lire quand même.

    Les classes de la banque ABSENTES du gold ne sont pas une erreur : ce sont
    les distracteurs, et c'est leur nombre qui fait la difficulté de la tâche.
    On les compte, on ne les refuse pas.
    """
    classes_gold = {c.class_id for c in gold}
    classes_bank = set(bank.eurio_ids)
    manquantes = sorted(classes_gold - classes_bank)
    if not manquantes:
        n_frames = len(gold)
        print(
            f"appariement OK : {len(classes_gold)} classes du gold toutes "
            f"présentes dans `{kind}` · {len(classes_bank) - len(classes_gold)} "
            f"classe(s) de banque en distracteurs · {n_frames} frames",
            file=sys.stderr,
        )
        return

    perdues = sum(1 for c in gold if c.class_id in set(manquantes))
    raise SystemExit(
        f"Manifeste et banque ne s'apparient pas — banc REFUSÉ.\n"
        f"  gold {gold_name} : {len(classes_gold)} classes\n"
        f"  banque {kind} : {len(classes_bank)} classes\n"
        f"  {len(manquantes)} classe(s) du gold ABSENTES de la banque, soit "
        f"{perdues} frames sur {len(gold)} "
        f"({perdues / len(gold):.1%}) : {manquantes[:5]}"
        f"{' …' if len(manquantes) > 5 else ''}\n"
        f"Ces frames partiraient en `out_of_scope` et disparaîtraient du "
        f"dénominateur : le recall serait calculé sur moins de classes "
        f"qu'annoncé — faux, pas partiel. Vérifie que --gold et "
        f"--anchors-kind sont le couple prévu."
    )


def _bank_build_id(conn: sqlite3.Connection, kind: str, encoder_version: str) -> str | None:
    """Le dernier ``dino_anchor_builds.build_id`` du couple, ou ``None``.

    ``None`` n'est pas rassurant : c'est exactement l'état que
    ``calibration_blockers`` transforme en bloqueur P3. Ici on se contente de
    le tracer.
    """
    try:
        row = conn.execute(
            "SELECT build_id FROM dino_anchor_builds "
            " WHERE anchors_kind = ? AND encoder_version = ? "
            " ORDER BY built_at DESC LIMIT 1",
            (kind, encoder_version),
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def build_run(
    result: dict,
    *,
    run_id: str,
    created_at: str,
    gold_version: str,
    gold_n_crops: int,
    gold_sample_n: int | None,
    blockers: Sequence[str],
    proposal_dict: dict | None,
    sweep_json: str | None,
    bank_build_id: str | None,
    baseline_run_id: str | None = None,
    mcnemar: Any | None = None,
    note: str | None = None,
    anchors_kind: str = BENCH_KIND,
) -> EncoderBenchRun:
    """Assemble la ligne ``encoder_bench_runs``. Fonction pure, donc testable.

    ``provisional`` suit les bloqueurs MESURÉS, jamais l'option
    ``--allow-provisional`` : cette option décide si l'opérateur voit le
    chiffre, pas s'il est promouvable.
    """
    blockers = [b for b in blockers if b]
    return EncoderBenchRun(
        run_id=run_id,
        created_at=created_at,
        gold_version=gold_version,
        gold_n_crops=gold_n_crops,
        gold_sample_n=gold_sample_n,
        # La banque NOTÉE, jamais une constante : deux runs contre deux banques
        # différentes seraient indiscernables dans `encoder_bench_runs`, et on
        # comparerait un recall à 60 classes avec un recall à 671.
        anchors_kind=anchors_kind,
        encoder_spec=result["model"],
        encoder_version=result["encoder_version"],
        n_in_scope=result["n_in_scope"],
        bank_build_id=bank_build_id,
        bank_n_anchors=result["anchors"],
        bank_n_classes=result["n_bank_classes"],
        embed_dim=result["dim"],
        n_params_m=result["params_m"],
        input_px=result["input_px"],
        device=result.get("device"),
        ms_per_img=result["ms_per_img"],
        recall1=_ratio(result["g1"], result["n_in_scope"]),
        recall5=_ratio(result["g5"], result["n_in_scope"]),
        country_n=result["c_total"],
        country_recall1=_ratio(result["c1"], result["c_total"]),
        country_recall5=_ratio(result["c5"], result["c_total"]),
        spread_at_p97=(proposal_dict or {}).get("threshold"),
        coverage_at_p97=(proposal_dict or {}).get("coverage"),
        precision_at_p97=(proposal_dict or {}).get("precision"),
        sweep_json=sweep_json,
        baseline_run_id=baseline_run_id,
        # b = le baseline seul a raison ; c = le candidat seul a raison.
        mcnemar_p=getattr(mcnemar, "p_value", None),
        mcnemar_b=getattr(mcnemar, "a_only", None),
        mcnemar_c=getattr(mcnemar, "b_only", None),
        # D16 : sur COMBIEN de paires b et c portent. Sans lui, un McNemar
        # calculé sur un recouvrement partiel est indiscernable d'un McNemar
        # complet. NULL quand il n'y a pas de baseline.
        n_paired=getattr(mcnemar, "n_paired", None),
        provisional=1 if blockers else 0,
        provisional_reason=" | ".join(blockers) or None,
        host=socket.gethostname(),
        git_commit=_git_commit(),
        note=note,
    )


def push_run(
    run: EncoderBenchRun,
    preds: Sequence[EncoderBenchPrediction],
    *,
    pending_dir: Path | None = None,
) -> tuple[bool, Path | None, str]:
    """Pousse le run au canonique. Rend ``(poussé, dump local, message)``.

    Aucun chemin ne perd le résultat en silence : sync désactivée ou POST en
    erreur, le payload est écrit sur disque et le message le dit. Deux heures
    de GPU ne doivent pas disparaître parce qu'un token a expiré.
    """
    from client.ingest import push_encoder_bench  # noqa: PLC0415

    # Résolu à l'appel : une valeur par défaut figée à la définition ne peut
    # plus être redirigée (test, machine sans state/ inscriptible).
    pending_dir = pending_dir or PENDING_DIR
    payload = {"run": run.to_dict(), "predictions": [p.to_dict() for p in preds]}
    try:
        res = push_encoder_bench(payload["run"], payload["predictions"])
    except Exception as exc:  # noqa: BLE001 — on rend la main, on ne se tait pas
        dump = _dump_pending(payload, pending_dir)
        return False, dump, f"!! POST /ingest/encoder-bench a échoué ({exc}) — payload gardé : {dump}"
    if res is None:
        dump = _dump_pending(payload, pending_dir)
        return False, dump, f"!! sync désactivée — run NON tracé au canonique, payload gardé : {dump}"
    # M2 — le canonique remesure le verdict et peut CORRIGER le payload (il
    # voit une base fraîche, le banc a mesuré sur la réplique). Sans cette
    # ligne, l'opérateur lit « ✔ CALIBRATION PROMOUVABLE » dans sa bannière
    # locale pendant que la table dit `provisional=1` : deux vérités, aucune
    # trace du désaccord côté banc. La réponse porte `corrections` ; on la
    # remonte au lieu de la laisser dans le `{res}` d'un f-string.
    corrections = res.get("corrections") if isinstance(res, dict) else None
    if corrections:
        return True, None, (
            f"→ run poussé : {run.run_id} — ⚠ CORRIGÉ PAR LE CANONIQUE : "
            + " ; ".join(str(c) for c in corrections)
            + f" (provisional en base = {res.get('provisional')})"
        )
    return True, None, f"→ run poussé : {run.run_id} ({res})"


def _dump_pending(payload: dict, pending_dir: Path) -> Path:
    pending_dir.mkdir(parents=True, exist_ok=True)
    out = pending_dir / f"{payload['run']['run_id']}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ─── Sortie ──────────────────────────────────────────────────────────────────


def _ratio(n: int, d: int) -> float | None:
    return (n / d) if d else None


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "—"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", nargs="+",
        default=["dinov2_vits14", "dinov2_vitl14"],
    )
    parser.add_argument(
        "--db", default=None,
        help="base à LIRE pour les bloqueurs de calibration ; défaut = "
             "store.resolve_db_path (EURIO_DB_PATH, sinon "
             f"state/eurio.replica.db) → {default_db()}",
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD,
                        help=f"manifeste figé (défaut : {DEFAULT_GOLD})")
    parser.add_argument(
        "--anchors-kind", default=BENCH_KIND,
        help=f"le `kind` de la banque d'ancres à noter (défaut : {BENCH_KIND}, "
             "la banque SERVIE). `matrice60` = la sous-banque des 60 classes "
             "du chantier juge-et-banc. ⚠️ Le kind et le --gold vont ENSEMBLE : "
             "une banque qui ne couvre pas les classes du manifeste ferait "
             "partir ses crops en `out_of_scope`, donc disparaître du "
             "dénominateur — c'est vérifié avant tout encodage.",
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="échantillon déterministe de N crops du gold — "
                             "marque le run comme non promouvable")
    parser.add_argument("--baseline", default=None,
                        help="spec du bras de référence pour McNemar "
                             "(défaut : le premier de --models)")
    parser.add_argument("--allow-provisional", action="store_true",
                        help="imprimer le seuil malgré les bloqueurs, marqué provisoire")
    parser.add_argument("--no-push", action="store_true",
                        help="ne pas tracer les runs au canonique")
    parser.add_argument("--note", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else default_db()

    base = resolve_bank(args.anchors_kind)
    if base is None or not base.source_paths:
        raise RuntimeError(
            f"Banque `{args.anchors_kind}` introuvable ou sans source_paths. "
            f"Pour `{BENCH_KIND}` : `go-task ml:dino-anchors:build`. Pour "
            f"`matrice60` : "
            f"`python -m scripts.build_matrice_subbank --apply`."
        )
    anchor_paths = [Path(p) for p in base.source_paths]

    # ── Le jeu d'évaluation : le gold figé, jamais une requête d'ici ──
    gold = load_gold(args.gold)
    meta = load_meta(args.gold)
    gold_version = meta["gold_version"]
    # L'emplacement des octets vient de la BASE, pas du manifeste : le gold
    # fige QUELS crops sont notés, pas OÙ ils sont rangés. Depuis le
    # déplacement des crops d'éval vers `eval-corpus` (D9), 208 des 1958
    # `storage_path` figés sont périmés — les suivre ferait perdre 10,6 % du
    # gold et basculerait le run en `provisional=1`.
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as _c:
        present, missing = resolve_local_paths(gold, _c)
    crops = select_sample(present, args.limit)
    gold_sample_n = len(crops) if len(crops) < len(gold) else None

    # Le couple (manifeste, banque) se vérifie AVANT le premier encodage.
    assert_gold_covered_by_bank(
        gold, base, gold_name=args.gold.name, kind=args.anchors_kind
    )

    print(
        f"gold {gold_version} : {len(gold)} crops figés · {len(present)} présents "
        f"en cache · {len(crops)} évalués · banque {base.count} ancres",
        file=sys.stderr,
    )
    if missing:
        print(
            f"  !! {len(missing)} crops du gold ABSENTS du cache local, exclus du "
            f"run (ex. {', '.join(missing[:3])}) — le run est donc un échantillon",
            file=sys.stderr,
        )

    # ── Les bloqueurs, mesurés en SQL, par encodeur ──
    # Mesurés DEUX fois : une fois avant le bench (bannière de tête, sur les
    # crops SOUMIS), une fois après (bannière de pied, rapport et trace, sur
    # les crops RÉELLEMENT encodés — cf. N1 plus bas).
    def _measure(
        models: Sequence[str],
        sample_by_model: dict[str, int | None],
        paired_by_model: dict[str, tuple[str | None, int | None]] | None = None,
    ) -> tuple[dict[str, list[str]], str | None]:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            blockers = {
                m: calibration_blockers(
                    conn,
                    anchors_kind=args.anchors_kind,
                    encoder_version=encoder_version_of(m),
                    gold_sample_n=sample_by_model.get(m),
                    gold_n_crops=len(gold),
                    baseline_run_id=(paired_by_model or {}).get(m, (None, None))[0],
                    n_paired=(paired_by_model or {}).get(m, (None, None))[1],
                )
                for m in models
            }
            build_id = _bank_build_id(conn, args.anchors_kind, base.encoder_version)
        finally:
            conn.close()
        return blockers, build_id

    blockers_by_model, bank_build_id = _measure(
        args.models, {m: gold_sample_n for m in args.models}
    )

    print("\n".join(blocker_banner(blockers_by_model)), file=sys.stderr)

    results = []
    failures: list[tuple[str, str]] = []
    for m in args.models:
        try:
            results.append(
                _bench_model(m, base.eurio_ids, anchor_paths, crops,
                             anchors_kind=args.anchors_kind)
            )
        except Exception as exc:  # noqa: BLE001 — un candidat KO ne tue pas le banc
            # N2 : le tombé est journalisé ICI (stderr, pour l'opérateur) ET
            # retenu, pour qu'il ressorte dans le rapport, dans la bannière de
            # pied et dans le code de sortie. Un `except` qui se contente de
            # stderr rend un banc à une ligne avec `exit=0`.
            print(f"!! {m} failed: {exc}", file=sys.stderr)
            failures.append((m, f"{type(exc).__name__}: {exc}"))
    if not results:
        raise RuntimeError("Aucun modèle benché avec succès.")

    # ── N1 : les crops perdus À L'ENCODAGE comptent comme les crops absents ──
    # ``score_crops`` compte dans ``n_not_encoded`` les crops présents sur
    # disque mais écartés par ``encode_paths`` (JPEG tronqué, EXIF cassé, OOM).
    # Ce compteur n'était lu par personne : un cache partiel ou une série
    # d'images corrompues rendait un recall publiable et faux, annoncé « gold
    # entier ». Le chemin VOISIN (crops absents du cache) était, lui, compté et
    # rendait ``gold_sample_n`` non nul — les deux chemins de perte sont
    # désormais alignés. Le compte est par modèle : un encodeur peut échouer
    # sur des images qu'un autre avale.
    sample_by_model: dict[str, int | None] = {}
    for r in results:
        n_perdus = int(r.get("n_not_encoded") or 0)
        n_couverts = max(len(crops) - n_perdus, 0)
        sample_by_model[r["model"]] = n_couverts if n_couverts < len(gold) else None
        if n_perdus:
            print(
                f"  !! {r['model']} : {n_perdus} crops présents en cache mais NON "
                f"ENCODÉS (image illisible/OOM) — le run porte sur {n_couverts} "
                f"crops sur les {len(gold)} du gold",
                file=sys.stderr,
            )
    # ── D16 : le recouvrement apparié, ARMÉ sur le chemin réel ──
    # Le garde `_paired_blockers` existait mais aucun appelant ne lui passait
    # `baseline_run_id` / `n_paired` : il ne se déclenchait jamais en
    # production. On calcule donc l'apparié AVANT la seconde mesure des
    # bloqueurs, et non plus dans la boucle d'assemblage des runs.
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    correctness = {
        r["model"]: {p.asset_id: bool(p.correct) for p in r["preds"]} for r in results
    }
    baseline_spec = args.baseline or results[0]["model"]
    mcnemar_by_model: dict[str, Any] = {}
    paired_by_model: dict[str, tuple[str | None, int | None]] = {}
    for r in results:
        m = r["model"]
        if m != baseline_spec and baseline_spec in correctness:
            res = paired_compare(correctness[baseline_spec], correctness[m])
            mcnemar_by_model[m] = res
            paired_by_model[m] = (
                f"{stamp}-{gold_version}-{_slug(baseline_spec)}", res.n_paired
            )
        else:
            paired_by_model[m] = (None, None)

    blockers_by_model, bank_build_id = _measure(
        [r["model"] for r in results], sample_by_model, paired_by_model
    )
    banner = blocker_banner(blockers_by_model, failures=failures)

    # ── Seuils : bloqués tant que les bloqueurs tiennent ──
    runs: list[EncoderBenchRun] = []
    threshold_lines: list[str] = []
    for r in results:
        blockers = blockers_by_model.get(r["model"], [])
        items = [
            (p.spread, bool(p.correct)) for p in r["preds"] if p.spread is not None
        ]
        curve = precision_coverage_curve(items)
        sweep_json = curve_to_json(curve) if curve else None
        proposal_dict = None
        try:
            prop = propose_threshold(
                curve, blockers=blockers, allow_provisional=args.allow_provisional
            )
        except CalibrationBlocked as exc:
            threshold_lines.append(
                f"- `{r['model']}` : **aucun seuil rendu** — {exc}"
            )
        else:
            proposal_dict = prop.to_dict()
            marque = " *(provisoire)*" if prop.provisional else ""
            if prop.threshold is None:
                threshold_lines.append(
                    f"- `{r['model']}` : aucun spread n'atteint "
                    f"{prop.target_precision:.0%} sur ce jeu{marque}"
                )
            else:
                threshold_lines.append(
                    f"- `{r['model']}` : spread ≥ {prop.threshold:.4f} → "
                    f"précision {proposal_dict['precision']:.1%} sur "
                    f"{proposal_dict['n_covered']} crops "
                    f"({proposal_dict['coverage']:.1%} de couverture){marque}"
                )

        mcnemar = mcnemar_by_model.get(r["model"])
        baseline_run_id = paired_by_model[r["model"]][0]
        runs.append(
            build_run(
                r,
                run_id=f"{stamp}-{gold_version}-{_slug(r['model'])}",
                created_at=created_at,
                gold_version=gold_version,
                gold_n_crops=len(gold),
                gold_sample_n=sample_by_model[r["model"]],
                blockers=blockers,
                proposal_dict=proposal_dict,
                sweep_json=sweep_json,
                bank_build_id=bank_build_id,
                baseline_run_id=baseline_run_id,
                mcnemar=mcnemar,
                note=args.note,
                anchors_kind=args.anchors_kind,
            )
        )

    # ── Rapport ──
    lines = [
        "# Bench encodeurs zero-shot (banque 2eur_all, GOLD FIGÉ de review)",
        "",
        "```",
        *banner,
        "```",
        "",
        f"- gold `{gold_version}` · {len(gold)} crops figés · {len(crops)} soumis"
        + (" (échantillon)" if gold_sample_n else " (gold entier)"),
        f"- banque `{args.anchors_kind}` : {base.count} ancres · "
        f"{len(set(base.eurio_ids))} classes · build "
        f"`{bank_build_id or 'inconnu'}`",
        "- Recall mesuré sur crops in-scope (classe de banque présente) ; bande "
        "pays = ancres du pays de la VÉRITÉ tranchée (`truth_country`).",
        "- Chaque modèle utilise SA transform recommandée (résolution/"
        "normalisation) — le zero-shot est un proxy du potentiel "
        "post-fine-tune ArcFace, pas une mesure absolue.",
        "",
        "| Modèle | M params | px | dim | in-scope | non encodés | global@1 "
        "| global@5 | pays@1 | pays@5 | ms/img | provisoire |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    by_model = {run.encoder_spec: run for run in runs}
    for r in sorted(results, key=lambda r: -r["c1"] / max(r["c_total"], 1)):
        run = by_model[r["model"]]
        lines.append(
            f"| {r['model']} | {r['params_m']:.1f} | {r['input_px']} "
            f"| {r['dim']} | {r['n_in_scope']} "
            f"| {int(r.get('n_not_encoded') or 0)} "
            f"| {_pct(r['g1'], r['n_in_scope'])} "
            f"| {_pct(r['g5'], r['n_in_scope'])} "
            f"| {_pct(r['c1'], r['c_total'])} "
            f"| {_pct(r['c5'], r['c_total'])} "
            f"| {r['ms_per_img']:.0f} "
            f"| {'oui' if run.provisional else 'non'} |"
        )
    lines += ["", "## Seuil d'auto-acceptation (spread)", ""] + (
        threshold_lines or ["- (aucune courbe : aucun spread mesurable)"]
    )
    paired = [run for run in runs if run.baseline_run_id]
    if paired:
        lines += ["", f"## Apparié McNemar (référence : `{baseline_spec}`)", ""]
        for run in paired:
            p = run.mcnemar_p
            lines.append(
                f"- `{run.encoder_spec}` : b={run.mcnemar_b} c={run.mcnemar_c} · "
                + (f"p = {p:.4g}" if p is not None else "p = — (rien de comparable)")
            )
    perdus = [(r["model"], int(r.get("n_not_encoded") or 0)) for r in results]
    if any(n for _m, n in perdus):
        lines += ["", "## Crops soumis mais NON encodés", ""]
        lines += [
            f"- `{m}` : {n} crops présents en cache et illisibles pour cet "
            f"encodeur → run sur {max(len(crops) - n, 0)} crops sur "
            f"{len(gold)}"
            for m, n in perdus if n
        ]
    if failures:
        lines += [
            "", "## Encodeurs TOMBÉS (non évalués — absents de la table)", "",
        ]
        lines += [f"- `{m}` : {err}" for m, err in failures]
    lines += ["", "## Traçabilité", ""]
    lines += [f"- `{run.run_id}` — provisional={run.provisional}" for run in runs]
    lines += ["", "```", *banner, "```", ""]
    report = "\n".join(lines)
    print(report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\n→ écrit dans {args.out}", file=sys.stderr)

    # ── Trace au canonique ──
    # N2 : ``failed`` ne comptait QUE les échecs de push. Un banc de nuit sur 4
    # encodeurs dont 3 tombent rendait `exit=0` et un rapport à une ligne.
    failed = len(failures)
    if args.no_push:
        print("(--no-push : aucun run tracé au canonique)", file=sys.stderr)
    else:
        for run, r in zip(runs, results):
            ok, _dump, message = push_run(run, r["preds"])
            print(message, file=sys.stderr)
            failed += 0 if ok else 1

    # La bannière une seconde fois, en tout dernier : sur un terminal, c'est
    # la seule chose encore visible après une table de résultats.
    print("\n".join(banner), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
