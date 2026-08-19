# Eurio — restaurer depuis pCloud

> **Tu lis ce fichier parce que tu as perdu le serveur Eurio et que tu veux
> récupérer la donnée.** Suis les étapes dans l'ordre.
>
> Ce document décrit la chaîne **réellement en service** : Duplicati → pCloud.
> Il a été réécrit le 2026-08-16 pendant le premier exercice de restauration ;
> tout ce qu'il affirme a été exécuté ce jour-là, sauf mention contraire.
> _(La version précédente décrivait `rclone crypt`, une clé age dédiée et le
> chemin `backups/serverOimNix/Eurio` : cette chaîne est abandonnée, seule
> subsiste l'archive figée du 17 juin, cf. `ETAT-DES-LIEUX.md` §7.)_

## 1. Ce qu'il y a sur la destination

Duplicati est le **moteur unique** : transport, chiffrement AES, rétention,
historique. Il sauvegarde un répertoire de *staging* produit chaque nuit par
`eurio-backup.sh stage` — jamais les binds vivants.

| | |
|---|---|
| Job | `[17] Eurio` sur `oim-duplicati` (VPS) |
| Destination | `pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/Eurio` |
| Chiffrement | AES Duplicati, passphrase de 16 caractères |
| Rétention | `keep-versions = 30` — 30 **versions**, pas 30 jours |
| Volume | ~5,6 Gio à la destination pour ~6,4 Gio de source |

Arborescence restaurée. Les chemins sont stockés sous `/eurio-source/` (le bind
dans le conteneur Duplicati), mais `restore` retire ce dossier de tête : les
fichiers atterrissent directement dans `--restore-path` :

```
eurio.db                 SQLite canonique, VACUUM INTO depuis eurio-api
review.db                SQLite de eurio-review
manifest.json            sentinelle : sha256, comptages, dangling, orphelins
baseline-manifest.json   référence du dernier verify réussi
minio/enrichment-crops/  ┐
minio/enrichment-raws/   │ miroir S3 des buckets, par rclone
minio/numista-canonical/ │
minio/model-artifacts/   │
minio/eurio-db/          ┘ (transfers/ seulement — la copie de eurio.db y est exclue)
```

## 2. Ce dont tu as besoin

**Le clone du dépôt et ta clé age SOPS. C'est tout.** Depuis le 2026-08-16
(D-28/D-29), `secrets/dev.env` contient les deux secrets de restauration —
`DUPLICATI_PCLOUD_AUTHID` (le jeton pCloud) et `DUPLICATI_EURIO_PASSPHRASE` —
ainsi que les 6 secrets d'infra nécessaires à remonter la stack. Il n'y a plus
de dépendance circulaire « pour restaurer, il faut le serveur perdu ».

```bash
git clone git@codeberg.org:Musubi42/Eurio.git && cd Eurio
# ~/.config/sops/age/keys.txt doit contenir ta clé privée (backup : password manager)
go-task secrets:check          # doit dire « déchiffrable »
```

⚠️ **Sans la clé age, la sauvegarde est irrécupérable.** C'est volontaire.

## 3. Outils

Restaure avec le **même Duplicati que celui qui a écrit** (2.2.x) quand c'est
possible.

- **Sur le VPS**, si le conteneur vit encore : `/app/duplicati/duplicati-cli`
  dans `oim-duplicati`.
- **Ailleurs** : `nix shell nixpkgs#duplicati` (2.3.0.1 au 2026-08-19) ou
  l'image `duplicati/duplicati:2.2.0`. **Une 2.3 lit bien une sauvegarde
  2.2** — vérifié le 2026-08-19 : `duplicati-cli find` déchiffre et liste les
  5 `dlist` écrits par le 2.2.0 du conteneur. C'est le chemin par défaut de
  l'exercice automatisé, puisque c'est celui du jour J : le conteneur
  `oim-duplicati` est ce que le sinistre emporte.

Deux binaires voisins à ne pas confondre :

| Chemin | Ce que c'est |
|---|---|
| `duplicati-cli` | **le CLI** — c'est celui-là |
| `duplicati` | le serveur TrayIcon : **core dump** si on lui passe une commande |
| `duplicati-server-util` | parle au serveur (list-backups, run, pause) — aucune commande `restore` |
| `duplicati-recovery-tool` | plan B si l'index distant est cassé |

## 4. Le fichier de paramètres — ne mets jamais l'URL sur la ligne de commande

L'URL de destination contient `?authid=<jeton>`. Passée en argument, elle
traverse le shell, `ssh`, `docker exec` — et il suffit qu'une couche la
déguillemette pour que tout ce qui suit `?` disparaisse. L'erreur qui en résulte
ne dit pas ça : elle dit `Value cannot be null (Parameter 'url')` depuis
`ApplySecretProvider`, ce qui envoie chercher un problème de secret provider qui
n'existe pas. **Trois tentatives ont été perdues là-dessus.**

La forme fiable met tout dans un fichier, y compris la destination
(`--target`) et la passphrase — aucun secret dans `argv`, donc rien dans
`ps` ni dans l'historique :

```bash
sops exec-env secrets/dev.env 'bash -s' <<'EOF'
umask 077
cat > /tmp/eurio-restore.params <<PARAMS
--target=pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/Eurio?authid=${DUPLICATI_PCLOUD_AUTHID}
--passphrase=${DUPLICATI_EURIO_PASSPHRASE}
--dbpath=/tmp/eurio-restore.sqlite
PARAMS
EOF
```

L'URL positionnelle reste obligatoire dans la syntaxe ; `--target` la remplace,
donc on passe un `dummy://x` sans conséquence.

## 5. Vérifier l'accès, et CHOISIR la version

```bash
duplicati-cli find dummy://x --parameters-file=/tmp/eurio-restore.params
```

Ça télécharge les `dlist` (~3 Mio par version) et liste les versions. Puis, et
**c'est l'étape que l'exercice a rendue obligatoire** :

```bash
duplicati-cli find dummy://x '*.json' '*.db' --version=0 --parameters-file=…
```

> ⚠️ **Ne restaure pas la version la plus récente les yeux fermés.**
> `manifest.json` est la sentinelle du staging : `stage` le **supprime en
> premier** et le réécrit en dernier. Un `stage` qui échoue laisse donc un
> staging sans manifeste — et Duplicati, qui est planifié indépendamment, le
> téléverse quand même. Constaté le 2026-08-16 : la version la plus récente à
> la destination n'avait pas de manifeste, celle de la veille oui.
>
> **Une version sans `manifest.json` est invérifiable : remonte d'un cran.**

## 6. Reconstruire l'index, puis restaurer — dans cet ordre

```bash
# 1) index complet (toutes versions) — ~15 min, ne restaure rien
duplicati-cli repair dummy://x --parameters-file=/tmp/eurio-restore.params

# 2) restauration proprement dite
duplicati-cli restore dummy://x '*' \
  --parameters-file=/tmp/eurio-restore.params \
  --restore-path=/chemin/jetable/eurio-drill \
  --restore-permissions=false --overwrite=true --version=<N>
```

**Pourquoi en deux temps** : lancer directement `restore --version=N` sans base
locale déclenche une reconstruction **partielle** de l'index. Les dlist des
autres versions restent sans fileset, et Duplicati échoue sur sa propre
incohérence après avoir téléchargé tout l'index :

```
DatabaseInconsistency — Detected 1 volume with missing filesets:
duplicati-<horodatage>.dlist.zip.aes, State = Uploaded
```

Ce n'est **pas** une sauvegarde corrompue. Un `repair` préalable, qui traite
toutes les versions, lève le problème.

Écris la base locale (`--dbpath`) sur un disque avec de la place : elle et les
fichiers temporaires pèsent quelques Gio pour ce dépôt.

**Combien de temps, mesuré le 2026-08-16** (VPS Hetzner, destination pCloud) :

| Étape | Durée |
|---|---|
| `find` (lecture des versions) | ~1 min |
| `repair` (index complet) | ~4 min |
| `restore` de 33 957 fichiers / 6,470 Gio | **30 min 58 s** |

Compte donc ~40 min pour récupérer la donnée, plus le temps de remonter la
stack. La première tentative — celle qui a échoué sur `DatabaseInconsistency` —
avait consommé 13 min avant d'abandonner.

## 7. Vérifier la restauration — le vrai critère

La restauration n'est pas réussie parce que des fichiers sont apparus. Elle est
réussie quand la **même suite d'invariants qui tourne chaque nuit** passe sur
l'arborescence restaurée :

```bash
python3 infra/backup/verify_invariants.py /chemin/jetable/eurio-drill \
  --baseline /chemin/jetable/eurio-drill/baseline-manifest.json --repo-root .
```

**Aucun service n'a besoin de tourner** : le miroir MinIO est restauré avec le
reste, donc l'échantillonnage d'objets et le contrôle de cohérence DB ↔ MinIO
travaillent sur des fichiers. Résultat obtenu le 2026-08-16 sur la copie
restaurée :

```
✅ 16/18 invariants passés, 2 avertissement(s)
   sha256 des deux bases ≡ manifeste · integrity_check ok · 0 violation FK
   0 dangling des deux côtés · 1 841 et 3 140 orphelins · 33 953 objets
   ⚠️ les 2 avertissements sont attendus : sources figées depuis 35 j, donc la
      non-décroissance ne prouve rien sur elles
```

La promotion de la référence (`baseline-manifest.json`) échoue sur une copie
restaurée, qui appartient à un autre utilisateur : c'est **normal et dit comme
tel**, ce n'est pas un invariant en défaut.

Contrôle minimal si tu n'as vraiment que quelques minutes :

```bash
sha256sum eurio.db review.db
python3 -c "import json;m=json.load(open('manifest.json'));print({k:v['sha256'] for k,v in m['files'].items()})"
```

Les deux doivent coïncider : c'est le round-trip complet (staging → chiffrement
→ pCloud → déchiffrement) prouvé sur les octets.

## 8. Remonter la stack

À partir d'ici, suis
[`RESTAURATION.md`](../../docs/work-in-progress/backup-pipeline/RESTAURATION.md)
§1, dont l'ordre n'est pas négociable :

1. secrets d'infra **régénérés depuis SOPS** (`infra/minio/secrets`,
   `infra/review/secrets`) ;
2. MinIO **vide** puis `infra/minio/bootstrap.sh` (buckets + policies) ;
3. `rclone sync staging/minio/<bucket> → minio:<bucket>` — **le store référencé
   d'abord** ;
4. poser `eurio.db` et `review.db` dans les binds — **sans** fichiers `-wal` /
   `-shm` : le `VACUUM INTO` produit une base autonome ;
5. démarrer `eurio-api` et `eurio-review` ;
6. rejouer les invariants contre la stack complète.

## 9. Si ça coince

| Symptôme | Cause réelle |
|---|---|
| `Value cannot be null (Parameter 'url')` | l'URL n'est jamais arrivée — guillemets mangés. Passe par `--parameters-file` (§4) |
| `DatabaseInconsistency … missing filesets` | reconstruction partielle de l'index. `repair` d'abord (§6) |
| core dump immédiat | tu as lancé `duplicati` et non `duplicati-cli` (§3) |
| `Failed to log in` sur l'API du serveur | inutile pour restaurer : la destination et la passphrase sont dans SOPS, pas besoin du serveur |
| Jeton pCloud refusé | `DUPLICATI_PCLOUD_AUTHID` a expiré ou été révoqué. Le régénérer côté pCloud et le remettre dans SOPS **avant** d'en avoir besoin |

## 10. Méta

- Chaîne décrite et décidée dans
  [`docs/work-in-progress/backup-pipeline/`](../../docs/work-in-progress/backup-pipeline/) —
  `ARCHITECTURE.md` pour le dispositif, `DECISIONS.md` pour le pourquoi,
  `RESTAURATION.md` pour la procédure complète, `VERIFICATION.md` pour les
  invariants.
- Dépôt canonique : Codeberg (`git@codeberg.org:Musubi42/Eurio.git`).
