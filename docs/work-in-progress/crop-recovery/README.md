# Crop recovery — index du chantier

Récupérer les pièces eBay **sous-croppées** (la détection se rabat sur le motif central
des bimétal → la pièce entière ≈ 2× le rayon détecté ; la **probe va bien**, c'est le crop).
On benche **deux stratégies en parallèle** et on garde la meilleure (ou un hybride).

## Par où commencer
1. **`VISION.md`** — le problème, le diagnostic vérifié, les 2 stratégies, la méthodo.
2. **`BENCHMARK.md`** — le contrat de mesure (D1/D2/D3, interface, critères figés). **À lire.**
3. **`strategy-a-score-guided/`** et **`strategy-b-geometric-rim/`** — un dossier par stratégie
   (`VISION.md` + `PLAN.md` chunké + `SESSION-PROMPT.md`).

## Lancer les deux sessions
Colle dans une nouvelle session Claude Code :
- A → `Lis et exécute docs/work-in-progress/crop-recovery/strategy-a-score-guided/SESSION-PROMPT.md`
- B → `Lis et exécute docs/work-in-progress/crop-recovery/strategy-b-geometric-rim/SESSION-PROMPT.md`

## Le banc (déjà construit — Chunk 0)
- Code : `ml/bench/crop_recovery/` (iface, common, datasets, harness, hybrid).
- CLI : `ml/scripts/run_crop_recovery_bench.py`.
- Jeux matérialisés : `ml/state/crop_recovery/{D1,D2,D3a,D3b}.json`.
- Front : `http://localhost:5173/crop-recovery` (API `go-task ml:api`). Hors nav.

```bash
# (les jeux sont déjà buildés — ne pas rebuild)
.venv/bin/python -m scripts.run_crop_recovery_bench --strategy baseline
.venv/bin/python -m scripts.run_crop_recovery_bench --import bench.crop_recovery.strategy_a --strategy "A:score_search"
.venv/bin/python -m scripts.run_crop_recovery_bench --hybrid state/crop_recovery/run_A_score_search.json,state/crop_recovery/run_B_bimetal_rim.json
```

## Critères figés (BENCHMARK §6)
D2 récup EMU/globe **≥70%** · D3a rétention **≥98%** · D3b faux-accept **≤2%** · D1 IoU médian **≥0,80**.

## Historique / contexte
Diagnostic et faux pas : `../crop-rim-overfit/FINDINGS-session2.md` (conclusion corrigée) +
mémoires `project_crop_rim_overfit`, `feedback_handoff_quality`.
