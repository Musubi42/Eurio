# PRD Bloc 3 — Real Photo Benchmark

> Le **dyno** de la chaîne d'augmentation : un harnais d'évaluation qui prend un modèle ArcFace entraîné + une bibliothèque de photos réelles et produit des métriques objectives (R@1, R@3, R@5, spread top1-top2, matrice de confusion). Sans lui, calibrer les recettes du Bloc 2 est à l'aveugle.

---

## 1. Contexte & motivation

Les Blocs 1 et 2 livrent un moteur d'augmentation figé + un cockpit visuel pour tweaker les recettes `green` / `orange` / `red`. Mais **l'œil ne suffit pas** pour trancher : une recette qui produit des variantes "qui ont l'air réalistes" peut dégrader R@1 si elle déforme trop le signal distinctif. Inversement, une recette qui semble trop douce visuellement peut donner un meilleur généralisation parce qu'elle préserve les features.

Le pipeline d'augmentation actuel (`docs/research/ml-scalability-phases/phase-2-augmentation.md`) est calibré sur des métriques **de labo** : R@1 sur un test set dérivé des images Numista augmentées. Ce chiffre est optimiste et déconnecté de la distribution cible (l'utilisateur scanne sa pièce avec un capteur Android, dans sa lumière de salon, en tenant la pièce en main).

Le banc d'éval "in-the-wild" décrit dans `phase-4-subcenter-evalbench.md` répond à ce gap, mais à l'échelle de centaines de pièces et de dizaines de classes ArcFace. Ce PRD en réalise la **première version pragmatique** : 15-30 pièces physiques (5-10 par zone) que le dev possède, photographiées à la main, et utilisées comme **hold-out strict** pour piloter le tuning des recettes Bloc 2.

La logique de calibration est **par zone d'abord, globale ensuite** :

1. Entraîne un modèle sur les pièces vertes augmentées → bench sur photos réelles vertes → tweak recette `green` jusqu'à satisfaction.
2. Idem orange, puis rouge.
3. Modèle unifié sur l'union → bench global → valider que la composition tient.

Cette stratification permet d'isoler les effets de chaque recette sans que le bruit des autres zones pollue la décision.

---

## 2. Workflow utilisateur

### Phase setup (une fois, ~2h)

1. Le dev choisit ses pièces physiquement : **5 à 10 zone verte, 5 à 10 zone orange, 5 à 10 zone rouge**, selon ce qu'il possède. Les zones viennent de la cartographie Phase 1 (`/confusion-map`).
2. Il photographie chaque pièce sous conditions variées (5 axes documentés — éclairage, fond, angle, distance, état). Les règles complètes vivent dans **`real-photo-criteria.md`** (doc séparé, hors scope de ce PRD). Cible : 5-10 photos par pièce, ~150-300 photos au total.
3. Il dépose les fichiers dans `ml/data/real_photos/<eurio_id>/*.jpg` en suivant la convention de nommage de `real-photo-criteria.md`.
4. Un script `ml/check_real_photos.py` (fourni par ce bloc) valide la structure du dossier, affiche la couverture par zone et flag les pièces sans photos.

### Phase calibration (itérative, par zone)

5. Le dev entraîne un modèle ArcFace sur les pièces **vertes** uniquement, augmentées avec la recette `green` courante (via `train_embedder.py --aug-recipe green-vN` du Bloc 1).
6. Il lance `go-task ml:benchmark -- --model <version> --zones green` → le harnais évalue le modèle sur les photos réelles des pièces vertes.
7. Le rapport (JSON + vue admin) donne : R@1 global pour la zone, R@1 par pièce, matrice de confusion, top-20 photos foirées.
8. Il tweak la recette `green` dans le Studio (Bloc 2) → sauvegarde `green-vN+1` → retrain → rebench.
9. Il compare les deux runs côte à côte dans `/benchmark` : "vN+1 est +3.2 pts R@1 sur zone verte, décision : garder".
10. Idem pour orange, puis rouge. Chaque zone est validée indépendamment.

### Phase consolidation (une fois les 3 zones validées)

11. Le dev entraîne un 4ᵉ modèle sur **l'union des 15-30 pièces** avec les 3 recettes finales par zone.
12. Il lance `go-task ml:benchmark -- --model <version>` (full run, toutes zones) → rapport global.
13. Si R@1 global tient et que R@1 par zone reste proche des benchs isolés, la composition est validée. Sinon, retour à l'étape tweak.

### Phase vie courante

14. Chaque nouveau training run important (changement backbone, ajout de pièces, nouvelle recette) repasse par `go-task ml:benchmark`. Les runs historiques sont consultables dans `/benchmark` avec filtre par model et par zone, mode compare 2 runs côte à côte.

---

## 3. Scope in / out

### In (v1)

- **Bibliothèque de photos réelles** stockée sous `ml/data/real_photos/<eurio_id>/*.jpg`, convention de nommage définie dans `real-photo-criteria.md`.
- **Script Python `ml/evaluate_real_photos.py`** : stateless, CLI, prend un modèle + une liste de pièces/zones et sort un JSON rapport + persiste la métadonnée en SQLite.
- **Tables SQLite** (extension de `training.db` mutualisé avec Blocs 1 & 2) : `benchmark_runs`.
- **Endpoints FastAPI** `/benchmark/*` pour lancer un run, lister l'historique, drill-down un run, lister les photos disponibles par pièce.
- **Commande go-task** : `go-task ml:benchmark` avec flags `--model`, `--zones`, `--eurio-ids`, `--recipe`.
- **Vue admin `/benchmark`** :
  - Tableau historique des runs (model, recipe, R@1 global, R@1 par zone, date, durée).
  - Drill-down d'un run : R@k tables, matrice de confusion visuelle, top-20 photos foirées (thumbnail + ground truth + top-3 predictions).
  - **Compare mode binaire** : 2 runs côte à côte pour visualiser l'uplift d'un tweak de recette.
- **Strict hold-out** : gate dur dans le code du training pour exclure `ml/data/real_photos/` du dataset, documenté en gras dans le README ML et dans ce PRD.
- **Métrique primaire** : R@1 global **+ R@1 par zone** comme tableau de bord.

### Out (v2+)

- Upload des photos depuis l'admin UI (drag & drop, auto-assignation à un eurio_id). v1 reste **file-based** : le dev dépose les fichiers manuellement dans le dossier.
- Génération automatique d'un guide de shooting dans l'app Android (overlay caméra pour photographier sa collection). Hors scope — c'est un outil ad-hoc du dev, pas une feature user.
- **Benchmark continu / CI** : re-run auto à chaque retrain, alerte sur régression > X pts. v2.
- **Comparaison multi-runs (>2)** : pour l'instant, le mode compare est binaire (A vs B). Extension à N runs = v2.
- **Export des métriques** en CSV, PDF, Markdown. v2.
- **Scraping automatique de photos réelles** (eBay, forums, etc.). Explicitement hors scope — c'est le territoire de la Phase 3 du plan ML scalability, un autre chantier avec ses propres règles de curation.
- **Enrichissement via synthétique 3D Blender**. Phase 5 du plan ML scalability, hors ce bloc.

---

## 4. User stories

| # | Rôle | Veux | Pour |
|---|---|---|---|
| US1 | Dev | Déposer un dossier de photos réelles et avoir un check instantané "15 pièces couvertes, 234 photos, répartition green 5 / orange 4 / red 6" | Savoir si ma session de shooting est complète avant de lancer un bench |
| US2 | Dev | Lancer `go-task ml:benchmark --model <v> --zones green` en ligne de commande | Itérer sur la recette `green` sans quitter le terminal |
| US3 | Dev | Voir dans `/benchmark` le tableau des 8 derniers runs avec R@1 par zone en colonnes | Repérer visuellement quelle recette a donné quel gain |
| US4 | Dev | Cliquer un run et drill-down jusqu'aux 20 photos qui ont foiré | Comprendre **pourquoi** un run a un R@1 bas (mauvais angle ? lumière ? paire rouge ?) |
| US5 | Dev | Sélectionner 2 runs et les comparer côte à côte (R@1 par pièce, matrice de confusion diff) | Trancher objectivement "recette vN+1 bat vN sur zone rouge de +4 pts, je garde" |
| US6 | Dev | Être **absolument sûr** que mes photos réelles ne sont jamais utilisées pendant le training | Éviter le data leakage qui fausserait tous les benchs |

---

## 5. Spec technique

### 5.1 Bibliothèque de photos réelles

Structure stricte :

```
ml/data/real_photos/
├── <eurio_id_1>/
│   ├── 20260420_120500_indoor_cloth_tilt15.jpg
│   ├── 20260420_120612_outdoor_wood_flat.jpg
│   └── …
├── <eurio_id_2>/
│   └── …
└── _manifest.json          # auto-généré, pas versionné
```

- **Un dossier par eurio_id** (pas de design_group_id ici — on évalue sur des pièces physiques précises, pas des groupes abstraits).
- **Convention de nommage** détaillée dans `real-photo-criteria.md`. Ne pas dupliquer les règles ici ; ce PRD s'en tient au fait qu'il existe une convention et qu'un script de validation la lit.
- **`_manifest.json`** est régénéré par `ml/check_real_photos.py` à chaque ajout ; il contient la liste des photos avec leur zone (dérivée de la zone du eurio_id dans la cartographie) et les méta extraites du nom de fichier (condition, session).
- Les fichiers sont `.jpg` (acceptés aussi `.jpeg`, `.png`), résolution ≥ 800×800 px ; rejet au validateur sinon.
- **Versionnage git** : `ml/data/real_photos/` est **exclu** du versionning (photos trop lourdes, uniques au dev). Un backup local suffit. `_manifest.json` idem.

### 5.2 Script `evaluate_real_photos.py`

Fichier : `ml/evaluate_real_photos.py`. Stateless, CLI.

**Inputs** (args argparse) :

| Flag | Type | Description |
|---|---|---|
| `--model` | path | Chemin vers le checkpoint PyTorch (`best_model.pth`) OU le TFLite exporté. Auto-détection du format. |
| `--eurio-ids` | list (CSV) | Optionnel. Filtre les pièces évaluées. Sinon, prend toutes celles présentes dans `ml/data/real_photos/`. |
| `--zones` | list (CSV) | Optionnel. Filtre par zone (`green`, `orange`, `red`). Les deux filtres se combinent en AND. |
| `--recipe-id` | string | Optionnel. ID de la recette d'augmentation utilisée au training (persisté en SQLite pour traçabilité). |
| `--output-dir` | path | Par défaut `ml/reports/`. |
| `--run-id` | string | Optionnel. Si fourni, le run est stocké en SQLite sous cet id (sinon uuid généré). |
| `--top-confusions` | int | Par défaut 20. Nb de photos foirées à sortir dans le rapport. |

**Pipeline** :

1. Charge le modèle (TFLite ou PyTorch).
2. Charge les centroïdes connus (embeddings précalculés des pièces du training set).
3. Pour chaque photo réelle dans la sélection :
   - Détecte la pièce via YOLO (reuse du détecteur Phase 0) + crop carré.
   - Embed le crop via le modèle.
   - Matche contre tous les centroïdes : top-5 similarités cosinus triées.
4. Calcule les métriques agrégées (cf. §6).
5. Sort un JSON rapport sous `ml/reports/benchmark_<model_name>_<iso_timestamp>.json`.
6. Persiste la métadonnée du run en SQLite (table `benchmark_runs`, cf. §5.3).

**Exemple de rapport JSON** :

```jsonc
{
  "run_id": "b3f2e1a4c7d9",
  "model_path": "ml/checkpoints/arcface_v4_green.pth",
  "model_name": "arcface_v4_green",
  "recipe_id": "green-tuned-v3",
  "started_at": "2026-04-17T14:32:11Z",
  "finished_at": "2026-04-17T14:32:27Z",
  "duration_ms": 15840,
  "num_photos": 48,
  "num_coins": 6,
  "zones": ["green"],
  "metrics": {
    "r_at_1": 0.896,
    "r_at_3": 0.958,
    "r_at_5": 0.979,
    "mean_spread": 0.312,
    "median_spread": 0.284
  },
  "per_zone": {
    "green": { "r_at_1": 0.896, "num_photos": 48 }
  },
  "per_coin": [
    { "eurio_id": "FR-2e-2007", "r_at_1": 1.0, "num_photos": 8 },
    { "eurio_id": "DE-2e-2005", "r_at_1": 0.75, "num_photos": 8 }
  ],
  "confusion_matrix": {
    "FR-2e-2007": { "FR-2e-2007": 8 },
    "DE-2e-2005": { "DE-2e-2005": 6, "AT-2e-2005": 2 }
  },
  "top_confusions": [
    {
      "photo_path": "ml/data/real_photos/DE-2e-2005/20260420_outdoor_wood_tilt30.jpg",
      "ground_truth": "DE-2e-2005",
      "top_3": [
        { "eurio_id": "AT-2e-2005", "similarity": 0.612 },
        { "eurio_id": "DE-2e-2005", "similarity": 0.587 },
        { "eurio_id": "NL-2e-2005", "similarity": 0.423 }
      ],
      "spread": 0.025
    }
  ]
}
```

### 5.3 Schéma SQLite

Extension de `ml/state/schema.sql`. Partage `training.db` avec Blocs 1 & 2 (un seul store local, un seul backup).

```sql
CREATE TABLE IF NOT EXISTS benchmark_runs (
  id                  TEXT PRIMARY KEY,                    -- run_id, uuid hex 12
  model_path          TEXT NOT NULL,                        -- chemin relatif au repo
  model_name          TEXT NOT NULL,                        -- ex: "arcface_v4_green"
  training_run_id     TEXT REFERENCES training_runs(id) ON DELETE SET NULL,
  recipe_id           TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  eurio_ids_json      TEXT NOT NULL,                        -- JSON list des pièces évaluées
  zones_json          TEXT NOT NULL,                        -- JSON list des zones filtrées
  num_photos          INTEGER NOT NULL,
  num_coins           INTEGER NOT NULL,
  r_at_1              REAL,
  r_at_3              REAL,
  r_at_5              REAL,
  mean_spread         REAL,
  per_zone_json       TEXT NOT NULL,                        -- {"green": {"r_at_1": 0.89, ...}, ...}
  per_coin_json       TEXT NOT NULL,                        -- [{"eurio_id": "...", "r_at_1": ...}, ...]
  confusion_json      TEXT NOT NULL,                        -- matrice de confusion
  top_confusions_json TEXT NOT NULL,                        -- top-N photos foirées
  report_path         TEXT NOT NULL,                        -- chemin vers le JSON complet
  status              TEXT NOT NULL
                      CHECK (status IN ('running','completed','failed')),
  error               TEXT,
  started_at          TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_model ON benchmark_runs(model_name);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_recipe ON benchmark_runs(recipe_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_started ON benchmark_runs(started_at DESC);
```

**Traçabilité** : chaque run de bench référence le `training_run_id` (Bloc 1 existant) qui a produit le modèle, qui lui-même référence `recipe_id` (Bloc 1/2). Cela ferme la boucle "cette recette → ce training → ce bench".

**Pourquoi SQLite, pas Supabase** : données de tooling strictement locales, pas de partage multi-user, pas d'usage côté app Android. Cohérent avec `training_runs` et `augmentation_recipes`.

### 5.4 Endpoints FastAPI

Tous servis par `ml/api/server.py`, cohérent avec `/training/*`, `/confusion-map/*`, `/augmentation/*`.

| Méthode | Route | Body/Params | Réponse |
|---|---|---|---|
| POST | `/benchmark/run` | `{ model_path, eurio_ids?, zones?, recipe_id?, top_confusions? }` | `{ run_id, status: "running" }` (lancement background) |
| GET | `/benchmark/runs` | query `?model_name=…&zone=…&recipe_id=…&limit=50&offset=0` | `[{ run_id, model_name, recipe_id, r_at_1, per_zone, started_at, status, … }]` |
| GET | `/benchmark/runs/{id}` | — | Run row complet + top-N confusions |
| GET | `/benchmark/runs/{id}/report` | — | JSON rapport complet (depuis le fichier) |
| GET | `/benchmark/photos/{eurio_id}` | — | `{ eurio_id, zone, photos: [{ path, size, session_id, conditions: {…} }] }` |
| GET | `/benchmark/photos/thumbnail/{path}` | — | `image/jpeg` (sert depuis `ml/data/real_photos/`, chemin hashé pour sécurité) |
| DELETE | `/benchmark/runs/{id}` | — | `{ deleted: true }` (supprime la ligne SQLite + le fichier rapport) |

**Notes** :

- `POST /benchmark/run` est non-bloquant (lance en background via le même pattern que `/training/run`) ; le dev poll `/benchmark/runs/{id}` ou regarde `/benchmark` en live.
- `/benchmark/photos/{eurio_id}` est **read-only** en v1 (le dev dépose les fichiers manuellement). v2 ajoutera un POST pour upload.
- Le thumbnail endpoint sert les photos compressées (100 KB max) pour l'affichage admin ; l'image originale n'est jamais exposée à un navigateur externe.

### 5.5 Commandes go-task

Ajouts dans `ml/Taskfile.yml` :

```yaml
ml:benchmark:
  desc: "Run a benchmark against real photos. Usage: go-task ml:benchmark -- --model <path> [--zones green,orange] [--eurio-ids …]"
  cmd: python ml/evaluate_real_photos.py {{.CLI_ARGS}}

ml:benchmark:photos:check:
  desc: "Validate structure of ml/data/real_photos/ and regenerate _manifest.json"
  cmd: python ml/check_real_photos.py
```

Le dispatch est transparent : le script est stateless, la SQLite est mise à jour par le script lui-même.

### 5.6 Vue admin `/benchmark`

Route `/benchmark`, feature module `admin/packages/web/src/features/benchmark/`.

**Layout** :

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Benchmark — Real Photo Hold-out                             [ML: online]    │
│  24 runs historiques · 18 pièces couvertes · 287 photos en library           │
│  ─────────                                                                    │
│                                                                               │
│  Filter: [ model ▾ ] [ zone ▾ ] [ recipe ▾ ]    [ + New run ]   [ Compare ] │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Model          Recipe         R@1 global  R@1 G  R@1 O  R@1 R  Date   │ │
│  │  ────────────────────────────────────────────────────────────────────  │ │
│  │  arcface_v4_all green-v3/…   87.4%        92.1%  85.0%  78.9%  4d ago │ │
│  │  arcface_v4_red red-tuned-v2 —            —      —      82.3%  2h ago │ │
│  │  arcface_v4_red red-tuned-v1 —            —      —      79.1%  3h ago │ │
│  │  …                                                                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Page drill-down `/benchmark/runs/:id`** :

- Header : model, recipe, training_run_id lié (cliquable → `/training`), dates, durée.
- Cartes métriques en haut : R@1, R@3, R@5 global + spread moyen. Chaque carte a un tooltip formule.
- Section **Par zone** : tableau R@1 par zone avec bars visuelles.
- Section **Par coin** : tableau par `eurio_id` avec R@1 + nb photos.
- Section **Matrice de confusion** : heatmap (cohérence avec `ConfusionMapPage`, palette identique).
- Section **Top-20 photos foirées** : grille de vignettes. Chaque tuile contient thumbnail photo + badge ground truth + top-3 predictions avec similarités. Clic → lightbox.

**Compare mode `/benchmark/compare?a=<id>&b=<id>`** :

- Header : les deux runs côte à côte (model + recipe + date).
- Tableau diff des métriques : R@1 / R@3 / R@5 global + par zone, avec delta (+3.2 pts en vert, -1.1 pts en rouge).
- Tableau par coin : chaque ligne a R@1 A, R@1 B, delta. Highlight en rouge si régression.
- Matrices de confusion côte à côte, même palette, synchronisation du hover (hover case (i,j) dans A → highlight case (i,j) dans B).
- Top-20 confusions par run empilées ou en onglets.

**Dégradation ML API offline** :

- Banner rouge full-width + tableau grisé (pattern `ConfusionMapPage`, `TrainingPage`).
- Les runs historiques restent consultables en mode lecture (car la liste vit en SQLite locale côté serveur ML — si serveur off, alors plus rien ne s'affiche).

**Design tokens** (cohérence Blocs précédents) :

- Brand indigo-700 sur CTA `New run` et compare actif.
- Zones : `--success` / `--warning` / `--danger` sur les badges par zone (`zoneStyle()` déjà exporté).
- Hairline gold sous le header (cohérence `ConfusionMapPage`, `AugmentationStudioPage`).
- Shadow `--shadow-sm` / `--shadow-card` sur les cartes.
- Font-display italic sur les titres de sections.

---

## 6. Métriques calculées en détail

### Recall@K

Pour chaque photo réelle `p` avec ground truth `gt(p)` et top-K predictions `pred_1, …, pred_K` (triées par similarité cosinus décroissante) :

```
hit_K(p) = 1 si gt(p) ∈ {pred_1, …, pred_K}
         = 0 sinon

R@K = mean(hit_K(p) for p in photos)
```

Calculé globalement, par zone, et par pièce (eurio_id).

### Spread top1-top2

Pour chaque photo :

```
spread(p) = similarity(pred_1) - similarity(pred_2)
```

Métrique de confiance : spread élevé = le modèle est confiant, spread faible = hésitation entre deux candidats proches (typique paire rouge).

Agrégats : `mean_spread`, `median_spread`, distribution en 5 buckets (`[0, 0.05], [0.05, 0.1], …`).

### Matrice de confusion

Dict-of-dicts `{ ground_truth: { predicted_top1: count } }`. Chaque cellule `(i, j)` compte le nb de photos de la pièce `i` matchées top-1 sur la pièce `j`. Diagonale = correct, hors-diagonale = confusion.

Visualisation : heatmap carrée, color scale du blanc (0) vers rouge (max), diagonale ignorée dans le scaling pour ne pas écraser la colormap.

### Top-N confusions

Les N photos avec le plus faible spread **ET** incorrectes (top-1 ≠ ground truth). Sorties avec thumbnail, ground truth, top-3 predictions, similarités brutes.

---

## 7. Règles strictes

### R1. Strict hold-out des photos réelles

> Les photos présentes dans `ml/data/real_photos/` **ne sont JAMAIS utilisées pour le training**.

Implémentation :

- `ml/prepare_dataset.py` et `ml/train_embedder.py` doivent **exclure explicitement** le path `ml/data/real_photos/` de toute lecture training. Assertion au démarrage du training : si un sample résolu pointe vers ce dossier, erreur fatale "data leak detected".
- Le `.gitignore` exclut le dossier pour éviter un commit accidentel qui pourrait le rendre ambigu.
- La doc README (`ml/README.md`) et ce PRD gravent la règle en gras.
- Tests de non-régression à ajouter : un test unitaire vérifie que `prepare_dataset` ne retourne jamais un path contenant `real_photos`.

Motivation : le banc perd toute valeur si les photos réelles fuitent dans le training. Une fois une photo vue en training, le modèle la reconnaît par cœur → R@1 gonflé artificiellement → tuning des recettes orienté vers de l'overfit. **Dette de dette**.

### R2. Split par session de shooting, pas par photo

Quand le dev prend 8 photos d'une même pièce pendant la même session (5 minutes, même éclairage, même fond, même main), ces photos partagent du contexte. Si on agrège naïvement R@1 sur ces 8 photos, une seule session "facile" gonfle le chiffre.

Mitigation (v1) : `real-photo-criteria.md` impose **≥ 2 sessions distinctes** par pièce (ex: une session indoor, une outdoor, à des moments différents). Le validateur `check_real_photos.py` flag les pièces avec < 2 sessions.

Pour v2 : les métriques pourront être calculées **par session d'abord, puis moyennées entre sessions** (évite qu'une session avec 12 photos pèse 3× plus qu'une session avec 4 photos).

### R3. Métriques par zone obligatoires

R@1 global est un chiffre trompeur quand les zones ne sont pas représentées également. Si 60% des photos sont zone verte, R@1 global bouge principalement avec la recette `green` et masque les régressions sur `red`.

Tout rapport de bench **doit** afficher R@1 par zone. Le tableau admin ne doit pas permettre de masquer ces colonnes.

### R4. Pas de crawling

Les photos sont **prises par le dev lui-même**, sur ses propres pièces. Pas de scraping eBay, Numista, forums. Motivation : les photos crawlées ont des biais de curation (vendeurs pros qui prennent de belles photos en studio) et ne reflètent pas la distribution "utilisateur lambda avec son téléphone". Ce canal existe mais relève de la Phase 3 du plan ML scalability, hors de ce bloc.

---

## 8. Métriques de succès (du bloc lui-même)

Observées localement par le dev :

| Métrique | Cible |
|---|---|
| Temps session de shooting 15 pièces → bench initial prêt | ≤ 2h (dont ~1h30 shooting + 30 min organisation) |
| Durée d'un run de bench (15 pièces, ~150 photos) | ≤ 30 s (hors warmup modèle) |
| Durée d'un run de bench (30 pièces, ~300 photos) | ≤ 60 s |
| Capacité à trancher "recette A > recette B pour zone rouge" avec confiance | Oui, delta ≥ 2 pts R@1 considéré significatif |
| Nb d'itérations de tuning par zone avant recette validée | 3-5 en moyenne |
| Utilisation du mode compare | ≥ 1 fois par itération tuning |
| Fuite training → eval (photo `real_photos` utilisée en training) | **Zéro**, gate assertionné |

---

## 9. Dépendances

### Bloc 1 (backend pipeline) — requis

- Store SQLite `training.db` existant (partagé) pour y ajouter la table `benchmark_runs`.
- Pattern FastAPI des endpoints `/augmentation/*` et `/training/*` à mimer pour `/benchmark/*`.
- Table `augmentation_recipes` pour foreign key `benchmark_runs.recipe_id`.
- Table `training_runs` pour foreign key `benchmark_runs.training_run_id`.

### Bloc 2 (Augmentation Studio) — complémentaire

- Pas de dépendance dure. Le Studio fonctionne sans le Bloc 3, mais son usage est aveugle sans lui.
- Inversement, le Bloc 3 fonctionne sans le Studio (le dev peut tuner les recettes à la main dans `recipes.py` ou via CLI). Mais la boucle `Studio tweak → retrain → bench → compare` est 10× plus rapide que sans Studio.
- Handshake : le `recipe_id` persisté dans `benchmark_runs` permet le drill-down "quel run de bench utilise telle recette".

### Document annexe `real-photo-criteria.md`

À **créer en parallèle**, hors du scope de ce PRD. Ce PRD se contente de **référencer** le fichier pour :

- Les règles de shooting (5 axes : éclairage, fond, angle, distance, état).
- La convention de nommage des fichiers (`YYYYMMDD_HHMMSS_<condition>_<...>.jpg`).
- La règle minimale de 2 sessions par pièce (cf. §7 R2).

**Ne pas dupliquer** ces règles dans ce PRD — elles vivent ailleurs et évolueront indépendamment.

### Infrastructure

- YOLO11-nano déjà déployé (Phase 0) pour la détection initiale pendant le bench.
- Modèle ArcFace + extraction d'embeddings déjà en place (`ml/compute_embeddings.py`, `ml/train_embedder.py`).

---

## 10. Questions ouvertes

| # | Question | Blocage | Proposition par défaut |
|---|---|---|---|
| Q1 | Le rapport JSON doit-il contenir l'embedding brut de chaque photo pour post-mortem ? | Débat sur taille des rapports | Non en v1 — les embeddings sont recalculables à la demande depuis la photo. Trop lourd en stockage. |
| Q2 | Les thumbnails servis par `/benchmark/photos/thumbnail/{path}` sont-ils cachés sur disque ou générés à la demande ? | Performance | Cache disque TTL 24h sous `ml/output/benchmark_thumbnails/` (pattern des previews augmentation). |
| Q3 | Que fait-on si un `eurio_id` présent dans `real_photos/` n'existe plus dans le référentiel Supabase (pièce obsolète) ? | Edge case | Skip la pièce avec un warning dans le rapport. Ne pas crasher. |
| Q4 | Faut-il un endpoint `GET /benchmark/runs/compare?a=<id>&b=<id>` qui renvoie le diff directement, ou le diff est-il calculé côté Vue ? | Perf + architecture | Calculé côté Vue en v1 (tableaux max ~30 lignes). Backend si > 100 pièces. |
| Q5 | Les photos réelles sont-elles pertinentes pour être photographiées **avers ET revers** ? Ou une seule face par photo ? | Produit | Les deux faces — la convention de nommage intègre un flag `face=obverse|reverse`. Déplacé au doc `real-photo-criteria.md`. |
| Q6 | Doit-on persister les 48 similarités (tous les centroïdes) pour chaque photo ou seulement le top-5 ? | Stockage vs flexibilité | Top-5 en v1. Si besoin d'analyses plus fines, v2 persiste top-50. |
| Q7 | Quelle est la stratégie de naming des modèles (`arcface_v4_green` vs `arcface_v4_all`) ? | Cohérence | À figer dans `training_runs` côté Bloc 1 — ce PRD consomme ce qui existe. |
| Q8 | Le drill-down "top-20 photos foirées" doit-il permettre d'ajouter une note/tag ("mauvaise prise de vue, à refaire") directement dans la vue admin ? | UX bonus | Non en v1 — le dev maintient ses notes ailleurs. v2 si besoin. |

---

## 11. Voir aussi

- [`docs/augmentation-benchmark/01-backend-pipeline.md`](./01-backend-pipeline.md) — PRD Bloc 1, contrat HTTP et SQLite partagé.
- [`docs/augmentation-benchmark/02-augmentation-studio.md`](./02-augmentation-studio.md) — PRD Bloc 2, cockpit visuel qui alimente la boucle de tuning.
- [`docs/augmentation-benchmark/real-photo-criteria.md`](./real-photo-criteria.md) — règles de shooting et convention de nommage (doc séparé, à créer en parallèle).
- [`docs/research/ml-scalability-phases/phase-4-subcenter-evalbench.md`](../research/ml-scalability-phases/phase-4-subcenter-evalbench.md) — spec initiale du banc in-the-wild, dont ce bloc est la première réalisation pragmatique.
- [`docs/research/ml-scalability-phases/phase-2-augmentation.md`](../research/ml-scalability-phases/phase-2-augmentation.md) — contexte Phase 2, les recettes qu'on calibre ici.
- [`ml/evaluate.py`](../../ml/evaluate.py) — pattern d'éval existant (test set synthétique), à ne pas confondre avec ce banc.
- [`ml/api/training_runner.py`](../../ml/api/training_runner.py) — pattern runner async + SQLite à mimer pour `/benchmark/run`.
- [`ml/confusion_map.py`](../../ml/confusion_map.py) — pattern script Python stateless + écriture SQLite.
- [`admin/packages/web/src/features/confusion/pages/ConfusionMapPage.vue`](../../admin/packages/web/src/features/confusion/pages/ConfusionMapPage.vue) — référence design pour heatmap, shimmer, palette zones.
- [`shared/tokens.css`](../../shared/tokens.css) — tokens référencés.
- **R1 proto-first non applicable** : `/benchmark` est une vue admin, pas une scène de l'app Android. La règle proto s'applique à l'UX user ; ce cockpit sert exclusivement le dev.
