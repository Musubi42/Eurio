# Phase 3 — Step `promote` explicite

> **Statut** : 🔲 à implémenter.
>
> **Pré-requis** : phase 2 livrée (artefacts isolés par iteration_id).
> Sans phase 2, il n'y a pas de `lab/iterations/<iid>/` à promouvoir.
>
> **Débloque** : la sémantique "prod = état stable", la possibilité de
> rollback, et la suppression définitive du mode destructif.

## Objectif

Faire de la promotion d'une itération vers la prod un **acte
explicite et atomique**. Une seule action déclenche :

1. Copie des artefacts lab → `prod/current/`
2. Push Supabase (table `coin_embeddings` + `model_classes`)
3. Trace dans `prod/current/promoted_from.json` (et optionnellement
   table `model_promotions`)

Avant cette phase, n'importe quel run lab pousse dans Supabase via
`_seed`. Après cette phase, **seule la promotion** écrit en prod.

## Ce qui change

### Nouveau script CLI

`ml/scripts/promote_iteration.py` (ou un sous-commande dans un script
existant). Signature :

```bash
python -m scripts.promote_iteration <iteration_id> [--force] [--dry-run]
```

Comportement :

1. Vérifie que l'itération est `status=completed` et qu'elle a un
   `verdict` ∈ {`baseline`, `better`} (sauf si `--force`).
2. Vérifie que `lab/iterations/<iid>/{checkpoints,embeddings,tflite}/`
   sont complets (sha256 attendus présents dans la DB ou les meta).
3. Calcule un diff de classes : qu'est-ce qui s'ajoute, change,
   disparaît côté `prod/current/` ?
4. Si `--dry-run`, affiche le diff et sort.
5. Sinon :
   - Backup `prod/current/` → `prod/archive/<promoted_from_iid>-<promoted_at>/`
     (rétention configurable, par défaut on garde au moins le dernier).
   - Copie atomique `lab/iterations/<iid>/{...}` → `prod/current/`.
   - Écrit `prod/current/promoted_from.json` :
     ```json
     {
       "iteration_id": "...",
       "training_run_id": "...",
       "promoted_at": "2026-05-02T..Z",
       "promoted_by": "<user>",
       "verdict": "better",
       "summary": {...metrics...},
       "sha256": {...artifact hashes...}
     }
     ```
   - Push Supabase (cf. ci-dessous).
   - Insère row dans `model_promotions` (si la table existe).

### Endpoint admin (optionnel mais recommandé)

`POST /lab/cohorts/{cohort_id}/iterations/{iteration_id}/promote` qui
appelle le script ci-dessus en background. Renvoie un `job_id` pour
suivi.

UI : un bouton "Promote en prod" sur la page iteration, visible
seulement si `verdict ∈ {baseline, better}`. Confirmation modale
obligatoire avec le diff classes.

### Suppression du `_seed` automatique

Dans `training_runner.py`, le step 4 `_seed` :

- **Avant phase 3** : appelé inconditionnellement à la fin du training
  pipeline.
- **Après phase 3** : appelé **uniquement** par
  `promote_iteration.py`. Le step 4 est retiré du `STEPS` du
  training_runner, ou conditionné à un flag explicite
  `cfg["push_supabase"] = True` qui n'est jamais set par le lab.

`seed_supabase.py` lui-même ne change pas — il continue de lire
`embeddings_v1.json` et `model_meta.json`. Le change est juste **qui
l'appelle** (la promotion, jamais le training direct).

### Sémantique de la promotion

La promotion **ne change pas l'itération source**. L'itération
`<iid>` reste `status=completed` avec ses artefacts intacts sous
`lab/iterations/<iid>/`. La promotion fait des **copies**.

Conséquence : on peut promouvoir une vieille itération si besoin
(rollback). On peut promouvoir la même itération deux fois (no-op
idempotent si rien n'a changé). On peut comparer plusieurs itérations
sans risquer d'en "détruire" une.

## Décision à trancher : fusion vs équivalence

Cf. [`vision.md`](./vision.md) §"Le label space".

Quand l'itération source est en `eurio_id` (toujours, après phase 1),
la prod doit gérer le `design_group_id`. Deux options :

### Option A — Fusion (centroïdes moyennés)

Au moment de la promotion, pour chaque `design_group_id` ayant des
membres dans l'itération promue, le script :

- Récupère les centroïdes des `eurio_id` membres dans
  `lab/iterations/<iid>/embeddings/embeddings_v1.json`.
- Calcule la moyenne (L2-normalisée).
- Pousse **un seul** centroïde sous le `design_group_id` dans Supabase.

`coin_embeddings` reste granulaire au niveau `eurio_id` mais avec
des centroïdes potentiellement identiques pour des membres du même
group (ou un schéma alternatif où la table est keyée par
`(class_id, class_kind)` avec class_id qui peut être un design_group).

**Avantage** : matcher prod simple, pas de logique d'équivalence.
**Inconvénient** : on perd la capacité de remonter à un eurio_id
précis (utile pour expliquer "cette pièce a été identifiée comme
BE-2007 ou BE-2008 ?"). Et si un design_group regroupe deux variantes
visuellement distinctes (cf. BE-2007 vs BE-2008), la fusion tire le
centroïde au milieu d'un cluster bimodal — moins bon.

### Option B — Équivalence (centroïdes par eurio_id, règle au matcher)

Tous les `eurio_id` gardent leur centroïde individuel dans Supabase.
Le matcher (côté Android et côté bench) applique une règle :

- À l'inférence, top-1 = `eurio_id` X.
- Le ground truth est `eurio_id` Y.
- Si X et Y partagent le même `design_group_id` non-null, c'est
  correct.

**Avantage** : on garde la granularité, l'évaluation reste fine, on
peut décider plus tard si on remonte le top-1 à l'utilisateur ou le
design_group.
**Inconvénient** : la règle doit être implémentée à plusieurs
endroits cohérents (matcher Android, bench Python). Risque de drift.

### Recommandation

**Option B**, parce qu'elle préserve la lisibilité de l'évaluation
et qu'on peut toujours basculer en fusion plus tard si l'option B
s'avère trop complexe à maintenir. La règle d'équivalence est petite
(une lookup `design_group_id`) et déjà partiellement implémentée
côté bench (cf. test-2 où R@1 acceptait at-2002 → at-2eur-standard-2002).

À discuter avant de coder. Ne pas livrer la phase 3 sans avoir
tranché.

## Critères d'acceptation

1. ✅ Un run lab ne pousse **plus rien** dans Supabase (table
   `coin_embeddings` et `model_classes` figées tant qu'aucune
   promotion n'est faite).
2. ✅ `python -m scripts.promote_iteration <iid>` copie les artefacts
   et pousse Supabase. `prod/current/promoted_from.json` est créé.
3. ✅ Promouvoir la même itération deux fois est idempotent (pas
   d'erreur, pas de doublon).
4. ✅ Promouvoir une vieille itération ré-écrit `prod/current/` avec
   ses artefacts.
5. ✅ Un dry-run affiche le diff sans rien modifier.
6. ✅ Si l'itération est `status != completed` ou `verdict ∉ {baseline,
   better}`, la promotion refuse (sauf `--force`).
7. ✅ La règle d'équivalence (option B) est en place côté bench et
   côté matcher Android, avec un test qui échoue si elle drift.

## Pièges à éviter

- **Race condition sur `prod/current/`.** La copie doit être atomique
  (rename via `os.rename(tmp_dir, prod_current_dir)` après prep dans
  un dossier temporaire). Sinon une lecture concurrente peut voir un
  prod/current/ semi-écrit.
- **Backup avant overwrite.** Toujours `prod/archive/<previous_iid>/`
  avant d'écraser. Sans archive, pas de rollback rapide.
- **Mismatch class set.** Si l'itération promue a 7 eurio_ids et la
  prod précédente en avait 50, les 43 autres centroïdes sont-ils
  supprimés ou conservés ? À trancher : par défaut **conserver** ce
  qui n'est pas dans la nouvelle promotion (la prod accumule), avec
  un flag `--replace-all` pour rebuild from scratch. Cohérent avec
  l'idée "prod = état stable".
- **Supabase eventually consistent.** Si plusieurs promotions sont
  enchaînées rapidement, l'ordre des PATCH/POST/DELETE peut donner
  un état intermédiaire incohérent. Verrouiller la promotion (un seul
  flow à la fois) au niveau du script.

## Sortie

À la fin de phase 3 :

- Le lab est totalement isolé : aucun effet de bord externe (ni
  Supabase, ni `prod/current/`).
- La promotion est l'unique chemin lab → prod, traçable et réversible.

Update `progress.md`.
