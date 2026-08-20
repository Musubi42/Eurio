-- 0009 — Les résultats du banc multi-encodeurs deviennent une donnée, pas un
-- fichier de sortie.
--
-- Le banc (`scripts/bench_encoder_dino.py`) imprime aujourd'hui deux
-- pourcentages dans un terminal. Deux conséquences mesurables :
--   · rien ne permet de rejouer un test APPARIÉ entre deux encodeurs sans
--     tout ré-encoder — d'où la table `encoder_bench_predictions`, qui garde
--     le strict nécessaire (correct / in_top5 / spread) et rien de plus ;
--   · la page admin voulue par PROTOCOLE-BENCH.md est servie par le front
--     HÉBERGÉ, qui n'a pas accès au ML local (`hasLocalMlApi=false`). Un
--     résultat qui ne vit que sur le Mac n'est pas consultable.
--
-- Pourquoi PAS `benchmark_runs` : ses FK pointent un run d'entraînement et une
-- recette d'augmentation, et elle n'a aucune colonne d'encodeur. Un banc
-- d'encodeurs gelés n'a ni l'un ni l'autre.
--
-- Ce qui reste LOCAL et ne monte jamais ici : les .npz, les embeddings, les
-- images. Ne montent que les scalaires de décision (<1 Mo par balayage complet :
-- 1911 crops × 4 encodeurs × ~120 o).
--
-- `CREATE TABLE IF NOT EXISTS` pur, aucun `ALTER` nu : la chaîne de migrations
-- n'est pas auto-suffisante (elle casse à 0003 sur une base vierge), un `ALTER`
-- la rendrait plus fragile encore.
--
-- Miroir DDL canonique : ml/state/schema.sql §« Banc multi-encodeurs » — ÉCRIT,
-- et verrouillé par ml/tests/test_schema_mirror.py (0009 y est déclarée
-- MIROIR_ATTENDU). Sans ce miroir, les bases locales n'auraient JAMAIS ces
-- tables : elles bootstrappent depuis schema.sql et ne rejouent pas les
-- migrations. Toute modification ici se refait À L'IDENTIQUE dans schema.sql,
-- sinon le test casse — c'est le but.
--
-- AMENDÉE EN PLACE le 2026-08-19 (n_paired ; truth_eurio_id → truth_class_id),
-- sans ALTER et sans 0010 : 0009 n'a JAMAIS été appliquée. Mesuré ce jour-là —
--   sqlite3 "file:ml/state/eurio.replica.db?mode=ro" \
--     "SELECT COUNT(*) FROM encoder_bench_predictions;"
--   → Error: no such table   (la table n'existe pas au canonique)
-- Éditer le CREATE est donc exact ; un 0010 d'ALTER serait un mensonge
-- d'historique sur une table que personne n'a encore.
-- Doctrine : docs/work-in-progress/banque-dino/PROTOCOLE-BENCH.md

CREATE TABLE IF NOT EXISTS encoder_bench_runs (
  run_id            TEXT PRIMARY KEY,
  created_at        TEXT NOT NULL,
  -- Le jeu d'évaluation est FIGÉ et versionné (P4) : sans ça, deux runs à deux
  -- semaines d'écart ne sont pas comparables, la file de review ayant bougé.
  gold_version      TEXT NOT NULL,          -- review.bench_gold.gold_version
  gold_n_crops      INTEGER NOT NULL,
  gold_sample_n     INTEGER,                -- non-NULL = run sur échantillon, pas sur le gold entier
  anchors_kind      TEXT NOT NULL,
  encoder_spec      TEXT NOT NULL,          -- la spec CLI : 'dinov2_vitl14' | 'timm:vit_small_patch16_dinov3.lvd1689m'
  encoder_version   TEXT NOT NULL,          -- le nom canonique stocké dans le .npz
  bank_build_id     TEXT,                   -- dino_anchor_builds.build_id, si connu
  bank_n_anchors    INTEGER,
  bank_n_classes    INTEGER,
  embed_dim         INTEGER,
  n_params_m        REAL,
  input_px          INTEGER,
  device            TEXT,
  ms_per_img        REAL,
  n_in_scope        INTEGER NOT NULL,
  recall1           REAL,
  recall5           REAL,
  country_n         INTEGER,
  country_recall1   REAL,
  country_recall5   REAL,
  spread_at_p97     REAL,
  coverage_at_p97   REAL,
  precision_at_p97  REAL,
  sweep_json        TEXT,
  baseline_run_id   TEXT,
  mcnemar_p         REAL,
  mcnemar_b         INTEGER,
  mcnemar_c         INTEGER,
  -- Nombre de crops RÉELLEMENT communs au run et à sa baseline (jointure sur
  -- asset_id, cf. store.encoder_bench.paired_overlap). Sans lui, un McNemar
  -- calculé sur un recouvrement partiel est indiscernable d'un McNemar complet
  -- (D16) : b et c ne disent pas sur combien de paires ils portent. NULL est
  -- légitime — un run sans baseline_run_id n'a pas de recouvrement.
  n_paired          INTEGER,
  -- 1 = les chiffres de calibration ne sont PAS promouvables en l'état.
  -- Aujourd'hui TOUJOURS 1 : la banque servie est amputée de 57 classes (P1)
  -- et les 12454 prédictions sont périmées (P3, non lancé).
  -- Le défaut est 1 : un run promouvable est l'exception qu'il faut justifier.
  provisional       INTEGER NOT NULL DEFAULT 1,
  provisional_reason TEXT,
  host              TEXT,
  git_commit        TEXT,
  note              TEXT
);

CREATE INDEX IF NOT EXISTS idx_encoder_bench_runs_couple
  ON encoder_bench_runs(anchors_kind, encoder_version, created_at DESC);

-- ~120 o/ligne. Volontairement SANS `top_k_json` : c'est ce qui fait peser
-- 975 o/ligne à `image_asset_dino_predictions` (19,7 Mo pour 20 234 lignes).
-- Ici on garde strictement ce dont McNemar et le balayage de seuils ont besoin.
CREATE TABLE IF NOT EXISTS encoder_bench_predictions (
  run_id        TEXT NOT NULL,
  asset_id      TEXT NOT NULL,
  -- ⚠️ C'est le `class_id` de la BANQUE, pas un `coins.eurio_id` (D5). La banque
  -- indexe une pièce sous le représentant de son groupe de dessin ; comparer
  -- au `decided_eurio_id` compterait fausses toutes les pièces repliées sur
  -- un représentant — 105 crops sur 1958 au 2026-08-19 (5,4 %), qui ne
  -- joignent donc PAS `coins.eurio_id`. La colonne s'appelait `truth_eurio_id`
  -- jusqu'au 2026-08-19 ; renommée pendant que la table était vide partout.
  truth_class_id TEXT NOT NULL,
  top1_eurio_id TEXT,
  top1_sim      REAL,
  top2_sim      REAL,
  spread        REAL,
  correct       INTEGER NOT NULL,
  in_top5       INTEGER NOT NULL,
  country_top1_eurio_id TEXT,
  country_correct INTEGER,
  PRIMARY KEY (run_id, asset_id)
);
