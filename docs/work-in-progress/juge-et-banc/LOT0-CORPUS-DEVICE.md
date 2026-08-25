# Lot 0 — retrouver et sécuriser le corpus device

> Mesuré le **2026-08-25** sur le Mac (`Musubi42s-MacBook-Air-Oim`), branche
> `repo-cleanup`, hors de toute écriture : aucun fichier du dépôt n'a été créé,
> déplacé ni supprimé, aucune base n'a été écrite, rien n'a été poussé sur MinIO.
> Chaque chiffre porte la commande qui le produit. Ce qui est **estimé** et non
> mesuré porte un ⚠️.
>
> 🟢 **Le fait en une ligne** : le corpus complet **est sur le Mac** — 337 photos
> device dans `debug_pull/20260601_154135/eval_real/`, elles se renormalisent
> à 337/337. Ce qui manque n'est pas la matière, c'est **le geste de sync** :
> `ml/datasets/eval_real_norm/` porte encore les 114 photos d'un pull d'avril,
> selon un protocole de prise de vue différent.

---

## 0. Correctifs à la formulation de la mission

Trois prémisses de l'énoncé sont fausses, et il faut le dire avant les réponses.

| Prémisse | Ce qui est mesuré |
|---|---|
| « `benchmark_runs.id = '0e2fbeeb0495'`, lisible dans `ml/state/eurio.replica.db` » | **Cet identifiant n'existe dans aucune base de cette machine**, ni ailleurs dans le dépôt. La réplique ne contient **qu'un** `benchmark_run`, et ce n'est pas celui-là |
| « le benchmark de référence du 2026-08-16 » | Le run 317/16 a tourné **sur le PC**, dans `ml/state/eurio.work-pc-exercice2.db` — une base qui n'existe que là-bas. Les deux `benchmark_runs` du 2026-08-16 présents ici font 36/6 et 18/3 |
| « `top_confusions_json` contient des `photo_path` — c'est le moyen le plus direct de savoir ce qui manque » | `top_confusions_json` ne contient **que les N (défaut 20) prédictions FAUSSES de plus faible marge**. À R@1 = 0,924 sur 317 photos il y a ~24 erreurs, dont 20 journalisées. **Cette colonne ne peut structurellement pas rendre la liste des 317 photos**, même en ayant la ligne |

```bash
for db in ml/state/eurio.replica.db ml/state/eurio.db ml/state/eurio.work.db \
          ml/state/eurio.work-dino.db ml/state/eurio.work-enrich.db \
          ml/state/eurio.work-enrich2.db ml/state/eurio.work-exercice1.db \
          ml/state/eurio.local.db ml/state/training.db; do
  n=$(sqlite3 -readonly "$db" "SELECT count(*) FROM benchmark_runs;" 2>/dev/null)
  echo "$db -> ${n:-NO TABLE}"; done
# replica 1 · eurio.db NO TABLE · work.db 2 · work-dino 1 · work-enrich 1
# work-enrich2 1 · work-exercice1 2 · local 0 · training 7
```

```bash
sqlite3 -readonly ml/state/eurio.work.db \
  "SELECT id, substr(started_at,1,19), num_photos, num_coins, round(r_at_1,4)
     FROM benchmark_runs ORDER BY started_at DESC;"
# 4034f601e645|2026-08-16T02:15:49|36|6|0.9722
# a0d6b607b2fe|2026-06-02T16:26:14|12|2|0.9167
sqlite3 -readonly ml/state/eurio.work-exercice1.db "SELECT id,num_photos,num_coins FROM benchmark_runs;"
# a2b799d71b1c|18|3   ·   a0d6b607b2fe|12|2
```

```bash
grep -rn "0e2fbeeb0495" . 2>/dev/null | grep -v '\.git/'   # (aucune sortie)
```

Le code qui produit la colonne, pour lever le doute
(`ml/training/eval/evaluate_real_photos.py:693-712`) :

```python
# Top-N confusions: lowest spread AND incorrect at top-1.
incorrects = [r for r in results if not r.hit_at.get(1)]
...
for r in incorrects[:top_n]
```

`top_n` vient de `--top-confusions`, borné à `[1, 100]`, défaut **20**
(`ml/serving/benchmark_routes.py:65`, `:325`).

**Ce qui, lui, porte la liste complète** : `per_coin_json` (comptes par classe)
et surtout `report_path` — le JSON écrit sur disque par
`evaluate_real_photos.py:514` contient `per_coin` et `confusion_matrix`. Sur la
machine qui a joué le run. Donc sur le PC.

---

## 1. Où vit la version complète ?

**Sur ce Mac, dans `debug_pull/20260601_154135/eval_real/` : 337 photos brutes,
17 dossiers de classe.** C'est la matière première ; ce n'est pas le dossier
`eval_real_norm/` que le pipeline lit.

```bash
find debug_pull/20260601_154135/eval_real -name '*_raw.jpg' | wc -l   # 337
find debug_pull/20260601_154135/eval_real -mindepth 1 -maxdepth 1 -type d | wc -l   # 17
du -sh debug_pull/20260601_154135                                      # 21M
```

Ces 337 se renormalisent **sans une seule perte** (sortie écrite dans le
scratchpad, jamais dans le dépôt) :

```bash
cd ml && ./.venv/bin/python -m vision.sync_eval_real ../debug_pull/20260601_154135 \
  --output /private/tmp/.../scratchpad/eval_real_norm_20260601
# Manifest: …/class_manifest.json (414 eurio_id mappings)
# 16 dossiers à 20/20 + at-2005-…-state-treaty à 17/17
# Total: 337/337
```

### Les cinq arbres `eval_real/` de la machine

```bash
for t in debug_pull/eval_real/20260529_162919/eval_real \
         debug_pull/20260601_154135/eval_real \
         debug_pull/20260529_150808/eurio_debug/eval_real \
         debug_pull/20260429_170852/eurio_debug/eval_real \
         app-android/debug_pull/20260429_214408/eurio_debug/eval_real; do
  echo "$t  dirs=$(find $t -mindepth 1 -maxdepth 1 -type d|wc -l) raw=$(find $t -name '*_raw.jpg'|wc -l)"
done
```

| Arbre | dossiers | `*_raw.jpg` |
|---|---:|---:|
| `debug_pull/20260429_170852/eurio_debug/eval_real` | 19 | **114** |
| `app-android/debug_pull/20260429_214408/eurio_debug/eval_real` | 19 | 114 *(doublon octet-pour-octet du précédent)* |
| `debug_pull/20260529_150808/eurio_debug/eval_real` | 22 | 144 |
| `debug_pull/eval_real/20260529_162919/eval_real` | 22 | 151 |
| **`debug_pull/20260601_154135/eval_real`** | **17** | **🟢 337** |

### D'où vient le 337 → 317

337 = 16 classes × 20 + `at-2005-…-state-treaty` × 17.
**317 = 15 × 20 + 17**, et le run annonce **16 pièces** contre 17 dossiers.
L'arithmétique se ferme exactement si **une seule classe à 20 photos a été
écartée** du run.

⚠️ **Estimation, pas mesure** : *quelle* classe, et *pourquoi* (probablement
absente des centroïdes du modèle de l'exercice #2, entraîné sur la cohorte
`ab28928bcdc2` « owned-ready-24 »), ne peut pas être établi d'ici. Il faut la
ligne `benchmark_runs` ou le `report_path` du PC. L'hypothèse concurrente —
des échecs de normalisation — est **écartée par la mesure** : 337/337 passent.

Le « 337 » recoupe indépendamment `docs/model-efficiency/C0-benchmark-ground-truth.md:48`
(« **337 vraies photos device**, ~17 classes 2€ », 2026-06-11), onze jours après
le pull du 2026-06-01. Les deux chiffres décrivent le même jeu.

### Pourquoi le Mac n'affiche que 114 : ce ne sont pas les mêmes photos

Les deux jeux suivent **deux protocoles de prise de vue différents**, et sont
donc disjoints — le 114 n'est pas un sous-ensemble du 337.

```bash
ls ml/datasets/eval_real_norm/fr-2018-2eur-simone-veil
# bright_plain · bright_textured · close_plain · daylight_plain · dim_plain · tilt_plain   (6)
ls debug_pull/20260601_154135/eval_real/fr-2018-2eur-simone-veil | grep _raw
# 5 conditions × 4 positions : bright_plain, bright_textured, dim, glare_specular, oblique
#                              × {base, _p1, _p2, _p3}                                   (20)
```

`eval_real_norm/` porte donc **le pull du 2026-04-29** (6 conditions), jamais
resynchronisé depuis le pull du 2026-06-01. Le geste manquant tient en une
commande — que **je n'ai pas jouée** (voir §5) :

```bash
go-task ml:eval-real:sync -- debug_pull/20260601_154135    # additif, n'efface rien
```

⚠️ **Attention avant de la jouer** : elle *ajoute* 17 dossiers à côté des 19
existants, et le juge deviendrait un mélange de deux protocoles. Le choix
(remplacer / cumuler / nommer deux corpus séparés) est une décision du chantier,
pas une manipulation de fichiers. La variante destructive est bien isolée dans
une tâche distincte (`ml:eval-real:sync:clear`) — l'avertissement de
`remap_bench_golden_set.py:41` (« la tâche embarque `--clear` en dur ») est
**périmé**, `ml/tasks.yml:47-55` le corrige.

### Ce qui n'est PAS sur le Mac, et ne peut pas l'être

- la ligne `benchmark_runs` du run 317/16 → `ml/state/eurio.work-pc-exercice2.db`, **sur le PC** ;
- son `report_path` (le JSON avec `per_coin` et la matrice de confusion) → **sur le PC** ;
- les artefacts de l'itération `03f767f998ef` (19 Mo) → **sur le PC**
  (`docs/archive/handoffs-2026/HANDOFF-2026-08-16.md:196-200` : « le modèle ne
  voyage pas », « au canonique, les deux `*_run_id` sont NULL »).

**Conclusion sur la question 1 : les *photos* sont ici ; le *run* est sur le PC.**
Les deux moitiés de la contradiction sont donc réelles, mais elles ne portent
pas sur le même objet.

---

## 2. La liste exacte des photos du run — **non établissable**

Ni d'ici, ni depuis la colonne indiquée, ni même depuis le PC via
`top_confusions_json` (§0). Ce qu'on peut affirmer :

- le run a noté **317 photos sur 16 classes**, prises dans un
  `ml/datasets/eval_real_norm/` du PC ;
- le format des chemins est connu — mesuré sur un run local :

```bash
sqlite3 -readonly ml/state/eurio.work.db \
  "SELECT substr(top_confusions_json,1,200) FROM benchmark_runs WHERE id='4034f601e645';"
# [{"photo_path": "datasets/eval_real_norm/at-2002-2eur-standard-1st-map/dim_plain.jpg", …
```

- ⚠️ **estimation** : ce `eval_real_norm/` du PC a très probablement été produit
  par `sync_eval_real` depuis le même pull du 2026-06-01 (le nombre 337 et les
  17 classes concordent), moins une classe. Non vérifiable sans accès au PC.

**Le seul chemin pour l'obtenir** : sur le PC,
`sqlite3 -readonly ml/state/eurio.work-pc-exercice2.db "SELECT per_coin_json, report_path FROM benchmark_runs WHERE num_photos=317;"`,
puis lire le JSON pointé. À demander au PO, ou à faire au prochain passage sur
la machine `desktop`.

---

## 3. Combien d'images device sur cette machine, et lesquelles sont labellisées

### Inventaire brut

```bash
for t in debug_pull app-android/debug_pull ml/datasets/eval_real_norm; do
  echo "$t files=$(find $t -type f|wc -l) img=$(find $t -type f \( -name '*.jpg' -o -name '*.png' \)|wc -l) $(du -sh $t|cut -f1)"; done
find ml/datasets -path '*/captures/*' -type f | wc -l
```

| Arbre | fichiers | images | taille |
|---|---:|---:|---:|
| `debug_pull/` | 2 968 | 2 150 | 80 Mo |
| `app-android/debug_pull/` | 879 | 699 | 26 Mo |
| `ml/datasets/eval_real_norm/` | 114 | 114 | 2,5 Mo |
| `ml/datasets/<nid>/captures/` (19 dossiers) | 114 | 114 | 2,5 Mo |
| `ml/bench/sessions/` | 1 | **0** | 16 Ko |
| `ml/state/live_test_logs/` | 3 | **0** | 28 Ko |
| `ml/state/scan_corpus.db` | — | **0 octet** | — |

`ml/bench/sessions/` et `ml/state/live_test_logs/` ne contiennent **aucune
image** : uniquement du JSONL d'événements et de prédictions. Ce ne sont pas des
pistes pour retrouver des photos.

### Dédoublonnage par contenu — le chiffre qui compte

```bash
find debug_pull app-android/debug_pull ml/datasets/eval_real_norm -type f \
     \( -name '*.jpg' -o -name '*.png' \) > /tmp/imgs.txt
find ml/datasets -path '*/captures/*' -type f >> /tmp/imgs.txt
wc -l < /tmp/imgs.txt                                   # 3077
xargs -a /tmp/imgs.txt shasum -a 256 > /tmp/imgs.sha
awk '{print $1}' /tmp/imgs.sha | sort -u | wc -l         # 1734
xargs -a /tmp/imgs.txt stat -c%s | awk '{s+=$1} END{printf "%.1f Mo\n", s/1048576}'   # 100.3 Mo
sort -u -k1,1 /tmp/imgs.sha | sed 's/^[0-9a-f]*  //' | tr '\n' '\0' \
  | xargs -0 stat -c%s | awk '{s+=$1} END{printf "%.1f Mo\n", s/1048576}'             # 59.7 Mo
```

**3 077 fichiers image, 100,3 Mo → 1 734 uniques, 59,7 Mo.** 40 % de redondance.

Deux redondances identifiées et mesurées :

```bash
# app-android/debug_pull est un doublon intégral de debug_pull
awk '{h=$1;p=$0;sub(/^[0-9a-f]*  /,"",p);print h"\t"p}' /tmp/imgs.sha > /tmp/hp.tsv
grep -P '\tapp-android/debug_pull' /tmp/hp.tsv | cut -f1 | sort -u > /tmp/a.sha   # 677
grep -P '\tdebug_pull'             /tmp/hp.tsv | cut -f1 | sort -u > /tmp/b.sha   # 1620
comm -12 /tmp/a.sha /tmp/b.sha | wc -l                                            # 677 → inclusion totale
# ml/datasets/<nid>/captures/ est un doublon intégral de eval_real_norm/
# captures uniq 114 · eval_real_norm uniq 114 · communs 114
```

### Répartition des 1 734 uniques par nature

```bash
sort -u -k1,1 /tmp/hp.tsv | cut -f2 | sed 's|.*/||' \
  | sed -E 's/^.*_(raw|crop)\.jpg$/[\1]/; t; s/[0-9]{4,}/N/g' | sort | uniq -c | sort -rn
```

| Nature | uniques |
|---|---:|
| **originaux caméra** (`*_raw.jpg` 492 · `raw.jpg` 66 · `frame_N.jpg` 143) | **701** |
| crops dérivés (`*_crop.jpg`, `crop.jpg`) | 672 |
| frames annotées de debug (`frame_N_annotated.jpg`) | 133 |
| diffs de portage Kotlin/Python (`*_diff.jpg`) | 114 |
| normalisés 224 px (`eval_real_norm/` + `captures/`) | 114 |

**Seuls les 701 originaux sont irremplaçables** : tout le reste s'en dérive.

### Labellisées vs non labellisées

```bash
awk -F'\t' '{h=$1;p=$2;n=p;sub(/.*\//,"",n);
 if (!(n ~ /_raw\.jpg$/ || n=="raw.jpg" || n ~ /^frame_[0-9]+\.jpg$/)) next;
 lab[h] = lab[h] ((p ~ /eval_real/) ? "L" : "U")}
 END{for (h in lab) if (lab[h] ~ /L/) nl++; else nu++;
     print "labellisées:",nl,"  non labellisées:",nu}' /tmp/hp.tsv
# labellisées: 492   non labellisées: 215
```

| | uniques | statut |
|---|---:|---|
| **rangées par classe** (sous un arbre `eval_real/`) | **492** | vérité terrain par dossier ; conditions dans le nom de fichier |
| **non labellisées** (sessions de scan / debug) | **215** | les `capture_*.txt` portent la *prédiction*, pas la vérité (cf. `DURABILITE-CORPUS.md` §1) |

⚠️ **Correction au chiffre de `DURABILITE-CORPUS.md` §1** (« 2 150 frames dans
`debug_pull` », « 2 264 images device »). Ce comptage additionne originaux,
crops dérivés, frames annotées et diffs, sur deux arbres dont l'un duplique
l'autre. Le **matériau device réel est de 701 frames uniques**, dont 492
labellisées. Le gisement non annoté n'est pas de 2 150 frames mais de **215**.
Le paragraphe « les 2 150 frames de `debug_pull` sont le gisement intéressant »
est donc à réviser — l'arbitrage « annoter ou archiver brut » porte sur dix fois
moins de matière que ce qui était supposé.

### Couverture en classes

```bash
find debug_pull app-android/debug_pull -path '*eval_real*' -name '*_raw.jpg' \
  | awk -F/ '{print $(NF-1)}' | sort -u | wc -l          # 31 noms de dossier
```

31 noms de dossier → **23 `eurio_id` cibles** après application de la table de
`remap_bench_golden_set.MAPPING`. ⚠️ **Estimation : ~19 classes réelles** —
4 des 23 sont des slugs morts **absents de la table de remap**
(`ad-2014-2eur-standard`, `de-2007-2eur-schwerin-castle-mecklenburg-vorpommern`,
`de-2020-2eur-50-years-since-the-kniefall-von-warschau`, `fr-2007-2eur-standard`)
et sont selon toute vraisemblance les jumeaux orthographiques de leur cible
moderne. **Non vérifié à l'œil** — c'est exactement ce que la table de remap
exige (« jamais par ressemblance de chaînes »), et je ne l'ai donc pas tranché.

---

## 4. Le nommage : 7 dossiers sur 19, pas 6

```bash
sqlite3 -readonly ml/state/eurio.replica.db \
  "SELECT eurio_id, coalesce(design_group_id, eurio_id) FROM coins;" > /tmp/map.txt
for d in $(ls ml/datasets/eval_real_norm); do
  m=$(grep -m1 "^$d|" /tmp/map.txt | cut -d'|' -f2)
  [ "$m" != "$d" ] && echo "$d  →  $m"; done
```

| Dossier (`eurio_id`) | `class_id` réel |
|---|---|
| `ad-2014-2eur-standard-1st-type` | `ad-2euro-standard-t1` |
| `at-2002-2eur-standard-1st-map` | `at-2euro-standard-t1` |
| `be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait` | `be-2euro-albert-ii-t1` |
| `be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait` | `be-2euro-albert-ii-t2` |
| `es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map` | `es-2euro-juan-carlos-i-t1` |
| `fr-1999-2eur-standard-1st-map` | `fr-2euro-standard-t1` |
| `mt-2008-2eur-standard-2nd-map` | `mt-2euro-standard-t1` |

**7 sur 19, pas 6.** `PROBLEME.md:199` dit « six dossiers » puis « 7 classes
fantômes » deux lignes plus bas — c'est **7** aux deux endroits.
Les 12 autres dossiers sont des commémoratives, où `class_id == eurio_id` : les
19 dossiers donnent bien 19 `class_id` distincts, aucune fusion silencieuse.

Le même comptage sur le pull complet du 2026-06-01 : **les 17 dossiers sont
nommés par `eurio_id`**, aucun n'est un `class_id`.

### Est-ce que `remap_bench_golden_set.py` traite ce cas ? **Non.**

Ce script fait autre chose : il remappe des **slugs d'APK périmés vers des
`eurio_id` vivants**. Sa table `MAPPING` (`ml/scripts/remap_bench_golden_set.py:112-165`)
a pour cibles précisément 6 des 7 dossiers ci-dessus — il les *produit*, il ne
les corrige pas. Son champ `design_group` n'est qu'une **motivation journalisée**,
jamais un nom de dossier écrit.

```bash
cd ml && ./.venv/bin/python -m scripts.remap_bench_golden_set --scope fs
# 14 lignes toutes en [done] « cible déjà en place »
# résumé : {'done': 14} → rien écrit (dry-run ; --apply pour appliquer)
```

Le remap est donc **déjà appliqué intégralement** (30 dossiers / 180 photos à
l'origine → 19 / 114 aujourd'hui). Aucune correction `eurio_id → class_id`
n'existe nulle part.

### 🔴 Un défaut de code trouvé au passage (mesuré, non corrigé)

`ml/vision/sync_eval_real.py` a **deux** chemins d'exécution qui ne font pas la
même chose :

| Point d'entrée | Applique `class_manifest.json` ? |
|---|---|
| `main()` — CLI / `go-task ml:eval-real:sync` (`:224`) | ✅ `class_id = eurio_to_class.get(eurio_id, eurio_id)` |
| `sync()` — appelée par `POST /lab/cohorts/{id}/captures/sync` (`:139`, `:147`) | ❌ `out_dir = output / eurio_id` — **le manifeste n'est jamais lu** |

`sync()` charge pourtant `also_write_captures` et son `coin_lookup`, mais
**aucune résolution `class_id`**. Le docstring du module promet l'inverse
(« The output folder is keyed by **class_id** »). Panne muette de la famille du
catalogue `eurio-verify` : le dossier se crée, rien ne lève, et le nom est faux.

Et même par le CLI, le résultat serait identique aujourd'hui — le manifeste ne
couvre pas ces classes :

```bash
cd ml && ./.venv/bin/python -c "
import json,os
m={e:c['class_id'] for c in json.load(open('datasets/eurio-poc/class_manifest.json'))['classes'] for e in c.get('eurio_ids',[])}
print(len(m),'mappings'); print(sum(1 for d in os.listdir('datasets/eval_real_norm') if d not in m),'/19 absents du manifest')"
# 414 mappings · 13/19 absents du manifest
```

**Deux causes indépendantes, donc, pour le même symptôme.** Conformément à la
consigne, rien n'a été renommé ni corrigé.

---

## 5. La réplication

### C'est encore vrai : rien n'est répliqué

```
mcp__minio-eurio__list_buckets
# enrichment-crops · enrichment-raws · eurio-db · model-artifacts · numista-canonical
```

Aucun bucket de corpus. Contenu vérifié préfixe par préfixe :

| Bucket | Racine | Verdict |
|---|---|---|
| `eurio-db` | `eurio.db`, `.sha256`, `.lock`, `transfers/` (2 `.pth`/`.tar.gz` ArcFace) | aucune image device |
| `model-artifacts` | `models/`, `training/` → `coin_detector_weights/…/best.pt`, `detection_dataset/…/.tar.gz` | aucune image device |
| `enrichment-raws` | `ebay/`, `mock/` | crops eBay uniquement |

**Zéro des 701 originaux device n'est sur MinIO.** L'avertissement de
`DURABILITE-CORPUS.md` §2 est intact au 2026-08-25, et l'unique copie est le
disque de ce portable.

Et — point que la doc ne dit pas — **poser un bucket ne suffira pas** :

```bash
grep -n "MIRROR_BUCKETS" infra/backup/eurio-backup.sh
# 74: MIRROR_BUCKETS=(${EURIO_BACKUP_BUCKETS-enrichment-crops enrichment-raws \
#                     numista-canonical model-artifacts eurio-db})
```

La liste des buckets sauvegardés est **une constante en dur**. Un bucket neuf
serait invisible de la chaîne de sauvegarde, et le corpus « dans MinIO » ne
serait **pas** sauvegardé. C'est un piège muet de plus.

### Le plan proposé — **rien n'a été poussé**

Ne pas inventer de mécanisme : `ml/scripts/training_assets.py` fait déjà
exactement ça (ADR-004) — arbre de fichiers → archive déterministe → bucket,
identité par `tree_digest` sur le contenu seul, manifeste committé dans git.
Le corpus device est un arbre comme un autre.

**Étape 1 — étendre `ASSETS` dans `ml/scripts/training_assets.py:56` :**

```python
ASSETS: list[tuple[str, str, str]] = [
    ("detection_dataset",      "tree", "ml/datasets/detection"),
    ("coin_detector_weights",  "file", "ml/output/detection/coin_detector/weights/best.pt"),
    ("device_pulls",           "tree", "debug_pull"),                    # ← nouveau
    ("device_eval_real_norm",  "tree", "ml/datasets/eval_real_norm"),    # ← nouveau
]
```

`app-android/debug_pull/` est **exclu délibérément** : doublon octet-pour-octet
mesuré (677/677), 26 Mo pour zéro information.

**Étape 2 — publier (à jouer par le PO, pas par un agent) :**

```bash
go-task ml:training-assets:publish -- --dry-run   # d'abord : lire ce qui partirait
go-task ml:training-assets:publish                # puis, seulement après lecture
```

**Étape 3 — la mesure qui prouve que ça a marché** (la skill `eurio-verify` :
les pannes sont muettes ici) :

```bash
go-task ml:training-assets:status     # doit sortir 0, pas 2
git diff --stat shared/training-assets.json   # 2 entrées de plus, n_files/content_size cohérents
# et depuis une autre machine, l'aller-retour réel :
go-task ml:training-assets:fetch && find debug_pull -name '*_raw.jpg' | wc -l   # 701 originaux attendus
```

**Étape 4 — sans laquelle les étapes 1-3 ne protègent rien :** brancher la
sauvegarde. `model-artifacts` **est déjà** dans `MIRROR_BUCKETS`, donc publier
dans ce bucket hérite de la chaîne sans toucher à `eurio-backup.sh`. C'est
l'argument décisif pour réutiliser `training_assets` plutôt que de créer un
bucket `device-corpus` : **un bucket neuf demanderait d'éditer la constante en
dur, et l'oubli serait silencieux.**

⚠️ **À vérifier avant de publier** : `infra/backup/verify_invariants.py` teste
« objets MinIO non décroissants » par bucket (`test_verify.sh:361`). Un ajout de
+77 Mo dans `model-artifacts` doit passer ce garde ; je ne l'ai pas exercé — il
ne tourne que sur le VPS.

### Coût en volume — mesuré

```bash
tar -cf - debug_pull | gzip -c | wc -c              # 74 943 676
tar -cf - ml/datasets/eval_real_norm | gzip -c | wc -c   #  2 302 226
```

| | |
|---|---:|
| `debug_pull/` → `.tar.gz` | **74,9 Mo** |
| `eval_real_norm/` → `.tar.gz` | **2,3 Mo** |
| **total sur MinIO** | **77,2 Mo** |
| ce que ça ajoute au staging de sauvegarde (6,6 Go) | **+1,2 %** |
| ce que ça ajoute à un `git clone` | **0** (manifeste JSON de ~40 lignes) |

⚠️ Les JPEG ne se compressent pas : 100,3 Mo bruts → 77,2 Mo n'est **pas** de la
compression, c'est l'exclusion d'`app-android/debug_pull` (26 Mo de doublons).
Dédoublonner à l'intérieur de `debug_pull/` (1 620 uniques sur 2 150) gagnerait
~15 Mo de plus, au prix d'une réorganisation des dossiers : **non recommandé**,
le gain ne vaut pas la perte de la structure par session de capture.

---

## 6. Ce que je n'ai pas pu établir

| Question | Pourquoi |
|---|---|
| **Quelle classe manque au run 317/16** | Il faut la ligne `benchmark_runs` du PC ou son `report_path`. L'arithmétique dit « une classe à 20 photos », pas laquelle |
| **La liste des 317 `photo_path`** | N'existe dans aucune colonne — `top_confusions_json` ne journalise que ≤ 20 erreurs (§0). Seul le JSON de `report_path`, sur le PC, porte `per_coin` |
| **Que le `eval_real_norm/` du PC vient bien du pull 2026-06-01** | ⚠️ estimation par concordance (337 / 17 classes / date). Aucune preuve |
| **Les 4 slugs morts sans entrée de remap** | Se tranchent **en regardant les photos**, jamais par ressemblance de chaînes — c'est la méthode explicite de `remap_bench_golden_set.py`. Décision humaine |
| **Que `verify_invariants.py` accepte +77 Mo** | Ne tourne que sur le VPS |
| **La diversité de conditions des 215 frames non labellisées** | Question ouverte de `DURABILITE-CORPUS.md` §5, non mesurée ici |

## 7. Ce qui a été touché

Rien dans le dépôt, hors ce fichier.

```bash
git status --porcelain
#  M secrets/dev.env          ← préexistant à la session
#  ?? docs/work-in-progress/juge-et-banc/LOT0-CORPUS-DEVICE.md
```

Les 337 photos renormalisées à titre de vérification sont dans le scratchpad de
session, hors du dépôt. Aucune écriture dans `ml/state/*.db`, aucun objet créé,
modifié ou supprimé sur MinIO, aucun commit, aucun push.
