-- 0008 — Les seuils DINO sortent du code.
--
-- `top1_country_sim_min = 0.55` et `country_spread_min = 0.05` vivaient dans
-- training/foundation/thresholds.py, dont le docstring dit encore « valeurs
-- provisoires, à calibrer après collecte d'au moins 200 reviews annotées ».
-- Il y en a 1 955. Un seuil qu'on ne peut pas bouger ne peut pas être éprouvé.
--
-- TABLE SÉPARÉE de `training_thresholds`, pour trois raisons cumulées :
--   · `value` y est un INTEGER CHECK (value >= 1) ; ici ce sont des flottants ;
--   · `key` y est sous contrainte CHECK — ajouter une clé imposerait de
--     reconstruire la table de toute façon (SQLite ne modifie pas un CHECK) ;
--   · surtout, la PORTÉE n'est pas la même. Un seuil calibré sur vits14 ne
--     veut rien dire pour vitl14 : l'axe pertinent est le couple
--     (banque, encodeur), pas la cohorte.
--
-- Les constantes Python RESTENT le filet (shared/dino_threshold_defaults.py) :
-- table absente ou vide = comportement d'avant, à l'identique.
--
-- Miroir DDL canonique : ml/state/schema.sql
-- Doctrine : docs/work-in-progress/banque-dino/DECISIONS.md §D5

CREATE TABLE IF NOT EXISTS dino_thresholds (
  anchors_kind    TEXT NOT NULL,
  encoder_version TEXT NOT NULL,
  key             TEXT NOT NULL CHECK (key IN (
                    'top1_country_sim_min','country_spread_min',
                    'spread_uncertain_max','spread_confident_min',
                    'spread_auto_accept_min')),
  value           REAL NOT NULL CHECK (value >= 0.0 AND value <= 1.0),
  -- Sur quoi la valeur a été calibrée. Sans ça, « 0.10 » est un nombre sans
  -- père et personne n'ose le bouger — c'est exactement le défaut de l'état
  -- qu'on quitte.
  calibrated_on   TEXT,
  precision_at    REAL,
  n_samples       INTEGER,
  note            TEXT,
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_by      TEXT,
  PRIMARY KEY (anchors_kind, encoder_version, key)
);

-- Bouger un seuil reclasse des milliers d'items entre `auto_accept` et
-- `manual`. Sans historique, ça se lit comme une régression.
CREATE TABLE IF NOT EXISTS dino_threshold_changes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  anchors_kind    TEXT NOT NULL,
  encoder_version TEXT NOT NULL,
  key             TEXT NOT NULL,
  old_value       REAL,       -- NULL = il n'y avait pas de surcharge
  new_value       REAL,       -- NULL = surcharge retirée
  note            TEXT,
  changed_by      TEXT,
  changed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dino_threshold_changes_at
  ON dino_threshold_changes(changed_at DESC);
