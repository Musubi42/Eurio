# Lot 3 — le juge devient exécutable, et on apprend à le lire

> Fait le **2026-08-25** sur le Mac (`Musubi42s-MacBook-Air-Oim`), branche
> `repo-cleanup`. Chaque chiffre porte sa commande. Aucun commit, aucun push,
> aucune écriture dans `eurio*.db` ni dans `scan_corpus.db`.
>
> 🟢 **Le fait en une ligne** : `--iteration <iid>` existe, le juge a tourné pour
> de vrai sur 337 frames en `--path full` (20 s, `exit=0`, **0 erreur de
> normalisation**), et le filtre `--bundle-source` est prouvé exact
> (114 + 337 = 451, intersection vide).
>
> 🔴 **Le fait qui compte** : le `r@1 = 0,1751` de la scorecard **n'est pas un
> mauvais score, c'est un score sans dénominateur**. L'itération ne porte que
> **3 centroïdes** ; **14 des 17 classes du corpus de juin n'ont aucune classe
> cible dans le modèle** et sont fausses par construction. Sur les **60 frames
> qu'elle pouvait répondre, elle en réussit 59**.
>
> ✅ **Ratifié par le PO et implémenté dans le même lot** (§9) : la scorecard
> porte maintenant `label_space`, rend `r_at_1_on_covered` avec son `n` à côté
> du global, et **refuse** de comparer deux candidats d'espaces différents. Le
> contrat est écrit dans `corpus-spec.md` §8ter.

---

## 1. La commande exacte

```bash
cd ml && ./.venv/bin/python -m scripts.replay_corpus \
  --iteration caf98145032c --path full \
  --bundle-source device_pull_20260601 --out /tmp/replay_smoke
; echo "exit=$?"
# Corpus : 337 frames (version 157923328d6e) — chemin full
# Candidat : caf98145032c (best_model.pth)
# exit=0
# 60,62s user 6,52s system 336% cpu 19,975 total
```

Codes de sortie relevés **sans pipe** (`; echo "exit=$?"`), comme l'exige
`eurio-verify` : `exit=0` pour les trois runs de §4.

Le candidat noté :

| | |
|---|---|
| itération | `caf98145032c` — cohorte `0b4cb60ce342`, `status=completed`, `created_at 2026-08-16 19:11:56` |
| modèle | `lab/iterations/caf98145032c/checkpoints/best_model.pth`, 4,23 Mo, `sha256[:16] = cff1ac5b5cee5c85` |
| centroïdes | `lab/iterations/caf98145032c/embeddings/embeddings_v1.json` — `model = v35-arcface`, `embedding_dim = 256`, **3 pièces** |

```bash
sqlite3 -readonly "file:state/eurio.replica.db?immutable=1" \
  "SELECT id, cohort_id, status, created_at FROM experiment_iterations WHERE id='caf98145032c';"
# caf98145032c|0b4cb60ce342|completed|2026-08-16 19:11:56
```

⚠️ La table s'appelle **`experiment_iterations`**, pas `iterations` (`.tables`
le confirme) — un `SELECT … FROM iterations` répond `no such table`.

---

## 2. La scorecard, point par point

```json
{
  "candidate": "caf98145032c",
  "corpus_version": "157923328d6e",
  "n_frames": 337,
  "filter": {
    "cohort_id": null, "conditions": null,
    "source_iteration_id": null,
    "bundle_sources": ["device_pull_20260601"]
  },
  "label_space": {
    "n_candidate_classes": 3, "n_ground_truth_classes": 17,
    "n_covered_classes": 3,   "n_uncoverable_classes": 14,
    "uncoverable_classes": ["ad-2014-2eur-standard-1st-type", "… (14 en tout)"],
    "n_frames_covered": 60, "n_frames_uncoverable": 277, "frame_coverage": 0.178
  },
  "primary": {
    "r_at_1_eq": 0.1751, "r_at_5_eq": 0.178, "r_at_1_strict": 0.1751,
    "r_at_1_on_covered": 0.9833, "n_on_covered": 60
  },
  "by_condition": {
    "bright_plain":    { "n": 68, "r_at_1_eq": 0.1765, "n_covered": 12, "r_at_1_on_covered": 1.0 },
    "bright_textured": { "n": 65, "r_at_1_eq": 0.1846, "n_covered": 12, "r_at_1_on_covered": 1.0 },
    "dim":             { "n": 68, "r_at_1_eq": 0.1765, "n_covered": 12, "r_at_1_on_covered": 1.0 },
    "glare_specular":  { "n": 68, "r_at_1_eq": 0.1765, "n_covered": 12, "r_at_1_on_covered": 1.0 },
    "oblique":         { "n": 68, "r_at_1_eq": 0.1618, "n_covered": 12, "r_at_1_on_covered": 0.9167 }
  },
  "errors":     { "n": 0, "rate": 0.0, "by_kind": {} },
  "abstention": { "coverage": 1.0, "precision_at_coverage": 0.1751 },
  "size":       { "model_mb": 4.23 }
}
```

Et la sortie console ne laisse plus lire le global tout seul :

```
Espace de labels : 3 classes au candidat, 17 en vérité terrain, 3 couvertes.
⚠️  277/337 frames sont FAUSSES PAR CONSTRUCTION (14 classes hors du candidat)
    : lis r_at_1_on_covered, pas r_at_1_eq.
```

| Point demandé | Verdict |
|---|---|
| `n` (frames notées) | **337** — égal au compte en base pour ce filtre (§4) |
| `corpus_version` **non vide** | **`157923328d6e`** — ✅ et c'est **exactement** la version épinglée par LOT1 §5 pour `device_pull_20260601`. Le juge et le manifeste committé désignent le même jeu |
| `filter_desc.bundle_source` | ✅ **inscrit dans la sortie** : `filter.bundle_sources = ["device_pull_20260601"]`. Le filtre n'est pas seulement passé, il est journalisé |
| `errors` | **0 sur 337, `by_kind` vide.** Aucun `normalize_failed`, aucun `load_failed` : les 337 raws de juin repassent tous par `normalize_device_path`. Le raw n'est pas en cause |
| `r@1` | **NON INTERPRÉTÉ** — voir §3. Ce modèle a été entraîné avec la fuite (`PROBLEME.md` §1bis) et ne porte que 3 pièces. La scorecard le **dit** maintenant : `label_space` 3/17/3 et `r_at_1_on_covered = 0,9833` sur `n = 60` |

⚠️ **`errors` n'existait pas dans la scorecard avant ce lot.** La seule trace
d'un échec était une baisse de `abstention.coverage` — indiscernable d'un
candidat prudent qui se tait. Un run où **tout** le raw échouerait à se
normaliser aurait sorti `r@1 = 0.0` et `coverage = 0.0`, deux nombres plausibles,
sans qu'aucune clé ne dise « le modèle n'a jamais vu ces images ». C'est le motif
exact du catalogue `eurio-verify` (*une valeur par défaut plausible là où il
fallait une erreur*). Le bloc est ajouté, et deux tests le tiennent.

---

## 3. 🔴 Combien de classes sont réellement notées : **3 sur 17**

C'est le chiffre qui manque à la scorecard, et sans lui le `r@1` ne veut rien
dire.

```bash
cd ml && ./.venv/bin/python - <<'PY'
import json, collections, sys; sys.path.insert(0,'.')
cids = list(json.load(open('lab/iterations/caf98145032c/embeddings/embeddings_v1.json'))['coins'])
rows = [json.loads(l) for l in open('/tmp/replay_smoke/predictions.jsonl')]
from training.eval.equivalence import build_equivalence_map
eq = build_equivalence_map(); mesh = {eq.coalesce(c) for c in cids}
gt = collections.Counter(r['eurio_id'] for r in rows)
cov = {k for k in gt if eq.coalesce(k) in mesh}
print(len(gt), len(cov), sum(gt[k] for k in cov), sum(r['correct_eq_top1'] for r in rows))
PY
# 17 3 60 59
```

| | |
|---|---:|
| classes de vérité terrain dans le corpus filtré | **17** |
| classes que le modèle **peut** prédire (centroïdes) | **3** |
| classes couvertes, en maille `design_group` | **3** |
| frames dont la vraie classe a un centroïde | **60 / 337** |
| frames correctes | **59** |

Par classe couverte (frames, correctes) : `es-…-segovia` (20, 20) ·
`fr-…-mitterrand` (20, **19**) · `it-…-plautus` (20, 20).

**277 frames sur 337 sont fausses par construction** : leur bonne réponse
n'existe pas dans le modèle. Elles se répartissent quand même sur les 3
centroïdes (`fr-…-mitterrand` 140, `it-…-plautus` 136, `es-…-segovia` 61
prédictions top-1 au total) — le matcher **répond toujours**, il n'y a pas de
`thresholds.json` dans cette itération.

⚠️ **Ne jamais présenter `0,1751` sans ce dénominateur.** Le `0,9833` sur les 60
frames couvrables ne vaut pas mieux : ce modèle a été entraîné avec la fuite de
centroïdes du §1bis de `PROBLEME.md`. **Les deux chiffres sont des preuves de
câblage, pas des mesures de performance.**

---

## 4. Le filtre filtre — la preuve, jouée

Trois runs, même candidat, même `--path full` :

```bash
cd ml
./.venv/bin/python -m scripts.replay_corpus --iteration caf98145032c --path full \
  --bundle-source device_pull_20260429 --out /tmp/replay_avril ; echo "exit=$?"   # exit=0
./.venv/bin/python -m scripts.replay_corpus --iteration caf98145032c --path full \
  --out /tmp/replay_all ; echo "exit=$?"                                          # exit=0
```

| filtre | `n_frames` | `corpus_version` | erreurs | `r@1_eq` (⚠️ 3/17 classes) |
|---|---:|---|---:|---:|
| `device_pull_20260429` | **114** | `9a88383653bc` | 0 | 0,1579 |
| `device_pull_20260601` | **337** | `157923328d6e` | 0 | 0,1751 |
| *(aucun)* | **451** | `494c71b726bf` | 0 | 0,1707 |

- **114 + 337 = 451** ✅
- intersection des `capture_id` des deux sous-ensembles : **0** ✅
- union des deux == l'ensemble sans filtre : **True** ✅
- corrects : 18 + 59 = **77**, et 0,1707 × 451 = **77** ✅
- les trois `corpus_version` sont **exactement** les trois hashs épinglés par
  LOT1 §5 (`9a88383653bc`, `157923328d6e`, `494c71b726bf`) ✅

C'est une partition, pas un chevauchement — et le hash le certifie sans avoir à
faire confiance au compte.

---

## 5. Ce qui a surpris

### 5.a 🔴 La scorecard ne dit pas combien de classes le modèle peut atteindre

C'est le vrai enseignement du lot. `n_frames` fait croire à un dénominateur
honnête ; il compte des frames dont la réponse n'est **pas dans le modèle**.
Deux candidats entraînés sur des cohortes différentes, notés sur le même
corpus, produisent des `r@1` **incomparables** sans que rien ne l'indique — et
c'est précisément le geste que le chantier « juge et banc » s'apprête à faire
(DINO vs ArcFace, `MATRICE.md`).

✅ **Ratifié par le PO le 2026-08-25 et implémenté dans ce même lot** — le
détail est en §9. Le contrat est écrit dans `corpus-spec.md` §8ter.

### 5.b Collision de noms : `--iteration` existait déjà, et voulait dire l'inverse

`--iteration` était le **filtre du corpus** sur
`scan_corpus.source_iteration_id` (la provenance des frames). Lui faire désigner
le **modèle noté** aurait été un renversement de sens muet — un jour quelqu'un
aurait écrit `--iteration caf98145032c` en croyant filtrer et aurait noté un
modèle sur le corpus entier.

Renommé en **`--source-iteration-id`** (même `dest`, même comportement) ;
`--iteration` désigne maintenant le candidat. Les deux sont mutuellement
exclusifs avec `--candidate` via un `mutually_exclusive_group(required=True)`.
**Aucun appelant n'utilisait l'ancien nom** (`grep -rn "replay_corpus"` : seuls
`tasks.yml` en passe-plat `CLI_ARGS`, les tests et de la doc), et la colonne
`source_iteration_id` est **NULL sur les 451 captures** (LOT1 §1) — le filtre ne
servait à rien aujourd'hui. Un test tient la frontière entre les deux drapeaux.

### 5.c Le symlink mort de `53caddf5ab54` ne casse **pas** ce qu'on croyait

```bash
find ml/lab/iterations/53caddf5ab54 -maxdepth 3 -type l -exec ls -la {} \;
# dataset/train -> /Users/…/bizz/Eurio/ml/datasets/iterations/53caddf5ab54   (mort)
```

Il est dans **`dataset/`**, pas dans `checkpoints/` ni `embeddings/` — les deux
que `--iteration` lit. Cette itération serait donc notable. Mais l'incident
donne l'argument décisif contre l'assouplissement de `load_candidate` :

`load_candidate` cherche en `rglob` et prend le **premier trié**. Sur un arbre
d'itération, `dataset/` passe **avant** `embeddings/` dans l'ordre alphabétique.
Un `embeddings_v1.json` qui traînerait dans `dataset/` serait choisi à la place
du bon — silencieusement. C'est vérifié par un test qui affirme les **deux**
comportements côte à côte (`test_ignore_ce_qui_traine_ailleurs_dans_l_iteration`).
Les chemins explicites ne sont pas un confort : ils suppriment une classe de
panne muette.

### 5.d L'équivalence `design_group` n'a rien changé sur ce run

`r_at_1_eq == r_at_1_strict == 0,1751`, aux trois filtres. Raison mesurée : les
3 pièces du modèle sont **standalone**.

```bash
sqlite3 -readonly "file:state/eurio.replica.db?immutable=1" \
 "SELECT eurio_id, design_group_id FROM coins WHERE eurio_id IN
  ('es-2016-2eur-old-town-of-segovia-and-its-aqueduct',
   'fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand',
   'it-2016-2eur-2200th-anniversary-of-the-death-of-plautus');"
# les 3 lignes ont design_group_id vide
```

La map a bien été construite (**689 `eurio_id`** lus depuis la réplique), elle
est simplement sans effet ici. **Sur un candidat à 68 classes elle en aura**, et
ce run ne prouve donc rien sur ce chemin.

### 5.e La mtime de la réplique — et pourquoi la lire seule tromperait

```bash
ls -la --time-style=full-iso ml/state/eurio.replica.db*
# eurio.replica.db      241M  2026-08-25 01:31:40.862 +0200
# eurio.replica.db-shm   98k  2026-08-25 15:09:00.607 +0200
# eurio.replica.db-wal   45M  2026-08-25 15:42:10.776 +0200
```

La `.db` porte **01:31:40**, mais son `-wal` fait **45 Mo** et bouge à la
seconde courante : des écritures postérieures sont dans le WAL, pas dans le
fichier principal (catalogue `eurio-verify`, ligne « la base n'a pas bougé »).
**Les deux mtimes sont dans ce rapport ; la première seule aurait menti.**

`EURIO_DB_PATH` pointe bien la réplique dans le shell utilisé :
`/Users/…/Eurio/ml/state/eurio.replica.db`. Le corpus, lui, **ne joint jamais le
canonique** (§4 de `corpus-spec`) : la réplique ne sert qu'à l'équivalence.

---

## 6. Ce que j'ai livré

| Fichier | Changement |
|---|---|
| `ml/scripts/replay_corpus.py` | `--iteration <iid>` + `--iteration-model {checkpoint,tflite}` + `--lab-root` ; `candidate_from_iteration()` ; ancien `--iteration` → `--source-iteration-id` ; blocs **`errors`** et **`label_space`**, `r_at_1_on_covered` ; `is_coverable()`, `centroid_class_ids()`, `assert_same_label_space()` ; docstring |
| `ml/tests/test_replay_corpus_iteration.py` | **neuf**, 25 tests |
| `docs/work-in-progress/scan-quality/corpus-spec.md` | **§8ter neuf** (espace de labels + `errors`) ; schéma §8 mis à jour ; §8bis renvoie au refus ; §7 corrigé sur `--path full` |
| `ml/tasks.yml` | desc de `scan-corpus:replay` (dit `--iteration`, `--path full`, `--bundle-source`) ; `scan-corpus:test` élargie au nouveau fichier |
| `docs/work-in-progress/juge-et-banc/LOT3-JUGE.md` | ce fichier |

Défaut du modèle noté : **`best_model.pth`**, pas le `.tflite` — contrairement à
`load_candidate` qui préfère `*.tflite`. Le choix est **nommé** (`--iteration-model`)
parce que l'axe quantisation de `MATRICE.md` fera un jour de cet écart une
mesure, pas un détail.

### Suite de tests

```bash
cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly ; echo "exit=$?"
# 2316 passed, 40 warnings in 94.48s
# exit=0
```

Baseline de la mission : **2291 passed, 0 failed**. Mesuré après §9 : **2316
passed, 0 failed** — les 25 de plus sont les miens. Aucune régression.

### Les mutations (un test qui ne peut pas échouer ne prouve rien)

| Mutation | Attendu | Observé |
|---|---|---|
| `candidate_from_iteration` se replie sur `rglob` | rougir | **2 failed** (`…_ignore_ce_qui_traine…`, `…_centroides_absents…`) |
| `source_iteration_id=args.iteration` (la collision, jouée) | rougir | **3 failed** (les 3 tests CLI) |
| `errored` compte les abstentions au lieu des erreurs | rougir | **1 failed** (`…_distingue_echec_et_abstention`) |
| revert (`command cp -f`) | revert | **15 passed** à chaque fois |

Et le **vrai point d'entrée a tourné** trois fois sur la vraie base, avec le vrai
`EURIO_DB_PATH` — les tests gardent le prédicat, seule l'exécution garde le
câblage.

---

## 7. Ce que je n'ai PAS pu établir

| Question | Pourquoi |
|---|---|
| **Ce que vaut ce modèle** | 3 classes sur 17, et entraîné avec la fuite de centroïdes. Le `r@1` de ce lot est une preuve de câblage. **Q6 de `PROBLEME.md` reste ouverte** : elle demande un modèle entraîné *après* les correctifs L2 |
| **Ce que vaut `--path fast` en écart** | Non mesuré : je n'ai fait tourner que `full`. La comparaison `fast` ↔ `full` chiffrerait le coût des 4 normaliseurs, mais elle n'a d'intérêt qu'avec un candidat qui couvre le corpus |
| **Si `53caddf5ab54` note vraiment** | Le symlink mort n'est pas sur le chemin lu, donc *a priori* oui — **non joué**, la mission écartait cette itération |
| **Le comportement avec `thresholds.json`** | Aucune des 3 itérations locales n'en porte : la lecture est testée en unitaire, jamais sur une vraie itération. `coverage = 1.0` partout est donc *attendu*, pas *vérifié* |
| **Le poids du biais par condition** | Mesuré : **12 frames couvrables par condition**, exactement, et **12/12 correctes partout sauf `oblique` à 11/12** — l'unique erreur du run. L'écart de `by_condition` (0,1618 pour `oblique` contre 0,1846) est donc **une seule frame**, diluée par 56 frames non couvrables. **Ne rien conclure sur la robustesse à l'inclinaison** |

## 8. Ce qui attend encore le PO

Plus rien sur l'espace de labels : ratifié et livré (§9). Reste ouvert, hors de
ce lot : **Q6 de `PROBLEME.md`** (combien vaut le biais actuel) — elle demande
un entraînement postérieur aux correctifs L2, qu'aucune itération locale
n'offre.

---

## 9. Addendum du 2026-08-25 — l'espace de labels entre au contrat

> Défaut de §5.a **ratifié par le PO**, implémenté dans ce lot, **avant L4**.
> Il touche L4 directement : la cohorte `ab28928bcdc2` (24 classes) et le juge
> (20 classes sur les deux protocoles) ne se recouvrent que partiellement — les
> deux runs jumeaux afficheraient eux aussi un chiffre dilué. L'écart A−B
> resterait valide ; **les niveaux absolus tromperaient tout lecteur**.

### 9.a Ce qui est en place

**1. `label_space` dans la scorecard.** Nombre de classes du candidat, de la
vérité terrain, leur intersection, la **liste** des classes non couvrables, et
le compte de frames des deux côtés.

**2. `r_at_1_on_covered` + `n_on_covered`**, dans `primary` **et** dans
`by_condition` (`n_covered`, `r_at_1_on_covered`). Les deux sont rendus
ensemble, toujours — c'est écrit comme obligation dans `corpus-spec.md` §8ter,
parce qu'un contrat qui autorise l'un sans l'autre autorise la faute de lecture.

**3. Le refus de comparer deux espaces différents.** `assert_same_label_space()`
sort en erreur explicite, **avant la première inférence et avant de créer le
dossier de sortie** — refuser après 20 s de replay laisserait sur disque des
`predictions.jsonl` qu'on serait tenté de lire quand même. Le message donne les
deux comptes, les ids en trop de chaque côté (5 max + reste), et le remède.

⚠️ **La comparaison se fait sur la maille `COALESCE(design_group, eurio_id)`**,
pas sur les `class_id` bruts : deux candidats entraînés l'un en `eurio_id` et
l'autre en `design_group` désignent le même jeu. Un garde plus naïf aurait
refusé **la comparaison la plus légitime du chantier**. Un test mesure les deux
comportements côte à côte.

**4. `coverable` sur chaque ligne de `predictions.jsonl`.** Calculée **avant**
toute lecture d'image : une frame illisible d'une classe connue reste couvrable.
Échec de lecture et absence de classe sont deux causes distinctes, et les
confondre était la même faute d'un cran plus bas.

**Définition, en parité stricte avec `compute_hits`** : couvrable ⇔ il existe un
centroïde qui `covers()` la vérité terrain **ou** qui lui est équivalent en
`design_group`. Non couvrable ⇒ `correct_eq_top1` faux **quoi que fasse le
modèle**.

### 9.b Le run témoin, rejoué

```bash
cd ml && ./.venv/bin/python -m scripts.replay_corpus \
  --iteration caf98145032c --path full \
  --bundle-source device_pull_20260601 --out /tmp/replay_final
; echo "exit=$?"   # exit=0
```

| | attendu | obtenu |
|---|---|---|
| `label_space` (candidat / GT / couvertes) | 3 / 17 / 3 | **3 / 17 / 3** ✅ |
| `r_at_1_on_covered` | ≈ 0,983 | **0,9833** ✅ |
| `n_on_covered` | 60 | **60** ✅ |
| `n_frames_uncoverable` | — | **277** (14 classes) |
| `r_at_1_eq` (global, dilué) | inchangé | **0,1751** ✅ |

Tout le reste de la scorecard est **bit-pour-bit identique** au run de §2
(`scorecard == scorecard` en Python, hors les clés neuves) : le changement
ajoute de la lisibilité, il ne déplace aucune mesure.

Le détail par condition confirme §7 : **12 frames couvrables par condition**,
`r_at_1_on_covered = 1.0` partout **sauf `oblique` à 0,9167** — l'unique erreur
du run, une frame sur 12. L'écart de `by_condition` était bien une frame,
diluée par 56 non couvrables.

### 9.c Les mutations — un garde dont rien ne rougit n'est pas un garde

| # | Mutation | Observé |
|---|---|---|
| **M1** | `coverable = True` (couvrabilité neutralisée) | **4 failed** — `…label_space_compte…`, `…r_at_1_on_covered…`, `…frame_non_couvrable…`, `…frame_illisible…` |
| **M2** | `is_coverable` ignore l'équivalence `design_group` | **1 failed** — `…suit_la_regle_de_compute_hits` |
| **M3** | `assert_same_label_space` ne refuse plus rien | **3 failed** — dont le CLI, qui produit alors un McNemar bancal (`discordantes=1 p=1.0`) |
| **M4** | le garde compare les `class_id` bruts, hors maille | **1 failed** — `…meme_maille_design_group_ne_refuse_pas` |
| **M5** | le refus arrive **après** `out_dir.mkdir()` | **1 failed** — `…refuse_avant_toute_inference` |
| **M6** | `r_at_1_on_covered` calculé sur **toutes** les frames | **1 failed** — `…est_rendu_avec_son_n` |
| revert (`command cp -f`) | | **25 passed** à chaque fois |

⚠️ **M5 a d'abord été écrite comme un no-op** (`_ = out_dir` ajouté après coup) :
25 passed, et j'ai failli conclure « le garde d'ordonnancement n'est pas
testé ». La vraie mutation — déplacer le bloc de garde **après** le `mkdir` —
rougit. Une mutation qui ne change pas le comportement ne réfute rien : c'est
le piège de la méthode elle-même.

### 9.d Ce que ça change pour L4 et pour `MATRICE.md`

Les deux voies du départage **n'ont pas le même espace de labels par défaut** :
la banque DINO couvre bien plus de classes qu'une cohorte d'entraînement
ArcFace. Le garde les **refusera** — c'est voulu. Les opposer demande de
recalculer les centroïdes des deux **sur le même ensemble de classes**. Ce n'est
pas un confort : c'est la condition pour que le p-value veuille dire quelque
chose. Écrit dans `corpus-spec.md` §8ter, obligation 3.

### 9.e Ce que je n'ai pas fait

- **Pas de dérogation au refus.** Aucun `--allow-label-space-mismatch` : une
  échappatoire serait empruntée, puis oubliée, et rendrait le garde décoratif.
  Si un besoin légitime apparaît, il se discute — il ne se contourne pas.
- **Pas de `label_space` rétroactif** sur les scorecards déjà écrites dans
  `ml/state/scan_corpus_runs/` : elles restent sans le bloc. Une scorecard sans
  `label_space` est **antérieure au 2026-08-25** et son `r@1` est à relire avec
  cette réserve.
