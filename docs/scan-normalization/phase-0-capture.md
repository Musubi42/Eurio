# Phase 0 — Capture vérité-terrain

> But : produire un golden set de snaps réels pris au téléphone, qui servira à (a) caler la spec de normalisation Phase 1 et (b) benchmarker chaque run d'entraînement avec une métrique device-grade.

## Approche

Mode `capture` ajouté à l'overlay debug du scan (gated par `debugMode = true`). L'utilisateur :

1. Active `capture` dans la barre d'outils debug.
2. L'écran affiche : `Coin X/4 — <eurio_id> — Step Y/6 : <consigne>`.
3. L'utilisateur place la pièce selon la consigne, tape `snap`.
4. Le snap est écrit dans une session dédiée + métadonnée enrichie.
5. La VM avance automatiquement au step suivant (puis à la pièce suivante).
6. Fin de session = écran « capture complete ».

## Pièces (4)

1. `ad-2014-2eur-standard`
2. `de-2007-2eur-schwerin-castle-mecklenburg-vorpommern`
3. `de-2020-2eur-50-years-since-the-kniefall-von-warschau`
4. `fr-2007-2eur-standard`

## Steps par pièce (6)

Couvrent la variabilité device qu'on veut robustifier — éclairage, fond, échelle, angle.

| # | step_id | Consigne |
|---|---|---|
| 1 | `bright_plain` | Intérieur lumineux, fond uni clair (table blanche / bois clair), centré |
| 2 | `dim_plain` | Intérieur tamisé / lumière jaune, fond uni, centré |
| 3 | `daylight_plain` | Proche fenêtre ou plein jour, fond uni, centré |
| 4 | `bright_textured` | Intérieur lumineux, fond texturé (tissu, bois marqué, papier kraft), centré |
| 5 | `tilt_plain` | Pièce légèrement inclinée (~10°), fond uni, centré |
| 6 | `close_plain` | Pièce remplit le mask au maximum (distance proche), fond uni |

Total : **24 snaps** (4 × 6).

## Output

Chaque snap écrit sous le `debugRootDir` Android :

```
<debugRootDir>/eval_real/
  manifest.json                            # session-level index
  <eurio_id>/
    <step_id>_raw.jpg                      # frame caméra brute
    <step_id>_crop.jpg                     # output du mask circulaire (état actuel snap)
    <step_id>.json                         # meta : ts, frame_size, crop_size, eurio_id, step_id, label
```

Récup côté PC via `go-task android:pull-debug` (existant, le sous-dossier `eval_real/` est inclus).

## Métadonnée par snap

```json
{
  "ts": "20260427_173241_812",
  "eurio_id": "de-2020-2eur-50-years-since-the-kniefall-von-warschau",
  "step_id": "bright_plain",
  "step_label": "Intérieur lumineux, fond uni clair",
  "step_index": 0,
  "frame_size": [480, 640],
  "crop_size": 336
}
```

## Critères de fin

- 4 × 6 = 24 fichiers `<step_id>_raw.jpg` + `<step_id>_crop.jpg` + `<step_id>.json` présents.
- `manifest.json` listant les 24 entrées avec leurs paths relatifs.
- Snaps inspectés visuellement : la pièce est bien centrée dans le mask sur chaque snap (re-prendre sinon).

## Scope hors Phase 0

- Pas de modification du pipeline ML existant.
- Pas de normalisation appliquée ici — on stocke `crop.jpg` (output mask actuel) pour servir d'input à `normalize_snap.py` (Phase 1).
- L'inférence ArcFace continue de tourner en arrière-plan sur chaque snap (pour debug), mais ses résultats ne sont pas utilisés par le mode capture.
