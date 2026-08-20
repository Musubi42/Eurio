"""Tests du garde de calibration — le blocage P3 doit PARLER, pas se taire.

Dans ce repo les pannes sont muettes (`.claude/skills/eurio-verify`). Le pire
comportement possible ici serait de rendre un `spread_auto_accept_min`
plausible calculé sur les 12454 prédictions périmées : personne ne le verrait.
Ces tests verrouillent l'inverse — sans `allow_provisional`, ça lève ; avec, le
chiffre sort marqué et sa bannière nomme la raison.
"""
from __future__ import annotations

import pytest

from shared.stats.calibration import (
    DEFAULT_MIN_COVERED,
    DEFAULT_TARGET_PRECISION,
    P3_BLOCKER,
    CalibrationBlocked,
    propose_threshold,
)
from shared.stats.sweep import precision_coverage_curve, threshold_for_precision


def _jeu_realiste() -> list[tuple[float, bool]]:
    """100 items dans [0,02 ; 0,06] : les 20 plus bas sont faux.

    Plage volontairement « à la DINOv3 » — un balayage codé en dur sur [0,1]
    n'y trouverait rien.
    """
    return [(0.02 + 0.04 * i / 99, i >= 20) for i in range(100)]


def _courbe():
    return precision_coverage_curve(_jeu_realiste(), n_steps=101)


def test_refuse_un_seuil_officiel_sous_blocage_p3() -> None:
    with pytest.raises(CalibrationBlocked) as exc:
        propose_threshold(_courbe(), blockers=[P3_BLOCKER])
    message = str(exc.value)
    assert "P3" in message
    assert "backfill_dino_predictions" in message
    assert "allow_provisional" in message


def test_provisoire_marque_et_banniere_nomme_la_raison() -> None:
    prop = propose_threshold(
        _courbe(), blockers=[P3_BLOCKER, "P1: banque amputee"], allow_provisional=True
    )
    assert prop.provisional is True
    assert prop.blockers == (P3_BLOCKER, "P1: banque amputee")
    banner = prop.banner()
    assert banner.startswith("⚠ CALIBRATION PROVISOIRE")
    assert "P3" in banner and "P1" in banner
    assert prop.threshold is not None
    assert prop.to_dict()["provisional"] is True
    assert "P3" in prop.to_dict()["provisional_reason"]


def test_sans_bloqueur_le_seuil_est_promouvable() -> None:
    curve = _courbe()
    prop = propose_threshold(curve)
    assert prop.provisional is False
    assert prop.banner() == ""
    assert prop.blockers == ()
    assert prop.target_precision == pytest.approx(DEFAULT_TARGET_PRECISION)
    assert prop.min_covered == DEFAULT_MIN_COVERED
    attendu = threshold_for_precision(curve, 0.97, min_covered=30)
    assert prop.threshold == pytest.approx(attendu.threshold)
    assert prop.to_dict()["provisional_reason"] is None


def test_bloqueurs_vides_ou_none_ne_bloquent_pas() -> None:
    """Une liste de bloqueurs filtrée qui ne contient que du vide = promouvable."""
    prop = propose_threshold(_courbe(), blockers=["", ""])
    assert prop.provisional is False


def test_cible_inatteignable_rend_un_point_none_sans_lever() -> None:
    items = [(0.1 * i, i % 2 == 0) for i in range(100)]  # ~50 % partout
    prop = propose_threshold(precision_coverage_curve(items, n_steps=51), min_covered=10)
    assert prop.point is None
    assert prop.threshold is None
    assert prop.to_dict()["n_covered"] == 0


def test_le_seuil_rendu_vit_dans_la_plage_observee() -> None:
    """P6-4 : la calibration ne peut pas rendre un seuil hors de l'échelle vue."""
    prop = propose_threshold(_courbe())
    assert 0.02 <= prop.threshold <= 0.06


def test_stdlib_seulement_pas_dimport_lourd() -> None:
    """Le paquet doit rester importable par l'image lean du VPS (ni cv2 ni torch)."""
    import subprocess
    import sys
    from pathlib import Path

    ml_dir = Path(__file__).resolve().parent.parent
    code = (
        "import sys; import shared.stats as s; "
        "assert s.propose_threshold; "
        "lourds=[m for m in ('torch','cv2','numpy','timm','scipy') if m in sys.modules]; "
        "print(lourds)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ml_dir, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", out.stdout
