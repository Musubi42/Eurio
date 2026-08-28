"""Le banc tient-il ses règles d'engagement ?

`PROTOCOLE-BANC.md` en pose sept. Trois sont exécutables par un test, et ce
sont celles qui ont manqué aux sept chantiers précédents :

* **RE-2** — aucune méthode candidate ne lit l'or ni n'importe le juge ;
* **RE-5** — l'or est un artefact de données : le changer change le `sha256`
  du run, donc invalide les comparaisons ;
* **RE-7** — 60 images ne départagent pas moins de ~5 points d'amputation. Le
  banc doit le DIRE plutôt que classer.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys

import cv2
import numpy as np
import pytest

from bench.gold_crop import bras as _bras  # noqa: F401  (enregistre les bras)
from bench.gold_crop.datasets import charger
from bench.gold_crop.harness import departage, executer, re4, resume, tableau
from bench.gold_crop.iface import (
    ContexteBorne,
    ContexteCandidat,
    controler_re2,
)

TAILLE, RAYON = 500, 180.0
C = (250.0, 245.0)


def _image(chemin):
    img = np.full((TAILLE, TAILLE, 3), 235, np.uint8)
    cv2.circle(img, (int(C[0]), int(C[1])), int(RAYON), (150, 150, 150), -1)
    cv2.circle(img, (int(C[0]), int(C[1])), int(0.735 * RAYON), (95, 95, 95), -1)
    for k in range(12):
        a = 2 * math.pi * k / 12
        cv2.circle(img, (int(C[0] + 0.86 * RAYON * math.cos(a)),
                         int(C[1] + 0.86 * RAYON * math.sin(a))),
                   int(0.05 * RAYON), (60, 60, 60), -1)
    cv2.imwrite(str(chemin), img)


def _jeu(tmp_path, n=6, indecidable=(), non_annote=(), k_hint=1.0,
         strate_confirmee=None, avec_passe2=False):
    (tmp_path / "raws").mkdir(parents=True, exist_ok=True)
    images, annots, annots2 = [], {}, {}
    for i in range(n):
        aid = f"{i:032x}"
        _image(tmp_path / "raws" / f"{aid}.jpg")
        images.append({
            "asset_id": aid, "role": "tirage",
            "strate": "S1_facile" if i % 2 else "S4_oblique",
            "verdict": "accept" if i % 2 else "reject",
            "fichier": f"raws/{aid}.jpg", "width": TAILLE, "height": TAILLE,
            "hint": {"cx": C[0], "cy": C[1], "r": k_hint * RAYON},
        })
        if aid in non_annote:
            continue
        annots[aid] = {
            "asset_id": aid, "indecidable": aid in indecidable,
            "strate_confirmee": strate_confirmee,
            "ellipse": {"cx": C[0], "cy": C[1], "a": RAYON, "b": RAYON, "theta": 0.0},
        }
        if avec_passe2:
            annots2[aid] = {"ellipse": {"cx": C[0], "cy": C[1],
                                        "a": RAYON * 1.005, "b": RAYON, "theta": 0.0}}
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"version": "vtest", "requete_sha256": "req", "images": images}))
    (tmp_path / "gold.json").write_text(json.dumps({"annotations": annots}))
    if avec_passe2:
        (tmp_path / "gold.pass2.json").write_text(json.dumps({"annotations": annots2}))
    return tmp_path


# ─── RE-2 : la séparation juge / méthode ────────────────────────────────────

def test_un_contexte_de_candidat_ne_porte_pas_l_or():
    """La frontière est un TYPE, pas une consigne : un candidat ne peut pas
    lire l'or, même en le voulant."""
    ctx = ContexteCandidat(10, 10, {"cx": 1, "cy": 1, "r": 1})
    assert not hasattr(ctx, "gold")
    assert hasattr(ContexteBorne(10, 10, {}, None, None), "gold")


def _module_bras(tmp_path, nom_module: str, source: str):
    """Charge un bras depuis SON PROPRE module.

    ⚠️ Nécessaire : `controler_re2` scanne le module entier, volontairement — un
    bras pourrait lire l'or via un helper de module plutôt qu'en ligne. Un bras
    déclaré dans ce fichier de test serait donc signalé, ce fichier citant
    `gold.json` dans ses fixtures. Le faux positif est le prix du bon niveau de
    contrôle.
    """
    chemin = tmp_path / f"{nom_module}.py"
    chemin.write_text(source)
    spec = importlib.util.spec_from_file_location(nom_module, chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom_module] = mod
    spec.loader.exec_module(mod)
    return mod


_SONDE = """
from bench.gold_crop.iface import Candidat, enregistrer
VUS = []

@enregistrer({nom!r}, borne={borne})
def sonde(raw, ctx):
    VUS.append((hasattr(ctx, 'gold'), hasattr(ctx, 'gold_2e_passe')))
    return [Candidat(250.0, 245.0, 180.0, {nom!r})]
"""


def _avec_sonde(tmp_path, nom, borne):
    from bench.gold_crop import iface
    mod = _module_bras(tmp_path / "m", nom, _SONDE.format(nom=nom, borne=borne))
    try:
        yield mod
    finally:
        iface._REGISTRE.pop(nom, None)
        sys.modules.pop(nom, None)


def test_le_harness_ne_donne_pas_l_or_a_un_candidat(tmp_path):
    """Le type ne suffit pas : encore faut-il que le banc passe le BON. C'est
    `executer` qu'on interroge, pas la déclaration."""
    (tmp_path / "m").mkdir(parents=True, exist_ok=True)
    gen = _avec_sonde(tmp_path, "sonde_candidat", False)
    mod = next(gen)
    try:
        executer("sonde_candidat", charger(_jeu(tmp_path, n=2, avec_passe2=True)))
        assert mod.VUS == [(False, False), (False, False)]
    finally:
        next(gen, None)


def test_une_borne_recoit_bien_l_or(tmp_path):
    (tmp_path / "m").mkdir(parents=True, exist_ok=True)
    gen = _avec_sonde(tmp_path, "sonde_borne", True)
    mod = next(gen)
    try:
        executer("sonde_borne", charger(_jeu(tmp_path, n=2, avec_passe2=True)))
        assert mod.VUS == [(True, True), (True, True)]
    finally:
        next(gen, None)


def test_un_bras_candidat_qui_importe_le_juge_est_disqualifie(tmp_path):
    mod = tmp_path / "bras_tricheur.py"
    mod.write_text(
        "from bench.gold_crop.judge import c1\n"
        "from bench.gold_crop.iface import Candidat, enregistrer\n"
        "@enregistrer('tricheur')\n"
        "def tricheur(raw, ctx):\n"
        "    return [Candidat(0, 0, 1, 'tricheur')]\n")
    spec = importlib.util.spec_from_file_location("bras_tricheur", mod)
    m = importlib.util.module_from_spec(spec)
    sys.modules["bras_tricheur"] = m
    try:
        spec.loader.exec_module(m)
        fautes = controler_re2("tricheur")
        assert fautes and "importe le juge" in fautes[0]
        with pytest.raises(RuntimeError, match="RE-2"):
            executer("tricheur", charger(_jeu(tmp_path)))
    finally:
        from bench.gold_crop import iface
        iface._REGISTRE.pop("tricheur", None)
        sys.modules.pop("bras_tricheur", None)


def test_une_borne_a_le_droit_de_lire_l_or():
    """`gold_replay` et `human_2nd_pass` lisent l'or — c'est leur raison d'être.
    Les soumettre à RE-2 supprimerait le plafond et le plancher du tableau."""
    assert controler_re2("gold_replay") == []
    assert controler_re2("human_2nd_pass") == []


# ─── le chargement du jeu ───────────────────────────────────────────────────

def test_sans_annotation_le_banc_refuse_au_lieu_de_tourner_a_vide(tmp_path):
    _jeu(tmp_path)
    (tmp_path / "gold.json").unlink()
    with pytest.raises(FileNotFoundError, match="annotate.serve"):
        charger(tmp_path)


def test_un_indecidable_sort_du_jeu_et_n_est_pas_remplace_en_douce(tmp_path):
    """Un jeu d'or qui se répare tout seul n'est plus un jeu d'or : la réserve
    existe pour que le PO en annote une de plus, pas pour qu'un script
    substitue une image dans son dos."""
    jeu = charger(_jeu(tmp_path, n=6, indecidable={f"{0:032x}", f"{3:032x}"}))
    assert len(jeu.cas) == 4
    assert set(jeu.indecidables) == {f"{0:032x}", f"{3:032x}"}
    assert jeu.non_annotes == []


def test_une_image_non_annotee_est_signalee_pas_ignoree(tmp_path):
    jeu = charger(_jeu(tmp_path, n=4, non_annote={f"{1:032x}"}))
    assert jeu.non_annotes == [f"{1:032x}"] and len(jeu.cas) == 3


def test_la_strate_confirmee_prime_sur_celle_du_tirage(tmp_path):
    jeu = charger(_jeu(tmp_path, n=2, strate_confirmee="S2_capsule"))
    assert {c.strate_retenue for c in jeu.cas} == {"S2_capsule"}
    assert {c.strate for c in jeu.cas} == {"S1_facile", "S4_oblique"}


def test_re5_changer_l_or_change_le_sha_du_run(tmp_path):
    """Un or modifié = une nouvelle version = tous les bras ré-exécutés. Le
    `sha256` est ce qui rend une comparaison entre deux runs vérifiable."""
    racine = _jeu(tmp_path, n=2)
    avant = charger(racine).gold_sha256
    d = json.loads((racine / "gold.json").read_text())
    next(iter(d["annotations"].values()))["ellipse"]["a"] = RAYON + 1
    (racine / "gold.json").write_text(json.dumps(d))
    assert charger(racine).gold_sha256 != avant


# ─── exécution ──────────────────────────────────────────────────────────────

def test_un_run_porte_tout_ce_qu_il_faut_pour_le_relire(tmp_path):
    run = executer("baseline_prod", charger(_jeu(tmp_path, n=4)))
    for cle in ("arm", "gold_version", "gold_sha256", "judge_version", "m",
                "d_frac", "arc_min", "cases"):
        assert cle in run, cle
    c = run["cases"][0]
    for cle in ("asset_id", "strate_retenue", "verdict_humain", "gold", "pred",
                "C1_marge_min_frac", "C1_ok", "arc_coverage", "C2_ok",
                "boundary_iou", "mask_iou", "hausdorff_frac", "ampute"):
        assert cle in c, cle


def test_tous_les_candidats_sont_journalises_pas_seulement_le_retenu(tmp_path):
    """Ce qui permet d'évaluer une politique hybride post-hoc, SANS re-run."""
    run = executer("measure_tilt_ellipse", charger(_jeu(tmp_path, n=2)))
    assert all(c["candidats"] for c in run["cases"])


def test_un_hint_ampute_est_vu_comme_ampute(tmp_path):
    """Le banc doit d'abord savoir voir une amputation qu'on lui pose."""
    sain = executer("baseline_prod", charger(_jeu(tmp_path / "a", k_hint=1.05)))
    casse = executer("baseline_prod", charger(_jeu(tmp_path / "b", k_hint=0.85)))
    assert resume(sain)["amputation_pct"] == 0.0
    assert resume(casse)["amputation_pct"] == 100.0


def test_gold_replay_est_un_vrai_plafond_pas_un_plancher(tmp_path):
    """Le plafond du banc doit être **à 0 % d'amputation** — sinon il ne plafonne
    rien.

    C'est ce que D9 a réglé : `gold_replay` prend `r = a`, donc le masque coupe
    pile sur le listel. Tant qu'`ampute` exigeait 2 % de marge sur la région
    retenue, le plafond était à 100 % et le tableau illisible. Séparer
    « amputé » (0 % de tolérance sur les pixels) de « marge promise tenue »
    (2 % sur le cadre) rend au plafond son rôle — et la seconde ligne dit
    quand même la vérité sur le padding.
    """
    run = executer("gold_replay", charger(_jeu(tmp_path, n=4)))
    assert run["borne"] is True
    s = resume(run)
    assert s["amputation_pct"] == 0.0
    # …et la marge promise est tenue elle aussi : le cadre a un demi-côté
    # `1,02·r`, donc exactement 2 % d'air autour d'une pièce de rayon `a`.
    # La perte du format ne se voit PAS dans C1 — elle se voit dans la Boundary
    # IoU, parce qu'un cercle ne peut pas épouser une ellipse.
    assert s["marge_promise_ko_pct"] == 0.0
    assert all(c["boundary_iou"] > 0.9 for c in run["cases"])   # or circulaire ici


def test_human_2nd_pass_est_absent_sans_seconde_passe(tmp_path):
    run = executer("human_2nd_pass", charger(_jeu(tmp_path, n=3)))
    assert all(c.get("absent") for c in run["cases"])
    assert resume(run)["n"] == 0


def test_human_2nd_pass_mesure_le_bruit_de_la_main(tmp_path):
    run = executer("human_2nd_pass", charger(_jeu(tmp_path, n=3, avec_passe2=True)))
    s = resume(run)
    assert s["n"] == 3 and s["biou_med"] > 0.8


# ─── RE-7 et RE-4 ───────────────────────────────────────────────────────────

def _run_factice(nom, cas):
    return {"arm": nom, "borne": False, "cases": cas}


def _cas(verdict, ampute, biou=0.5):
    return {"asset_id": "x", "strate_retenue": "S1_facile", "verdict_humain": verdict,
            "ampute": ampute, "C1_ok": not ampute, "C2_ok": True,
            "boundary_iou": biou, "mask_iou": 0.9, "hausdorff_frac": 0.05,
            "C1_marge_min_frac": 0.03 if not ampute else -0.05}


def test_re7_un_petit_ecart_n_est_pas_un_departage():
    a = _run_factice("A", [_cas("accept", i < 10) for i in range(100)])
    b = _run_factice("B", [_cas("accept", i < 13) for i in range(100)])
    assert "pas un départage" in departage(a, b)
    c = _run_factice("C", [_cas("accept", i < 30) for i in range(100)])
    assert "devant" in departage(a, c) and "A devant C" in departage(a, c)


def test_re4_dit_quand_le_juge_separe():
    cas = ([_cas("reject", True) for _ in range(20)]
           + [_cas("accept", False) for _ in range(20)])
    v = re4(_run_factice("baseline_prod", cas))
    assert v["verdict"] == "sépare" and v["fisher_p"] < 0.001


def test_re4_dit_quand_le_juge_ne_separe_pas():
    """Le cas qui compte : un juge géométriquement cohérent mais aveugle au
    verdict humain. `quality_score` y a échoué à 0,0008 près."""
    cas = ([_cas("reject", i % 2 == 0) for i in range(20)]
           + [_cas("accept", i % 2 == 0) for i in range(20)])
    v = re4(_run_factice("baseline_prod", cas))
    assert v["verdict"] == "NE SÉPARE PAS" and v["fisher_p"] > 0.05


def test_le_tableau_met_les_bornes_en_tete():
    """Un tableau sans plancher ni plafond est illisible."""
    runs = [{"arm": "baseline_prod", "borne": False, "cases": [_cas("accept", False)]},
            {"arm": "gold_replay", "borne": True, "cases": [_cas("accept", True)]},
            {"arm": "human_2nd_pass", "borne": True, "cases": [_cas("accept", False)]}]
    lignes = tableau(runs).splitlines()
    assert "human_2nd_pass" in lignes[2] and "gold_replay" in lignes[3]
    assert "baseline_prod" in lignes[4]
