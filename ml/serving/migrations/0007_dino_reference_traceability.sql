-- 0007 — La traçabilité de la banque d'ancres doit répondre à quatre
-- questions : quelles pièces, quelle image, quand, quel encodeur.
--
-- Elle n'en répondait à aucune de façon fiable, et pour cause : la table
-- `dino_class_references` est VIDE dans les 8 bases locales ET au canonique.
-- La cause est écrite dans `scripts/build_dino_anchors.py` : `BEGIN IMMEDIATE`
-- réussit sur une connexion en lecture seule, et l'échec n'arrive qu'à la
-- première vraie écriture — c'est-à-dire après quatre minutes d'encodage, à la
-- dernière ligne du build. Sous le flip Direction A, tous les builds ont donc
-- écrit leur .npz et perdu leur trace.
--
-- Ce que la table ne pouvait pas dire, même remplie :
--   · avec quel ENCODEUR (colonne absente) — deux banques du même kind sont
--     indiscernables, et le prochain build en effacerait une ;
--   · à quel BUILD une ligne appartient (`built_at` est un DEFAULT par ligne,
--     donc ~1200 horodatages voisins mais distincts) ;
--   · quelle IMAGE a servi pour le canonique (`asset_id` NULL, chemin nulle
--     part) — précisément la ligne qui pose problème quand l'avers manque.
--
-- Miroir DDL canonique : ml/state/schema.sql
-- Doctrine : docs/work-in-progress/banque-dino/DECISIONS.md

CREATE TABLE IF NOT EXISTS dino_anchor_builds (
  build_id        TEXT PRIMARY KEY,
  anchors_kind    TEXT NOT NULL,
  encoder_version TEXT NOT NULL,
  -- UNE heure pour tout le build, à la différence du built_at par ligne.
  built_at        TEXT NOT NULL,
  n_classes       INTEGER NOT NULL,
  n_rows          INTEGER NOT NULL,
  n_canonical     INTEGER NOT NULL,
  n_exemplars     INTEGER NOT NULL,
  -- Classes portées par leurs seuls crops validés, faute d'avers canonique.
  -- Ce compteur est la mesure de santé du référentiel image : s'il monte,
  -- c'est que les téléchargements Numista échouent quelque part.
  n_no_canonical  INTEGER NOT NULL DEFAULT 0,
  exemplars_per_class INTEGER,
  floor_sim       REAL,
  host            TEXT,
  note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_dino_builds_kind
  ON dino_anchor_builds(anchors_kind, built_at DESC);

ALTER TABLE dino_class_references ADD COLUMN encoder_version TEXT;
ALTER TABLE dino_class_references ADD COLUMN build_id TEXT;
-- Le chemin RÉELLEMENT encodé. Pour un exemplaire c'est le crop ; pour le
-- canonique (asset_id NULL) c'est la seule trace de l'avers utilisé.
ALTER TABLE dino_class_references ADD COLUMN source_path TEXT;

CREATE INDEX IF NOT EXISTS idx_dino_class_refs_build
  ON dino_class_references(build_id);

-- L'unicité du canonique devient (kind, ENCODEUR, classe) : sans l'encodeur,
-- deux banques du même kind ne peuvent pas coexister, et toute comparaison
-- d'encodeurs serait bloquée dès le premier build. On aligne cette table sur
-- `image_asset_dino_predictions`, dont la clé primaire porte déjà l'encodeur.
DROP INDEX IF EXISTS idx_dino_class_refs_canonical;
CREATE UNIQUE INDEX IF NOT EXISTS idx_dino_class_refs_canonical
  ON dino_class_references(anchors_kind, encoder_version, class_id)
  WHERE asset_id IS NULL;
