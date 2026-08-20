"""M1 — l'identité d'une ligne de `dino_class_references` porte-t-elle l'encodeur ?

Le correctif D1/P1 scope son ``COUNT`` sur ``encoder_version`` et le justifiait
par « la table est scopée ``UNIQUE(anchors_kind, encoder_version, class_id)`` ».
C'était **faux pour les lignes ``fps``** : cet index est PARTIEL
(``… WHERE asset_id IS NULL`` → canoniques seulement) et la clé primaire réelle
était ``(anchors_kind, class_id, eurio_id, asset_id)``, **sans l'encodeur**,
tandis que ``replace_auto_references`` écrit en ``INSERT OR REPLACE``.

Conséquence mesurée avant correctif (sonde ci-dessous, sur le DDL réel) ::

    apres build PROD : prod=200 cand=0
    apres build CAND : prod=0   cand=200
    total lignes fps : 200

c'est-à-dire : **bâtir la banque d'un encodeur candidat détruit les références
de la production**, en silence — le ``.npz`` servi ne bouge pas.

⚠️ Toutes les sondes de ce fichier se posent sur le **DDL réel** de
``state/schema.sql`` (cf. ``tests/_schema_reel``). C'est le point : la fixture
DDL du banc fabriquait un ``asset_id`` par encodeur
(``f"asset-{encoder_version}-{i}"``), donc le scénario nominal — les deux
encodeurs piochant dans le MÊME pool de crops validés — n'y était pas
exprimable, et M1 y était invisible par construction.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store.dino_references import (  # noqa: E402
    DinoRefRow,
    replace_auto_references,
    set_reference_override,
)
from tests._schema_reel import (  # noqa: E402
    applique_migration,
    base_au_schema_reel,
    ddl_table_reelle,
    lit_schema_reel,
    normalise_ddl,
)

PROD = "dinov2-vitl14"
CAND = "timm-vit_small_patch16_dinov3"
KIND = "2eur_all"


def _seed_assets(conn: sqlite3.Connection, n: int) -> list[str]:
    """`n` crops réels — le FK ``dino_class_references.asset_id`` l'exige."""
    ids = []
    for i in range(n):
        sid = f"si{i}"
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref) "
            "VALUES (?, 'ebay', ?)", (sid, f"ref{i}"),
        )
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, "
            "storage_path) VALUES (?, ?, 0, ?)", (f"a{i}", sid, f"p/{i}.png"),
        )
        ids.append(f"a{i}")
    return ids


def _rows_fps(asset_ids: list[str]) -> list[DinoRefRow]:
    """Un exemplaire ``fps`` par classe — LES MÊMES crops pour les deux
    encodeurs : c'est le cas nominal, le pool de crops validés est unique."""
    return [
        DinoRefRow(f"c{i}", f"c{i}", aid, "fps", 1, 0.5)
        for i, aid in enumerate(asset_ids)
    ]


def _n_fps(conn: sqlite3.Connection, encoder: str) -> int:
    return conn.execute(
        "SELECT COUNT(DISTINCT class_id) FROM dino_class_references "
        " WHERE anchors_kind=? AND encoder_version=? AND method='fps'",
        (KIND, encoder),
    ).fetchone()[0]


def test_construire_la_banque_candidate_ne_detruit_pas_celle_de_production(tmp_path):
    """LA sonde M1, sur le DDL réel et via le vrai writer.

    200 classes à un exemplaire, les deux encodeurs piochant le même crop.
    Attendu : les deux banques coexistent (200 / 200). Avant correctif :
    200/0 puis 0/200.
    """
    conn = base_au_schema_reel(tmp_path / "m1.db")
    assets = _seed_assets(conn, 200)
    rows = _rows_fps(assets)

    replace_auto_references(conn, KIND, rows, encoder_version=PROD)
    assert (_n_fps(conn, PROD), _n_fps(conn, CAND)) == (200, 0)

    replace_auto_references(conn, KIND, rows, encoder_version=CAND)
    assert (_n_fps(conn, PROD), _n_fps(conn, CAND)) == (200, 200), (
        "le build candidat a écrasé les références de la production — "
        "l'encodeur n'est pas dans l'identité de la ligne (M1)"
    )
    total = conn.execute(
        "SELECT COUNT(*) FROM dino_class_references WHERE method='fps'",
    ).fetchone()[0]
    assert total == 400


def test_le_canonique_reste_unique_par_classe_ET_par_encodeur(tmp_path):
    """L'index partiel ``idx_dino_class_refs_canonical`` dit-il encore ce
    qu'on veut ? Oui : un canonique par (kind, encodeur, classe) — deux
    encodeurs coexistent, un doublon pour le même encodeur est refusé.

    Il a gagné en force avec le correctif : tant que ``encoder_version`` était
    NULLABLE, deux canoniques à encodeur NULL échappaient à l'unicité
    (NULL ≠ NULL dans un index UNIQUE).
    """
    conn = base_au_schema_reel(tmp_path / "canon.db")
    canon = [DinoRefRow("c1", "c1", None, "canonical", 0, None)]
    replace_auto_references(conn, KIND, canon, encoder_version=PROD)
    replace_auto_references(conn, KIND, canon, encoder_version=CAND)
    assert conn.execute(
        "SELECT COUNT(*) FROM dino_class_references WHERE method='canonical'",
    ).fetchone()[0] == 2

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO dino_class_references "
            "(anchors_kind, encoder_version, class_id, eurio_id, asset_id, method) "
            "VALUES (?,?,?,?,NULL,'canonical')", (KIND, PROD, "c1", "c1"),
        )


def test_un_override_humain_ne_se_duplique_pas_par_encodeur(tmp_path):
    """Un pin humain vaut pour TOUS les encodeurs — il n'est pas scopé.

    Le builder ré-émet les ``manual_pin`` dans les rows qu'il passe au writer
    (``training/foundation/anchors.py``). Si le writer leur collait l'encodeur
    du build, chaque encodeur créerait sa copie de la décision humaine :
    ``get_reference_overrides`` rendrait N lignes pour un seul pin.
    """
    conn = base_au_schema_reel(tmp_path / "pin.db")
    _seed_assets(conn, 1)
    set_reference_override(conn, class_id="c0", eurio_id="c0", asset_id="a0",
                           method="manual_pin", anchors_kind=KIND)
    pin = [DinoRefRow("c0", "c0", "a0", "manual_pin", 1, None)]
    replace_auto_references(conn, KIND, pin, encoder_version=PROD)
    replace_auto_references(conn, KIND, pin, encoder_version=CAND)

    lignes = conn.execute(
        "SELECT encoder_version FROM dino_class_references "
        " WHERE method='manual_pin'",
    ).fetchall()
    assert [r["encoder_version"] for r in lignes] == [""], (
        "un override humain a été dupliqué (ou scopé) par encodeur"
    )


def test_le_writer_refuse_une_table_dont_la_cle_ignore_lencodeur(tmp_path):
    """Le garde est sur le chemin où la chose arrive.

    Une base locale ANTÉRIEURE garde son ancienne PK : ``CREATE TABLE IF NOT
    EXISTS`` ne la reconstruit pas, et ``serving/migrations/`` n'est rejoué que
    par le conteneur canonique. Sans ce garde, un build sur une telle base
    écraserait l'autre encodeur — muet. Le writer doit refuser, en nommant le
    remède.
    """
    conn = _base_forme_anterieure(tmp_path / "vieille.db")
    _seed_assets(conn, 1)
    with pytest.raises(RuntimeError, match="0010"):
        replace_auto_references(
            conn, KIND, _rows_fps(["a0"]), encoder_version=PROD,
        )


# ── La migration 0010 ────────────────────────────────────────────────────────

def _objets_dino(conn: sqlite3.Connection) -> dict[str, str]:
    """La table ET SES INDEX, tels que la base les porte vraiment.

    Comparer la seule table laisserait passer le piège qui a été trouvé ici :
    un index ne suit pas le renommage de sa table, donc les ``CREATE INDEX IF
    NOT EXISTS`` de la migration ne faisaient rien et le ``DROP TABLE`` finissait
    d'emporter les index — table saine, plus aucune contrainte d'unicité.
    """
    return {
        r["name"]: normalise_ddl(r["sql"])
        for r in conn.execute(
            "SELECT name, sql FROM sqlite_master "
            " WHERE sql IS NOT NULL AND ("
            "   name = 'dino_class_references' "
            "   OR tbl_name = 'dino_class_references')",
        )
    }


def _objets_dino_de_schema_sql(tmp_path: Path) -> dict[str, str]:
    """Les mêmes objets, dans une base créée par le VRAI ``state/schema.sql``.

    Référence apple-to-apple : on compare ce que SQLite a stocké de part et
    d'autre, pas un texte de fichier contre un texte de sqlite_master (qui
    diffèrent d'un ``IF NOT EXISTS`` et d'un point-virgule).
    """
    ref = base_au_schema_reel(tmp_path / "_reference_schema.db")
    try:
        return _objets_dino(ref)
    finally:
        ref.close()


def _schema_forme_anterieure() -> str:
    """Le schéma réel, ramené à la forme d'AVANT 0010.

    Deux substitutions sur le DDL réel — jamais de colonnes retapées à la main
    (c'est ce qui a fait passer D1 entre les mailles). Les deux `assert`
    garantissent que le test rougit si schema.sql est reformulé, au lieu de
    tester silencieusement une table qui n'a jamais existé.
    """
    texte = lit_schema_reel()
    ancien = ddl_table_reelle("dino_class_references", texte)
    avant = ancien
    avant, n1 = _remplace(
        avant,
        "PRIMARY KEY (anchors_kind, encoder_version, class_id, eurio_id, asset_id)",
        "PRIMARY KEY (anchors_kind, class_id, eurio_id, asset_id)",
    )
    avant, n2 = _remplace(
        avant, "encoder_version TEXT NOT NULL DEFAULT ''", "encoder_version TEXT",
    )
    assert (n1, n2) == (1, 1), (
        "state/schema.sql ne porte plus la forme attendue pour "
        "dino_class_references — mettre à jour cette dérivation"
    )
    return texte.replace(ancien, avant)


def _remplace(texte: str, vieux: str, neuf: str) -> tuple[str, int]:
    return texte.replace(vieux, neuf), texte.count(vieux)


def _base_forme_anterieure(chemin: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(chemin))
    conn.row_factory = sqlite3.Row
    conn.executescript(_schema_forme_anterieure())
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def test_0010_preserve_les_donnees_et_produit_le_ddl_de_schema_sql(tmp_path):
    """Reconstruction de table = le moment où l'on perd des lignes sans un mot.

    On vérifie les trois choses qui comptent : le compte, le contenu, et que la
    table d'arrivée est bien **celle que schema.sql décrit** (sinon les bases
    fraîches et le canonique divergent — la panne muette classique du repo).
    """
    conn = _base_forme_anterieure(tmp_path / "avant.db")
    _seed_assets(conn, 2)
    conn.executemany(
        "INSERT INTO dino_class_references "
        "(anchors_kind, class_id, eurio_id, asset_id, method, rank, "
        " selected_sim, encoder_version, build_id, source_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (KIND, "c0", "c0", None, "canonical", 0, None, PROD, "b1", "/p/c0.png"),
            (KIND, "c0", "c0", "a0", "fps", 1, 0.42, PROD, "b1", "/p/a0.png"),
            # Ligne humaine : jamais d'encodeur (set_reference_override n'en pose pas).
            (KIND, "c1", "c1", "a1", "manual_pin", None, None, None, None, None),
            # Ligne auto ANTÉRIEURE à 0007 : encodeur inconnu.
            (KIND, "c2", "c2", None, "canonical", 0, None, None, None, None),
        ],
    )
    conn.commit()
    avant = conn.execute("SELECT COUNT(*) FROM dino_class_references").fetchone()[0]

    applique_migration(conn, "0010_dino_refs_encoder_dans_la_cle.sql")

    apres = conn.execute("SELECT COUNT(*) FROM dino_class_references").fetchone()[0]
    assert apres == avant == 4

    # Les NULL deviennent '' — « aucun encodeur attribué », le seul sens
    # défendable pour une ligne humaine comme pour une ligne pré-0007.
    par_encodeur = dict(conn.execute(
        "SELECT encoder_version, COUNT(*) FROM dino_class_references GROUP BY 1",
    ).fetchall())
    assert par_encodeur == {PROD: 2, "": 2}
    # Le contenu utile a survécu à la reconstruction, colonne pour colonne.
    fps = conn.execute(
        "SELECT * FROM dino_class_references WHERE method='fps'",
    ).fetchone()
    assert (fps["rank"], fps["selected_sim"], fps["build_id"],
            fps["source_path"]) == (1, 0.42, "b1", "/p/a0.png")

    assert _objets_dino(conn) == _objets_dino_de_schema_sql(tmp_path), (
        "0010 et state/schema.sql ont divergé — double-écrit rompu"
    )


def test_0010_est_idempotente(tmp_path):
    """``run_migrations`` ne rejoue pas un fichier déjà appliqué, mais une base
    locale peut arriver DÉJÀ à la bonne forme (schema.sql l'y a créée neuve).
    La migration doit alors ne rien faire, pas reconstruire une table saine."""
    conn = base_au_schema_reel(tmp_path / "deja.db")
    _seed_assets(conn, 1)
    replace_auto_references(conn, KIND, _rows_fps(["a0"]), encoder_version=PROD)
    applique_migration(conn, "0010_dino_refs_encoder_dans_la_cle.sql")
    assert _n_fps(conn, PROD) == 1
    assert _objets_dino(conn) == _objets_dino_de_schema_sql(tmp_path)


def test_0010_refuse_de_fusionner_deux_canoniques_pre_0007(tmp_path):
    """Le cas que la migration ne DOIT pas absorber en silence.

    Deux canoniques de la même classe à ``encoder_version`` NULL sont
    aujourd'hui légaux (NULL ≠ NULL dans l'index UNIQUE partiel) ; les replier
    tous deux sur ``''`` en choisirait un et jetterait l'autre. Mesuré le
    2026-08-20 : zéro ligne NULL, donc le cas ne se présente pas — mais s'il se
    présentait, l'échec bruyant est le seul comportement honnête.
    """
    conn = _base_forme_anterieure(tmp_path / "collision.db")
    conn.executemany(
        "INSERT INTO dino_class_references "
        "(anchors_kind, class_id, eurio_id, asset_id, method, encoder_version) "
        "VALUES (?,?,?,NULL,'canonical',NULL)",
        [(KIND, "c0", "c0"), (KIND, "c0", "autre-membre")],
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        applique_migration(conn, "0010_dino_refs_encoder_dans_la_cle.sql")
