# `infra/backup/` — staging et vérification de la sauvegarde Eurio

> **Duplicati est le moteur unique** : transport, chiffrement, rétention, historique.
> Ce répertoire ne parle pas au distant. Il produit un **staging** — des artefacts
> cohérents et vérifiables — que Duplicati ramasse à 03:00 UTC.
>
> Chantier et raisonnement complets :
> [`docs/work-in-progress/backup-pipeline/`](../../docs/work-in-progress/backup-pipeline/)

## TL;DR

```bash
go-task backup:stage     # snapshots VACUUM INTO des deux bases + manifest.json
go-task backup:verify    # invariants : transport, structure, plausibilité
go-task backup:test      # test NÉGATIF : la suite sait-elle dire non ?
```

## Pourquoi un staging plutôt que pointer Duplicati sur les binds

Duplicati sauvegarde des **chemins de fichiers**. Or aucune des données qui comptent
n'a le système de fichiers pour surface valide :

- `eurio.db` est une **SQLite en WAL** sous écriture — une copie fichier est corrompue,
  le journal vivant à côté de la base. D'où `VACUUM INTO`, qui produit une base
  autonome et compacte.
- MinIO stocke ses objets dans un **format interne** (`xl.meta` + parts). On ne peut pas
  calculer le sha256 d'un objet sans le réassembler : sauvegarder le répertoire brut
  rendrait toute vérification impossible. D'où le miroir par API S3 (lot 3).

## Fichiers

| Fichier | Rôle |
|---|---|
| `eurio-backup.sh` | Orchestration : `stage`, `verify` |
| `build_manifest.py` | Produit `manifest.json` — le contrat entre `stage` et `verify` |
| `verify_invariants.py` | La suite d'invariants — niveaux 1 à 3 (les 4 et 5 sont l'exercice humain) |
| `test_verify.sh` | **Test négatif** — 16 cas : 14 corruptions à détecter + 2 contrôles de non-régression |
| `README-RESTORE.md` | Procédure de restauration ⚠️ décrit encore l'ancien chemin |
| `rclone.conf.example` | Modèle de configuration rclone (remotes `minio`, `pcloud`) |

Produits, **gitignorés** :

| Chemin | Contenu |
|---|---|
| `staging/` | Ce que Duplicati sauvegarde. Jusqu'à ~6,5 Go au lot 3 |
|  `staging/baseline-manifest.json` | Référence du dernier `verify` réussi |

> ⚠️ `staging/` contient des **données**, pas des artefacts régénérables à volonté.
> Un `git clean -xdf` le détruit.

## Le manifeste, et ses trois rôles

`manifest.json` est écrit **en dernier** par `stage`. Il sert à trois choses :

1. **Sentinelle d'atomicité** — il porte le sha256 de chaque fichier qu'il décrit. Un
   staging interrompu n'a pas de manifeste ; un fichier modifié après lui produit un
   écart de sha. Dans les deux cas, `verify` refuse.
2. **Enregistrement d'intégrité** — sha256, `integrity_check`, violations de clés
   étrangères, au moment de la capture.
3. **Base de comparaison** — comptages par table, pour l'invariant de non-décroissance.

## L'ordre de capture n'est pas cosmétique

`stage` capture **les bases d'abord, le miroir MinIO ensuite**.

`eurio.db` référence des objets MinIO (`image_assets.storage_path`,
`source_images.storage_path`) sans transaction commune. Le décalage entre les deux
snapshots est inévitable, mais il n'est pas symétrique :

| Ordre | Effet du décalage | Verdict |
|---|---|---|
| MinIO puis bases | la base référence des objets absents du miroir → **dangling** | ☠️ corruption silencieuse |
| **Bases puis MinIO** | le miroir est un sur-ensemble → **orphelins** | ✅ bénin |

On capture donc toujours le store **référençant** avant le store **référencé**.
À la restauration, c'est l'inverse : les objets d'abord, les bases ensuite.

## Vérifier, et savoir dire non

`verify` ne se contente pas d'un code de retour. Il calcule — **jamais ne lit** — les
propriétés qui distinguent « la sauvegarde a marché » de « la sauvegarde est bonne » :

- sha256 recalculé ≡ manifeste ;
- `integrity_check` et `foreign_key_check` sur les deux bases ;
- migrations appliquées ≡ migrations du dépôt (`ml/serving/migrations/`) ;
- **non-décroissance** des 17 + 4 tables surveillées, contre la référence précédente ;
- une **pièce canari** se résout (`coins` → noms → images canoniques) ;
- cohérence DB ↔ MinIO, `dangling == 0` (dès le lot 3) ;
- **fraîcheur du staging** : un staging figé passe tout le reste, et n'est pas une
  sauvegarde ;
- **vivacité des sources** : si la source n'a pas bougé depuis la référence, la
  non-décroissance est vraie par construction — `verify` le **dit** au lieu d'afficher
  un ✅ qui ne couvre rien.

Trois états et pas deux : un contrôle qu'on n'a pas pu faire s'affiche ⚠️, jamais ✅.
« Aucune référence », « miroir absent », « source figée » sont des **contrôles
inopérants**, et les confondre avec des réussites est le défaut que ce chantier corrige.

Pourquoi « calculé, jamais lu » : `storage_status` vaut `'present'` sur 100 % des lignes,
**y compris sur celles qui pointent vers un objet absent**. Un invariant bâti dessus
serait un mensonge.

### Une décroissance exige un humain

Un comptage qui baisse peut être légitime (purge volontaire). `verify` échoue quand même,
et n'avance pas la référence. Après examen :

```bash
go-task backup:verify -- --accept-baseline
```

### Le test négatif est ce qui rend la suite crédible

Une suite qui ne sort jamais en erreur ne prouve rien. `go-task backup:test` fabrique
**16 stagings** volontairement cassés et exige que chacun soit détecté **sur le bon
invariant** — un cas qui rougirait pour une autre raison que celle visée serait un
invariant inopérant déguisé en test réussi.

Parmi eux : base tronquée · base **vide mais structurellement parfaite**
(`integrity_check` répond `ok`, seul le canari la rejette) · **table surveillée
supprimée** · base obligatoire absente du manifeste · migration inconnue du dépôt ·
migration partiellement appliquée · fichier altéré après le manifeste · staging périmé ·
sources figées · base réellement corrompue (doit rougir, pas produire un traceback).

Plus deux contrôles de non-régression : un staging sain **doit** passer — sinon un
script qui échoue toujours réussirait tous les tests — et `--accept-baseline` ne doit
jamais absoudre autre chose qu'une décroissance.

## État — 2026-08-15

| Lot | | |
|---|---|---|
| 1 | `stage` + manifeste | ✅ |
| 2 | Invariants + test négatif | ✅ |
| 3 | Miroir MinIO + cohérence inter-stores | ⬜ |
| 4 | Job Duplicati + timer NixOS | ⬜ |
| 5 | Alerting Kuma + healthchecks.io | ⬜ |

**Rien n'est encore ordonnancé** : `stage` et `verify` se lancent à la main. Le timer
systemd arrive au lot 4, l'alerting au lot 5.

## Historique — l'ancien chemin

Jusqu'au 2026-08-15, ce répertoire poussait directement vers pCloud via `rclone crypt`
et une clé age dédiée (`keygen`, `run`, `verify`, `upload-readme`). Ce chemin est
**retiré** : il doublonnait Duplicati, n'a tourné qu'une fois (le 2026-06-17) et n'a
jamais été ordonnancé.

L'archive qu'il a produite reste sur pCloud et **n'est pas supprimée** avant le premier
exercice de restauration réussi (lot 6). `README-RESTORE.md` décrit encore cette
ancienne procédure — sa réécriture fait partie du lot 6.
