"""Unit tests for C-1 — cible training >100 + réfs BCE/EUR-Lex dans le seed pool.

Couvre la rupture A (docs/cohort-pipeline) : la cible d'augmentation est
calculée dynamiquement (×10/source, plancher 100) et les réfs canoniques
officielles (BCE / EUR-Lex JO) alimentent le bake en filet pour les classes
pauvres en crops eBay.

Run: `.venv/bin/python -m pytest ml/tests/test_iteration_augmentations.py -q`
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from training.foundation.enrichment import MIN_REAL, TRAINING_TARGET  # noqa: E402
from store import Store  # noqa: E402
from training.iteration_augmentations import (  # noqa: E402
    _canonical_ref_images,
    _ebay_training_sources,
    _target_per_coin,
)


def test_target_per_coin_dynamic_factor():
    # Facteur dynamique ceil(100/seed) appliqué uniformément → projeté ≥ 100,
    # SANS gonflement ×10 (l'exemple du PO : 15 réels → ×7 → 105).
    assert _target_per_coin(15, None) == 105
    assert _target_per_coin(21, None) == 105   # ×5
    # Classe pauvre (peu de sources) → facteur élevé, projeté juste au-dessus de 100.
    assert _target_per_coin(2, None) == 100     # ×50
    assert _target_per_coin(3, None) == 102     # ×34
    assert _target_per_coin(9, None) == 108     # ×12
    # Classe riche : 11 → ×10 → 110 ; at-2005 (17 sources) → ×6 → 102 (plus de 170).
    assert _target_per_coin(11, None) == 110
    assert _target_per_coin(17, 100) == 102
    # Tout projeté est ≥ la cible dès qu'il y a au moins une source.
    for n in (1, 2, 3, 11, 15, 17, 21, 50):
        assert _target_per_coin(n, None) >= TRAINING_TARGET
    # variant_count agit comme plancher optionnel quand > cible dynamique.
    assert _target_per_coin(3, 150) == 150
    # Plancher qualité « sources réelles » inchangé.
    assert MIN_REAL == 10


def test_canonical_ref_images_filters_source_role_and_existence(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute("PRAGMA foreign_keys=OFF")  # pas de coins parent dans ce test isolé
    present = tmp_path / "obverse_bce.webp"
    present.write_bytes(b"webp")
    rows = [
        ("c", "bce_official", "obverse", str(present)),                 # gardé
        ("c", "eurlex_jo", "obverse", str(tmp_path / "gone.webp")),     # fichier absent → ignoré
        ("c", "numista_api", "obverse", str(present)),                  # source exclue
        ("c", "bce_official", "reverse", str(present)),                 # revers → exclu
    ]
    conn.executemany(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, local_path) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    # Seule la ligne BCE obverse dont le fichier existe est retenue.
    assert _canonical_ref_images("c", store) == [present]
    # eurio_id inconnu → liste vide.
    assert _canonical_ref_images("does-not-exist", store) == []


def test_ebay_training_sources_excludes_confirmed_reverse(tmp_path, monkeypatch):
    """Gate bake P3 (improvement-loop) : un crop ``face='reverse'`` éligible
    n'entre PAS au train ; NULL / 'unknown' / 'obverse' passent."""
    import shared.storage.local_cache as lc

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute("PRAGMA foreign_keys=OFF")  # pas de coins parent, test isolé
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref) "
        "VALUES ('si1', 'ebay', 'ref1')"
    )
    crops = [
        ("a-obv", "obverse"),
        ("a-null", None),
        ("a-unk", "unknown"),
        ("a-rev", "reverse"),  # seul exclu
    ]
    for idx, (aid, face) in enumerate(crops):
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, "
            "eurio_id, resolution_status, face, training_eligible, "
            "storage_path) VALUES (?, 'si1', ?, 'c', 'manual', ?, 1, ?)",
            (aid, idx, face, f"ebay/si1/{aid}.png"),
        )
    conn.commit()
    # local_path read-through → fichiers locaux du test (pas de MinIO ici).
    files = {}
    for aid, _ in crops:
        p = tmp_path / f"{aid}.png"
        p.write_bytes(b"png")
        files[f"ebay/si1/{aid}.png"] = p
    monkeypatch.setattr(lc, "local_path", lambda bucket, key: files[key])

    paths = _ebay_training_sources("c", store)
    names = {p.stem for p in paths}
    assert names == {"a-obv", "a-null", "a-unk"}


# ─── Idempotence du bake : sur l'identité des entrées, pas sur le compte ──────
#
# Le bug couvert ici (mesuré le 2026-08-16 sur l'itération 4aaac6865ca9) : le
# bake réutilisait un snapshot dès que `len(existing) >= target` et réécrivait
# quand même le `_manifest.json` en re-dérivant `sources[i % len(sources)]` sur
# la liste de sources DU MOMENT. Une review qui ajoutait ou retirait un crop
# sans faire bouger la cible produisait donc un manifeste qui attribuait les
# samples à des sources qui ne les avaient pas produits — silencieusement.


def _bake_env(tmp_path, monkeypatch, *, target: int = 3):
    """Monte un bake minimal et isolé : 1 pièce, cible fixe, sources injectées.

    On neutralise ce qui n'est pas le sujet (résolution numista, collecte des
    sources réelles, calcul de cible) pour que le test porte sur la SEULE
    décision « régénérer ou réutiliser ».
    """
    import training.iteration_augmentations as ia
    from store import ExperimentCohortRow, ExperimentIterationRow

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id) "
        "VALUES ('c', 'AT', 2002, 2.0, 42)"
    )
    conn.commit()
    store.upsert_cohort(ExperimentCohortRow(id="co1", name="c1", eurio_ids=["c"]))
    store.upsert_iteration(
        ExperimentIterationRow(
            id="it1", cohort_id="co1", name="i1", status="pending",
            variant_count=target, augmentations_seed=1234,
        )
    )

    datasets = tmp_path / "datasets"
    (datasets / "42").mkdir(parents=True)
    monkeypatch.setattr(ia, "DATASETS_DIR", datasets)
    monkeypatch.setattr(ia, "ITERATION_TRAIN_ROOTS", datasets / "iterations")
    monkeypatch.setattr(ia.coin_lookup, "numista_id_for", lambda eid: 42)
    monkeypatch.setattr(ia, "_target_per_coin", lambda n, vc, t=None: target)

    def _source(name: str, colour: tuple[int, int, int]):
        from PIL import Image as PILImage

        p = tmp_path / name
        PILImage.new("RGB", (64, 64), colour).save(p, "JPEG")
        return p

    sources: list[Path] = [_source("s1.jpg", (200, 30, 30))]

    def _fake_sources(eurio_id, numista_id, store_):
        return ia.CoinSources(
            n_numista=1, n_ebay=len(sources) - 1, n_ref=0, paths=list(sources)
        )

    monkeypatch.setattr(ia, "real_training_sources", _fake_sources)

    out_dir = datasets / "42" / "augmentations" / "it1"
    return ia, store, sources, out_dir, _source


def _snapshot_state(out_dir: Path) -> tuple[dict, dict]:
    """(manifeste, {nom de sample: mtime_ns}) — de quoi prouver un non-rebuild."""
    import json as _json

    manifest = _json.loads((out_dir / "_manifest.json").read_text())
    mtimes = {p.name: p.stat().st_mtime_ns for p in out_dir.glob("sample_*.jpg")}
    return manifest, mtimes


def test_bake_reuses_snapshot_without_touching_the_manifest(tmp_path, monkeypatch):
    """Entrées inchangées → aucune image régénérée ET manifeste laissé tel quel."""
    ia, store, _sources, out_dir, _mk = _bake_env(tmp_path, monkeypatch)

    ia.generate_for_iteration(iteration_id="it1", store=store)
    manifest_1, mtimes_1 = _snapshot_state(out_dir)
    assert manifest_1["version"] == 2
    assert len(manifest_1["samples"]) == 3
    assert manifest_1["inputs_digest"]

    reports = ia.generate_for_iteration(iteration_id="it1", store=store)
    manifest_2, mtimes_2 = _snapshot_state(out_dir)

    assert mtimes_2 == mtimes_1                      # aucune image réécrite
    assert manifest_2 == manifest_1                  # y compris generated_at
    assert reports[0].written == 3                   # le rapport reste juste


def test_bake_regenerates_when_sources_change_at_constant_target(
    tmp_path, monkeypatch
):
    """Le piège historique : sources modifiées, cible identique.

    Avant, ce cas réutilisait les samples et réécrivait le manifeste avec la
    nouvelle liste de sources → provenance fausse. Maintenant il régénère.
    """
    ia, store, sources, out_dir, mk = _bake_env(tmp_path, monkeypatch)

    ia.generate_for_iteration(iteration_id="it1", store=store)
    manifest_1, mtimes_1 = _snapshot_state(out_dir)
    assert {s["source"] for s in manifest_1["samples"]} == {"s1.jpg"}

    sources.append(mk("s2.jpg", (30, 30, 200)))      # une review a ajouté un crop
    ia.generate_for_iteration(iteration_id="it1", store=store)
    manifest_2, mtimes_2 = _snapshot_state(out_dir)

    assert manifest_2["inputs_digest"] != manifest_1["inputs_digest"]
    assert mtimes_2 != mtimes_1                      # les images ont été refaites
    # Et la provenance décrit le cyclage réel sur les DEUX sources.
    assert [s["source"] for s in manifest_2["samples"]] == [
        "s1.jpg", "s2.jpg", "s1.jpg",
    ]
    assert [s["name"] for s in manifest_2["sources"]] == ["s1.jpg", "s2.jpg"]


def test_bake_regenerates_a_v1_snapshot(tmp_path, monkeypatch):
    """Un manifeste legacy (sans digest) ne prouve rien → on régénère une fois."""
    import json as _json

    ia, store, _sources, out_dir, _mk = _bake_env(tmp_path, monkeypatch)
    ia.generate_for_iteration(iteration_id="it1", store=store)

    legacy = _json.loads((out_dir / "_manifest.json").read_text())
    legacy.pop("version")
    legacy.pop("inputs_digest")
    (out_dir / "_manifest.json").write_text(_json.dumps(legacy))
    _manifest_0, mtimes_0 = _snapshot_state(out_dir)

    ia.generate_for_iteration(iteration_id="it1", store=store)
    manifest_1, mtimes_1 = _snapshot_state(out_dir)

    assert manifest_1["version"] == 2
    assert mtimes_1 != mtimes_0


def test_bake_regenerates_when_the_recipe_config_changes_in_place(
    tmp_path, monkeypatch
):
    """`PUT /lab/recipes/{id}` modifie une recette EN PLACE, sans changer son id.

    Hacher l'id laissait donc réutiliser un snapshot produit par l'ancienne
    config, pendant que le manifeste affirmait la nouvelle — le mensonge de
    provenance que le digest existe pour supprimer. On hache la config.
    """
    import training.iteration_augmentations as ia
    from store import AugmentationRecipeRow

    ia_, store, _sources, out_dir, _mk = _bake_env(tmp_path, monkeypatch)
    recipe = AugmentationRecipeRow(
        id="r1", name="r1", zone=None,
        config={"count": 100, "layers": []},
    )
    store.create_recipe(recipe)
    store.update_iteration("it1", recipe_id="r1")

    ia_.generate_for_iteration(iteration_id="it1", store=store)
    manifest_1, mtimes_1 = _snapshot_state(out_dir)

    # L'admin édite la recette dans le front : même id, config différente.
    store.update_recipe(
        "r1", config={"count": 100, "layers": [], "jitter": 0.4},
    )
    ia_.generate_for_iteration(iteration_id="it1", store=store)
    manifest_2, mtimes_2 = _snapshot_state(out_dir)

    assert manifest_2["inputs_digest"] != manifest_1["inputs_digest"]
    assert mtimes_2 != mtimes_1          # les images ont bien été refaites


def test_bake_regenerates_when_a_source_disappears(tmp_path, monkeypatch):
    """Retrait d'une source à cible constante — le pendant de l'ajout."""
    ia_, store, sources, out_dir, mk = _bake_env(tmp_path, monkeypatch)
    sources.append(mk("s2.jpg", (30, 30, 200)))
    ia_.generate_for_iteration(iteration_id="it1", store=store)
    manifest_1, mtimes_1 = _snapshot_state(out_dir)
    assert len(manifest_1["sources"]) == 2

    sources.pop()                        # la review a retiré le crop
    ia_.generate_for_iteration(iteration_id="it1", store=store)
    manifest_2, mtimes_2 = _snapshot_state(out_dir)

    assert manifest_2["inputs_digest"] != manifest_1["inputs_digest"]
    assert [s["name"] for s in manifest_2["sources"]] == ["s1.jpg"]
    assert mtimes_2 != mtimes_1


def test_bake_regenerates_on_a_corrupted_manifest(tmp_path, monkeypatch):
    """Un manifeste illisible ne prouve rien → on régénère plutôt que supposer."""
    ia_, store, _sources, out_dir, _mk = _bake_env(tmp_path, monkeypatch)
    ia_.generate_for_iteration(iteration_id="it1", store=store)
    _m0, mtimes_0 = _snapshot_state(out_dir)

    (out_dir / "_manifest.json").write_text("{ ceci n'est pas du JSON")
    ia_.generate_for_iteration(iteration_id="it1", store=store)
    manifest_1, mtimes_1 = _snapshot_state(out_dir)

    assert manifest_1["version"] == 2
    assert mtimes_1 != mtimes_0


def test_clear_covers_out_of_cohort_members(tmp_path, monkeypatch):
    """`clear` doit balayer l'ensemble baké, pas la seule cohorte.

    La maille design_group tire des pièces hors cohorte (56 % du dataset mesuré
    sur une cohorte de 27). Quand `clear` les ignorait, « regénérer » laissait
    intacte la moitié des augmentations.
    """
    import training.iteration_augmentations as ia

    ia_, store, _sources, out_dir, _mk = _bake_env(tmp_path, monkeypatch)
    ia_.generate_for_iteration(iteration_id="it1", store=store)
    assert out_dir.is_dir()

    # L'ensemble baké contient une pièce que la cohorte ne liste pas : c'est
    # le cas design_group, simulé ici au niveau de la fonction partagée.
    monkeypatch.setattr(
        ia_, "bake_member_ids", lambda ids, st: (None, ["sister", "c"]),
    )
    removed = ia_.clear_for_iteration(iteration_id="it1", store=store)

    assert removed == 1
    assert not out_dir.exists()          # le membre hors cohorte a bien été balayé


def test_bake_drops_leftovers_when_the_target_shrinks(tmp_path, monkeypatch):
    """Cible qui baisse → plus de samples orphelins (le staging symlinke TOUT)."""
    ia, store, _sources, out_dir, _mk = _bake_env(tmp_path, monkeypatch, target=5)
    ia.generate_for_iteration(iteration_id="it1", store=store)
    assert len(list(out_dir.glob("sample_*.jpg"))) == 5

    monkeypatch.setattr(ia, "_target_per_coin", lambda n, vc, t=None: 2)
    ia.generate_for_iteration(iteration_id="it1", store=store)

    assert sorted(p.name for p in out_dir.glob("sample_*.jpg")) == [
        "sample_001.jpg", "sample_002.jpg",
    ]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
