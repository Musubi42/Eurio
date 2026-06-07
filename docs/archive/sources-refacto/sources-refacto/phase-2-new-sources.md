# Phase 2 — Nouvelles sources

> Catawiki, NumisCorner, CGB. Première vraie validation du contrat
> modulaire posé en phase 1.

## Pourquoi cette phase

- Le dataset training plafonne sur la plupart des `eurio_id` faute
  de variation. Ces 3 sources apportent simultanément photos
  diverses **et** prix par condition.
- C'est le **stress test** du contrat `_base/`. Si les 3 sources
  s'écrivent confortablement après phase 1, le contrat tient.
- Catawiki est probablement le plus gros volume images in-hand de
  qualité décente disponible légalement (fair_use_research) hors eBay.

## Ordre proposé

### 2.1 NumisCorner (le plus simple)

- Site marchand structuré, fiches produit standardisées.
- Photos catalogue propres, fond neutre (≈ canonical).
- Prix par condition explicite (UNC, BU, FDC).
- Pas de quota dur, rate limit politesse 1 req/s.
- License : `fair_use_research`, `redistributable=false`.
- `variant_kind = 'merchant_catalog'` par défaut.
- **Bon premier candidat** car structuré + faible bruit, valide le
  contrat sans introduire les complexités d'un site dynamique.

### 2.2 CGB (FR pro)

- Site marchand FR, catalogue très riche, photos haute qualité.
- Grading très fin (FDC, SPL, SUP-62, …) → travail de mapping
  `condition_normalized` non trivial. Mettre la table de mapping
  exhaustive dans `_base/condition_map.py`.
- `variant_kind = 'merchant_catalog'`, parfois `'macro'` selon zoom.
- Volume : ~quelques milliers de fiches actives.

### 2.3 Catawiki (le plus complexe)

- Plateforme d'enchères, contenu dynamique JS — **scraping plus
  délicat**. Évaluer à l'attaque :
  - API publique disponible ?
  - rendering server-side suffisant pour scraper requests + bs4 ?
  - sinon Playwright headless (ajouter dépendance only-this-source).
- Vendeurs variables → photos très hétérogènes, **pipeline qualité
  (phase 3) crucial** pour cette source.
- Prix : enchères clôturées = prix de vente réel (proche eBay sold,
  manqué côté API gratuite). Très précieux.
- Conditions déclarées par le vendeur, parfois absentes → tolérer
  `condition_normalized='unknown'`.
- `variant_kind = 'auction_listing'` par défaut, parfois
  `'in_hand'` selon CV.

## Pour chaque source — checklist

Reprendre la checklist d'`module-contract.md` :

1. `ml/sources/<source>/` créé avec 4 fichiers
2. Entrée dans `sources_registry.py` + license_map + condition_map
3. `fetch.run` qui upsert images + quotes
4. Tasks `ml:src:<source>:{run,dry,limit,status}`
5. Carte admin via registry
6. Tests smoke
7. README module avec ToS, license, quirks

## Validation par source

À la fin de chaque sous-phase :

- `go-task ml:src:<source>:limit -- 5` produit 5 quotes + 10-30
  images en DB et sur disque.
- La carte apparaît dans `/sources` avec health + dernier run.
- `go-task ml:src:<source>:status` affiche dernier run + quota.

## Out of scope (phase 2)

- Pipeline qualité — les images entrent avec
  `training_eligible=false` jusqu'à phase 3. Acceptable parce que le
  training existant tourne sur les sources existantes en attendant.
- Page détail admin — phase 4. Phase 2 se valide sur les cards
  liste actuelles + go-task status.
- Wikipedia, eBay sold listings — futur, hors scope ici.

## Risques

- **ToS Catawiki/NumisCorner/CGB** : à vérifier avant tout fetch
  réel. En cas de refus explicite ToS, soit on n'en garde que les
  éléments de prix (sans images), soit on retire la source. Les
  modules sont conçus pour être désactivables proprement via le
  registry.
- **Volume disque** : un fetch complet Catawiki peut représenter
  plusieurs Go d'images. Prévoir politique de purge des
  `training_eligible=false` après N jours si on ne re-score pas.
