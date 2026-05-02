# Problèmes ouverts

> Questions identifiées pendant cette refacto qu'on **ne résout pas
> ici**. À traiter dans des refactos séparées.

## OP-1 — Résolution `listing → eurio_id`

### Le problème

Quand on récupère un listing eBay ou Catawiki, on a un titre
("2 euros Allemagne 2020 Kniefall von Warschau UNC"), parfois un
pays, une année. Pas de `numista_id` ni de `eurio_id` propre.

L'approche actuelle (matching naïf sur titre + filtres pays/année) :
- rate les variantes de wording (FR/EN/DE)
- assigne au mauvais `eurio_id` quand titres ambigus
- ignore les listings de lots

### Pourquoi c'est hors scope ici

C'est un problème de **résolution / NLP** orthogonal au refacto
ingestion. La refacto actuelle déplace simplement le problème : peu
importe que le matching soit imparfait, les rows `image_assets` et
`coin_market_quotes` peuvent être **réassignées** plus tard via une
update sur `eurio_id` sans toucher au reste du schéma.

### Pistes futures

- LLM léger sur les titres pour extraire (pays, année, programme,
  dénomination).
- Matching image-side : utiliser le modèle ArcFace existant pour
  matcher l'image listing à un cluster d'`eurio_id` connus.
- Review queue admin pour corriger à la main les bas-confiance.

## OP-2 — eBay sold listings (Marketplace Insights API)

### Le problème

eBay Browse expose des listings actifs, donc des prix demandés (pas
forcément vendus). La distribution réelle des prix de vente nécessite
**Marketplace Insights API**, qui est :
- payante
- soumise à approbation (programme partenaire)

### Statut

- À demander quand on aura un usage clair.
- Le schéma `coin_market_quotes` est prêt : `source = 'ebay_sold'`
  vs `'ebay_active'`. Pas de migration nécessaire le jour où on
  l'allume.

## OP-3 — Licences images marchand & enchères

### Le problème

Catawiki, NumisCorner, CGB, eBay ne donnent pas explicitement le
droit de stocker / utiliser leurs images pour entraînement ML. On
utilise `license = 'fair_use_research'` + `redistributable = false`
en partant de l'argument :
- usage interne de recherche
- pas de redistribution
- pas de concurrence directe (eurio est une app utilisateur, pas un
  scraper de marché)

C'est **défendable**, pas blindé. Avant un déploiement large ou un
modèle distribué publiquement entraîné sur ces images, repasser sur
chaque ToS et idéalement obtenir des accords explicites pour les
sources de gros volume (Catawiki en premier).

### Statut

- Documenter la position dans `docs/legal/data-sources.md`
  (à créer hors de cette refacto).
- Tagger systématiquement chaque row avec sa license, ne **jamais**
  exporter les images `redistributable=false` hors training.

## OP-4 — Backfill historique vers `image_assets`

### Le problème

Les images Numista déjà fetched (dans `coin_images` legacy) ne sont
pas dans `image_assets`. Pour le training futur, on aimerait y avoir
**toute** la donnée disponible, pas juste les nouveaux fetchs.

### Pistes

- Script one-shot `ml:src:numista:backfill-image-assets` qui crée
  les rows `image_assets` correspondantes pointant sur les fichiers
  existants. Pas de re-download.
- Décider si on duplique ou si on déprécate `coin_images` legacy.

### Statut

- Hors scope phase 1-4. À traiter quand le nouveau pipeline tourne
  en routine et qu'on veut consolider.

## OP-5 — Volume disque & politique de purge

### Le problème

Si on capture les images eBay (~3 par listing × ~500 listings ×
30 runs/an = 45k images/an) + Catawiki (volume comparable ou plus),
le disque local va grossir vite. Plusieurs Go par an facilement.

### Pistes

- Politique de purge : images `training_eligible=false` plus
  vieilles que N jours → suppression du fichier disque, row
  conservée avec `storage_path=null` pour audit.
- Migration vers S3/Supabase Storage à terme — le schéma supporte
  déjà via `storage_path` libre.

### Statut

- Hors scope V1. Tant que le disque tient, on continue.

## OP-6 — Versionning de `quality_pipeline_version`

### Le problème

Quand la chaîne de scoring change, des images vieilles ont un score
ancien et de nouvelles ont un score nouveau. Comparer R@1 lab à R@1
lab après changement devient bruité.

### Pistes

- Stocker `quality_pipeline_version` dans `raw_payload`.
- Re-scoring complet à chaque bump majeur.
- Snapshot du dataset par itération lab (cohérent avec
  `lab-prod-refacto/phase-2`).

### Statut

- Géré naturellement par le re-scoring (cf. phase 3).
