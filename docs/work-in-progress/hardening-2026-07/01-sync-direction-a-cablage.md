# Fiche 01 — Sync Direction A : câbler `EURIO_DB_PATH` / read-only partout

> **Résumé en une phrase** : la réplique auto-sync (`ml/state/eurio.replica.db`, commit `4c06cfb`)
> est LIVRÉE et se rafraîchit toutes les 120 s… mais **AUCUN chemin de lecture ne la consomme** —
> `EURIO_DB_PATH` n'est posé nulle part (ni `.envrc`, ni `flake.nix`, ni `Taskfile.yml`, ni
> `ml/tasks.yml` : grep vide), et une trentaine de writers/lecteurs hardcodent encore
> `ml/state/eurio.db` (legacy, périmé par construction sous Direction A) ou écrivent en local
> hors du writer canonique VPS.

> **AVANCEMENT (2026-07-04, session advisory)** — Chunks **0 ✅** (VPS déjà à `d0d2fb3`,
> `DELETE /ingest/assets` live), **1b ✅** (filet : réplique refusée en écriture au constructeur
> `StoreBase`), **2 ✅** (5 chemins serving/export routés via `resolve_db_path`), **3 ✅**
> (39 scripts CLI : 38 routés + 14 gardes read-only ; `wipe_referential --apply` refuse sous
> `READONLY=1`, dry-run OK ; `backfill_dino_predictions` isolé sur un scratch dédié). Zéro
> régression (1341 pass / 17 rouges pré-existants). Décisions PO tranchées : D1=run-batch,
> D2=route /ingest, D3=route /ingest/referential-fix, D5=n'importe quelle machine.
>
> **MAJ 2026-07-05** — Chunk **4c ✅** : `coin_source_status` ajouté au run-batch (`_TABLE_ORDER`
> + bloc `export_run` scopé `WHERE last_run_id=?`, `ml/client/runbatch.py`). Aucun changement
> serveur (l'ingest n'a pas d'allowlist ; `_TABLE_ORDER` est le seul gate). 2 tests ajoutés
> (`test_runbatch.py` : scoping `last_run_id` NULL exclu + round-trip avec dimensions seedées).
> Suite 1343 pass / 17 rouges pré-existants (zéro régression).
>
> **MAJ 2026-07-05 (bis)** — Chunk **5 ✅** : durcissement transport rsync (`ml/client/replica.py`)
> — stderr host-key bénin toléré (`_significant_stderr`, no-op silencieux toujours détecté),
> `StrictHostKeyChecking=accept-new` + `UserKnownHostsFile` stable, **flock** `state/replica.lock`
> non-bloquant couvrant thread-serveur ET timer systemd (skip si tenu), en-tête `X-Eurio-DB-Sha256`
> autoritaire + retry (fin de la course TTL du `/sha` séparé), import mort + commentaire faux
> retirés. 3 tests ajoutés ; suite 1346 pass / 17 rouges pré-existants.
> **Reste** : chunk 4a (route /ingest bench-exclude + gate-reject), 4b (/ingest/referential-fix),
> 6 (split local-state scratch), **1a** (flip `EURIO_DB_PATH`+`READONLY=1` — EN DERNIER).

Contexte : Direction A = writer unique VPS (`/var/lib/eurio/eurio.db`, process
`server_serve.py` avec `read_only=False` explicite à `server_serve.py:75`) + réplique locale
read-only tirée par `sqlite3_rsync` (`ml/client/replica.py`). Docs de référence :
`docs/work-in-progress/local-sync/replica-auto-sync.md`, `c4-c8-known-gaps.md`,
`vps-only-migrations.md`.

---

## 1. Table des findings

| Sévérité | Fichier:ligne | Constat (1 phrase) |
|---|---|---|
| **HIGH** | `ml/serving/server.py:63,102` + `ml/client/replica.py:42,231` | Réplique auto-pull **inerte** : le thread autopull (`server.py:194` → `start_autopull_thread()` sans `dest`) et le timer rafraîchissent `eurio.replica.db`, mais `EURIO_DB_PATH` n'étant posé nulle part, `CANONICAL_DB` retombe sur `state/eurio.db` legacy — tout le lab `:8042` lit du périmé en croyant lire du frais (la doc se contredit : `replica-auto-sync.md:13-15` vs §Limite connue `:89-99`). |
| **HIGH** | `ml/serving/referential_fix_apply.py:37` | `_DB_PATH = _ML_ROOT/"state"/"eurio.db"` figé (backup `:157`, mutations `:569`) alors que le router referential est monté sur l'image lean du VPS (`server_serve.py:174`) et expose `POST /referential/fix-proposals/{id}/apply` (`referential_routes.py:1119-1136`) — sur le VPS ce fichier n'existe pas, l'écriture ne peut structurellement PAS atteindre le canonique. |
| **HIGH** | `ml/serving/sources_aggregator.py:511` | Même hardcode `ML_DIR/state/eurio.db` (mode=ro) : sur le VPS `db_path.is_file()` est False → couverture BCE du dashboard operations retourne silencieusement `None`. |
| ✅ CORRIGÉ | `ml/shared/storage/cascade.py:39` | La cascade de suppression MinIO↔DB lisait `EURIO_DB` (variable inexistante ailleurs) au lieu d'`EURIO_DB_PATH`. **Corrigé par l'audit** : lit désormais `EURIO_DB_PATH` (fallback `EURIO_DB` déprécié + warning). `scripts/cascade_sync.py:35` hérite du fix via import. |
| **HIGH** | `ml/scripts/wipe_referential.py:399-402`, `enqueue_orphan_crops.py:26,43`, `discover_numista_standards.py:279`, … (~30 scripts) | `EURIO_DB_READONLY` **et** `EURIO_DB_PATH` ignorés : ces CLI font `sqlite3.connect(chemin hardcodé, isolation_level=None)` directement — la promesse de `store/connection.py:24-30` (« le flag bascule TOUS les Store ») ne couvre pas ces connexions brutes, qui écrivent en dur en local malgré `EURIO_DB_READONLY=1`. |
| **HIGH** | `ml/serving/bench_routes.py:1330-1398` + `ml/scripts/gate_standard_vision.py:101-130` | Deux writers **vivants** hors Direction A : `POST /bench/runs/{id}/crops/exclude` (monté inconditionnellement `server.py:169`, appelé depuis `useBenchApi.ts:421`) fait `UPDATE image_assets SET training_eligible=0…` en SQL brut local ; `_reject` de gate_standard_vision idem (`resolution_status='rejected'` + `review_queue`) — décisions qui ne rejoignent JAMAIS le VPS (friction-log #12, statut `partial`). |
| **HIGH** | `ml/serving/crop_edit.py:609-644` + `local-sync/HANDOFF-next-session.md`, `c4-c8-known-gaps.md:91-98` | `delete_crop` forwarde `DELETE /ingest/assets/{id}` au VPS et lève 502 si échec — or les docs indiquent que le VPS tourne encore en C3 (`12a04e9`), sans cette route : toute suppression de crop depuis Mac/PC échouerait en 502 tant que C4-C8 (`0d506d3`) n'est pas déployé (à re-vérifier : des déploiements ont pu avoir lieu depuis le 2026-07-04). |
| **MEDIUM** | `ml/store/connection.py:75-79` + `ml/serving/server.py:63` | Piège latent : `EURIO_DB_PATH` et `EURIO_DB_READONLY` sont **découplés** — poser le premier sur la réplique sans le second ouvre la réplique en R/W et exécute tout `_bootstrap()` (`connection.py:124-655`, PRAGMA WAL + ALTER en écriture) dessus, en collision avec le `sqlite3_rsync` concurrent du thread autopull. |
| **MEDIUM** | `ml/export/app_export/io.py:36,44-49`, `build_app_core.py:48`, `upload_app_obverse.py:91,117` | **Toute la chaîne export catalogue** (→ projection Supabase → APK) lit `ml/state/eurio.db` en dur : `go-task ml:sync-app` / `ml:upload-app-obverse` lancés sur Mac/PC construisent l'APK depuis un DB legacy périmé, silencieusement (counts plausibles). |
| **MEDIUM** | `ml/scripts/backfill_detections_json.py:113-116`, `backfill_coin_source_status.py:139-145` | Le garde-fou VPS-only (`_vps_only_guard.py`) ne couvre que 3 scripts (backfill_face/denom/quality_score) ; ces deux-là mutent `source_images.detections_json` et `coin_source_status` en UPDATE brut local, hors `/ingest` et hors garde — l'inventaire « les 5 scripts » de `vps-only-migrations.md` est incomplet. |
| **MEDIUM** | `ml/scripts/backfill_dino_predictions.py:85-92` | Appelle `pull_replica()` sans `dest` puis ouvre `Store(…, read_only=False)` sur `eurio.replica.db` — **le même fichier** que le thread autopull (le commentaire « c'est un SCRATCH, pas le cache réplique » est faux) : course concurrente, les prédictions insérées avant `push_run` peuvent être écrasées par le pull suivant. |
| **MEDIUM** | `ml/client/replica.py:88-98,116-128` | Heuristique « tout stderr = échec » fragile : le wrapper ssh ne fixe pas `StrictHostKeyChecking` ni ne filtre stderr — un `Warning: Permanently added…` bénin fait échouer (rc=0 !) un rsync réussi ; le commentaire `:127` (« stats -v sur stdout ») est faux, la commande ne passe pas `-v` ; aucun test ne couvre rc=0 + stderr non vide (`test_replica_rsync.py:73-79`). |
| LOW | `ml/client/replica.py:228-236` + `ml/scripts/replica_autopull.sh` | Double writer sur la réplique côté PC : thread serveur (120 s) + timer systemd (2 min) sans lockfile → runs perdantes en BUSY, bruit journalctl, fallback API 106 Mo inutile. |
| LOW | `ml/client/replica.py:169-187` + `ml/serving/db_routes.py:66-84` | Fallback API : `GET /db/replica/sha` puis `GET /db/replica` en deux requêtes ; si le snapshot (TTL 60 s) se reconstruit entre les deux → mismatch sha spurious « Intégrité réplique » sans corruption réelle. |
| LOW | `ml/client/replica.py:212` | `import time as _time` mort dans `start_autopull_thread` (cosmétique). |

---

## 2. Cause racine commune

Trois défauts qui se renforcent :

1. **Deux flags découplés, aucun posé** — `EURIO_DB_PATH` (quel fichier) et `EURIO_DB_READONLY`
   (quel mode) sont indépendants (`store/connection.py:75-79`), chacun optionnel, et **aucun des
   deux n'est posé dans le devShell**. Le durcissement C5 protège le writer canonique
   (`server_serve.py:75`, `read_only=False` explicite) mais reporte toute la responsabilité sur
   des machines clientes qui n'ont jamais reçu la config.
2. **Chemins hardcodés hors convention** — `resolve_db_path()` (`ml/store/__init__.py:71-82`)
   existe et est honoré par ~20 modules, mais `referential_fix_apply.py`, `sources_aggregator.py`,
   toute la chaîne `ml/export/`, `shared/storage/cascade.py` (autre nom de variable) et ~30 CLI
   `ml/scripts/` (connexions `sqlite3.connect()` brutes) y dérogent.
3. **Audit incomplet des writers** — l'inventaire Direction A (« les 5 scripts » de
   `vps-only-migrations.md`) a raté `backfill_detections_json.py`, `backfill_coin_source_status.py`,
   `gate_standard_vision.py` et la route `POST /bench/runs/{id}/crops/exclude` : des chemins
   d'écriture locale **vivants et atteignables depuis l'UI** qui ne rejoignent jamais le VPS —
   exactement le mode de défaillance (« bulk qui ne voyage pas ») qui a motivé l'abandon de
   l'event-log.

---

## 3. Plan de correction (chunks ordonnés par risque)

> Chaque chunk = 30 min–3 h, livrable et testable indépendamment. Ne pas enchaîner sans « go »
> (cf. doctrine chunk-by-chunk).

### Chunk 0 — Vérifier/déployer C4-C8 sur le VPS (~30 min, ops)

- **Quoi** : confirmer l'état réel du canonique. Si le VPS tourne encore en C3 (`12a04e9`),
  déployer `0d506d3` (route `DELETE /ingest/assets/{id}`) — sinon toute suppression de crop
  depuis Mac/PC (chemin `crop_edit.py:609-644`) échoue en 502.
- **Fichiers** : aucun (déploiement) ; docs `local-sync/HANDOFF-next-session.md` et
  `c4-c8-known-gaps.md` à rafraîchir.
- **Vérification** : `curl` sur le VPS → la route `DELETE /ingest/assets/{id}` répond (pas 404/405) ;
  supprimer un crop de test depuis le front local avec sync activée → 200, et l'asset ne
  « ressuscite » pas au pull-replica suivant.

### Chunk 1 — Poser `EURIO_DB_PATH` + `EURIO_DB_READONLY` dans le devShell, avec couplage de sécurité (~2-3 h)

**C'est le chunk qui ferme le vrai trou.** Deux moitiés indissociables :

- **1a. Config devShell** : poser sur Mac/PC (via `.envrc` / `flake.nix`, selon le profil
  `hostname`) : `EURIO_DB_PATH=<repo>/ml/state/eurio.replica.db` et `EURIO_DB_READONLY=1`.
  Le VPS (profil `vps`) ne pose rien — `server_serve.py` force `read_only=False` et
  `EURIO_DB_PATH=/var/lib/eurio/eurio.db` vient du compose.
- **1b. Couplage de sécurité dans le code** (protège contre l'oubli du flag, cf. finding
  MEDIUM `connection.py:75-79`) : dans `StoreBase.__init__` (ou `resolve_db_readonly()`),
  **refuser au boot** (raise explicite) un chemin résolu dont le nom est `eurio.replica.db`
  ouvert avec `read_only=False` non explicite — ou dériver read-only du nom de fichier réplique.
  Le writer canonique reste immunisé (il passe `read_only=False` explicite ET ne pointe jamais
  la réplique).
- **Fichiers** : `.envrc`, `flake.nix`, `ml/store/connection.py`, `ml/store/__init__.py`
  (+ test dans `ml/tests/`).
- **Vérification** :
  1. Sur Mac : `direnv reload` puis `python -c "from serving.server import CANONICAL_DB; print(CANONICAL_DB)"`
     → affiche `…/eurio.replica.db` ;
  2. démarrer `:8042`, requêter un endpoint de lecture → les données matchent le VPS (comparer
     un count avec `GET` sur eurio-api) ;
  3. tentative d'écriture via un Store sans `read_only=False` → `sqlite3.OperationalError`
     (mode=ro) ;
  4. test unitaire : `Store("…/eurio.replica.db")` avec `EURIO_DB_READONLY` absent → **raise au
     constructeur** (pas de bootstrap silencieux en écriture).

### Chunk 2 — Router les chemins hardcodés serving/export via `resolve_db_path` (~2 h)

- **Quoi** : remplacer les `_DB_PATH` figés par `resolve_db_path(default)` (convention
  `ml/store/__init__.py:71`) :
  - `ml/serving/referential_fix_apply.py:37` (+ vérifier que `apply_fix`, un **writer**, pointe
    bien `/var/lib/eurio/eurio.db` une fois sur le VPS — cf. point de décision D3) ;
  - `ml/serving/sources_aggregator.py:511` ;
  - `ml/export/app_export/io.py:36,44-49`, `ml/export/build_app_core.py:48`,
    `ml/export/upload_app_obverse.py` ;
  - `ml/shared/storage/cascade.py:41` : `EURIO_DB` → `EURIO_DB_PATH` (**fix signalé fait pendant
    l'audit — vérifier sa présence effective au merge**, le working tree audité lisait encore
    `EURIO_DB`).
- **Fichiers** : les 6 ci-dessus + `ml/scripts/cascade_sync.py` (hérite via import).
- **Vérification** : `grep -rn 'state.*eurio\.db' ml/serving ml/export ml/shared` ne retourne
  plus que des **defaults passés à `resolve_db_path`** ; avec `EURIO_DB_PATH` posé (chunk 1),
  le dashboard operations affiche la couverture BCE (plus de `None` silencieux) et
  `go-task ml:sync-app --dry-run`/preview lit la réplique (comparer un count avec le VPS).

### Chunk 3 — Scripts CLI : passer les `sqlite3.connect()` bruts par `resolve_db_path` + respect read-only (~3 h, mécanique)

- **Quoi** : sur les ~30 scripts `ml/scripts/` (dont `wipe_referential.py:399-402`,
  `enqueue_orphan_crops.py:26,43`, `discover_numista_standards.py:279`,
  `recrop_cohort_census.py`) : défaut `--db` = `resolve_db_path(ML_DIR/"state"/"eurio.db")`,
  et **avant toute écriture**, raise si `resolve_db_readonly()` est vrai (message pointant
  le VPS). Idéalement, migrer vers `Store`/`StoreBase` qui honore déjà le flag.
- Cas particulier `backfill_dino_predictions.py:85-92` : passer un `dest` **distinct**
  (tempfile scratch) à `pull_replica()` au lieu de partager `eurio.replica.db` avec l'autopull.
- **Fichiers** : `ml/scripts/*.py` (inventaire par
  `grep -ln 'sqlite3.connect' ml/scripts/*.py`), `ml/scripts/backfill_dino_predictions.py`.
- **Vérification** : avec `EURIO_DB_READONLY=1`, `python -m scripts.wipe_referential --apply --yes`
  (et 2-3 autres writers) **refusent** avec un message clair ; `grep -rn 'sqlite3.connect'
  ml/scripts/ | grep -v resolve_db_path` vide (ou liste blanche justifiée) ;
  `backfill_dino_predictions` tourne avec le serveur `:8042` up sans qu'aucun pull autopull
  n'écrase son scratch (vérifier mtime de `eurio.replica.db` vs le scratch).

### Chunk 4 — Étendre le garde-fou VPS-only + fermer les writers bench/gate (~2-3 h, dépend de D1/D2)

- **Quoi** :
  - ajouter `guard_vps_only()` (ou la route `/ingest` correspondante, selon décision D1) à
    `backfill_detections_json.py:113-116` et `backfill_coin_source_status.py:139-145` ;
    mettre à jour l'inventaire de `vps-only-migrations.md` ;
  - trancher friction-log #12 : `gate_standard_vision.py:101-130` (`_reject`) et
    `bench_routes.py:1330-1398` (`crops/exclude`) doivent soit passer par un endpoint
    canonique VPS (`/ingest/decisions/reject` à créer), soit **refuser explicitement** en mode
    client (si `EURIO_API_URL` configurée / DB read-only) au lieu de réussir silencieusement
    en local.
- **Fichiers** : `ml/scripts/_vps_only_guard.py`, `ml/scripts/backfill_detections_json.py`,
  `ml/scripts/backfill_coin_source_status.py`, `ml/scripts/gate_standard_vision.py`,
  `ml/serving/bench_routes.py` (+ côté VPS si route `/ingest` ajoutée),
  `docs/work-in-progress/local-sync/vps-only-migrations.md`.
- **Vérification** : sur Mac avec chunk 1 en place, `POST /bench/runs/{id}/crops/exclude`
  → soit la décision arrive au VPS (vérifiable par `GET` sur eurio-api), soit 4xx explicite —
  jamais un 200 qui n'écrit qu'en local ; les deux backfills refusent hors VPS.

### Chunk 5 — Durcir le transport rsync (~1-2 h)

- **Quoi** (trois fixes indépendants, même zone) :
  - `replica.py:116-128` : ne plus traiter tout stderr comme échec — filtrer sur motifs d'erreur
    réels OU rc≠0, et poser `-o StrictHostKeyChecking=accept-new` + `UserKnownHostsFile` stable
    dans le wrapper (`:88-98`) ; corriger le commentaire faux `:127` ; ajouter le test
    rc=0 + stderr-warning (`test_replica_rsync.py`) ;
  - flock sur `ml/state/.replica.lock` partagé thread autopull / `replica_autopull.sh`
    (skip si tenu) pour tuer le double-writer PC ;
  - fallback API (`replica.py:169-187`) : faire autorité au header `X-Eurio-DB-Sha256` du
    download (le `/sha` séparé devient best-effort) ou retry une fois sur mismatch ;
  - retirer l'import mort `:212`.
- **Vérification** : `pytest ml/tests/test_replica_rsync.py` (nouveaux cas rc=0/stderr,
  lock tenu → skip) ; sur PC, `journalctl --user -u eurio-replica-pull` sans échecs BUSY
  récurrents après 30 min.

### Chunk 6 — Split local-state : état local légitime vs état partagé (~3 h, dépend de D1)

- **Quoi** : le chantier annoncé (`replica-auto-sync.md:96-98`, MEMORY « split local-state »).
  Une fois D1 tranché, séparer physiquement : la réplique (`eurio.replica.db`, ro, jetable)
  d'un éventuel fichier d'état **local légitime** (caches de calcul, scratch) qui, lui, reste
  inscriptible à un chemin distinct — pour que `EURIO_DB_READONLY=1` global ne casse aucun
  workflow légitime et que plus personne n'ait « besoin » d'écrire `ml/state/eurio.db`.
- **Fichiers** : à cadrer après D1 (probablement `ml/store/__init__.py` : second resolver,
  + les call-sites cache identifiés en D1).
- **Vérification** : sur Mac config chunk 1, une session complète de lab (review lecture,
  bench, suggestions Dino) fonctionne sans jamais toucher `ml/state/eurio.db` legacy
  (`fs_usage`/mtime inchangé) ; le fichier legacy peut être renommé sans rien casser.

---

## 4. Points de décision produit (PO) à trancher

| # | Question | Impact |
|---|---|---|
| **D1** | `source_images.detections_json` et `coin_source_status` sont-ils **canoniques** (→ writes obligatoirement via VPS `/ingest`) ou **cache dérivé recalculable** (→ écriture locale tolérée, hors réplique, documentée comme exemption) ? | Conditionne chunks 4 et 6 : c'est la frontière exacte du split local-state. |
| **D2** | Les writers bench/gate (`crops/exclude`, `gate_standard_vision._reject`) doivent-ils passer par un **endpoint `/ingest` VPS à créer** (décision durable, du travail côté serveur), ou suffit-il de les **bloquer en mode client** en attendant (friction-log #12) ? | Un blocage rend l'exclusion de crops inutilisable depuis le lab tant que la route VPS n'existe pas — arbitrage vitesse vs. complétude. |
| **D3** | `POST /referential/fix-proposals/{id}/apply` (writer) a-t-il vocation à tourner **sur le VPS** (alors le router doit lire `/var/lib/eurio/eurio.db` via env — chunk 2 suffit) ou est-ce un outil **local-only** à démonter de l'image lean (`server_serve.py:174` `_CANDIDATES`) ? | Aujourd'hui il est monté sur le VPS mais opère sur un fichier absent : les deux issues sont simples, mais il faut choisir. |
| **D4** | Le timer systemd PC (2 min) reste-t-il en plus du thread serveur (120 s), ou le conditionne-t-on à l'absence du serveur `:8042` ? | Détermine si le flock (chunk 5) est un patch ou la solution finale. |
| **D5** | La chaîne export catalogue (`ml:sync-app`, APK) doit-elle pouvoir tourner **depuis n'importe quelle machine sur la réplique** (chunk 2 suffit) ou être **restreinte à un host désigné** (garde explicite refusant un chemin non canonique) ? | Un snapshot APK construit sur réplique légèrement en retard est-il acceptable ? |

---

## 5. Effort total estimé et ordre de priorité

| Ordre | Chunk | Effort | Pourquoi cet ordre |
|---|---|---|---|
| 1 | Chunk 0 — déploiement C4-C8 VPS | ~30 min | Débloque une opération de review courante (suppression de crop), zéro code. |
| 2 | Chunk 1 — env vars + couplage sécurité | 2-3 h | **Ferme le trou principal** (réplique inerte) ET pose le filet (réplique jamais R/W) avant que quiconque ne pointe dessus. |
| 3 | Chunk 2 — chemins serving/export | ~2 h | Rend chunk 1 effectif partout (sinon les hardcodes continuent de lire le legacy) ; fixe deux bugs VPS réels (fix-apply fantôme, BCE `None`). |
| 4 | Chunk 3 — scripts CLI | ~3 h | Mécanique mais large surface ; ferme le bypass read-only le plus dangereux (`wipe_referential --apply`). |
| 5 | Chunk 4 — garde-fou + bench/gate | 2-3 h | Nécessite D1/D2 tranchés ; ferme les derniers writers hors-Direction A vivants. |
| 6 | Chunk 5 — transport rsync | 1-2 h | Fiabilité/bruit, pas de perte de données — peut se glisser n'importe quand après chunk 1. |
| 7 | Chunk 6 — split local-state | ~3 h | Dernier : dépend de D1 et de l'expérience accumulée avec les chunks 1-4. |

**Total : ~14-17 h** (2-3 jours de travail effectif), hors décisions PO (D1-D5, ~1 discussion).

Le gain immédiat est concentré sur **Chunk 0 + Chunk 1** (~3 h) : après eux, la réplique
auto-sync livrée en `4c06cfb` sert enfin à quelque chose, et l'invariant « la réplique n'est
jamais écrite localement » est garanti par le code plutôt que par la discipline.
