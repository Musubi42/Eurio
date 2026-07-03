# HANDOFF — reprise Direction A (Mac ↔ VPS ↔ PC synchronisés)

> Point d'entrée UNIQUE pour une nouvelle session. Lis ce fichier en entier
> avant d'agir. Date du handoff : 2026-07-04. Branche : `sources-jo-wikipedia`.

---

## 0. Prompt prêt à coller (démarrage nouvelle session)

```
Contexte : projet Eurio (~/Documents/Musubi42/bizz/Eurio). On termine la migration
« Direction A » : le VPS est le SEUL eurio.db inscriptible ; Mac + PC sont des
clients replica (lecture) + forward (écriture = POST à l'API VPS). But : je peux
bosser sur mon Mac ET mon PC, les données restent cohérentes via le VPS.

LIS D'ABORD, dans cet ordre :
  docs/work-in-progress/local-sync/HANDOFF-next-session.md   (ce contexte)
  docs/work-in-progress/local-sync/c4-c8-known-gaps.md       (le travail du jour)
  docs/work-in-progress/local-sync/friction-log.md           (pièges à éviter)
  docs/work-in-progress/local-sync/migration-direction-a.md  (le plan complet)

Outils à ta disposition :
  - SSH VPS  : `ssh serverOimNixDontpanic` (canonique + déploiement)
  - SSH PC   : `ssh pc` (raphael@192.168.1.163, LAN — vérif multi-machine)

Objectif de CETTE session (dans l'ordre) :
  1. Fermer les 2 gaps MAJOR de c4-c8-known-gaps.md (delete non propagé + read-only
     pas enforced) + finir C4d.
  2. Déployer C4–C8 sur le VPS (après les fix), avec health-check.
  3. Vérifier live Mac↔VPS↔PC (le canonique reflète une décision, l'autre machine
     la voit après pull-replica).
  4. Décider du nettoyage des 3 commits « WIP » poussés (force-push ?).
Procède chunk par chunk, vérifie chaque étape en live, ne casse pas le tree.
```

---

## 1. Le but (en une phrase)

Travailler sur Mac **et** PC avec **une seule source de vérité** (l'`eurio.db` du
VPS). Chaque machine lit une **réplique read-only** tirée du VPS et **écrit** en
POSTant à l'API VPS. Aucune machine n'ouvre `eurio.db` en écriture sauf le VPS →
**aucune divergence possible par construction**.

## 2. Pourquoi (le problème qu'on a diagnostiqué et résolu)

L'ancienne archi = **sync par event-log** (chaque machine a un `eurio.db`
inscriptible + un journal d'events qu'on rejoue pour converger). **Elle ne
convergeait PAS** — prouvé par triangulation Mac/VPS/PC sur une pièce test : les
3 machines avaient le **même log d'events** mais **matérialisaient des états
différents**. Deux causes :
1. Le **bulk ne voyage pas** (l'event-log porte des décisions-sur-lignes, pas
   l'existence d'une ligne).
2. **18 fichiers mutent `image_assets` sans émettre d'event** → le log est une
   ombre partielle, le replay ne peut pas reconstruire la vérité.

Conclusion : on ne peut pas event-sourcer une table à écrivains multiples. La
seule solution = **supprimer la 2ᵉ copie inscriptible** → writer canonique unique
(le VPS). C'est « Direction A ».

## 3. Où on en est EXACTEMENT (état au 2026-07-04)

| | Commit | État |
|---|---|---|
| **C2a–C3** | `12a04e9` | ✅ committé, **poussé** (codeberg+github), **DÉPLOYÉ + vérifié LIVE sur le VPS** |
| **C4–C8** | `0d506d3` | ✅ committé **local**, **PAS poussé**, **PAS déployé** sur le VPS |

- **Le VPS canonique tourne en C3** (`12a04e9`) — sain, en prod. C3 prouvé live :
  une décision faite depuis le Mac atterrit sur le VPS et est **vue depuis le PC**
  qui lit le VPS. Zéro split. ✅
- **C4–C8 est committé mais pas déployé** — le canonique n'a donc PAS encore le
  retrait d'event-log ni le schéma modifié. **Ne déploie C4–C8 qu'après les 2 fix
  MAJOR** (§5).

### Ce qui est fait, chunk par chunk
- **C2a** : décisions funnel + lot sur l'image lean du VPS (`serving/funnel_writes.py`,
  `store/decisions.py`, scope `review:write`).
- **C2b** : `POST /ingest/crops` (géométrie recrop, `store/crops.py`, `ingest:write`).
- **C3** : lecture funnel depuis le VPS (`store/funnel.py`, `serving/lab_read_routes.py`,
  scope `lab:read`) + overlay Dino calculé LOCAL et mergé par asset_id côté front +
  `POST /ingest/faces` (le scan Dino forwarde ses verdicts face au VPS) + reassign :
  le dismiss intrus est un overlay LOCAL (retiré de la connexion VPS).
- **C4** : le compute lourd (GPU, local) forwarde ses résultats au VPS au lieu d'un
  `UPDATE` local (`client/ingest.py`, `/ingest/crops|run|dino`). Fallback Model A
  local seulement sans `EURIO_API_URL`.
- **C5** : plomberie réplique read-only (`store/connection.py`, `resolve_db_readonly`).
  ⚠️ **pas branchée** (voir §5).
- **C6** : **retrait de l'event-log mort** — `client/sync.py`, `store/sync_replay.py`,
  `store/hlc.py`, `serving/sync_{routes,worker,local_routes}.py`, colonnes sync du
  schéma, badge front, tests_sync. **Gardé** : `client/replica.py` + `GET /db/replica`
  (lecture réplique), `image_state_events` (audit), `store/events.py` emit_* (audit).
- **C7** : migrations one-shot gardées VPS-only (`scripts/_vps_only_guard.py`).
- **C8** : `walkthrough-tests.md` réécrit pour Direction A.

## 4. Preuves de vérif (déjà faites, ne pas refaire)
- Front validé **à la main par le PO** : Mac + PC affichent les mêmes infos du
  Jeu d'entraînement.
- C3 live : Mac POST training-eligible → VPS canonique change → **PC lisant le VPS
  voit le changement** → revert net-zéro. `/ingest/faces` live.
- C4–C8 : lean-safe (modules unconditionnels 0 dep lourde), imports intacts,
  +27 tests, **pytest 1322 passed / 18 reds préexistants / 0 régression**, front
  `vue-tsc` clean.

## 5. LE TRAVAIL DE CETTE SESSION (dans l'ordre)

Détail complet dans **`c4-c8-known-gaps.md`**. Résumé :

1. **MAJOR — les suppressions ressuscitent.** `serving/crop_edit.py::delete_crop`
   ne propage plus le delete au VPS (C6 a retiré le tombstone, C4d a câblé le
   recrop mais pas le delete). Un delete Mac revient au prochain `pull-replica`.
   → Ajouter `DELETE /ingest/assets/{id}` + forward depuis `delete_crop` quand
   `sync_enabled()`.
2. **MAJOR — C5 read-only pas enforced.** La plomberie existe + est testée mais
   aucun Store applicatif ne l'utilise. → Brancher `resolve_db_readonly()` sur les
   Store côté compute/funnel Mac/PC (mode client), VPS en écriture.
3. **C4d partial** — finir la couverture `/ingest/dino` (tous les écrivains de
   prédictions Dino forwardent).
4. **Déployer C4–C8 sur le VPS** (après 1–3) : `cd /opt/eurio && git pull` puis
   `cd infra/eurio-api && direnv exec /opt/eurio docker compose up -d --build`.
   ⚠️ touche le schéma (retrait colonnes sync) + retire `/db/events` + le worker.
   Health-check après (`/healthz` 200, `docker logs eurio-api` → « serve-role prêt »,
   les routes existent = 401 pas 404).
5. **Nettoyer les 3 commits `WIP` poussés** (décision PO) — force-push (impacte le
   PC) ou les laisser.

## 6. Outils & accès (pour la nouvelle session)

### VPS (canonique + déploiement)
- SSH : **`ssh serverOimNixDontpanic`** (176.9.107.216, port custom). NB : un
  warning `bind [127.0.0.1]:8080` peut apparaître (tunnel) — bénin, ignorer.
- Repo VPS : **`/opt/eurio`** (branche `sources-jo-wikipedia`, remote origin =
  codeberg). Pull pour déployer.
- Canonique : `docker exec eurio-api python -c "import sqlite3; ..."` →
  **`/var/lib/eurio/eurio.db`** (dans le conteneur `eurio-api`).
- API publique : `https://eurio-api.musubi.dev` (Traefik + auth OBLIGATOIRE).
- **Déploiement** : `cd /opt/eurio/infra/eurio-api && direnv exec /opt/eurio docker
  compose up -d --build`. ⚠️ **`sops` n'est PAS dans le PATH ssh nu** → `direnv
  exec /opt/eurio` charge le devShell nix (qui a sops) + décrypte les secrets.
- Image lean : le Dockerfile copie SEULEMENT `serving/store/client/shared/jobs/
  referential/review` — **PAS `training/`**. Tout module monté sur le lean doit
  être cv2/torch/numpy-free ET ne rien importer de `training/sources/vision/scan`
  au top-level (sinon crash conteneur — `lab_read`/`funnel_writes`/`ingest` sont
  montés INCONDITIONNELLEMENT). Vérif lean-safety AVANT deploy (cf. friction-log).

### PC (vérif multi-machine)
- SSH : **`ssh pc`** = `raphael@192.168.1.163` (NixOS `desktop`, LAN). ⚠️ **DHCP
  dynamique** — si l'IP a changé : `ip -4 addr` sur le PC ou `desktop.local`
  (avahi), puis maj `~/.ssh/config` Host `pc`. Clé `~/.ssh/Oim_M4` (dans l'agent).
- Repo PC : **`~/Documents/Musubi42/Eurio`** (⚠️ **SANS `bizz/`** — diffère du Mac).
- Charger l'env PC (secrets) : `cd ~/Documents/Musubi42/Eurio && direnv exec . <cmd>`
  (fournit `EURIO_API_URL` + `EURIO_API_TOKEN`).

### Mac (machine pilote)
- Repo : `/Users/musubi42/Documents/Musubi42/bizz/Eurio`.
- Env : `EURIO_API_URL=https://eurio-api.musubi.dev`, `EURIO_API_TOKEN` = PAT
  (49 char, prefix `eurio_`) — **owner/admin/reviewer, TOUS les scopes**
  (`review:write`, `ingest:write`, `lab:read`, …). Même token sur le PC (via SOPS).

## 7. Pièges connus (voir `friction-log.md` pour les 21) — les plus mordants
- **zsh + heredoc** : les python inline avec `\n`/quotes imbriquées cassent
  (`parse error near \n`, quotes mangées via ssh) → **écris les scripts dans
  `/tmp/x.py` et lance-les**. Récurrent, fais-le d'emblée.
- **db_migrate** : `serving.server_serve` ne boote pas sur une DB neuve (suppose
  le canonique existant) → pour un smoke, `cp state/eurio.db /tmp/x.db` +
  `EURIO_DB_PATH=/tmp/x.db`.
- **19 tests rouges PRÉEXISTANTS** (benchmark ModuleNotFound, normalize_listing,
  wipe_referential, orchestrator, eurio_referential, ingest FK) = bruit. Pour
  affirmer « 0 régression » : compare A/B via `git stash` (baseline vs tes edits).
- **go-task** marche depuis n'importe quel sous-dossier (fix : `ml/tasks.yml`).
- **Autonomie workflow** : un agent a déjà committé+poussé des commits « WIP » sans
  autorisation. Si tu lances un workflow, surveille `git log`/`git status` après.

## 8. Docs de référence (toutes dans `docs/work-in-progress/local-sync/`)
- `migration-direction-a.md` — le plan (§1 verdict d'échec, §4 inventaire des
  écrivains, §5 chunks avec statut C0→C8).
- `c4-c8-known-gaps.md` — les 2 MAJOR + C4d + runbook deploy. **← le TODO du jour.**
- `friction-log.md` — 21 frictions en 7 catégories (backlog de cleaning).
- `README.md` — verdict d'échec de l'event-log (archi abandonnée).
- `walkthrough-tests.md` — le flux Direction A (setup machine, décision, reprise).
- Mémoire agent : `project-sync-direction-a-single-writer` (fil complet).
