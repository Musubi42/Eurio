"""O6 — l'amorce du FPS au médoïde.

Le farthest-point sampling, amorcé par un seed (le canonique Numista), retient
D'ABORD le crop le plus lointain de ce seed : le plus atypique de sa classe,
un faux attracteur en banque. Mesuré le 2026-08-20 à nombre d'ancres identique
(795 lignes, un exemplaire par classe, ``scripts.bench_refs_curve
--model dinov2_vitl14 --refs 0 1 2 3 --rank-order last``) : le rang le MOINS
diversifiant rend 77,8 % contre 73,8 % au rang 1. Spec :
``docs/work-in-progress/pipeline-propre/outils/O6-amorce-fps-medoide.md``.

Ces tests protègent trois choses :

1. **La pathologie est reproduite**, pas supposée : en FPS nu
   (``medoid_first=False``) le premier choix EST l'outlier.
2. **L'amorce au médoïde la corrige** : premier choix = médoïde, outlier
   ensuite ; ``k``, ``floor_sim`` et les pins restent respectés.
3. **Le builder ``2eur_all`` la transmet** et la note du build la dit.

MUTATION (vérifiée le 2026-08-21) : remplacer ``if medoid_first or not
selected:`` par ``if not selected:`` dans ``farthest_point_select`` fait
rougir ``test_medoid_first_amorce_au_medoide_malgre_le_seed`` (premier choix
= 3, l'outlier, au lieu de 0). Si ce test reste vert après une telle
mutation, il teste la signature, pas le comportement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402
from training.foundation import anchors as A  # noqa: E402
from training.foundation.anchors import farthest_point_select  # noqa: E402


def _unit(*xs: float) -> np.ndarray:
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


# Un amas serré (0, 1, 2), un outlier (3) et un canonique à l'écart.
# Le médoïde de l'amas est 0 (les deux autres se penchent de part et d'autre).
CLUSTER_0 = _unit(1.0, 0.0, 0.0)
CLUSTER_1 = _unit(0.98, 0.10, 0.0)
CLUSTER_2 = _unit(0.98, -0.10, 0.0)
OUTLIER = _unit(0.30, 0.0, 0.95)
CANON = _unit(0.80, 0.60, 0.0)
VECS = np.stack([CLUSTER_0, CLUSTER_1, CLUSTER_2, OUTLIER])
POOL = [0, 1, 2, 3]
SEED = CANON[None, :]


def _medoid(vecs: np.ndarray, pool: list[int]) -> int:
    c = vecs[pool].mean(axis=0)
    c /= np.linalg.norm(c)
    return max(pool, key=lambda j: float(vecs[j] @ c))


def test_le_jeu_synthetique_a_la_forme_annoncee():
    """Sans quoi les tests suivants testeraient un autre problème."""
    assert _medoid(VECS, POOL) == 0
    # L'outlier est bien le plus lointain du canonique.
    sims = VECS @ CANON
    assert int(np.argmin(sims)) == 3


# ── 1. La pathologie mesurée ─────────────────────────────────────────────────

def test_fps_nu_amorce_sur_loutlier_le_plus_loin_du_canonique():
    """La pathologie, telle que mesurée : avec un seed et sans amorce au
    médoïde, le premier choix est le point le plus LOINTAIN du canonique —
    l'outlier. C'est le comportement de l'ancienne banque, pas un bug du test."""
    picks = farthest_point_select(
        VECS, candidate_idx=POOL, k=4, seed_vecs=SEED, floor_sim=0.0,
        medoid_first=False,
    )
    assert picks[0][0] == 3


# ── 2. L'amorce au médoïde ───────────────────────────────────────────────────

def test_medoid_first_amorce_au_medoide_malgre_le_seed():
    """LE test de la mutation : avec seed, ``medoid_first=True`` retient
    d'abord le médoïde (0), et l'outlier vient plus tard."""
    picks = farthest_point_select(
        VECS, candidate_idx=POOL, k=4, seed_vecs=SEED, floor_sim=0.0,
        medoid_first=True,
    )
    order = [i for i, _ in picks]
    assert order[0] == 0
    assert 3 in order[1:]
    # Après l'amorce, le FPS reprend : le 2e choix est le plus lointain de
    # {canonique, médoïde}, c'est-à-dire l'outlier.
    assert order[1] == 3
    assert len(order) == 4 and len(set(order)) == 4


def test_sim_au_set_du_medoide_est_sa_similarite_max_au_seed():
    """Le rang 1 reste lisible : sa ``sim_au_set`` est sa similarité au seed,
    pas un 1,0 de convention (réservé au cas sans seed)."""
    picks = farthest_point_select(
        VECS, candidate_idx=POOL, k=1, seed_vecs=SEED, floor_sim=0.0,
        medoid_first=True,
    )
    (idx, sim), = picks
    assert idx == 0
    assert sim == float(CLUSTER_0 @ CANON)
    assert 0.0 < sim < 1.0

    sans_seed = farthest_point_select(
        VECS, candidate_idx=POOL, k=1, seed_vecs=None, floor_sim=0.0,
        medoid_first=True,
    )
    assert sans_seed == [(0, 1.0)]


def test_sans_seed_medoid_first_ne_change_rien():
    """Sans seed, l'amorce au médoïde existait déjà : les deux réglages
    rendent la même sélection."""
    a = farthest_point_select(VECS, candidate_idx=POOL, k=4, floor_sim=0.0,
                              medoid_first=False)
    b = farthest_point_select(VECS, candidate_idx=POOL, k=4, floor_sim=0.0,
                              medoid_first=True)
    assert a == b


def test_k_est_respecte_et_le_medoide_compte_dans_le_budget():
    picks = farthest_point_select(
        VECS, candidate_idx=POOL, k=2, seed_vecs=SEED, floor_sim=0.0,
        medoid_first=True,
    )
    assert [i for i, _ in picks] == [0, 3]
    assert farthest_point_select(
        VECS, candidate_idx=POOL, k=0, seed_vecs=SEED, medoid_first=True,
    ) == []


def test_le_plancher_exclut_avant_lamorce():
    """Le médoïde est celui du pool ÉLIGIBLE : un outlier sous le plancher
    n'entre ni dans le choix ni dans la suite."""
    # Centroïde ≈ (0.87, 0, 0.24) ; l'outlier y est à ~0.49, l'amas à ~0.87+.
    picks = farthest_point_select(
        VECS, candidate_idx=POOL, k=4, seed_vecs=SEED, floor_sim=0.6,
        medoid_first=True,
    )
    order = [i for i, _ in picks]
    assert order[0] == 0
    assert 3 not in order
    assert len(order) == 3


def test_un_pin_deja_dans_le_seed_nest_pas_rechoisi():
    """Le builder retire les pins du pool et les met dans le seed ; le médoïde
    se calcule alors sur ce qui reste — et un pin n'est jamais rechoisi."""
    pinned = 0
    pool = [j for j in POOL if j != pinned]
    seed = np.stack([CANON, VECS[pinned]])
    picks = farthest_point_select(
        VECS, candidate_idx=pool, k=4, seed_vecs=seed, floor_sim=0.0,
        medoid_first=True,
    )
    order = [i for i, _ in picks]
    assert pinned not in order
    assert order[0] == _medoid(VECS, pool)
    assert set(order) == set(pool)


def test_le_defaut_reste_le_fps_nu():
    """La fonction ne change pas de comportement tant qu'on ne le demande
    pas ; c'est le BUILDER qui pose le défaut O6."""
    sans = farthest_point_select(VECS, candidate_idx=POOL, k=4, seed_vecs=SEED,
                                 floor_sim=0.0)
    nu = farthest_point_select(VECS, candidate_idx=POOL, k=4, seed_vecs=SEED,
                               floor_sim=0.0, medoid_first=False)
    assert sans == nu


# ── 3. Le builder 2eur_all transmet l'amorce et la trace ─────────────────────
# Même approche que tests/test_plancher_exemplaires.py : encodeur remplacé par
# des vecteurs déterministes, aucun torch, base temporaire.

_VEC = {
    "obverse.jpg": [1.0, 0.0, 0.0],
    "c1": [0.90, 0.44, 0.0],
    "c2": [0.60, 0.80, 0.0],
}


def _fake_encode(paths, **_kw):
    kept, rows = [], []
    for p in paths:
        s = str(p)
        vec = next((v for k, v in _VEC.items() if k in s), [1.0, 0.0, 0.0])
        arr = np.array(vec, dtype=np.float32)
        arr /= np.linalg.norm(arr)
        kept.append(Path(p))
        rows.append(arr)
    return kept, np.stack(rows)


def _patch_encoder(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(A, "load_encoder", lambda **kw: (None, None))
    monkeypatch.setattr(A, "build_transform", lambda: None)
    monkeypatch.setattr(A, "encode_paths", _fake_encode)
    monkeypatch.setattr(
        "shared.storage.local_cache.local_path",
        lambda bucket, key: Path("/fake") / bucket / key,
    )


def _seed_db(conn, datasets_dir: Path, *, crops: list[str]):
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, raw_payload_json) "
        "VALUES ('fr-2015-a', 'FR', 'France', 2015, 2.0, 1, 5001, '{}')",
    )
    obv = datasets_dir / "5001"
    obv.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (128, 128, 128)).save(obv / "obverse.jpg")
    for aid in crops:
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref) VALUES (?, 'ebay', ?)",
            (f"SI_{aid}", f"ref_{aid}"),
        )
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
            "resolution_status, face, denom, training_eligible, storage_path) "
            "VALUES (?, ?, 0, 'fr-2015-a', 'manual', 'obverse', '2eur', 1, ?)",
            (aid, f"SI_{aid}", f"{aid}.png"),
        )


def _spy_fps(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    original = A.farthest_point_select

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(A, "farthest_point_select", spy)
    return calls


def _build(store, datasets, **kw):
    with store._writing() as conn:  # noqa: SLF001
        return A.build_anchors_2eur_all(
            conn=conn, datasets_dir=datasets, force_recompute=True,
            floor_sim=0.0, encoder_version="dinov2-vitl14",
            exemplars_per_class=10, **kw,
        )


def test_le_builder_transmet_medoid_first_par_defaut(tmp_path, monkeypatch):
    """Le défaut de PRODUCTION est l'amorce au médoïde (O6), et la note du
    build le dit — c'est là qu'on lira, six semaines plus tard, avec quelle
    amorce une banque a été bâtie."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    calls = _spy_fps(monkeypatch)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed_db(conn, datasets, crops=["c1", "c2"])
    bank = _build(store, datasets)

    assert calls and all(c["medoid_first"] is True for c in calls)
    assert "amorce=medoide" in bank.build.note
    assert "amorce=fps" not in bank.build.note


def test_le_builder_transmet_medoid_first_false_et_le_trace(tmp_path, monkeypatch):
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    calls = _spy_fps(monkeypatch)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed_db(conn, datasets, crops=["c1", "c2"])
    bank = _build(store, datasets, medoid_first=False)

    assert calls and all(c["medoid_first"] is False for c in calls)
    assert "amorce=fps" in bank.build.note
    assert "amorce=medoide" not in bank.build.note


def test_la_note_garde_min_exemplars_en_tete(tmp_path, monkeypatch):
    """L'amorce s'ajoute à la note, elle ne déplace pas ce qui s'y lisait."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed_db(conn, datasets, crops=["c1"])
    bank = _build(store, datasets)
    assert bank.build.note.startswith("min_exemplars=1 (source=code); amorce=medoide; ")


# ── 4. Le CLI ────────────────────────────────────────────────────────────────

def test_cli_seed_order_defaut_medoid_et_choix_fps():
    from scripts import build_dino_anchors as bda
    parser = bda.build_parser()
    assert parser.parse_args([]).seed_order == "medoid"
    assert parser.parse_args(["--seed-order", "fps"]).seed_order == "fps"


def test_cli_seed_order_arrive_au_builder_2eur_all(tmp_path, monkeypatch):
    from scripts import build_dino_anchors as bda
    recu: dict = {}

    def fake_builder(*, conn, **kwargs):
        recu.update(kwargs)
        return object()

    monkeypatch.setitem(bda._BUILDERS, "2eur_all", fake_builder)
    store = Store(tmp_path / "t.db")
    bda._build_dispatcher("2eur_all", store, False, write_references=False,
                          seed_order="fps")
    assert recu["medoid_first"] is False
    recu.clear()
    bda._build_dispatcher("2eur_all", store, False, write_references=False)
    assert recu["medoid_first"] is True


def test_cli_seed_order_nest_pas_transmis_aux_autres_banques(tmp_path, monkeypatch):
    """Les autres builders n'ont pas ce mot-clé : le leur passer les ferait
    planter par TypeError."""
    from scripts import build_dino_anchors as bda
    recu: dict = {}

    def fake_builder(*, conn, **kwargs):
        recu.update(kwargs)
        return object()

    monkeypatch.setitem(bda._BUILDERS, "2eur_commemo", fake_builder)
    store = Store(tmp_path / "t.db")
    bda._build_dispatcher("2eur_commemo", store, False, write_references=False,
                          seed_order="fps")
    assert "medoid_first" not in recu
