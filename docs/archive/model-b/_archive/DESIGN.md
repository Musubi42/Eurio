> 📜 **HISTORIQUE.** Design d'origine. État courant + cible + roadmap : [`README.md`](./README.md).

# Modèle B — eurio.db serveur-canonique derrière l'API (design v2)

> Statut : **design verrouillé, all-in, non démarré**. Décidé 2026-06-16.
> Remplace **définitivement** le single-file-lease (Modèle A,
> `docs/operations/deployment-topology.md`) — pas de dual-mode, pas de fallback,
> pas de coexistence « ancien + nouveau ». On construit la cible et on bascule.
> Doctrine : R0 (réduit la dette), chunks 30 min–3 h **livrés + audités** avant
> d'enchaîner ([[feedback_chunk_audit_flow]]), vérifier sur le code pas les docs.

## Contexte & problème

Modèle A : `eurio.db` est **un fichier unique**, canonique dans MinIO (`eurio-db`),
protégé par un **lease mutex** (`ml/store/lease.py`). Un seul writer à la fois,
séquentiel Mac→PC→Mac. Impossible de reviewer sur le Mac pendant que le PC entraîne ;
le lease est un verrou global sur tout le fichier, sans voie lecteur ni gestion de
conflit sémantique. Ce n'est pas un défaut de design — c'était l'intérim assumé avant
le Modèle B (déjà cible dans `deployment-topology.md §73`).

## Décisions verrouillées

1. **SQLite, une seule DB.** Doctrine [[feedback_sqlite_only_doctrine]] intacte. Ce qui
   change : **où vit le fichier** (VPS) et **qui l'écrit** (un seul process).
2. **Writer unique = le FastAPI `ml/serving/server.py` sur le VPS.** SQLite WAL = N
   lecteurs + 1 writer ; le seul writer étant l'API, les écritures se sérialisent dans
   ce process. Suffisant à l'échelle (1 dev + amis reviewers + 2 machines de calcul).
3. **Interactif = thin-client direct serveur.** Review/édition/dashboards : la console
   admin (déjà web→API) tape l'API du VPS. 1 aller-retour par page/décision (~dizaines
   de ms) vs lecture humaine de plusieurs secondes → ressenti quasi-identique. Simple,
   éprouvé, read-your-writes gratuit. **Pas de réplique locale pour l'interactif.**
4. **Calcul CV/ML = 100 % Mac/PC**, jamais sur le VPS. Mesuré (`deployment-topology.md`) :
   crop YOLO+Hough 2-5 min/batch + OOM, DINO ~30 min CPU, training GPU-only. Le VPS est
   Skylake (6ᵉ gén, no AVX-512, no-swap 32 Go) → CV/ML y est 30-300× plus lent + risque
   OOM. Le compute lit une **réplique read-only locale** (vitesse dedup/dataset préservée)
   et pousse ses résultats par **run-batch**. La réplique n'est PAS une demi-mesure :
   c'est le seul moyen d'éviter les round-trips fatals sur 50K-300K lignes/run.
5. **Auth = bearer token app-level** (dépendance FastAPI, table de tokens type
   `review_service`, révocable, mini-panel plus tard). **Pas d'IP-whitelist** (IP
   changeante). Traefik = TLS + routage seulement.
6. **PAS** libSQL (client Python immature, ADR D4), **PAS** Postgres (réintroduirait
   Supabase admin, hors échelle), **PAS** de split physique data/training (casse les FK).

### Invariant central

> **Exactement un process écrit le fichier canonique : l'API serveur (VPS).**
> L'interactif tape l'API. Le calcul lit une réplique locale et POST un run-batch.

## Les trois classes d'accès (cartographie réelle)

| Classe | Exemples (routers/modules) | Volume | Stratégie |
|---|---|---|---|
| **A. Interactif léger** | review (`review_queue_routes`), arbitrage (`peer_arbitration_routes`), sets, coin edits (`coins_routes`/`coins_review_routes`), crop edit (`coin_assets_routes`), cohort/iteration/recipe CRUD (`lab_routes`, `augmentation_routes`) | 1–500 lignes/action | **API serveur directe** (thin-client). La console admin l'est déjà. |
| **B. Calcul lourd scopé run** | scraping (`sources/_base/steps/*`), recrop (`vision/recrop_zero`), DINO (`scripts/backfill_dino_predictions`), métadonnées training (`training_runner`) | **50K-300K lignes/run** | **run-batch reconcile** : calcul local sur réplique → `export_run(run_id)` → `POST /ingest/run` (1 tx, idempotent). |
| **C. Lectures de calcul** | dataset prepare, training reads, dedup scraping | gros | **réplique read-only** locale (pull). `prepare_dataset`+`train_embedder` déjà read-only (vérifié). |

## Architecture cible

```
                    ┌───────────────────────────────────────────┐
   amis reviewers ──┤  VPS (always-on, Skylake CPU, no GPU)      │
   admin web    ────┤   • review_service (review.db)  [existant] │
   (VITE_ML_API →   │   • eurio-api = ml/serving/server.py       │
    eurio-api…)     │       WRITER UNIQUE du canonique           │
                    │       eurio.db (WAL) + bearer auth + Traefik│
                    │   • MinIO (images + backup eurio.db)        │
                    └───────────────┬───────────────────────────┘
                       interactif   │ HTTP (bearer)   run-batch + pull réplique
        ┌───────────────────────────┴───────────────────────────┐
   Mac (M4, calcul)                                   PC (1080Ti, training)
   • édition/review → API directe                     • prepare+train (lit réplique)
   • scrape/crop/dino LOCAL (lit réplique)            • POST run-batch (métriques)
   • POST run-batch → /ingest/run                     • POST start/finish iteration
```

## Structure du repo (le seam client/serveur)

Aujourd'hui : plat par domaine ([[project_refacto_ml]]), tout le compute fait
`Store(fichier local)` en direct. Cible : **une seule couture nette**.

```
ml/
├── serving/   ─┐  LE SERVEUR (déployé VPS) : FastAPI writer unique
├── store/      ├─ accès canonique + schéma
├── state/     ─┘  (Store au fichier canonique n'existe QUE là)
│
├── client/    ←─ NOUVEAU PACKAGE (la porte workstation→serveur) :
│                 • replica.py  : pull réplique read-only (snapshot)
│                 • runbatch.py : export_run(run_id) + push → /ingest/run
│                 • auth.py     : bearer token
│                 • http.py     : client HTTP (base URL, retries, chunking)
│
└── sources/ vision/ training/ referential/ + scripts dino
              ←─ COMPUTE (Mac/PC) = CLIENTS : lisent la réplique,
                 poussent par run-batch via ml/client/. Ne touchent
                 JAMAIS le canonique en direct.

infra/eurio-api/  ←─ NOUVEAU : docker + Traefik (à la infra/review)
```

Règle structurelle : **le compute ne touche plus jamais le canonique en direct.**

## Pattern reconcile (généralisé depuis `review_service`)

Réutilise les invariants prouvés (`ml/review/publish_cli.py` + `review_service/routes_admin.py`) :
idempotence par clé naturelle (`ON CONFLICT DO UPDATE`), garde anti-écrasement, auth
header, batch+chunking, transaction `BEGIN IMMEDIATE`. Pour la classe B la clé est
`run_id` + clés naturelles des tables.

```
export_run(run_id) → { run_id, tables: { source_images:[…], image_assets:[…], … } }
POST /ingest/run (bearer) → applique en 1 tx : UPSERT par clé naturelle,
                            marque le run 'applied' (re-POST = no-op idempotent)
```

## Plan chunké (all-in, incrémental — pas de dual-mode)

> « All-in » = on vise la cible sans filet ancien. « Chunké » = on livre par morceaux
> auditables (pas un big-bang non testé). Le lease reste **physiquement présent jusqu'au
> cutover (Phase 3)** uniquement comme sécurité de données, pas comme mode de
> fonctionnement.

### Phase 1 — Fondation in-repo (testable, zéro infra)
- **C1 — Contrat run-batch + `export_run`/`ingest_run`** (`ml/client/runbatch.py` +
  serveur) : schéma de run-tracking (table `ingested_runs` pour l'idempotence), export
  des lignes d'un run sur les tables lourdes, apply atomique UPSERT. **Tests parité**
  (run exporté d'une DB → ingéré dans une DB vierge → identique) **+ idempotence**
  (2× ingest = no-op). ← premier livrable.
- **C2 — Auth bearer** : dépendance FastAPI `require_token`, table `api_tokens`, mini
  CLI `add-token`/`revoke`. No-op en local si pas de token configuré ; requis sinon.
- **C3 — `ml/client/` SDK** : `http.py` (base URL `EURIO_API_URL` + bearer), `replica.py`
  (pull read-only de `eurio.db`), wrapper `push_run`.

### Phase 2 — Le serveur devient le canonique
- **C4 — Dockeriser eurio-api** (`infra/eurio-api/`, Traefik `eurio-api.musubi.dev`,
  secrets SOPS). Boot : pull `eurio.db` depuis MinIO.
- **C5 — `VITE_ML_API` configurable** (web) → console admin sur le serveur. La classe A
  écrit server-side (les handlers écrivent déjà ; déplacer le process suffit).

### Phase 3 — Migrer le calcul vers réplique + run-batch, puis cutover
- **C6 — Câbler les runners compute** (scraping/crop/dino) : lire la réplique → run local
  → `push_run`. Un domaine par chunk (parité vérifiée vs Modèle A).
- **C7 — Orchestration server-side** : `POST /lab/iterations` avec le garde-fou conflit
  (cf. ci-dessous). Training PC lit réplique + réconcilie métriques/statut.
- **C8 — Cutover** : défaut = serveur-canonique ; lease → secours/emergency uniquement ;
  backup périodique `eurio.db` serveur → MinIO versionné ; mettre à jour
  `deployment-topology.md` (A→B).

## Gestion de conflit — « un training tourne déjà »

Logique applicative dans `POST /lab/iterations` (writer unique) : si une itération
`status='training'` existe pour la cohorte → `409 { running_on, since, hint:"crée une
nouvelle itération" }`. Garde-fou déjà existant côté lab (commit `4644b29`), monté
server-side. Le Mac reviewe en parallèle (classe A via API, zéro contention).

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| SQLite single-writer sature | Writer unique = API ; charge réelle faible. Porte de sortie Postgres si un jour nécessaire (pas maintenant). |
| Réplique périmée (dedup scraping) | UPSERT par clé naturelle à l'ingest (item_id+URL) ; re-pull en début de session. |
| Latence HTTP sur lectures de calcul | Lectures lourdes via réplique locale, pas HTTP. |
| Perte réseau pendant un run | Run local (réplique + scratch) ; batch rejouable (idempotent run_id). |
| Cutover irréversible | Backup MinIO avant C8 ; lease gardé comme secours jusque-là ; cutover fait **avec** l'humain, pas en autonome. |
| Interactif lent si VPS lointain | Mesurer le RTT (dé-risque en 2 min) ; thin-client OK à hauteur humaine. |

## Ce qu'on NE fait PAS

- ❌ Dual-mode `serve|full` permanent / garder l'ancien modèle en parallèle.
- ❌ libSQL/Turso (ADR D4) · Postgres/Supabase admin · deux fichiers DB.
- ❌ CV/ML sur le VPS (Skylake CPU/OOM).
- ❌ Reconcile per-item pour le scraping (→ batch par run).
- ❌ Big-bang non testé : chaque chunk est livrable + audité seul.

## Vérification (par phase)

- **C1** : parité export→ingest (DB vierge identique à la source) + double-ingest no-op.
- **C5** : console admin sur `eurio-api.musubi.dev` lit/écrit (review/sets/arbitrage) ;
  2 navigateurs concurrents OK.
- **C6** : un run scrapé localement + `push_run` → comptages identiques à un run Modèle A.
- **C7** : PC entraîne (réplique + réconcile) pendant que le Mac reviewe ; 2ᵉ itération
  même cohorte → `409`.
- **C8** : cycle complet (scrape Mac → review amis → iteration PC) sans `acquire/release`.

## Références code (preuves)

- Lease : `ml/store/lease.py` ; ADR D4 : `docs/refacto-ml/adr.md:64`.
- Reconcile template : `ml/review/publish_cli.py` (publish:151, reconcile:193) ;
  `ml/review_service/routes_admin.py` (publish:40, ack:107).
- Routers + classes : `ml/serving/server.py:95-149`.
- Store seam : `ml/store/connection.py:69` (WAL, row_factory, UDFs).
- Topologie : `docs/operations/deployment-topology.md` (A §32, B §73).
