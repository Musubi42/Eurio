"""Publier le tirage dans le canonique — la conversion, et les deux refus.

Trois propriétés, et rien d'autre :

* **le verdict humain ne monte pas.** Le manifeste le porte, le tirage servi à
  l'annotateur ne doit pas : qui voit le verdict le confirme au lieu de tracer
  ce qu'il voit, et RE-4 ne mesure plus rien ;
* **la conversion est fidèle** — `prefill.ok = false` devient `null` mais la
  raison survit, et `major/minor/angle` deviennent `a/b/theta_deg` ;
* **l'UA est posé.** `eurio-api.musubi.dev` est derrière Cloudflare, qui refuse
  `Python-urllib/3.x` avec un 403 « error code: 1010 » — une page HTML, pas du
  JSON. La panne ne se voit QUE dans l'outil.

Aucun réseau : `urlopen` est remplacé par un canonique de paille, celui de
`test_gold_crop_fetch`.
"""

from __future__ import annotations

import json

import pytest

from bench.gold_crop import publier_tirage as P
from tests.test_gold_crop_fetch import _Erreur, _brancher

ASSET_A = "a" * 32
ASSET_B = "b" * 32


def _image(asset_id=ASSET_A, **kw):
    img = {"asset_id": asset_id, "source_image_id": "si0", "source": "ebay",
           "raw_path": "ebay/si0.jpg", "width": 900, "height": 900,
           "bbox_json": "{}", "role": "tirage", "strate": "S1_facile", "rn": 1,
           "verdict": "reject", "tilt_deg": 10.6, "axis_ratio": 0.983,
           "fichier": "raws/a.jpg",
           "hint": {"cx": 450.5, "cy": 449.4, "r": 449.3},
           "prefill": {"ok": True, "cx": 453.5, "cy": 450.3, "major": 401.4,
                       "minor": 394.6, "angle": 21.53, "axis_ratio": 0.983,
                       "trustworthy": False, "reason": "too_circular:0.983"}}
    img.update(kw)
    return img


def _manifeste(tmp_path, images=None, **kw):
    out = tmp_path / "v1"
    out.mkdir(exist_ok=True)
    corps = {"version": "v1", "db": "/x/eurio.replica.db",
             "requete_sha256": "req-a", "n_tirage": 1, "n_reserve": 0,
             "images": images if images is not None else [_image()]}
    corps.update(kw)
    (out / "manifest.json").write_text(json.dumps(corps))
    return out


def _lancer(monkeypatch, out, reponses, vu=None, argv=()):
    _brancher(monkeypatch, P, reponses, vu)
    return P.main(["--out", str(out), "--api-url", "https://api.test",
                   "--api-token", "tok", *argv])


OK = {"ok": True, "gold_version": "v1", "n": 1, "ignorees": []}


# ─── la conversion ──────────────────────────────────────────────────────────

def test_le_verdict_ne_monte_pas(tmp_path, monkeypatch, capsys):
    """Mutation : ajouter `verdict` à `entree_tirage` → rouge."""
    vu = []
    out = _manifeste(tmp_path)
    assert _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": OK}, vu) == 0
    (image,) = vu[0]["corps"]["images"]
    assert "verdict" not in image
    assert set(image) == {"asset_id", "role", "rn", "strate_tiree", "width",
                          "height", "hint", "prefill", "prefill_reason"}


def test_les_demi_axes_prennent_le_vocabulaire_du_canonique(tmp_path, monkeypatch):
    """`major/minor/angle` (measure_tilt) → `a/b/theta_deg` (0019/0020). Envoyer
    les noms d'origine ferait tomber le pré-remplissage à `null` en silence —
    pydantic jetterait le champ inconnu et le groupe deviendrait incomplet."""
    vu = []
    out = _manifeste(tmp_path)
    _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": OK}, vu)
    (image,) = vu[0]["corps"]["images"]
    assert image["prefill"] == {"cx": 453.5, "cy": 450.3, "a": 401.4,
                                "b": 394.6, "theta_deg": 21.53}
    assert image["hint"] == {"cx": 450.5, "cy": 449.4, "r": 449.3}
    assert image["strate_tiree"] == "S1_facile"


def test_un_prefill_en_echec_devient_null_mais_garde_sa_raison(tmp_path, monkeypatch):
    """Une proposition ABSENTE et une proposition DOUTEUSE ne sont pas la même
    chose : la raison dit sur quelles strates `measure_tilt` propose mal."""
    vu = []
    # ⚠️ des coordonnées SONT présentes : `measure_tilt` rend ce qu'il a trouvé
    # même quand il se déclare en échec. C'est `ok` qui tranche, et lui seul —
    # sans ces valeurs, le test passerait aussi si la garde disparaissait.
    out = _manifeste(tmp_path, [_image(prefill={
        "ok": False, "cx": 12.0, "cy": 13.0, "major": 9.0, "minor": 8.0,
        "angle": 3.0, "reason": "no_contour"})])
    _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": OK}, vu)
    (image,) = vu[0]["corps"]["images"]
    assert image["prefill"] is None and image["prefill_reason"] == "no_contour"


def test_la_requete_du_manifeste_accompagne_le_tirage(tmp_path, monkeypatch):
    """Sans elle, le canonique ne peut pas refuser un tirage venu d'une AUTRE
    requête — et le jeu se croirait reproductible sans l'être (RE-5)."""
    vu = []
    out = _manifeste(tmp_path)
    _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": OK}, vu)
    assert vu[0]["corps"]["requete_sha256"] == "req-a"
    assert vu[0]["methode"] == "PUT" and vu[0]["chemin"] == "/crop-gold/v1/tirage"


def test_l_user_agent_est_pose(tmp_path, monkeypatch):
    """⚠️ Cloudflare refuse l'UA par défaut d'urllib avec un 403 « error code:
    1010 » — une page HTML, pas du JSON. Mutation : retirer l'en-tête → rouge."""
    vu = []
    out = _manifeste(tmp_path)
    _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": OK}, vu)
    assert vu[0]["ua"] == P.USER_AGENT
    assert vu[0]["auth"] == "Bearer tok"


def test_la_version_du_cli_prime_sur_celle_du_manifeste(tmp_path, monkeypatch):
    vu = []
    out = _manifeste(tmp_path)
    code = _lancer(monkeypatch, out, {"/crop-gold/v2/tirage": OK}, vu,
                   argv=("--version", "v2"))
    assert code == 0 and vu[0]["chemin"] == "/crop-gold/v2/tirage"


# ─── ce qui s'affiche, et les codes de sortie ───────────────────────────────

def test_le_compte_par_role_et_strate_est_affiche(tmp_path, monkeypatch, capsys):
    out = _manifeste(tmp_path, [
        _image(ASSET_A), _image(ASSET_B, role="reserve", strate="S4_oblique")])
    _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": {**OK, "n": 2}})
    sortie = capsys.readouterr().out
    assert "publiées : 2 / 2" in sortie
    assert "tirage   S1_facile    1" in sortie
    assert "reserve  S4_oblique   1" in sortie


def test_les_ignorees_sont_listees_sans_faire_echouer(tmp_path, monkeypatch, capsys):
    """Un asset purgé ne fait pas tomber le tirage — mais il ne passe pas non
    plus sous silence : la séance aura moins d'images que prévu."""
    out = _manifeste(tmp_path)
    code = _lancer(monkeypatch, out,
                   {"/crop-gold/v1/tirage": {**OK, "n": 0, "ignorees": [ASSET_A]}})
    sortie = capsys.readouterr().out
    assert code == 0 and "IGNORÉE(S)" in sortie and ASSET_A in sortie


def test_un_409_sort_en_2_avec_la_raison_verbatim(tmp_path, monkeypatch, capsys):
    """Gel, ou requête divergente. La raison du serveur est reprise telle
    quelle : la reformuler perdrait ce qui dit quoi faire."""
    out = _manifeste(tmp_path)
    code = _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": _Erreur(
        409, '{"detail":"l\'or v1 est gelé depuis 2026-09-01"}')})
    sortie = capsys.readouterr().out
    assert code == 2 and "gelé depuis 2026-09-01" in sortie


def test_un_403_cloudflare_sort_en_1_en_disant_lequel(tmp_path, monkeypatch, capsys):
    out = _manifeste(tmp_path)
    code = _lancer(monkeypatch, out,
                   {"/crop-gold/v1/tirage": _Erreur(403, "<html>error code: 1010</html>")})
    sortie = capsys.readouterr().out
    assert code == 1 and "Cloudflare" in sortie


def test_sans_token_rien_n_est_tente(tmp_path, monkeypatch, capsys):
    """Le tirage s'écrit dans le canonique : il n'a aucun sens en local, et un
    message qui dit « charge le devShell » vaut mieux qu'une trace réseau."""
    vu = []
    out = _manifeste(tmp_path)
    _brancher(monkeypatch, P, {}, vu)
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    monkeypatch.delenv("EURIO_API_TOKEN", raising=False)
    assert P.main(["--out", str(out), "--api-url", "", "--api-token", ""]) == 1
    assert vu == [] and "devShell" in capsys.readouterr().out


def test_sans_manifeste_le_cli_dit_ou_le_fabriquer(tmp_path, monkeypatch, capsys):
    vu = []
    _brancher(monkeypatch, P, {}, vu)
    code = P.main(["--out", str(tmp_path / "vide"), "--api-url", "https://api.test",
                   "--api-token", "tok"])
    assert code == 1 and vu == []
    assert "bench.gold_crop.sample" in capsys.readouterr().out


def test_un_manifeste_sans_image_ne_publie_rien(tmp_path, monkeypatch):
    vu = []
    out = _manifeste(tmp_path, [])
    assert _lancer(monkeypatch, out, {"/crop-gold/v1/tirage": OK}, vu) == 1
    assert vu == []
