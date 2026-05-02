# Phase 4 — Bundle routing (APK prod / cohort-test)

> **Statut** : 🔲 à implémenter.
>
> **Pré-requis** : phase 2 livrée (artefacts isolés). La phase 3 est
> recommandée mais pas strictement nécessaire — sans phase 3 on peut
> déjà router le bundle vers une itération lab spécifique.
>
> **Débloque** : A/B sur device entre prod et candidat, et cohérence
> entre ce qui est testé en lab et ce qui sortira en prod.

## Objectif

Rendre `build_cohort_bundle.py` (et le build APK prod) capable de
**choisir explicitement** la source du bundle :

- `prod/current/` pour l'APK prod.
- `lab/iterations/<iid>/` pour le cohort-test sur une itération
  spécifique.

Aujourd'hui, les deux lisent `ml/output/` qui reflète "la dernière
itération qui a tourné" — c'est ambigu et ça empêche de comparer
deux modèles sur le même device.

## Ce qui change

### `ml/scripts/build_cohort_bundle.py`

Aujourd'hui le script lit en dur :

- `ml/output/embeddings_v1.json`
- `ml/output/eurio_embedder_v1.tflite`
- `ml/output/model_meta.json`
- `ml/datasets/eval_real_norm/` (pour les live tests)

À refactorer pour accepter une source explicite :

```bash
python -m scripts.build_cohort_bundle --source prod
python -m scripts.build_cohort_bundle --source lab --iteration-id <iid>
```

Mapping :

| `--source` | Lit |
|---|---|
| `prod` | `prod/current/embeddings/`, `prod/current/tflite/` |
| `lab --iteration-id <iid>` | `lab/iterations/<iid>/embeddings/`, `.../tflite/` |

Le manifest `bundle_meta.json` ajouté dans le bundle indique
explicitement la source :

```json
{
  "schema_version": 2,
  "source": "lab",
  "iteration_id": "8ac508b062da",
  "training_run_id": "...",
  "built_at": "2026-05-02T..Z",
  "model_version": "v10-arcface",
  "num_classes": 7,
  "class_kind": "eurio_id"
}
```

L'app cohort-test lit `bundle_meta.json` et l'affiche dans son écran
de status — l'utilisateur sait toujours sur quoi il teste.

### Build APK prod

Le build APK prod (cf. `app-android/Taskfile.yml` ou équivalent)
appelle `build_cohort_bundle --source prod` au lieu de l'invocation
actuelle. Si `prod/current/` n'existe pas (cas où aucune promotion
n'a encore été faite), le build échoue clairement avec un message qui
pointe vers la doc promote.

### Endpoint admin

`POST /lab/cohorts/{cohort_id}/iterations/{iteration_id}/build-bundle`
(probablement déjà existant) accepte un param `source` :

- défaut `lab` (= bundle l'itération en cours)
- `prod` (= bundle la prod actuelle, utile pour comparer)

UI : tiroir build APK avec deux boutons "Build cohort-test (cette
itération)" et "Build cohort-test (prod)".

## Ce qui ne change pas

- Le format du `cohort_bundle/` côté Android (`embeddings_v1.json`,
  `eurio_embedder_v1.tflite`, etc.) reste identique. Juste le
  `bundle_meta.json` est ajouté/enrichi.
- Le `EmbeddingMatcher` Android et son code de live tests : aucun
  change. Il bouffe le bundle qu'on lui donne.

## Critères d'acceptation

1. ✅ `build_cohort_bundle --source prod` produit un bundle figé sur
   l'état `prod/current/`, indépendamment des itérations lab en cours.
2. ✅ `build_cohort_bundle --source lab --iteration-id <iid>` produit
   un bundle figé sur cette itération précise.
3. ✅ `bundle_meta.json` indique sans ambiguïté la source.
4. ✅ L'app cohort-test affiche la source dans son écran de status
   (au moins l'iteration_id ou "prod").
5. ✅ Le build APK prod refuse explicitement si `prod/current/`
   n'existe pas (avec un message qui dit "lance une promotion").

## Pièges à éviter

- **Bundle stale.** Le bundle est figé au build. Si l'itération source
  est modifiée après le build (ce qui ne devrait jamais arriver, mais
  bon), le bundle garde l'ancienne version. Le `bundle_meta.json`
  capture les sha256 des artefacts au moment du build pour
  diagnostiquer.
- **Live tests cross-bundle.** Le bundle inclut un manifest des live
  tests à exécuter. Aujourd'hui ce manifest est calé sur
  `eval_real_norm/<class_id>/` côté lab. À voir si ça reste cohérent
  pour `--source prod` (probablement oui : prod expose toutes les
  classes promues, et leurs eval_real_norm existent côté lab).
- **Coexistence avec phase 1.** Côté lab les classes sont en
  `eurio_id`. Côté prod elles peuvent être en `design_group_id` (si
  option fusion) ou en `eurio_id` avec règle d'équivalence (option
  équivalence — recommandée). Le `class_kind` dans `bundle_meta.json`
  doit être cohérent avec ce que le matcher attend.

## Sortie

À la fin de phase 4 :

- L'APK prod consomme un état stable promu, indépendant des
  expérimentations en cours.
- L'app cohort-test peut tester n'importe quelle itération précisément.
- L'utilisateur sait toujours quel modèle est sur son device en
  regardant `bundle_meta.json`.

Update `progress.md`.
