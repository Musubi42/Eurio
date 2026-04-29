# Design — Cohort capture flow (admin)

> Statut : **DRAFT — en attente validation utilisateur.**
> Périmètre : faire piloter par le front admin (Vue) la boucle complète
> *sélection coins → capture device guidée → sync sur disque → iteration ML*.
> Source : `session-kickoff.md` dans le même dossier (lire d'abord).
>
> **Aucun code ne sera écrit avant validation de ce doc.**

---

## 1. Objectif & non-objectifs

### Objectif
Construire un flow utilisateur où, depuis le front admin :
1. Le user sélectionne des coins (CoinsPage existante) et les ajoute à un cohort `draft`.
2. Le front lui dit *exactement* quels coins ont déjà des captures device et lesquels manquent.
3. Le front génère un **CSV de capture delta** + lui affiche les commandes shell (`adb push`, `adb pull`) à coller.
4. Après pull, un clic sur **Synchroniser** dispatche les fichiers depuis `debug_pull/<ts>/` vers le store canonique `ml/datasets/<numista_id>/captures/`.
5. Le user lance une iteration → le cohort se fige (`frozen`), le benchmark consomme les captures.

### Non-objectifs (out of scope ce sprint)
- Versioning des captures (v1/v2). Les captures sont **canoniques par pièce**.
- Migration `ml/datasets/<numista_id>/` → `ml/datasets/coins/<numista_id>/`. **Statu quo** : on continue d'utiliser le path plat existant. Le rename est un sprint séparé qui demande un grep complet des consommateurs Python.
- Rename `numista_id` → `eurio_id` dans la structure disque. Statu quo aussi.
- Refonte de la pipeline `prepare_dataset.py` ou du benchmark. On les nourrit, on ne les touche pas.
- Capture multi-device, capture par plusieurs operators.

---

## 2. Décisions clés (résolution des Q-OPEN du kickoff)

### Q-OPEN-1 — Stockage des CSV cohort sur disque ⇒ **Option A**

**Décision** : `ml/state/cohort_csvs/<cohort_slug>.csv` (gitignored).

**Pourquoi** :
- `ml/state/training.db` est déjà la source de vérité côté ML. Les CSV vivent à côté.
- Permet à des scripts admin/CI de retrouver le CSV (relancer un push après un crash device).
- L'endpoint `POST /lab/cohorts/<id>/captures/csv` :
  - **écrit** le fichier sur disque
  - **retourne** aussi le contenu en `text/csv` pour download direct depuis le browser
  → on a les deux ergonomies sans complexité supplémentaire.

**Garde-fou** : ré-générer le CSV écrase l'ancien (le delta peut avoir évolué — coins ajoutés au cohort entre-temps).

### Q-OPEN-2 — Chemin device pour le CSV runtime ⇒ **app-scoped external**

**Décision** : `/sdcard/Android/data/com.musubi.eurio/files/Documents/eurio_capture/cohort.csv`
(soit côté Kotlin : `getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS)/eurio_capture/cohort.csv`).

**Pourquoi** :
- Aligné avec le pattern existant `DEBUG_DIR_DEVICE` (`.../files/Documents/eurio_debug`) — voir `app-android/Taskfile.yml`.
- **Aucune permission requise** : app-scoped external storage est lisible par l'app et writable par `adb push` sans `READ_EXTERNAL_STORAGE` ni `MANAGE_EXTERNAL_STORAGE`.
- Le kickoff suggérait `/sdcard/eurio_capture/cohort.csv` (storage racine) — on rectifie ici : ça demanderait `MANAGE_EXTERNAL_STORAGE` (heavy, demande validation Play Store) ou `READ_EXTERNAL_STORAGE` (deprecated sur Android 13+). L'app-scoped path est strictement meilleur.

**Logique de chargement** dans `CaptureProtocol.init(ctx)` :
1. Tenter de lire le fichier app-scoped. S'il existe et parse OK → l'utiliser.
2. Sinon → fallback sur `assets/capture_coins.csv` (le default debug capture set, ~19 coins, comportement actuel).

Le user peut donc toujours capturer "sans frontend" en mode démo via l'asset bundlé.

### Q-OPEN-3 — Endpoint sync = synchrone ou async ⇒ **synchrone**

**Décision** : synchrone, avec progress steps texte dans la réponse.

**Pourquoi** :
- 17 coins × 6 angles = 102 fichiers. Chaque fichier passe par `normalize_device_path` (Hough + crop + resize 224). Coût mesuré ~0.1–0.3s/fichier sur Mac M4 → ~15–30s pour le worst case.
- L'infra background task n'existe pas dans `ml/api/`. La rajouter pour ce besoin = sur-ingénierie.
- Le user clique "Synchroniser", attend, voit un `{ok, copied: 102, skipped: 0, failures: []}`. Si jamais ça grossit (multi-cohort batch), on async-ifiera plus tard.

---

## 3. Modèle de données

### 3.1. Extension de `Cohort` (SQLite + Pydantic + TS)

Champs ajoutés à `ExperimentCohortRow` (côté `ml/state/`) :

| Champ | Type | Default | Notes |
|---|---|---|---|
| `status` | `'draft' \| 'frozen'` | `'draft'` | Mute → `'frozen'` lors de la 1re iteration créée. Irréversible. |
| `frozen_at` | `str \| null` (ISO) | `null` | Set au passage `draft → frozen`. |

**Migration SQLite** : ajouter colonne `status TEXT NOT NULL DEFAULT 'draft'` + `frozen_at TEXT NULL` dans la table `experiment_cohorts`. Migration applicable in-place (alter table) — voir `ml/state/store.py`.

Note : on n'introduit **pas** de table `cohort_captures` séparée. L'état "le coin X a-t-il des captures" est dérivé du filesystem (présence + nombre de fichiers dans `ml/datasets/<numista_id>/captures/`). Une table dupliquerait ce que le FS dit déjà — risque de drift. Trade-off : chaque appel à l'endpoint status fait N stat() — pour 17 coins c'est imperceptible.

### 3.2. Modèle Capture (dérivé, pas persisté)

```python
@dataclass
class CoinCaptureStatus:
    eurio_id: str
    numista_id: int | None        # null si pas de mapping (coin non capturable)
    has_captures: bool            # at least one file in captures/
    num_files: int                # count *.jpg in captures/
    expected_steps: list[str]     # CaptureProtocol.steps (6 atm)
    missing_steps: list[str]      # expected - present
    last_modified: str | None     # max mtime of files (ISO)
```

Côté TS :
```ts
export interface CoinCaptureStatus {
  eurio_id: string
  numista_id: number | null
  has_captures: boolean
  num_files: number
  expected_steps: string[]
  missing_steps: string[]
  last_modified: string | null
}

export interface CohortCaptureManifest {
  cohort_id: string
  total_coins: number
  fully_captured: number       // num_files >= len(expected_steps)
  partial: number              // 0 < num_files < expected
  missing: number              // num_files == 0
  per_coin: CoinCaptureStatus[]
}
```

### 3.3. CSV cohort — format

Identique au format actuel de `assets/capture_coins.csv` :

```
eurio_id;numista_id;display_name
fr-2007-2eur-standard;6376;France 2007 — Standard
de-2020-2eur-50-years-since-the-kniefall-von-warschau;226447;Allemagne 2020 — Kniefall
…
```

- Header obligatoire (le parser Kotlin existant le tolère/skip).
- Délimiteur `;` (idem).
- Le CSV contient **uniquement** les coins du cohort dont le delta capture > 0 (au moins un step manquant). Coins déjà 100 % capturés exclus.
- `display_name` = `coins.theme` (Supabase) si présent, sinon `eurio_id` en fallback.
- Coins sans `numista_id` : exclus + warning dans le manifest (impossible de capturer un coin qui n'a pas de slot disque puisque le store actuel est par `numista_id`).

---

## 4. Endpoints backend (FastAPI, dans `ml/api/lab_routes.py`)

Tous sous le prefix `/lab/cohorts/{cohort_id}/captures/`.

### 4.1. `GET /lab/cohorts/{id}/captures/status`

Retourne le `CohortCaptureManifest`. Lit le FS pour chaque coin du cohort.

Pseudocode :
```python
def captures_status(cohort_id: str) -> CohortCaptureManifest:
    cohort = store.get_cohort(cohort_id) or 404
    expected = list(CAPTURE_STEPS)  # imported from a shared constant
    per_coin = []
    for eid in cohort.eurio_ids:
        nid = catalog.numista_id_for(eid)  # via coin_catalog.json or Supabase
        captures_dir = ML_DIR / "datasets" / str(nid) / "captures" if nid else None
        files = sorted(captures_dir.glob("*.jpg")) if captures_dir and captures_dir.exists() else []
        present_steps = {f.stem for f in files}
        per_coin.append(CoinCaptureStatus(
            eurio_id=eid, numista_id=nid,
            has_captures=len(files) > 0,
            num_files=len(files),
            expected_steps=expected,
            missing_steps=[s for s in expected if s not in present_steps],
            last_modified=max((f.stat().st_mtime for f in files), default=None),
        ))
    return aggregate(per_coin)
```

### 4.2. `POST /lab/cohorts/{id}/captures/csv`

- **Calcule le delta** (coins avec `missing_steps != []`).
- **Écrit** `ml/state/cohort_csvs/<cohort.name>.csv`.
- **Retourne** :
  ```json
  {
    "csv_path": "ml/state/cohort_csvs/green-v1.csv",
    "csv_content": "eurio_id;numista_id;display_name\n…",
    "rows": 12,
    "skipped_no_numista": ["xx-2024-…"],
    "skipped_complete": 5,
    "device_target_path": "/sdcard/Android/data/com.musubi.eurio/files/Documents/eurio_capture/cohort.csv",
    "push_command": "adb push ml/state/cohort_csvs/green-v1.csv /sdcard/.../cohort.csv",
    "pull_command": "go-task --taskfile app-android/Taskfile.yml pull-debug",
    "sync_endpoint_hint": "POST /lab/cohorts/{id}/captures/sync"
  }
  ```

### 4.3. `POST /lab/cohorts/{id}/captures/sync`

Body :
```json
{ "pull_dir": "debug_pull/20260429_170852", "overwrite": false }
```

- Si `pull_dir` omis → utilise le plus récent `debug_pull/<ts>/` (max mtime).
- Walk `<pull_dir>/eurio_debug/eval_real/<eurio_id>/<step>_raw.jpg` (format actuel produit par l'app, voir `sync_eval_real.py`).
- Pour chaque fichier : map `eurio_id → numista_id`, normaliser via `normalize_device_path` (réutilise la pipeline existante), écrire dans `ml/datasets/<numista_id>/captures/<step>.jpg`.
- Aussi écrire dans `ml/datasets/eval_real_norm/<eurio_id>/<step>.jpg` (compatibilité — c'est ce que `prepare_dataset.py` consomme aujourd'hui pour le val/ split). Concrètement ⇒ on **réutilise** `sync_eval_real.main()` puis on **dupplique** vers `captures/` (ou inverse — voir §6.2).
- Garde-fou anti-écrasement : si un fichier existe déjà dans `captures/<step>.jpg`, on **n'écrase pas** sauf si `overwrite=true` dans le body. Réponse liste les `skipped_existing`.
- Met à jour la stat `last_pulled_at` côté Supabase ? **Non pour ce sprint** — on dérive du FS, pas besoin d'écriture Supabase. (Évite la dépendance backend → Supabase pour cette opération.)

Réponse :
```json
{
  "pull_dir": "debug_pull/20260429_170852",
  "copied": 102,
  "skipped_existing": 0,
  "skipped_unmapped_eurio_id": [],
  "failures": [{"file": "…", "reason": "normalize failed"}],
  "duration_s": 18.4
}
```

### 4.4. Modification `POST /lab/cohorts/{id}/iterations`

Avant de créer l'iteration, **passer le cohort en `frozen` si encore `draft`**. Pseudocode :

```python
if cohort.status == 'draft':
    store.update_cohort(cohort.id, status='frozen', frozen_at=now_iso())
```

Aussi : tout endpoint qui muterait un cohort `frozen` (ajout/retrait d'`eurio_ids`, edit recipe, …) renvoie `409 Conflict`. Aujourd'hui on ne peut **pas** muter `eurio_ids` (création seulement) → §4.5 ajoute cette mutation.

### 4.5. Nouveaux endpoints de mutation cohort (draft only)

- `POST /lab/cohorts/{id}/coins` — body `{eurio_ids: [...]}` ⇒ ajoute des coins (uniquement si `status='draft'`).
- `DELETE /lab/cohorts/{id}/coins/{eurio_id}` — retire un coin (idem).
- `POST /lab/cohorts/{id}/clone` — body `{name, description?}` ⇒ crée un nouveau cohort `draft` avec `eurio_ids` copiés.

---

## 5. Front admin

### 5.1. CoinsPage.vue — refactor du bouton "Nouveau cohort Lab"

Aujourd'hui (lignes ~1283–1287) le bouton fait :
```
router.push(`/lab/cohorts/new?eurio_ids=${ids}`)
```

Cible : ouvrir une **modal** avec deux options.

```
┌─────────────────────────────────────┐
│ Cohort lab                          │
│                                     │
│ ⚪ Créer un nouveau cohort          │
│ ⚪ Ajouter à un cohort existant     │
│   └─ <select> draft cohorts only    │
│                                     │
│              [Annuler] [Confirmer]  │
└─────────────────────────────────────┘
```

- Liste des cohorts en `status='draft'` chargée via `GET /lab/cohorts?status=draft`. (Petit ajout backend : filtre `status` dans `list_cohorts`.)
- "Confirmer (créer)" → `router.push('/lab/cohorts/new?eurio_ids=…')` (comportement actuel).
- "Confirmer (ajouter)" → `POST /lab/cohorts/<id>/coins` puis `router.push('/lab/cohorts/<id>')`.
- Composant : `<CohortAttachModal>` neuf dans `src/features/lab/components/`.

### 5.2. CohortDetailPage.vue — restructuration en sections

Layout actuel : header → liste pièces (compact chips) → trajectoire → table itérations + sidebar sensitivity.

Layout cible (cohort `draft`) :

```
┌───────────────────────────────────────┐
│ Header (status badge: DRAFT / FROZEN) │
├───────────────────────────────────────┤
│ §1. Pièces (X)                        │
│   - chips éditables (✕ pour retirer)  │
│   - bouton "Ajouter des pièces"       │
│       → ouvre /coins?cohort_attach=id │
├───────────────────────────────────────┤
│ §2. Captures device                   │
│   - bandeau ⚠ canonicité (cf §7)      │
│   - récap : X complets / Y partiels   │
│              / Z manquants            │
│   - liste par coin avec ✅ ❌ ⚠         │
│   - bouton "Générer CSV de capture"   │
│   - encadré commandes shell quand CSV │
│     généré (push / pull / sync)       │
│   - bouton "Synchroniser depuis pull" │
│     (avec sélecteur de pull_dir)      │
├───────────────────────────────────────┤
│ §3. Recipe (existing — placeholder    │
│     UI uniquement, déjà géré par      │
│     l'iteration form pour l'instant)  │
├───────────────────────────────────────┤
│ §4. Run                               │
│   - bouton "Nouvelle itération"       │
│   - warning : "lancer figera le cohort"│
└───────────────────────────────────────┘
```

Layout cible (cohort `frozen`) : §1 et §3 deviennent read-only, §2 garde la liste mais sans bouton générer (read-only — captures déjà figées au moment du run), §4 garde "Nouvelle itération", header affiche un bouton **"Cloner"**.

**Section §2 (Captures) en détail** :

```
┌──────────────────────────────────────────────┐
│ Captures device                              │
│                                              │
│ ⚠ Les captures sont canoniques par pièce.    │
│    Modifier le protocole brise tous les      │
│    benchmarks passés. (Lire avant.)          │
│                                              │
│ 12 / 17 coins capturés (72%)                 │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ░░░░░         │
│                                              │
│ ✅ fr-2007-2eur-standard  6/6  (4 j)         │
│ ⚠  de-2020-…-kniefall    4/6  manque tilt,…  │
│ ❌ at-2002-2eur-standard  0/6                │
│ ❌ es-2016-…-segovia      0/6                │
│                                              │
│ [Générer CSV pour les 5 manquants/partiels]  │
│                                              │
│ ── Quand le CSV est prêt, encadré : ──       │
│ 1. Push :                                    │
│    adb push ml/state/cohort_csvs/green-v1.csv│
│      /sdcard/Android/data/...                │
│ 2. Capture sur le phone (mode debug)         │
│ 3. Pull :                                    │
│    go-task --taskfile app-android/Taskfile.yml pull-debug│
│ 4. [Synchroniser depuis le dernier pull]     │
│    (ou choisir un autre pull_dir)            │
└──────────────────────────────────────────────┘
```

### 5.3. CohortNewPage.vue — petits ajouts

- Ajouter un toggle "Démarrer en draft" (toujours coché — cohorts naissent draft, l'auto-freeze advient à la 1re iteration). Le coup de pédale c'est de **retirer** le warning actuel "frozen dès création" qui est maintenant faux.
- Reste largement inchangé.

### 5.4. Composables & types

- `src/features/lab/composables/useLabApi.ts` :
  - `fetchCohortCaptures(cohortId)` → `CohortCaptureManifest`
  - `generateCohortCsv(cohortId)` → `{ csv_path, csv_content, … }`
  - `syncCohortCaptures(cohortId, { pull_dir?, overwrite? })`
  - `addCoinsToCohort(cohortId, eurio_ids)`
  - `removeCoinFromCohort(cohortId, eurio_id)`
  - `cloneCohort(cohortId, payload)`
  - `listDraftCohorts()` (utilise `?status=draft`)
- `src/features/lab/types.ts` : `CoinCaptureStatus`, `CohortCaptureManifest`, et étendre `CohortSummary` avec `status: 'draft' | 'frozen'`, `frozen_at: string | null`.

---

## 6. Pipeline ML & scripts

### 6.1. Helper de mapping `eurio_id ↔ numista_id`

À ajouter dans `ml/api/` (ou `ml/scan/` si plus naturel) — un module `coin_lookup.py` qui :
- charge `ml/datasets/coin_catalog.json` (déjà la source de vérité — voir mémoire utilisateur "Coin catalog convention")
- cache un dict `{eurio_id: numista_id}` et l'inverse
- expose `numista_id_for(eurio_id) -> int | None` et `eurio_id_for(numista_id) -> str | None`

`coin_catalog.json` est indexé par `numista_id` mais ne contient pas l'`eurio_id` directement (vérifié, schéma : `{numista_id, name, country, year, face_value, type}`). **Action** : le `eurio_id` doit venir d'ailleurs — soit de Supabase (`coins.eurio_id` + `coins.cross_refs->>numista_id`), soit d'un fichier déjà existant à grep.

⇒ **Sous-question à grep avant impl** : où vit aujourd'hui le mapping eurio_id → numista_id côté Python ? Hypothèses :
- Le bootstrapper Supabase (`ml/bootstrap/`) en a probablement besoin
- Les scripts de fetch images (`ml/fetch/numista_*.py`)

Si la seule source canonique est Supabase, le helper devra `SELECT eurio_id, cross_refs->numista_id FROM coins` au cold-start (cache en RAM, refresh sur 401/410/manuel).

### 6.2. `sync_eval_real.py` — extension

Aujourd'hui le script écrit dans `ml/datasets/eval_real_norm/<eurio_id>/<step>.jpg`. **Modification minimale** : ajouter un flag `--also-write-captures` qui, en parallèle, copie chaque sortie normalisée vers `ml/datasets/<numista_id>/captures/<step>.jpg` (en respectant le garde-fou anti-écrasement décrit §4.3).

L'endpoint sync (§4.3) appelle `sync_eval_real.main(["<pull_dir>", "--also-write-captures"])` et capture stdout pour le retour API.

Note : `eval_real_norm/` reste populé tel quel — c'est ce que `prepare_dataset.py` consomme déjà. On **ajoute** un store canonique `captures/` sans casser l'existant.

### 6.3. Migration `<numista_id>/` → `coins/<numista_id>/` — DEFERRED

Documenté dans le kickoff. Pour ce sprint, statu quo. Le code admin/backend utilise des **constantes path** (`CAPTURES_BASE = ML_DIR / "datasets"`) pour qu'au jour de la migration on n'ait qu'**un** endroit à toucher.

---

## 7. Android — chargement runtime du CSV

### 7.1. Modification de `CaptureProtocol.kt`

Le contrat actuel est `init(context)` → lit `assets/capture_coins.csv`. Modification :

```kotlin
fun init(context: Context) {
    _coins = runCatching { readRuntimeOverride(context) ?: readAsset(context) }
        .onFailure { Log.e(TAG, "Failed to load capture coins", it) }
        .getOrDefault(emptyList())
    Log.i(TAG, "Loaded ${_coins.size} coin(s) (source=${if (overrideUsed) "runtime" else "asset"})")
}

private fun readRuntimeOverride(context: Context): List<Coin>? {
    val docs = context.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS) ?: return null
    val file = File(docs, "eurio_capture/cohort.csv")
    if (!file.isFile) return null
    return parseCsv(file.readLines())
}
```

- `parseCsv` extrait la logique commune actuellement dans `readAsset`.
- Aucune permission supplémentaire requise (`getExternalFilesDir` est app-scoped).
- `AndroidManifest.xml` : **pas de modif** (vérifié — aucune permission ajoutée).
- Comportement : si le user push un CSV via `adb`, l'app au prochain démarrage le lit. Si le fichier est supprimé/absent, fallback transparent sur le default bundlé.

### 7.2. Hot-reload (out of scope)
Aujourd'hui `init()` n'est appelé qu'une fois dans `EurioApp.onCreate()`. Pour qu'un CSV pushé pendant que l'app tourne soit pris en compte, il faut tuer l'app (`adb shell am force-stop`). Acceptable pour le workflow capture (le user re-lance l'app après push). **Non-objectif** d'auto-reload.

### 7.3. Documentation
Le bouton "Capture mode" dans l'app (déjà présent pour l'eval) consomme automatiquement le CSV chargé. Aucune modif UI Android requise au-delà de §7.1.

---

## 8. Taskfile — orchestration utilisateur

Ajouter une task de pratique dans `app-android/Taskfile.yml` (ou `Taskfile.yml` racine) :

```yaml
push-capture-csv:
  desc: Push a cohort capture CSV to the device
  vars:
    CSV: '{{.CSV}}'  # required
  preconditions:
    - sh: 'test -f {{.CSV}}'
      msg: "CSV file not found: {{.CSV}}"
  cmds:
    - adb push {{.CSV}} /sdcard/Android/data/{{.APP_ID}}/files/Documents/eurio_capture/cohort.csv
    - adb shell am force-stop {{.APP_ID}}
    - echo "Pushed. Re-launch app to pick up new cohort."
```

Usage : `go-task -t app-android/Taskfile.yml push-capture-csv CSV=ml/state/cohort_csvs/green-v1.csv`.

Le front affiche cette commande directement (dans l'encadré §5.2). Pas obligatoire — un `adb push` brut marche aussi —, mais ergonomique.

---

## 9. Avertissements UX (à afficher dans le front)

Encadré permanent dans CohortDetailPage §2 (cf kickoff §"Avertissement à afficher") :

> ⚠ **Captures canoniques par pièce.** Une fois prises, les photos d'une pièce
> sont réutilisées par tous les cohorts qui contiennent cette pièce. Pas de
> versioning v1 : si tu modifies le protocole de capture (angles, normalize
> device, hardware phone), **tous les benchmarks passés deviennent silencieusement
> incomparables**. Migration vers un capture-set versionné = sprint futur.

---

## 10. Migration & ordre de déploiement

Découpage en phases commitables indépendamment, dans l'ordre :

### Phase A — Backend status (non-breaking)
- Ajouter colonnes `status`, `frozen_at` à la table cohorts (DEFAULT 'draft' → tous les cohorts existants deviennent `draft` rétroactivement). **Décision** : OK car aucun n'a actuellement été lancé en prod. Vérifier en lisant `ml/state/training.db` avant.
- Helper `coin_lookup.py` (§6.1).
- Endpoint `GET /lab/cohorts/{id}/captures/status`.
- Modifier `_cohort_summary` pour inclure `status`/`frozen_at` dans la réponse.

### Phase B — Backend mutation & sync
- Auto-freeze sur `POST iterations` + 409 sur mutations frozen.
- Endpoints `POST /coins`, `DELETE /coins/<eid>`, `POST /clone`.
- Endpoint `POST /captures/csv` + dossier `ml/state/cohort_csvs/` créé à la volée.
- Endpoint `POST /captures/sync` + extension de `sync_eval_real.py` avec `--also-write-captures`.

### Phase C — Front admin (Vue)
- Types + composables.
- Modal "Cohort lab" sur CoinsPage.
- Refonte CohortDetailPage avec sections + section §2 Captures.
- Page CohortNewPage : retire le warning "frozen dès création", ajoute mention "draft".
- Bouton "Cloner" (frozen view).

### Phase D — Android runtime
- Modif `CaptureProtocol.kt` (§7.1).
- Task `push-capture-csv` (§8).
- Test e2e sur un cohort réel.

### Phase E — Doc & cleanup
- Doc `docs/admin/cohort-capture-flow/README.md` (workflow utilisateur).
- Mémoire utilisateur à mettre à jour (project type) : "Cohort capture flow live".

**Rule R1 (proto-first)** : voir §11 — décision à valider par l'utilisateur AVANT phase C.

---

## 11. Question méta : proto-first sur l'admin ?

CLAUDE.md R1 dit textuellement :
> Tout nouveau design doit d'abord exister dans le prototype HTML
> avant d'être implémenté en Compose Android.

⇒ R1 cible **l'app Android** (Compose). L'admin Vue n'a **aujourd'hui aucune scène proto** (`docs/design/prototype/scenes/` ne contient que des écrans mobiles : scan-*, vault-*, profile-*, onboarding-*).

Le kickoff dit pourtant :
> **R1 strict** : avant de coder la nouvelle CohortDetailPage, ajouter une scène proto correspondante.

**Décision demandée à l'utilisateur** :
- **(a)** Élargir R1 à l'admin → on ajoute `docs/design/prototype/scenes/lab-cohort-detail.html` (et siblings) AVANT phase C. Coût : ~1 demi-journée de proto.
- **(b)** Limiter R1 à Compose Android → l'admin reste hors-périmètre proto-first (statu quo de fait, vu les pages admin existantes). Le design doc ci-dessus suffit comme spec visuelle.

**Recommandation** : (b) pour ce sprint. L'admin est outil interne (pas vu par les utilisateurs finaux), le design est dérivé de mockups texte ci-dessus, et investir en proto admin serait un gros chantier transverse à scoper dans son propre sprint. Garder R1 strict pour Android (où il a payé). À acter explicitement.

---

## 12. Récap des fichiers touchés

### Backend
| Fichier | Action |
|---|---|
| `ml/state/store.py` (& schema) | + colonnes `status`, `frozen_at`, helpers |
| `ml/state/types.py` (ou équivalent dataclass) | + `status` sur `ExperimentCohortRow` |
| `ml/api/lab_routes.py` | + 6 endpoints, + auto-freeze, + `status` filter |
| `ml/api/coin_lookup.py` | **nouveau** — mapping eurio↔numista |
| `ml/scan/sync_eval_real.py` | + flag `--also-write-captures` |

### Front
| Fichier | Action |
|---|---|
| `admin/packages/web/src/features/lab/types.ts` | + types capture, + status |
| `admin/packages/web/src/features/lab/composables/useLabApi.ts` | + 6 méthodes |
| `admin/packages/web/src/features/lab/pages/CohortDetailPage.vue` | refonte sections, +§2 |
| `admin/packages/web/src/features/lab/pages/CohortNewPage.vue` | retrait warning frozen, mention draft |
| `admin/packages/web/src/features/lab/components/CohortAttachModal.vue` | **nouveau** |
| `admin/packages/web/src/features/lab/components/CaptureSection.vue` | **nouveau** |
| `admin/packages/web/src/features/coins/pages/CoinsPage.vue` | bouton → modal |

### Android
| Fichier | Action |
|---|---|
| `app-android/src/main/java/com/musubi/eurio/features/scan/CaptureProtocol.kt` | + readRuntimeOverride |

### Taskfile / docs
| Fichier | Action |
|---|---|
| `app-android/Taskfile.yml` | + task `push-capture-csv` |
| `docs/admin/cohort-capture-flow/README.md` | **nouveau** (workflow utilisateur) |
| `docs/admin/cohort-capture-flow/design.md` | **ce doc** |

---

## 13. Validation requise avant implémentation

Avant tout code, j'ai besoin que tu m'actes :

1. ✅/❌ **Q-OPEN-1** résolu en option A (`ml/state/cohort_csvs/`) ?
2. ✅/❌ **Q-OPEN-2** résolu en path app-scoped (`getExternalFilesDir(...)/eurio_capture/cohort.csv`) au lieu de `/sdcard/eurio_capture/` du kickoff ?
3. ✅/❌ **Q-OPEN-3** résolu en synchrone ?
4. ✅/❌ **§3.1** : ajout des colonnes `status`/`frozen_at` (vs table séparée) ?
5. ✅/❌ **§3.2** : pas de table SQL pour les captures, dérivé du FS — d'accord ?
6. ✅/❌ **§5.1** : modal "Cohort lab" avec 2 options + filtre draft only — UX OK ?
7. ✅/❌ **§5.2** : restructuration CohortDetailPage en 4 sections — OK ?
8. ✅/❌ **§6.2** : `sync_eval_real.py` étendu avec `--also-write-captures` (vs script séparé) ?
9. ✅/❌ **§7.1** : modification `CaptureProtocol.kt` (vs nouveau loader) ?
10. ✅/❌ **§11** : décision (a) ou (b) sur proto-first admin ? *(reco : (b))*
11. ✅/❌ **§10** : découpage en phases A→E commitables ?

Toute autre divergence : flag-la, on ajuste avant de toucher au code.
