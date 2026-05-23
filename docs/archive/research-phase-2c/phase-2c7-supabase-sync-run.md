# Phase 2C.7 — Run report sync Supabase

> Push du référentiel canonique JSON vers Supabase + mise en place du schema cible.
> Date : 2026-04-13.
> Doc parent : [`phase-2c-referential.md`](../phases/phase-2c-referential.md) §2C.7, [`data-referential-architecture.md`](./data-referential-architecture.md) §7.3, [`ARCHITECTURE.md`](../ARCHITECTURE.md) §3.

---

## TL;DR

Le référentiel **vit maintenant dans Supabase** avec le schema canonique. 2 938 pièces, 3 695 observations, 197 items en queue, 1 771 décisions de matching, tout auditable via SQL. RLS configurée (lecture publique, écriture owner-only sur `user_collections`). `sync_to_supabase.py` est idempotent — re-runnable sans drift. Zéro warning sur les advisors Supabase.

| Table | Rows | Description |
|---|---|---|
| `coins` | **2 938** | Référentiel canonique (identity + images + cross_refs + sources_used) |
| `source_observations` | **3 695** | Variants lmdlp, prix MDP, marché eBay, mintage Wikipedia/BCE |
| `review_queue` | **197** | Escalades Stage 5 (121 groupes uniques) |
| `matching_decisions` | **1 771** | Audit trail de toutes les décisions lmdlp / mdp / ebay / bce |
| `coin_embeddings` | 0 | Prêt pour Phase 2B (ArcFace export) |
| `user_collections` | 0 | Prêt pour Phase 3 (coffre) |

---

## 1. État initial : un schema legacy à remplacer

Le projet Supabase avait déjà 3 migrations du 9 avril (`initial_schema`, `add_rls_policies`, `add_unique_coin_id_on_embeddings`) qui créaient un schema **incompatible** avec l'architecture canonique adoptée le 13 avril :

| Legacy v0 | Problème |
|---|---|
| `coins(id UUID PK, numista_id INT UNIQUE, ...)` | PK UUID aléatoire au lieu d'`eurio_id TEXT` reconstructible |
| Colonnes plates (country, year, mintage, rarity) | Pas de 4-layer identity/cross_refs/observations/provenance |
| `price_history(coin_id UUID, source, ...)` | Mono-source, pas de namespace par source |
| Pas de `review_queue`, pas de `matching_decisions` | Pas d'audit trail pour la pipeline de matching |

**Décision** (validée par l'utilisateur) : drop+rebuild. Les 10 rows de test étaient disposables et la Phase 2B n'est pas encore branchée, donc zéro risque de casser du code Kotlin en production.

---

## 2. Migrations appliquées

### `drop_legacy_v0_schema`
```sql
drop table if exists public.price_history cascade;
drop table if exists public.user_collections cascade;
drop table if exists public.coin_embeddings cascade;
drop table if exists public.coins cascade;
```

### `create_canonical_referential_schema` (~170 lignes SQL)

6 tables :
- **`coins`** — identity immutable + images + cross_refs + sources_used + provenance flags. PK `eurio_id TEXT`. 4 index : `(country, year)`, `face_value`, `is_commemorative`, `needs_review` partial.
- **`source_observations`** — une row par `(eurio_id, source, source_native_id, observation_type)`. Payload JSONB. `observation_type` ∈ `{variant, issue_price, market_stats, mintage, image}`. Index sur `eurio_id`, sur `(source, sampled_at desc)`, sur `observation_type`.
- **`matching_decisions`** — audit trail, une row par décision du matcher. Colonnes `method`, `confidence`, `runner_up`.
- **`review_queue`** — escalades Stage 5, avec `resolved`, `resolution` JSONB. Unique constraint `(source, source_native_id, reason)` pour l'idempotence.
- **`coin_embeddings`** — PK `eurio_id`, embedding `real[]`, model_version. Sera populé par Phase 2B.
- **`user_collections`** — PK `id bigserial`, FK sur `user_id` (auth.users) et `eurio_id` (coins), unique `(user_id, eurio_id)`.

**RLS activée** sur les 6 tables. Politiques :
- `coins`, `source_observations`, `matching_decisions`, `review_queue`, `coin_embeddings` : SELECT autorisé `anon, authenticated` (référentiel = données publiques read-only)
- `user_collections` : SELECT/INSERT/UPDATE/DELETE réservés au propriétaire via `(select auth.uid()) = user_id`

### `fix_source_observations_null_distinct`

Bug rencontré lors du premier sync : 3 695 rows attendues, 6 825 en base après 2 runs. Cause : **Postgres traite NULL comme distinct par défaut dans les unique constraints**, donc les upserts avec `source_native_id = NULL` (Wikipedia mintage, eBay market_stats, lmdlp_mintage) créaient un nouveau row à chaque run.

Fix : `NULLS NOT DISTINCT` sur la contrainte unique (Postgres 15+).
```sql
alter table public.source_observations
  drop constraint source_observations_unique;
alter table public.source_observations
  add constraint source_observations_unique
  unique nulls not distinct (eurio_id, source, source_native_id, observation_type);
```
Précédé d'un `delete ... where row_number > 1` pour nettoyer les doublons existants avant que la contrainte puisse être reconstruite.

### `perf_rls_initplan_and_fk_index`

Après le premier set d'advisors :
1. **`user_collections.eurio_id`** : FK sans covering index → `create index idx_uc_eurio on public.user_collections(eurio_id)`.
2. **RLS `auth.uid()` re-évalué par row** sur les 4 policies `user_collections_*_own`. Fix : wrap en `(select auth.uid())` pour que le planner le traite comme subquery scalaire.

---

## 3. Bug découvert et corrigé pendant le sync : les images BCE étaient wipées

Quand j'ai query `jsonb_array_length(images) > 0` sur `coins`, résultat **0**. Les 419 images BCE scrappées en Phase 2C.5 n'étaient plus dans le JSON du référentiel.

Investigation : les 3 scripts `bootstrap_*.py` ont un merge pattern idempotent qui, lors d'un re-run, **ne préserve pas `entry["images"]` ni `identity.design_description`** :

```python
# Avant
entry["provenance"]["first_seen"] = surviving[eid]["provenance"]["first_seen"]
for k, v in surviving[eid].get("observations", {}).items():
    if k not in entry["observations"]:
        entry["observations"][k] = v
for k, v in surviving[eid].get("cross_refs", {}).items():
    if k not in entry["cross_refs"]:
        entry["cross_refs"][k] = v
```

Seules `observations` et `cross_refs` étaient préservées. `images`, `design_description`, `sources_used` étaient silencieusement écrasés par les valeurs vides de `make_entry()`.

**Fix** appliqué aux 3 scripts (`bootstrap_referential.py`, `bootstrap_circulation.py`, `bootstrap_circulation_de.py`) :
```python
# Après
if surviving[eid].get("images"):
    entry["images"] = surviving[eid]["images"]
if surviving[eid]["identity"].get("design_description"):
    entry["identity"]["design_description"] = surviving[eid]["identity"]["design_description"]
for s in surviving[eid]["provenance"].get("sources_used", []):
    if s not in entry["provenance"]["sources_used"]:
        entry["provenance"]["sources_used"].append(s)
# ... observations / cross_refs merge as before
```

Re-run de `scrape_bce_images.py` → images restaurées (419 commemos). Re-sync Supabase → propre.

**Leçon** : chaque fois qu'un nouvel enricher ajoute un champ au schema canonique (ici `images` via Phase 2C.5b, `design_description` via BCE), il faut étendre le merge des bootstraps. À surveiller en Phase 2C.6 quand Stage 4 visual ajoutera des champs.

---

## 4. `ml/sync_to_supabase.py` — flatteners

~280 lignes. Lit le référentiel JSON + `review_queue.json` + `matching_log.jsonl`, flatte chaque structure vers les colonnes cibles, et fait un upsert batché via PostgREST.

### Flattening rules

**`coins` rows** (1:1 avec les entries du référentiel) :
```python
{
  "eurio_id": entry["eurio_id"],
  "country": ident["country"],
  "year": ident["year"],
  "face_value": float(ident["face_value"]),
  "currency": "EUR",
  "is_commemorative": ident["is_commemorative"],
  "collector_only": ident["collector_only"],
  "theme": ident["theme"],
  "design_description": ident["design_description"],
  "national_variants": ident["national_variants"],
  "images": entry["images"],                    # JSONB
  "cross_refs": entry["cross_refs"],            # JSONB
  "sources_used": prov["sources_used"],         # text[]
  "needs_review": prov["needs_review"],
  "review_reason": prov["review_reason"],
  "first_seen": prov["first_seen"],
  "last_updated": prov["last_updated"],
}
```

**`source_observations` rows** (1:N avec les entries, une row par observation logique) :

| Type | Source | Quand |
|---|---|---|
| `mintage` | wikipedia | Une par entry avec `observations.wikipedia` populé |
| `variant` | lmdlp | Une par élément de `observations.lmdlp_variants` (clé SKU) |
| `mintage` | lmdlp | Une par entry avec `observations.lmdlp_mintage` populé |
| `issue_price` | mdp | Une par élément de `observations.mdp_issue` (clé SKU image-filename) |
| `market_stats` | ebay | Une par entry avec `observations.ebay_market` populé |

Chaque row a `payload: JSONB` = le dict complet original. Les observations restent queryables par type ET par contenu JSON natif.

**`matching_decisions` rows** : 1 ligne par entry dans `matching_log.jsonl`. Méthode composée : `stage{N}_{reason}` pour les décisions auto, `stage5_human_{action}` pour les résolutions CLI/serveur.

**`review_queue` rows** : 1:1 avec `review_queue.json`.

### Batching

PostgREST accepte des payloads JSON volumineux mais l'expérience montre qu'au-delà de ~500 rows / batch les timeouts peuvent piquer. Le client batche systématiquement en chunks de 500.

### Idempotence

- `coins` upsert via `on_conflict=eurio_id`
- `source_observations` upsert via `on_conflict=eurio_id,source,source_native_id,observation_type` (+ NULLS NOT DISTINCT)
- `review_queue` upsert via `on_conflict=source,source_native_id,reason`
- `matching_decisions` est append-only → le script **reset la table** avant chaque run (flag `--no-reset-decisions` pour désactiver) pour éviter l'accumulation

Vérifié : deuxième run du sync → compteurs identiques (2938 / 3695 / 197 / 1771). Zéro drift.

### CLI

```bash
python ml/sync_to_supabase.py                   # full sync
python ml/sync_to_supabase.py --dry-run         # just print counts
python ml/sync_to_supabase.py --coins-only      # skip observations/queue/decisions
python ml/sync_to_supabase.py --no-reset-decisions
```

---

## 5. Validation end-to-end

### Counts post-sync (via SQL direct)

```
coins                   : 2938 (517 commemos, 2421 circulation, 419 avec images)
source_observations     : 3695
  lmdlp variants        : 548
  lmdlp mintage         : 162
  mdp issue_price       : 17
  ebay market_stats     : 30
  wikipedia mintage     : 2938
review_queue            : 197 unresolved (121 groupes uniques)
matching_decisions      : 1771 (453 stage2, 936 stage3, reste stage5/skip/bce)
```

### Jointure anon — l'app peut fetcher une pièce + ses observations

Via l'anon key (ce que l'app Kotlin utilisera), requête :
```
GET /rest/v1/coins?select=eurio_id,theme,images,source_observations(source,observation_type,payload)
  &eurio_id=eq.fr-2019-2eur-60-years-since-the-creation-of-asterix
```

Retourne en 1 round-trip :
```json
{
  "eurio_id": "fr-2019-2eur-60-years-since-the-creation-of-asterix",
  "theme": "60 years since the creation of Asterix",
  "images": [{"url": "...bce_comm/...asterix.jpg", ...}],
  "source_observations": [
    {"source": "ebay", "observation_type": "market_stats",
     "payload": {"p25": 65.0, "p50": 65.0, "p75": 65.95, "samples_count": 4}},
    {"source": "lmdlp", "observation_type": "variant", "payload": {...}},
    ...
  ]
}
```

C'est **exactement** la shape que la Fiche Pièce Android va consommer en Phase 3. PostgREST fait la jointure côté serveur, l'app reçoit un seul JSON.

### RLS validation

- **GET /rest/v1/coins** avec anon key → **200 OK**, lecture publique ✓
- **POST /rest/v1/coins** avec anon key → **401 Unauthorized** (pas de policy INSERT pour anon) ✓

---

## 6. Types TypeScript générés

Pour les futures Edge Functions (cron scrapers, aggregation prix) :

```
supabase/types/database.ts    # NEW — auto-generated, import en Deno/TS
```

Usage (exemple futur Edge Function) :
```typescript
import type { Database, Tables } from "./types/database.ts"
import { createClient } from "@supabase/supabase-js"

const sb = createClient<Database>(URL, SERVICE_KEY)
const coin: Tables<'coins'> = await sb.from('coins').select().eq('eurio_id', ...).single()
```

Le fichier contient les 3 types (Row/Insert/Update) pour les 6 tables + les types Relationships pour l'autocompletion des joins imbriqués.

---

## 7. Sortie observable

```
supabase/types/database.ts                    # NEW TypeScript types
ml/sync_to_supabase.py                        # NEW writer (~280 lignes)

Migrations appliquées sur Supabase :
  20260413xxx1  drop_legacy_v0_schema
  20260413xxx2  create_canonical_referential_schema
  20260413xxx3  fix_source_observations_null_distinct
  20260413xxx4  perf_rls_initplan_and_fk_index
```

---

## 8. Advisor status final

| Niveau | Count | Note |
|---|---|---|
| ERROR | 0 | ✓ |
| WARN | **0** | ✓ tous résolus |
| INFO | 6 | `unused_index` sur des index fraîchement créés — normal, deviendra `used` dès que l'app query |

---

## 9. Ce qui n'est PAS encore fait

| Élément | Pourquoi | Plan |
|---|---|---|
| Écrire côté sync depuis Edge Function (cron hebdo) | Nécessite le déploiement Edge Functions + orchestrateur | Phase 3 ou avant la beta |
| Branchement Kotlin app → Supabase | Phase 2B en cours, pas encore besoin | Phase 3 (coffre) |
| Population `coin_embeddings` | Nécessite Phase 2B (modèle ArcFace entraîné et exporté) | Phase 2B.x |
| Re-apply `manual_resolutions.json` lors des re-runs scraper | Pas bloquant (queue reste en place) | Quand on fera des runs cron réguliers |
| Backup stratégie (`pg_dump`) | Supabase fait déjà des backups quotidiens free tier 7j | Upgrade Pro si retention plus longue |

---

## 10. Prochaine étape

Phase 2C est **terminée** côté data pipeline. La boucle bootstrap → scrapers → matching → review → sync est fonctionnelle et sync-ready pour l'app Android.

Candidats pour la suite :

- **A. Phase 2B ArcFace** — training du modèle de scan + export TFLite + `coin_embeddings` pré-calculé. C'est le bloquant pour le scan utilisateur et pour Stage 4 visual.
- **B. Phase 3 coffre** — écrans Kotlin Compose, branchement Supabase, collection user. Peut avancer en parallèle de 2B.
- **C. Review manuelle de la queue** — ~20 min dans le serveur web, résout les 121 cas lmdlp FR↔EN.
- **D. Mettre à jour `ARCHITECTURE.md`** avec le milestone Phase 2C complète (changelog + roadmap Gantt).

Je recommande **D** d'abord (5 min), puis **B** (Phase 3 kicks off la partie visible de l'app), puis **A** en parallèle sur le GPU.
