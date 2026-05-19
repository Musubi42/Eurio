# eBay multi-marketplace — index

> Chantier qui transforme l'extract eBay d'un single-marketplace `EBAY_FR`
> codé en dur (`ml/market/ebay_client.py:28`) vers une stratégie
> **GB (global) + marketplace natif selon l'origine de la pièce**, avec
> post-filter theme multilingue et visibilité côté admin sur les
> requêtes effectuées et les règles de filtrage actives.
>
> Pourquoi : Eurio est positionnée européenne. Le probe S3
> (`ml/state/probe_ebay_query_strategies_20260504T212313Z.json`) prouve
> qu'on rate ~95 % du marché actif en restant sur `EBAY_FR` seul. Voir
> `vision.md` §"Constat probe S3".

## Ordre de lecture

1. [`vision.md`](./vision.md) — cible end-state, KPI, scope, anti-objectifs.
   **Lire en premier.**
2. [`marketplace-map.md`](./marketplace-map.md) — table de correspondance
   pays → marketplace primaire + secondaire (GB toujours), langue native,
   dédup item_id cross-marketplace.
3. [`language-probe.md`](./language-probe.md) — probe systématique pour
   confirmer la langue réelle retournée par chaque marketplace et
   alimenter la map d'aliases i18n.
4. [`schema.md`](./schema.md) — migrations DB (`marketplace` sur
   `source_images` + `discovery_searches`, dédup item_id), impact sur
   `source_ref`.
5. [`front-ux.md`](./front-ux.md) — pilote eBay (stratégie visible),
   run-detail (1 row par (eurio_id, marketplace), funnel par marketplace),
   panel "règles actives" (NOISE_PATTERNS, prix×face, year policy, theme).
6. [`rollout.md`](./rollout.md) — chunks ordonnés, dépendances, critères
   de validation chunk-par-chunk.
7. [`i18n-bootstrap-kickoff.md`](./i18n-bootstrap-kickoff.md) — brief
   auto-suffisant pour la session qui livre I1 (scrape Numista 9 langues
   → `coin_names_i18n`). À lire avant d'attaquer la session i18n.

## Contexte amont (à lire si besoin)

- `docs/sources-refacto/ebay-kickoff.md` — base eBay enrichment (D-19 → D-27).
- `docs/sources-refacto/ebay-strategy-v2-kickoff.md` — première itération
  multi-marketplace + i18n (préfigure ce chantier ; on capitalise et on
  élargit).
- `docs/sources-refacto/ebay-strategy-v3-kickoff.md` — pagination + lot
  review price (orthogonal, peut être fait en parallèle).
- `docs/sources-refacto/listing-debug-view-kickoff.md` — fondation
  `discovery_searches` + `discarded_listings` qu'on étend ici.

## Sources de vérité

- Code legacy single-mkt : `ml/market/ebay_client.py`, `ml/sources/ebay/`.
- Probe data : `ml/state/probe_ebay_query_strategies_20260504T212313Z.json`
  (5 eurio_ids × 6 variantes).
- Schema : `ml/state/schema.sql` § `source_images`, `discovery_searches`,
  `discarded_listings`.
- Front actuel : `admin/packages/web/src/features/sources/`
  (`EbayPilotPanel.vue`, `SourceRunDetailPage.vue`, `SourceRunListingsPage.vue`).

## Décisions actées (verrouillées 2026-05-19)

- **D-MM1** Global catch-all = **EBAY_GB**. Non négociable pour V1.
- **D-MM2** Pour les pays sans marketplace dédié, **fallback par langue
  principale** (ex : LU→FR, AD→ES, SM/VA→IT). **PT→ES est provisoire**
  (à confirmer par mini-probe en chunk V1, défaut GB-only sinon — cf.
  `marketplace-map.md` §"Routage PT provisoire"). Si pas de marketplace
  dans la langue native (GR, BG, EE, FI, …) → GB-only.
- **D-MM3** Source i18n des théme-tokens = scraping HTML
  **`<lang>.numista.com/<id>`** en **9 langues**
  (`fr,en,de,it,es,nl,ru,pt,el`). Le `<h1>` est extrait, le tokenizer
  I2 fait le filtrage. **API Numista non utilisée** pour cette tâche
  — voir `i18n-bootstrap-kickoff.md` §"Décisions actées" pour la
  rationale (quota précieux, scrape future-proof).
- **D-MM4** Dédup cross-marketplace : `(source, source_ref)` UNIQUE
  existante suffit pour empêcher les doublons, **MAIS** le merge des
  `marketplace_found_json` est fait **en mémoire avant INSERT** par
  l'adapter — pas via `ON CONFLICT DO UPDATE`. Détails dans
  `schema.md` §"Stratégie d'écriture" et `rollout.md` chunk B4.
- **D-MM5** EBAY_BE bilingue → query en FR uniquement V1, matcher theme
  en FR+NL. Sacrifice volontaire du segment vendeur NL pour préserver
  l'invariant "GB toujours" (cf. `marketplace-map.md` note BE).
- **D-MM6** `endpoint` dans `discovery_searches` reste générique
  (`ebay.browse.search`) ; le marketplace vit exclusivement dans la
  colonne `marketplace`. Pas de duplication tolérée (cf.
  `marketplace-map.md` §"Convention endpoint vs colonne marketplace").
- **D-MM7** Théme-tokens multilingues sont **extraits du titre Numista
  localisé** (pas du slug EN), avec stop-words par langue. La voie
  "dict d'aliases EN→lang étendu" est explicitement rejetée comme dette
  technique (cf. `language-probe.md` §"Étape 2bis").

Les D-MMn supplantent rétroactivement les ébauches §2.B de
`ebay-strategy-v2-kickoff.md` qui restaient ouvertes (notamment BE→FR
qui était une approximation).

## Progress

Pas encore commencé. Ce chantier est figé en plan ; aucun chunk livré.
Mise à jour à chaque chunk via section §"Progress" dédiée à créer dans
chaque fichier concerné (ou un `progress.md` ajouté quand on démarre,
sur le modèle de `auto-validation/progress.md`).
