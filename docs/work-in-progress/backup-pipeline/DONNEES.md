# Les données d'Eurio — inventaire et cohérence inter-stores

> La difficulté d'Eurio n'est pas le volume (6,43 GiB, dérisoire), c'est que ses données
> sont **réparties sur deux stores qui se référencent mutuellement sans transaction
> commune**. Ce document établit ce qu'il faut sauvegarder, et surtout *dans quel ordre*.

## 1. Inventaire par classe

| Classe | Emplacement | Volume | Reproductible | Surface de sauvegarde **valide** |
|---|---|---|---|---|
| `eurio.db` (canonique) | bind `infra/eurio-api/data` | 155 Mo + WAL | 🔴 non | `VACUUM INTO` (WAL actif) |
| `review.db` | bind `infra/review/data` | **954 368 o** | 🔴 non — décisions humaines | `VACUUM INTO` |
| MinIO `enrichment-raws` | bind `infra/minio/data` | 5,168 GiB / 17 129 obj | 🔴 non — scrapes non rejouables | **API S3** |
| MinIO `enrichment-crops` | idem | 1011 MiB / 12 998 obj | 🟡 recalculable depuis les raws, coûteux | **API S3** |
| MinIO `numista-canonical` | idem | 78,7 MiB / 3 824 obj | 🟡 refetchable, quotas Numista | **API S3** |
| MinIO `eurio-db` | idem | **201,760 MiB / 5 obj** | 🟡 modèles très chers ; `eurio.db` du 29/06 = legacy | **API S3** |
| Creds MinIO / review | `infra/*/secrets` (gitignorés) | ko | ❓ à établir | fichier |
| Code, compose, secrets SOPS | git, 2 remotes | — | ✅ | git |

Le futur bucket d'artefacts d'[ADR-004](../../adr/004-artefacts-binaires-hors-git.md)
(modèles de l'APK) s'ajoutera à cette liste. Son adressage par contenu
(`models/<nom>/<sha256[:12]>/<fichier>`) le rend **immuable** : republier à l'identique
est un no-op, un contenu différent ne peut jamais écraser l'ancien. C'est le cas le plus
simple possible à sauvegarder.

Le bucket `eurio-db` contient 5 objets : `eurio.db` (101 937 152 o, 2026-06-29),
`eurio.db.lock`, `eurio.db.sha256`, et les deux artefacts `transfers/arcface_*`
(109,6 Mo). Sa copie de `eurio.db` est un vestige du modèle pré-R2 — et
[`data-layer-unification`](../data-layer-unification/README.md) phase 5 prévoit de tuer
ce bucket. Voir la question ouverte du [`HANDOFF`](./HANDOFF-NEXT-SESSION.md).

`eurio.db` compte **80 tables** applicatives (81 dans `sqlite_master`, dont
`sqlite_sequence`). Les plus volumineuses :

| Table | Lignes | | Table | Lignes |
|---|---|---|---|---|
| `image_state_events` | 22 968 | | `listing_text_signals` | 15 440 |
| `source_image_runs` | 19 661 | | **`mint_release_prices`** | **12 161** |
| `image_asset_dino_predictions` | 16 460 | | `coin_descriptions_i18n` | 11 345 |
| `source_images` | 15 991 | | `image_assets` / `image_state_current` | 11 162 |
| `discovery_log` | 15 081 | | `review_queue` | 10 663 |

`review.db` (le vrai, celui de `infra/review/data/`) est petit mais irremplaçable :
`review_items` 575, `decisions` 3, `reviewers` 1, `meta` 1. ⚠️ Ne pas le confondre avec
le résidu de 49 152 o présent dans `infra/eurio-api/data/`
(cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §1).

## 2. Le point dur : `eurio.db` référence MinIO

`image_assets.storage_path` et `source_images.storage_path` contiennent des **clés
d'objets MinIO**. C'est une intégrité référentielle qui traverse deux stores, sans
transaction commune, donc sans garantie de cohérence.

État mesuré le 2026-08-14 (comparaison ensembliste des `storage_path` distincts de la
base contre `rclone lsf -R` sur chaque bucket) :

| | `enrichment-crops` ↔ `image_assets` | `enrichment-raws` ↔ `source_images` |
|---|---|---|
| Lignes DB ↔ objet présent | 11 157 | 13 989 |
| **Dangling** (DB → objet absent) | **5** | **551** |
| Orphelins (objet sans ligne DB) | 1 841 | 3 140 |

Les 556 dangling se décomposent **intégralement** en deux catégories connues :

- **546 chemins absolus de machine de développement** :
  `/Users/musubi42/.cache/eurio/enrichment-raws/bce/<hash>/<uuid>.jpg` — le cache local
  d'un Mac a fuité dans la base canonique ;
- **10 lignes `mock/`** (5 crops + 5 raws) — données de test.

> **Il n'y a donc aucun dangling sur les données réelles.** L'intégrité inter-stores est
> saine aujourd'hui. C'est une propriété vraie, mesurable et peu coûteuse — donc un
> invariant de vérification idéal, et le critère d'acceptation naturel d'une restauration.

Les ~4 981 orphelins (de l'ordre d'1 GiB) sont bénins : ils occupent de la place dans la
sauvegarde sans que rien ne les réclame. À suivre en tendance, pas à corriger ici.

## 3. La règle d'ordre — conséquence directe

Les deux snapshots ne peuvent pas être pris au même instant. Le décalage produit **soit**
des orphelins **soit** des dangling, et ce n'est **pas symétrique** :

| Ordre de capture | Ce que produit le décalage | Verdict |
|---|---|---|
| MinIO à T1, **puis** DB à T2 | La DB connaît des objets uploadés entre T1 et T2, absents du miroir → **dangling** | ☠️ corruption silencieuse |
| **DB à T1, puis MinIO à T2** | MinIO est un sur-ensemble de ce que la DB référence → **orphelins seulement** | ✅ bénin |

> ### Règle : on capture toujours le store **référençant** avant le store **référencé**.
> Concrètement pour Eurio : **`eurio.db` et `review.db` d'abord, le miroir MinIO ensuite.**

Ça ne coûte rien et ça élimine par construction le seul mode de corruption silencieuse
de la restauration. Le plan initial ne mentionnait pas l'ordre.

**Réserve à assumer.** Cette règle tient parce que MinIO est *append-only en pratique*.
Si un processus se met à supprimer des objets, une ligne DB de T1 peut pointer vers un
objet supprimé avant T2 → dangling malgré le bon ordre. C'est exactement ce que
l'invariant `dangling == 0` est là pour détecter : la règle d'ordre supprime le cas
courant, l'invariant couvre le cas résiduel.

## 4. Quatre bugs de qualité de données

Trouvés en étudiant la cohérence. Ils ne relèvent pas de la sauvegarde, mais ils
**contraignent ce qu'on peut vérifier**, ce qui les rend structurants ici.

| # | Bug | Impact sur ce chantier |
|---|---|---|
| 1 | **`image_assets.sha256` est NULL sur 11 162 / 11 162 lignes.** La colonne existe, rien ne la remplit | Aucune vérification de contenu possible sur les crops. L'échantillonnage sha se limite aux raws (90 % renseignés) et à la comparaison miroir ↔ source |
| 2 | **546 chemins absolus de Mac** dans `source_images.storage_path` | Références non restaurables. L'invariant « dangling == 0 » doit les exclure explicitement, sinon il naît déjà rouge |
| 3 | **`storage_status = 'present'` sur 100 % des lignes**, y compris les 556 dangling | ⚠️ **Le champ affirme quelque chose de faux.** C'est celui vers lequel on tendrait naturellement la main pour vérifier la présence des objets — et c'est un mensonge |
| 4 | ~4 981 objets orphelins (1 841 crops + 3 140 raws) | ~1 GiB sauvegardé sans réclamant. Bénin, à suivre en tendance |

Le bug 3 porte la leçon générale de ce chantier :

> **On ne peut pas construire un invariant sur un champ que personne ne maintient.
> Les invariants doivent être *calculés*, jamais *lus*.**

C'est la même erreur de raisonnement que « le script existe donc le backup tourne » :
faire confiance à une déclaration au lieu de mesurer l'état.

**Décision** : ces bugs sortent en tickets séparés (ils touchent le pipeline
d'ingestion, pas la sauvegarde), **sauf le n°2**, dont l'exclusion propre est un
prérequis de l'invariant inter-stores et fait donc partie du lot 3.

## 5. Ce que ça implique pour la restauration

Une restauration d'Eurio n'est pas « remettre des fichiers en place ». C'est rétablir
**deux stores dans un état mutuellement cohérent**, dans un ordre imposé par les
dépendances, puis le **prouver**. Voir [`RESTAURATION.md`](./RESTAURATION.md).
