# Lot 4 — ce que la fuite vaut, mesuré

> Fait le **2026-08-25** sur le Mac (`Musubi42s-MacBook-Air-Oim`, Apple M3),
> branche `repo-cleanup`. Deux runs jumeaux sur la cohorte `70c74956061f`
> (clone de `ab28928bcdc2` / `owned-ready-24`), notés contre le corpus device
> par `scripts/replay_corpus.py`. Chaque chiffre porte sa commande.
>
> Aucun commit, aucun push, rien sur le VPS, rien sur MinIO.
> Ni `ml/training/*` ni `ml/scripts/replay_corpus.py` n'ont été modifiés.
>
> Préparation, calibration et choix de E : [`LOT4-PREPARATION.md`](./LOT4-PREPARATION.md).

---

## 🟢 Le résultat, en cinq lignes

**La fuite de centroïdes vaut +14,7 points sur les photos qu'elle a vues, et
−4,4 points sur celles qu'elle n'a pas vues.** Globalement elle vaut **+0,24
point** (p = 1,0) — et ce zéro est un **artefact de moyenne**, pas une absence
d'effet : il additionne un gain massif et significatif sur un sous-ensemble
(p = 6,1 × 10⁻⁵) et une perte sur l'autre.

🔴 **Et le hasard a rendu l'expérience plus propre que prévu : les deux runs
sont le MÊME réseau, au bit près** (242/242 tenseurs identiques, écart max
0,0). L'écart mesuré ne peut donc venir **que des centroïdes** — la fuite de
sélection de checkpoint s'est trouvée inerte (§6). C'est une isolation parfaite
du §1bis de [`PROBLEME.md`](./PROBLEME.md), et elle n'était pas planifiée.

---

## 🔴 À lire avant tout chiffre de ce document

**1. Les deux runs sont SOUS-ENTRAÎNÉS.** 8 epochs, dont **5 à backbone gelé** et
**3 seulement dégelés**. Le run de référence du 2026-08-16 en faisait 40. Ce que
ce lot établit est le **signe et l'existence** de l'écart entre A et B — **pas
son amplitude à convergence**. Rien ne garantit que l'écart à 8 epochs ait la
même taille qu'à 40 ; il peut être plus petit (la fuite a eu moins le temps de
payer) comme plus grand.

**2. 🔴 `eval_real_norm/` EST le protocole d'avril** (démontré au §2). 19 classes × 6
conditions = 114 photos, vocabulaire identique (`bright_plain`,
`bright_textured`, `close_plain`, `daylight_plain`, `dim_plain`, `tilt_plain`,
19 chacune des deux côtés). Autrement dit : **le corpus qui a fuité dans le run
A est exactement le sous-ensemble d'avril du juge.** C'est ce qui rend la
lecture par protocole obligatoire — et c'est ce que la lecture globale cachait
(§7).

**3. La couche de textures était inerte des deux côtés** (§3). La recette
`test-3` déclare trois couches d'augmentation ; deux seulement se sont
appliquées.

**4. Ces `r@1` ne sont pas des performances**, et **ils ne se comparent pas au
`92,4 %` du 2026-08-16**. Trois raisons cumulées : le sous-entraînement, la
couche inerte, et le fait que le run de référence a tourné sur une autre
machine avec un pool de crops plus petit (5051 samples contre 6594 ici). ⚠️ **Si
le PC disposait de ses textures d'overlay le 2026-08-16, alors son bake n'est
pas celui-ci et le `92,4 %` n'est comparable à rien de ce qui est produit ici.**
Ce n'est pas un problème — notre comparaison est **interne à A ↔ B**, où tout
est partagé sauf deux clés — mais que personne ne rapproche les deux plus tard
sans le savoir.

---

## 1. Le protocole, et ce qui garantit que les deux runs sont jumeaux

| | **Run A — AVEC la fuite** | **Run B — SANS** |
|---|---|---|
| itération | `027254937193` (`l4-run-a-avec-fuite`) | `11b7a626c57a` (`l4-run-b-sans-fuite`) |
| **`val_source`** | 🔴 `device` | 🟢 `none` |
| **`centroid_source`** | 🔴 `auto` | 🟢 `train_mean` |
| `epochs` | 8 | 8 |
| `batch_size` · `m_per_class` | 256 · 4 | 256 · 4 |
| `augmentations_seed` | **20260825** | **20260825** |
| recette · `variant_count` | `3e022c8bb17a` (test-3) · 100 | idem |
| cohorte | `70c74956061f` (24 classes) | idem |

```bash
curl -s "http://127.0.0.1:8042/lab/cohorts/70c74956061f/iterations" \
 | python3 -c "
import json,sys
for it in json.load(sys.stdin):
    print(it['id'], it['name'], it['augmentations_seed'], it['training_config'])"
# 027254937193 l4-run-a-avec-fuite 20260825 {… 'val_source': 'device',
#                                              'centroid_source': 'auto'}
# 11b7a626c57a l4-run-b-sans-fuite 20260825 {… 'val_source': 'none',
#                                              'centroid_source': 'train_mean'}
```

**Exactement deux clés diffèrent.** Les trois valeurs `m_per_class` / `min_real`
/ `training_target` sont ajoutées d'office par la route (gel des seuils) et sont
identiques des deux côtés.

### 1bis. La graine, et pourquoi il a fallu la mesurer plutôt que la supposer

La route `POST …/iterations` **ne savait pas transporter `augmentations_seed`**
avant le correctif du lot 3 (`ml/serving/lab_routes.py`, 7 lignes, 3 tests,
mutation vérifiée — cf. `LOT4-PREPARATION.md` §4). Sans lui, le runner en tire
une au hasard et deux « jumeaux » reçoivent des augmentations différentes.

L'API a été redémarrée à **17:17:34** ; `lab_routes.py` porte une mtime de
**16:26:31** → le process tourne bien avec le correctif.

### 1ter. La preuve que les deux bakes sont le même bake

Un contrôle sur les **noms** de samples ne prouve rien : ils sont déterministes
et **indépendants de la graine**. Deux bakes de graines différentes rendent le
même hash de noms :

```bash
cd ml && for iid in 027254937193 8bbe7ac6c2ac; do
  find "datasets/iterations/$iid" -type l | sed "s|datasets/iterations/$iid/||" \
    | sort | shasum -a 256 | cut -c1-16
done
# e14dbc07a8ce6578   ← run A (graine 20260825)
# e14dbc07a8ce6578   ← calibration (graine 1842102175) — IDENTIQUE
```

⚠️ **C'est un piège** : on aurait pu « vérifier » la gémellité avec ce hash et
conclure à tort. La graine vit dans les **octets**, pas dans l'arborescence.
L'empreinte qui décide hache le contenu de tous les samples
(`scratchpad/hash_bake.sh`) :

```bash
find datasets -path "*/augmentations/<IID>/*.jpg" -type f -print0 | sort -z \
  | xargs -0 shasum -a 256 | sed "s|/augmentations/<IID>/|/augmentations/<IID>/|" \
  | shasum -a 256 | cut -c1-16
```

| bake | graine | empreinte du **contenu** |
|---|---:|---|
| calibration `8bbe7ac6c2ac` | 1842102175 | `93fc734ba730af4b` |
| **run A** `027254937193` | **20260825** | **`db99f441503a81e0`** |
| **run B** `11b7a626c57a` | **20260825** | **`db99f441503a81e0`** |

🟢 **Les deux contrôles tombent juste** : à graine identique, empreinte
identique (`db99f441503a81e0` des deux côtés) ; à graine différente, empreinte
différente. Les deux runs partagent **exactement** le même jeu d'entraînement,
au bit près.

---

## 2. 🔴 Le corpus qui a fuité EST le protocole d'avril

Sans ce fait, le résultat du §7 est illisible. `ml/datasets/eval_real_norm/` —
la source du split `val` du run A, donc de ses centroïdes — n'est pas « un
échantillon du corpus device » : c'est **exactement** le protocole
`device_pull_20260429`.

```bash
cd ml
find datasets/eval_real_norm -type f -name '*.jpg' \
  | sed 's|.*/||; s|\.jpg$||' | sort | uniq -c | sort -rn
#   19 tilt_plain   19 dim_plain      19 daylight_plain
#   19 close_plain  19 bright_textured  19 bright_plain
ls datasets/eval_real_norm | wc -l    # 19

sqlite3 "file:state/scan_corpus.db?immutable=1" \
  "select condition, count(*) from scan_corpus
    where bundle_source='device_pull_20260429' group by 1 order by 2 desc;"
# tilt_plain|19  dim_plain|19  daylight_plain|19
# close_plain|19 bright_textured|19  bright_plain|19
sqlite3 "file:state/scan_corpus.db?immutable=1" \
  "select count(distinct eurio_id) from scan_corpus
    where bundle_source='device_pull_20260429';"    # 19
```

**19 classes × 6 conditions = 114 photos des deux côtés, avec le même
vocabulaire de conditions.** Ce sont les mêmes prises de vue.

⚠️ Une comparaison **par octets** ne le montre pas — elle rend 0 correspondance.
`eval_real_norm/` est passé par `normalize_device` et ré-encodé en JPEG : les
pixels diffèrent, la provenance non. Conclure « aucun recouvrement » sur un
`sha256` aurait été l'erreur exacte que ce lot cherchait à éviter.

### Ce que ça impose à la lecture

| Sous-ensemble du juge | frames couvertes | Rapport à la fuite |
|---|---:|---|
| **avril `20260429`** | 102 | 🔴 **la fuite l'a vu** — les centroïdes de A en sont la moyenne |
| **juin `20260601`** | 317 | 🟢 jamais vu |

Noter un run fuité sur le corpus **entier** revient donc à moyenner un examen
dont on a eu les réponses (24 %) avec un examen honnête (76 %). Le §7 montre ce
que cette moyenne cache.

---

## 3. 🔴 Une couche d'augmentation inerte, et le garde qui n'a jamais pu garder

Trouvé en lisant le log du bake. La recette `test-3` (`3e022c8bb17a`) déclare
**trois** couches ; elle n'en applique que **deux**.

```bash
sqlite3 "file:ml/state/eurio.work-juge-banc.db?mode=ro" \
  "select config_json from augmentation_recipes where id='3e022c8bb17a';"
# {"count": 100, "layers": [
#   {"type": "perspective",  …},
#   {"type": "relighting",   …},
#   {"type": "overlays", "categories": ["patina","dust"], …}]}
```

Le répertoire de textures **n'existe pas**, et n'a **jamais** été versionné :

```bash
ls ml/training/data/overlays            # No such file or directory
git log --all -- 'ml/training/data/overlays/*'   # aucun commit
```

Les textures se **génèrent** (`go-task ml:augment-textures-generate`) ; ça n'a
jamais été fait sur ce Mac. Vérifié par la vraie fonction, code de sortie lu
sans pipe :

```bash
cd ml && ./.venv/bin/python -c "from training.augmentations.overlays import \
  sanity_check_textures; import sys; sys.exit(sanity_check_textures())" ; echo "exit=$?"
# | patina | 0 | missing-dir |   | dust | 0 | missing-dir |
# | scratches | 0 | missing-dir | | fingerprints | 0 | missing-dir |
# Total textures: 0
# exit=1
```

Le bake le **dit** — mais dans un log de job détaché, noyé :

```bash
grep -c "No overlay textures found" \
  ml/state/job_logs/augmentation-1c1ec3ddb75b4b56bd9b0001d6f74249.log
# 36
```

### Et le contrôle prévu pour attraper ça ne peut pas fonctionner

```bash
go-task ml:augment-textures-check ; echo "exit=$?"
# ModuleNotFoundError: No module named 'augmentations'
# exit=201
```

La commande importe `augmentations.overlays` au lieu de
`training.augmentations.overlays` — **dans les deux fichiers de tâches** :
`ml/tasks.yml:802` **et** `Taskfile.yml:203`. Le garde plante avant de rendre
son verdict, dans ses deux points d'entrée. Il n'a donc **jamais** pu signaler
l'absence de textures, sur aucune machine, depuis qu'il existe.

C'est le motif `eurio-verify` dans sa forme la plus pure : *un garde qui n'a
jamais gardé* — ici sur une couche d'augmentation qui n'a jamais été appliquée.

⛔ **Non corrigé volontairement.** Générer les textures en cours d'expérience
ferait diverger A et B. À traiter au lot 7. La portée pour ce lot : A et B
subissent **exactement la même privation**, donc la comparaison interne tient.
⚠️ Mais si le PC avait ses textures le 2026-08-16, son bake n'est pas celui-ci —
cf. l'avertissement n°3 en tête.

---

## 4. Le contexte d'exécution — mode compute, et le 503 qui ne parlait pas

Les deux runs ne pouvaient **pas** tourner sous le flip Direction A :
`training_runner.create_run_row` écrit `training_runs` dans le store, donc dans
la réplique en lecture seule. Et il échouait **en silence** — mesuré au lot
précédent : `HTTP 200`, itération `pending`, `error: null`, et le job détaché
mort en moins d'une seconde sur `attempt to write a readonly database`.

Bascule en mode compute :

```bash
sqlite3 ml/state/eurio.replica.db "VACUUM INTO 'ml/state/eurio.work-juge-banc.db'"
# 0,45 s — 228 Mo. Fichier NEUF : eurio.work.db (16 août) laissée intacte.
lsof -ti :8042 | xargs kill
EURIO_DB_READONLY= EURIO_DB_PATH="$PWD/ml/state/eurio.work-juge-banc.db" go-task ml:api-prod
ps eww -o command= -p $(lsof -ti :8042) | tr ' ' '\n' | grep -E '^EURIO_DB'
# EURIO_DB_PATH=…/ml/state/eurio.work-juge-banc.db
# EURIO_DB_READONLY=
```

⚠️ **`go-task ml:db:pull-replica` n'a pas été nécessaire** — et c'est contraire à
ce que la préparation prévoyait. `lab_writes` rafraîchit la réplique **après**
l'écriture canonique (`iteration_runner`, commentaire C5) : les deux itérations
créées sous le flip y étaient déjà lisibles, donc le `VACUUM INTO` les a
emportées.

### ⚠️ Le mtime du `.db` ment — chiffré

Au moment du `VACUUM INTO` :

```bash
ls -la --time-style=full-iso ml/state/eurio.replica.db*
# eurio.replica.db      2026-08-25 01:31:40   ← 16 heures de retard
# eurio.replica.db-wal  2026-08-25 17:21:16   ← la vérité
```

Le `.db` affichait **seize heures de retard** alors que les itérations venaient
d'y être écrites. En WAL, les écritures récentes vivent dans le sidecar : juger
la fraîcheur d'une réplique sur le `mtime` du `.db` aurait fait conclure
« rien n'a bougé » — et déclencher un pull inutile, ou pire, croire à une panne.

### La vérification qui compte : le job tourne vraiment

`HTTP 200` ne dit rien. La table `jobs` le dit :

```bash
cd ml && ./.venv/bin/python -c "
import sys;sys.path.insert(0,'.');import jobs
for r in jobs.connection().execute('select id,kind,status,error,started_at "
"from jobs order by rowid desc limit 1'): print(dict(r))"
# {'kind':'iteration','status':'running','error':None, …}
```

**`running`, pas `failed`.** Le mode compute lève bien le blocage.

---

## 5. Comment les deux runs ont été notés

```bash
cd ml
./.venv/bin/python -m scripts.replay_corpus --iteration 027254937193 \
  --path full --out /tmp/l4_a ; echo "exit=$?"
./.venv/bin/python -m scripts.replay_corpus --iteration 11b7a626c57a \
  --path full --out /tmp/l4_b ; echo "exit=$?"
```

**`--path full` est une condition de validité**, pas une option de performance :
quatre normaliseurs cohabitent dans les crops stockés (`hough_tight` 113,
`hough_relaxed` 1, `hough_strict` 280, `hough_loose` 57) et `fast` mélangerait
une différence de prise de vue avec une différence de code.

### Le McNemar apparié — et le piège du `.tflite`

`--baseline` prend un **dossier**, pas une itération, et `load_candidate` fait
`sorted(rglob("*.tflite")) or sorted(rglob("*.pth"))`
(`scripts/replay_corpus.py:101`). Pointer `--baseline` sur
`lab/iterations/027254937193` noterait donc la **baseline en int8** pendant que
le candidat est en fp32 : l'écart mesuré mélangerait la fuite et la
quantisation.

La parade est un **dossier miroir** qui ne contient que les deux artefacts que
`candidate_from_iteration` aurait choisis :

```bash
DST=/tmp/l4_baseline_a
rm -rf "$DST"; mkdir -p "$DST"
ln -s "$PWD/lab/iterations/027254937193/checkpoints/best_model.pth"    "$DST/best_model.pth"
ln -s "$PWD/lab/iterations/027254937193/embeddings/embeddings_v1.json" "$DST/embeddings_v1.json"
find "$DST" -name '*.tflite'    # doit être VIDE
```

### Ce qui se lit, et ce qui ne se lit pas

`r_at_1_eq` porte sur **451** frames dont **32 sont fausses par construction**
(leur classe n'existe dans aucun des deux modèles). Il **dilue**. Le lot 3 l'a
montré au pire : `0,1751` là où la vraie valeur était `0,9833`.

**La valeur qui décide est `r_at_1_on_covered`, citée avec son `n_on_covered`.**
Les deux sont donnés ci-dessous, jamais l'un sans l'autre.

⚠️ **`n_paired` du McNemar vaut 451, pas 419.** `crossed_stats` apparie toutes
les frames ; les 32 non couvrables tombent en `both_incorrect` des deux côtés.
Elles ne peuvent donc **pas** produire de paire discordante : `b` et `c` ne
viennent que des 419 couvrables. Le `n_paired` de 451 est correct et sans effet
sur la p-value.

---

## 6. 🔴 Les deux runs sont le même réseau — au bit près

Ce n'était pas prévu, et c'est le fait le plus utile du lot.

**Les pertes d'entraînement sont identiques, epoch par epoch :**

| epoch | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| **A** | 8.5001 | 3.3108 | 2.4195 | 1.9701 | 1.7030 | 0.4540 | 0.0202 | 0.0075 |
| **B** | 8.5001 | 3.3108 | 2.4195 | 1.9701 | 1.7030 | 0.4540 | 0.0202 | 0.0075 |

C'est attendu : même bake au bit près (§1ter), même `--seed 42`
(`train_embedder`, jamais surchargé par `pipeline.py`), même sampler. Ce qui
l'était moins, c'est la conséquence.

**A a sauvegardé aux epochs 6 (82,35 %), 7 (86,27 %) et 8 (86,27 %).** Le test
de sauvegarde est `>=` (`train_embedder.py:1016-1019`), donc l'epoch 8 l'emporte
sur l'egalité. B, sans val, garde le dernier epoch — **8 lui aussi**.

```bash
cd ml && ./.venv/bin/python - <<'PY'
import torch
B="lab/iterations"
a=torch.load(f"{B}/027254937193/checkpoints/best_model.pth",map_location='cpu',weights_only=False)
b=torch.load(f"{B}/11b7a626c57a/checkpoints/best_model.pth",map_location='cpu',weights_only=False)
sa,sb=a['model_state_dict'],b['model_state_dict']
print("tenseurs différents :", sum(1 for k in sa if not torch.equal(sa[k],sb[k])), "sur", len(sa))
print("arcface_W identiques :", torch.equal(a['arcface_weights'],b['arcface_weights']))
print("epochs :", a['epoch'], b['epoch'])
PY
# tenseurs différents : 0 sur 242
# arcface_W identiques : True
# epochs : 8 8
```

⚠️ Les fichiers `.pth` ont malgré tout des sha256 différents — ils diffèrent par
leurs **métadonnées** (`recall@1` : 0,8627 pour A contre 0,0 pour B, faute de
val ; `model_version` v35 contre v36). Comparer les fichiers aurait conclu
« modèles différents » ; seule la comparaison tenseur par tenseur dit la vérité.

### Ce que ça change pour la lecture

| Fuite de `PROBLEME.md` | Active dans ce run ? |
|---|---|
| §1 — **sélection de checkpoint** sur le juge | ❌ **inerte** : le meilleur epoch selon le juge s'est trouvé être le dernier |
| §1bis — **centroïdes** fabriqués depuis le juge | ✅ **seule variable** |

**L'écart A−B mesuré ci-dessous est donc, exactement et uniquement, le prix de
la fuite de centroïdes.** C'est une isolation qu'on n'aurait pas su fabriquer
exprès. ⚠️ Elle est aussi **fragile** : à 40 epochs, rien ne dit que le meilleur
epoch selon le juge serait encore le dernier, et la fuite de sélection
redeviendrait active. Ce lot ne mesure pas ce second terme.

### La preuve directe que la fuite est fermée côté B

C'est ce que le PO a demandé nommément, et ça ne dépend d'aucun chiffre de
performance.

```bash
grep -c "val_mean" ml/state/job_logs/iteration-50a176bb93d64223b841d9dc5032b4c5.log  # run A → 18
grep -c "val_mean" ml/state/job_logs/iteration-766a7118ab4745c1ae11c6ba286af75f.log  # run B →  0
```

Et dans l'artefact lui-même (`embeddings_v1.json`, champ `n_samples`) :

| | run A | run B |
|---|---|---|
| classes dont le centroïde vient de **6 photos du juge** | **17** | **0** |
| classes repliées sur `arcface_W` (1 « échantillon ») | **7** | **0** |
| `n_samples` min → max | **1 → 6** | **102 → 1818** |
| **total d'images derrière les 24 centroïdes** | **109** | **6594** |

`6594` est exactement la taille du bake : **B moyenne tout son entraînement**, A
moyennait 6 photos de test par classe. La fuite est close, et l'artefact en
porte la trace de façon vérifiable après coup.

⚠️ **Un défaut de message, au passage.** Le run A journalise
`WARNING: --centroid-source absent → défaut 'auto'` — alors que `pipeline.py` le
passe **explicitement** (`--centroid-source auto`) depuis le lot 2.
`describe_auto_source` se déclenche sur `source == "auto"` sans savoir si la
valeur a été passée ou héritée. Le message accuse une cause fausse ; à corriger
au lot 7, il induira en erreur le prochain qui le lira.

---

## 7. 🔴 Le résultat — et pourquoi le chiffre global ment

### 7.a Sur le corpus entier : rien. Et ce « rien » est faux

| | `r_at_1_on_covered` | `n` | `r_at_1_eq` (dilué) | `n` |
|---|---:|---:|---:|---:|
| **A — avec la fuite** | **0,6754** | 419 | 0,6275 | 451 |
| **B — sans** | **0,6730** | 419 | 0,6253 | 451 |
| **écart A − B** | **+0,0024** | | +0,0022 | |

**+0,24 point. Une frame sur 419** (283 contre 282). McNemar apparié :

```
McNemar : discordantes=87 (baseline_only=44, candidate_only=43) p=1.0
n_paired=451 | both_correct=239 | both_incorrect=125
```

`p = 1,0`. Lu seul, ce tableau dit : **la fuite ne vaut rien**.

⚠️ Il dit faux — et le nombre qui le trahit est **87 discordantes**. Les deux
modèles (le même réseau, rappelons-le) répondent différemment sur **87 frames
sur 451**. Ce n'est pas « la même chose » : c'est **deux erreurs de sens
opposé** qui s'annulent.

### 7.b Par protocole : deux résultats opposés, et l'un est massif

Rappel du §2bis : **`eval_real_norm/` est le protocole d'avril**. Avril est donc
le sous-ensemble que la fuite a **vu** ; juin est celui qu'elle n'a **jamais
vu**.

| Protocole | frames couvertes | **A** | **B** | **A − B** | McNemar `b` / `c` | **p** |
|---|---:|---:|---:|---:|---:|---:|
| **avril `20260429`** — *les photos qui ont fuité* | 102 | **0,9706** | 0,8235 | **+0,1471** | **15 / 0** | **6,1 × 10⁻⁵** |
| **juin `20260601`** — *jamais vues* | 317 | 0,5804 | **0,6246** | **−0,0442** | 29 / 43 | 0,125 |
| corpus entier | 419 | 0,6754 | 0,6730 | +0,0024 | 44 / 43 | 1,0 |

*(`b` = frames où seul A a raison ; `c` = seul B. `n_paired` vaut 114 / 337 /
451 : les 32 frames non couvrables tombent en `both_incorrect` et ne peuvent pas
être discordantes.)*

**Sur les photos qu'elle a vues, la fuite gagne 15 frames sur 102 et n'en perd
aucune.** `c = 0` : il n'existe pas une seule frame d'avril où B bat A. C'est
unidirectionnel, et `p = 6,1 × 10⁻⁵` ne laisse aucune place au hasard.

**Sur les photos qu'elle n'a pas vues, la fuite en coûte 14** (43 contre 29).
`p = 0,125` : la direction est nette, la significativité ne l'est pas à ce `n`.
On ne peut donc pas affirmer que la fuite **dégrade** — seulement qu'elle
n'aide pas, et que le signe penche vers la dégradation.

Vérification arithmétique : 99 + 184 = **283** (A) et 84 + 198 = **282** (B) —
les deux protocoles recomposent bien le total.

### 7.c Par condition, protocole par protocole

⚠️ **Jamais mélangés.** Les deux protocoles n'ont pas le même vocabulaire :
seuls `bright_plain` et `bright_textured` portent le même nom des deux côtés, et
ils désignent des séances différentes. Un tableau unique sur les 451 frames
additionnerait 17 frames d'avril et 64 de juin sous une même étiquette.

**Avril — la fuite gagne partout, et sature :**

| condition | `n` | A | B | A − B | frames |
|---|---:|---:|---:|---:|---:|
| `close_plain` | 17 | **1,0000** | 0,8235 | +0,1765 | +3 |
| `daylight_plain` | 17 | **1,0000** | 0,8824 | +0,1176 | +2 |
| `bright_plain` | 17 | **1,0000** | 0,8824 | +0,1176 | +2 |
| `bright_textured` | 17 | **1,0000** | 0,9412 | +0,0588 | +1 |
| `dim_plain` | 17 | 0,9412 | 0,7059 | **+0,2353** | +4 |
| `tilt_plain` | 17 | 0,8824 | 0,7059 | +0,1765 | +3 |

**A est à 100 % sur quatre conditions sur six.** Ce n'est pas de la
reconnaissance, c'est de la **restitution** : le prototype de chaque classe est
la moyenne de ces six photos-là, dont celle qu'on lui présente. Le gain est le
plus fort là où la tâche est la plus dure (`dim_plain`, +4 frames) — la fuite
compense exactement ce que la difficulté enlève.

**Juin — la fuite perd sur 3 conditions sur 5 :**

| condition | `n` | A | B | A − B | frames |
|---|---:|---:|---:|---:|---:|
| `bright_plain` | 64 | 0,5625 | **0,7031** | **−0,1406** | **−9** |
| `oblique` | 64 | 0,2969 | **0,3906** | −0,0937 | −6 |
| `dim` | 64 | 0,7500 | **0,7969** | −0,0469 | −3 |
| `glare_specular` | 64 | 0,6406 | 0,6250 | +0,0156 | +1 |
| `bright_textured` | 61 | 0,6557 | 0,6066 | +0,0491 | +3 |

La perte se concentre sur `bright_plain` (−9 frames) et `oblique` (−6). ⚠️
`oblique` est **la condition la plus dure des deux runs** (0,30 et 0,39) : c'est
là que le corpus de juin fait le plus mal, et là que la fuite n'aide pas.

### 7.d Le `label_space` — identique des deux côtés

| | A | B |
|---|---|---|
| classes du candidat | **24** | **24** |
| classes en vérité terrain | 20 | 20 |
| **classes couvertes** | **17** | **17** |
| frames couvertes / totales | 419 / 451 | 419 / 451 |
| `errors.n` | **0** | **0** |
| `abstention.coverage` | 1,0 | 1,0 |
| taille du modèle | 4,25 Mo | 4,25 Mo |

Le garde `assert_same_label_space` n'a donc pas eu à refuser — et c'est bien
ce qu'on voulait vérifier : le repli `arcface_W` du run A (§1 de
`LOT4-PREPARATION.md`) donne bien 24 centroïdes, pas 17.

Les 3 classes non couvrables sont les mêmes des deux côtés :
`fr-2007-2eur-standard-2nd-map`,
`fr-2018-…-bleuet-de-france`, `mt-2008-2eur-standard-2nd-map`.

`abstention.coverage = 1,0` : aucune des deux itérations n'a produit de
`thresholds.json`, donc le matcher **répond toujours**. Aucune abstention n'a pu
masquer une erreur.

---

## 8. Ce que ça veut dire

**1. La fuite de centroïdes est réelle, mesurée, et significative — mais elle
n'améliore que ce qu'elle a vu.** +14,7 points et `c = 0` sur avril, à
`p = 6,1 × 10⁻⁵`. Un modèle noté sur le corpus qui a servi à fabriquer ses
prototypes affiche une performance qu'il n'a pas.

**2. Le `r@1` global d'un run fuité n'est pas « optimiste de x points » — il est
incohérent.** Il vaut +14,7 sur une partie du juge et −4,4 sur l'autre. Aucun
correctif scalaire ne le répare. C'est exactement le mot de
[`PROBLEME.md`](./PROBLEME.md) §1bis : **« non interprétable »**, et ce lot le
démontre au lieu de l'affirmer.

**3. Q6 de `PROBLEME.md` reçoit une réponse partielle.** *« Combien vaut le biais
actuel ? »* → **au moins 14,7 points sur la fraction du juge qui a fuité**, à 8
epochs, pour la seule fuite de centroïdes. Le run du 2026-08-16 (`92,4 %`) était
noté sur `eval_real_norm/` = avril **entier**, avec cette fuite active : son
chiffre est du même côté que le `0,9706` de A. ⚠️ Ce n'est **pas** une
correction à appliquer au `92,4 %` — les deux runs ne partagent ni le nombre
d'epochs, ni le bake, ni peut-être la machine (§3).

**4. Le protocole de juin doit devenir le juge principal.** Il n'a jamais fuité,
il est trois fois plus gros (317 frames couvertes contre 102), et il contient
les conditions qui discriminent (`oblique` à 0,30–0,39). Avril, lui, est
**grillé pour l'évaluation d'ArcFace** tant que `eval_real_norm/` reste la
source des splits : tout run à `val_source=device` le mémorise.

**5. Le remède est déjà en place et il fonctionne.** `val_source=none` +
`centroid_source=train_mean` produit un modèle dont les centroïdes reposent sur
6594 images d'entraînement et **aucune** image du juge. Ça se vérifie après coup
sur l'artefact (`n_samples`), sans avoir à croire le journal.

---

## 9. Réserves — ce que ce lot n'établit PAS

| Question | Pourquoi elle reste ouverte |
|---|---|
| **L'amplitude à convergence** | 8 epochs, 3 dégelés. Les deux runs sont sous-entraînés. Le signe est établi, la taille de l'écart à 40 epochs ne l'est pas |
| **La fuite de sélection de checkpoint** | **Inerte dans ce run** (§6) : le meilleur epoch selon le juge s'est trouvé être le dernier. Son coût propre n'est **pas** mesuré, et il redeviendra actif dès que la courbe de val cessera d'être monotone |
| **La dégradation sur juin est-elle réelle ?** | `p = 0,125`. La direction est nette (43 contre 29), la significativité non. Il faudrait plus de frames — ou plus d'epochs |
| **La comparaison avec le `92,4 %` du 2026-08-16** | Impossible : epochs, bake et machine diffèrent. Et ⚠️ si le PC avait ses textures d'overlay (§3), son bake n'est pas celui-ci |
| **Le coût du bake sur le PC** | Non mesuré. Les extrapolations du lot précédent tiennent toujours |
| **Ce que valent ces modèles** | Rien : ce sont des preuves de mécanisme. Ni l'un ni l'autre ne doit être promu |

---

## 10. Chronologie et coût réel

| Étape | Début → fin | Durée |
|---|---|---|
| bake A | 15:22:09 → 15:26:03 | **3 min 54 s** |
| **entraînement A** (+ embeddings, TFLite, benchmark) | 15:26:15 → 16:02:56 | **36 min 41 s** |
| bake B | 16:03:27 → 16:07:19 | **3 min 52 s** |
| **entraînement B** (idem) | 16:08:08 → 16:44:33 | **36 min 25 s** |
| **total des quatre étapes** | | **1 h 20 min 52 s** |

*(horodatages de la table `jobs` ; l'horloge murale correspondante va de 17:22 à
18:44.)*

**E = 8 était le bon choix.** Le budget de 90 minutes est tenu avec ~9 minutes
de marge, bakes inclus — là où E = 9 l'aurait dépassé. La prédiction du lot
précédent (71 min 12 s d'entraînement seul, ~19 min pour le reste) était juste :
73 min 06 s d'entraînement mesurés, 7 min 46 s de bakes.

Le scoring, lui, est négligeable : ~30 s par scorecard en `--path full`,
**0 erreur de normalisation** sur les 451 frames dans les six runs de notation.

---

## 11. Ce qui a été touché

Aucun commit, aucun push, rien sur le VPS, rien sur MinIO.

| Fichier | Statut |
|---|---|
| `ml/serving/lab_routes.py` | 7 lignes (transport de `augmentations_seed`) — non committé |
| `ml/tests/test_lab_iteration_seed.py` | neuf, 3 tests — non committé |
| `ml/state/eurio.work-juge-banc.db` | nouvelle, 228 Mo. `eurio.work.db` **intacte** |
| `ml/lab/iterations/{027254937193,11b7a626c57a,8bbe7ac6c2ac}/` | artefacts (gitignorés) |
| `ml/datasets/iterations/…`, `ml/datasets/*/augmentations/…` | bakes (gitignorés) |

Ni `ml/training/*` ni `ml/scripts/replay_corpus.py` n'ont été modifiés.

⚠️ **L'API `:8042` tourne encore en mode compute** (`EURIO_DB_PATH=…work-juge-banc.db`,
`EURIO_DB_READONLY=` vide), PID relancé à 18:08. Pour revenir au mode normal :
`lsof -ti :8042 | xargs kill` puis `go-task ml:api-prod` dans un shell direnv.

### À reprendre au lot 7

1. `go-task ml:augment-textures-check` — corriger le chemin d'import dans
   `ml/tasks.yml:802` **et** `Taskfile.yml:203`, puis générer les textures.
2. `describe_auto_source` — le message dit « absent » quand la valeur a été
   passée explicitement.
3. Committer le transport de `augmentations_seed` et son test.
