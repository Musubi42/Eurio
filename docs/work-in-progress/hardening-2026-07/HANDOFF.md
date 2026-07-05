# HANDOFF — Session robustesse & chantier F01 (2026-07-04 → 05)

> **Point d'entrée unique** pour reprendre le travail de robustesse. Lis-le en entier avant d'agir.
>
> **État 2026-07-05 (soir)** : **TOUT le code F01 est committé + poussé (codeberg+github,
> `HEAD=2355eccd` sur `sources-jo-wikipedia`) + DÉPLOYÉ sur le VPS** (eurio-api rebuild, 3 routes
> `/ingest` vérifiées live → 401 non-auth). P0 secrets **traité** (détracké+révoqué, sans réécriture
> d'historique — décision PO). **Il ne reste QUE** : (a) le **split bookkeeping** (à discuter PO,
> cf. §Activation 1a précond. 3) puis (b) le **flip 1a** (patch prêt, non activé). Détail chunk par
> chunk : §1 + fiche `01-…md §6`. Ordre historique des chunks conservé plus bas pour référence.
>
> ⚠️ Le PC (`ssh pc`) est à `4c06cfb0` avec 7 fichiers source non-committés (travail local) + un
> souci d'auth codeberg en session non-interactive : **à synchroniser manuellement** par l'opérateur
> (ne pas forcer — risque de clobber le travail local).

## 0. Carte des documents (ne rien dupliquer)

| Doc | Rôle |
|---|---|
| `README.md` (ce dossier) | Rapport de la review complète : 58 findings + tableau exhaustif + 8 fiches |
| `01-…` à `08-…md` | Fiches de remédiation par thème (F01 = ce chantier sync) |
| **`HANDOFF.md`** (ce fichier) | **Où on en est + ce qui reste + problèmes rencontrés** |

Doctrine (cf. `feedback_handoff_quality`, `project_graphify_doc_hygiene`) : **ne pas fragmenter**.
Mettre à jour CE fichier + la fiche concernée quand un chunk avance ; ne pas créer un nᵉ handoff.

---

## 1. Ce qui a été fait cette session

### 1.1 Review complète de robustesse (livrée)

Review multi-agents (Fable 5 pilote + 76 sous-agents) → **58 findings confirmés** (4 critical,
21 high, 33 medium) + 19 low. Détail : `README.md`. Sortie = 8 fiches F01–F08.

**12 corrections appliquées inline** (working tree, non committées) :

| Fichier | Correction |
|---|---|
| `.envrc copy` (supprimé du tracking) + `.gitignore` | Secrets en clair détrackés + patterns anti-fuite ; `image copy.png` orphelin détracké |
| `ml/serving/crop_recovery_routes.py`, `ml/bench/crop_recovery/common.py` | Path-traversal `/crop-recovery/raw` fermé (chemin absolu restreint à l'arbre `ml/`) |
| `ml/serving/lab_routes.py` | Décorateur `DELETE …/iterations/…` remis sur `delete_iteration` (guard 409 était mort) |
| `ml/review_service/routes_reviewer.py` + `db.py` | Double ROLLBACK supprimé + `writing()` défensif (409 n'est plus masqué en 500) |
| `ml/review_service/auth.py` | Secret HMAC de session : fail-hard si `REVIEW_SESSION_SECRET` absent |
| `ml/export/app_export/run.py` | `except ImportError: pass` → échoue visiblement (builder cassé n'est plus « skipped ») |
| `ml/shared/storage/cascade.py` | `EURIO_DB` → `EURIO_DB_PATH` (+ fallback déprécié) |
| `CLAUDE.md`, `docs/operations/secrets-followup.md`, `docs/work-in-progress/model-b/README.md`, `docs/work-in-progress/collaborative-review/README.md` | 4 doc-drift dangereux corrigés |

### 1.2 Chantier F01 — sync Direction A (chunks 0, 1b, 2, 3 faits)

**Objectif F01** : la réplique auto-sync (`ml/state/eurio.replica.db`) est livrée mais
**personne ne la lit** (`EURIO_DB_PATH` posé nulle part) et ~30 writers hardcodent
`ml/state/eurio.db` legacy ou écrivent en local hors du writer canonique VPS. Fiche complète :
`01-sync-direction-a-cablage.md`.

**Décisions PO tranchées cette session** (gravées, ne pas re-débattre) :
- **D1** : `coin_source_status` → **ajouté au run-batch** (voyage comme le reste). `detections_json`
  reste canonique (voyage déjà via run-batch).
- **D2** : writers bench/gate → **route `/ingest` VPS durable** (pas de blocage interim).
- **D3** : `referential_fix_apply` → **construire une route `/ingest/referential-fix`** (client
  calcule le diff, VPS applique).
- **D5** : export catalogue → **n'importe quelle machine** sur la réplique (latence acceptée).
- **D4** (timer PC vs thread serveur) : non tranché formellement → défaut = garder les deux +
  flock (chunk 5).

**Chunks faits (working tree) :**

| Chunk | Fait | Fichiers | Vérif passée |
|---|---|---|---|
| **0** | VPS déjà à jour (`d0d2fb3`), `DELETE /ingest/assets/{asset_id}` **live** | — (ops) | route confirmée via `docker exec eurio-api python -c "…app.routes…"` |
| **1b** | Filet : `StoreBase.__init__` **refuse** d'ouvrir `eurio.replica.db` en écriture | `ml/store/connection.py` | test : réplique R/W → `RuntimeError` ; RO + db normale OK ; 31 tests store verts |
| **2** | 5 chemins serving/export routés via `resolve_db_path` | `serving/sources_aggregator.py`, `export/app_export/io.py`, `export/sync_to_supabase.py`, `serving/auth.py` (CLI), `shared/storage/cascade.py` (docstring) | no-op sans `EURIO_DB_PATH` confirmé ; routage effectif quand posé |
| **3** | **39 scripts CLI** : 38 routés `resolve_db_path` + 14 gardes `resolve_db_readonly` | `ml/scripts/*.py` (39 fichiers) | `wipe_referential --apply` refuse sous `READONLY=1`, `--dry-run` OK ; suite 1341 pass / 17 rouges pré-existants (zéro régression) |
| **4c** | `coin_source_status` ajouté au run-batch (D1) : entrée `_TABLE_ORDER` (après `source_runs`, idx 9/15) + bloc `export_run` scopé `WHERE last_run_id=?`. **Serveur inchangé** (`ingest_routes.py` : dict ouvert, pas d'allowlist ; `_TABLE_ORDER` EST le gate). | `ml/client/runbatch.py`, `ml/tests/test_runbatch.py` | 12 tests runbatch verts (2 nouveaux : scoping `last_run_id` NULL exclu + round-trip avec dimensions `coins`/`source_registry` seedées) ; suite 1343 pass / 17 rouges pré-existants (zéro régression, `test_model_b_c2_c3::test_ingest_route…` confirmé pré-existant par stash) |
| **5** | Durcissement transport rsync : (a) stderr — filtre le warning host-key bénin (`_significant_stderr`), échoue toujours sur rc≠0 OU stderr significatif (no-op silencieux préservé) ; (b) wrapper ssh — `StrictHostKeyChecking=accept-new` + `UserKnownHostsFile` stable local ; (c) **flock** `state/replica.lock` non-bloquant dans `pull_replica_rsync` → couvre thread-serveur ET timer systemd (skip si tenu, PAS de fallback API) ; (d) fallback API — l'en-tête `X-Eurio-DB-Sha256` devient l'autorité (immunisé au rebuild snapshot TTL) + 1 retry sur transfert corrompu, `/sha` = filet vieux-serveur ; (e) import mort `time` retiré + commentaire faux `-v` corrigé. | `ml/client/replica.py`, `ml/tests/test_replica_rsync.py`, `.gitignore` | 17 tests replica verts (3 nouveaux : stderr bénin toléré, stderr significatif rc=0 rejeté, lock tenu→skip) + `pull_replica` verify/corrupt inchangés ; suite 1346 pass / 17 rouges pré-existants (zéro régression) |
| **4a** | `POST /ingest/crops/exclude` + `POST /ingest/gate/reject` (`ingest_routes.py`, helpers lean `store.crops.apply_exclude_crops` / `store.gate.apply_gate_reject`, scope `ingest:write`). `bench_routes` + `gate_standard_vision._reject` forward via `client.ingest` quand sync active, écrivent local sinon (D2). | `ml/store/{crops,gate}.py`, `ml/serving/{ingest_routes,bench_routes}.py`, `ml/scripts/gate_standard_vision.py`, `ml/client/ingest.py`, `ml/tests/test_ingest_gate_exclude.py` | 9 tests neufs (exclusion, garde run, reject 3-écritures review-first, review close→no-op, scope 403, push no-op) ; suite 1355 pass / 17 pré-existants |
| **4b** | `POST /ingest/referential-fix` (`store.referential_fix` lean : preflight_coins + apply, `ReferentialFixConflict`→409). Client (`referential_fix_apply` refactoré) calcule le diff coins+canonical sur la réplique (ro), FS/fetch image restent client, forward via `client.ingest.push_referential_fix` sinon local (D3). | `ml/store/referential_fix.py`, `ml/serving/{ingest_routes,referential_fix_apply}.py`, `ml/client/ingest.py`, `ml/tests/test_ingest_referential_fix.py`, `test_referential_fix_client.py` | 7 tests neufs (apply/reparent/upsert, 409 divergence, one-shot conflict, scope, diff pur, apply local) ; suite 1362 pass / 17 pré-existants |
| **6** | Split local-state (borné) : `resolve_local_state_db()` + `staging_store()` (`store/__init__.py`). `sources/cli` + `recrop_cohort_census` (work_conn) stagent sur scratch dédié (corrige la course cache autopull, existe DÉJÀ). Garde VPS-only sur `backfill_coin_source_status` + `backfill_detections_json`. **Bookkeeping cohort_jobs/scans : précondition flip documentée** (JOINs canoniques → ATTACH/décision archi). | `ml/store/__init__.py`, `ml/sources/cli.py`, `ml/scripts/{recrop_cohort_census,backfill_coin_source_status,backfill_detections_json}.py`, `.gitignore`, `ml/tests/test_local_state_split.py` | 3 tests neufs (resolver ≠ réplique, staging writable sous READONLY) ; guard refuse sous `READONLY=1` ; suite 1365 pass / 17 pré-existants |
| **1a** | **PRÉPARÉ, NON ACTIVÉ** — patch `flake.nix` (mac+pc) + checklist d'activation (2 préconditions : P0 secrets→push→déploiement VPS ; split bookkeeping) dans fiche `01-…md` §6. | `docs/…/01-sync-direction-a-cablage.md` (§Activation 1a) | patch prêt, non appliqué |

Détails chunk 3 :
- Gardes **scopées derrière `--apply`/`--commit`/`--push`** → les lectures dry-run marchent sur réplique.
- `backfill_dino_predictions` : pull sur un **scratch tempfile dédié** (fin de la course avec l'autopull).
- `recrop_cohort_census` : garde sur la seule branche d'écriture locale, `--push` canonique intact.
- `contradict_rescue` : confirmé **reader**, routé sans garde.

**Comment vérifier l'état des chunks faits** (repro rapide) :
```bash
cd ml
# 1b : la réplique refuse l'écriture
./.venv/bin/python -c "from store import Store; Store('/tmp/eurio.replica.db')"   # → RuntimeError attendu
# 3 : un writer refuse sous read-only, mais pas en dry-run
EURIO_DB_READONLY=1 ./.venv/bin/python -m scripts.wipe_referential --apply --yes  # → SystemExit
EURIO_DB_READONLY=1 ./.venv/bin/python -m scripts.wipe_referential --dry-run       # → OK
# aucun sqlite3.connect hardcodé restant dans les scripts :
grep -rn 'sqlite3.connect' scripts/*.py | grep -iE 'state.*eurio\.db' | grep -v resolve_db_path   # → vide
```

---

## 2. Ce qui reste à faire

### 2.1 Chantier F01 — reste (ordre SÛR, ne pas inverser)

> ⚠️ **Le basculement `EURIO_DB_PATH`+`READONLY=1` (chunk 1a) doit venir EN DERNIER.** Le poser
> avant d'avoir fermé/routé tous les writers convertirait certains en **no-op silencieux** et
> casserait l'ingestion source (elle stage en local avant de pousser). Voir leçon #1.

**Tous les chunks CODE sont FAITS** (4c, 5, 4a, 4b, 6 — committés 2026-07-05, cf. §1.2). Ne reste
que le **flip 1a**, préparé mais **NON activé**, gaté sur 2 préconditions non-agent :

| Ordre | Étape | Quoi | Bloqué par |
|---|---|---|---|
| ~~1-4~~ | ✅ **4c/5/4a/4b/6** | **FAITS** — routes `/ingest` (exclude/gate/referential-fix), run-batch `coin_source_status`, durcissement rsync, staging scratch. Cf. §1.2. | — |
| 1 | **P0 secrets** | Révoquer/rotater clés `.envrc copy` + `git-filter-repo` + **push**. §2.3. | utilisateur |
| 2 | **Déploiement VPS** | Rebuild eurio-api (après push) + vérifier les 3 routes `/ingest` live. | P0 secrets |
| 3 | **Split bookkeeping** | Câbler cohort_jobs/scans read+write sur `eurio.local.db` (blocage archi : JOINs canoniques → ATTACH/décision PO + vérif lab live). | décision PO |
| 4 | **1a — LE FLIP** | Appliquer le patch `flake.nix` (mac+pc). Patch + checklist : fiche `01-…md` §6. | 1+2+3 |

Détail complet, patch prêt-à-appliquer et vérifications : **fiche `01-sync-direction-a-cablage.md` §6 « Activation 1a »**.

### 2.2 Autres fiches (non démarrées)

F02 (Supabase décommission), F03 (Android caméra/bind), F04 (front health-check), F05 (tests :
`wipe_referential` cascade destructeur = CRITICAL toujours ouvert, source_registry seed),
F06 (duplication : contrat app_core 3-langages), F07 (atomicité `lab_routes` 5 handlers),
F08 (docs + garde-fous : règle R7 anti-échec-silencieux proposée). Voir `README.md`.

### 2.3 ✅ P0 secrets — TRAITÉ (2026-07-05)

`.envrc copy` (secrets `service_role`/eBay PROD/Numista) : clés **révoquées** (PO) + fichier
**détracké** (commit `d15cd4a`) + patterns gitignore anti-réintroduction. **Décision PO : PAS de
`git-filter-repo`/force-push** — les clés étant mortes, le fichier reste dans l'ancien historique
(inerte) plutôt que réécrire ~20 refs sur 2 remotes + reset 3 machines. Rien d'autre à faire.

---

## 3. Problèmes rencontrés & leçons (pour ne pas les refaire)

### #1 — Le piège de séquencement : `READONLY=1` en premier CASSE tout

La fiche F01 initiale mettait le flip `READONLY=1` en chunk 1. **C'est faux.** Sous `READONLY=1`
un writer a **3 comportements** selon comment il ouvre la DB :
- via `Store`/`StoreBase` → `OperationalError` **bruyant** (sûr) ;
- via `sqlite3.connect(_db_path())` honorant `EURIO_DB_PATH` → **écrit la réplique en clair**
  (collision rsync, divergence **silencieuse**) ;
- via `sqlite3.connect("state/eurio.db")` hardcodé → **écrit le legacy orphelin** (no-op **silencieux**).

Les deux modes silencieux sont le vrai danger. **Il faut router/fermer tous les writers AVANT de
flipper.** D'où l'ordre corrigé (chunks 2/3/4/6 puis 1a). C'est le même mode de défaillance
(« l'écriture ne voyage pas, mais ça affiche succès ») qui a tué l'event-log — cf.
`project_local_sync_event_log`.

### #2 — Router un writer sans garde le rend PIRE, pas mieux

`referential_fix_apply` écrit aujourd'hui le legacy orphelin. Si on se contente de router son
chemin via `resolve_db_path` (sans route /ingest ni refus), il écrira désormais la **réplique** —
collision avec l'autopull. **Ne jamais router un writer canonique sans lui donner un vrai foyer
(route /ingest) OU un refus bruyant.** C'est pourquoi A1 est laissé intact en attendant 4b.

### #3 — Le VPS lean n'exécute PAS tout le code du repo

Sur le VPS, les routers `referential`, `review_queue`, `coin_assets` sont **skippés** (`No module
named 'PIL'`/`cv2` — l'image lean n'a pas les deps lourdes). Un finding basé sur la lecture du
code (« ce writer est monté sur le VPS ») peut être faux au runtime. **Toujours vérifier le
runtime réel** :
```bash
ssh serverOimNixDontpanic 'docker exec eurio-api python -c "from serving.server_serve import app; [print(sorted(r.methods), r.path) for r in app.routes]"'
```
Conséquence directe : `referential_fix_apply` n'a **aucun** chemin canonique aujourd'hui (le VPS
ne peut pas l'héberger sans cv2/PIL) → chunk 4b est un vrai chantier, pas un simple câblage.

### #4 — Dispatch d'édits mécaniques à des sous-agents : ça marche, mais VÉRIFIER au centre

Les 39 scripts du chunk 3 ont été édités par 3 agents parallèles (sous-ensembles **disjoints**,
convention stricte, worklist avec file:line). Bonne fiabilité (les agents ont même eu le bon
jugement de scoper les gardes derrière `--apply`). **Mais** la confiance vient de la vérif
centralisée post-dispatch : compile all + test comportemental (`READONLY=1` → refus) + grep
anti-hardcode + suite complète. Ne jamais faire confiance au rapport d'un agent sans re-vérifier
sur données réelles (cf. `feedback_handoff_quality`).

### #5 — `zsh` ne fait PAS de word-splitting sur les variables non quotées

`for f in $CHANGED` (avec `$CHANGED` multiligne) itère **une seule fois** avec tout le blob en zsh
(contrairement à bash) → « File name too long », faux « FAIL ». Utiliser `while read f; do … done
< fichier` ou un glob direct (`for f in ml/scripts/*.py`). Le shell de cette session est **zsh**.

### #6 — Un HANDOFF/README auto-déclaré « à jour » qui ne l'est pas est PIRE que rien

Vécu ≥2 fois dans ce repo (le `HANDOFF-next-session.md` de local-sync périmé de 5 commits ;
`model-b/README.md` qui affirmait l'event-log « livré » alors qu'abandonné). **Règle** : tout
chunk qui ferme un point listé ici doit **mettre à jour ce fichier** (ou la fiche) dans la foulée.
Ce handoff est **épinglé au SHA `1594d30`** exprès : si `HEAD` a avancé, re-vérifier avant de
suivre. Garde-fou proposé (fiche F08, règle R7 + skill `handoff-sync`) : pas encore implémenté.

### #7 — `isolation_level=None` (autocommit) : `conn.commit()` est un no-op

Rappel transverse (fiche F07) : les connexions Store sont en autocommit. Un handler qui enchaîne
plusieurs écritures **sans `BEGIN` explicite** n'est pas atomique. Pertinent pour tout chunk qui
touche des writers (4a/4b) : envelopper via `BEGIN`/`COMMIT`/`ROLLBACK` ou `store._writing()`.

---

## 4. Prochaine action recommandée

**Tout le CODE F01 est livré + committé + poussé + déployé** (2026-07-05). P0 secrets traité (§2.3).
Préconditions 1+2 du flip **faites** ; il ne reste QUE la précondition **3 (split bookkeeping)**,
puis le **flip 1a** (patch prêt, non activé — fiche `01-…md §6`).

**Prochaine action** : **discuter le split bookkeeping** (précond. 3, fiche §6) — décision d'archi
(`ATTACH` vs garder ces tables canoniques), car `cohort_jobs`/`cohort_training_scans` sont jointes
au canonique (`store/decisions.py`, `review_queue`). Une fois tranché + câblé + vérifié en lab live,
appliquer le patch flip. **Puis** : re-validation globale de la phase review/refacto (F01→F08).
