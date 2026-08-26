"""Les quatre défauts d'extraction trouvés par l'audit visuel du 2026-08-27.

Chaque test porte le titre RÉEL qui l'a révélé, et la mutation qui le rend
rouge est écrite dans son docstring. Un correctif sans mutation jouée ne
prouve rien dans ce dépôt (cf. `.claude/skills/eurio-verify`).
"""

from __future__ import annotations

import pytest

from sources.text_signals.comparator import TargetIdentity, compare_to_target
from sources.text_signals.extractor import extract_listing_text_signals


# ── 1. le millésime collé à la lettre d'atelier ──────────────────────────


def test_millesime_colle_a_la_lettre_datelier():
    """Mutation : remettre `\\b` en borne droite de YEAR_RE → rouge.

    Titre réel de la file ouverte. « 2016R » : R est la lettre d'atelier de
    Rome. Le `\\b` d'origine exigeait une frontière de mot après le
    millésime, que la lettre supprime.
    """
    sig = extract_listing_text_signals("2016R Italien 2 Euro Plautus Plauto NGC MS67")
    assert 2016 in sig.years


@pytest.mark.parametrize("titre", ["KM2016 catalogue", "reference 20161"])
def test_la_borne_gauche_protege_des_faux_millesimes(titre):
    """Mutation : passer la borne gauche de `\\b` à `(?<!\\d)` → « KM2016 » rouge.

    Élargir la borne DROITE ne doit pas élargir la gauche : un numéro de
    catalogue collé et un entier plus long ne sont pas des millésimes.
    """
    assert extract_listing_text_signals(titre).years == frozenset()


# ── 2. les noms de pays en espagnol ──────────────────────────────────────


@pytest.mark.parametrize(
    ("titre", "iso"),
    [
        ("Luxemburgo 2 euros 2004 a 2024, recién acuñado", "LU"),
        ("MONEDAS 2€ Alemania 2010 Cattedrale Brema", "DE"),
        ("2 euros Chipre 2012 conmemorativa", "CY"),
        ("2 euros Grecia 2011 Juegos Olimpicos", "GR"),
        ("2 euros Eslovenia 2015 conmemorativa", "SI"),
    ],
)
def test_noms_de_pays_en_espagnol(titre, iso):
    """Mutation : retirer la forme espagnole du dico → rouge.

    EBAY_ES est un marché de découverte à part entière. Mesuré le
    2026-08-27 : 1 638 crops de la file ouverte portaient un de ces noms et
    rendaient `countries_json = []`.
    """
    assert iso in extract_listing_text_signals(titre).countries


# ── 3. l'objet vendu EST le rangement ────────────────────────────────────


def test_marqueur_accessoire():
    """Mutation : retirer la catégorie `accessory` → rouge.

    Titre réel. Le crop associé sort à sim 0,191 et occupe la file. Le
    marqueur ne le RETIRE pas de la file (personne ne lit
    `rejected_markers_json` pour filtrer) — il le rend visible à l'humain.
    """
    sig = extract_listing_text_signals(
        "2€-Münzen Sammlerbox für Coincards - Vatikan, San Marino, Andorra *3D-Druck*"
    )
    assert "accessory" in sig.rejected_markers


@pytest.mark.parametrize(
    "titre",
    [
        "2 euro fdc Estonia 2016 Keres in blister",
        "2 Euro Coincard Luxemburg 2015",
        "2 Euro 2015 en capsule",
    ],
)
def test_le_marqueur_accessoire_ne_mord_pas_sur_un_emballage(titre):
    """Mutation : ajouter `blister|coincard|capsule` à la catégorie → rouge.

    Un emballage accompagne presque toujours une vraie pièce : 1 213 crops
    de la file ouverte contre 1 seul pour les marqueurs d'accessoire nu.
    Élargir ici jetterait mille pièces vraies.
    """
    assert "accessory" not in extract_listing_text_signals(titre).rejected_markers


# ── 4. une plage de millésimes n'affirme rien ────────────────────────────


def test_plage_de_millesimes_detectee():
    """Mutation : `is_range = False` en dur → rouge."""
    sig = extract_listing_text_signals("Italien 2 Euro 2004 bis 2022, prägefrisch")
    assert sig.years_are_range is True
    assert {2004, 2022} <= sig.years


def test_deux_millesimes_sans_plage_ne_sont_pas_une_plage():
    """Mutation : retirer la garde `YEAR_RANGE_RE.search(...)` → rouge.

    « 2004, 2007 » sont deux millésimes AFFIRMÉS. Les traiter comme une
    plage désarmerait le veto sur des titres qui, eux, contredisent bien.
    """
    sig = extract_listing_text_signals("2 euro commemorative 2004, 2007 Allemagne")
    assert sig.years_are_range is False


def test_une_plage_ne_contredit_pas_la_cible():
    """Mutation : retirer le `if years_are_range: return \"absent\"` → rouge.

    C'est le défaut mesuré : cible 2002, titre « 2004 bis 2022 ». La règle
    de plage englobante ne rattrapait pas ce cas (2002 n'est pas
    STRICTEMENT entre 2004 et 2022), donc l'axe rendait `contradict`, donc
    le verdict `divergent`, donc de la review humaine sur un titre honnête.
    """
    sig = extract_listing_text_signals("Italien 2 Euro 2004 bis 2022, prägefrisch")
    cmp_ = compare_to_target(
        sig,
        TargetIdentity(
            eurio_id="it-2002-2eur-standard-1st-map",
            country="IT",
            year=2002,
            face_value=2.0,
        ),
    )
    assert "year" not in cmp_.contradictions
    assert cmp_.verdict != "contradict"


def test_un_millesime_seul_contredit_toujours():
    """Mutation : rendre `absent` sans la garde de plage → rouge.

    Le veto année RESTE armé hors plage, et il le doit : sur les crops en
    `contradict`, l'exactitude de DINO tombe de 96,3 % à 64,6 %
    (mesuré le 2026-08-27 sur 305 crops tranchés). Ce n'est pas du bruit.
    """
    sig = extract_listing_text_signals("2 Euro Italia 2018 commemorativa")
    cmp_ = compare_to_target(
        sig,
        TargetIdentity(
            eurio_id="it-2002-2eur-standard-1st-map",
            country="IT",
            year=2002,
            face_value=2.0,
        ),
    )
    assert "year" in cmp_.contradictions
    assert cmp_.verdict == "contradict"


# ── 5. la version d'extracteur, seule clé d'idempotence ──────────────────


def test_la_version_dextracteur_a_bumpe_avec_les_regles():
    """Mutation : remettre `EXTRACTOR_VERSION = "v2"` → rouge.

    Les règles d'extraction ont changé le 2026-08-27. Sans bump, les 22 423
    rows `v2` déjà en base restent périmées **et** un backfill sans
    `--force` les saute toutes en annonçant « Selected 0 » et un exit 0 :
    la panne serait parfaitement muette. Ce test n'est pas là pour garder
    la valeur « v3 » — il est là pour que la prochaine personne qui touche
    aux règles voie rouge si elle oublie de bumper.
    """
    from sources._base.steps.text_signal import EXTRACTOR_VERSION

    assert EXTRACTOR_VERSION == "v3", (
        "Les règles d'extraction ont changé sans bump de version : les rows "
        "déjà en base ne seront jamais recalculées et rien ne le dira."
    )
