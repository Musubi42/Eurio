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

## Défaut connexe relevé · 2026-08-27

**`_R_OUTER_FRAC = 0.47` (`ml/vision/denom_geometry.py`) sous-estime le rayon
réel d'environ 4 %** : mesuré à **0,975** du demi-côté sur la banque et **0,977**
sur le corpus d'éval. Les deux anneaux ρ du `bimetal_score` sont donc dessinés
trop loin. Défaut réel et silencieux, **indépendant de ce chantier** — à corriger
là où il vit.
