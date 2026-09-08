"""Les runs du banc servis à la planche — forme, refus, et absence sur le lean.

Trois choses s'y vérifient, et chacune répond à une panne déjà payée ailleurs
dans ce dépôt :

* **le résumé est le MÊME nombre que celui du tableau du harness.** La planche
  et la console doivent dire la même chose du même run ; deux implémentations
  d'une médiane qui divergent d'un dixième font douter du banc entier ;
* **un identifiant n'est pas un chemin.** `..` est composé de caractères
  parfaitement légaux — et suffirait à sortir de `state/gold_crop/` ;
* **ces routes n'existent pas sur le VPS.** Les fichiers qu'elles lisent non
  plus. Une route annoncée dans l'OpenAPI du canonique et absente du disque est
  la panne muette type : elle ressemble à un bug de données.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving import crop_gold_runs_routes as mod


def _cas(**over) -> dict:
    base = {
        "asset_id": "a1", "strate": "S1_facile", "strate_confirmee": "S1_facile",
        "strate_retenue": "S1_facile", "verdict_humain": "accept",
        "gold": {"cx": 450.0, "cy": 450.0, "a": 400.0, "b": 390.0, "theta": 0.3},
        "pred": {"cx": 450.0, "cy": 450.0, "r": 395.0},
        "candidats": [{"cx": 450.0, "cy": 450.0, "r": 395.0, "source": "b", "debug": {}}],
        "C1_marge_min_frac": -0.003, "C1_cadre_marge_min_frac": 0.004,
        "C1_disque_marge_min_frac": -0.003, "C1_cadre_tronque": False,
        "boundary_iou": 0.95, "mask_iou": 0.99, "hausdorff_frac": 0.0032,
        "C1_region": "retenu", "arc_coverage": 1.0, "n_ring": 5575,
        "C1_ok": False, "C2_ok": True, "marge_promise_ok": False, "ampute": True,
    }
    base.update(over)
    return base


def _run(bras: str, *, borne: bool = False, cases: list[dict] | None = None) -> dict:
    return {
        "arm": bras, "borne": borne, "gold_version": "v1", "gold_sha256": "c8dd",
        "requete_sha256": "59d4", "judge_version": 1, "m": 0.0, "d_frac": 0.08,
        "arc_min": 11 / 12, "c2_compte": False, "region_c1": "retenu",
        "execute_le": "2026-09-08T08:30:24+00:00", "n_indecidables": 0,
        "n_non_annotes": 58,
        "cases": [_cas()] if cases is None else cases,
    }


@pytest.fixture()
def banc(tmp_path, monkeypatch):
    """Un `state/gold_crop/` de poche : deux bras, un manifeste, un raw."""
    racine = tmp_path / "v1"
    (racine / "raws").mkdir(parents=True)
    (racine / "run_baseline_prod.json").write_text(json.dumps(_run("baseline_prod")))
    (racine / "run_gold_replay.json").write_text(json.dumps(_run(
        "gold_replay", borne=True,
        cases=[_cas(boundary_iou=1.0, ampute=False, C1_ok=True, mask_iou=1.0,
                    hausdorff_frac=0.0, marge_promise_ok=True)])))
    (racine / "manifest.json").write_text(json.dumps(
        {"version": "v1", "images": [{"asset_id": "a1", "width": 900, "height": 1200}]}))
    (racine / "raws" / "a1.jpg").write_bytes(b"\xff\xd8\xff\xdb-pas-un-vrai-jpeg")
    monkeypatch.setattr(mod, "_DIR", tmp_path)
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app), tmp_path


def test_la_forme_du_contrat(banc):
    client, _ = banc
    d = client.get("/crop-gold/v1/runs").json()
    assert d["gold_version"] == "v1" and d["n"] == 2
    bras = {r["bras"]: r for r in d["runs"]}
    assert set(bras) == {"baseline_prod", "gold_replay"}
    r = bras["baseline_prod"]
    assert r["borne"] is False and bras["gold_replay"]["borne"] is True
    assert r["juge_version"] == 1
    assert r["execute_le"] == "2026-09-08T08:30:24+00:00"
    assert r["params"] == {"m": 0.0, "d_frac": 0.08, "arc_min": 11 / 12,
                           "region": "retenu", "c2_compte": False}
    assert r["resume"]["n"] == 1 and r["resume"]["amputation_pct"] == 100.0
    assert bras["gold_replay"]["resume"]["amputation_pct"] == 0.0
    cas = r["cas"][0]
    # Les dimensions viennent du MANIFESTE : sans elles la planche caderait son
    # `viewBox` sur un carré supposé, et dessinerait faux sans en avoir l'air.
    assert (cas["largeur"], cas["hauteur"]) == (900, 1200)
    assert cas["raw_url"] == "/crop-gold/v1/raws/a1"
    assert cas["verdict_humain"] == "accept" and cas["boundary_iou"] == 0.95
    # RE-4 vient du harness lui-même, et une BORNE n'en a pas : rejouer l'or
    # contre lui-même ne mesure pas le pouvoir prédictif du juge.
    assert bras["gold_replay"]["re4"] is None
    assert r["re4"]["verdict"] == "impossible"
    assert "vide" in r["re4"]["raison"]


def test_re4_separe_quand_les_deux_groupes_existent(banc, tmp_path):
    """Le bloc RE-4 est celui du harness, verbatim — pas une seconde version.

    Deux groupes NON vides : le verdict cesse d'être « impossible » et porte
    alors sa table 2×2 et son p de Fisher, les seuls chiffres qui font arrêter
    le banc.
    """
    client, racine = banc
    cases = ([_cas(asset_id=f"r{i}", verdict_humain="reject", ampute=True) for i in range(6)]
             + [_cas(asset_id=f"a{i}", verdict_humain="accept", ampute=False,
                     C1_ok=True, boundary_iou=0.99) for i in range(6)])
    (racine / "v1" / "run_baseline_prod.json").write_text(
        json.dumps(_run("baseline_prod", cases=cases)))
    d = client.get("/crop-gold/v1/runs").json()
    re4 = next(r for r in d["runs"] if r["bras"] == "baseline_prod")["re4"]
    assert re4["verdict"] == "sépare"
    assert re4["n_accept"] == 6 and re4["n_reject"] == 6
    assert re4["table_2x2"]["rejete"]["ampute"] == 6


def test_le_resume_dit_le_meme_nombre_que_le_harness():
    """Miroir chiffre à chiffre de `harness.resume`, sur des valeurs non triviales.

    `numpy` sert ici d'arbitre — c'est lui que le harness utilise. Une médiane
    interpolée autrement ferait diverger la planche du tableau imprimé.
    """
    import numpy as np

    bious = [0.12, 0.44, 0.67, 0.81, 0.93, 0.95, 0.99]
    cas = [_cas(asset_id=f"a{i}", boundary_iou=b, mask_iou=b * 0.9,
                hausdorff_frac=1 - b, ampute=i % 3 == 0, C1_ok=i % 3 != 0)
           for i, b in enumerate(bious)]
    r = mod.resume(cas)
    assert r["n"] == 7
    assert r["biou_med"] == pytest.approx(float(np.median(bious)))
    assert r["biou_p10"] == pytest.approx(float(np.percentile(bious, 10)))
    assert r["iou_masque_med"] == pytest.approx(
        float(np.median([b * 0.9 for b in bious])))
    assert r["hausdorff_p90"] == pytest.approx(
        float(np.percentile([1 - b for b in bious], 90)))
    assert r["amputation_pct"] == pytest.approx(100.0 * 3 / 7)


def test_un_bras_sans_cas_mesure_rend_n_zero(banc):
    """`human_2nd_pass` sans seconde passe : une borne NON MESURÉE.

    Elle ne doit surtout pas se lire « 0 % d'amputation » — un plafond fantôme
    au-dessus d'un banc réel rendrait tout le tableau flatteur.
    """
    client, racine = banc
    (racine / "v1" / "run_human_2nd_pass.json").write_text(json.dumps(_run(
        "human_2nd_pass", borne=True,
        cases=[{"asset_id": "a1", "strate": "S1_facile",
                "verdict_humain": "accept", "absent": True}])))
    d = client.get("/crop-gold/v1/runs").json()
    borne = next(r for r in d["runs"] if r["bras"] == "human_2nd_pass")
    assert borne["resume"] == {"n": 0}
    assert borne["cas"][0]["absent"] is True


@pytest.mark.parametrize("jeton", ["..", ".", "...", "../secrets", "a/b", "a" * 65, ""])
def test_une_version_qui_ressemble_a_un_chemin_est_refusee(banc, jeton):
    """Le refus se teste sur `_racine`, PAS à travers le client HTTP.

    `TestClient` normalise `..` hors du chemin avant l'envoi : la requête
    n'atteint jamais le handler, et le test resterait vert avec un garde
    supprimé (vérifié — la mutation survivait). Ce qui protège, c'est la
    fonction ; c'est donc elle qu'on interroge.
    """
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        mod._racine(jeton)
    assert exc.value.status_code == 422


def test_une_version_valide_reste_sous_state_gold_crop(banc):
    client, racine = banc
    assert mod._racine("v1") == racine / "v1"
    assert client.get("/crop-gold/v1/runs").status_code == 200


def test_un_asset_id_qui_ressemble_a_un_chemin_est_refuse(banc):
    """Même raison que ci-dessus : on appelle le handler, pas l'URL.

    `raws/../../secrets.env` n'arrive jamais tel quel au serveur — mais
    `get_raw` est aussi la fonction que n'importe quel appelant interne peut
    invoquer, et c'est là que le nom doit cesser d'être un chemin.
    """
    from fastapi import HTTPException

    for jeton in ("..", ".", "a/b", ""):
        with pytest.raises(HTTPException) as exc:
            mod.get_raw("v1", jeton)
        assert exc.value.status_code == 422, jeton

    client, _ = banc
    assert client.get("/crop-gold/v1/raws/a1").status_code == 200


def test_sans_run_ce_n_est_pas_une_panne_mais_une_commande(banc):
    client, racine = banc
    (racine / "vide").mkdir()
    r = client.get("/crop-gold/vide/runs")
    assert r.status_code == 404
    # Le message porte le geste, pas seulement le constat.
    assert "bench.gold_crop.harness" in r.json()["detail"]


def test_le_raw_local_est_servi_en_jpeg(banc):
    client, _ = banc
    r = client.get("/crop-gold/v1/raws/a1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get("/crop-gold/v1/raws/inconnu").status_code == 404


def test_le_lean_n_expose_pas_ces_routes():
    """L'app du VPS ne doit PAS annoncer ce qu'elle ne peut pas servir.

    On lit la SOURCE plutôt que l'app : importer `server_serve` ouvre la base
    canonique, applique les migrations et monte l'auth — hors de portée d'un
    test unitaire (même raison que `test_serve_router_order.py`).
    """
    src = (Path(__file__).parent.parent / "serving" / "server_serve.py").read_text(
        encoding="utf-8")
    assert "crop_gold_runs_routes" not in src, (
        "ces routes lisent state/gold_crop/ — un répertoire absent du VPS ; "
        "les monter sur le lean promettrait une capacité inexistante"
    )
    full = (Path(__file__).parent.parent / "serving" / "server.py").read_text(
        encoding="utf-8")
    assert "app.include_router(crop_gold_runs_routes.router)" in full


def test_le_scope_lab_read_mord_des_que_l_auth_est_armee(banc, monkeypatch):
    """Sur `:8042` l'auth est un no-op ; là où elle est armée, `lab:read` décide."""
    client, _ = banc
    monkeypatch.setenv("EURIO_API_AUTH_REQUIRED", "1")
    assert client.get("/crop-gold/v1/runs").status_code == 401
    monkeypatch.delenv("EURIO_API_AUTH_REQUIRED")
    assert client.get("/crop-gold/v1/runs").status_code == 200
