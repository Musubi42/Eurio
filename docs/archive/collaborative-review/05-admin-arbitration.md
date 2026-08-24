# 05 — Arbitrage admin & qualité

## Le modèle qualité v1 (décision actée)

**Un ami review un item → la décision va en staging → Raphaël arbitre.**

Pas de double-vote automatique entre amis, pas de gold items, pas de score de trust
auto en v1. La qualité passe par **une passe d'arbitrage humaine** de Raphaël, dans
une **vue rapide** façon `AutoValidateVerdict.vue`.

```
ami décide ──reconcile──▶ peer_review_decisions (pending) ──arbitrage──▶ canonique
                              (eurio.db)                    (Raphaël)
```

## La vue d'arbitrage (dans le console admin)

Nouvelle page dans `admin/packages/web` (ex. `/review/peer-arbitration`),
alimentée par `peer_review_decisions WHERE arbitration_status='pending'`.

Pensée pour être **rapide** (revue de masse, pas item par item lent) :

- Grille de cartes : **crop + choix du reviewer + qui** (`Paolo`) + candidats Dino
  pour comparer d'un coup d'œil.
- Quand le verdict auto-validate **coïncide** avec le choix de l'ami → badge vert
  « concorde », pré-coché pour approbation en masse (revue ultra-rapide).
- Quand ça **diverge** → mis en avant, Raphaël regarde de près.
- Actions : **Approuver** (→ applique la vraie décision via `decide()`),
  **Rejeter** (→ re-publie l'item ou le ferme), en masse ou à l'unité.

Au moment de l'approbation, la décision entre au canonique avec
`decision_engine_version='peer@v1'` et un niveau de confiance **`peer_review`**.

## Juger la qualité par reviewer

Comme chaque décision porte `reviewer_token`, l'admin peut afficher par ami :
- nombre de décisions, taux d'approbation par Raphaël, taux de rejet.
- → repérer un ami qui fait des bêtises, ajuster (lui réexpliquer, ou désactiver
  son token via `reviewers.is_active=0`).

## Comment ça s'emboîte avec l'auto-validation

La review collaborative et l'`autovalidation-redesign` (consensus text+dino+crop)
sont **complémentaires** :
- L'auto-validation tranche les cas faciles (auto-accept) → ils ne partent **pas**
  en review collaborative.
- Restent les `needs_review` → publiés aux amis.
- L'arbitrage de Raphaël utilise le verdict auto-validate comme **filet** (concorde
  / diverge) pour aller vite.

## Évolutions futures (hors v1, notées pour mémoire)

- **Double-vote** : servir les items litigieux à 2 amis, majorité l'emporte ;
  désaccord → arbitrage. Réduit la charge d'arbitrage de Raphaël.
- **Gold items** : semer ~5 % d'items à réponse connue dans le flux de chaque ami
  → mesurer son taux d'accord → **score de confiance auto** par reviewer.
- **Trust auto-promote** : un ami au-dessus d'un seuil de fiabilité → ses décisions
  concordantes avec l'auto-validation s'auto-promeuvent sans arbitrage.
- **Classement / badges** entre amis pour la motivation.

Ces quatre points transforment l'ami en « expert de plus » dans l'ensemble de
consensus. À considérer quand le volume d'arbitrage de Raphaël devient le goulot.
