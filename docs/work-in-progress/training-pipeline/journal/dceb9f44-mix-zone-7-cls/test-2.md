# test-2 — mix-zone-7-cls

- **Cohort** : `dceb9f44ba8f` (`mix-zone-7-cls`, frozen 2026-05-01)
- **Iteration** : `e3c4df8678eb`
- **Parent** : `4be0cb425881` (test-1, échouée — orchestrator died avant benchmark)
- **Démarrée** : `2026-05-01T21:18:09Z`
- **Terminée** : `2026-05-01T21:49:56Z` (~32 min, training 31 min + bench 7 s)
- **Verdict (UI)** : `baseline`
- **Verdict (humain)** : **baseline trompeuse** — la métrique du bench masque un problème de label space, voir interprétation.

## Hypothèse

Première itération aboutie de la cohort. Pas d'hypothèse précise — on cherche à établir un point de référence sur 7 classes mélangeant standards et commémoratives.

## Setup

- **Training config** : `epochs=40, batch_size=256, m_per_class=4, mode=arcface, prebaked_augmentations=true`
- **Recipe d'augmentation** : `e6ea78f284ff` (`test-1`)
  - background : prob 0 (désactivé)
  - perspective : prob 0.8, max tilt **15°**
  - relighting : prob 0.8, ambient 0.65, intensity 0.6–1.25
  - overlays : prob 1.0, patina + dust, opacity 0.15–0.4
  - count cible : 100 augs/coin (50 utilisées)
- **Classes** : 7 `eurio_id` ajoutées (`classes_added`), mais `classes_before` contient déjà des `design_group_id` (`at-2eur-standard-2002`, `es-2eur-standard-1999`) qui couvrent les **mêmes designs** que les nouveaux `eurio_id` AT-2002 et ES-1999. **Label space pollué** dès le départ.
- **Variants par classe** : 50

## Résultats

### Training (`61a051bb`)

- Loss : **0.0**
- R@1 (eval interne) : **0.3824**
- Notes : loss=0 + R@1 train=0.38 → overfit massif sur les augs, le réseau mémorise sans apprendre une métrique transférable.

### Benchmark photos réelles (`9bc9d548387d`)

- 42 photos, 7 pièces (zone unique `unknown`, condition `close`)
- **R@1 / R@3 / R@5 : 85.7% / 88.1% / 88.1%**
- **mean_spread : 0.060** (top1↔top2 collés)
- Confusions :
  - ad-2014 : 6/6 ✓
  - at-2002-2eur-standard → **at-2eur-standard-2002** : 6/6 (vers le design_group)
  - be-2007-2eur-standard → at-2eur-standard-2002 : 5/6, → es-2eur-standard-1999 : 1/6
  - es-1999-2eur-standard → **es-2eur-standard-1999** : 6/6 (vers le design_group)
  - fi-2017, fr-2016, it-2016 : 6/6 ✓

### Aug-vs-DINO (cosine real↔aug, dinov2-vits14)

| eurio_id | cos |
|---|---|
| ad-2014 | 0.893 |
| at-2002 | 0.887 |
| be-2007 | 0.863 |
| fr-2016 | 0.848 |
| es-1999 | 0.836 |
| fi-2017 | 0.828 |
| it-2016 | 0.800 |

Tous au-dessus de 0.80. **Aucune corrélation avec la perf live** : IT-2016 (pire cos) fait 3/3 ; AT-2002 (2e meilleure cos) fait 0/3.

### Live tests (21 tests = 7 × {bright, dim, tilt})

- **R@1 strict : 12/21 = 57.1%**
- Détail :
  - ad-2014 : ✓ ✓ ✗(tilt → it-2016, GT en top3)
  - **at-2002 : 0/3** (→ fr / ad / ad)
  - **be-2007 : 0/3** (→ ad / it / it)
  - **es-1999 : 0/3** (→ fr / fr / it)
  - fi-2017 : 3/3 ✓ (gros écart top1↔top2, ~0.40)
  - fr-2016 : 3/3 ✓
  - it-2016 : 3/3 ✓

## Interprétation

1. **Le 85.7% du bench est faussement bon.** Le bench accepte qu'une photo `at-2002-2eur-standard` soit prédite comme `at-2eur-standard-2002` (le design_group préexistant) et compte ça correct. Sous métrique stricte eurio_id, le bench tomberait à ~24/42 = 57%, ce que confirment exactement les live tests (12/21 = 57%).
2. **Cause racine n°1 : collision design_group_id × eurio_id dans le label space.** ArcFace voit deux clusters censés couvrir les mêmes pixels et choisit l'attracteur le plus stable (le design_group préexistant, probablement plus ancien et mieux ancré). Les nouveaux `eurio_id` AT-2002 et ES-1999 ne capturent rien.
3. **Cause racine n°2 : collapse des standards.** BE-2007 (seule erreur "honnête" du bench) est confondu avec les clusters AT/ES standards. Les obverses cartes-d'Europe se ressemblent et 6 photos + 50 augs ne suffisent pas à séparer Belgique 2007 (Albert II ancien profil) du cluster générique. Cette erreur survivrait probablement même sans la collision de classes.
4. **Les commémoratives marchent.** FI-2017, FR-2016, IT-2016 sont robustes aux 3 conditions live (gros écart top1/top2 pour FI). Designs visuellement uniques → le pipeline fait son boulot quand les classes ne se chevauchent pas.
5. **DINO cos n'est pas prédictif.** À garder comme sanity check (un score < 0.7 serait alarmant) mais pas comme proxy de qualité finale.
6. **Recipe d'augmentation pas testée.** Avec la pollution du label space, impossible de juger l'apport ou les manques de la recipe. À réévaluer une fois le label space assaini.

## Décisions

- [x] **Aller en design_group only.** Plus de mix `eurio_id` + `design_group_id` dans une même cohort. Une itération = un seul niveau de classification.
- [x] **Le bench doit reporter R@1 strict eurio_id et R@1 design_group côte à côte.** À implémenter dans `ml/serving/` ou `ml/eval/`. Sans ça on continuera à valider des baselines fantômes.
- [x] **Démarrer un journal d'itérations** (ce dossier).

## Suite

Itération suivante (test-3, à créer) :
- Cohort design_group only — soit refrozer cette cohort sous l'angle design_group, soit en créer une nouvelle.
- Recipe inchangée d'abord pour isoler l'effet "label space propre".
- Si R@1 strict remonte vers 80%+ on saura que la collision était bien le problème principal. Si BE collapse encore, attaquer la recipe (tilt > 15°, motion blur, finger smudges).
