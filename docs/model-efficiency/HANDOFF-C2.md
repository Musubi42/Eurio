# HANDOFF — C2 : le flywheel de données eBay (review autonome)

> Doc de passation pour une **nouvelle session**. Objectif : démarrer avec le
> meilleur contexte et traiter **C2 de bout en bout**. Écrit le 2026-06-11 à la
> fin de la session 1 (entraînement + déploiement du 1er modèle dinov2).

---

## 0. Ta mission (bout en bout)

Construire le **flywheel de données** : un meilleur modèle pré-classe les pièces
scrapées eBay → la **review devient plus autonome** → on récolte plus de
**références « from the wild »** par classe → on **agrandit la base de classes**
→ benchmarks plus grands et plus fiables → meilleur modèle → … (cf.
[C2-data-flywheel-ebay-review.md](./C2-data-flywheel-ebay-review.md)).

Concrètement, la session doit décider/mettre en place, dans l'ordre logique :
1. **Le « modèle »** qui pré-classe (choix mesuré — voir §5 Décisions).
2. **La méthode de scrape eBay** (réutiliser l'existant, voir §3).
3. **Le filtrage** (theme-matcher texte + vision + qualité crop).
4. **L'auto-review** (seuils d'auto-accept, lanes).
5. **La passe humaine** (ce qui reste à trancher, et l'UI).
6. **L'entraînement** (consommer les refs validées → réentraîner).
7. **La boucle d'amélioration** (re-encoder, re-mesurer, fermer la boucle).

**But supérieur** (north star, [VISION.md](./VISION.md)) : couvrir **toutes les
2€ de la DB**. C2 est le moteur de données qui rend ça possible.

---

## 1. RÈGLES DE TRAVAIL (non négociables — lis-les)

Voir [VISION.md §Règles](./VISION.md). En résumé :
- **Pas d'hypothèse cachée** : toute supposition est écrite comme « Hypothèse (à
  challenger) » et on **sème un benchmark**.
- **Benchmark-first** : mesurer avant d'optimiser.
- **Test réel dès que possible**, puis **mettre à jour la doc** (Résultats +
  journal des croyances dans VISION.md).
- **Un chiffre non mesuré n'est pas un fait** (`⚠️ estimation`).

> En session 1, le 1er benchmark a **réfuté 2 croyances** (H2 et H6). Attends-toi
> à ce que tes intuitions sur la review/le scrape soient fausses tant que tu ne
> les as pas mesurées. C'est le but.

---

## 2. À lire en premier (ordre conseillé)

| # | Doc | Pourquoi |
|---|---|---|
| 1 | [VISION.md](./VISION.md) | North star, règles, registre d'hypothèses H1–H6, journal des croyances |
| 2 | [C2-data-flywheel-ebay-review.md](./C2-data-flywheel-ebay-review.md) | Le chantier lui-même : objectif, **H4**, benchmark à semer |
| 3 | [C1-reliable-centroids.md](./C1-reliable-centroids.md) | D'où vient le modèle/centroïdes qu'on va brancher sur la review |
| 4 | [C0-benchmark-ground-truth.md](./C0-benchmark-ground-truth.md) | Le harness d'éval réel + la baseline |
| 5 | `docs/work-in-progress/dino-suggestions/KICKOFF.md` | Design de l'auto-validation DINOv2 (le pré-classement actuel) |
| 6 | `docs/work-in-progress/autovalidation-redesign.md` | Consensus verdicts + lanes (review routing) |
| 7 | `docs/work-in-progress/collaborative-review/07-reconciliation.md` | Cycle publish/reconcile review |
| 8 | `docs/research/ebay-api-strategy.md` | Quota/contraintes API eBay |
| 9 | `docs/research/detection-pipeline-unified.md` | YOLO11 + Hough (étape detect/crop du scrape) |
| 10 | `docs/research/training-guide.md` | Vue d'ensemble entraînement |

Mémoire à jour : `[[feedback-model-efficiency-benchmark-first]]`.

---

## 3. Carte de l'infra existante (vérifiée — ne pas réinventer)

> Tout ceci a été audité en session 1. Réutilise-le. Entrées = go-tasks ;
> code = `file`.

### Scrape eBay — pipeline 9 étapes
- Orchestrateur : `ml/sources/_base/orchestrator.py`. Tasks : `ml:src:ebay:run`
  (10 coins depuis la freshness queue), `ml:src:ebay:dry`, `ml:src:ebay:status`
  (quota), `ml:src:mock:run` (5 fixtures, pour tester sans quota).
- Étapes : **Discover** (Browse API + theme-matcher) → **Persist**
  (`source_images`) → **Text-Signal** (`listing_text_signals`) → **Download**
  (MinIO `enrichment-raws`) → **Detect/Crop** (YOLO11+Hough → `image_assets`,
  MinIO `enrichment-crops`) → **Resolve** (phash dedup + eurio_id) →
  **Auto-Validate** (DINOv2 → `image_asset_dino_predictions`) → **Enqueue**
  (`review_queue`, lane) → **Price Aggregate**.
- Quota eBay : ~5000 calls/j (Browse), tracké (`api_call_log`). Creds
  `EBAY_CLIENT_ID/SECRET` (déjà en env via SOPS).

### Pré-classement visuel — DINOv2 anchor banks (le « modèle » actuel de review)
- Tasks : `ml:dino-anchors:build [-- --kind 2eur_all]`,
  `ml:dino-predictions:backfill`. Code : `ml/training/foundation/{encoder,anchors,matcher}.py`.
- Banks (`ml/state/foundation_anchors_<kind>.npz`) construites depuis les avers
  Numista canoniques : `2eur_commemo` (vits14, consensus), `2eur_standard`,
  `2eur_all` (**vitl14**, banque des suggestions review).
- Prédictions → table `image_asset_dino_predictions` (top-K, top1_sim, spread,
  et **re-rank par pays** quand `target_country` connu).
- ⚠️ **C'est du zero-shot** (avers Numista comme ancres), PAS notre modèle
  fine-tuné `arcface-vits14-v1`. → décision §5.

### Filtrage texte — theme-matcher
- `ml/sources/ebay/queries.py` (`match_listing_to_group`), aliases multi-langue
  (`coin_aliases`, tasks `ml:aliases:*`). Bench : **`ml:bench:theme-match`** sur
  le gold figé `ml/state/discovery_bench/theme_match_gold.jsonl` → recall /
  precision / false-discard / **auto-attribution %**. C'est le benchmark de H4.

### Review system (2 DB)
- `eurio.db` (PC, source de vérité, lease MinIO) ↔ `review.db` (VPS, service
  always-on). Pont : `ml:review:publish` / `ml:review:reconcile`.
- Service FastAPI `:8048` (`ml/review_service/app.py`, task `ml:review:serve`),
  UI Vue `admin/packages/review*/`. Reviewers : `ml:review:reviewer:*`.
- Queue locale `review_queue` : `status`, `candidate_eurio_ids_json`, **`lane`**
  (manual / auto_accept / ccproxy), `decided_eurio_id`, `decided_by`,
  `decision_metadata_json`. Lane ccproxy = vision Claude 4.6 (`review_claude_verdicts`).
- `consensus_verdicts` (texte+dino+qualité → accept/needs_review/reject) : en
  **SHADOW** (backfill, pas encore live). C'est le socle de l'auto-review.

### Listing → référence d'entraînement
- Consommation **confirmée** : `ml/training/iteration_augmentations.py`
  (`_ebay_training_sources`) lit les `image_assets` `source='ebay'`,
  **`training_eligible=1`**, `storage_status='present'`, cappé ~100/coin.
- ⚠️ **GAP / à vérifier** : *qui* et *quand* met `training_eligible=1` à partir
  d'une décision de review n'a **pas pu être confirmé** (pas de code trouvé
  reliant `review_queue.decided_eurio_id` → `image_assets.training_eligible`).
  **C'est probablement le maillon manquant n°1 du flywheel.** À investiguer en
  premier (ne pas supposer qu'il existe).

---

## 4. État de la session 1 (ce que tu hérites)

- **Modèle** : `arcface-vits14-v1` (DINOv2 ViT-S/14 + Linear→384, ArcFace).
  Checkpoint sur MinIO `eurio-db/transfers/arcface_vits14_v1_best_model.pth`.
  R@1 val 66.67% ; **top-1 réel 82–83%** sur 317 snaps (`eval_real_norm`).
- **Déployé** sur un Pixel 9a (smoke test, 27 classes fiables, fp16 41.8 MB).
  ⚠️ Les **3 assets Android sont swappés en local non commités** (test) —
  restaurer le POC via `git checkout app-android/src/main/assets/...`.
- **Finding C1** : pour les centroïdes, **train-mean (82.97%) ≈ ArcFace-W
  (82.65%) > val-mean (77.6%)**. Option `--centroid-source` ajoutée à
  `compute_embeddings.py`.
- **Gain immédiat non pris** (optionnel) : régénérer les centroïdes de l'app en
  `train_mean` (au lieu de val-mean, le pire) + redéployer → meilleur scan sans
  réentraîner.
- **Commits session 1** (branche `sources-jo-wikipedia`) : `4463fbf8` (opencv
  override), `8d34e0ab` (export/deploy dinov2), docs C0, `da49a4fb`
  (centroid-source + finding). Le skill graphify est installé (`/graphify`) mais
  a été mis de côté (besoin d'un backend LLM ou du flux skill in-session).

---

## 5. Décisions clés à prendre (mesurées, pas supposées)

1. **Quel modèle pré-classe la review ?** Candidats : (a) DINOv2 **zero-shot**
   actuel (anchor banks vitl14/vits14, déjà câblé en step Auto-Validate) ;
   (b) notre **fine-tuné `arcface-vits14-v1`** ; (c) **ensemble** vision +
   theme-matcher texte. → **Décider par la mesure** : éval sur le gold
   theme-match + une éval DINO-predictions, métrique = auto-attribution % à
   precision fixée (H4). Ne pas présumer que le fine-tuné gagne (il est ViT-S ;
   la bank de suggestions est vitl14, plus forte en zero-shot global).
2. **Seuils d'auto-accept** (lane auto_accept vs manual) : à calibrer sur le
   gold (precision cible → quel `top1_sim`/`spread` minimal ?).
3. **Le maillon `training_eligible`** (cf. §3 gap) : concevoir/implémenter le
   commit review-décision → flag d'entraînement (proprement, R0).
4. **Boucle** : après une passe de review, re-builder le dataset + réentraîner,
   re-encoder, re-mesurer le gain. Cf. C2c→C2e.

---

## 6. Premiers pas concrets (benchmark-first)

1. `go-task ml:src:ebay:status` — état quota + derniers runs.
2. `go-task ml:bench:theme-match -- -v` — **baseline H4** du filtrage texte
   actuel (recall/precision/auto-attribution). Consigne le chiffre dans C2.
3. Auditer le **gap `training_eligible`** : chercher dans `ml/review/` et
   `ml/review_service/` qui écrit ce flag. Si absent → c'est la 1re brique.
4. Comparer **pré-classement vision** : zero-shot DINO vs `arcface-vits14-v1`
   sur un échantillon labellisé (ré-utiliser/étendre le gold). → §5 décision 1.
5. `go-task ml:src:mock:run` — dérouler le pipeline complet hors quota sur 5
   fixtures pour tout valider end-to-end avant un vrai run eBay.
6. Mettre à jour C2 (Résultats) + le journal VISION à chaque mesure.

---

## 7. Hypothèses / zones à VÉRIFIER (ne pas tenir pour acquis)

- **H4** (les gains DINOv2 transfèrent à la classif eBay) — **non mesuré**.
- Le **commit `training_eligible`** existe-t-il ? **Non confirmé** (probable gap).
- `consensus_verdicts` est en **SHADOW** — pas la vérité live aujourd'hui.
- Le set d'éval réel ne couvre que ~17 classes ; **élargir** est justement un
  objectif de C2 (plus de classes review-validées → plus gros benchs).
- Détails non lus en session 1 (à confirmer dans le code) : impl exacte de
  `match_listing_to_group`, des anchor builders, schéma `review.db`.

---

## 8. Definition of done (pour cette mission C2)

- Un **flux documenté et testé** : scrape → filtrage → pré-classement →
  auto-review (seuils mesurés) → passe humaine résiduelle → `training_eligible`
  → réentraînement → re-mesure.
- Des **métriques persistées** (auto-attribution %, effort review, gain modèle)
  dans C2 + journal VISION.
- Une **base de classes élargie** (plus de classes avec refs wild validées),
  pour grossir les benchmarks de C0.
