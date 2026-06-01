# Cohort capture — ablation format crop

> Tracker opérationnel pour la session capture des **340 photos device cohort
> mix-zone-17**, hold-out de l'ablation format crop.
> Pour le contexte stratégique : `docs/roadmap.md` § « Chantier ablation
> format crop ». Pour l'intent métier : memory `project_crop_format_ablation`.

---

## TL;DR

- **Cible** : 17 coins × 5 conditions × 4 photos = **340 captures** (obverse only)
- **Cohorte** : `mix-zone-17` (frozen, AD/AT/BE/ES/FI/FR/IT/DE)
- **App** : main debug build, `captureMode` via DebugBar, déclenche flow guidé
- **Mode protocole** : ABLATION (5 conditions × 4 photos) via directive
  `# mode=ablation` dans le CSV
- **Sortie** : `debug_pull/<ts>/eval_real/{<eurio_id>/<step>_p<n>_*.{jpg,json}, manifest.jsonl}`
- **Temps** : ~1h30 si flow nominal

---

## Progress

- [x] CSV pushé sur device
- [x] App buildée + installée
- [x] Capture démarrée (debugMode → captureMode dans DebugBar)
- [x] Captures atteintes — **337/340** (at-2005 `bright_textured` : skip volontaire après 1 photo)
- [x] `capture:pull` exécuté → `debug_pull/20260601_154135/eval_real/` (réconcilié 337/337, 0 manquant). Device **non cleané** (filet de sécurité).
- [ ] Sweep lancé — **délégué au PC (1080 Ti), stratégie A : screen 12 combos @ 8ep → full-train finalistes @ 20ep ≈ 45h**. Runbook autonome : `docs/operations/crop-ablation-pc-runbook.md`
- [ ] Résultats lus dans `_sweep_results_final.md`

---

## Setup (one-shot avant de shooter)

### 1. Push le CSV

```bash
go-task -t app-android/Taskfile.yml push-capture-csv \
    CSV=ml/state/cohort_csvs/mix-zone-17.csv
```

Le CSV contient la directive `# mode=ablation` en première ligne — l'app
bascule automatiquement en protocole ABLATION (5 conditions × 4 photos)
au prochain lancement.

### 2. Build + install

```bash
go-task android:install   # build + push APK
go-task android:run       # ou install + start
```

### 3. Activer capture mode dans l'app

1. Lance l'app
2. Active **debugMode** (tap sur le titre de l'app je crois — sinon DebugBar
   est visible quand un build debug est utilisé)
3. Dans la DebugBar → bouton **capture mode** (icône caméra+rec)

L'UI passe en mode guidé. Tu vois en haut :

```
PIÈCE 1/17 · STEP 1/5 · PHOTO 1/4
Andorra 2014 standard
→ Lumière jour, fond uni
```

---

## Les 5 conditions à shooter (dans l'ordre)

| # | step_id | Setup |
|---|---|---|
| 1 | `bright_plain` | Lumière jour, fond uni clair (papier blanc, table claire) |
| 2 | `bright_textured` | Lumière jour, fond bois ou tissu visible |
| 3 | `dim` | Intérieur soir, lampe loin (lumière chaude faible) |
| 4 | `oblique` | Caméra inclinée ~30° par rapport à la pièce |
| 5 | `glare_specular` | Lampe directe au-dessus de la pièce, reflet central spéculaire |

Pour chaque pièce, l'app cycle 1→5 automatiquement, 4 photos par step puis
auto-advance au step suivant. Quand step 5 photo 4 est faite, passage à la
pièce suivante.

---

## Pendant la capture

- **Tap "snap"** : prend la photo, l'app sauvegarde + auto-avance dans la
  cellule (photo 1/4 → 2/4 → 3/4 → 4/4 → step suivant)
- **"refaire"** (sur la result layer) : annule la dernière, refais-la
- **"suivant"** : skip la cellule entière (passe au step suivant même si <4 photos)
- Si Hough rate la détection (pas de cercle), l'app affiche
  « ▲ NORMALIZE FAILED » → corrige le cadrage et retape snap (n'avance pas
  tant qu'une normalize valide n'est pas obtenue)

---

## Liste des 17 pièces (mix-zone-17)

| Country | Year | eurio_id |
|---|---|---|
| AD | 2014 | ad-2014-2eur-standard |
| AT | 2002 | at-2002-2eur-standard |
| AT | 2005 | at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty |
| BE | 2007 | be-2007-2eur-standard |
| BE | 2011 | be-2011-2eur-1st-centenary-of-the-international-womens-day |
| DE | 2007 | de-2007-2eur-schwerin-castle-mecklenburg-vorpommern |
| DE | 2020 | de-2020-2eur-50-years-since-the-kniefall-von-warschau |
| ES | 1999 | es-1999-2eur-standard |
| ES | 2016 | es-2016-2eur-old-city-of-segovia-and-its-aqueduct |
| FI | 2016 | fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright |
| FI | 2017 | fi-2017-2eur-100-years-of-independence |
| FR | 1999 | fr-1999-2eur-standard |
| FR | 2008 | fr-2008-2eur-french-presidency-of-the-council-of-the-european-union |
| FR | 2016 | fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand |
| FR | 2018 | fr-2018-2eur-simone-veil |
| IT | 2016 | it-2016-2eur-2200-years-since-the-death-of-plautus |
| IT | 2016 | it-2016-2eur-550-years-since-the-death-of-donatello |

---

## Après la capture — pull + sweep

### Pull

Préfère la task **par catégorie** `capture:pull` (ne ramasse que `eval_real/`,
pas les `photo_snaps/` / `scan_sessions/` jetables — cf.
`docs/operations/debug-data-taxonomy.md`) :

```bash
go-task -t app-android/Taskfile.yml capture:pull
# Output : debug_pull/<timestamp>/eval_real/{manifest.jsonl, <eid>/<step>_p<n>_*.jpg}
# Le device reste intact ; nettoyage explicite via capture:clean (voir ci-dessous).
```

`pull-debug` (ramasse tout `eurio_debug/` en vrac) reste dispo en fallback.

Vérifier que tu as bien ~340 lignes dans `manifest.jsonl` :

```bash
wc -l debug_pull/<ts>/eval_real/manifest.jsonl
```

### Clean (après vérification du pull)

Suppression **device** par catégorie, jamais automatique :

```bash
go-task -t app-android/Taskfile.yml capture:clean   # eval_real/ uniquement
go-task -t app-android/Taskfile.yml photo:clean     # photo_snaps/
go-task -t app-android/Taskfile.yml scan:clean      # scan_sessions/
go-task -t app-android/Taskfile.yml bench:clean     # bench/ (autre racine)
```

Vérification visuelle on-device : `/dev/status` (bottom-sheet debug du scan) montre
le compte + la taille par catégorie et doit afficher la catégorie **vide** après son
clean.

### Sweep ablation (60h GPU 1080 Ti, à piloter en background)

```bash
cd ml
.venv/bin/python -m scripts.sweep_ablation \
    --device-pull ../debug_pull/<ts>/eval_real \
    --sweep-default \
    --class-kind eurio_id
```

Ré-entrant : si interrompu, relance la même commande, il skip les étapes
déjà faites. Pour forcer une re-run, `--force-from {recrop,train,embed,eval}`.

### Lire les résultats

```bash
cat ml/state/ablation_eval/_sweep_results.md
```

Table triée par R@1 décroissant. Le gagnant définit le format final →
Step 4 cutover (Kotlin SnapNormalizer + re-deploy).

---

## Troubleshooting

| Symptôme | Cause probable | Fix |
|---|---|---|
| L'app affiche « STEP 1/6 » au lieu de 1/5 | CSV legacy (sans directive `# mode=ablation`) | Re-push le CSV, force-stop l'app, relance |
| « PHOTO 1/1 » sans incrémenter | Mode LEGACY actif | Idem ci-dessus |
| Beaucoup de « NORMALIZE FAILED » | Pièce mal cadrée, Hough rate | Recule un peu, recentre, refais. Le rim doit être net |
| `manifest.jsonl` n'a que ~100 lignes au lieu de 340 | Tu as tap "suivant" au lieu de continuer à snap | Reprends la session en mode capture : l'app reconstruit le curseur depuis le disque (crops présents + lignes skip), tu repars sur la 1re cellule ni capturée ni skippée. Vérifie sur `/dev/status`. |
| `pull-debug` ne récupère rien | Mauvais device ID adb, ou chemin app changé | `adb devices` ; vérifier path dans `app-android/Taskfile.yml` `DEBUG_DIR_DEVICE` |

---

## Liens

- Roadmap : `docs/roadmap.md` § « Chantier ablation format crop »
- Code capture protocole : `app-android/.../CaptureProtocol.kt`
- Code scan VM : `app-android/.../ScanViewModel.kt`
- Sweep orchestrateur : `ml/scripts/sweep_ablation.py`
- Eval : `ml/scripts/eval_cohort_ablation.py`
- Recrop : `ml/scripts/recrop_with_config.py`
- Memory plan : `project_crop_format_ablation`
- Memory recherche SOTA : `reference_crop_format_research`
