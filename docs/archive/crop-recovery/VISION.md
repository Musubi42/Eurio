# VISION — Crop recovery (récupérer les pièces sous-croppées)

> Objectif : sur les pièces où la détection **se rabat sur le motif central** (bimétal à
> gros motif : EMU 2009, globe 2012, aigles, etc.), produire un crop qui capte la **pièce
> entière** (rebord externe), pour qu'elle (a) **passe le gate** et (b) soit **bien
> identifiée** en aval. On construit **deux stratégies en parallèle**, on les **benche sur
> le même banc**, on garde la meilleure — ou un **hybride**.
> Créé 2026-06-15 (session 3). Doctrine : **benchmark-first**, probe **gelée**, critères
> de succès **pré-enregistrés**, rien de committé sans accord PO.

## 1. Le problème, en une phrase

Sur run `fa8a9af939ce43e6a3eee6842ecae170` (AT/2009 EMU + AT/2012 globe), **341/562
zero_crops (61%)**. Diagnostic **vérifié sur données réelles** (≠ sessions précédentes) :

- **C'est le CROP, pas la probe.** Les **crops validés-main** (pièces entières) de ces
  designs scorent **médiane 0,87 / passent 86%** sur la probe ACTUELLE → la probe accepte
  ces designs. Ce sont les crops de **prod** (sous-croppés sur le globe) qui scorent ~0,04.
- **La détection se rabat sur le disque interne / motif central.** Balayage de rayon : le
  score monte 0,19→0,76 quand on agrandit ; la **pièce entière ≈ 2,2–2,6× le rayon
  détecté**. YOLO+Hough captent le disque, pas le rebord bimétal externe.
- Corollaire : **pas besoin de ré-entraîner la probe.** Et le fix `bbox-floor` de la
  session 2 est **mort** (il s'ancre sur la bbox elle-même sous-croppée).

Détail du cheminement (et des deux faux pas) : `../crop-rim-overfit/FINDINGS-session2.md`
(conclusion corrigée en tête) + mémoire `project_crop_rim_overfit`.

## 2. Les deux stratégies

| | **A — Crop guidé par le score** | **B — Détection géométrique du rebord** |
|---|---|---|
| Idée | Essayer plusieurs crops (rayons/centres), **garder l'argmax du score** de la probe gelée | Détecter le **rebord externe bimétal** (silhouette pièce / 2 anneaux), pas le disque interne |
| Signal | « sous-croppé ? » = le score de la probe (monte avec la taille jusqu'à la pièce entière) | Géométrie pure (contraste métal/fond, modèle bimétal, `denom_geometry`) |
| Coût | K appels DINO / détection → **enrichment serveur OK**, **scan on-device NON** | Cheap, pas de modèle → marche **aussi on-device (scan)** |
| Risque | sur-crop sur le fond si la probe aime le contexte ; dépend de la probe | rebord externe peu contrasté / fond encombré |
| Dossier | `strategy-a-score-guided/` | `strategy-b-geometric-rim/` |

Elles ne s'excluent pas : l'**hybride** probable = **B partout** (y compris scan) **+ A en
booster côté serveur**. Le banc permet d'évaluer l'hybride **sans re-run** (cf. BENCHMARK).

## 3. Comment on compare (résumé — détail dans `BENCHMARK.md`)

Comparabilité = **non négociable** (c'est ce qui a manqué jusqu'ici). Donc :

1. **Interface commune** : chaque stratégie n'implémente qu'une fonction
   `recrop(raw_bgr, hint) -> [Candidate(cx, cy, r, source)]`. Le **banc partagé** fait le
   reste (crop, score probe gelée, métriques, sortie JSON, front). Aucune des deux sessions
   ne réinvente la mesure.
2. **Trois jeux de données fixes** : D1 *gold géométrie* (crops validés-main = vérité
   terrain du bon cercle), D2 *récupération* (les 341 zero_crops), D3 *non-régression*
   (success + fragments + crop-bench device).
3. **Critères de succès pré-enregistrés** (avant de coder) : récupération D2 ↑, sans casser
   D3, avec un bon IoU sur D1. Départage = coût + applicabilité on-device.
4. **Évaluation hybride offline** : le banc logge **tous** les candidats + scores → on
   calcule a posteriori n'importe quelle politique (A seul, B seul, argmax, B-puis-A…).

## 4. Le front

Une page admin `/crop-recovery` qui charge les JSON du banc et montre : le **tableau
agrégé** (A / B / hybride sur D1·D2·D3) + une **grille par cas** (raw | crop A | crop B |
gold humain | scores | IoU), triable par **désaccord A↔B** (les cas les plus instructifs)
et par récupération. Les deux stratégies alimentent **le même schéma** → **le même front**.

## 5. Découpage & sessions parallèles

- **Chunk 0 (PARTAGÉ, à faire EN PREMIER)** : le **banc** + les 3 jeux + l'interface + le
  schéma de sortie + le front. Tant qu'il n'existe pas, A et B ne sont pas comparables.
  → voir `BENCHMARK.md`. Idéalement construit/validé avant de lancer les 2 sessions.
- **Session A** prend `strategy-a-score-guided/` (VISION + PLAN), implémente `recrop()`,
  lance le banc, écrit ses résultats.
- **Session B** prend `strategy-b-geometric-rim/` (VISION + PLAN), idem.
- **Convergence** : chaque session **output** son JSON de banc + un court `RESULTS.md`
  (ce qu'elle a fait, ses chiffres D1/D2/D3, ses angles morts). On compare via le front +
  l'évaluateur hybride, et on tranche (ou on assemble l'hybride).

## 6. Ce qu'on ne refait pas

- On ne touche **pas** la probe (gelée = oracle, prouvée saine sur ces designs).
- On ne casse pas la garde multi-pièces (`feedback_recrop_multicoin_guard`).
- On réutilise l'outillage session 2 (`measure_crop_undercrop.py`, hook `trace`).
