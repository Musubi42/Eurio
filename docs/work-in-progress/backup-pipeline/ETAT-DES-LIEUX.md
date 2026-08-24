# État des lieux — mesuré sur le VPS le 2026-08-14

> Toutes les valeurs de ce document ont été **mesurées**, pas estimées. La commande
> d'origine est indiquée pour chaque bloc afin que n'importe qui puisse les recontrôler.
> Hôte : `nixos` (le VPS), Linux 6.18.38, NixOS 26.05.

## 1. Une sauvegarde existe — et le plan initial l'ignorait

`docs/archive/operations/backup-strategy.md` §1 affirmait « **aucune sauvegarde ne tourne** » et
en concluait qu'il n'existait aucune copie. La première affirmation est vraie, la
seconde est fausse.

```
pcloud:backups/serverOimNix/Eurio  →  21 661 objets, 3,842 GiB, datés du 2026-06-17
```

Et surtout : **la clé age du 17 juin déchiffre encore ce backup.** Le remote `crypt` a
été monté avec elle et les 4 dossiers listés en clair. La chaîne cryptographique est
intacte ; il y a bien **une copie hors site restaurable**, simplement figée.

C'est un *one-shot jamais rejoué*. Écart mesuré entre la source et cette copie :

| Source | Sur le VPS | Dans le backup (17 juin) | Couverture |
|---|---|---|---|
| `eurio.db` | 155 648 000 o (mtime 2026-07-12 14:39) | 104 165 376 o | 2 mois de retard |
| `enrichment-raws` | 17 129 obj / 5,168 GiB | 9 918 obj / 2,958 GiB | **58 %** |
| `enrichment-crops` | 12 998 obj / 1011,811 MiB | 7 915 obj / 621,255 MiB | **61 %** |
| `numista-canonical` | 3 824 obj / 78,678 MiB | 3 824 obj / 78,678 MiB | 100 % |
| `review.db` | **954 368 o** (mtime 2026-07-12 16:09) | — **absent** | **0 %** |

⚠️ **Il existe deux fichiers `review.db` sur le VPS.** Ne pas les confondre :

| Chemin | Taille | Contenu | Verdict |
|---|---|---|---|
| `infra/review/data/review.db` (conteneur `eurio-review`) | 954 368 o | `review_items` 575, `decisions` 3, `reviewers` 1 | ✅ **le vrai** |
| `infra/eurio-api/data/review.db` | 49 152 o | `review_items` 2, `decisions` 1, **pas de table `reviewers`** | ❌ résidu |

C'est un piège de restauration réel : le lot 1 doit nommer explicitement lequel il
snapshote.

> `rclone size minio:<bucket> --fast-list` · `rclone size pcloud_crypt:<bucket>` ·
> `rclone ls pcloud:backups/serverOimNix/Eurio`

Le bucket `eurio-db` du backup contient aussi des artefacts ML :
`transfers/arcface_vits14_v1_best_model.pth` (88 049 859 o) et
`transfers/arcface_vits14_v1.tar.gz` (21 573 608 o), plus le sidecar
`eurio.db.sha256` (64 o).

### Autres prémisses du plan initial à corriger

| Affirmation initiale | Réalité mesurée |
|---|---|
| « `rclone` n'est pas installé » | Exact — mais le self-reexec `nix shell` de `eurio-backup.sh` fonctionne (testé, rclone 1.74.4, ~30 s au premier appel) |
| « Destination à décider » | Déjà opérationnelle : token pCloud **valide**, `rclone about` répond, `~/.config/rclone/rclone.conf` contient `[pcloud]`, `[pcloud_crypt]`, `[minio]` |
| « Ordonnanceur à décider » | Déjà écrit : `nix/eurio-vps.nix` définit `systemd.services.eurio-backup` + timer hebdo. **Jamais importé** — `/etc/nixos/configuration.nix` a `imports = [ ./hardware-configuration.nix ]` et rien d'autre |
| « Rétention : 149 Mo × 11 ≈ 1,6 Go, compromis à trouver » | Non-sujet. pCloud : 2 TiB au total, **1,191 TiB libres**. 1,6 Go = 0,1 % de l'espace libre |
| « MinIO = 6,8 Go » | 6,8 Go est un `du` disque, qui compte les métadonnées internes MinIO. Le contenu réel vu par l'API S3 est de **6,430 GiB / 33 956 objets** sur 4 buckets (6,233 GiB sans `eurio-db`) — et c'est lui qu'on sauvegarde |

## 2. Volumétrie

```
/dev/sda1  393G  288G utilisés  85G libres  78 %

/opt/eurio            9,0 G
├── infra             7,7 G
│   ├── minio         6,8 G   (disque ; 6,430 GiB via l'API S3)
│   ├── eurio-api     868 M
│   ├── review        1,1 M
│   └── backup         36 K
├── admin             281 M
├── ml                 77 M
├── docs               28 M
└── app-android        21 M
```

> `df -h /` · `du -sh /opt/eurio/*`

`infra/minio/data/*`, `infra/eurio-api/data/` et `infra/review/data/` sont bien
gitignorés (vérifié par `git check-ignore -v` et `git status --ignored`).

## 3. Le dispositif Duplicati — était en panne, ✅ réparé le 2026-08-15

> **Découvert le 2026-08-14 lors de la revue de ce document, réparé le 2026-08-15.**
> La première version affirmait que Duplicati « sauvegarde les 10 autres stacks ».
> C'était faux : il tentait et échouait toutes les nuits.

### Le diagnostic corrigé : une érosion, pas une panne

La première analyse concluait à un échec unique le 26 mai. **C'est plus grave que ça.**
En listant les fichiers réellement écrits sur pCloud, on obtient une extinction
progressive, job par job, sur neuf mois :

| Job | Dernière sauvegarde réelle | Ancienneté au 2026-08-15 |
|---|---|---|
| Beszel | 2025-11-08 | 9 mois |
| Authentik | 2026-01-21 | 7 mois |
| Hoppscotch | 2026-01-28 | 6 mois |
| Immich / Outline | 2026-03-16 | 5 mois |
| Ntfy | 2026-05-04 | 3 mois |
| Traefik | 2026-05-22 | 3 mois |
| Homarr / Uptime Kuma / Vaultwarden | 2026-05-25 | 3 mois |

### La cause racine

Le transport était `webdav://webdav.pcloud.com:443/…?auth-username&auth-password&use-ssl`.
**pCloud traite chaque connexion WebDAV en Basic Auth comme une nouvelle ouverture de
session** et, depuis une IP de datacenter, déclenche sa vérification d'appareil : un mail
« est-ce bien vous ? » valable 3 minutes, à 3 h du matin, pour chacun des 10 jobs.

D'où l'érosion : les jobs tombaient selon que le mail avait été validé à temps ou non.
Ce n'est pas un credential qui expire, c'est **une loterie quotidienne**. Aucun réglage
ne rend un couple identifiant/mot de passe non suspect aux yeux de pCloud — il fallait
changer de mode d'authentification, pas de paramètre.

| Fait | Valeur mesurée |
|---|---|
| Dernier backup réussi, tous jobs confondus | **2026-05-25**, entre 03:00:03 et 03:06:00 UTC |
| Première erreur `401 Unauthorized` | **2026-05-26 03:55:37 UTC** |
| Notifications accumulées | **456 `Error` + 468 `Warning`** |
| Message | `Response status code does not indicate success: 401 (Unauthorized).` |

### La réparation — 2026-08-15

Duplicati 2.2.0 embarque un **backend pCloud natif en OAuth**
(`Duplicati.Library.Backend.pCloud.dll`, format `pcloud://api.pcloud.com/dossier?authid=…`).

Découverte décisive : **le jeton pCloud de `~/.config/rclone/rclone.conf` est accepté
tel quel comme `authid`.** C'est un bearer **sans expiration**
(`expiry: 0001-01-01`, aucun refresh token — modèle pCloud : le jeton OAuth est permanent
jusqu'à révocation), ce qui explique qu'il fonctionne sans interruption depuis le
17 juin. Il n'y a donc **aucune poignée de main à réussir** avec
`oauth-service.duplicati.com`.

Opération réalisée par l'API REST de Duplicati : export des 10 configurations, puis
remplacement du seul champ `TargetURL`. **`DBPath` et `Sources` inchangés** — bases
locales et jeux de sauvegarde existants préservés.

Résultat des 10 exécutions, le 2026-08-15 entre 22:24 et 22:28 :

| Job | Résultat | Examinés | Envoyés |
|---|---|---|---|
| Vaultwarden | ✅ Success | 1 628 | 2 528 711 o |
| Uptime Kuma | ✅ Success | 13 | 5 142 951 o |
| Outline | ⚠️ Warning | 374 | 34 554 247 o |
| Homarr | ✅ Success | 11 | 2 623 911 o |
| Ntfy / Hoppscotch / Traefik / Immich | ⚠️ Warning | 4 à 43 | 1 818 à 6 711 o |
| Authentik | ✅ Success | 8 | 0 (rien n'a changé depuis janvier) |
| Beszel | ✅ Success | **0** | 0 (source vide — cf. §8) |

**Zéro erreur, zéro mail de vérification pCloud.** Planifications intactes (`1D`,
03:00 UTC). Total sur pCloud : 1,164 → 1,206 GiB.

La preuve la plus nette, sur un même job le même jour :

| Run | Transport | Résultat |
|---|---|---|
| 2026-08-15 04:40 UTC | WebDAV | 🔴 `Fatal` — TimeoutException, remote jamais atteint |
| 2026-08-15 20:22 UTC | pCloud OAuth | ✅ `Success` — 2 791 o lus, 3 fichiers distants reconnus |

Bénéfice annexe : le WebDAV utilisait **le mot de passe du compte pCloud**. Il est
remplacé par un jeton révocable — gain de sécurité autant que de fiabilité.

> ⚠️ L'export des configurations est dans
> `/opt/stacks/oim-duplicati/api-config-export-20260815/` (mode 700/600). **Il contient
> les identifiants WebDAV en clair** : à supprimer une fois la confiance établie.

> `sqlite3` sur une copie de `/config/Duplicati-server.sqlite`, tables `Metadata`
> (`LastBackupFinished`, `BackupListCount`), `Notification`, `Option`, `Schedule`.

**Ce qui est réellement protégé aujourd'hui** — nombre de versions conservées par job,
toutes antérieures au 25 mai :

| ID | Job | Versions | | ID | Job | Versions |
|---|---|---|---|---|---|---|
| 7 | Authentik | **2** | | 12 | Beszel | **1** (source vide) |
| 8 | Vaultwarden | 30 | | 13 | Homarr | 30 |
| 9 | Immich | **4** | | 14 | Ntfy | 27 |
| 10 | Traefik | **4** | | 15 | Hoppscotch AIO | **4** |
| 11 | Uptime Kuma | 30 | | 16 | Outline | **7** |

Immich (photos), Vaultwarden (gestionnaire de mots de passe) et Authentik
(authentification de tout le reste) n'ont **aucune sauvegarde postérieure au 25 mai**.

**Portée pour ce chantier.** Ce n'est pas un détail de contexte : c'est le **moteur sur
lequel repose toute l'architecture retenue** ([D-01](./DECISIONS.md)). Le réparer est un
**prérequis dur du lot 4**. Y ajouter un job Eurio sans réparer le credential
reviendrait à créer un onzième job qui échoue chaque nuit.

**Et c'est la même pathologie, un cran plus haut.** Le dispositif existe, il est
ordonnancé, il tourne — et il ne produit rien depuis trois mois, sans que personne ne le
sache. C'est exactement le diagnostic porté sur Eurio, à ceci près que le silence y était
total (aucun job) alors qu'ici il est *bruyant mais inaudible* (456 erreurs dans une
interface que personne n'ouvre). Les deux se soignent de la même façon : §4 et
[`ARCHITECTURE.md`](./ARCHITECTURE.md) §5.

### Configuration mesurée

Le VPS fait tourner `oim-duplicati` (`linuxserver/duplicati:2.2.0`,
`duplicati.musubi.dev`) avec **10 jobs** :

| ID | Job | | ID | Job |
|---|---|---|---|---|
| 7 | Authentik | | 12 | Beszel |
| 8 | Vaultwarden | | 13 | Homarr |
| 9 | Immich | | 14 | Ntfy |
| 10 | Traefik | | 15 | Hoppscotch AIO |
| 11 | Uptime Kuma | | 16 | Outline |

- **Planification** : `Repeat = 1D`, tous les jours de la semaine, déclenchement à
  **03:00 UTC**. Prochaine tentative : 2026-08-15 03:00 UTC.
- **Durée en régime sain** : le 25 mai, les 10 jobs se sont enchaînés de **03:00:00 à
  03:06:00 UTC** — **six minutes**, le plus long étant Uptime Kuma (5 min 21 s).
  ⚠️ Le `LastRun` de 04:59 UTC visible aujourd'hui est un horaire de **panne**, pas de
  fonctionnement normal. Ne pas dimensionner de fenêtre là-dessus.
- **Rétention : `keep-versions = 30`** sur les 10 jobs — **30 versions, pas 30 jours**.
  Lu en clair dans la table `Option` (seul `passphrase` y est chiffré). La valeur
  « 30 jours » de `BACKUP_STRATEGY.md` n'est vraie que si un backup réussit chaque
  jour — ce qui n'est plus le cas depuis trois mois.
- **Destination** : non lisible (`TargetURL` chiffrés `enc-v1:`). Indice fort en faveur
  de pCloud : `pcloud:homarr-test/` contient des `duplicati-*.dblock.zip.aes`. Mais
  `pcloud:backups/serverOimNix/` ne contient **que** `Eurio/` — l'arborescence réelle
  des 10 jobs reste à confirmer par le PO.
- La doctrine est écrite : `/opt/stacks/oim-duplicati/BACKUP_STRATEGY.md`, 683 lignes,
  daté nov. 2025, avec classification 🔴/🟡/🟢 et procédures de restauration par service.

**Eurio n'y figure pas** — et le conteneur Duplicati **n'a aucun montage vers
`/opt/eurio`** (14 binds, tous sous `/opt/stacks`). L'y ajouter demandera d'éditer
`/opt/stacks/oim-duplicati/compose.yaml` et de **recréer le conteneur**, une opération
hors dépôt Eurio sur une stack partagée.

**Conséquence de méthode** : ce chantier ne consiste pas à inventer une politique de
sauvegarde, mais à faire entrer Eurio dans une politique **déjà écrite** — en la
réparant au passage, puisqu'elle ne s'exécute plus.

## 4. Pourquoi la panne est restée invisible 81 jours

- **Aucune option de notification** n'est configurée dans Duplicati (aucune entrée
  `send-*` dans la table `Option`).
- `unacked-error = **True**` **et** `unacked-warning = **True**` : 456 erreurs et 468
  avertissements attendent dans une interface web que personne n'ouvre.
- Aucun de ces échecs n'a jamais atteint Discord, ni ntfy, ni Uptime Kuma.

C'est la démonstration la plus nette possible de la thèse de ce chantier :

> **Un dispositif qui échoue bruyamment mais sans destinataire est indiscernable d'un
> dispositif qui n'existe pas.** Le silence d'Eurio et le vacarme inaudible de Duplicati
> ont produit exactement le même résultat — des mois sans sauvegarde, sans que personne
> ne le sache.

C'est aussi ce qui justifie l'**anneau n°4** de [`ARCHITECTURE.md`](./ARCHITECTURE.md)
§5 : vérifier le staging local ne suffit pas, il faut un signal qui prouve que **la
destination a reçu quelque chose**. C'est précisément ce signal qui manquait ici.

**Le transport est réparé, l'alerting ne l'est pas.** Rien ne garantit aujourd'hui qu'une
rechute serait vue plus vite que la précédente. C'est le lot 5 qui ferme ce trou, et
l'anneau 3 est directement transposable aux 10 jobs.

## 5. L'outillage de notification est déjà installé

| Service | URL | État |
|---|---|---|
| `oim-uptime-kuma` | `uptime.musubi.dev` | 13 monitors, **tous de type `http` ou `group` — aucun `push`** |
| `oim-ntfy` | `ntfy.musubi.dev` | actif, auto-hébergé **sur ce VPS** |
| `oim-beszel` | `beszel.musubi.dev` | monitoring système |

Canaux de notification déjà configurés dans Uptime Kuma :

| # | Nom | Type | Défaut |
|---|---|---|---|
| 1 | Discord monitoring | discord | non |
| 2 | **Musubi Discord** | discord | **oui** |
| 3 | Musubi Ntfy | ntfy | non |

> `sqlite3` sur une copie de `/app/data/kuma.db`, tables `monitor` et `notification`.

**Conséquence** : Discord est déjà le canal par défaut de tout le monitoring du VPS.
Le brancher pour Eurio ne demande aucun webhook nouveau — seulement des *push monitors*,
qui n'existent pas encore.

**Limite structurelle à retenir** : `ntfy` et Kuma sont hébergés **sur le VPS qu'ils
surveillent**. Ni l'un ni l'autre ne peut signaler la mort de cette machine. C'est ce
qui justifie un troisième anneau hors site (cf. [`ARCHITECTURE.md`](./ARCHITECTURE.md) §5).

## 6. Conteneurs Eurio et leurs montages

```
eurio-api      bind  /opt/eurio/infra/eurio-api/data  => /var/lib/eurio
eurio-review   bind  /opt/eurio/infra/review/data     => /var/lib/eurio
               bind  /opt/eurio/infra/review/secrets  => /run/secrets
eurio-minio    bind  /opt/eurio/infra/minio/data      => /data
               bind  /opt/eurio/infra/minio/secrets   => /run/secrets
eurio-admin    (aucun montage — nginx static)
```

Dans `infra/eurio-api/data/` on trouve **huit** sauvegardes ad hoc laissées par des
migrations (`bak-20260619`, `bak-pre0003`, `bak-pre0004`, `pre-migA-20260703`,
`pre-c4c8-20260704`, `review-backup-2026-07-08` avec ses `-shm`/`-wal`,
`review.db.bak-20260619`), plus un sous-répertoire `backups/` — soit ~640 Mo de
doublons. L'habitude de sauvegarder existe ; elle n'est jamais devenue un dispositif.

C'est aussi un argument de plus pour le design retenu : sauvegarder le *bind* embarquerait
ces 640 Mo de doublons à chaque passe, là où `VACUUM INTO` ne produit que la base vivante.
Candidats naturels à un nettoyage au lot 1.

`eurio.db` est en mode **WAL** (`eurio.db-wal` 82 432 o, `eurio.db-shm` 32 768 o présents),
ce qui interdit une copie fichier naïve et impose `VACUUM INTO`.

**Les secrets de MinIO et de review sont absents du dépôt** — formulation précise :
les *répertoires* ne sont pas ignorés, mais leur contenu l'est, via des règles
`<dir>/*` (`.gitignore:234:infra/minio/secrets/*` et
`infra/review/.gitignore:6:secrets/*`). Seuls les `.example` et `.gitkeep` sont
committés. Un `git clone` ne fournit donc **aucun secret utilisable**, et une
restauration s'arrête très tôt. Point porté à la session « secrets »
(cf. [`DECISIONS.md`](./DECISIONS.md) D-09).

`eurio-scrape-tor` possède un **volume Docker anonyme** pour `/var/lib/tor` (clés
d'identité de l'instance Tor). Vraisemblablement jetable — mais la décision n'est pas
prise. Voir [`ROADMAP.md`](./ROADMAP.md), « Ce qui vient après ».

## 7. Une deuxième archive pCloud, non mentionnée jusqu'ici

Il existe **deux** copies de l'archive du 17 juin, et non une :

| Chemin pCloud | Objets | Taille | Date |
|---|---|---|---|
| `pcloud:backups/serverOimNix/Eurio` | 21 661 | 3,842 GiB | 2026-06-17 |
| **`pcloud:eurio-backup`** | 21 661 | 3,841 GiB | 2026-06-17 00:24 → 01:59 |

Mêmes 4 dossiers, même contenu apparent. Le lot 7 doit trancher **les deux**, sinon on
en supprime une en croyant tout nettoyer — ou on en garde une orpheline dont plus
personne ne connaît la clé.


## 8. Trois sauvegardes qui réussissent en protégeant moins que leur nom

Découvert en réparant, le 2026-08-15. **Aucun de ces trois points n'est lié à la panne
de transport** — ils étaient là avant, ils y sont encore, et chacun produit un job vert.

### 8.1 Beszel ne sauvegarde rien, et ne l'a jamais fait

Une faute de casse dans `/opt/stacks/oim-duplicati/compose.yaml` :

```
/opt/stacks/devOps/oim-Beszel   ← monté dans Duplicati : répertoire VIDE
/opt/stacks/devOps/oim-beszel   ← les vraies données : 4,7 Mo
```

`ExaminedFiles: 0` sur **tous** ses runs historiques. Correction : une lettre, à faire
en même temps que le montage `/opt/eurio` (lot 4).

### 8.2 Des fichiers critiques sont exclus faute de permissions

Duplicati tourne en `PUID`/`PGID` et n'a pas accès à certains chemins :

```
Warning-…-PermissionDenied: Excluding path: /oim-traefik-source/volumes/…
Warning-…-PermissionDenied: Excluding path: /oim-traefik-source/scripts/
Warning-…-PermissionDenied: Excluding path: /oim-ntfy-source/.claude/
```

`/oim-traefik-source/volumes/` contient **`acme.json`**, les certificats Let's Encrypt.
Le job Traefik a « réussi » en envoyant **1 818 octets** : ce n'est pas une sauvegarde de
Traefik, c'est une sauvegarde de ce que Duplicati a le droit de lire.

### 8.3 Immich et Authentik sauvegardent leur configuration, pas leurs données

- **Immich** : la ligne `- /opt/stacks/oim-immich/library:/oim-immich-library` est
  **commentée** dans le compose, et la bibliothèque vit en réalité sur
  `/mnt/hetzner-storage/immich` (stockage réseau), non monté. Le job envoie ~5 ko. Les
  1,206 GiB totaux des 10 jobs confirment qu'aucune photothèque n'y est.
- **Authentik** : le `pg_dump` est une **procédure manuelle** documentée, jamais
  automatisée (aucun `run-script-before`, aucun cron, aucun timer). `backup-temp/`
  contient un unique dump daté du **8 novembre 2025**, fidèlement resauvegardé depuis.

### Ce que ces trois cas prouvent

> Un job vert ne dit pas « mes données sont protégées ». Il dit **« l'outil a fait ce
> qu'on lui a demandé »** — et ce qu'on lui a demandé peut être vide, tronqué, ou figé.

C'est exactement l'angle mort que les invariants de niveau 3 comblent
([`VERIFICATION.md`](./VERIFICATION.md) §3), et la démonstration que le problème dépasse
largement Eurio. Ces trois points sortent en tickets séparés, sauf 8.1 qui se corrige
dans la même édition de compose que le lot 4.
