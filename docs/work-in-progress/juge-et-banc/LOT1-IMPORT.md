# Lot 1 — peupler la maison du juge

> Fait le **2026-08-25** sur le Mac (`Musubi42s-MacBook-Air-Oim`), branche
> `repo-cleanup`. Chaque chiffre porte sa commande. Ce qui est **estimé** et non
> mesuré porte un ⚠️.
>
> 🟢 **Le fait en une ligne** : `ml/state/scan_corpus.db` est passée de **0 octet
> à 451 captures** (114 + 337), les deux protocoles étiquetés séparément, les
> slugs morts remappés, `cohort_id` et `source_iteration_id` **NULL** partout.
> Le manifeste committé `ml/state/validation_gold/device_corpus_manifest.jsonl`
> fige la vérité terrain sans une seule prédiction.
>
> 🔴 **Une décision est en attente du PO** (§6.a) : 4 des 19 slugs d'avril
> n'ont **pas** de ligne dans la table tranchée à l'œil
> `remap_bench_golden_set.MAPPING`. Ils sont importés via une table
> **mesurée** (`EXTRA_MAPPING`) dont la preuve est reproductible (§2), mais qui
> n'a pas été validée à l'œil comme l'exige la méthode du remap.

---

## 1. Ce qui est en base — la vérification demandée, jouée

```bash
sqlite3 -readonly ml/state/scan_corpus.db \
  "SELECT bundle_source, COUNT(*), COUNT(DISTINCT eurio_id) FROM scan_corpus GROUP BY 1;"
# device_pull_20260429|114|19
# device_pull_20260601|337|17
sqlite3 -readonly ml/state/scan_corpus.db "SELECT COUNT(*) FROM scan_corpus;"
# 451
sqlite3 -readonly ml/state/scan_corpus.db \
  "SELECT COUNT(*) FROM scan_corpus WHERE eurio_id='ad-2014-2eur-standard';"
# 0   ← le remap a été appliqué
sqlite3 -readonly ml/state/scan_corpus.db \
  "SELECT COUNT(*) FROM scan_corpus WHERE cohort_id IS NOT NULL OR source_iteration_id IS NOT NULL;"
# 0   ← aucune provenance inventée
sqlite3 -readonly ml/state/scan_corpus.db "SELECT COUNT(DISTINCT eurio_id) FROM scan_corpus;"
# 20  ← union des deux protocoles (19 ∪ 17)
```

**Idempotence** — les deux imports rejoués tels quels :

```bash
cd ml && ./.venv/bin/python -m scripts.import_device_pull \
  --pull ../debug_pull/20260429_170852 --bundle-source device_pull_20260429 --execute
# seen=114 inserted=0 updated=114 duplicate_bytes=0 no_crop=0 unknown_eurio_id=0
./.venv/bin/python -m scripts.import_device_pull \
  --pull ../debug_pull/20260601_154135 --bundle-source device_pull_20260601 --execute
# seen=337 inserted=0 updated=337 …
sqlite3 -readonly ml/state/scan_corpus.db "SELECT COUNT(*) FROM scan_corpus;"   # 451
```

**Suite complète** (`; echo "exit=$?"`, sans pipe) :

```bash
cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly ; echo "exit=$?"
# 2289 passed, 40 warnings in 102.45s
# exit=0
```

⚠️ La baseline annoncée par la mission était **2267**. Le compte mesuré est
**2289** : +8 sont mes tests (`tests/test_import_device_pull.py`), les 14 autres
viennent des agents qui travaillent en parallèle sur `ml/training/*`,
`ml/vision/sync_eval_real.py` et `ml/tests/test_benchmark.py`. **0 failed** :
aucune régression.

### 🔴 Piège de vérification : `sqlite3 -readonly` échoue sur cette base

```bash
sqlite3 -readonly ml/state/scan_corpus.db "SELECT COUNT(*) FROM scan_corpus;"
# Error: in prepare, unable to open database file (14)
```

La base est en **WAL** (posé par le store à chaque connexion). Un `-readonly`
sur une base WAL doit pouvoir créer le fichier `-shm` : quand le dernier
écrivain s'est fermé proprement, `-shm`/`-wal` n'existent plus et l'ouverture
échoue. Les autres bases de `ml/state/` n'ont ce problème **que parce que leurs
`-shm` traînent sur disque** (`ls -la ml/state/*-shm`) — ce n'est pas une
propriété, c'est un résidu.

La forme robuste, en vraie lecture seule :

```bash
sqlite3 -readonly "file:ml/state/scan_corpus.db?immutable=1" "SELECT COUNT(*) FROM scan_corpus;"
# 451
```

C'est celle à écrire dans les procédures. Le symptôme est **muet au sens de la
skill `eurio-verify`** : le code de sortie est 14, pas 0, mais le message ne dit
rien de WAL et invite à conclure « la base est vide / absente » alors qu'elle
contient 451 lignes.

---

## 2. Le remap — 10 lignes tranchées à l'œil, 4 lignes mesurées

`remap_bench_golden_set.MAPPING` couvre **10 des 19 dossiers** du pull d'avril.
Les 4 slugs morts restants (déjà signalés par
[`LOT0-CORPUS-DEVICE.md`](./LOT0-CORPUS-DEVICE.md) §3 comme non tranchés)
n'y sont pas :

| Dossier d'avril (slug mort) | `eurio_id` importé |
|---|---|
| `ad-2014-2eur-standard` | `ad-2014-2eur-standard-1st-type` |
| `de-2007-2eur-schwerin-castle-mecklenburg-vorpommern` | `de-2007-2eur-state-of-mecklenburg-vorpommern` |
| `de-2020-2eur-50-years-since-the-kniefall-von-warschau` | `de-2020-2eur-german-polish-reconciliation` |
| `fr-2007-2eur-standard` | `fr-1999-2eur-standard-1st-map` |

**Ils ne sont pas devinés par ressemblance de chaînes** — c'est précisément ce
que la méthode du remap interdit. Ils sont établis par **mesure**, en trois
temps :

1. `ml/datasets/eval_real_norm/` porte les **19 dossiers déjà remappés**
   (`remap_bench_golden_set --scope fs` sort 14 lignes `[done]`, cf. LOT0 §4) —
   ses noms sont donc la cible validée à l'œil ;
2. la normalisation device est **déterministe** : renormaliser le pull d'avril
   reproduit `eval_real_norm/` **octet pour octet** —

   ```bash
   cd ml && ./.venv/bin/python -m vision.sync_eval_real ../debug_pull/20260429_170852 \
     --output <scratchpad>/norm_avril     # Total: 114/114
   # 108 sha256 communs sur les 108 produits (6 écrasés par une collision
   # class_id du manifeste, cf. §6.b) → jointure exacte
   ```
3. frame par frame, `sha256(normalize_device_path(<avril>/<slug>/<step>_raw.jpg))`
   est cherché dans `eval_real_norm/` : **114/114 appariés, 0 échec de
   normalisation**, et chaque dossier d'avril tombe dans **un seul** dossier
   cible, 6 photos sur 6.

```
ad-2014-2eur-standard          -> {'ad-2014-2eur-standard-1st-type': 6}
de-2007-…-schwerin-castle-…    -> {'de-2007-2eur-state-of-mecklenburg-vorpommern': 6}
de-2020-…-kniefall-von-warschau-> {'de-2020-2eur-german-polish-reconciliation': 6}
fr-2007-2eur-standard          -> {'fr-1999-2eur-standard-1st-map': 6}
… (19 lignes, toutes à 6/6, aucun '??')
normalize failures: 0
```

Les 10 lignes que `MAPPING` couvre **sont retrouvées à l'identique par cette
mesure** : la méthode se valide elle-même là où la table existe. `fr-2007-2eur-standard`
tombe sur `fr-1999-2eur-standard-1st-map`, exactement la cible que `MAPPING`
donne à son jumeau orthographique `fr-2eur-standard-2007` — dont la raison
journalisée cite `close_plain` et `daylight_plain`, deux étapes du protocole
d'avril. Les deux orthographes désignent bien la même capture.

**`MAPPING` reste prioritaire** dans le code : `EXTRA_MAPPING` ne comble que ce
qu'elle ignore, et un recouvrement contradictoire lève (`build_remap()`,
testé par `test_extra_mapping_ne_contredit_pas_la_table_a_l_oeil`).

### Le garde-fou qui rend le remap non facultatif

Tout `eurio_id` résolu est confronté au **référentiel** en lecture seule
(`store.class_resolver`, 689 `eurio_id`). Un slug absent fait **échouer
l'import** (code 2), il ne s'écrit pas :

```bash
cd ml && ./.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from store.class_resolver import coin_refs_from_sqlite
refs={r.eurio_id for r in coin_refs_from_sqlite()}; import os
av=set(os.listdir('../debug_pull/20260429_170852/eurio_debug/eval_real'))-{'manifest.jsonl'}
ju=set(os.listdir('../debug_pull/20260601_154135/eval_real'))-{'manifest.jsonl'}
print('avril bruts vivants:',len(av&refs),'/',len(av))
print('juin  bruts vivants:',len(ju&refs),'/',len(ju))"
# avril bruts vivants: 5 / 19
# juin  bruts vivants: 17 / 17
```

**Sans remap, 14 des 19 dossiers d'avril auraient posé une vérité terrain qui ne
désigne aucune pièce du référentiel.** Le pull de juin, lui, est déjà propre :
0 remap appliqué, mesuré.

---

## 3. Ce que le corpus contient exactement

```bash
sqlite3 -readonly "file:ml/state/scan_corpus.db?immutable=1" \
  "SELECT bundle_source, condition, COUNT(*) FROM scan_corpus GROUP BY 1,2 ORDER BY 1,2;"
```

| `bundle_source` | `condition` | n |
|---|---|---:|
| `device_pull_20260429` | `bright_plain` | 19 |
| `device_pull_20260429` | `bright_textured` | 19 |
| `device_pull_20260429` | `close_plain` | 19 |
| `device_pull_20260429` | `daylight_plain` | 19 |
| `device_pull_20260429` | `dim_plain` | 19 |
| `device_pull_20260429` | `tilt_plain` | 19 |
| `device_pull_20260601` | `bright_plain` | 68 |
| `device_pull_20260601` | `bright_textured` | 65 |
| `device_pull_20260601` | `dim` | 68 |
| `device_pull_20260601` | `glare_specular` | 68 |
| `device_pull_20260601` | `oblique` | 68 |

**La collision de noms d'étape est réelle et mesurable :**

```bash
cd ml && ./.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from store.scan_corpus import ScanCorpusStore; s=ScanCorpusStore()
print(len(s.list_captures(conditions=['bright_plain'])))                                    # 87
print(len(s.list_captures(conditions=['bright_plain'], bundle_sources=['device_pull_20260429'])))  # 19"
```

**87 captures répondent à `bright_plain`** : 19 d'avril + 68 de juin. Un filtre
par condition seule mélange les deux protocoles sans le dire. C'est la raison
d'être de `bundle_source` dans `list_captures()` — et pourquoi il fallait
**refuser** de détourner `source_iteration_id`, colonne documentée « provenance
uniquement, jamais scoré ».

### Choix de modélisation

| Champ | Valeur | Pourquoi |
|---|---|---|
| `capture_id` | `sha256(raw_bytes)[:16]` | dédoublonne par contenu ; **0 collision** mesurée sur les 451 (`shasum … \| uniq -d \| wc -l` → 0) |
| `condition` | le `step_id` **brut** du sidecar | pas de vocabulaire réinventé ; ⚠️ `KNOWN_CONDITIONS` du store n'est validé **nulle part** (vérifié) — ce n'est pas un garde, ne pas s'y fier |
| `bundle_source` | `device_pull_20260429` / `device_pull_20260601` | porte le **protocole**, seul discriminant des deux jeux |
| `cohort_id` | **NULL** | ces pulls précèdent toute cohorte |
| `source_iteration_id` | **NULL** | idem ; le renseigner serait un mensonge de provenance. C'est aussi pourquoi `_ingest_frame()` de `import_scan_corpus` **n'est pas réutilisé** : son contrat impose `str(line["iteration_id"])`, qui écrirait la chaîne `"None"` |
| `quality_json` | `{source_slug, source_file, position, step_index, step_label, protocol_mode, normalize}` | la **position** de juin (`_p1`…`_p3`, 4 positions par étape) et le normaliseur d'origine y survivent sans polluer `condition` |
| `notes` | « slug d'origine `<slug>` ; crop transcodé JPEG→PNG » | le nom mort n'est pas effacé, il est journalisé |
| `device_model` | **NULL** | ⚠️ **aucun des deux pulls ne porte l'info** : ni fichier de session, ni champ de sidecar (`ls debug_pull/2026*/` → uniquement `eurio_debug/` ou `eval_real/`) |
| `captured_at` | ISO 8601 **sans fuseau** | le sidecar donne `20260429_164750_336`, heure **locale du device**. On ne fabrique pas un `Z` qu'on ne sait pas vrai |

Les images sont archivées **telles quelles** : `raw` copié octet pour octet,
crop transcodé JPEG q95 → PNG (perte amont actée, pas masquée). **451/451 crops
présents** (`no_crop=0`), tous **224×224**.

```bash
du -sh ml/state/scan_corpus ml/state/scan_corpus.db
# 53M   ml/state/scan_corpus      (frames, gitignoré : .gitignore:161)
# 448K  ml/state/scan_corpus.db
```

---

## 4. 🔴 Quatre normaliseurs, pas deux — la notation se fait en `--path full`

```bash
sqlite3 -readonly "file:ml/state/scan_corpus.db?immutable=1" \
  "SELECT json_extract(quality_json,'\$.normalize.method'), bundle_source, COUNT(*)
     FROM scan_corpus GROUP BY 1,2;"
# hough_loose  |device_pull_20260601| 57
# hough_relaxed|device_pull_20260429|  1
# hough_strict |device_pull_20260601|280
# hough_tight  |device_pull_20260429|113
```

La mission annonçait deux normaliseurs (avril `hough_tight` vs juin
`hough_strict`). Il y en a **quatre** : chaque protocole a des replis
(`hough_relaxed`, `hough_loose`) déclenchés par la difficulté de la photo, et
`hough_loose` couvre **57 captures de juin sur 337 (17 %)** — pas un cas
marginal.

**Conséquence, non négociable : la notation du corpus device se fait en
`--path full`** (renormalisation depuis le raw, port bit-for-bit de
`SnapNormalizer.kt`), **jamais** `--path fast`. En `fast`, l'écart mesuré entre
deux candidats serait pollué par l'écart entre quatre normaliseurs — et rien ne
le signalerait. C'est écrit dans le docstring de `replay_corpus`, dans la desc
de la tâche, et dans le sidecar du manifeste (`scoring_path: "full"`).

---

## 5. Ce qui a été livré

| Fichier | État |
|---|---|
| `ml/scripts/import_device_pull.py` | **neuf** — lit l'arbre brut, remappe, dédoublonne, `--dry-run` par défaut |
| `ml/store/scan_corpus.py` | `list_captures(bundle_sources=…)` ajouté (`IN (…)`) |
| `ml/scripts/replay_corpus.py` | `--bundle-source` (csv) → filtre **et** `filter_desc` de la scorecard |
| `ml/state/validation_gold/device_corpus_manifest.jsonl` | **neuf, committable** (95 ko, 451 lignes) + sidecar `.meta.json` |
| `ml/tests/test_import_device_pull.py` | **neuf**, 8 tests |
| `ml/tasks.yml` | `scan-corpus:import-pull` ; `scan-corpus:test` élargie |
| `docs/work-in-progress/juge-et-banc/LOT1-IMPORT.md` | ce fichier |

Le manifeste **n'est pas gitignoré** (`git check-ignore -v … ` → exit 1, aucune
règle ne matche), comme ses voisins `encoder_bench_gold.jsonl` et
`verdict_gold.jsonl`. Il porte `(capture_id, eurio_id, condition, bundle_source,
captured_at)` et **rien d'autre** — aucune prédiction, jamais ; c'est vérifié
par `test_manifeste_sans_prediction`.

```json
{
  "corpus_version": "494c71b726bf",
  "n_captures": 451,
  "n_eurio_ids": 20,
  "n_by_bundle_source": {"device_pull_20260429": 114, "device_pull_20260601": 337},
  "n_eurio_ids_by_bundle_source": {"device_pull_20260429": 19, "device_pull_20260601": 17},
  "contains_predictions": false,
  "scoring_path": "full"
}
```

Versions par pull (utiles pour épingler un sous-ensemble) :
`device_pull_20260429` → **`9a88383653bc`** · `device_pull_20260601` →
**`157923328d6e`** · corpus entier → **`494c71b726bf`**.

### La tâche

```bash
go-task ml:scan-corpus:import-pull -- \
  --pull ../debug_pull/20260601_154135 --bundle-source device_pull_20260601 [--execute]
```

⚠️ **Piège du dry-run** : `ScanCorpusStore()` crée sa base au premier appel,
dry-run compris. Un fichier qui passe de 0 à 12 ko **ne prouve rien** ; le seul
critère est le `COUNT(*)`. C'est ce que teste
`test_dry_run_n_ecrit_aucune_ligne`.

### Ce qui n'a **pas** été fait, volontairement

- Aucune écriture dans `ml/state/eurio*.db`. La seule lecture du référentiel est
  le garde-fou `eurio_id`, et elle est **facultative** (repli explicite « garde-fou
  NON exercé » si la base est injoignable).
- **Le flip Direction A n'est pas invoqué** : `scan_corpus.db` n'est ni le
  canonique ni une réplique, c'est un store lab isolé. Son absence de garde
  `EURIO_DB_READONLY` est le comportement voulu, pas un défaut à réparer.
- Rien sur MinIO, rien sur le VPS, aucun commit, aucun push. Aucune image, aucun
  pull supprimé.
- `ml/vision/sync_eval_real.py`, `ml/training/*`, `ml/tests/test_benchmark.py`
  n'ont pas été touchés.

---

## 6. Décisions en attente, et ce que je n'ai pas pu établir

### 6.a 🔴 Décision PO — valider (ou corriger) les 4 lignes d'`EXTRA_MAPPING`

Ces 4 correspondances sont **mesurées et reproductibles** (§2), mais la méthode
du remap exige une validation **à l'œil sur la photo**, et je ne l'ai pas faite.
Le risque résiduel n'est pas nul et il a un précédent exact dans ce dépôt :
`MAPPING` contient **deux lignes où le nom de dossier ment sur le millésime**
(`fr-2eur-standard-2007` → pièce de 1999 ; `be-2008-2eur-standard` → pièce datée
2011). Une correspondance transitive par sha256 hérite de la vérité de
`eval_real_norm/` — elle ne la re-juge pas.

Deux issues possibles :
- **valider** → déplacer les 4 lignes d'`EXTRA_MAPPING` vers `MAPPING` avec leur
  `reason`, et les journaliser dans `eurio_id_migrations` au canonique
  (`remap_bench_golden_set --emit-sql`, cf. skill `eurio-data-writes` : aucune
  route `/ingest/*` n'expose cette table) ;
- **corriger** → rejouer l'import après édition de la table ; il est idempotent
  et le `capture_id` ne dépend pas du label, donc un relabel est un simple
  `UPDATE` par upsert, sans recopier une image.

### 6.b Le cas belge se propage au corpus — `be-2008` reste faux **à la pièce**

`MAPPING` marque `be-2008-2eur-standard` `resolution='needs_rematch'` et
`class_level_only=True` : la photo montre une pièce **datée 2011** que le
référentiel ne possède pas. Elle est importée sous
`be-2008-…-2nd-portrait` : **valide à la classe, fausse à la pièce**.

⚠️ Ces **6 captures** (avril, 1 dossier × 6 conditions) sont donc à exclure d'une
évaluation à la pièce. **Aucune colonne du corpus ne le dit aujourd'hui** —
`class_level_only` n'a pas de jumeau dans `scan_corpus`. C'est un silence à
lever avant la première notation stricte ; le porter dans `notes` ne suffira
pas, un filtre a besoin d'une colonne.

### 6.c Un défaut de `sync_eval_real` observé au passage (non corrigé, hors périmètre)

En renormalisant le pull d'avril (§2), la sortie signale :

```
⚠️  6 fichier(s) ÉCRASÉ(S) :
  ! be-2eur-standard-2007/bright_plain.jpg  … (6 fichiers)
```

`ml/datasets/eurio-poc/class_manifest.json` replie **`be-2007-2eur-standard` et
`be-2008-2eur-standard` sur le même `class_id`** `be-2eur-standard-2007` : deux
pièces distinctes, un seul dossier, 6 photos perdues en silence. Le compteur
`overwritten` existe et l'a dit — le garde fonctionne. Le fichier appartient à
un autre agent ; je ne l'ai pas touché. **Sans effet sur le corpus** : l'import
lit l'arbre brut et ne passe jamais par ce manifeste.

### 6.d Non établi

| Question | Pourquoi |
|---|---|
| Le modèle de device des deux pulls | ⚠️ l'information **n'existe dans aucun fichier des deux pulls** — ni sidecar, ni fichier de session. `device_model` reste NULL |
| Le fuseau de `captured_at` | Les `ts` sont en heure locale device, sans offset. Comparer les deux protocoles dans le temps demande de connaître le fuseau du device à ces deux dates |
| Quelle classe manque au run 317/16 | Inchangé depuis LOT0 §6 : il faut le `report_path` du PC |
| Que `KNOWN_CONDITIONS` serve à quelque chose | Vérifié : le set est défini dans le store et **validé nulle part**. **10 des 11 conditions importées n'y figurent pas** (seul `dim` y est), et rien n'a levé. Ce n'est pas un garde |

---

## 7. Ce qui a été touché

```bash
git status --porcelain   # (limité à ce que ce lot possède)
#  M ml/scripts/replay_corpus.py
#  M ml/store/scan_corpus.py
#  M ml/tasks.yml
# ?? docs/work-in-progress/juge-et-banc/LOT1-IMPORT.md
# ?? ml/scripts/import_device_pull.py
# ?? ml/state/validation_gold/device_corpus_manifest.jsonl
# ?? ml/state/validation_gold/device_corpus_manifest.meta.json
# ?? ml/tests/test_import_device_pull.py
```

Les autres entrées de `git status` appartiennent aux agents qui travaillent en
parallèle. Aucun commit, aucun push.
