"""Q1 — le texte n'est plus une CONDITION de l'auto-acceptation, seulement un VETO.

Tranchée le 2026-08-27 sur le gold rebâti (1 309 crops évaluables contre 466) :

    porte texte      n_auto  faux  précision   Wilson 95 %
    convergent          526     1    99,81 %   [98,93 ; 99,97]
    ≠ contradict        755     2    99,74 %   [99,04 ; 99,93]   ← retenu

La précision PONCTUELLE baisse de 0,07 pt ; c'est la borne BASSE de Wilson qui
décide, et elle MONTE. Volume sur la file du jour : 1 819 → 2 308 (+489).
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402

from training.foundation.auto_validate import _verdict_from_signals  # noqa: E402


def _v(text, *, sim=0.80, spread=0.20, target="fr-x", top1="fr-x"):
    return _verdict_from_signals(
        face="obverse", target=target, top1=top1,
        sim=sim, spread=spread, text_verdict=text,
    )


# ─── Ce que Q1 ouvre ────────────────────────────────────────────────────────


@pytest.mark.parametrize("texte", ["convergent", "partial", "absent", None])
def test_tout_texte_non_contredisant_laisse_passer(texte):
    """Mutation : remettre `and text_verdict == "convergent"` à l'étape 5 → rouge.

    Les quatre valeurs sont mesurées aussi justes les unes que les autres. Le
    cas qui portait le défaut est `partial` : il vaut « le titre ne nomme pas
    les trois axes », pas « le titre est douteux » — un vendeur qui écrit
    « 2 euro Erasmus 2022 » sans le pays produit `partial`.
    """
    v = _v(texte)
    assert v.level == "auto_candidate"
    assert v.decided_eurio_id == "fr-x"


# ─── Ce que Q1 NE touche PAS ────────────────────────────────────────────────


def test_le_veto_de_contradiction_tient():
    """Mutation : retirer la règle 2 (`text_verdict == "contradict"`) → rouge.

    C'est la garde qui rend le changement acceptable : sur les crops en
    `contradict`, l'exactitude de DINO tombe de 96,3 % à 64,6 % (mesuré le
    2026-08-27 sur 305 crops tranchés). Un titre qui CONTREDIT reste un veto,
    même avec Dino largement au-dessus des deux seuils.
    """
    v = _v("contradict", sim=0.99, spread=0.99)
    assert v.level == "divergent"
    assert v.decided_eurio_id is None


@pytest.mark.parametrize(
    ("sim", "spread"),
    [(0.30, 0.20), (0.80, 0.01), (0.30, 0.01)],
)
def test_les_seuils_dino_bloquent_toujours(sim, spread):
    """Mutation : rendre `auto_candidate` sans `dino_all_pass` → rouge.

    Q1 retire la porte TEXTE, pas les portes Dino. D4 les a mesurées inertes
    mais elles restent la garde.
    """
    assert _v("convergent", sim=sim, spread=spread).level == "partial"


def test_top1_different_de_la_cible_reste_divergent():
    """Mutation : retirer la règle 4 → rouge."""
    assert _v("convergent", top1="de-y").level == "divergent"


# ─── La raison ne doit plus accuser le texte ────────────────────────────────


def test_la_raison_de_partial_ne_parle_plus_du_texte():
    """Mutation : remettre les lignes `texte …` dans les raisons → rouge.

    Le texte ne bloque plus rien à l'étape 6 : l'y laisser ferait passer une
    observation pour une cause, et enverrait la prochaine personne corriger le
    mauvais signal.
    """
    v = _v("partial", sim=0.30)
    assert v.level == "partial"
    assert "texte" not in v.reason, v.reason
    assert "sim" in v.reason


# ─── Le port lean dit la même chose ─────────────────────────────────────────


def test_le_port_lean_est_un_miroir_exact():
    """Mutation : ne changer QU'UNE des deux copies → rouge.

    La règle vit à deux endroits — le legacy et le port lean de
    `serving/review_queue/service.py` (l'image du VPS ne peut pas importer
    `training/`). Un correctif d'une seule moitié passerait au vert sur
    l'autre.
    """
    import sqlite3

    from serving.review_queue.service import auto_validate_view

    class _Row(dict):
        def __getitem__(self, k):
            return dict.get(self, k)

    for texte in ("convergent", "partial", "absent", None, "contradict"):
        legacy = _v(texte)
        row = _Row(
            target_eurio_id="fr-x", top1_country_eurio_id="fr-x",
            top1_eurio_id="fr-x", top1_country_sim=0.80, top1_sim=0.80,
            country_spread=0.20, spread=0.20, vs_target_verdict=texte,
        )
        lean_level, _reason, _crit = auto_validate_view(row)
        assert lean_level == legacy.level, (
            f"texte={texte!r} : legacy dit {legacy.level}, lean dit {lean_level}")
    assert sqlite3  # le port lean travaille sur des sqlite3.Row en prod
