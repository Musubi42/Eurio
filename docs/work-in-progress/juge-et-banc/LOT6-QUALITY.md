# Lot 6 — `quality_score` : une colonne gelée depuis le 5 juin, et le garde qui l'y tenait

> Joué le **2026-08-25**. Décision du PO : le backfill porte sur **tout le parc**
> (17 678 crops non examinés), pas seulement sur le pool éligible.
>
> ⚠️ **Rien n'est déployé, et le parc n'est pas encore rempli.** La route existe,
> le script marche de bout en bout — mais contre une **copie** du canonique
> montée sur le port 8043, supprimée depuis. Le VPS ne sert pas encore
> `/ingest/quality-scores`, donc la passe réelle n'a pas pu partir. L'API `:8042`
> n'a pas été touchée (vérifié : toujours `EURIO_DB_READONLY=1` sur la réplique).
> Cf. §« Ce qui attend le PO ».

## 1. L'état mesuré, avant

```bash
sqlite3 -readonly ml/state/eurio.replica.db \
  "SELECT COUNT(*), SUM(quality_score IS NOT NULL), SUM(tilt_deg IS NOT NULL)
     FROM image_assets WHERE training_eligible=1;"
# 2969|262|637          → 8,8 % du pool éligible, tilt 21,5 %

sqlite3 -readonly ml/state/eurio.replica.db \
  "SELECT COUNT(*), SUM(quality_score IS NOT NULL), SUM(tilt_deg IS NOT NULL)
     FROM image_assets;"
# 18730|1052|2345       → 5,6 % du parc
```

Toutes les lignes scorées portent `quality_pipeline_version = 1` et sont
antérieures au 2026-06-03. **Les 16 369 crops arrivés depuis n'ont jamais été
touchés.**

## 2. Pourquoi c'était gelé — deux causes, toutes deux muettes

### (a) Un chiffre juste un jour, plafond le lendemain

`crop_quality_diag.py:109` portait :

```python
_MAX_SAMPLE = 2274  # tous les crops eBay présents
```

C'était vrai le 5 juin 2026. Le parc a quadruplé ; le diagnostic a continué à
tirer 2 274 crops au hasard (seed 42) et à produire un `results.csv` que le
backfill relisait comme s'il décrivait la base. Un plafond en dur ne se plaint
jamais.

→ remplacé par `--limit`, **défaut `None` = tout le pool**.

### (b) Un seul écrivain, alimenté par un CSV figé

`backfill_quality_score.py` n'était pas un calculateur : c'était un **importeur
de CSV**. Sa source (`ml/state/crop_diag/results.csv`) datait du 5 juin et n'a
jamais été régénérée.

### (c) Le garde qui envoyait le calcul sur la machine qui ne peut pas le faire

`backfill_quality_score.py:90` appelait `guard_vps_only(...)`, qui refuse dès
que `EURIO_DB_READONLY` est vrai **ou** `EURIO_API_URL` est posée — c'est-à-dire
**toujours, sur Mac et PC**. Sa justification était exacte : le script faisait un
`UPDATE image_assets` brut, transporté par aucune route.

Mais la seule machine qu'il autorisait — le VPS — **n'a pas les 12 Go de raws**
dont l'oracle a besoin. Le garde était donc une impasse : il n'y avait aucune
machine où le script pouvait légitimement tourner.

## 3. La solution — le geste que le dépôt avait déjà fait deux fois

| Option | Verdict |
|---|---|
| Lancer sur le VPS | ⛔ physiquement impossible — pas d'images là-bas |
| `--i-know-this-is-canonical` sur le Mac | ⛔ dette : transfert de base entière, course avec la review qui écrit en continu, divergence invisible |
| **Une route `/ingest/quality-scores`** | ✅ le motif de `/ingest/consensus` et `/ingest/faces`, mot pour mot |

Le docstring de `/ingest/consensus` énonce déjà le problème : *« le Mac a le
moteur mais lit une réplique read-only, le VPS écrit mais n'embarque pas
`training/` »*. Ici la variable change (les **images** au lieu de `training/`),
la structure est identique. **Le calcul reste où sont les images, les lignes
voyagent.**

Et une fois la route écrite, **le garde a été retiré** : il existait parce
qu'aucune voie ne transportait cette écriture. Le laisser en aurait fait un
garde décoratif protégeant d'un danger disparu — le motif exact de
`train_embedder.py:53`, corrigé le même jour. Le motif est écrit dans
`scripts/_vps_only_guard.py` : *le jour où `face` et `denom` auront leur route,
ce module doit disparaître, pas se durcir.*

## 4. Ce qui a été écrit

| Fichier | Rôle |
|---|---|
| `ml/store/quality.py` | **neuf** — `apply_ingest_quality_scores(conn, scores)`, SQL pur, commit-free, idempotent, `emit_field_event`, `{updated, skipped, missing}` |
| `ml/serving/ingest_routes.py` | `POST /ingest/quality-scores`, scope `ingest:write`, `BEGIN`/`COMMIT`/`ROLLBACK` |
| `ml/client/ingest.py` | `push_quality_scores(scores)` — no-op si la sync n'est pas activée |
| `ml/scripts/backfill_quality_score.py` | **réécrit** : calculateur + pousseur **en flux**, sélection en LECTURE SEULE, lots de 500, `--dry-run` par défaut, `guard_vps_only` retiré, `--from-csv` conservé pour rejouer l'historique |
| `ml/scripts/crop_quality_diag.py` | `_MAX_SAMPLE` → `--limit` ; `_crop_local_path`/`_raw_local_path` passent par `local_path` ; `measure_crop_quality()` extraite |
| `ml/review/validation/experts.py` | la docstring annonçait « ~46 % » — corrigé **avec la requête et la date** |
| `ml/serving/crop_bench_routes.py`, `scripts/recrop_*.py` | trois appelants de `_raw_local_path` mis à jour (l'absence devient une exception, pas un chemin inexistant) |
| `ml/tests/test_ingest_quality_scores.py` | **neuf** — 13 tests |

### Les deux gardes de l'applier

1. **Jamais de rétrogradation.** Une ligne écrite par un
   `quality_pipeline_version` ≥ n'est pas retouchée (`skipped`). Sous
   Direction A le backfill sélectionne depuis une **réplique**, qui retarde par
   construction : sans ce garde, une passe lancée sur une réplique périmée
   rétrograderait des mesures que le canonique avait déjà améliorées.
2. **`quality_reason` n'est JAMAIS touchée.** Elle porte des labels **humains**
   et des états de review — 1 352 `rejected_in_review`, 51
   `vision_standard_gate`, et `too_tilted` qui vient du banc. Un oracle
   géométrique n'a pas qualité à les écraser. La colonne n'apparaît dans aucune
   chaîne exécutable du module, et un test le vérifie sur l'**AST** (pas sur le
   texte : le module en PARLE dans sa docstring, et c'est ce qu'il doit faire).

### Pourquoi le calcul est un générateur, pas une liste

Première version : mesurer les 17 678 crops, tout accumuler, pousser à la fin.
Vérifié à l'exécution — après 30 minutes et 9 500 crops mesurés, la base copie
n'avait **rien** reçu. Une veille du Mac, un Ctrl-C, une coupure réseau, et
l'heure entière était perdue.

`_measure` **cède** désormais chaque payload dès qu'il est calculé, et l'appelant
pousse dès qu'un lot de 500 est plein. Une interruption ne coûte que le lot en
cours ; les crops déjà écrits ressortent en `skipped` au passage suivant. C'est
ce qui rend la phrase « le script est relançable » vraie plutôt que rassurante.

### Le bug de cache, silencieux

`_crop_local_path` / `_raw_local_path` construisaient
`~/.cache/eurio/<bucket>/<key>` **à la main**, court-circuitant
`shared/storage/local_cache.local_path`. Un crop absent du cache était
**silencieusement sauté** au lieu d'être téléchargé — un diagnostic « complet »
pouvait ignorer un quart du parc sans le dire. Et le bucket était *deviné* alors
qu'il se **dérive** (`bucket_for_asset`) : `image_assets.storage_path` est la
**clé S3**, pas un chemin.

Après le fix, `local_path` télécharge, retente les 403 transitoires de MinIO, et
lève `FileNotFoundError` sur une absence **confirmée** (en marquant la row
`missing_in_storage`). La distinction « absent du cache » (non-événement) /
« absent du stockage » (fait) devient lisible.

## 5. ⚠️ La limite de méthode — à lire avant d'appeler cette colonne « qualité »

`quality_score = clamp(min(r, 2-r), 0, 1)` où `r = r_pipe / r_probe` : le rayon
croppé rapporté au rim vrai trouvé par Otsu. **C'est une mesure de CADRAGE, pas
de qualité**, et ce n'est pas un détecteur d'erreur :

- **elle plafonne.** Sur fond texturé Otsu n'isole pas le rim, `r_ratio` reste
  `None`, et **~35 % du parc restera NULL** — mesuré sur les passes de ce jour :
  32 % à 48 % de scores obtenus selon l'échantillon. NULL = **non mesuré**,
  jamais *mauvais* : l'expert `crop_quality` s'abstient ;
- **elle est AVEUGLE aux vraies pannes.** L'oracle re-probe autour du centre
  **choisi par le pipeline**. Un crop pris sur le **mauvais objet** — capsule,
  coincard, tissu, pièce voisine, graphisme de numisbrief — est scoré « ok ».
  La vraie question (« est-ce seulement une pièce ? ») se lit avec le DINO
  `top1_sim` (cf. `crop_quality_diag.py` §oracle DINOv2).

Cette limite est écrite dans le docstring de `store/quality.py`, dans celui de
la route, et dans celui du script. **Une colonne qui s'appelle « quality » sans
que sa limite soit lisible à côté est un piège**, et c'est déjà arrivé une fois
sur ce chantier.

## 6. Vérification

### Suite

Suite complète : **2357 passed, 0 failed** (2346 + 11 de `test_sources_base.py`
lancé à part), dont **13 tests neufs**. **Deux mutations obligatoires**, chacune fait
rougir le test qu'elle vise et lui seul :

```
=== MUTATION 1 : garde de version neutralisée (`if existante… >=` → `if False`) ===
FAILED tests/test_ingest_quality_scores.py::test_rejouer_la_meme_version_ne_change_rien
FAILED tests/test_ingest_quality_scores.py::test_ne_retrograde_jamais_une_mesure_plus_recente
2 failed, 11 passed
=== REVERT 1 === 13 passed

=== MUTATION 2 : protection de quality_reason retirée (colonne ajoutée au SET) ===
FAILED tests/test_ingest_quality_scores.py::test_n_ecrase_jamais_un_label_humain
1 failed, 12 passed
=== REVERT 2 === 13 passed
```

### Bout en bout, contre une API de test (port 8043, **copie** du canonique)

L'API `:8042` n'a pas été touchée (elle tourne en mode réplique read-only). Copie
faite par `VACUUM INTO` — jamais `cp` sur un SQLite en WAL.

```
$ python -m scripts.backfill_quality_score --dry-run
parc : 18730 crops, 1052 déjà scorés (5.6 %)
scope=all · à examiner (pipeline v1) : 17678
  mesurés : 50 · score obtenu : 24 (48,0 %) · oracle muet : 26 (52,0 %)
  tilt mesuré : 50 (fiable : 22)
DRY-RUN — rien écrit, rien poussé.
{"updated": 0, "skipped": 0, "missing": 0, "dry_run": true, "a_examiner": 17678}
exit=0

$ EURIO_API_URL=http://127.0.0.1:8043 python -m scripts.backfill_quality_score \
    --apply --limit 300 --batch 100
mesure de 300 crops (…), poussés par lots de 100…
  … écrit 0/100 (skipped=100, missing=0)     ← les 200 du run précédent : idempotence
  … écrit 0/100 (skipped=100, missing=0)
  … écrit 100/100 (skipped=0, missing=0)
{"updated": 100, "skipped": 200, "missing": 0}
exit=0
```

`missing = 0` sur toutes les passes — c'est LE critère : aucun asset poussé n'est
inconnu du canonique.

### La répétition à l'échelle — arrêtée volontairement à 6 500 crops

Une passe `--apply` sans `--limit` a été lancée contre la copie, puis **arrêtée
en cours** (elle avançait à ~150 crops/min ; cf. le coût de parcours de cache
ci-dessous). Ce qu'elle a prouvé, et qui était le but :

```
  … écrit 500/500 (skipped=0, missing=0)     × 13 lots, aucun autre motif
```

État de la copie **après l'interruption** — la preuve que le flux écrit au fil
de l'eau et qu'un Ctrl-C ne perd rien :

```
sqlite3 -readonly ml/state/eurio.work.quality.db \
  "SELECT COUNT(*), SUM(quality_score IS NOT NULL), SUM(tilt_deg IS NOT NULL),
          SUM(quality_pipeline_version IS NOT NULL) FROM image_assets;"
# avant : 18730|1052|2345|1052
# après : 18730|4641|7598|7552
```

+3 589 scores, +5 253 tilts, +6 500 crops examinés, tous conservés malgré
l'arrêt. La copie a ensuite été supprimée : elle n'a servi qu'à la répétition.

⚠️ Ces chiffres viennent d'une **copie**, pas du canonique. Ils ne dispensent
pas de la passe réelle.

**Un push raté rend bien un échec, pas un faux succès** (canonique injoignable) :

```
$ EURIO_API_URL=http://127.0.0.1:9999 python -m scripts.backfill_quality_score --apply --limit 3
exit=1
```

(Le code retour a été lu **hors pipe** — `cmd | tail; echo $?` rend le statut de
`tail`, piège documenté dans `eurio-verify`.)

## 7. Ce qui attend le PO

1. **Déployer** `eurio-api` sur le VPS — sans ça, `/ingest/quality-scores`
   n'existe pas côté canonique et le backfill réel ne peut pas partir
   (`go-task` + skill `eurio-vps-deploy`). Rien n'a été déployé ici.
2. **Lancer la passe réelle** une fois déployé :
   `cd ml && ./.venv/bin/python -m scripts.backfill_quality_score --apply`
   Le script est relançable : une interruption ne coûte que le lot en cours.

   ⚠️ **Le coût réel n'est PAS le CPU de l'oracle.** Mesuré ce jour sur le Mac :

   ```python
   # 62 103 fichiers, 14,5 Go, parcours complet = 1,30 s
   for f in Path.home().joinpath(".cache/eurio").rglob("*"): f.stat()
   ```

   `EURIO_CACHE_MAX_GB=20` est posé dans l'environnement, et
   `local_cache.local_path` appelle `_evict_if_needed()` **avant chaque
   téléchargement** — donc un `rglob` complet du cache à chaque raw manquant.
   Avec ~3 800 raws à récupérer, cela fait **~80 min de parcours de cache**
   contre ~7,5 min de CPU d'oracle. C'est ce qui domine la passe, et ce n'est
   pas une propriété du backfill.

   Deux sorties possibles, à trancher (aucune n'a été faite ici —
   `shared/storage/local_cache.py` est hors périmètre de ce lot) : lancer la
   passe avec `EURIO_CACHE_MAX_GB=0` (éviction désactivée, le cache grossit),
   ou corriger l'éviction pour qu'elle ne re-scanne pas tout à chaque objet.
3. **Décider si `results.csv` doit être régénéré.** `--from-csv` reste là pour
   rejouer l'historique, mais le CSV figé n'est plus le chemin nominal.
4. **Ne PAS ressusciter `ml/archive/scripts/crop_tilt_backfill_db.py`** : il
   pointe `ml/state/eurio.db` **en dur, sans `resolve_db_path`** — il écrirait la
   base périmée. Un seul écrivain, une seule route.
5. **La question de fond reste ouverte** : cette colonne mesure le cadrage, pas
   la qualité. Tant que rien ne mesure « est-ce la bonne pièce ? », un pool
   « 100 % quality_score ≥ 0,85 » ne dit rien sur la propreté du corpus
   d'entraînement. C'est le sujet de `docs/work-in-progress/review-autovalidation/`.
