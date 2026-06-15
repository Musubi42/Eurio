# PROMPT — Session « Améliorer la review (fix bugs) »

> À coller dans une nouvelle session Claude Code (repo Eurio). Auto-suffisant.
> Écrit 2026-06-15 à la fin d'une session crop-recovery (contexte ci-dessous).

## Ta mission

Améliorer l'app de **review admin** (`http://localhost:5173/review`), **surtout fixer des
bugs**. Le PO (Raphaël) fait ses reviews à la main et bute sur des bugs/frictions. Tu vas
**reproduire chaque bug dans l'app qui tourne**, le localiser via la carte ci-dessous, le
corriger proprement, et **vérifier le fix dans le navigateur** avant de conclure.

**Méthode (non négociable, cf. `feedback_handoff_quality` en mémoire)** : preuve-first. Pour
CHAQUE bug : (1) reproduis-le sur données réelles dans l'app, (2) montre la cause dans le
code (fichier:ligne), (3) corrige, (4) re-teste dans l'app et montre que c'est réglé. Pas de
fix « à l'aveugle » sur hypothèse.

**Commence par demander au PO de te lister/démontrer les bugs qu'il voit** (il en a en tête).
Ne devine pas une liste de bugs — fais-toi les montrer, puis attaque-les un par un (chunk par
chunk, cf. `feedback_chunk_audit_flow` : livre + attends la rétro, n'enchaîne pas sans « go »).

## Comment lancer & vérifier (l'app tourne peut-être déjà)

```bash
# ML API (port 8042) — source de vérité = ml/state/eurio.db
go-task ml:api          # uvicorn serving.server:app --port 8042 --reload

# Front admin (port 5173)
cd admin/packages/web && pnpm dev    # vite

# (séparé, PAS la review locale) service review collaboratif = go-task ml:review:serve (:8048)
```

- Front → ML API sur `http://127.0.0.1:8042` (constante `ML_API` dans
  `admin/packages/web/src/features/review/composables/useReviewApi.ts`).
- L'API est en `--reload` → tes edits Python sont pris en compte sans redémarrer.
- Le front Vite a le HMR → tes edits `.vue/.ts` sont live.
- **Vérif navigateur** : tu peux piloter Chrome via le MCP `chrome-devtools` (navigate /
  screenshot / console). ⚠️ Si « browser already running », le profil est tenu (ferme l'autre
  instance ou demande au PO de regarder). À défaut, vérifie via `curl` l'endpoint + demande
  au PO de confirmer visuellement.
- **Type-check front** : `cd admin/packages/web && npx vue-tsc --noEmit` (⚠️ il y a des
  erreurs TS **préexistantes** hors review — ne corrige que les tiennes ; filtre sur
  `features/review`).

## Carte de la feature review (pour localiser vite)

### Front — `admin/packages/web/src/features/review/`

**Pages** (routées dans `admin/packages/web/src/app/router.ts`) :
| Route | Page | Rôle |
|---|---|---|
| `/review` | `ReviewDashboardPage.vue` | Dashboard : counts par lane (manual/auto_accept/ccproxy) + stats + batch |
| `/review/manual` | `ReviewPage.vue` → `SingleReviewView.vue` / `LotReviewView.vue` | Queue single OU lot (toggle `?mode=lot`) — **c'est là que le PO review** |
| `/review/lot/:listing_key` | `LotReviewDetailPage.vue` | Détail lot : images + crops + recrop + decide bulk |
| `/review/auto-accept` | `AutoAcceptReviewPage.vue` | Lane Dino auto (crop ↔ top-1, ACK bulk) |
| `/review/ccproxy` | `ClaudeReviewPage.vue` | Lane Claude vision (verdicts Sonnet, ACK/reject) |
| `/review/recover` | `RecoverRejectedPage.vue` | Grille des rejetés, un-reject en masse |
| `/review/peer-arbitration` | `PeerArbitrationPage.vue` | (review_service collaboratif, review.db — **séparé** de la queue locale) |

**Composants clés** :
- `ReviewRightColumn.vue` — colonne droite du single : target/standard candidates, group
  candidates (2€ commémo même pays/année), `DinoSuggestions.vue` (top-K DINOv2), recherche
  libre (`FreeSelectorPanel.vue`, touche F).
- `ReviewActionBar.vue` — Validate (⏎) / Reject (R) / Skip (N) + **undo toast (commit
  différé 10s)** + face selector.
- `DinoSuggestions.vue` — top-K Dino, dual band (pays + global), abstention (confident /
  low_margin / uncertain). `useDinoSuggestions.ts`.
- `CircleCropEditor.vue` — éditeur de cercle de recrop (touche E). **Vient d'être fixé** (voir
  « déjà fait » plus bas). Le cercle de départ = `suggested_circle ?? hint` (ligne ~153).
- `AutoValidateVerdict.vue` (verdict consensus, fait foi) vs `DinoVerdict.vue` (display).
- `ListingContextCard.vue` / `TextSignals.vue` — listing_kind / condition / sold_qty (touches K/C).

**Composables** : `useReviewApi.ts` (tous les appels API), `useReviewKeybinds.ts` (raccourcis),
`useDinoSuggestions.ts`, `useLotReview.ts` (flow lot), `useCoinsSearch.ts` (recherche libre).

**Raccourcis clavier** (`useReviewKeybinds.ts`) : `1-5` focus candidat · `⏎` valider · `R`
reject · `N` skip · `F` recherche libre · `O/V/U` face obverse/reverse/unknown · `K` cycle
listing_kind · `C` cycle condition · `D` accepter Dino top-1 · `E` recrop · `L` requalif en
lot · `Esc` fermer.

### Back — `ml/review/review_queue_routes.py` (~4100 lignes) + `ml/serving/crop_edit.py`

Endpoints principaux (préfixe `/review-queue`) :
- `GET /review-queue` — 20 items priorisés (filtres status/kind/lane/cohort_id/eurio_id).
- `GET /review-queue/{id}` · `POST /{id}/decide` (assign eurio_id+face) · `POST /{id}/reject`
  · `POST /{id}/skip`.
- `GET /review-queue/stats` · `/triage-stats` (dashboard).
- `GET /review-queue/rejected` · `POST /review-queue/restore` (recover).
- Lots : `GET /lots`, `GET /lots/{key}`, `POST /lots/{key}/images/{sid}/detect`,
  `.../crops` (add), `.../sync-crops`, `POST /lots/{key}/decide` (bulk).
- `POST /{id}/requalify-lot` (single→lot, touche L) · `/lots/{key}/requalify-single`.
- `POST /{id}/correct-listing` (listing_kind/condition) · `GET /{id}/crop-edit-context` ·
  `POST /{id}/manual-crop` · `GET /{id}/dino-suggestions`.
- Crop edit/recrop : `ml/serving/crop_edit.py` (`load_crop_edit_context`,
  `apply_manual_crop`, `create_manual_crop`, `_plausible_suggestion`).

**Modèle de données** (dans `ml/state/eurio.db`) :
- `review_queue` (status open/done/skipped, lane manual/auto_accept/ccproxy, kind single/lot,
  decided_*, priority).
- `image_assets` (eurio_id, face, resolution_status needs_review/manual/rejected/auto_dino/
  auto_accept, bbox_json, crop_index, phash, quality_score, training_eligible).
- `source_images` (listing_title/price, target_eurio_id, detections_json, is_lot_suspected).
- `image_asset_dino_predictions` (top1_eurio_id, top1_sim, top1_country_*, spread).
- `listing_text_signals`, `coins`, `consensus_verdicts`.
- **State model** : `emit_state_event(...)` écrit `image_state` / `image_state_current`
  (open→done). Grep `emit_state_event` pour les transitions.

**Patterns à connaître** :
- Commits atomiques **1st-write-wins** (`UPDATE ... WHERE status='open'`, 409 si concurrent).
- `decided_by` : `human` / `auto_dino` / `claude_ack` / `admin` ; `decision_engine_version`
  horodate les seuils.
- `decision_notes='restored'` = item épinglé manuel (exclu de l'auto-triage).
- Lane `NULL` (legacy) traité comme `manual`.

## Zones de fragilité repérées (pistes de bugs probables)

1. **Commit différé / undo 10s** (`ReviewActionBar.vue` + decide endpoint) : race possible si
   ⏎ rapides ou deux onglets → 409. Vérifier le comportement du timer + l'état après undo.
2. **Crop editor** (`CircleCropEditor.vue` + `crop_edit.py`) : démarre sur
   `suggested_circle ?? hint`. Le `suggested` (Hough dominant) peut être aberrant (déjà durci
   pour coincard, voir ci-dessous) — surveiller macro/capsule/lot.
3. **Lot detections_json** : si le RAW n'est pas en cache local, `_compute_detections` rend
   `[]` silencieusement → overlay vide. Vérifier le message d'erreur / fallback.
4. **Dino périmé** : après un renommage de slugs il FAUT
   `go-task ml:dino-anchors:build -- --force` puis `ml:dino-predictions:backfill -- --force`
   sinon suggestions obsolètes (top1 pointe un eurio_id mort).
5. **Canvas CORS** du crop editor : le raw `?canvas=1` + `crossorigin=anonymous` ; si l'aperçu
   224 est noir, c'est le cache CORS (voir `canvasRawSrc`, lignes ~76-80).
6. **Lane `NULL`** : items legacy sans lane → comptés en manual ; vérifier les compteurs du
   dashboard si des totaux semblent faux.
7. **Recherche libre / candidats** : `FreeSelectorPanel` + `useCoinsSearch` (cascade pays→
   dénom→année) — vérifier les cas vides / pays sans commémo.

(Ce ne sont QUE des pistes. Fais-toi montrer les vrais bugs par le PO d'abord.)

## Ce qui vient d'être fait (NE PAS refaire / contexte)

Session crop-recovery (2026-06-15), committée (3 commits sur la branche `sources-jo-wikipedia`,
non poussés) — voir mémoire `project-score-guided-recovery`, `project-crop-recovery-strategy-b`,
`feedback-handoff-quality` :

- **Recovery score-guided (stratégie A)** intégrée en prod : `vision/score_recover.py` +
  fallback census `EURIO_CENSUS_RECOVER=1` (activé pour les futurs runs eBay). Le dernier run
  est passé de 341 zero_crops → 78 (263 pièces récupérées) ; elles sont en review en
  `pending_match` avec suggestions Dino.
- **Vue par image brute** d'audit crop : `/crop-recovery/by-raw` (pas /review).
- **Re-crop des undercrops de la lane manual** : `scripts/recrop_review_score_guided.py` a
  remplacé 69 crops mal cadrés (singles). Les « lots » sont d'autres dénominations bien
  cropées (relevance, pas crop) — laissés intacts.
- **Fix éditeur de crop pour coincard/capsule** : `serving/crop_edit.py::_plausible_suggestion`
  rejette le cercle Hough dominant quand il est aberrant vs la bbox (pièce petite dans un coin
  d'un coincard → Hough accrochait le rebord de la carte). L'éditeur repart alors de la bbox =
  sur la pièce. **C'était le bug « cadre complètement off » du PO — réglé.**

→ Si le PO reparle de crops mal cadrés : les vrais undercrops single sont traités, les coincards
sont réglés dans l'éditeur ; le reste est probablement de la relevance (lots multi-dénom) ou des
lots à recadrer par-pièce (`scripts/recrop_lots_per_coin.py`, garde voisin anti-fusion).

## Garde-fous (repo Eurio)

- **R0 — zéro dette** : construire proprement, pas de shortcut. Pas de `TODO:` dans le code.
- **Admin Vue EXEMPT du proto-first** : tu peux coder le design admin directement (la règle
  proto-first ne vaut que pour l'app Android). Tokens partagés `shared/tokens.css`.
- **`go-task`** (jamais `task` nu) pour toutes les commandes.
- **Git** : jamais `git add -A`/`.` (staging explicite par fichier — secrets). L'arbre
  contient des changements **non liés** d'autres sessions (proto redesign, détection
  `normalize_snap.py`, renommages docs) — **n'y touche pas**, ne stage que tes fichiers review.
  Branche courante `sources-jo-wikipedia` ; ne commit que sur accord PO.
- **eurio.db = source de vérité** (lease MinIO, Mac = seul writer). Si tu mutes la DB, le PO
  fait `go-task ml:db:sync` pour pousser (push sans relâcher le verrou). Backup avant mutation.
- **Vérifie tout fait douteux sur données réelles** avant de conclure.

## Livrable

Pour chaque bug fixé : un court compte-rendu **preuve-first** (symptôme reproduit → cause
fichier:ligne → fix → re-test dans l'app). Découpe en chunks, livre, attends le « go » du PO
avant d'enchaîner. Ne commit qu'avec accord PO (commits séparés et lisibles par bug/thème).
