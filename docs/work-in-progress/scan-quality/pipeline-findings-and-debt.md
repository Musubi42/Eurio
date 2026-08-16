# Pipeline eBay scrape → crop → review → coins — findings & dette technique

> **Tracker vivant.** Bugs, incohérences et non-optimisations découverts pendant l'exploitation
> du pipeline d'enrichissement (scrape eBay → download → detect/crop → auto-validate → review →
> compteur d'enrichissement coins). Chaque entrée est self-contained : symptôme, cause racine au
> `file:line`, preuve, impact, correctif proposé, statut. Les sessions futures peuvent traiter
> chaque item indépendamment. Ajouter les nouveaux findings en fin de doc avec la date.

## Contexte de la session d'origine (2026-07-08, sur le PC `desktop`)

Un scrape global eBay a été lancé depuis `lab/cohorts/9ecc2cd3f31a` (cohorte `mix-owned-42`).

- **Run** : `source_runs.id = fc47cc3c51af4748a75dca81742e7c93` (affiché `fc47cc3c` tronqué), source `ebay`,
  29 discovery groups (2€ standard + commémo, ~10 pays) × 2 marketplaces (EBAY_DE / EBAY_ES).
- **Discovery + download OK** : 58 recherches, 6448 summaries → 4873 kept → **6684 raws** téléchargés
  (6683 success / 1 échec HTTP 525). DB canonique locale = `ml/state/eurio.db` (le worker uvicorn
  `:8042` tourne en `--reload`, PID variable ; **ne pas restart**).
- **Échec initial** : le run a fini `status=failed` à l'étape `detect` car les artefacts ML locaux
  manquaient sur le PC (voir §F5). Reconstruits pendant la session (YOLO best.pt rapatrié du Mac,
  anchor bank commémo rebuildé, fragment_face_probe restauré du git). Reprocess relancé via
  `process_downloaded` (`--no-push`, local only) — voir §Référence opérationnelle.

Mémoires liées : `pc-ml-state-artifacts-missing`, `ebay-quota-split-brain-db`,
`scan-corpus-funnel-livre`, `local-sync = seed baseline requis`.

---

## Résumé priorisé

| # | Finding | Sévérité | Type | Statut |
|---|---------|----------|------|--------|
| B1 | Quota eBay split-brain (2 fichiers DB) | 🔴 haute | Bug correctness | ✅ **fixé 2026-08-16** |
| B2 | Détection sans cap de taille → gel sur images géantes | 🔴 haute | Bug perf/robustesse | ✅ **fixé 2026-07-08** |
| B3 | Compteur enrichissement lit le local, review écrit le VPS | 🟠 moyenne | Bug incohérence | ✅ **fixé 2026-08-16** — direction 1, tranchée par le PO (cf. §B3) |
| B4 | Pas de vue détail depuis `lab/cohorts` (run-id tronqué) | 🟡 UX | Manque feature | ✅ **fixé 2026-08-16** |
| B5 | Reprise `process_downloaded` reapée en « orphan run » (pid non réclamé) | 🔴 haute | Bug correctness | ✅ **fixé 2026-07-08** |
| B6 | Reprise re-broie le backlog `zero_crops` (skip idempotent incomplet) | 🟠 moyenne | Bug efficacité/UX | ✅ **fixé 2026-07-08**, corrigé 2026-08-16 (voir §B6) |
| N1 | Détecteur YOLO mal adapté au domaine eBay (61% zéro-crop) | 🟠 moyenne | Non-opti qualité | à investiguer |
| N2 | Anchor bank commémo à couverture partielle (239/630) | 🟡 basse | Non-opti données | à compléter |
| N3 | Suggestions DINO faibles sur les nouveaux crops eBay (banque review stale/petite) | 🟠 moyenne | Non-opti qualité | à corriger |
| F5 | Artefacts ML state gitignorés absents sur le PC | 🟢 infra | Dette infra | recette dispo |

---

## B1 — Quota eBay : split-brain entre deux fichiers `eurio.db` 🔴 ✅ FIXÉ 2026-08-16

> **Correctif appliqué.** Ni l'une ni l'autre des deux directions proposées ci-dessous
> telles quelles : « faire respecter `EURIO_DB_PATH` » aurait fait écrire le compteur
> dans la **réplique read-only** (Direction A : `eurio-api` est le writer unique), donc
> échouer. Le quota est de l'observabilité **par machine** — il ne voyage pas au
> canonique. Il vit désormais dans la DB locale inscriptible déjà prévue par l'archi
> (`store.resolve_local_state_db()`, `EURIO_LOCAL_STATE_DB`, gitignorée), et les
> lecteurs (`sources_routes.ebay_calls_today`, `sources/repository.ebay_calls_today`)
> passent par le **même `QuotaTracker`** que l'écrivain au lieu de faire du SQL sur le
> Store. Les compteurs de l'ancien fichier sont repris une fois, en `INSERT OR IGNORE`
> — sans ça le mois Numista en cours repartait à zéro et le KeyManager surconsommait
> les 8 clés jusqu'au 429.
>
> **Trouvé en corrigeant** : le garde-fou `check_ebay_quota` s'exécutait **après**
> `_load_adapter`, qui exige les credentials eBay et va chercher un token par le
> réseau. Un garde purement local ne doit pas coûter un aller-retour réseau — il passe
> désormais avant. Effet de bord révélateur : le test
> `test_trigger_run_returns_409_if_quota_insufficient` ne testait rien (il sortait en
> 503 avant d'atteindre le garde). Il teste maintenant vraiment le 409.
>
> **Test de régression** : `test_quota_status_sees_what_the_tracker_wrote` n'insère
> rien à la main — il appelle `QuotaTracker.record()` puis lit l'endpoint. C'est le
> seul test qui aurait attrapé le split-brain.
>
> **Reste ouvert** : `ml/shared/state/eurio.db` est encore **tracké dans git** alors
> que plus personne ne le lit — les compteurs de quota de chaque machine partaient
> donc dans l'historique. Son rôle, jusqu'ici « non établi » dans
> `docs/architecture/artifacts.md`, est maintenant identifié : c'était la DB de quota.
> Le détracker est une décision du PO (supprimer de la donnée), à faire une fois que
> chaque machine a joué la reprise.
>
> **Corrigé après revue adversariale** (même jour) — trois défauts de la première
> version du correctif, tous silencieux :
>
> 1. La reprise des compteurs **ne s'exécutait jamais** : l'`ATTACH` employait un nom
>    de fichier URI (`file:…?mode=ro`) sur une connexion ouverte sans `uri=True`, donc
>    SQLite prenait la chaîne au pied de la lettre. L'échec était avalé par l'`except`
>    juste en dessous. Reproduit puis corrigé (chemin nu) ; 5 tests dédiés, dont un qui
>    échoue si l'on remet la forme URI.
> 2. Le `DETACH` du `finally` **lève** « database legacy is locked » dès que l'ATTACH
>    réussit, l'`INSERT` ayant ouvert la transaction implicite de sqlite3 — et comme il
>    était hors `try`, il serait remonté jusqu'à `QuotaTracker.__init__`, tuant **tout**
>    appel eBay et Numista. `commit()` avant, `DETACH` protégé.
> 3. `ebay_calls_today` importait `sources.market.ebay_client` pour la limite, or
>    `infra/eurio-api/Dockerfile` ne copie **pas** `ml/sources` dans l'image lean →
>    `ModuleNotFoundError` à la requête, donc 500 sur `/sources/ebay/quota-status`.
>    Constante locale (même valeur).
>
> Et un quatrième, de périmètre : le **widget** interrogeait `eurioApi`, c'est-à-dire
> le VPS — dont le tracker n'enregistre jamais rien, puisque les appels eBay partent de
> la machine qui scrape. Le garde-fou était corrigé, l'affichage non : le symptôme
> d'origine survivait à l'écran. `fetchEbayQuotaStatus` passe par `ML_API`.
>
> L'annexe ci-dessous (estimation « ~N appels » qui ignore les `get_item`
> d'hydratation, 47 estimés vs 4733 réels) **reste ouverte**.

**Symptôme.** Pendant un gros scrape, le widget affiche « 5000/5000 restants » et le quota eBay
ne descend jamais, alors que des milliers d'appels sont réellement consommés.

**Cause racine.** Le compteur est **écrit et lu dans deux fichiers SQLite différents, jamais
réconciliés** :
- **Écriture** : `ml/sources/market/ebay_client.py` (`_request` → `QuotaTracker.record()`) →
  `ml/shared/api_quota.py:~23` `DEFAULT_DB = Path(__file__).parent / "state" / "eurio.db"` =
  **`ml/shared/state/eurio.db`**, hardcodé, **ignore `EURIO_DB_PATH`**. Table `api_call_log`
  (clé `source, key_hash, window='daily', period=YYYY-MM-DD`).
- **Lecture** : `ml/serving/sources_routes.py:2077` `ebay_calls_today(store)` /
  `:2173 check_ebay_quota` / `quota-status` lisent `api_call_log` depuis le **Store canonique** =
  `ml/state/eurio.db` (via `resolve_db_path`/`EURIO_DB_PATH`).

**Preuve (2026-07-08).** Run `fc47cc3c` : `ml/shared/state/eurio.db` `api_call_log` 2026-07-08 =
**4733 appels** (≈267 restants sur 5000). `ml/state/eurio.db` : dernière ligne eBay = **2026-06-07**
→ 0 aujourd'hui → widget « 5000/5000 ».

**Impact.** (1) Widget faux. (2) **Le garde-fou `check_ebay_quota` (HTTP 409 `quota_insufficient`)
lit la table périmée → laisserait relancer un gros run avec le quota du jour quasi épuisé → 429 eBay.**

**Correctif proposé.** Unifier : faire respecter `EURIO_DB_PATH` dans `api_quota.py` (que tracker et
lecteurs pointent le même fichier), OU lire le quota via le `QuotaTracker` plutôt qu'une requête SQL
directe sur le Store. Vérifier ensuite qu'aucun autre consommateur n'écrit dans `shared/state`.

**Annexe.** L'estimation « ~N appels » du preview (`ebay/run-preview`) ne modélise que les
recherches, pas les milliers de `get_item` d'hydratation (47 estimé vs 4733 réels) → à recalibrer.

---

## B2 — Détection sans cap de taille → gel CPU sur images géantes 🔴 ✅ FIXÉ 2026-07-08

> **Correctif appliqué.** `vision/normalize_snap.py` : constante `LISTING_DETECT_MAX_LONG_SIDE = 2048` +
> cap en entrée de `detect_circles_multi` (downscale INTER_AREA si long-side > cap) + re-projection des
> coordonnées (`det_scale`) en fin de fonction. Le crop reste extrait plein-res (coords re-scalées) → qualité
> intacte. Cas nominal (≤2048, soit 6679/6683 images du run) = no-op strict. Vérifié : l'image 42 Mpx passe
> de gel (minutes/h) → **3,7 s**, 8 détections en coords plein-res. Reste applicable à tout futur run.
>
> **Complété après revue adversariale (2026-08-16)** : la re-projection ne touchait que
> les `CircleDetection`. Les entrées de `trace` (`cx`, `cy`, `bcx`, `bcy`, `r_final`,
> `r_bbox`, `r_hough`, `r_polish`, `r_rim`) restaient en espace **détection**, alors que
> `bench/crop_recovery/common.detect_hint` les lit comme des coordonnées natives — il
> les compare à des bboxes gold mesurées sur le raw, puis passe le hint à
> `recover_crop(bgr_original, …)`. L'association gold et le banc de recovery se
> dégradaient donc en silence, et **uniquement** sur les images au-dessus du cap :
> exactement les photos vendeur pleine résolution que B2 vise. Deux tests couvrent
> désormais la re-projection (dont un vérifié par mutation).


**Symptôme.** Le job de crop semble « gelé » : process à ~98% CPU (`State=R`), aucun log ni
progression DB pendant 15-30 min, puis reprend. Bloqué ~1h sur un seul listing.

**Cause racine.** `ml/vision/normalize_snap.py` `detect_circles_multi` (~ligne 853) opère à
**pleine résolution** sur l'image d'entrée : `_yolo_detect_bboxes(bgr)` (census), puis
`cv2.cvtColor(bgr, ...)` + `cv2.Laplacian(gray, CV_32F, ksize=3)` sur l'image entière, puis Hough.
Le downscale `_downscale_to_working_res` (cap 1024, `normalize_snap.py:175`) n'est appliqué **qu'à
l'étape crop (`normalize_listing_with_detections:294,363`), APRÈS la détection** → aucune protection
en amont.

**Preuve (2026-07-08).** Listing eBay `205878939286` = 4 images en **7952×5304 = 42,2 Mpx (~19 MB
chacune)**. `…0_img0` a fini en ~10-20 min (0 crop), le job a ensuite grincé 15+ min sur `…0_img1`.
Toutes les autres images non traitées du run ≤ 2,6 Mpx → une fois ce listing passé, vitesse normale.
Laplacian float32 sur 42 Mpx = tableau ~168 MB + convolution sur 42M pixels.

**Impact.** Toute image d'entrée ≥ ~20 Mpx re-gèle un run (temps quasi-illimité par image). Les
vendeurs eBay postent régulièrement des photos pleine résolution d'appareil.

**Correctif proposé.** Capper la taille d'entrée **AVANT** `detect_circles_multi` (ex. downscale si
`max(h,w) > N` px, N ~2000-3000, en gardant le facteur d'échelle pour re-projeter les bboxes/cercles).
Ne PAS se reposer sur le cap crop tardif. Ajouter un garde-fou de log si une image dépasse un seuil.

---

## B3 — Compteur d'enrichissement (local) ≠ écriture review (VPS) 🟠 ✅ FIXÉ 2026-08-16

> **Direction 1 tranchée par le PO.** Compteurs, galerie **et** reflag passent au
> canonique (`eurioApi`), comme les métadonnées et la file de review. Trois choses
> manquaient pour que ce soit possible — le rebranchement front n'était que la
> dernière :
>
> 1. **Gating fin de `coin_assets_routes`.** Ses deux imports lourds (`crop_edit` et
>    `review.review_queue_routes`, tous deux cv2) ne servent qu'aux **deux** routes
>    d'édition de crop, en fin de fichier. Au niveau module, ils faisaient échouer
>    l'import de tout le fichier et le VPS skippait le routeur entier. Ils sont
>    maintenant enveloppés, et les deux routes lourdes ne sont **enregistrées que si**
>    cv2 est là. Pas de repli en 503 : une route absente vaut mieux qu'une route qui
>    existe et explose — le front découvre la capacité via `hasLocalMlApi`.
> 2. **Les URLs d'images.** `file_url` valait `/sources/{source}/assets/{id}/file`, une
>    route que le canonique n'expose pas. Il renvoie désormais une **URL S3 signée
>    absolue** (le bucket `enrichment-crops` est privé — c'est le pattern déjà
>    documenté). Le front anticipait exactement ça : son `promoteUrl` devient un no-op,
>    comme son commentaire le prévoyait depuis le début.
> 3. **Un défaut latent, découvert en chemin** : le VPS signait ses URLs avec
>    `MINIO_ENDPOINT=eurio-minio:9000`, un nom du réseau Docker que **le navigateur ne
>    résout pas**. Les crops de la review étaient donc déjà cassés en mode hébergé, en
>    silence : l'API répond 200 avec une URL parfaitement formée, seule l'image
>    manque. `shared/storage._public_client` signe avec `MINIO_PUBLIC_ENDPOINT`
>    (`eurio-s3.musubi.dev`), ajouté au compose. On ne s'est **pas** reposé sur le fait
>    qu'une présignature SigV2 ignore l'en-tête Host : ce serait dépendre d'un repli
>    implicite de boto3 qu'une montée de version peut basculer en SigV4.
>
> **Conséquence assumée** (celle que la direction 1 portait dès l'origine) : les crops
> produits localement en `--no-push` n'apparaissent qu'une fois poussés au canonique.
>
> **Le reflag change de camp aussi** — et c'est une correction, pas un effet de bord :
> sous Direction A le canonique est le writer unique, donc un reflag écrit en local
> n'était jamais vu par la file de review, lue depuis le VPS.
>
> ⚠️ **Déploiement couplé** : tant que `eurio-api` n'est pas reconstruit, le front
> (local comme hébergé) reçoit des 404 sur ces deux routes. Backend d'abord.
>
> 6 tests ajoutés, dont la garde qui rend la direction possible — le module doit
> s'importer sans cv2 — vérifiée par mutation.

**Symptôme.** En review manuelle (`/review/manual`), valider des crops n'augmente **jamais** le
nombre d'images d'enrichissement affiché dans `coins` (badge liste + `total` de la gallery).

**Cause racine.** Read et write tapent des backends/DB différents :
- **Compteur (lecture)** → **LOCAL `:8042`** : `admin/.../features/coins/composables/useCoinAssets.ts:12`
  (`ML_API = http://127.0.0.1:8042`), `:107-112` `GET /coins/enrichment-counts`, `:83-103` `total`.
  Backend `ml/serving/coin_assets_routes.py:148-172` compte `image_assets WHERE eurio_id IS NOT NULL
  AND resolution_status IN ('auto_name','auto_phash','manual')` — sur `ml/state/eurio.db` **local**.
- **Review decide (écriture)** → **VPS `eurio-api.musubi.dev`** :
  `admin/.../features/review/composables/useReviewApi.ts:257-270` → `eurioApi.post('/review-queue/{id}/decide')`.
  Handler VPS `ml/serving/review_queue/writes.py:80-171` (monté par `server_serve.py`) passe l'asset
  à `resolution_status='manual'` — sur le `eurio.db` **canonique VPS**. La file de review est **aussi**
  lue depuis le VPS (`useReviewApi.ts:211` `fetchReviewQueue` → `eurioApi.get`).

→ Deux bases différentes : valider sur le VPS ne peut pas bouger un compteur qui lit le local.

**Incohérence corroborante.** Sur la même page coins, les *métadonnées* pièce viennent du VPS
(`useCoinsApi.ts` → `eurioApi`) et le bouton « renvoyer en review » de la gallery tape le **local**
(`useCoinAssets.ts:117`) — seul le compteur d'enrichissement est branché local de façon incohérente.

**Impact.** Le feedback d'enrichissement est faux/muet pour l'opérateur en review.

> ### ⚠️ Vérifié le 2026-08-16 : la direction 1 n'est PAS un rebranchement de front
>
> Elle suppose que `eurioApi` sert déjà ces endpoints. Il ne les sert pas :
>
> - Log de démarrage du conteneur `eurio-api` :
>   `routers montés : ['coins', 'sets', 'operations', 'peer_arbitration']` /
>   `routers skippés : [… "coin_assets (ModuleNotFoundError: No module named 'cv2')"]`.
>   `coin_assets_routes` importe `.crop_edit` **au niveau module** → cv2 → skip sur
>   l'image lean. Les deux endpoints sont pourtant du SQL pur : ils sont lourds **par
>   voisinage, pas par nature**.
> - L'OpenAPI du VPS ne contient **aucune** route `assets` ni `enrichment`
>   (une route bidon répond 401 comme les autres : le middleware d'auth répond avant
>   le routage, donc un 401 ne prouve rien — c'est l'OpenAPI qui tranche).
> - Et surtout : `file_url` vaut `/sources/{source}/assets/{id}/file`, route **absente
>   du routeur `sources` lean du VPS**. Lire la galerie depuis le canonique afficherait
>   des images cassées tant que le canonique ne sait pas servir les octets — or les
>   assets vivent dans MinIO, donc la vraie réponse est une **URL signée**, pas un
>   proxy de fichier.
>
> La direction 1 coûte donc : gating fin des routes lourdes + une histoire d'URL
> d'images côté canonique + rebranchement front + déploiement VPS — et fait
> disparaître les crops locaux `--no-push`. **Décision d'archi, pas correctif.**

**Correctif proposé (2 directions).**
1. **(recommandé)** Brancher `/coins/enrichment-counts` + `/coins/{id}/assets` sur le **canonique**
   (`eurioApi`), comme les métadonnées et la review. ⚠️ mais alors les crops produits **localement**
   (runs `--no-push`) n'apparaîtront qu'après push vers le VPS.
2. Router toute la review (queue + decide) vers le **local** `:8042` (le twin existe :
   `ml/review/review_queue_routes.py:1936`). Cohérent avec des crops frais locaux, mais diverge du canon.

**Caveat data.** Les crops du run `fc47cc3c` ont été croppés `--no-push` → **local only**, absents
du VPS. La file de review lisant le VPS, ils n'y apparaissent pas. Tension Modèle A ↔ canonique
(cf. mémoire `local-sync = seed baseline requis`).

---

## B4 — Pas de vue détail temps réel depuis `lab/cohorts` 🟡 ✅ FIXÉ 2026-08-16

> **Correctif appliqué**, caveat levé d'abord — sans quoi le lien aurait été un
> cul-de-sac. `fetchSourceRun` (`useSourceDetail.ts`) se replie sur `ML_API`
> **uniquement sur 404** du canonique : un run déclenché depuis le drawer lab passe
> par `:8042` et vit dans la DB locale, que le VPS ne connaît pas. On ne replie pas
> sur 401/500 — masquer une panne d'auth derrière un « run introuvable » coûterait
> plus cher que le bug d'origine. Le badge de `CohortDrawerEbay.vue` est devenu un
> `RouterLink` vers `/sources/ebay/runs/{id}`, avec l'**id complet** (la troncature à
> 8 reste de l'affichage). `front:typecheck` vert.
>
> **Corrigé après revue adversariale** — la première version du repli était un no-op
> et la page restait un cul-de-sac, pour deux raisons :
>
> 1. **Les chemins diffèrent selon le backend.** Le canonique expose
>    `/source-runs/{id}` ; `:8042` (`sources_routes.py`, prefix `/sources`) expose
>    `/sources/{source_id}/runs/{id}`. Le repli visait le chemin canonique côté ML_API
>    → 404 → repli sans effet, en silence.
> 2. **Ce n'est pas le snapshot qui bloque la page**, c'est le *breakdown* :
>    `SourceRunDetailPage.load()` lève sur son échec (le snapshot est explicitement
>    secondaire). `fetchRunBreakdown` était canonique-only, donc corriger le seul
>    snapshot ne changeait rien à l'écran.
>
> Le repli est devenu un helper partagé, `fetchWithLocalRunFallback(canonique, mlApi)`,
> utilisé par les deux appels — les deux chemins sont donnés explicitement, précisément
> parce que les supposer identiques était le bug.

**Symptôme.** Le scrape lancé depuis `lab/cohorts/:id` n'affiche qu'un résumé (badge `run fc47cc3c`,
`+N raws`, `+N crops`) ; pas de détail (funnel, listings, searches) ni de quotas visibles en direct.

**Contexte.** Même machinerie que la page détail dédiée : le trigger `POST /sources/ebay/runs`
(`sources_routes.py:175`) écrit dans `source_runs`, table partagée. La page
`/sources/ebay/runs/:run_id` sait tout afficher (funnel/breakdown/searches/listings/discarded, poll
2s via `GET /source-runs/{id}`). Le drawer lab tronque juste l'id à 8 (`CohortDrawerEbay.vue:321`),
mais `res.run_id` du POST contient l'id complet.

**Correctif proposé.** Transformer le badge run du drawer en **lien vers
`/sources/ebay/runs/${liveRun.id}`** (id complet). Pur front.
**⚠️ Caveat à lever d'abord** : le trigger cohort passe par `ML_API` (`:8042`, run en DB **locale**),
mais `fetchSourceRun` de la page détail passe par `eurioApi` (base VPS par défaut). En local, il faut
que `VITE_EURIO_API_BASE` pointe `:8042` (ou router la lecture du run via `ML_API` quand il est local),
sinon la page détail interroge le VPS et ne trouve pas le run local.

---

## B5 — Reprise `process_downloaded` tuée par le reaper « orphan run » 🔴 ✅ FIXÉ 2026-07-08

**Symptôme.** Après reprise d'un run (`--crop-pending`), le CLI tourne (logs qui défilent) mais les
compteurs DB restent figés et le run repasse `status=failed`, `error_summary='process restart — orphan run'`.

**Cause racine.** `process_downloaded` / `resume_failed_downloads` (`ml/sources/_base/orchestrator.py`)
réattachent au run et repassent `status='running'` **sans mettre à jour `source_runs.pid`** → le pid du
run initial (souvent le worker uvicorn d'origine, mort après un restart) survit. Le reaper
`reset_orphan_runs` (`ml/serving/sources_routes.py:2635`, lancé au **startup backend = à chaque `--reload`**)
marque `failed` tout run `running` dont `_pid_alive(pid)` est faux → il tue le run vivant sous les pieds
du CLI. Édition de code (reload) pendant une reprise = run tué.

**Correctif appliqué.** Les deux UPDATE de reattach réclament désormais `pid=os.getpid()` (le pid du
process CLI/thread courant, vivant) → le reaper l'épargne. `import os` ajouté.

## B6 — Reprise re-broie le backlog `zero_crops` 🟠 ✅ FIXÉ 2026-07-08

> **Deux régressions corrigées le 2026-08-16 (revue adversariale).** Le skip était trop
> large et rendait muettes deux surfaces entières :
>
> 1. **Les scripts `recrop_*` étaient neutralisés.** `recrop_zero_score_guided.py`
>    sélectionne `WHERE crop_status = 'zero_crops'` et passe exactement ces ids à
>    `run_detect_crop` — c'est toute sa raison d'être. Chaque cible tombait sur le
>    nouveau `continue` : `0 récupéré sur N`, sans la moindre erreur.
>    `recrop_ebay_orphans.py` était touché aussi (il cible `pipeline_state='downloaded'`,
>    or une image zéro-crop n'atteint jamais `'cropped'`, donc elles y dominent).
>    → paramètre `retry_zero_crops`, que les deux scripts passent.
> 2. **`error` n'aurait jamais dû être skippé.** Son unique écrivain est le
>    `FileNotFoundError` « raw absent de MinIO » — une indisponibilité réseau, pas un
>    verdict du détecteur. Le skipper à vie faisait qu'un hoquet MinIO excluait ces
>    images définitivement, sans reprise possible. Seul `zero_crops` est déterministe.
>
> 5 tests ajoutés (`test_detect_crop_resume.py`), dont une garde de contrat sur les deux
> scripts : s'ils cessent de passer l'opt-out, ils redeviendraient inopérants en silence.

**Symptôme.** À la reprise (`--crop-pending`), le CLI ne semble « faire que des 0 crops » et les
compteurs ne bougent pas — l'opérateur croit que c'est cassé et le tue.

**Cause racine.** `run_detect_crop` (`ml/sources/_base/steps/detect_crop.py`) ne skippait au resume que
les images ayant **au moins un `image_asset`** (les `success`). Les images `crop_status='zero_crops'`
(détectées, 0 crop) n'ont pas d'asset → **re-détectées à chaque reprise**. Comme elles sont en tête de
la boucle (rowid bas, traitées en premier au run initial), la reprise re-broie ~1090 images à zéro
(≈1-1,5 h) AVANT d'atteindre les images jamais traitées (`crop_status IS NULL`) où de nouveaux crops
apparaissent.

**Correctif appliqué.** Skip précoce si `crop_status IN ('zero_crops','error')` (détecteur déterministe →
re-run inutile). Les `success` gardent le skip idempotent existant (collecte des chemins de crops) ; les
`NULL` sont détectées. `resolve`/`auto_validate` en aval couvrent toujours TOUS les crops existants.
Effet : la reprise va directement aux images non traitées.

## N1 — Détecteur YOLO mal adapté au domaine eBay (61% zéro-crop) 🟠

**Symptôme.** Sur les listings traités du run, **61% rendent 0 crop** (1090 zero_crops / 1785 traités
au moment du constat).

**Cause probable.** `best.pt` a été entraîné sur le dataset Roboflow **`coin-gva2j`** (14 classes de
monnaies du monde, photos type KakaoTalk, imgsz 320) — domaine différent des images de listing eBay
(fonds variés, capsules, lots multi-pièces, packaging). Le rappel du détecteur y est faible.

**Impact.** Rendement en crops faible → enrichissement lent, corpus sous-alimenté.

**Piste.** Mesurer le rappel réel (échantillon annoté d'images eBay), tuner le seuil de conf
(`_YOLO_CONF_THRESHOLD` / `_CENSUS_YOLO_CONF` dans `normalize_snap.py`), et/ou ré-entraîner/fine-tuner
le détecteur sur des crops eBay validés. À faire APRÈS déblocage B2.

---

## N2 — Anchor bank commémo à couverture partielle (239/630) 🟡

**Symptôme.** `go-task ml:dino-anchors:build` : `Selected 630 · Skipped 391 (no obverse.jpg) ·
Encoded 239`. 62% des commémo n'ont pas d'avers canonique → `auto_validate` ne peut pas les valider.

**Cause.** `go-task ml:import-numista` (nominal) ne télécharge que les pièces dont l'URL image est en
cache dans `datasets/coin_catalog.json` → 274 obverses seulement.

**Correctif.** `python -m referential.import_numista --backfill-urls` (récupère les URLs manquantes
via l'API Numista — quota Numista, pas eBay) → re-fetch images → `go-task ml:dino-anchors:build --force`.

---

## F5 — Artefacts ML state absents sur le PC (dette infra) 🟢

**Symptôme.** Sur le PC, le pipeline crop/validate échoue en cascade sur des artefacts manquants
(gitignorés, non transportés par `git pull`, canoniques sur le Mac).

**Les 4 artefacts + récupération** (détail complet dans la mémoire `pc-ml-state-artifacts-missing`) :
1. `ml/output/detection/coin_detector/weights/best.pt` (YOLO) — rapatrier du Mac (suivi git côté Mac).
   Ré-entraîner (`go-task ml:detect-train`) est bloqué : `datasets/detection/coin_detect/` n'a que les
   **labels, aucune image** (gitignorées, source Roboflow `coin-gva2j` v1 CC BY 4.0). De plus son
   `data.yaml` a des chemins **Mac absolus** → fix portable = **omettre la clé `path:`** (ultralytics
   prend alors le dossier du yaml, `ultralytics/data/utils.py:504`). ⚠️ ce fix se fait perdre par un
   `git pull` (le yaml committé a les chemins Mac) → à committer proprement une fois.
2. `ml/state/foundation_anchors_2eur_commemo.npz` — reconstructible (import-numista + dino-anchors:build), cf. N2.
3. `ml/state/denom_probe.npz` — souvent présent (suivi git, ~5,7k).
4. `ml/state/fragment_face_probe.npz` (gate anti-fragment census) — builder **archivé**
   (`archive/scripts/build_fragment_probe.py`), pas de task active. Récupérable du blob historique :
   `git cat-file -p 7a096d76:ml/state/fragment_face_probe.npz > ml/state/fragment_face_probe.npz`.

**Piste durable.** Décider où vivent ces artefacts (les committer proprement / MinIO / doc de bootstrap
PC), plutôt que la dépendance implicite au Mac.

---

## N3 — Suggestions DINO faibles sur les nouveaux crops en review 🟠

**Symptôme (rapporté opérateur, 2026-07-08).** En review manuelle, les crops déjà validés avaient de
BONNES suggestions DINO ; les nouveaux crops (run `fc47cc3c`) ont des suggestions mauvaises/absentes.

**Preuve.** Sur 3999 `needs_review` du run : **1411 sans aucune prédiction DINO** (crops « non ciblés »
= recherches générales sans `target_eurio_id` → `out_of_scope=1434` à l'auto_validate). Les 2588 avec
prédiction ont un `top1_sim` (banque `2eur_all`, celle des suggestions review) **médian 0,705** vs
**0,803** pour les crops déjà validés manuellement (p25 0,63 vs 0,75).

**Causes.** (1) La banque de suggestions `foundation_anchors_2eur_all.npz` est **ancienne (12 juin) et
petite (406 ancres, vitl14)** → couverture insuffisante des pièces de ce scrape large (lié N2).
(2) Qualité crop plus faible (détecteur non calibré eBay, lié N1) → embeddings plus faibles → sim plus basse.

**Correctif proposé (levier le plus rentable pour la review).**
1. Rebuild `2eur_all` avec couverture complète + crops validés en multi-exemplaires :
   `go-task ml:dino-anchors:build -- --kind 2eur_all --force` (après avoir complété les obverses, N2).
2. Recalculer les suggestions : `go-task ml:dino-predictions:backfill -- --kind 2eur_all --force`.
3. Les 1411 « non ciblés » : décider s'ils doivent recevoir une prédiction country-agnostique ou être
   routés différemment (aujourd'hui ils arrivent en review sans aide DINO).
Fond : (N1) calibrer/ré-entraîner le détecteur sur crops eBay.

## Référence opérationnelle

**Reprocess des raws d'un run SANS re-scraper eBay** (idempotent, aucun appel/credential eBay) :
`process_downloaded` (`ml/sources/_base/orchestrator.py:263`) reprend le **même** run et enchaîne
detect → crop → auto_validate → enqueue → price_aggregate sur les `download_status='success'`.
- CLI : `python -m sources.cli --source ebay --crop-pending <run_id> --no-push`
  (⚠️ `--source` **requis** ; `--no-push` = Modèle A local, sinon push auto au VPS si `EURIO_API_URL` défini).
- Endpoint : `POST /sources/{source}/runs/{run_id}/crop` (`sources_routes.py:598`, push auto VPS).
- Le backend `--reload` **n'a pas besoin de restart** : chargement YOLO paresseux ; uvicorn ne
  surveille que les `.py` → écrire des `.npz/.pt/.jpg/.yaml/.md` ne déclenche **pas** de hot-reload.

**État du run `fc47cc3c` au moment de la rédaction (2026-07-08, ~21:20)** : `--no-push`, gelé sur
l'image 42 Mpx (B2), **1785/6683 traités, 1298 crops**. Décision en attente : attendre / kill + quarantaine
des 4 images `205878939286` + reprise.

**Chemins clés.** DB canonique locale `ml/state/eurio.db` · quota `ml/shared/state/eurio.db` (B1) ·
run log `ml/state/run_logs/<run_id>.log` · artefacts `ml/state/*.npz`, `ml/output/detection/.../best.pt`.
