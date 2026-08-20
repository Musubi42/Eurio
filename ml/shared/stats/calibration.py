"""Garde-fou de calibration : un seuil promouvable ne sort pas d'ici en silence.

POURQUOI CE MODULE EXISTE, ET PAS SEULEMENT `sweep.py`
------------------------------------------------------
`sweep.precision_coverage_curve` + `sweep.threshold_for_precision` savent lire
le spread qui atteint 97 % sur un jeu donné. Ce chiffre alimente
`dino_thresholds.spread_auto_accept_min`, donc l'auto-acceptation de la review.

Mais un chiffre juste sur un jeu périmé est un chiffre faux en production. Au
2026-08-19 les prédictions servies sont périmées :

    sqlite3 ml/state/eurio.replica.db "
      SELECT COUNT(*) FROM image_asset_dino_predictions
       WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14';"
    -- 12454, calculées contre une banque à 546 classes

et la banque servie est amputée (125 classes à exemplaires mesurées contre 182
classes ayant au moins un candidat éligible — cf. PREREQUIS.md P1). Rendre un
seuil « officiel » dans cet état ne lèverait aucune erreur : il déplacerait
silencieusement le taux de faux positifs de la review. C'est exactement la
famille de pannes que `.claude/skills/eurio-verify` décrit — **une valeur par
défaut plausible là où il fallait une erreur**.

D'où `propose_threshold` : tant que l'appelant lui passe des bloqueurs, elle
LÈVE. Avec `allow_provisional=True`, elle rend le chiffre mais le marque, et
`banner()` donne la ligne à imprimer avant tout usage.

QUI MESURE LES BLOQUEURS
------------------------
Pas ce module — il reste stdlib pur (contrat d'import du paquet
`shared.stats`, importable par l'image lean du VPS qui n'a ni cv2 ni torch).
La mesure SQL vit dans `store.encoder_bench.calibration_blockers()` (module D
de la spec P4/P6) ; ici on ne consomme que son verdict.

COMMENT ON SAURA QUE P3 EST FAIT
--------------------------------
La liste de bloqueurs se vide. Le point d'accroche recommandé par l'audit est
une colonne `build_id` sur `image_asset_dino_predictions`, à comparer au
`dino_anchor_builds.build_id` du build courant : une prédiction dont le
`build_id` diffère est périmée, et le dire devient une jointure au lieu d'une
heuristique de date. **Cette colonne n'existe pas encore et ce module ne la
crée pas** (schéma hors périmètre : c'est P3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from shared.stats.sweep import SweepPoint, threshold_for_precision

#: Précision cible par défaut d'une calibration d'auto-acceptation.
#: 97 % = le palier retenu par le PO, cf.
#: `docs/work-in-progress/banque-dino/DECISIONS.md` §D4.
DEFAULT_TARGET_PRECISION = 0.97

#: Nombre minimal de crops au-dessus du seuil pour qu'une précision veuille
#: dire quelque chose. Trois crops à 100 % n'est pas une calibration.
DEFAULT_MIN_COVERED = 30

#: Bloqueur type à passer tant que le backfill P3 n'a pas tourné. Sa mesure
#: exacte est dans `store.encoder_bench.calibration_blockers` ; cette constante
#: sert de libellé partagé pour que le message soit le même partout.
P3_BLOCKER = (
    "P3: les predictions DINO en base sont anterieures au build de banque "
    "courant -- relancer scripts.backfill_dino_predictions --kind <kind> --force"
)


class CalibrationBlocked(RuntimeError):
    """Levée quand on demande un seuil promouvable sur des données périmées."""


@dataclass(frozen=True)
class ThresholdProposal:
    """Un seuil candidat, et le fait — explicite — qu'il soit promouvable ou non."""

    point: SweepPoint | None
    target_precision: float
    min_covered: int
    provisional: bool
    blockers: tuple[str, ...]

    @property
    def threshold(self) -> float | None:
        """Le spread retenu, ou `None` si la cible est inatteignable."""
        return self.point.threshold if self.point else None

    def banner(self) -> str:
        """Ligne à imprimer avant tout usage du chiffre. Vide si promouvable."""
        if not self.provisional:
            return ""
        return "⚠ CALIBRATION PROVISOIRE — " + " | ".join(self.blockers)

    def to_dict(self) -> dict:
        """Forme sérialisable, pour `encoder_bench_runs` et le rapport du banc."""
        return {
            "threshold": self.threshold,
            "target_precision": self.target_precision,
            "min_covered": self.min_covered,
            "provisional": self.provisional,
            "provisional_reason": " | ".join(self.blockers) or None,
            "n_covered": self.point.n_covered if self.point else 0,
            "coverage": self.point.coverage if self.point else 0.0,
            "precision": self.point.precision if self.point else 0.0,
        }


def propose_threshold(
    curve: Sequence[SweepPoint],
    *,
    target_precision: float = DEFAULT_TARGET_PRECISION,
    min_covered: int = DEFAULT_MIN_COVERED,
    blockers: Sequence[str] = (),
    allow_provisional: bool = False,
) -> ThresholdProposal:
    """Enveloppe `threshold_for_precision` d'un verdict de promouvabilité.

    `blockers` non vide et `allow_provisional` faux → `CalibrationBlocked`, en
    nommant les raisons. Un seuil issu de prédictions périmées ne doit pas
    pouvoir sortir d'ici en se faisant passer pour officiel.
    """
    blockers_t = tuple(str(b) for b in blockers if b)
    if blockers_t and not allow_provisional:
        raise CalibrationBlocked(
            "Seuil non promouvable : "
            + " | ".join(blockers_t)
            + ". Relancer avec allow_provisional=True (CLI : --allow-provisional) "
            "pour obtenir un chiffre explicitement marque provisoire."
        )
    return ThresholdProposal(
        point=threshold_for_precision(curve, target_precision, min_covered=min_covered),
        target_precision=target_precision,
        min_covered=min_covered,
        provisional=bool(blockers_t),
        blockers=blockers_t,
    )
