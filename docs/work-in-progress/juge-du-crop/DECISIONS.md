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

## D11 — L'or vit dans le canonique, pas dans un bucket · 2026-08-28 · ✅ TRANCHÉ (PO)

Migration `0019` : `crop_gold_versions` + `crop_gold_annotations`.

**Ce qui l'a tranché, mesuré le jour même.** `MIRROR_BUCKETS`
(`infra/backup/eurio-backup.sh:74`) est une liste **en dur** :

```bash
mc ls eurio/ | grep eval-corpus     # créé le 2026-08-26, 260 objets
sed -n 74p infra/backup/eurio-backup.sh   # …et absent de la liste
```

`eval-corpus` — le corpus qui a tranché ArcFace ↔ DINO — **n'était pas
sauvegardé**, et l'invariant [3] rougissait depuis. Un bucket neuf est hors des
cinq anneaux par défaut, et l'oubli est muet. `juge-et-banc/LOT0-REPLICATION.md`
avait identifié ce piège exact et choisi `model-artifacts` pour l'éviter ;
on applique la même prudence.

Quatre raisons, dans l'ordre où elles pèsent :

1. `eurio.db` est capturée **par construction** (`VACUUM INTO`) — rien à penser ;
2. l'or doit se **joindre** à `image_assets` (strate, verdict humain,
   `detection_method`). Un blob JSON ne se joint pas ;
3. le front hébergé doit l'afficher → il faut une route → il faut du SQL ;
4. `crop_edit_observations` (0018) porte déjà la **même nature de donnée**. Deux
   rangements pour une même nature, c'est la dette que R0 interdit.

**RE-5 est tenu par le GEL, pas par le support.** Tant que
`crop_gold_versions.frozen_at` est NULL, la version s'annote — c'est la séance.
Une fois gelée, elle refuse toute écriture (409), et son instantané part dans
**`model-artifacts`**, bucket déjà miroité. Le `sha256` est calculé **par le
serveur** : un gel dont le client fournit l'empreinte n'atteste rien.

Re-geler le même contenu est idempotent ; re-geler un contenu **différent** est
refusé. Sans ça on pourrait geler, éditer, re-geler — et le gel ne prouverait
rien.

**Scopes.** Écriture `review:arbitrate`, pas `review:write` : un ami invité
tranche des crops, il ne fixe pas la référence contre laquelle on juge. Et pas
un scope neuf `bench:write` non plus — les PAT en circulation portent une liste
figée à leur création, un scope neuf les ferait tomber en 403 jusqu'à
réémission. Lecture `lab:read`, que `reviewer` possède : la planche doit être
regardable depuis un téléphone.

## Défaut connexe relevé · 2026-08-27

**`_R_OUTER_FRAC = 0.47` (`ml/vision/denom_geometry.py`) sous-estime le rayon
réel d'environ 4 %** : mesuré à **0,975** du demi-côté sur la banque et **0,977**
sur le corpus d'éval. Les deux anneaux ρ du `bimetal_score` sont donc dessinés
trop loin. Défaut réel et silencieux, **indépendant de ce chantier** — à corriger
là où il vit.

## D12 — Le tirage vit dans le canonique, et la séance s'annote depuis le front hébergé · 2026-09-08 · 🟡 PROPOSÉ

**Ce qui l'a motivé, mesuré le jour même.** Dix jours après l'ouverture de la
séance, `SELECT COUNT(*) FROM crop_gold_annotations` rend **2**, et la dernière
ligne date du 29/08 08:54 UTC. L'outil d'annotation local a déjà cassé deux
fois pour des raisons d'environnement, jamais de géométrie : l'UA d'urllib
refusé par Cloudflare (28/08), une session d'essai dans le répertoire de la
vraie séance (29/08). Et il exige `cd ml`, le devShell chargé, un port libre
et une console qu'il faut lire — quatre conditions pour un geste de 40 min.

**Ce qui est décidé.**

1. **Le tirage rejoint l'or dans le canonique** — migration `0020`,
   table `crop_gold_tirage` (`role`, `strate_tiree`, `rn`, `hint`, `prefill`
   `measure_tilt` calculé une fois en local et poussé). Les quatre raisons de
   [D11](#d11) s'appliquent à l'identique : joignable, servable au front
   hébergé, capturée par `VACUUM INTO`, même nature que l'annotation. Le
   **verdict humain n'y est pas** : il reste joignable depuis `image_assets`,
   et l'annotateur ne doit pas le voir. `PUT /crop-gold/{v}/tirage` refuse une
   version gelée (409) et un `requete_sha256` différent de celui de la version
   (409) — un tirage et une version viennent de la même requête, ou ce n'est
   pas RE-5.
2. **La page `/gold-crop/annoter`** porte le même geste que l'outil local,
   comportement pour comportement (reprise sur « annotée » et non « touchée »,
   loupes, chrono, passe 2 par ordre de hachage), et écrit par la même route.
   Elle n'est pas `heavy` : canonique + URLs présignées.
3. **`editor_version = 'gold_web_v1'`**, distinct de celui de l'outil local.
   Même leçon que [D5](#d5) : deux instruments qui produisent la même grandeur
   doivent rester distinguables, sinon on ne saura jamais lequel a un biais.
4. **L'outil local n'est pas retiré.** Il écrit dans la même table par la même
   route ; il reste le repli si le front hébergé tombe. Il n'est plus le
   chemin documenté.

**Ce que ça ne change pas.** Le protocole (60 images, 15 par strate, seconde
passe à ≥ 24 h sur 10), le gel, l'empreinte serveur, le juge. Aucun seuil.

**Ce qui attend le PO.** Confirmer que le geste passe mieux au navigateur qu'au
terminal — c'est une hypothèse sur la cause de l'arrêt, pas une mesure. Si la
séance reprend, l'hypothèse tient ; sinon la cause est ailleurs et il faudra
la lui demander.

## D13 — Un rejet de mauvaise face n'entre pas dans l'or : v1 est abandonné pour v2 · 2026-09-10 · 🟡 PROPOSÉ

**Ce qui l'a déclenché.** Le PO, à la 2ᵉ image de la séance : « la pièce 2/60
est une obverse ». Elle l'est : `986ada7d…` montre les deux faces côte à côte,
et le cercle de production (`bbox {x:349, y:25, w:294, h:294}` sur 643×324)
tombe sur la face commune. Verdict humain : *reject*.

**Ce que la vérification a trouvé, et qui est plus grave que le cas.** Le filtre
anti-fuite de `sample.py` ne coupait que sur le **motif**
(`face_reverse`, `not_2eur`). Or `rejected_in_review` est un fourre-tout :

```sql
-- ml/state/eurio.replica.db (réplique du 2026-09-08)
SELECT face, COUNT(*) FROM image_assets
 WHERE resolution_status='rejected' AND quality_reason='rejected_in_review'
 GROUP BY 1;        -- obverse 842 | reverse 619
```

Dans le tirage v1 : **9 des 28 rejets** portaient `face='reverse'` (S1 rn 3 et
6, S2 rn 2/4/5, S3 rn 1, S4 rn 2/3/7). Vérifié à l'œil sur `bdbacea1…` :
coincard belge, face commune, **cadrage impeccable**. RE-4 — « le juge
prédit-il le verdict humain ? » — aurait mesuré un désaccord fabriqué sur près
d'un tiers du bras rejet. Et **la réserve était contaminée pareil** (6 rejets
sur 12, dont les 3 de S1) : la substitution par la réserve ne réparait rien.

**Ce qui est décidé.**

1. La coupe porte aussi sur la face, et **sur les seuls rejets** :
   `AND COALESCE(ia.face,'') <> 'reverse'`. `face` est une prédiction
   (`face_source='pipeline'` sur les 6 299 rejets, 0 NULL) — l'appliquer aux
   acceptés sortirait du vivier des crops qu'un humain a validés, sur la foi
   d'un classifieur.
2. **La requête change, donc la version change** : `v2`. Ce n'est pas un choix
   de confort, c'est la garde de `enregistrer_tirage` (409 : « un tirage et sa
   version sortent de la MÊME requête, sinon le jeu n'est pas reproductible »).
   Écraser v1 aurait rendu irreproductible un jeu qui se croit reproductible —
   RE-5.
3. Le manifeste ne fige plus `"version": "v1"` : elle vaut le **nom du
   dossier**, sinon `sample --out …/v2` publie sous v1 sans le dire.

**Ce que ça coûte** — mesuré avant d'agir : v1 n'est **pas gelée**
(`frozen_at IS NULL`) et ne porte que **2 annotations**, toutes deux sur des
*acceptés*. `ROW_NUMBER()` partitionnant par `(strate, verdict)`, retirer des
rejets ne déplace aucun rang du bras accepté : **51 des 60 images sont
identiques**, les 2 ellipses déjà tracées portent sur des images inchangées
(même `hint`). Coût réel : les retracer sous v2. Vivier restant après la coupe,
par strate (accept / reject) : S1 1 224/184 · S2 176/**41** · S3 1 240/409 ·
S4 271/184 — le 8/7 tient partout.

**Résiduel assumé.** `986ada7d…` — le cas d'origine — **est toujours en
position 2 de v2** : le classifieur l'étiquette `obverse` à tort. Aucune requête
ne le rattrape. C'est le bouton **indécidable** qui le sort, et la réserve,
propre depuis v2, qui le remplace. C'est exactement l'usage pour lequel la
réserve existe.

**Ce qui attend le PO.** Confirmer l'abandon de v1 (rien n'y est gelé), et dire
s'il veut qu'on corrige `face` en base pour les assets mal classés — geste
distinct, qui touche la donnée de production et pas seulement l'or.

## D14 — Le bras « rejet » de l'or est contaminé par le contenu, pas par le cadrage · 2026-09-11 · 🟡 PROPOSÉ

**Mesuré sur v2, passe 1 complète** (`GET /crop-gold/v2`, 60 annotations, 2026-09-11) :

| | tirage | indécidables | restants |
|---|---:|---:|---:|
| acceptés (`manual`) | 32 | 0 | 32 |
| rejetés | 28 | **16** | **12** |

Les 16 indécidables sont **tous des rejets**. Les commentaires du PO sur dix positions (24, 27, 28, 33, 37, 40, 44, 45, 51, 59) disent pourquoi : dessins, illustration, planche d'images, pièce dans un rouleau. Un rejet de ce genre n'a rien à voir avec le cadrage — c'est la contamination de D13 sous une autre forme : `rejected_in_review` est dominé par « ce n'est pas une photo de pièce », pas par « mal cadré ».

**Trois dessins ont été annotés au lieu d'être écartés** : positions **44** (`9c7025e9`, rejeté), **59** (`d439819d`, rejeté) et **45** (`17c70842`, **accepté en review** — un dessin validé par un humain, cf. mémoire « ancres atypiques »). Ils entrent dans RE-4 avec un verdict que le cadrage n'explique pas.

**Les strates confirmées ne sont plus 15/15/15/15** : S1 23 · S4 9 · S3 6 · S2 6 (sur 44). 43 images sur 60 ont changé de strate à la confirmation. Le tirage sur texte a menti à 72 %.

**Ce qui est décidé.**
1. Les positions 44, 45 et 59 sont **à passer indécidables** par le PO — trois clics sur la page v2, non gelée. Aucun code.
2. RE-4 se joue **d'abord en préliminaire** sur les 41 restantes (44 moins les trois dessins), sans gel, pour savoir si le juge sépare **10 rejets de 31 acceptés** (corrigé le 2026-09-11 : 44 et 59 sont des rejets, 45 un accepté). Un bras rejet à 12 est mince ; le résultat est une indication, pas le verdict.
3. La **réserve** (24 images dans le tirage, rôle `reserve`) sert à regarnir : le PO l'annote après les trois clics. Le gel attend passe 2 et la réserve.
4. Pour la suite du vivier (v3 si nécessaire) : le tirage ne peut pas couper « dessin » par SQL — c'est la confirmation humaine qui le fait, et elle coûte 16 images sur 28 dans le bras rejet. Si RE-4 préliminaire est concluant, on regarnit par la réserve ; sinon on discute d'un v3 avec un vivier de rejets **`crop`-motivés** (les lignes L1 du recadrage manuel, quand la review aura repris).

**Ce qui attend le PO** : les trois clics (44, 45, 59 → indécidable), la passe 2 (10 images, ≥ 24 h après la passe 1, donc dès cet après-midi), la réserve.


## D15 — RE-4 préliminaire : le juge sépare à l'envers ; le banc s'arrête sur `amputation_rate`, pas sur la géométrie · 2026-09-11 · 🟡 PROPOSÉ

**Mesuré** (`python -m bench.gold_crop.harness --out state/gold_crop/v2`, 44 annotées, et sur une copie locale à 41 avec les trois dessins de D14 marqués indécidables ; rien d'écrit au canonique, rien de gelé) :

| run | n accept / reject | amputés chez les acceptés | amputés chez les rejetés | Fisher | sens |
|---|---:|---:|---:|---:|---|
| 44 | 32 / 12 | **29 (90,6 %)** | 7 (58,3 %) | p = 0,025 | **inversé** |
| 41 | 31 / 10 | **28 (90,3 %)** | 6 (60,0 %) | p = 0,047 | **inversé** |

`amputation_rate` à `m = 0` est **saturé et anticorrélé** : la prod rogne en routine ~2 % du rayon (`C1_marge_min_frac` médian −0,0195·a chez les acceptés) et l'humain l'accepte. La profondeur de marge **ne sépare pas** (Mann-Whitney p = 0,68). Fisher est bilatéral : il criait « sépare » sur une relation inversée — **le harness rend désormais `SÉPARE À L'ENVERS` et s'arrête** (`a13dc30a`, un test verrouille le cas).

Ce qui sépare, et fort : la **position** du cercle par rapport à l'or. Boundary IoU médian **0,677** (accept) contre **0,058** (reject), p = 1,5·10⁻⁵ ; IoU de masque **0,970** contre **0,779**, p = 2,3·10⁻⁵. Les rejets ne sont pas « un peu rognés », ce sont des cercles posés ailleurs (un cas à IoU 0,000, un à marge −5,2·a).

**Ce qui est proposé.**
1. RE-4 est **tenu** : sur le critère déclaré (amputation binaire à `m = 0`), le juge est faux, et le banc s'arrête là. C'est le huitième oracle qui tombe, mais celui-ci est tombé **avant** de servir — le dispositif a fonctionné.
2. Le juge est **amendé, pas abandonné** : critère = **IoU de masque contre l'or ≥ τ** (contrainte géométrique, pas un score d'embedding — D2 tient). L'amputation reste **publiée** comme mesure, hors verdict, comme C2 depuis D8.
3. **τ ne se choisit pas sur les 41.** Il se pose par une règle écrite avant (RE-1), puis se **valide sur la réserve annotée**, qui devient le jeu tenu à l'écart. Proposition de règle : τ = le point qui maximise la séparation acceptés/rejetés sur passe 1, arrondi au centième, signé avant que la réserve ne soit lue par le banc.
4. Le piège « `gold_replay` doit être à 0 % » est amendé en « 0 % **hors images tronquées par le bord du raw** » : les 4 cas à 9,1 % ont tous `C1_cadre_tronque = True`, disque à 0,000, cadre clampé — aucune méthode ne peut les récupérer.

**Réserves.** Dix rejets, deux strates à une seule image rejetée (S2, S4) : aucune lecture par strate côté rejet. La réserve (24 images, 6 par strate tirée, 3 accept + 3 reject chacune) rapporte ~17 utilisables et **ne ramène ni S2 ni S3 à 15**. Un v3 avec un vivier de rejets `crop`-motivés (les lignes L1 du recadrage manuel) restera probablement nécessaire.

**Ce qui attend le PO** : (a) valider l'amendement du juge (point 2) et la règle de τ (point 3) ; (b) les trois clics de D14 ; (c) la passe 2 ; (d) la réserve — la page doit d'abord savoir la servir (`?role=reserve`, trois lignes de front, en cours).
