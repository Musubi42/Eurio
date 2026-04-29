# Sprint 2 — Aug ↔ réelles + déprécation `/benchmark`

> Durée estimée : 2 jours
> Pré-requis : Sprint 1 complet (augmentations sur disque accessibles).
>
> **Cold start** : lis `vision.md` (acte 4 pour la valeur de cette
> comparaison), `decisions.md` (D-001, D-006), `filesystem.md`, et le
> sprint 1 progress pour savoir où vivent les augmentations.

## Goal

Donner à l'utilisateur les deux datapoints qui manquent pour comprendre la
qualité d'une recipe :
1. **Visuel** — galerie côte à côte captures réelles | augmentations
2. **Quantitatif** — distance cosine DINO entre centroid des aug et
   centroid des réelles, par pièce

Et retirer `/benchmark` du menu admin (la fonction est intégrée dans
cohort).

## Scope

### Inclus

- Galerie aug↔réelles dans iteration detail (§4)
- Endpoint qui calcule la distance DINO par pièce
- Endpoint qui retourne les paths des captures + samples augmentations
  pour la galerie
- Cache du calcul distance (snapshot persisté DB ou en RAM cleanly invalidé)
- `/benchmark` retiré du menu, route → 301 vers `/lab` ou supprimée

### Exclus

- t-SNE/UMAP (niveau 3 mentionné en brainstorm, plus tard)
- Live tests (sprint 4)
- Cross-cohort dashboard (sprint 5)

## Tasks

### A. Backend : calcul distance DINO (~½ jour)

1. **Helper `compute_aug_vs_real(iteration_id)`** dans
   `ml/api/distance_logic.py` (nouveau fichier) :
   - pour chaque pièce de la cohort :
     - charge les captures réelles (`<numista_id>/captures/*.jpg`)
     - charge les samples d'augmentations (`<numista_id>/augmentations/<iid>/*.jpg`)
     - encode tout via DINO (réutiliser le wrapper existant —
       cf `ml/training/compute_embeddings.py` ou la confusion-map pipeline)
     - calcule centroid réelles, centroid aug
     - cosine = (centroid_real · centroid_aug) / (||r|| · ||a||)
   - retourne `[{eurio_id, num_real, num_aug, cosine, distance: 1-cosine}]`
2. **Cache** : stocker le résultat dans une nouvelle table
   `iteration_aug_vs_real`:
   ```sql
   CREATE TABLE iteration_aug_vs_real (
     iteration_id    TEXT NOT NULL,
     eurio_id        TEXT NOT NULL,
     num_real        INTEGER NOT NULL,
     num_aug         INTEGER NOT NULL,
     cosine          REAL NOT NULL,
     dino_version    TEXT NOT NULL,
     computed_at     TEXT NOT NULL,
     PRIMARY KEY (iteration_id, eurio_id)
   );
   ```
3. Idempotent : si `dino_version` matche le wrapper actuel et que les
   counts sont les bons, retourner le cache. Sinon recompute.

### B. Endpoint exposition (~½ jour)

4. **`GET /lab/cohorts/{cid}/iterations/{iid}/aug-vs-real`** :
   - retourne `{
       per_coin: [...],
       summary: {mean_cosine, min_cosine, max_cosine, num_coins},
       dino_version, computed_at
     }`
   - lazy compute si pas en cache, sinon serve cache.
5. **`POST /lab/cohorts/{cid}/iterations/{iid}/aug-vs-real/recompute`** :
   - force recompute (utile si DINO version change ou si on suspecte un
     stale).

### C. Front : galerie + métriques (~1 jour)

6. **Composable** `useAugVsRealQuery(iterationId)` (Vue Query, cache 1h).
7. **Composant** `AugVsRealSection.vue` (§4 dans iteration detail) :
   - tableau récap : par pièce, num_real / num_aug / cosine (badge
     coloré : vert >0.85, orange 0.7-0.85, rouge <0.7)
   - click sur une ligne → ouvre la galerie de cette pièce :
     - colonne gauche : 6 captures réelles
     - colonne droite : 12 samples d'augmentations
   - bouton "Recompute" déclenche la mutation
8. **Lazy image loading** (`loading="lazy"`) — beaucoup d'images.

### D. Déprécation `/benchmark` (~½ jour)

9. **Front** : retirer la route `/benchmark` du menu (cf `app/router.ts`).
   Garder la page accessible si on tape l'URL pour le moment (read-only),
   mais ajouter un banner "Cette page sera supprimée — passe par cohort".
10. **Doc** : marquer `docs/augmentation-benchmark/` (s'il existe) comme
    legacy. Pas de suppression de fichier dans ce sprint.
11. **Sprint 5** retirera complètement la route et la doc legacy.

## Files à toucher

### Backend
- `ml/api/distance_logic.py` — nouveau, helper DINO distance
- `ml/api/lab_routes.py` — 2 endpoints
- `ml/state/schema.sql` + `store.py` — table + CRUD
- `ml/training/compute_embeddings.py` — exposer si nécessaire un wrapper
  DINO réutilisable

### Front
- `admin/packages/web/src/features/lab/composables/useLabQueries.ts` — 2
  hooks
- `admin/packages/web/src/features/lab/components/AugVsRealSection.vue` —
  nouveau
- `admin/packages/web/src/features/lab/pages/IterationDetailPage.vue` (ou
  CohortDetailPage selon où §4 vit) — intégration
- `admin/packages/web/src/app/router.ts` (ou équivalent) — retirer
  `/benchmark` du menu
- `admin/packages/web/src/features/benchmark/pages/BenchmarkPage.vue` —
  banner deprecation

## Endpoints

```
GET  /lab/cohorts/{cid}/iterations/{iid}/aug-vs-real
POST /lab/cohorts/{cid}/iterations/{iid}/aug-vs-real/recompute
```

## Validation

- [ ] Sur une iteration trainée avec captures + augmentations existantes,
      la galerie affiche les images correctement
- [ ] La distance cosine est plausible (>0.5 généralement, <0.99 sinon il
      y a un bug — les centroids ne sont pas identiques)
- [ ] Recompute change `computed_at` et le résultat (si DINO mis à jour)
- [ ] `/benchmark` plus dans le menu, banner visible si on tape l'URL

## Open questions

- **OQ-1** : DINO version — où est-elle exposée aujourd'hui ? Le wrapper
  `compute_embeddings.py` doit avoir un constant ou un model identifier.
  À tracer pendant ce sprint pour stocker `dino_version` dans le cache.
- **OQ-2** : les centroids sont normalisés L2 avant cosine ? Vérifier la
  convention (ArcFace utilise déjà des normalisés, on suppose pareil pour
  DINO).
- **OQ-3** : poids des conditions dans le centroid ? Aujourd'hui les 6
  captures sont équipondérées. Si on en a 4 bright et 2 dim par exemple,
  le centroid biaise vers bright. Acceptable pour v1, à reconsidérer en
  sprint 5.

## Handoff

Mettre à jour `progress.md` avec :
- la version DINO trackée
- des exemples de cosines observés (sanity check)
- éventuelles découvertes sur la qualité des recipes existantes
