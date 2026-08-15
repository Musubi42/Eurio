# Architecture de la chaîne de sauvegarde

> Duplicati est le **moteur unique** : transport, chiffrement, rétention, historique.
> Eurio lui fournit un répertoire de staging contenant des artefacts **cohérents et
> vérifiables**, produits par du code conscient de l'application.

## 1. Le motif : staging dir — celui d'Authentik, en plus riche

Duplicati sauvegarde des **chemins de fichiers**. Or aucune des données qui comptent
chez Eurio n'a le système de fichiers pour surface valide : `eurio.db` est une SQLite en
WAL sous écriture, et la disposition sur disque de MinIO est un format interne.

Le motif est **décrit** dans la doctrine du VPS — Authentik fait `pg_dump →
backup-temp/`, Duplicati sauvegarde la stack. Le motif technique est bon et on le reprend.

> ⚠️ **Mais ce précédent n'est pas une doctrine éprouvée — c'est un échec de plus.**
> Vérifié le 2026-08-14 : la source Duplicati du job Authentik est
> `/oim-authentik-source/` (le répertoire de stack entier), pas `backup-temp/` ; aucun
> `run-script-before` n'est configuré ; il n'y a **aucun cron ni timer systemd** sur la
> machine pour lancer le `pg_dump`. Résultat : `backup-temp/` contient **un seul
> fichier, daté du 8 novembre 2025**, que Duplicati re-sauvegarde chaque nuit depuis
> neuf mois.
>
> C'est la troisième occurrence de la même pathologie sur cette machine : une procédure
> écrite, jamais automatisée, dont personne ne sait qu'elle ne tourne pas. **On reprend
> le motif, pas la façon de l'exploiter** — d'où l'ordonnancement déclaratif (§4) et la
> surveillance de l'anneau n°1 (§5).

```
/opt/eurio/infra/backup/staging/          ← la SEULE chose que Duplicati regarde
├── eurio.db                              VACUUM INTO        (T1)
├── review.db                             VACUUM INTO        (T1)
├── minio/
│   ├── enrichment-crops/                 rclone sync        (T2 > T1)
│   ├── enrichment-raws/
│   ├── numista-canonical/
│   └── eurio-db/                         (modèles ML)
├── baseline-manifest.json                référence du dernier verify réussi
└── manifest.json                         T1, T2, sha256, comptages, invariants
```

`baseline-manifest.json` vit **dans** le staging, donc Duplicati le sauvegarde. Ce
n'est pas un détail : sans référence, l'invariant de non-décroissance est inopérant —
or c'est lui le critère d'acceptation d'une restauration ([D-13](./DECISIONS.md)).
Une référence gardée hors du staging disparaîtrait avec la machine qu'elle sert
précisément à restaurer.

`staging/` doit être **gitignoré** (il vit sous `infra/backup/`, qui est dans le dépôt).

L'ordre `eurio.db` → `review.db` → `minio/` n'est pas cosmétique : c'est la règle
« référençant avant référencé » de [`DONNEES.md`](./DONNEES.md) §3.

## 2. Pourquoi un miroir rclone, et pas le répertoire MinIO brut

On pourrait pointer Duplicati directement sur `infra/minio/data`. **C'est le choix
qu'il ne faut pas faire**, pour une raison qui est le cœur de ce chantier.

La disposition MinIO sur disque, c'est `<clé>/xl.meta` plus des fichiers de parts. On ne
peut pas calculer le sha256 d'un objet sans réassembler ce format interne. Donc :

> **Sauvegarder le répertoire brut rend la vérification impossible.** On retomberait
> exactement dans « un dispositif dont on croit qu'il marche » — la situation qu'on est
> en train de corriger.

S'y ajoute un risque de cohérence : sauvegarder à chaud un répertoire écrit par un
serveur d'objets peut capturer un objet en cours d'écriture, et `.minio.sys/` (métadonnées
de buckets, policies) n'est pas un format documenté comme surface de sauvegarde.

Le miroir S3 coûte **6,43 GiB de disque** (4 buckets, 33 956 objets ; 6,23 GiB si l'on
exclut `eurio-db`) et achète trois choses :

| Gain | Détail |
|---|---|
| **Vérifiabilité** | Vrais fichiers, vrais sha256, comparables objet par objet à la source |
| **Surface naturelle pour Duplicati** | Fichiers plats — sa déduplication fonctionne bien dessus |
| **Restauration triviale** | `rclone sync` en sens inverse, sans outil spécial |

Il est **incrémental** : en régime permanent, `rclone sync` ne transfère que les objets
nouveaux ou modifiés. Le coût récurrent est proche de zéro.

> ⚠️ **Le miroir n'est *pas* une copie au sens 3-2-1.** Il vit sur le même disque
> `/dev/sda1`, la même machine et le même répertoire parent que la source. Un disque
> perdu emporte les deux. C'est un **tampon de vérification**, pas une protection.
> La seule vraie copie reste celle que Duplicati pousse hors site.

**Coût disque total** : `/opt/eurio` passe d'environ 9,0 Go à ~15,3 Go. Le VPS est à
78 %, 85 Go libres. Marge suffisante, à surveiller quand MinIO grossira.

## 3. Duplicati porte la rétention, donc le versioning

`rclone sync` propage les suppressions au miroir — **c'est voulu**. Le miroir est un
point-dans-le-temps fidèle, et **Duplicati est la seule couche d'historique**.

> ⚠️ **La rétention Duplicati est `keep-versions = 30` — 30 *versions*, pas 30 jours.**
> Mesuré sur les 10 jobs existants. La distinction est cruciale : si des runs échouent,
> 30 versions couvrent une fenêtre **beaucoup plus longue** que 30 jours, et si des runs
> se multiplient, beaucoup plus courte. **Le job Eurio devra fixer explicitement
> `keep-time`** s'il veut une garantie *temporelle* — c'est elle, et non un nombre de
> versions, qui borne « combien de temps j'ai pour détecter une corruption ».

Ça tranche proprement deux questions restées ouvertes dans le plan initial :

- *« MinIO : full ou incrémental ? »* — mal posée. `rclone` est déjà incrémental. La
  vraie question était le **versioning**, et la réponse est : chez Duplicati.
- *« Faut-il rouvrir l'interdiction du versioning S3 ? »* (`infra/minio/README.md`
  §Anti-patterns) — **non.** Le versioning S3 doublerait l'usage disque de MinIO sur un
  VPS à 78 %. La rétention Duplicati donne l'historique **hors du disque saturé** et
  sans toucher à MinIO. La règle anti-patterns reste valable telle quelle ; sa prémisse
  redevient vraie, simplement autrement que prévu.

**Corollaire à assumer explicitement** : si MinIO est vidé, le miroir se vide, et
Duplicati sauvegarde du vide. La rétention laisse le temps de s'en apercevoir — **et
l'invariant de non-décroissance le voit le jour même**. C'est précisément le scénario
pour lequel le niveau 3 existe (cf. [`VERIFICATION.md`](./VERIFICATION.md)).

## 4. Ordonnancement — découplé de Duplicati

**Contrainte mesurée** : les jobs Duplicati démarrent à **03:00 UTC**. En régime sain
(mesuré le 25 mai, dernière nuit réussie) les 10 jobs se sont enchaînés en **six
minutes**, de 03:00:00 à 03:06:00 UTC. Le staging d'Eurio doit être **terminé avant
03:00 UTC**.

> Les horaires de 04:59 UTC visibles dans `Schedule.LastRun` aujourd'hui sont des
> horaires de **panne** (cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §3), pas de
> fonctionnement normal. Ne pas dimensionner de fenêtre sur eux.

```
02:00 UTC   eurio-backup-stage.service    VACUUM INTO ×2 → miroir MinIO → manifest.json
                                          └─ push Kuma « eurio-staging »
02:30 UTC   eurio-backup-verify.service   niveaux 1-2-3 sur la copie du staging
                                          └─ push Kuma « eurio-verify »
                                          └─ ping healthchecks.io  (si OK)
03:00 UTC   Duplicati job « Eurio »       staging/ → pCloud, keep-time explicite
                                          └─ --send-http-url → Kuma « eurio-uploaded »
```

### Pourquoi ne pas utiliser `--run-script-before` de Duplicati

Duplicati sait exécuter des scripts avant/après un job, ce qui en ferait le chef
d'orchestre — séduisant, vu la décision « tout basculer sur Duplicati ». Mais ces
scripts s'exécutent **dans le conteneur** `linuxserver/duplicati`, qui n'a ni `docker`
ni `rclone`. Il faudrait lui exposer le socket Docker : couplage fort, surface d'attaque
inutile, et un conteneur de sauvegarde qui obtient les pleins pouvoirs sur l'hôte.

**Retenu : découplage.** Un timer systemd sur l'hôte produit le staging ; Duplicati le
ramasse à son heure et ne sait rien d'Eurio. C'est plus simple, et c'est déjà ce que la
doctrine du VPS décrit pour Authentik (le `pg_dump` y est une étape séparée).

Les timers sont déclarés dans **`nix/eurio-vps.nix`**, importé dans `/etc/nixos` par un
**input flake** (`path:/opt/eurio/nix`, `flake = false`) et **non** par chemin absolu :
le système du VPS est construit par un flake, et l'évaluation pure refuse les chemins
hors du flake. Détail et raisonnement : [D-22](./DECISIONS.md).

Un service NixOS déclaratif survit à une réinstallation, contrairement à un cron.
C'est la réponse à la question « quel ordonnanceur » du plan initial.

**Conséquence à ne pas rater** : un `nixos-rebuild switch` sera nécessaire, et il
touche la configuration d'un VPS qui héberge 60+ conteneurs. Voir
[`ROADMAP.md`](./ROADMAP.md) lot 4 pour les précautions.

## 5. Alerting — trois anneaux concentriques

Le principe est l'inverse de « rapporter son succès » : **on surveille l'anomalie, et la
détection d'absence appartient à un système extérieur au dispositif surveillé.**

| # | Anneau | Signal | Ce qu'il détecte | Notifie |
|---|---|---|---|---|
| 1 | Kuma push `eurio-staging` | le staging a été produit | script cassé, Docker HS, disque plein | Discord |
| 2 | Kuma push `eurio-verify` | niveaux 1-2-3 passés | **sauvegarde réussie mais mauvaise** | Discord |
| 3 | **Kuma push `eurio-uploaded`** | **le job Duplicati a fini en succès** | **la destination ne reçoit rien** | Discord |
| 4 | **healthchecks.io** | ping uniquement si tout est vert | **VPS mort, Kuma mort** | Discord |
| 5 | Kuma push `eurio-drill` (~100 j) | l'exercice trimestriel a eu lieu | le rituel humain oublié | Discord |

**Des monitors distincts** parce qu'ils échouent pour des raisons différentes et
appellent des actions différentes : « le staging n'a pas tourné » est un problème
d'infrastructure, « verify est rouge » est un problème de données, « uploaded est rouge »
est un problème de destination.

### L'anneau 3 est celui qui manquait — et son absence a coûté 81 jours

Les niveaux 1-2-3 tournent tous sur le **staging local**. Aucun d'eux ne prouve que
Duplicati a effectivement poussé quoi que ce soit. Sans l'anneau 3, un staging
impeccable et une destination qui refuse tout produisent exactement le même signal :
vert.

**Ce n'est pas une hypothèse.** C'est très précisément ce qui s'est passé sur les 10
autres jobs : ils s'exécutent chaque nuit, échouent en `401 Unauthorized` depuis le
26 mai, et personne ne l'a su pendant 81 jours
(cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §3-4).

Duplicati sait faire ce signal nativement : **`--send-http-url`** vers l'URL du push
monitor Kuma, avec `--send-http-level=all` pour que l'échec soit rapporté autant que le
succès. Le conteneur possède `curl` (vérifié) — et c'est le seul usage pour lequel on
accepte de faire parler Duplicati, parce qu'il ne demande ni Docker ni `rclone`, donc
aucun des couplages écartés en §4.

**Cet anneau est directement réutilisable pour les 10 autres jobs**, et c'est le
livrable le plus transférable de tout le chantier.

**Pourquoi Kuma plutôt que l'astuce éditer/poster sur Discord** (proposée dans le plan
initial) :

- Éditer un message webhook exige de persister un `message_id` et de le survivre aux
  redéploiements — on ajouterait un mode de panne **dans le chemin de notification
  lui-même**, la partie qui doit être la plus fiable.
- Un « bilan hebdomadaire » est un dead-man's switch faible : détecter une absence est
  un travail de machine, pas d'humain.
- Kuma **déduplique nativement** (il notifie sur *changement d'état*, pas à chaque
  échec). L'argument « les échecs sont rares donc pas de saturation » est faux dans le
  cas qui compte : un token expiré échoue *toutes les nuits*, exactement quand on a
  besoin du signal.
- La preuve de vie datée est meilleure : `uptime.musubi.dev` montre l'historique et
  le pourcentage d'uptime, pas seulement le dernier point.
- Eurio apparaît **au même endroit que les 13 autres monitors**. Un seul tableau à
  regarder.

**Pourquoi un troisième anneau hors site.** Kuma et ntfy tournent *sur le VPS qu'ils
surveillent* : aucun des deux ne peut annoncer la mort de cette machine. Il n'y a qu'un
seul VPS — s'il tombe, il n'y a plus de signal du tout, et une absence de signal est
indiscernable du silence normal. `healthchecks.io` (offre gratuite) est un dead-man's
switch hors site : c'est **son absence de ping** qui déclenche, ce qui couvre le seul
scénario que rien d'autre ne couvre.

Discord reste le médium, et c'est le bon choix : c'est le seul canal **externe** au VPS,
et il est déjà le canal par défaut de tout le monitoring existant.

## 6. Ce que devient `infra/backup/eurio-backup.sh`

Il n'est **pas jeté** — il est refactorisé. Sa logique correcte est précisément celle
dont on a besoin :

| Ce qui est gardé | Ce qui disparaît |
|---|---|
| `VACUUM INTO` dans le conteneur + `docker cp` (l.111-114) | `cmd_run` — push direct vers pCloud (doublon de Duplicati) |
| Lecture de MinIO par l'API S3 (l.137) | `load_age_key` / `rclone crypt` (Duplicati chiffre) |
| Calcul et sidecar sha256 (l.116-119) | `cmd_upload_readme` (l.189) |
| Self-reexec `nix shell` (l.29) | `cmd_keygen` (l.74) |

Deux fonctions supplémentaires existent et doivent être tranchées explicitement :

- **`cmd_verify` (l.145)** — fait déjà `rclone check --one-way` et compare le sha au
  sidecar. **C'est le niveau 1 déjà écrit.** À récupérer dans la suite d'invariants du
  lot 2 plutôt qu'à réécrire.
- **`cmd_rclone` (l.201)** — échappatoire de débogage. À garder ou supprimer, au choix.

`cmd_run` devient **`cmd_stage`**. Le script gagne `review.db`, qu'il ne connaît pas du
tout aujourd'hui (zéro occurrence) alors que le plan initial le listait comme donnée
critique — et il devra nommer **lequel** des deux fichiers il snapshote
(cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §1).

À noter : `cmd_run` sauvegarde **déjà** la DB avant les buckets (l.133 puis l.135).
L'ordre « référençant d'abord » de [D-04](./DECISIONS.md) est donc déjà respecté par le
code existant — c'est le *plan initial* qui ne le mentionnait pas, pas le script.

**L'ancien backup pCloud du 17 juin n'est pas supprimé** avant que la nouvelle chaîne
n'ait passé un exercice de restauration complet (lot 7, après le lot 6). Une copie
périmée vaut mieux que zéro copie pendant une transition.
