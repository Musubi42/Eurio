# Session kickoff — Cohort capture flow (admin refactor)

> Prompt à coller dans une nouvelle session Claude Code. Self-contained — toutes les décisions ont été prises lors d'une discussion préalable. La mission de la session : produire d'abord un design doc validé, **puis** implémenter par étapes.

---

## Mission de cette session

Construire le pont manquant entre :
- les **captures device** (photos de pièces réelles prises avec l'app Android en mode debug)
- le **modèle admin** (Cohort / Iteration / Benchmark dans `admin/packages/web` + backend `ml/api/lab_routes.py`)

Aujourd'hui ces deux mondes vivent en parallèle : le user prend des photos avec son téléphone, fait `adb pull`, lance des scripts à la main pour synchroniser les datasets, puis va dans le front Lab pour créer une cohorte et un benchmark — sans aucun lien explicite entre les deux. On veut que le front pilote ce flow de bout en bout, en disant à l'utilisateur quelles commandes shell exécuter à chaque étape.

**Livrable étape 1 (cette session, début)** : un design doc dans `docs/admin/cohort-capture-flow/design.md` qui spécifie le modèle de données, les endpoints backend, les pages front à modifier, la pipeline de capture, et les étapes de migration. **Ne pas écrire de code avant que ce design soit validé par l'utilisateur.**

**Livrable étape 2 (après validation)** : implémentation par phases découpées proprement, chacune commitable indépendamment.

---

## Conventions repo (à respecter strictement)

Lire `CLAUDE.md` à la racine. Points critiques :
- **R0** : pas de dette technique, on construit proprement depuis le POC
- **R1** : proto-first design — toute scène/composant visuel admin doit d'abord exister en proto HTML (`docs/design/prototype/`) avant Vue. Si tu inventes du visuel sans équivalent proto, **stop et demande**.
- **R2** : tokens auto-générés (Color/Shape/Spacing.kt côté Android — non pertinent pour ce sprint admin, mais idem pour le CSS du front : `shared/tokens.css` est canonique)
- **`go-task` toujours**, jamais `task`
- **Pas de `git add -A` ni `git add .`** : staging par fichier
- **Pas de `TODO:` dans le code** : la dette est explicite via docs, pas enfouie

Stack admin : Vue 3 + Vite + pnpm workspace. Vit dans `admin/packages/web/`. Backend ML standalone Python en `ml/api/` (FastAPI). Voir `CLAUDE.md` §"Monorepo" et §"Déploiement admin".

Backend storage : Supabase (Postgrest), schéma de vérité dans `supabase/types/database.ts`. Le state local de training/lab/benchmark est dans `ml/state/training.db` (SQLite, source de vérité côté ML). Voir mémoire utilisateur "Training pipeline refacto".

---

## Contexte récent (utile pour comprendre l'état du repo)

Le rework du pipeline `scan/normalize_snap.py` vient de se terminer (2026-04-29) : R@1 ArcFace passé de ~68 % à 94.74 % sur le golden set device, parity studio↔device validée à 100 %. Le port Kotlin `SnapNormalizer.kt` est validé. Détails : `docs/scan-normalization/normalize-rework/`. Pas directement pertinent pour cette session, mais c'est ce qui a généré les ~600 fichiers dans `debug_pull/20260429_170852/` que tu vas voir.

L'état actuel : la pipeline scan marche bien sur **17 pièces × 6 angles** (le golden set device), mais on veut maintenant industrialiser le process pour scaler à plusieurs cohortes de pièces, comparer des recettes d'augmentation, et avoir un vrai workflow A/B reproductible.

---

## Le problème concret à résoudre

### Flow actuel (manuel, fragile)

```
[Phone Android — mode capture activé via capture_coins.csv en assets/]
   ↓ user prend 17 coins × 6 angles guidé par l'app
   ↓ adb pull /sdcard/eurio_debug ./debug_pull/<ts>/   (manuel)
debug_pull/<ts>/eurio_debug/eval_real/<eurio_id>/*.jpg
   ↓ ml/scan/sync_eval_real.py  (manuel, à lancer après chaque pull)
ml/datasets/eval_real_norm/<eurio_id>/*.jpg            (regenerable)
   ↓ prepare_dataset.py auto-injecte en val/
ml/datasets/eurio-poc/val/<eurio_id>/*.jpg             (regenerable, dépend du run)
   ↓ training run consomme val/
[Iteration → Benchmark → R@1 dans le Lab admin]
```

### Modèle admin existant (sans lien aux captures)

```
Cohort (id, name, eurio_ids[], zone, …)
└── Iteration (id, recipe_id, training_config, …)
    └── Benchmark (R@1, R@3, R@5, num_photos, …)
```

Voir types complets : `admin/packages/web/src/features/lab/types.ts`. La `Cohort` dit *"ces 17 coins"* mais pas *"capturés sur ce phone, ce jour, avec ce protocole"*. Les photos vivent juste sur disque sans métadonnée admin.

### Gap conceptuel

Les **captures appartiennent au coin (canonical)**, pas à la cohorte. Une cohorte est juste une **sélection de coins** + **une recipe d'augmentation**. Plusieurs cohortes peuvent partager des coins → elles partagent les captures gratuitement. Si je crée une nouvelle cohorte qui réutilise des coins déjà capturés, je n'ai à capturer que les coins manquants (delta).

---

## Modèle cible (validé avec l'utilisateur)

### Structure disque (côté ml/datasets/)

```
ml/datasets/
├── coins/                                    # NOUVEAU dossier (migration séparée, hors scope ce sprint)
│   └── <numista_id>/                         # ⚠ statu quo : on garde numista_id (rename → eurio_id deferred)
│       ├── sources/                          # Numista, Wiki — aujourd'hui à la racine ml/datasets/<numista_id>/
│       └── captures/                         # photos device canoniques, jamais re-prises
│           ├── bright_plain.jpg
│           ├── tilt_plain.jpg
│           └── …  (les 6 angles du protocole)
├── eurio-poc/                                # généré par training (regenerable)
├── eval_real_norm/                           # généré par sync_eval_real (regenerable)
└── sources/                                  # raw downloads
```

**Migration `<numista_id>/` → `coins/<numista_id>/` : DEFERRED.** Statu quo pour ce sprint. À grep tous les scripts qui consomment ces chemins (`prepare_dataset.py`, `sync_eval_real.py`, etc.) avant de bouger. Mais on peut **dès maintenant** écrire le code du flow cohort en visant la structure cible et garder un alias temporaire si besoin.

### Convention de naming : eurio_id à terme, numista_id pour l'instant

L'`eurio_id` (slug `at-2002-2eur-standard`) est la **norme cible**. On l'a designé pour être collision-free. Mais aujourd'hui les dossiers disque sont par `numista_id` (reliquat du début du projet). **Statu quo pour ce sprint**, mais le code admin/CSV doit utiliser `eurio_id` partout sauf au moment du dispatch sur disque où on map via le CSV. Mémoire à garder : "eurio_id devrait être la norme partout, numista_id est un reliquat".

### Modèle admin enrichi

```
Coin (eurio_id, numista_id) ← entité existante côté Supabase
└── captures: { exists: bool, num_files: int, last_pulled_at: ts | null }   ← propriété calculée

Cohort
├── id, name, description, eurio_ids[]
├── recipe_id (augmentation)
├── status: 'draft' | 'frozen' | 'running' | 'done'
└── status passe à 'frozen' automatiquement à la 1re Iteration lancée

Iteration → Benchmark  (inchangé)
```

### Workflow utilisateur cible (front admin)

1. **CoinsPage.vue** : user filtre/sélectionne N coins.
   - Bouton actuel "Nouveau cohort lab" → renommer **"Cohort lab"** → ouvre une modal :
     - "Créer un nouveau cohort" → CohortNewPage
     - "Ajouter à un cohort existant" → liste des cohorts en `status='draft'` uniquement → ajoute les coins sélectionnés
2. **CohortDetailPage.vue** : page principale de pilotage, structurée en sections séquentielles :
   - **§1 Coins** : liste des coins de la cohorte, possibilité d'ajouter/retirer (si draft)
   - **§2 Captures** : pour chaque coin, badge ✅ (capturé) ou ❌ (à capturer). Bouton **"Générer CSV de capture"** qui :
     - calcule le delta (coins sans `captures/` ou avec `captures/` incomplet)
     - génère `capture_cohort_<slug>.csv` (où le stocker côté ordinateur ? **question ouverte ci-dessous**)
     - affiche un encadré avec la commande shell à exécuter pour push :
       ```
       adb push <chemin>/capture_cohort_<slug>.csv /sdcard/eurio_capture/cohort.csv
       ```
     - explique qu'après capture, l'utilisateur fait `adb pull` (commande aussi affichée) puis clique **"Synchroniser"** qui dispatche les fichiers dans `coins/<numista_id>/captures/`
   - **§3 Recipe** : sélection/édition de la recipe d'augmentation (existant)
   - **§4 Run** : bouton lancer iteration → fige la cohort en `frozen`
3. **CohortDetailPage.vue (vue cohort frozen)** : read-only, mais bouton **"Cloner"** qui crée un nouveau cohort en draft avec mêmes coins/recipe, modifiable.

### Avertissement à afficher dans le front

Encadré informatif permanent dans CohortDetailPage §2 Captures :

> ⚠ Les captures sont **canoniques par pièce** : une fois prises, elles ne sont pas re-prises (pas de versioning v1). Si tu modifies le protocole de capture (angles, normalize device, hardware phone), tous les benchmarks passés deviennent silencieusement incomparables. Migration vers un capture-set versionné = sprint futur.

---

## Décisions déjà tranchées (ne pas re-débattre)

| Q | Décision | Raison |
|---|---|---|
| **Versioning captures** | Pas de versioning v1. `coins/<numista_id>/captures/` est un dossier unique. | Simplicité. Garde-fou : script de pull refuse d'écraser sans flag explicite. Warning dans le front. |
| **CSV cohort transport** | `/sdcard/eurio_capture/cohort.csv` via `adb push` (runtime, pas de rebuild) | Itération rapide. L'app Android lit le CSV au runtime. |
| **`assets/capture_coins.csv`** | Garder (default debug capture set, ~19 coins) | Permet mode capture sans frontend pour démo/dev. |
| **CSV de cohort = delta uniquement** | Liste seulement les coins manquants (sans `captures/`). Coins déjà capturés exclus. | Évite de re-capturer ce qu'on a déjà. |
| **Auto-freeze** | Status `draft` → `frozen` automatiquement à la 1re iteration lancée. Modifs interdites après. Clone autorisé. | Reproductibilité benchmarks. |
| **Naming dossiers disque** | Statu quo `numista_id` pour le sprint. `eurio_id` à terme (deferred). | Migration coûteuse, pas le sprint. |
| **Migration `ml/datasets/<id>/` → `ml/datasets/coins/<id>/`** | Deferred (sprint séparé). | Demande grep + mise à jour de tous les scripts ML. |

---

## Questions ouvertes pour cette session (à résoudre dans le design doc)

### Q-OPEN-1 : Où stocker les CSV de cohorte côté ordinateur ?

Options :
- **A.** `ml/state/cohort_csvs/<cohort_slug>.csv` — proche du SQLite source de vérité, gitignored
- **B.** `ml/datasets/cohorts/<cohort_slug>.csv` — proche des datasets, gitignored
- **C.** Pas de stockage permanent : généré à la volée par l'endpoint, téléchargé par le browser, l'utilisateur le push manuellement où il veut

Trade-off : C est plus simple mais si l'utilisateur perd le fichier il doit le re-télécharger. A/B permet à un script admin de retrouver le CSV pour relancer un push. À trancher dans le design doc.

### Q-OPEN-2 : Comment l'app Android sait quelle cohorte est active ?

Aujourd'hui le mode capture lit `assets/capture_coins.csv`. Demain il doit lire `/sdcard/eurio_capture/cohort.csv` si présent, sinon fallback sur `assets/capture_coins.csv`. Côté Kotlin il faut modifier la classe qui charge le CSV (probablement dans `app-android/src/main/java/com/musubi/eurio/capture/` ou similaire — à grep). Voir `app-android/src/main/assets/capture_coins.csv` pour le format.

### Q-OPEN-3 : Endpoint de sync = synchrone ou async ?

Quand le user clique "Synchroniser", on doit :
1. Lire les fichiers du dernier `debug_pull/<ts>/` (ou un chemin choisi)
2. Pour chaque fichier, identifier le coin (via le path `eurio_real/<eurio_id>/...`)
3. Mapper `eurio_id` → `numista_id` (via `coin_catalog.json` ou Supabase)
4. Copier vers `ml/datasets/coins/<numista_id>/captures/` (avec garde-fou anti-écrasement)
5. Mettre à jour Supabase (timestamp `last_pulled_at` par coin)

Question : est-ce qu'on bloque le user pendant ça (synchrone, simple) ou on lance une task background avec polling (plus propre mais demande l'infra `ml/api`) ? Pour 17 coins × 6 = 102 fichiers, sync probablement OK.

---

## Pages / fichiers à toucher (vue d'ensemble)

### Front admin (`admin/packages/web/`)

- `src/features/coins/pages/CoinsPage.vue` — refactor du bouton "Nouveau cohort lab" en modal
- `src/features/lab/pages/CohortDetailPage.vue` — ajouter §2 Captures + workflow par étapes
- `src/features/lab/pages/CohortNewPage.vue` — accepter coins pré-sélectionnés via query param ou store
- `src/features/lab/composables/useLabApi.ts` — ajouter méthodes pour endpoints captures
- `src/features/lab/types.ts` — ajouter types `CaptureStatus`, `CohortCaptureManifest`

### Backend ML (`ml/`)

- `ml/api/lab_routes.py` — endpoints :
  - `GET /lab/cohorts/<id>/captures/status` → liste {coin_id, has_captures, num_files}
  - `POST /lab/cohorts/<id>/captures/csv` → génère + retourne le CSV delta
  - `POST /lab/cohorts/<id>/captures/sync` → dispatch des fichiers depuis `debug_pull/<ts>/`
- `ml/scan/sync_eval_real.py` — adapter pour aussi alimenter `coins/<numista_id>/captures/` (ou créer un nouveau script qui appelle l'ancien)
- Helper de mapping `eurio_id` ↔ `numista_id` (probablement déjà présent quelque part — grep)

### Android (`app-android/`)

- Trouver la classe qui lit `assets/capture_coins.csv` (grep `capture_coins.csv`)
- Modifier pour lire `/sdcard/eurio_capture/cohort.csv` en priorité, fallback sur l'asset
- Ajouter la permission `READ_EXTERNAL_STORAGE` si pas déjà là (vérifier `AndroidManifest.xml`)

### Proto (`docs/design/prototype/`)

- **R1 strict** : avant de coder la nouvelle CohortDetailPage, ajouter une scène proto correspondante. Voir `docs/design/_shared/scene-parity.md` et `parity-rules.md`.
- Probablement scène `lab-cohort-detail.html` enrichie de la section "Captures" avec ses 3 états (draft / capture en cours / capturé complet).

### Taskfile / docs

- Nouvelle task go-task pour le pull → dispatch en une commande, ex. `go-task lab:cohort-pull -- <cohort_slug>` qui appelle `adb pull` puis l'endpoint sync
- Doc `docs/admin/cohort-capture-flow/design.md` (le livrable étape 1 de cette session)

---

## Fichiers à lire en priorité au démarrage

```
CLAUDE.md                                                      # règles non négociables
docs/admin/cohort-capture-flow/session-kickoff.md              # ce fichier
admin/packages/web/src/features/lab/types.ts                   # modèle admin actuel
admin/packages/web/src/features/lab/pages/CohortDetailPage.vue # page à enrichir
admin/packages/web/src/features/lab/pages/CohortNewPage.vue
admin/packages/web/src/features/coins/pages/CoinsPage.vue      # bouton à refactor
ml/api/lab_routes.py                                           # endpoints actuels (à étendre)
ml/scan/sync_eval_real.py                                      # script de sync existant
app-android/src/main/assets/capture_coins.csv                  # format du CSV (eurio_id;numista_id;display_name)
ml/datasets/coin_catalog.json                                  # mapping eurio_id ↔ numista_id
```

Plus le grep nécessaire pour trouver la classe Kotlin qui charge `capture_coins.csv`.

---

## Plan d'attaque suggéré pour la session

1. **Lire les fichiers ci-dessus** (10 min)
2. **Grep des points inconnus** : où est lu le CSV côté Android, où est le mapping eurio_id↔numista_id, qui consomme `ml/datasets/<numista_id>/` (1 sprint de grep, écrire les findings en cache mental ou TaskList)
3. **Écrire `docs/admin/cohort-capture-flow/design.md`** (livrable étape 1) — modèle de données complet, séquence de chaque endpoint, tableau des fichiers à toucher, étapes de migration. Résoudre les 3 questions ouvertes Q-OPEN-1/2/3.
4. **Demander validation à l'utilisateur** sur le design doc. **NE PAS coder avant validation.**
5. **Une fois validé** : découper en phases (proto → backend endpoints → front pages → Android CSV runtime), une phase = un commit.

---

## Notes finales

- Tu n'as pas besoin de toucher au pipeline scan/normalize ni au training : tout ça marche déjà. Tu construis juste l'orchestration admin par-dessus.
- Le user attend du flow utilisateur, pas de la sur-ingénierie. Si tu hésites entre simple et générique, choisis simple.
- Demande dès qu'un truc est ambigu. Le user préfère valider une décision en 30 s plutôt que défaire 2 h de code mal calibré.
- Mémoire utilisateur : "Build properly from POC, no shortcuts that create debt" — pas de TODO en escargot, pas de hack qu'on "fixera plus tard".
