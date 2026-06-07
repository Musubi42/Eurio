# Tracks — vue d'ensemble

> Index léger des chantiers ML/lab en cours, leurs phases, leurs
> dépendances mutuelles. À mettre à jour dès qu'une phase change de
> statut. Pas de duplication des contenus — chaque cellule pointe
> vers le doc faisant autorité.
>
> Maintenu append-light : on édite les statuts, on ne réécrit pas
> l'historique. Pour la trace narrative, voir le `progress.md` de
> chaque track et le `journal/` des itérations.
>
> **Vision stratégique segmentée par feature** :
> [`features/`](./archive/features/) (scrape, augmentation, model). Les
> tracks ci-dessous sont les chantiers d'infrastructure qui
> supportent ces features.

## Les tracks actifs

| Track | Doc racine | Mission | Démarré | Statut global |
|---|---|---|---|---|
| **lab-prod-refacto** | [`lab-prod-refacto/`](./work-in-progress/lab-prod-refacto/) | Isoler lab et prod, rendre le label space cohérent (`eurio_id` côté lab) | 2026-05-02 | ✅ phase 1 livrée et validée (test-1 v2 : 85.7% live vs 57.1% en test-2) · phase 2 à démarrer |
| **training-refacto-ux** | [`training-pipeline/refacto/`](./training-pipeline/refacto/) | UX lab : tiroirs cohort/iteration, training monitor, purge transforms | en cours | partiel — voir doc |
| **harvest** | [`training-pipeline/harvest/`](./training-pipeline/harvest/) | Élargir le corpus de photos réelles (scraping + cloud fallback + user scans) | 2026-05-02 | 🔲 phase 1 (DINOv2 bring-up) à démarrer |
| **on-device-v2** | _(à créer)_ | Backbone DINOv2 + tête ArcFace fine-tunée, distill mobile, intégration TFLite | non démarré | 🔲 dépend de `harvest/phase-1` |

## Graphe de dépendances

```
                   ┌─────────────────────────────┐
                   │  lab-prod-refacto · phase 1 │
                   │  (label space eurio_id)     │
                   └──────────────┬──────────────┘
                                  │ débloque
              ┌───────────────────┴────────────────────┐
              ▼                                        ▼
  ┌──────────────────────┐              ┌─────────────────────────┐
  │ Itérations propres   │              │ harvest · phase 1       │
  │ (test-1 v2 et au-delà)  │              │ (DINOv2 bring-up)       │
  └──────────┬───────────┘              └────────────┬────────────┘
             │                                       │ valide foundation
             ▼                                       ▼
  ┌──────────────────────┐              ┌─────────────────────────┐
  │ lab-prod-refacto     │              │ harvest · phase 2       │
  │ phase 2 (isolation)  │              │ (auto-validateur eBay)  │
  └──────────┬───────────┘              └────────────┬────────────┘
             │                                       │
             ▼                                       ▼
  ┌──────────────────────┐              ┌─────────────────────────┐
  │ phase 3 (promote)    │              │ harvest · phase 3-5     │
  │ phase 4 (bundle)     │              │ (sources, user, review) │
  └──────────┬───────────┘              └────────────┬────────────┘
             │                                       │
             └────────────────┬──────────────────────┘
                              ▼
                ┌──────────────────────────┐
                │  on-device-v2            │
                │  (DINOv2 + ArcFace head, │
                │   distill mobile, TFLite)│
                └──────────────────────────┘

`training-refacto-ux` est orthogonal — peut avancer en parallèle de tout.
```

## Statut par phase

### lab-prod-refacto
| # | Phase | Statut | Bloque |
|---|---|---|---|
| 1 | [Label space eurio_id](./work-in-progress/lab-prod-refacto/phase-1-label-space.md) | ✅ livrée, validée par test-1 v2 (85.7% live R@1 strict) | — |
| 2 | [Isolation artefacts](./work-in-progress/lab-prod-refacto/phase-2-isolation-artefacts.md) | 🔲 | comparaison inter-itérations, on-device-v2 propre |
| 3 | [Step promote](./work-in-progress/lab-prod-refacto/phase-3-promote.md) | 🔲 | versionning prod |
| 4 | [Bundle routing](./work-in-progress/lab-prod-refacto/phase-4-bundle-routing.md) | 🔲 | A/B cohort-test |

### harvest
| # | Phase | Statut | Bloque |
|---|---|---|---|
| 1 | [DINOv2 bring-up](./training-pipeline/harvest/phase-1-dinov2-bring-up.md) | 🔲 | tout le reste du track + on-device-v2 |
| 2 | [Auto-validateur eBay (commémo)](./training-pipeline/harvest/auto-validator.md) | 🔲 | scraping massif |
| 3 | [Sources étendues](./training-pipeline/harvest/sources.md) | 🔲 | — |
| 4 | [User harvest in-app](./training-pipeline/harvest/user-harvest.md) | 🔲 | dépend on-device shippé |
| 5 | [Review humaine admin](./training-pipeline/harvest/human-review.md) | 🔲 | support phases 2 et 4 |

### training-refacto-ux
Voir [`archive/training-pipeline/refacto/progress.md`](./archive/training-pipeline/refacto/progress.md) pour le détail des 5 phases (chantier archivé, livré). Aucune dépendance bloquante avec les autres tracks.

### on-device-v2
Pas encore de doc dédié. À créer quand `harvest/phase-1` aura validé DINOv2 (ou alt). Périmètre attendu : fine-tune ArcFace head sur backbone foundation, distillation mobile, export TFLite, intégration `app-android/`.

## Prochaine étape

**Cible immédiate** : lab-prod-refacto phase 1 (label space).

Pré-requis avant de coder :
1. Audit `ml/datasets/eurio-poc/eval_real_norm/<eurio_id>/` — tous les eurio_id de la cohort active ont-ils un dossier ?
2. Grep des appelants de `ml/training/prepare_dataset.py` — décide si la rétrocompat `--class-kind=design_group` est utile.

Ensuite : code phase 1 + relance test-1 v2 sur `mix-zone-7-cls` → premier vrai chiffre R@1 strict propre.

## Convention de mise à jour

Quand une phase change de statut :

1. Mettre à jour la cellule `Statut` dans la table correspondante.
2. Mettre à jour le `Statut global` du track si pertinent.
3. Append une entrée dans le `progress.md` du track concerné (pas
   ici).
4. Si une dépendance se débloque, mettre à jour le graphe ASCII
   (rare — il est stable par construction).

Statuts possibles : 🔲 à faire · 🔄 en cours · ✅ livré · ⏸️ en pause · ❌ abandonné.
