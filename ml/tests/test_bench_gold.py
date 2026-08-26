"""P4 — le gold du banc d'encodeurs doit être figé, versionné, et honnête.

Chaque test ici garde un défaut SILENCIEUX déjà payé ailleurs dans ce repo :

- ``class_id`` = ``eurio_id`` → 105 crops sur 1 958 comptés faux (8 classes
  courantes indexées par leur représentant de groupe de dessin, mesuré le
  2026-08-19 sur la réplique). Aucune exception, juste un recall plancher.
- gold filtré sur la présence du fichier local → jeu qui rétrécit avec un cache
  froid, donc deux runs incomparables : le défaut même qu'on corrige.
- ``--db`` codé en dur → banque bâtie sur une base périmée (cf.
  ``tests/test_build_dino_anchors_cli.py``).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from review.bench_gold import (
    GoldCrop,
    build_gold,
    diff_gold,
    gold_version,
    load_gold,
    load_meta,
    meta_path,
    resolve_local_paths,
    save_gold,
)

# ─── une base minuscule, construite ICI : le gold ne doit dépendre d'aucune
#     réplique locale pour être testable (et la réplique bouge). ──────────────

_SCHEMA = """
CREATE TABLE coins (
  eurio_id TEXT PRIMARY KEY,
  design_group_id TEXT,
  is_commemorative INTEGER NOT NULL DEFAULT 0,
  canonical_eurio_id TEXT,
  year INTEGER
);
CREATE TABLE source_images (
  id TEXT PRIMARY KEY,
  target_eurio_id TEXT
);
CREATE TABLE image_assets (
  id TEXT PRIMARY KEY,
  source_image_id TEXT,
  storage_path TEXT,
  face TEXT,
  training_eligible INTEGER
);
CREATE TABLE review_queue (
  id TEXT PRIMARY KEY,
  image_asset_id TEXT,
  status TEXT,
  decided_eurio_id TEXT,
  decided_face TEXT,
  decided_at TEXT,
  decided_by TEXT,
  kind TEXT
);
"""


def _mkdb() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO coins(eurio_id, design_group_id, is_commemorative, year) VALUES (?,?,?,?)",
        [
            # Le cas du piège : deux millésimes d'une même courante française.
            ("fr-1999-2eur-standard-1st-map", "fr-2euro-standard-t1", 0, 1999),
            ("fr-2007-2eur-standard-2nd-map", "fr-2euro-standard-t1", 0, 2007),
            # Une commémorative : indexée sous elle-même.
            ("fr-2008-2eur-commemo-presidency", None, 1, 2008),
        ],
    )
    conn.executemany(
        "INSERT INTO source_images(id, target_eurio_id) VALUES (?,?)",
        [("s1", "FR-2007-2eur-standard-2nd-map"), ("s2", "de-2008-2eur-x"), ("s3", None)],
    )
    conn.executemany(
        "INSERT INTO image_assets(id, source_image_id, storage_path, face, training_eligible)"
        " VALUES (?,?,?,?,?)",
        [
            ("a1", "s1", "crops/a1.jpg", "obverse", 1),
            ("a2", "s2", "crops/a2.jpg", "reverse", 0),
            ("a3", "s3", "crops/a3.jpg", None, 1),
            ("a4", "s1", None, "obverse", 1),          # pas de storage_path → exclu
            ("a5", "s1", "crops/a5.jpg", "obverse", 1),  # status pending → exclu
            ("a6", "s1", "crops/a6.jpg", "obverse", 1),  # decided_eurio_id NULL → exclu
        ],
    )
    conn.executemany(
        "INSERT INTO review_queue(id, image_asset_id, status, decided_eurio_id,"
        " decided_face, decided_at, decided_by, kind) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("q1", "a1", "done", "fr-2007-2eur-standard-2nd-map", None,
             "2026-08-01T10:00:00Z", "admin", "single"),
            ("q2", "a2", "done", "fr-2008-2eur-commemo-presidency", "obverse",
             "2026-08-02T10:00:00Z", "admin", "lot"),
            ("q3", "a3", "done", "fr-1999-2eur-standard-1st-map", None,
             "2026-08-03T10:00:00Z", "auto_dino", "single"),
            ("q4", "a4", "done", "fr-1999-2eur-standard-1st-map", None,
             "2026-08-04T10:00:00Z", "admin", "single"),
            ("q5", "a5", "pending", "fr-1999-2eur-standard-1st-map", None,
             None, None, "single"),
            ("q6", "a6", "done", None, None, None, None, "single"),
        ],
    )
    conn.commit()
    return conn


@pytest.fixture()
def conn():
    c = _mkdb()
    yield c
    c.close()


# ─── 1. sélection ────────────────────────────────────────────────────────────

def test_build_gold_selectionne_les_decides_et_exclut_le_reste(conn):
    rows = build_gold(conn)
    assert [r.asset_id for r in rows] == ["a1", "a2", "a3"], (
        "a4 (storage_path NULL), a5 (status!='done') et a6 (pas de décision) "
        "doivent être hors gold"
    )
    a1 = rows[0]
    assert a1.truth_eurio_id == "fr-2007-2eur-standard-2nd-map"
    assert a1.truth_country == "fr", "decided_eurio_id[:2] minusculé"
    assert a1.review_kind == "single"
    assert a1.decided_by == "admin"
    assert a1.training_eligible == 1
    # `decided_face` prime sur `image_assets.face` quand il est posé.
    assert rows[1].face == "obverse"
    assert rows[2].truth_country == "fr", (
        "source_image sans cible : le pays vient quand même de la décision"
    )


def test_training_eligible_est_une_colonne_pas_un_filtre(conn):
    rows = build_gold(conn)
    assert {r.training_eligible for r in rows} == {0, 1}, (
        "les crops non éligibles à l'entraînement restent dans le gold : leur "
        "vérité vient d'un humain, et le banc n'entraîne rien"
    )


# ─── 2. le piège class_id ────────────────────────────────────────────────────

def test_class_id_est_le_representant_du_groupe_de_dessin(conn):
    """LE test du chantier : sans lui, 105 crops sur 1 958 sont comptés faux.

    ``fr-2007-…-2nd-map`` n'existe PAS dans la banque ``2eur_all`` : le groupe
    ``fr-2euro-standard-t1`` y est indexé sous son millésime le plus ancien,
    ``fr-1999-…-1st-map`` (``anchors._select_2eur_standard_groups``, tri
    ``year ASC, eurio_id ASC``).
    """
    by_id = {r.asset_id: r for r in build_gold(conn)}
    assert by_id["a1"].truth_eurio_id == "fr-2007-2eur-standard-2nd-map"
    assert by_id["a1"].class_id == "fr-1999-2eur-standard-1st-map"
    # La plus ancienne du groupe est son propre représentant.
    assert by_id["a3"].class_id == "fr-1999-2eur-standard-1st-map"
    # Une commémorative est indexée sous elle-même.
    assert by_id["a2"].class_id == "fr-2008-2eur-commemo-presidency"


# ─── 3. la version → voir §9 (elle hache la vérité, pas que la population) ───


# ─── 4. roundtrip ────────────────────────────────────────────────────────────

def test_roundtrip_save_load_champ_a_champ(conn, tmp_path):
    rows = build_gold(conn)
    out = tmp_path / "gold.jsonl"
    meta = save_gold(rows, out, meta_extra={"db_path": ":memory:", "note": "test"})

    back = load_gold(out)
    assert back == sorted(rows, key=lambda r: r.asset_id)

    relu = load_meta(out)
    assert relu == meta
    assert relu["gold_version"] == gold_version(rows)
    assert relu["n_crops"] == 3
    assert relu["n_classes"] == 2, "a1 et a3 partagent leur class_id de banque"
    assert relu["n_truth_eurio_ids"] == 3
    assert relu["n_training_eligible"] == 2
    assert relu["note"] == "test"
    assert "review_queue" in relu["selection_sql"], (
        "le sidecar doit porter le TEXTE de la requête, pas seulement sa date"
    )
    assert meta_path(out).name == "gold.meta.json"


def test_aucune_prediction_dans_le_manifeste(conn, tmp_path):
    """Le manifeste doit rester indépendant de P3 : pas un champ de prédiction."""
    out = tmp_path / "gold.jsonl"
    save_gold(build_gold(conn), out)
    keys = set()
    for line in out.read_text(encoding="utf-8").splitlines():
        keys |= set(json.loads(line))
    interdits = {"top1", "top1_eurio_id", "top1_sim", "sim", "spread", "correct",
                 "prediction", "anchors_kind", "encoder_version"}
    assert keys & interdits == set(), f"champs de prédiction dans le gold : {keys & interdits}"


def test_load_gold_refuse_un_schema_etranger(tmp_path):
    out = tmp_path / "gold.jsonl"
    out.write_text(json.dumps({"asset_id": "a1", "top1_sim": 0.9}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_gold(out)
    assert "top1_sim" in str(exc.value)


# ─── 5. diff ─────────────────────────────────────────────────────────────────

def test_diff_gold_detecte_added_removed_et_truth_changed(conn):
    frozen = build_gold(conn)
    # a3 disparaît du gold figé → la base le verra comme "added".
    reduit = [r for r in frozen if r.asset_id != "a3"]
    # a1 avait une autre vérité au moment du gel.
    reduit = [
        GoldCrop(**{**r.__dict__, "truth_eurio_id": "fr-1999-2eur-standard-1st-map"})
        if r.asset_id == "a1" else r
        for r in reduit
    ]
    # un asset qui n'existe plus en base
    reduit.append(GoldCrop("zz", "fr-1999-2eur-standard-1st-map",
                           "fr-1999-2eur-standard-1st-map", "crops/zz.jpg",
                           "fr", None, "2026-01-01T00:00:00Z", "admin", "single", 1))

    d = diff_gold(conn, reduit)
    assert d["added"] == ["a3"]
    assert d["removed"] == ["zz"]
    assert d["truth_changed"] == [
        {"asset_id": "a1", "was": "fr-1999-2eur-standard-1st-map",
         "now": "fr-2007-2eur-standard-2nd-map"}
    ]
    assert d["n_stable"] == 1, "a2 seul est inchangé"
    assert d["gold_version_frozen"] != d["gold_version_current"]


def test_diff_gold_vide_quand_rien_ne_bouge(conn):
    d = diff_gold(conn, build_gold(conn))
    assert d["added"] == [] and d["removed"] == [] and d["truth_changed"] == []
    assert d["n_stable"] == 3
    assert d["gold_version_frozen"] == d["gold_version_current"]


# ─── 6. resolve_local_paths ne filtre PAS ────────────────────────────────────

def test_resolve_local_paths_ne_retire_rien_du_gold(conn, tmp_path, monkeypatch):
    """Un fichier absent est SIGNALÉ, jamais retiré : sinon le gold rétrécit
    avec un cache froid et deux runs ne sont plus comparables."""
    rows = build_gold(conn)
    present_file = tmp_path / "a1.jpg"
    present_file.write_bytes(b"x")

    def fake_local_path(bucket, key):
        assert bucket == "enrichment-crops"
        if key == "crops/a1.jpg":
            return present_file
        raise FileNotFoundError(key)

    monkeypatch.setattr("shared.storage.local_cache.local_path", fake_local_path)
    present, missing = resolve_local_paths(rows, conn)
    assert [g.asset_id for g, _ in present] == ["a1"]
    assert missing == ["a2", "a3"]
    assert len(rows) == 3, "le manifeste d'entrée n'est pas muté"


# ─── 6bis. L'emplacement vient de la BASE, jamais du manifeste ───────────────
#
# Le gold fige QUELS crops sont notés ; il ne fige pas OÙ leurs octets sont
# rangés. Confondre les deux a coûté cher le 2026-08-26 : le déplacement des
# crops d'éval vers le bucket `eval-corpus` (D9) a périmé 208 des 1958
# `storage_path` du manifeste d'un coup. L'ancienne version suivait le chemin
# figé et hardcodait `enrichment-crops` — ces 208 partaient en `missing`, le
# banc perdait 10,6 % de son gold, basculait en `provisional=1`, et ses
# chiffres cessaient d'être comparables aux bras d'avant. Rien de faux,
# seulement décalé — la pire espèce d'écart.


def test_un_crop_deplace_reste_trouve_via_la_base(conn, tmp_path, monkeypatch):
    """LE test de cette correction.

    Le manifeste garde l'ANCIEN chemin (c'est sa provenance, elle est figée) ;
    la base porte le NOUVEAU. Le crop doit être trouvé, et depuis le bon bucket.
    """
    rows = build_gold(conn)
    # Le crop `a1` déménage : nouveau bucket, nouvelle clé. Le gold, lui, ne
    # bouge pas — il est figé, c'est tout son intérêt.
    nouvelle = "eval/matrice-encodeurs-2026-08/crops/a1.jpg"
    conn.execute("UPDATE image_assets SET storage_path = ? WHERE id = 'a1'", (nouvelle,))
    fichier = tmp_path / "a1.jpg"
    fichier.write_bytes(b"x")

    vus: list[tuple[str, str]] = []

    def fake_local_path(bucket, key):
        vus.append((bucket, key))
        if key == nouvelle:
            return fichier
        raise FileNotFoundError(key)

    monkeypatch.setattr("shared.storage.local_cache.local_path", fake_local_path)
    present, missing = resolve_local_paths(rows, conn)

    assert [g.asset_id for g, _ in present] == ["a1"], (
        "le crop déplacé doit rester trouvé — sinon le banc perd 10,6 % de son gold"
    )
    assert ("eval-corpus", nouvelle) in vus, (
        "le bucket doit être DÉRIVÉ de la nouvelle clé, pas hardcodé"
    )
    # Et le manifeste n'a pas été réécrit : sa provenance reste la vérité de ce
    # qui a été figé, ce que `diff_gold` sait lire.
    a1 = next(r for r in rows if r.asset_id == "a1")
    assert a1.storage_path == "crops/a1.jpg"


def test_un_asset_disparu_de_la_base_part_en_missing(conn, tmp_path, monkeypatch):
    """Pas de repli sur le chemin figé : un asset supprimé est une VRAIE dérive,
    pas un cache froid. Le taire ferait chercher des octets qui n'ont plus de
    ligne, et `diff_gold` est là pour la nommer."""
    rows = build_gold(conn)
    conn.execute("DELETE FROM image_assets WHERE id = 'a1'")

    vus: list[str] = []

    def fake_local_path(bucket, key):
        vus.append(key)
        raise FileNotFoundError(key)

    monkeypatch.setattr("shared.storage.local_cache.local_path", fake_local_path)
    present, missing = resolve_local_paths(rows, conn)
    assert present == []
    assert "a1" in missing
    assert "crops/a1.jpg" not in vus, (
        "pas de repli sur le chemin figé : l'asset n'a plus de ligne, "
        "on ne va pas chercher ses octets à l'ancienne adresse"
    )
    assert len(rows) == 3, "le manifeste d'entrée n'est pas muté"


# ─── 7. le CLI ───────────────────────────────────────────────────────────────

def _write_fixture_db(path):
    src = _mkdb()
    dst = sqlite3.connect(path)
    src.backup(dst)
    dst.close()
    src.close()


def test_cli_build_refuse_d_ecraser_sans_force(tmp_path, capsys):
    from scripts.bench_gold import main

    db = tmp_path / "eurio.db"
    _write_fixture_db(db)
    out = tmp_path / "gold.jsonl"

    assert main(["build", "--db", str(db), "--out", str(out)]) == 0
    first = out.read_text(encoding="utf-8")

    out.write_text("", encoding="utf-8")  # simule une divergence
    assert main(["build", "--db", str(db), "--out", str(out)]) == 2, (
        "sans --force, build doit refuser et sortir en 2"
    )
    assert out.read_text(encoding="utf-8") == "", "rien n'a été écrasé"
    assert "--force" in capsys.readouterr().err

    assert main(["build", "--db", str(db), "--out", str(out), "--force"]) == 0
    assert out.read_text(encoding="utf-8") == first


def test_cli_show_et_diff(tmp_path, capsys):
    from scripts.bench_gold import main

    db = tmp_path / "eurio.db"
    _write_fixture_db(db)
    out = tmp_path / "gold.jsonl"
    main(["build", "--db", str(db), "--out", str(out)])
    capsys.readouterr()

    assert main(["show", "--gold", str(out)]) == 0
    txt = capsys.readouterr().out
    assert "gold_version" in txt
    assert "class_id ≠ truth_eurio_id (groupes de dessin) : 1 crops" in txt

    assert main(["diff", "--db", str(db), "--gold", str(out)]) == 0
    assert "= 3 stables" in capsys.readouterr().out


def test_cli_show_et_diff_sortent_en_2_sans_gold(tmp_path):
    from scripts.bench_gold import main

    db = tmp_path / "eurio.db"
    _write_fixture_db(db)
    absent = tmp_path / "nope.jsonl"
    assert main(["show", "--gold", str(absent)]) == 2
    assert main(["diff", "--db", str(db), "--gold", str(absent)]) == 2


def test_db_path_defaut_honore_eurio_db_path(monkeypatch, tmp_path):
    """Le défaut de ``--db`` suit ``EURIO_DB_PATH``, pas ``state/eurio.db`` en dur.

    Calque de ``tests/test_build_dino_anchors_cli.py::
    test_db_path_defaut_honore_eurio_db_path`` : c'est ce littéral qui a fait
    bâtir la banque servie sur une base périmée (6 205 ``image_assets`` contre
    12 454), sans un message d'erreur.
    """
    import importlib

    import scripts.bench_gold as cli

    replique = tmp_path / "eurio.replica.db"
    monkeypatch.setenv("EURIO_DB_PATH", str(replique))
    module = importlib.reload(cli)
    try:
        assert module.DB_PATH == replique
    finally:
        monkeypatch.delenv("EURIO_DB_PATH", raising=False)
        importlib.reload(cli)


# ─── 8. D6 — le pays vient de la DÉCISION, jamais du scrape ──────────────────

def test_truth_country_vient_de_la_decision_pas_de_la_cible_du_scrape(conn):
    """D6. Le label pays doit être ``decided_eurio_id[:2]``, pas
    ``source_images.target_eurio_id[:2]``.

    Mesuré le 2026-08-19 sur ``ml/state/eurio.replica.db`` (requête dans
    l'en-tête du module ``review.bench_gold``) : sur les 1 958 crops du gold,
    **33 portaient un pays faux** (be→de ×5, es→de ×2, cy→gr, fr→de…) et
    **209 un pays nul** (10,7 %) — parce que le listing eBay visait une pièce
    et que l'humain en a tranché une autre, ou que le listing n'avait pas de
    cible du tout. Or la bande pays est le critère de départage entre deux
    encodeurs proches : 1,7 % de bruit d'étiquetage est du même ordre que
    l'écart cherché.
    """
    by_id = {r.asset_id: r for r in build_gold(conn)}
    # a2 : le scrape visait `de-2008-2eur-x`, l'humain a tranché une française.
    assert by_id["a2"].truth_eurio_id.startswith("fr-")
    assert by_id["a2"].truth_country == "fr", (
        "le pays suit la vérité tranchée, pas la cible du listing (ici 'de')"
    )
    # a3 : le listing n'avait aucune cible — la vérité, elle, en a toujours une.
    assert by_id["a3"].truth_country == "fr", (
        "un listing sans cible ne doit plus produire un pays nul : la décision "
        "porte toujours son ISO2"
    )
    # a1 : cible et vérité concordent, casse normalisée.
    assert by_id["a1"].truth_country == "fr"
    assert all(r.truth_country == r.truth_eurio_id[:2].lower()
               for r in by_id.values())


def test_le_gold_ne_porte_plus_le_pays_du_scrape(conn, tmp_path):
    """D6. Le champ ``target_country`` est retiré, pas conservé « au cas où » :
    tant qu'il est là, un lecteur peut le reprendre pour la bande pays."""
    out = tmp_path / "gold.jsonl"
    save_gold(build_gold(conn), out)
    keys = set()
    for line in out.read_text(encoding="utf-8").splitlines():
        keys |= set(json.loads(line))
    assert "target_country" not in keys
    assert "truth_country" in keys


# ─── 9. D2 — la version hache la VÉRITÉ, pas seulement la population ─────────

def test_gold_version_bouge_quand_une_verite_est_re_tranchee(conn):
    """D2. Le cas que ``diff_gold`` désigne lui-même comme « celui qui doit
    alerter » laissait la version IDENTIQUE : deux runs estampillés du même
    ``gold_version`` pouvaient avoir été notés contre des vérités différentes.

    Reproduction sur le gold committé (avant correctif) : remplacer le
    ``truth_eurio_id`` du 1er crop rendait toujours ``9b15176b3309``.
    """
    rows = build_gold(conn)
    v = gold_version(rows)
    mute = [
        GoldCrop(**{**r.__dict__, "truth_eurio_id": "de-2008-2eur-x"})
        if r.asset_id == "a1" else r
        for r in rows
    ]
    assert gold_version(mute) != v, (
        "une re-décision humaine DOIT changer la version du gold"
    )


def test_gold_version_bouge_quand_un_class_id_change(conn):
    """D2. Un ``class_id`` qui bascule (nouveau représentant de groupe de
    dessin) change ce que le banc mesure sans toucher à la vérité affichée."""
    rows = build_gold(conn)
    v = gold_version(rows)
    mute = [
        GoldCrop(**{**r.__dict__, "class_id": "fr-2007-2eur-standard-2nd-map"})
        if r.asset_id == "a1" else r
        for r in rows
    ]
    assert gold_version(mute) != v


def test_gold_version_reste_stable_par_permutation_et_bouge_a_l_ajout(conn):
    rows = build_gold(conn)
    v = gold_version(rows)
    assert gold_version(list(reversed(rows))) == v, "un set, pas une liste ordonnée"
    assert gold_version(rows[:-1]) != v
    assert len(v) == 12 and all(ch in "0123456789abcdef" for ch in v)


def test_gold_version_refuse_une_liste_d_asset_ids(conn):
    """D2. L'ancienne signature prenait des ``asset_id`` nus. La laisser passer
    silencieusement rendrait un hash de l'ancienne famille — donc comparable à
    tort avec une version d'avant correctif."""
    with pytest.raises(TypeError) as exc:
        gold_version(["a1", "a2"])
    assert "GoldCrop" in str(exc.value)


def test_diff_gold_signale_un_class_id_change(conn):
    """D2. ``diff_gold`` ne comparait que ``truth_eurio_id``."""
    frozen = [
        GoldCrop(**{**r.__dict__, "class_id": "fr-2007-2eur-standard-2nd-map"})
        if r.asset_id == "a1" else r
        for r in build_gold(conn)
    ]
    d = diff_gold(conn, frozen)
    assert d["truth_changed"] == []
    assert d["class_changed"] == [
        {"asset_id": "a1", "was": "fr-2007-2eur-standard-2nd-map",
         "now": "fr-1999-2eur-standard-1st-map"}
    ]
    assert d["n_stable"] == 2, "a1 n'est pas stable : sa classe de banque a bougé"
    assert d["gold_version_frozen"] != d["gold_version_current"]


# ─── 10. la propriété affirmée en §8.4 : rebuild byte-identique ──────────────

def test_le_gold_se_rebatit_byte_identique(tmp_path):
    """FINDINGS §8.4. Deux builds sur la même base rendent le même fichier —
    sinon le gold n'est pas un jeu figé et son diff git est illisible."""
    from scripts.bench_gold import main

    db = tmp_path / "eurio.db"
    _write_fixture_db(db)
    first = tmp_path / "g1.jsonl"
    second = tmp_path / "g2.jsonl"
    assert main(["build", "--db", str(db), "--out", str(first)]) == 0
    assert main(["build", "--db", str(db), "--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    m1, m2 = load_meta(first), load_meta(second)
    assert m1["gold_version"] == m2["gold_version"]
    # `built_at` bouge par construction : c'est le seul champ autorisé à différer
    # avec `db_path`/`out`. Le reste du sidecar doit être identique.
    volatils = {"built_at", "db_path"}
    assert {k: v for k, v in m1.items() if k not in volatils} == \
           {k: v for k, v in m2.items() if k not in volatils}


def test_cli_diff_imprime_les_classes_de_banque_changees(tmp_path, capsys):
    """D2. Le CLI taisait un ``class_id`` qui bouge — donc un gold qui ne
    mesure plus la même chose ressortait « 0 changement »."""
    from scripts.bench_gold import main

    db = tmp_path / "eurio.db"
    _write_fixture_db(db)
    out = tmp_path / "gold.jsonl"
    assert main(["build", "--db", str(db), "--out", str(out)]) == 0
    fige = load_gold(out)
    save_gold(
        [GoldCrop(**{**r.__dict__, "class_id": "fr-2007-2eur-standard-2nd-map"})
         if r.asset_id == "a1" else r for r in fige],
        out,
    )
    capsys.readouterr()

    assert main(["diff", "--db", str(db), "--gold", str(out)]) == 0
    txt = capsys.readouterr().out
    assert "1 classes de banque changées" in txt
    assert "0 vérités changées" in txt
    assert "a1  fr-2007-2eur-standard-2nd-map → fr-1999-2eur-standard-1st-map" in txt
    assert "= 2 stables" in txt


def test_cli_build_ne_crashe_pas_sur_un_gold_d_un_autre_schema(tmp_path, capsys):
    """Le correctif D6 change le schéma du manifeste (``target_country`` →
    ``truth_country``) : le gold committé d'avant ne se charge plus. Le CLI doit
    le DIRE et garder son contrat, pas rendre une traceback."""
    from scripts.bench_gold import main

    db = tmp_path / "eurio.db"
    _write_fixture_db(db)
    out = tmp_path / "gold.jsonl"
    out.write_text(
        json.dumps({"asset_id": "a1", "truth_eurio_id": "fr-1999-2eur-standard-1st-map",
                    "class_id": "fr-1999-2eur-standard-1st-map",
                    "storage_path": "crops/a1.jpg", "target_country": "de",
                    "face": None, "decided_at": "", "decided_by": None,
                    "review_kind": "single", "training_eligible": 1}) + "\n",
        encoding="utf-8",
    )
    assert main(["build", "--db", str(db), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "target_country" in err and "schéma" in err
    assert "--force" in err

    assert main(["build", "--db", str(db), "--out", str(out), "--force"]) == 0
    assert [r.asset_id for r in load_gold(out)] == ["a1", "a2", "a3"]
