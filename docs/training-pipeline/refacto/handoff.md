# Refacto training-pipeline — handoff

> Synthèse à la livraison des 5 phases (2026-05-01). Lis ce document avant
> de toucher la pipeline ou avant de partir en review. Les détails
> phase-par-phase sont dans `progress.md` ; les specs initiales dans
> `phase-N-*.md`.

## Vue d'ensemble

Le refacto remplit 4 promesses :

1. **Le flow Cohort → Iteration → Training est gated par contrat.**
   Tu ne peux pas lancer une iteration tant que la cohort n'a pas ses
   captures, et tu ne peux pas lancer un training tant que les
   augmentations ne sont pas bakées.
2. **L'augmentation à la volée est purgée du training prebaked.** Le
   modèle ne voit que ce que le bake a écrit. Audit trail dans
   `_manifest.json` par coin.
3. **Le runtime est visible avant le run** (bandeau global +
   carte I3) et **confirmé pendant le run** (monitor live).
4. **Le training stream son state** (epoch, loss, ETA, log tail) à
   2 s de cadence — plus de spinner aveugle.

## Ce qui est bien codé

### Backend

| Endroit | Pourquoi c'est solide |
|---|---|
| `ml/api/lab_routes.py` `cohort_progress` / `iteration_progress` | États dérivés du disque + DB, jamais de drapeau déclaratif. Le polling front n'a aucune chance de mentir. |
| Helpers `_drawer_state_*`, `_i*_state`, `_i4_substate_*`, `_i4_aggregate` | Logique d'agrégation isolée, testable à l'unité plus tard sans toucher l'endpoint. |
| `ml/training/runtime.py` | Module unique, cache `lru_cache(1)`, `detect()` ne raise pas (fallback CPU + hint d'erreur). Réutilisable depuis tout l'écosystème ML, pas seulement la route Lab. |
| `_log_runtime_contract` (train_embedder) | JSON ligne unique préfixée `RUNTIME ` — grep target stable. Embarque le runtime info complet ; la phase 5 ré-utilise la même donnée sans re-fetch. |
| `_write_progress` atomique (`tmp.replace(final)`) | Le front peut lire à n'importe quel moment sans torn-write. |
| `_set_progress_phase` côté runner | Merge sur le payload existant — la transition `bake → training → export` ne perd jamais les métriques écrites par le subprocess. |
| `_launch_training` belt-and-suspenders | Refuse les bakes incomplets dès `_launch_training`, en plus du check public dans `IterationRunner.launch_training`. Les scripts/tests internes ne peuvent pas court-circuiter. |
| `iteration_augmentations._manifest.json` | Audit trail explicite "obverse uniquement" — vérifiable à la main, pas une promesse de code. |
| `tail_logs(n)` thread-safe sur `TrainingRunner` | Verrou réutilisé du writer, garantit pas de race. |

### Front

| Endroit | Pourquoi c'est solide |
|---|---|
| `DrawerSection.vue` | Primitive unique, 4 états visuels (empty/partial/ready/running) + locked. Réutilisée 2 niveaux (cohort + iteration + sous-tiroirs I4). Header sticky, body collapse, tooltip lockReason. |
| Polling adaptatif (TanStack Query) | `refetchInterval` calculé depuis le status réel (training/benchmarking → 2 s, sinon 5 s ou off). Aucun setInterval custom dans les composants. |
| Invalidation déclarative | Mutations (attach/detach/sync/regenerate/launch/stop) invalident toujours `progress` + `iterationProgress` — pas de "refresh manuel" qui traîne. |
| Watcher status flip | `IterationDetailPage` watch `progress.i3.status` ; quand running → completed, déclenche un reload pour rafraîchir `training_summary`/`benchmark_summary` côté UI. |
| `RuntimeBadge.vue` | Compact pill + full card dans un seul fichier, comportement piloté par 1 prop. Couleur backend (cuda=green, mps=warning, cpu=danger) communique l'urgence d'un fallback inattendu. |
| `TrainingMonitor.vue` | Garde un visuel utile pour toutes les phases (bake / training / export / benchmark / failed), pas juste pour training. |

## Manquements & TODO

### Pas testé en condition réelle (à faire en next session)

- **Aucun training réel n'a tourné** pendant la session (Mac M3, batterie
  basse, pas de GPU). Tout le wiring a été validé statiquement (syntax,
  build, endpoints, payloads vides). Le **premier training de
  validation** doit produire :
  - Une ligne `RUNTIME {...}` parsable au boot du subprocess.
  - Un fichier `ml/state/training_progress/<iid>.json` qui s'incrémente
    epoch par epoch.
  - Un `TrainingMonitor` qui affiche epoch + loss + ETA + log_tail
    sans rafraîchissement manuel.
  - `augmentations_runtime: "disabled"` confirmé.
  - Transition visible bake → training → export → benchmark → done.

- **Stop pendant un training** : pas vérifié visuellement. Le SIGTERM
  coopératif est en place (Sprint 1) ; phase 5 expose juste le bouton
  dans le monitor.

- **PC + 1080 Ti** : runtime detection écrit pour cuda mais jamais
  exécuté ici. Quand tu basculeras de machine, vérifier que
  `gpu_name`, `cuda_version`, `dataloader_workers=4` apparaissent dans
  le payload `/runtime-info`.

### Hors-scope volontaires (par les specs)

- Pas de **graphe loss curve** dans le monitor (juste valeur courante
  + best). La table `epochs` du store reste consultable post-run.
- Pas de **persistence du log tail** entre restarts API (in-memory
  uniquement). Le passé reste accessible via `TrainingRunner.load_logs`
  qui lit l'archive post-run.
- Pas de **WebSocket / SSE** : polling HTTP suffit pour 1 user.
- Pas de **estimation ETA pré-lancement** basée sur l'historique des
  runs.
- Pas de **détection de mémoire GPU libre** (`torch.cuda.mem_get_info`).
- Pas de **switch runtime** dans l'UI (force CPU). Si besoin, passer
  `--device cpu` à la main au subprocess.
- Pas de **A/B comparaison side-by-side** entre iterations (statu quo
  via la trajectory chart).
- Pas de **migration des iterations existantes** : les augmentations
  bakées avant phase 3 restent valides, mais leur `_manifest.json` est
  généré seulement quand on re-déclenche un bake (idempotent).
- Pas de **modification du mode `embed` (triplet)** : il garde l'ancien
  comportement (legacy compose, aucun progress JSON). Si on revient à
  triplet, dupliquer le bloc `_write_progress` du `train_arcface`.

### Petites dettes acceptées

- **Le `_set_progress_phase` côté runner ne notifie pas le front.** Le
  polling 2 s détecte la transition à la prochaine seconde ; latence
  visible mais inférieure à 1 query interval.
- **Le fichier `training_progress/<iid>.json` n'est jamais supprimé.**
  Quand l'iteration est gc'ée par le sprint-5 cleanup, ce fichier
  reste. ~500 octets/iteration, négligeable mais à surveiller si on
  passe à des centaines de runs.
- **`_iteration_progress` lit le disque à chaque request** (poll 2-5 s).
  Pour 16 coins × N=4-5 endpoints, c'est ~50 stat() par seconde au
  pire — non bloquant. Si on grossit, ajouter un cache invalidé sur
  les mutations bake/launch.
- **ETA linéaire** ignore le saut de vitesse à `freeze_epochs + 1`
  (unfreeze backbone). L'utilisateur verra l'ETA se ré-équilibrer
  après quelques epochs unfrozen.
- **Bouton Stop apparaît à 2 endroits** quand un training tourne :
  header de la page (sticky) ET `TrainingMonitor` interne. Doublon
  cosmétique, pas un bug.

## Deltas vs specs initiales

Listés ici les écarts conscients entre les 5 phase docs et le livré.

### Phase 1
- Wording du badge état choisi `Empty/Partial/Ready/Running` (pas
  spécifié par la doc).
- `CAPTURE_STEPS` côté serveur a 6 entrées (`bright_plain`,
  `dim_plain`, `daylight_plain`, `bright_textured`, `tilt_plain`,
  `close_plain`) au lieu du tuple suggéré par la doc
  (`bright_perturbed` etc.). Le code lit la constante runtime, statu
  quo.

### Phase 2
- Pas de pré-vérif additionnelle ajoutée à `launch-training` : le
  runner enforce déjà l'invariant ligne 198. Phase 3 a renforcé ça
  par un check redondant côté `_launch_training` interne.
- I4 utilise des `<DrawerSection>` imbriquées avec numérotation
  visible `I4a/I4b/I4c/I4d` au lieu d'un layout custom. Plus lisible.

### Phase 3
- Manifest écrit MÊME quand le bake skip (idempotent) — la doc
  suggérait juste "à la fin de la boucle". Choix : audit trail
  uniforme.
- Pas d'endpoint `GET .../bake-manifest/<eurio_id>` (F2 hors-scope
  v1 confirmé).

### Phase 4
- Hint pour mps : "Apple Silicon (mps) — slower, OK for iterating"
  au lieu de "Apple M3" hardcodé. La génération du chip est dans
  `cpu_brand`.
- `_log_runtime_contract` embarque le runtime dict imbriqué (`runtime`
  field) au lieu de remplacer le payload phase 3. Compat ascendante.
- Pas modifié `get_device(args.device)` (B4 marqué optionnel).
- Composant `RuntimeBadge` factorise compact + full au lieu de deux
  composants séparés (`RuntimeBadge` + `RuntimeCard` annoncés en
  inventory).

### Phase 5
- Bouton Stop dans le header du `TrainingMonitor` au lieu d'un bouton
  séparé dans I3.
- Fichier progress conservé (`phase=done` ou `failed`) au lieu d'être
  supprimé.
- Mode `embed` (triplet) non instrumenté (statu quo arcface).

## Surface de tests recommandée

Pour valider le refacto en bloc :

1. **Smoke flow complet** sur cohort `green-v1` (1 coin) :
   - Vérifier le bandeau RuntimeBadge sur `/lab`.
   - Aller sur la cohort, vérifier C1=ready, C2=ready (1 coin × 6
     captures déjà sync'd).
   - Créer iteration → I1 sélectionner recipe `test-3` → save →
     I2 "Générer" → bake instantané → I3 "Lancer training".
   - Pendant le run : monitor affiche bake → training (epoch
     incrémente) → training_done → export → benchmark → done.
   - I3 passe en ready avec recap, I4 devient interactif.
2. **Stop flow** : pendant le training, cliquer Stopper. Iteration
   passe à failed avec phase=failed dans le payload progress.
3. **Inspection manifest** : `cat
   ml/datasets/<nid>/augmentations/<iid>/_manifest.json` montre tous
   les samples avec `source: "obverse.jpg"`.
4. **Inspection log subprocess** : grep `RUNTIME` et `TENSOR_CHECK`
   dans le log file de l'iteration. Doit avoir
   `augmentations_runtime: "disabled"` et `model.device=mps:0`.

## Pour la suite

Si on continue sur la pipeline :

- **Phase 6 candidate** (pas écrite) : graphe loss curve dans le
  monitor + replay post-run depuis la table `epochs`. Une vraie courbe
  est la suite logique.
- **Phase 7 candidate** : A/B compare de 2 iterations terminées
  (delta R@1 par axe + galerie aug-vs-real côte à côte).
- **Endpoint manifest** : si on veut afficher la source par sample
  dans I2, exposer `GET .../iterations/<iid>/bake-manifest/<eurio_id>`
  qui lit le `_manifest.json` correspondant. ~10 lignes.
- **GC du progress dir** : ajouter une purge dans le sprint-5
  cleanup quand une iteration est supprimée.
- **Mode triplet** : si on revient au `train_embedder` mode embed,
  porter le `_write_progress` (5 minutes de copier-coller).
