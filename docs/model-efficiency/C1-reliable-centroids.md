# C1 — Centroïdes fiables

**Statut : 🔲 pas commencé**  ·  Dépend de : C0  ·  Débloque : C2, C3

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

| Source centroïde | Classes couvertes | R@1 (C0) | Notes |
|---|---|---|---|
| ArcFace-W | 546 | | baseline actuelle (519) |
| train-mean | 546 | | |
| val-mean | 27 | | fiable mais partiel |

## Décisions & next

_(à compléter)_
