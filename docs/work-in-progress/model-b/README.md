# Model B — État courant & cible (source de vérité)

> **Ce doc est LE seul à lire pour Model B.** État présent + cible + roadmap +
> mode opératoire + briefs R3/R4 vivent ici. Les anciens docs de raisonnement
> (`DESIGN`, `GAP-ANALYSIS`, `HANDOFF-2026-06-29`, `HANDOFF-NEXT-SESSIONS`,
> `C4-HANDOFF-SERVER`, `C8-CUTOVER-PLAN`) sont dans [`_archive/`](./_archive/) —
> trace de raisonnement, plus à lire au quotidien. `QA-CHROME-MCP.md` reste à côté
> (suite de tests navigateur re-jouable). Dernière MAJ : 2026-06-30.

## En une phrase

Le **canonique** = une base **SQLite sur le VPS**, contactée **via l'API**
(`eurio-api`). Plusieurs machines de calcul (Mac/PC) travaillent en parallèle sur
des **répliques locales** (copies de travail) et **poussent** leurs runs au VPS
(`/ingest/run`). Pas de lease, pas de writer unique sérialisé — l'API arbitre.

> 🔄 **Extension livrée (2026-07-03) : [local-sync](../local-sync/README.md)** —
> les **écritures interactives** (classification, review, crops manuels) sont
> désormais répliquées multi-maître par event-log (op_id/machine/HLC, worker
> debounce, LWW-par-champ) : le travail local converge automatiquement sur le
> canonique et redescend sur l'autre machine. Ferme le trou du handoff
> `local-canonical-double-write-HANDOFF.md`.

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

> ✅ **Livré (R1, 2026-06-30).** Tout ce qui suit est **fait** : un seul codebase
> `studio-local`, knob `VITE_DEPLOY_TARGET`, auth-adapter PAT/cookie, gating route-level
> (`meta.heavy` + `LocalOnlyNotice`), 3 vues admin rapatriées, `admin-vps` supprimé,
> déployé sur `eurio-admin.musubi.dev`.

- **Un seul codebase** (le front riche `studio-local`, devenu front canonique),
  servi à **deux endroits** via deux réglages (pas deux codebases) :
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

## État courant (2026-06-30) — ce qui EST fait

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
  (`infra/backup/eurio-backup.sh`, plus via MinIO). **Plus aucune référence
  DB↔MinIO dans le code.** Déployé + vérifié VPS (healthz 200, endpoint sha≡header≡
  fichier, `foreign_key_check`=0, `go-task ml:db:pull-replica` ramène l'état VPS).
  - ⏳ **Housekeeping restant (1 action user, non bloquant)** : lancer une fois
    `eurio-backup.sh run` sur le VPS (premier backup direct du canonique sur pCloud),
    **puis** supprimer les objets `eurio.db`/`.sha256`/`.lock` du bucket MinIO
    `eurio-db` (devenu orphelin). Ordre = backup d'abord, suppression ensuite.
- ✅ **R1 (2026-06-30) — fusion front** : un seul codebase `studio-local` servi local
  (PAT, ML lourd) + hébergé (cookie OIDC, lourd grisé), piloté par `VITE_DEPLOY_TARGET`.
  Auth-adapter (`shared/api/eurio-api.ts`), capacité `hasLocalMlApi` (`stores/capabilities.ts`
  + ping `:8042`), gating route-level (`meta.heavy` + `LocalOnlyNotice`). 3 vues rapatriées
  (dashboard KPIs / users / mes tokens). `admin-vps` **supprimé**. `infra/eurio-admin/`
  build désormais `studio-local` mode hosted. CLAUDE.md §Architecture frontend réécrit.

## Roadmap (compressée — ce qui RESTE)

| # | Chantier | Quoi | Effort |
|---|---|---|---|
| ~~**R1**~~ | ~~**Fusion front**~~ | ✅ **LIVRÉ 2026-06-30** — 1 codebase, auth-adapter PAT/cookie, gating `hasLocalMlApi` (route `meta.heavy` + `LocalOnlyNotice`), 3 vues rapatriées, `admin-vps` supprimé, déployé hébergé. | L |
| ~~**R2**~~ | ~~**Réplique ← VPS, retrait MinIO-DB**~~ | ✅ **LIVRÉ 2026-06-30** — endpoint `GET /db/replica` (+ sha, `VACUUM INTO`), `pull_replica` repointé, `canonical_sync`+`lease` supprimés, backup canonique direct→pCloud. | M |
| **R3** | **Finitions Model B** (différé, pas bloquant) | wire `--push` dans le pipeline training GPU ; endpoint orchestration lean (C7 server-side). | M |
| **R4** | **Débit review** (valeur produit) | ~2700 items open sur le canonique = goulot cohorte→training. Outillage / autovalidation. | — |

> **Priorité** : R1 (front) ✅ et R2 (cohérence archi) ✅ faits. Reste **R3** (finitions,
> différé) et **R4** (débit review, valeur produit) — briefs en bas de ce doc.

> 🧪 **QA navigateur** : suite de tests Chrome MCP re-jouable (Sonnet 4.6) dans
> [`QA-CHROME-MCP.md`](./QA-CHROME-MCP.md) — valide R1 (front local+hébergé, gating) et
> le chemin de données (charge du VPS, images MinIO, zéro mixed-content). **Validée 2026-06-30.**

## Garde-fous / invariants à ne pas casser

- Le compute **n'écrit jamais** le canonique en direct → toujours réplique + `--push`.
- `batch_sha` garantit l'idempotence d'un re-POST identique (pas la stabilité d'un
  vieux run dont le contenu mutable a changé — résidu assumé).
- `source_images.run_id` = first-seen **immuable** ; la containment par-run vit dans
  `source_image_runs` (sinon un re-scrape vole l'attribution — cf. fix parité).
- MinIO = images. **Jamais** la DB (R2 fait — `canonical_sync`/`lease` supprimés).

---

## Mode opératoire (serveur / deploy / tests)

### Accès VPS (autorisé)
- **SSH** : `ssh serverOimNixDontpanic` → le VPS (NixOS, no-GPU, toujours allumé).
- **Rebuild + deploy `eurio-api`** (après `git push`) :
  ```bash
  ssh serverOimNixDontpanic 'cd /opt/eurio && git pull origin sources-jo-wikipedia && \
    cd infra/eurio-api && direnv exec /opt/eurio bash -c "docker compose up -d --build"'
  ssh serverOimNixDontpanic 'docker logs --tail 30 eurio-api'
  curl -sS -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/healthz   # attendu 200
  ```
  Migrations SQL (`ml/serving/migrations/*.sql`) appliquées **au boot**. `direnv exec
  /opt/eurio` charge les secrets SOPS (pas de `sops` nu en ssh non-interactif).
- **Requêter le canonique** (pas de `sqlite3` CLI dans le conteneur lean) :
  ```bash
  ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
  import sqlite3; c=sqlite3.connect(\"/var/lib/eurio/eurio.db\")
  print(list(c.execute(\"SELECT count(*) FROM coins\")))"'
  ```
  Script plus long : l'écrire dans `/tmp/x.py` → `scp` VPS → `docker cp` dans
  `eurio-api` → `docker exec eurio-api python /tmp/x.py` (évite l'enfer du quoting).
- **MinIO** : `eurio-minio` sur le VPS (réseau docker `traefik`). Depuis le conteneur
  eurio-api, endpoint **interne** `http://eurio-minio:9000` (boto3 + creds `MINIO_*`).
  L'endpoint public `eurio-s3.musubi.dev` n'est PAS résolu depuis le conteneur.
- **Front hébergé** : `infra/eurio-admin/` (nginx static derrière Traefik). Rebuild =
  `cd /opt/eurio/infra/eurio-admin && direnv exec /opt/eurio docker compose up -d --build`.

### Git / deploy
- Branche : `sources-jo-wikipedia`. Remotes : `origin` = codeberg, `github` = backup.
  **Push les deux**. Staging explicite par fichier (jamais `git add -A`/`.`).
- Footer : `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

### Tests / build
- Python : `cd ml && .venv/bin/python -m pytest tests/test_runbatch.py -q` (10/10).
  ⚠️ `python-jose` absent du venv compute Mac → pas d'import `serving.auth_principal`
  en local ; `py_compile` + boot Docker VPS valident ces modules.
- Front : `cd admin/packages/studio-local && pnpm typecheck` (+ `pnpm build`).

### Secrets / PAT
- Secrets via SOPS+direnv (`go-task secrets:edit`). PAT user dans
  `studio-local/.env.local` (`VITE_EURIO_PAT`, gitignored). Minter un PAT :
  ```bash
  ssh serverOimNixDontpanic 'docker exec eurio-api python -m serving.auth \
    create-pat --email raphaelthi59@gmail.com --name <nom>'
  ```

---

## Briefs des chantiers restants

### R3 — Finitions Model B (effort M — différé, pas bloquant)
- **Training `--push`** : câbler le push du run-batch training (export C6c déjà dans
  `client/runbatch._collect_training_tables`) dans le pipeline GPU
  (`ml/training/pipeline.py` / `serving/training_runner.py`) : à la fin d'un run,
  `push_run(run_id)` (training_runs = sa propre PK, pas de stub source_runs).
  Vérifier la FK closure recipe côté canonique.
- **Endpoint orchestration lean (C7 server-side)** : `lab_routes` est lourd (imports
  `iteration_runner`→`training.*`→torch/cv2) → non mountable lean. Pour servir
  `POST /lab/iterations` sur le VPS, faire un routeur mince n'important que `store`.
  Différable : utile seulement quand le VPS orchestre.
- **Done quand** : un training local pousse ses métadonnées au canonique (vérifiable
  SSH : `training_runs`/`steps`/`epochs` côté VPS).

### R4 — Débit review (valeur produit — chantier ouvert)
Vrai goulot : **~2700 items `open`** sur le canonique (`review_queue`) bloquent
cohorte→training. Pistes (à cadrer avec le user, pas turn-key) :
- Outillage pour accélérer la review humaine (raccourcis, batch, pré-tri).
- Calibrer les seuils d'autovalidation (consensus/Dino) pour réduire le volume manuel.
- Relabel `mix-zone-17` (hold-out) pour mesurer.

Plus **produit** que technique → discussion de cadrage avant de coder. Vérif d'état :
`SELECT status, count(*) FROM review_queue GROUP BY status` sur le canonique (SSH).
