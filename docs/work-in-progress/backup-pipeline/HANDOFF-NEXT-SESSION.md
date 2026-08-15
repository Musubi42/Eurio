# Handoff — reprise de session

> Écrit le 2026-08-16 à la fin d'une longue session. **Lots 0 à 4 livrés, lot 5 à
> moitié.** Eurio a sa première sauvegarde automatisée hors site, et l'ordonnancement
> est actif. Ce qui manque : les alertes.

## Lire dans cet ordre en reprenant

1. Ce fichier, en entier.
2. [`README.md`](./README.md) — le principe directeur et la table des lots.
3. [`DECISIONS.md`](./DECISIONS.md) — 23 décisions, chacune avec ce qu'elle **écarte**.
4. [`ROADMAP.md`](./ROADMAP.md) lot 5 — le travail immédiat.

Le reste (`ETAT-DES-LIEUX`, `DONNEES`, `ARCHITECTURE`, `VERIFICATION`, `RESTAURATION`)
se lit à la demande.

---

## Où on en est vraiment

| Lot | | Statut |
|---|---|---|
| 0 | Copie manuelle hors site | ✅ |
| 1 | `stage` + manifeste | ✅ |
| 2 | Invariants + test négatif | ✅ |
| 3 | Miroir MinIO + cohérence inter-stores | ✅ |
| 4 | Job Duplicati + ordonnancement NixOS | ✅ |
| **5** | **Alerting** | ✅ **4 anneaux sur 5 branchés et prouvés** (reste `eurio-drill`, cf. ci-dessous) |
| 6 | Restauration + exercice à froid | ⬜ |
| 7 | Décommissionnement de l'ancien chemin | ⬜ |

**Ce qui est ordonnancé** :

```
02:00 UTC  eurio-backup-stage.service    (timer NixOS armé)
02:30 UTC  eurio-backup-verify.service   (timer NixOS armé)
03:00 UTC  Duplicati job « Eurio » (ID 17) → pCloud
```

> ⚠️ **Armé ≠ prouvé.** Au 2026-08-16 00:20 CEST, `systemctl list-timers 'eurio-*'`
> affiche `LAST = -` sur les deux unités : **elles n'ont encore jamais tiré**, ayant été
> installées après l'heure de déclenchement. Le staging et la première sauvegarde ont été
> produits **à la main**. La première exécution automatique est le 2026-08-16 à 04:00 CEST.
> C'est la distinction n°1 du chantier appliquée à l'ordonnancement lui-même : tant que le
> timer n'a pas tiré une fois et laissé une trace dans le journal, on a un dispositif
> préparé, pas un dispositif qui tourne.

**Première sauvegarde réussie** (déclenchée à la main) : 33 957 fichiers, 6,47 Gio
examinés, 5,61 Gio poussés en 8 min 59, zéro erreur, zéro avertissement.

> ⚠️ **Le dispositif tourne, mais personne ne sera prévenu s'il s'arrête.** C'est
> exactement la situation des 10 jobs Duplicati pendant neuf mois. La différence est
> qu'on sait précisément quel signal manque — et c'est le lot 5.

---

## Contre-vérification indépendante — 2026-08-16 00:20 CEST

Refaite depuis la machine, sans se fier aux statuts affichés.

| Contrôle | Commande | Résultat |
|---|---|---|
| **Arrivée à destination** | `rclone size pcloud:Applications/DuplicatiBackup/Oim/Eurio` | **235 objets · 5,613 GiB** |
| **Archive refermée** | `rclone lsl …` | `duplicati-20260815T214948Z.dlist.zip.aes` — dlist récent, extension `.aes` ⇒ chiffré |
| **Invariants** | `go-task backup:verify` | **16/18 ✅ + 2 ⚠️ attendus** |
| **Ordonnancement** | `systemctl list-timers 'eurio-*'` | armé, `LAST = -` ⇒ **jamais tiré** |
| **Alerting** | idem | **0 anneau sur 4 configuré** |

La présence d'un `dlist` daté prouve une archive complète et refermée, pas un dépôt
d'orphelins — c'est le contrôle qui distingue « des fichiers sont arrivés » de « une
sauvegarde restaurable existe ».

Le `.stage.lock` résiduel est **inoffensif** : le script verrouille par `flock` (l. 182),
pas par l'existence du fichier.

---

## ✅ Lot 5 — état au 2026-08-16 01:00 CEST

Les anneaux sont branchés dans `infra/backup/notify.conf` (gitignoré, `chmod 600`).
**Chacun a été prouvé par un `down` réel arrivé sur Discord**, pas par une lecture de code.

| # | Anneau | Support | État |
|---|---|---|---|
| 1 | `eurio-staging` | Kuma push | ✅ up/down prouvés |
| 2 | `eurio-verify` | Kuma push | ✅ up/down prouvés |
| 3 | `eurio-uploaded` | Duplicati job 17 | ✅ configuré — 1re preuve à 03:00 UTC |
| 4 | healthchecks.io | hors site | ✅ up/down prouvés |
| 5 | `eurio-drill` | → healthchecks.io | 🟡 monitor Kuma **en pause**, à porter au lot 6 (**D-26**) |

### Deux défauts trouvés en branchant — les deux inversaient le signal

Aucun n'était visible en lecture, ni attrapé par les 20 cas du test négatif. Les deux
faisaient dire « tout va bien » au dispositif **au moment précis où tout allait mal**.

1. **healthchecks.io ignore les paramètres de requête.** `notify` envoyait
   `?status=down` à l'URL de base — ce qui y enregistre un **succès**. L'état se porte
   par le chemin (`<url>/fail`). Corrigé : `notify` prend un 5e paramètre de dialecte
   (`kuma` | `hc`).
2. **`stage_rc` était `local`.** Le trap `EXIT` s'exécute *après* le retour de
   `cmd_stage`, donc après la disparition des variables locales : sous `set -u`, les
   sous-shells du trap échouaient et `notify` partait avec un **statut vide**, que Kuma
   lit comme un succès. Un `stage` mort en cours de route annonçait donc « up ».
   Corrigé (variable globale) et **le chemin d'échec est désormais exercé** :
   `EURIO_DB_CONTAINER=inexistant ./eurio-backup.sh stage` ⇒ `→ eurio-staging : down`.

> La suite de tests ne couvrait pas le chemin d'échec du trap, et ne pouvait pas
> découvrir le dialecte de healthchecks : elle n'appelait aucun endpoint réel. **Un
> anneau ne se valide qu'en le débranchant pour de vrai.** C'est la même limite que
> celle relevée au lot 2 : un test écrit par l'auteur du code teste ce qu'il a pensé à
> tester.

### `send-http-level = Success`, et non `all`

Le plan initial disait `all`. C'est faux, pour la raison n°1 ci-dessus : un monitor Push
passe au vert **dès qu'il reçoit un ping**, quel qu'en soit le contenu. Avec `all`,
Duplicati pingerait aussi après un échec ⇒ Kuma vert sur une sauvegarde ratée.

Avec `Success`, seule une exécution réussie pinge, et **c'est le silence qui alerte**
(dépassement des 25 h). Un run terminé en *Warning* ne pinge pas non plus : il déclenche
donc une alerte, ce qui est le bon défaut — on préfère regarder un avertissement de trop
que manquer une sauvegarde partielle.

### `eurio-drill` — différé au lot 6, délibérément

Kuma **plafonne l'intervalle à 2 073 600 s (24 j)**, alors que l'exercice de restauration
est trimestriel (~90 j). Un monitor à 24 j serait donc rouge en permanence entre deux
exercices.

Ne pas le laisser rouge « en attendant » : **un monitor perpétuellement rouge apprend à
ignorer les alertes**, ce qui est exactement la pathologie du chantier. Deux options à
trancher au lot 6, quand le script d'exercice existera :

- **(recommandé)** porter l'anneau 5 sur **healthchecks.io**, qui accepte des périodes
  jusqu'à 365 j — et qui est de toute façon hors site ;
- ou garder Kuma et accepter une cadence d'exercice mensuelle (24 j).

En attendant : monitor `eurio-drill` **mis en pause dans Kuma le 2026-08-16** ✅. Sa Push
URL est déjà dans `notify.conf`, rien à recréer. Décision complète : **D-26**.

### Les `403 Forbidden` du miroir MinIO — élucidés, bénins, non masqués

`stage` émet quelques `NOTICE: Failed to read metadata: HeadObject 403` (une poignée sur
33 953 objets). **L'intégrité est intacte**, vérifié objet par objet : `sha256` local ≡
`sha256` distant, taille ≡ taille, `mtime` préservé.

Cause : Cloudflare devant `eurio-s3.musubi.dev` **rate-limite les HEAD signés sous
rafale** (`--transfers 8`) — alternance 403/OK pendant un burst, 8/8 OK au repos, et 200
en HEAD non authentifié depuis le cache CDN. Ce n'est pas une permission manquante.

`rclone sync` bâtit son plan depuis **LIST** (qui porte taille et `mtime`) : un HEAD
refusé ne retire aucun objet du transfert. On a **écarté `--s3-no-head-object`**, qui
ferait taire le message : on ne masque pas un avertissement pour retrouver une sortie
propre. Détail complet et chiffres : **D-27**.

---

## 🔴 Travail immédiat — *(historique : lot 5 terminé, conservé pour la trace)*

### Étape 1 — Créer 4 push monitors dans Uptime Kuma *(humain, ~3 min)*

Sur `uptime.musubi.dev` → **Add New Monitor** → **Monitor Type = Push** :

| Nom (Friendly Name) | Heartbeat Interval | Retries | Notification |
|---|---|---|---|
| `eurio-staging` | `90000` s (25 h) | `0` | ☑ Musubi Discord |
| `eurio-verify` | `90000` s (25 h) | `0` | ☑ Musubi Discord |
| `eurio-uploaded` | `90000` s (25 h) | `0` | ☑ Musubi Discord |
| `eurio-drill` | `8640000` s (100 j) | `0` | ☑ Musubi Discord |

25 h et non 24 h : le job tourne toutes les 24 h, la marge évite une alerte au premier
retard de quelques minutes.

**`Retries = 0` est délibéré** : sur un monitor *Push*, un « retry » ne re-teste rien —
Kuma attend passivement un ping qui, par construction, n'arrivera pas avant le prochain
cycle de 24 h. Une valeur non nulle ne ferait que **retarder l'alerte d'un cycle entier**.

Chaque monitor, une fois créé, affiche sa **Push URL** :
`https://uptime.musubi.dev/api/push/<token>` — c'est ce `<token>` qui compte.

### Ce qu'il faut me fournir

Les **5 URLs** ci-dessous. Elles contiennent des jetons ⇒ elles atterrissent dans
`notify.conf`, **gitignoré**, jamais dans un commit.

```
eurio-staging   → https://uptime.musubi.dev/api/push/XXXXXXXX
eurio-verify    → https://uptime.musubi.dev/api/push/XXXXXXXX
eurio-uploaded  → https://uptime.musubi.dev/api/push/XXXXXXXX
eurio-drill     → https://uptime.musubi.dev/api/push/XXXXXXXX
healthchecks.io → https://hc-ping.com/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
```

Note l'asymétrie : `eurio-uploaded` ne va **pas** dans `notify.conf` — il se branche
dans Duplicati (étape 4), seul à savoir si l'upload a réussi.

**Je n'ai pas créé ces monitors moi-même** : Kuma n'a pas d'API REST de création, et
écrire dans `kuma.db` à la main sur un service de monitoring partagé en production est
exactement le raccourci que R0 interdit. Trois minutes d'interface valent mieux.

Chaque monitor donne une **Push URL** de la forme
`https://uptime.musubi.dev/api/push/<token>`.

### Étape 2 — Créer un compte healthchecks.io *(humain, ~5 min)*

Offre gratuite (20 checks, largement au-delà du besoin).

1. **Add Check** → Name `Eurio backup`
2. **Period** = `1 day` · **Grace Time** = `6 hours`
   *(grâce 6 h : le staging à 02:00 UTC + Duplicati à 03:00 UTC + marge de dérive ;
   plus court alerterait sur une simple nuit lente, plus long masquerait un jour perdu)*
3. **Integrations → Discord** → connecter le webhook du serveur Musubi, puis **cocher
   l'intégration sur le check** *(une intégration créée mais non cochée sur le check ne
   notifie rien — c'est le même piège que les 10 jobs Duplicati sans destinataire)*
4. Copier la **Ping URL** (`https://hc-ping.com/<uuid>`)

**Pourquoi ce quatrième anneau, alors que Kuma alerte déjà ?** C'est le seul anneau
**hors site**, et c'est le seul qui fonctionne *par absence*. Kuma et ntfy tournent sur le
VPS qu'ils surveillent, et il n'y a qu'un seul VPS : si la machine meurt, Kuma meurt avec
elle et **personne n'envoie l'alerte**. healthchecks.io, lui, n'attend rien d'autre qu'un
ping quotidien — c'est son silence qui déclenche. Un dead man's switch ne peut pas vivre
sur la machine qu'il surveille.

Corollaire : le ping n'est envoyé **que si tous les invariants passent**. Un ping
inconditionnel transformerait le dispositif en « le VPS est allumé », ce qu'on sait déjà.

### Étape 3 — Remplir `notify.conf` *(moi, dès que j'ai les URLs)*

```bash
cp infra/backup/notify.conf.example infra/backup/notify.conf   # gitignoré
```

Quatre variables : `KUMA_STAGING_URL`, `KUMA_VERIFY_URL`, `KUMA_DRILL_URL`,
`HEALTHCHECKS_URL`. La plomberie est **déjà écrite et testée** — un anneau vide est
signalé bruyamment à chaque exécution, jamais silencieux.

### Étape 4 — Anneau 3 dans Duplicati *(moi)*

Ajouter au job « Eurio » (ID 17), par l'API :

```
--send-http-url   = <push URL de eurio-uploaded>
--send-http-level = all
```

**C'est l'anneau le plus important du chantier.** Les invariants tournent tous sur le
staging *local* : aucun ne prouve que Duplicati a poussé quoi que ce soit. Un staging
impeccable et une destination qui refuse tout produisent le même signal — vert. C'est
littéralement ce qui s'est passé pendant neuf mois. Et il est directement réutilisable
pour les 10 autres jobs.

### Étape 5 — Le critère de fin *(moi)*

```bash
./infra/backup/eurio-backup.sh notify-test    # envoie un `down` réel sur chaque anneau
```

**Un échec provoqué doit effectivement arriver sur Discord.** Tant que ce test n'est pas
passé, le lot 5 n'est pas fini : un canal d'alerte non testé est une alerte qui n'existe
pas.

---

## Commandes

```bash
go-task backup:stage          # snapshots VACUUM INTO + miroir MinIO + manifeste
go-task backup:verify         # 18 invariants
go-task backup:verify -- --accept-baseline   # acquitter une décroissance légitime
go-task backup:test           # 20 cas négatifs — la suite sait-elle dire non ?
./infra/backup/eurio-backup.sh notify-test   # teste les anneaux

systemctl list-timers 'eurio-*'
journalctl -u eurio-backup-stage -u eurio-backup-verify --since today
```

---

## Les cinq idées qui gouvernent tout ce chantier

Si tout le reste est oublié, garder ça.

1. **Un dispositif préparé ≠ qui tourne ≠ qui arrive ≠ complet ≠ restaurable.** Cinq
   états que le « ✅ » d'un job confond en un seul. Vérifié **cinq fois** sur cette
   machine (README §Principe directeur).
2. **Les invariants sont calculés, jamais lus.** `storage_status` vaut `'present'` sur
   100 % des lignes, y compris celles qui pointent vers un objet absent (D-10).
3. **L'absence de preuve n'est pas une preuve.** Un contrôle qu'on n'a pas pu faire
   s'affiche ⚠️, jamais ✅. C'est par là que passent les pertes silencieuses.
4. **On capture le store référençant avant le store référencé.** DB puis MinIO ⇒
   orphelins (bénins). L'inverse ⇒ dangling (corruption silencieuse) (D-04).
5. **Le critère d'acceptation d'une restauration est la suite de tests nocturne.** Un
   seul corpus, deux usages : ils ne peuvent pas diverger (D-13).

---

## Ce qui a été découvert en chemin, et qui dépasse Eurio

À traiter hors de ce chantier, mais **ne pas perdre** :

| # | Découverte | État |
|---|---|---|
| 1 | **Les 10 jobs Duplicati n'écrivaient plus rien depuis 3 à 9 mois** — WebDAV Basic Auth déclenchait la vérification d'appareil pCloud, chaque nuit à 3 h | ✅ **réparé** (backend pCloud OAuth) |
| 2 | **Beszel sauvegardait un répertoire vide** depuis nov. 2025 — faute de casse `oim-Beszel` / `oim-beszel` | ✅ **corrigé**, 727 ko envoyés depuis |
| 3 | **Traefik n'envoie que 1 818 octets** — `acme.json` exclu faute de permissions (Duplicati tourne en PUID/PGID) | ⬜ ticket à ouvrir |
| 4 | **Immich sauvegarde sa config, pas la photothèque** — ligne commentée dans le compose, données sur `/mnt/hetzner-storage` non monté | ⬜ ticket à ouvrir |
| 5 | **Authentik : `pg_dump` documenté, jamais automatisé** — `backup-temp/` contient un dump du 8 nov. 2025, resauvegardé chaque nuit depuis | ⬜ ticket à ouvrir |
| 6 | **924 notifications non acquittées** dans Duplicati | ⬜ à purger |
| 7 | **`/etc/nixos` n'est dans aucun job Duplicati** | ⬜ à vérifier |

Les points 3, 4 et 5 sont la même pathologie : **des jobs verts qui protègent moins que
leur nom** (D-19). L'anneau 3 et les invariants de niveau 3 sont directement
transposables.

---

## Actions humaines en attente

| # | Action | Bloque |
|---|---|---|
| 1 | ~~Créer les 4 push monitors Kuma~~ | ✅ fait |
| 2 | ~~Créer le check healthchecks.io~~ | ✅ fait |
| 0 | **Vérifier que le timer du 2026-08-16 04:00 CEST a bien tiré** : `journalctl -u eurio-backup-stage -u eurio-backup-verify --since today` — c'est ce qui fait passer l'ordonnancement d'« armé » à « prouvé » | — |
| 0bis | **Vérifier que `eurio-uploaded` est passé au vert** après le run Duplicati de 03:00 UTC — c'est la 1re preuve de l'anneau 3, le seul qui atteste que la destination a reçu | — |
| 0ter | **Mettre `eurio-drill` en pause dans Kuma** jusqu'au lot 6 (cf. §Lot 5) | — |
| 3 | Supprimer `/opt/stacks/oim-duplicati/api-config-export-20260815/` — **identifiants WebDAV en clair** | — |
| 4 | Confirmer que `infra/minio/secrets` et `infra/review/secrets` sont couverts par la session « secrets » | Lot 6 |
| 5 | Décider du nettoyage des 8 sauvegardes ad hoc de `infra/eurio-api/data/` (~640 Mo) — suppression irréversible, je ne l'ai pas faite | — |
| 6 | Décider du sort du volume Docker anonyme de `eurio-scrape-tor` (clés Tor) | Lot 7 |

---

## Pièges à ne pas redécouvrir

| Piège | Détail |
|---|---|
| **Import NixOS par chemin absolu** | **Impossible** : le VPS est flake-based, l'évaluation pure refuse `/opt/eurio/nix/...`. Passer par l'input `eurio-nix`. Après modif du module : `nix flake update eurio-nix` **puis** `nixos-rebuild switch` (D-22) |
| **Deux `review.db`** | Le vrai : `infra/review/data/` (954 ko). Le résidu : `infra/eurio-api/data/` (49 ko, sans table `reviewers`) |
| **`staging/` contient des DONNÉES** | 6,6 Go gitignorés. Un `git clean -xdf` le détruit — d'autant que la branche s'appelle `repo-cleanup` |
| **`eurio-minio.service`** | **Supprimé** du module Nix. Son `ExecStop` faisait `docker compose down` : tout `systemctl stop` aurait coupé MinIO, `eurio-api`, `eurio-review` et le miroir |
| **Rétention Duplicati** | Les 10 jobs : `keep-versions = 30` (**versions**, pas jours). Le job Eurio : `keep-time = 30D`, borne temporelle explicite |
| **`bootstrap.sh` régénère les secrets MinIO** | S'ils manquent, il en crée de nouveaux → MinIO fonctionnel que `eurio-api` ne sait plus lire. Restaurer `infra/minio/secrets` **avant** |
| **Deux archives pCloud du 17 juin** | `pcloud:backups/serverOimNix/Eurio` **et** `pcloud:eurio-backup`. Ne pas en traiter qu'une |
| **Ne rien supprimer avant le lot 6** | Les archives de juin et la copie du lot 0 restent jusqu'au premier exercice de restauration réussi (D-14) |

---

## Chiffres de référence — 2026-08-16

```
Staging          6,6 Go · 33 953 objets · stage incrémental ~1 min 40
eurio.db         144 056 320 o (VACUUM INTO)   mtime source 2026-07-12
review.db        950 272 o                      infra/review/data/
MinIO (API S3)   enrichment-raws 17 129 · enrichment-crops 12 998
                 numista-canonical 3 824 · eurio-db/transfers 2
Cohérence        dangling = 0 · orphelins 4 981
                 (556 exclus : 546 chemins Mac + 10 mock)
Disque /         80 % · 78 Go libres
pCloud           Applications/DuplicatiBackup = 6,82 GiB (11 jobs)
                 dont Oim/Eurio = 5,61 GiB / 235 objets
Invariants       18 sur le staging réel (16 ✅ + 2 ⚠️ attendus)
Test négatif     20 cas, 0 en défaut
```

Les 2 ⚠️ attendus : `vivacité de la source` — `eurio.db` n'a pas bougé depuis le
12 juillet, donc la non-décroissance est vraie par construction et **ne prouve rien**.
Ils passeront au vert dès que le projet reprendra des écritures. C'est voulu : un
contrôle inopérant doit se voir.

---

## Commits de la session

```
d9744fef  feat(backup): lot 4 — Eurio entre dans Duplicati, ordonnancement NixOS
deb17258  feat(backup): lot 3 — miroir MinIO et invariants inter-stores
a1cadd35  fix(backup): corrige 6 defauts trouves par la revue adversariale
fb3a1a9b  feat(backup): lots 1 et 2 — staging verifiable + suite d'invariants
3624550d  docs(backup): lot 0 — copie chiffree des deux bases sur pCloud
7cfab826  docs(backup): chantier backup-pipeline + reparation Duplicati
```

Hors dépôt Eurio, modifié sur le VPS (retours arrière préparés) :

- `/opt/stacks/oim-duplicati/compose.yaml` — bind `:ro` + casse Beszel
  *(→ `compose.yaml.bak-20260815-234703`)*
- `/etc/nixos/flake.nix` — input `eurio-nix` *(→ `flake.nix.bak-20260815`, dépôt git)*
- Les 11 jobs Duplicati — destination pCloud OAuth
  *(→ `api-config-export-20260815/`)*

---

## La leçon de la session

On est parti pour sauvegarder Eurio. On a trouvé **cinq façons différentes d'avoir tort
en croyant être protégé** : un dispositif jamais branché, dix jobs qui échouent sans
destinataire, un dump figé depuis novembre, un job sur un dossier vide, un autre qui
exclut les certificats faute de permissions.

Aucune ne se voyait en regardant un statut. Toutes se voient en regardant **ce qui est
réellement arrivé à destination**.

Et la revue adversariale du lot 2 a trouvé trois trous dans la suite de vérification
elle-même — écrite justement pour attraper ces pertes silencieuses. Le test négatif
passait alors à 9/9 : il testait ce que j'avais pensé à tester. **C'est la limite
structurelle de tout test écrit par l'auteur du code**, et la raison de faire relire par
un tiers ce dont dépendent des données irremplaçables.
