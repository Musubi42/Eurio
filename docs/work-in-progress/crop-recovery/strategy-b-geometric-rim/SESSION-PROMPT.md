# PROMPT — Session « Stratégie B : détection géométrique du rebord externe »

> À coller dans une nouvelle session Claude Code (repo Eurio). Auto-suffisant.

Tu travailles le **chantier crop-recovery** (récupérer les pièces eBay sous-croppées).
**Lis d'abord, dans l'ordre** :
1. `docs/work-in-progress/crop-recovery/VISION.md` (le problème + le diagnostic VÉRIFIÉ)
2. `docs/work-in-progress/crop-recovery/BENCHMARK.md` (le contrat de mesure — non négociable)
3. `docs/work-in-progress/crop-recovery/strategy-b-geometric-rim/VISION.md` + `PLAN.md`

**Diagnostic déjà établi (ne pas re-débattre, c'est mesuré)** : sur run
`fa8a9af939ce43e6a3eee6842ecae170` (EMU 2009 / globe 2012, bimétal à gros motif central), la
détection (YOLO + cercles) accroche le **disque interne** au lieu du **rebord externe** ; la
pièce entière ≈ **2× le rayon détecté**. La probe va bien — c'est le crop.

**Ta mission** : implémenter la stratégie B = **détecter géométriquement le rebord EXTERNE**
de la pièce (silhouette métal/fond, modèle bimétal 2-anneaux `vision/denom_geometry.py`,
Hough plus-grand-cercle-centré durci), **sans appeler la probe** (c'est l'intérêt : ça
tournera aussi on-device).

**Le banc est déjà construit.** Tu n'écris QUE `recrop()` :
- Commence par **Chunk B0** : comprendre POURQUOI `detect_bbox_refine`
  (`vision/crop_detectors.py`) ne récupère pas le rebord ici (contour noyé ? Hough ne voit
  pas le rebord externe peu contrasté ? plancher/plafond ?). Visualise des cas EMU/globe.
- Puis crée `ml/bench/crop_recovery/strategy_b.py` :
  ```python
  from .iface import Candidate, register
  @register("B:bimetal_rim")
  def recrop(raw_bgr, hint):   # hint = {cx, cy, r_final, r_bbox, short}
      # détecte le cercle EXTERNE (concentrique au hint, plancher r >= r_final,
      # plafond voisin-aware). Retourne un (ou +) Candidate(cx, cy, r, source="B:...").
      # Fallback = garder le hint si pas de rebord franc (le banc le verra).
  ```
- Détails/pistes/pièges (fond encombré, capsule, non-bimétal, lots) : voir `VISION.md`+`PLAN.md`.

**Commandes** (depuis `ml/`, venv) :
```bash
# les jeux D1/D2/D3 sont déjà dans state/crop_recovery/ (NE PAS rebuild)
.venv/bin/python -m scripts.run_crop_recovery_bench --import bench.crop_recovery.strategy_b --strategy "B:bimetal_rim"
# front pour analyser : go-task ml:api  +  http://localhost:5173/crop-recovery
```

**Critères à atteindre (pré-enregistrés, BENCHMARK §6)** : D2 EMU/globe **≥70%**,
rétention D3a **≥98%**, faux-accept D3b **≤2%**, D1 IoU médian **≥0,80**. Note : B vise un
**IoU élevé sur D1** (match géométrique au crop humain) — c'est son avantage attendu vs A.

**Livrable** : `strategy-b-geometric-rim/RESULTS.md` (chiffres D1/D2/D3, piste(s) retenue(s),
taux de fallback hint-gardé, angles morts) + le JSON `state/crop_recovery/run_B_bimetal_rim.json`.

**Garde-fous** : ne touche PAS la probe. Ne casse pas la garde multi-pièces
(`feedback_recrop_multicoin_guard`). Réutilise `denom_geometry` / `crop_detectors` plutôt
que réécrire. Benchmark-first, chunk par chunk (PLAN.md), **ne committe pas** sans accord PO.
Vérifie tout fait douteux sur **données réelles** avant de conclure (cf.
`feedback_handoff_quality`).
