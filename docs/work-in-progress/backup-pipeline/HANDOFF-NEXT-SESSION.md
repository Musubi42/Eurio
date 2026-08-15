# Handoff — prochaine session

> Écrit le 2026-08-14, mis à jour le 2026-08-15. **Lots 0, 1 et 2 livrés.** La panne
> Duplicati découverte en chemin a été réparée. Rien n'est encore ordonnancé.

## Où on en est

- Étude des données faite et mesurée ([`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md),
  [`DONNEES.md`](./DONNEES.md)).
- Architecture arbitrée, **19 décisions** consignées ([`DECISIONS.md`](./DECISIONS.md)).
- 8 lots découpés avec critères de fin ([`ROADMAP.md`](./ROADMAP.md)).
- **Duplicati réparé** (10 jobs, transport OAuth) — le prérequis du lot 4 est levé.
- **Lots 0-1-2 livrés** : copie hors site, `stage` + manifeste, suite d'invariants avec
  son test négatif. 11 invariants verts sur les données réelles, 9 cas négatifs détectés.
- Reste intact : **aucun `nixos-rebuild`, aucun compose modifié, aucun ordonnancement.**

## ✅ Fait le 2026-08-15 — Duplicati réparé

Les 10 jobs sont passés du WebDAV Basic Auth au backend pCloud natif OAuth, et ont tous
tourné avec succès. Détail : [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §3.

| # | Vérification restante | Priorité |
|---|---|---|
| 0a | **Contrôler la passe automatique de 03:00 UTC** — c'est elle qui prouve que ça tient sans intervention humaine | 🔴 lendemain matin |
| 0b | Acquitter les **456 erreurs + 468 avertissements** dans `duplicati.musubi.dev` | après 0a |
| 0c | Supprimer `/opt/stacks/oim-duplicati/api-config-export-20260815/` — contient les **identifiants WebDAV en clair** | après 0a |

## Actions humaines requises — bloquantes

| # | Action | Bloque |
|---|---|---|
| 1 | **Créer le compte healthchecks.io** et brancher sa notification sur Discord — un compte externe, ça ne peut pas se faire depuis le VPS | Lot 5 |
| 2 | **Valider l'édition de `/opt/stacks/oim-duplicati/compose.yaml`** — ajout du bind `/opt/eurio/infra/backup/staging` **et** correction de casse `oim-Beszel` → `oim-beszel`, puis recréation du conteneur. Hors dépôt Eurio, sur une stack partagée | Lot 4 |

> **Lots 0 à 3 faits le 2026-08-15.**
> Lot 0 : copie chiffrée des deux bases dans `pcloud_crypt:lot0-manuel-20260815/`,
> vérifiée depuis la destination — un filet ponctuel qui vieillira, pas un dispositif.
> Lots 1 à 3 : `go-task backup:stage` / `backup:verify` / `backup:test`. Staging de
> 6,6 Go (bases + miroir MinIO), **16 invariants verts** sur les données réelles dont
> `dangling == 0`, et **20 cas négatifs** détectés.
> **Rien n'est encore ordonnancé** : `stage` et `verify` se lancent à la main jusqu'au
> lot 4.

## Actions humaines requises — non bloquantes

| # | Action | Quand |
|---|---|---|
| 3 | Confirmer que `infra/minio/secrets` et `infra/review/secrets` sont couverts par la session « secrets » | Avant le lot 6 |
| 4 | Décider du sort du volume Docker anonyme de `eurio-scrape-tor` (clés d'identité Tor) | Avant le lot 7 |
| 4 | Ouvrir des tickets pour les trois sauvegardes incomplètes : Traefik/`acme.json` (permissions), Immich (photothèque non montée), Authentik (`pg_dump` figé depuis nov. 2025). Cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §8 | Hors chantier |

> **Résolus** : la rétention est `keep-versions = 30` (lue en clair, pas 30 jours) ·
> la destination pCloud est `Applications/DuplicatiBackup/Oim/<Service>`, confirmée par
> l'inspection et par les 10 jobs réparés.

## Ordre d'exécution proposé pour la prochaine session

**Lot 4** — le premier qui touche la production. Trois opérations distinctes, à ne pas
mélanger :

1. **Éditer `/opt/stacks/oim-duplicati/compose.yaml`** — ajouter le bind
   `/opt/eurio/infra/backup/staging` **et** corriger `oim-Beszel` → `oim-beszel`.
   Copie horodatée du compose et de `appdata-test` avant, `docker compose config` pour
   valider, puis recréation du conteneur, puis vérifier que les 10 jobs sont toujours là.
2. **Créer le job Duplicati « Eurio »** — destination
   `pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/Eurio?authid=…`,
   `keep-time` explicite, `--send-http-url` vers Kuma.
3. **Réorienter et importer `nix/eurio-vps.nix`** — `stage` à 02:00 UTC, `verify` à
   02:30. ⚠️ Retirer `systemd.services.eurio-minio` d'abord (son `ExecStop` couperait
   MinIO), et `nixos-rebuild build` avant le `switch`.

Puis **lot 5** (alerting), à ne pas enchaîner dans la même session.

## Pièges identifiés, à ne pas redécouvrir

| Piège | Détail |
|---|---|
| 🔴 **Duplicati ne voit pas `/opt/eurio`** | 14 binds, tous sous `/opt/stacks`. Aucun job Eurio n'est possible sans ajouter un montage et **recréer le conteneur** |
| 🔴 **Deux `review.db`** | Le vrai est `infra/review/data/review.db` (954 368 o, `reviewers` + 575 items). Celui de `infra/eurio-api/data/` (49 152 o) est un **résidu** sans table `reviewers` |
| 🔴 **`staging/` contient des DONNÉES** | Gitignoré depuis le lot 1, donc invisible dans `git status` — mais un `git clean -xdf` le détruit quand même (branche `repo-cleanup` !). Jusqu'à 6,5 Go au lot 3 |
| **`systemd.services.eurio-minio`** | Son `ExecStop = docker compose down` fait de tout `systemctl stop` ou de toute désactivation du module un **arrêt de MinIO**. À retirer ou neutraliser avant l'import — le `ExecStart` n'est pas le risque |
| **`nixos-rebuild` sur ce VPS** | 60+ conteneurs en production. `nixos-rebuild build` ou `dry-activate` **avant** le `switch` |
| **Fenêtre horaire** | Duplicati démarre à 03:00 UTC ; en régime sain les 10 jobs prennent **6 minutes**. Les horaires de 04:59 visibles aujourd'hui sont des horaires de panne — ne pas dimensionner dessus. D'où 02:00 / 02:30 |
| **Premier `rclone sync`** | 6,43 GiB depuis MinIO, transfert local, quelques minutes. Les suivants sont incrémentaux |
| **Course staging ↔ Duplicati** | Traité au lot 1 : `flock` contre deux `stage` concurrents, et `manifest.json` écrit en dernier comme sentinelle (son sha détecte un fichier modifié après lui) |
| **`.minio.sys/` n'est pas dans le miroir** | Users IAM, service accounts, policies. On **suppose** que `bootstrap.sh` les recrée — non vérifié, à faire au lot 3 |
| **Deux archives pCloud du 17 juin** | `pcloud:backups/serverOimNix/Eurio` **et** `pcloud:eurio-backup`. N'en traiter qu'une laisse une orpheline |
| **`VACUUM INTO`** | S'exécute **dans** les conteneurs `eurio-api` et `eurio-review` puis `docker cp`. Traité au lot 1 |
| **Ne pas restaurer les `-wal` / `-shm`** | `VACUUM INTO` produit une base autonome ; restaurer des fichiers WAL à côté est une source de corruption |
| **L'invariant `dangling == 0` naît rouge** | Sans exclusion des 546 chemins absolus et des 10 lignes `mock/`. L'exclusion est déjà codée (`EXCLUDED_PREFIXES`), non testée sur données réelles avant le lot 3 |
| **Ne pas supprimer l'archive du 17 juin** | Avant le lot 6. C'est la seule copie hors site existante |

## Chiffres de référence, mesurés le 2026-08-14

À recomparer à chaque étape pour détecter une dérive.

```
eurio.db          155 648 000 o   mtime 2026-07-12   80 tables applicatives
review.db         954 368 o       infra/review/data/  (review_items 575)
                  49 152 o        infra/eurio-api/data/  ← RÉSIDU, ne pas utiliser
MinIO (API S3)    6,430 GiB       33 956 objets sur 4 buckets
  enrichment-raws      17 129 obj / 5,168 GiB
  enrichment-crops     12 998 obj / 1011,811 MiB
  numista-canonical     3 824 obj / 78,678 MiB
  eurio-db                  5 obj / 201,760 MiB
Cohérence         dangling réel = 0   (556 exclus : 546 chemins Mac + 10 mock)
                  orphelins = 4 981
Disque            /opt/eurio 9,0 Go   ·   85 Go libres   ·   78 %
pCloud            2 TiB total   ·   1,191 TiB libres
Archives juin     pcloud:backups/serverOimNix/Eurio   3,842 GiB / 21 661 obj
                  pcloud:eurio-backup                 3,841 GiB / 21 661 obj
                  déchiffrables toutes deux   ·   2026-06-17
Duplicati         dernier succès 2026-05-25   ·   401 depuis 2026-05-26
                  keep-versions = 30 (versions, pas jours)   ·   456 erreurs
```

## Question tranchée le 2026-08-15

**Le miroir MinIO doit-il inclure le bucket `eurio-db` ?** Oui pour ses artefacts ML
(`transfers/`, 105 Mo, issus de runs d'entraînement), **non** pour sa copie de `eurio.db`
figée au 29 juin — doublon périmé et piège de restauration. Détail :
[`DECISIONS.md`](./DECISIONS.md) D-20.
