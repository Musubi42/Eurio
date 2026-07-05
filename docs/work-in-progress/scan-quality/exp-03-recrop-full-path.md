# exp-03-recrop-full-path — crop device vs re-crop Python (chemin full)

> Exploite les deux axes de rejouabilité du corpus (spec §2) : les mêmes 73
> frames rejouées en `fast` (crop device archivé) et en `full`
> (raw → `vision.normalize_snap.normalize_device`, port bit-for-bit de
> `SnapNormalizer.kt` → crop → embed). **État : terminée (2026-07-06),
> verdict EXPLORATOIRE** (confondants connus, §5).

## 1. Hypothèse

Le maillon crop/normalisation device laisse des points sur la table : re-cropper
la même frame côté PC change le score.

## 2. Variable unique

Chemin de replay `fast` → `full`. Centroïdes/modèle/corpus fixes (mesuré pour
train_mean ET val_mean).

## 3. Résultat (corpus `9b1bc705525d`, n=73, 0 échec Hough)

| R@1 eq | fast (crop device) | full (re-crop PC) | Δ |
|---|---|---|---|
| val_mean | 0.6849 | 0.6986 | +1.4 pts |
| **train_mean** | 0.7671 | **0.8082** | **+4.1 pts** |
| train_mean vs val_mean en full | | +11.0 pts, McNemar p=0.057 (11/3) | |

Par condition (train_mean full vs fast) : dim 0.71 vs 0.61, bright 0.95 vs
0.90, tilt 0.82 vs 0.86. Sortie : `ml/state/scan_corpus_runs/exp-01-full/`.

## 4. Décision

| Étage | Verdict |
|---|---|
| **S0** | 🟡 exploratoire — signal réel mais **confondu** (§5) ; ouvre une piste crop, ne la tranche pas |

## 5. Verdict écrit — et pourquoi on ne conclut PAS encore

Le re-crop PC gagne sur les deux jeux de centroïdes (jusqu'à +4.1 pts), ce qui
pointe vers une divergence crop device↔PC qui compte. **Mais ce corpus est un
backfill** : (a) le crop `fast` a subi un transcodage JPEG q95→PNG (perte JPEG
amont actée en `notes`), (b) la raw rejouée en `full` est le debug `raw.jpg`
q90 — deux artefacts absents du corpus natif Lot 2 (crop PNG lossless au SNAP,
raw q95). Le delta observé peut mélanger « meilleur crop » et « moins de
JPEG ». **Action** : re-mesurer fast vs full sur le prochain corpus natif ;
si l'écart persiste, ouvrir une exp dédiée géométrie de crop (lien avec la
mémoire bimetal harden / sous-crop 2€).
