# test-1 — mix-zone-7-cls-v2

- **Cohort** : `510f658ecee4` (`mix-zone-7-cls-v2`, frozen 2026-05-02)
- **Iteration** : `8ac508b062da`
- **Parent conceptuel** : test-2 de `mix-zone-7-cls` v1 (`e3c4df8678eb`)
  — même 7 eurio_ids, mais cohort recréée et phase 1 du refacto
  lab-prod livrée entre les deux (cf.
  `docs/lab-prod-refacto/progress.md`).
- **Démarrée** : `2026-05-02T14:30:04Z`
- **Terminée** : `2026-05-02T15:01:37Z` (training 31 min, bench 6 s)
- **Verdict (UI)** : `baseline`
- **Verdict (humain)** : **baseline propre** — la métrique n'est plus
  faussée par la collision design_group, les 3 classes qui
  collapsaient en test-2 (AT-2002, BE-2007, ES-1999) sortent du trou.

## Hypothèse

Vérifier que le fix label space (phase 1 lab-prod-refacto :
`build_resolver(force_eurio_id=True)` côté lab) débloque l'itération
sur les 7 classes complètes et fait remonter la R@1 strict live au
voisinage du R@1 bench. Recipe d'augmentation **identique** à
test-2 pour isoler l'effet du label space.

## Setup

- **Training config** : `epochs=40, batch_size=256, m_per_class=4,
  mode=arcface, prebaked_augmentations=true`
- **Recipe d'augmentation** : `e6ea78f284ff` (identique à test-2)
- **Classes** : 7 `eurio_id` purs (label space cohérent post phase 1).
  Plus aucune collision design_group_id × eurio_id.
- **Variants par classe** : 50

## Résultats

### Training (`a2bfd8e3`, version=13)

- Loss : **0.0**
- R@1 (eval interne) : **0.4286** (test-2 : 0.3824)
- Notes : loss=0 + R@1 train=0.43 → toujours overfit massif sur les
  augs, mais l'amélioration légère vs test-2 est cohérente avec un
  label space plus discriminant.

### Benchmark photos réelles (`65f0d01a6279`)

- 42 photos, 7 pièces (zone unique `unknown`, condition `close`)
- **R@1 / R@3 / R@5 : 92.86% / 97.62% / 100%**
- **mean_spread : 0.090** (vs 0.060 sur test-2 — meilleur, mais
  toujours collé)
- Confusions :
  - ad-2014 : 6/6 ✓
  - at-2002 : 5/6 (1 → es-1999)
  - be-2007 : 5/6 (1 → es-1999)
  - es-1999 : 5/6 (1 → ad-2014)
  - fi-2017, fr-2016, it-2016 : 6/6 ✓
- Le cluster standards UE (AT/BE/ES) reste serré entre lui — chacun
  des trois confond une fois avec un autre du cluster, mais aucun
  ne collapse sur un design_group inexistant comme en test-2.

### Aug-vs-DINO (cosine real↔aug, dinov2-vits14)

| eurio_id | cos | live R@1 |
|---|---|---|
| ad-2014 | 0.897 | 2/3 |
| at-2002 | 0.885 | 3/3 |
| be-2007 | 0.862 | 3/3 |
| fr-2016 | 0.847 | 3/3 |
| es-1999 | 0.837 | 1/3 |
| fi-2017 | 0.832 | 3/3 |
| it-2016 | 0.802 | 3/3 |

**Toujours aucune corrélation** entre cos DINO et perf live. IT-2016
(plus bas cos) reste 3/3 ; ES-1999 (mid) collapse partiellement.
Confirmé : DINO cos n'est pas un prédicteur, juste un sanity check.

### Live tests (21 = 7 × {bright, dim, tilt})

- **R@1 strict : 18/21 = 85.7%** (vs 12/21 = 57.1% en test-2)
- Détail :
  - ad-2014 : ✓ ✓ ✗(bright → it-2016 0.93 vs ad 0.92, top-2 collés)
  - at-2002 : 3/3 ✓
  - be-2007 : 3/3 ✓
  - **es-1999 : 1/3** (✓ bright → ✗ dim, ✗ tilt — IT-2016 attracteur)
  - fi-2017 : 3/3 ✓
  - fr-2016 : 3/3 ✓
  - it-2016 : 3/3 ✓

## Interprétation

1. **Le diagnostic phase 1 est entièrement validé.** Les 3 classes
   qui faisaient 0/9 live en test-2 (AT/BE/ES) passent à 7/9 en
   test-1 v2. Le bug n'était pas la recipe — c'était la collision
   eurio_id × design_group_id qui empêchait ArcFace de constituer
   trois clusters distincts pour ces designs. Avec un label space
   propre, les standards UE deviennent discriminables.
2. **Bench R@1 92.86% est honnête** — strict eurio_id, plus de
   complaisance "design_group accepté = correct". Le bench et le
   live convergent (92.86% vs 85.7%), pas de biais structurel comme
   en test-2 (85.7% vs 57.1%).
3. **Mur résiduel = trois erreurs live, toutes vers IT-2016 ou
   AD-2014.** AD-2014 bright (0.93 vs 0.92), ES-1999 dim
   (0.78 vs 0.76), ES-1999 tilt (ES-1999 même pas dans top-3).
   Pattern : IT-2016 et AD-2014 sont des attracteurs sur conditions
   extrêmes (bright/tilt). Hypothèse : la recipe d'augmentation
   couvre mieux ces deux classes que les standards. À creuser.
4. **mean_spread 0.09 reste serré.** Sur les standards UE, top-1/top-2
   à <0.05 d'écart fréquemment — un changement de luminosité fait
   basculer. C'est ce qui fait basculer ES-1999 dim/tilt. La recipe
   actuelle ne crée pas de marge suffisante.
5. **DINO cos non prédictif, second confirmation.** Garder comme
   sanity (cos < 0.7 = alarme) mais pas comme cible d'optim.
6. **R@1 train=0.43 vs bench 92.86%** : régime "memorize then
   generalize via centroïdes" qui caractérise ArcFace prebaked, pas
   un signal pertinent. Le train R@1 est un proxy bruyant.

## Décisions

- [x] **Phase 1 lab-prod-refacto = livrée et validée.** Marquer ✅
  dans progress.md et tracks.md.
- [x] **Conserver `eurio_id` strict côté lab** comme méthodologie de
  référence. Pas de retour en arrière sur le label space.
- [x] **Élargir la stratégie en 3 features** : scrape (sources),
  augmentation (recipes), model (backbone). Cf. nouveau
  `docs/features/`.
- [ ] **Prochaine itération à décider** :
  - (A) Tuner aug recipe sur cette même cohort pour casser les
    confusions standards UE (motion blur, plus de tilt, glow
    spéculaire).
  - (B) Démarrer harvest/phase-1 (bring-up DINOv2) pour bench
    zero-shot sur ces 21 photos live.
  - (C) Phase 2 lab-prod-refacto (isolation par iteration_id) pour
    pouvoir faire (A) et (B) en parallèle proprement.
  - Reco : (B) en premier — chiffre stratégique à très haute valeur
    informationnelle.

## Suite

Référence pour les itérations suivantes :

- **Floor à battre** : 85.7% live R@1 strict, 92.86% bench R@1, sur
  cette cohort. Toute itération qui descend en-dessous sans bonne
  raison est suspecte.
- **Cibles à débloquer** : ES-1999 (1/3 live), AD-2014 bright
  (top-2 collés), confusions intra-cluster standards UE.
- **Recipe baseline** : `e6ea78f284ff` (test-1 v2 + test-2). Toute
  variation se compare contre cette baseline.
