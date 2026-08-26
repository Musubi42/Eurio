"""La sous-banque de la matrice — ce qu'elle fusionne, et ce qu'elle refuse.

Chantier `juge-et-banc`, étape 4 (D3).

Ce que ces tests verrouillent :

1. **la FUSION.** Les émissions communes européennes vivent dans la banque
   servie comme une classe PAR PAYS (jusqu'à 21 pour un seul dessin) ; le
   manifeste et ArcFace les traitent comme une seule. Un filtre sans fusion
   demanderait à DINO de désigner le bon pays entre des images identiques ;
2. **les trois refus**, et chacun protège un chiffre :
   - une ancre qui EST un crop d'éval se noterait elle-même à similarité 1,0 ;
   - une classe sans ancre voit ses crops partir en `out_of_scope` : le recall
     est alors calculé sur moins de classes qu'annoncé — faux, pas partiel ;
   - un `source_path` absent est laissé tomber par `encode_paths` **en
     silence**, donc l'ancre disparaît sans qu'on le sache ;
3. **la banque SERVIE n'est jamais visée** (D3).

Run: `.venv/bin/python -m pytest ml/tests/test_matrice_subbank.py -q`
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from scripts.build_matrice_subbank import SOURCE_KIND, main, restreindre  # noqa: E402
from training.foundation.anchors import AnchorBank  # noqa: E402

#: Les trois pays d'une même émission commune, telles que la banque servie les
#: porte : une classe chacun, parce que `bank_class_ids` rend `[eurio_id]` pour
#: toute commémorative.
COMMUNES = ("at-2015-2eur-flag", "be-2015-2eur-flag", "fr-2015-2eur-flag")

#: La maille du produit : les trois se replient sur un seul dessin.
MESH = {
    **{e: "eu-eu-flag-2015" for e in COMMUNES},
    "de-2018-2eur-schmidt": "de-2018-2eur-schmidt",
    "es-2016-2eur-segovia": "es-2016-2eur-segovia",
    "hors-sujet": "hors-sujet",
}


def _bank(tmp_path, entrees):
    """``entrees`` = liste de ``(eurio_id, asset_id|None, fichier_existe)``."""
    eids, aids, paths = [], [], []
    for i, (eid, aid, existe) in enumerate(entrees):
        p = tmp_path / f"anchor-{i}.jpg"
        if existe:
            p.write_bytes(b"x")
        eids.append(eid)
        aids.append(aid)
        paths.append(str(p))
    return AnchorBank(
        eurio_ids=eids,
        matrix=np.zeros((len(eids), 4), dtype=np.float32),
        encoder_version="dinov2-vitl14",
        anchors_kind=SOURCE_KIND,
        built_at="2026-08-24T20:41:15+00:00",
        source_paths=paths,
        asset_ids=aids,
        bank_id="deadbeef",
    )


# ─── 1. La fusion ────────────────────────────────────────────────────────────


def test_les_classes_pays_dune_emission_commune_fusionnent(tmp_path):
    """LE test de ce module.

    Trois classes de banque, un seul dessin : après restriction elles ne font
    qu'une, et cette classe porte les trois ancres. Fusionner n'appauvrit rien
    — une classe de banque porte PLUSIEURS ancres par construction.
    """
    bank = _bank(tmp_path, [(e, f"a{i}", True) for i, e in enumerate(COMMUNES)])
    plan = restreindre(bank, classes={"eu-eu-flag-2015"}, mesh=MESH,
                       eval_asset_ids=set())
    assert plan["par_classe"] == {"eu-eu-flag-2015": 3}
    assert len(plan["garde"]) == 3
    assert plan["sans_ancre"] == []


def test_une_classe_hors_manifeste_est_ecartee(tmp_path):
    """La restriction est le point du lot : sans elle, DINO affronterait 671
    distracteurs là où ArcFace n'en a que 60."""
    bank = _bank(tmp_path, [
        ("de-2018-2eur-schmidt", "a0", True),
        ("hors-sujet", "a1", True),
    ])
    plan = restreindre(bank, classes={"de-2018-2eur-schmidt"}, mesh=MESH,
                       eval_asset_ids=set())
    assert plan["par_classe"] == {"de-2018-2eur-schmidt": 1}
    assert plan["garde"] == [0]


# ─── 2. Les trois refus ──────────────────────────────────────────────────────


def test_une_ancre_qui_est_un_crop_deval_est_signalee_et_ecartee(tmp_path):
    """Elle se noterait elle-même à similarité 1,0.

    La banque servie n'en contient aucune aujourd'hui — D5 avait exclu les
    ancres du prélèvement. Ce garde existe pour que ça reste vrai après un
    rebuild de la banque, qui pourrait très bien élire un crop d'éval comme
    ancre sans que personne ne le remarque.
    """
    bank = _bank(tmp_path, [
        ("de-2018-2eur-schmidt", "sain", True),
        ("de-2018-2eur-schmidt", "crop-deval", True),
    ])
    plan = restreindre(bank, classes={"de-2018-2eur-schmidt"}, mesh=MESH,
                       eval_asset_ids={"crop-deval"})
    assert plan["fuites"] == ["crop-deval"]
    assert plan["garde"] == [0], "la fuite est écartée, pas seulement signalée"


def test_une_classe_sans_ancre_est_nommee(tmp_path):
    """Ses crops partiraient en `out_of_scope` et disparaîtraient du
    dénominateur : un recall calculé sur 59 classes présenté comme couvrant les
    60 est un chiffre FAUX, pas un chiffre partiel."""
    bank = _bank(tmp_path, [("de-2018-2eur-schmidt", "a0", True)])
    plan = restreindre(
        bank, classes={"de-2018-2eur-schmidt", "es-2016-2eur-segovia"},
        mesh=MESH, eval_asset_ids=set(),
    )
    assert plan["sans_ancre"] == ["es-2016-2eur-segovia"]


def test_une_classe_videe_par_une_fuite_compte_comme_sans_ancre(tmp_path):
    """Le cas composé, et le plus dangereux : la classe EXISTE dans la banque,
    mais sa seule ancre était un crop d'éval. Sans ce chaînage on écarterait la
    fuite et on croirait la classe couverte."""
    bank = _bank(tmp_path, [("de-2018-2eur-schmidt", "crop-deval", True)])
    plan = restreindre(bank, classes={"de-2018-2eur-schmidt"}, mesh=MESH,
                       eval_asset_ids={"crop-deval"})
    assert plan["fuites"] == ["crop-deval"]
    assert plan["sans_ancre"] == ["de-2018-2eur-schmidt"]


def test_un_source_path_absent_est_signale_pas_ignore(tmp_path):
    """`encode_paths` laisse tomber un chemin illisible SANS erreur : l'ancre
    disparaîtrait de la banque du run sans que rien ne le dise. On préfère le
    savoir avant de calculer."""
    bank = _bank(tmp_path, [
        ("de-2018-2eur-schmidt", "a0", True),
        ("de-2018-2eur-schmidt", "a1", False),
    ])
    plan = restreindre(bank, classes={"de-2018-2eur-schmidt"}, mesh=MESH,
                       eval_asset_ids=set())
    assert len(plan["chemins_absents"]) == 1
    assert plan["garde"] == [0]


def test_une_ligne_canonique_na_pas_dasset_id_et_passe(tmp_path):
    """Les avers Numista entrent avec `asset_id` vide. Les confondre avec une
    fuite viderait la banque de ses 142 lignes canoniques."""
    bank = _bank(tmp_path, [("de-2018-2eur-schmidt", None, True)])
    plan = restreindre(bank, classes={"de-2018-2eur-schmidt"}, mesh=MESH,
                       eval_asset_ids={"crop-deval"})
    assert plan["garde"] == [0] and plan["fuites"] == []


# ─── 3. La banque servie n'est jamais visée ──────────────────────────────────


def test_ecrire_sur_le_kind_servi_est_refuse(capsys):
    """D3 : la banque servie n'est pas touchée. Le `kind` distinct est ce qui
    empêche `save_anchors` de viser son fichier — le rendre égal contournerait
    la garantie, donc c'est refusé avant tout calcul."""
    code = main(["--kind", SOURCE_KIND, "--apply"])
    assert code == 2
    assert "banque SERVIE" in capsys.readouterr().err


def test_un_manifeste_a_la_mauvaise_maille_est_refuse(tmp_path, capsys):
    """Le manifeste et la sous-banque doivent replier sur la MÊME maille,
    sinon le garde d'espace de labels refusera — après le calcul."""
    gold = tmp_path / "g.jsonl"
    gold.write_text(
        '{"asset_id": "a0", "class_id": "at-2015-2eur-flag", "decided_at": "",'
        ' "decided_by": null, "face": null, "review_kind": null,'
        ' "storage_path": "x.png", "training_eligible": 1, "truth_country": "at",'
        ' "truth_eurio_id": "at-2015-2eur-flag"}\n', encoding="utf-8")
    (tmp_path / "g.meta.json").write_text('{"mesh": "bank"}', encoding="utf-8")

    assert main(["--gold", str(gold)]) == 2
    assert "maille" in capsys.readouterr().err


def test_un_manifeste_absent_dit_quoi_lancer(tmp_path, capsys):
    """Un `FileNotFoundError` nu ferait chercher la cause ; le nom de la
    commande à lancer la donne."""
    assert main(["--gold", str(tmp_path / "jamais.jsonl")]) == 2
    assert "eval_corpus_gold build" in capsys.readouterr().err
