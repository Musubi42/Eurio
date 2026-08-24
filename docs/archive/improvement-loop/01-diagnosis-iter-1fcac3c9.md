# Diagnostic — itération `1fcac3c952a9` (cohorte `mix-zone-17`, 16 classes)

> Date : 2026-06-30. Données : 48 live-tests on-device (16 pièces × 3 conditions)
> + stats crops de la replica DB + inspection visuelle de crops réels (MinIO
> `enrichment-crops`).

## TL;DR

Le « drop à 0.58 » était **surtout un bug de mesure**, pas un effondrement
modèle. Décomposition de l'écart vs le studio benchmark (0.937) :

| Métrique | R@1 | Note |
|---|---|---|
| Reporté §5 (avant fix) | 0.562 | strict eurio_id — **bug**, voir §1 |
| **Vrai on-device (eq design_group)** | **0.792** | maille COALESCE(group, eurio_id) |
| Studio bench | 0.937 | crops eBay held-out |

Trois contributions empilées :

1. **Bug strict-vs-eq (le plus gros, ~0.23 de faux écart)** → corrigé.
2. **Domaine + near-twins (~0.15, réel)** → vraies confusions résiduelles.
3. **Déchets training (mineur)** → existe, pas dominant.

## 1. Le bug de mesure (corrigé)

Le serveur calculait la recall sur `is_correct` *strict* (eurio_id exact). Or le
modèle prédit des labels **design_group** (`ad-2euro-standard-t1`) qui ne peuvent
structurellement jamais matcher un eurio_id attendu (`ad-2014-…`). Corrigé :
verdict recomputé server-side sur la maille eq, colonne `is_correct_eq`, parité
restaurée avec l'Android. Détail : `[[project_live_tests_strict_recall_bug]]`,
commits 708c5bc1 / e583183e.

R@1 par condition (recomputé eq) : **bright 0.875 · tilt 0.812 · dim 0.688**.
Le *dim* est le pire — cohérent avec un domaine basse lumière mal couvert.

## 2. Les 10 vraies confusions (après fix eq)

```
expected                          → predicted_top1                  sim    cond
at-2005-austrian-state-treaty     → ad-2euro-standard-t1            0.518  bright
at-2005-austrian-state-treaty     → de-2007-mecklenburg             0.556  dim
de-2020-german-polish             → de-2007-mecklenburg             0.665  dim
es-1999-standard                  → fr-2018-simone-veil             0.803  tilt
fi-2016-von-wright                → de-2007-mecklenburg             0.627  dim
fi-2016-von-wright                → fr-2008-french-presidency       0.630  tilt
fr-2016-mitterrand                → fr-2008-french-presidency       0.581  dim
fr-2016-mitterrand                → fr-2018-simone-veil             0.615  tilt
it-2016-donatello                 → fr-2016-mitterrand              0.880  bright  ← confiant !
it-2016-donatello                 → fr-2008-french-presidency       0.541  dim
```

**Attracteurs** (ce vers quoi ça se trompe) : `de-2007-mecklenburg` ×3,
`fr-2008-french-presidency` ×4, `fr-2018-simone-veil` ×2, `fr-2016-mitterrand` ×1.

### La confusion la plus parlante : donatello → mitterrand @ 0.88 (bright)

Inspection visuelle des crops d'entraînement (les deux sont des **portraits de
profil**) :
- `it-2016-donatello` : buste de profil juvénile avec coiffe (le David de
  Donatello). Crops propres et corrects.
- `fr-2016-mitterrand` : tête de profil « 1916 FRANÇOIS MITTERRAND 2016 ».

→ **Near-twin authentique** : pour un matcher *obverse-only*, deux designs
« tête de profil » occupent la même région de l'espace. Ce n'est pas du déchet,
c'est une similarité visuelle réelle. C'est exactement ce que `confusion_map.py`
(cartographie DINOv2 pré-training) est censé flagger en zones orange/rouge.

## 3. Stats crops par classe (replica DB, cohorte `b0299ca0252b`)

`elig` = `training_eligible=1` · `obv` = `face='obverse'` · `unk` = face non
classée (eligible) :

| eurio_id | crops | elig | rejected | obv(elig) | unk(elig) |
|---|---:|---:|---:|---:|---:|
| ad-2014-standard | 17 | 17 | 0 | 17 | 0 |
| at-2002-standard | 27 | 27 | 0 | 27 | 0 |
| at-2005-state-treaty | 275 | 91 | 106 | 58 | **33** |
| **be-2007-albert-ii** | **0** | **0** | 0 | 0 | 0 |
| be-2011-womens-day | 112 | 27 | 52 | 27 | 0 |
| de-2007-mecklenburg | 83 | 34 | 24 | 34 | 0 |
| de-2020-german-polish | 109 | 21 | 35 | 21 | 0 |
| es-1999-standard | 12 | 12 | 0 | 12 | 0 |
| es-2016-segovia | 99 | 32 | 32 | 20 | 12 |
| fi-2016-von-wright | 177 | 30 | 32 | 25 | 5 |
| fi-2017-independence | 108 | 28 | 27 | 24 | 4 |
| fr-2008-french-presidency | 107 | 48 | 25 | 35 | **13** |
| fr-2016-mitterrand | 120 | 32 | 48 | 19 | **13** |
| fr-2018-simone-veil | 17 | 16 | 1 | 16 | 0 |
| it-2016-plautus | 111 | 37 | 22 | 37 | 0 |
| it-2016-donatello | 67 | 28 | 24 | 28 | 0 |

### Observations

1. **`be-2007` a 0 crop.** Classe de la cohorte sans aucune donnée d'entraînement
   propre (le bake hérite des crops d'un autre membre du design_group s'il existe ;
   sinon, classe fantôme). À surveiller — cf. commit `b1f8ffcf`.
2. **`face='unknown'` eligible** : at-2005 (33), fr-2008 (13), fr-2016 (13),
   es-2016 (12). Hypothèse initiale = déchet. **Réfutée à l'inspection** : les
   crops unknown de fr-2008 et at-2005 sont des avers propres et corrects, juste
   non classés par le face-classifier. Le bake lab les **inclut** (filtre =
   `training_eligible=1` seul, pas de filtre face — cf. `02-pipeline-map`), ce
   qui ici est bénin/bénéfique.
3. **Quelques crops bas de gamme réels** : ex. un crop mitterrand sombre +
   motion-blur. Ceux-là méritent l'exclusion. Mais c'est marginal, pas la cause
   dominante.
4. **Déséquilibre de couverture** : 12–17 crops (ad, es-1999, fr-2018) vs 91
   (at-2005). Les petites classes propres (ad-2014) marchent bien ; le volume
   n'est pas le problème premier.

## 4. Verdict & leviers (par ordre d'impact estimé)

1. **Déjà fait** — corriger la mesure eq (0.58→0.79). Le plus gros gain était
   illusoire.
2. **Near-twins de portrait** (donatello/mitterrand, simone-veil) : levier =
   exploiter `confusion_map.py` (zones) au moment de l'échantillonnage / d'un
   hard-negative mining, ou accepter l'équivalence visuelle. À creuser itér. 2.
3. **Domaine eBay→device, surtout *dim*** : les crops eBay sont souvent proof /
   tonés / sous flash ; les scans device sont des pièces de circulation en
   lumière faible. Levier = augmentations basse-lumière + filtrer les crops
   proof/atypiques.
4. **Nettoyage déchets** (le levier que demande l'outil INSPECT) : réel mais
   marginal sur CETTE cohorte. Devient important quand on scale à plus de classes
   où le ratio déchet monte. L'outil sert aussi à *voir* les leviers 2 et 3.
5. **`be-2007` à 0 crop** : soit sourcer des crops, soit retirer de la cohorte.

## 5. Méthode (reproductible)

- Stats : `scratchpad/class_stats.py` + `junk_detail.py` (replica DB read-only).
- Crops : `shared.storage.local_cache.local_path("enrichment-crops", storage_path)`
  (read-through MinIO), puis inspection visuelle.
- Confusions : déjà dans le report bench (`confusion_matrix`, `top_confusions`)
  et dans `live_test_logs/<iid>.jsonl` (top-3 par test).
