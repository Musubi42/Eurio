# Revue complète de robustesse — Eurio (2026-07-04)

> **Nature** : audit de *robustesse* (pas une roadmap produit). On cherche les endroits où le
> code « attend quelque chose », où la doc dit une chose et le code l'inverse, où une brique est
> écrite deux fois, où un échec passe en silence. **On ne développe pas de feature ; on solidifie.**
>
> **Méthode** : review multi-agents pilotée par Fable 5 — 15 lecteurs par zone (Sonnet/Opus) +
> 2 passes transverses (Opus) + vérification adversariale finding par finding (Sonnet). 76 agents,
> 4,15 M tokens. Chaque finding ci-dessous a été **relu et confirmé** sur le code réel (`file:line`).

## Bilan chiffré

- **58 findings confirmés** : 4 critical · 21 high · 33 medium. + **19 low** confirmés. 1 réfuté (écarté).
- **12 corrigés directement** par la session d'audit (working tree, non committés) — voir colonne *Traitement* = `corrige`.
- **46 restants** cadrés dans **9 fiches de remédiation** auto-portées (`F01`…`F09`), prêtes à dispatcher.

> 🔴 **Ces chiffres datent du 2026-07-04. Lis [`ETAT-2026-08-25.md`](ETAT-2026-08-25.md) avant les fiches** : sur les 46, **26 sont tombés tout seuls** depuis, 2 sont sans objet, et **36 tiennent** — la re-vérification a été faite au code, finding par finding.

## ⚠️ Action P0 utilisateur (hors périmètre agent)

Le fichier **`.envrc copy`** contenait `SUPABASE_SERVICE_ROLE_KEY`, eBay PROD, clés Numista **en
clair**, tracké et **poussé sur codeberg + github**. Il a été **retiré du tracking + gitignoré**
par l'audit, MAIS :

1. **Révoquer/rotater MAINTENANT** : Supabase `service_role`, eBay PROD (Client ID + Secret),
   clés Numista. Elles sont compromises publiquement.
2. **Purger l'historique** des 2 remotes (`git-filter-repo`) + force-push — le `git rm` ne suffit pas.
3. Détail et suivi : `docs/operations/secrets-followup.md` (bandeau d'alerte mis à jour).

## Les 9 fiches de remédiation

| # | Fiche | Cœur |
|---|---|---|
| **F01** | [`01-sync-direction-a-cablage.md`](./01-sync-direction-a-cablage.md) | La réplique auto-sync est **livrée mais inerte** : `EURIO_DB_PATH` n'est posé nulle part → rien ne lit la réplique fraîche, et plusieurs writers/lecteurs hardcodent `ml/state/eurio.db`. Le gros morceau. |
| **F02** | [`02-supabase-decommission.md`](./02-supabase-decommission.md) | « Supabase retiré » mais confusion-map, coins_review, zone_resolver **et toute la chaîne catalogue** en dépendent encore via `service_role`. Révoquer la clé casse le shipping APK. |
| **F03** | [`03-android-robustesse.md`](./03-android-robustesse.md) | 2 bugs UX bloquants (permission caméra jamais re-demandée ; échec bind CameraX avalé), + APP_CORE_VERSION manuel, double state machine scan, couleurs hardcodées. |
| **F04** | [`04-front-studio-hygiene.md`](./04-front-studio-hygiene.md) | `useCapabilities` existe mais **aucune feature ne le consomme** → 5-6 health-checks dupliqués, pas de retry, routes non-heavy servant du **mock silencieux** en hosted. |
| **F05** | [`05-tests-reparation.md`](./05-tests-reparation.md) | Les « 18 rouges connus » ne sont pas du bruit : certains cachent des **bugs de prod** (wipe_referential détruit des tables préservées ; source_registry jamais seedé). |
| **F06** | [`06-duplication-refacto.md`](./06-duplication-refacto.md) | Briques écrites N fois : fetch+cache+ratelimit ×3, reap PID ×3, pattern transactionnel ×6, **contrat app_core en Python+TS+Kotlin** sans source unique. |
| **F07** | [`07-store-atomicite.md`](./07-store-atomicite.md) | `isolation_level=None` (autocommit) : 5 handlers `lab_routes` enchaînent des écritures **sans BEGIN** → états partiels définitifs en cas d'erreur. |
| **F08** | [`08-docs-et-garde-fous.md`](./08-docs-et-garde-fous.md) | Nettoyage doc-drift + **garde-fous durables** contre les difficultés récurrentes (échec silencieux, HANDOFF périmé, bypass writer). |

## Ce qui a été corrigé directement (working tree, non committé)

| Fichier | Correction |
|---|---|
| `.envrc copy`, `.gitignore` | Retiré du tracking git + patterns anti-fuite (`.envrc copy`, `.envrc*copy*`, `*.envrc.bak`) ; `image copy.png` détracké |
| `ml/serving/crop_recovery_routes.py`, `ml/bench/crop_recovery/common.py` | Path-traversal `/crop-recovery/raw` fermé : chemin absolu accepté **seulement** sous l'arbre `ml/` (résolution symlinks) |
| `ml/serving/lab_routes.py` | Décorateur `DELETE …/iterations/…` remis sur `delete_iteration` (le guard 409 + suppression DB était mort, shadowé par `_purge_iteration_artifacts`) |
| `ml/review_service/routes_reviewer.py` + `db.py` | Double ROLLBACK supprimé + `writing()` rendu défensif → le 409 (conflit de claim) n'est plus masqué en 500 |
| `ml/review_service/auth.py` | Secret HMAC de session : **fail-hard** si `REVIEW_SESSION_SECRET` absent (opt-out dev explicite) au lieu du fallback public `dev-insecure-secret` |
| `ml/export/app_export/run.py` | `except ImportError: pass` → capture l'erreur réelle et **échoue** (exit 1) au lieu de « skipped », un builder cassé n'est plus invisible |
| `ml/shared/storage/cascade.py` | Lit `EURIO_DB_PATH` (convention repo) au lieu de `EURIO_DB` divergent ; `EURIO_DB` en fallback déprécié |
| `docs/operations/secrets-followup.md` | Bandeau : l'affirmation « caviardé de tout l'historique » est fausse (re-fuite `.envrc copy`) |
| `docs/work-in-progress/model-b/README.md` | Bandeau : event-log **abandonné** (Direction A), ne pas suivre le paragraphe barré |
| `docs/work-in-progress/collaborative-review/README.md` | Statut corrigé : implémenté + testé E2E, reste le déploiement VPS (n'était pas « rien implémenté ») |
| `CLAUDE.md` | `android:snapshot`/`snapshot-dry` (inexistants) → `ml:build-app-core` |

## Inventaire complet des findings (58 confirmés + 19 low)

Colonne *Traitement* : `corrige` = déjà appliqué · `F0x` = fiche de remédiation · `corrige-doc` = doc corrigée.

| Sév | Cat | Traitement | Fichier | Finding |
|---|---|---|---|---|
| critical | security | corrige | `.envrc copy` | Fichier `.envrc copy` avec secrets en clair committé et poussé sur codeberg + github + présent world-readable sur le VPS |
| critical | security | corrige | `ml/serving/crop_recovery_routes.py` | Lecture de fichier arbitraire via /crop-recovery/raw?key=<chemin absolu> |
| critical | bug | F05 | `ml/scripts/wipe_referential.py` | wipe_referential.py cascade-supprime les tables « préservées » (coin_variants, coin_mint_releases, mint_release_prices/observations, coin_credits) |
| critical | bug | corrige | `ml/serving/lab_routes.py` | DELETE /cohorts/{cohort_id}/iterations/{iteration_id} : le décorateur de route est sur la mauvaise fonction — le guard 409 (itération en cours) est mort |
| high | bug | F03 | `app-android/src/main/java/com/musubi/eurio/features/onboarding/pages/OnboardingPermissionPage.kt` | Onboarding claims ScanScreen re-requests camera permission on skip — it doesn't |
| high | bug | F03 | `app-android/src/main/java/com/musubi/eurio/features/scan/components/CameraPreview.kt` | CameraX bind failure is silently swallowed — no error state, no user feedback |
| high | incomplete | F03 | `app-android/src/main/java/com/musubi/eurio/data/local/bootstrap/AppCoreBootstrapper.kt` | APP_CORE_VERSION is a hand-maintained constant with no tooling to bump it — stale catalog risk on every asset refresh |
| high | doc-drift | corrige-doc | `docs/work-in-progress/model-b/README.md` | model-b/README.md (doc unique déclaré) affirme que le sync event-log est livré et fonctionnel, alors qu'il a été abandonné le jour même |
| high | incomplete | F08 | `ml/serving/crop_edit.py` | Suppression de crop potentiellement bloquée en production si le VPS n'a pas encore le endpoint DELETE /ingest/assets (déploiement C4-C8 pas confirmé) |
| high | doc-drift | F01/F08 | `docs/work-in-progress/local-sync/HANDOFF-next-session.md` | HANDOFF-next-session.md (point d'entrée unique de reprise) est périmé de 5 commits |
| high | arch | F01/F08 | `ml/scripts/gate_standard_vision.py` | gate_standard_vision.py et bench_routes.py écrivent encore directement en local hors du writer canonique VPS (Direction A non fermée) |
| high | doc-drift | corrige-doc | `docs/operations/secrets-followup.md` | doc-drift: secrets-followup.md affirme l'historique 'caviardé de tout l'historique' — faux, les mêmes secrets sont en clair à HEAD |
| high | bug | corrige | `ml/review_service/routes_reviewer.py` | Double ROLLBACK masque le 409 en 500 sur /items/{id}/decide (conflit de claim) |
| high | security | corrige | `ml/review_service/auth.py` | Secret de session HMAC review_service en dur, sans garde-fou de démarrage |
| high | bug | F01/F06 | `ml/serving/referential_routes.py` | Endpoints /referential/discover et /referential/heal appellent un module archivé et inexistant (scripts.migrate_canonical_images_local) |
| high | bug | F06/F01 | `ml/serving/server.py` | Guard anti-double-run des jobs subprocess non détachés (/export/tflite, /confusion-map/compute) cassé par --reload |
| high | doc-drift | F06/F01 | `ml/serving/server.py` | Confusion-map divisée entre Supabase (écriture, compute local) et SQLite eurio.db (lecture, VPS) sans synchro continue — doctrine SQLite-only violée |
| high | bug | F07/F01 | `ml/serving/lab_routes.py` | Décisions du Jeu d'entraînement non-atomiques sur le Store local (autocommit non enveloppé) |
| high | bug | corrige | `ml/shared/storage/cascade.py` | Cascade de suppression MinIO↔DB lit une variable d'env différente (EURIO_DB vs EURIO_DB_PATH) — divergence silencieuse possible |
| high | bug | F07/F01 | `ml/scripts/wipe_referential.py` | EURIO_DB_READONLY et EURIO_DB_PATH ignorés par ~30 scripts CLI qui ouvrent sqlite3.connect() directement sur un chemin hardcodé |
| high | bug | corrige | `ml/export/app_export/run.py` | app_export/run.py masque toute erreur d'import des builders comme "pas encore implémenté" |
| high | bug | F03/F04 | `admin/packages/parity/flows/scan-detecting.yaml` | 5 flows de capture parity Scan ciblent des routes proto supprimées — capture silencieuse du mauvais écran (Placeholder) |
| high | incomplete | F01 | `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/serving/server.py` | Réplique auto-pull inerte : aucun chemin de lecture ne consomme eurio.replica.db (EURIO_DB_PATH non posé sur Mac/PC) |
| high | bug | F01 | `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/serving/referential_fix_apply.py` | referential_fix_apply / sources_aggregator hardcodent ml/state/eurio.db et ignorent EURIO_DB_PATH → cassés sur le writer canonique VPS |
| high | bug | F05 | `ml/sources/_base/steps/price_aggregate.py` | source_registry n'est jamais auto-seedé — toute écriture data-aware (coin_source_refs, price_aggregate) crash sur une DB fraîche |
| medium | doc-drift | corrige | `CLAUDE.md` | CLAUDE.md documents `go-task android:snapshot` / `android:snapshot-dry`, which no longer exist |
| medium | duplication | F03 | `app-android/src/main/java/com/musubi/eurio/features/scan/components/ScanRevealLayer.kt` | Pervasive hardcoded Color.White/Black overlays across the scan feature, violating the no-hardcode-color rule, with no single source of truth for alpha values |
| medium | arch | F03 | `app-android/src/main/java/com/musubi/eurio/features/scan/ScanViewModel.kt` | Two parallel scan state machines (legacy _state + domain _scanMachineState/ScanReducer) must be kept manually in sync, self-documented as unfinished migration debt |
| medium | bug | F01/F02 | `ml/export/app_export/io.py` | Toute la chaîne export catalogue lit eurio.db à un chemin codé en dur (ml/state/eurio.db), ignore EURIO_DB_PATH / la réplique |
| medium | doc-drift | F01/F02 | `ml/export/app_export/io.py` | Chaîne catalogue entièrement dépendante de SUPABASE_SERVICE_ROLE_KEY que la doctrine veut révoquer |
| medium | duplication | F06 | `ml/export/build_app_core.py` | Le contrat app_core (Snapshot v2) et son algorithme de reconstruction imbriquée sont ré-implémentés à l'identique en Python (producteur) et en TS (proto live), plus un 3e miroir de schéma côté Android — synchronisés à la main, sans aucun test de garde |
| medium | doc-drift | F08 | `docs/work-in-progress/local-sync/HANDOFF-next-session.md` | HANDOFF-next-session.md (point d'entrée unique pour reprise) liste comme 'travail de cette session' des tâches déjà closes 14 minutes plus tard par le commit suivant |
| medium | doc-drift | F08 | `docs/work-in-progress/README.md` | docs/work-in-progress/README.md ('focus actuel', point d'entrée du dossier WIP) est muet sur la migration Direction A, le chantier le plus critique en cours |
| medium | doc-drift | corrige-doc | `docs/work-in-progress/collaborative-review/README.md` | collaborative-review/README.md affirme 'Rien n'est implémenté' alors qu'un service complet existe dans le code depuis plusieurs commits |
| medium | dead-code | F02/F08 | `secrets/dev.env` | TODO connu ouvert: VITE_SUPABASE_* + SUPABASE_SERVICE_ROLE_KEY toujours dans secrets/dev.env alors que Supabase est retiré du front |
| medium | dead-code | F02/F08 | `infra/review/docker-compose.yml` | Pattern legacy Docker-secrets (déprécié) toujours vivant dans infra/review/ + token admin en clair dans le working tree |
| medium | duplication | F06 | `ml/sources/jo/adapter.py` | HTTP-fetch + daily-snapshot-cache + rate-limit brique copiée 3 fois (BCE, LMDLP, JO) |
| medium | test | F06 | `ml/sources/jo/adapter.py` | Adaptateur JO et scraper Wikipedia NL sans aucun test malgré une logique de matching complexe et des overrides manuels |
| medium | doc-drift | corrige-doc | `docs/work-in-progress/collaborative-review/README.md` | Doc-drift : README collaborative-review dit "Rien n'est implémenté" alors que le service complet existe et a été testé E2E |
| medium | doc-drift | F06/F02 | `ml/review/coins_review_routes.py` | coins_review_routes.py dépend directement de Supabase alors que la doctrine SQLite-only dit Supabase retiré côté admin |
| medium | arch | F01/F06 | `ml/scripts/_vps_only_guard.py` | Le garde-fou VPS-only (_vps_only_guard) ne couvre pas tous les scripts qui font des UPDATE bruts sur des colonnes canoniques hors /ingest |
| medium | duplication | F06/F01 | `ml/jobs/reaper.py` | Logique de reap PID-liveness dupliquée 3 fois alors qu'un helper canonique existe et est déjà réutilisé ailleurs |
| medium | arch | F06/F01 | `ml/serving/server.py` | server.py (API locale FULL) monte /ingest/* (écriture canonique) sur le Store local sans garde explicite qu'il soit bien read-only |
| medium | bug | F07/F01 | `ml/scripts/backfill_dino_predictions.py` | Réplique locale eurio.replica.db écrite en direct par backfill_dino_predictions.py au même chemin que l'autopull thread — course concurrente |
| medium | duplication | F07/F01 | `ml/sources/_base/steps/enqueue.py` | Deux stratégies d'idempotence différentes sur review_queue.UNIQUE(image_asset_id): UPSERT vs SELECT-then-INSERT racy |
| medium | dead-code | F03/F04 | `app-android/src/main/java/com/musubi/eurio/features/scan/components/ScanAcceptedCard.kt` | Deux composables Compose Scan complets sont du code mort (jamais appelés) mais documentés comme livrés |
| medium | bug | F03/F04 | `admin/packages/parity/capture/referential.ts` | capture:admin écrit dans le même dossier de sortie que capture:proto — collision/écrasement silencieux malgré un commentaire disant le contraire |
| medium | duplication | F04 | `admin/packages/studio-local/src/stores/capabilities.ts` | Trois implémentations indépendantes du health-check ML API (:8042/health), incohérentes entre elles |
| medium | bug | F04 | `admin/packages/studio-local/src/stores/capabilities.ts` | Le gate global hasLocalMlApi n'a aucun mécanisme de retry — le seul remède documenté est de recharger toute la page |
| medium | arch | F04 | `admin/packages/studio-local/src/app/router.ts` | Routes /sources/* et /referential/* appellent directement l'API ML locale (:8042) sans être marquées meta.heavy, en violation de la règle R0bis documentée dans CLAUDE.md |
| medium | duplication | F04 | `admin/packages/studio-local/src/stores/capabilities.ts` | Le store partagé useCapabilities (ping ML API) existe mais n'est utilisé par AUCUNE feature — 5+ réimplémentations indépendantes du même health-check |
| medium | arch | F04 | `admin/packages/studio-local/src/features/sources/pages/SourcesPage.vue` | Couplage cross-feature : sources/ importe usePoller/checkMlApi depuis training/ (feature non liée) |
| medium | bug | F04 | `admin/packages/studio-local/src/features/coins/pages/CoinDetailPage.vue` | Race condition dans CoinDetailPage.vue : fetchCoin et ses loaders chaînés n'ont pas de garde anti-réponse-obsolète |
| medium | bug | F01 | `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/client/replica.py` | Heuristique 'tout stderr = échec' fragile : stderr ssh bénin fait échouer un rsync réussi |
| medium | bug | F01 | `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/store/connection.py` | Piège latent : EURIO_DB_PATH→réplique sans EURIO_DB_READONLY ouvre la réplique en écriture et lance le bootstrap (collision avec sqlite3_rsync) |
| medium | doc-drift | F05 | `ml/tests/test_benchmark.py` | 7 tests de test_benchmark.py testent des modules qui n'existent plus au chemin importé — zéro couverture réelle sur le hold-out gate et l'agrégation real-photos |
| medium | doc-drift | F05 | `ml/tests/test_normalize_listing.py` | test_normalize_listing.py teste un pipeline Hough-seul que le code ne fait plus tourner en premier — 4 tests rouges depuis le passage à YOLO-first, plus aucune couverture sur la détection multi-pièces |
| medium | test | F05 | `ml/tests/test_model_b_c2_c3.py` | Fixture de test _seed_min_run incomplète : omet source_image_runs, viole l'invariant M:N que la prod respecte partout ailleurs |
| low | bug | F01/F02 | `ml/export/app_export/builders/coin.py` | _resolve_shared_reverse assigne un revers 2€ à TOUTES les pièces sans garde face_value |
| low | dead-code | F02/F08 | `image copy.png` | Fichier binaire orphelin `image copy.png` tracké à la racine du repo |
| low | doc-drift | F02/F08 | `infra/eurio-api/docker-compose.yml` | VPS déployé 3 commits derrière le travail sync local (non déployé) |
| low | duplication | F06 | `ml/sources/jo/adapter.py` | Parsing du suffixe slug de eurio_id dupliqué avec fallback silencieux inconsistant |
| low | duplication | F06/F02 | `ml/review/review_queue_routes.py` | Pattern transactionnel dupliqué (BEGIN/COMMIT/ROLLBACK manuel) au lieu de store._writing(), 6 occurrences dans ml/review/ |
| low | duplication | F01/F06 | `ml/scripts/crop_exp/sampler.py` | ml/scripts/crop_exp/ accumule des variantes sampler_*/score_crops_* quasi-dupliquées sans module partagé |
| low | bug | F07/F01 | `ml/store/connection.py` | _bootstrap(): ALTER TABLE additifs vulnérables à une race TOCTOU inter-process au démarrage concurrent |
| low | doc-drift | F03/F04 | `docs/design/_shared/components-parity.md` | components-parity.md documente ~25 composables Compose EurioXxx qui n'existent dans aucun fichier du repo |
| low | doc-drift | F03/F04 | `docs/design/_shared/scene-parity.md` | scene-parity.md n'a aucune ligne pour ProfileHistory.vue (route livrée) — violation de R4 |
| low | bug | F04 | `admin/packages/studio-local/src/stores/capabilities.ts` | Race condition au boot: hasLocalMlApi est faux par défaut jusqu'à résolution du ping, donc AppLayout affiche LocalOnlyNotice / nav grisée sur les routes heavy même quand l'API ML tourne réellement |
| low | arch | F04 | `admin/packages/studio-local/src/shared/utils/coin-images.ts` | shared/utils/coin-images.ts gate son fetch ML API sur import.meta.env.DEV, un signal indépendant et distinct de HAS_LOCAL_ML_API / hasLocalMlApi utilisé partout ailleurs |
| low | bug | F04 | `admin/packages/studio-local/src/features/denom-gold/pages/DenomGoldValidatePage.vue` | Checkbox 'masquer validés' (hideValidated) dans DenomGoldValidatePage : lié mais jamais consommé, no-op complet |
| low | doc-drift | F04 | `admin/packages/studio-local/src/features/confusion/composables/useConfusionMap.ts` | Doc-drift : confusion/useConfusionMap.ts nomme encore ses fonctions '...FromSupabase' et documente un fallback Supabase alors que Supabase est retiré du front depuis D7 (2026-07-01) |
| low | arch | F04 | `admin/packages/studio-local/src/shared/query/client.ts` | TanStack Query (cache partagé + IndexedDB) sous-utilisé : seuls lab/ et coins/useCoinLookups l'exploitent, ~20 autres pages réimplémentent loading/error/data à la main |
| low | bug | F01 | `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/client/replica.py` | Double writer non synchronisé sur eurio.replica.db : thread serveur (120s) + timer systemd PC (2min) lancent sqlite3_rsync en parallèle |
| low | bug | F01 | `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/client/replica.py` | Fallback API : /db/replica/sha et /db/replica appelés séparément → mismatch sha spurious si le snapshot se reconstruit entre les deux (TTL 60s) |
| low | dead-code | F01 | `/Users/musubi42/Documents/Musubi42/bizz/Eurio/ml/client/replica.py` | Import mort dans start_autopull_thread |
| low | test | F05 | `ml/tests/test_wipe_referential.py` | test_wipe_referential.py hardcode source_registry == 10 alors que la source_registry courante en a 11 (ajout JO) |
| low | test | F05 | `admin/packages/studio-local/package.json` | Aucun outillage de test dans le front unique studio-local |
