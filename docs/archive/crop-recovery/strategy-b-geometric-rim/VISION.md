# Stratégie B — Détection géométrique du rebord externe (bimétal-aware)

> Implémente `recrop(raw_bgr, hint)` (interface dans `../BENCHMARK.md` §2) puis se mesure
> sur le banc partagé. **Ne réinvente pas la mesure.** Probe **gelée** (sert juste d'oracle
> au banc — B n'appelle PAS la probe : c'est tout l'intérêt, ça tourne aussi on-device).

## L'idée

La détection se rabat sur le **disque interne** (le motif central / l'anneau bimétal
interne). On veut le **rebord EXTERNE** de la pièce. C'est de la **géométrie** : la pièce
est un disque métallique sur un fond ; le bimétal a **deux anneaux concentriques**. On
trouve le cercle externe sans modèle.

## Pistes (à départager par le bench)

1. **Silhouette pièce vs fond** : sur un crop large autour du `hint`, segmenter le métal
   (Otsu/adaptatif, ou couleur) → plus grand contour circulaire concentrique au hint =
   rebord externe. Robuste si le fond contraste.
2. **Modèle bimétal 2 anneaux** : réutiliser `vision/denom_geometry.py` (anneau
   argent/or) — le rebord externe est juste au-delà de l'anneau. Marche bien… sur bimétal.
3. **Hough « plus grand cercle centré »** dans une ROI élargie (≥ `2.6×r_hint`), plancher
   `r ≥ r_hint`, plafond voisin-aware. C'est ce que `detect_bbox_refine` tente déjà mais
   échoue ici (rebord peu contrasté) → **comprendre pourquoi et durcir** (pré-traitement,
   égalisation, gradient radial sur l'anneau externe).
4. **Fallback** : si aucun rebord franc, garder le `hint` (pas de dégradation) — le banc le
   verra (cas non récupérés → candidats pour A ou pour l'hybride).

## Pièges à traiter (ce que le bench doit attraper)

- **Fond encombré / capsule / coincard** : Otsu noyé, faux rebord. Garde : concentricité au
  hint + circularité (fill ≈ 1) + plancher/plafond de rayon.
- **Sur-segmentation lots** : ne pas fusionner 2 pièces (garde voisin-aware, IoU).
  Cf. `feedback_recrop_multicoin_guard`.
- **Pièces non-bimétal / motif plein** : la piste « 2 anneaux » ne s'applique pas →
  retomber sur silhouette/Hough.

## Atout clé

**Pas de coût modèle → applicable au scan on-device** (`SnapNormalizer.kt`), là où A ne peut
pas. C'est ce qui peut faire de B la base de l'hybride (B partout, A en booster serveur).

## Découpage : voir `PLAN.md`.

## Ce qu'on rend en fin de session (`RESULTS.md`)
Le JSON de banc (schéma `../BENCHMARK.md` §4) + un court récap : chiffres D1/D2/D3, piste(s)
retenue(s), taux de fallback (hint gardé), angles morts, cas de désaccord notables.
