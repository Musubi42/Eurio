# Protocole de prise de vue — corpus de scan (P5)

> À lire **téléphone en main**. Le plan est dans
> [`plan-capture-scan.csv`](./plan-capture-scan.csv) — une ligne = une cellule
> `classe × condition`, déjà ordonnée en 11 sessions.
>
> Prérequis : [`PREREQUIS.md`](./PREREQUIS.md) §P5 · Schéma du corpus :
> [`../scan-quality/corpus-spec.md`](../scan-quality/corpus-spec.md)
>
> **Tu ne referas pas ces photos.** Le corpus est le seul juge de ce qui part
> dans l'APK, et il est append-only : une session bâclée reste dans la mesure.
>
> 🔴 **À FAIRE AVANT LA PREMIÈRE SESSION — protéger ce qui existe déjà.** Ce Mac
> porte **2 264 images device** (114 dans `ml/datasets/eval_real_norm`, 2 150
> frames caméra dans `debug_pull`) qui ne sont **sur aucun MinIO** et **dans
> aucune sauvegarde** : deux dossiers gitignorés sur un disque de portable, sans
> réplique. Le futur `ml/state/scan_corpus/frames/` aura exactement le même
> statut. Produire 985 captures de plus avant d'avoir branché la réplication,
> c'est parier le travail sur un `git clean -xdf`. Le problème est chiffré et
> le remède décrit dans
> [`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md).
>
> ⚠️ **Et ces 2 150 frames sont peut-être une partie de la réponse.** Ce sont de
> vraies frames de caméra en conditions réelles ; il leur manque une annotation,
> pas une prise de vue. ⚠️ *estimation* : leur diversité de classes et de
> conditions n'a **pas** été mesurée — les dépouiller avant de photographier
> pourrait réduire le plan ci-dessous, ou ne rien y changer.

---

## 0. Ce que dit le plan, en une ligne

**80 classes possédées · 5 conditions · 400 cellules · 985 captures · 11 sessions
de ~100 captures** (30-40 min chacune). Régénérable à l'identique :

```bash
go-task ml:scan-corpus:prescribe
```

Le script lit la réplique **en lecture seule** (`ml/state/eurio.replica.db`,
ouverte en `mode=ro`) et n'écrit rien en base.

---

## 1. Avant la première session — brancher le plan dans l'app

L'app de capture (`cohortTest`) **ne lit pas ce CSV**. Elle lit un
`live_tests_manifest.json` produit à partir d'une **cohorte en base**. Le CSV
est le plan humain ; la cohorte est son jumeau machine. Les deux sortent de la
même commande (`plan-capture-scan.cohorte.csv`, format
`eurio_id;numista_id;display_name`).

1. **Créer la cohorte de prescription.** C'est une **écriture** → elle part au
   canonique, jamais en SQLite direct (cf. skill `eurio-data-writes`). Via le
   front (`/lab/cohorts`, bouton « créer une cohorte ») ou en HTTP :

   ```bash
   # les 80 eurio_id sont la colonne 1 de plan-capture-scan.cohorte.csv
   curl -sX POST http://127.0.0.1:8042/lab/cohorts \
     -H 'content-type: application/json' \
     -d "$(python3 - <<'PY'
   import json, pathlib
   p = pathlib.Path("docs/work-in-progress/scan-sans-retrain/plan-capture-scan.cohorte.csv")
   ids = [l.split(";")[0] for l in p.read_text().splitlines()
          if l and not l.startswith(("#", "eurio_id"))]
   print(json.dumps({"name": "scan-owned-80", "description":
                     "Prescription corpus de scan P5", "eurio_ids": ids}))
   PY
   )"
   ```

   Note l'`id` retourné (12 hex) — c'est le `PRESCRIBE_COHORT`.

2. **Builder le bundle et l'APK.** ⚠️ **`NO_SAMPLE=1` est obligatoire** :
   au-delà de 30 pièces, `build_cohort_bundle` échantillonne **silencieusement à
   3 pièces** (`SAMPLE_COIN_THRESHOLD`, `ml/scripts/build_cohort_bundle.py:65`).
   Sans ce flag tu photographierais 3 classes sur 80 sans aucun message.

   ```bash
   go-task -t app-android/Taskfile.yml cohort-test:install \
     COHORT=<cohorte-du-modèle> ITERATION=<iid> \
     PRESCRIBE_COHORT=<id-scan-owned-80> NO_SAMPLE=1
   ```

   Le modèle embarqué n'a **aucune** importance pour le corpus : les frames sont
   model-agnostic (`corpus-spec.md` §1). Il ne sert qu'à remplir le tableau de
   bord §I4d pendant la session. N'attends pas un « bon » modèle pour commencer.

3. **Vérifier avant de photographier quoi que ce soit.** Ouvre le bundle staged
   et compte :

   ```bash
   python3 -c "import json;m=json.load(open('app-android/src/cohortTest/assets/cohort_bundle/live_tests_manifest.json'));\
   print(m['sampled'], len(m['tests']), len({t['expected_eurio_id'] for t in m['tests']}))"
   # attendu : False 400 80
   ```

   `sampled=True` ou moins de 80 classes ⇒ **stop**, le `NO_SAMPLE` n'est pas
   passé.

---

## 2. Les 5 conditions — définition opératoire

Mêmes libellés que l'app (`HeroCoinCard.kt:170`), mêmes gestes que
`BenchProtocol.kt`. Une condition mal définie = une mesure ininterprétable.

| Condition | Libellé app | Ce que tu fais, précisément |
|---|---|---|
| `bright` | ☀️ Lumière vive | Plein jour ou près d'une fenêtre. Pièce à plat, caméra perpendiculaire, pas d'ombre portée du téléphone sur la pièce. |
| `dim` | 🌙 Faible lumière | Soir, une seule lampe **à plus de 2 m**. Pas de flash. Si l'app hésite à déclencher, c'est normal : c'est la condition. |
| `tilt` | 📐 Inclinée | **La pièce** est inclinée ~20-30° (calée sur un objet), pas le téléphone. La caméra reste à plat au-dessus. |
| `glare` | ✨ Reflets | Lampe **directe au-dessus**, reflet spéculaire franc visible sur le champ de la pièce. Le reflet doit être dans le cadre, pas évité. |
| `inhand` | ✋ En main | Pièce tenue entre pouce et index, l'autre main tient le téléphone. Doigts visibles. Fond = ce qu'il y a derrière ta main, pas la table. |

**`worn`/`dirty` sont hors prescription** (`corpus-spec.md` §Q2) : les pièces sont
propres et ne se salissent pas à la demande. Ne les improvise pas.

---

## 3. Le geste, session par session

Une session = un bloc de lignes de même `session` dans le CSV. Elles sont
**ordonnées** : suis la colonne `ordre`, ne saute pas.

1. **Une session = une ambiance, une seule.** Ne fais pas deux sessions dans la
   même heure. L'intérêt du découpage est que la lumière du jour, la table, ton
   geste changent entre deux sessions.
2. **Une classe apparaît dans exactement 2 sessions** (colonne `passe`). C'est
   voulu : chaque pièce est vue sous deux ambiances distinctes. Ne regroupe pas
   ses 5 conditions en une fois pour « gagner du temps » — tu détruirais
   précisément ce que le découpage achète.
3. **Les 2 à 3 lignes consécutives d'une même classe se font pièce en main**,
   sans la ranger. Change le fond entre elles (colonne `fond`).
4. **Repose la pièce entre chaque capture**, même dans la même cellule : nouvelle
   orientation, nouvelle position dans le cadre. Deux captures identiques ne
   valent qu'une.
5. **`n_captures` par cellule** : 2 pour les strates riche/moyenne, 3 pour
   canonique/hors_banque. Fais-en le nombre exact, pas « au moins ».
6. **Ne refais pas une capture ratée en la supprimant** — refais-en une de plus.
   Le corpus est append-only et une capture floue est une donnée, pas un déchet
   (elle mesure ta robustesse réelle).

### Après chaque session — sinon rien n'existe

```bash
go-task -t app-android/Taskfile.yml cohort-test:pull-tests ITERATION=<iid>
go-task ml:scan-corpus:import ITERATION=<iid>
```

Puis vérifie que le compte a bougé — **la panne est muette ici** :

```bash
sqlite3 ml/state/scan_corpus.db \
  "SELECT condition, COUNT(*), COUNT(DISTINCT eurio_id) FROM scan_corpus GROUP BY 1;"
```

Si le total n'a pas augmenté d'à peu près `n_captures` de la session, l'archivage
frames n'a pas tourné : `snapArchiveDir` est nul dans le build
(`CoinAnalyzer.archiveSnap`, opt-in). Corrige **avant** la session suivante.

---

## 4. Les pièges — ce qui rend un corpus inexploitable

| Piège | Pourquoi ça tue la mesure | Ce que le plan fait déjà |
|---|---|---|
| **Même fond pour toute une classe** | Le fond devient un indice de la classe. Un encodeur qui « reconnaît » le bois n'a rien appris de la pièce. | Colonne `fond` : 4 fonds tournés, **chaque classe voit les 4**, et chaque fond voit les 4 strates. |
| **Tout d'affilée** | Une seule lumière, une seule table, un seul état de main. Le corpus mesure ta cuisine, pas le scan. | 11 sessions, 2 passes par classe dans **2 sessions différentes**. |
| **Une session = une strate** | Le jour où tu shootes les pauvres est aussi le jour où la lumière était mauvaise → la strate et l'ambiance sont confondues, le chiffre ne veut plus rien dire. | Chaque session contient les 4 strates au prorata (~15 canonique / 11 riche / 10 moyenne / 3 hors_banque). |
| **Ne shooter que les classes riches** | Exactement le biais qui rend les 317 snaps `eval_real_norm` inutilisables (~17 classes, celles où le modèle est déjà bon). | La strate `canonique` pèse **45,7 % des captures** pour 37,5 % des classes. |
| **Cadrage identique partout** | Le modèle apprend ta distance de travail. | Varie la distance (pièce entre ~60 % et ~90 % du cercle de visée) et la position dans le cadre à chaque capture. |
| **Toujours le même côté** | On mesure l'avers uniquement (le matcher est obverse-only). | **Toujours l'avers national** (la face pays), jamais la face commune. Une capture de face commune est une erreur de label. |
| **Refaire une session « ratée »** | Append-only : la première existe toujours. | Ne supprime rien ; ajoute. |

---

## 5. Pourquoi cette répartition — l'argument

Répartition retenue (mesurée sur la réplique, cf. §7) :

| Strate | Classes | Captures/cellule | Captures | Part |
|---|---:|---:|---:|---:|
| `riche` (≥ 9 `fps` en banque) | 22 | 2 | 220 | 22,3 % |
| `moyenne` (1-8 `fps`) | 21 | 2 | 210 | 21,3 % |
| **`canonique` (0 `fps`)** | **30** | **3** | **450** | **45,7 %** |
| `hors_banque` (couverte via son `design_group`) | 7 | 3 | 105 | 10,7 % |

**La strate `canonique` est sur-représentée exprès, et c'est le point le plus
important du plan.**

1. **Elle est le régime réel du produit.** 539 classes sur 664 dans la banque
   n'ont que le canonique Numista — **81 % du catalogue**. Un utilisateur qui
   scanne une commémorative au hasard tombe presque toujours dans ce régime.
2. **C'est là que le chiffre est le plus incertain, donc le plus cher à
   mesurer.** H4 mesure vitl14 zero-shot à **62,8 %** top-1 en canonical-only
   contre **72,7 %** en wild-rich. Un taux proche de 50-60 % a la variance
   binomiale maximale : il faut plus d'échantillons pour le même intervalle.
   À 450 captures, l'IC95 de la strate est d'environ **±4,6 pts** ; à 220 il
   serait de ±6,5. La strate `riche`, elle, tourne près du plafond — 220
   captures y suffisent largement pour établir une borne haute.
3. **On ne peut pas élargir, seulement approfondir.** Il n'y a que 30 classes
   pauvres *possédées physiquement*. Le seul levier disponible est le nombre de
   captures par cellule : d'où 3 au lieu de 2.
4. **C'est la strate qu'on est tenté de couper**, parce qu'elle donnera les plus
   mauvais scores et qu'aucun de ces scores ne fera plaisir. Couper la mesure
   qui dérange, c'est exactement ce qui a produit le R@1 de 0,9722 sur 36 images
   qui ne mesure rien.

**La strate `hors_banque` (7 classes) est incluse alors qu'aucune n'est dans la
banque** : chacune a exactement **un frère dans son `design_group`** qui, lui, y
est (vérifié, §7). Elles sont donc scorables en maille eq — la maille de vérité
du replay (`corpus-spec.md` §8). Les exclure aurait coûté 7 pièces qu'on tient
déjà dans la main pour zéro gain.

### Critère de sortie (PREREQUIS §P5)

| Exigence | Plan | Marge |
|---|---|---|
| ≥ 500 captures | 985 | ×1,97 |
| ≥ 50 classes | 80 | ×1,6 |
| ≥ 3 conditions/classe | 5 | ✅ |
| `glare` et `inhand` représentées | 80 cellules chacune | ✅ |
| corpus figé et versionné | `corpus_version()` du store (§5 spec) | ✅ |

Le corpus est **utile bien avant d'être complet** : après 3 sessions (~290
captures, les 4 strates représentées) on peut déjà lancer un premier replay et
détecter un problème de protocole tant qu'il est encore réparable. Ne pas
attendre la session 11 pour regarder.

---

## 6. Variantes du plan

La composition n'est pas gravée. Le générateur est paramétrable :

```bash
# la proposition 15/15/20 de PREREQUIS.md §P5 (600 captures, 50 classes)
go-task ml:scan-corpus:prescribe -- \
  --classes-par-strate riche=15,moyenne=15,canonique=20,hors_banque=0 \
  --out /tmp/plan-50.csv

# creuser encore le régime pauvre
go-task ml:scan-corpus:prescribe -- --captures-canonique 4

# sessions plus courtes (~20 min)
go-task ml:scan-corpus:prescribe -- --cells-per-session 25
```

`--seed` fixe le tirage : même seed ⇒ même plan, à la ligne près.

---

## 7. Les chiffres et leurs requêtes

Réplique `ml/state/eurio.replica.db`, **2026-08-19**.

Stratification (30 / 7 / 21 / 22) :

```sql
WITH owned AS (SELECT eurio_id FROM coins WHERE personal_owned = 1),
per AS (SELECT class_id, SUM(method='fps') n
          FROM dino_class_references WHERE anchors_kind='2eur_all' GROUP BY 1)
SELECT CASE WHEN per.class_id IS NULL THEN 'hors_banque'
            WHEN n = 0 THEN 'canonique_seul'
            WHEN n <= 8 THEN 'moyenne' ELSE 'riche' END AS strate,
       COUNT(*)
  FROM owned LEFT JOIN per ON per.class_id = owned.eurio_id
 GROUP BY 1;
-- canonique_seul|30   hors_banque|7   moyenne|21   riche|22
```

Les 7 `hors_banque` ont chacune un frère de `design_group` dans la banque :

```sql
WITH owned AS (SELECT eurio_id, design_group_id FROM coins WHERE personal_owned=1),
bank AS (SELECT DISTINCT class_id FROM dino_class_references WHERE anchors_kind='2eur_all')
SELECT o.eurio_id,
       (SELECT COUNT(*) FROM coins c JOIN bank b ON b.class_id = c.eurio_id
         WHERE c.design_group_id = o.design_group_id) AS freres_en_banque
  FROM owned o WHERE o.eurio_id NOT IN (SELECT class_id FROM bank);
-- 7 lignes, freres_en_banque = 1 partout
```

La banque est en maille `eurio_id` pure — aucun `class_id` n'est un
`design_group` :

```sql
SELECT COUNT(*) FROM (SELECT DISTINCT class_id FROM dino_class_references
                       WHERE anchors_kind='2eur_all') d
  JOIN design_groups g ON g.id = d.class_id;   -- 0
```

Totaux du plan : rejouer `go-task ml:scan-corpus:prescribe`, le récapitulatif
est imprimé en fin de commande.
