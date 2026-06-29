# Topologie de déploiement — qui tourne où

> Doc opératoire. Tranche, une fois pour toutes, **ce qui tourne sur le serveur
> toujours-allumé** vs **ce qui tourne sur le Mac/PC à la demande**, et le
> **rythme quotidien** entre les deux. À lire avant de se demander « ça tourne
> où ». Décidé 2026-06-08.

## Les machines et leurs rôles

| Machine | Profil | Rôle |
|---|---|---|
| **Serveur** (NixOS, VM 6 vCPU / 32 Go / **no swap** / **no GPU**) | flake `vps` | Services **toujours-allumés** : MinIO (stockage canonique) + `review_service` (collaboration amis). |
| **Mac** (M4, MPS) | flake `mac` | **Client de calcul** à la demande : crop, fetch eBay, DINO, embeddings, édition admin. |
| **PC** (1080 Ti, CUDA) | flake `pc` | Calcul lourd GPU : **training** ArcFace, export TFLite, detector. |

**Règle d'or : pas de GPU sur le serveur ⇒ aucune ML lourde dessus.** Sur CPU
c'est 30-300× plus lent, et sans swap un batch DINO ou un training peut OOM-kill
la VM.

## Ce qui tourne où

| Charge | Où | Pourquoi |
|---|---|---|
| MinIO (eurio.db canonique + buckets images) | **Serveur** | Durable, toujours dispo |
| `review_service` + front reviewer + page `/admin` régie | **Serveur** | Les amis reviewent sans que le Mac soit allumé |
| Fetch eBay / BCE / JO (HTTP + parsing) | **Mac** | Réseau ; bottleneck = review humaine, pas la machine |
| Crop refine (YOLO11-nano + Hough) | **Mac** | CPU serveur = 2-5 min/batch + risque OOM |
| DINO anchors / predictions / confusion-map | **Mac** | ~30 min CPU vs 1-2 min GPU |
| Training ArcFace + export TFLite | **PC** (GPU) | GPU obligatoire |
| Console admin (arbitrage, crop edits, sets, dashboards) | **Mac** (local) | Outil perso ; reste local jusqu'au Modèle B |

## Le rythme quotidien (Modèle B — ACTIF depuis 2026-06-29, cutover C8)

> **Cutover effectué le 2026-06-29.** Le canonique est désormais le **eurio.db du
> VPS** (`/var/lib/eurio/eurio.db`), writer unique derrière `eurio-api`
> (`/ingest/run` + écritures review). Le Modèle A ci-dessous est **superseded**
> (conservé comme référence + procédure de secours).

```
┌─ VPS : writer canonique unique (toujours allumé) ──────────────┐
│ eurio-api  →  /var/lib/eurio/eurio.db  (canonique SQLite)      │
│   • /ingest/run : applique les run-batches poussés (Model B)   │
│   • écritures review (decide/skip/reject/restore, TC2)         │
│   • [CIBLE R2] GET /db/replica (+ sha) : sert un snapshot      │
│     cohérent → le compute tire SA réplique depuis le VPS        │
└────────────────────────────────────────────────────────────────┘

┌─ Mac/PC : CALCUL (plus writer du canonique) ───────────────────┐
│ pull-replica (← VPS)         # copie de travail locale          │
│   … scrape / crop / DINO / training EN LOCAL sur la réplique …  │
│ <pipeline> --push            # un seul POST au VPS (/ingest/run)│
└────────────────────────────────────────────────────────────────┘
```

**Conséquence :** le canonique survit au Mac éteint. Le compute lit une réplique
locale, fait son travail multi-étapes **sans aller-retour**, et pousse le run fini ;
il n'écrit jamais le canonique en direct. Multi-PC sans conflit (l'API arbitre, pas
de lease).

> **⚠️ Transitoire à remplacer (cf. `model-b/README.md` §R2)** : aujourd'hui la
> réplique passe encore par MinIO — `serving/canonical_sync.py` pousse le canonique
> VPS → bucket `eurio-db`, et `pull_replica` lit MinIO (+ un lock VPS qui bloque un
> `db:acquire` Model A). C'est **le dernier reste Model A**. Cible : un endpoint
> `GET /db/replica` côté VPS, **retrait** de `canonical_sync→MinIO` + du lease
> (`store/lease.py`). **MinIO ne doit garder que les images.**

**Durabilité** : `eurio-backup.sh` sauvegarde les buckets MinIO → pCloud (couvre les
images ; après R2, prévoir un backup direct du eurio.db VPS → pCloud).

**Secours (VPS down)** : tant que le transitoire MinIO existe, le dernier snapshot
DB est dans le bucket `eurio-db`. Après R2, le secours = restaurer le backup pCloud
du eurio.db. Cf. `docs/work-in-progress/model-b/README.md`.

---

## Le rythme quotidien (Modèle A — SUPERSEDED, référence + secours)

Le **eurio.db canonique vivait dans MinIO** (bucket `eurio-db`, lease atomique —
cf. lease MinIO chunk 6). Le Mac/PC en était le **seul writer**, sérialisé par le
lease. Le serveur ne touchait pas à eurio.db (il servait MinIO + review).

```
┌─ Mac/PC : session de travail ──────────────────────────────┐
│ go-task ml:db:acquire     # pull eurio.db + pose le lock    │
│   … crop / fetch / DINO / édition admin / training (PC) …   │
│ go-task ml:db:release     # checkpoint + push + retire lock │
└────────────────────────────────────────────────────────────┘

┌─ Pont vers la collaboration review (Mac, lease détenu) ────┐
│ go-task ml:review:publish    # pousse les items à reviewer  │
│   … les amis reviewent sur eurio-review.musubi.dev …        │
│ go-task ml:review:reconcile  # tire leurs décisions         │
└────────────────────────────────────────────────────────────┘

┌─ Serveur : toujours allumé, zéro intervention ─────────────┐
│ MinIO  +  review_service (+ page /admin régie)              │
└────────────────────────────────────────────────────────────┘
```

**Conséquence pratique :** une seule maison pour eurio.db (MinIO), un seul
writer à la fois (lease). Plus de « quelle copie est à jour ? ». Le serveur
porte la seule chose qui doit survivre au Mac éteint : la collaboration.

### Finaliser le déploiement review (one-shot, en SSH)

```bash
cd /opt/eurio && git pull
cd /opt/eurio/infra/review && docker compose up -d --build
# créer mon reviewer perso (ou via la page /admin une fois le service up) :
docker compose exec review python -m review_service.manage \
  add-reviewer --token raph --name Raphael
```

Page régie : `https://eurio-review.musubi.dev/admin` (coller le
`REVIEW_ADMIN_TOKEN` au premier chargement).

## Le cap — Modèle B (serveur = canonique vivant)

Aujourd'hui l'édition admin (arbitrage, crop edits, CRUD sets) **écrit** dans
eurio.db et se fait donc côté Mac (qui détient le lease). Le Modèle B déplace le
**eurio.db vivant sur le serveur** : toutes les lectures *et écritures*
admin/review passent par son API ; le Mac/PC redevient un **pur client de
calcul** qui réconcilie ses résultats vers le serveur (même pattern
publish/reconcile que `review_service`). MinIO redevient store d'images +
backup.

**C1–C4 codés** (cf. `docs/work-in-progress/model-b/GAP-ANALYSIS.md`) — migration
incrémentale, pas big-bang. **Reste : C4-deploy + C5 + C6+.**

1. **Gating des routers** — approche **fichier parallèle** (acté, non une var
   `EURIO_SERVER_ROLE`) : `ml/serving/server_serve.py` (lean, sans torch/cv2, monte
   best-effort via `try/except`) coexiste avec `ml/serving/server.py` (full, Mac/PC).
   Garde-fou anti-OOM sur la VM no-swap. (Sous-gaps restants : resserrer l'`except`,
   smoke-test routers — cf. GAP-ANALYSIS §3.1 / chunk H3.)
2. ✅ **LIVRÉ (code)** — `infra/eurio-api/` : Dockerfile + `docker-compose.yml`
   (Traefik `eurio-api.musubi.dev`, OIDC+PAT, SOPS). **Reste : C4-deploy** (lancer
   le conteneur sur le VPS — cf. `docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md`).
3. **Read-sync eurio.db** — le serveur tire la dernière version depuis MinIO
   (sans lease, lecture seule) après chaque `release` du Mac.
4. **Chemin d'écriture réconcilié** — les mutations éditoriales lourdes faites
   sur le Mac (recrop, ré-embeddings) remontent vers le serveur-canonique par
   un reconcile, comme les décisions review.
5. **Admin web configurable** — `VITE_ML_API` au lieu du `http://127.0.0.1:8042`
   hardcodé, pointé sur `eurio-api.musubi.dev`.

À déclencher chunk par chunk selon le plan GAP-ANALYSIS §5 ; C6 est le verrou
central (câblage compute) et conditionne le cutover C8.
