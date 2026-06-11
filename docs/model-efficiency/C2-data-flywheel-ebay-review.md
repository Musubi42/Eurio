# C2 — Flywheel données : review eBay

**Statut : 🟡 en cours** (session 2, 2026-06-12)  ·  Dépend de : C0, C1  ·  Débloque : C3

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

### 2026-06-12 — Session 2 (PC, DB scratch 25/05 — voir caveats)

**Audit code : le flywheel n'a pas de maillon manquant.** Le « gap
`training_eligible` » supposé par le handoff est réfuté : toutes les décisions
de review (humain single/bulk, 1-click DINO, ack Claude, arbitrage pair,
auto-reject consensus/gate) écrivent `image_assets.training_eligible`
atomiquement avec `resolution_status`, et l'entraînement le consomme
(`iteration_augmentations.py:136`). Ce qui manque est du **volume** : au
25/05, 0 asset `training_eligible=1` sur 1961 (80 décisions prises, toutes
antérieures au câblage ? à re-vérifier sur la DB canonique).

**Baseline H4 — matcher texte** (`ml:bench:theme-match`, gold 196 listings) :

| Date | Source | Recall | Précision autos | Auto-attrib % | Junk false-keep | Notes |
|---|---|---|---|---|---|---|
| 2026-06-12 | texte (HEAD, DB scratch 25/05) | 100 % | 94,9 % (75/79) | 75,8 % (75/99) | 36,5 % (31/85) | 563 aliases |
| 2026-06-12 | texte (HEAD, **DB canonique**) | 100 % | **94,5 %** (69/73) | **69,7 %** (69/99) | **36,5 %** (31/85) | 69 aliases (purge) — la purge coûte ~6 pts d'auto-attrib, la précision tient |

> ⚠️ Premier replay canonique : 17,2 % @ 23,3 % — **artefact de slugs**. Le
> référentiel canonique est revenu aux slugs « anciens » et le gold (figé
> 01/06) portait les renommés : 52 des 53 « erreurs » étaient la bonne pièce
> sous un autre slug (1 seule vraie erreur, ghent→liège). Le gold a été
> **réaligné sur les slugs canoniques** (76 verdicts) — leçon : le gold est
> figé sur l'identité des pièces, pas sur l'orthographe des slugs.

**Pré-classement vision** (`ml/scripts/bench_vision_preclass.py`, nouveau —
94 listings gold `coin:*`, 551 crops multi-Hough, 9 classes BE, ancres =
canonical Numista uniquement, n=1 train pour ces 9 classes) :

| Système | Scope | Top-1 | Hit@5 | Auto-attrib @ p≥95 % |
|---|---|---|---|---|
| DINOv2 vitl14 zero-shot (`2eur_all`, 544 ancres) | full | 39,4 % | 46,8 % | 0 % |
| DINOv2 vitl14 zero-shot | re-rank pays (be) | **62,8 %** | **79,8 %** | 1,1 % (seuil sim 0,878) |
| arcface-vits14-v1 + centroïdes train-mean | full | 11,7 % | 20,2 % | 0 % |
| arcface-vits14-v1 | re-rank pays (be) | 28,7 % | 35,1 % | 0 % |

_(Chiffres confirmés sur DB canonique + gold réaligné — identiques au run
scratch 25/05 à ±1 pt de hit@5 : la conclusion est robuste au référentiel.)_

Sur le **résiduel texte** (24 listings que le matcher canonique route en
review — le rôle réel de la vision en prod) : zs_country top-1 45,8 %,
arc_country 25,0 %.

**Lectures :**
- **H4 réfutée sur ce régime** : les gains du fine-tuné (82–83 % sur snaps
  device, 27 classes fiables) ne transfèrent pas au scrape eBay quand l'ancre
  de classe est la canonical seule — le zero-shot vitl14 le bat ×2.2.
  Mécanisme plausible : vitl14 (300M, 1024-d) >> vits14 fine-tuné sur 1004
  images pour la généralisation hors domaine ; le fine-tuné gagne là où il a
  des refs réelles — exactement ce que le flywheel doit produire (H1).
- **La vision seule ne porte pas l'auto-attribution** (≈0 % à p≥95 %, sims
  correct/erroné trop entrelacés sur ancres canonical-only). L'auto-attribution
  reste portée par le **texte** ; la vision reste la couche **suggestions
  top-K** (UI review) + signal de consensus.
- Le vrai point faible mesuré du filtrage est le **junk false-keep 36,5 %**
  (2,5 € belges, colorisées, blisters « toutes années ») — prochain levier
  d'effort review, pas l'auto-attribution.

**Caveats (à lever sur DB canonique) :** DB scratch du 25/05 (aliases/coins
de cette date) ; crops bench multi-Hough sans YOLO (poids `coin_detector`
absents du PC) ; gold BE-only, 9 classes commémo ; centroïdes arcface
train-mean avec n=1 pour les 9 classes testées.

## Décisions & next

**Décision §5.1 (mesurée)** : le modèle de pré-classement review reste le
**zero-shot DINOv2 vitl14 `2eur_all`** (l'existant). Ne pas brancher
`arcface-vits14-v1` sur la review tant qu'il n'a pas de refs wild dans ses
centroïdes ; re-mesurer avec ce bench après chaque itération de la boucle.

**Décision §5.2 (seuils auto-accept)** : pas de lane auto-accept vision-seule
(précision insuffisante). La lane auto-accept reste texte `single` (précision
mesurée 94,9 %) ; le consensus texte+dino+qualité (shadow) est le bon cadre —
à calibrer sur la DB canonique avec les verdicts réels.

**Bloqué par la DB canonique (action Mac requise : `ml:db:release`, puis
`ml:db:acquire` sur PC)** : runs eBay réels (quota/freshness/dedup faux sur
scratch), calibration consensus, vérification de l'état réel de
`training_eligible`, élargissement du gold à d'autres pays.

**Next mesurables (quota-free)** :
1. Junk filtering : réduire le false-keep 36,5 % (signaux texte « 2,5 € »,
   « coloré », « choisissez l'année ») — rejouable sur le gold à chaque itération.
2. Élargir le gold au-delà de BE (bench:export-batch sur d'autres runs).
3. Re-bencher la vision quand des refs wild seront dans les centroïdes
   (boucle C2c→e) — le bench est commité et reproductible.
