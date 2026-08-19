---
name: eurio-backup
description: Sauvegarder et restaurer Eurio — les 3 timers, les 5 anneaux, l'exercice de restauration en une commande, et les pièges qui rendent le dispositif muet. À lire avant de toucher à infra/backup/, avant de répondre « est-ce qu'on est sauvegardés ? », et le jour où il faut vraiment restaurer.
---

# Sauvegarder Eurio, et savoir qu'on peut le récupérer

> Ce chantier existe parce que **10 jobs Duplicati sont morts pendant neuf mois
> sans que personne le sache**. Le défaut n'était pas l'absence de sauvegarde :
> c'était l'absence de témoin. Tout ce qui suit découle de là — chaque anneau,
> chaque invariant, chaque refus de « masquer un avertissement pour retrouver une
> sortie propre ».
>
> Les deux questions ne sont pas la même, et il faut les deux :
> **la sauvegarde est-elle crédible ?** (les invariants, chaque nuit) et
> **est-elle restaurable ?** (l'exercice, chaque trimestre).

## ⚠️ Tout ceci ne tourne que sur le VPS

`backup:stage`, `backup:verify`, `backup:test`, `backup:drill` dépendent de
conteneurs Docker locaux (`eurio-api`, `eurio-review`, MinIO), d'un staging de
7 Go et de `infra/backup/notify.conf` — **tous gitignorés**, donc absents sur
Mac/PC. Ne pas les y lancer, ne pas « réparer » leur absence.

⚠️ `infra/backup/staging/` contient **7 Go de données** gitignorées. Un
`git clean -xdf` les détruit.

## Le dispositif en une image

```
02:00 UTC  eurio-backup-stage.service    → staging (VACUUM INTO + miroir MinIO + manifeste)
02:30 UTC  eurio-backup-verify.service   → 18 invariants ; ne pingue hors site que si TOUT est vert
03:00 UTC  Duplicati job 17 « Eurio »    → pCloud, AES, keep-time=30D
                                           portier /eurio-gate.py AVANT (refuse un staging sans manifeste)
trimestriel eurio-backup-drill.service   → exercice de restauration complet, 5 jan/avr/juil/oct 04:00 UTC
```

Duplicati est le **moteur unique** : transport, chiffrement, rétention,
historique. `eurio-backup.sh` ne parle jamais au distant.

**Les 5 anneaux** (`infra/backup/notify.conf`, gitignoré, `chmod 600`) :

| # | Anneau | Porté par | Ce que son silence signifie |
|---|---|---|---|
| 1 | `eurio-staging` | Kuma push | le script est cassé, Docker HS, disque plein |
| 2 | `eurio-verify` | Kuma push | ça a tourné mais les **données** sont mauvaises |
| 3 | `eurio-uploaded` | Duplicati (`--send-http-url`) | la destination n'a rien reçu ← la panne des 10 jobs |
| 4 | healthchecks.io | hors site | **le VPS entier est mort** — Kuma ne peut pas le dire, il tourne dessus |
| 5 | `eurio-drill` | healthchecks.io (90 j / grâce 30 j) | l'exercice de restauration n'a pas eu lieu |

`send-http-level = Success` et **non `all`** : un monitor Push passe au vert dès
qu'il reçoit un ping, quel qu'en soit le contenu. Avec `all`, Duplicati pingerait
aussi après un échec.

## Répondre à « est-ce qu'on est sauvegardés ? »

Trois commandes, dans cet ordre. Ne jamais répondre depuis les statuts affichés
dans une interface.

```bash
# 1. les timers ont-ils TIRÉ ? (armé ≠ tiré : LAST = - veut dire jamais)
systemctl list-timers 'eurio-*' --all --no-pager

# 2. qu'ont dit les invariants, et les anneaux sont-ils partis ?
journalctl -u eurio-backup-verify.service --since -2d --no-pager \
  | grep -E "invariants passés|→ eurio-|→ healthchecks"

# 3. la destination a-t-elle reçu une archive REFERMÉE ?
rclone lsl pcloud:Applications/DuplicatiBackup/Oim/Eurio | grep dlist | sort -k2 | tail -1
```

Le contrôle 3 est celui qui distingue « des fichiers sont arrivés » d'« une
sauvegarde restaurable existe » : un `dlist` daté prouve un fileset complet et
refermé, pas un dépôt d'orphelins. L'extension `.aes` prouve le chiffrement.

Mesures du 2026-08-19 pour étalonner ce que « sain » veut dire (commandes
ci-dessus, ce jour-là) : `17/18 invariants passés, 1 avertissement`,
`Total objects: 266 · 6,130 GiB`, dernier dlist `duplicati-20260819T140245Z`.
Le 18e invariant est un avertissement **attendu** : `review.db` est inchangée
depuis ~38 jours, donc la non-décroissance ne prouve rien sur elle.

## Restaurer

**Procédure du jour J** :
[`infra/backup/README-RESTORE.md`](../../../infra/backup/README-RESTORE.md) — écrit
*pendant* une restauration réelle, corrigé par elle.

**S'entraîner, ou vérifier que ça marche encore** :

```bash
go-task backup:drill          # 28 min mesurées, ~14 Go, ne touche pas la production
go-task backup:drill:status
go-task backup:drill:down     # à lancer même après un échec
```

Il fait ce que le jour J impose : `git clone` du canonique, **rebuild des
images**, restauration pCloud, stack isolée, invariants, et il demande à
l'application de servir la donnée. Succès → acquitte l'anneau 5 puis détruit ;
échec → anneau au rouge (`drill-fail`) et **tout est conservé** pour l'autopsie.

## Les pièges — chacun a coûté quelque chose

### 1. `nixos-rebuild switch` ne prend PAS les changements de `nix/eurio-vps.nix`

Le module est un **input de flake épinglé** dans `/etc/nixos/flake.lock`. Un
rebuild reconstruit fidèlement la copie épinglée, et rien ne signale l'écart :

```bash
# la révision réellement en service
python3 -c "import json;print(json.load(open('/etc/nixos/flake.lock'))['nodes']['eurio-nix']['locked'])"
# le geste manquant
cd /etc/nixos && sudo nix flake update eurio-nix && sudo nixos-rebuild switch
```

Symptôme vécu le 2026-08-19 : rebuild passé, `eurio-backup-drill.service`
inexistant (`No files found`) et toujours pas de `curl` dans le PATH des unités.
`flake.nix` le documente pourtant ligne 23. **Contrôler après, jamais avant** :
`systemctl list-timers 'eurio-*'` doit montrer **3** timers.

### 2. Docker rootless — le piège n°1 du dépôt

Les conteneurs vivent sur `/run/user/<uid>/docker.sock`. Une unité systemd
*système* ne charge pas le profil qui pose `DOCKER_HOST` : `docker exec eurio-api`
répond « No such container » pendant que `docker ps` le montre à l'écran. Le
timer de staging a échoué ainsi **à chacune de ses exécutions** jusqu'au
2026-08-16. Résolu dans `eurio-backup.sh` et `run-drill.sh` (pas dans l'unité,
pour que ça vaille aussi hors systemd).

### 3. Un anneau ne se valide qu'en le débranchant

Deux bugs trouvés en branchant le lot 5, **tous deux invisibles en lecture, et
tous deux inversant le signal** :

- **healthchecks.io ignore les paramètres de requête.** L'état se porte par le
  **chemin** : `<url>` = succès, `<url>/fail` = échec. Envoyer `?status=down` à
  l'URL de base y enregistre un **succès**. D'où le 5e paramètre de dialecte de
  `notify()` (`kuma` | `hc`).
- **une variable `local` lue dans un trap `EXIT`** partait vide sous `set -u`,
  et Kuma lit un statut vide comme un succès : un `stage` mort annonçait « up ».

```bash
./infra/backup/eurio-backup.sh notify-test   # envoie un down RÉEL sur chaque anneau
./infra/backup/eurio-backup.sh drill-fail    # anneau 5 au rouge
./infra/backup/eurio-backup.sh drill-ack     # anneau 5 au vert
```

### 4. Ne restaure pas la version la plus récente les yeux fermés

`stage` **supprime `manifest.json` en premier** et le réécrit en dernier :
un staging sans manifeste est un staging mort. Duplicati, planifié
indépendamment, le téléverse quand même — constaté le 2026-08-16, la version la
plus récente à la destination était invérifiable.

```bash
duplicati-cli find dummy://x '*manifest.json' --version=N --parameters-file=…
```

Pas de `/eurio-source/manifest.json` dans la sortie ⇒ **remonter d'un cran**.
`run-drill.sh pick` le fait automatiquement. Le portier `pre-upload-gate.py`
(`--run-script-before=/eurio-gate.py` sur le job 17) refuse désormais en amont,
avec le code **5** = « erreur, ne pas lancer ».

### 5. Duplicati — trois pièges dans la même commande

- **Jamais l'URL de destination dans `argv`.** Elle contient `?authid=<jeton>` ;
  une couche qui déguillemette fait disparaître tout ce qui suit `?`, et l'erreur
  parle d'un secret provider inexistant (`Value cannot be null (Parameter 'url')`).
  Tout passe par `--parameters-file` : cible, passphrase, dbpath.
- **`repair` AVANT `restore`.** Un `restore --version=N` sans base locale ne
  reconstruit l'index que partiellement et échoue sur sa propre incohérence
  (`DatabaseInconsistency`) après avoir tout téléchargé.
- **`duplicati-cli`, pas `duplicati`** — ce dernier est le TrayIcon et fait un
  core dump si on lui passe une commande.

L'API du serveur **est** scriptable, contrairement à ce qu'a longtemps dit la
ROADMAP (vérifié le 2026-08-19) :

```bash
docker exec oim-duplicati sh -lc \
  '/app/duplicati/duplicati-server-util list-backups --password "$DUPLICATI__WEBSERVICE_PASSWORD"'
# … run 17 · status
```

Attention : **l'interface web réécrit les noms d'options avec un préfixe `--`**
en sauvegardant (job 17 : `--send-http-url`, là où les jobs 7-16 ont des noms
nus). Vérifié sans conséquence sur le run suivant — à ne pas prendre pour un
symptôme en relisant `Duplicati-server.sqlite`.

### 6. L'exercice tourne depuis le CLONE

`run-drill.sh` clone Codeberg et exécute **le harnais du clone**, pas celui de
`/opt/eurio` : c'est tout l'intérêt. Une modification non poussée n'est donc pas
testée. Le script refuse de continuer si le compose du clone ignore
`DRILL_API_IMAGE`. **Committer et pousser avant de lancer.**

Corollaire utile : le drill trouve ce qu'aucune relecture ne trouve. Le
2026-08-19 il a établi que **`eurio-review` n'était plus reconstructible** depuis
le dépôt — image en service datant du 8 juin, `docker build` cassé.

### 7. Les fichiers restaurés résistent à `rm -rf`

Duplicati restaure les répertoires en `dr-xr-xr-x`, même avec
`--restore-permissions=false`. `rm -rf` échoue sur chacun (il faut le droit
d'écriture sur le **parent**), et 7 Go survivent. `run-drill.sh down` fait
`chmod -R u+w` puis **vérifie** que le répertoire a disparu.

### 8. Écriture refusée pendant un geste de sauvegarde

Un `readonly database` ou un `503 canonical_readonly` n'est **jamais** une panne
du dispositif de sauvegarde. Lire [`eurio-data-writes`](../eurio-data-writes/SKILL.md)
avant de contourner quoi que ce soit.

## Où continuer

| Question | Document |
|---|---|
| Restaurer pour de vrai | [`infra/backup/README-RESTORE.md`](../../../infra/backup/README-RESTORE.md) |
| L'ordre de restauration et son protocole | `docs/work-in-progress/backup-pipeline/RESTAURATION.md` |
| Ce que valent les invariants, et à quel niveau | `docs/work-in-progress/backup-pipeline/VERIFICATION.md` |
| Pourquoi telle décision, et ce qu'elle écarte | `docs/work-in-progress/backup-pipeline/DECISIONS.md` (32 entrées) |
| État, lots, exercices | `docs/work-in-progress/backup-pipeline/ROADMAP.md` |
| Le harnais d'exercice | [`infra/backup/drill/README.md`](../../../infra/backup/drill/README.md) |

Skills voisines : [`eurio-verify`](../eurio-verify/SKILL.md) (ici les pannes sont
muettes — c'est la même discipline), [`eurio-data-writes`](../eurio-data-writes/SKILL.md)
(où part une écriture), [`eurio-vps-deploy`](../eurio-vps-deploy/SKILL.md)
(remonter la stack après restauration).
