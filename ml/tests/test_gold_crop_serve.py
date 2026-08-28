"""Le serveur d'annotation perd-il du travail ?

Une séance d'annotation ne se refait pas : ce qui est validé doit être sur
disque avant l'image suivante, et un écrasement partiel ne doit jamais laisser
un `gold.json` tronqué. Ces deux propriétés sont les seules qui comptent ici.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bench.gold_crop.annotate.serve import Handler, _sortie, pousser_au_canonique


@pytest.fixture()
def serveur(tmp_path):
    def monter(passe=1, n_double=10, api_url=None, api_token=None):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(
            Handler, racine=tmp_path, passe=passe, n_double=n_double,
            version="vtest", api_url=api_url, api_token=api_token))
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srvs = []
    def usine(**kw):
        s, url = monter(**kw)
        srvs.append(s)
        return url
    yield tmp_path, usine
    for s in srvs:
        s.shutdown()


def _manifeste(racine, n=6):
    images = [{"asset_id": f"{i:032x}", "role": "tirage" if i < n - 1 else "reserve",
               "strate": "S1_facile", "verdict": "accept", "fichier": f"raws/{i}.jpg"}
              for i in range(n)]
    (racine / "manifest.json").write_text(json.dumps(
        {"version": "v1", "requete_sha256": "abc", "images": images}))
    return images


def _get(url, chemin):
    with urllib.request.urlopen(url + chemin) as r:
        return json.loads(r.read())


def _post(url, payload):
    req = urllib.request.Request(url + "/api/save", data=json.dumps(payload).encode(),
                                 method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_la_session_ne_sert_que_le_tirage_pas_la_reserve(serveur):
    racine, usine = serveur
    images = _manifeste(racine)
    s = _get(usine(), "/api/session")
    assert [i["asset_id"] for i in s["images"]] == [i["asset_id"] for i in images
                                                    if i["role"] == "tirage"]


def test_chaque_validation_est_sur_disque_immediatement(serveur):
    racine, usine = serveur
    _manifeste(racine)
    url = usine()
    r = _post(url, {"annotations": {"a": {"ellipse": {"a": 1}}}})
    assert r["ok"] and r["fichier"] == "gold.json"
    ecrit = json.loads((racine / "gold.json").read_text())
    assert ecrit["annotations"] == {"a": {"ellipse": {"a": 1}}}
    assert ecrit["passe"] == 1 and ecrit["n"] == 1


def test_l_ecriture_ne_laisse_jamais_de_fichier_tronque(serveur):
    """L'écriture passe par un `.tmp` puis un `replace` — atomique sur POSIX."""
    racine, usine = serveur
    _manifeste(racine)
    url = usine()
    for n in (1, 40, 3):
        _post(url, {"annotations": {str(i): {"ellipse": {}} for i in range(n)}})
        assert json.loads((racine / "gold.json").read_text())["n"] == n
    assert not list(racine.glob("*.tmp"))


def test_un_corps_illisible_ne_detruit_pas_la_passe_en_cours(serveur):
    racine, usine = serveur
    _manifeste(racine)
    url = usine()
    _post(url, {"annotations": {"a": {"ellipse": {}}}})
    req = urllib.request.Request(url + "/api/save", data=b"{pas du json",
                                 method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400
    assert json.loads((racine / "gold.json").read_text())["n"] == 1


def test_la_seconde_passe_relit_un_sous_ensemble_deterministe(serveur):
    """La double annotation fixe le PLAFOND du banc : aucune méthode ne peut
    être créditée au-dessus du bruit de la main. Le sous-ensemble doit donc
    être stable d'une session à l'autre, pas retiré à chaque ouverture."""
    racine, usine = serveur
    images = _manifeste(racine, n=6)
    tirage = [i["asset_id"] for i in images if i["role"] == "tirage"]
    (racine / "gold.json").write_text(json.dumps(
        {"annotations": {a: {"ellipse": {}} for a in tirage}}))
    a = [i["asset_id"] for i in _get(usine(passe=2, n_double=3), "/api/session")["images"]]
    b = [i["asset_id"] for i in _get(usine(passe=2, n_double=3), "/api/session")["images"]]
    assert len(a) == 3 and a == b
    assert set(a) <= set(tirage)


def test_la_seconde_passe_ecrit_a_part(serveur):
    racine, usine = serveur
    _manifeste(racine)
    (racine / "gold.json").write_text(json.dumps({"annotations": {"00000000000000000000000000000000": {}}}))
    url = usine(passe=2, n_double=1)
    assert _post(url, {"annotations": {"x": {}}})["fichier"] == "gold.pass2.json"
    # la passe 1 est intacte : on compare deux passes, on ne les écrase pas
    assert list(json.loads((racine / "gold.json").read_text())["annotations"]) == \
        ["00000000000000000000000000000000"]


def test_sans_passe_1_la_passe_2_refuse_au_lieu_d_inventer(serveur):
    racine, usine = serveur
    _manifeste(racine)
    assert "erreur" in _get(usine(passe=2), "/api/session")


def test_sortie_par_passe():
    from pathlib import Path
    assert _sortie(Path("/x"), 1).name == "gold.json"
    assert _sortie(Path("/x"), 2).name == "gold.pass2.json"


# ─── le canonique, et le silence qu'on refuse ───────────────────────────────

def test_sans_canonique_le_serveur_le_DIT_a_chaque_ecriture(serveur):
    """Un dispositif qui a l'air de marcher sans sauvegarder est exactement le
    défaut qu'on corrige (`denom-gold` et son `.jsonl` local). Le fichier reste
    écrit — c'est le filet — mais la réponse porte l'échec, et l'outil l'affiche.
    """
    racine, usine = serveur
    _manifeste(racine)
    r = _post(usine(), {"annotations": {"a": {"ellipse": {"a": 1}}}})
    assert r["ok"] is True                      # le filet local a fonctionné
    assert r["canonique"]["ok"] is False
    assert "EURIO_API_URL" in r["canonique"]["detail"]
    assert json.loads((racine / "gold.json").read_text())["n"] == 1


def _faux_canonique(tmp_path, code=200, corps=None):
    """Un canonique de paille : on veut voir ce qui PART, pas ce qui revient."""
    recu = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_PUT(self):                        # noqa: N802
            n = int(self.headers.get("Content-Length", 0))
            recu["chemin"] = self.path
            recu["auth"] = self.headers.get("Authorization")
            recu["corps"] = json.loads(self.rfile.read(n))
            body = json.dumps(corps or {"comptes": {"ecrit": 1}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", recu


def test_l_annotation_part_bien_au_canonique(serveur, tmp_path):
    racine, usine = serveur
    _manifeste(racine)
    srv, base, recu = _faux_canonique(tmp_path)
    try:
        url = usine(api_url=base, api_token="secret")
        r = _post(url, {"annotations": {"a": {
            "asset_id": "a", "ellipse": {"cx": 1, "cy": 2, "a": 3, "b": 3, "theta": 0},
            "strate_confirmee": "S1_facile", "secondes": 12.5}}})
        assert r["canonique"]["ok"] is True
        assert recu["chemin"] == "/crop-gold/vtest/annotations"
        assert recu["auth"] == "Bearer secret"
        (envoye,) = recu["corps"]["annotations"]
        assert envoye["asset_id"] == "a" and envoye["passe"] == 1
        assert envoye["strate_confirmee"] == "S1_facile"
        assert recu["corps"]["requete_sha256"] == "abc"
    finally:
        srv.shutdown()


def test_un_or_gele_remonte_le_409_au_lieu_de_planter(serveur, tmp_path):
    """Un or gelé n'est pas une panne, c'est une réponse. L'outil doit pouvoir
    la lire et la dire — pas voir une exception côté serveur."""
    racine, usine = serveur
    _manifeste(racine)
    srv, base, _ = _faux_canonique(tmp_path, code=409, corps={"detail": "gelé"})
    try:
        r = _post(usine(api_url=base, api_token="s"),
                  {"annotations": {"a": {"asset_id": "a", "ellipse": {"a": 1}}}})
        assert r["ok"] is True                   # la séance continue
        assert r["canonique"]["ok"] is False
        assert r["canonique"]["code"] == 409
        assert "gel" in r["canonique"]["detail"]
        assert json.loads((racine / "gold.json").read_text())["n"] == 1
    finally:
        srv.shutdown()


def test_un_canonique_injoignable_ne_retient_pas_la_seance(serveur):
    """Le réseau tousse : l'annotation est déjà sur disque, et la route est
    idempotente — le renvoi suivant rattrapera."""
    racine, usine = serveur
    _manifeste(racine)
    r = _post(usine(api_url="http://127.0.0.1:1", api_token="s"),
              {"annotations": {"a": {"asset_id": "a", "ellipse": {"a": 1}}}})
    assert r["ok"] is True and r["canonique"]["ok"] is False
    assert json.loads((racine / "gold.json").read_text())["n"] == 1


def test_les_cas_sans_geste_ne_partent_pas(serveur, tmp_path):
    """Une entrée ouverte puis abandonnée sans ellipse ni « indécidable » n'est
    pas une annotation : l'envoyer ferait entrer des lignes vides dans l'or."""
    racine, usine = serveur
    _manifeste(racine)
    srv, base, recu = _faux_canonique(tmp_path)
    try:
        _post(usine(api_url=base, api_token="s"), {"annotations": {
            "vide": {"asset_id": "vide"},
            "faite": {"asset_id": "faite", "ellipse": {"cx": 1}},
            "indec": {"asset_id": "indec", "indecidable": True}}})
        assert {a["asset_id"] for a in recu["corps"]["annotations"]} == {"faite", "indec"}
    finally:
        srv.shutdown()


def test_la_passe_2_part_avec_son_numero(serveur, tmp_path):
    """Sans ça, la 2ᵉ annotation ÉCRASERAIT la 1ʳᵉ dans le canonique et le
    plafond du banc disparaîtrait en silence."""
    racine, usine = serveur
    images = _manifeste(racine, n=4)
    tirage = [i["asset_id"] for i in images if i["role"] == "tirage"]
    (racine / "gold.json").write_text(json.dumps(
        {"annotations": {a: {"ellipse": {}} for a in tirage}}))
    srv, base, recu = _faux_canonique(tmp_path)
    try:
        _post(usine(passe=2, api_url=base, api_token="s"),
              {"annotations": {"a": {"asset_id": "a", "ellipse": {"cx": 1}}}})
        assert recu["corps"]["annotations"][0]["passe"] == 2
    finally:
        srv.shutdown()
