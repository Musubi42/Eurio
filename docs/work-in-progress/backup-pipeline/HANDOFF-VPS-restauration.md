# Passation — terminer l'exercice de restauration (lot 6), depuis le VPS

> **Pour qui** : une session Claude Code qui tourne **sur le VPS** (`nixos`,
> 176.9.107.216), avec accès direct aux conteneurs, aux composes de
> `/opt/stacks/`, et à la configuration NixOS de `/home/dontpanic/nixos`.
>
> **Pourquoi toi et pas moi** : la session qui a produit ce document travaillait
> depuis le Mac, par SSH. Elle pouvait lire et lancer, mais pas modifier un
> compose Duplicati ni reconstruire le système. Elle a buté trois fois sur la
> forme d'appel du CLI et s'est arrêtée là plutôt que de tâtonner.
>
> **Date de l'état décrit** : 2026-08-16, ~20 h 30 CEST. Vérifie avant d'agir —
> tout ce qui suit a été mesuré, pas supposé, mais l'état bouge.

---

## 1. L'objectif en une phrase

Prouver qu'on sait **restaurer Eurio depuis pCloud**, puis corriger la
documentation de tout ce qui aura manqué. C'est le lot 6 de
[`ROADMAP.md`](./ROADMAP.md), le protocole est en
[`RESTAURATION.md`](./RESTAURATION.md) §4, et le critère de réussite est la suite
d'invariants de [`VERIFICATION.md`](./VERIFICATION.md) §3.

Tant que ce n'est pas fait, Eurio a des sauvegardes **vérifiées à l'émission,
jamais à la réception**.

---

## 2. Ce qui est déjà acquis — ne le refais pas

### La chaîne locale marche, depuis aujourd'hui seulement

Elle n'avait **jamais** fonctionné : le timer `eurio-backup-stage` avait tourné
une fois depuis son installation et échoué. Cause, corrigée dans `a46b887` :

> Le VPS fait tourner **Docker en rootless**. Les conteneurs Eurio vivent sur
> `/run/user/<uid>/docker.sock`, désigné par `DOCKER_HOST` dans un shell
> interactif. Une unité systemd **système** ne charge pas ce profil, donc
> `docker` interrogeait le démon root — où aucun conteneur Eurio n'existe.
> `docker exec eurio-api` répondait « No such container » pendant que
> `docker ps` le montrait à l'écran.

`infra/backup/eurio-backup.sh` résout maintenant `DOCKER_HOST` lui-même
(`resolve_docker_host`) et vérifie les conteneurs avant de commencer
(`require_container`). Corrigé dans le **script** et pas dans l'unité, pour que
ça vaille aussi hors systemd.

État vérifié après correction, en reproduisant l'environnement systemd :

```
✅ staging prêt — 6,7 Go, manifeste écrit
✅ 17/18 invariants passés, 1 avertissement
   (le 18e : review.db inchangée depuis 35 j — attendu)
   dangling 0 des deux côtés · 1 841 crops et 3 140 raws orphelins
```

⚠️ **Le service systemd lui-même n'a pas été relancé** — la session n'avait pas
`sudo` sans mot de passe. Elle a reproduit l'environnement de l'unité à la main
(`env -i` + le PATH exact de l'unité). **Première chose à faire : vérifier que le
timer réussit vraiment maintenant**, avec `systemctl start eurio-backup-stage`
puis `journalctl -u eurio-backup-stage`.

### La sauvegarde distante existe et est fraîche

| Fait | Valeur |
|---|---|
| Job Duplicati | `[17] Eurio` |
| Dernier run | 2026-08-16 03:01:28 UTC → 03:02:52 (1 min 23) |
| Taille destination | **5,627 Gio**, 238 fichiers cible, 2 versions |
| Source | 6,470 Gio, 33 956 fichiers |
| Planification | quotidienne 05:00, `Repeat=1D` |
| Destination réelle | `pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/Eurio` |

⚠️ **`README-RESTORE.md` ment sur trois points** : il décrit le chemin
`backups/serverOimNix/Eurio`, l'outil `rclone crypt`, et une clé age dédiée.
Rien de tout ça n'est la chaîne actuelle. Sa réécriture fait partie du lot.

### Comment lire la config du job sans deviner

L'URL de destination est chiffrée (`enc-v1:`) dans `Duplicati-server.sqlite`,
mais le serveur la rend en clair par son API :

```sh
docker exec oim-duplicati sh -c '
  TOK=$(curl -s -X POST http://127.0.0.1:8200/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d "{\"Password\":\"$DUPLICATI__WEBSERVICE_PASSWORD\"}" \
    | sed -n "s/.*\"AccessToken\":\"\([^\"]*\)\".*/\1/p")
  curl -s -H "Authorization: Bearer $TOK" http://127.0.0.1:8200/api/v1/backup/17
'
```

Le JSON contient `TargetURL` (avec `authid`) et, dans `Settings`, une entrée
`passphrase` (16 caractères). Les mêmes valeurs sont aussi dans
`secrets/dev.env` (SOPS) sous `DUPLICATI_EURIO_PASSPHRASE` et
`DUPLICATI_PCLOUD_AUTHID` — c'est ce qui rend la restauration possible **sans**
le VPS, et c'est la décision D-28.

---

## 3. Le point de blocage exact

### Le binaire existe — ce n'est pas un problème d'installation

Dans le conteneur `oim-duplicati` (image 2.2.0) :

```
/app/duplicati/duplicati-cli      ← LE CLI, c'est celui-là
/app/duplicati/duplicati          ← le serveur TrayIcon : core dump si on lui
                                    passe une commande. Piège perdu 10 minutes.
/app/duplicati/duplicati-server-util   ← parle au serveur : list-backups, run,
                                    pause… mais AUCUNE commande restore
/app/duplicati/duplicati-recovery-tool ← plan B, voir §4
```

### L'appel qui échoue, et son erreur

```sh
/app/duplicati/duplicati-cli restore "$URL" "*eurio.db" \
  --restore-path=/backups/drill --passphrase="$PASS" \
  --restore-permissions=false --dbpath=/tmp/drill.sqlite
```

```
The operation Restore has failed => Value cannot be null. (Parameter 'url')
System.ArgumentNullException: Value cannot be null. (Parameter 'url')
   at Duplicati.Library.Utility.Uri..ctor(String url)
   at Duplicati.Library.Main.Controller.ApplySecretProvider(...)
```

**Ce qui est notable** : l'exception vient d'`ApplySecretProvider`, pas du
parsing de la destination. Ça ne ressemble pas à « ton URL est mauvaise » mais à
« un *secret provider* est configuré quelque part et son URL à lui est nulle ».

### Hypothèses, de la plus probable à la moins

1. **`SETTINGS_ENCRYPTION_KEY` est dans l'environnement du conteneur** (posé par
   le compose). Le CLI le voit, en déduit qu'un fournisseur de secrets est actif,
   et cherche une `--secret-provider` URL qu'il ne trouve pas. → tester avec
   `env -u SETTINGS_ENCRYPTION_KEY`, ou en passant `--secret-provider=""`.
2. Le CLI lit `/config/` par défaut et y trouve un réglage de secret provider
   incomplet. → tester avec `--server-datafolder=/tmp/vide`.
3. L'URL contient `?authid=...` : si une couche de shell la déguillemette, tout
   ce qui suit `?` disparaît. La session a quoté, mais à travers
   `ssh → docker exec sh -c` — trois niveaux. **Toi tu es sur la machine : écris
   l'URL dans un fichier et lis-la, ne la fais pas transiter par des guillemets
   imbriqués.**
4. Argument positionnel mal placé : en 2.2 la forme est
   `duplicati-cli restore <url> [<filtres>] --options`. Le glob `"*eurio.db"`
   pourrait devoir être `--include` à la place.

**Commence par `duplicati-cli help restore`** — ça n'a pas été fait, et c'est
gratuit.

---

## 4. Les options si le CLI du conteneur résiste

| Option | Ce que ça coûte | Ce que ça vaut |
|---|---|---|
| **A — corriger l'appel** dans le conteneur | rien | le plus propre : même version que celle qui a écrit la sauvegarde |
| **B — `duplicati` depuis nixpkgs** sur l'hôte | `nix shell nixpkgs#duplicati` — **version 2.3.0.1** | pratique, mais ⚠️ **2.3 lit une sauvegarde écrite par 2.2** : la restauration devrait passer, ce n'est pas garanti. Si tu l'utilises, dis-le dans le compte rendu — un exercice réussi avec un autre binaire que celui de production ne prouve pas tout à fait la même chose |
| **C — interface web** Duplicati | manuel, non scriptable | prouve la restauration mais ne laisse pas de trace rejouable. Acceptable en dernier recours, à condition de noter les étapes |
| **D — `duplicati-recovery-tool`** | conçu pour « le serveur est perdu » | c'est **le** scénario du lot 6. Vaut le détour même si A marche |

Préférence : **A**, puis **D** en complément. **B** seulement si A échoue, et en
le signalant.

---

## 5. Le protocole à respecter

De [`RESTAURATION.md`](./RESTAURATION.md) §4 — la règle du jeu compte autant que
le résultat :

1. Répertoire jetable **hors `/opt/eurio`**.
2. Restaurer **depuis pCloud**, jamais depuis `infra/backup/staging/` — l'exercice
   doit traverser réseau, identifiants et déchiffrement. Restaurer depuis le
   staging local ne prouverait rien.
3. Ports et projet compose **distincts** : la production ne doit pas bouger.
4. Exécuter la suite d'invariants contre la stack restaurée.
5. Corriger `README-RESTORE.md` de tout ce qui a manqué ou menti.
6. Noter date et résultat dans [`ROADMAP.md`](./ROADMAP.md) (le tableau existe
   déjà, exercice #1 y est ouvert).
7. Acquitter le push monitor Kuma `eurio-drill`.
8. Détruire le répertoire jetable.

**Un exercice partiel bien décrit vaut mieux qu'un exercice complet raconté à
l'approximation.** Si tu ne restaures que `eurio.db`, dis-le, et mesure au moins
ça : temps, taille, et sha256 comparé au `manifest.json` du staging.

### Garde-fous

- **Ne touche pas** `/opt/eurio/infra/backup/staging/` : 6,7 Go de données, la
  sauvegarde du jour, gitignorée. Un `git clean -xdf` la détruit.
- **Ne relance pas** `eurio-backup.sh stage` pendant un exercice : il écrase le
  staging et ferait bouger la référence sous tes pieds.
- L'espace disque est à **80 % (77 Go libres)**. Une restauration complète des
  6,43 Gio passe, mais surveille.
- `/opt/eurio` est un checkout git sur `repo-cleanup`, à jour au commit du
  correctif. Si tu modifies le script, commite-le, ne le laisse pas divergent.

---

## 6. Les trois défauts à corriger, indépendants de la restauration

Trouvés en réparant la chaîne. Ils sont plus urgents que l'exercice lui-même :
sans eux, la prochaine panne sera à nouveau silencieuse.

### 6.1 — Aucun anneau de notification ne fonctionne 🔴

Les trois répondent « INJOIGNABLE » alors que `infra/backup/notify.conf` est
renseigné (`KUMA_STAGING_URL`, `KUMA_VERIFY_URL`, `HEALTHCHECKS_URL`,
`KUMA_DRILL_URL` ont tous une valeur).

La sentinelle a parfaitement détecté l'absence de manifeste. **Personne ne l'a
su.** Un dispositif de détection dont l'alerte est muette a exactement la même
valeur qu'aucun dispositif — c'est le constat que ce chantier entier était censé
corriger.

À faire : tester chaque URL à la main (`curl -sv`), identifier si c'est Kuma qui
est tombé, l'URL qui a changé, ou le réseau du conteneur.

### 6.2 — Un `verify` en échec n'empêche pas Duplicati de téléverser 🟠

`stage` 02:00 UTC, `verify` 02:30, Duplicati 03:00 — trois planifications
**indépendantes**. Le 16 août, Duplicati a fidèlement sauvegardé un staging que
la sentinelle venait de déclarer invalide.

À arbitrer, ce n'est pas évident : une sentinelle bloquante protège d'un mauvais
téléversement mais peut faire sauter une nuit entière de sauvegarde. Une
sauvegarde légèrement périmée vaut peut-être mieux que pas de sauvegarde. **Pose
la question au PO plutôt que de trancher seul.**

### 6.3 — Le staging n'a pas de sentinelle d'âge côté Duplicati 🟡

Duplicati sauvegarde ce qu'il trouve. Si `stage` échoue trois semaines, il
téléverse trois semaines de suite le même staging périmé, avec succès à chaque
fois. L'invariant de fraîcheur existe côté `verify` (plafond 36 h) — mais il ne
parle à personne (cf. 6.1).

---

## 7. Ce que la session Mac continue en parallèle

Le **mapping complet des flux de données** — où naît chaque donnée, par quel
transport elle voyage, où elle vit sur chacune des trois machines. Carte
actuelle : `docs/architecture/README.md` et `artifacts.md`, tous deux mis à jour
aujourd'hui.

Pour éviter de se marcher dessus : **tu prends `infra/backup/`,
`infra/*/compose*`, la config NixOS et les composes de `/opt/stacks/`.** La
session Mac reste sur `ml/`, `docs/architecture/` et `docs/work-in-progress/`
hors `backup-pipeline/`.

Si tu modifies `docs/work-in-progress/backup-pipeline/*`, dis-le dans ton
compte rendu — c'est la seule zone partagée.

---

## 8. Contexte utile qui n'est écrit nulle part ailleurs

- **Le VPS est en Docker rootless.** Ça explique la panne du lot 6, et ça
  piégera toute automatisation future qui parle à Docker depuis systemd.
- **`eurio-scrape-tor` est `unhealthy` depuis ~5 semaines.** Pré-existant, jamais
  investigué, hors périmètre — ne pars pas dessus.
- **Les 403 de MinIO** pendant le miroir (`Failed to read metadata: 403`) sont un
  bruit connu (P1 de `storage-hardening`, jamais résolu à la source, masqué par
  un retry). Ils n'empêchent pas le staging d'aboutir. Ne les traite pas comme
  une régression.
- **Les 1 841 crops et 3 140 raws orphelins** dans MinIO ne sont pas des déchets :
  leur fiche vivait dans les `.bak` de `ml/state/`, audités et supprimés le
  2026-08-16. Le détail est dans `docs/architecture/artifacts.md`. L'invariant
  « dangling == 0 » reste vrai et c'est bien le bon critère.
- **`git clean -xdf` dans `/opt/eurio` détruit 6,7 Go de staging.** Il est
  gitignoré.
