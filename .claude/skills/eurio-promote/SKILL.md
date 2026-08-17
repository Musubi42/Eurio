---
name: eurio-promote
description: Mettre un modèle du lab en production — prod/current, assets APK, MinIO, Supabase. À lire avant tout `promote_iteration`, ou quand on se demande ce que l'APK reconnaîtra après.
---

# Promouvoir un modèle

> ⚠️ **La promotion écrit en production.** C'est le seul geste du projet qui
> franchit la frontière préprod → prod. Elle **remplace**, elle n'accumule pas :
> ce que l'itération ne couvre pas, l'APK cesse de le reconnaître.
>
> La chaîne complète n'a été parcourue pour la première fois que le
> **2026-08-16**, jusqu'à `prod/current` — jamais au-delà.

## La chaîne, et ses quatre outils

```
ml/lab/iterations/<iid>/                       ← sortie du parcours 4
   │  python -m scripts.promote_iteration <iid>
   │     • copie ATOMIQUE des 3 dossiers → prod/current (archive l'ancien)
   │     • écrit promoted_from.json (sha256 de chaque fichier)
   │     • POUSSE SUPABASE, sauf --no-supabase
   ▼
ml/prod/current/{checkpoints,embeddings,tflite}
   │  python -m scripts.promote_prod_assets
   ▼
app-android/src/main/assets/{models,data}
   │  go-task ml:assets:publish  → MinIO `model-artifacts`
   │                             + réécrit shared/model-assets.json (committé)
   ▼
MinIO ── go-task ml:assets:fetch (preBuild Gradle) ──▶ APK
```

Il existe un **troisième chemin qui fait la même chose en silence** :
`POST /export/deploy`, qui renvoie `200 {count: 0}` si la source manque. Ne
l'utilise pas.

## Les quatre pièges, dans l'ordre où ils mordent

### ① La promotion doit tourner sous le MÊME `EURIO_DB_PATH` que le calcul

Le script honore `EURIO_DB_PATH` (depuis le 2026-08-16 — avant, le chemin était
en dur et la promotion était **impossible** en mode compute). Or le devShell
pointe cette variable sur la **réplique**, où les lignes de run n'existent pas.

```bash
cd ml
EURIO_DB_PATH="$PWD/state/eurio.work.db" \
  ./.venv/bin/python -m scripts.promote_iteration <iid> --dry-run
```

⚠️ **Ne lis pas le code de sortie à travers un pipe** : `… | tail -12; echo $?`
rend le statut de `tail`. Un refus a déjà été rapporté comme `exit=0`.

### ② La garde de traçabilité — et ce que son message a de faux

Une itération `completed` dont `training_run_id` est NULL est **refusée** : le
modèle promu ne serait reliable à aucun run. `--force` passe outre.

Le message d'erreur affirme que la réplique « n'a jamais reçu les tables de
run ». **C'est faux**, et le savoir évite une demi-heure : la réplique porte
**34 `training_runs`**, et certaines itérations `completed` y **gardent** leur
lien. Le vrai mécanisme est au canonique —
`serving/iteration_sync_routes.py:126-129` annule le lien **au cas par cas**
quand la ligne de run ne lui a pas été poussée :

```python
if data.get("training_run_id") and store.get_run(data["training_run_id"]) is None:
    data["training_run_id"] = None
```

Corollaire : le remède que le message propose (« promeus depuis la base de
CALCUL ») **n'est pas toujours une sortie**. Mesuré le 2026-08-17 :
`eurio.replica.db` → 7 `completed` dont 6 sans run ; `eurio.work.db` → 5
`completed` dont **3 sans run**. Pour ces trois-là, les deux bases refusent.

### ③ `--force` désarme trois contrôles à la fois — mais il le crie désormais

Le même drapeau couvre le statut, le verdict **et** la traçabilité. Quelqu'un qui
le pose pour un verdict `pending` désarmait la traçabilité **sans le savoir** :
`promoted_from.json` s'écrivait avec `"training_run_id": null`, en silence.

Depuis le 2026-08-17, chaque contrôle désarmé émet son propre avertissement sur
**stderr** (`⚠️ --force : TRAÇABILITÉ DÉSARMÉE …`) et la liste est persistée dans
`promoted_from.json.force_overrides` — pour qu'on sache après coup si c'était un
choix ou un accident.

⚠️ Le drapeau reste **unique** : il n'y a toujours pas de `--force-no-run`
distinct. `--force` pour un statut désarme encore la traçabilité au passage ; la
différence est qu'il ne le fait plus en cachette.

### ④ La promotion REMPLACE — et les mots du script suggèrent le contraire

`_atomic_copy` remplace `prod/current` en bloc. Le fichier d'embeddings de l'APK
est **substitué**, pas fusionné.

`--replace-all` **n'affecte QUE Supabase** (suppression des lignes orphelines) ;
son `--help` le dit, le vocabulaire du diff (`added` / `kept` /
`absent_in_promotion`) le cache. **Les classes listées `absent_in_promotion` sont
exactement celles qui disparaîtront de l'APK.**

Mesuré sur l'itération du PC `03f767f998ef` contre la production :

| | classes |
|---|---|
| en production | 23 embeddings → **20 classes** |
| itération du PC | **61** (expansion design_group) |
| communes | 20 |
| **perdues** | **3** pièces standard FR et ES |
| gagnées | 41 |

Bilan très favorable — mais **trois 2 € standard, les pièces les plus courantes
en circulation**, cesseraient d'être reconnues. C'est un arbitrage produit, pas
un détail. La parade est une **cohorte d'union** : cf. `eurio-cohort`.

### Lis `reference` avant `absent_in_promotion` — corrigé le 2026-08-17

Le diff se comparait à `prod/current/embeddings/embeddings_v1.json` et prenait
**l'ensemble vide** quand le fichier manquait : `absent_in_promotion` valait
alors *toujours* `[]`. Sur le Mac, où `ml/prod/` n'existe pas, le dry-run
annonçait « rien de perdu » là où la vérité était **16 pièces perdues sur 23**.

Il choisit maintenant sa référence, du plus fidèle au moins fidèle, et **le dit** :

| `reference` | Source | `id_space` |
|---|---|---|
| `prod_current` | `prod/current/…/embeddings_v1.json` | `class_id` — comparaison exacte |
| `apk_asset` | `app-android/src/main/assets/data/coin_embeddings.json` | `numista_id` — l'état **réel** de la prod, disponible partout |
| `none` | aucune | `blind: true`, champs à **`None`** (jamais `[]`), et la promotion **refuse** sauf `--allow-blind-diff` |

Toute perte non vide déclenche un avertissement sur **stderr**. Vérifié sur le
vrai point d'entrée :

```
$ EURIO_DB_PATH="$PWD/state/eurio.work.db" … promote_iteration 4aaac6865ca9 --dry-run
⚠️  16 entrée(s) sur 23 (numista_id) … ABSENTES de cette promotion —
    l'app cessera de les reconnaître. Référence : apk_asset.
  reference: apk_asset | n_new: 7 | n_current: 23 | perdues: 16
```

⚠️ **Les deux modes ne sont pas commensurables** : `prod_current` compare en
`class_id`, `apk_asset` en `numista_id`. D'où le champ `id_space` — lis-le avant
de comparer deux sorties entre elles.

⚠️ Et la perte de classes reste un **avertissement**, pas un blocage : c'est un
arbitrage produit. Le script ne décidera pas à ta place.

## Exercer la chaîne sans toucher à la production

`--no-supabase` (ajouté le 2026-08-16) sépare le geste local du geste de prod :

```bash
cd ml
EURIO_DB_PATH="$PWD/state/eurio.work.db" \
  ./.venv/bin/python -m scripts.promote_iteration <iid> --no-supabase
./.venv/bin/python -m scripts.promote_prod_assets --dry-run
```

`--dry-run` sur `promote_iteration`, lui, **ne fait rien du tout** : il imprime
le diff et sort. Il ne crée pas `prod/current`.

⚠️ **Donc `promote_prod_assets --dry-run` échoue tant qu'aucune promotion réelle
n'a eu lieu** (`error: ml/prod/current missing`, exit 2). La « répétition à
blanc » n'est pas entièrement à blanc : son premier maillon (`--no-supabase`)
**écrit** sur le disque local. Vérifié le 2026-08-17.

### ⛔ La cible Supabase n'existe pas — mais l'échec est maintenant préventif

`bootstrap/seed_supabase.py` upserte `/rest/v1/model_classes` et
`/rest/v1/coin_embeddings`. Mesuré le 2026-08-17 sur le projet ciblé :

```sql
select to_regclass('public.coin_embeddings'), to_regclass('public.model_classes');
-- null | null
```

Le projet porte bien la projection catalogue (`coin`, `design_group`, `sets`…)
mais **ni l'une ni l'autre des deux tables du modèle**. `promote()` écrasait
`prod/current`, archivait l'ancienne, **puis** plantait : état à moitié promu.

Depuis le 2026-08-17, `_check_supabase_target()` sonde les deux tables
(`?select=*&limit=0`, lecture seule, **aucune DDL**) **avant** `_promote_lock()`
et `_atomic_copy`. En cas d'absence : refus, et le message le dit —
*« Rien n'a été écrit : prod/current est INTACT »*.

Tant que ces tables n'existent pas, `--no-supabase` reste **obligatoire**, et la
projection se pousse séparément. Créer les tables est une **DDL en production** :
c'est une décision, pas un correctif de script.

## Piège de lecture : trois cardinalités pour un modèle

Le lab produit **deux** fichiers d'embeddings, et ils ne comptent pas la même
chose :

| Fichier | Clés | Qui le lit |
|---|---|---|
| `coin_embeddings.json` | `numista_id` | `EmbeddingMatcher` de l'app — **c'est lui qui décide ce que l'APK reconnaît** |
| `embeddings_v1.json` | `class_id` | Supabase, et le diff de promotion |

Vérifié : le diff annonce `n_new: 24` (espace `class_id`) pendant que l'APK
recevra **61 entrées** (espace `numista_id`). Un opérateur qui lit « 24 » et voit
61 lignes arriver a raison de s'inquiéter, et tort de conclure à un bug.

Troisième compte, encore différent : `model_meta.json` liste **17 classes** pour
23 embeddings, sous des slugs **qui n'existent plus** au référentiel
(`at-2eur-standard-2002`, `es-2016-…-old-city-of-segovia…`,
`de-2007-2eur-schwerin-castle…`). Sans conséquence fonctionnelle — l'app matche
sur `numista_id`, stable — mais **toute lecture humaine de ce fichier est
trompeuse**.

## Ce que la promotion ne couvre pas

- **Le détecteur.** `coin_detector.tflite` n'entre dans aucune promotion :
  `promote_prod_assets` ne copie que `eurio_embedder_v1.tflite`,
  `coin_embeddings.json` et `model_meta.json`. Le YOLO a sa propre chaîne,
  `ml:training-assets:*`.
- **`promote_prod_assets.py` est le script *legacy* PC-only.**
  `promote_iteration`, lui, crée `ml/prod/` à la demande **sur n'importe quelle
  machine** — la doc qui dit « la promotion est PC-only » se trompe de script.
- **Le rechargement du catalogue côté app** : `AppCoreBootstrapper.kt` gate sur
  `APP_CORE_VERSION`, constante **codée en dur et jamais incrémentée**. Ça
  concerne `app_core.db`, pas les embeddings, mais c'est le même genre de piège
  dans la même étape.

## Avant de promouvoir — la liste

0. **Les artefacts sont-ils sur CETTE machine ?** `ml/lab/iterations/<iid>/` doit
   exister avec `checkpoints/`, `embeddings/`, `tflite/`. Une itération visible
   au canonique n'est **pas** promouvable ailleurs que là où elle a été calculée
   — le modèle ne voyage pas (parcours 4 ①). Mesuré le 2026-08-17 : 3 dossiers
   sur le Mac pour 7 itérations connues.
1. L'itération est `completed` avec un verdict, et son `training_run_id` **n'est
   pas** NULL dans la base que tu vas lire (⚠️ ② ci-dessus).
2. `--dry-run` sous le bon `EURIO_DB_PATH`. **Regarde `n_current` AVANT
   `absent_in_promotion`** : à 0, le diff est aveugle et ne dit rien de ce que
   tu perds (⚠️ ④). Compare alors à l'asset de l'APK.
3. Si des classes se perdent → cohorte d'union, ou décision produit assumée.
4. Répétition à blanc : `--no-supabase` (⚠️ **ça écrit** sur le disque local),
   puis `promote_prod_assets --dry-run`.
5. Vérifie que le correctif marche vraiment : **`eurio-verify`**.

## Ce que cette skill ne couvre PAS

- Produire l'itération : **`eurio-cohort`** puis **`eurio-run-local`**.
- Le trajet complet mesuré, avec ses chiffres :
  `docs/architecture/parcours.md` §5.
- Le déploiement du canonique et des fronts : **`eurio-vps-deploy`**.
