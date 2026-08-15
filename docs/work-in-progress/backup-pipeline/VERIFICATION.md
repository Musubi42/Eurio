# Vérification — cinq niveaux, et pourquoi trois d'entre eux ne suffisent pas

> **Une sauvegarde jamais restaurée n'est pas une sauvegarde.** Mais « restaurer » veut
> dire cinq choses différentes, qui coûtent cinq prix différents et attrapent cinq
> classes de panne différentes. Les confondre est la façon la plus courante de croire
> qu'on est protégé.

## 1. Pourquoi le plan initial testait la mauvaise chose

Le plan initial proposait : extraire un fichier de l'archive, comparer son sha256 à
celui enregistré au moment de la sauvegarde, et lancer `PRAGMA integrity_check`.

Le problème : **`sha(backup) == sidecar` ne teste que le transport.** Le sidecar est
écrit par le même script, au même moment, à partir du même fichier. Ça prouve que les
octets ont survécu au trajet. Ça ne prouve rien sur la *qualité de ce qu'on a
sauvegardé*.

Le scénario qui compte est celui-ci :

> `eurio.db` se fait tronquer par une migration ratée. La nuit suivante, la sauvegarde
> s'exécute parfaitement. Le `VACUUM INTO` réussit. Le sha correspond au sidecar.
> `PRAGMA integrity_check` retourne `ok` — **une base vide est une base SQLite
> parfaitement valide**. Le job rapporte ✅. La rétention finit par expirer la bonne
> version.

Aucun des deux tests proposés ne voit quoi que ce soit. C'est le trou que le niveau 3
comble.

## 2. Les cinq niveaux

| # | Niveau | Question à laquelle il répond | Coût | Rythme |
|---|---|---|---|---|
| 1 | **Intégrité transport** | Les octets ont-ils survécu ? | ~0 | quotidien |
| 2 | **Validité structurelle** | Est-ce un SQLite valide ? | ~0 | quotidien |
| 3 | **Plausibilité sémantique** | Le contenu est-il **crédible** ? | ~0 | **quotidien** |
| 4 | **Restauration fonctionnelle** | L'application démarrerait-elle dessus ? | moyen | trimestriel |
| 5 | **DR complet à froid** | **Moi**, pourrais-je vraiment restaurer ? | élevé | trimestriel |

Les niveaux 1 à 3 sont **automatiques** et tournent sur la copie du staging.
Les niveaux 4 et 5 sont **l'exercice humain** (§5).

## 3. Les invariants du niveau 3, pour Eurio

Calculés sur la **copie du staging**, jamais sur la source vivante, et comparés au
`manifest.json` de la veille.

| # | Invariant | Ce qu'il attrape |
|---|---|---|
| 1 | `PRAGMA integrity_check` = `ok` **et** `PRAGMA foreign_key_check` vide, sur `eurio.db` et `review.db` | corruption structurelle |
| 2 | `_schema_migrations` = 5 lignes, cohérent avec les migrations du dépôt | restauration d'un schéma désaligné, migration à moitié appliquée |
| 3 | Comptages des ~15 tables clés **non décroissants** au-delà d'une tolérance | **troncature, wipe partiel, migration destructrice** |
| 4 | **dangling == 0**, hors `mock/` et hors chemins absolus | désynchronisation DB ↔ MinIO |
| 5 | Nombre d'orphelins dans une bande attendue | suppression anormale côté MinIO, dérive |
| 6 | 20 objets tirés au hasard : présents dans le miroir **et** sha256 conforme à la source S3 | corruption silencieuse du corpus |
| 7 | Une pièce connue se résout : `coins` → `coin_names_i18n` → `coin_canonical_images` | la base est **utilisable**, pas seulement valide |
| 8 | **Fraîcheur** : `mtime` de la source vs `t1` du manifeste ; le staging ne doit jamais être plus vieux que N jours | **le staging a cessé d'être régénéré** — un miroir figé passe les invariants 1 à 7 |
| 9 | **La destination a reçu** : le job Duplicati a fini en succès (anneau 3, [`ARCHITECTURE.md`](./ARCHITECTURE.md) §5) | **la sauvegarde n'arrive nulle part** |

### Notes sur trois d'entre eux

**Invariant 3 — la non-décroissance est le vrai filet.** C'est lui qui attrape le
scénario du §1. Une décroissance peut être légitime (purge volontaire) ; elle doit alors
**notifier et exiger un acquittement humain**, jamais passer en silence. Tables candidates
pour la liste de surveillance : `coins`, `image_assets`, `source_images`,
`review_queue`, `consensus_verdicts`, `coin_observations`, `image_state_events`,
`coin_descriptions_i18n`, `mint_release_prices`, `training_runs`, plus `review_items` et
`decisions` dans `review.db`. **Liste à figer au lot 2.**

**Invariants 8 et 9 — ajoutés après la revue du 2026-08-14**, parce que les sept
premiers ont un angle mort commun : **ils vérifient tous un fichier local**. Un staging
figé (le script ne tourne plus) et un upload qui échoue (la destination refuse) les
passent tous les sept sans broncher.

Ce n'est pas théorique. `eurio.db` n'a pas été écrit depuis le **2026-07-12** — un mois
d'inactivité pendant lequel l'invariant 3 (non-décroissance) est vert par construction et
ne prouve strictement rien. Et les 10 jobs Duplicati échouent depuis 81 jours en
produisant, localement, des sources parfaitement saines. **L'invariant 9 est celui dont
l'absence a coûté trois mois de sauvegardes sur cette machine.**

**Invariant 4 — c'est celui qui est propre à Eurio**, et il n'existe nulle part
aujourd'hui. Il mesure la seule propriété qui ne peut pas être vérifiée store par store.
Il doit **exclure explicitement** les 546 chemins absolus de Mac et les 10 lignes
`mock/`, sinon il naît rouge (cf. [`DONNEES.md`](./DONNEES.md) §4, bug n°2).

**Invariant 6 — l'échantillonnage aléatoire est ce qui rend la vérification tenable.**
20 objets par nuit couvrent statistiquement les 30 000 objets sur un an, sans jamais
faire un téléchargement complet. C'est très supérieur à un `rclone check` intégral
hebdomadaire, en coût comme en pouvoir de détection du pourrissement lent.

⚠️ **Limite connue** : `image_assets.sha256` est NULL sur 100 % des lignes. Pour les
crops, la comparaison ne peut donc porter que sur **miroir ↔ source S3**, pas sur
**miroir ↔ sha attendu par la base**. Pour les raws, 90 % des lignes ont un sha
exploitable. À retester quand le bug n°1 sera corrigé.

### La règle qui gouverne tous les invariants

> **On ne construit pas un invariant sur un champ que personne ne maintient. Les
> invariants sont *calculés*, jamais *lus*.**

Contre-exemple concret et vérifié : `storage_status` vaut `'present'` sur 100 % des
lignes, **y compris sur les 556 qui pointent vers un objet absent**. C'est le champ vers
lequel on tendrait naturellement la main pour l'invariant 4, et il est faux.

## 4. Étagement des coûts

Re-télécharger 6 GiB pour tester est un coût réel. L'étagement retenu :

| Rythme | Portée | Volume | Niveaux |
|---|---|---|---|
| **Quotidien** | `eurio.db` + `review.db` + 20 objets échantillonnés | ~155 Mo + qq Mo | 1, 2, 3 |
| **Hebdomadaire** | + comparaison de comptage complète miroir ↔ source par bucket | métadonnées seules | 1, 3 |
| **Trimestriel** | restauration fonctionnelle + exercice à froid | complet | 4, 5 |

La vérification quotidienne tourne sur le **staging local**, pas sur pCloud : il n'y a
donc rien à re-télécharger dans le cas courant. Le trimestriel est le seul moment où on
tire réellement depuis la destination hors site — et c'est justement l'intérêt de
l'exercice.

## 5. Automatique et humain — ils ne testent pas la même chose

C'est la question centrale, et la réponse n'est pas un compromis mou : les deux ont un
rôle **structurellement distinct**, et aucun ne remplace l'autre.

**L'automatique détecte les régressions.** Les octets, la structure, les invariants. Il
tourne sans attention humaine, chaque nuit, et son seul travail est de crier quand une
propriété vraie hier devient fausse. Il est excellent à ça ; l'humain est mauvais à ça.

**L'humain teste ce que l'automatique ne peut pas tester par construction : le chemin de
récupération humain.** Un test automatisé a toujours la clé au bon endroit, la
configuration déjà écrite, les commandes déjà connues. Il ne teste jamais :

- la clé de déchiffrement est-elle **récupérable par un humain qui a tout oublié** et
  n'a plus accès au VPS ?
- `README-RESTORE.md` est-il **exact**, ou décrit-il une version d'il y a six mois ?
- est-ce que je sais **par où commencer**, à 2 h du matin, sans historique de shell ?

**C'est exactement ce qui a échoué le 14 août.** Rien n'était cassé techniquement : le
token fonctionnait, la clé fonctionnait, le script fonctionnait. C'est l'étape humaine
« brancher le dispositif » qui n'a jamais eu lieu. Un test automatisé n'aurait rien vu —
il n'aurait pas existé non plus.

### L'exercice trimestriel

Restaurer depuis pCloud dans un répertoire jetable **en n'utilisant que
`README-RESTORE.md`** : pas d'historique de shell, pas d'assistant, pas de mémoire.
Chaque étape manquante ou fausse est un **bug du document**, corrigé sur-le-champ. La
date et le résultat sont notés dans [`ROADMAP.md`](./ROADMAP.md).

Le critère de réussite est **la suite d'invariants du §3**, exécutée contre la stack
restaurée. Ce qui donne la propriété la plus élégante du design :

> **Le critère d'acceptation d'une restauration est exactement la suite de tests qui
> tourne chaque nuit.** Un seul corpus de code, deux usages. Ils ne peuvent donc pas
> diverger, et l'exercice de restauration ne peut pas devenir du théâtre.

### Le piège du rituel humain, et sa parade

**Un rituel humain ne se fait pas.** Preuve directe, sur cette machine :
`/opt/stacks/oim-duplicati/BACKUP_STRATEGY.md` prescrit déjà un « Monthly Disaster
Recovery Test » depuis novembre 2025. C'est une case à cocher dans un markdown. Elle n'a
jamais été cochée. Il existe même un montage `/opt/duplicati-test-restore` préparé et
inutilisé — la même pathologie que le backup d'Eurio, un cran plus haut.

La parade : **traiter l'exercice humain comme un job qui peut échouer.** Un push monitor
Kuma d'intervalle ~100 jours, que **seul le script d'exercice acquitte**. Si l'exercice
n'a pas eu lieu, Kuma notifie Discord.

On applique au rituel humain exactement la logique qu'au job automatique : **on
surveille son absence, et cette absence a une adresse.**
