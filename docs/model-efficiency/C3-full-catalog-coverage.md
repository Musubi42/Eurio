# C3 — Couverture catalogue complète

**Statut : 🔲 pas commencé**  ·  Dépend de : C1, C2  ·  C'est le cœur de la vision

## Objectif

Passer de **27 classes fiables** à **toutes les classes de la DB** (~546 designs
2€ aujourd'hui, et la suite à mesure que le référentiel grossit). C'est la
réalisation de la north star : scanner n'importe quelle 2€.

## Pourquoi à cette place

Dépend de centroïdes fiables (C1) et d'assez de données réelles (C2). Sans eux,
étendre à 546 = étendre des matches non fiables (cf. l'attracteur ArcFace-W).

## Hypothèses (à challenger)

- **H1 — Plus d'images réelles par classe ↑ précision.** Test : courbe R@1
  (C0) en fonction du nombre d'images réelles par classe ; identifier le seuil
  de rendement décroissant et la cible minimale par classe.
- **Hypothèse couverture — toutes les classes DB ont un eurio_id résoluble
  côté app.** L'app résout le match via `findByEurioId(slug)`. Vérifier que les
  546 slugs existent dans la DB Room embarquée (sinon le match ne s'affiche pas).
- **Hypothèse périmètre — « toutes les 2€ » = commémoratives + standards, avers
  uniquement.** Le revers commun n'est pas matché (décision actée). À garder
  explicite : variantes/millésimes regroupés par design d'avers.

## Benchmark à semer

- R@1 / R@3 sur le set C0 **étendu** à un échantillon stratifié des 546 classes.
- Couverture : % de classes DB avec (a) un centroïde fiable, (b) ≥ K images réelles.

## Plan

- [ ] Garantir un centroïde fiable pour les 546 (sortie de C1).
- [ ] Vérifier la résolution slug→pièce pour les 546 (DB Room).
- [ ] Mesurer la couverture data réelle par classe ; prioriser les classes pauvres
      (alimentées par C2).
- [ ] Déployer un build « full coverage » et le mesurer device.

## Résultats

_(vide)_

| Date | Classes couvertes | R@1 (C0 étendu) | % classes ≥K img réelles | Notes |
|---|---|---|---|---|
| | | | | |

## Décisions & next

_(à compléter)_
