# Auto-accept heuristique — guide opérateur

> Triage déterministe (Dino + texte convergent) de la review queue, sans LLM.
> Livré : 2026-05-24.

## Ce que ça fait

Pour chaque item `status='open'` de `review_queue`, calcule un verdict :

| Verdict | Critère |
|---|---|
| `auto_candidate` | Top1 Dino == target ET sim ≥ 0.55 ET spread ≥ 0.05 ET `vs_target_verdict='convergent'` |
| `partial` | Top1 Dino == target, mais ≥ 1 critère n'atteint pas le seuil |
| `divergent` | Top1 Dino ≠ target OU texte contradictoire |
| `unknown` | Pas de prédiction Dino, ou pas de target connu |

Seuls les `auto_candidate` peuvent être auto-acceptés en un clic. Source de vérité
des seuils : `ml/foundation/thresholds.py` (`DINO_VERDICT_THRESHOLDS`). Logique du
verdict, partagée front/back : `ml/foundation/auto_validate.py` (port exact de
`useAutoValidateVerdict.ts`).

## Lancer un run

1. UI : `/review` → bouton **Auto-accept** → page `/review/auto-accept` →
   sélection granulaire → clic *Accepter N items*.
2. CLI (sans UI) :
   ```bash
   # Dry-run : compte + preview, aucune écriture
   curl -X POST 'http://127.0.0.1:8042/review-queue/auto-accept/run?dry_run=true&limit=5000'

   # Run sur toute la queue
   curl -X POST 'http://127.0.0.1:8042/review-queue/auto-accept/run?dry_run=false&limit=5000'

   # Run sur une sélection
   curl -X POST 'http://127.0.0.1:8042/review-queue/auto-accept/run?dry_run=false' \
        -H 'Content-Type: application/json' \
        -d '{"review_ids":["8ad7f177...","a550315e..."]}'
   ```

## Auditer les décisions

```sql
-- Ce qui a été auto-décidé (par date desc)
SELECT id, decided_eurio_id, decided_face, decision_notes, decided_at
  FROM review_queue
 WHERE decided_by = 'auto_dino'
 ORDER BY decided_at DESC
 LIMIT 50;

-- Volume par jour
SELECT date(decided_at) AS day, count(*) AS n
  FROM review_queue
 WHERE decided_by = 'auto_dino'
 GROUP BY 1 ORDER BY 1 DESC;
```

## Revert (en cas d'erreur de calibration)

Pas de bouton UI dédié — opération admin SQL :

```sql
-- Vue de ce qui sera reverté
SELECT count(*) FROM review_queue WHERE decided_by = 'auto_dino';

-- Revert : remettre la queue en 'open' + l'image en 'needs_review'
BEGIN;
UPDATE image_assets
   SET resolution_status = 'needs_review', eurio_id = NULL,
       face = NULL, resolution_confidence = NULL, resolved_at = NULL
 WHERE id IN (
   SELECT image_asset_id FROM review_queue WHERE decided_by = 'auto_dino'
 );
UPDATE review_queue
   SET status = 'open', decided_eurio_id = NULL, decided_face = NULL,
       decided_variant_kind = NULL, decided_at = NULL,
       decided_by = NULL, decision_notes = NULL
 WHERE decided_by = 'auto_dino';
COMMIT;
```

Pour cibler une fenêtre temporelle uniquement :
`WHERE decided_by = 'auto_dino' AND decided_at >= '2026-05-24'`.

## Calibrer les seuils

Bouger les seuils dans `ml/foundation/thresholds.py` propage automatiquement
au front (via `verdict_thresholds` dans la réponse Dino). Recalibration
recommandée après ~100 décisions humaines récentes : exporter les
auto_candidate récents, comparer la sim/spread distribution des bons vs
mauvais matches, ajuster.

## Limites connues

- **Sous-crop bimétal** : certains crops 2 € ne capturent que la partie dorée
  centrale. Le verdict reste correct (le motif central suffit), mais l'image
  canonique stockée pour training est biaisée. Cf.
  [crop-bimetal-undercrop.md](crop-bimetal-undercrop.md).
- **face=NULL** : quand l'image_asset n'a pas de face détectée, on fallback
  sur `'obverse'`. Si la pièce était un revers, l'attribution est bonne mais
  la face est fausse — détectable en croisant `decided_by='auto_dino'` avec
  `decided_face='obverse'` et inspection visuelle.

## Fichiers

| Couche | Chemin |
|---|---|
| Verdict serveur | `ml/foundation/auto_validate.py` |
| Seuils | `ml/foundation/thresholds.py` |
| Route API | `ml/api/review_queue_routes.py` (`run_auto_accept`) |
| Verdict front | `admin/.../review/composables/useAutoValidateVerdict.ts` |
| Client API | `admin/.../review/composables/useReviewApi.ts` (`runAutoAccept`) |
| Page revue | `admin/.../review/pages/AutoAcceptReviewPage.vue` |
