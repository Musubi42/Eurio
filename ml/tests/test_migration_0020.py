"""0020 — le tirage du jeu d'or, et le triple mécanisme du dépôt.

Une table qui ne vit que dans `serving/migrations/` n'existe JAMAIS en local
(les bases locales ne rejouent pas les migrations, elles bootstrappent depuis
`state/schema.sql`), et la panne est muette jusqu'au premier `no such table`.
Ces tests verrouillent les trois endroits, puis les contraintes qui portent une
décision — chacune avec la mutation qui la rend rouge.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests._schema_reel import (
    applique_migration,
    base_au_schema_reel,
    ddl_table_reelle,
    normalise_ddl,
)
from tests.test_schema_mirror import MIROIR_ATTENDU, MIGRATIONS

MIGRATION = "0020_crop_gold_tirage.sql"


def _base(tmp_path):
    conn = base_au_schema_reel(tmp_path / "t.db")
    conn.execute("INSERT INTO source_images (id, source, source_ref,"
                 " storage_path, width, height, sha256)"
                 " VALUES ('si','ebay','r','ebay/x.jpg',900,900,'sha')")
    conn.execute("INSERT INTO image_assets (id, source_image_id, crop_index,"
                 " resolution_status, storage_path)"
                 " VALUES ('ia','si',0,'manual','crops/x.png')")
    conn.execute("INSERT INTO crop_gold_versions (gold_version) VALUES ('v1')")
    conn.commit()
    return conn


def _insere(conn, **kw):
    ligne = {"gold_version": "v1", "asset_id": "ia", "role": "tirage", "rn": 1,
             "strate_tiree": "S1_facile", "width": 900, "height": 900,
             "hint_cx": 450.0, "hint_cy": 450.0, "hint_r": 440.0,
             "prefill_cx": None, "prefill_cy": None, "prefill_a": None,
             "prefill_b": None, "prefill_theta_deg": None,
             "prefill_reason": None}
    ligne.update(kw)
    colonnes = ", ".join(ligne)
    trous = ",".join("?" * len(ligne))
    conn.execute(f"INSERT INTO crop_gold_tirage ({colonnes}) VALUES ({trous})",
                 tuple(ligne.values()))


# ─── 1. les trois endroits du triple mécanisme ──────────────────────────────

def test_une_base_neuve_nait_avec_la_table(tmp_path):
    """Mutation : retirer `crop_gold_tirage` de `state/schema.sql` → rouge.
    C'est le SEUL des trois mécanismes que voient les bases locales."""
    conn = _base(tmp_path)
    _insere(conn)
    assert conn.execute("SELECT COUNT(*) FROM crop_gold_tirage").fetchone()[0] == 1
    conn.close()


def test_la_migration_est_rejouable_seule_et_donne_le_meme_ddl(tmp_path):
    """Mutation : changer une colonne dans l'un des deux fichiers → rouge.
    Une migration et son miroir qui divergent, c'est une base locale et un
    canonique qui ne portent pas la même table.

    On compare les DDL tels que SQLite les REND (`sqlite_master`) des deux
    côtés : la relecture normalise `IF NOT EXISTS` et le `;` final, qu'aucun
    des deux fichiers n'écrit pareil.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=OFF")   # la migration référence 0019
    applique_migration(conn, MIGRATION)
    ddl_migre = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'crop_gold_tirage'"
    ).fetchone()[0]
    conn.close()

    neuve = base_au_schema_reel(tmp_path / "neuve.db")
    ddl_miroir = neuve.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'crop_gold_tirage'"
    ).fetchone()[0]
    neuve.close()
    assert normalise_ddl(ddl_migre) == normalise_ddl(ddl_miroir)


def test_la_migration_est_declaree_dans_le_miroir_attendu():
    """Mutation : la retirer de MIROIR_ATTENDU → rouge (et
    `test_toute_migration_neuve_est_declaree_ou_exclue_sciemment` aussi)."""
    assert MIGRATION in MIROIR_ATTENDU
    sql = (MIGRATIONS / MIGRATION).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS crop_gold_tirage" in sql
    assert "idx_crop_gold_tirage_asset" in sql
    assert "idx_crop_gold_tirage_version_role" in sql


def test_le_verdict_humain_n_est_pas_dans_la_table():
    """Ce n'est pas un oubli, c'est la décision : l'annotateur qui voit le
    verdict le confirme au lieu de tracer ce qu'il voit, et RE-4 ne mesure plus
    rien. Il reste joignable depuis `image_assets` pour le banc.

    Mutation : ajouter une colonne `verdict` → rouge."""
    ddl = normalise_ddl(ddl_table_reelle("crop_gold_tirage"))
    assert "verdict" not in ddl


# ─── 2. les contraintes qui portent une décision ────────────────────────────

def test_un_role_inconnu_est_refuse(tmp_path):
    """Mutation : retirer le CHECK sur `role` → rouge. Un rôle libre ferait
    passer une faute de frappe pour une image de réserve, donc hors séance."""
    conn = _base(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        _insere(conn, role="tirag")
    conn.close()


def test_un_prefill_a_moitie_rempli_est_refuse(tmp_path):
    """Le pré-remplissage est nullable EN GROUPE : une ellipse à moitié remplie
    serait une proposition au jugé. Mutation : retirer le CHECK → rouge."""
    conn = _base(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        _insere(conn, prefill_cx=450.0, prefill_cy=450.0)
    conn.close()


def test_un_demi_grand_axe_inverse_est_refuse(tmp_path):
    """`cv2.fitEllipse` rend (largeur, hauteur), PAS (grand, petit) — et le
    pré-remplissage vient précisément de là. Mutation : retirer
    `prefill_a >= prefill_b` → rouge."""
    conn = _base(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        _insere(conn, prefill_cx=450.0, prefill_cy=450.0, prefill_a=100.0,
                prefill_b=200.0, prefill_theta_deg=0.0)
    _insere(conn, prefill_cx=450.0, prefill_cy=450.0, prefill_a=200.0,
            prefill_b=100.0, prefill_theta_deg=0.0)
    conn.close()


def test_une_image_ne_figure_qu_une_fois_par_version(tmp_path):
    """La clé primaire est ce qui rend la publication IDEMPOTENTE. Sans elle,
    republier le manifeste doublerait la séance."""
    conn = _base(tmp_path)
    _insere(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insere(conn, role="reserve")
    conn.close()


def test_supprimer_la_version_emporte_son_tirage(tmp_path):
    """`ON DELETE CASCADE` : un tirage orphelin dirait qu'il reste des images à
    annoter pour une version qui n'existe plus."""
    conn = _base(tmp_path)
    _insere(conn)
    conn.execute("DELETE FROM crop_gold_versions WHERE gold_version = 'v1'")
    assert conn.execute("SELECT COUNT(*) FROM crop_gold_tirage").fetchone()[0] == 0
    conn.close()
