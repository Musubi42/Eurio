# Features de reconnaissance — vision produit

> Vision stratégique segmentée par feature. Chaque feature a son
> propre doc qui décrit l'état actuel, les limites, et les
> directions d'expansion. Les docs d'implémentation détaillés
> (`lab-prod-refacto/`, `training-pipeline/harvest/`, `training-
> pipeline/refacto/`, `journal/`) sont référencés depuis chaque
> feature comme couche d'infrastructure.

## Mission

Faire tourner la reconnaissance de pièces euro **sur le téléphone
de l'utilisateur**, sans inférence cloud par défaut, avec un fallback
cloud uniquement quand l'on-device hésite. Le produit central est
le scan ; tout le reste s'organise autour.

## Trois features de reconnaissance

La reconnaissance d'une pièce, c'est trois leviers indépendants qui
se composent. Améliorer l'un sans toucher aux autres est presque
toujours possible et c'est ce qui rend ces features autonomes.

| Feature | Question centrale | Doc | Statut global |
|---|---|---|---|
| **[Scrape](./scrape.md)** | Combien de photos différentes par pièce on a, et d'où elles viennent ? | [`scrape.md`](./scrape.md) | 🔲 1 source (Numista canonique) — élargissement à plusieurs sources planifié |
| **[Augmentation](./augmentation.md)** | À partir des photos qu'on a, comment fabrique-t-on des variantes qui couvrent les conditions wild ? | [`augmentation.md`](./augmentation.md) | 🔄 recipe baseline en place, optim à mener |
| **[Model](./model.md)** | Quel embedder produit les vecteurs, et comment on l'entraîne ? | [`model.md`](./model.md) | 🔄 ArcFace from-scratch en place, pivot DINOv2 planifié |

## Comment elles se composent

```
┌────────────────────────────────────────────────────────────┐
│  scrape : sources + auto-validateur                        │
│           ↓                                                │
│  pool de photos labelées par eurio_id                      │
└────────────────────┬───────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────┐
│  augmentation : recipe (perspective, lighting, overlays)   │
│                 ↓                                          │
│  variants synthétiques par photo source                    │
└────────────────────┬───────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────┐
│  model : backbone + tête + training (ArcFace ou DINOv2)    │
│          ↓                                                 │
│  embedder TFLite + lib de centroïdes                       │
└────────────────────┬───────────────────────────────────────┘
                     │
                     ▼
        Scan on-device → top-k → fallback cloud si flou
```

Chaque feature peut être améliorée indépendamment. Doubler le pool
de photos (scrape) ou changer le backbone (model) ou retoucher la
recipe (augmentation) sont **trois interventions distinctes** qu'on
peut benchmarker sur la même cohort.

## Méthodologie figée (post test-1 v2)

Quel que soit le levier qu'on tire, ces invariants restent :

- **Label space `eurio_id` strict côté lab.** Pas de COALESCE
  design_group_id, pas d'exception. Validé empiriquement par
  phase 1 du refacto lab-prod : 57% → 85.7% live R@1 strict sur la
  même cohort, même recipe, même backbone. Cf.
  [`docs/lab-prod-refacto/`](../lab-prod-refacto/).
- **Obverse-only matching.** Le reverse 2€ est partagé entre toutes
  les commémoratives, le donner à ArcFace pollue le signal. Cf.
  memory `project_obverse_only_matching`.
- **Cohort frozen + journal d'itération.** Chaque expérimentation
  porte un `iteration_id`, chaque résultat exploité a une entrée
  dans `docs/training-pipeline/journal/`. Pas d'optim à l'aveugle.
- **Bench R@1 strict + live tests** comme métriques de vérité. R@1
  d'eval interne pendant le training est un proxy bruyant.
- **DINO cos pour aug-vs-real est un sanity check, pas un proxy de
  perf.** Validé deux fois (test-2 et test-1 v2).

## Couches d'infrastructure (sous les features)

Les features s'appuient sur des couches techniques qui ne sont pas
des features produit mais sans lesquelles aucune feature ne tient :

| Couche | Doc | Rôle |
|---|---|---|
| **Lab/prod isolation** | [`lab-prod-refacto/`](../lab-prod-refacto/) | Une itération de lab ne pollue pas la prod ; chaque iteration_id a ses artefacts. Phase 1 ✅, phases 2-4 🔲. |
| **UX du lab** | [`training-pipeline/refacto/`](../training-pipeline/refacto/) | Tiroirs cohort/iteration, training monitor, drawer iterations. |
| **Journal d'itérations** | [`training-pipeline/journal/`](../training-pipeline/journal/) | Trace écrite des expérimentations notables. |
| **Tracks de delivery** | [`tracks.md`](../tracks.md) | Statut global de chaque chantier infra. |

## État actuel — chiffres de référence

Baseline du **2026-05-02** (test-1 v2 sur cohort `mix-zone-7-cls-v2`,
7 eurio_ids) :

- Bench R@1 strict : **92.86%** (42 photos studio device)
- Live R@1 strict : **85.7%** (21 photos in-the-wild)
- Floor à battre pour toute itération suivante. Sous ce floor sans
  raison documentée = suspect.

## Comment lire ce dossier

Si tu veux **brainstormer une nouvelle feature** ou un nouvel angle
d'attaque : commence par lire le doc feature concerné (`scrape.md`,
`augmentation.md`, `model.md`), il liste les pistes connues. Ajoute
ta proposition dans la section "Pistes ouvertes" du doc.

Si tu veux **comprendre où on en est globalement** : ce README + le
journal des dernières itérations.

Si tu veux **implémenter** : trouve la phase concernée dans le doc
infra qui pilote cette feature (souvent `lab-prod-refacto/` ou
`harvest/`).
