-- 0015 — `encoder_bench_runs` gagne les deux axes qui lui manquaient pour
-- porter la matrice d'encodeurs dans le temps.
--
-- Chantier `juge-et-banc`, lot 5 (« durcir la matrice pour qu'elle survive à la
-- croissance du corpus »). La table de 0009 sait déjà dire QUEL encodeur, sur
-- QUELLE banque, contre QUEL gold. Elle ne sait pas dire **à quelle précision**
-- ni **sur quel corpus d'évaluation** — et sans ces deux-là, deux runs
-- deviennent indiscernables en base alors qu'ils ne mesurent pas la même chose.
--
--   · `quantization` — l'axe int8 n'a jamais été mesuré (cf. SUIVI-MATRICE.md
--     §« ce qui reste »). Le jour où il le sera, `arcface fp32` et
--     `arcface int8_dynamic` partageront `encoder_spec`, `encoder_version`,
--     `anchors_kind` et `gold_version` : ils s'écraseraient l'un l'autre dans
--     l'index `idx_encoder_bench_runs_couple` et surtout dans la lecture d'un
--     humain. Le défaut `'fp32'` est la vérité de tous les runs existants —
--     `_load_model` ne fait aucune conversion de dtype, et le banc RELÈVE
--     désormais la précision sur le modèle chargé plutôt que de la déclarer ;
--
--   · `eval_corpus` — la table est câblée sur le gold de REVIEW
--     (`gold_version`, `gold_n_crops` viennent de `review.bench_gold`). Depuis
--     la 0014, un crop porte un `image_assets.eval_corpus`, et le sidecar d'un
--     gold d'éval le recopie (`review.eval_corpus_gold.eval_gold_extra`). Sans
--     la colonne ici, « noté sur matrice-encodeurs-2026-08 » et « noté sur le
--     gold de review » se lisent pareil. NULL = gold de review, et c'est le
--     défaut de tous les runs existants.
--
-- Pourquoi PAS `eval_corpus_version` (que MATRICE.md §4 proposait à côté) : le
-- gold d'un corpus est FIGÉ et déjà versionné — `gold_version` porte l'empreinte
-- du manifeste (`9bc08e19b83c` pour les 260 frames du 2026-08-26). Une seconde
-- colonne de version dirait la même chose une seconde fois, et deux sources de
-- version qui divergent valent moins qu'une seule.
--
-- Pourquoi un ALTER ici, et pas un amendement de 0009 comme le 2026-08-19 :
-- 0009 pouvait s'amender en place parce que la table n'existait NULLE PART.
-- Ce n'est plus vrai — la matrice du 2026-08-26 a écrit des runs. Amender
-- serait un mensonge d'historique sur une table peuplée.
--
-- ⚠️ Miroir DDL obligatoire dans `ml/state/schema.sql` (les bases locales ne
-- rejouent pas les migrations, elles bootstrappent depuis schema.sql), plus
-- `_ensure_column` PRE-bootstrap dans `store/connection.py` : l'index partiel
-- ci-dessous référence `eval_corpus`, donc sur une base antérieure
-- `executescript` planterait en « no such column » avant que quoi que ce soit
-- d'autre tourne. Exactement le piège payé en 0014.

ALTER TABLE encoder_bench_runs
  ADD COLUMN quantization TEXT NOT NULL DEFAULT 'fp32';

ALTER TABLE encoder_bench_runs ADD COLUMN eval_corpus TEXT;

CREATE INDEX IF NOT EXISTS idx_encoder_bench_runs_corpus
  ON encoder_bench_runs(eval_corpus, created_at DESC)
  WHERE eval_corpus IS NOT NULL;
