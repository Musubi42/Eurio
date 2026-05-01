# Refacto progress log

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

## 2026-05-01 · Phase 0 · Brainstorm + structure docs

**Done** :
- Discussion utilisateur sur les frustrations principales (training
  invisible, page iteration empilée, augmentation à la volée
  résiduelle, runtime invisible).
- Décision : refacto en tiroirs C1/C2 (cohort) + I1/I2/I3/I4
  (iteration), purge des transforms torchvision résiduelles,
  exposition du runtime.
- Création du dossier `docs/training-pipeline/refacto/` :
  - `README.md` (index)
  - `vision.md` (récit complet)
  - `inventory.md` (état actuel codebase, fichiers à toucher)
  - `phase-1-cohort-tiroirs.md`
  - `phase-2-iteration-tiroirs.md`
  - `phase-3-bake-only.md`
  - `phase-4-runtime-backends.md`
  - `phase-5-training-monitor.md`
  - `progress.md` (ce fichier)
- 4 questions tranchées avec l'utilisateur :
  1. C1/C2 : OK
  2. I1/I2/I3/I4 dans cet ordre : OK
  3. Runtime info : bandeau global ET carte I3 : OK
  4. Captures : on garde le wiring actuel (`CaptureSection.vue` +
     CSV + `pull-debug` + sync) : OK

**Working** : doc structure complète et autoportante.

**Broken / partial** : aucun code écrit. C'est volontaire — phases 1-5
prêtes à démarrer.

**Decisions taken** :
- 5 phases au lieu de plus pour ne pas trop fragmenter. Chaque phase
  est un livrable autonome qu'un agent peut faire en une session.
- `progress.md` dans le dossier `refacto/` (pas dans le parent), pour
  bien séparer ce log de celui des sprints originaux.
- Pas de changement de schéma SQLite a priori (sauf nécessité émergeant
  en phase 5).

**Handoff** :
- Démarrer par `phase-1-cohort-tiroirs.md`. Pré-requis listés dedans.
- Aucun blocage.
- À surveiller : la phase 2 dépend de la phase 1 (composant
  `DrawerSection.vue` réutilisé). Les phases 3, 4, 5 peuvent en
  théorie tourner en parallèle de la phase 2 mais on les fait
  séquentiellement pour garder une seule rebase.

---

## 2026-05-01 · Phase 1 · Cohort en 2 tiroirs (C1/C2)

**Done** :
- Backend : `GET /lab/cohorts/{id}/progress` ajouté dans
  `ml/api/lab_routes.py` (avant `update_cohort`). Helpers
  `_has_obverse`, `_drawer_state_c1`, `_drawer_state_c2`. C1 stat
  `ml/datasets/<nid>/obverse.{jpg,png}` ; C2 réutilise
  `_coin_capture_status` + `CAPTURE_STEPS`.
- Front types : `DrawerState`, `CohortProgress{C1,C2}` ajoutés à
  `features/lab/types.ts`.
- API/queries : `fetchCohortProgress` dans `useLabApi.ts`,
  `useCohortProgressQuery` (refetchInterval 5s, staleTime 2s) dans
  `useLabQueries.ts`. Invalidation ajoutée sur
  `useAddCoinsMutation`, `useRemoveCoinMutation`,
  `useSyncCapturesMutation`.
- Composants : `DrawerSection.vue` (badge état coloré + collapse
  animation, support locked/lockReason), `CohortDrawerC1.vue`
  (liste coins + encart orange `missing_obverse` lien `/coins/<eid>`),
  `CohortDrawerC2.vue` (wrappe `CaptureSection`, locked tant que C1
  pas ready).
- `CohortDetailPage.vue` : §1/§2 remplacées par les 2 tiroirs ;
  bouton "Nouvelle itération" gated sur `c2.state === 'ready'` avec
  tooltip explicite quand pas prêt.

**Working** :
- `pnpm tsc --noEmit` clean.
- `pnpm exec vite build` clean (CohortDetailPage ~32 KB).
- `curl /lab/cohorts/green-v1/progress` retourne
  `{c1:ready/1 coin/[], c2:ready/6/1/0/0/[]}`.
- `curl /lab/cohorts/mix-zone-17/progress` retourne
  `{c1:ready/16/[], c2:ready/6/16/0/0/[]}`.

**Broken / partial** : aucun cohort `partial` n'existe en l'état
pour valider visuellement le badge orange. Vérification manuelle
restante en navigateur sur cohort draft incomplète si besoin.

**Deviations from phase doc** : aucune. La doc ne spécifiait pas
le wording exact du badge — choisi `Empty/Partial/Ready/Running`.
La constante `CAPTURE_STEPS` côté serveur a 6 steps mais inclut
`daylight_plain`, `bright_textured`, `close_plain` (pas le tuple
de la doc qui mentionnait `bright_perturbed`/`dim_perturbed`/
`tilt_perturbed`). Le code lit la constante runtime, donc statu quo.

**Decisions taken** :
- `DrawerSection` ouvre par défaut quand `state ∈
  {empty,partial,running}` ; `ready` est collapsé pour réduire le
  bruit visuel. Override possible via `defaultOpen` ; toggle user
  est sticky (pas réécrit par les changements d'état).
- `locked` désactive juste le toggle + dim 0.65 + tooltip via
  `alert` au click. Pas de toast lib, statu quo.
- Pas de hover sur "Nouvelle itération" — la propriété cursor
  `not-allowed` suffit, le tooltip natif explique.

**Handoff** :
- Phase 2 peut démarrer ; `DrawerSection.vue` est exporté et prêt
  à servir pour I1/I2/I3/I4.
- Si on veut un visuel "partial" : créer une cohort draft avec un
  `eurio_id` sans `obverse.jpg` sur disque pour voir l'encart
  orange dans C1.

---

## 2026-05-01 · Phase 2 · Iteration en 4 tiroirs (I1/I2/I3/I4)

**Done** :
- Backend :
  - `GET /lab/cohorts/{cid}/iterations/{iid}/progress` ajouté
    (helpers `_i1_state`/`_i2_state`/`_i3_state` + `_i4_substate_*`
    + `_i4_aggregate` + `_iteration_progress`).
  - `POST /lab/cohorts/{cid}/iterations/{iid}/bake` (idempotent —
    appelle `generate_for_iteration` sans clear ; valide
    status==pending et recipe_id non null).
  - `_iteration_with_run_metrics` enrichi : champ `recipe_name` joint
    via `store.get_recipe()`.
  - Pas touché à `IterationRunner.launch_training` : il enforce déjà
    "fail-if-not-baked" (ligne 198).
- Front :
  - Types : `IterationDetail.recipe_name`, `IterationProgress*`,
    `BakeResult` ajoutés à `types.ts`.
  - `useLabApi.ts` : `fetchIterationProgress`,
    `bakeIterationAugmentations`.
  - `useLabQueries.ts` : `LAB_KEYS.iterationProgress`,
    `useIterationProgressQuery` (poll 2s pendant
    training/benchmarking, 5s sinon), `useBakeIterationMutation`.
    Invalidation iterationProgress ajoutée à regenerate, stop,
    update, launch.
  - 4 nouveaux composants : `IterationDrawerI1.vue` (recipe + variant
    count, RecipeConfigurator inline en pending uniquement),
    `IterationDrawerI2.vue` (Bake/Régénérer + AugmentationsGallery +
    encart orange coins incomplets, summary "obverse uniquement"
    literal), `IterationDrawerI3.vue` (coquille : pending →
    bouton Lancer + placeholder runtime ; running → placeholder
    monitor ; completed → recap durée/v/recall ; failed → Retry),
    `IterationDrawerI4.vue` (méta + 4 sous-`DrawerSection` imbriquées
    qui wrappent `BenchmarkSummary`+`PerConditionTable`,
    `AugVsRealSection`, `BuildTestAppSection`, `LiveTestsSection`).
  - `IterationDetailPage.vue` rewrite complet : header inchangé,
    bandeaux running/failed, 4 tiroirs gated par `iN.state==='ready'`,
    sidebar Notes/verdict_override conservée. Polling local
    setInterval supprimé (remplacé par useIterationProgressQuery).

**Working** :
- `pnpm tsc --noEmit` clean.
- `pnpm exec vite build` clean (IterationDetailPage 61 KB).
- `curl .../iterations/8597c43b8233/progress` (failed iter) →
  `i1=empty, i2=empty, i3=partial+failure_reason, i4=empty`.
- `curl .../iterations/da2a76432dfc/progress` (pending, baked) →
  `i1=empty, i2=ready 144/144, i3=empty, i4=empty`.
- `curl -X POST .../bake` valide `status` et `recipe_id` (409 +
  400 testés).
- `recipe_name` apparaît dans la réponse iteration list (vérifié sur
  cohort `mix-zone-17` : iter `ok` → `recipe_name='test-3'`).

**Broken / partial** :
- I3 reste une coquille : carte runtime + monitor live arrivent en
  phase 4/5.
- Pas de "running" visuel actuellement testable (aucune training en
  cours sur le serveur).

**Deviations from phase doc** :
- Pas de pré-vérif additionnelle dans `launch-training` : le runner
  enforce déjà l'invariant (`list_for_iteration` + comparaison à
  `variant_count`). Le piège connu de la doc est déjà résolu en code.
- `IterationDrawerI3` retire le bandeau "tflite manquant"
  contextuel — c'est le rôle de I4c désormais.

**Decisions taken** :
- I4 utilise des `DrawerSection` imbriquées (pas un layout custom).
  Conséquence : numérotation `I4a/I4b/I4c/I4d` apparaît dans les
  badges. Plus lisible, et zéro nouvelle primitive.
- `IterationDrawerI1` charge sa propre `fetchRecipes()` côté
  composant pour rester autonome (la page maître ne porte plus de
  state recipes).
- `useIterationProgressQuery` watch refresh full iteration via
  `reload()` quand `progress.i3.status` change — garantit que les
  metrics affichées (training_summary, benchmark_summary, verdict)
  rafraîchissent quand l'iteration termine sans manual reload.

**Handoff** :
- Phase 3 (purge transforms torchvision résiduels dans
  `train_embedder.py`) peut démarrer indépendamment.
- Phase 4 (runtime backends) : remplacer le placeholder dans
  `IterationDrawerI3.vue` par `<RuntimeCard>` quand l'endpoint
  `/lab/runner/runtime-info` existera.
- Phase 5 (training monitor) : remplacer le bandeau "monitor live
  arrive en phase 5" dans le même tiroir par `<TrainingMonitor>`.
- Le composant `DrawerSection.vue` supporte déjà le state `running`
  (badge bleu) — pas de changement nécessaire pour les phases
  suivantes.

---

## 2026-05-01 · Phase 3 · Bake = seule source d'augmentation

**Done** :
- `train_embedder.py` :
  - `get_train_transforms()` renommée en `get_legacy_train_transforms()`
    (legacy 9-transform compose : Resize+RandomRotation+RandomAffine+
    RandomPerspective+ColorJitter+GaussianBlur+ToTensor+Normalize+
    RandomErasing). Conservée pour le path non-prebaked.
  - Nouvelle `get_prebaked_transforms()` : Resize(224,224) + ToTensor
    + Normalize ImageNet. Aucune randomness.
  - `_build_train_dataset()` dispatch : prebaked → `get_prebaked_transforms`
    avec `recipe_override={"layers": []}` ; legacy → `get_legacy_train_transforms`.
  - Helpers `_log_runtime_contract(args, device, n_train, n_classes)` et
    `_log_tensor_check(model)` ajoutés. Appelés dans `train_classifier`,
    `train_embedder` (triplet), `train_arcface` juste après `model.to(device)`.
- `iteration_augmentations.py` :
  - Écrit `_manifest.json` par coin à côté des `sample_NNN.jpg`.
    Champs : iteration_id, eurio_id, numista_id, recipe_id, seed,
    samples=[{file, source}], generated_at.
  - Manifest réécrit à chaque appel (idempotent + reflète le
    snapshot courant), valable pour les baked-skip et pour les
    fresh-bake.
- `iteration_runner.py:_launch_training` : pré-vérif "I2 incomplete"
  via `list_for_iteration` + comparaison à `variant_count`. Refuse
  avec `RuntimeError` explicite si un coin manque.
- `augmentations/recipes.py` : référence dans la docstring mise à
  jour (`get_legacy_train_transforms`).

**Working** :
- `python -c "from training.train_embedder import get_prebaked_transforms; print(...)"`
  affiche bien Compose(Resize, ToTensor, Normalize) — 3 étapes, zéro
  random.
- Bake trigger sur iteration `da2a76432dfc` (cohort `mix-zone-17`,
  16 coins déjà bakés) produit un `_manifest.json` valide listant
  9 samples × source=`obverse.jpg`.
- Tous les fichiers Python parsent sans erreur de syntaxe.

**Broken / partial** :
- Pas testé un training réel end-to-end (pas de GPU dispo + iteration
  pending suffisamment isolée). La ligne `RUNTIME {...}` et
  `TENSOR_CHECK ...` apparaîtront au prochain training lancé via le
  Lab.
- Manifests rétroactivement créés uniquement quand un bake est
  re-déclenché : iterations historiques sans manifest restent
  valides (pas de migration). Doc le précise déjà.

**Deviations from phase doc** :
- Manifest écrit même sur le path "skip" (idempotent re-bake) — la
  doc suggérait juste "à la fin de la boucle" sans préciser pour
  les coins déjà complets. Choix : toujours écrire pour avoir un
  audit trail uniforme. Coût négligeable (~quelques KB).
- Pas d'endpoint `GET .../bake-manifest/<eurio_id>` (F2 hors-scope
  v1 confirmé par la doc). Le manifest est lisible sur disque.

**Decisions taken** :
- `_log_runtime_contract` ajouté aux 3 modes (classify, embed,
  arcface) au lieu de seulement arcface : coût quasi-nul, et c'est
  le bon endroit pour s'assurer qu'on documente le contrat partout
  (un futur bug "j'ai lancé classify et il y a encore des aug
  random" sera détectable depuis le log).
- `_log_tensor_check` placé juste après `model.to(device)` (avant
  l'optimizer setup) : si le `.to(device)` foire silencieusement,
  on le voit avant de perdre des cycles.

**Handoff** :
- Phase 4 (runtime backends) : `_log_runtime_contract` émet déjà
  `device` et `torch_version`. Le futur module `ml/training/runtime.py`
  pourra réutiliser le même JSON shape ; idéalement le bandeau
  global `/lab` réutilise les helpers existants.
- Phase 5 (training monitor) : le préfixe `RUNTIME ` est le grep
  target — le parseur peut chercher `^RUNTIME (.+)$` dans le tail
  in-memory de `TrainingRunner._train`. Idem `TENSOR_CHECK` pour
  confirmer device.

---

## 2026-05-01 · Phase 4 · Runtime backends visibles

**Done** :
- Backend :
  - Nouveau module `ml/training/runtime.py` : `RuntimeInfo` dataclass
    (host_os, arch, cpu_brand, torch_version, backend, device,
    num_cuda_devices, gpu_name, cuda_version, dataloader_workers,
    hint), `detect()` mémo via `lru_cache(1)`, `to_dict()`. CPU brand
    via `sysctl` (darwin) ou `/proc/cpuinfo` (linux), fallback
    `platform.processor()`. Backend dispatch cuda > mps > cpu. Hint
    composé en clair selon le backend. `detect()` ne raise pas (try/
    except → fallback cpu+hint d'erreur).
  - `GET /lab/runner/runtime-info` ajouté à côté de `/runner/status`.
  - `train_embedder.py:_log_runtime_contract` enrichi : nested
    `runtime` dict (asdict de RuntimeInfo) dans la ligne `RUNTIME {...}`
    pour que phase 5 puisse parser un seul payload self-contained.
- Front :
  - Type `RuntimeInfo` dans `types.ts`.
  - `fetchRuntimeInfo` dans `useLabApi.ts`,
    `useRuntimeInfoQuery` (staleTime 1h) dans `useLabQueries.ts`.
  - Composant `RuntimeBadge.vue` (compact pill | full card) avec
    couleur cuda=green / mps=warning / cpu=danger, icône Zap (cuda)
    / Cpu (autres). Compact affiche `device · hint` ; full liste
    OS, CPU, torch, backend, device, GPU, CUDA, workers + hint.
  - Bandeau global ajouté à `LabHomePage.vue` à gauche de l'indicateur
    "API ML prête".
  - `IterationDrawerI3.vue` : placeholder phase-4 remplacé par
    `<RuntimeBadge>` full card en mode pending, sous le texte
    "Le training tournera sur ce matos…".

**Working** :
- `curl /lab/runner/runtime-info` (Mac M3) →
  `{"host_os":"darwin","arch":"arm64","cpu_brand":"Apple M3",
    "torch_version":"2.11.0","backend":"mps","device":"mps:0",
    "num_cuda_devices":0,"gpu_name":null,"cuda_version":null,
    "dataloader_workers":0,"hint":"Apple Silicon (mps) — slower,
    OK for iterating"}`.
- `pnpm tsc --noEmit` + `pnpm exec vite build` clean.
- Sur PC + 1080 Ti (à valider lors du prochain switch de machine), le
  même endpoint retournera `backend:"cuda"`, `gpu_name:"NVIDIA
  GeForce GTX 1080 Ti"`, `cuda_version:"12.x"`, `dataloader_workers:4`.

**Broken / partial** :
- Pas testé sur la machine PC/CUDA (Mac M3 only ce moment). Le code
  utilise `torch.cuda.is_available()` + `torch.cuda.get_device_name(0)`,
  comportement standard.
- Pas implémenté le piège connu "estimation ETA" — hors-scope v1.

**Deviations from phase doc** :
- Le hint pour mps dit "Apple Silicon (mps) — slower, OK for
  iterating" au lieu de "Apple M3 (mps) — slower…" : on ne hardcode
  pas la génération du chip dans le hint, le `cpu_brand` la porte
  déjà.
- `_log_runtime_contract` n'a pas remplacé l'ancien JSON (phase 3)
  par celui de runtime.py : il l'embarque comme champ `runtime`
  imbriqué. Évite de péter le contrat phase 3 (mode/dataset_size/
  num_classes/epochs/batch_size restent au top-level pour phase 5).
- Pas modifié `get_device(args.device)` ni `training_runner._train`
  (B4 marqué optionnel par la doc) — le subprocess log déjà sa
  config runtime via `_log_runtime_contract`, et `auto` fait le bon
  choix.

**Decisions taken** :
- `RuntimeBadge` factorise compact + full dans un seul fichier (vs
  deux composants `RuntimeBadge` / `RuntimeCard` annoncés dans
  l'inventory). Moins de surface, comportement piloté par 1 prop.
- Couleur backend choisie : cuda=success (rapide), mps=warning
  (utilisable mais lent), cpu=danger (pathologique). Communique
  l'urgence d'un fallback inattendu sans texte.
- `lru_cache(1)` sur `detect()` : torch lazy-load + sysctl coûtent
  ~10ms, le bandeau global se rafraîchit quand on rentre sur `/lab`,
  pas besoin de payer ce coût à chaque polling.

**Handoff** :
- Phase 5 (training monitor) : `runtime` est dispo dans la ligne
  `RUNTIME {...}` que le subprocess émet. Le parseur live pourra
  surfacer le device confirmé pendant le run sans re-fetch.
- Si on veut afficher la mémoire GPU libre côté carte : ajouter
  `mem_free_mb`/`mem_total_mb` à `RuntimeInfo` via
  `torch.cuda.mem_get_info(0)` et invalider la query toutes les
  ~30s. Hors-scope présent.

---

## 2026-05-01 · Phase 5 · Training monitor live

**Done** :
- Backend :
  - `train_embedder.py` (mode arcface) :
    - Imports `time` ; constante `PROGRESS_DIR = ml/state/training_progress`.
    - Helpers `_iso_now_utc()`, `_write_progress(iid, payload)` (atomic
      via `tmp.replace(final)`).
    - Nouvel arg `--iteration-id` (défaut None → `_write_progress` no-op).
    - Au boot du training : payload initial avec `phase=training`,
      `epoch_current=0`, started_at, device, augmentations_runtime.
    - À chaque epoch : payload mis à jour (epoch_current, loss_current,
      loss_best, elapsed_seconds, eta_seconds dérivé de la moyenne
      des epochs déjà finies).
    - Fin du training : `phase=training_done`.
  - `training_runner.py:_train` : ajoute `--iteration-id <iid>` au cmd
    quand `cfg["iteration_id"]` est set.
  - `iteration_runner.py` :
    - Import `json`, constante `PROGRESS_DIR`, helper
      `_set_progress_phase(iteration_id, phase, **extra)` (merge
      sur le fichier existant pour ne pas perdre les métriques
      écrites par le subprocess).
    - `_launch_training` : ajoute `config["iteration_id"] = iteration.id`.
    - `_chain_steps` : appels `_set_progress_phase` aux transitions
      `bake` (avant launch) → `export` (entre training et tflite) →
      `benchmark` (entre tflite et benchmark) → `done` (après
      finalize).
    - `_fail` : écrit `phase=failed` avec champ `error`.
  - `training_runner.py` : nouvelle méthode `tail_logs(n=30)`
    thread-safe.
  - `iteration_runner.py` : property publique `training_runner` pour
    exposer le runner aux routes.
  - `lab_routes.py` : nouvel endpoint
    `GET /lab/runner/training-progress/{iid}` qui :
    - Lit `ml/state/training_progress/<iid>.json` si présent (sinon
      retourne `phase=unknown`).
    - Concatène `log_tail = _get_runner().training_runner.tail_logs(30)`.
- Front :
  - Types : `TrainingProgressPhase` (union 8 valeurs incluant
    `unknown`), `TrainingProgress`.
  - `useLabApi.ts` : `fetchTrainingProgress(iid)`.
  - `useLabQueries.ts` : `useTrainingProgressQuery(iid, status)` —
    enabled + refetchInterval 2 s seulement quand status ∈
    {training, benchmarking}.
  - Nouveau composant `TrainingMonitor.vue` :
    - Header : phase courante (label en français) + bouton Stopper
      (réutilise `useStopIterationMutation`).
    - Bloc runtime confirmé : `device` + couleur sur
      `augmentations_runtime` (vert si "disabled", warning si
      "legacy_compose").
    - Barre de progression epoch (avec %), loss courante / best,
      temps écoulé / ETA (formattés en s/m/h).
    - Tail logs dans `<details>` : `<pre>` scrollable monospace,
      30 dernières lignes.
    - Bandeau d'erreur si `phase === 'failed'`.
  - `IterationDrawerI3.vue` : placeholder phase-5 remplacé par
    `<TrainingMonitor>` quand `iteration.status ∈ {training, benchmarking}`.

**Working** :
- `python -c "import ast; ..."` clean sur les 4 fichiers Python touchés.
- `curl /lab/runner/training-progress/<inexistant>` → `{schema_version:1,
   iteration_id:<id>, phase:"unknown", log_tail:[]}`.
- `pnpm tsc --noEmit` + `pnpm exec vite build` clean
   (IterationDetailPage 66 KB, +5 KB vs phase 4 — TrainingMonitor + types).

**Broken / partial** :
- Pas testé un training réel end-to-end pendant la session (Mac M3,
  no GPU dispo + aucun training en vol). Le wiring complet a été
  validé statiquement (parsing + endpoint vide + build front).
  Premier training réel = test live.
- Mode `embed` (triplet) n'écrit PAS de progress JSON. Statu quo
  `arcface` est le mode utilisé par le runner (`DEFAULT_CONFIG.mode
  = "arcface"`). Si un jour on switch vers triplet, dupliquer le
  bloc.
- Pas de **graphe loss curve** ni de **persistence du log_tail** —
  hors-scope confirmés par la doc.

**Deviations from phase doc** :
- Bouton Stop déplacé dans le header de `TrainingMonitor` au lieu
  d'être un bouton à part dans I3 : moins de doublon visuel (le
  monitor remplace toute la zone running de I3).
- Fichier progress n'est PAS supprimé en fin de chain — au contraire
  on le marque `phase=done` (resp. `failed`). Si l'iteration est
  ultérieurement supprimée, le sprint-5 GC ne nettoie pas ce dir
  (pas dans son périmètre). À surveiller si le dir grossit (1 fichier
  ~500 octets par iteration).
- `_set_progress_phase` n'invalide pas la query côté front — c'est
  le polling 2 s qui voit le changement. Pas de race grave (si
  l'utilisateur était sur "training" et la phase passe à "export",
  il verra l'update dans la prochaine seconde).

**Decisions taken** :
- `phase=unknown` retourné quand le fichier n'existe pas (au lieu
  de 404) : permet au monitor de rester monté sans gérer un
  spinner d'erreur, c'est la situation entre "user clic Lancer"
  et "le subprocess écrit le premier payload" (~quelques ms à 1 s).
- `TrainingMonitor` montre TOUJOURS le bloc runtime + tail, pas
  seulement la progress bar. Les phases hors training (bake,
  export, benchmark) gardent un visuel utile (spinner + label).
- ETA calculée côté Python via `mean_epoch_s * (epochs - epoch)`.
  Simple linéaire, ignore le freeze→unfreeze de l'epoch
  `freeze_epochs+1` qui change la vitesse. Acceptable v1.

**Handoff** :
- Le test live consiste à lancer un training depuis le front :
  - Cohort `green-v1` (1 coin déjà ready C1+C2) ou `mix-zone-17`
    (16 coins) → créer une iteration avec recipe `test-3` →
    "Générer" en I2 → "Lancer training" en I3.
  - Vérifier que le monitor affiche : phase=bake → training avec
    epoch_current qui s'incrémente toutes les ~secondes →
    training_done → export → benchmark → done.
  - Vérifier que `device=mps:0` et `augmentations_runtime=disabled`.
- Si tout marche, on peut considérer le refacto entièrement livré.

---
