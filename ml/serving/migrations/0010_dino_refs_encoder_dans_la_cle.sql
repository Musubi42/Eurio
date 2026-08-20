-- 0010 — L'encodeur entre dans l'IDENTITÉ d'une référence d'ancre (défaut M1).
--
-- Ce que la table promettait et ne tenait pas
-- -------------------------------------------
-- Depuis 0007, `dino_class_references` porte `encoder_version`, et le garde de
-- calibration (`store.encoder_bench._p1_blockers`) compte les classes à
-- exemplaires POUR UN ENCODEUR en se justifiant ainsi : « la table est scopée
-- UNIQUE(anchors_kind, encoder_version, class_id) ».
--
-- C'est FAUX pour les lignes `fps` :
--   · cet index est PARTIEL — `… WHERE asset_id IS NULL`, donc canoniques
--     seulement ;
--   · la clé primaire réelle était `(anchors_kind, class_id, eurio_id,
--     asset_id)`, SANS l'encodeur ;
--   · et le builder écrit en `INSERT OR REPLACE`
--     (`store/dino_references.replace_auto_references`).
--
-- Deux encodeurs qui choisissent le même crop — le cas NOMINAL, puisque c'est
-- le même pool de crops validés — écrivent donc la même clé. Sonde exécutée le
-- 2026-08-20 sur le DDL réel, 200 classes à un exemplaire, via le vrai writer
-- (`ml/tests/test_dino_refs_encoder_key.py`) :
--
--     apres build PROD : prod=200 cand=0
--     apres build CAND : prod=0   cand=200
--     total lignes fps : 200
--
-- Effet le jour du premier build d'un encodeur candidat : les 182 classes à
-- exemplaires de `dinov2-vitl14` tombent à 0, le garde P1 se met à bloquer la
-- PRODUCTION, et la traçabilité du build `23c637d93b43` disparaît. Le `.npz`
-- servi ne bouge pas : muet côté scan, visible seulement en base.
--
-- Pourquoi un fichier NEUF et pas un amendement
-- ---------------------------------------------
-- 0009 a été amendée EN PLACE le 2026-08-19, et c'était légitime : elle
-- n'avait jamais été appliquée nulle part et ses tables étaient vides partout
-- (`SELECT COUNT(*) FROM encoder_bench_predictions` → « no such table » au
-- canonique). Rien de tel ici :
--   · 0007 EST appliquée au canonique — la réplique en porte le résultat,
--     `SELECT anchors_kind, COALESCE(encoder_version,'<NULL>'), method,
--     COUNT(*) FROM dino_class_references GROUP BY 1,2,3` sur
--     `ml/state/eurio.replica.db` (2026-08-20) → `2eur_all|dinov2-vitl14|
--     canonical|664` et `…|fps|586`, 1250 lignes ;
--   · la table est PLEINE en production (1533 lignes au canonique depuis le
--     rebuild du 2026-08-19 16:36).
-- Réécrire 0007 ne changerait donc rien à la base déployée tout en mentant sur
-- l'historique. Une migration appliquée quelque part ne s'amende pas ; elle se
-- corrige par la suivante.
--
-- Le sort des lignes `encoder_version IS NULL`
-- --------------------------------------------
-- Elles deviennent `''`, qui se lit « aucun encodeur attribué » :
--   · les overrides humains (`manual_pin` / `manual_exclude`) n'en ont JAMAIS
--     eu — `set_reference_override` n'écrit pas la colonne — et n'en veulent
--     pas : une décision d'humain sur un crop vaut pour tous les encodeurs.
--     `''` est leur valeur normale, pas une valeur de repli ;
--   · les rares lignes AUTO antérieures à 0007 ont un encodeur inconnu. `''`
--     les garde lisibles et les tient hors de toute mesure par encodeur
--     (`encoder_version = 'dinov2-vitl14'` ne matche pas `''`), ce qui est
--     exactement le comportement que le correctif D1/P1 avait choisi pour
--     NULL. Le prochain build les balaie : le DELETE de
--     `replace_auto_references` couvre `encoder_version IN (?, '')` pour les
--     méthodes `canonical`/`fps`.
-- Mesuré le 2026-08-20 sur la réplique : ZÉRO ligne NULL. La règle est donc
-- écrite pour le cas qui ne se présente pas — c'est le but : ne pas laisser la
-- migration choisir en silence le jour où il se présentera.
--
-- Le seul cas que la migration REFUSE : deux canoniques de la même classe à
-- encodeur NULL. Ils sont légaux aujourd'hui (NULL ≠ NULL dans un index UNIQUE
-- partiel) ; les replier tous deux sur `''` en garderait un et jetterait
-- l'autre. La migration échoue alors sur `CREATE UNIQUE INDEX
-- idx_dino_class_refs_canonical` — bruyamment, transaction annulée
-- (`db_migrate.run_migrations` journalise et remonte). Remède manuel :
--     SELECT anchors_kind, class_id, COUNT(*) FROM dino_class_references
--      WHERE asset_id IS NULL AND encoder_version IS NULL GROUP BY 1,2
--      HAVING COUNT(*) > 1;
-- puis trancher à la main quelle ligne garder. Un échec de migration coûte un
-- redémarrage ; une fusion silencieuse coûte une donnée.
--
-- Miroir DDL canonique : ml/state/schema.sql §« Références Dino
-- multi-exemplaires » — la table y est ÉCRITE à l'identique. Sans ce miroir,
-- les bases locales (qui bootstrappent depuis schema.sql et ne rejouent PAS
-- les migrations) garderaient l'ancienne clé pour toujours.
-- ⚠️ Le miroir ne suffit pas pour une base locale DÉJÀ créée : `CREATE TABLE
-- IF NOT EXISTS` ne reconstruit pas une table existante. Le garde qui rattrape
-- ce cas est dans le writer lui-même
-- (`store/dino_references._exige_encodeur_dans_la_cle`) : il refuse d'écrire
-- sur une table à l'ancienne clé plutôt que d'y écraser l'autre encodeur.
--
-- Doctrine : docs/work-in-progress/scan-sans-retrain/FINDINGS.md §8.8 (M1)

-- Base neuve (le runner tourne AVANT le bootstrap schema.sql, cf. FINDINGS
-- §6.5) : on crée directement la bonne forme, le reste devient un no-op.
CREATE TABLE IF NOT EXISTS dino_class_references (
  anchors_kind  TEXT NOT NULL DEFAULT '2eur_all',
  class_id      TEXT NOT NULL,
  eurio_id      TEXT NOT NULL,
  asset_id      TEXT REFERENCES image_assets(id) ON DELETE CASCADE,
  method        TEXT NOT NULL
                CHECK (method IN ('canonical','fps','manual_pin','manual_exclude')),
  rank          INTEGER,
  selected_sim  REAL,
  built_at      TEXT NOT NULL DEFAULT (datetime('now')),
  encoder_version TEXT NOT NULL DEFAULT '',
  build_id        TEXT,
  source_path     TEXT,
  PRIMARY KEY (anchors_kind, encoder_version, class_id, eurio_id, asset_id)
);

-- Compte AVANT — une reconstruction de table est le moment exact où l'on perd
-- des lignes sans un mot. Relu tout en bas, dans un CHECK.
DROP TABLE IF EXISTS temp._m0010_avant;
CREATE TEMP TABLE _m0010_avant AS
  SELECT COUNT(*) AS n FROM dino_class_references;

-- Reconstruction : on RENOMME l'ancienne (ses index la suivent) puis on
-- recrée la table sous son nom définitif. L'ordre inverse (créer `…_0010`
-- puis RENAME) laisserait un DDL guillemeté dans sqlite_master, divergent de
-- schema.sql pour toujours.
DROP TABLE IF EXISTS dino_class_references_avant_0010;
ALTER TABLE dino_class_references RENAME TO dino_class_references_avant_0010;

-- ⚠️ Un index NE SUIT PAS le renommage de son nom : il reste accroché à la
-- table renommée, sous le même nom. Sans ces DROP, les `CREATE INDEX IF NOT
-- EXISTS` plus bas ne feraient RIEN (le nom est pris), puis le `DROP TABLE`
-- emporterait les index avec l'ancienne table : on se retrouverait avec une
-- table SANS AUCUN INDEX, y compris sans l'unique index du canonique. Attrapé
-- par `test_0010_refuse_de_fusionner_deux_canoniques_pre_0007`, qui ne levait
-- plus rien.
DROP INDEX IF EXISTS idx_dino_class_refs_asset;
DROP INDEX IF EXISTS idx_dino_class_refs_class;
DROP INDEX IF EXISTS idx_dino_class_refs_build;
DROP INDEX IF EXISTS idx_dino_class_refs_canonical;

CREATE TABLE IF NOT EXISTS dino_class_references (
  anchors_kind  TEXT NOT NULL DEFAULT '2eur_all',
  class_id      TEXT NOT NULL,
  eurio_id      TEXT NOT NULL,
  asset_id      TEXT REFERENCES image_assets(id) ON DELETE CASCADE,
  method        TEXT NOT NULL
                CHECK (method IN ('canonical','fps','manual_pin','manual_exclude')),
  rank          INTEGER,
  selected_sim  REAL,
  built_at      TEXT NOT NULL DEFAULT (datetime('now')),
  encoder_version TEXT NOT NULL DEFAULT '',
  build_id        TEXT,
  source_path     TEXT,
  PRIMARY KEY (anchors_kind, encoder_version, class_id, eurio_id, asset_id)
);

-- Index posés AVANT la copie : une violation nomme alors la ligne fautive,
-- pas « CREATE UNIQUE INDEX ».
CREATE INDEX IF NOT EXISTS idx_dino_class_refs_asset
  ON dino_class_references(asset_id) WHERE asset_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dino_class_refs_class
  ON dino_class_references(anchors_kind, class_id);
CREATE INDEX IF NOT EXISTS idx_dino_class_refs_build
  ON dino_class_references(build_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dino_class_refs_canonical
  ON dino_class_references(anchors_kind, encoder_version, class_id)
  WHERE asset_id IS NULL;

-- Copie colonne par colonne (jamais `SELECT *` : l'ordre des colonnes d'une
-- table ALTERée n'est pas celui de schema.sql par construction).
INSERT INTO dino_class_references
  (anchors_kind, class_id, eurio_id, asset_id, method, rank, selected_sim,
   built_at, encoder_version, build_id, source_path)
SELECT anchors_kind, class_id, eurio_id, asset_id, method, rank, selected_sim,
       built_at, COALESCE(encoder_version, ''), build_id, source_path
  FROM dino_class_references_avant_0010;

DROP TABLE dino_class_references_avant_0010;

-- Vérification de compte : le CHECK échoue → la migration entière est annulée.
-- C'est la seule façon d'assertir en SQL pur, et elle est bruyante.
CREATE TEMP TABLE _m0010_verif (delta INTEGER NOT NULL CHECK (delta = 0));
INSERT INTO _m0010_verif(delta)
  SELECT (SELECT COUNT(*) FROM dino_class_references)
       - (SELECT n FROM _m0010_avant);
DROP TABLE temp._m0010_verif;
DROP TABLE temp._m0010_avant;
