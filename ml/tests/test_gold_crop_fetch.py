"""Rapatrier l'or du canonique — et ne jamais perdre le filet local.

Le `gold.json` local n'est pas la source de vérité (D11), mais il est la SEULE
copie d'une annotation dont l'envoi a échoué. Ces tests portent sur les trois
propriétés qui comptent : le format rendu est exactement celui que le banc
lit, le filet n'est pas écrasé à l'aveugle, et un or GELÉ dont l'empreinte a
bougé arrête tout.

Aucun réseau : `urlopen` est remplacé par un canonique de paille.
"""

from __future__ import annotations

import json
import math
import urllib.error

import pytest

from bench.gold_crop import fetch as F
from bench.gold_crop import geler as G

ASSET_A = "a" * 32
ASSET_B = "b" * 32


# ─── un canonique de paille ─────────────────────────────────────────────────

class _Reponse:
    def __init__(self, corps: bytes):
        self._corps = corps

    def read(self):
        return self._corps

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Erreur(urllib.error.HTTPError):
    """Une vraie `HTTPError` — le code la trie par `except`, pas par duck-typing."""

    def __init__(self, code, corps):                       # noqa: D107
        self.code = code
        self._corps = corps.encode() if isinstance(corps, str) else corps

    def read(self):
        return self._corps


def _brancher(monkeypatch, module, reponses: dict, vu: list | None = None):
    """`reponses` : chemin → dict (rendu en JSON) ou `_Erreur` (levée)."""

    def faux_urlopen(req, timeout=None):
        chemin = req.full_url.split("://", 1)[1].split("/", 1)[1]
        if vu is not None:
            vu.append({"chemin": "/" + chemin, "methode": req.get_method(),
                       "ua": req.get_header("User-agent"),
                       "auth": req.get_header("Authorization"),
                       "corps": json.loads(req.data) if req.data else None})
        rep = reponses.get("/" + chemin)
        if rep is None:
            raise _Erreur(404, '{"detail":"inconnu"}')
        if isinstance(rep, _Erreur):
            raise rep
        return _Reponse(json.dumps(rep).encode())

    monkeypatch.setattr(module.urlrequest, "urlopen", faux_urlopen)


def _ligne(asset_id=ASSET_A, passe=1, **kw):
    ligne = {"gold_version": "v1", "asset_id": asset_id, "passe": passe,
             "actor": "po", "cx": 450.5, "cy": 400.25, "a": 300.0, "b": 290.0,
             "theta_deg": 12.5, "indecidable": 0, "strate_tiree": "S1_facile",
             "strate_confirmee": "S4_oblique", "secondes": 24.5,
             "prefill_modifie": 1, "editor_version": "gold_v1",
             "width": 900, "height": 900, "source": "ebay"}
    ligne.update(kw)
    return ligne


def _payload(lignes, *, frozen_at=None, snapshot_sha256=None):
    return {"gold_version": "v1", "n": len(lignes), "annotations": lignes,
            "version": {"gold_version": "v1", "frozen_at": frozen_at,
                        "snapshot_sha256": snapshot_sha256,
                        "requete_sha256": "abc", "snapshot_key": None,
                        "note": None, "created_at": "2026-08-29"}}


def _manifeste(racine, assets=(ASSET_A,)):
    (racine / "manifest.json").write_text(json.dumps({
        "version": "v1", "requete_sha256": "abc",
        "images": [{"asset_id": a, "role": "tirage", "strate": "S1_facile",
                    "verdict": "accept", "fichier": f"raws/{a}.jpg",
                    "width": 900, "height": 900, "hint": {}} for a in assets]}))


def _lancer(monkeypatch, out, reponses, argv=()):
    _brancher(monkeypatch, F, reponses)
    return F.main(["--out", str(out), "--api-url", "https://faux.test",
                   "--api-token", "tok", *argv])


# ─── le format : ce que le banc lit doit être ce que le canonique dit ───────

def test_le_gold_json_rapatrie_donne_au_banc_la_MEME_ellipse(monkeypatch, tmp_path,
                                                             capsys):
    """Le pont canonique → `charger()` ne doit rien déformer. `theta_deg`
    redevient `theta` : l'oublier ferait charger une ellipse d'angle nul, donc
    un `d = 0,08·a` faux, sans le moindre message."""
    _manifeste(tmp_path)
    assert _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([_ligne()])}) == 0

    from bench.gold_crop.datasets import charger
    jeu = charger(tmp_path)
    (cas,) = jeu.cas
    assert cas.asset_id == ASSET_A
    assert cas.strate_retenue == "S4_oblique"      # la CONFIRMÉE prime
    assert cas.gold.cx == pytest.approx(450.5)
    assert cas.gold.cy == pytest.approx(400.25)
    assert cas.gold.a == pytest.approx(300.0)
    assert cas.gold.b == pytest.approx(290.0)
    assert math.degrees(cas.gold.theta) == pytest.approx(12.5)


def test_l_entree_a_la_forme_de_celle_qu_ecrit_l_outil(monkeypatch, tmp_path):
    """Mêmes clés que `annotate/index.html` : `serve.py` doit pouvoir reprendre
    une séance sur un fichier rapatrié sans re-annoter ce qui est déjà fait."""
    _manifeste(tmp_path)
    _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([_ligne()])})
    ecrit = json.loads((tmp_path / "gold.json").read_text())
    entree = ecrit["annotations"][ASSET_A]
    assert set(entree["ellipse"]) == {"cx", "cy", "a", "b", "theta"}
    assert entree["indecidable"] is False and entree["prefill_modifie"] is True
    assert entree["strate_confirmee"] == "S4_oblique"
    assert entree["secondes"] == 24.5
    assert ecrit["passe"] == 1 and ecrit["n"] == 1


def test_un_indecidable_sans_ellipse_reste_un_indecidable(monkeypatch, tmp_path):
    _manifeste(tmp_path)
    ligne = _ligne(indecidable=1, cx=None, cy=None, a=None, b=None, theta_deg=None)
    _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([ligne])})
    entree = json.loads((tmp_path / "gold.json").read_text())["annotations"][ASSET_A]
    assert entree["ellipse"] is None and entree["indecidable"] is True

    from bench.gold_crop.datasets import charger
    # un indécidable SORT du jeu, il ne devient pas un cas fantôme
    assert charger(tmp_path).cas == []


def test_la_passe_2_va_dans_son_propre_fichier(monkeypatch, tmp_path):
    """Sans ça la 2ᵉ passe écraserait la 1ʳᵉ et le plafond du banc
    disparaîtrait en silence."""
    _manifeste(tmp_path)
    lignes = [_ligne(passe=1), _ligne(passe=2, theta_deg=30.0)]
    rep = {"/crop-gold/v1": _payload(lignes)}
    assert _lancer(monkeypatch, tmp_path, rep) == 0
    assert _lancer(monkeypatch, tmp_path, rep, ["--passe", "2"]) == 0
    assert F._sortie(tmp_path, 2).name == "gold.pass2.json"
    p2 = json.loads((tmp_path / "gold.pass2.json").read_text())
    assert p2["passe"] == 2 and p2["annotations"][ASSET_A]["ellipse"]["theta"] == 30.0
    assert json.loads((tmp_path / "gold.json").read_text())["passe"] == 1


def test_l_ecriture_est_atomique(monkeypatch, tmp_path):
    _manifeste(tmp_path)
    _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([_ligne()])})
    assert not list(tmp_path.glob("*.tmp"))


# ─── le filet local : la seule perte vraiment possible ──────────────────────

def test_le_filet_local_n_est_PAS_ecrase_a_l_aveugle(monkeypatch, tmp_path, capsys):
    """Une annotation sur disque et absente du canonique = un envoi qui a
    échoué. Ce fichier en est la seule copie."""
    _manifeste(tmp_path, (ASSET_A, ASSET_B))
    (tmp_path / "gold.json").write_text(json.dumps({"annotations": {
        ASSET_A: {"asset_id": ASSET_A, "ellipse": {"cx": 1, "cy": 1, "a": 1,
                                                   "b": 1, "theta": 0}},
        ASSET_B: {"asset_id": ASSET_B, "ellipse": {"cx": 2, "cy": 2, "a": 2,
                                                   "b": 2, "theta": 0}}}}))
    code = _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([_ligne(ASSET_A)])})
    assert code == 2
    assert ASSET_B in capsys.readouterr().out
    # rien n'a bougé : l'annotation orpheline est toujours là
    garde = json.loads((tmp_path / "gold.json").read_text())["annotations"]
    assert set(garde) == {ASSET_A, ASSET_B}


def test_force_ecrase_quand_meme(monkeypatch, tmp_path):
    _manifeste(tmp_path, (ASSET_A, ASSET_B))
    (tmp_path / "gold.json").write_text(json.dumps({"annotations": {
        ASSET_B: {"asset_id": ASSET_B, "ellipse": {"cx": 2, "cy": 2, "a": 2,
                                                   "b": 2, "theta": 0}}}}))
    code = _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([_ligne(ASSET_A)])},
                   ["--force"])
    assert code == 0
    assert list(json.loads((tmp_path / "gold.json").read_text())["annotations"]) == [ASSET_A]


def test_le_canonique_plus_riche_ecrase_sans_ceremonie(monkeypatch, tmp_path):
    """L'asymétrie est voulue : perdre une copie locale redondante ne coûte
    rien, perdre la seule copie coûte une séance."""
    _manifeste(tmp_path, (ASSET_A, ASSET_B))
    (tmp_path / "gold.json").write_text(json.dumps({"annotations": {
        ASSET_A: {"asset_id": ASSET_A, "ellipse": {"cx": 1, "cy": 1, "a": 1,
                                                   "b": 1, "theta": 0}}}}))
    code = _lancer(monkeypatch, tmp_path,
                   {"/crop-gold/v1": _payload([_ligne(ASSET_A), _ligne(ASSET_B)])})
    assert code == 0
    assert set(json.loads((tmp_path / "gold.json").read_text())["annotations"]) == \
        {ASSET_A, ASSET_B}


def test_une_entree_sans_geste_ne_declenche_pas_la_protection(monkeypatch, tmp_path):
    """Confirmer une strate crée une entrée sans ellipse. `serve.py` ne
    l'envoie pas au canonique — elle ne doit donc pas passer pour perdue."""
    _manifeste(tmp_path, (ASSET_A, ASSET_B))
    (tmp_path / "gold.json").write_text(json.dumps({"annotations": {
        ASSET_B: {"asset_id": ASSET_B, "strate_confirmee": "S2_capsule"}}}))
    assert _lancer(monkeypatch, tmp_path,
                   {"/crop-gold/v1": _payload([_ligne(ASSET_A)])}) == 0


# ─── le gel : l'empreinte, recalculée et comparée ───────────────────────────

def _sha_serveur(lignes):
    """Ce que `store.crop_gold.instantane()` + le routeur calculent."""
    import hashlib

    projete = [{k: l.get(k) for k in F.COLONNES_INSTANTANE} for l in lignes]
    contenu = json.dumps({"gold_version": "v1", "annotations": projete},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(contenu.encode()).hexdigest()


def test_l_empreinte_client_reproduit_celle_du_serveur(monkeypatch, tmp_path):
    """Si elle ne la reproduisait pas, la vérification du gel serait un
    théâtre : elle échouerait toujours, ou ne serait jamais faite."""
    lignes = [_ligne(ASSET_B, passe=2), _ligne(ASSET_A)]
    assert F.empreinte_instantane("v1", lignes) == _sha_serveur(lignes)


def test_un_or_gele_conforme_passe_et_le_dit(monkeypatch, tmp_path, capsys):
    _manifeste(tmp_path)
    lignes = [_ligne()]
    rep = _payload(lignes, frozen_at="2026-08-30 10:00:00",
                   snapshot_sha256=_sha_serveur(lignes))
    assert _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": rep}) == 0
    sortie = capsys.readouterr().out
    assert "gelé le 2026-08-30" in sortie and "empreinte vérifiée" in sortie
    assert "NON gelée" not in sortie


def test_un_or_gele_dont_l_empreinte_a_bouge_ARRETE_tout(monkeypatch, tmp_path,
                                                         capsys):
    """RE-5 : un or qui a bougé après son gel n'est plus une référence. On
    n'écrit rien — un fichier écrit ferait croire que le banc peut tourner."""
    _manifeste(tmp_path)
    rep = _payload([_ligne()], frozen_at="2026-08-30 10:00:00",
                   snapshot_sha256="0" * 64)
    assert _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": rep}) == 2
    assert "empreinte divergente" in capsys.readouterr().out
    assert not (tmp_path / "gold.json").exists()


def test_une_version_NON_gelee_est_annoncee_comme_copie_de_travail(monkeypatch,
                                                                   tmp_path, capsys):
    _manifeste(tmp_path)
    assert _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([_ligne()])}) == 0
    assert "NON gelée" in capsys.readouterr().out


# ─── ce qui casse, et ce que le message doit dire ───────────────────────────

def test_sans_env_le_message_nomme_le_devShell(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    monkeypatch.delenv("EURIO_API_TOKEN", raising=False)
    assert F.main(["--out", str(tmp_path)]) == 1
    sortie = capsys.readouterr().out
    assert "EURIO_API_URL" in sortie and "devShell" in sortie


def test_un_403_HTML_est_nomme_Cloudflare_pas_auth(monkeypatch, tmp_path, capsys):
    """Le piège n°1 des clients Python du canonique : Cloudflare refuse l'UA
    par défaut d'urllib avec un 403 « error code: 1010 », une page HTML. Un
    message « token invalide » enverrait chercher au mauvais endroit."""
    _manifeste(tmp_path)
    erreur = _Erreur(403, "<html><body>error code: 1010</body></html>")
    assert _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": erreur}) == 1
    sortie = capsys.readouterr().out
    assert "Cloudflare" in sortie and "User-Agent" in sortie


def test_le_client_pose_un_User_Agent(monkeypatch, tmp_path):
    """Sans lui, Cloudflare répond 403 en production — et seulement là."""
    vu = []
    _brancher(monkeypatch, F, {"/crop-gold/v1": _payload([])}, vu)
    _manifeste(tmp_path)
    F.main(["--out", str(tmp_path), "--api-url", "https://faux.test",
            "--api-token", "tok"])
    assert vu[0]["ua"] and "urllib" not in vu[0]["ua"].lower()
    assert vu[0]["auth"] == "Bearer tok"


def test_un_401_parle_du_scope(monkeypatch, tmp_path, capsys):
    _manifeste(tmp_path)
    assert _lancer(monkeypatch, tmp_path,
                   {"/crop-gold/v1": _Erreur(401, '{"detail":"nope"}')}) == 1
    assert "lab:read" in capsys.readouterr().out


def test_sans_manifeste_le_hint_dit_que_fetch_complete_sample(monkeypatch, tmp_path,
                                                              capsys):
    """`charger()` a besoin du manifeste ET des raws. Rapatrier les annotations
    seules donne un dossier qui a l'air prêt et ne l'est pas."""
    assert _lancer(monkeypatch, tmp_path, {"/crop-gold/v1": _payload([_ligne()])}) == 0
    sortie = capsys.readouterr().out
    assert "manifest.json" in sortie and "bench.gold_crop.sample" in sortie


# ─── le gel, côté CLI ───────────────────────────────────────────────────────

def _geler(monkeypatch, reponses, argv=(), vu=None):
    _brancher(monkeypatch, G, reponses, vu)
    return G.main(["--version", "v1", "--api-url", "https://faux.test",
                   "--api-token", "tok", *argv])


def _instantane(lignes):
    projete = [{k: l.get(k) for k in F.COLONNES_INSTANTANE} for l in lignes]
    return json.dumps({"gold_version": "v1", "annotations": projete},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_geler_refuse_en_dessous_des_60_et_dit_combien_il_manque(monkeypatch,
                                                                 capsys):
    """La séance compte 60 images. Geler à 12 figerait un or sur lequel RE-4 ne
    conclut rien — et le gel est irréversible."""
    lignes = [_ligne(f"{i:032x}") for i in range(12)]
    vu = []
    assert _geler(monkeypatch, {"/crop-gold/v1": _payload(lignes)}, vu=vu) == 2
    sortie = capsys.readouterr().out
    assert "12" in sortie and "48" in sortie
    # et surtout : RIEN n'a été posté
    assert [v["methode"] for v in vu] == ["GET"]


def test_geler_force_passe_outre(monkeypatch, capsys):
    lignes = [_ligne()]
    contenu = _instantane(lignes)
    sha = _sha_serveur(lignes)
    monkeypatch.setattr(G, "publier", lambda c, v: (G.cle_instantane(v), None))
    vu = []
    code = _geler(monkeypatch, {
        "/crop-gold/v1": _payload(lignes),
        "/crop-gold/v1/geler": {"gold_version": "v1", "deja": False,
                                "snapshot_sha256": sha, "octets": len(contenu)},
        "/crop-gold/v1/instantane": {"gold_version": "v1", "sha256": sha,
                                     "contenu": contenu, "octets": len(contenu)},
    }, ["--force"], vu=vu)
    assert code == 0
    sortie = capsys.readouterr().out
    assert sha in sortie and "crop-gold/v1/instantane.json" in sortie
    poste = [v for v in vu if v["methode"] == "POST"]
    assert poste and poste[0]["chemin"] == "/crop-gold/v1/geler"
    assert poste[0]["corps"]["snapshot_key"] == "crop-gold/v1/instantane.json"


def test_geler_rend_le_409_du_serveur_VERBATIM(monkeypatch, capsys):
    """Le serveur nomme les deux sha ; c'est la seule information qui dit quoi
    faire. La reformuler la perdrait."""
    raison = ("l'or v1 est déjà gelé sur abc123456789… ; un contenu différent "
              "(def987654321…) exige une nouvelle version")
    code = _geler(monkeypatch, {
        "/crop-gold/v1": _payload([_ligne()]),
        "/crop-gold/v1/geler": _Erreur(409, json.dumps({"detail": raison})),
    }, ["--force"])
    assert code == 2
    sortie = capsys.readouterr().out
    assert raison in sortie
    assert "idempotent" in sortie          # re-geler l'identique est permis


def test_geler_un_contenu_identique_est_idempotent(monkeypatch, capsys):
    lignes = [_ligne()]
    contenu, sha = _instantane(lignes), _sha_serveur([_ligne()])
    monkeypatch.setattr(G, "publier", lambda c, v: (G.cle_instantane(v), None))
    code = _geler(monkeypatch, {
        "/crop-gold/v1": _payload(lignes, frozen_at="2026-08-30", snapshot_sha256=sha),
        "/crop-gold/v1/geler": {"gold_version": "v1", "deja": True,
                                "frozen_at": "2026-08-30", "snapshot_sha256": sha,
                                "octets": len(contenu)},
        "/crop-gold/v1/instantane": {"sha256": sha, "contenu": contenu},
    }, ["--force"])
    assert code == 0
    assert "déjà gelé" in capsys.readouterr().out


def test_geler_refuse_de_publier_un_instantane_qui_ne_porte_pas_l_empreinte(
        monkeypatch, capsys):
    """Publier autre chose que ce qui a été gelé donnerait un artefact qui ment
    sur son propre sha."""
    publie = []
    monkeypatch.setattr(G, "publier", lambda c, v: publie.append(c) or ("k", None))
    code = _geler(monkeypatch, {
        "/crop-gold/v1": _payload([_ligne()]),
        "/crop-gold/v1/geler": {"deja": False, "snapshot_sha256": "0" * 64},
        "/crop-gold/v1/instantane": {"contenu": "autre chose"},
    }, ["--force"])
    assert code == 2 and publie == []


def test_geler_sans_env_le_dit(monkeypatch, capsys):
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    monkeypatch.delenv("EURIO_API_TOKEN", raising=False)
    assert G.main(["--version", "v1"]) == 1
    assert "devShell" in capsys.readouterr().out


def test_compter_passe1_ignore_la_passe_2_et_les_entrees_vides(monkeypatch):
    lignes = [_ligne(ASSET_A), _ligne(ASSET_A, passe=2),
              _ligne(ASSET_B, cx=None, indecidable=0)]
    assert G.compter_passe1(lignes) == 1
