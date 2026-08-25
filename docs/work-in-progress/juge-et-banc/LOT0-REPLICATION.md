# Lot 0 — répliquer le corpus device : prêt à lancer, **rien n'a été publié**

> Mesuré le **2026-08-25** sur le Mac (`Musubi42s-MacBook-Air-Oim`), branche
> `repo-cleanup`. **Aucune écriture MinIO, aucun commit, aucun fichier supprimé.**
> Seul `ml/scripts/training_assets.py` a été modifié (deux entrées de registre).
> `shared/training-assets.json` est **inchangé** — seul un `publish` réel le réécrit.
> Chaque chiffre porte sa commande. Ce qui est estimé porte un ⚠️.
>
> 🟢 **Le fait en une ligne** : deux entrées ajoutées au registre `ASSETS`, le
> `--dry-run` passe (`exit=0`) et annonce **77 Mo à transporter en 2 objets** ;
> il ne reste qu'une commande à autoriser.

---

## 1. Ce qui a été ajouté

`ml/scripts/training_assets.py`, registre `ASSETS` :

```python
("device_debug_pull", "tree", "debug_pull"),
("eval_real_norm",    "tree", "ml/datasets/eval_real_norm"),
```

Motif strictement identique aux deux entrées existantes (ADR-004) : `kind="tree"`,
`dest` relatif à la racine du dépôt, identité par `tree_digest` sur le **contenu**,
archive `tar.gz` déterministe, clé `training/<name>/<digest[:12]>/<name>.tar.gz`.

**Bucket : `model-artifacts`** — il n'y a pas eu de choix à faire, `cmd_publish`
n'utilise que `ARTIFACTS_BUCKET` (`ml/shared/storage/local_cache.py:312`), qui vaut
déjà `model-artifacts`. C'est **la** bonne valeur, et pour une raison décisive :

```bash
sed -n 74p infra/backup/eurio-backup.sh
# MIRROR_BUCKETS=(${EURIO_BACKUP_BUCKETS-enrichment-crops enrichment-raws numista-canonical model-artifacts eurio-db})
```

Cette liste est **en dur**. Un bucket neuf serait hors miroir, donc hors des 5
anneaux, et **cet oubli serait muet** — le corpus paraîtrait sauvegardé sans l'être.

## 2. Aucun symlink dans les deux arbres (contrôle bloquant)

`_iter_tree` (`ml/scripts/training_assets.py:81-86`) **refuse** un lien symbolique,
et l'échec ne surviendrait qu'en toute fin de course, après avoir tout haché.

```bash
find debug_pull ml/datasets/eval_real_norm -type l | wc -l
# 0
```

✅ Contrôle passé. Rien ne bloque la publication de ce côté.

## 3. Le `--dry-run`, sortie intégrale

```bash
cd ml && ./.venv/bin/python -m scripts.training_assets publish --dry-run; echo "exit=$?"
```

```
  = detection_dataset        déjà publié (5dd7a1b88105)
  = coin_detector_weights    déjà publié (ab6e746976ef)
  + device_debug_pull        À PUBLIER training/device_debug_pull/83f103e0074a/device_debug_pull.tar.gz (2968 fichiers, 74.7 Mo transportés)
  + eval_real_norm           À PUBLIER training/eval_real_norm/697e80ca36c0/eval_real_norm.tar.gz (114 fichiers, 2.3 Mo transportés)

(dry-run — manifeste non réécrit)
exit=0
```

⚠️ Le dry-run **requiert `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`** (il fait un
`head_object` par asset pour savoir ce qui existe déjà) : il ne se joue que dans
le devShell direnv. Il ne fait **que** des lectures.

### Volume exact, par entrée

```bash
cd ml && ./.venv/bin/python -c "
from scripts.training_assets import _content_digest, REPO_ROOT, ASSETS
for n,k,d in ASSETS:
    dg,nf,sz=_content_digest(k,REPO_ROOT/d); print(n,dg[:12],nf,sz)"
```

| Entrée | digest | fichiers | contenu sur disque | objet transporté | état |
|---|---|---:|---:|---:|---|
| `detection_dataset` | `5dd7a1b88105` | 7 580 | 47 500 604 o (47,5 Mo) | 43,5 Mo | déjà publié |
| `coin_detector_weights` | `ab6e746976ef` | 1 | 6 221 866 o (6,2 Mo) | 6,2 Mo | déjà publié |
| **`device_debug_pull`** | `83f103e0074a` | **2 968** | **76 330 291 o (76,3 Mo)** | **74,7 Mo** | **à publier** |
| **`eval_real_norm`** | `697e80ca36c0` | **114** | **2 367 074 o (2,4 Mo)** | **2,3 Mo** | **à publier** |

**Total à écrire : 2 objets, 77,0 Mo.** Rien n'est écrasé : les clés portent le
digest du contenu, elles n'existent pas encore dans le bucket.

```bash
cd ml && ./.venv/bin/python -c "
from shared.storage import local_cache
for o in local_cache._client().list_objects_v2(Bucket='model-artifacts',Prefix='training/').get('Contents',[]):
    print(o['Key'], o['Size'])"
# training/coin_detector_weights/ab6e746976ef/best.pt 6221866
# training/detection_dataset/5dd7a1b88105/detection_dataset.tar.gz 43453961
```

## 4. La commande que le PO devra lancer

Depuis le Mac, **dans le devShell direnv** (les secrets MinIO viennent de SOPS) :

```bash
cd /Users/musubi42/Documents/Musubi42/bizz/EurioProject/Eurio/ml
./.venv/bin/python -m scripts.training_assets publish; echo "exit=$?"
```

Hors shell interactif, l'équivalent explicite :

```bash
sops exec-env secrets/dev.env 'go-task ml:training-assets:publish'
```

Ce que ça fait, et rien d'autre : envoie les **2** archives manquantes dans
`model-artifacts`, puis **réécrit `shared/training-assets.json`** avec les 4
entrées. ⚠️ **Ce fichier est le livrable à committer** — c'est lui qui épingle le
corpus ; sans lui, `fetch` ne sait pas quoi rapatrier. Le commit doit contenir
`shared/training-assets.json` **et** `ml/scripts/training_assets.py`.

Vérification d'après-coup (le vrai point d'entrée, pas seulement les tests) :

```bash
cd ml && ./.venv/bin/python -m scripts.training_assets status; echo "exit=$?"   # attendu : 4 « à jour », exit=0
```

⚠️ **Durée estimée, non mesurée** : 77 Mo vers `eurio-s3.musubi.dev` en deux
`upload_file`, plus la construction des deux archives (hachage de 3 082 fichiers,
déjà fait deux fois en < 1 min chacune pendant le dry-run).

## 5. Ce qui a été exclu, et pourquoi

**`app-android/debug_pull/` — exclu.** Re-mesuré ici, et le chiffre de la mission
(« 677/677 ») ne se reproduit pas ; le fait, lui, tient :

```bash
ha=$(find debug_pull -type f -exec shasum -a 256 {} \; | awk '{print $1}' | sort -u)
hb=$(find app-android/debug_pull -type f -exec shasum -a 256 {} \; | awk '{print $1}' | sort -u)
echo "root=$(echo "$ha"|wc -l) android=$(echo "$hb"|wc -l) communs=$(comm -12 <(echo "$ha") <(echo "$hb")|wc -l) android_only=$(comm -13 <(echo "$ha") <(echo "$hb")|wc -l)"
# root=2184 android=857 communs=857 android_only=0
du -sh app-android/debug_pull   # 26M
```

**857 hachés distincts, 857 déjà sous la racine `debug_pull/`, zéro contenu
propre.** 26 Mo pour zéro information. À noter : la racine `debug_pull/` ne
contient pas `app-android/debug_pull/` — il n'y a donc **rien à filtrer**, juste
une entrée à ne pas ajouter. La raison est écrite en commentaire dans le registre.

**Rien d'autre n'est exclu.** `_EXCLUDED_NAMES` / `_EXCLUDED_DIRS` retirent déjà
`.DS_Store`, `Thumbs.db`, `__pycache__`, `.ipynb_checkpoints` — résidus d'outils
qui rendraient le `tree_digest` dépendant de la machine qui publie.

⚠️ `debug_pull/` est publié **tel quel, doublons internes compris** : 2 968
fichiers pour 2 184 hachés distincts (2 150 `.jpg` pour 1 620 jpg distincts, 746
`*_raw.jpg` pour 492 distincts). Dédupliquer ferait perdre l'arborescence par
pull, qui porte la date et le protocole de capture. Le prix du doublon est
~15 Mo ; le prix d'une arborescence cassée est la traçabilité du corpus.

## 6. Ce que je n'ai pas pu établir

- **Le « 701 originales uniques » de l'énoncé ne se retrouve dans aucune de mes
  mesures.** Ce que je mesure sous `debug_pull/` : 2 968 fichiers, 2 184 hachés
  distincts, 2 150 `.jpg` (1 620 distincts), 746 `*_raw.jpg` (492 distincts), 812
  `.json`. Le 701 vient probablement d'un autre périmètre (⚠️ estimation). Sans
  incidence sur la publication : on publie l'arbre, pas un décompte.
- **Rien n'est vérifié côté sauvegarde.** Que `model-artifacts` soit dans
  `MIRROR_BUCKETS` est lu dans le source ; que le miroir tourne effectivement et
  reprenne ces 77 Mo ne se vérifie **que sur le VPS** (`go-task backup:verify`),
  hors de ma portée depuis le Mac. **À faire après le `publish`** — sinon on aura
  l'illusion de la sauvegarde sans sa preuve, exactement le silence que ce lot
  cherche à supprimer.
- **Le PC n'a pas été touché.** Le `eval_real_norm/` publié ici est celui du Mac
  (114 fichiers, pull du 2026-04-29) ; celui du PC, qui a servi au run 317/16, est
  un **autre** contenu (cf. `LOT0-CORPUS-DEVICE.md` §1). Publier celui-ci ne le
  remplace pas et ne le sauve pas.

## 7. Un silence rencontré en chemin, à consigner

Le **premier** dry-run a rendu `+ detection_dataset À PUBLIER` alors que l'objet
`training/detection_dataset/5dd7a1b88105/…` **existe** dans le bucket (vérifié par
`list_objects_v2` puis par un `head_object` direct, tous deux OK) ; le second
dry-run, identique, a rendu `= déjà publié`. Cause : `cmd_publish` enveloppe le
`head_object` dans un `except Exception: exists = False`
(`ml/scripts/training_assets.py:~270`) — **un incident réseau transitoire est
lu comme « objet absent »**. Conséquence bénigne aujourd'hui (le ré-upload va à la
même clé, il est idempotent), mais le message ment sur l'état du bucket, et un
opérateur pourrait en conclure que le dataset a été perdu. Non corrigé ici :
hors périmètre de ce lot, et le fichier est partagé.

## 8. Vérifications

```bash
cd ml && ./.venv/bin/python -m scripts.training_assets --help; echo "exit=$?"      # exit=0
cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly; echo "exit=$?"
# 2267 passed, 40 warnings in 114.55s — exit=0   (baseline tenue)
git diff --stat shared/training-assets.json                                        # (vide)
```
