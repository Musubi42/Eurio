# C6 — Gate d'éval continue

**Statut : 🔲 pas commencé**  ·  Dépend de : C0

## Objectif

Faire du benchmark C0 un **gate** : tout changement de modèle (ré-entraînement,
nouveaux centroïdes, quantization, distillation) **rejoue automatiquement** la
vérité terrain et bloque/alerte si la qualité régresse, **avant** déploiement
device.

C'est ce qui empêche nos croyances de re-diverger silencieusement entre
sessions.

## Pourquoi à cette place

Inutile avant que C0 existe ; mais dès qu'il existe, c'est lui qui garantit que
C1→C5 ne dégradent rien sans qu'on le sache.

## Hypothèses (à challenger)

- **Hypothèse parité — l'inférence Python (bench) et l'inférence Android
  donnent la même sortie sémantique.** À garder vrai : sinon le gate valide un
  modèle qui se comporte autrement sur device. Lien avec le contrat de parité
  déjà en place (`ml:scan:parity-*`, ε sur la sortie sémantique).

## Benchmark à semer

- Le gate **est** l'exécution de C0 ; il produit un diff de métriques
  (R@1/R@3/confusion) vs la dernière baseline validée, avec un seuil de
  régression.

## Plan

- [ ] Une commande `go-task` qui : prend un checkpoint → exporte → calcule
      centroïdes → rejoue C0 → diff vs baseline → exit non-zéro si régression.
- [ ] Brancher sur le pré-déploiement (avant `android:install` d'un nouveau modèle).
- [ ] Optionnel : CI cloud (lien `/code-review ultra` / pipeline existante).

## Résultats

_(vide)_

## Décisions & next

_(à compléter)_
