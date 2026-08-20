# Comparer deux encodeurs sur NOS données — le protocole

> Écrit le 2026-08-19, avant implémentation. But : pouvoir trancher entre
> `dinov2-vits14`, `dinov2-vitl14` et **DINOv3** sur une mesure, pas sur un
> benchmark public.


> **Mis à jour le 2026-08-19 (soir).** Les **quatre manques** listés ici et les
> **deux blocages structurels** sont comblés : gold figé
> (`gold_version=0ecbb1d70e3c`, 1958 crops), `mcnemar_exact` extrait dans
> `ml/shared/stats/paired.py`, balayage de seuils par encodeur
> (`shared/stats/sweep.py` + `calibration.py`), tables `encoder_bench_*`
> (migration 0009 + miroir `schema.sql`), et `anchor_path` scopé par encodeur.
>
> **Ce qui reste** : le câblage du banc lui-même — `bench_encoder_dino.py` rejoue
> encore sa propre requête de sélection au lieu du gold figé, et n'écrit rien
> dans `encoder_bench_runs`. Plus 16 dettes mesurées, dont 5 pannes muettes :
> [`../scan-sans-retrain/FINDINGS.md`](../scan-sans-retrain/FINDINGS.md) §7 et §8.
>
> **La licence DINOv3 est levée** : redistribution permise, sous obligation
> d'inclure l'accord et d'afficher « Built with DINOv3 ». La note « le PO avait
> indiqué pas d'usage commercial à ce stade » n'est plus le sujet — le sujet est
> ces deux mentions dans l'APK. Cf. [ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md).

## Ce qui existe déjà (et qu'il ne faut pas réécrire)

`ml/scripts/bench_encoder_dino.py` fait 90 % du travail : il ré-encode la
banque d'ancres **et** les crops étiquetés avec chaque modèle, mesure
recall@1/@5 global et bande pays avec **la même logique que la prod**, et
n'écrit rien — « c'est un chiffre pour décider, pas une bascule ».

Il accepte deux familles de specs : les noms `torch.hub` DINOv2, et
`timm:<model>`. Or `timm` 1.0.27 (déjà installé) expose **18 modèles DINOv3**,
dont `vit_large_patch16_dinov3.lvd1689m` et `vit_small_patch16_dinov3.lvd1689m`.
**DINOv3 est donc testable sans changement de code.**

Résultat de référence, juin 2026 (`dino-suggestions/phase2-encoder-bench.md`,
478 crops) :

| Modèle | dim | global@1 | pays@1 | ms/img |
|---|---:|---:|---:|---:|
| dinov2_vits14 | 384 | 55,1 % | 74,9 % | 28 |
| dinov2_vitl14 | 1024 | 77,2 % | 89,1 % | 116 |

Le jeu étiqueté a **quadruplé** depuis : 1 955 crops avec vérité terrain.

## Les quatre manques

**1. Un set figé.** Le banc reconstruit son jeu à chaque exécution par une
requête SQL sur une table vivante : deux runs à deux semaines d'écart ne sont
pas comparables. Il faut un manifeste versionné, sur le modèle de
`verdict_gold.jsonl` et de `corpus_version()` (`ml/store/scan_corpus.py`).

**2. Un test apparié.** Le banc sort deux pourcentages indépendants. Sur ~2 000
crops, un écart de deux points ne prouve rien. `mcnemar_exact` existe déjà dans
`ml/scripts/replay_corpus.py`, écrit précisément pour cette raison — à extraire
et à consommer ici, sur les vecteurs correct/incorrect appariés par crop.

**3. Un balayage de seuils par encodeur.** Chaque encodeur a sa propre échelle
de spread. Comparer à seuils gelés mesure « qui gagne avec les seuils de
l'autre ». Le banc doit sortir, par modèle, la courbe précision/couverture et
le spread qui atteint 97 % — c'est cette valeur qui alimente `dino_thresholds`,
une ligne par couple `(anchors_kind, encoder_version)`.

**4. Une table de résultats.** `benchmark_runs` ne convient pas : ses clés
étrangères pointent un run d'entraînement et une recette, et il n'a aucune
colonne d'encodeur. Prévoir `encoder_bench_runs` + `encoder_bench_predictions`
(pour rejouer l'apparié plus tard sans tout ré-encoder).

## Deux blocages structurels à lever avant tout A/B

- `anchor_path(kind)` (`anchors.py:130`) ne met pas l'encodeur dans le nom du
  `.npz` : deux encodeurs sur le même kind **s'écrasent**.
- `_get_bank` (`auto_validate.py:129`) traite une banque comme absente si son
  encodeur ne correspond pas au mapping — la banque « autre encodeur » serait
  invisible pendant la phase de comparaison.

En revanche, `image_asset_dino_predictions` est **déjà prête** : sa clé primaire
inclut `(encoder_version, anchors_kind)`, et deux séries coexistent aujourd'hui
en production (7 780 lignes vits14 + 10 218 vitl14).

## Sur DINOv3

Sorti depuis la dernière session. Sur les benchmarks publics de recherche
d'instance — la même famille de problème que la nôtre — DINOv3 ViT-S/16 fait
mAP 0,406 contre 0,327 pour DINOv2 ViT-S/14, soit +24 % relatif à taille égale.
Les petites variantes sont distillées depuis un modèle 7B.

Deux réserves à garder en tête :
- **licence** : les modèles LVD-1689M sont sous licence DINOv3 propre à Meta ;
  les variantes EUPE sont explicitement non commerciales. Le PO a indiqué qu'il
  n'y a pas d'usage commercial des données à ce stade, mais le choix doit être
  conscient ;
- **le benchmark public n'est pas notre tâche**. Distinguer deux faces
  nationales de 2 € est du quasi-duplicata fin. La seule mesure qui tranche est
  celle qu'on fera sur nos 1 955 crops.

Et changer d'encodeur invalide **toutes** les prédictions stockées et tous les
seuils — le coût qu'on paie déjà entre vits14 et vitl14. Autant ne le payer
qu'une fois : recalibration et changement d'encodeur dans le même geste.

## La page admin

Lecture seule sur `encoder_bench_runs` : une ligne par run, la p-value de
McNemar contre le champion courant, et le geste de promotion = écrire les
seuils du gagnant dans `dino_thresholds` + rebâtir la banque sous son nom.
Une fois les étapes 2 et 3 faites, promouvoir un encodeur ne demande plus
aucune migration.
