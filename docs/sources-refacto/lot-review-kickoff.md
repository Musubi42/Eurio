# Kickoff Lot Review — V1.5 (post-eBay)

> Brief auto-suffisant pour ouvrir la session "page de review dédiée
> aux lots multi-pièces" (V1.5 du parking lot eBay). À lire en premier
> dans la nouvelle conversation.

## Prompt à coller en début de session

```
J'ouvre une session pour implémenter la page de review dédiée aux
items kind='lot' (V1.5 du parking lot eBay). Lis ce fichier en entier :
docs/sources-refacto/lot-review-kickoff.md

Puis lis dans l'ordre :
  1. docs/sources-refacto/decisions.md (D-26 surtout)
  2. docs/sources-refacto/review-queue.md (vision complète)
  3. docs/sources-refacto/progress.md (dernière entrée — eBay livré)
  4. ml/api/review_queue_routes.py (endpoints single existants)
  5. ml/sources/_base/steps/enqueue.py (kind logic actuelle)
  6. admin/packages/web/src/features/review/ (single flow existant)

On découpe en chunks audit-par-chunk. Ordre proposé :
  - L.A — API endpoints lots (grouped par listing)
  - L.B — Page Vue /review/lots (grille + détail)
  - L.C — Action de décision multi-crop (bulk decide)
  - L.D — Tests + smoke sur vraies données accumulées
```

## Contexte produit

**eBay V1 livré 2026-05-03** : le pipeline ingère et flagge les lots
(D-26 niveaux 1+2), mais aucune UI n'existe pour les *résoudre*.
Aujourd'hui :

- Un titre eBay style "Coffret 5 pièces 2€ Belgique" → `is_lot_suspected=true`
  → toutes les images du listing → `review_queue.kind='lot'`
- Une photo "table shot" (le vendeur montre son stock) → `n_crops>1`
  sur cette image → cette image en `kind='lot'` (les autres images du
  listing restent en `kind='single'` si elles n'ont qu'1 crop)

Les rows `kind='lot'` s'accumulent dans `review_queue` en statut
`'open'`. La page `/review` actuelle (single-item flow) ne sait pas
les afficher différemment — elles apparaissent comme un crop normal,
mais **sans** pending_quote associée et **sans** `target_eurio_id`
fiable (le titre dit "5 pièces", on ne sait pas laquelle est laquelle).

## Pourquoi c'est nécessaire

1. **Gisement de training data perdu** : les coffrets eBay ont souvent
   des photos HD bien éclairées de plusieurs pièces. Sans UI dédiée,
   on les laisse dormir.
2. **Single review pollué** : si on tente de les traiter en single,
   le reviewer voit "voici une photo, choisis l'eurio_id" alors qu'il
   y a 3 pièces dans l'image. Confusion garantie.
3. **Cas D-26 niveau 2** (multi-coin photo sur listing single) :
   actuellement *toutes* les crops de cette image sortent en `kind='lot'`,
   y compris celles qui sont noise (table-shots de stocks). Le
   reviewer doit pouvoir picker la canonique et rejeter les autres.

## Deux cas distincts à supporter

### Cas A — Vraie lot listing (D-26 niveau 1)

**Signaux** : `source_images.is_lot_suspected = true` (titre matche
`lot|coffret|série|rouleau|set`).

**Sémantique** : le listing vend N pièces différentes pour un prix global.
Les photos peuvent être :
- N photos individuelles (1 par pièce) → 1 crop par photo
- Quelques photos table-shots (toutes les pièces ensemble) → N crops
- Mix des deux

**Action review** : pour chaque crop, soit assigner à un `eurio_id`,
soit rejeter (si c'est du noise). Le prix de l'annonce n'est **pas**
attribuable (D-15 : prix coffret non décomposable). Mais les images
deviennent du training data précieux.

### Cas B — Multi-coin photo sur listing single (D-26 niveau 2)

**Signaux** : `source_images.is_lot_suspected = false` MAIS
`COUNT(image_assets WHERE source_image_id = X) > 1`.

**Sémantique** : le titre dit "1 pièce, c'est X" (fiable parce que la
search était scopée sur cette pièce). Mais une des photos contient
plusieurs pièces (table-shot du stock du vendeur). Une seule crop est
*la* pièce vendue ; les autres sont noise.

**Action review** : picker la crop canonique (assigner à
`target_eurio_id` du listing) + rejeter les autres comme non-pièces
ou pièces hors-scope. Le pending_quote a déjà été créé (sur img0,
qui n'est pas l'image multi-coin probablement) → garder.

## Décisions à graver en début de session

### L-D-1 — Grouper par listing, pas par image

Une listing eBay = N source_images = potentiellement N×M image_assets
= N×M rows `review_queue.kind='lot'`. Le reviewer doit voir **tout
le listing en une fois** : titre, prix, toutes les photos, toutes
les crops. Sinon il décide à l'aveugle "cette pièce, c'est laquelle ?"
sans contexte.

**Implication** : la page `/review/lots` est une grille où chaque
*card* = un listing eBay. Cliquer une card = vue détail listing avec
toutes ses photos et crops.

**Clé de groupement** : pour eBay, `source_images.source_ref` matche
`ebay_<itemId>_img<N>`. On groupe par `<itemId>`. Pour catawiki, idem
`catawiki_lot_<lotId>_img<N>`. Pour les autres sources, à voir au
moment où elles arrivent (parking lot V2).

### L-D-2 — Décision multi-crop atomique par listing

Le reviewer voit toutes les crops d'un listing, fait ses N décisions
en une fois (drag-drop ou top-K + skip), puis "Valider listing".
**Pas de validation crop-par-crop dans le flow lot** (sinon retour
au pattern single, perte du contexte).

**API** : `POST /review-queue/lots/<listing_id>/decide` avec body
`{ assignments: [{ asset_id, eurio_id | reject_reason }, ... ] }`.
Chaque asset reçoit son verdict, le listing entier passe `done`.

### L-D-3 — Pas de promotion `pending_quote → coin_market_quote` sur lots

Cas A (vrai lot) : aucun pending_quote n'a été créé (D-26 a bloqué
au resolve). Donc rien à promouvoir.

Cas B (multi-coin photo) : un pending_quote a été créé (img0,
typiquement single-coin). À la review du lot (qui ne touche que les
crops multi-coin), on **garde** le pending_quote tel quel. Si plus
tard l'utilisateur résout aussi la review single (img0), le quote
sera promu normalement.

### L-D-4 — UI minimale V1.5, pas de drag-drop

Drag-drop est tentant mais long à coder propre. V1.5 livre :
- Liste verticale des crops, chacun avec un bouton "Assigner" qui
  ouvre `CoinSearchModal` (déjà existant)
- Bouton "Rejeter" par crop (preset reasons : `not_a_coin`,
  `out_of_scope`, `duplicate`)
- Bouton "Valider listing" en bas qui submit toutes les assignments

Drag-drop = V2 si ergo le justifie après usage.

### L-D-5 — Page `/review` unique avec toggle Single | Lot

**Mise à jour 2026-05-03** : décision architecture 3-axes admin
(cf. `coins-admin-kickoff.md`). La review est **un seul axe produit**,
on ne fait pas de page séparée `/review/lots`.

Implémentation :
- `/review` reste l'URL d'entrée, avec un toggle/tabs en haut :
  `Single` (défaut) | `Lot`
- Les **deux vues sont techniquement distinctes** pour V1.5 (composants
  différents, pas de mutualisation prématurée — cf. memory
  "Chunk-by-chunk avec audit visuel")
- Les **endpoints restent séparés** : `/review-queue?kind=single`
  (défaut côté serveur) et `/review-queue/lots`
- Filtres optionnels via query params : `?run_id=...`, `?eurio_id=...`,
  `?source=ebay` (entrées venues du breakdown de run, ou de la fiche
  pièce dans Coins V2)
- Risque "reviewer single voit une photo de lot" résolu par le filtre
  serveur `kind=single` par défaut sur l'endpoint single

Pas de migration de données — les rows existantes ont déjà leur kind
correct.

**Implication architecture front** : un seul `ReviewPage.vue` avec
deux sous-composants `SingleReviewView.vue` et `LotReviewView.vue`,
switchés par le toggle. Pas de routes nested type `/review/lots` —
juste `/review?mode=lot` ou un state interne.

## Architecture cible

```
ml/api/review_queue_routes.py
  ├── GET /review-queue                   ← filter kind=single by default (modif)
  ├── GET /review-queue/lots              ← NEW : groupé par listing
  ├── GET /review-queue/lots/<listing_id> ← NEW : détail 1 lot
  └── POST /review-queue/lots/<listing_id>/decide  ← NEW : bulk decisions

admin/packages/web/src/features/review/
  ├── pages/
  │   └── ReviewPage.vue                  ← shell unique avec toggle Single | Lot
  ├── views/
  │   ├── SingleReviewView.vue            ← extrait du flow existant
  │   └── LotReviewView.vue               ← NEW : grille de listings
  ├── components/
  │   ├── LotCard.vue                     ← NEW : 1 card grille
  │   ├── LotDetailDrawer.vue             ← NEW : vue détail full
  │   └── (existants : CoinSearchModal, CandidateRow réutilisés)
  └── composables/
      └── useLotReview.ts                 ← NEW : fetchLots, fetchLot, decideLot
```

## Pipeline de la session (chunks)

### L.A — API endpoints lots (~150 lignes)

**Modifs `review_queue_routes.py`** :

1. `GET /review-queue` : ajouter query param `kind=single|lot|all`
   default `single`. Filtre `WHERE rq.kind = ?`.
2. `GET /review-queue/lots` : list de listings groupés.
   Query SQL :
   ```sql
   SELECT
     -- Listing key (ebay_<itemId>, catawiki_<lotId>, ...)
     CASE
       WHEN si.source = 'ebay'
         THEN substr(si.source_ref, 1, length(si.source_ref) - length('_img' || cast(json_extract(si.raw_payload_json, '$.image_index') as text)))
       ELSE si.source_ref
     END AS listing_key,
     si.source,
     si.target_eurio_id,
     si.listing_title,
     si.listing_price,
     si.listing_currency,
     count(distinct si.id) AS n_images,
     count(distinct ia.id) AS n_crops_in_review,
     min(rq.enqueued_at) AS oldest_enqueued_at
   FROM review_queue rq
   JOIN image_assets ia ON ia.id = rq.image_asset_id
   JOIN source_images si ON si.id = ia.source_image_id
   WHERE rq.kind = 'lot' AND rq.status = 'open'
   GROUP BY listing_key
   ORDER BY oldest_enqueued_at ASC
   LIMIT ? OFFSET ?
   ```
   Réponse paginated `{ items, total }`.

3. `GET /review-queue/lots/<listing_key>` : détail
   ```json
   {
     "listing_key": "ebay_v1|336075712778|0",
     "source": "ebay",
     "target_eurio_id": "fr-2015-...",
     "listing_title": "Coffret 5 pièces ...",
     "listing_price": 25.0,
     "is_lot_suspected": true,
     "is_multi_crop_single": false,
     "images": [
       {
         "source_image_id": "...",
         "image_index": 0,
         "raw_url": "/sources/ebay/raws/<sha-prefix>/<file>.jpg",
         "crops": [
           { "asset_id": "...", "review_id": "...", "crop_url": "...",
             "crop_index": 0, "phash": ..., "current_eurio_id": null }
         ]
       },
       ...
     ]
   }
   ```

4. `POST /review-queue/lots/<listing_key>/decide` :
   ```json
   {
     "assignments": [
       { "asset_id": "...", "eurio_id": "be-2002-2eur-albert" },
       { "asset_id": "...", "reject_reason": "not_a_coin" },
       { "asset_id": "...", "skip": true }
     ]
   }
   ```
   Pour chaque assignment :
   - eurio_id présent → image_assets.resolution_status='manual',
     eurio_id=X, review_queue.status='done', decided_eurio_id=X
   - reject_reason présent → resolution_status='rejected',
     review_queue.status='done', decision_notes=reject_reason
   - skip=true → review_queue.status='skipped'
   
   Idempotent. Retourne `{ done: N, skipped: N, errors: [] }`.

**Endpoint storage des raws** : pour afficher la photo originale du
listing, on a besoin d'un endpoint qui sert le fichier raw. Aujourd'hui
on a `/sources/<id>/assets/<asset_id>/file` mais c'est la **crop**.
Il faut ajouter `/sources/<id>/raws/<source_image_id>/file` qui sert
`source_images.storage_path`. ~10 lignes.

### L.B — Page Vue `/review/lots` (~250 lignes)

**Route** : `/review` (shell unique) avec query param `?mode=lot`
pour activer la vue lot, et `?listing=<key>` pour deep-link sur un
lot précis (ouvre le drawer au mount).

**LotReviewPage.vue** :
- Header : count buckets ("47 lots à reviewer / 12 multi-crop / total 59")
- Grille de `LotCard` (3-4 colonnes) :
  - Thumbnail (1ère image)
  - Title du listing tronqué
  - Badge "Lot 5 pcs" ou "Multi-crop"
  - Source + price
  - "X crops à assigner"
- Click card → ouvre `LotDetailDrawer` (overlay 3/4 écran)

**LotCard.vue** : ~80 lignes, layout simple basé sur `EbayPilotPanel.vue`
existant pour cohérence.

**LotDetailDrawer.vue** :
- Panel gauche : grille des photos du listing (cliquer = zoom)
- Panel droit : liste des crops à reviewer avec pour chacun :
  - Thumbnail crop (224×224)
  - Bouton "Assigner" → ouvre `CoinSearchModal` (réutilisé du single)
  - Bouton "Rejeter" → dropdown des reasons
  - Bouton "Skip"
  - Affichage du verdict si déjà fait (vert "→ fr-2002-..." ou rouge "rejeté")
- Footer : "Valider listing (N décisions)" + "Annuler"
- Bouton actif uniquement si toutes les crops ont un verdict

### L.C — Bulk decide endpoint + intégration front (~80 lignes)

Déjà couvert dans L.A en backend. Côté front :
- `useLotReview.ts` : `decideLot(listingKey, assignments)` POST
- `LotDetailDrawer.vue` accumule les décisions en local state, les
  envoie au "Valider"
- Toast résultat + retour à la grille

### L.D — Tests + smoke

**Tests unit** :
- `test_review_lots_api.py` : endpoints lots (list, detail, decide)
  avec fixtures lots seed
- `test_review_kind_filter.py` : `/review-queue` filtre kind=single
  par défaut (régression du single flow)

**Smoke test manuel** :
- Lancer 2-3 vrais runs eBay sur des commémos populaires (FR 2015
  paix, DE 2015 EU flag) qui ont souvent des coffrets associés
- Vérifier que ≥ 5 rows `kind='lot'` apparaissent
- Ouvrir `/review/lots` → reviewer 1 lot complet
- Vérifier en DB : `review_queue.status='done'`,
  `image_assets.resolution_status='manual'`, eurio_ids cohérents

## Cas tricky à anticiper

### 1. Le listing a aussi des images en kind='single'

Une listing avec 5 photos peut avoir 4 photos single-coin + 1
table-shot multi-coin (5 crops). En review single, l'utilisateur
résout les 4 photos single normalement. En review lot, il voit le
listing entier ?

**Décision proposée** : la page `/review/lots` montre **uniquement
les photos qui ont des crops kind='lot'**. Les photos single du même
listing restent visibles dans `/review` single. Pas de cross-mixing.

C'est cohérent avec L-D-1 (groupement par listing) — la card affiche
"3 crops à reviewer" même si le listing a 7 crops au total dont 4
déjà résolus en single.

### 2. listing_key extraction pour les autres sources

L-D-1 dépend du pattern `<source>_<listing_id>_img<N>`. eBay, catawiki
ont ce pattern. Les sources sans multi-image (numista canonique : 1
listing = 1 source_image avec obverse + reverse comme image_assets
distincts) ne génèrent pas de lots normalement. À documenter dans
`module-contract.md` quand catawiki arrive.

### 3. Re-fetch d'un lot déjà reviewé

Si un eBay run re-discover le même `<itemId>` (par exemple le vendeur
re-up), idempotence des 5 couches : aucun nouveau row review_queue.
Les rows existantes restent `status='done'`. Bon comportement, rien
à coder.

Si on **veut** re-reviewer (parce qu'on a changé d'avis), c'est un
override manuel SQL ou un endpoint admin V2. Hors scope V1.5.

### 4. Lots avec dizaines de crops

Une "Collection 24 commémo BU" → 24 crops à assigner manuellement.
UX V1.5 : on liste tout dans le drawer, le reviewer scrolle. Pénible
mais 1× — ces grosses collections sont rares. Si on observe le
pattern, V2 ajoute un mode "assigner par batch sélection rectangulaire"
(cluster pHash D-07 propagation, déjà documenté en parking lot).

### 5. Aucune crop visible

Cas dégénéré : detect_crop a tout rejeté (image illisible) → 0
image_assets pour cette source_image. Donc 0 review_queue. Le listing
n'apparaît pas dans `/review/lots`. Bon comportement par construction.

### 6. Source_image avec la même crop dupliquée

pHash dedup intra-source attrape ça normalement (couche 4). Si pour
une raison X deux source_images ont des crops identiques pHash, la
2e hérite du label de la 1e (`auto_phash`). Donc ne montre pas en
review. Encore une fois, idempotence par construction.

## Décisions à valider en début de session L

Avant de coder L.A :

1. **`listing_key` extraction** : SQL inline (avec `substr` +
   `json_extract`) ou refacto en colonne stable `source_images.listing_key`
   stockée à l'ingestion ? Mon vote : **SQL inline V1.5** — plus
   léger, refacto column V2 si on observe que les requêtes sont lentes.

2. **Reject reasons preset** : `not_a_coin`, `out_of_scope`,
   `duplicate_in_listing`, `unreadable`, `other` (avec textarea libre).
   Mon vote : oui, ces 5 + textarea pour `other`.

3. **Que faire de `target_eurio_id` à la décision** : si le reviewer
   assigne un crop à un eurio_id différent de `source_images.target_eurio_id`,
   on update juste `image_assets.eurio_id` (pas le source_images.target).
   Le target reste un audit "cette pièce a été cherchée pour X". Vote : OK.

4. **Quand promouvoir `pending_quote → coin_market_quote`** :
   inchangé V1.5 (cf. L-D-3). Le hook reste sur la review single.
   Lots = jamais de quote.

5. **Pagination grille** : combien de lots par page ? 24 (4×6) ?
   Vote : 24, slider/infinite scroll V2.

6. **Auto-redirection si plus de lots** : quand le reviewer valide
   le dernier lot, il revient à la grille. Si grille vide, message
   "Tous les lots reviewés ✓". Pas de prefetch du suivant V1.5.

## Tests verts à conserver

```
tests/test_sources_base.py        8/8
tests/test_orchestrator.py       12/12
tests/test_bootstrap_coins.py     4/4
tests/test_ebay_adapter.py       24/24
tests/test_ebay_api.py            8/8
tests/test_resolve_lot_quote.py   9/9
                                ────
                                 65/65 ✅
```

L.D ajoute ~10 tests : `test_review_lots_api.py` + extension
`test_review_kind_filter.py`.

## Vérifications avant de coder

```bash
cd ml && .venv/bin/python -m pytest tests/test_resolve_lot_quote.py -q
# → 9 passed (kind logic actuelle)

# Combien de lots actuels en DB ?
sqlite3 ml/state/training.db "SELECT count(*) FROM review_queue WHERE kind='lot' AND status='open'"

# Distribution kind
sqlite3 ml/state/training.db "SELECT kind, count(*) FROM review_queue GROUP BY kind"
```

Si `count(lot) < 5`, lance un batch eBay sur des commémos commémoratives
qui ont souvent des coffrets (BE Albert II, FR 70 ans paix, DE Bundesländer)
pour générer des lots à reviewer en smoke L.D.

## Ce qu'on NE fait PAS dans la session L (V2)

- **Drag-drop** crop → eurio_id (UI fancy, gain marginal vs modal+top-K)
- **Cluster pHash propagate** "appliquer à toutes les similaires"
  (déjà documenté en parking lot ebay-kickoff §"Évolutions futures")
- **Multi-source lot review** (catawiki, etc. — viendront avec leurs
  propres tests)
- **Re-review d'un lot done** (override admin V2)
- **Promotion automatique d'un quote sur résolution multi-coin**
  (sémantique floue, on garde D-15 strict)
- **Filtres avancés** sur la grille (par pays, par date, par source) —
  V2 si besoin

## Sortie attendue

À la fin de la session L :
- 5+ lots reviewés à la main, image_assets.resolution_status='manual'
  avec eurio_ids cohérents validés humainement
- Tests 75/75 verts (65 + ~10)
- Front : page `/review/lots` opérationnelle, drawer fluide,
  bouton "Valider listing" fonctionne
- `progress.md` documenté avec stats observées (taux de noise dans
  les multi-crop, distribution lot vs multi-crop, temps moyen
  par lot)

## Contraintes héritées

- **R0 pas de dette technique** (CLAUDE.md)
- **D-26 niveaux 1+2** : kind logic acté
- **D-15** : prix de lot non décomposable, pas de quote
- **R1 proto-first** : ⚠️ la lot review page n'existe pas dans le
  prototype HTML actuel. **À ajouter au proto avant L.B** sinon
  on viole la règle. Cf. `docs/design/_shared/parity-rules.md` §R6.
- Pas d'emojis dans le code.

## Comment reprendre dans une nouvelle session

1. Lire ce fichier en entier (5 min).
2. Lire `decisions.md` D-26.
3. Vérifier les tests : `cd ml && .venv/bin/python -m pytest tests/ -q`
4. Compter les lots disponibles (cf. §"Vérifications avant de coder").
5. Si < 5 lots, lancer 2 batches eBay pour en générer.
6. Attaquer L.A (API endpoints).
