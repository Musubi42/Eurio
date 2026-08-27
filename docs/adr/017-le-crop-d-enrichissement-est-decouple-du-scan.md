# ADR-017 — Le crop d'enrichissement est découplé du scan, et se juge par contrainte

- **Statut** : ✅ Acceptée
- **Date** : 2026-08-27

## Contexte

**Sept chantiers « crop » entre mai et août 2026. Aucune ADR. Chacun a atteint
sa cible sur sa propre métrique, et produit des crops que l'humain jette.**

| chantier | sa cible | son résultat | ce que l'humain en a fait |
|---|---|---|---|
| `crop-quality-overhaul` (juin) | undercrop < 5 % | **97,4 % « ok »** sur son oracle | cet oracle est `image_assets.quality_score`, mesuré le 2026-08-27 **inerte** |
| `crop-recovery` (juin) | D2 ≥ 70 %, critères pré-enregistrés et **validés PO** | **86 %** | **93,1 % de rejet humain** (`score_recover`) |

Ce n'était pas de la négligence. `crop-recovery` avait tout fait dans les
règles : critères écrits, datés, validés avant de coder, oracle gelé. **Son
critère de cadrage était mathématiquement aveugle à ce qu'il devait mesurer.**

Pour deux disques concentriques de rayons `R` (vrai) et `kR` (prédit),
`IoU = k²`. Donc :

| rognage du rayon | IoU de masque | Boundary IoU (d = 8 % R) |
|---:|---:|---:|
| 3 % | 0,941 | 0,464 |
| **6 %** | **0,884** | **0,148** |
| 10 % | 0,810 | 0,000 |

> **Un seuil « IoU médian ≥ 0,80 » tolère l'amputation de 10,6 % du rayon**
> (`1 − √0,80`). Soit tout le listel. Un crop qui satisfaisait ce critère est un
> crop que la review rejette.

Et l'IoU de masque est **insensible au signe** : `0,80` s'atteint aussi bien en
rognant 10,6 % qu'en cadrant 11,8 % trop large. Or ces deux erreurs ne sont pas
symétriques — trop large donne un crop médiocre, trop serré donne un crop
inutilisable **et une ancre empoisonnée dans la banque** (cf. le mécanisme des
ancres atypiques, `debit-enrichissement/SUIVI.md`).

**Le mode d'échec est constant : l'oracle, jamais l'algorithme.** Trois oracles
successifs ont été mesurés optimisables *dans la mauvaise direction* :

- `quality_score` **monte** quand on rogne un fond bruité. Mesuré le
  2026-08-27 : **0,9200** chez les acceptés contre **0,9208** chez les rejetés
  pour motif de crop (`rejected_in_review`). Huit dix-millièmes. Il ne sépare
  rien, et sa propre docstring le dit — « aveugle aux vraies pannes ».
- La **probe fragment** répond « pièce entière ? », pas « CETTE pièce ? ». Écrit
  dans `crop-recovery/strategy-a/RESULTS.md:60-62` **en juin**, et livré quand
  même.
- La **similarité DINO** décroît quand on ajoute du fond et reste quasi plate
  quand on retire de la pièce, tant que le motif central survit. **L'optimum de
  cette fonction EST l'amputation.** Vérifié par le banc du 2026-08-27 : un
  balayage de rayon scoré par `top1_sim` améliore son score en amputant
  visiblement la pièce (« LUXEMBOURG » → « LUXEMBO… »).

Ce n'est pas un bug d'implémentation à chaque fois. C'est **la forme de la
fonction**.

Second constat, indépendant : la contrainte de parité avec le scan Android a
été traitée comme si elle interdisait de changer la méthode de détection pour
l'enrichissement. **Elle ne l'interdit pas**, et le code le dit déjà en quatre
endroits — mais aucune décision ne l'avait acté, donc chaque chantier se l'est
imposée par prudence.

## Décision

**1. Le crop d'enrichissement (eBay) et le crop du scan (Android) sont deux
objets différents. Seul le FORMAT de sortie les lie ; la MÉTHODE de détection
est libre côté serveur.**

Ce qui est **contraint** — le contrat, gelé par ArcFace :

```
(cx, cy, r) → 224×224 BGR · marge 2 % · masque circulaire dur · fond noir
```

Ce qui est **libre** : tout ce qui produit `(cx, cy, r)`. Trois méthodes
cohabitent déjà sous ce format (`normalize_studio` = Otsu + contours,
`normalize_device` = cascade Hough, `normalize_listing` = YOLO + Hough + polish
+ rim-refine), et ArcFace a été entraîné sur des crops issus d'au moins quatre
d'entre elles. **La méthode n'a jamais été homogène.**

La parité **bit-à-bit** ne porte que sur `_crop_mask_resize_int` ↔
`SnapNormalizer.kt`, et le gate `ml/tests/parity_test.py` compare
`normalize_studio` ↔ `normalize_device` — **il ne regarde pas
`normalize_listing`**, le chemin eBay. Vérifié en base : le pipeline device n'a
jamais écrit un seul crop d'enrichissement.

**2. La sortie reste un cercle.** `_apply_edge_mask` peint un disque et noircit
le reste ; un masque de forme libre produirait des pixels qu'ArcFace n'a jamais
vus. Toute méthode de segmentation doit donc se terminer par un
`fitEllipse`/`minEnclosingCircle` → cercle.

**3. Aucune méthode de crop ne se juge sur un score continu. Le juge est une
contrainte géométrique, et il se paramètre sur une vérité terrain humaine.**

Deux contraintes dures — un crop qui les viole est **rejeté**, pas pénalisé :

- **C1, marge** : le contour de la pièce (vérité d'or) doit être intérieur au
  cadre avec ≥ 2 % du demi-grand axe. C'est la marge que la prod prétend déjà
  appliquer (`COIN_MARGIN = 0.02`).
- **C2, listel** : la couverture angulaire du listel en 12 secteurs
  (`measure_tilt`, `crop_detectors.py:408-420`) doit valoir ≥ 11/12.

**C2 est choisie pour une propriété démontrable, pas empirique** : elle est
**monotone par inclusion**. Si `F₁ ⊆ F₂` alors `couverture(F₁) ≤ couverture(F₂)`
— *il n'existe aucun rognage qui l'augmente*. C'est exactement ce qui manquait
aux trois oracles précédents. La seule façon d'en gagner est d'inclure davantage
du listel vrai, c'est-à-dire de faire ce qu'on veut.

Métrique d'évaluation : **Boundary IoU** (`d = 0,08 · R`), 7,4× plus sensible
que l'IoU de masque à l'amputation. Chiffre de pilotage unique : le **taux
d'amputation** — la fraction d'images violant C1 ou C2. Un taux ne se moyenne
pas avec du bon ; une moyenne mélange 55 crops parfaits et 5 amputés en un
nombre qui reste bon, et c'est littéralement ce que faisait « 97,4 % ok ».

**4. Le juge se falsifie avant de servir.** Avant tout classement de méthode, on
publie la corrélation entre le taux d'amputation du **crop actuel** et le
verdict humain sur le jeu d'or. S'il ne sépare pas les acceptés des rejetés,
**le juge est faux et le banc s'arrête**. C'est le test qu'aucun des sept
chantiers n'a fait passer à son oracle ; `quality_score` y échoue à 0,0008 près.

**5. Le recadrage manuel devient une mesure.** Le delta entre le crop proposé et
le crop final est l'étiquette — pas une taxonomie que l'humain remplirait à la
main. Elle enregistrerait son interprétation ; la géométrie enregistre le fait.

## Alternatives considérées

| Option | Verdict |
|---|---|
| **Continuer à améliorer l'algorithme sans changer d'oracle** | ❌ C'est ce qui a été fait sept fois. Chaque chantier a atteint sa cible. |
| **Imposer la parité de méthode entre eBay et le scan** | ❌ Jamais exigée par le code, et coûteuse : les deux problèmes sont différents (photo de vendeur inconnue vs flux caméra maîtrisé). La dette est d'ailleurs enregistrée **dans l'autre sens** (`BACKLOG.md` M3 : le scan Android n'a pas suivi la correction du crop eBay). |
| **Un masque de forme libre (silhouette réelle)** | ❌ Casse le contrat ArcFace : pixels hors distribution. |
| **Garder l'IoU de masque comme critère** | ❌ Tolère 10,6 % d'amputation à 0,80, et insensible au signe. Conservée en log pour comparabilité historique, jamais en critère. |
| **Hausdorff comme métrique principale** | ❌ C'est un maximum : un seul pixel aberrant la fait exploser. Gardée en diagnostic — elle dit *où* ça dérape. |
| **Une taxonomie de rejet remplie à la main** | ❌ Mal remplie au bout de trois jours, et enregistre une interprétation. Le delta géométrique est gratuit et factuel. |
| **Basculer le crop sur le disque intérieur bimétallique** | 🟡 **Mesuré le 2026-08-27, non décidé ici.** L'information survit (96,9–98,8 % contre 98,1 %, aucun écart significatif sur quatre comparaisons McNemar) mais ne gagne rien en justesse. Sa valeur est de **détection** — la jonction est une frontière de couleur intrinsèque, insensible au fond — et cela n'est pas mesuré. Décision reportée au chantier. |

## Conséquences

**Bonnes.**

- La méthode de détection de l'enrichissement est libre : segmentation amorcée
  par boîte, ajustement d'ellipse, rectification par homographie deviennent
  recevables sans toucher à l'APK.
- Le juge est falsifiable avant d'être utilisé, et son critère central n'est pas
  optimisable en trichant.
- La review quotidienne du PO produit de la vérité terrain sans changer sa façon
  de travailler.

**Mauvaises, et il faut les regarder.**

- **`bimetal_score` se dérèglerait en silence** si le nouveau cadrage diffère :
  ses anneaux ρ supposent un cadrage serré à 2 %. Il rendrait `ok:True` avec un
  score faux. *(Défaut connexe mesuré le 2026-08-27 : `_R_OUTER_FRAC = 0.47`
  sous-estime le rayon réel, mesuré à 0,975 du demi-côté. À corriger
  indépendamment.)*
- **La probe anti-fragment (τ = 0,55) est calibrée sur la distribution actuelle
  des crops.** Changer la détection change ce qu'elle voit, sans que rien ne le
  signale.
- **Les phash existants deviennent incomparables** → la dédup layer-4 et les
  `auto_phash` ne matcheront plus l'ancien parc.
- **Les ancres DINO déjà en banque** ont été bâties sur l'ancien cadrage.
  Mélanger deux cadrages dans une même banque introduit une variance sans
  rapport avec la classe. **Une bascule impose une reconstruction, jamais un
  mélange.**
- Le scan Android reste sur son propre chemin, et **l'écart entre les deux
  grandit**. C'est assumé ici, et c'est M3 au backlog.

## Ce qui n'est pas décidé

Le choix de la méthode de détection. Cette ADR décide **comment on choisira**,
pas quoi. Le chantier est
[`docs/work-in-progress/juge-du-crop/`](../work-in-progress/juge-du-crop/README.md).
