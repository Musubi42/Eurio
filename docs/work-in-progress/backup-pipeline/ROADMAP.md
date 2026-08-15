# Roadmap — 8 lots

> Chaque lot est **vérifiable seul** et laisse le système dans un état sain. L'ordre
> n'est pas négociable : il applique la leçon du 2026-08-14 — on ne construit pas de
> surface avant d'avoir le moyen de la vérifier.

## Statut global

| Lot | Description | Statut | Date |
|---|---|---|---|
| 0 | Copie manuelle immédiate hors site | ✅ | 2026-08-15 |
| 1 | `eurio-backup.sh stage` + `manifest.json` | ✅ | 2026-08-15 |
| 2 | Suite d'invariants (niveaux 1-2-3) | ✅ | 2026-08-15 |
| **3** | Miroir MinIO + invariants inter-stores | ⬜ **next** | |
| 4 | Duplicati + timer NixOS | ⬜ | |
| 5 | Kuma ×3 + healthchecks.io | ⬜ | |
| 6 | Restauration + premier exercice à froid | ⬜ | |
| 7 | Décommissionnement de l'ancien chemin pCloud | ⬜ | |

---

## Lot 0 — La copie la plus bête qui marche ✅ **2026-08-15**

**Pourquoi maintenant** : la dernière copie de `eurio.db` datait du 17 juin, `review.db`
n'avait **jamais** été sauvegardé. Une sauvegarde imparfaite qui existe bat une
sauvegarde parfaite qui n'existe pas.

- [x] `VACUUM INTO` sur `eurio.db` (155,6 → 144,1 Mo après compaction) et `review.db`
- [x] sha256 des deux + `manifest.json` (comptages de 12 + 4 tables)
- [x] Copie hors site **chiffrée** → `pcloud_crypt:lot0-manuel-20260815/`
      (= `pcloud:backups/serverOimNix/Eurio/lot0-manuel-20260815/`)
- [x] Manifeste déposé **aussi en clair** hors crypt, lisible sans la clé
- [x] Vérifié **depuis la destination** : re-téléchargement complet, sha256 conformes,
      `integrity_check` ok, `foreign_key_check` à 0, comptages identiques

**Résultat** :

| | `eurio.db` | `review.db` |
|---|---|---|
| Taille | 144 056 320 o | 950 272 o |
| sha256 | `2f0fbb7bffba33…` | `9c972f074e55a6…` |
| `integrity_check` | ok | ok |
| Violations FK | 0 | 0 |

Chiffrement confirmé côté stockage : les octets bruts sur pCloud commencent par
`52 43 4c 4f 4e 45` (en-tête rclone crypt), pas par `53 51 4c 69 74 65` (« SQLite »).

**Ce que ce lot a produit en plus de la copie** : le format de `manifest.json` — date,
tailles, sha256, `integrity_check`, violations FK, comptages par table. C'est la graine
du manifeste du lot 1 et de l'invariant de non-décroissance du lot 2, écrite en la
faisant plutôt qu'en la spécifiant.

**Chiffres de référence figés le 2026-08-15** (base de comparaison pour l'invariant 3) :

```
coins 689 · image_assets 11162 · source_images 15991 · review_queue 10663
consensus_verdicts 8484 · coin_observations 10626 · image_state_events 22968
coin_descriptions_i18n 11345 · mint_release_prices 12161 · training_runs 34
coin_canonical_images 1924 · _schema_migrations 5
review.db : review_items 575 · decisions 3 · reviewers 1 · meta 1
```

> ⚠️ Cette copie dépend de la clé age de `~/.config/eurio-backup/age-key.txt`. Sa
> récupérabilité relève de la session « secrets » (D-09). Elle **ne remplace pas** le
> dispositif automatisé — c'est un filet ponctuel, non répété, qui vieillira.

---

## Lot 1 — `eurio-backup.sh stage` ✅ **2026-08-15**

Refactorisation, pas réécriture (cf. [`ARCHITECTURE.md`](./ARCHITECTURE.md) §6).

- [x] **Gitignorer `infra/backup/staging/` — EN PREMIER** (voir l'encadré ci-dessous)
- [x] `cmd_run` → `cmd_stage`, écriture dans `infra/backup/staging/`
- [x] Ajouter **`review.db`**, en nommant explicitement `infra/review/data/review.db`
      et **pas** le résidu de `infra/eurio-api/data/`
- [x] Écriture atomique : produire dans `staging.tmp/` puis `mv`, ou déposer
      `manifest.json` **en dernier** comme sentinelle
- [x] Produire `manifest.json` : `t1` (DB), `t2` (MinIO), sha256, comptages par table,
      version de schéma, `mtime` des sources (invariant 8)
- [x] Retirer `cmd_keygen`, `cmd_upload_readme`, la logique `rclone crypt`
- [x] Trancher le sort de `cmd_verify` (= niveau 1 déjà écrit, à récupérer au lot 2) et
      de `cmd_rclone`
- [x] Garder le self-reexec `nix shell` (portabilité)
- [ ] Nettoyer les 8 sauvegardes ad hoc de `infra/eurio-api/data/` (~640 Mo)
      — **non fait volontairement** : suppression irréversible de données, décision du PO

**Livré** : `eurio-backup.sh` (`stage` / `verify`) + `build_manifest.py`.
Le `.gitignore` a été posé **avant** la première exécution : les 139 Mo de staging
n'apparaissent pas dans `git status` (vérifié).

**Critère de fin atteint** : `staging/` contient les deux bases et un `manifest.json`
lisible ; trois exécutions successives donnent le même résultat (idempotence vérifiée).
Le `VACUUM INTO` s'exécute dans les conteneurs `eurio-api` et `eurio-review` puis
`docker cp` ; un `flock` empêche deux `stage` concurrents.

---

## Lot 2 — La suite d'invariants ✅ **2026-08-15**

**Avant** d'élargir la surface sauvegardée. C'est délibéré et c'est le cœur de la
correction d'erreur : en juin on a construit le transport sans le moyen de le vérifier.

- [x] Script autonome, exécutable sur n'importe quel `staging/` ou stack restaurée
- [x] Invariants 1, 2, 3, 7 de [`VERIFICATION.md`](./VERIFICATION.md) §3
- [x] **Figer la liste des ~15 tables surveillées** pour la non-décroissance
- [x] Comparaison au `manifest.json` précédent, avec tolérance et acquittement humain
      sur décroissance
- [x] Code de retour ≠ 0 et message exploitable en cas d'échec

**Livré** : `verify_invariants.py` + `test_verify.sh` + tâches `go-task backup:*`.

**Critère de fin atteint — 9 cas, 0 en défaut** (`go-task backup:test`) :

| # | Cas | Attrapé par |
|---|---|---|
| 0 | staging **sain** accepté | *contrôle* — sans lui, un script qui échoue toujours passerait |
| 1 | base tronquée (100 → 0 lignes) | non-décroissance |
| 2 | base **vide mais structurellement parfaite** | pièce canari (`integrity_check` répond `ok` !) |
| 3 | migrations du dépôt non appliquées | comparaison à `ml/serving/migrations/` |
| 4 | fichier modifié après le manifeste | sha256 ≡ manifeste (atomicité) |
| 5 | staging figé | fraîcheur |
| 6 | manifeste absent (`stage` interrompu) | sentinelle |
| 7 | base absente du staging | présence |
| 8 | `--accept-baseline` lève la décroissance, et elle seule | acquittement humain |

**Vérifié aussi sur les données réelles** : une suppression de 3 554 lignes de
`review_queue` (10 663 → 7 109) fait échouer **deux** invariants indépendants — la
non-décroissance *et* `foreign_key_check` (147 violations). Deux angles, même dégât.

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
