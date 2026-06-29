# HANDOFF — sessions suivantes (R1 → R4)

> **Pour une session fraîche qui reprend le chantier.** Lis d'abord
> [`README.md`](./README.md) (état + archi cible) — il est court et c'est LA vérité.
> Ce doc-ci donne le **mode opératoire** (serveur, deploy, git, tests, workflows) +
> un **brief turn-key par chantier**. Chaque chantier ≈ une session (R1 peut se
> scinder en 2). Branche de travail : `sources-jo-wikipedia`.

---

## 0. Mode opératoire (à savoir avant de toucher quoi que ce soit)

### Accès serveur (VPS) — autorisé
- **SSH** : `ssh serverOimNixDontpanic` → le VPS (NixOS, no-GPU, toujours allumé).
  Tu peux t'y connecter librement pour vérifier, relancer, déployer, débugger.
- **Rebuild + déploiement de `eurio-api`** (après un `git push`) :
  ```bash
  ssh serverOimNixDontpanic 'cd /opt/eurio && git pull origin sources-jo-wikipedia && \
    cd infra/eurio-api && direnv exec /opt/eurio bash -c "docker compose up -d --build"'
  # vérifs
  ssh serverOimNixDontpanic 'docker logs --tail 30 eurio-api'
  curl -sS -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/healthz   # attendu 200
  ```
  Les migrations SQL (`ml/serving/migrations/*.sql`) s'appliquent **au boot**
  (db_migrate). `direnv exec /opt/eurio` charge les secrets SOPS (PAS de `sops` nu
  dans le PATH ssh non-interactif).
- **Requêter le canonique** (pas de `sqlite3` CLI dans le conteneur lean) :
  ```bash
  ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
  import sqlite3; c=sqlite3.connect(\"/var/lib/eurio/eurio.db\")
  print(list(c.execute(\"SELECT count(*) FROM coins\")))"'
  ```
  Pour un script Python plus long : l'écrire dans `/tmp/x.py`, `scp` au VPS,
  `docker cp` dans `eurio-api`, `docker exec eurio-api python /tmp/x.py` (pattern
  utilisé en C8 — évite l'enfer du quoting).
- **MinIO** : serveur `eurio-minio` sur le VPS (même réseau docker `traefik`).
  Depuis le conteneur eurio-api, endpoint **interne** `http://eurio-minio:9000`
  (boto3 + creds `MINIO_*` déjà dans l'env du conteneur). L'endpoint **public**
  `eurio-s3.musubi.dev` n'est PAS résolu depuis le conteneur.
- **Front hébergé** (`eurio-admin.musubi.dev`) : `infra/eurio-admin/` (nginx static
  derrière Traefik). Rebuild = `cd /opt/eurio/infra/eurio-admin && docker compose up -d --build`.

### Git / deploy
- Branche : `sources-jo-wikipedia`. Remotes : `origin` = codeberg, `github` = backup.
  **Push les deux** (`git push origin … && git push github …`).
- **Staging explicite par fichier** (jamais `git add -A` / `.` — secrets).
- Footer de commit : `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

### Tests / build
- Python : `cd ml && .venv/bin/python -m pytest tests/test_runbatch.py -q`
  (10/10 vert attendu). ⚠️ `python-jose` est **absent du venv compute Mac**
  (dépendance serveur lean) → tu ne peux pas importer `serving.auth_principal`
  en local ; `py_compile` + le boot Docker VPS valident ces modules.
- Front : `cd admin/packages/studio-local && pnpm typecheck` (et `pnpm build`).

### Secrets / PAT
- Secrets via SOPS+direnv (`go-task secrets:edit`). PAT du user dans
  `studio-local/.env.local` (`VITE_EURIO_PAT`, gitignored).
- Minter un PAT (scopes = rôles du user, owner+admin+reviewer → tous scopes) :
  ```bash
  ssh serverOimNixDontpanic 'docker exec eurio-api python -m serving.auth \
    create-pat --email raphaelthi59@gmail.com --name <nom>'
  ```

### Workflows — AUTORISÉS et encouragés
Le user a **opté pour l'usage de workflows** sur ces chantiers (orchestration
multi-agents, cf. l'outil `Workflow`). Bon usage : **scout d'abord** (lister les
fichiers/vues à toucher) puis **fan-out** sur la liste (port de N vues, audit de N
call-sites, review adversariale). Garde le fan-out pour du travail **indépendant** ;
les éditions interdépendantes sur les mêmes fichiers restent séquentielles.

### Doctrine projet (rappel)
R0 = zéro dette (pas de shortcut ; si la solution propre n'est pas claire, on discute
avant). Chunks de 30 min-3 h, livrer + attendre rétro, ne pas enchaîner sans « go ».
Proto-first pour tout NOUVEAU design d'app (pas concerné par R1-R3, outillage admin).

---

## R1 — Fusion front (effort L — possible en 2 sessions)

**But.** Un **seul** codebase front : le front riche `studio-local` devient le front
canonique, servi **hébergé** (cookie Authentik, léger) **et** **local** (PAT, full).
`admin-vps` disparaît. Features lourdes (crop/scrape/training) **grisées + bandeau**
en hébergé. Détail cible : `README.md` §Front.

**Découpage proposé.**
- **R1a (auth + gating, sans toucher au déploiement)** :
  1. **Auth-adapter** dans `studio-local/src/shared/api/eurio-api.ts` : mode `pat`
     (Bearer depuis `VITE_EURIO_PAT`) vs `cookie` (`credentials: 'include'`),
     sélectionné par une env (`VITE_AUTH_MODE` ou `VITE_DEPLOY_TARGET=local|hosted`).
  2. **Capacité `hasLocalMlApi`** : composable qui résout vrai/faux (env explicite,
     ou ping `GET ${ML_API}/healthz` au boot). Exposer un store/flag global.
  3. **Gating** : les vues/boutons lourds (crop edit, scrape, training, recrop —
     tout ce qui tape `ML_API` cf. `useReviewApi.ts`, `useTrainingApi.ts`,
     `useReferentialApi.ts` compute, `useSetsApi`…) lisent le flag → état désactivé
     + **bandeau** « ceci tourne en local : lance `…` puis va sur localhost ».
  - *Vérif* : `pnpm dev` local (mode pat, hasLocalMlApi=true) = tout marche ;
    build avec `VITE_DEPLOY_TARGET=hosted` = lourd grisé. `pnpm typecheck`.
- **R1b (port des vues admin-vps + déploiement + retrait)** :
  4. **Porter** les 3 vues utiles d'`admin-vps` dans `studio-local` :
     `UsersPage` (F6), `MyTokensPage` (F7), dashboard KPIs `Home`/`stats` (F9).
     Source : `admin/packages/admin-vps/src/views/`. Les endpoints VPS existent déjà
     (`users_routes`, `tokens_routes`, `stats_routes`).
  5. **Déployer `studio-local` en hébergé** sur `eurio-admin.musubi.dev` : build mode
     hosted → static → servi par `infra/eurio-admin/` (remplace le build admin-vps).
     Auth cookie OIDC (Authentik) déjà en place côté `eurio-api`.
  6. **Retirer** le package `admin/packages/admin-vps/` (et ses refs Taskfile/CI).
  - *Vérif* : aller sur `eurio-admin.musubi.dev`, login Authentik, voir review
    (consultation) + users + tokens + KPIs ; vérifier que crop/scrape/training sont
    grisés avec le bandeau. SSH pour rebuild le conteneur `eurio-admin`.

**Workflow utile** : un agent d'audit qui **liste tous les call-sites `ML_API`** dans
`studio-local/src` (= la surface « lourde » à gater) + mappe les vues `admin-vps` à
porter → puis tu codes le gating sur cette liste. Le port des 3 vues peut fan-out.

**Done quand** : un seul codebase, `eurio-admin` sert le front riche (léger marche,
lourd grisé), `admin-vps` supprimé, `CLAUDE.md` §Architecture frontend réécrit (retire
le dual-front, décrit le mono-front + modes). MAJ `README.md` §État (R1 ✅).

---

## R2 — Réplique ← VPS, retrait MinIO-DB (effort M)

**But.** `pull_replica` tire la réplique **d'un endpoint VPS**, plus de MinIO. On
retire le dernier reste Model A (sync→MinIO + lease). **MinIO = images uniquement.**

**Étapes.**
1. **Endpoint VPS** `GET /db/replica` (auth `require_scope`, ex. `ingest:run` ou un
   nouveau `db:replica`) qui sert un **snapshot cohérent** du canonique :
   `VACUUM INTO /tmp/snap.db` (intègre sous WAL) → `StreamingResponse` du fichier →
   cleanup. Plus `GET /db/replica/sha` (sha du même snapshot) pour l'intégrité.
   *Réutilise la logique de `serving/canonical_sync.py::_snapshot` + `store.lease._sha256`.*
   ⚠️ 106 Mo : streamer, pas charger en RAM ; envisager un cache court (snapshot +
   sha valides N secondes) pour ne pas VACUUM à chaque pull.
2. **Repointer `client/replica.pull_replica`** : download HTTP depuis l'endpoint VPS
   (via `client.http` + le PAT `EURIO_API_TOKEN`) + vérif sha, au lieu de
   `_lease._s3()` / MinIO. Garder le contrat (retourne le `Path`, vérifie le sha).
3. **Retirer** `serving/canonical_sync.py` + son hook startup dans
   `serving/server_serve.py` (`_start_canonical_sync`) + le lock VPS.
4. **Déprécier/retirer** `store/lease.py` + les tâches `Taskfile` `ml:db:acquire/
   release/sync/steal` (ou les marquer « secours uniquement » si on garde un filet).
5. **Backup** : MinIO ne contient plus la DB → ajouter un backup **direct** du
   `eurio.db` VPS → pCloud (greffer sur `infra/backup/eurio-backup.sh`, ou un cron
   VPS `docker exec eurio-api … VACUUM INTO` puis rclone). Sans ça, plus de copie
   hors-VPS de la base.
6. **Nettoyer** le bucket MinIO `eurio-db` (objets `eurio.db`, `.sha256`, `.lock`)
   une fois R2 validé.

**Vérif (SSH + Mac)** : depuis le Mac, `go-task ml:db:pull-replica` ramène une
réplique = état VPS courant (contient les derniers runs) sans toucher MinIO ;
`grep -r minio client/replica.py` ne renvoie plus rien de la DB. Endpoint testable :
`curl -H "Authorization: Bearer <PAT>" https://eurio-api.musubi.dev/db/replica/sha`.

**Done quand** : aucune référence DB↔MinIO ne subsiste, `pull_replica` lit le VPS,
backup DB hors-VPS en place. MAJ `README.md` (retirer l'encart transitoire) +
`deployment-topology.md` (le « transitoire » devient l'état nominal).

---

## R3 — Finitions Model B (effort M — différé, pas bloquant)

- **Training `--push`** : câbler le push du run-batch training (l'export C6c existe
  déjà dans `client/runbatch._collect_training_tables`) dans le pipeline GPU
  (`ml/training/pipeline.py` / `serving/training_runner.py`) : à la fin d'un run,
  stub source_runs pas nécessaire (training_runs = sa propre PK), `push_run(run_id)`.
  Vérifier la FK closure recipe côté canonique.
- **Endpoint orchestration lean (C7 server-side)** : aujourd'hui `lab_routes` est
  lourd (imports `iteration_runner`→`training.*`→torch/cv2) → non mountable lean.
  Pour servir `POST /lab/iterations` (create + garde 409 par-cohorte) sur le VPS,
  faire un **routeur mince** qui n'importe que `store` (pas le runner). Décision
  ouverte : utile seulement quand le VPS orchestre — peut rester différé.

**Done quand** : un training local pousse ses métadonnées au canonique (vérifiable
en SSH : `training_runs`/`steps`/`epochs` apparaissent côté VPS).

---

## R4 — Débit review (valeur produit — chantier ouvert)

Le vrai goulot : **~2700 items `open`** sur le canonique (`review_queue`) bloquent le
flux cohorte→training. Pistes (à cadrer avec le user, pas turn-key) :
- Outillage pour accélérer la review humaine (raccourcis, batch, pré-tri).
- Calibrer les seuils d'autovalidation (consensus/Dino) pour réduire le volume à
  reviewer manuellement (cf. mémoires autovalidation / dino thresholds).
- Relabel `mix-zone-17` (hold-out) pour mesurer.

C'est plus **produit** que technique → commencer par une discussion de cadrage avec
le user avant de coder. Vérif d'état : `SELECT status, count(*) FROM review_queue
GROUP BY status` sur le canonique (SSH).

---

## Ordre recommandé

**R1** (front, le plus visible) et **R2** (cohérence archi, tue le dernier Model A)
en priorité — indépendants, faisables dans n'importe quel ordre. Puis **R3** si
besoin réel, **R4** quand on veut débloquer le pipeline data.

Après chaque chantier : MAJ `README.md` §État + roadmap, commit doc, et (si tu as
touché au serveur) vérifier `healthz` 200 + `foreign_key_check` = 0 sur le canonique.
