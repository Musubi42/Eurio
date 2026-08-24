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

## R1 — Fusion front ✅ LIVRÉ (2026-06-30)

Front unique `studio-local`, servi local (PAT, ML lourd) + hébergé (cookie OIDC,
lourd grisé) via `VITE_DEPLOY_TARGET`. Auth-adapter (`eurio-api.ts`), capacité
`hasLocalMlApi` (`stores/capabilities.ts` + ping `:8042`), gating **route-level**
(`meta.heavy` + `LocalOnlyNotice` — pas d'édition des 25 call-sites ML). 3 vues
rapatriées (`features/{dashboard,users,tokens}`). `admin-vps` supprimé.
`infra/eurio-admin/` build désormais studio-local mode hosted. Déployé + vérifié
(200, bundle cookie, healthz 200). Commits `9478335`→`aba0a5b`. État : `README.md` §État.

---

## R2 — Réplique ← VPS, retrait MinIO-DB ✅ LIVRÉ (2026-06-30)

`pull_replica` tire la réplique du VPS (`GET /db/replica`, snapshot `VACUUM INTO` +
sha). `canonical_sync.py` + `store/lease.py` supprimés, tâches `ml:db:acquire/release/
sync/steal` retirées, backup canonique direct conteneur→pCloud. **MinIO = images.**
Déployé + vérifié (3 sha concordent, `foreign_key_check`=0). Commits `caf8f2a`→`4940f41`.
⏳ Seul reste (housekeeping user) : 1er `eurio-backup.sh run` puis purge du bucket MinIO
`eurio-db` orphelin (cf. `README.md` §État).

---

## QA — vérification navigateur (Chrome MCP)

Suite de tests turn-key (Sonnet 4.6 + sous-agents) dans [`QA-CHROME-MCP.md`](./QA-CHROME-MCP.md) :
charge-t-on bien du VPS, gating correct, 3 vues admin, images depuis MinIO, zéro
mixed-content, mode local vs hébergé. À lancer dans une session dédiée.

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
