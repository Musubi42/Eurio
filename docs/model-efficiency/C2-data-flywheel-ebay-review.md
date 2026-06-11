# C2 — Flywheel données : review eBay

**Statut : 🔲 pas commencé**  ·  Dépend de : C0, C1  ·  Débloque : C3

## Objectif

Boucler un **flywheel de données** : utiliser le modèle de scan amélioré pour
**pré-classer** les pièces scrapées depuis eBay → **streamline la review
humaine** → récolter plus de **références « from the wild »** par classe → qui
ré-alimentent l'entraînement (et les centroïdes C1) → meilleur modèle → …

C'est l'idée produit qui transforme un coût (review manuelle) en moteur de
croissance de la donnée réelle.

## Pourquoi à cette place

La donnée réelle est le levier #1 (H1). La review eBay est aujourd'hui le
goulot pour transformer du scrape brut en références propres. Un bon
pré-classement réduit l'effort humain par item et débloque le volume nécessaire
à C3 (couverture complète).

## Hypothèses (à challenger)

- **H4 — Les gains DINOv2 transfèrent à la classification du scrape eBay.**
  Croyance : moyenne (plausible mais non mesuré). Test : rejouer le modèle sur
  le **gold existant** (`ml:bench:theme-match`, `theme_match_gold.jsonl`) et
  mesurer recall / precision / faux-rejet / taux d'auto-attribution. Comparer au
  matcher actuel.
- **Hypothèse effort — un meilleur pré-classement réduit le temps de review.**
  Test : mesurer le temps/erreurs de review avec vs sans suggestions modèle
  (lien avec `ml:dino-predictions:*` qui peuple déjà des top-K en review).

## Benchmark à semer

- Métriques de classification sur le gold eBay : recall, precision, false-discard,
  auto-attribution %, avant/après.
- Proxy d'effort review : items auto-validables vs nécessitant un humain.

## Plan

- [ ] Auditer l'existant : `ml:scrape-ebay`, `ml:src:ebay`, `ml:review:*`,
      `ml:dino-predictions:backfill`, `ml:bench:theme-match` (ne pas réinventer).
- [ ] Brancher `arcface-vits14-v1` (post-C1) comme source de suggestions review.
- [ ] Mesurer H4 sur le gold ; décider seuils d'auto-attribution.
- [ ] Définir la boucle : items validés → nouvelles refs wild → C1/C3.

## Résultats

_(vide)_

| Date | Source suggestions | Recall | Precision | Auto-attrib % | Notes |
|---|---|---|---|---|---|
| | | | | | |

## Décisions & next

_(à compléter)_
