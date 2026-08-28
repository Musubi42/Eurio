# Le juge — deux contraintes, une métrique, un chiffre

> **La règle fondatrice : toute grandeur du juge se calcule à partir de
> l'ellipse d'or. Aucune ne se calcule à partir de ce que la méthode propose.**

C'est ce qui a manqué aux sept chantiers (cf. [`PROBLEME.md`](./PROBLEME.md)) :
`quality_score`, la probe fragment et la similarité DINO se calculent toutes sur
la sortie de la méthode — donc toutes sont optimisables par la méthode.

## C1 — la marge intérieure

Soient `E_gold = (cx, cy, a, b, θ)` l'ellipse d'or en pixels natifs et `F` le
cadre carré effectivement découpé.

⚠️ **Ce n'est pas le carré qui retire des pixels** — c'est le masque circulaire
dur de rayon `r`. Les deux régions diffèrent (le carré atteint `1,44·r` dans ses
coins), et le choix entre elles déplace le taux d'amputation de dizaines de
points. **Question ouverte au PO, à trancher avec les seuils :**
[`DECISIONS.md` §D9](./DECISIONS.md). Le juge journalise les trois marges
(`retenu`, `cadre`, `disque`) ; `--region-c1` choisit laquelle décide.

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

🔴 **C2 est INERTE — mesuré le 2026-08-28, cf. [`DECISIONS.md` §D8](./DECISIONS.md).**
`arc_coverage` vaut **1,000 jusqu'à 25 % d'amputation du rayon**. L'anneau
`[0,70 ; 1,15]` englobe la **jonction bimétallique** (ρ ≈ 0,735), un cercle de
contraste intrinsèque à la pièce qui remplit les 12 secteurs quel que soit le
cadrage. Elle est calculée et journalisée, mais **n'entre pas dans
`amputation_rate`** tant que le PO n'a pas amendé (RE-3). Tout ce qui suit sur
la monotonie reste vrai — et se révèle **vide** : voir l'encadré en fin de
section.

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

> 🔴 **Et il ne suffit pas.** La monotonie dit que rogner ne peut pas *augmenter*
> la couverture. Elle ne dit pas qu'elle la fait *baisser*. Une grandeur saturée
> à 1,000 est monotone au sens large et n'apprend rien — c'est exactement le cas
> ici (§D8). Resserrer l'anneau la rend discriminante, mais elle ne mesure alors
> plus que « `r ≥ 0,95·a` ? », une question géométrique que C1 tranche déjà.
>
> **Ce que C2 devait apporter, C1 l'a déjà** : C1 n'est pas un score, c'est une
> distance entre `E_gold` et la géométrie proposée. Aucune méthode ne peut
> déplacer `E_gold`. L'argument « il faut C2 parce que les scores sont
> optimisables » ne s'applique pas à C1.

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

- **principale : Boundary IoU, `d = 0,08 · a`**, la bande étant **ancrée sur
  l'or** pour les deux formes ([§D10](./DECISIONS.md)) — sinon une méthode qui
  rétrécit rétrécirait sa propre bande. ⚠️ La table ci-dessus a été calculée
  avec une bande proportionnelle à chaque forme ; ancrée sur l'or on lit 0,4545
  et 0,1429 au lieu de 0,464 et 0,148 ;
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
| `d` (Boundary IoU) | **0,08 · a** | **médiane mesurée** de la bande sans dessin, 521 canoniques (D4) |
| succès primaire | `amputation_rate ≤ 5 %` par strate | à discuter |
| garde | `BIoU p10 ≥ 0,50` | le décile bas contient ce que l'humain jette |
| garde | aucune strate > 10 % d'amputation | gagner en moyenne en perdant sur une strate, ce n'est pas gagner |

✅ **`d = 0,08·a` est vérifié** (2026-08-28) : la bande sans dessin du parc
canonique BCE mesure **≈ 0,080·a en médiane** (p25 ≈ 0,060 · p75 ≈ 0,097), après
correction d'un biais de surestimation de 0,023·a calibré sur pièce de synthèse.
`d = 0,08·a` est donc littéralement la médiane du listel nu.

Reproduire — `cd ml && .venv/bin/python -m bench.gold_crop.measure_listel --plate /tmp/listel.png`.
Méthode, biais et réserves : [`DECISIONS.md` §D4](./DECISIONS.md). **Ne pas
ré-essayer la mesure par le relief** : sur une photo, le listel est l'arête la
plus contrastée de l'image, pas une zone lisse — trois tentatives ont échoué là.
