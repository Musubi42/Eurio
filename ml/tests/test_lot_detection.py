"""Détection lot multilingue — quick win cohort-pipeline (coin-census-bench).

Vérifie que `listing_kind` capte les lots déclarés au titre en DE/ES/IT/NL
(KMS/Satz/cofre/cartera, compteurs « N valores/piezas/münzen », plage de
dénominations 1 cent–2 euro, ≥2 pays) — sans transformer un coincard/blister
d'UNE pièce en lot (leçon FP du bench). Cf. docs/cohort-pipeline/coin-census-bench.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402

from sources.text_signals.extractor import extract_listing_text_signals as X  # noqa: E402


def kind(title: str) -> str:
    return X(title).listing_kind


# Lots déclarés au titre (multilingues) — DOIVENT être 'lot'.
@pytest.mark.parametrize("title", [
    "3 x 2 Euro Gedenkmünzen Österreich 2005, 2016 und 2018, unzirkuliert",   # N×
    "AUSTRIA 2005 CARTERA OFICIAL - 8 VALORES - 2 EUROS CONMEMORATIVOS",       # cartera + 8 valores
    "K-17) EURO KMS ÖSTERREICH 2005 HGH mit 2 Euro Staatsvertrag",             # KMS
    "5,88 Euro KMS Italien 2016 inklusive 2 Euro Gedenkmünze Plauto",          # KMS
    "Österreich 2005 kompletter Euro-Satz 1 Cent - 2 Euro - bankfrisch",       # Satz + plage
    "Cofre BU España 2016 - 8 Piezas De 1 Cent a 2 Euro + 2€ Conm",            # cofre + 8 piezas + plage
    "2005 2 EURO COMMEMORATIVI AUSTRIA/BELGIO/FINLANDIA/ITALIA/SPAGNA",        # ≥2 pays
    "Österreich 2005 mit 8 prägefrischen Münzen 1 Cent bis 2 Euro",            # plage 1cent-2euro
])
def test_titles_declaring_a_lot_are_classified_lot(title):
    assert kind(title) == "lot", f"attendu lot pour: {title!r} (got {kind(title)})"


# Pièces UNIQUES (éventuellement emballées) — NE DOIVENT PAS être 'lot'.
@pytest.mark.parametrize("title", [
    "2 Euro Münze Belgien 2011 100 Jahre Internationaler Frauentag in Coincard",  # coincard = 1 pièce
    "2 Euro Österreich Sonderprägung 2005 50 Jahre Staatsvertrag in Coincard. Rar!",
    "Finland 2016 Eino Leino 2 euro BU",                                           # single nu
    "2 Euros commémoratif Autriche 2005 50e anniversaire du Traité",               # single nu
    "2 Euro Finnland 2017 100 Jahre Unabhängigkeit im Blister",                    # blister = 1 pièce
])
def test_single_or_packaged_single_is_not_lot(title):
    assert kind(title) != "lot", f"NE devrait PAS être lot: {title!r} (got {kind(title)})"


def test_coincard_classified_as_coffret_not_lot():
    # Un coincard est un emballage d'UNE pièce : catégorie 'coffret', pas 'lot'.
    assert kind("2 Euro Belgien 2011 Frauentag in Coincard") == "coffret"
