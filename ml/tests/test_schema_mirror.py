"""Le double-écrit migration ↔ schema.sql est-il tenu ?

Le repo fait vivre un changement de schéma par TROIS mécanismes :

1. ``state/schema.sql`` — rejoué par ``executescript`` à chaque ouverture d'un
   Store inscriptible (``store/connection.py``) ; c'est le SEUL que voient les
   bases locales ;
2. les ``_ensure_column`` de ``store/connection.py`` (ALTER idempotents) ;
3. ``serving/migrations/*.sql`` + ``_schema_migrations``, appliqués UNIQUEMENT
   au démarrage de ``serving/server_serve.py``, c'est-à-dire uniquement au
   conteneur canonique du VPS.

Conséquence mesurée : ``ml/state/eurio.db`` porte les tables de 0006/0007/0008
alors que son ``_schema_migrations`` s'arrête à 0005. Ce n'est donc pas le
ledger qui rattrape les bases locales, c'est le MIROIR dans ``schema.sql``.
Oublier le miroir = la table n'existe jamais en local, et la panne est muette
jusqu'au premier ``no such table``.

Ce test verrouille ce double-écrit pour les migrations qui déclarent des tables
partagées local ↔ canonique. Il ne le fait PAS pour toutes :

* 0001/0002 (``users``, ``roles``, ``pat_tokens``, ``auth_audit``,
  ``coin_confusion_map``, ``sets_audit``) sont volontairement absentes de
  ``schema.sql`` — tables d'auth/legacy propres au canonique ;
* 0003/0004/0005/0007 ne sont pas rejouables seules (elles ``ALTER`` des tables
  créées par ``schema.sql``) : les comparer sur une base vierge n'a pas de sens.

La comparaison normalise commentaires et blancs : c'est la STRUCTURE qui doit
coïncider, pas la mise en page.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
SCHEMA = ML_DIR / "state" / "schema.sql"
MIGRATIONS = ML_DIR / "serving" / "migrations"

#: Les migrations dont les tables DOIVENT aussi vivre dans schema.sql.
MIROIR_ATTENDU = [
    "0006_training_thresholds.sql",
    "0008_dino_thresholds.sql",
    "0009_encoder_bench.sql",
    # 0010 reconstruit `dino_class_references` (l'encodeur entre dans la clé
    # primaire, défaut M1). Elle est REJOUABLE SEULE — contrairement à 0007,
    # elle ne fait aucun `ALTER` nu : elle commence par un `CREATE TABLE IF NOT
    # EXISTS` à la forme d'arrivée. Elle est donc comparable au miroir, et le
    # miroir est ici vital : une base locale déjà créée garde l'ancienne clé
    # pour toujours (`CREATE TABLE IF NOT EXISTS` ne reconstruit rien) — c'est
    # le writer qui la refuse alors, bruyamment.
    "0010_dino_refs_encoder_dans_la_cle.sql",
    # 0011 reconstruit `dino_thresholds` (la clé `min_exemplars`, défaut A1).
    # Rejouable seule pour la même raison que 0010 : elle commence par un
    # `CREATE TABLE IF NOT EXISTS` à la forme d'arrivée.
    "0011_dino_thresholds_min_exemplars.sql",
]

#: Les objets qu'une migration a DÉCLARÉS puis qu'une suivante a remplacés.
#: Le miroir de `schema.sql` porte forcément la forme la PLUS RÉCENTE : exiger
#: qu'il colle aussi à l'ancienne reviendrait à interdire toute reconstruction
#: de table. On nomme donc le couple (migration dépassée, objet), plutôt que de
#: sortir la migration de la liste — ses AUTRES objets restent gardés.
DEPASSES: dict[str, set[str]] = {
    # `dino_thresholds` a repris sa forme en 0011 ; `dino_threshold_changes` et
    # son index, eux, sont toujours ceux de 0008 et restent comparés.
    "0008_dino_thresholds.sql": {"dino_thresholds"},
}


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", " ", sql)).strip().lower()


def _objets(sql: str) -> dict[str, str]:
    conn = sqlite3.connect(":memory:")
    conn.executescript(sql)
    return {
        name: ddl
        for name, ddl in conn.execute("SELECT name, sql FROM sqlite_master")
        if ddl is not None and name != "sqlite_sequence"
    }


@pytest.fixture(scope="module")
def objets_schema() -> dict[str, str]:
    return _objets(SCHEMA.read_text(encoding="utf-8"))


@pytest.mark.parametrize("nom_migration", MIROIR_ATTENDU)
def test_la_migration_est_miroir_dans_schema_sql(nom_migration, objets_schema):
    migration = MIGRATIONS / nom_migration
    assert migration.exists(), f"migration disparue : {nom_migration}"
    for name, ddl in _objets(migration.read_text(encoding="utf-8")).items():
        if name in DEPASSES.get(nom_migration, set()):
            continue
        assert name in objets_schema, (
            f"{name} est déclarée par {nom_migration} mais ABSENTE de "
            "state/schema.sql — les bases locales ne l'auront jamais "
            "(elles ne rejouent pas les migrations)."
        )
        assert _normalise(objets_schema[name]) == _normalise(ddl), (
            f"{name} a dérivé entre {nom_migration} et state/schema.sql — "
            "les deux DDL doivent rester identiques."
        )


def test_les_tables_du_banc_sont_bien_dans_les_deux_fichiers(objets_schema):
    """Garde nommée : le test paramétré ci-dessus passerait aussi si
    0009 ne déclarait plus rien du tout."""
    for name in (
        "encoder_bench_runs",
        "encoder_bench_predictions",
        "idx_encoder_bench_runs_couple",
    ):
        assert name in objets_schema, f"{name} absente de state/schema.sql"
    migration = (MIGRATIONS / "0009_encoder_bench.sql").read_text(encoding="utf-8")
    assert "encoder_bench_runs" in migration
    assert "encoder_bench_predictions" in migration


def test_toute_migration_neuve_est_declaree_ou_exclue_sciemment():
    """Le jour où quelqu'un ajoute 0010, ce test le force à trancher :
    miroir attendu (l'ajouter à MIROIR_ATTENDU) ou exclusion motivée (l'ajouter
    ici). Sans ce garde-fou, une migration non miroir passe inaperçue."""
    exclues = {
        "0001_auth_redesign.sql",
        "0002_orphan_supabase_tables.sql",
        "0003_source_image_runs.sql",
        "0004_dino_predictions_run_id.sql",
        "0005_iteration_origin_summary.sql",
        "0007_dino_reference_traceability.sql",
        # 0012 n'ajoute qu'un INDEX à `peer_review_decisions`, table déclarée par
        # `state/schema.sql` et non par une migration. Elle n'est donc pas
        # applicable sur une base vide, ce que la comparaison de miroir exige —
        # d'où l'exclusion, PAS un oubli.
        #
        # La propriété qui compte est tenue autrement, et elle est vérifiée :
        # l'index EST dans `schema.sql` (une base neuve naît avec), et
        # `test_review_quarantine.test_la_course_sur_la_quarantaine_est_barree_en_base`
        # prouve qu'il mord.
        "0012_peer_review_une_seule_decision_pendante.sql",
        # 0013 ajoute `stale_since` à `image_asset_dino_predictions` par un ALTER
        # NU — exactement la forme de 0004 sur la même table, exclue pour la même
        # raison : inapplicable sur une base vide (la table n'existe pas encore
        # à ce stade), donc incomparable au miroir.
        #
        # La propriété qui compte est tenue ailleurs, et vérifiée : la colonne ET
        # son index sont dans `schema.sql` (une base neuve naît avec),
        # `store.connection` la rattrape sur une base ANTÉRIEURE via
        # `_ensure_column` — sans quoi l'index partiel de `schema.sql` échoue en
        # « no such column » avant que quoi que ce soit d'autre tourne — et
        # `test_recadrage_a_distance` prouve qu'un recadrage la pose et que le
        # backfill la lit.
        "0013_dino_prediction_perimee_par_recadrage.sql",
    }
    connues = set(MIROIR_ATTENDU) | exclues
    presentes = {f.name for f in MIGRATIONS.glob("*.sql")}
    inconnues = presentes - connues
    assert not inconnues, (
        f"migration(s) non classée(s) : {sorted(inconnues)} — décider si leur "
        "DDL doit être miroir dans state/schema.sql, puis compléter "
        "MIROIR_ATTENDU ou la liste des exclusions de ce test."
    )
