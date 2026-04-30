# Training pipeline — Guide utilisateur

> Tutorial concret : tu veux entraîner un nouveau modèle Eurio, voici la
> route A → Z. Les concepts sont dans `vision.md` ; ici on enchaîne les
> commandes et les clics dans l'ordre.
>
> Ce guide assume que tu es à la racine du repo Eurio, que `ml/.venv`
> existe, que `app-android/keys/debug.keystore` est présent (versionné),
> et que l'API ML tourne (`go-task ml:api` dans un terminal séparé).

## Vue d'ensemble — les 3 numéros qui comptent

À la fin du flow, une iteration "validée" a :

- **R@1 studio ≥ 0.85** — entraîné sur augmentations, évalué sur 6 photos
  device par pièce. Indicateur de capacité brute du modèle.
- **R@1 live ≥ 0.70** — pièce scannée *via l'app cohortTest* dans des
  conditions prescrites. Indicateur de généralisation au monde réel.
- **Cosine aug ↔ réel ∈ [0.70, 0.95]** — au-dessus de 0.95 la recipe est
  trop conservatrice (pas de variabilité réelle), en-dessous de 0.70 elle
  s'éloigne tellement des photos device que le training est biaisé.

Si les 3 sont au vert, l'iteration peut servir de baseline pour la
suivante. Si l'un des 3 décroche, c'est l'enquête qui démarre.

---

## Étape 1 — Créer la cohort

Une cohort = ensemble figé de 3 à 10 eurio_ids qui partagent un défi.
Exemples : "5 pièces vert (faciles)", "3 pièces rouge similaires (Allemands
2007 commémo)".

1. Ouvre `/lab` dans l'admin web.
2. Clique **« Nouveau cohort »** (en haut à droite).
3. Nomme-la en kebab-case (`green-v1`, `red-similar-de-2007`).
4. Choisis une zone (`green` / `orange` / `red`) — facultatif mais utile
   pour la sensibilité par zone plus tard.
5. Sélectionne les eurio_ids depuis le picker.
6. Valide.

La cohort est en status `draft` tant qu'aucune iteration n'a tourné.
Tu peux ajouter / retirer des coins à `draft`. Dès la 1ère iteration
elle bascule en `frozen` automatiquement.

> **Gotcha** : si tu te trompes de coins après freeze, clique
> **« Cloner »** depuis la page cohort — ça crée une nouvelle cohort en
> draft avec les mêmes coins, modifiable.

## Étape 2 — Capturer les photos device pour chaque pièce

Le bench studio + le calcul de la distance aug↔réel ont besoin de 6
photos device par pièce, 1 par condition (`bright_plain`, `dim_plain`,
`daylight_plain`, `bright_textured`, `tilt_plain`, `close_plain`).

1. Sur la page cohort, va dans **§2 Captures**.
2. Clique **« Générer CSV »** — copie la commande générée.
3. Lance l'app prod sur le device, autorise CAMERA si demandé.
4. Push le CSV : `go-task -t app-android/Taskfile.yml push-capture-csv
   CSV=ml/state/cohort_csvs/<slug>.csv`.
5. Relance l'app sur le device, fais les 6 snaps prescrits par pièce.
6. De retour sur le poste : clique **« Pull + sync »** dans la §2 — ça
   pull les images et les normalise sous `ml/datasets/<numista_id>/captures/`.

Le panneau §2 affiche la matrice par pièce / condition. Tant qu'une case
manque, l'iteration ne pourra pas calculer le R@1 par axe.

## Étape 3 — Choisir / créer une recipe d'augmentation

Une recipe = liste de couches (`perspective`, `overlay_texture`,
`relighting`, etc.) avec leurs paramètres. Voir
`docs/augmentation-benchmark/01-backend-pipeline.md` pour le schéma.

Sur la page cohort, **§3 Recipe** :
1. Sélectionne une recipe existante (filtrée par zone du cohort).
2. Choisis un `variant_count` (≈ 100 pour un training réel, 9 pour preview).
3. Clique **« Prévisualiser »** — bake les augmentations pour cette
   recipe + seed et affiche la galerie. Itère jusqu'à ce que la galerie
   te paraisse plausible.

> **Gotcha** : le preview crée une iteration `pending` nommée
> `preview-<recipe>`. Elle reste là tant que tu ne lances pas un vrai
> training — pas grave. Sprint 5 gère le GC manuel via les boutons
> "Purger" sur chaque iteration detail.

## Étape 4 — Lancer une iteration (training + benchmark)

1. Sur la page cohort, **« Nouvelle itération »** (haut à droite).
2. Donne-lui un nom (`baseline`, `with-patina`, `more-tilt`).
3. Recipe : la recipe choisie à l'étape 3.
4. Variant count : ce que tu veux (100-300 typiques).
5. Parent iteration : la baseline si tu veux un delta automatique.
6. Hypothèse : phrase courte (`"plus de patina devrait aider sur les
   pièces sales"`) — elle apparaîtra à côté du verdict.
7. Clique **« Lancer »**.

L'iteration enchaîne :
- bake des augmentations sur disque
- training arcface (~10-30 min sur M4 selon la cohort)
- export TFLite auto (Sprint 4 : auto-hooké post-training)
- benchmark sur photos device → R@1 studio + per-zone + per-condition
- verdict (`better` / `worse` / `mixed` / `no_change` / `baseline`)

Tu peux suivre l'avancée dans la page iteration detail (poll 4s pendant
training/benchmarking). En cas de problème, clique **« Stop »** dans la
table d'iterations — SIGTERM coopératif, l'iteration finit son epoch et
sort proprement.

## Étape 5 — Inspecter le résultat studio

Sur la page iteration detail :

- **§1 Sommaire** : R@1 / R@3 / R@5 + delta vs parent.
- **Per-zone** : R@1 par zone (vert / orange / rouge).
- **Per-condition** : R@1 par axe de variabilité (lighting, angle, etc.).
- **§3 Augmentations** : galerie post-training, 12 samples par pièce.
- **§4 Aug ↔ réelles** : cosine DINO global + par pièce, galerie
  side-by-side captures vs aug.

> **Reading the cosine** : 0.95+ = recipe trop proche des captures (peu
> d'aug réelle), 0.85-0.95 = saine, 0.70-0.85 = recipe agressive (à
> vérifier que le R@1 ne s'écroule pas), <0.70 = augmentations trop
> bizarres.

Si R@1 studio ≥ 0.85 et le verdict te plaît, passe à l'étape 6.
Sinon : itère sur la recipe, change `variant_count`, ou retire des
coins du cohort qui dégradent (clone + retire).

## Étape 6 — Builder l'APK cohortTest

Sur la page iteration detail, **§5 Test app** :

1. Vérifie que **« Modèle prêt »** est en vert.
2. Copie la commande (bouton **« Copier »**).
3. Colle dans un terminal :
   ```
   go-task -t app-android/Taskfile.yml cohort-test:install \
     COHORT=<name> ITERATION=<iid>
   ```
4. La commande bundle (model.tflite filtré + catalog filtré +
   live_tests_manifest), build, et installe l'APK `Eurio Test` sur le
   device. Cohabite avec l'app prod (applicationId
   `com.musubi.eurio.cohorttest`).

> **Gotcha** : si tu vois "TFLite stale" en CLI, c'est que le runner
> n'a pas re-exporté. Lance manuellement :
> `cd ml && .venv/bin/python -m training.export_tflite`

## Étape 7 — Faire les live tests sur device

1. Ouvre **« Eurio Test »** sur le device. Tu vois "Test 1/N : … · bright".
2. Pose la pièce attendue dans les conditions prescrites
   (`bright`/`dim`/`tilt`).
3. Snap. Le top-3 s'affiche, badge ✓/✗ comparé à l'expected.
4. Clique **« Test suivant → »**. Continue.
5. Si tu kill l'app et relances, elle reprend au test où tu en étais.
6. Quand les N tests sont faits, tu vois "Tests terminés".

Les résultats sont écrits localement en JSONL :
`/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iid>.jsonl`

## Étape 8 — Sync les live tests vers l'admin

```
go-task -t app-android/Taskfile.yml cohort-test:pull-tests ITERATION=<iid>
```

Ça pull le JSONL et le POST sur `/lab/.../live-tests/sync`. La page
iteration detail §6 affiche maintenant :

- la matrix `eurio_id × condition` avec ✓/✗
- R@1 live global + delta studio↔live
- les rows en erreur (NORMALIZE FAILED, etc.)

> **Reading the delta** : si studio R@1 = 0.92 et live R@1 = 0.45, ta
> recipe overfit la distribution studio. Direction : recipe plus
> agressive (overlays patina, tilt, lighting variable).

## Étape 9 — Itérer

Selon ce que tu vois :

- **Live R@1 OK et stable** : passe à une cohort plus difficile.
- **Live R@1 décroche sur certaines pièces** : regarde la matrix par
  condition. Si toujours en `tilt`, ajoute du tilt à la recipe.
- **Live R@1 décroche sur 1 pièce** : c'est peut-être un coin
  intrinsèquement difficile. Va sur `/lab` → §Dashboard → "Pièces
  difficiles" — si elle revient sur ≥3 iterations, envisage de la sortir
  du cohort principal et d'en faire son propre cohort.

Pour itérer : retourne à l'étape 4 avec une nouvelle iteration, en
mettant l'iteration courante comme `parent_iteration_id` pour avoir le
delta automatique.

## Étape 10 — Garbage collect

Quand tu as ≥5 iterations sur une cohort dont 2+ failed, un banner
apparaît sur la page cohort. Action :

1. Va sur l'iteration failed.
2. Clique **« Purger »** dans §3 Augmentations → libère
   `ml/datasets/<nid>/augmentations/<iid>/`.
3. Si tu avais bundlé l'APK, clique **« Purger bundle »** dans §5 →
   libère `ml/output/cohort_test_<iid>/`.

L'iteration row reste consultable, juste les artefacts disque sont
effacés. Pas de cascade DELETE — l'historique reste.

---

## Troubleshooting

| Symptôme | Cause probable | Fix |
|---|---|---|
| Iteration en `failed` immédiatement | Augmentations skipped (no source for a coin) | §2 Captures incomplet — capture la pièce manquante avant de relancer. |
| `TFLite stale` au build cohortTest | Auto-export TFLite a raté (venv cassé) | `cd ml && .venv/bin/python -m training.export_tflite` puis re-bundle. |
| App `Eurio Test` crash au launch | Bundle absent dans assets | Re-run `go-task -t app-android/Taskfile.yml cohort-test:install`. |
| Snap → "NORMALIZE FAILED" en boucle | OpenCV pas init / pièce hors cadre | Vérifier que la pièce est centrée dans le viewfinder, lighting correct. Logs : `go-task android:logs`. |
| §6 Live tests ne montre rien après pull-tests | Sync n'a pas hit l'API | Vérifier que `go-task ml:api` tourne, refresh la page. |
| Cosine aug↔réel = NaN | DINO pas chargé / captures vides | Cliquer **« Recompute »** dans §4. Vérifier que les captures sont bien sous `ml/datasets/<nid>/captures/`. |
| `vue-tsc` erreurs dans audit/sets | Pré-existantes, hors training-pipeline | Ignore-les pour ce flow. |

---

## Check-list "iteration validée"

Avant de claim qu'une iteration est bonne pour la prod ou comme
baseline d'un cohort plus large :

- [ ] Status `completed`, verdict ≠ `worse`
- [ ] R@1 studio ≥ 0.85 (ou ≥ baseline + 2pp si pas de cible absolue)
- [ ] R@1 live ≥ 0.70
- [ ] Delta studio↔live ≤ 20pp (sinon recipe overfit)
- [ ] Cosine aug↔réel moyen ∈ [0.70, 0.95]
- [ ] Aucune pièce du cohort en "Pièces difficiles" sur la 3ème iteration
      consécutive
- [ ] Notes remplies (au moins l'hypothèse vérifiée + le takeaway)

Si tout est vert, l'iteration peut servir de `parent_iteration_id` pour
la suivante. Si le cohort entier passe, envisage de cloner pour étendre
(ajouter des coins, augmenter la difficulté).

---

## Pour aller plus loin

- `vision.md` — pourquoi ce flow existe, ce qu'il remplace.
- `decisions.md` — toutes les décisions D-001 à D-014 et leurs justifs.
- `glossary.md` — distinguer "App full" vs "App cohortTest", "studio" vs
  "live", etc.
- `progress.md` — historique sprint par sprint, ce qui a été touché
  quand. Lis-le quand tu reprends après une pause.
