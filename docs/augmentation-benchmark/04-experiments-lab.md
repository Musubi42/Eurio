# PRD Bloc 4 — Lab & Experiments

> La **couche narrative** au-dessus des Blocs 1-3. Jusqu'ici on avait 3 outils indépendants (Studio / Training / Benchmark) mais aucune structure pour répondre "qu'est-ce qui a bougé la précision ?". Le Lab introduit deux entités (cohort, itération) qui relient recipe → training → benchmark comme **une seule expérience traçable**, calculent le verdict automatiquement, et agrègent les leviers qui comptent.

---

## 1. Contexte & motivation

Après les Blocs 1-3 on peut : tweaker une recette dans le Studio, lancer un training, benchmarker sur photos réelles. Mais **rien ne relie les trois**. Quand le dev fait 10 essais, il se retrouve avec 10 lignes dans 3 tables différentes à cross-référencer à la main. Pas de mémoire de **pourquoi** il a fait l'essai, pas de calcul automatique du delta vs essai précédent, pas d'agrégat "tel paramètre a bougé R@1 de +X en moyenne".

Le Lab traite ce gap avec deux abstractions :

1. **Cohort** : ensemble figé d'eurio_ids qui partagent un challenge (zone, pays, décennie). Frozen : si tu veux ajouter des coins, tu forks — pas d'édition in-place pour garantir la comparabilité entre itérations.
2. **Iteration** : un passage de la chaîne `stage → train → bench → verdict` avec une hypothèse, des inputs (recipe, variant_count, training_config), et une sortie (verdict + delta vs parent + diff d'inputs).

Le dev arrête de jouer au détective sur 3 onglets : il lance une itération, observe le verdict dans une page, comprend ce qu'il a changé et ce que ça a donné.

---

## 2. Workflow utilisateur

### Phase setup (une fois par cohort)

1. Le dev sélectionne 3-10 pièces dans `/coins` qui ont déjà leurs photos réelles (bibliothèque Bloc 3).
2. Clic "Nouveau cohort Lab" dans le footer sticky → wizard `/lab/cohorts/new?eurio_ids=…`.
3. Il nomme le cohort (kebab-case), choisit la zone, valide. Un badge indique quelles pièces ont (ou n'ont pas) de photos — soft-gate, il peut créer malgré tout.

### Phase itérative (la boucle)

4. Dans `/lab/cohorts/:id`, clic "Nouvelle itération".
5. Wizard pré-rempli depuis la dernière itération. Il ajuste 1-2 paramètres (recipe, variant_count, epochs) et formule une **hypothèse** ("bumper max_tilt à 25° devrait fermer le gap sur photos 45°").
6. Clic "Lancer" → l'orchestrateur backend enchaîne : stage cohort + recipe → training → benchmark → verdict + delta.
7. La page cohort poll toutes les 4s ; les statuts passent `training` → `benchmarking` → `completed` (ou `failed`).
8. Une fois terminée, l'itération apparaît avec son verdict (`better` / `worse` / `mixed` / `no_change` / `baseline`), son delta R@1 vs parent, et le diff d'inputs visualisé en chips.

### Phase analyse

9. Clic sur une ligne → drill-down `/lab/cohorts/:id/iterations/:iter` :
   - Cartes R@k + delta vs parent
   - Table R@1 par zone + par pièce (avec delta)
   - **Section "Par axe de variabilité"** : lighting / background / angle / distance / state — R@1 par valeur d'axe. C'est ici que "R@1 = 82% global" devient "R@1 à 45° = 45%, à 0° = 98% → la recette perspective est sous-calibrée".
   - Notes éditables + override manuel du verdict
10. Le **SensitivityPanel** sur la page cohort agrège tous les (iter, parent) pour montrer quel paramètre a le plus bougé R@1 en moyenne : "variant_count ×2 (3 obs) : +1.2pts", "max_tilt 15→25° (2 obs) : +4.0pts".

---

## 3. Scope in / out

### In (v1)

- Table `experiment_cohorts` + `experiment_iterations` (SQLite, extension `training.db`).
- Migration additive `benchmark_runs.per_condition_json`.
- Store CRUD complet (Python dataclasses + méthodes).
- Enrichissement `evaluate_real_photos.py` : parse des axes via `ml/real_photo_meta.py`, calcul `per_condition` (R@1 par lighting / background / angle / distance / state).
- Logique pure dans `ml/api/iteration_logic.py` : `compute_verdict`, `compute_delta`, `compute_input_diff`, `compute_sensitivity`.
- Orchestrateur `ml/api/iteration_runner.py` : chain training → bench, verrou global (1 itération à la fois), recovery au boot de l'API.
- Routes `/lab/*` dans FastAPI : CRUD cohorts + iterations + trajectory + sensitivity + runner status.
- UI admin `features/lab/` : 4 pages, 6 composants, composable API.
- Réutilisation du `PerConditionTable` dans `/benchmark/runs/:id` aussi.
- CTA "Nouveau cohort Lab" dans le footer sticky de `/coins`.
- Entrée navbar "Lab" (icône FlaskConical).

### Out (v2+)

- **Itérations parallèles** : v1 = 1 globale à la fois (lock process-wide). Le checkpoint `best_model.pth` est partagé et l'M4 ne peut entraîner qu'un modèle à la fois de toute façon.
- **Fork de cohort automatique** avec préservation des itérations parent : v1 c'est du copier-coller manuel (créer un nouveau cohort avec une liste eurio_ids modifiée).
- **Heuristiques d'interprétation automatique** ("45% des top confusions ont spread<0.05 → modèle incertain, suggère plus de diversité") : v2. La donnée est là (per_condition + top_confusions), on peut ajouter des cards de suggestion plus tard.
- **Export d'un rapport PDF d'expérience** : v2.
- **Graphes avancés** (violin plots par axe, matrice confusion diff en compare) : v2.
- **Comparaison multi-runs (>2)** : compare binaire stays in `/benchmark`, pas étendu au Lab v1.
- **Recette diff visuel dans le wizard iteration** : pour l'instant on affiche juste `{before: X, after: Y}` par path. Rendu plus joli (slider-style) = v2.

---

## 4. User stories

| # | Rôle | Veux | Pour |
|---|---|---|---|
| US1 | Dev | Figer 5 pièces rouges comme "bench de calibration zone rouge" | Itérer dessus sans changer la base d'un essai à l'autre |
| US2 | Dev | Créer une nouvelle itération en modifiant 1 paramètre | Isoler l'effet de ce paramètre |
| US3 | Dev | Voir le verdict `better`/`worse` calculé automatiquement | Décider rapide si je garde ou rollback |
| US4 | Dev | Lire le delta R@1 par zone et par pièce vs parent | Repérer régressions cachées derrière un gain global |
| US5 | Dev | Voir R@1 par angle (0°/15°/30°/45°) | Comprendre quelle condition limite mon modèle |
| US6 | Dev | Voir "variant_count ×2 donne en moyenne +1pt" sur les 3 essais passés | Arrêter de tester ce levier si faible leverage |
| US7 | Dev | Ajouter une note libre sur une itération | Garder un cahier de labo |
| US8 | Dev | Override manuel du verdict | Quand je vois une subtilité que l'auto ne capture pas |

---

## 5. Spec technique

### 5.1 Schéma SQLite

Deux nouvelles tables + une colonne additive sur `benchmark_runs`.

```sql
CREATE TABLE experiment_cohorts (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL UNIQUE,
  description         TEXT,
  zone                TEXT CHECK (zone IS NULL OR zone IN ('green','orange','red')),
  eurio_ids_json      TEXT NOT NULL,        -- frozen list
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE experiment_iterations (
  id                        TEXT PRIMARY KEY,
  cohort_id                 TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,
  parent_iteration_id       TEXT REFERENCES experiment_iterations(id) ON DELETE SET NULL,
  name                      TEXT NOT NULL,
  hypothesis                TEXT,
  recipe_id                 TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  variant_count             INTEGER NOT NULL DEFAULT 100,
  training_config_json      TEXT NOT NULL DEFAULT '{}',
  status                    TEXT NOT NULL
                            CHECK (status IN ('pending','training','benchmarking','completed','failed')),
  training_run_id           TEXT REFERENCES training_runs(id) ON DELETE SET NULL,
  benchmark_run_id          TEXT REFERENCES benchmark_runs(id) ON DELETE SET NULL,
  verdict                   TEXT
                            CHECK (verdict IN ('pending','baseline','better','worse','mixed','no_change')),
  verdict_override          TEXT,                              -- override manuel
  delta_vs_parent_json      TEXT NOT NULL DEFAULT '{}',        -- {r_at_1, per_zone, per_coin, ...}
  diff_from_parent_json     TEXT NOT NULL DEFAULT '{}',        -- {path: {before, after}, ...}
  notes                     TEXT,
  error                     TEXT,
  created_at                TEXT NOT NULL DEFAULT (datetime('now')),
  started_at                TEXT,
  finished_at               TEXT
);

-- migration additive sur benchmark_runs (via _ensure_column)
ALTER TABLE benchmark_runs ADD COLUMN per_condition_json TEXT NOT NULL DEFAULT '{}';
```

### 5.2 Logique — verdict

```
Δ_global = iter.r_at_1 - parent.r_at_1
Δ_per_zone = {z: iter.zones[z] - parent.zones[z]}

verdict =
  "better"     si Δ_global ≥ +0.02 ET aucun Δ_zone < -0.03
  "worse"      si Δ_global ≤ -0.02
  "mixed"      si Δ_global ∈ [-0.02, +0.02] ET ∃ Δ_zone avec |Δ| ≥ 0.02
             OU si Δ_global ≥ +0.02 mais une zone régresse > 3pts
  "no_change"  si tous les |Δ| < 0.005
  "baseline"   si parent est absent
  "pending"    si benchmark pas fini
```

Seuils :
- `SIGNIFICANT_DELTA = 0.02` (2pts R@1)
- `NOISE_BAND = 0.005` (0.5pt)
- `ZONE_REGRESSION_THRESHOLD = 0.03` (3pts)

Définis dans `ml/api/iteration_logic.py` et modifiables au besoin.

### 5.3 API

```
GET    /lab/cohorts                                  # list (avec iteration_count + best_r_at_1)
POST   /lab/cohorts                                  # create
GET    /lab/cohorts/{id_or_name}                     # detail
PUT    /lab/cohorts/{id}                             # update metadata (eurio_ids FROZEN)
DELETE /lab/cohorts/{id}                             # cascade

GET    /lab/cohorts/{id}/iterations                  # list
POST   /lab/cohorts/{id}/iterations                  # create + launch chain
GET    /lab/cohorts/{id}/iterations/{iter}           # detail (avec benchmark + training summary embedded)
PUT    /lab/cohorts/{id}/iterations/{iter}           # update notes + verdict_override
DELETE /lab/cohorts/{id}/iterations/{iter}           # delete (rejeté si en cours)

GET    /lab/cohorts/{id}/trajectory                  # compact timeseries pour chart
GET    /lab/cohorts/{id}/sensitivity                 # computed parametric leverage

GET    /lab/runner/status                            # {busy: bool}
```

Body `POST /lab/cohorts/{id}/iterations` :

```jsonc
{
  "name": "green-v3 more variants",
  "hypothesis": "Doubler variant_count devrait fermer le gap sur angle=45°",
  "parent_iteration_id": "abc123",   // optional
  "recipe_id": "green-tuned-v2",     // optional — id or name
  "variant_count": 200,
  "training_config": { "epochs": 40, "batch_size": 256, "m_per_class": 4 }
}
```

Retour immédiat : `{ iteration_id, status: "pending" }`. Poll GET pour voir les transitions.

### 5.4 UI

**Navbar** : `/lab` sous "Outils", icône `FlaskConical`.

**`/lab`** — grid de `CohortCard`. Stats rapides (N cohorts, N iterations, best R@1 global). Filter par zone. Status pill ML API + Runner.

**`/lab/cohorts/new`** — wizard : nom, description, zone, eurio_ids (textarea ou prefill depuis `?eurio_ids=`), badges photo-ready via `/benchmark/library`.

**`/lab/cohorts/:id`** — **la vue clé** :
- Header : nom + zone + coin list + CTA new iteration + delete
- `TrajectoryChart` SVG : waterfall R@1 ordre chrono, dot color = verdict
- Table des itérations : nom/hypothèse, diff d'inputs en chips, R@1 + delta, verdict badge, date
- `SensitivityPanel` à droite : paramètres triés par |avg ΔR@1|

**`/lab/cohorts/:id/iterations/new`** — wizard :
- Nom + hypothèse
- Parent (default: dernière)
- Recipe (dropdown existantes OU lien Studio nouvel onglet)
- Variant count (slider 50-500)
- Training config (epochs / batch / m-per-class)
- Preview diff vs parent en bas

**`/lab/cohorts/:id/iterations/:iter`** :
- Cartes R@k + delta vs parent
- Inputs card (recipe, variant_count, training_config, training run link)
- Delta par zone + par pièce
- `PerConditionTable` — R@1 par valeur d'axe (réutilisé de Bloc 3)
- Sidebar : notes éditables + verdict override

### 5.5 Orchestrateur (`iteration_runner.py`)

Daemon thread par itération, global lock pour 1 à la fois. Séquence :

1. `status=training` — call `TrainingRunner.start_run(added, removed=[], config)` avec `target_augmented=variant_count` + `aug_recipe=recipe_id`. Poll `store.get_run(id)` toutes les 5s.
2. `status=benchmarking` — spawn `evaluate_real_photos.py` subprocess (même pattern que `benchmark_routes._launch_run`). Stamp `training_run_id` sur la `benchmark_run` après succès. Poll.
3. `status=completed` — fetch parent metrics, compute `verdict` + `delta_vs_parent` + `diff_from_parent`, persist.

**Recovery au boot** : `recover_on_boot()` scanne `status IN ('training','benchmarking')` et relance les threads. Pattern appelé depuis `app.on_event('startup')` dans `server.py`.

Échec à chaque étape → `status=failed`, `error` rempli, lock libéré.

---

## 6. Règles strictes

### R1. Cohort.eurio_ids est frozen

L'API refuse toute modif de `eurio_ids` via `PUT /lab/cohorts/{id}`. La seule voie pour changer l'ensemble = créer un nouveau cohort (fork manuel). Motivation : sans ça, les métriques entre itérations ne sont plus comparables.

### R2. Une seule itération globale à la fois

`iteration_runner` a un `threading.Lock` process-wide. `POST /lab/.../iterations` retourne 409 si `runner.is_busy()`. Motivation : le checkpoint `best_model.pth` est partagé ; l'M4 ne peut entraîner qu'un modèle à la fois.

### R3. Le training runner iterations-only ne passe PAS par la staging table globale

Le Lab appelle `TrainingRunner.start_run(added=..., removed=[], config=...)` directement avec les ClassRef du cohort, **sans** remplir `training_staging`. Ça évite de clobber un staging en cours depuis `/coins` → "Ajouter au training".

### R4. Recovery au boot obligatoire

Sans recovery, un reload `go-task ml:api` au milieu d'une itération l'abandonnerait en `training` ou `benchmarking` à jamais. Le startup hook est non-négociable.

---

## 7. Métriques de succès (du bloc lui-même)

| Métrique | Cible |
|---|---|
| Temps wizard "new cohort" → cohort créé | ≤ 30 s |
| Temps wizard "new iteration" → itération lancée | ≤ 45 s |
| Durée end-to-end d'une itération (5 coins, 100 variants, 40 epochs, 150 photos) | dépend du HW — ~15-30 min sur M4 |
| Temps de lecture verdict + delta | ≤ 10 s (tout est dans la page cohort détail) |
| Compréhension "quel levier bouge le plus R@1" | Oui, via SensitivityPanel, après 5+ itérations |
| Survie à un reload API en plein milieu | Oui, recovery automatique |
| Fuite training → eval | Zéro, héritée du Bloc 3 R1 |

---

## 8. Dépendances

- Bloc 1 (augmentation pipeline) — recipes stockées dans `augmentation_recipes`
- Bloc 2 (Studio) — création/édition de recettes
- Bloc 3 (Benchmark) — `benchmark_runs` table, `evaluate_real_photos.py` script, bibliothèque `ml/data/real_photos/`
- `TrainingRunner` existant (daemon thread, subprocess pattern)

---

## 9. Questions tranchées

| # | Question | Décision |
|---|---|---|
| Q1 | Nom du menu navbar | **Lab** |
| Q2 | On garde "Benchmark" dans la navbar ? | Oui (runs ad-hoc) |
| Q3 | Itérations parallèles | Non — 1 globale à la fois |
| Q4 | Verdict de la première itération (sans parent) | `baseline` |
| Q5 | `training_run_id` cliquable depuis IterationDetail | Oui |

---

## 10. Voir aussi

- [`01-backend-pipeline.md`](./01-backend-pipeline.md)
- [`02-augmentation-studio.md`](./02-augmentation-studio.md)
- [`03-real-photo-benchmark.md`](./03-real-photo-benchmark.md)
- [`real-photo-criteria.md`](./real-photo-criteria.md)
- [`PRD04-implementation-notes.md`](./PRD04-implementation-notes.md) — handoff d'implém.
