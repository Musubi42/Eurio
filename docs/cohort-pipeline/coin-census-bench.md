# Coin-census bench v0 — combien de pièces sur le raw ?

> Sous-chantier de [cohort-pipeline](./README.md). Objectif : décider lot/single de façon fiable = **recenser les pièces physiques distinctes** sur la photo d'annonce, sans faux-single (empoisonne le training) ni faux-lot.

## Le bench (vérité-terrain)
- **110 raws** de mix-zone-17, stratifiés : 45 single · 20 lot · 20 coincard/capsule (pièges FP) · 15 vrais-lots-titre · 10 au-choix.
- **Labellisés par LLM-professeur (vision)** : chaque agent *ouvre* l'image et compte les pièces **physiques distinctes** (règles : avers+revers d'1 pièce = 1 ; bimétal = 1 ; coincard/capsule = 1 ; 2 pièces différentes = 2+). Champs : `n_coins`, `n_disks_visible` (ce qu'un détecteur naïf verrait), `scene_type`, `is_lot`, `confidence`.
- **Qualité des labels** : 95 high / 13 med / 2 low → vérité-terrain solide.
- Artefacts (local) : `ml/state/coin_census_bench/bench_v0.json` (labels + jointure n_crops), `analysis_v0.json`.
- Construit via workflow `coin-census-bench-v0` (run `wf_30968b09-096`).

## Findings (vision vs détecteur actuel `n_crops`)
| Métrique | Valeur |
|---|---|
| Accord exact `n_crops == n_coins` | **33 %** (37/110) |
| **Sous-compte** (`n_crops < n_coins`) | **63 %** |
| Sur-compte | 4 % |
| **`n_crops=0` sur une pièce visible** | **55 %** (61/110) |
| Vrais lots (vision) | 27/110 |
| **Faux-single** (vrai lot routé pending/single) | **13/27 = 48 %** ⚠️ training poison |
| Faux-lot (vrai single routé review_lot) | 6/83 = 7 % |
| Front/back (1 pièce, ≥2 disques) | 3/110 (rare ici, fréquent en stock réel) |

**Lecture :**
1. **Le mode d'échec dominant = sous-détection / zéro-crop** (55 %), surtout sur les **pièces emballées** (capsule/coincard/coffret — `packaged_single` = 41/110, souvent `n_crops=0`). Le détecteur est **muet**, pas sur-compteur. → problème de **RAPPEL**.
2. **L'erreur coûteuse (faux-single) = lots déclarés au titre** : **13/13** des faux-singles ont un marqueur explicite (`3 x 2 Euro`, `KMS/Kursmünzensatz`, `8 VALORES`, listes multi-pays) que `LOT_PATTERNS` (FR/EN) rate. Aucun n'est un coincard.
3. **Front/back** (avers+revers = 2 disques, 1 pièce) : rare dans cette cohorte (3), mais le pattern est fréquent sur eBay → un détecteur objet naïf compterait 2.

## Design retenu (mis à jour par les données)
- **Quick win, haute précision (~0 FP)** : étendre la détection titre avec un set **étroit, multilingue, à compte explicite** — `\d+\s*x`, `KMS|Kursmünzensatz|Münzset`, `\d+\s*(Münzen|valori|valores|monete|monnaies|pièces|Stück)`, listes multi-pays `XX/XX/XX`. Force `lot`. **Attrape 13/13 faux-singles du bench**, sans toucher aux coincards (correctement single). ⚠️ NE PAS inclure `coincard/blister/set` nu (over-catch prouvé avant).
- **Le détecteur visuel (le vrai chantier)** traite le résidu : **rappel sur pièces emballées** + multi-pièces sans titre. Pattern **propose (haut rappel) → verify is-coin → fusion d'identité (avers/revers, exemplaires identiques via embedding) → dedup → count**, découplé du crop, validé sur ce bench.
- **Asymétrie** : à compte incertain, pencher `lot` (un faux-lot = une review ; un faux-single = dataset empoisonné).

## Reste / next
- Construire le proposeur visuel bench-first (YOLO census via compositing + LLM-labels ; ou SAM2+verify pour mesurer le plafond sans entraînement).
- Brique « fusion d'identité » avers/revers (révélée par le bench).
- Élargir le bench au-delà de mix-zone-17 (front/back plus représenté).
