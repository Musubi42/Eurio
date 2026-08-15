# Roadmap — 8 lots

> Chaque lot est **vérifiable seul** et laisse le système dans un état sain. L'ordre
> n'est pas négociable : il applique la leçon du 2026-08-14 — on ne construit pas de
> surface avant d'avoir le moyen de la vérifier.

## Statut global

| Lot | Description | Statut | Date |
|---|---|---|---|
| **0** | Copie manuelle immédiate hors site | ⬜ **next** | |
| 1 | `eurio-backup.sh stage` + `manifest.json` | ⬜ | |
| 2 | Suite d'invariants (niveaux 1-2-3) | ⬜ | |
| 3 | Miroir MinIO + invariants inter-stores | ⬜ | |
| 4 | Duplicati + timer NixOS | ⬜ | |
| 5 | Kuma ×3 + healthchecks.io | ⬜ | |
| 6 | Restauration + premier exercice à froid | ⬜ | |
| 7 | Décommissionnement de l'ancien chemin pCloud | ⬜ | |

---

## Lot 0 — La copie la plus bête qui marche

**Pourquoi maintenant** : la dernière copie de `eurio.db` date du 17 juin, `review.db`
n'a jamais été sauvegardé. Une sauvegarde imparfaite qui existe bat une sauvegarde
parfaite qui n'existe pas.

- [ ] `VACUUM INTO` sur `eurio.db` et `review.db`
- [ ] sha256 des deux
- [ ] Copie hors site *(destination à confirmer par le PO)*
- [ ] Vérifier que la copie est lisible **depuis la destination**, pas depuis la source

**Critère de fin** : une copie fraîche des deux bases existe hors du VPS, et on a ouvert
la copie distante pour le prouver.
**Coût** : ~155 Mo, quelques minutes. Aucune automatisation, aucun risque.

---

## Lot 1 — `eurio-backup.sh stage`

Refactorisation, pas réécriture (cf. [`ARCHITECTURE.md`](./ARCHITECTURE.md) §6).

- [ ] **Gitignorer `infra/backup/staging/` — EN PREMIER** (voir l'encadré ci-dessous)
- [ ] `cmd_run` → `cmd_stage`, écriture dans `infra/backup/staging/`
- [ ] Ajouter **`review.db`**, en nommant explicitement `infra/review/data/review.db`
      et **pas** le résidu de `infra/eurio-api/data/`
- [ ] Écriture atomique : produire dans `staging.tmp/` puis `mv`, ou déposer
      `manifest.json` **en dernier** comme sentinelle
- [ ] Produire `manifest.json` : `t1` (DB), `t2` (MinIO), sha256, comptages par table,
      version de schéma, `mtime` des sources (invariant 8)
- [ ] Retirer `cmd_keygen`, `cmd_upload_readme`, la logique `rclone crypt`
- [ ] Trancher le sort de `cmd_verify` (= niveau 1 déjà écrit, à récupérer au lot 2) et
      de `cmd_rclone`
- [ ] Garder le self-reexec `nix shell` (portabilité)
- [ ] Nettoyer les 8 sauvegardes ad hoc de `infra/eurio-api/data/` (~640 Mo)

> ⚠️ **Le `.gitignore` d'abord, avant la première exécution.** `infra/backup/staging/`
> n'est **pas** ignoré aujourd'hui (vérifié). Trois raisons de ne pas inverser l'ordre :
> 6,4 Go d'untracked dans `git status` ; un `git clean -xdf` détruit le staging et son
> `manifest.json` — réflexe d'autant plus probable que la branche courante s'appelle
> `repo-cleanup` ; et l'interdiction `git add -A` du CLAUDE.md devient une garde de
> sécurité pour les **données**, plus seulement pour les secrets.

**Critère de fin** : `staging/` peuplé des deux bases et d'un `manifest.json` lisible ;
la commande est idempotente (deux exécutions de suite ne cassent rien).
**Attention** : le `VACUUM INTO` s'exécute **dans** le conteneur `eurio-api` puis
`docker cp`. Le script doit échouer proprement si Docker est absent.

---

## Lot 2 — La suite d'invariants

**Avant** d'élargir la surface sauvegardée. C'est délibéré et c'est le cœur de la
correction d'erreur : en juin on a construit le transport sans le moyen de le vérifier.

- [ ] Script autonome, exécutable sur n'importe quel `staging/` ou stack restaurée
- [ ] Invariants 1, 2, 3, 7 de [`VERIFICATION.md`](./VERIFICATION.md) §3
- [ ] **Figer la liste des ~15 tables surveillées** pour la non-décroissance
- [ ] Comparaison au `manifest.json` précédent, avec tolérance et acquittement humain
      sur décroissance
- [ ] Code de retour ≠ 0 et message exploitable en cas d'échec

**Critère de fin** : le script sort en ≠ 0 sur une base **volontairement tronquée** et
sur une base au schéma désaligné. Tant que ce test négatif n'est pas fait, la suite ne
prouve rien.

---

## Lot 3 — Miroir MinIO et cohérence inter-stores

- [ ] `rclone sync` des buckets vers `staging/minio/`, **après** le snapshot des bases
- [ ] Trancher l'inclusion du bucket `eurio-db` (voir la question ouverte du HANDOFF)
- [ ] Invariants 4, 5, 6
- [ ] Exclusion propre des 546 chemins absolus et des 10 lignes `mock/`
      (cf. [`DONNEES.md`](./DONNEES.md) §4, bug n°2)
- [ ] Échantillonnage aléatoire de 20 objets, sha miroir ↔ source S3
- [ ] 🔴 **Vérifier que `bootstrap.sh` recrée les users/policies/service accounts de
      `.minio.sys/`** — le miroir ne les capture pas
      (cf. [`RESTAURATION.md`](./RESTAURATION.md) §3)
- [ ] Vérifier l'impact disque réel (attendu : `/opt/eurio` 9,0 → ~15,3 Go)

**Critère de fin** : `dangling == 0` constaté automatiquement, et le premier miroir
complet passe sans erreur.
**Attention** : le premier `sync` transfère 6,43 GiB depuis MinIO (6,23 sans
`eurio-db`) — transfert local, quelques minutes. Les suivants sont incrémentaux.

---

## Lot 4 — Duplicati et timer NixOS

> ### ✅ Prérequis levé le 2026-08-15 : les 10 jobs Duplicati sont réparés
> Basculés du WebDAV Basic Auth vers le backend pCloud natif en OAuth, avec le jeton
> rclone existant comme `authid`. Les 10 ont tourné avec succès
> (cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §3).
>
> - [x] Diagnostiquer la panne — vérification d'appareil pCloud sur Basic Auth
> - [x] Basculer les 10 jobs sur `pcloud://api.pcloud.com/…?authid=…`
> - [x] Confirmer que les jobs réussissent — 8/10 avec écriture réelle sur pCloud
> - [ ] **Vérifier la passe automatique de 03:00 UTC** — c'est elle qui prouve que ça
>       tient sans intervention
> - [ ] Acquitter les 456 erreurs / 468 avertissements
> - [ ] Supprimer `/opt/stacks/oim-duplicati/api-config-export-20260815/`
>       (contient les identifiants WebDAV en clair)

- [ ] 🔴 **Ajouter un bind `/opt/eurio/infra/backup/staging` au conteneur Duplicati** —
      il n'en a aucun aujourd'hui (14 binds, tous sous `/opt/stacks`). Édition de
      `/opt/stacks/oim-duplicati/compose.yaml` **hors dépôt Eurio** + recréation du
      conteneur, sur une stack partagée
- [ ] **Dans la même édition** : corriger `oim-Beszel` → `oim-beszel` (cf.
      [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §8.1)
- [ ] Job Duplicati « Eurio », destination
      `pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/Eurio?authid=…`
      (même AuthID que les 10 autres), source = `infra/backup/staging/`,
      **`keep-time` explicite** (pas seulement `keep-versions = 30`)
- [ ] `--send-http-url` vers le push monitor Kuma `eurio-uploaded`, avec
      `--send-http-level=all` (anneau 3)
- [ ] Réorienter `nix/eurio-vps.nix` : `run` → `stage`, quotidien **02:00 UTC**,
      + service `verify` à 02:30 UTC
- [ ] Importer le module dans `/etc/nixos/configuration.nix`
- [ ] `nixos-rebuild switch`

**Critère de fin** : **3 nuits consécutives vertes**, staging + verify + job Duplicati
**+ anneau 3 confirmant l'upload**. Une seule nuit ne prouve rien.

> ⚠️ **Précautions `nixos-rebuild`.** Cette machine héberge 60+ conteneurs (Immich,
> Vaultwarden, Authentik, Traefik, torhub…). Le module ajoute `rclone`, `age`, `curl` en
> `systemPackages` et déclare `virtualisation.docker.enable`, déjà actif.
> Faire un `nixos-rebuild build` (ou `dry-activate`) **avant** le `switch`, et vérifier
> qu'aucune option Docker n'entre en conflit avec la configuration existante.
>
> **`systemd.services.eurio-minio` doit être retiré ou neutralisé avant l'import.** Le
> risque principal n'est pas son `ExecStart` (`docker compose up -d`, idempotent) mais
> son **`ExecStop = docker compose down`** : tout `systemctl stop`, toute désactivation
> future du module, tout `nixos-rebuild` qui décide d'arrêter l'unité **coupe MinIO** —
> et donc `eurio-api`, `eurio-review` et le miroir. Le service n'apporte rien : MinIO
> tourne déjà et n'a pas demandé à être géré par systemd.

---

## Lot 5 — Alerting

- [ ] Push monitors Kuma : `eurio-staging`, `eurio-verify`, **`eurio-uploaded`**,
      `eurio-drill` (~100 j)
- [ ] Les brancher sur le canal **Musubi Discord** (déjà configuré, déjà par défaut)
- [ ] Compte healthchecks.io, ping depuis `verify` uniquement si tous les invariants
      passent
- [ ] Notification healthchecks.io → Discord

**Critère de fin** : **un échec provoqué** (couper le réseau, tronquer une base) arrive
effectivement sur Discord. Un canal d'alerte non testé est une alerte qui n'existe pas —
c'est la même erreur que le backup non branché.

---

## Lot 6 — Restauration et premier exercice

- [ ] **Mettre à jour** `infra/backup/README-RESTORE.md` d'après
      [`RESTAURATION.md`](./RESTAURATION.md) §1 — ⚠️ le fichier **existe déjà** (159
      lignes, tracké) et décrit l'ancien chemin `rclone crypt` ; il ne s'agit pas de
      l'écrire mais de le réécrire pour Duplicati
- [ ] **Premier exercice à froid**, protocole §4
- [ ] Compléter les 6 points ouverts de [`RESTAURATION.md`](./RESTAURATION.md) §3
- [ ] Corriger `README-RESTORE.md` de tout ce qui a manqué
- [ ] Noter la date ci-dessous

| Exercice | Date | Résultat | Corrections apportées |
|---|---|---|---|
| #1 | — | — | — |

**Critère de fin** : restauration réussie, invariants verts sur la stack restaurée,
document corrigé.

---

## Lot 7 — Décommissionnement

**Après le lot 6, jamais avant.**

- [ ] Retirer la logique `rclone crypt` / pCloud direct de `infra/backup/`
- [ ] Mettre à jour `infra/backup/README.md`
- [ ] Décider du sort des **deux** archives du 17 juin — `pcloud:backups/serverOimNix/Eurio`
      **et** `pcloud:eurio-backup` (cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §7).
      N'en traiter qu'une laisse une orpheline dont plus personne ne connaîtra la clé
- [x] ~~Marquer `docs/operations/backup-strategy.md` comme remplacé~~ — fait le 2026-08-14
- [ ] Retirer la clé age dédiée du backup si elle n'a plus d'usage
      *(coordination avec la session « secrets »)*

**Critère de fin** : un seul chemin de sauvegarde existe, et la documentation ne décrit
plus que celui-là.

---

## Ce qui vient après ce chantier

- **Le silence des 10 jobs Duplicati** — la solution des lots 2 et 5 est directement
  réutilisable. Eurio sert de prototype.
- **Les bugs de qualité de données** 1, 3, 4 de [`DONNEES.md`](./DONNEES.md) §4.
- **Le bucket d'artefacts ADR-004**, à ajouter au miroir quand il existera.
