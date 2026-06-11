# Progress — track harvest

> Append-only. Une entrée par session de travail sur ce track. Pas
> de réécriture rétroactive — si un fait change, on append une
> correction datée.

## 2026-05-02 — Création du track

- Brainstorm meta après test-2 (R@1 strict 57% live sur cohort
  `mix-zone-7-cls`).
- Constat : augmentation seule depuis une photo Numista insuffisante.
- Direction validée : DINOv2 (ou alt foundation) comme **backbone**
  on-device ET **verifier** harvest. Cloud fallback en complément.
  Build alongside l'ArcFace from-scratch actuel, pas de remplacement.
- Cinq sous-docs créés : README, sources, auto-validator, user-
  harvest, human-review, phase-1-dinov2-bring-up.
- Aucune ligne de code écrite. Décisions seulement.
- Prochaine étape : décider quand démarrer phase 1 vs prioriser
  `lab-prod-refacto` phase 1 (label space) qui est aussi bloquant.

## 2026-06-11 — Correction de drift (chemins post-refacto ml/)

- Audit doc↔code : **tout ce que le README liste comme « déjà
  construit » existe bien**, mais les chemins dataient d'avant la
  refacto ml/ (structure plate par domaine). Corrigé dans README +
  phase-1 : `ml/foundation/` → `ml/training/foundation/` (encoder,
  auto_validate, thresholds, claude_review) ; `ml/api/
  review_queue_routes.py` → `ml/review/review_queue_routes.py` ;
  `review_lanes.py` vit dans `ml/review/`.
- Les refs `ml/api/` des sprint-docs et de progress.md (track parent)
  sont des logs historiques — laissées telles quelles.
- Reste-à-faire inchangé : canal A user-harvest in-app (gated app
  Android, proto-first) + exploration Numista API fallback.
