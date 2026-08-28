# Le protocole du banc

## Ce qu'on reprend de `crop-recovery`, et ce qu'on jette

`docs/archive/crop-recovery/BENCHMARK.md` avait **raison sur la forme et tort
sur le fond**.

**À reprendre tel quel :**

- **L'interface commune** `recrop(raw_bgr, hint) -> list[Candidate]` : un seul
  point d'entrée, **le banc seul mesure**. « Aucune des deux stratégies ne
  duplique la mesure » — la phrase clé, et elle a tenu.
- **Les candidats multiples loggés pour tous les bras** → permet d'évaluer une
  politique hybride *post-hoc, sans re-run*.
- **Le baseline loggé dans chaque cas**, ce qui rend le lift lisible sans
  comparaison croisée.
- **Les critères pré-enregistrés, datés et validés PO avant de coder.** Le geste
  était bon.

**À jeter :**

- **L'oracle** : « probe fragment GELÉE, τ=0,55 ». Un score continu calculé sur
  la sortie de la méthode. **Geler ≠ non-optimisable** — geler ne fait que fixer
  la cible que l'optimiseur va viser.
- **Le critère `IoU médian ≥ 0,80`** : tolère 10,6 % d'amputation (cf.
  [`JUGE.md`](./JUGE.md)).
- **La tendance centrale comme critère primaire** : une médiane cache les
  catastrophes par construction.

## Les bras

| bras | ce qu'il est | pourquoi il est là |
|---|---|---|
| `baseline_prod` | le `bbox_json` actuel, tel qu'en base | **le seul chiffre qui compte.** Une méthode qui ne le bat pas ne se déploie pas |
| `gold_replay` | `E_gold` elle-même passée dans `_crop_mask_resize_float` | le **plafond mécanique** : ce que le format perd même avec une géométrie parfaite. Sans lui on attribue à la méthode un défaut du format |
| `human_2nd_pass` | la 2ᵉ annotation des 10 images doublées | le **plancher de bruit** |
| `measure_tilt_ellipse` | `fitEllipseAMS` déjà écrit dans `crop_detectors.py` | le naïf gratuit |
| `M1…Mn` | les méthodes candidates | — |

**Les trois premiers ne sont pas des candidats, ce sont des bornes.** Un tableau
sans bornes est illisible.

## La sortie — un JSON par bras

```json
{ "arm": "baseline_prod", "gold_version": "v1", "gold_sha256": "…",
  "judge_version": 1, "m": 0.02, "d_frac": 0.08, "arc_min": 0.9167,
  "cases": [
    { "asset_id": "…", "strate": "S4_oblique", "strate_confirmee": "S4_oblique",
      "verdict_humain": "reject",
      "gold": {"cx":…, "cy":…, "a":…, "b":…, "theta":…},
      "pred": {"cx":…, "cy":…, "r":…},
      "C1_marge_min_frac": -0.031, "C1_ok": false,
      "C2_arc_coverage": 0.833,   "C2_ok": false,
      "boundary_iou": 0.14, "mask_iou": 0.88, "hausdorff_frac": 0.061,
      "ampute": true } ] }
```

Artefacts dans `ml/state/gold_crop/`, code dans `ml/bench/gold_crop/` — à côté de
`ml/bench/crop_recovery/`, dont il **réutilise le harness**. On n'en écrit pas un
deuxième.

✅ **Écrit le 2026-08-28.** `judge.py` · `geometry.py` · `iface.py` ·
`datasets.py` · `bras.py` · `harness.py`.

```bash
cd ml && python -m bench.gold_crop.harness --out state/gold_crop/v1
# bras par défaut : human_2nd_pass · gold_replay · baseline_prod · measure_tilt_ellipse
# --region-c1 {retenu,cadre,disque}   (D9)   --c2-compte   (D8)
```

**RE-2 n'est pas une consigne, c'est une frontière de type.** Un bras candidat
reçoit un `ContexteCandidat` qui **ne porte pas l'or** ; seules les bornes
reçoivent un `ContexteBorne`. Un contrôle syntaxique (`controler_re2`) refuse en
plus tout bras candidat qui importerait le juge ou citerait `gold.json` —
`executer` lève avant de lancer quoi que ce soit. **RE-5** (le `sha256` de l'or
dans chaque run) et **RE-7** (`departage` refuse de classer sous 5 points) sont
exécutables et testés.

⚠️ Deux constats du juge attendent le PO avant la première exécution réelle :
**C2 est inerte** ([`DECISIONS.md` §D8](./DECISIONS.md)) et **la région de C1
n'est pas tranchée** ([§D9](./DECISIONS.md)) — sous la lettre actuelle, le
plafond `gold_replay` est à 100 % d'amputation.

## Le tableau

`amputation_rate` en **première colonne** :

| bras | **amput. %** | amp C1 | amp C2 | BIoU méd. | **BIoU p10** | IoU masque méd. | Haus. p90 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `human_2nd_pass` | *plancher* | | | | | | |
| `gold_replay` | *plafond* | | | | | | |
| `baseline_prod` | | | | | | | |
| `measure_tilt_ellipse` | | | | | | | |
| `M1` | | | | | | | |

Plus **le même tableau ventilé par strate**. Une méthode qui gagne globalement en
perdant sur S4 n'a pas gagné, elle a suivi la distribution.

Et **`BIoU p10`, pas seulement la médiane** : le décile bas contient les crops que
l'humain jette. **Une médiane qui monte pendant qu'un p10 descend est la signature
d'un optimiseur qui triche.**

## La règle d'engagement

À valider par le PO **avant la première exécution**.

> **RE-1 — Pré-enregistrement.** Les seuils (`m = 0,02`, `d = 0,08·a`,
> `arc ≥ 11/12`) et les critères de succès sont figés et signés **avant** que le
> premier bras candidat ne soit exécuté. Un desserrage ultérieur exige une entrée
> datée dans `DECISIONS.md` **et** une ré-exécution de **tous** les bras — pas
> seulement de celui qui échouait.
>
> **RE-2 — Séparation juge / méthode.** Aucune méthode candidate ne peut lire
> `gold.json`, ni importer le module du juge, ni recevoir C1/C2 comme fonction
> objectif. Le juge n'est appelé que par le harness, après coup. Une méthode qui
> optimise directement `arc_coverage` sur sa propre sortie est **disqualifiée**,
> quelle que soit sa performance — c'est la définition de l'auto-oracle.
>
> **RE-3 — Pas d'oracle maison.** Un chantier qui a besoin d'une grandeur que le
> juge ne fournit pas ne l'ajoute pas de son côté : il propose un **amendement au
> juge**, qui repasse par RE-1 et ré-exécute tous les bras. Sept chantiers ont
> défini leur propre oracle ; sept chantiers ont échoué.
>
> **RE-4 — Falsifier le juge d'abord.** Avant tout classement, publier la
> corrélation entre `amputation_rate(baseline_prod)` et le verdict humain sur les
> 60. **Si le juge ne sépare pas les 32 acceptés des 28 rejetés, le juge est faux
> et le banc s'arrête là.** *(Test de référence : `quality_score` y échoue à
> 0,0008 près.)*
>
> **RE-5 — L'or est un artefact de données.** `gold.json` vit sur MinIO,
> versionné `v1`, `v2`… ; le dépôt ne porte que le `sha256` et la requête. Un or
> modifié = une nouvelle version = tous les bras ré-exécutés. **Aucune annotation
> n'est corrigée « au passage ».**
>
> **RE-6 — Aucun déploiement sur une médiane.** Le seul critère est
> `amputation_rate < amputation_rate(baseline_prod)` **sur les 4 strates**, avec
> `BIoU p10` non régressé. Une amélioration moyenne ne suffit pas.
>
> **RE-7 — 60 n'est pas beaucoup.** Un écart de moins de ~5 points de taux
> d'amputation (≈ 3 images sur 60) **n'est pas un départage**. Le dire dans le
> tableau plutôt que de classer. Un second tirage
> (`substr(si.sha256 || ia.id, -16, 8)`) est disponible — et il ne s'annote
> qu'**après** le premier verdict, jamais avant.
