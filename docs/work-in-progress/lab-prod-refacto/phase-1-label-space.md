# Phase 1 — Label space `eurio_id` partout (côté lab)

> **Statut** : 🔲 à implémenter. Bloque les itérations à classes
> mixtes (toute cohort qui contient au moins un coin avec un
> `design_group_id` non null).
>
> **Pré-requis** : aucun. Cette phase est autonome.
>
> **Débloque** : test-1 v2, et toutes les itérations futures sur des
> cohorts contenant des standards (AT, BE, ES, DE, FR, etc. tels
> qu'ils sont catalogués aujourd'hui).

## Objectif

Rendre l'iteration runner et `prepare_dataset.py` cohérents : tout ce
qui se passe en lab raisonne en `eurio_id`, **sans exception**. Le
`design_group_id` n'a aucune influence côté lab.

## Le bug à corriger

Aujourd'hui (cf. [`analysis.md`](./analysis.md) §"Symptôme 2") :

- `iteration_runner` passe `--only-classes=<eurio_id_list>` à
  `prepare_dataset.py`.
- `prepare_dataset.py` instancie un Resolver, qui mappe chaque
  numista_id à `descriptor.class_id = COALESCE(design_group_id,
  eurio_id)`.
- Pour les coins avec un `design_group_id` (AT-2002, BE-2007,
  ES-1999, …), `descriptor.class_id` est le `design_group_id` →
  pas dans `--only-classes` → la classe est skipée silencieusement.

Conséquence : `eurio-poc/val/` n'a pas toutes les classes de la
cohort, et la library d'embeddings finale est incomplète. Le bench
ne peut jamais prédire les classes manquantes.

## Périmètre

### Fichiers à toucher

| Fichier | Change |
|---|---|
| `ml/eval/class_resolver.py` | Ajouter un mode "force eurio_id" qui ignore le `design_group_id` lors de la construction des descripteurs |
| `ml/training/prepare_dataset.py` | Ajouter un arg CLI `--class-kind {eurio_id,design_group}` (défaut : `design_group` pour rétrocompat) qui propage le mode au resolver |
| `ml/api/training_runner.py` | Dans `_prepare()`, passer `--class-kind eurio_id` quand `cfg.get("dataset_override")` est set (= signal qu'on est en mode iteration lab) |

### Tests fonctionnels

- Une itération sur la cohort `mix-zone-7-cls` (qui contient AT-2002,
  BE-2007, ES-1999) doit produire `eurio-poc/{train,val,test}/` avec
  les **7** dossiers nommés par eurio_id.
- `embeddings_v1.json` doit avoir 7 entrées après
  `compute_embeddings.py`.
- Le bench doit pouvoir prédire chaque eurio_id de la cohort
  (centroïde présent dans la lib).

### Hors-scope

- Déplacer les artefacts vers `lab/iterations/<iid>/` (c'est phase 2).
- Modifier le comportement legacy de `prepare_dataset.py` quand
  appelé sans `--class-kind` (rétrocompat stricte).
- Retirer le mode "destructif par itération" du `iteration_runner`
  (c'est phase 2).

## Approche d'implémentation suggérée

### `class_resolver.py`

Le `CoinRef.class_id` actuel coalesce :

```python
@property
def class_id(self) -> str:
    return self.design_group_id or self.eurio_id
```

Approche minimale : ajouter un paramètre à `build_resolver` (ou la
fonction qui construit le Resolver depuis Supabase) qui, si vrai,
réécrit chaque `CoinRef` avec `design_group_id=None` avant
construction. Le Resolver lui-même reste inchangé — il continue de
faire son COALESCE, sauf que tous les `design_group_id` sont None,
donc ça revient à `eurio_id` partout.

```python
def build_resolver(*, force_eurio_id: bool = False) -> Resolver:
    coins = fetch_coin_refs(...)
    if force_eurio_id:
        coins = [
            CoinRef(eurio_id=c.eurio_id, numista_id=c.numista_id, design_group_id=None)
            for c in coins
        ]
    return Resolver(coins)
```

Pas besoin de toucher la classe `Resolver`, ses méthodes restent
sémantiquement identiques.

### `prepare_dataset.py`

Ajouter un arg CLI :

```python
parser.add_argument(
    "--class-kind",
    choices=["eurio_id", "design_group"],
    default="design_group",
    help="..."
)
```

Le passer à `build_resolver(force_eurio_id=(args.class_kind == 'eurio_id'))`.

Aussi : vérifier que la lecture `eval_real_norm/<class_id>/` (ligne
247 actuelle) tape bien `eval_real_norm/<eurio_id>/` quand on est en
mode eurio. **À vérifier sur disque** : les sous-dossiers existent
bien sous les deux noms (j'ai vu plus tôt que oui pour AT-2002,
BE-2007, ES-1999), mais à valider exhaustivement avant de bouger.

### `training_runner.py`

Dans `_prepare()`, ligne ~362 :

```python
def _prepare(self, row: RunRow) -> str:
    cmd = [VENV_PYTHON, str(ML_DIR / "training" / "prepare_dataset.py")]
    if row.classes_after:
        only = ",".join(sorted({c.class_id for c in row.classes_after}))
        cmd.extend(["--only-classes", only])
    # Iteration mode = eurio_id partout.
    if row.config.get("dataset_override"):
        cmd.extend(["--class-kind", "eurio_id"])
    self._run_subprocess(row.id, cmd)
    ...
```

Le test `cfg.get("dataset_override")` est un proxy fiable — il n'est
set que par `iteration_runner._launch_training`. Si à terme un autre
chemin lance une iteration, on raffinera le signal (ex: `cfg["mode"] =
"lab_iteration"`), mais pour l'instant c'est suffisant.

## Critères d'acceptation

1. ✅ Itération `8ac508b062da` (ou un nouveau test équivalent) relancée
   produit `eurio-poc/train/` à 7 dossiers (un par eurio_id).
2. ✅ `eurio-poc/val/<eurio_id>/` contient bien 6 device snaps pour
   chacun des 7 eurio_ids.
3. ✅ `embeddings_v1.json` a 7 entrées, toutes nommées par eurio_id.
4. ✅ `model_meta.json` indique `num_classes=7`.
5. ✅ Le bench peut prédire chaque eurio_id (au moins un photo→prediction
   pour chaque classe est dans la matrice de confusion).
6. ✅ Aucun changement de comportement quand `prepare_dataset.py` est
   appelé sans `--class-kind` (rétrocompat).

## Pièges à éviter

- **Double mode caché.** Ne pas faire en sorte que le resolver expose
  parfois `class_id=eurio_id` et parfois `class_id=design_group_id`
  selon une variable globale. Le mode est passé explicitement à la
  construction, et le Resolver reste pur.
- **Cohérence de `class_kind`.** En mode eurio, tous les
  `descriptor.class_kind` doivent être `"eurio_id"`. Si certaines
  écritures DB sortent encore `"design_group_id"` parce qu'on a
  oublié un endroit, on aura des manifests incohérents.
- **eval_real_norm/.** Bien vérifier que tous les eurio_id de la
  cohort ont un dossier sous `eval_real_norm/<eurio_id>/` (et pas
  seulement sous `<design_group_id>/`). Si manquant, c'est qu'une
  capture n'a jamais été faite pour cet eurio_id précis — à signaler
  comme un fail explicite côté `_prepare`, pas un silent skip.

## Sortie

Une fois cette phase livrée, on peut relancer test-1 v2 sans changer la
définition de la cohort, et on récolte des chiffres honnêtes. Le mode
"destructif par itération" reste en place (phase 2 le retirera).

Update `progress.md` avec l'entrée datée à la fin de la session.
