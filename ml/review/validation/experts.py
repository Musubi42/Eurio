"""Experts d'auto-validation — interface normalisée (C1 + C2 du redesign).

Chaque expert lit une source de signal et produit un :class:`Signal` homogène
``(expert, score, label, reason, raw)``. Experts actifs : **text**, **dino**
(C1) et **crop_quality** (C2). La règle de consensus qui agrège les Signals
arrive en C3 (doc docs/work-in-progress/autovalidation-redesign.md).

Invariant de non-régression (C1) : les Signals text+dino reflètent EXACTEMENT
les valeurs que ``training/foundation/auto_validate.py`` consomme aujourd'hui —
un verdict reconstruit depuis eux est identique au verdict canonique. Gate :
tests/test_validation_experts.py.

Données crop — **la couverture réelle, avec sa requête** (mesurée le
2026-08-25, réplique ``ml/state/eurio.replica.db``) ::

    sqlite3 -readonly ml/state/eurio.replica.db \\
      "SELECT COUNT(*), SUM(quality_score IS NOT NULL) FROM image_assets;"
    -- 18730|1052                                   → 5,6 % du parc
    -- …WHERE training_eligible=1 → 2969|262        → 8,8 % du pool éligible

Le « ~46 % » qui figurait ici datait du 2026-06-08 et parlait d'un parc de 2 274
crops : c'était la couverture *de l'échantillon diagnostiqué*, pas celle de la
base, et le parc a quadruplé depuis sans que rien ne soit re-mesuré (cf.
``scripts/backfill_quality_score.py``, qui a été refait pour ça). ~46 % reste le
plafond attendu de l'oracle Otsu *sur les crops qu'il examine* — ce n'est pas la
même phrase. NULL = **non mesuré**, jamais *mauvais* : l'expert s'abstient.
``quality_reason`` ne porte que des états de review
(``rejected_in_review``/``vision_standard_gate``) — sauf ``too_tilted`` (label
humain du banc). Le tilt fiable (``tilt_trustworthy=1``) complète sur les crops
sans quality_score. Ordre de priorité dans ``crop_signal`` : label humain →
quality_score → tilt → abstention.

Dépendance : ``review`` → ``training.foundation`` (sens correct). La résolution
des signaux verdict (préférence country-restricted) reste définie une seule fois
côté foundation (``fetch_and_resolve_signals``) — pas de duplication ici.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Protocol

from shared.bank_classes import bank_class_ids
from shared.verdict_scope import VERDICT_ANCHORS_KIND, VERDICT_ENCODER_VERSION
from training.foundation.auto_validate import (
    ResolvedSignals,
    fetch_and_resolve_signals,
)
from training.foundation.thresholds import DINO_VERDICT_THRESHOLDS

logger = logging.getLogger(__name__)


#: Banques qui ne contiennent QUE des commémoratives. Pour elles, et elles
#: seules, « dans le scope » se lit « la pièce est commémorative ». La liste est
#: explicite plutôt que déduite de la base : cf. `target_in_dino_scope`.
_COMMEMO_ONLY_BANKS: frozenset[str] = frozenset({"2eur_commemo"})


@dataclass(frozen=True)
class Signal:
    """Avis normalisé d'un expert.

    - ``score`` ∈ [0, 1] (``None`` = abstention, pas de donnée exploitable) :
      force/confiance de l'expert. Provisoire — la règle de consensus (C3) le
      calibrera.
    - ``label`` : verdict propre à l'expert (lisible, pour l'audit).
    - ``raw`` : signaux sous-jacents, conservés pour l'audit et le consensus.
    """

    expert: str
    score: float | None
    label: str
    reason: str
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CropQuality:
    """Colonnes crop-quality de ``image_assets`` (None = non mesuré)."""

    tilt_deg: float | None
    tilt_trustworthy: int | None  # 1 / 0 / None
    quality_score: float | None  # oracle r_ratio, peuplé ~46 % (NULL ailleurs)
    quality_reason: str | None


@dataclass(frozen=True)
class AssetContext:
    """Contexte d'un asset partagé par tous les experts — résolu une seule
    fois en amont (``collect_signals``) pour éviter une requête par expert."""

    resolved: ResolvedSignals
    crop: CropQuality
    # La cible est-elle dans le scope du banc d'ancres DINO (2eur_commemo) ?
    # False pour un standard → la prédiction DINO est structurellement fausse.
    dino_in_scope: bool = True


class Expert(Protocol):
    """Un expert transforme le contexte d'un asset en un ``Signal``."""

    name: str

    def evaluate(self, ctx: AssetContext) -> Signal: ...


# ── Text expert ─────────────────────────────────────────────────────────

# Score provisoire par label (calibré en C3 avec la règle de consensus).
_TEXT_SCORE = {"convergent": 1.0, "partial": 0.5, "contradict": 0.0}


def text_signal(text_verdict: str | None) -> Signal:
    """Normalise le verdict texte (``listing_text_signals.vs_target_verdict``).

    ``text_verdict`` ∈ {convergent, partial, absent, contradict, None}. None et
    'absent' sont traités identiquement (rien d'exploitable côté texte).
    """
    label = text_verdict or "absent"
    return Signal(
        expert="text",
        score=_TEXT_SCORE.get(label),  # None pour 'absent'
        label=label,
        reason=f"texte {label}",
        raw={"vs_target_verdict": text_verdict},
    )


class TextExpert:
    name = "text"

    def evaluate(self, ctx: AssetContext) -> Signal:
        return text_signal(ctx.resolved.text_verdict)


# ── Dino expert ─────────────────────────────────────────────────────────


def dino_signal(
    *,
    target: str | None,
    top1: str | None,
    sim: float | None,
    spread: float | None,
    in_scope: bool = True,
) -> Signal:
    """Normalise le signal DINO : top1 (country-restricted, fallback global) vs
    target + similarité/spread confrontés aux seuils canoniques.

    ``label`` ∈ {match, mismatch, absent}. ``absent`` quand il n'y a pas de
    prédiction (top1 et sim nuls), pas de cible, OU que la cible est **hors
    scope** du banc d'ancres (ex: un standard dans le banc 2eur_commemo) — dans
    ce dernier cas top1 ne PEUT PAS être la cible, donc un "mismatch" serait
    trompeur (faux rejet). On s'abstient.
    """
    sim_min = DINO_VERDICT_THRESHOLDS["top1_country_sim_min"]
    spread_min = DINO_VERDICT_THRESHOLDS["country_spread_min"]
    sim_pass = sim is not None and sim >= sim_min
    spread_pass = spread is not None and spread >= spread_min
    raw = {
        "target": target,
        "top1": top1,
        "sim": sim,
        "spread": spread,
        "sim_pass": sim_pass,
        "spread_pass": spread_pass,
        "in_scope": in_scope,
    }

    if target is not None and not in_scope:
        return Signal(
            "dino", None, "absent",
            "cible hors scope ancres (standard) — DINO non fiable", raw,
        )

    if (top1 is None and sim is None) or target is None:
        label = "absent"
    elif top1 == target:
        label = "match"
    else:
        label = "mismatch"

    return Signal(
        expert="dino",
        score=sim,  # la similarité est déjà dans [0, 1]
        label=label,
        reason=(
            f"top1={top1} sim={sim} spread={spread}"
            if sim is not None
            else "pas de prédiction DINO"
        ),
        raw=raw,
    )


class DinoExpert:
    name = "dino"

    def evaluate(self, ctx: AssetContext) -> Signal:
        r = ctx.resolved
        return dino_signal(
            target=r.target, top1=r.top1, sim=r.sim, spread=r.spread,
            in_scope=ctx.dino_in_scope,
        )


# ── Crop-quality expert (C2) ────────────────────────────────────────────

# Seuils provisoires (à calibrer). Au-delà de ``_TILT_MAX_DEG``, un crop incliné
# de façon FIABLE (tilt_trustworthy=1) pénalise le verdict (pièce non frontale →
# embedding DINO moins fiable). Tilt non fiable / NULL = abstention : le
# détecteur n'est fiable que sur ~36 % des assets.
# ``quality_score`` (oracle r_ratio, scripts/backfill_quality_score.py) est
# peuplé sur ~46 % des crops ; ``_QUALITY_MIN`` = 0.85 = seuil d'undercrop du
# chantier crop-quality-overhaul (< 0.85 → under/overcrop → pénalité).
_TILT_MAX_DEG = 30.0
_QUALITY_MIN = 0.85

# quality_reason qui dénotent un défaut de CROP (pas un état de review).
_CROP_BAD_REASONS = {"too_tilted"}


def crop_signal(crop: CropQuality) -> Signal:
    """Normalise la qualité de crop en pénalité.

    Ordre de priorité : label humain ``too_tilted`` → ``quality_score`` (dormant
    tant que vide) → tilt mesuré fiable → abstention. ``score`` : 0.0 = crop à
    écarter (capera le verdict en C3), 1.0 = crop géométriquement OK, None =
    abstention (aucune pénalité — pas de mesure fiable).
    """
    base = {
        "tilt_deg": crop.tilt_deg,
        "tilt_trustworthy": crop.tilt_trustworthy,
        "quality_score": crop.quality_score,
        "quality_reason": crop.quality_reason,
    }

    # 1. Label humain explicite (banc "exclure crops" → quality_reason).
    if crop.quality_reason in _CROP_BAD_REASONS:
        return Signal("crop_quality", 0.0, "too_tilted",
                      f"label humain {crop.quality_reason}", base)

    # 2. quality_score (oracle r_ratio, peuplé ~46 % des crops).
    if crop.quality_score is not None:
        good = crop.quality_score >= _QUALITY_MIN
        return Signal(
            "crop_quality", crop.quality_score,
            "good" if good else "low_quality",
            f"quality_score {crop.quality_score:.2f}", base,
        )

    # 3. Tilt mesuré fiable.
    if crop.tilt_trustworthy == 1 and crop.tilt_deg is not None:
        if crop.tilt_deg >= _TILT_MAX_DEG:
            return Signal("crop_quality", 0.0, "too_tilted",
                          f"tilt {crop.tilt_deg:.0f}° ≥ {_TILT_MAX_DEG:.0f}° (fiable)",
                          base)
        return Signal("crop_quality", 1.0, "ok",
                      f"tilt {crop.tilt_deg:.0f}° < {_TILT_MAX_DEG:.0f}° (fiable)", base)

    # 4. Pas de mesure fiable → abstention (pénalité nulle).
    return Signal("crop_quality", None, "unmeasured",
                  "tilt non mesuré/non fiable, pas de quality_score", base)


class CropQualityExpert:
    name = "crop_quality"

    def evaluate(self, ctx: AssetContext) -> Signal:
        return crop_signal(ctx.crop)


def target_in_dino_scope(
    conn: sqlite3.Connection,
    target: str | None,
    *,
    anchors_kind: str = VERDICT_ANCHORS_KIND,
) -> bool:
    """La cible est-elle une classe que la banque d'ancres sait reconnaître ?

    Hors scope ⇒ l'expert DINO **s'abstient** : sa prédiction serait
    structurellement fausse, puisque la bonne réponse n'existe pas parmi les
    ancres. Inconnue ⇒ True — on ne supprime pas un signal qu'on ne sait pas
    invalider.

    ⛔ **Le prédicat dépend de la banque, et il n'y a pas de formule unique.**

    - `2eur_commemo` ne contient QUE des commémoratives et ne trace aucune ligne
      dans `dino_class_references` : le seul prédicat disponible y reste « la
      pièce est commémorative ».
    - `2eur_all` contient les commémoratives ET les classes courantes : y
      demander « est-elle commémorative ? » écarterait à tort tous les
      standards, dont c'est précisément la raison d'être de cette banque.

    🔴 **L'aiguillage est EXPLICITE, et il l'est depuis la revue du
    2026-08-24.** La première version décidait d'après l'état de la base — « la
    table contient-elle des lignes pour ce kind ? ». C'était un piège : les
    références sont écrites par le build local et n'atteignent le canonique que
    par `POST /ingest/dino-references`. Un push manqué aurait donc fait basculer
    le prédicat, sur la machine concernée seulement, de « appartenance à la
    banque » à « est commémorative » — c'est-à-dire fait abstenir l'expert DINO
    sur **toute** pièce courante, la population même pour laquelle la bascule
    vers `2eur_all` a été faite. Sans erreur, et avec deux machines rendant des
    verdicts différents pour le même crop.

    Désormais : la règle vient de `_COMMEMO_ONLY_BANKS`, pas de la donnée. Une
    banque censée porter des courantes mais dont la table est vide **le dit en
    WARNING** — et fait abstenir l'expert, délibérément.

    Pourquoi abstenir plutôt que « dans le doute, garde le signal » : ici les
    deux erreurs ne coûtent pas la même chose. Un expert DINO qui parle alors
    qu'on ne peut pas mesurer son périmètre, combiné à un texte contradictoire,
    donne `dual_contradict` — c'est-à-dire un **rejet**, définitif, sans humain.
    Abstenir donne `text_contradict_rescue`, c'est-à-dire une review humaine.
    Face à un état qu'on ne sait pas mesurer, on choisit celui qui demande un
    humain, pas celui qui détruit. (Verrouillé par
    `test_standard_out_of_scope_not_falsely_rejected`.)

    La traduction pièce → classe passe par `shared.bank_classes`, jamais par un
    `COALESCE(design_group_id, eurio_id)` naïf : la banque indexe une courante
    sous le REPRÉSENTANT de son groupe de dessin.
    """
    if not target:
        return True

    if anchors_kind in _COMMEMO_ONLY_BANKS:
        row = conn.execute(
            "SELECT is_commemorative FROM coins WHERE eurio_id = ?", (target,)
        ).fetchone()
        if row is None:
            return True
        return bool(row[0])

    classes = bank_class_ids(conn, target)
    ph = ",".join("?" * len(classes))
    row = conn.execute(
        f"SELECT 1 FROM dino_class_references "
        f" WHERE anchors_kind = ? AND class_id IN ({ph}) LIMIT 1",
        (anchors_kind, *classes),
    ).fetchone()
    if row is not None:
        return True

    # Rien trouvé : soit cette classe n'est vraiment pas en banque, soit la
    # table est vide ici (références jamais poussées). Le second cas ne doit pas
    # se déguiser en premier — il vaut un WARNING, pas une abstention massive.
    if not conn.execute(
        "SELECT 1 FROM dino_class_references WHERE anchors_kind = ? LIMIT 1",
        (anchors_kind,),
    ).fetchone():
        logger.warning(
            "[verdict] dino_class_references VIDE pour anchors_kind=%s sur cette "
            "base — le périmètre de l'expert DINO n'est pas mesurable ici. "
            "Références jamais poussées (POST /ingest/dino-references) ? "
            "L'expert s'abstient : mieux vaut une review humaine qu'un rejet "
            "fondé sur un périmètre inconnu.", anchors_kind,
        )
    return False


def fetch_crop_quality(
    conn: sqlite3.Connection, asset_id: str
) -> CropQuality | None:
    """Colonnes crop-quality d'un asset (None si l'asset n'existe pas)."""
    row = conn.execute(
        "SELECT tilt_deg, tilt_trustworthy, quality_score, quality_reason "
        "  FROM image_assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        return None
    return CropQuality(
        tilt_deg=row["tilt_deg"],
        tilt_trustworthy=row["tilt_trustworthy"],
        quality_score=row["quality_score"],
        quality_reason=row["quality_reason"],
    )


# ── Façade ──────────────────────────────────────────────────────────────

# Registre des experts actifs.
EXPERTS: list[Expert] = [TextExpert(), DinoExpert(), CropQualityExpert()]


def collect_signals(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    encoder_version: str = VERDICT_ENCODER_VERSION,
    anchors_kind: str = VERDICT_ANCHORS_KIND,
) -> list[Signal]:
    """Collecte les avis d'experts pour un asset (text + dino + crop_quality).

    ⛔ Les défauts viennent de `shared.verdict_scope`, PLUS de littéraux.
    Ils portaient `"dinov2-vits14"` / `"2eur_commemo"` en dur jusqu'au
    2026-08-24, et ce module est le chemin de routage **LIVE** :
    `sources/_base/steps/enqueue.py` l'appelle sans kwargs, puis écrit la lane.
    Basculer `verdict_scope.py` n'aurait donc pas changé la lane posée à
    l'enqueue — la bascule aurait été à moitié faite, en silence. Le test
    paramétré `tests/test_verdict_anchors_scope.py` couvre désormais ce module.

    Les ``Signal`` sont la matière première de la règle de consensus (C3).
    Résolution faite en amont (verdict-bundle + crop-bundle), puis fan-out.
    Liste vide si l'asset est introuvable.
    """
    resolved = fetch_and_resolve_signals(
        conn,
        asset_id,
        encoder_version=encoder_version,
        anchors_kind=anchors_kind,
    )
    if resolved is None:
        return []
    crop = fetch_crop_quality(conn, asset_id) or CropQuality(None, None, None, None)
    ctx = AssetContext(
        resolved=resolved,
        crop=crop,
        dino_in_scope=target_in_dino_scope(
            conn, resolved.target, anchors_kind=anchors_kind),
    )
    return [expert.evaluate(ctx) for expert in EXPERTS]
