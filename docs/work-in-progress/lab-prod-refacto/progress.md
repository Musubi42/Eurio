# Progress log — refacto lab ↔ prod

> Append-only. Une entrée datée par session significative. Les agents
> qui démarrent une nouvelle session lisent ce fichier en entier (au
> moins les dernières entrées) avant d'attaquer la phase suivante.
>
> Format :
>
> ```
> ## YYYY-MM-DD · Phase N · titre
>
> **Done** : ce qui a été livré
> **Working** : ce qui marche end-to-end
> **Broken / partial** : ce qui ne marche pas
> **Deviations from phase doc** : si on s'est écarté du plan
> **Decisions taken** : choix non triviaux
> **Handoff** : ce qu'il faut savoir pour la session suivante
> ```

---

## 2026-05-02 · Phase 0 · Mise en place du refacto

**Done** :

- Création du dossier `docs/lab-prod-refacto/` avec :
  - `README.md` (index, motivation, phases)
  - `analysis.md` (état actuel, deux symptômes observés sur cohort
    `mix-zone-7-cls`, cartographie des artefacts partagés)
  - `vision.md` (cible architecturale, structure disque, contrats)
  - `phase-1-label-space.md` (eurio_id partout côté lab)
  - `phase-2-isolation-artefacts.md` (lab/iterations/<iid>/ par run)
  - `phase-3-promote.md` (step promote explicite, options fusion vs
    équivalence à trancher)
  - `phase-4-bundle-routing.md` (APK prod / cohort-test sources
    explicites)
  - `progress.md` (ce fichier)

- Document `docs/training-pipeline/refacto/lab-prod-isolation.md`
  retiré (déplacé/segmenté ici).

**Working** :

- Aucun code livré dans cette session — uniquement de la doc.
- Le patch temporaire "destructif par itération" reste en place dans
  `ml/api/iteration_runner.py:871-884` (livré dans une session
  antérieure), il restera là tant que phase 2 n'est pas faite.

**Broken / partial** :

- L'itération `8ac508b062da` est en cours d'exécution avec le bug
  prepare 4-classes-sur-7 actif. À stopper et reset (cf. handoff).
  La phase 1 doit être livrée avant de relancer pour récolter des
  chiffres exploitables.

**Decisions taken** :

- Le label space côté lab est `eurio_id` strict, sans exception.
- Le label space côté prod est tranché en phase 3 — recommandation
  initiale : option équivalence (centroïdes par eurio_id, règle au
  matcher). À confirmer.
- Le mode "destructif par itération" est un patch temporaire, pas une
  cible. Il sera retiré en phase 2.
- Le refacto est segmenté en 4 phases, chacune autonome, livrable
  indépendamment.

**Handoff** :

- Avant la session phase 1 : stopper l'itération `8ac508b062da` via
  l'UI lab (bouton stop). Une fois la run vraiment morte
  (`status='failed'` ou `completed` dans la DB), reset l'itération
  en `pending` via SQL :
  ```sql
  UPDATE experiment_iterations
  SET status='pending', training_run_id=NULL, error=NULL,
      started_at=NULL, finished_at=NULL
  WHERE id='8ac508b062da';
  ```
- La phase 1 débloque immédiatement test-1 v2. C'est l'urgence.
- Les phases 2-4 améliorent l'isolation et la traçabilité mais ne
  bloquent pas l'expérimentation immédiate.

---

## 2026-05-02 · Phase 1 · Label space eurio_id côté lab — code livré

**Done** :

- `ml/eval/class_resolver.py` : `build_resolver(force_eurio_id=False)`.
  Quand True, réécrit chaque `CoinRef` avec `design_group_id=None`
  avant construction du Resolver. Aucune modif de la classe
  `Resolver` elle-même.
- `ml/training/prepare_dataset.py` :
  - Nouvel arg CLI `--class-kind {eurio_id,design_group}`,
    **required** (pas de défaut).
  - Propagation à `build_resolver(force_eurio_id=...)`.
  - `split_dataset(..., class_kind=...)` propage le mode jusqu'à
    l'override eval_real_norm.
  - **Fail-explicit** sur `eval_real_norm/<eurio_id>/` manquant en
    mode eurio_id (vs silent skip historique). Erreur listant
    toutes les classes manquantes.
- `ml/api/training_runner.py:_prepare()` : lit
  `row.config.get("class_kind", "design_group")` et le passe en
  `--class-kind` au subprocess.
- `ml/api/iteration_runner.py:_launch_training` :
  `config["class_kind"] = "eurio_id"` ajouté explicitement (signal
  explicite plutôt que proxy `dataset_override`).
- `ml/Taskfile.yml` : `task prepare` reçoit
  `--class-kind design_group` (legacy preserved).
- Nouveau `ml/tests/test_class_resolver.py` : 3 tests qui verrouillent
  le contrat (default coalesce, force_eurio_id strip, distinct coins
  pas collapsés). Tous passent.

**Working** :

- Imports propres (`prepare_dataset`, `training_runner`,
  `iteration_runner`, `class_resolver`) — sanity check passé.
- Tests `test_class_resolver` (3) + `test_normalize_dispatch` (4)
  passent.

**Broken / partial** :

- `tests/test_benchmark.py` a 7 fails — **pré-existants**
  (`ModuleNotFoundError: evaluate_real_photos`, problème de
  sys.path dans le fichier de test, sans lien avec phase 1).

**Deviations from phase doc** :

- **Pas de rétrocompat default** sur `--class-kind` : l'arg est
  required, pas defaulté à `design_group`. Conséquence : le seul
  caller manuel (`task prepare` dans `ml/Taskfile.yml`) a été mis
  à jour pour passer explicitement `--class-kind design_group`.
  Décidé pour éviter une dépendance implicite "si je lance sans
  flag, je me prends le mode legacy".
- **Signal explicite `cfg["class_kind"]`** ajouté à
  `iteration_runner` plutôt que de relire `dataset_override` comme
  proxy. Plus lisible, plus testable.
- **Test unit ajouté** alors que la phase doc ne le requérait pas —
  10 lignes, verrouille le contrat à vie.

**Decisions taken** :

- Le silent skip dans `prepare_dataset.py:248` devient fail-explicit
  uniquement en mode `eurio_id`. En mode `design_group`, le
  comportement legacy reste (parce qu'on ne sait pas si tous les
  design_group_ids ont un dossier eval_real_norm — pas notre
  problème dans cette phase).
- `confusion_map.py` reste intact — sémantique distincte du label
  space d'entraînement.
- Cleanup des dirs fantômes `eval_real_norm/at-2eur-standard-2002/`
  etc. → reporté.
- `model_classes` Supabase peut accumuler des rows design_group
  stales → problème phase 3 (promote).

**Handoff** :

- **Audit eval_real_norm pour la cohort `mix-zone-7-cls`** : les 7
  eurio_ids ont tous un dossier sous `ml/datasets/eval_real_norm/`.
  Pas de blocker pour relancer test-1 v2.
- **Avant de relancer test-1 v2** : reset l'itération `8ac508b062da`
  en `pending` via SQL (cf. session précédente) si pas déjà fait.
- **Critères d'acceptance à valider** post-relance :
  1. `eurio-poc/train/` → 7 dossiers (un par eurio_id)
  2. `eurio-poc/val/<eurio_id>/` → 6 device snaps chacun
  3. `embeddings_v1.json` → 7 entrées
  4. `model_meta.json` → `num_classes=7`
  5. Bench peut prédire chaque eurio_id
- **Régime change attendu** côté `compute_embeddings.py` : plus de
  classes vont basculer sur la fallback ArcFace-W (moins de val
  samples par classe sans le merging design_group). À surveiller
  dans les logs, pas un bug.
- **Wart pré-existant flagué** : `prepare_dataset.py:240-242` a un
  fallback `eval_real_dir` mort par construction (la première
  branche ne match jamais). Hors scope phase 1.
- Phase 2 (isolation par iteration_id) peut démarrer dès que test-1 v2
  donne des chiffres exploitables.

---

## 2026-05-02 · Phase 1 · ✅ validée par test-1 v2

**Done** :

- Test-1 de la cohort `mix-zone-7-cls-v2` (`8ac508b062da`) tourne
  end-to-end avec phase 1 active.
- Critères d'acceptance tous validés :
  1. ✅ `eurio-poc/train/` → 7 dossiers (un par eurio_id)
  2. ✅ `eurio-poc/val/<eurio_id>/` → 6 device snaps chacun
  3. ✅ `embeddings_v1.json` → 7 entrées
  4. ✅ `model_meta.json` `num_classes=7`
  5. ✅ Bench prédit chaque eurio_id (matrice de confusion couvre
     les 7 classes, aucun collapse)
- Journal détaillé écrit :
  `docs/training-pipeline/journal/510f658e-mix-zone-7-cls-v2/test-1.md`

**Working** :

- Bench R@1 / R@3 / R@5 : **92.86% / 97.62% / 100%** (strict eurio_id).
- Live R@1 strict : **85.7%** (18/21) — vs 57.1% en test-2.
- Les 3 classes qui collapsaient en test-2 (AT-2002, BE-2007,
  ES-1999) sortent du trou.

**Broken / partial** :

- 3 erreurs live résiduelles (AD-2014 bright, ES-1999 dim+tilt) qui
  vont toutes vers IT-2016 — pattern d'attracteur sur conditions
  extrêmes. Pas un bug structurel, problème de recipe / backbone à
  attaquer dans les phases suivantes.

**Decisions taken** :

- Phase 1 lab-prod-refacto **clôturée** ✅.
- Méthodologie `eurio_id` strict côté lab **figée comme baseline**.
  Pas de retour en arrière.
- Élargissement stratégique : nouvelle structure `docs/features/`
  qui segmente par feature produit (scrape, augmentation, model)
  et référence ce refacto comme couche infrastructure.

**Handoff** :

- Phase 2 (isolation par iteration_id) peut démarrer immédiatement,
  ou en parallèle de `harvest/phase-1` (DINOv2 bring-up) selon la
  reco du journal test-1 v2.
- Le mode "destructif par itération" dans
  `iteration_runner.py:870-895` reste en place tant que phase 2
  n'est pas livrée.

---

## 2026-05-02 · Phase 2 · Isolation des artefacts par `iteration_id` — code livré

**Done** :

- Nouveau layout `ml/lab/iterations/<iid>/{dataset,checkpoints,
  embeddings,tflite,metrics,reports}/`. Création des sous-dossiers
  + symlink `dataset/train` → `ml/datasets/iterations/<iid>/` (le
  bake canonique reste à sa place, déjà bien isolé par iid).
- `ml/api/iteration_runner.py` :
  - `_iter_dir(iid)` / `_iter_model_path(iid)` helpers ajoutés.
  - `_launch_training` : crée l'arborescence iter, pose le symlink
    `dataset/train`, propage `config["iter_dir"]`,
    `config["dataset_override"] = symlink path`.
  - **Mode destructif retiré** : `removed = []` au lieu du diff
    `current_classes - cohort`. Commentaire pointe vers
    `phase-2-isolation-artefacts.md`.
  - `_export_tflite` : exporte sous `iter_dir/tflite/`, plus
    nouvelle méthode `_mirror_iter_outputs` qui copie
    `embeddings_v1.json`, `coin_embeddings.json`,
    `eurio_embedder_v1.tflite`, `model_meta.json` vers `ml/output/`
    (rétrocompat aval — phase 4 retirera la copie).
  - `_launch_benchmark` + `_record_benchmark_phase_failure` :
    `model_path = _iter_model_path(iid)`.
  - Mtime check `finished_at` : pointe sur le tflite iter (pas
    `ml/output/`) pour rester cohérent quand 2 itérations se suivent.
  - Constante `CHECKPOINTS_DIR` retirée (plus aucun consommateur).
- `ml/api/training_runner.py` :
  - Helper module-level `_iter_dir(row)` qui lit `config["iter_dir"]`.
  - Chaque step (`_delete`, `_prepare`, `_train`,
    `_compute_embeddings`, `_seed`, `_validate_per_class`,
    `_finalize_run`) branche sur iter_dir. Mode legacy (sans
    iter_dir) inchangé.
  - `_delete` : skip explicite en mode iter (pas de purge
    inter-run nécessaire).
  - `_seed` : skip explicite en mode iter (push Supabase devient
    l'effet exclusif de la promotion — phase 3).
  - `_prepare` : passe `--output-dir iter_dir/dataset` +
    `--skip-train-split` à `prepare_dataset.py`.
  - `_train` : `--val-dataset iter_dir/dataset/val`, `--output
    iter_dir/checkpoints` (write `best_model.pth` +
    `training_log.json` là).
  - `_compute_embeddings` : `--model iter_dir/checkpoints/...`,
    `--dataset iter_dir/dataset`, `--output-dir iter_dir/embeddings`.
  - `_validate_per_class` : `--model`, `--dataset`, `--output
    iter_dir/metrics/per_class_metrics.json`.
  - `_finalize_run` : lit `iter_dir/checkpoints/training_log.json`.
- `ml/training/prepare_dataset.py` :
  - Nouveau flag `--skip-train-split`. En mode skip : ne génère
    que `val/` (depuis eval_real_norm) + `class_manifest.json`,
    n'efface pas `output_dir` (préserve le symlink train/).
  - Refacto interne : `_override_val_with_eval_real()` extrait en
    helper, partagé par les deux modes.

**Working** :

- Imports propres (`api.iteration_runner`, `api.training_runner`,
  `training.prepare_dataset`).
- `tests/test_class_resolver.py` (3) + `tests/test_normalize_dispatch.py`
  (6) → 9 passent.

**Broken / partial** :

- Pas de run de bout en bout exécutée dans cette session. Validation
  réelle = lancer une itération dans le lab et vérifier les critères
  d'acceptance (cf. handoff).
- `tests/test_benchmark.py` toujours 7 fails pré-existants
  (`ModuleNotFoundError: evaluate_real_photos`), pas lié à phase 2.

**Deviations from phase doc** :

- **`prepare_dataset.py` : ajout de `--skip-train-split`** plutôt
  que de laisser un `train/` studio orphelin sous `iter_dir/dataset/`
  (le doc proposait l'orphelin comme acceptable). R0 : pas de dette,
  on n'écrit que ce qui sert.
- **Symlink `iter_dir/dataset/train` → `ml/datasets/iterations/<iid>/`**
  (pas de migration du bake lui-même). Conforme au doc qui dit
  "iteration_augmentations.py n'a pas besoin de bouger".
- **Constante `CHECKPOINTS_DIR` retirée** d'`iteration_runner.py`
  (orpheline après le refacto, aucun import externe). Cleanup au
  passage.

**Decisions taken** :

- `_seed` est **skipé** en mode iter (pas commenté, pas conditionné
  à un flag opt-in). Les écritures Supabase deviennent l'effet
  exclusif de la promotion (phase 3). En mode legacy hors-iteration,
  comportement inchangé.
- Le symlink `dataset/train` est **idempotent** (re-créé à chaque
  `_launch_training`) — supporte les relances d'itération sans
  laisser d'état pourri.
- Mtime check `finished_at` pointe sur `iter_dir/tflite/...` (pas
  `ml/output/...`). La copie vers `ml/output/` se fait juste après,
  donc on a `mtime(iter) ≤ mtime(output)` ; le bundle script lit
  `output/`, qui est plus récent → pas de faux-positif stale.
- Mode legacy (`start_run` direct, sans iteration) **préservé** :
  pas de `iter_dir` dans config → tous les paths fallback sur
  `EURIO_POC` / `CHECKPOINTS_DIR` / `OUTPUT_DIR`. Aucun caller hors
  iteration_runner n'est cassé.

**Handoff** :

- **Avant la prochaine itération** : `mkdir -p ml/lab/iterations/`
  ne suffit pas, c'est créé automatiquement à la volée par
  `_launch_training`. Aucune migration manuelle requise.
- **Critères d'acceptance à valider** post-relance d'une itération :
  1. `ml/lab/iterations/<iid>/{dataset,checkpoints,embeddings,
     tflite,metrics,reports}/` complets après training.
  2. `ml/datasets/eurio-poc/` **non modifié** par l'itération
     (peut être vide ou stale).
  3. Symlink `iter_dir/dataset/train` valide vers
     `ml/datasets/iterations/<iid>/`.
  4. `ml/output/embeddings_v1.json` + `eurio_embedder_v1.tflite`
     mis à jour à la fin (mirror).
  5. Aucun message "removed N classes" dans les logs (le mode
     destructif n'existe plus).
- **Phase 3 (promote)** peut démarrer : la sémantique
  "iter_dir auto-suffisant + ml/output/ = dernière itération" est en
  place, il reste à ajouter `prod/current/` et l'opération promote
  qui pousse Supabase + copie iter→prod.
- **Phase 4 (bundle routing)** : tant que `_mirror_iter_outputs`
  est en place, `build_cohort_bundle.py` continue à lire
  `ml/output/`. À retirer quand le bundle pourra cibler
  `iter_dir/...` ou `prod/current/...`.

---

## 2026-05-02 · Phase 3 · Promote + équivalence design_group (Python) — code livré

**Done** :

- **`ml/scripts/promote_iteration.py`** (nouveau, premier script
  CLI sous `scripts/`) :
  - `python -m scripts.promote_iteration <iid> [--force] [--dry-run]
    [--replace-all]`.
  - Valide statut `completed` + verdict ∈ {`baseline`, `better`} (
    bypass via `--force`). Lit `verdict_override || verdict`.
  - Vérifie que `lab/iterations/<iid>/{checkpoints,embeddings,tflite}/`
    sont non vides — fail explicite sinon.
  - `--dry-run` : affiche le diff classes (added / kept /
    absent_in_promotion) et sort sans rien écrire.
  - Lock fichier `prod/.promote.lock` (PID owner) — bloque les
    promotions concurrentes.
  - Backup atomique : déplace `prod/current/` →
    `prod/archive/<previous_iid>-<ISO timestamp>/` avant overwrite.
  - Copie atomique : staging dir `prod/current.new-<ms>/` puis
    `os.replace` → `prod/current/`. Recovery automatique : si la
    copie échoue mid-way, restore depuis l'archive.
  - sha256 de tous les fichiers sous `prod/current/{checkpoints,
    embeddings,tflite}/` + écriture `prod/current/promoted_from.json`
    (`{iteration_id, name, cohort_id, training_run_id,
    benchmark_run_id, verdict, promoted_at, promoted_by, sha256}`).
  - Push Supabase via subprocess `seed_supabase.py --embeddings
    prod/current/embeddings/embeddings_v1.json` (idempotent upsert).
  - `--replace-all` : DELETE Supabase rows
    (`model_classes` + `coin_embeddings`) absentes de la promotion
    avant l'upsert. Par défaut : accumulate (préserve les anciennes
    classes).
- **`ml/eval/equivalence.py`** (nouveau) :
  - `EquivalenceMap` immutable (`eurio_id → design_group_id | None`).
  - `are_equivalent(predicted, ground_truth)` : True si strict match
    OU `design_group_id` identique non-null.
  - `build_equivalence_map()` charge la map depuis Supabase via
    `fetch_coin_refs`. Sérialisation JSON (round-trip) pour la
    parité Android (la table coins est la source de vérité unique,
    mais le JSON peut être pré-baké si besoin).
- **`ml/eval/evaluate_real_photos.py`** :
  - `compute_hits` retourne `(hits_strict, hits_eq)` au lieu de
    `hits` seul. Signature changée — un seul caller (interne).
  - `PhotoResult` gagne `hit_at_eq: dict[int, bool]`.
  - `_aggregate` émet `r_at_1_eq`, `r_at_3_eq`, `r_at_5_eq` à côté
    de `r_at_*` strict. Égales si l'équivalence map n'a pas pu se
    charger.
  - `build_equivalence_map()` appelé best-effort au démarrage du
    bench. Pas de Supabase → log warning, R@k_eq retombe sur strict.
  - `_evaluate_all` accepte `equivalence: EquivalenceMap | None`.
- **Tests** :
  - `ml/tests/test_equivalence.py` : 8 tests verrouillent le
    contrat équivalence (strict, group-share, null-group,
    one-side-null, unknown id, JSON round-trip). **Référence
    Python pour la parité Kotlin.**
  - `ml/tests/test_promote.py` : 7 tests filesystem (atomic copy,
    archive then copy, lock blocks concurrent, lock released on
    success/exception, diff_classes, hash_tree stable). Pas de
    Supabase touché (mockable).
  - Total : 24 tests passent
    (`test_equivalence` 8 + `test_promote` 7 + `test_class_resolver` 3
    + `test_normalize_dispatch` 6).

**Working** :

- Imports propres (`scripts.promote_iteration`,
  `eval.equivalence`, `eval.evaluate_real_photos`).
- `python -m scripts.promote_iteration --help` OK.

**Broken / partial** :

- **Côté Android** : la règle d'équivalence n'est PAS encore
  câblée. L'app cohort-test évalue toujours en strict eurio_id. Un
  agent Android doit livrer la moitié Kotlin avec parité au test
  Python (cf. brief plus bas).
- Pas de promotion réelle exécutée. Premier vrai test = promouvoir
  une itération `completed + verdict=baseline` une fois le code
  Android prêt (sinon l'app cohort-test divergera de la métrique
  bench).
- Pas d'endpoint admin / bouton UI "Promote" dans cette PR. Le doc
  classait ça "optionnel mais recommandé" — à faire plus tard.
- Table Supabase `model_promotions` : pas créée (la doc la disait
  optionnelle). À ajouter quand on voudra l'historique queryable.

**Deviations from phase doc** :

- **`_seed` non retiré du training_runner pour le mode legacy.**
  En mode iteration, déjà skipé depuis phase 2. En mode legacy
  (admin endpoint `/training/sync` qui fait `start_run` direct),
  `_seed` continue de pousser Supabase — c'est tout l'intérêt de
  cet endpoint admin manuel. Le doc envisageait un retrait global ;
  je préserve le legacy pour ne pas casser un flow existant. La
  promotion devient le chemin **principal**, mais pas exclusif.
  Rationnel : R0 (pas de dette) ≠ casser un endpoint qui marche.
- **`r_at_*_eq` pas persisté en DB** (`benchmark_runs` n'a que
  `r_at_1`, `r_at_3`, `r_at_5`). Migration de schéma hors scope
  phase 3. Les valeurs eq sont dans le JSON report
  (`reports/benchmark_*.json`), suffisant pour l'analyse en lab.
  À ajouter en migration séparée si on veut les surfacer dans la UI.
- **Pas de table `model_promotions` créée.** Doc la disait
  optionnelle, je m'aligne. `promoted_from.json` couvre le besoin
  immédiat (savoir ce qui est en prod, depuis quand, par qui).

**Decisions taken** :

- **Option B (équivalence)** validée — confirmé par utilisateur en
  début de session.
- **Accumulate par défaut** : `coin_embeddings` garde les anciennes
  classes lors d'une promotion partielle. `--replace-all` pour
  rebuild from scratch.
- **`prod/archive/` rétention illimitée** : on garde tout (un
  checkpoint = ~30 MB, c'est de la traçabilité bon marché).
- **Verdict strict** : `{baseline, better}` requis sauf `--force`.
  Pas d'état "completed sans verdict" toléré (force-le ou échoue).
- **Lock fichier (pas DB)** : `prod/.promote.lock` simple PID-based.
  Suffisant tant qu'on a un seul opérateur ; à upgrader si
  multi-utilisateur un jour.
- **R@k_eq dans le JSON report uniquement**, pas en DB. Cf.
  Deviations.

**Handoff** :

### Tester promote en local

```bash
cd ml
# 1. Vérifier qu'une itération existe et est promouvable
.venv/bin/python -m scripts.promote_iteration <iid> --dry-run

# 2. Promote (touche Supabase !)
.venv/bin/python -m scripts.promote_iteration <iid>

# 3. Vérifier
ls ml/prod/current/{checkpoints,embeddings,tflite}/
cat ml/prod/current/promoted_from.json
ls ml/prod/archive/   # devrait contenir l'ancienne prod si elle existait
```

### Critères d'acceptance restants à valider

1. ✅ Lab ne pousse plus Supabase (déjà vrai depuis phase 2).
2. ✅ `promote` copie + push Supabase + écrit `promoted_from.json`
   (testé unitairement, pas en réel).
3. ✅ Promotion idempotente (upsert seed_supabase + os.replace).
4. ✅ Promouvoir une vieille itération réécrit prod (testé).
5. ✅ `--dry-run` n'écrit rien (testé).
6. ✅ Verdict invalide → refus sauf `--force`.
7. 🔲 **Règle d'équivalence côté Android : à livrer dans
   l'app-android par un agent dédié** — voir brief ci-dessous.

### Brief pour l'agent Android (à dispatcher)

**Objectif** : implémenter la règle d'équivalence design_group côté
matcher Android, en parité parfaite avec `ml/eval/equivalence.py`.

**Source de vérité Python** : `ml/eval/equivalence.py` +
`ml/tests/test_equivalence.py`. La règle :

```
are_equivalent(predicted, ground_truth) :=
    predicted == ground_truth
    OR (design_group_id(predicted) is not null
        AND design_group_id(predicted) == design_group_id(ground_truth))
```

**Où câbler** :

- App `app-android/src/cohortTest/` : c'est là que les live tests
  tournent et calculent un verdict (correct / incorrect) par rapport
  au ground truth de chaque snap. Aujourd'hui le verdict est strict
  eurio_id (cf. `LiveTestState.kt`, `LiveTestsScreen.kt`,
  `EmbeddingMatcher.kt`).
- Pas besoin de toucher l'app prod (`src/main/`) pour cette phase :
  l'équivalence est un sujet de **mesure** (cohort-test) et de
  **présentation** future. Le matcher principal continue de
  retourner top-1 ; la décision UX "afficher l'eurio_id top-1 ou le
  design_group" reste ouverte pour plus tard.

**Source de la map design_group** : la table `coins` Supabase a
`eurio_id` + `design_group_id`. Deux options :

- **(préférée)** Inclure la map dans le bundle cohort-test. Au
  moment où `build_cohort_bundle.py` construit le ZIP, dump aussi
  `equivalence_map.json` (`{eurio_id: design_group_id|null}`) à
  côté. Côté Android, charger ce JSON au démarrage du test et
  l'utiliser pour le verdict. Avantage : zéro réseau, parité figée
  au build.
- (alternative) Lecture Supabase au boot du cohort-test. Plus
  fragile (réseau), évite la régénération bundle.

**Tests à écrire (Kotlin)** : transposer
`ml/tests/test_equivalence.py` en JUnit. Les 8 cas doivent passer à
l'identique. Tester aussi : verdict d'un live test où prédit ≠
ground truth mais même design_group → "correct".

**À mettre à jour côté script Python** : `build_cohort_bundle.py`
doit dumper l'`equivalence_map.json` dans le bundle (option
préférée).

**Acceptance** : un live test sur la cohort treaty-of-rome (BE/DE/
FR 2007 = même design_group_id) où le matcher prédit DE quand le
GT est BE doit compter comme **correct** côté UI cohort-test
(actuel : compté incorrect). Compteur "R@1 strict" inchangé,
nouveau compteur "R@1 eq" qui les sépare.

### Phase 4 ensuite

Bundle routing : `build_cohort_bundle.py` doit pouvoir cibler soit
`lab/iterations/<iid>/...` soit `prod/current/...` (aujourd'hui :
ml/output/ uniquement). Couplé naturellement à l'option préférée
ci-dessus (inclure equivalence_map.json dans le bundle).

---

## 2026-05-02 · Phase 4 · Bundle routing (lab vs prod) — code livré

**Done** :

- **`ml/scripts/build_cohort_bundle.py`** :
  - Argument `--source {lab,prod}` **required** (pas de défaut —
    force le choix explicite, élimine "wrong source by accident").
  - `--source lab --iteration <iid>` : lit `lab/iterations/<iid>/
    {tflite,embeddings}/`.
  - `--source prod` : lit `prod/current/{tflite,embeddings}/`.
    `--iteration` optionnel ; si absent, auto-résolu via
    `prod/current/promoted_from.json:iteration_id`. Refuse
    explicitement si `prod/current/` n'existe pas (message qui
    pointe vers `scripts.promote_iteration`).
  - Helper `_resolve_source()` extrait, testable.
  - Nouveau `bundle_meta.json` (schema_version=2) ajouté au bundle :
    `{source, cohort_id, cohort_name, iteration_id|null,
    iteration_name, training_run_id, model_version, num_classes,
    class_kind, built_at, sha256}`. C'est le contrat phase 4
    pour l'app cohort-test.
  - `cohort_meta.json` **conservé** pour rétrocompat (Android le
    lisait avant phase 4).
  - Helper `_infer_class_kind()` (majorité, fallback `eurio_id`)
    pour le bundle_meta.
  - Helper `_sha256()` réutilisé du pattern de promote.
  - Drop du check mtime sur `ml/output/eurio_embedder_v1.tflite` —
    obsolète, on ne lit plus ce path en mode iter ou prod.
- **`ml/scripts/promote_prod_assets.py`** (nouveau) :
  - CLI `python -m scripts.promote_prod_assets [--dry-run]`.
  - Copie `prod/current/{tflite/eurio_embedder_v1.tflite,
    embeddings/coin_embeddings.json, tflite/model_meta.json}` →
    `app-android/src/main/assets/{models,data}/`.
  - Refuse clairement si `prod/current/` absent (pointe vers
    `promote_iteration`).
  - Refuse si un fichier source est manquant (prod corrupt).
  - Imprime sha256[:12] de chaque destination pour traçabilité.
  - Première brique d'automatisation du build APK prod (avant :
    copie manuelle depuis `ml/output/`).
- **`app-android/Taskfile.yml`** :
  - `cohort-test:bundle` : invocation passe `--source lab`.
  - `cohort-test:bundle:prod` (nouveau) : `COHORT` requis,
    `--source prod`, OUT séparé pour ne pas écraser un bundle lab
    existant.
  - `prod:assets:promote` (nouveau) : appelle `promote_prod_assets`.
  - `prod:assets:promote-dry` (nouveau) : version dry-run.
- **App Android cohort-test** (sous-agent dédié) :
  - `BundleMeta.kt` (nouveau) : data class + parser + enum `Source`
    + `shortLabel()` pour la UI. Fallback gracieux quand JSON
    absent (bundle pré-phase-4) ou malformé.
  - `CohortTestActivity.kt` : `CohortBundle` gagne
    `bundleMeta: BundleMeta?`, chargé via `BundleMeta.fromAssets`.
  - `LiveTestsScreen.kt` : composable privée `BundleSourceHeader`
    affiche `<cohort_name>` + caption mono `Lab · <name|id8>` /
    `Prod · promu depuis <id8>` / `Prod` / `Bundle legacy`, sub-line
    `model_version · N classes`.
  - `LiveTestLogger.kt` : nouveau paramètre `bundleSource`, ajout
    `"bundle_source": "<lab|prod|legacy>"` sur **chaque ligne**
    JSONL (cohérent avec le format append-only existant).
  - `BundleMetaTest.kt` (nouveau) : 9 tests JUnit verrouillent
    parsing, fallback, schema futur, source manquante/inconnue,
    cohort_id manquant, sentinel legacy. **9 passent.**
- **Tests Python** :
  - `ml/tests/test_build_cohort_bundle.py` (nouveau, 11 tests) :
    `_resolve_source` × 6 cas (lab requires iter, lab missing dir,
    lab returns paths, prod missing, prod uses promoted_from,
    prod explicit override, prod no meta), `_infer_class_kind` × 3,
    `_sha256` stable.
  - `ml/tests/test_promote_prod_assets.py` (nouveau, 4 tests) :
    refuse missing prod, copies tous les artefacts, dry-run no-op,
    partial prod state fails.
  - Total Python : **39 tests passent** (15 nouveaux + 24 phase 3
    précédents).

**Working** :

- Imports propres (`scripts.build_cohort_bundle`,
  `scripts.promote_prod_assets`).
- `python -m scripts.build_cohort_bundle --help` montre la nouvelle
  signature.
- `python -m scripts.promote_prod_assets --dry-run` (nécessite
  `prod/current/` pour aller au bout — refuse proprement sinon).
- Side Android : `./gradlew :app-android:testCohortTestDebugUnitTest
  --tests "com.musubi.eurio.cohorttest.BundleMetaTest"` BUILD
  SUCCESSFUL d'après le sous-agent.

**Broken / partial** :

- Pas de bundle réel généré → l'affichage `BundleSourceHeader` Android
  n'a pas été vérifié sur device. Premier vrai test : promouvoir
  une iter, puis lancer `go-task cohort-test:install COHORT=...
  ITERATION=...` et `go-task cohort-test:bundle:prod COHORT=...`.
- `_mirror_iter_outputs` dans `iteration_runner.py` **toujours en
  place**. Cf. Deviations ci-dessous.

**Deviations from phase doc** :

- **`_mirror_iter_outputs` non retiré.** Le doc disait "à la fin de
  phase 4, plus aucun consommateur ne lit `ml/output/` directement,
  on peut retirer la copie". Faux à la livraison : encore consommé
  par (audit `grep -rn ml/output`) :
    - `ml/scan/eval_real_snaps.py` (manual snap eval, dev workflow)
    - `ml/state/archive.py` (vérifie `output/embeddings_v1.json`
      dans les zips d'archive)
    - défauts CLI : `compute_embeddings.py --output-dir`,
      `export_tflite.py --output-dir`, `validate_export.py
      --tflite`, `eval/visualize.py --output-dir`
    - `ml/Taskfile.yml` (artefacts attendus pour task chaining)
  Ces consommateurs sont legacy/dev — pas critiques pour la pipeline
  iteration, mais retirer le mirror les casserait silencieusement.
  À traiter dans un cleanup séparé (migrer chacun à `--source` ou
  les supprimer s'ils sont morts).
- **`--source` required (pas de défaut `lab`).** Le doc le présente
  comme un flag explicite des deux usages. J'ai préféré le rendre
  obligatoire pour éliminer toute ambiguïté ; existing Taskfile
  invocation mise à jour en conséquence.
- **`promote_prod_assets.py` ajouté hors scope strict de la doc.**
  La doc parle vaguement de "build APK prod appelle
  `build_cohort_bundle --source prod`" — mais le bundle cohort-test
  est distinct des assets prod APK (`src/main/assets/`). J'ai créé
  le script séparé qui fait le pont `prod/current/` → assets prod
  APK. Couvre le critère 5 (build APK prod refuse si pas de
  promotion).

**Decisions taken** :

- **`bundle_meta.json` schema_version=2** (1 = pré-phase-4 sans ce
  fichier). Permet à Android de détecter et dégrader si un vieux
  bundle est chargé.
- **`cohort_meta.json` conservé** dans le bundle pour rétrocompat
  Android (pas de breaking change côté flavor cohort-test). À
  retirer dans une PR séparée quand on aura migré tous les
  consommateurs Android vers `bundle_meta.json`.
- **`bundle_source` per-ligne** dans le JSONL (et non en header) —
  préserve le format append-only et tolère reprise mid-fichier.
  Choix du sous-agent Android.
- **Mirror legacy gardé** : voir Deviations.
- **Auto-résolution `iteration_id` côté `--source prod`** depuis
  `promoted_from.json`. Override possible via `--iteration` explicite
  pour cas avancés (re-bundler la prod avec un iteration_id
  différent).

**Handoff** :

### Workflow complet end-to-end (à valider)

```bash
# 1. Lab : entraîner une iteration, attendre 'completed' + verdict
# 2. Promouvoir vers prod
cd ml
.venv/bin/python -m scripts.promote_iteration <iid> --dry-run
.venv/bin/python -m scripts.promote_iteration <iid>

# 3. Refresh prod APK assets (avant le build APK prod)
go-task -t ../app-android/Taskfile.yml prod:assets:promote
# → app-android/src/main/assets/{models,data}/ à jour

# 4. Bundle cohort-test depuis l'iteration lab
go-task -t ../app-android/Taskfile.yml cohort-test:install \
  COHORT=mix-zone-7-cls ITERATION=<iid>

# 4bis. OU bundle cohort-test depuis la prod (pour A/B)
go-task -t ../app-android/Taskfile.yml cohort-test:bundle:prod \
  COHORT=mix-zone-7-cls
# puis assembleCohortTestDebug à la main
```

### Critères d'acceptance phase 4

1. ✅ `--source prod` produit un bundle figé sur `prod/current/`,
   indépendamment des iterations en cours (testé unitairement).
2. ✅ `--source lab --iteration <iid>` produit un bundle figé sur
   cette iteration précise (testé).
3. ✅ `bundle_meta.json` indique sans ambiguïté la source (testé +
   mirror Kotlin testé côté Android).
4. ✅ App cohort-test affiche la source dans son écran de status
   (header `BundleSourceHeader`, à valider sur device).
5. ✅ Build APK prod refuse si `prod/current/` absent — couvert par
   `promote_prod_assets.py` qui exit 2 avec message qui pointe
   vers `promote_iteration`.

### Cleanup à programmer (post phase 4)

- Migrer `scan/eval_real_snaps.py` à un argument `--source` explicite
  (lab/prod), au lieu de défauter sur `ml/output/`.
- Idem défauts CLI de `compute_embeddings.py` / `export_tflite.py`
  / `validate_export.py` / `visualize.py` — supprimer les défauts
  pointant vers `output/` ou les rendre opt-in via flag.
- Retirer `_mirror_iter_outputs` de `iteration_runner.py` une fois
  les ci-dessus migrés.
- Retirer `cohort_meta.json` du bundle quand l'app cohort-test ne
  le consomme plus.
- Créer la table `model_promotions` Supabase (historique queryable).
- Ajouter colonnes `r_at_*_eq` à `benchmark_runs` si on veut les
  surfacer dans la UI lab.

### Refacto lab-prod **fonctionnellement clos**

Les 4 phases sont livrées. Le pipeline lab→prod est maintenant
explicite, traçable et réversible :

- Phase 1 : label space `eurio_id` strict côté lab.
- Phase 2 : artefacts isolés sous `lab/iterations/<iid>/`.
- Phase 3 : promotion explicite `prod/current/` + équivalence
  design_group.
- Phase 4 : bundle routing source-aware (lab vs prod).

Les chantiers restants sont du **cleanup** (cf. ci-dessus), pas du
refacto structurel.
