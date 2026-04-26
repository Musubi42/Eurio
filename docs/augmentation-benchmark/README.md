# Augmentation & Benchmark — Plan d'outillage

> Outils pour construire, calibrer et valider le pipeline d'augmentation synthétique qui génère des variantes de pièces à partir d'un scan Numista "parfait". Objectif : équiper Eurio pour scaler ArcFace de 7 designs à 300-500 designs de manière **calibrée et mesurée**, pas à l'aveugle.
>
> Session de planification : 2026-04-19.

## Contexte

La [Phase 2 du plan ML scalability](../research/ml-scalability-phases/phase-2-augmentation.md) a posé la stratégie : augmenter agressivement les données à partir de la seule image Numista disponible par design. Cette phase est maintenant en cours d'implémentation.

Après les 2 premières itérations (perspective warp + overlays texturés + relighting 2.5D), on a constaté qu'**itérer à l'œil via CLI n'est pas soutenable** : chaque tweak de paramètre demande de regénérer un PNG, l'ouvrir, juger, revenir au code. Et surtout, juger à l'œil **ne remplace pas une mesure numérique** : "cette recipe est-elle vraiment meilleure ?" ne se répond qu'avec un bench.

On a donc besoin de **3 outils complémentaires** travaillant de concert.

## Les 3 blocs

```
┌──────────────────────────────────────────────────────────────┐
│                                                               │
│   Bloc 1 ─── MOTEUR ────→ génère des variantes               │
│   ml/augmentations/       (perspective, overlays, relighting)│
│        ↓                                                      │
│   Bloc 2 ─── COCKPIT ───→ calibre les recettes visuellement  │
│   /admin/augmentation     (preview, sliders, save recipe)    │
│        ↓                                                      │
│   Bloc 3 ─── DYNO ──────→ valide numériquement               │
│   real photos + bench     (R@1 / R@3 sur photos réelles)     │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

| # | Bloc | Nature | PRD |
|---|------|--------|-----|
| 1 | Pipeline d'augmentation backend | Code Python stable + API stable | [`01-backend-pipeline.md`](./01-backend-pipeline.md) |
| 2 | Augmentation Studio (admin UI) | Vue interactive de calibration | [`02-augmentation-studio.md`](./02-augmentation-studio.md) |
| 3 | Benchmark sur photos réelles | Vérité terrain numérique | [`03-real-photo-benchmark.md`](./03-real-photo-benchmark.md) |

## Documents associés

- [`real-photo-criteria.md`](./real-photo-criteria.md) — Critères de shooting pour la bibliothèque de photos réelles (5 axes à varier). À consulter au moment de photographier les pièces.
- [`PRD01-implementation-notes.md`](./PRD01-implementation-notes.md) — Résumé de la session d'implémentation Bloc 1 (2026-04-19) : ce qui a été livré, contrats figés, points de dette, smoke tests.
- [`PRD02-implementation-notes.md`](./PRD02-implementation-notes.md) — Résumé de la session d'implémentation Bloc 2 (2026-04-19) : Studio admin, contrats UX, décisions techniques, dette identifiée.
- [`PRD03-implementation-notes.md`](./PRD03-implementation-notes.md) — Résumé de la session d'implémentation Bloc 3 (2026-04-19) : banc d'éval real-photo, schéma + routes + admin, hold-out gate, dette identifiée.
- [`04-experiments-lab.md`](./04-experiments-lab.md) — PRD Bloc 4 : couche Lab & Experiments (cohorts + iterations + verdict + sensitivity).
- [`PRD04-implementation-notes.md`](./PRD04-implementation-notes.md) — Résumé de la session d'implémentation Bloc 4 (2026-04-19) : orchestrateur iteration → training → benchmark, verdict automatique, per-axis metrics, dette identifiée.

## Décisions cadres (2026-04-19)

| Décision | Motivation |
|---|---|
| **Freeze du Bloc 1** (code actuel) avant de démarrer l'implémentation des Blocs 2 et 3 | Le Bloc 2 consomme l'API du Bloc 1 — il doit partir d'une surface stable. Les finitions du Bloc 1 (specular, motion blur, color grading) reviennent après validation 2/3 |
| **Recettes, runs et benchmarks stockés en SQLite local** (pas Supabase) | Supabase = référentiel prod de l'app. Ici on est dans le training/calibration — artefacts locaux uniquement. Extension du `training.db` existant |
| **Photos réelles strict hold-out** | Toute fuite dans le training → métriques gonflées → tuning à l'aveugle. Gate dur dans le code + gitignore |
| **Workflow par zone** : valider recipe verte → orange → rouge en isolation, puis combiner | Permet de tester chaque recette sur un dataset restreint (5 pièces par zone) avant composition complète |
| **Pas d'auto-regen** dans le Studio au tweak — bouton explicite | Génération 16 variantes = 2-3s. Auto-regen deviendrait frustrant. Badge "config modifiée" suffit |
| **Save recipe conditionnel** : bouton visible uniquement quand un tweak est détecté | Évite pollution du store par sauvegardes non intentionnelles |
| **Compare mode** dans le Studio v1 (A/B 2 recettes côte à côte) | Central au workflow d'itération — voir le delta visuel d'un tweak est plus parlant que le voir en isolation |
| **Stage depuis /coins** via bouton "Augmenter" dans le footer sticky existant | Flux naturel : on sélectionne des coins, on les augmente, on les envoie au training. Pas de silo entre admin pages |
| **Nombre de pièces par zone libre** (pas hardcodé) | L'user choisit selon ce qu'il possède physiquement. Pas de règle "il faut exactement 5" |
| **Endpoint admin** = `/augmentation` (pas `/augmentation-studio`) | Compact, match les autres routes admin |
| **Photos prises par le dev lui-même** (pas de scraping) | Contrôle total sur les conditions + aucun risque légal. Scraping = Phase 3 ML scalability, autre chantier |

## Dépendances entre blocs

```
    Bloc 1 (freeze current code)
       │
       ├── expose schema API + /preview + /recipes CRUD
       │
       ▼
    Bloc 2 (Studio)
       │
       └── produces recipes + stages trained models
                         │
                         ▼
                    Bloc 3 (Benchmark)
                         │
                         └── metrics → feedback visuel Studio
```

- **Bloc 2 dépend du Bloc 1** : API stable + introspection des params
- **Bloc 3 dépend du Bloc 1** : stockage SQLite mutualisé
- **Bloc 2 et Bloc 3 sont indépendants** entre eux — le Studio tune visuellement, le Benchmark valide numériquement (signaux complémentaires, pas redondants)

## Ordre d'implémentation

1. **Figer le Bloc 1** (freeze de l'API actuelle, pas de nouvelle feature) — cadré par le PRD Bloc 1
2. **Implémenter Bloc 2 (Studio)** — session dédiée. Consomme Bloc 1
3. **Implémenter Bloc 3 (Benchmark)** — en parallèle ou après Bloc 2
4. **Retour au Bloc 1** pour les finitions (specular, motion blur, color grading) + tout ce que les Blocs 2/3 ont montré comme manque empiriquement

Chaque bloc = une session d'implémentation dédiée, guidée par son PRD. Les questions ouvertes de chaque PRD se tranchent au moment de l'implém.

## Métriques de succès (globales à l'outillage)

Livré quand on peut :

- **Itérer sur une recipe** en <1 minute (tweak → preview → jugement) via le Studio
- **Sauvegarder une recipe custom** puis la retrouver/recharger
- **Entraîner un modèle** sur une recipe donnée depuis le Studio (handoff vers Training)
- **Évaluer un modèle** sur les photos réelles et obtenir un rapport R@k par zone en <30s
- **Comparer 2 recipes** numériquement et dire objectivement laquelle gagne

## Questions ouvertes à l'échelle du dossier

Listées dans chaque PRD + quelques questions transverses :

- **Traçabilité recipe → training_run → benchmark_run** : chaque bench doit pouvoir remonter à la recipe qui a servi à augmenter le dataset d'entraînement. Contrat : `benchmark_runs.training_run_id` FK + `training_runs.aug_recipe_id` FK.
- **Mono-utilisateur** : toutes les décisions assument un seul dev. Si multi-user v2, il faudra ajouter `owner` sur les recipes et benchmarks.
- **Suppression en cascade** : si une recipe est supprimée, que faire des training_runs qui l'ont utilisée ? Probablement : soft-delete (flag `archived`) plutôt que hard-delete.

## Voir aussi

- [`../research/ml-scalability-phases/phase-2-augmentation.md`](../research/ml-scalability-phases/phase-2-augmentation.md) — spec fonctionnelle Phase 2
- [`../research/ml-scalability-phases/phase-4-subcenter-evalbench.md`](../research/ml-scalability-phases/phase-4-subcenter-evalbench.md) — spec initiale du banc d'éval (le Bloc 3 est la première réalisation pragmatique)
- [`../research/ml-scalability-phases/README.md`](../research/ml-scalability-phases/README.md) — plan scalability global
- [`../../ml/augmentations/`](../../ml/augmentations/) — code du Bloc 1 en l'état figé
- [`../../ml/data/overlays/README.md`](../../ml/data/overlays/README.md) — banque de textures (générées procéduralement + réelles CC0)
