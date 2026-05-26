# Expérience 01 — Composite scorer A+B vs D

> Lien : [théorie 04 priorize](../theories/04-priorize.md). Verdict
> **inconclu / asymétrique** : utile pour TOP-tri (D), faible pour
> BOTTOM-flag (A+B mélangés avec C).

## But

Tester si le composite `rim_peak × (1 - continuity_norm) × disc_metalness`
capture les mauvais crops (cat A faux positif + cat B inner feature) en
les classant dans le bottom-30 du run V.3, et les bons crops (cat D) en
top-30.

## Setup

- `ml/scripts/crop_exp/score_crops.py` (approche A SOTA finding 02) :
  rim_peak (gradient radial sur l'anneau du bord) ×
  continuity_penalty (variance angulaire faible = uniforme 360°) ×
  disc_metalness (ratio pixels HSV saturation/value typiques de métal).
- Sidecar `ml/state/crop_scores/059dc8d9...json` (1678 records).
- `ml/scripts/crop_exp/sampler_by_score.py` → HTML bottom-30 / top-30.

## Mesure

Inspection visuelle du sampler (`/tmp/scored.html`) via chrome-devtools
fullPage screenshot. Catégorisation par œil humain :

- **Cat A** : faux positif non-pièce (timbre, strip numérique, sticker)
- **Cat B** : inner feature crop (bbox tiny sur macro)
- **Cat C** : multi-pièce album (légitime mais ambigu)
- **Cat D** : pièce isolée correctement, cadrée plein-disque

## Résultat

| Panel | Cat A+B | Cat C | Cat D | Objectif | Atteint |
|---|---:|---:|---:|---|---|
| BOTTOM 30 | ~8-9 (~30 %) | ~10-12 | ~10 | ≥ 70 % A+B | ❌ |
| TOP 30 | ~0 | ~5 | ~25 (~83 %) | ≥ 80 % D | ✅ |

Détail BOTTOM observable :
- ≥ 5 strips numériques `1234567890` (pris pour des pièces alignées)
- 2-3 macro shots avec bbox tiny sur "10" / "EU" gravé
- 10+ albums multi-cases avec rim diffus / fond uniforme dark
- 5-10 coins isolés mais avec rim faible (lighting / OOF)

Détail TOP :
- Quasi exclusivement des cards où l'avers est bien visible, bord net,
  métal brillant. Quelques crops sur fond textured (album bois clair)
  passent quand même.

## Verdict — inconclu (asymétrique)

**Le scorer marche pour le TOP** : 83 % > seuil 80 %, donc utilisable
comme "tri par confiance" — afficher les hauts-scorers en premier dans
l'UI bench, c'est valide.

**Le scorer marche moyennement pour le BOTTOM** : 30 % < seuil 70 %. La
queue basse est polluée par cat C (albums multi) qui ont aussi des rim
peaks faibles. Pas suffisant pour un filtre auto-reject.

## Action

1. **Win partiel** : utiliser le composite comme tri descendant par défaut
   du panel Crop dans le bench (pas comme reject). Permet déjà à Raphaël
   d'attaquer les pires en haut.
2. **Lose pour reject auto** : il faudrait un sous-signal anti-strip et
   anti-inner-feature pour séparer A+B de C. Théories 02 (radial_grad
   externe vs interne) et 01 (bg_uniformity strict) restent à instancier
   séparément — pas tous fondus dans un seul composite.
3. **Next** : expé 02 — scorer dédié anti-cat A (détection strip /
   périodicité numérique) et anti-cat B (ratio bbox / raw_min_dim < seuil
   → reject inner feature). Cibler ces 2 cats spécifiquement.

## Sidecar produit

- `ml/state/crop_scores/059dc8d9...json` — 1678 records persistés
- `ml/state/crop_scores/expe01_full4.png` — screenshot inspection
