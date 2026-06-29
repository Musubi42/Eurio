# Model B — État courant & cible (source de vérité)

> **Ce doc est LA référence.** Les autres fichiers de ce dossier (`DESIGN.md`,
> `GAP-ANALYSIS.md`, `HANDOFF-2026-06-29.md`, `C4-HANDOFF-SERVER.md`,
> `C8-CUTOVER-PLAN.md`) sont **historiques** — gardés comme trace de raisonnement,
> mais c'est ici que vit l'état présent + la cible + la roadmap.
> Dernière MAJ : 2026-06-30.

## En une phrase

Le **canonique** = une base **SQLite sur le VPS**, contactée **via l'API**
(`eurio-api`). Plusieurs machines de calcul (Mac/PC) travaillent en parallèle sur
des **répliques locales** (copies de travail) et **poussent** leurs runs au VPS
(`/ingest/run`). Pas de lease, pas de writer unique sérialisé — l'API arbitre.

## Pourquoi (le « pourquoi » qui guide tout)

- **Multi-PC sans conflit** : Model A faisait vivre la DB dans MinIO derrière un
  **lease** (un seul writer à la fois) → impossible de bosser depuis 2 PC. Model B
  met le canonique derrière l'API : chaque PC pousse ses runs, l'API sérialise.
- **Pas de back-and-forth** : un travail multi-étapes (scrape → crop → résolution)
  se fait **entièrement sur la réplique locale**, puis **un seul push** à la fin.
  La donnée ne fait pas l'aller-retour VPS à chaque étape.
- **Le canonique survit au Mac éteint** : la vérité partagée est sur le VPS.

## Architecture cible

### Données

- **Canonique** = `/var/lib/eurio/eurio.db` (SQLite) sur le VPS, **writer unique**
  derrière `eurio-api` : `/ingest/run` (run-batches poussés par le compute) +
  écritures review (decide/skip/reject/restore, TC2).
- **Réplique** = copie de travail locale, **tirée DU VPS** via un endpoint
  authentifié (`GET /db/replica` + `/db/replica/sha`, scope `ingest:run`). C'est la
  copie sur laquelle le compute lourd (scrape/crop/dino/training) lit/écrit en
  local, avant de pousser. ✅ **Livré (R2)** : `client.replica.pull_replica` tire
  un snapshot `VACUUM INTO` cohérent servi par `serving.db_routes`.
- **MinIO = images uniquement** (buckets `enrichment-raws`, `enrichment-crops`,
  `numista-canonical`, transfers). **PLUS la DB.** Le MinIO-pour-la-DB + le lease
  étaient une béquille Model A → ✅ **retirés (R2)** (`canonical_sync.py`,
  `store/lease.py` supprimés).
- Cycle type (scrape eBay) : `pull-replica` (depuis VPS) → scrape+crop+résolution
  **en local sur la réplique** → `--push` (un seul POST au VPS). Idem recrop/dino.
  Training : on tire la réplique (métadonnées) + les **images depuis MinIO** en
  cache local le temps du run.

### Front

- **Un seul codebase** (le front riche actuel `studio-local`, renommé front
  canonique), servi à **deux endroits** via deux réglages (pas deux codebases) :
  - **En local** (`pnpm dev`, `localhost`, auth **PAT**) : **tout** marche, y
    compris crop/scrape/training (la page appelle l'API ML locale `:8042`, même
    origine non-sécurisée → zéro mixed-content).
  - **Hébergé** (`eurio-admin.musubi.dev`, HTTPS, auth **cookie Authentik**) : le
    **même front riche**, mais les features lourdes sont **grisées** avec un bandeau
    « ceci tourne en local : lance `…` puis va sur localhost ». Le léger (review en
    consultation, users, tokens, KPIs, édition métadonnées) marche depuis le VPS.
- Deux réglages, pas deux codebases :
  1. **auth-adapter** : PAT (Bearer) vs cookie (`credentials: include`), choisi par
     env de build.
  2. **capacité `hasLocalMlApi`** (env ou ping `:8042`) : les vues lourdes la lisent
     → activées en local, grisées + bandeau en hébergé.
- **`admin-vps` (le front thin actuel) disparaît** : on rapatrie ses 3 vues utiles
  (users / tokens / dashboard KPIs) dans le front riche, et c'est lui qu'on déploie
  en hébergé.
- **Pourquoi pas le hack « l'hébergé appelle le local »** : HTTPS → `http://localhost`
  = mixed-content / Private Network Access, fragile et cross-browser instable. On ne
  fait PAS ça. Le lourd se déclenche depuis le local, point.

## État courant (2026-06-29) — ce qui EST fait

- ✅ Backend Model B : `eurio-api` (JWT/RBAC, PAT, `/ingest/run`), run-batch
  export/ingest idempotent (`client/runbatch.py`), parité A↔B validée + fix
  attribution `source_images` (lien M:N `source_image_runs`, run_id first-seen).
- ✅ Compute → push : scrape (`--push`), recrop & dino backfill (`--push`),
  export training (C6c, run-scopé + FK closure recipes).
- ✅ **TC2** : écritures review server-side (lean, cv2-free) + front sur l'API VPS.
- ✅ **Cutover** : VPS = canonique. Orphelins FK nettoyés (`foreign_key_check`=0).
  Topology A→B.
- ✅ **R2 (2026-06-30) — dernier reste Model A retiré** : `pull_replica` tire la
  réplique **directement du VPS** (`GET /db/replica`, snapshot `VACUUM INTO`
  cohérent + vérif sha). `serving/canonical_sync.py` (sync→MinIO) et
  `store/lease.py` (lease) **supprimés** ; tâches `ml:db:acquire/release/sync/steal`
  retirées du Taskfile. Backup du canonique **direct** conteneur→pCloud
  (`infra/backup/eurio-backup.sh`, plus via MinIO). **MinIO ne contient plus la DB.**

## Roadmap (compressée — ce qui RESTE)

| # | Chantier | Quoi | Effort |
|---|---|---|---|
| **R1** | **Fusion front** | 1 codebase : porter users/tokens/dashboard d'`admin-vps` dans le front riche + auth-adapter (PAT/cookie) + gating `hasLocalMlApi` + bandeau rappel local. Déployer en hébergé (remplace `admin-vps`), retirer `admin-vps`. | L |
| ~~**R2**~~ | ~~**Réplique ← VPS, retrait MinIO-DB**~~ | ✅ **LIVRÉ 2026-06-30** — endpoint `GET /db/replica` (+ sha, `VACUUM INTO`), `pull_replica` repointé, `canonical_sync`+`lease` supprimés, backup canonique direct→pCloud. | M |
| **R3** | **Finitions Model B** (différé, pas bloquant) | wire `--push` dans le pipeline training GPU ; endpoint orchestration lean (C7 server-side). | M |
| **R4** | **Débit review** (valeur produit) | ~2700 items open sur le canonique = goulot cohorte→training. Outillage / autovalidation. | — |

> **Priorité** : R1 (front, le plus visible/structurant) — R2 (cohérence archi —
> tuer le dernier reste Model A) ✅ fait. R3/R4 ensuite.

> 🛠️ **Pour exécuter** : briefs turn-key par chantier (avec accès SSH serveur,
> deploy, tests, usage workflows) dans [`HANDOFF-NEXT-SESSIONS.md`](./HANDOFF-NEXT-SESSIONS.md).

## Garde-fous / invariants à ne pas casser

- Le compute **n'écrit jamais** le canonique en direct → toujours réplique + `--push`.
- `batch_sha` garantit l'idempotence d'un re-POST identique (pas la stabilité d'un
  vieux run dont le contenu mutable a changé — résidu assumé).
- `source_images.run_id` = first-seen **immuable** ; la containment par-run vit dans
  `source_image_runs` (sinon un re-scrape vole l'attribution — cf. fix parité).
- MinIO = images. **Jamais** la DB (R2 fait — `canonical_sync`/`lease` supprimés).
