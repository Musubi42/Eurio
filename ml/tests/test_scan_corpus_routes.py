"""Routes du corpus d'évaluation — voir les photos qui jugent, et agir dessus.

Ce que ces tests garantissent, et pourquoi chacun existe :

- la **maille est dite** : pour une pièce d'un groupe de dessin, la réponse
  annonce ``scope='design_group'`` et marque chaque capture ``is_exact_match``.
  Sans ça l'écran montrerait les photos d'une autre pièce en les appelant
  « les photos de celle-ci » ;
- le **garde-fou référentiel** du remap : un ``eurio_id`` absent est refusé
  (400) et rien n'est écrit — même garde qu'à l'import ;
- référentiel injoignable → **503**, pas une écriture à l'aveugle ;
- la **traversée de chemin** est refusée (400) ;
- **chaque geste est journalisé** (ancien → nouveau, qui, quand). Un remap sans
  trace est irrattrapable ;
- ``eval_decision`` est un **avis** distinct du **fait** ``class_level_only``,
  et un ré-import ne l'efface pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from serving import scan_corpus_routes as routes  # noqa: E402
from store.scan_corpus import ScanCapture, ScanCorpusStore  # noqa: E402


class FakeDescriptor:
    def __init__(self, class_id, class_kind, eurio_ids):
        self.class_id = class_id
        self.class_kind = class_kind
        self.eurio_ids = tuple(eurio_ids)


class FakeResolver:
    """Deux pièces d'un même groupe de dessin, une pièce isolée."""

    GROUP = ("fr-1999-2eur-standard-1st-map", "fr-2007-2eur-standard-2nd-map")

    def for_eurio(self, eurio_id):
        if eurio_id in self.GROUP:
            return FakeDescriptor("fr-2euro-standard-t1", "design_group_id", self.GROUP)
        if eurio_id == "fr-2018-2eur-simone-veil":
            return FakeDescriptor(eurio_id, "eurio_id", (eurio_id,))
        return None


def _write_image(path: Path, color=(120, 30, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color).save(path, "JPEG")


@pytest.fixture
def store(tmp_path: Path) -> ScanCorpusStore:
    st = ScanCorpusStore(db_path=tmp_path / "corpus.db")
    for cid, eurio_id, flag in (
        ("aaaa0000aaaa0000", "fr-1999-2eur-standard-1st-map", False),
        ("bbbb1111bbbb1111", "fr-2007-2eur-standard-2nd-map", True),
        ("cccc2222cccc2222", "fr-2018-2eur-simone-veil", False),
    ):
        _write_image(st.frames_dir / f"{cid}.raw.jpg")
        _write_image(st.frames_dir / f"{cid}.crop.jpg")
        st.upsert_capture(
            ScanCapture(
                capture_id=cid,
                eurio_id=eurio_id,
                condition="bright_plain",
                captured_at="2026-04-29T16:47:50.336",
                raw_path=f"frames/{cid}.raw.jpg",
                crop_path=f"frames/{cid}.crop.jpg",
                bundle_source="device_pull_20260429",
                class_level_only=flag,
            )
        )
    return st


@pytest.fixture
def client(store, monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(routes, "_store", store)
    monkeypatch.setattr(routes._referential, "_resolver", FakeResolver())
    monkeypatch.setattr(
        routes, "_thumbs", routes.ThumbnailCache(tmp_path / "thumbs")
    )
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


# ─── La maille ──────────────────────────────────────────────────────────────


def test_maille_groupe_de_dessin_est_dite(client):
    """Une pièce du groupe rend AUSSI les photos de sa sœur — et l'annonce."""
    r = client.get("/scan-corpus/captures/fr-1999-2eur-standard-1st-map")
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "design_group"
    assert body["class_kind"] == "design_group_id"
    assert body["class_id"] == "fr-2euro-standard-t1"
    assert body["n_captures"] == 2
    assert body["n_exact_match"] == 1
    exact = {c["eurio_id"]: c["is_exact_match"] for c in body["captures"]}
    assert exact == {
        "fr-1999-2eur-standard-1st-map": True,
        "fr-2007-2eur-standard-2nd-map": False,
    }


def test_maille_piece_seule(client):
    body = client.get("/scan-corpus/captures/fr-2018-2eur-simone-veil").json()
    assert body["scope"] == "coin"
    assert body["n_captures"] == 1 and body["n_exact_match"] == 1


def test_eurio_id_inconnu_404(client):
    assert client.get("/scan-corpus/captures/inexistant").status_code == 404


def test_class_level_only_est_expose(client):
    body = client.get("/scan-corpus/captures/fr-1999-2eur-standard-1st-map").json()
    assert body["n_class_level_only"] == 1
    flagged = [c for c in body["captures"] if c["class_level_only"]]
    assert [c["capture_id"] for c in flagged] == ["bbbb1111bbbb1111"]


# ─── Vignettes et traversée ─────────────────────────────────────────────────


def test_thumbnail_sert_le_crop_et_le_raw(client):
    for url in (
        "/scan-corpus/thumbnail/cccc2222cccc2222",
        "/scan-corpus/thumbnail/cccc2222cccc2222?kind=raw",
    ):
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["content-type"] == "image/jpeg"


def test_thumbnail_refuse_la_traversee(client):
    """⚠️ Deux couches, et une seule est à nous.

    Un ``../..`` MULTI-segment n'atteint jamais le handler : Starlette
    n'apparie ``{capture_id}`` que sur UN segment → 404 avant tout garde. Et le
    client HTTP (httpx comme curl sans ``--path-as-is``) normalise ``..``
    côté client. Le garde s'éprouve donc là où il vit — sur la fonction — et le
    trajet HTTP est vérifié pour ce qui l'atteint vraiment.

    Mesuré sur un vrai uvicorn (2026-08-25) :
    ``curl --path-as-is .../thumbnail/..`` → **400** ;
    ``.../thumbnail/../../etc/passwd`` → **404** (pas de route).
    """
    from fastapi import HTTPException

    for bad in ("..", "../..", "a/b", "a\\b", "/etc/passwd", "", "x" * 129):
        with pytest.raises(HTTPException) as exc:
            routes._sanitize_capture_id(bad)
        assert exc.value.status_code == 400, bad

    for bad in ("%2e%2e", "a%5Cb", "..%2Fetc"):
        assert client.get(f"/scan-corpus/thumbnail/{bad}").status_code in (400, 404)


def test_safe_child_refuse_un_chemin_stocke_qui_sort_de_la_racine(store):
    """Deuxième garde, indépendant du premier : le chemin vient de la BASE, pas
    de l'URL. Un ``raw_path`` sortant de ``frames_root`` ne doit rien servir."""
    from fastapi import HTTPException

    from serving.thumbnails import safe_child

    with pytest.raises(HTTPException) as exc:
        safe_child(store.frames_root, "../../etc/passwd")
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        safe_child(store.frames_root, "/etc/passwd")


def test_thumbnail_capture_inconnue_404(client):
    assert client.get("/scan-corpus/thumbnail/deadbeef").status_code == 404


# ─── Remap ──────────────────────────────────────────────────────────────────


def test_remap_refuse_un_eurio_id_absent_du_referentiel(client, store):
    r = client.post(
        "/scan-corpus/captures/cccc2222cccc2222/remap",
        json={"eurio_id": "xx-9999-2eur-inexistante"},
    )
    assert r.status_code == 400
    assert "référentiel" in r.json()["detail"]
    # Rien écrit — c'est le point : un refus qui écrit quand même ne garde rien.
    assert store.get_capture("cccc2222cccc2222").eurio_id == "fr-2018-2eur-simone-veil"
    assert store.list_decisions("cccc2222cccc2222") == []


def test_remap_refuse_si_referentiel_injoignable(client, store, monkeypatch):
    monkeypatch.setattr(routes._referential, "resolver", lambda: None)
    r = client.post(
        "/scan-corpus/captures/cccc2222cccc2222/remap",
        json={"eurio_id": "fr-1999-2eur-standard-1st-map"},
    )
    assert r.status_code == 503
    assert store.get_capture("cccc2222cccc2222").eurio_id == "fr-2018-2eur-simone-veil"


def test_remap_ecrit_et_journalise(client, store):
    r = client.post(
        "/scan-corpus/captures/cccc2222cccc2222/remap",
        json={
            "eurio_id": "fr-1999-2eur-standard-1st-map",
            "reason": "la photo montre l'arbre de vie daté 2000",
            "decided_by": "po",
        },
    )
    assert r.status_code == 200
    assert store.get_capture("cccc2222cccc2222").eurio_id == (
        "fr-1999-2eur-standard-1st-map"
    )
    journal = store.list_decisions("cccc2222cccc2222")
    assert len(journal) == 1
    entry = journal[0]
    assert entry["kind"] == "remap"
    assert "fr-2018-2eur-simone-veil" in entry["old_value"]
    assert "fr-1999-2eur-standard-1st-map" in entry["new_value"]
    assert entry["decided_by"] == "po"
    assert entry["decided_at"]


def test_remap_capture_inconnue_404(client):
    r = client.post(
        "/scan-corpus/captures/deadbeef/remap",
        json={"eurio_id": "fr-2018-2eur-simone-veil"},
    )
    assert r.status_code == 404


def test_remap_peut_poser_le_drapeau_class_level_only(client, store):
    client.post(
        "/scan-corpus/captures/cccc2222cccc2222/remap",
        json={"eurio_id": "fr-1999-2eur-standard-1st-map", "class_level_only": True},
    )
    assert store.get_capture("cccc2222cccc2222").class_level_only is True


# ─── Avis humain : garder / écarter ─────────────────────────────────────────


def test_eval_decision_ecarte_et_journalise(client, store):
    r = client.post(
        "/scan-corpus/captures/cccc2222cccc2222/eval-decision",
        json={"decision": "exclude", "reason": "cadrage raté", "decided_by": "po"},
    )
    assert r.status_code == 200
    c = store.get_capture("cccc2222cccc2222")
    assert c.eval_decision == "exclude"
    assert c.eval_decision_reason == "cadrage raté"
    assert c.eval_decision_by == "po" and c.eval_decision_at
    journal = store.list_decisions("cccc2222cccc2222")
    assert [j["kind"] for j in journal] == ["eval_decision"]
    assert journal[0]["old_value"] is None and journal[0]["new_value"] == "exclude"


def test_eval_decision_valeur_invalide_400(client, store):
    r = client.post(
        "/scan-corpus/captures/cccc2222cccc2222/eval-decision",
        json={"decision": "peut-être"},
    )
    assert r.status_code == 400
    assert store.get_capture("cccc2222cccc2222").eval_decision is None


def test_ecartee_reste_visible_mais_filtrable(client):
    client.post(
        "/scan-corpus/captures/cccc2222cccc2222/eval-decision",
        json={"decision": "exclude"},
    )
    visible = client.get("/scan-corpus/captures/fr-2018-2eur-simone-veil").json()
    assert visible["n_captures"] == 1 and visible["n_excluded"] == 1
    filtre = client.get(
        "/scan-corpus/captures/fr-2018-2eur-simone-veil?include_excluded=false"
    ).json()
    assert filtre["n_captures"] == 0


def test_reimport_n_efface_pas_l_avis_humain(client, store):
    """Un ré-import est idempotent sur les métadonnées ; il ne doit PAS
    réinitialiser un avis humain. Sinon rejouer l'import effacerait en silence
    le travail de tri du PO."""
    client.post(
        "/scan-corpus/captures/cccc2222cccc2222/eval-decision",
        json={"decision": "exclude", "reason": "illisible"},
    )
    before = store.get_capture("cccc2222cccc2222")
    store.upsert_capture(
        ScanCapture(
            capture_id=before.capture_id,
            eurio_id=before.eurio_id,
            condition=before.condition,
            captured_at=before.captured_at,
            raw_path=before.raw_path,
            crop_path=before.crop_path,
            bundle_source=before.bundle_source,
        )
    )
    after = store.get_capture("cccc2222cccc2222")
    assert after.eval_decision == "exclude"
    assert after.eval_decision_reason == "illisible"


def test_avis_et_fait_sont_deux_colonnes(client, store):
    """``class_level_only`` est un FAIT sur le label ; ``eval_decision`` un
    AVIS sur la photo. Les confondre ferait écarter d'un geste des photos
    parfaitement exploitables (mais rattachées à la classe faute de pièce)."""
    client.post(
        "/scan-corpus/captures/bbbb1111bbbb1111/eval-decision",
        json={"decision": "keep"},
    )
    c = store.get_capture("bbbb1111bbbb1111")
    assert c.class_level_only is True and c.eval_decision == "keep"
