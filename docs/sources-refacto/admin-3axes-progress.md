# Progress — Admin 3-axes (Sources / Review / Coins)

> Suivi exclusif des 3 phases du chantier admin 3-axes décidé le
> 2026-05-03. Pour le contexte produit, lire d'abord :
> - `coins-admin-kickoff.md` (vision Coins + 3-axes)
> - `run-breakdown-kickoff.md` (Phase 1)
> - `lot-review-kickoff.md` (Phase 2, V1.5)
>
> Cadence : chunk-by-chunk avec audit visuel — je livre, on review,
> on valide, on continue. Pas d'enchaînement sans "go".

## Vue d'ensemble

| Phase | Objet | Statut |
|---|---|---|
| 1 — Sources | Run breakdown par eurio_id | 🟡 in-progress |
| 2 — Review | Page unique Single \| Lot (V1.5) | ⏸ planifié |
| 3 — Coins | Vue produit agrégée multi-source | ⏸ planifié post-Phase 2 |

## Phase 1 — Run breakdown

| Chunk | Périmètre | Statut | Livré le | Reviewé le |
|---|---|---|---|---|
| RB.A | Endpoint backend + tests | 🟢 livré | 2026-05-03 | ✅ validé 2026-05-04 |
| RB.A+ | via_lot sur les deux axes | 🟢 livré | 2026-05-04 | ✅ validé 2026-05-04 |
| RB.B | Page Vue + nav | 🟢 livré | 2026-05-04 | ✅ validé 2026-05-04 |
| RB.C | Polish UX (rows clickables, header Review, tooltips) | 🟢 livré | 2026-05-04 | ⏳ à reviewer |

### Sessions

#### 2026-05-03 — RB.A livré

- `compute_run_breakdown()` + endpoint `GET /sources/:id/runs/:run_id/breakdown`
  dans `ml/api/sources_routes.py` (~210 lignes ajoutées, dont
  models Pydantic + 2 helpers SQL).
- 6 tests dans `ml/tests/test_run_breakdown.py` : 404, ciblés vides,
  ciblés auto-résolus, ciblés en review (single+lot), bonus via lot,
  run dry sans filtres.
- Suite globale : **72/72 verts** (65 baseline + 6 nouveaux + 1 qui
  n'était pas compté dans la baseline du kickoff).
- **Refacto sémantique post-feedback Raphaël (2026-05-04)** : abandon
  du modèle 2-blocs (targeted/bonus) à cause du double-comptage. Nouveau
  modèle :
  - **Un seul bloc `per_eurio`** (was_targeted=True d'abord, puis
    discovered alphabétique).
  - **Deux axes strictement disjoints** par eurio_id :
    - Search axis (`si.target_eurio_id = E`) : `n_listings` +
      `n_crops_searched` partitionnés en `n_searched_{auto,
      review_single, review_lot, pending, rejected}` (somme = total).
    - Attribution axis (`ia.eurio_id = E AND si.target_eurio_id != E`) :
      `n_attributed_from_other` + `via_lot`.
  - **Ajouts** : `n_searched_pending` et `n_searched_rejected` (demandés
    par Raphaël). `n_searched_pending` exclut les crops ayant une row
    `review_queue` open (sinon double-comptage avec n_searched_review_*).
- Tests : 7/7 verts (404, ciblés vides, ciblés auto+quote, ciblés review
  single+lot, ciblés rejected, attribution via lot, dry sans filtres).
- Suite globale Phase 1 : **73/73 verts**.
- **Reste smoke curl** : serveur tourne sur **port 8042** (uvicorn
  --reload), donc la nouvelle route est dispo sans redémarrage manuel.

#### 2026-05-04 — RB.A+ et RB.B livrés

**RB.A+** : `via_lot` étendu aux deux axes. Désormais `via_lot=true`
si soit l'attribution axis (crops résolus depuis un autre listing
lot), soit le search axis (target qui a ramené un listing
is_lot_suspected ou multi-crop). Helper `_has_lot_context` ajouté.
Tests : 7/7 verts (1 assertion ajustée).

**RB.B** : page `/sources/:id/runs/:run_id` opérationnelle.
- `useRunBreakdown.ts` : composable + types + `RunBreakdownError`
  (~70 lignes).
- `SourceRunDetailPage.vue` : ~360 lignes. Header (run_id, source,
  status pill, started_at, count ciblés/découverts). 2 sections :
  - **Ciblés** : tableau dense 12 colonnes (eurio_id cliquable copy,
    n_listings, n_crops, partition exhaustive search axis colorée
    par signal, n_attributed_from_other, n_quotes, badge lot, lien
    review). Ligne Total en bas.
  - **Découverts** : tableau réduit (eurio_id, attr, lot, quotes, review)
    visible seulement si non-vide.
  Légende en pied pour expliciter la sémantique des colonnes.
- Route `/sources/:id/runs/:run_id` ajoutée dans `app/router.ts`.
- `SourceDetailPage.vue` : rows table runs cliquables (hover bg +
  navigation, exclu si click sur un bouton enfant comme "log").
- Type-check `vue-tsc` : 0 erreur sur nos fichiers (les erreurs
  préexistantes dans `features/sets/` ne sont pas touchées).
- Tests Python : 73/73 verts.

#### 2026-05-04 — RB.C (polish UX) livré

Feedback Raphaël après revue RB.B → 3 ajustements :
1. **Rows entières cliquables** dans les deux tableaux (Ciblés +
   Découverts), avec hover bg `var(--surface-1)` (mimique de la
   table runs sur SourceDetailPage). Click → `/coins/:eurio_id`.
   Helper `onRowClick` qui exclut les clics sur boutons enfants
   (`closest('button, a')`) + `@click.stop` sur le bouton review
   pour double-sécurité. La copie clipboard sur eurio_id est
   supprimée — le click ouvre maintenant la fiche pièce.
2. **Header colonne "Review"** ajouté avec icône `Search`
   (lucide). Bouton review enrichi : icône Search + texte "review"
   + ExternalLink, sur fond bordé qui s'allume gold au hover. Quand
   pas d'item review : `·` (inchangé).
3. **Tooltips `title=""` sur tous les headers** des deux tableaux
   (List., Crops, Auto, Rev.S, Rev.L, Pend., Rej., Attr., Quotes,
   Lot ?, Review). Explicite la sémantique sans lire la légende.

Phase 1 livrée techniquement. Smoke fait (le user a confirmé que le
curl renvoie bien le breakdown du run Andorre, et a navigué sur la
page UI).

## Phase 2 — Review unifié + Lot V1.5

| Chunk | Périmètre | Statut |
|---|---|---|
| R.0 | Refacto ReviewPage en shell + extract SingleReviewView | 🟢 livré 2026-05-04 ✅ validé |
| L.A | API endpoints lots (list / detail / decide) | 🟢 livré 2026-05-04 ✅ validé |
| L.B | LotReviewView + LotCard + LotDetailDrawer | 🟢 livré 2026-05-04 ✅ validé (drawer drop chunk 5) |
| L.C.1 | Bulk checkboxes + sub-footer indigo | 🟢 livré 2026-05-04 ✅ validé |
| L.C.2 | Raccourcis clavier drawer (composable useLotReviewKeybinds) | 🟢 livré 2026-05-04 ✅ validé |
| L.C.3 | Deep-link toggle depuis breakdown run | 🟢 livré 2026-05-04 ✅ validé |
| **Chunk 1** | Backend multi-Hough detection (eBay) | 🟢 livré 2026-05-04 ✅ validé |
| **Chunk 2** | Cleanup eBay (SQL + recrop script) | 🟢 livré 2026-05-04 (exec côté user) |
| **Chunk 3** | API détections + nav prev/next | 🟢 livré 2026-05-04 ✅ validé |
| **Chunk 4** | Tokens parchment (admin override) | 🟢 livré 2026-05-04 ✅ validé |
| **Chunk 5** | Page Vue full-page LotReviewDetailPage | 🟢 livré 2026-05-04 ⏳ à smoke-tester |
| **Chunk 6** | Raccourcis étendus (D/←/→/chain) | 🟢 livré dans chunk 5 (consolidé) |
| **Chunk 7** | Smoke vraies données | ⏸ à faire en session suivante |
| L.D | Tests Python (déjà couvert dans chunk 3 backend) | 🟢 livré (19/19 review_lots_api) |

### Sessions Phase 2

#### 2026-05-04 — R.0 livré

- `views/SingleReviewView.vue` (~310 lignes) : extraction complète
  du flow review historique sans modification fonctionnelle. Stats,
  boutons F/?, queue, item courant, action bar, undo toast, help
  overlay, search modal — tout déplacé dans la vue.
- `views/LotReviewView.vue` (~30 lignes) : placeholder avec icône
  Package + texte "V1.5 en cours" + pointeur vers le kickoff.
- `pages/ReviewPage.vue` réécrit en shell (~100 lignes) : titre
  "Review queue" + toggle Single | Lot dense (rounded toggle group
  style segmented control). Mode persisté via `?mode=lot` (atterrissage
  depuis breakdown de run pourra forcer mode=lot via query param).
- 0 erreur `vue-tsc` sur les fichiers review.
- Aucune régression fonctionnelle attendue : le mode `single` mount
  exactement le même code qu'avant.

#### 2026-05-04 — L.A (API endpoints lots) livré

**Modifications `ml/api/review_queue_routes.py`** :
- Constante `_LISTING_KEY_SQL` : extraction du listing_key via
  `json_extract(raw_payload_json, '$.ebay_item_id')` pour eBay,
  fallback `source_ref` pour les autres sources. Documenté pour
  catawiki/futures.
- `GET /review-queue?kind=single|lot|all` : nouveau paramètre,
  default `single` (ferme la régression L-D-5). 422 si kind invalide.
- `GET /review-queue/lots` : liste paginated, 1 ligne par listing_key,
  thumb_url pointant sur la 1ère raw, ordre `oldest_enqueued_at ASC`.
- `GET /review-queue/lots/{listing_key}` : détail avec sections
  `images: [{source_image_id, image_index, raw_url, crops:[...]}, ...]`,
  flag `is_multi_crop_single` (D-26 niveau 2).
- `POST /review-queue/lots/{listing_key}/decide` : bulk decide ;
  chaque assignment = `{asset_id, eurio_id|reject_reason|skip}`.
  Validation : asset doit appartenir au listing, reject_reason whitelist,
  idempotence sur déjà-done. Réponse `{done, rejected, skipped, errors}`.
- Routes `/lots*` déclarées AVANT `/{review_id}` (sinon FastAPI capture
  "lots" comme un review_id).

**Modification `ml/api/sources_routes.py`** :
- `GET /sources/{source_id}/raws/{source_image_id}/file` : sert le
  fichier raw d'un source_image (différent de `/assets/.../file`
  qui sert le crop). ~10 lignes.

**Tests `ml/tests/test_review_lots_api.py`** : 15 tests couvrant filtre
kind (4), liste lots (3), détail lot (3), decide (5). FastAPI app
in-memory + override de `_store` via monkeypatch.

**Suite globale** : 88/88 verts (73 baseline Phase 1 + 15 L.A).

#### 2026-05-04 — L.B (front lot review) livré

**Composable `composables/useLotReview.ts`** (~170 lignes) :
- Types TS strictement alignés sur les Pydantic models de L.A
  (LotListItem, LotDetail, LotImage, LotCrop, LotCandidate, LotBbox,
  LotAssignment, LotDecideResponse, LotRejectReason).
- `fetchLots` / `fetchLot` / `decideLot` avec `LotReviewError`.
- Préfixe automatique `ML_API` sur les URLs raw_url/crop_url/thumb_url
  (cohérent avec le pattern `useSourceDetail.ts`).

**Composant `components/LotCard.vue`** (~95 lignes) :
- Aspect 4/3 thumbnail avec fallback icône Image
- Badge type en overlay : "Lot" (gold) ou "Multi-crop" (indigo)
- Badge count crops/images en overlay bas-droite
- Footer : titre tronqué 2 lignes, source, prix, date relative
  (il y a Xj/h/min), target_eurio_id si présent
- Hover : border-color → gold, légère scale sur l'image
- Click : émet `open(listing_key)`

**Composant `components/LotDetailDrawer.vue`** (~440 lignes) :
- Drawer 85vw glissant depuis la droite, backdrop cliquable
- Header : badge type, listing_key, titre, source/prix/cible
- Layout 2 colonnes :
  - Gauche (40%) : galerie verticale des raws avec compteur crops/img
  - Droite (60%) : liste des crops actionnables (ceux ayant une review_id)
- Par crop : thumbnail 80×80, label img/crop, candidats top-3 cliquables,
  3 boutons d'action (Assigner / Rejeter / Skip), bouton Annuler décision
- Rejeter : `<details>` dropdown avec les 5 reasons whitelistées
- Assigner : ouvre `CoinSearchModal` (réutilisé du single)
- État local des décisions par asset_id (assign | reject | skip)
- Couleur de border de la row crop colorée selon décision (success/danger/ink)
- Footer : compteur "X / N décisions" + bouton "Valider listing" actif
  uniquement si toutes les actionnables sont décidées
- Submit appelle `decideLot` avec les assignments compilés, émet `decided`
- Helper `isAssignedTo()` extrait pour contourner la limitation Vue
  template parser sur les casts TS inline

**Vue `views/LotReviewView.vue`** (~135 lignes, remplace le placeholder) :
- Sub-header : compteur total + hint clavier
- Grille responsive (1/2/3/4 colonnes selon breakpoint)
- État vide avec icône Package
- Drawer monté en permanence, listing_key pioché depuis `?listing=`
  (deep-linkable, navigation back/forward navigable)
- Esc ferme le drawer (listener attaché/détaché via watch)
- Toast "Listing validé · X assignés · Y rejetés · Z reportés" 4.5s
  après decide success, puis reload de la grille

**TS** : 0 erreur sur tous les fichiers review (corrigé un cas où le
parser Vue n'aimait pas un cast inline `as { ... }` dans un :style —
remplacé par helper `isAssignedTo`).

#### 2026-05-04 — L.C (polish + raccourcis + deep-link) livré

**L.C.1 — Bulk via checkboxes + sub-footer** dans
`components/LotDetailDrawer.vue` (~80 lignes ajoutées) :
- `selected: ref<Set<string>>` (asset_ids cochés), `bulkMode = size > 0`
- Checkbox top-right de chaque crop row, indigo si cochée
- Master "tout sélec. / désélec." dans le header de section
- Sub-footer overlay indigo au-dessus du footer principal avec
  Assigner / Rejeter ▾ / Skip / Désélec.
- Bulk Assigner ouvre `CoinSearchModal` en mode bulk → applique le même
  eurio_id à tous les sélectionnés (le user a explicitement préféré ce
  pattern à un "tout assigner à la cible" qui n'a de sens que sur lots
  de N pièces identiques)

**L.C.2 — Raccourcis clavier drawer** :
- Nouveau composable `composables/useLotReviewKeybinds.ts` (~80 lignes),
  nomenclature alignée sur `useReviewKeybinds` (single)
- Mapping : 1-5 assign top-N, F search, R reject, N skip, O/V/U face,
  J/K (et ↑↓) crop actif suivant/précédent, Enter submit, ?
  help, Esc cascade fermeture (help → search → bulk → drawer)
- `kbAssignCandidate`, `kbRejectActive`, `kbSkipActive`, `kbSubmit`
  agissent sur le crop actif (ring gold, scrollIntoView smooth)
- Help overlay raccourcis intégré dans le drawer

**L.C.3 — Deep-link toggle depuis breakdown** :
- `SourceRunDetailPage.gotoReview()` : si row a uniquement
  `n_searched_review_lot > 0` → `mode=lot`, sinon default single
- Tooltips review buttons mis à jour

#### 2026-05-04 — Chantier *Specimen Plate* (chunks 1-5)

Décision : refondre la review lot en **route full-page**
`/review/lot/:listing_key` avec **vue debug 3-stages** (raw + cercles
détectés + crops). Drop du drawer 85vw en faveur d'une page entière —
le drawer trop étroit pour les raws eBay 2K-3K et la vue 3-stages
gagne en lisibilité avec plus de surface.

**Proto HTML** : `docs/sources-refacto/prototype-review-lot-debug.html`
(autonome, ~1300 lignes, esthétique "specimen sheet / forensic
cabinet" — Cormorant Garamond italic, parchment cream, tags numérotés
liant cercles ↔ crops).

**Chunk 1 — Backend multi-Hough** (`ml/scan/normalize_snap.py` +
`ml/sources/_base/steps/detect_crop.py`) :
- Nouveau dataclass `CircleDetection(cx, cy, r, accepted, reject_reason,
  method)`
- Nouvelle fonction `detect_circles_multi(bgr) → list[CircleDetection]`
  — single-pass loose Hough + per-circle strict filtering. Retourne
  *acceptés* et *rejetés* (avec raison) pour la vue debug Stage 2.
- Nouvelle fonction `normalize_listing(bgr) → list[NormalizationResult]`
  — un crop 224×224 par cercle accepté.
- `normalize_studio` / `normalize_device` **inchangés** (Numista
  pipeline + scan Android intacts).
- `detect_crop.py` : routage par source (`mock`/`numista` → studio,
  reste → listing), boucle sur N cercles, émet `image_assets` avec
  `crop_index 0..N-1`, idempotence revue.
- 11 nouveaux tests dans `tests/test_normalize_listing.py`.
- Régression : 105/105 verts (orchestrator + ebay + review_lots +
  breakdown + sources_base + resolve_lot_quote + normalize_dispatch).

**Tuning multi-Hough** : `rmin_loose=6%`, `rmin_strict=10%`,
`rmax=55%`, `minDist=18%`, `param1=80`, `param2=22`. À tuner sur
vraies images eBay au smoke (chunk 7).

**Chunk 2 — Cleanup eBay** (`docs/sources-refacto/cleanup-ebay-crops.sql`
+ `ml/scripts/recrop_ebay_orphans.py`) :
- SQL idempotent : supprime `image_assets` non-manual eBay +
  `review_queue` open/skipped, reset `discovery_log.pipeline_state` à
  `'downloaded'` (le user a corrigé le schéma — `pipeline_state` vit
  sur `discovery_log`, pas `source_images`).
- Préserve : `source_images` (raws sur disque), `image_assets` manual
  (décisions humaines déjà prises), `review_queue` done.
- Compteurs BEFORE/AFTER pour validation visuelle avant COMMIT.
- Script Python recrop : reprend les source_images au state `'downloaded'`
  (JOIN discovery_log), nettoie les .png orphelins sur disque, lance
  `run_detect_crop` dans un `start_run(kind='reset')`.
- **Exec manuelle** (pas de go-task) : backup DB → SQL → script
  Python `--dry` → `--limit 5` → full run.

**Chunk 3 — API détections + nav prev/next**
(`ml/api/review_queue_routes.py`, +~80 lignes) :
- Nouveau modèle `LotDetection(cx, cy, r, accepted, reject_reason,
  method, crop_index)`.
- `LotImage` étendu : `raw_width`, `raw_height`, `detections`.
- `LotDetail` étendu : `prev_listing_key`, `next_listing_key`.
- `_compute_detections(raw_path, crop_indices)` : compute on-the-fly
  via `detect_circles_multi` (no persistance, déterministe). Latence
  estimée 50-200ms par image.
- `_siblings(conn, listing_key)` : ordre `MIN(enqueued_at) ASC` sur la
  file lot open → `(prev, next)`.
- 4 nouveaux tests dans `test_review_lots_api.py` (raw_dimensions,
  detections empty si raw missing, detections computed depuis raw réel
  synthétique 2-cercles, nav prev/next sur 3 lots).
- 19/19 review_lots_api verts ✅ ; 91/91 pipeline complète verte.

**Chunk 4 — Tokens parchment (admin only)**
(`admin/packages/web/src/styles/index.css`) :
- Override `--surface` (#F5F1E7), `--surface-1` (#EDE8DA),
  `--surface-2` (#E2DBC8), `--surface-3` (#D0C7B2), `--paper`.
- HSL shadcn-vue mappings synchronisés.
- ⚠ `shared/tokens.css` global **intact** : Android theme préservé
  (Color.kt généré via tokens partagés).

**Chunk 5 — Page Vue full-page** :
- Nouvelle page `pages/LotReviewDetailPage.vue` (~720 lignes), port
  complet de la proto HTML.
- Nouvelle route `/review/lot/:listing_key` dans `app/router.ts`.
- Composable `useLotReview.ts` étendu : types `LotDetection`,
  `raw_width/height`, `detections`, `prev/next_listing_key`.
- `LotReviewView.vue` : `openLot` push vers la route (au lieu d'ouvrir
  drawer via query param `?listing=`).
- 🗑 **Drop** `components/LotDetailDrawer.vue` (700 lignes supprimées).
- UX livrée :
  - Header : Case № + listing_key mono + tags + titre Cormorant italic
  - Stage 1+2 superposés : raw strip + plate frame avec SVG overlay
    cercles (acceptés gold + rejetés danger dashed + tag badges
    numérotés)
  - Stage 3 : isolates panel 480px, crop cards avec tag numéroté
    top-left, bulk checkbox top-right, candidates chips, actions,
    décisions colorées
  - Bulk sub-footer indigo (preserve L.C.1)
  - Footer principal avec progress bar gold + hints clavier
  - Help overlay (incl. nouveau raccourci `D` overlay toggle)
- **Nav prev/next** + **chain** : toggle dans le header (gold quand ON
  par défaut), validate→next auto si chain ON, sinon retour grille.
- **Raccourcis** : J/K nav, 1-5 assign, F search, R reject, N skip,
  O/V/U face, **D toggle overlay**, **← / → prev/next listing** (si
  pas de crops actionnables), Enter submit, Esc cascade, ? help.
- 0 erreur vue-tsc sur les fichiers review.

**Chunk 6** : raccourcis étendus consolidés directement dans chunk 5
(D, ←, →, chain) — pas de chunk séparé livré.

**Reste : Chunk 7 — Smoke vraies données**
(à faire en session suivante)
- Pré-requis : cleanup eBay exécuté + recrop_ebay_orphans terminé
- Ouvrir un vrai lot multi-coin sur la nouvelle page
- Vérifier : détections visibles, tags numérotés cohérents, crops
  cliquables, raccourcis clavier, validate→next chain, prev/next nav
- Tuning éventuel des params Hough si rejets/parasites observés sur
  vraies images
- Audit visuel parchment palette (Chunk 4) sur toutes les pages admin

## Phase 3 — Coins admin

À planifier après validation Phase 2 et accumulation de données
(≥ 3 sources actives, ≥ 50 pièces couvertes). Cf.
`coins-admin-kickoff.md` §"Pré-requis avant d'attaquer".

## Décisions prises pendant le chantier

(à compléter au fil des sessions ; les décisions structurelles
restent dans `decisions.md` global, ici on note seulement les micro
ajustements liés à l'exécution)

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

Phase 1 ajoute ~5 tests. Phase 2 ajoute ~10 tests. Phase 3 TBD.

État après chunks 1+3 (2026-05-04) :

```
tests/test_normalize_listing.py     11/11   (Chunk 1)
tests/test_review_lots_api.py       19/19   (15 baseline + 4 chunk 3)
tests/test_orchestrator.py          12/12   (vert avec routage studio/listing)
tests/test_run_breakdown.py          7/7
tests/test_normalize_dispatch.py     ✓
                                   ─────
Pipeline-relevant tests:           105/105 ✅
```

Échecs préexistants ailleurs (test_benchmark, test_eurio_referential,
test_lab_api) : `ModuleNotFoundError: 'evaluate_real_photos'`,
non touchés par ce chantier.
