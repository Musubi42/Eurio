# C1 — Centroïdes fiables

**Statut : 🟡 en cours**  ·  Dépend de : C0  ·  Débloque : C2, C3

## Objectif

Donner à **chaque classe** un centroïde de référence **fiable**, sans
ré-entraîner. C'est le gain de qualité le moins cher : l'app compare le vecteur
scanné aux centroïdes ; si les centroïdes sont mauvais, même un bon modèle
matche mal.

## Pourquoi à cette place

État actuel : seules **27/546 classes** ont un centroïde fiable (val-mean). Les
519 autres retombent sur le **prototype ArcFace-W**, que le code documente
comme peu fiable (« une classe devient un attracteur »). C'est *le* blocage
pour passer de 27 à 546 classes utilisables.

## Hypothèses (à challenger)

- **H2 — Les centroïdes ArcFace-W sont moins bons que des moyennes d'images.**
  ⚠️ **Premier test (2026-06-11) CONTREDIT cette croyance** : sur 317 vraies
  photos, ArcFace-W = **82.65%** top-1 vs **77.60%** pour les val-mean déployés
  (cf. C0 / journal VISION). La croyance « W mauvais » venait du run F2, pas de
  ce modèle. **Conséquence : ne pas remplacer W aveuglément.** Ce chantier
  devient « *trouver la meilleure source de centroïde, mesurée* », pas
  « *remplacer W* ». Reste à tester sur set large : W vs train-mean vs val-mean
  vs mix, par classe.
- **H1 (partielle) — Plus d'images réelles par classe → meilleur centroïde.**
  Test : courbe R@1 vs nombre d'images réelles utilisées pour le centroïde.

## Benchmark à semer

- Variante centroïdes × R@1 sur le set C0 (table ci-dessous).
- Idéalement : ablation 1/2/5/10/N images par centroïde → courbe de rendement.

## Plan

- [ ] Implémenter une option `--centroid-source {arcface_w, train_mean, val_mean, auto}`
      dans `compute_embeddings.py` (aujourd'hui : val-mean puis fallback W).
- [ ] Générer les variantes, mesurer via C0.
- [ ] Décider la stratégie par défaut, regénérer les centroïdes des 546.

## Résultats

_(vide)_

3-way mesuré sur **317 vraies photos** (`eval_real_norm`, ~17 classes),
`arcface-vits14-v1`, 2026-06-11 :

| Source centroïde | Classes couvertes | Top-1 réel | Notes |
|---|---|---|---|
| **train-mean** | 546 | **82.97%** (263/317) | meilleur ; mais `n=1` pour bcp de classes |
| ArcFace-W | 546 | 82.65% (262/317) | ~à égalité avec train-mean (1 snap) |
| val-mean (déployé) | 27 | 77.60% (246/317) | **le pire** — centroïdes val ~2 img/classe, bruités |

**Conclusion (à confirmer sur set large)** :
- Le maillon faible n'est **pas** ArcFace-W mais **val-mean** (peu d'images val).
- train-mean ≈ W ; train-mean est préférable car il **s'améliorera avec plus
  d'images** (H1), alors que W est figé.
- **Action immédiate possible** : l'app déployée priorise val-mean → regénérer
  ses centroïdes en train-mean (ou W) pour un gain de qualité sans ré-entraîner.

Implémenté : option `--centroid-source {auto,val_mean,train_mean,arcface_w}`
dans `compute_embeddings.py`.

## Décisions & next

_(à compléter)_
