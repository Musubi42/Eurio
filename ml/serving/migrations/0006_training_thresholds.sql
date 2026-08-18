-- 0006 — Les seuils d'entraînement sortent du code Python.
--
-- `m_per_class`, `min_real` et `training_target` vivaient en constantes
-- (store/funnel_constants.py). Les changer demandait un redéploiement de l'API
-- locale ET du canonique — donc personne ne les changeait, donc le plancher de
-- 10 n'a jamais été éprouvé. Ici ils deviennent des lignes.
--
-- Les constantes RESTENT, comme filet : `store/thresholds.resolve()` retombe
-- dessus quand la table est absente (réplique d'un canonique plus vieux) ou
-- vide. Une table vide = le comportement d'avant, à l'identique.
--
-- Miroir DDL canonique : ml/state/schema.sql
-- Doctrine : docs/work-in-progress/refacto-page-cohorte/DECISIONS.md §D5

CREATE TABLE IF NOT EXISTS training_thresholds (
  -- 'class' est prévu et jamais alimenté : c'est le point d'accroche du seuil
  -- par classe (D2), qu'on n'activera qu'avec des benchmarks pour le justifier.
  scope       TEXT NOT NULL CHECK (scope IN ('global','cohort','class')),
  -- '' pour le global : une chaîne vide plutôt que NULL, pour que la clé
  -- primaire compare (SQLite ne dédoublonne pas les NULL dans un index unique).
  scope_id    TEXT NOT NULL DEFAULT '',
  key         TEXT NOT NULL CHECK (key IN ('m_per_class','min_real','training_target')),
  value       INTEGER NOT NULL CHECK (value >= 1),
  note        TEXT,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_by  TEXT,
  PRIMARY KEY (scope, scope_id, key)
);

-- Historique : une classe qui redevient incomplète parce que le plancher est
-- monté n'a pas régressé — la règle a changé. Sans cette table, l'écran ne peut
-- pas le dire, et la hausse se lit comme une panne (cf. D1).
CREATE TABLE IF NOT EXISTS training_threshold_changes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  scope       TEXT NOT NULL,
  scope_id    TEXT NOT NULL DEFAULT '',
  key         TEXT NOT NULL,
  old_value   INTEGER,           -- NULL = il n'y avait pas de surcharge
  new_value   INTEGER,           -- NULL = surcharge retirée
  note        TEXT,
  changed_by  TEXT,
  changed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_threshold_changes_at
  ON training_threshold_changes(changed_at DESC);
