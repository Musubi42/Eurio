# 02 — Décommission Supabase : le paradoxe du « retiré mais obligatoire »

> Fiche de remédiation — hardening 2026-07. Auto-portée : toutes les preuves sont en `file:line`.

## Résumé — le paradoxe

La doctrine actée dit : **eurio.db (SQLite, writer VPS) = LA source de vérité ; Supabase retiré**.
D2+D7 (2026-07-01, commits `05d9eb0` + `6c866b9`) ont retiré Supabase du **front** admin, et le TODO
restant est explicite : « purger `VITE_SUPABASE_*` de `secrets/dev.env` + révoquer la clé
`service_role` ».

**MAIS** la review montre que Supabase reste un **maillon obligatoire** de quatre chaînes vivantes,
toutes authentifiées par cette même clé `service_role` marquée pour révocation :

1. **Confusion-map (écriture)** — le compute local upsert dans Supabase, pas dans eurio.db
   (`ml/training/eval/confusion_map.py:568-606`, déclenché par `ml/serving/server.py:1393-1456`).
2. **coins_review** — router `/coins-review` monté en prod, 100 % PostgREST direct
   (`ml/serving/server.py:164-166`, `ml/review/coins_review_routes.py:32,39-51`).
3. **zone_resolver (training)** — l'agressivité d'augmentation par zone lit Supabase
   (`ml/training/zone_resolver.py:29-54`).
4. **TOUTE la chaîne export catalogue** — projection C2 (`ml/export/app_export/io.py:56-68`),
   upload des avers Storage (`ml/export/upload_app_obverse.py:132-138`), et build de
   `app_core.db` packagé dans l'APK (`ml/export/build_app_core.py:45,242`).

**Conséquence : révoquer `service_role` aujourd'hui casse silencieusement le shipping du
catalogue Android** (`go-task ml:sync-app` / `ml:upload-app-obverse` / `ml:build-app-core` →
`RuntimeError` io.py:64 côté build, 401 côté Storage) ainsi que la review coins et le pilotage
de zones au training. La doctrine et le pipeline de shipping se contredisent : il faut trancher
**avant** de révoquer — mais il faut **roter** la clé immédiatement (voir P0), car elle a fuité.

## Table des findings

| Sévérité | Preuve (file:line) | Constat |
|---|---|---|
| **critical** | `.envrc copy` (tracké à HEAD, commits `f7dd22f`/`a8d7f55`/`22fc46f`) ; `.gitignore` (ne couvre que `.envrc.local`) | Secrets en clair (`SUPABASE_SERVICE_ROLE_KEY`, `VITE_SUPABASE_SERVICE_KEY`, eBay PROD, Numista) poussés sur codeberg **et** github. Le pilote a retiré le fichier du tracking, mais **les clés ne sont pas révoquées** et **l'historique des 2 remotes les contient encore**. |
| **high** | `docs/operations/secrets-followup.md` (~l.14-16) | Le doc affirme « historique git nettoyé / caviardé » — **faux** : `.envrc copy` a re-fuité les mêmes secrets après le caviardage. Cases §2 (révocation eBay PROD + service_role) toujours `[ ]`. Faux sentiment de sécurité. |
| **high** | `ml/serving/server.py:1393-1456` (compute) + `ml/training/eval/confusion_map.py:568-606` (upsert Supabase) vs `ml/serving/confusion_routes.py:1-9,30-37` (lecture SQLite, VPS via `server_serve.py:40,100`) ; `ml/serving/migrate_orphan_supabase.py:1-19` (one-shot, jamais rejoué) | Confusion-map **divisée** : écriture → Supabase (compute local Mac/PC), lecture VPS → eurio.db figé au dernier run manuel du one-shot. Toute nouvelle cartographie diverge silencieusement. `admin/.../useConfusionMap.ts:113-115` admet la confusion de nommage sans la corriger. |
| **high** | `ml/serving/server.py:1094` (`_export_status`), `:1144-1176` (`trigger_export`), `:1367-1373` + `:1393-1456` (`_confusion_status` / compute) | Guard anti-double-run des jobs `/export/tflite` et `/confusion-map/compute` = dicts module-level, `subprocess.run` en thread sans `start_new_session=True` ni PID persisté. Un `--reload` remet `running: False` → double compute possible écrasant `checkpoints/best_model.pth`, `prod/current/tflite/*`. Même piège que BUG-1 documenté `server.py:246-276`, déjà corrigé dans `lab_routes.py` mais pas ici. |
| **medium** | `ml/review/coins_review_routes.py:32,39-51,340-535` ; monté `ml/serving/server.py:164-166` ; consommé par `admin/packages/studio-local/src/features/coins/composables/useCoinsReview.ts:86,112,120,136,152` | `/coins-review` (queue, rebind, no-coverage, delete-redirect) = PostgREST direct avec `service_role`. Chemin **vivant**, non listé comme dépendance restante dans le plan de révocation → casse sans fallback si révocation. |
| **medium** | `ml/export/app_export/io.py:56-68,81-125` ; `ml/export/upload_app_obverse.py:132-138` ; `ml/export/build_app_core.py:45,242` | Chaîne catalogue bout-en-bout dépendante de `SUPABASE_SERVICE_ROLE_KEY` (delete_all/upsert bypass RLS, empty+refill du bucket `coin-images`, relecture Supabase pour `app_core.db`). |
| **medium** | `ml/export/app_export/io.py:36,44-49` ; `ml/export/build_app_core.py:48` ; `ml/export/upload_app_obverse.py:91,117` | Chaîne export lit `ml/state/eurio.db` **codé en dur**, ignore `EURIO_DB_PATH` et la réplique `eurio.replica.db` (contrairement aux ~20 fichiers `serving/*`/`training/eval/*` qui l'honorent). Lancée hors du host au eurio.db frais → projection + APK construits sur données périmées, silencieusement. |
| **medium** | `secrets/dev.env` (sops, noms) ; `infra/eurio-admin/Dockerfile:~38` | `VITE_SUPABASE_URL/ANON_KEY/SERVICE_KEY` + `SUPABASE_*` toujours dans le store SOPS alors que le Dockerfile confirme « plus aucun VITE_SUPABASE_* requis au build ». Une service_role derrière préfixe `VITE_` = risque bundle. |
| **medium** | `infra/review/docker-compose.yml:20-26` ; `infra/review/entrypoint.sh` (`load_secret`) ; `infra/review/secrets/review_admin_token` (fichier réel, 65 o) | Pattern legacy Docker-secrets déprécié (CLAUDE.md §Secrets) toujours vivant ; token admin en clair dans le working tree d'une machine dev. |

## Le nœud : qui dépend de `service_role`, et qui va où

| Chaîne | Auth actuelle | Destination cible | Justification |
|---|---|---|---|
| **Confusion-map écriture** (`confusion_map.py:568-606` + `server.py:1393-1660`) | service_role (upsert `coin_confusion_map`) | **Migrer → eurio.db** | La lecture est DÉJÀ en SQLite (`confusion_routes.py`, VPS). Migrer l'écriture supprime le split et le one-shot `migrate_orphan_supabase.py`. Aucune raison app-facing : c'est de la donnée interne ML. |
| **zone_resolver** (`zone_resolver.py:29-54`) | service_role/anon (lecture `coin_confusion_map`) | **Migrer → eurio.db** | Consomme la même table ; suit mécaniquement la migration de l'écriture. Donnée interne training. |
| **coins_review** (`coins_review_routes.py`) | service_role (lecture/écriture coins) | **Migrer → eurio.db/Store** | Le reste de `review/` est déjà sur Store ; c'est de l'admin, domaine où la doctrine SQLite-only s'applique sans ambiguïté. |
| **Export catalogue** (`app_export/io.py`, `upload_app_obverse.py`, `build_app_core.py`) | service_role (delete_all/upsert projection C2 + Storage `coin-images` + relecture pour APK) | **Dépend de la décision produit (§5)** | C'est la **projection app-facing read-only** actée par la mémoire projet (« Supabase = projection read-only app-facing de eurio.db »). Soit elle est assumée (Supabase reste, avec une clé scoppée), soit elle disparaît (tout passe par snapshot APK). |

Point clé : les trois premières chaînes doivent migrer **quelle que soit** la décision produit.
Seule la chaîne export conditionne le sort final de Supabase et de la clé.

> ### ✅ État 2026-07-05 — C3/C2/C5 livrés (`79f3359`/`50ffabf`/`b7cc8dd`, poussés), **C1=Option A**
>
> **Corrections à la fiche** (vérifiées contre la vraie eurio.db) : (a) **C5 était déjà fait** en F01
> `3663703` — `app_export/io.py._DB_PATH` route via `resolve_db_path` ; `build_app_core.py:48` est le
> chemin de SORTIE `app_core.db`, pas un read à router (la fiche l'a mal identifié). (b)
> `coin_confusion_map` vit dans `serving/migrations/0002` (pas `schema.sql`) et était **vide** (le
> one-shot n'a jamais convergé).
>
> - **C3 zone_resolver → SQLite** ✅ (lecture `coin_confusion_map` via resolver ; table absente →
>   défaut orange ; autre `OperationalError` propagée). 4 tests.
> - **C2 confusion-map** ✅ CODE (écriture ET lecture hors Supabase) : `store/confusion.py`
>   (`apply_ingest_confusion_map`, validation bruyante), `POST /ingest/confusion-map` (canonique),
>   `client.ingest.push_confusion_map` (Direction A) + fallback write local Model A ; routes lecture
>   `server.py` repointées eurio.db ; guard anti-double-run refait (`_spawn_detached_job` + PID
>   sidecar, fix `--reload`) ; `migrate_orphan_supabase.py` supprimé. 7 tests. **RESTE : déployer
>   `server_serve.py` au VPS** pour exposer `/ingest/confusion-map` avant tout compute Direction A.
> - **C5 export** ✅ (routage déjà OK ; docstring corrigé ; Option A documentée dans model-b/README).
>   **RESTE : créer la clé Supabase scopée** (dashboard, action user) ; `service_role` NON révoquée.
> - **C4 coins_review** ❌ **BLOQUÉ — DÉCISION PO REQUISE** : le modèle de données de la feature
>   n'existe PLUS dans eurio.db (colonnes `review_action_hint`/`review_payload`/`cross_refs`/`images`
>   absentes ; writer legacy `apply_3e_enrich_context.py` Supabase-only ; les 6 `needs_review` réels
>   portent le schéma récent `review_reason=variant_canonical_*` sans mapping vers les 3 buckets du
>   front). Un rewrite « au jugé » inventerait du produit (R0/R1) ou viderait la file en silence. **À
>   trancher** : (a) porter l'enrichissement review-context dans eurio.db + réconcilier le front avec
>   `variant_canonical_*`, ou (b) retirer cette feature legacy. `coins_review` **garde donc sa
>   dépendance `service_role`** — ne pas révoquer en croyant F02 l'a couverte.
> - **C6** (secrets SOPS) = action user : purger `VITE_SUPABASE_*` ; garder `SUPABASE_SERVICE_ROLE_KEY`
>   pour l'export Option A jusqu'à la clé scopée.
>
> Suite : **1393 pass / 0 rouge** (11 tests neufs, zéro régression), vérifié dans le checkout principal.

## Plan en chunks ordonnés

### P0 — Rotation + purge des secrets (BLOQUANT, avant tout le reste)

Prérequis absolu : les clés actuelles sont **compromises** (fuite `.envrc copy` sur codeberg +
github, historique non purgé). Aucune migration ne doit se faire « pour éviter de roter » — on
rote d'abord, on migre ensuite.

- **Fichiers/actions** :
  - Révoquer/roter dans les dashboards : `SUPABASE_SERVICE_ROLE_KEY` (+ anon), `EBAY_CLIENT_ID/SECRET` PROD, `NUMISTA_API_KEY_MUSUBI00/01`. *(Action PO — dashboards externes.)*
  - Purger l'historique des **2 remotes** (`git-filter-repo` sur `.envrc copy`, force-push codeberg + github), le fichier étant déjà hors tracking à HEAD.
  - `.gitignore` : ajouter `.envrc copy` (et idéalement un pattern `.envrc*` avec exception `.envrc` + `.envrc.example`).
  - Supprimer `/opt/eurio/.envrc copy` sur le VPS (world-readable 644).
  - Injecter les **nouvelles** clés via `go-task secrets:edit` (la chaîne export doit continuer à marcher jusqu'à la décision §5 — ne PAS révoquer sans remplacer tant que C1 n'est pas tranché).
  - Corriger `docs/operations/secrets-followup.md` : retirer l'affirmation « caviardé de tout l'historique », documenter la re-fuite, re-cocher les cases quand c'est réellement fait.
- **Vérif** : `git log --all --diff-filter=A -- '.envrc copy'` vide sur les 2 remotes après purge ; ancienne service_role → 401 sur PostgREST ; `go-task ml:sync-app` (dry) passe avec la nouvelle clé ; `stat '/opt/eurio/.envrc copy'` → ENOENT.

### C1 — Décision produit projection catalogue (voir §5)

- **Fichiers** : aucun code — décision PO consignée dans `docs/work-in-progress/model-b/README.md` + cette fiche.
- **Vérif** : la décision (option A ou B) est écrite, datée, et le sort de `service_role` en découle explicitement.

### C2 — Confusion-map : écriture → eurio.db, retrait du one-shot

- **Fichiers** :
  - `ml/training/eval/confusion_map.py` : remplacer l'upsert Supabase (l.568-606) par un `INSERT OR REPLACE` dans `eurio.db.coin_confusion_map` (via `EURIO_DB_PATH` / API eurio-api si le compute tourne sur Mac/PC et le writer est le VPS — respecter la Direction A writer-unique : passer par un endpoint eurio-api d'ingestion plutôt qu'une écriture SQLite distante).
  - `ml/serving/server.py:1367-1660` : supprimer les routes `/confusion-map/*` Supabase au profit du router SQLite existant `ml/serving/confusion_routes.py` (à monter aussi côté ML API locale si nécessaire), et au passage corriger le guard anti-double-run (Popen `start_new_session=True` + PID persisté + reaper, pattern `lab_routes.py`) — même correctif pour `trigger_export` (l.1144-1176).
  - Supprimer `ml/serving/migrate_orphan_supabase.py` (après un dernier run de rattrapage).
  - `admin/.../useConfusionMap.ts` : retirer le fallback double-source et renommer les fonctions `*FromSupabase` (l.113-115).
- **Vérif** : compute d'une cartographie depuis l'UI locale → `SELECT count(*), max(computed_at) FROM coin_confusion_map` sur le eurio.db VPS reflète le run **sans** action manuelle ; grep `coin_confusion_map` dans `ml/` ne retourne plus aucun client Supabase ; kill `--reload` pendant un compute → pas de double job possible au redémarrage.

### C3 — zone_resolver → eurio.db

- **Fichiers** : `ml/training/zone_resolver.py` (l.29-54) : remplacer `_make_supabase_client`/`fetch_eurio_zones` par une lecture SQLite (`EURIO_DB_PATH`, fallback réplique `eurio.replica.db` sur Mac/PC — le training tourne là où le compute a lieu). Conserver le fallback `DEFAULT_ZONE` si table vide.
- **Vérif** : lancer un training avec zones connues → log `[zone_resolver]` montre les zones lues depuis SQLite ; `SUPABASE_URL` absent de l'env → plus aucun warning « defaulting all classes to orange » causé par Supabase.

### C4 — coins_review → eurio.db/Store

- **Fichiers** : `ml/review/coins_review_routes.py` (réécrire `_sb()`/requêtes PostgREST l.340-535 sur le Store SQLite, comme le reste de `review/`) ; `ml/serving/server.py:164-166` (rebind sur `_store`) ; le front `useCoinsReview.ts` ne change pas (mêmes endpoints).
- **Vérif** : parcours complet queue → rebind → no-coverage → delete-redirect depuis studio-local en mode local, avec `SUPABASE_*` retirés de l'env ; les 82+ tests review passent.

### C5 — Chaîne export : `EURIO_DB_PATH` + exécution de la décision C1

- **Fichiers** :
  - `ml/export/app_export/io.py:36,44-49`, `ml/export/build_app_core.py:48`, `ml/export/upload_app_obverse.py:91,117` : router `_DB_PATH`/`get_sqlite_con()` via `EURIO_DB_PATH` (resolve commun `ml/store`), ou refuser de tourner si le chemin n'est pas le canonique attendu — quelle que soit l'option C1, l'export doit lire la donnée fraîche.
  - Si **option B** (tout-SQLite) : réécrire `io.py` (delete_all/upsert PostgREST → écriture `app_core.db`/snapshot direct), `upload_app_obverse.py` (Storage Supabase → MinIO ou assets APK), `build_app_core.py:242` (relire eurio.db au lieu de Supabase). Puis seulement : révoquer définitivement `service_role`.
  - Si **option A** (projection assumée) : créer une clé **dédiée scoppée** aux tables de projection + bucket `coin-images` (pas la service_role globale), documenter dans `docs/work-in-progress/model-b/README.md` que Supabase = projection app-facing assumée.
- **Vérif** : `go-task ml:sync-app` lancé sur une machine où `ml/state/eurio.db` est stale → soit lit la réplique fraîche, soit refuse explicitement (plus de counts plausibles silencieux) ; option B : `grep -rn SUPABASE ml/export/` vide ; option A : la service_role globale révoquée, l'export passe avec la clé scoppée.

### C6 — Nettoyage final secrets + legacy

- **Fichiers** : `secrets/dev.env` (retirer `VITE_SUPABASE_*` ; retirer `SUPABASE_SERVICE_ROLE_KEY` si option B) via `go-task secrets:edit` ; `infra/review/` (migrer vers SOPS-via-env comme eurio-api, ou finaliser la suppression C9 auth-redesign) ; supprimer `infra/review/secrets/review_admin_token` du disque local.
- **Vérif** : `go-task secrets:list` sans `VITE_SUPABASE_*` ; `grep -rn '_FILE' infra/review/` vide ou dossier supprimé ; `ls infra/review/secrets/` ne contient que `.example`.

## Décision produit centrale (à trancher par le PO — conditionne C1/C5 et la révocation)

> **Supabase reste-t-il la projection app-facing de eurio.db (l'app Android lit Supabase :
> tables C2 + Storage `coin-images`), ou bien tout passe en eurio.db → snapshot/`app_core.db`
> packagé APK (+ assets MinIO), et Supabase disparaît entièrement ?**

- **Option A — projection assumée** : Supabase n'est PAS « retiré », il est **requalifié** :
  read-only app-facing, alimenté par la chaîne export avec une clé dédiée scoppée. La mémoire
  projet « Supabase app schema V2 » va dans ce sens. La service_role globale peut être révoquée,
  mais Supabase reste une dépendance runtime de l'app (free tier : DB 0.5 GB, egress 5 GB).
- **Option B — tout-SQLite** : cohérente avec la doctrine SQLite-only et l'offline-first APK
  (`app_core.db` est déjà packagé dans l'APK par `build_app_core.py:48`). Demande de re-router
  la relecture (`build_app_core.py:242`) sur eurio.db et de déplacer les avers vers MinIO/assets.
  À terme : **zéro clé Supabase**, compte fermable.

**Tant que cette décision n'est pas prise, `service_role` ne doit PAS être révoquée sans
remplacement — mais elle doit être ROTÉE immédiatement (P0), car la valeur actuelle a fuité.**

## Effort + priorité

| Chunk | Effort | Priorité |
|---|---|---|
| P0 rotation + purge | ~2-3 h (dashboards + filter-repo ×2 remotes + VPS) | **P0 — immédiat, sécurité** |
| C1 décision projection | discussion PO | **P0-bis — bloque C5** |
| C2 confusion-map | ~3 h (écriture + suppression routes + guard jobs + one-shot) | P1 |
| C3 zone_resolver | ~1 h | P1 (avec C2) |
| C4 coins_review | ~2-3 h (réécriture Store + tests) | P2 |
| C5 export catalogue | option A ~1 h (clé scoppée + EURIO_DB_PATH) / option B ~1-2 j (re-plomberie Storage/projection) | P2 (après C1) |
| C6 nettoyage secrets/legacy | ~1 h | P3 |

Total : ~1 à 3 jours selon l'option retenue en C1. Le seul travail non différable est P0.
