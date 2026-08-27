# Le juge — deux contraintes, une métrique, un chiffre

> **La règle fondatrice : toute grandeur du juge se calcule à partir de
> l'ellipse d'or. Aucune ne se calcule à partir de ce que la méthode propose.**

C'est ce qui a manqué aux sept chantiers (cf. [`PROBLEME.md`](./PROBLEME.md)) :
`quality_score`, la probe fragment et la similarité DINO se calculent toutes sur
la sortie de la méthode — donc toutes sont optimisables par la méthode.

## C1 — la marge intérieure

Soient `E_gold = (cx, cy, a, b, θ)` l'ellipse d'or en pixels natifs et `F` le
cadre carré effectivement découpé.

> Pour les 360 directions `φ` (pas de 1°), le point du contour d'or `P(φ)` doit
> satisfaire `dist(P(φ), ∂F) ≥ m · a`, avec **`m = 0,02`**.

`m = 0,02` n'est pas un goût : c'est la marge que la prod prétend déjà appliquer
(`normalize_snap.py`, `COIN_MARGIN = 0.02`). **Le juge exige ce que le code
promet.** Violer C1 = **rejeté**, pas pénalisé.

*Note attendue :* un masque circulaire rogne nécessairement une pièce oblique sur
son petit axe. C1 le dira. C'est une information sur le **format**, pas un défaut
du juge — et c'est le rôle du bras `gold_replay`.

## C2 — la couverture du listel, et sa propriété démontrable

`measure_tilt` (`ml/vision/crop_detectors.py:408-420`) calcule déjà :

```python
n_sectors   = 12
sector_size = 360.0 / n_sectors
occupied    = len(set(int(a / sector_size) for a in angles_deg))
arc_coverage = occupied / n_sectors
```

12 secteurs de 30°, occupé s'il contient ≥ 1 point de bord dans l'anneau
`[0,70·r ; 1,15·r]`.

> **C2.** `arc_coverage`, recalculée **sur l'image de sortie de la méthode** (le
> crop 224 masqué, tel qu'il partirait à l'entraînement), l'anneau étant défini
> par `E_gold` reprojetée, doit valoir **≥ 11/12**.

### Pourquoi cette grandeur — la monotonie par inclusion

> Si `F₁ ⊆ F₂`, alors `arc_coverage(F₁) ≤ arc_coverage(F₂)`.

Retirer des pixels ne peut que vider des secteurs. **Il n'existe aucun rognage
qui l'augmente.** L'unique façon d'en gagner est d'inclure davantage du listel
vrai — c'est-à-dire de faire exactement ce qu'on veut.

C'est une propriété **prouvable**, pas une observation. Comparer :

| oracle | comportement sous rognage |
|---|---|
| `quality_score` (netteté / contraste) | **monte** quand on rogne un fond bruité |
| similarité DINO | **monte** quand on ampute une zone atypique, un halo de capsule |
| probe fragment | bornée [0,1], continue, **saturable** |
| **`arc_coverage`** | **ne peut que baisser** |

Un score continu se fait manger parce qu'il n'a **aucune orientation garantie**
vis-à-vis de l'amputation. C2 en a une. C'est le seul argument qui compte.

### Deux garde-fous à ne pas perdre

- Le centre et le rayon de l'anneau viennent de **`E_gold`**, jamais d'un
  `fitEllipse` refait sur le crop candidat — sinon la méthode déplace l'ellipse
  pour remplir ses secteurs.
- Les seuils de bord sont recalculés sur la médiane du crop candidat (comme dans
  le code existant) : neutre vis-à-vis du cadrage.

## La métrique d'évaluation — Boundary IoU

Pour deux disques concentriques de rayons `R` (or) et `kR` (prédit) :
`IoU = k²`, `Dice = 2k²/(1+k²)`. La Boundary IoU
([Cheng et al., CVPR 2021](https://arxiv.org/abs/2103.16562)) restreint le calcul
à une bande de largeur `d` le long du contour ; avec **`d = 0,08·R`** elle est
littéralement *l'IoU du listel*.

| rognage du rayon | IoU de masque | Dice | **Boundary IoU** |
|---:|---:|---:|---:|
| 0 % | 1,000 | 1,000 | 1,000 |
| 3 % | 0,941 | 0,970 | 0,464 |
| **6 %** | **0,884** | 0,938 | **0,148** |
| 10 % | 0,810 | 0,895 | 0,000 |
| 20 % | 0,640 | 0,780 | 0,000 |

**Rogner 6 % du rayon fait chuter l'IoU de masque de 11,6 points et la Boundary
IoU de 85,2 — un facteur 7,4 de sensibilité.**

Décisions :

- **principale : Boundary IoU, `d = 0,08 · a`** ;
- **Hausdorff** en **diagnostic seulement** — c'est un maximum, un seul pixel
  aberrant la fait exploser ; utile pour voir *où* ça dérape, pas pour classer ;
- **IoU de masque** loggée pour comparabilité historique, **jamais dans un
  critère** ;
- **Dice** écartée : transformation monotone de l'IoU ici, elle sur-flatte encore
  davantage.

## Le chiffre de pilotage — le taux d'amputation

> **`amputation_rate` = fraction des images où C1 **ou** C2 est violée.**
> Décomposée en `amp_C1` / `amp_C2`, et **ventilée par strate**.

1. **Le rejet humain est binaire et catastrophique, pas graduel.** Une moyenne
   mélange 55 crops parfaits et 5 amputés en un nombre qui reste bon — c'est
   mathématiquement ce que faisait le « 97,4 % ok ». Un taux compte les
   catastrophes.
2. **Le listel porte la décision.** Amputer 6 % du rayon retire ~15 % de l'aire
   du listel en laissant `IoU = 0,884` : la métrique de surface dit « très
   bien », l'œil dit « cassé ».
3. **C'est le seul chiffre non optimisable en trichant** (monotonie de C2).
4. **Il est falsifiable immédiatement** — cf. RE-4 dans
   [`PROTOCOLE-BANC.md`](./PROTOCOLE-BANC.md).

## La reproductibilité de l'or lui-même

Le juge ne vaut pas mieux que l'or qui le paramètre. **Double annotation de 10
des 60 images, à ≥ 24 h d'écart**, et publication de :

- la Boundary IoU médiane entre les deux passes → **c'est le plafond du banc** ;
  aucune méthode ne peut être créditée au-dessus du bruit de l'annotateur ;
- le taux de désaccord sur C1/C2.

Si la BIoU intra-annotateur est **< 0,70**, la tolérance `m` ou `d` est trop
serrée pour la main humaine et doit être desserrée **avant** de voir le moindre
résultat de méthode.

## Les seuils, à figer par le PO avant la première exécution

| paramètre | proposé | d'où il vient |
|---|---|---|
| `m` (marge C1) | **0,02** | `COIN_MARGIN` de la prod |
| `arc_min` (C2) | **11/12** | un secteur de tolérance pour un vrai défaut d'image |
| `d` (Boundary IoU) | **0,08 · a** | ~la largeur du listel |
| succès primaire | `amputation_rate ≤ 5 %` par strate | à discuter |
| garde | `BIoU p10 ≥ 0,50` | le décile bas contient ce que l'humain jette |
| garde | aucune strate > 10 % d'amputation | gagner en moyenne en perdant sur une strate, ce n'est pas gagner |

⚠️ **`d = 0,08·a` suppose que le listel occupe ~8 % du rayon. NON VÉRIFIÉ.**
À mesurer sur les canoniques avant de figer.
