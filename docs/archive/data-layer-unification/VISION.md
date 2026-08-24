# Vision — data-layer unification Eurio

> Décidée le 2026-06-19, raffinée le 2026-06-20. Ce doc capture le **pourquoi**
> et la **cible architecturale**. Lire avant d'écrire du code.

## 1. Le problème

Avant la refonte 2026-06 :

- 3 lieux de vérité data : Supabase (Postgres), `eurio.db` SQLite local sur
  Mac/PC (leasé via MinIO), `eurio.db` VPS (auth seulement)
- Frontend studio-local tape **trois backends** différents :
  - Supabase directement (anon key + RLS) pour 4-6 tables éditoriales
  - ML API local `localhost:8042` pour le reste (depuis le browser)
  - eurio-api `eurio-admin.musubi.dev` pour rien (auth seulement)
- Mécanisme de lease MinIO `eurio.db` pour échanger l'état canonique entre
  Mac et PC — "hack dégueu" assumé
- Schémas désynchronisés entre Supabase ("app-facing v2" pour l'Android)
  et SQLite (schéma éditorial complet)
- Mix de frontends qui n'a aucun sens : tu lances un scrape qui écrit
  localement, tu pushes via lease, l'autre machine pull, etc.

## 2. La cible

**Une seule porte d'entrée data : `eurio-api.musubi.dev`.**

```
┌──────────────────────────────────────────────────────────────────────┐
│  VPS                                                                 │
│  ────────────────────                                                │
│  eurio-api.musubi.dev   ← FastAPI : seule porte d'entrée data        │
│        │                                                             │
│        └─► eurio.db (SQLite WAL, /opt/eurio/infra/eurio-api/data/)   │
│            = 71 tables (65 éditoriales + 6 auth)                     │
│            = source de vérité unique                                 │
│                                                                      │
│  MinIO (eurio-s3.musubi.dev)                                         │
│  ──────────────────                                                  │
│  • Buckets enrichment-crops, enrichment-raws, numista-canonical      │
│    = assets uniquement (binaries images)                             │
│  • Bucket eurio-db → KILLED (Phase 5)                                │
│                                                                      │
│  Supabase (read-only mirror Android)                                 │
│  ──────────────────────────                                          │
│  • Sync descendant SQLite → Supabase (cron, schéma app-facing v2)    │
│  • App Android lit Supabase directement (offline-first + fallback)   │
│  • studio-local + admin-vps NE TAPENT JAMAIS Supabase                │
└──────────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ HTTP (Bearer PAT ou cookie OIDC)
              ┌───────────────────┼───────────────────┐
              │                   │                   │
       studio-local         admin-vps           ML compute local
       (Mac/PC :5173)       (eurio-admin)       (Mac/PC :8042)
       Bearer PAT           cookie OIDC         = client HTTP de
       lit/écrit            consult + auth      eurio-api (Phase 6).
       l'API maison         mobile-friendly     Heavy compute (crops,
                                                 scrape, training)
                                                 push résultats par
                                                 API.
```

## 3. Trois principes non-négociables

### P1. `eurio-api` est la **seule** porte d'entrée data

- Frontend (studio-local, admin-vps) ne fait **jamais** de SQL direct
- ML compute local **devient** un client HTTP de eurio-api (Phase 6)
- Supabase n'est plus un client pour le code-base interne — c'est un
  **mirror downstream** alimenté par sync depuis eurio.db SQLite
- L'app Android continue à lire Supabase comme aujourd'hui (mirror)

### P2. Heavy compute = local, data = serveur

- Crops (yolo, dino, opencv) = local sur Mac/PC, avec GPU/CPU disponible
- Scrape eBay/Numista/Wikipedia = local (latence, IP, quotas)
- Training = local (1080 Ti sur PC, batch GPU)
- Mais **toute écriture data passe par HTTP vers eurio-api** — pas de
  base locale, pas de lease, pas de sync à la main

### P3. Pas de hacks, architecture propre

- Endpoints structurés en **modèle / repository / service / router**
  (cf. `ARCHITECTURE.md`)
- Migrations SQL versionnées (`ml/serving/migrations/NNNN_*.sql`)
- Auth uniforme (`require_principal` partout)
- Tests smoke par endpoint
- Erreurs propres (HTTPException avec detail explicite)
- Pas de "fat controllers" : SQL ne vit pas dans les routes

## 4. Conséquences observables

Quand cette vision sera entièrement implémentée (Phase 6 incluse) :

- Mon Mac peut planter, j'achète un nouveau ordi, je clone, je colle un
  PAT, je relance — **rien n'est perdu**, tout est sur VPS
- Mon PC fait du training pendant que mon Mac fait des reviews — chacun
  utilise eurio-api, **aucun conflit** (SQLite WAL gère le concurrent)
- Je suis sur mon tel, je veux check une stat → admin-vps me la donne en
  3 secondes, en consultant la même base
- Plus de "ah faut que j'fasse release avant de switcher de machine"
- L'app Android continue de marcher comme aujourd'hui (mirror Supabase)

## 5. Ce qu'on **ne** fait **pas** dans cette refonte

- Pas de refonte du schéma SQLite — il est déjà correct (validé par
  l'usage), on ne touche que l'auth + 2 tables orphelines (Phase 1 done)
- Pas de portage de l'app Android (continue à taper Supabase)
- Pas de remplacement de SQLite par Postgres serveur — SQLite WAL nous
  suffit pour 1-3 dev concurrents et nous évite un service
- Pas de migration vers un ORM lourd (SQLAlchemy etc.) — sqlite3 stdlib
  + repository pattern dataclass-based est suffisant
- Pas de réécriture du code ML compute Python — il reste tel qu'il est,
  juste son persistence layer devient client HTTP (Phase 6)

## 6. Lectures suivantes

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — pattern layered backend, conventions de code
- [`ROADMAP.md`](./ROADMAP.md) — phases d'exécution avec statut
- [`DECISIONS.md`](./DECISIONS.md) — log chronologique des décisions
- [`HANDOFF-NEXT-SESSION.md`](./HANDOFF-NEXT-SESSION.md) — par où reprendre maintenant
