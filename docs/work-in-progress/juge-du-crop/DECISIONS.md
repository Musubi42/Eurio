# Décisions — juge du crop

> Journal daté. **Chaque desserrage de seuil s'y inscrit**, avec sa mesure.
> Une décision ne se réécrit pas : on en ajoute une qui supersède.

## D1 — Le crop d'enrichissement est découplé du scan Android · 2026-08-27 · ✅

Seul le **format** de sortie lie les deux : `(cx, cy, r) → 224×224 BGR, marge
2 %, masque circulaire dur, fond noir`. La **méthode** est libre côté serveur.

**Ce qui l'a tranché** : la parité bit-à-bit ne porte que sur
`_crop_mask_resize_int` ↔ `SnapNormalizer.kt`, et `ml/tests/parity_test.py`
compare `normalize_studio` ↔ `normalize_device` — **il ne regarde pas
`normalize_listing`**, le chemin eBay. Vérifié en base : le pipeline device n'a
jamais écrit un seul crop d'enrichissement. Trois méthodes cohabitent déjà sous
ce format.

Acté en [ADR-017](../../adr/017-le-crop-d-enrichissement-est-decouple-du-scan.md).

## D2 — Aucun score continu comme juge de cadrage · 2026-08-27 · ✅

Le juge est un jeu de **contraintes géométriques dures** (C1 marge, C2 couverture
du listel) plus un **taux d'amputation**. Métrique d'évaluation : Boundary IoU.

**Ce qui l'a tranché** : les trois oracles successifs sont mesurés optimisables
*dans la mauvaise direction*. `quality_score` : 0,9200 accepté / 0,9208 rejeté-
crop. La probe fragment répond « pièce entière ? », pas « CETTE pièce ? » (écrit
en juin, livré quand même). La similarité DINO : l'optimum **est** l'amputation,
vérifié sur planche visuelle le 2026-08-27.

C2 est retenue pour une propriété **démontrable** : elle est monotone par
inclusion, donc aucun rognage ne peut l'augmenter.

## D3 — Le recadrage manuel devient une mesure · 2026-08-27 · ✅

Le delta entre le crop proposé et le crop final **est** l'étiquette. Pas de
taxonomie remplie à la main : elle serait mal remplie au bout de trois jours et
enregistrerait une interprétation, là où la géométrie enregistre le fait.

**Ce qui l'a rendu possible** : `circleTouched` existe déjà et est correct —
tous les gestes humains passent par `clampCircle()`, et la suggestion Hough s'y
soustrait délibérément. Il ne manque que la **transmission**.

## D4 — Les seuils du juge · 🟡 EN ATTENTE DU PO

`m = 0,02` · `arc_min = 11/12` · `d = 0,08·a` · succès `amputation_rate ≤ 5 %`
par strate · gardes `BIoU p10 ≥ 0,50` et aucune strate > 10 %.

⚠️ **RE-1 impose qu'ils soient signés avant la première exécution d'un bras
candidat.**

✅ **`d = 0,08·a` est mesuré, et la prémisse tient** (2026-08-28). Reproduire :

```bash
cd ml && .venv/bin/python -m bench.gold_crop.measure_listel --plate /tmp/listel.png
# 521 / 819 canoniques BCE (anneau d'étoiles lisible, SNR harmonique 12 ≥ 3)
# bande lisse extérieure : p25 0,0825 a · p50 0,1035 a · p75 0,1195 a
```

La mesure **surestime** la bande d'environ **0,023·a** — biais mesuré sur pièce
de synthèse (`ml/tests/test_measure_listel.py`), la demi-hauteur de l'harmonique
tombant entre le centre de l'étoile et sa pointe. Après correction :

| | bande lisse vraie, estimée |
|---|---|
| p25 | ≈ 0,060 a |
| **p50** | **≈ 0,080 a** |
| p75 | ≈ 0,097 a |

**`d = 0,08·a` est donc la médiane de la bande sans dessin du parc canonique.**
Sur la moitié basse des dessins la bande du Boundary IoU effleure la pointe des
étoiles ; sur la moitié haute elle reste dans le listel nu. C'est exactement ce
que `JUGE.md` voulait dire par « l'IoU du listel ».

⚠️ **Trois méthodes ont échoué avant celle-ci, toutes pour la même raison** :
sur une photo ou un rendu, le listel n'est *pas* une zone lisse — c'est l'arête
la plus contrastée de l'image. Toute statistique de texture le classe comme du
dessin. Ce qui marche est la **périodicité 12 des étoiles**, que ni le bord ni
l'éclairage ne partagent. Ne pas ré-essayer par le relief.

⚠️ **Réserve de substrat** : mesuré sur des rendus BCE de pièces **commémoratives
de 2 €**, pas sur les crops eBay. L'ellipse ajustée est légèrement généreuse sur
certains rendus (le halo doux), ce qui joue dans le même sens que le biais —
donc la bande vraie est plutôt un peu plus étroite encore.

## D5 — L'ellipse dans l'éditeur : après, pas avant · 🟡 PROPOSÉ

L'instrumentation se branche sur l'éditeur **cercle** actuel (coût : un champ de
payload). L'ellipse vient ensuite, en `editor_version='v2'`.

**Pourquoi** : brancher l'observation aujourd'hui fait produire de la donnée à
chaque review dès demain. L'inverse ferait attendre la collecte derrière un
chantier d'UI de 600 lignes — et sept chantiers ont déjà été perdus à attendre le
bon outil.

⚠️ **Conséquence à ne pas perdre** : passer à l'ellipse est une **rupture
d'instrument**, pas une amélioration incrémentale. Un Δrayon de cercle et un
Δrayon d'ellipse ne sont pas la même grandeur — d'où la colonne
`editor_version`, qui n'existe que pour ça.

## D6 — Les 2 181 recadrages reconstitués : calibration seulement · 🟡 PROPOSÉ

`source_images.detections_json` garde la géométrie native du détecteur et
`apply_manual_crop` n'y touche jamais → **2 181 des 2 913 recadrages manuels
(75 %) sont reconstituables**.

Premier signal apparié jamais obtenu sur le cadrage : Δrayon médian **0,976**,
**rétréci 555 contre agrandi 253**, Δcentre médian 0,067·r.

⚠️ **Deux réserves qui interdisent d'en faire du jeu d'or** : une passe batch est
très probablement intervenue **entre** la détection et le geste humain (1 960 des
1 993 cas portent aussi un `recrop_ingest`), et `POST /ingest/detections` peut
réécrire `detections_json` après coup, sans horodatage permettant de le détecter.

→ **Jeu de calibration** (fixer les seuils d'`outcome`), **jamais** entraînement.

## D7 — Le disque intérieur bimétallique : validé sans être décidé · 2026-08-27 · 🟡

**Mesuré** (banque rebâtie dans chaque bras, jeu d'éval de 260 crops jamais
ancres, encodeur `dinov2-vitl14`) :

| bras | top-1 dessin (52 cl.) |
|---|---:|
| A — pièce entière | 98,1 % |
| B — disque seul (0,717 du côté) | 96,9 % |
| C — disque + 10 % | 98,5 % |
| D — disque découpé dans le **raw** | **98,8 %** |

McNemar apparié : **aucun bras n'est distinguable de la pièce entière**
(p ≥ 0,45). Rapport de rayons réel mesuré : **0,735** (physique : 18,0/25,75 =
0,699).

**Le nom du pays est DANS le disque, sur son bord extérieur** — pas dans l'anneau
aux étoiles. Les émissions communes ne deviennent donc pas indiscernables : elles
l'étaient déjà (**68 % pays contre 94,5 % pour le reste, sur la pièce entière**).

**22 % des classes** ont un débordement mesurable dans l'anneau, marginal et sans
effet observé.

> **Ce que ça décide : rien encore. Ce que ça autorise : tout.** La valeur de
> l'idée n'est pas la justesse — elle n'en gagne pas — c'est la **détection** :
> la jonction bimétallique est une frontière de couleur **intrinsèque à la
> pièce**, insensible au fond, là où le listel doit être trouvé contre un fond
> imprévisible. **Ce banc ne mesure rien de cela** : il a simulé le recadrage par
> géométrie sur des crops déjà réussis.

⚠️ Tout est mesuré avec **DINO, pas ArcFace** — qui est l'encodeur retenu depuis
le 2026-08-26 et qui est entraîné sur des crops pièce entière. Une bascule
imposerait un réentraînement **et une reconstruction de banque, jamais un
mélange**.

## D8 — C2 sort du critère · 2026-08-28 · ✅ TRANCHÉ (PO)

**`arc_coverage` vaut 1,000 jusqu'à 25 % d'amputation du rayon.** Mesuré sur les
60 raws du jeu, puis reproduit sur pièce de synthèse
(`ml/tests/test_gold_crop_judge.py::test_c2_est_inerte_sur_l_anneau_specifie`).

**Pourquoi.** L'anneau de `measure_tilt`, `[0,70 ; 1,15]·ρ`, englobe la
**jonction bimétallique** — ρ ≈ 0,735, chiffre déjà au SUIVI. C'est un cercle
de contraste **intrinsèque à la pièce**, présent dans les 12 secteurs quel que
soit le cadrage. Les secteurs sont donc pleins par construction.

**Ce que ça fait à l'argument de `JUGE.md`.** La monotonie par inclusion est
vraie et **vide** : elle garantit que rogner ne peut pas *augmenter* la
couverture — elle ne garantit pas qu'elle la *fasse baisser*. Une grandeur
saturée est monotone au sens large et ne dit rien.

**Et resserrer l'anneau ne sauve pas C2.** Avec `[0,95 ; 1,05]`, elle devient
discriminante — mais pour rien : le masque circulaire dur a noirci tout au-delà
de `r`, donc l'anneau est vide de Canny dès que `r < ~0,95·a`. C2 répond alors
« `r ≥ 0,95·a` ? », une question **purement géométrique** que C1 tranche déjà,
plus finement et de façon continue.

| anneau | k=1,00 | k=0,95 | k=0,90 | k=0,85 | k=0,75 |
|---|---:|---:|---:|---:|---:|
| `[0,70 ; 1,15]` *(spécifié)* | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 |
| `[0,95 ; 1,05]` | 1,000 | 1,000 | 0,000 | 0,000 | 0,000 |

**Ce qui est fait en attendant** : C2 est **calculée et journalisée** (RE-3
interdit de retirer un critère sans amendement daté) mais **n'entre pas dans
`amputation_rate`** — `juger(..., c2_compte=False)` par défaut, `--c2-compte`
pour l'inverse. Un critère mort qui décide est pire qu'un critère absent.

**Ce que ça ne casse pas.** C2 avait été introduite pour une propriété que C1
possède déjà : **C1 n'est pas un score**, c'est une distance entre `E_gold` et
la géométrie proposée. Aucune méthode ne peut déplacer `E_gold`. L'argument
« il faut C2 parce que les scores sont optimisables » ne s'applique pas à C1.

**✅ Tranché par le PO le 2026-08-28 : (a) + (b).** C2 sort du critère, reste au
journal comme diagnostic. `c2_compte=False` est le défaut ; `--c2-compte` la
réintègre pour qui veut vérifier. Le juge pilote sur **C1 + Boundary IoU**.

## D9 — C1 pose DEUX questions, pas une · 2026-08-28 · ✅ TRANCHÉ (PO)

`JUGE.md` §C1 écrit `dist(P(φ), ∂F) ≥ m·a` avec **F le cadre carré**. Or ce
n'est pas le carré qui retire des pixels : c'est le **masque circulaire dur** de
rayon `r`, qui noircit tout le dehors du disque. Les deux régions ne coïncident
pas — le carré a un demi-côté `1,02·r` et atteint `1,44·r` dans ses coins.

| lecture | ce qu'elle mesure | `gold_replay` (r = a) | détection parfaite d'un cercle |
|---|---|---|---|
| **`cadre`** (la lettre) | la prod tient-elle sa promesse de padding ? | marge = 0,02 exactement ✅ | ✅ |
| **`retenu`** = disque ∩ cadre | la prod perd-elle des pixels de la pièce ? | marge = **0** ❌ à `m = 0,02` | ❌ |

🔴 **Conséquence mesurée : sur la région `retenu` avec `m = 0,02`, le PLAFOND du
banc (`gold_replay`) est à 100 % d'amputation.** C'est géométrique et vrai pour
tout or : `gold_replay` prend `r = a`, donc le masque coupe pile sur le listel.
Un tableau dont le plafond est au plancher est illisible.

Et l'inverse est vrai aussi : la lecture `cadre` déclare sain un cas où une
ellipse oblique tient dans le carré mais **sort du disque** — amputée pour de
bon (`test_le_carre_est_plus_permissif_que_le_masque_dans_les_diagonales`).

**✅ Tranché : les deux questions sont séparées, parce qu'elles n'en étaient
pas une.**

| grandeur | question | région | seuil | décide de `ampute` ? |
|---|---|---|---:|---|
| `ampute` | perd-on des **pixels de la pièce** ? | `retenu` | **0** | ✅ oui |
| `marge_promise_ok` | la prod tient-elle son `COIN_MARGIN` ? | `cadre` | 0,02 | ❌ journalisée |

`m = 0` n'est pas un desserrage : c'est la fin d'une confusion. **Un crop
complet mais serré n'est pas un crop cassé** — et c'est sur le crop cassé que
l'humain rejette. Les deux répondent bel et bien différemment ; le cas près du
bord de l'image le montre (padding à 1,3 %, zéro pixel perdu), il est verrouillé
par `test_un_crop_complet_mais_serre_n_est_pas_un_crop_casse`.

**Effet mesuré : le plafond `gold_replay` passe de 100 % à 0 % d'amputation.**
C'est ce qu'un plafond doit faire. Et la perte du format ne disparaît pas pour
autant — elle se déplace là où elle est réelle, dans la Boundary IoU :

| obliquité de l'or `b/a` | 1,00 | 0,95 | 0,90 | 0,85 | 0,80 |
|---|---:|---:|---:|---:|---:|
| BIoU de `gold_replay` | 1,000 | 0,518 | **0,257** | 0,182 | 0,145 |

> **Sur une pièce à 10 % d'obliquité, aucune méthode ne peut dépasser
> BIoU ≈ 0,26 tant que la sortie doit être un cercle.** Ce n'est pas une limite
> de méthode, c'est ADR-017. La strate S4 doit être lue avec ce plafond sous les
> yeux.

`--region-c1 {retenu,cadre,disque}` et `--m` restent disponibles pour rejouer
sous une autre convention ; les trois marges sont journalisées dans chaque cas.

## D10 — La bande du Boundary IoU est ancrée sur l'or · 2026-08-28 · ✅

`d = d_frac · a_gold`, **en pixels, identique pour les deux formes**. Une bande
dont la largeur suivrait le rayon *prédit* serait une grandeur calculée sur la
sortie de la méthode — et une méthode qui rétrécit rétrécirait sa propre bande.
C'est la règle fondatrice appliquée à la métrique.

⚠️ **La table de `JUGE.md` a été calculée avec l'autre convention** (une bande
proportionnelle à chaque forme). Les valeurs exactes :

| rognage | table `JUGE.md` (par forme) | juge (ancré sur l'or) |
|---|---:|---:|
| 3 % | 0,464 | **0,4545** |
| 6 % | 0,148 | **0,1429** |

L'écart est < 0,01 et ne change aucun classement. Il est dit ici plutôt que
découvert plus tard. Vérifié en forme close par
`test_les_deux_conventions_de_bande`.

## Défaut connexe relevé · 2026-08-27

**`_R_OUTER_FRAC = 0.47` (`ml/vision/denom_geometry.py`) sous-estime le rayon
réel d'environ 4 %** : mesuré à **0,975** du demi-côté sur la banque et **0,977**
sur le corpus d'éval. Les deux anneaux ρ du `bimetal_score` sont donc dessinés
trop loin. Défaut réel et silencieux, **indépendant de ce chantier** — à corriger
là où il vit.
