# PROMPT — Session « Stratégie A : crop guidé par le score »

> À coller dans une nouvelle session Claude Code (repo Eurio). Auto-suffisant.

Tu travailles le **chantier crop-recovery** (récupérer les pièces eBay sous-croppées).
**Lis d'abord, dans l'ordre** :
1. `docs/work-in-progress/crop-recovery/VISION.md` (le problème + le diagnostic VÉRIFIÉ)
2. `docs/work-in-progress/crop-recovery/BENCHMARK.md` (le contrat de mesure — non négociable)
3. `docs/work-in-progress/crop-recovery/strategy-a-score-guided/VISION.md` + `PLAN.md`

**Diagnostic déjà établi (ne pas re-débattre, c'est mesuré)** : sur run
`fa8a9af939ce43e6a3eee6842ecae170` (EMU 2009 / globe 2012), la détection se rabat sur le
**disque interne** ; la pièce entière ≈ **2× le rayon détecté**. La **probe va bien** (crops
validés-main → 0,87). Le **score de la probe monte avec la taille du crop** jusqu'à la pièce
entière → c'est ton signal.

**Ta mission** : implémenter la stratégie A = **chercher le crop qui maximise le score de la
probe gelée**, autour de la détection.

**Le banc est déjà construit (par la session de cadrage).** Tu n'écris QUE `recrop()` :
- Crée `ml/bench/crop_recovery/strategy_a.py` avec :
  ```python
  from .iface import Candidate, register
  @register("A:score_search")
  def recrop(raw_bgr, hint):   # hint = {cx, cy, r_final, r_bbox, short}
      # retourne une liste de Candidate(cx, cy, r, source="A:...") ; le harness
      # crope+score chaque candidat (probe gelée) et garde l'argmax. Retourne
      # PLUSIEURS candidats (permet l'hybride). NE PAS appeler la probe toi-même
      # pour décider — tu peux la lire via bench.crop_recovery.common.score_crops si
      # tu fais une recherche coarse-to-fine interne, mais loggue tes candidats.
  ```
- Détails/pièges (sur-crop fond, centre faux, lots, coût K) : voir `VISION.md` + `PLAN.md`.

**Commandes** (depuis `ml/`, venv) :
```bash
# les jeux D1/D2/D3 sont déjà dans state/crop_recovery/ (NE PAS rebuild)
.venv/bin/python -m scripts.run_crop_recovery_bench --import bench.crop_recovery.strategy_a --strategy "A:score_search"
# front pour analyser : go-task ml:api  +  http://localhost:5173/crop-recovery
```

**Critères à atteindre (pré-enregistrés, BENCHMARK §6)** : D2 EMU/globe **≥70%**,
rétention D3a **≥98%**, faux-accept D3b **≤2%**, D1 IoU médian **≥0,80**.

**Livrable** : `strategy-a-score-guided/RESULTS.md` (chiffres D1/D2/D3, K retenu, gardes,
angles morts, cas de désaccord) + le JSON `state/crop_recovery/run_A_score_search.json`.

**Garde-fous** : ne touche PAS la probe (gelée = oracle). Ne casse pas la garde
multi-pièces (`feedback_recrop_multicoin_guard`). Benchmark-first, chunk par chunk (PLAN.md),
**ne committe pas** sans accord PO. Si un fait du diagnostic te paraît faux, **vérifie sur
données réelles** (crops validés-main, images) avant de conclure — c'est comme ça qu'on a
trouvé la vérité (cf. `feedback_handoff_quality`).
