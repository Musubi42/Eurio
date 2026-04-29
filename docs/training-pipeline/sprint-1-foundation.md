# Sprint 1 — Foundation : augmentations stockées + stop training + recipe interactive

> Durée estimée : 2-3 jours
> Pré-requis : cohort capture flow livré (acté), aucun autre.
>
> **Si tu reprends ce sprint en cold start** : lis `vision.md`, `decisions.md`
> (D-004, D-009), `filesystem.md`, puis `progress.md` (entrées de ce sprint).

## Goal

Donner à une iteration sa vraie identité reproductible :
- ses augmentations vivent sur disque, identifiables, regénérables
- son training peut être stoppé proprement (sans crasher l'API)
- la recipe est éditable depuis la page cohort (statu quo : passage par un
  formulaire d'iteration séparé)

## Scope

### Inclus

- Persistance des augmentations sur disque sous
  `ml/datasets/<numista_id>/augmentations/<iteration_id>/`
- Seed reproductible par iteration (`augmentations_seed`)
- Endpoint POST regenerate augmentations (utile si on change la recipe
  associée à une iteration draft)
- Endpoint POST stop training avec graceful SIGTERM + 30s timeout + SIGKILL
- Bouton "Stop" dans l'iteration row pendant qu'elle tourne
- Section §3 Recipe interactive dans CohortDetailPage : sélectionner une
  recipe, prévisualiser N samples augmentations (3-6 par pièce), avant
  même de lancer le training
- Galerie augmentations dans iteration detail (post-training : tout le
  snapshot stocké)

### Exclus (sprints suivants)

- Comparaison aug↔réelles (sprint 2)
- Distance DINO (sprint 2)
- Build cohort-test app (sprint 3)
- Live tests device (sprint 4)
- Garbage collect des augmentations (sprint 5)

## Tasks (ordre)

### A. Backend storage & seed (~½ jour)

1. **Migration SQLite** : ajouter colonne `augmentations_seed INTEGER` à
   `experiment_iterations` (via `_ensure_column` dans `Store._bootstrap`).
   Backfill = `NULL` pour iterations existantes.
2. **À la création d'une iteration** : si seed pas fourni dans le payload,
   générer `random.randint(0, 2**31-1)`. Persister.
3. **Constante de path** : exposer `AUGMENTATIONS_BASE = ml/datasets` et
   helper `augmentations_dir_for(numista_id, iteration_id) -> Path`.

### B. Pipeline d'augmentation persistante (~1 jour)

4. **Adapter `train_embedder.py`** (ou le pipeline qui génère les
   augmentations) :
   - Avant le training, si `augmentations/<iteration_id>/` est vide,
     régénérer avec `seed`.
   - Si non vide, **réutiliser** ce qui est sur disque (reproductibilité).
   - Path d'écriture : `<numista_id>/augmentations/<iteration_id>/sample_<NNN>.jpg`.
5. Vérifier que le DataLoader pointe sur `augmentations/<iid>/` au lieu
   d'augmentations en mémoire.
6. **Endpoint** `POST /lab/cohorts/<cid>/iterations/<iid>/augmentations/regenerate`
   - efface le dossier, regenère depuis recipe + seed
   - 409 si l'iteration n'est pas en `pending` (i.e. déjà trainée)
7. **Endpoint** `GET /lab/cohorts/<cid>/iterations/<iid>/augmentations`
   - retourne la liste des fichiers par pièce :
     `{per_coin: [{eurio_id, numista_id, samples: [<path>...]}]}`
   - paths relatifs à `ml/` pour le serving

### C. Stop training (~½ jour)

8. **Signal handler dans `train_embedder.py`** :
   ```python
   import signal
   _stop_requested = False
   def _on_term(_signum, _frame):
       global _stop_requested
       _stop_requested = True
   signal.signal(signal.SIGTERM, _on_term)
   ```
   - À chaque fin d'epoch, check `_stop_requested` → sauve checkpoint
     `*.partial`, exit(2).
9. **`IterationRunner.stop(iteration_id)`** :
   - récupère le subprocess, `subprocess.terminate()` (SIGTERM)
   - attend `proc.wait(timeout=30)`
   - si timeout, `proc.kill()` (SIGKILL)
   - update DB : iteration `status='failed'`, `error="Stopped by user
     (graceful|forced)"`, `finished_at=now`.
10. **Endpoint** `POST /lab/cohorts/<cid>/iterations/<iid>/stop`
    - 409 si l'iteration n'est pas `training|benchmarking`
    - sinon délègue au runner

### D. Front : recipe + augmentations preview (~1 jour)

11. **Composable Vue Query** :
    - `useAugmentationsQuery(iterationId)` → liste fichiers
    - `useRegenerateAugmentationsMutation(iterationId)` → invalidate above
    - `useStopIterationMutation()` → invalidate iterations list
12. **Section §3 Recipe** dans `CohortDetailPage` (ou dans un nouveau
    composant `RecipeSection.vue`) :
    - select de recipe (déjà existant ailleurs, à intégrer)
    - bouton "Prévisualiser augmentations" → si aucune iteration n'existe,
      crée une iteration en status `pending` sans lancer le training
    - galerie : pour chaque pièce de la cohort, afficher 6 samples
13. **Bouton "Stop"** sur l'iteration row si status `training|benchmarking`,
    avec confirm dialog. Click → `useStopIterationMutation`.
14. **Section §3 augmentations galerie** post-training : grille `<img>`,
    cliquable pour zoom, regroupé par pièce.

### E. Endpoint statique pour servir les images (~½ jour)

15. **`GET /datasets/<numista_id>/augmentations/<iid>/<filename>`** dans
    le FastAPI server. Sert le fichier depuis disque.
    - Réutiliser le pattern de `GET /images/<numista_id>/source` qui sert
      déjà des fichiers.
16. Déclencher cache HTTP : `Cache-Control: max-age=86400` (les
    augmentations ne changent pas pour un (numista_id, iteration_id) donné).

## Files à toucher

### Backend
- `ml/state/store.py` — colonne seed, helpers
- `ml/state/schema.sql` — colonne seed
- `ml/api/lab_routes.py` — endpoints regenerate/list/stop, payloads
- `ml/api/iteration_runner.py` — méthode `stop()`, lecture seed à la création
- `ml/training/train_embedder.py` (ou nom équivalent) — signal handler,
  consommation augmentations disque, écriture sample_*.jpg
- `ml/api/server.py` — endpoint statique pour servir augmentations

### Front
- `admin/packages/web/src/features/lab/composables/useLabQueries.ts` — 3
  nouveaux hooks
- `admin/packages/web/src/features/lab/components/RecipeSection.vue` —
  nouveau composant (preview + select recipe)
- `admin/packages/web/src/features/lab/components/AugmentationsGallery.vue` —
  nouveau, grille d'images
- `admin/packages/web/src/features/lab/components/IterationRow.vue` —
  bouton Stop conditionnel
- `admin/packages/web/src/features/lab/pages/CohortDetailPage.vue` —
  intégration §3
- `admin/packages/web/src/features/lab/types.ts` — types augmentations

## Endpoints à ajouter

```
POST   /lab/cohorts/{id}/iterations/{iid}/stop
GET    /lab/cohorts/{id}/iterations/{iid}/augmentations
POST   /lab/cohorts/{id}/iterations/{iid}/augmentations/regenerate
GET    /datasets/{numista_id}/augmentations/{iid}/{filename}   ← static serving
```

## Validation

- [ ] Une iteration créée a un seed persistant
- [ ] Le training utilise le snapshot disque (vérifier en supprimant les
      aug → training plante avec un message clair, pas une régen silencieuse)
- [ ] Stopper un training en cours : passe en `failed` dans les 30s, le
      subprocess Python n'est plus actif (`ps` clean)
- [ ] Refaire le même training (même iteration_id) re-utilise le snapshot
      disque, ne regénère pas
- [ ] La galerie front affiche les samples, par pièce
- [ ] Cache HTTP correct sur les images (test : F5 ne re-télécharge pas)

## Open questions spécifiques

- **OQ-1** : si l'utilisateur change la recipe d'une iteration `pending`,
  les augmentations existantes deviennent invalides. On efface
  automatiquement ou on attend un click "regenerate" explicite ? Reco :
  efface auto au passage de la recipe, mais **uniquement si l'iteration
  est `pending`**. Une iteration `completed|failed` est immutable.
- **OQ-2** : combien de samples on génère par pièce ? Aujourd'hui le
  training utilise N (cf `variant_count` dans la table). Pour la galerie
  preview avant training, 6-9 samples suffit. Pour le snapshot complet
  post-training, on en stocke autant que `variant_count`. Acté ?
- **OQ-3** : le signal handler dans `train_embedder.py` doit-il forcer
  l'écriture d'un benchmark partial même si l'iteration est stoppée tôt ?
  Reco : non. Stop = abandon, l'iteration finit `failed`, pas de R@1 calculé.

## Handoff après le sprint

À la fin, mettre à jour `progress.md` avec :
- ce qui marche end-to-end (iteration → augmentations sur disque → training
  consomme → stoppable)
- décisions OQ-1/2/3 prises
- éventuel code mort à nettoyer (legacy mémoire-only augmentation pipeline)
- pistes pour sprint 2 si découvertes
