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
    # 0018 crée une table NEUVE (`crop_edit_observations`) : elle est rejouable
    # telle quelle sur une base vide, donc directement comparable au miroir.
    # C'est ce qui la distingue de 0017, exclue parce qu'elle fait un ALTER +
    # backfill sur une table que `schema.sql` crée déjà.
    "0018_crop_edit_observations.sql",
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
    # `encoder_bench_runs` a gagné `quantization` et `eval_corpus` en 0015
    # (ALTER). `encoder_bench_predictions` et l'index `..._couple`, eux, sont
    # toujours ceux de 0009 et restent comparés. Le miroir des deux colonnes
    # est gardé nommément par
    # test_les_deux_colonnes_de_0015_sont_dans_les_deux_fichiers.
    "0009_encoder_bench.sql": {"encoder_bench_runs"},
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


def test_les_deux_colonnes_de_0015_sont_dans_les_deux_fichiers(objets_schema):
    """0015 ajoute `quantization` / `eval_corpus` par ALTER — donc hors du
    test paramétré (une migration d'ALTER n'est pas rejouable seule) ET hors
    de la comparaison de `encoder_bench_runs`, qui est désormais dans
    `DEPASSES`. Sans ce test nommé, plus rien ne garde ces deux colonnes : le
    miroir pourrait les perdre, les bases locales ne les auraient jamais, et
    `record_run` lèverait « colonne absente » après le calcul.
    """
    migration = MIGRATIONS / "0015_encoder_bench_quantization_eval_corpus.sql"
    sql = migration.read_text(encoding="utf-8")
    assert "ADD COLUMN quantization TEXT NOT NULL DEFAULT 'fp32'" in sql
    assert "ADD COLUMN eval_corpus TEXT" in sql
    assert "idx_encoder_bench_runs_corpus" in sql

    ddl = objets_schema["encoder_bench_runs"]
    assert "quantization" in ddl and "eval_corpus" in ddl, (
        "state/schema.sql a perdu le miroir de 0015 — les bases locales "
        "n'auraient jamais ces colonnes (elles ne rejouent pas les migrations)"
    )
    assert "idx_encoder_bench_runs_corpus" in objets_schema

    # Le miroir doit produire le MÊME DDL qu'une base migrée : `ALTER TABLE ADD
    # COLUMN` ajoute à la fin, donc les deux colonnes viennent après `note`.
    migre = sqlite3.connect(":memory:")
    migre.executescript(
        (MIGRATIONS / "0009_encoder_bench.sql").read_text(encoding="utf-8"))
    migre.executescript(sql)
    apres = [r[1] for r in migre.execute("PRAGMA table_info(encoder_bench_runs)")]
    neuve = sqlite3.connect(":memory:")
    neuve.executescript(SCHEMA.read_text(encoding="utf-8"))
    assert [
        r[1] for r in neuve.execute("PRAGMA table_info(encoder_bench_runs)")
    ] == apres, (
        "l'ordre des colonnes diverge entre une base migrée (0009 puis 0015) "
        "et une base neuve (schema.sql)"
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
        # 0014 ajoute `eval_corpus` à `image_assets` par un ALTER NU, même forme
        # que 0013 et exclue pour la même raison : `image_assets` est déclarée
        # par `schema.sql`, pas par une migration, donc la migration n'est pas
        # applicable sur une base vide et n'est pas comparable au miroir.
        #
        # Les trois branches du contrat sont tenues, et vérifiées :
        # la colonne ET son index partiel sont dans `schema.sql` (une base neuve
        # naît avec), `store.connection._ensure_column` la rattrape sur une base
        # antérieure — sans quoi l'index partiel échouerait en « no such
        # column » —, et `test_eval_holdout` prouve que les DEUX collectes
        # d'entraînement l'honorent.
        "0014_eval_corpus_holdout.sql",
        # 0015 — deux `ALTER` sur `encoder_bench_runs` (quantization,
        # eval_corpus) + un index partiel. Même raison que 0014 : pas rejouable
        # seule. Son miroir dans schema.sql, l'ordre des colonnes qu'elle
        # produit et son `_ensure_column` pre-bootstrap sont gardés nommément
        # par test_les_deux_colonnes_de_0015_sont_dans_les_deux_fichiers.
        "0015_encoder_bench_quantization_eval_corpus.sql",
        # 0016 — un `ALTER` nu sur `experiment_iterations` (inputs_digest),
        # table créée par schema.sql : pas rejouable seule. Son miroir et son
        # `_ensure_column` sont gardés par test_iteration_inputs_digest.
        "0016_iteration_inputs_digest.sql",
        # 0017 — `image_assets.face_source` : un ALTER, un BACKFILL et un
        # index partiel sur une table créée par schema.sql, donc pas
        # rejouable seule. Le backfill (`decided_face` → 'human') n'a de
        # sens que sur une base peuplée. Son miroir dans schema.sql, son
        # `_ensure_column` pre-bootstrap ET la reprise du backfill au
        # bootstrap sont gardés nommément par
        # tests/test_face_source_provenance.py.
        "0017_image_assets_face_source.sql",
    }
    connues = set(MIROIR_ATTENDU) | exclues
    presentes = {f.name for f in MIGRATIONS.glob("*.sql")}
    inconnues = presentes - connues
    assert not inconnues, (
        f"migration(s) non classée(s) : {sorted(inconnues)} — décider si leur "
        "DDL doit être miroir dans state/schema.sql, puis compléter "
        "MIROIR_ATTENDU ou la liste des exclusions de ce test."
    )
