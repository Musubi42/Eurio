-- 0011 — Le PLANCHER d'exemplaires devient un seuil réglable (défaut A1).
--
-- Le défaut qu'elle sert
-- ----------------------
-- 64 classes de la banque servie (`2eur_all` / `dinov2-vitl14`, build
-- 23c637d93b43) portent EXACTEMENT un exemplaire :
--     SELECT n, COUNT(*) FROM (SELECT class_id, COUNT(*) n
--       FROM dino_class_references
--      WHERE anchors_kind='2eur_all' AND method='fps' GROUP BY 1)
--     GROUP BY n ORDER BY n;
--   → 1|64  2|27  3|7  4|9  5|6  6|5  7|1  8|2  9|6  10|55
--     (ml/state/eurio.replica.db, 2026-08-20)
-- Or la courbe références/classe en held-out (COURBE-REFERENCES.md) mesure
-- N=1 à 50,1 % contre N=0 à 53,1 % : un exemplaire unique DÉGRADE la classe.
-- Le plancher est donc « ses exemplaires, ou son canonique seul — jamais un
-- seul exemplaire ».
--
-- Pourquoi le seuil va EN BASE et pas dans le code
-- ------------------------------------------------
-- D5 du chantier banque-dino : les seuils DINO sortent du code. Celui-ci a la
-- même portée que les autres — le couple (banque, encodeur) — parce que le
-- niveau de la courbe dépend de l'encodeur (vitl14 et vits14 ont la même
-- FORME de courbe, décalée en niveau).
--
-- Pourquoi une migration NEUVE et pas un amendement de 0008
-- ---------------------------------------------------------
-- 0008 est APPLIQUÉE au canonique : `dino_thresholds` y existe (la réplique du
-- 2026-08-20 répond à `SELECT * FROM dino_thresholds` — zéro ligne, pas « no
-- such table »). Une migration appliquée quelque part ne s'amende pas, le
-- runner ne la rejouerait jamais (cf. 0010, même raisonnement).
--
-- Pourquoi une RECONSTRUCTION et pas un ALTER
-- -------------------------------------------
-- Deux contraintes de 0008 rejettent la nouvelle clé, et SQLite ne modifie pas
-- un CHECK :
--   · `key TEXT CHECK (key IN (…5 clés…))` — `min_exemplars` n'y est pas ;
--   · `value REAL CHECK (value >= 0.0 AND value <= 1.0)` — or 2 exemplaires
--     n'est pas une similarité. La borne devient conditionnelle à la clé
--     plutôt que globale : relâcher à [0, 50] pour TOUTES les clés laisserait
--     passer `spread_auto_accept_min = 7`, qui gèlerait l'auto-acceptation en
--     silence.
-- Le coût de la reconstruction est nul ici : la table est VIDE au canonique
-- (mesure ci-dessus). La copie et le CHECK de compte sont écrits quand même —
-- une réplique locale, elle, peut porter des surcharges.
--
-- Miroir DDL canonique : ml/state/schema.sql (§Seuils DINO). Les bases locales
-- ne rejouent PAS les migrations : sans le miroir, elles garderaient la forme
-- de 0008 pour toujours et l'écriture de `min_exemplars` y échouerait sur le
-- CHECK. Le garde qui nomme ce cas est côté writer
-- (`store.dino_thresholds.set_threshold`, IntegrityError → 503 nommé).
-- ⚠️ Le miroir ne rattrape PAS une base locale déjà créée : `CREATE TABLE IF
-- NOT EXISTS` ne reconstruit rien.
--
-- Doctrine : docs/work-in-progress/banque-dino/DECISIONS.md §D5
--            docs/work-in-progress/scan-sans-retrain/COURBE-REFERENCES.md

-- Base neuve (le runner tourne AVANT le bootstrap schema.sql) : la bonne forme
-- directement, le reste devient un no-op.
CREATE TABLE IF NOT EXISTS dino_thresholds (
  anchors_kind    TEXT NOT NULL,
  encoder_version TEXT NOT NULL,
  key             TEXT NOT NULL CHECK (key IN (
                    'top1_country_sim_min','country_spread_min',
                    'spread_uncertain_max','spread_confident_min',
                    'spread_auto_accept_min','min_exemplars')),
  value           REAL NOT NULL CHECK (
                    value >= 0.0 AND value <= (
                      CASE WHEN key = 'min_exemplars' THEN 50.0 ELSE 1.0 END)),
  calibrated_on   TEXT,
  precision_at    REAL,
  n_samples       INTEGER,
  note            TEXT,
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_by      TEXT,
  PRIMARY KEY (anchors_kind, encoder_version, key)
);

-- Compte AVANT : une reconstruction de table est le moment exact où l'on perd
-- des lignes sans un mot. Relu tout en bas, dans un CHECK.
DROP TABLE IF EXISTS temp._m0011_avant;
CREATE TEMP TABLE _m0011_avant AS
  SELECT COUNT(*) AS n FROM dino_thresholds;

-- RENAME puis recréation sous le nom définitif (l'ordre inverse laisserait un
-- DDL guillemeté dans sqlite_master, divergent de schema.sql pour toujours).
DROP TABLE IF EXISTS dino_thresholds_avant_0011;
ALTER TABLE dino_thresholds RENAME TO dino_thresholds_avant_0011;

CREATE TABLE IF NOT EXISTS dino_thresholds (
  anchors_kind    TEXT NOT NULL,
  encoder_version TEXT NOT NULL,
  key             TEXT NOT NULL CHECK (key IN (
                    'top1_country_sim_min','country_spread_min',
                    'spread_uncertain_max','spread_confident_min',
                    'spread_auto_accept_min','min_exemplars')),
  value           REAL NOT NULL CHECK (
                    value >= 0.0 AND value <= (
                      CASE WHEN key = 'min_exemplars' THEN 50.0 ELSE 1.0 END)),
  calibrated_on   TEXT,
  precision_at    REAL,
  n_samples       INTEGER,
  note            TEXT,
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_by      TEXT,
  PRIMARY KEY (anchors_kind, encoder_version, key)
);

-- Copie colonne par colonne (jamais `SELECT *` : l'ordre des colonnes d'une
-- table ALTERée n'est pas celui de schema.sql par construction).
INSERT INTO dino_thresholds
  (anchors_kind, encoder_version, key, value, calibrated_on, precision_at,
   n_samples, note, updated_at, updated_by)
SELECT anchors_kind, encoder_version, key, value, calibrated_on, precision_at,
       n_samples, note, updated_at, updated_by
  FROM dino_thresholds_avant_0011;

DROP TABLE dino_thresholds_avant_0011;

-- Le CHECK échoue → la migration entière est annulée. Seule façon d'assertir
-- en SQL pur, et elle est bruyante.
CREATE TEMP TABLE _m0011_verif (delta INTEGER NOT NULL CHECK (delta = 0));
INSERT INTO _m0011_verif(delta)
  SELECT (SELECT COUNT(*) FROM dino_thresholds)
       - (SELECT n FROM _m0011_avant);
DROP TABLE temp._m0011_verif;
DROP TABLE temp._m0011_avant;
