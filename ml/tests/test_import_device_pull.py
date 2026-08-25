"""Import d'un pull device dans le corpus de scan — arbre synthétique.

Ce que ces tests garantissent, et pourquoi chacun existe :

- le **remap** d'un slug d'APK mort est appliqué (sans lui, le corpus stockerait
  une vérité terrain qui ne désigne aucune pièce du référentiel) ;
- le **dédoublonnage par ``capture_id``** : deux fichiers identiques octet pour
  octet ne font qu'une capture, quel que soit leur nom ;
- ``bundle_source`` est renseigné, et il est **filtrable** — c'est la seule
  chose qui sépare deux protocoles partageant un nom d'étape ;
- ``cohort_id`` / ``source_iteration_id`` restent **NULL** (provenance non
  inventée) ;
- l'**idempotence** : rejouer l'import ne crée aucune ligne neuve.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts import import_device_pull as idp  # noqa: E402
from store.scan_corpus import ScanCorpusStore  # noqa: E402

# Un slug mort couvert par la table tranchée à l'œil, et son jumeau vivant.
DEAD_SLUG = "es-2016-2eur-old-city-of-segovia-and-its-aqueduct"
LIVE_SLUG = "es-2016-2eur-old-town-of-segovia-and-its-aqueduct"
# Un slug mort couvert seulement par la table MESURÉE.
DEAD_SLUG_EXTRA = "ad-2014-2eur-standard"
LIVE_SLUG_EXTRA = "ad-2014-2eur-standard-1st-type"


def _jpeg(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _write_frame(
    class_dir: Path,
    stem: str,
    *,
    raw: bytes,
    eurio_id: str,
    step_id: str,
    ts: str,
    photo_index: int = 0,
    method: str = "hough_strict",
) -> None:
    class_dir.mkdir(parents=True, exist_ok=True)
    (class_dir / f"{stem}_raw.jpg").write_bytes(raw)
    (class_dir / f"{stem}_crop.jpg").write_bytes(_jpeg((10, 20, 30), (224, 224)))
    (class_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "ts": ts,
                "eurio_id": eurio_id,
                "step_id": step_id,
                "step_label": "libellé",
                "step_index": 0,
                "photo_index": photo_index,
                "frame_size": [480, 640],
                "crop_size": 224,
                "normalize": {"method": method, "cx": 1, "cy": 2, "r": 3},
                "matches": [{"class": "68395", "sim": 0.8}],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def pull(tmp_path: Path) -> Path:
    """Arbre synthétique : 2 classes à slug mort + 1 doublon octet-pour-octet."""
    root = tmp_path / "pull_20260429" / "eurio_debug" / "eval_real"

    shared = _jpeg((1, 2, 3))
    d = root / DEAD_SLUG
    _write_frame(d, "bright_plain", raw=shared, eurio_id=DEAD_SLUG,
                 step_id="bright_plain", ts="20260429_164750_336")
    # Même contenu, autre nom : le capture_id les fusionne.
    _write_frame(d, "bright_plain_p1", raw=shared, eurio_id=DEAD_SLUG,
                 step_id="bright_plain", ts="20260429_164751_000", photo_index=1)
    _write_frame(d, "dim_plain", raw=_jpeg((4, 5, 6)), eurio_id=DEAD_SLUG,
                 step_id="dim_plain", ts="20260429_164800_100")

    e = root / DEAD_SLUG_EXTRA
    _write_frame(e, "bright_plain", raw=_jpeg((7, 8, 9)), eurio_id=DEAD_SLUG_EXTRA,
                 step_id="bright_plain", ts="20260429_165000_000")
    return tmp_path / "pull_20260429"


def _run(pull: Path, db: Path, bundle: str, *, execute: bool, manifest: Path) -> int:
    argv = [
        "--pull", str(pull),
        "--bundle-source", bundle,
        "--db", str(db),
        "--manifest", str(manifest),
        # Le référentiel n'est pas garanti présent en CI ni sur une machine
        # fraîche ; le garde-fou a son propre test ci-dessous.
        "--allow-unknown",
    ]
    if execute:
        argv.append("--execute")
    return idp.main(argv)


def test_slug_mort_remappe_et_dedoublonnage(tmp_path: Path, pull: Path) -> None:
    db = tmp_path / "corpus.db"
    manifest = tmp_path / "manifest.jsonl"
    assert _run(pull, db, "device_pull_20260429", execute=True, manifest=manifest) == 0

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM scan_corpus ORDER BY capture_id").fetchall()

    # 4 fichiers lus, 3 captures : le doublon octet-pour-octet a fusionné.
    assert len(rows) == 3
    ids = {r["eurio_id"] for r in rows}
    assert ids == {LIVE_SLUG, LIVE_SLUG_EXTRA}
    assert DEAD_SLUG not in ids and DEAD_SLUG_EXTRA not in ids

    # capture_id = sha256(raw_bytes)[:16], pas un identifiant fabriqué.
    for r in rows:
        raw = (Path(db).parent / "scan_corpus" / r["raw_path"]).read_bytes()
        assert r["capture_id"] == hashlib.sha256(raw).hexdigest()[:16]

    # condition = step_id brut ; provenance jamais inventée ; protocole porté.
    assert {r["condition"] for r in rows} == {"bright_plain", "dim_plain"}
    assert all(r["cohort_id"] is None for r in rows)
    assert all(r["source_iteration_id"] is None for r in rows)
    assert all(r["bundle_source"] == "device_pull_20260429" for r in rows)

    # Le slug d'origine n'est pas perdu : il est journalisé, pas effacé.
    assert all(DEAD_SLUG in r["notes"] or DEAD_SLUG_EXTRA in r["notes"] for r in rows)
    q = json.loads(rows[0]["quality_json"])
    assert q["normalize"]["method"] == "hough_strict"

    # Crop transcodé en PNG, raw archivé tel quel.
    for r in rows:
        assert r["crop_path"].endswith(".crop.png")
        assert (Path(db).parent / "scan_corpus" / r["crop_path"]).exists()


def test_idempotence(tmp_path: Path, pull: Path) -> None:
    db = tmp_path / "corpus.db"
    manifest = tmp_path / "manifest.jsonl"
    _run(pull, db, "device_pull_20260429", execute=True, manifest=manifest)
    before = sqlite3.connect(db).execute("SELECT COUNT(*) FROM scan_corpus").fetchone()[0]

    stats = idp.ImportStats()
    store = ScanCorpusStore(db_path=db)
    frames, _ = idp.scan_tree(idp.resolve_eval_real(pull), idp.build_remap())
    idp.ingest(store, frames, "device_pull_20260429", stats, execute=True)

    after = sqlite3.connect(db).execute("SELECT COUNT(*) FROM scan_corpus").fetchone()[0]
    assert after == before == 3
    assert stats.inserted == 0
    assert stats.updated == 3


def test_deux_protocoles_se_filtrent(tmp_path: Path, pull: Path) -> None:
    """Deux pulls partagent ``bright_plain`` : seul ``bundle_source`` les sépare."""
    db = tmp_path / "corpus.db"
    manifest = tmp_path / "manifest.jsonl"
    _run(pull, db, "device_pull_20260429", execute=True, manifest=manifest)

    juin = tmp_path / "pull_20260601" / "eval_real"
    _write_frame(juin / LIVE_SLUG, "bright_plain", raw=_jpeg((30, 40, 50)),
                 eurio_id=LIVE_SLUG, step_id="bright_plain",
                 ts="20260601_144743_071", method="hough_strict")
    _run(tmp_path / "pull_20260601", db, "device_pull_20260601",
         execute=True, manifest=manifest)

    store = ScanCorpusStore(db_path=db)
    assert store.count() == 4
    avril = store.list_captures(bundle_sources=["device_pull_20260429"])
    juin_caps = store.list_captures(bundle_sources=["device_pull_20260601"])
    assert len(avril) == 3 and len(juin_caps) == 1
    assert len(store.list_captures(
        bundle_sources=["device_pull_20260429", "device_pull_20260601"])) == 4

    # La condition SEULE ne sépare rien : elle vaut bright_plain des deux côtés.
    assert len(store.list_captures(conditions=["bright_plain"])) == 3


def test_dry_run_n_ecrit_aucune_ligne(tmp_path: Path, pull: Path) -> None:
    db = tmp_path / "corpus.db"
    manifest = tmp_path / "manifest.jsonl"
    assert _run(pull, db, "device_pull_20260429", execute=False, manifest=manifest) == 0
    # ⚠️ Le store crée sa base au premier ScanCorpusStore() — le fichier existe
    # donc, et sa taille ne prouve rien. Le seul critère est le COUNT(*).
    assert sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM scan_corpus"
    ).fetchone()[0] == 0
    assert not manifest.exists()


def test_manifeste_sans_prediction(tmp_path: Path, pull: Path) -> None:
    db = tmp_path / "corpus.db"
    manifest = tmp_path / "manifest.jsonl"
    _run(pull, db, "device_pull_20260429", execute=True, manifest=manifest)

    lines = [json.loads(l) for l in manifest.read_text().splitlines() if l.strip()]
    assert len(lines) == 3
    assert [l["capture_id"] for l in lines] == sorted(l["capture_id"] for l in lines)
    for l in lines:
        assert set(l) == {
            "capture_id", "eurio_id", "condition", "bundle_source", "captured_at"
        }
    meta = json.loads(manifest.with_suffix(".meta.json").read_text())
    assert meta["n_captures"] == 3
    assert meta["n_by_bundle_source"] == {"device_pull_20260429": 3}
    assert meta["contains_predictions"] is False
    assert meta["scoring_path"] == "full"
    assert len(meta["corpus_version"]) == 12


def test_eurio_id_hors_referentiel_refuse(tmp_path: Path, monkeypatch) -> None:
    """Un slug que le référentiel ne connaît pas est un slug mort de plus : le
    script refuse au lieu d'écrire une vérité terrain qui ne désigne rien."""
    root = tmp_path / "pull" / "eval_real" / "xx-9999-2eur-inexistante"
    _write_frame(root, "bright_plain", raw=_jpeg((11, 22, 33)),
                 eurio_id="xx-9999-2eur-inexistante", step_id="bright_plain",
                 ts="20260601_144743_071")
    monkeypatch.setattr(idp, "load_referential_ids", lambda: {LIVE_SLUG})
    db = tmp_path / "corpus.db"
    rc = idp.main([
        "--pull", str(tmp_path / "pull"),
        "--bundle-source", "device_pull_test",
        "--db", str(db),
        "--manifest", str(tmp_path / "m.jsonl"),
        "--execute",
    ])
    assert rc == 2
    assert sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM scan_corpus"
    ).fetchone()[0] == 0


def test_parse_ts_et_position() -> None:
    assert idp.parse_ts("20260429_164750_336") == "2026-04-29T16:47:50.336"
    assert idp.parse_ts("pas-un-ts") is None
    assert idp._split_position("bright_plain_p2") == ("bright_plain", 2)
    assert idp._split_position("bright_plain") == ("bright_plain", 0)
    assert idp._split_position("glare_specular") == ("glare_specular", 0)


def test_extra_mapping_ne_contredit_pas_la_table_a_l_oeil() -> None:
    """``MAPPING`` est tranchée à l'œil : la table mesurée ne la surcharge jamais."""
    from scripts.remap_bench_golden_set import MAPPING

    by_old = {m.old_eurio_id: m.new_eurio_id for m in MAPPING}
    for old, new in idp.EXTRA_MAPPING.items():
        assert by_old.get(old, new) == new
    assert idp.build_remap()[DEAD_SLUG_EXTRA] == LIVE_SLUG_EXTRA


# ─── class_level_only : le FAIT « juste à la classe, faux à la pièce » ──────


def test_class_level_only_vient_de_la_table_a_l_oeil() -> None:
    """Le drapeau n'est pas deviné : il est LU dans ``MAPPING``.

    Sans lui, ``scan_corpus`` n'avait aucune colonne pour dire qu'une capture
    est bien labellisée à la classe et fausse à la pièce — et un écran qui
    permet de remapper aurait fait remapper à l'aveugle.
    """
    flagged = idp.build_class_level_only()
    assert flagged == {"be-2008-2eur-standard"}
    # Les 4 lignes MESURÉES visent des pièces existantes : aucune n'est dans ce cas.
    assert not (flagged & set(idp.EXTRA_MAPPING))


def test_import_pose_le_drapeau_sur_les_captures_concernees(tmp_path: Path) -> None:
    """Bout en bout : un dossier au slug ``class_level_only`` ressort flaggé,
    ses voisins non."""
    root = tmp_path / "pull" / "eurio_debug" / "eval_real"
    _write_frame(root / "be-2008-2eur-standard", "close_plain",
                 raw=_jpeg((11, 22, 33)), eurio_id="be-2008-2eur-standard",
                 step_id="close_plain", ts="20260429_170000_000")
    _write_frame(root / DEAD_SLUG, "bright_plain", raw=_jpeg((44, 55, 66)),
                 eurio_id=DEAD_SLUG, step_id="bright_plain",
                 ts="20260429_170100_000")

    db = tmp_path / "corpus.db"
    assert _run(tmp_path / "pull", db, "device_pull_test", execute=True,
                manifest=tmp_path / "m.jsonl") == 0

    store = ScanCorpusStore(db_path=db)
    by_flag = {c.eurio_id: c.class_level_only for c in store.list_captures()}
    assert by_flag == {
        "be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait": True,
        LIVE_SLUG: False,
    }
