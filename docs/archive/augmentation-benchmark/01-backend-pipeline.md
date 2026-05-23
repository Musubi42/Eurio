# PRD Bloc 1 — Backend pipeline d'augmentation

> Moteur Python qui transforme une image Numista en N variantes augmentées. Consommé par le Studio admin (Bloc 2) et le Benchmark (Bloc 3). Ce PRD fige l'API, le contrat d'introspection, les endpoints HTTP et le schéma SQLite local.

## 1. Contexte & motivation

Phase 2 du plan ML scalability (`docs/research/ml-scalability-phases/phase-2-augmentation.md`) a livré un pipeline d'augmentation avancé : perspective warp, re-lighting 2.5D, overlays (patina / dust / scratches / fingerprints), paramétré par zone (`green` / `orange` / `red`).

Le code est posé (`ml/augmentations/`), avec une CLI de preview (`ml/preview_augmentations.py`). Il manque deux choses pour que la phase prenne de la valeur opérationnelle :

- Un **Studio admin** (Bloc 2) pour régler visuellement les paramètres sans éditer `recipes.py` et regarder l'effet sur une pièce réelle, côte à côte avec le sample source.
- Un **Benchmark** (Bloc 3) qui entraîne sur plusieurs recettes candidates et compare R@1 / spread top1-top2, pour choisir empiriquement les bonnes valeurs au lieu de les deviner.

Ces deux blocs consomment le moteur via HTTP depuis le workspace `admin/`. Ils ont besoin d'un **contrat stable**, d'une **introspection programmatique** (pour générer les sliders Vue sans dupliquer la source de vérité) et d'un **format recipe JSON-serializable** (pour transiter par API et être stocké).

Ce PRD existe pour figer ce contrat avant que les Blocs 2 et 3 démarrent.

## 2. État actuel

Livré (Phase 2 itérations 1 & 2) :

| Fichier | Rôle |
|---|---|
| `ml/augmentations/base.py` | Contrat `Augmentor` (apply + maybe_apply + probabilité), helper `circular_mask` |
| `ml/augmentations/perspective.py` | `PerspectiveAugmentor` — tilt 3D via homographie OpenCV |
| `ml/augmentations/overlays.py` | `OverlayAugmentor` — patina / dust / scratches / fingerprints (blend multiply/screen/overlay) |
| `ml/augmentations/relighting.py` | `RelightingAugmentor` — normal map Sobel + Lambertian, cache LRU par image source |
| `ml/augmentations/pipeline.py` | `AugmentationPipeline(recipe, seed)` — compose les layers depuis un dict |
| `ml/augmentations/recipes.py` | `ZONE_RECIPES` — presets `green` / `orange` / `red` |
| `ml/preview_augmentations.py` | CLI : `eurio_id` ou `design_group_id` → grille PNG |

Non livré (scope de ce bloc) :

- Freeze explicite de l'API publique (aujourd'hui implicite, pas de garantie pour les consommateurs externes)
- Introspection (`get_schema()` sur Augmentor) pour Studio
- Endpoints FastAPI `/augmentation/*`
- Stockage SQLite des recipes et runs de preview
- Flag `--aug-recipe` dans `train_embedder.py`

## 3. Scope

### In

- **Freeze** de la signature `AugmentationPipeline(recipe, seed).generate(base_img, count) -> list[PIL.Image]` comme point d'entrée stable
- Contrat d'**introspection** sur chaque `Augmentor` (nom, params, types, bounds, description)
- **Sérialisation JSON-friendly** des recipes (pas de tuples côté wire, strings/numbers/lists seulement)
- Endpoints FastAPI :
  - `GET /augmentation/schema`
  - `GET /augmentation/overlays`
  - `POST /augmentation/preview`
  - `GET /augmentation/preview/images/{run_id}/{index}`
  - `GET/POST/PUT/DELETE /augmentation/recipes`
- Extension du store SQLite (`ml/state/schema.sql`) :
  - Deux nouvelles tables : `augmentation_recipes`, `augmentation_runs`
  - Colonne additive `training_runs.aug_recipe_id` (FK → `augmentation_recipes(id) ON DELETE SET NULL`)
  - Colonne additive `training_staging.aug_recipe_id` (FK idem) pour propager la recette depuis le handoff Studio → Training
- Extension du body `POST /training/stage` : accepte `aug_recipe_id?: string | null` par item (résolu par id ou name côté API). Consommé par le handoff Studio (PRD02).
- Intégration opt-in dans `train_embedder.py` via `--aug-recipe <id_or_name>`
- Propagation `TrainingRunner` : lit `config.aug_recipe` OU dérive depuis les items de staging (au choix, cf. §5.6), persiste `aug_recipe_id` sur `training_runs` au moment du run

### Out (roadmap)

- **Finitions Augmentors** (specular hotspots, motion blur directionnel, color grading non uniforme) — décision post-Benchmark : on verra empiriquement si l'uplift R@1 justifie de les rajouter (v1.5)
- **Promotion DB → `recipes.py`** : export d'une recette DB en code Python commité. Utile quand on veut ancrer un preset en "default" pour un zone — v1.5
- **Multi-base augmentation** (plusieurs images sources par design_group, ex. obverse + reverse mélangés) — v2
- **Studio admin UI** (sliders, compare, save) — PRD Bloc 2
- **Benchmark orchestrator** (grid search sur recipes, training distribué) — PRD Bloc 3

## 4. User stories

| Rôle | Veux | Pour |
|---|---|---|
| Training engineer | Un moteur d'augmentation stable avec une API figée | Construire le Studio sans craindre un rename qui casse tout |
| Admin UI dev (Studio) | Une route `/augmentation/schema` qui me dit quels layers existent + quels params ils exposent + leurs bounds | Générer les sliders Vue sans hardcoder la liste côté JS |
| Admin UI dev (Studio) | Envoyer un recipe JSON par POST et récupérer N PNG générées | Preview live sans refaire tourner une CLI |
| Training engineer | Sauvegarder une recette réglée au Studio sous un nom lisible | La relancer sur un autre eurio_id ou la référencer depuis le Benchmark |
| Training engineer | Entraîner un modèle avec `--aug-recipe my-red-tuned` | Reproduire un training exactement, et comparer deux recettes à pipeline constant |

## 5. Spec technique

### 5.1 API publique Python (freeze)

Les entités suivantes sont **publiques** (exportées depuis `ml/augmentations/__init__.py`) et **figées** : aucune rupture tant que les Blocs 2 & 3 ne sont pas délivrés, puis sémantique versionnée ensuite.

| Symbole | Statut | Contrat |
|---|---|---|
| `AugmentationPipeline` | figé | `__init__(recipe: dict, seed: int \| None)`, `generate(base_img, count=None) -> list[Image]` |
| `Augmentor` (ABC) | figé | `apply`, `maybe_apply`, `probability`, nouveau `get_schema()` classmethod |
| `PerspectiveAugmentor`, `RelightingAugmentor`, `OverlayAugmentor` | figés | Params nommés documentés, constructeur accepte `**params` (tolérance forward-compat) |
| `ZONE_RECIPES`, `DEFAULT_RECIPE` | figés | Shape de recipe ci-dessous |
| Dispatch `_DISPATCH` dans `pipeline.py` | interne | Les consommateurs externes passent par `AugmentationPipeline`, pas par le dispatch directement |

**Garanties** :

- La forme du recipe (`{count, layers: [{type, probability, ...params}]}`) ne changera pas de manière breaking sans bump explicite
- Les noms de layer types (`perspective`, `relighting`, `overlays`) sont gravés — on peut en ajouter, pas en renommer
- `generate()` retourne toujours `list[PIL.Image]` en mode RGB, même count que demandé

### 5.2 Format recipe JSON-serializable

Exemple commenté. Ce format est **identique** côté Python, côté API, côté DB :

```jsonc
{
  "count": 50,                      // nb de variations à générer par appel
  "layers": [
    {
      "type": "perspective",        // clé du dispatch dans pipeline.py
      "probability": 0.7,
      "max_tilt_degrees": 20
    },
    {
      "type": "relighting",
      "probability": 0.6,
      "ambient": 0.35,
      "max_elevation_deg": 60.0,
      "min_elevation_deg": 15.0,
      "intensity_range": [0.7, 1.1], // LISTE, pas tuple : JSON-friendly
      "normal_strength": 1.3,
      "smooth_sigma": 2.0
    },
    {
      "type": "overlays",
      "probability": 0.7,
      "categories": ["patina", "dust"],
      "opacity_range": [0.10, 0.30],
      "max_layers": 2
    }
  ]
}
```

**Contrainte "JSON-friendly"** : aucun tuple, aucun `np.float32`, aucun objet Python. Les Augmentors convertissent les listes reçues en tuples internes si besoin (cf. `RelightingAugmentor.__init__` qui accepte déjà une séquence).

### 5.3 Contrat d'introspection

Chaque classe `Augmentor` expose `get_schema()` (classmethod) qui retourne :

```jsonc
{
  "type": "relighting",             // identique à la clé _DISPATCH
  "label": "Re-lighting 2.5D",      // lisible humain, FR, pour UI
  "description": "Re-éclaire la pièce avec une lumière directionnelle dérivée d'un normal map Sobel.",
  "params": [
    {
      "name": "ambient",
      "type": "float",                // float | int | string | list[float] | list[string]
      "default": 0.35,
      "min": 0.0,
      "max": 1.0,
      "description": "Lumière ambiante de base (0 = noir dans les ombres, 1 = image plate)."
    },
    {
      "name": "intensity_range",
      "type": "list[float]",
      "default": [0.7, 1.1],
      "min": 0.0,
      "max": 2.0,
      "length": 2,                    // pour les ranges min/max
      "description": "Plage d'intensité appliquée après shading."
    }
    // …
  ]
}
```

L'endpoint `GET /augmentation/schema` agrège ces schemas pour tous les Augmentors enregistrés et retourne :

```jsonc
{
  "layers": [ /* un get_schema() par type */ ],
  "zones": ["green", "orange", "red"],
  "default_recipe": { /* ZONE_RECIPES["orange"] */ }
}
```

**Règle** : la source de vérité du schema est Python. Le Studio (Bloc 2) ne duplique jamais les bounds — il consomme cet endpoint au mount et génère ses sliders dynamiquement.

### 5.4 Endpoints FastAPI

Tous les endpoints sont servis par `ml/api/server.py` (pas un sous-module séparé pour rester cohérent avec `/training/*`, `/confusion-map/*`).

| Méthode | Route | Body/Params | Réponse |
|---|---|---|---|
| GET | `/augmentation/schema` | — | `{ layers, zones, default_recipe }` |
| GET | `/augmentation/overlays` | — | `{ patina: [paths], dust: [paths], scratches: [paths], fingerprints: [paths] }` — chemins relatifs à `ml/data/overlays/` |
| POST | `/augmentation/preview` | `{ recipe, eurio_id OR design_group_id, count?, seed? }` | `{ run_id, images: [{ index, url }], duration_ms, seed }` |
| GET | `/augmentation/preview/images/{run_id}/{index}` | — | `image/png` binary (sert depuis `ml/output/augmentation_previews/{run_id}/`) |
| GET | `/augmentation/recipes` | query `?zone=orange` | `[{ id, name, zone, config, created_at, updated_at, based_on_recipe_id }]` |
| GET | `/augmentation/recipes/{id}` | — | Recipe row complet |
| POST | `/augmentation/recipes` | `{ name, zone, config, based_on_recipe_id? }` | Recipe row créé |
| PUT | `/augmentation/recipes/{id}` | `{ name?, config? }` | Recipe row mis à jour |
| DELETE | `/augmentation/recipes/{id}` | — | `{ deleted: true }` |

**Notes** :

- `POST /augmentation/preview` valide le recipe contre le schema avant d'instancier (rejet 400 sur param inconnu ou hors bounds — on ne veut pas qu'un param aberrant pose en silence et casse un training plus tard)
- Les PNG de preview vivent sous `ml/output/augmentation_previews/{run_id}/{index}.png` et sont nettoyés par un job TTL (détail d'implém ; conceptuellement : les previews sont éphémères, les recipes sauvegardées sont durables)
- `/augmentation/overlays` est là pour que le Studio puisse afficher les textures disponibles (vignettes) et permettre à l'utilisateur de cocher/décocher des catégories

### 5.5 Schéma SQLite

Extension de `ml/state/schema.sql`. Les tables partagent la même base `training.db` (pas un second fichier — on veut un seul store local, un seul backup).

```sql
CREATE TABLE IF NOT EXISTS augmentation_recipes (
  id                    TEXT PRIMARY KEY,                  -- uuid hex 12 chars
  name                  TEXT NOT NULL UNIQUE,              -- lisible, ex: "red-tuned-v2"
  zone                  TEXT                               -- 'green'|'orange'|'red'|NULL (libre)
                        CHECK (zone IS NULL OR zone IN ('green','orange','red')),
  config_json           TEXT NOT NULL,                     -- le recipe JSON
  based_on_recipe_id    TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_augmentation_recipes_zone ON augmentation_recipes(zone);

CREATE TABLE IF NOT EXISTS augmentation_runs (
  id                TEXT PRIMARY KEY,                      -- run_id, uuid hex 12
  recipe_id         TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  eurio_id          TEXT,                                  -- un OU l'autre
  design_group_id   TEXT,
  count             INTEGER NOT NULL,
  seed              INTEGER,
  output_dir        TEXT NOT NULL,                         -- relatif à ml/output/
  status            TEXT NOT NULL
                    CHECK (status IN ('running','completed','failed')),
  error             TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_augmentation_runs_recipe ON augmentation_runs(recipe_id);
CREATE INDEX IF NOT EXISTS idx_augmentation_runs_created ON augmentation_runs(created_at DESC);
```

**Migration additive** sur les tables existantes (via `PRAGMA table_info` + `ALTER TABLE` idempotent côté Store bootstrap, SQLite ne supportant pas `ADD COLUMN IF NOT EXISTS`) :

```sql
-- Ajouté par Store._bootstrap si la colonne n'existe pas :
ALTER TABLE training_runs     ADD COLUMN aug_recipe_id TEXT
  REFERENCES augmentation_recipes(id) ON DELETE SET NULL;
ALTER TABLE training_staging  ADD COLUMN aug_recipe_id TEXT
  REFERENCES augmentation_recipes(id) ON DELETE SET NULL;
```

**Traçabilité** : `training_runs.aug_recipe_id` ferme la chaîne recipe → training_run → benchmark_run (cf. PRD03 §5.3 qui consomme `training_run_id` comme FK). Sans cette colonne, PRD03 ne peut pas drill-down "quel run de bench vient de quelle recette".

**Pourquoi SQLite, pas Supabase** : c'est de la donnée de tooling (training/calibration), strictement locale au poste du dev. Pas de partage multi-user, pas d'usage côté app Android. Ça cohabite proprement avec `training_runs` existant.

### 5.6 Intégration `train_embedder.py` + `/training/stage`

**Flag CLI `--aug-recipe`**, opt-in :

```
--aug-recipe <id_or_name>    # référence une recette stockée en SQLite
```

Comportement :

- Sans flag : comportement actuel inchangé (augmentations legacy rotation/color jitter/blur + augmented/ côté dataset)
- Avec flag : le dataloader applique `AugmentationPipeline(recipe).generate(...)` **en plus** des augmentations legacy (cf. note dans `recipes.py` : les deux couches se composent, l'avancée s'empile sur la legacy)
- La résolution `id_or_name` passe par le Store SQLite étendu (méthode `get_recipe(id_or_name)`)

**Extension `POST /training/stage`** :

```jsonc
// Avant
{ "items": [{ "class_id": "...", "class_kind": "eurio_id" }] }

// Après
{
  "items": [
    {
      "class_id": "...",
      "class_kind": "eurio_id",
      "aug_recipe_id": "red-tuned-v2"   // nouveau — id OU name, optionnel
    }
  ]
}
```

Le champ est résolu côté API (name ↔ id) avant persistence dans `training_staging.aug_recipe_id`. `null` ou absent = pas de recipe associée (comportement legacy).

**Propagation `TrainingRunner`** :

- Au `start_run`, le runner lit `aug_recipe_id` depuis les items `training_staging` collectés. Si une seule valeur distincte non-null est présente pour tous les items, elle est promue sur `training_runs.aug_recipe_id`. Sinon (hétérogène ou toutes null), le champ reste null (v1 = un seul recipe par run).
- Le flag `--aug-recipe` est ajouté à la commande `train_embedder.py` lors du step `Entraînement` si la recipe est résolue.
- Alternativement, `RunPayload.config.aug_recipe` peut forcer une recipe uniforme depuis l'endpoint `/training/run` (override des items).

**Non-régression** : aucune recette par défaut n'est appliquée. Les runs existants sans `aug_recipe_id` staged + sans flag produisent exactement les mêmes poids qu'avant.

## 6. Métriques de succès

Le bloc est considéré livré quand :

- `GET /augmentation/schema` retourne les 3 layers existants avec params complets, bounds et descriptions FR
- `POST /augmentation/preview` produit 16 images en ≤ 5s sur un eurio_id standard, répétable avec le même `seed`
- Une recette créée via `POST /augmentation/recipes` peut être rechargée via son `name` et exécutée par `preview_augmentations.py` (ie. la CLI existante accepte aussi un `--recipe <name>`)
- `train_embedder.py --aug-recipe <name>` tourne sans erreur et produit un `best_model.pth` utilisable par le reste de la pipeline
- Les tests de non-régression passent : sans `--aug-recipe`, training produit les mêmes métriques qu'avant (R@1 / R@3 sur test set actuel)

## 7. Dépendances

**Entrant** (ce dont ce bloc a besoin) :
- Phase 2 livrée (faite)
- Store SQLite existant `ml/state/store.py` (fait — à étendre)
- Augmentors livrés en `ml/augmentations/` (faits)

**Sortant** (ce qui dépend de ce bloc) :
- Bloc 2 (Studio admin) : consomme `/augmentation/schema`, `/augmentation/preview`, `/augmentation/recipes`, `/augmentation/overlays`
- Bloc 3 (Benchmark) : consomme la même API + `train_embedder.py --aug-recipe` pour orchestrer des grid searches

**Non-dépendances explicites** : pas de couplage avec Supabase, pas de couplage avec app-android, pas de couplage avec le prototype HTML.

## 8. Décisions (session 2026-04-19)

Tranchées avant implém :

1. **TTL des previews** sur disque : **24h**. Cleanup au démarrage du serveur FastAPI (`on_startup`) — balayage unique des dossiers `ml/output/augmentation_previews/*` dont `mtime > 24h`, supprimés avec leurs PNG. Le `ml/output/` est déjà `.gitignore` donc aucun risque de commit accidentel.
2. **Cap `count` côté API** : **64 max** (le Studio en demande 16 par run, 64 laisse de la marge). Au-delà → 400 avec message explicite.
3. **Validation bounds** : **rejet 400** (explicite > clamp silencieux). Un `ambient=1.5` remonte une erreur détaillée `{param: "ambient", got: 1.5, max: 1.0}` pour que le Studio puisse afficher côté UI.
4. **`based_on_recipe_id`** : automatique côté Studio lors d'un clone, champ **optionnel côté API** (pas d'enforcement serveur).
5. **Layer ordering** : **non v1**. L'ordre `perspective → relighting → overlays` est sémantiquement contraint (cf. commentaire `recipes.py`). Le Studio n'expose pas de drag & drop.

## 9. Voir aussi

- `docs/research/ml-scalability-phases/phase-2-augmentation.md` — spec fonctionnelle Phase 2
- `ml/augmentations/` — code du moteur (base, pipeline, recipes, augmentors)
- `ml/preview_augmentations.py` — CLI preview existante
- `ml/api/server.py` — patterns FastAPI (`/training/*`, `/confusion-map/*`) à mimer
- `ml/state/schema.sql` — schema SQLite à étendre
- `docs/augmentation-benchmark/02-augmentation-studio.md` — PRD Bloc 2 (Studio)
- `docs/augmentation-benchmark/03-real-photo-benchmark.md` — PRD Bloc 3 (Benchmark)
