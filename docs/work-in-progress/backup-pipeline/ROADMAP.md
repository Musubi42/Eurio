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
| 3 | Miroir MinIO + invariants inter-stores | ✅ | 2026-08-15 |
| 4 | Duplicati + timer NixOS | ✅ | 2026-08-16 |
| **5** | Kuma ×4 + healthchecks.io | 🟡 **code fait, monitors à créer** | |
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

## Lot 3 — Miroir MinIO et cohérence inter-stores ✅ **2026-08-15**

- [x] `rclone sync` des buckets vers `staging/minio/`, **après** le snapshot des bases
- [x] Inclusion du bucket `eurio-db` tranchée — cf. [D-20](./DECISIONS.md)
- [x] Invariants 4 (dangling), 5 (objets non décroissants), 6 (échantillonnage sha)
- [x] Exclusion des 546 chemins absolus et des 10 lignes `mock/` — vérifiée sur données
      réelles : `dangling == 0` sans exclusion manuelle
- [x] Échantillonnage aléatoire de 20 objets
- [x] 🔴 **Question tranchée** : `bootstrap.sh` recrée bien users, policy et ACLs
      (cf. [`RESTAURATION.md`](./RESTAURATION.md) §3)
- [x] Impact disque mesuré

**Critère de fin atteint**, sur données réelles :

```
✅ [3] image_assets  ↔ enrichment-crops : aucun dangling
       11 157 références résolues, 1 841 orphelins
✅ [3] source_images ↔ enrichment-raws  : aucun dangling
       13 989 références résolues, 3 140 orphelins
✅ [5] objets MinIO non décroissants — 33 953 objets sur 4 buckets
✅ [6] échantillon miroir ≡ sha256 de la base — 20 objets sur 13 989 vérifiables
```

Les chiffres reproduisent **exactement** la mesure manuelle du 2026-08-14
([`DONNEES.md`](./DONNEES.md) §2). L'invariant propre à Eurio est opérationnel.

**Découverte de l'invariant 6** : il valide empiriquement que `source_images.sha256`
**est bien le sha256 du contenu de l'objet** — hypothèse sur laquelle reposait tout
l'invariant, et qui n'avait jamais été vérifiée. 20 objets tirés au hasard, 20 conformes.

**Volumétrie mesurée** :

| | Objets | Taille |
|---|---|---|
| `enrichment-raws` | 17 129 | 5,3 Go |
| `enrichment-crops` | 12 998 | 1,1 Go |
| `numista-canonical` | 3 824 | 90 Mo |
| `eurio-db/transfers/` | 2 | 105 Mo |
| **staging total** | **33 953** | **6,6 Go** |

Disque : `/` passe de 78 % à **80 %**, 78 Go libres. Premier `sync` : **12 min 50**.
Les suivants sont incrémentaux. Un garde-fou refuse de miroiter sous 10 Go libres.

**Ordre vérifié dans le manifeste** : `t1_databases 21:15:22Z` → `t2_minio 21:28:08Z`.
Le référençant avant le référencé.

---

## Lot 4 — Duplicati et timer NixOS ✅ **2026-08-16**

> ### ✅ Prérequis levé le 2026-08-15 : les 10 jobs Duplicati sont réparés
> Basculés du WebDAV Basic Auth vers le backend pCloud natif en OAuth
> (cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §3).

### 4a — Compose Duplicati ✅

- [x] Copie horodatée de `compose.yaml` + ré-export des 10 configs par l'API
- [x] Bind `/opt/eurio/infra/backup/staging:/eurio-source:**ro**` — lecture seule
      ([D-23](./DECISIONS.md))
- [x] Correction de casse `oim-Beszel` → `oim-beszel` dans la même édition
- [x] `docker compose config` puis recréation du conteneur
- [x] **Les 10 jobs ont survécu** : mêmes IDs, mêmes destinations, mêmes bases
      locales, mêmes planifications

**Preuve immédiate de la correction de casse** : Beszel a examiné **10 fichiers et
envoyé 727 575 octets**, contre `ExaminedFiles: 0` sur tous ses runs depuis
novembre 2025.

### 4b — Job Duplicati « Eurio » ✅

- [x] Job **ID 17**, destination
      `pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/Eurio`
- [x] Source `/eurio-source/`, chiffrement AES, **même passphrase que les 10 autres**
      (un seul secret à protéger, cohérent avec le reste)
- [x] **`keep-time = 30D`** et non `keep-versions` : une borne *temporelle* définit
      « combien de temps j'ai pour détecter une corruption » ([D-05](./DECISIONS.md))
- [x] Planifié `1D` à 03:00 UTC, comme les 10 autres
- [ ] `--send-http-url` vers Kuma — **reporté au lot 5**, le monitor n'existe pas encore

### 4c — Ordonnancement NixOS 🟡 construit et validé, **pas encore activé**

- [x] `nix/eurio-vps.nix` réécrit : `eurio-backup-stage` (02:00 UTC) et
      `eurio-backup-verify` (02:30 UTC), deux unités **séparées**
- [x] **`systemd.services.eurio-minio` supprimé** — son `ExecStop` faisait
      `docker compose down` : tout `systemctl stop` ou toute désactivation future du
      module aurait coupé MinIO, et avec lui `eurio-api`, `eurio-review` et le miroir
- [x] Import par **input flake** et non par chemin absolu — la méthode documentée
      depuis juin était **inapplicable** ([D-22](./DECISIONS.md))
- [x] `nixos-rebuild build` **réussi**, diff de closure vérifié
- [x] ✅ **`nixos-rebuild switch` fait le 2026-08-16** — les deux timers sont armés :
      `eurio-backup-stage.timer` → 04:00 CEST (02:00 UTC),
      `eurio-backup-verify.timer` → 04:30 CEST (02:30 UTC)

**Diff de closure vérifié** — rien de retiré sur un VPS à 60+ conteneurs :

```
rclone: ∅ → 1.74.4, 99.2 MiB
unit-eurio-backup-stage.service   ∅ → ε
unit-eurio-backup-stage.timer     ∅ → ε
unit-eurio-backup-verify.service  ∅ → ε
unit-eurio-backup-verify.timer    ∅ → ε
```

**Activation confirmée** :

```
NEXT                          LEFT       UNIT
Sun 2026-08-16 04:00:00 CEST  3h 52min   eurio-backup-stage.timer
Sun 2026-08-16 04:30:00 CEST  4h 22min   eurio-backup-verify.timer
```

**Première sauvegarde Eurio** : `Success`, 33 957 fichiers / 6,47 Gio examinés,
**5,61 Gio poussés en 8 min 59**, 0 erreur, 0 avertissement.

Retours arrière préparés : `/etc/nixos/flake.nix.bak-20260815`,
`/etc/nixos/configuration.nix.bak-20260815` (non modifié au final),
`/opt/stacks/oim-duplicati/compose.yaml.bak-20260815-234703`.
`/etc/nixos` est un dépôt git : `git diff` y montre exactement les deux ajouts.

**Critère de fin** : **3 nuits consécutives vertes**, staging + verify + job Duplicati.
Une seule nuit ne prouve rien.

---

## Lot 5 — Alerting 🟡 **2026-08-16 — code fait, monitors à créer**

**Fait** :

- [x] Plomberie `notify()` dans `eurio-backup.sh` — battement de cœur vers un push
      monitor, jamais l'état complet : c'est Kuma qui possède l'alerte ([D-06](./DECISIONS.md))
- [x] `stage` notifie sous **trap** : le signal part même si le script meurt en cours de
      route. Sans ça, un échec au milieu ne produirait aucun signal, et le silence est
      indiscernable du succès
- [x] `verify` notifie up/down, et ne pingue healthchecks.io **que si tout est vert** —
      son silence doit vouloir dire « quelque chose ne va pas », jamais « ça a tourné
      mais les données sont mauvaises »
- [x] Un anneau non configuré est **signalé bruyamment** à chaque exécution, jamais tu sous silence
- [x] Une notification injoignable ne fait **jamais** échouer la sauvegarde, mais le dit
- [x] `notify.conf.example` + `notify.conf` gitignoré (les URLs portent des jetons)
- [x] Commande `notify-test` : envoie un `down` réel sur chaque anneau

**Reste** — détail dans [`HANDOFF-NEXT-SESSION.md`](./HANDOFF-NEXT-SESSION.md) :

- [ ] Créer 4 push monitors Kuma *(humain, ~3 min)* — pas de création par API dans Kuma,
      et écrire dans `kuma.db` sur un service partagé en production serait le raccourci
      que R0 interdit
- [ ] Créer le compte healthchecks.io *(humain)*
- [ ] Remplir `notify.conf`
- [ ] `--send-http-url` + `--send-http-level=all` sur le job Duplicati « Eurio »
      (**anneau 3** — le plus important, cf. [D-16](./DECISIONS.md))

**Critère de fin** : `notify-test` provoque un échec qui **arrive effectivement sur
Discord**. Un canal d'alerte non testé est une alerte qui n'existe pas — les 10 jobs
criaient dans une interface sans lecteur depuis neuf mois.

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
