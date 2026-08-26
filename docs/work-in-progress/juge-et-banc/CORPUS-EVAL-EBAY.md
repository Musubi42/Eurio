# Le corpus d'évaluation vient d'eBay — ce qui est déjà vrai, et ce qui ne l'est pas

> Ouvert le **2026-08-26** à la demande du PO, qui veut « utiliser des crops
> eBay comme jeu d'évaluation ». Document de travail, pas de décision.
>
> ⚠️ **Trois des prémisses de la demande sont fausses, et une quatrième est
> déjà écrite dans le dépôt depuis des mois.** Elles sont traitées d'abord :
> tant qu'elles tiennent, on risque de rebâtir ce qui existe et de rater ce qui
> manque. Ce qui manque, lui, est réel — et plus grave que ce que la demande
> décrivait.

## 0. L'inventaire — où sont TOUTES les photos d'évaluation

Question du PO le 2026-08-26 : *« il y a deux sets de données… où sont ces
photos ? »*. Mesuré, pas de mémoire. **Il y a bien deux sets, ils sont tous les
deux réels, et ils ne se recouvrent en rien.**

### Set 1 — le corpus DEVICE, 451 captures

```sql
-- ml/state/scan_corpus.db
select bundle_source, count(*) from scan_corpus group by 1;
-- device_pull_20260601|337
-- device_pull_20260429|114
```

| | |
|---|---|
| volume | **451 captures**, **20 classes** seulement |
| les deux pulls | avril (`device_pull_20260429`, 114) et juin (`device_pull_20260601`, 337) — exactement les deux sets dont le PO se souvient |
| conditions | 8 : `bright_plain` 87, `bright_textured` 84, `oblique` 68, `glare_specular` 68, `dim` 68, `tilt_plain`/`dim_plain`/`daylight_plain` 19 chacune |
| base | `ml/state/scan_corpus.db` (463 ko) |
| octets | `ml/state/scan_corpus/frames/` — **53 Mo, 903 fichiers**, en local |
| qui le lit | `scripts/replay_corpus.py`, et lui seul |

**Sur MinIO : oui, mais PAS dans un bucket d'évaluation.** Il y est sous forme
de **3 archives** dans `model-artifacts/training/` :

| clé | taille |
|---|---:|
| `training/scan_corpus_frames/287fc454e403/scan_corpus_frames.tar.gz` | 53,3 Mo |
| `training/device_debug_pull/83f103e0074a/device_debug_pull.tar.gz` | 74,7 Mo |
| `training/eval_real_norm/697e80ca36c0/eval_real_norm.tar.gz` | 2,3 Mo |
| **total** | **130,3 Mo** |

C'est la réplication du lot 0. Le souvenir du PO (« on les a mis dans MinIO »)
est juste ; la précision « dans un bucket d'évaluation » ne l'est pas — le
bucket `eval-corpus` a été créé **le 2026-08-26** et ne contient que les
300 crops eBay.

### Set 2 — les 300 crops eBay, créés le 2026-08-26

| | |
|---|---|
| volume | **300 crops**, **60 classes**, 5 par classe |
| origine | prélevés du pool d'enrichissement par `scripts/select_eval_holdout.py` (règle D5/D7) |
| marquage | `image_assets.eval_corpus = 'matrice-encodeurs-2026-08'` |
| octets | bucket **`eval-corpus`**, 300 objets, préfixe `eval/matrice-encodeurs-2026-08/` |
| manifeste | `state/validation_gold/matrice_eval_gold.jsonl`, `gold_version=5b161e789f0d` |

### Ce que l'inventaire dit

**751 images d'évaluation au total**, mais elles ne sont pas
interchangeables — et surtout, **elles ne notent pas la même tâche** :

| | device | eBay |
|---|---:|---:|
| images | 451 | 300 |
| classes | **20** | **60** |
| conditions de prise de vue étiquetées | 8 | aucune |
| exclues de l'entraînement | oui (bench-only) | oui (`eval_corpus`) |
| outil qui sait les noter | `replay_corpus` | `bench_encoder_dino` |

⚠️ **Aucun outil ne sait noter les deux.** C'est le lot A que le PC est en
train d'écrire (faire lire des crops eBay à `replay_corpus`). Tant qu'il n'est
pas là, les deux corpus vivent dans deux mondes.

---

## 1. Les prémisses, une par une

### ❌ « Les 300 images d'éval sont des images récupérées on-device »

**Faux. Elles sont eBay à 100 %.**

```sql
select si.source, count(*)
  from image_assets a join source_images si on si.id = a.source_image_id
 where a.eval_corpus is not null group by si.source;
-- ebay|300
```

C'est la **décision D1** du 2026-08-26, prise le matin même : *« Le jeu
d'évaluation vient des crops eBay. 5 par classe, prélevés du pool
d'enrichissement, exclus de l'entraînement. »* Le parc entier ne contient plus
que **5** assets non-eBay/non-Numista, et les captures device sont arrêtées par
décision du PO (`CLAUDE.md` §Interdictions).

👉 **Le chantier demandé est déjà livré.** Ce qui suit porte donc sur *quels*
crops eBay, pas sur *si* on en prend.

### ❌ « Il faut retirer de `CLAUDE.md` l'idée que les photos eBay sont parfaites »

**Cette idée n'y est pas.** Ni dans `CLAUDE.md`, ni dans les skills. Le dépôt
dit l'inverse, et depuis longtemps :

> `docs/research/ml-scalability-phases/phase-3-ebay-enrichment.md:10`
> « eBay est la seule source scalable à coût zéro : ~3000 pièces euro,
> beaucoup listées, avec des photos de vendeurs qui sont **exactement la
> distribution cible** (angles bizarres, mauvaise lumière, pièces sales). »

Le seul endroit où « éclairage parfait, pièce propre, bien droite » est écrit,
c'est à propos de **Numista** (`ml-scalability-phases/README.md:11`), et c'est
exact. La confusion vient probablement de là.

👉 **Rien à corriger.** La conviction du PO est celle du dépôt.

### ❌ « Ce serait un chantier neuf »

Le point central en est écrit depuis des mois, et il n'a **pas** été appliqué :

> `docs/research/ml-scalability-phases/phase-4-subcenter-evalbench.md:40`
> « Évite le data leakage : des photos du même vendeur/lot eBay partagent du
> contexte (même fond, même lumière). Si on met 4 photos d'un lot en train et
> 1 en eval, l'eval est trop optimiste. Donc **split par lot/seller**, pas par
> photo individuelle. »

`scripts/select_eval_holdout.py` ne faisait **aucun** split par vendeur ni par
lot. La suite de ce document mesure ce que ça coûte.

> ✅ **Corrigé depuis.** Règle **v2** (2026-08-26, commit `22364b34`) : garde
> vendeur. Règle **v3** (lot 5, même jour) : garde quasi-doublon sur
> `source_image_id`, et un test nommé par garde — sans quoi la règle pouvait
> disparaître du code sans qu'aucune suite ne rougisse. Les chiffres ci-dessous
> restent ceux du corpus v1, qui est ce qu'ils mesurent.

### ✅ « Il va falloir plus de review, c'est un trade-off que j'accepte »

Vrai, et le PO a raison de le poser. Mais le trade-off n'est pas celui qu'il
croit — cf. §5. Ce n'est pas sa volonté de reviewer qui limite, c'est la
taille du pool **par classe** aujourd'hui.

---

## 2. Ce que les mesures du 2026-08-26 disent, et il faut s'asseoir

Toutes obtenues avec `dinov2_vitb14` sur la sous-banque `matrice60`
(893 ancres, 60 classes), les crops jamais vus comme ancres exclus du calcul
d'ancre. Reproductibles avec les commandes du §7.

### 🔴 2.a La contamination par vendeur est réelle, large, et significative

**40,7 % des 300 crops d'éval partagent leur `seller_id` avec une ancre de leur
propre classe.**

| population (60 classes, hors ancres) | n | r@1 |
|---|---:|---:|
| crops dont le vendeur porte aussi une ancre | 364 | **96,2 %** |
| crops dont le vendeur n'apparaît nulle part | 791 | **91,2 %** |

**+5,0 points**, `z ≈ 3,05`, `p ≈ 0,002`. C'est la seule mesure de ce document
qui soit franchement significative — et c'est exactement ce que
`phase-4 §40` annonçait.

Le même effet, en plus fin, au niveau de la **photo brute** : 36 des 300 crops
d'éval sortent du *même fichier raw* qu'une ancre. Ils sont **100 % justes**
(contre 95,8 % pour les autres).

👉 Le 96,3 % annoncé pour `vitb14` est donc **gonflé**. Le chiffre défendable
est **94,9 %** (crops propres uniquement).

### 🔴 2.b La règle de sélection D5/D7 n'a pas sélectionné du dur — l'inverse

C'était sa raison d'être : *« la dégradation visée est géométrique, et elle se
mesure sans aucun modèle appris — `tilt_deg` »*. Testée contre ce qu'elle a
laissé de côté :

| population propre (vendeur jamais vu) | n | r@1 |
|---|---:|---:|
| **jeu d'éval** — la moitié la plus inclinée, choisie par D7 | 178 | **94,9 %** |
| **reste du pool** — ce que D7 n'a pas pris | 792 | **91,2 %** |

Le jeu « dur » est **3,7 points plus FACILE** que le reste. (`p ≈ 0,10` : pas
significatif, donc on ne dira pas « plus facile » comme un fait — mais il n'y a
**aucune trace** de l'effet recherché, et l'estimation ponctuelle va à
l'envers.)

Et à l'intérieur du jeu, le tilt ne classe rien :

| quartile de tilt (13,5° / 15,7° / 18,8°) | n | r@1 |
|---|---:|---:|
| Q1 le moins incliné | 74 | 97,3 % |
| Q2 | 76 | 94,7 % |
| Q3 | 75 | 94,7 % |
| **Q4 le plus incliné** | 75 | **98,7 %** |

### 🔴 2.c Aucun signal géométrique ne prédit la difficulté — et le meilleur est INVERSÉ

| signal (crops propres) | n | r@1 |
|---|---:|---:|
| `tilt_trustworthy` = 1 | 354 | 92,7 % |
| `tilt_trustworthy` = 0 | 615 | 91,4 % |
| `quality_score` non mesuré | 324 | 93,2 % |
| `quality_score` bas (< 0,91) | 203 | 93,1 % |
| `quality_score` moyen (0,91–0,98) | 230 | 92,6 % |
| **`quality_score` haut (≥ 0,98)** | 213 | **87,8 %** |

Le crop le mieux **cadré** est le plus difficile (`p ≈ 0,067`, marginal, mais
c'est l'écart le plus large du tableau : 5,3 points).

⚠️ **Je ne propose aucun mécanisme pour l'expliquer.** Toute histoire qu'on
inventerait ici serait une histoire. Le fait mesurable est : *si on veut un
jeu plus dur, il faut sélectionner sur `quality_score` HAUT* — l'exact
contraire de ce que l'intuition dicte. C'est précisément pourquoi la règle D7
a été écrite par raisonnement et n'a rien produit.

---

## 3. Le vrai problème n'est pas la source des images

Le PO veut plus d'images, et de source eBay. Les deux sont déjà acquis. Ce qui
bloque la matrice est ailleurs, et c'est mesuré :

**Les trois DINOv2 sont d'accord sur 281 frames sur 300.** Le McNemar n'a que
**19 et 18 paires discordantes**, d'où `p = 0,167` et `p = 0,481`. La puissance
d'un McNemar vient de la **discordance**, pas du nombre de frames — la cible
« 150-300 frames » d'`exp-01 §9` visait la mauvaise grandeur.

Deux leviers, et ils ne coûtent pas la même chose :

| levier | ce qu'il faut | ce qu'il rend |
|---|---|---|
| **plus de frames**, même difficulté | ≈ 6,3 % de discordance observée → il faut ~**1 100 à 1 300 frames** pour ~75 paires discordantes, soit la puissance de détecter l'écart observé | linéaire, cher, et ne change pas le fait que la tâche est facile |
| **frames plus dures** | trouver le signal qui les désigne — §2.c dit qu'on ne l'a pas encore | non linéaire : à r@1 ≈ 75 %, la discordance explose et 300 frames suffisent |

👉 **Le second levier est le bon, et c'est lui qui est ouvert.** Le premier est
une rustine qu'on peut chiffrer ; le second demande de trouver comment
reconnaître une « photo d'utilisateur » dans le pool eBay.

---

## 4. Les questions ouvertes, par ordre de ce qu'elles débloquent

### Q0 — Enrichissement et ancres : ce sont DÉJÀ le même set

Le PO : *« si enrichissement et ancres DINO sont deux sets d'images différents,
c'est nul à chier »*. **Ils n'en sont pas.** Mesuré sur la banque servie :

| ligne de la banque `2eur_all` | n |
|---|---:|
| avers canoniques Numista (aucun crop) | 671 |
| **crops eBay** | **1 391** |
| … dont `source = 'ebay'` | 1 391 / 1 391 |
| … dont `training_eligible = 1` | **1 391 / 1 391** |
| … dont marqués `eval_corpus` | **0** / 1 391 |

Une ancre est un crop d'enrichissement **désigné en plus** comme ancre. Elle
reste dans le pool d'entraînement. Il n'y a pas deux sets à entretenir — il y
en a un, plus un marquage.

Le seul « autre » set dans la banque, ce sont les **671 avers canoniques
Numista**, et ceux-là ne viennent pas d'eBay par construction.

### Q0bis — « Pourquoi une partie et pas tout ? » — mesuré

Le PO a raison, et voici de combien. Même jeu (300 frames), même encodeur
(`vitb14`), deux banques :

| banque | ancres | r@1 | r@5 |
|---|---:|---:|---:|
| sous-ensemble FPS (actuel) | 893 | 96,3 % | 99,7 % |
| **tout le pool éligible** | **2 050** | **97,3 %** | 99,3 % |

**+1,0 point pour 2,3× les ancres.** Le sous-ensemble n'existe donc PAS pour
la qualité — il existe pour la **taille embarquée et la latence** : chaque scan
compare la requête à **toutes** les ancres, et la banque part dans l'APK.
2,3× d'ancres, c'est 2,3× de comparaisons sur le téléphone.

👉 **Conséquence directe : pour le BANC, il n'y a aucune raison de se
restreindre.** Le FPS est un arbitrage de production, pas de mesure. La
sous-banque de la matrice devrait prendre **tout** le pool des 60 classes.

### Q1 — Comment reconnaître une photo « à l'arrache » dans le pool ?

C'est LA question. Aujourd'hui on a trois signaux (`tilt_deg`, `axis_ratio`,
`quality_score`) et **aucun ne marche** dans le sens voulu (§2.c). Pistes non
mesurées :

* **flou** — aucune métrique de netteté n'existe en base. Variance du
  laplacien : quelques lignes, calculable sur tout le parc, et c'est le
  candidat le plus évident pour « photo de téléphone à main levée » ;
* **exposition / contraste** — histogramme du crop. Un crop sous-exposé ou
  cramé est un crop d'utilisateur ;
* **désordre du fond** — le crop est masqué (masque dur, 224), donc le fond a
  déjà disparu. ⚠️ **Conséquence importante et pas encore digérée** : notre
  pipeline *détruit* une partie de ce qui distingue une photo de canapé d'une
  photo de studio. On note des pièces détourées, pas des scènes ;
* **le signal du modèle lui-même** — le `spread` (top1 − top2). Circulaire si
  on l'utilise pour SÉLECTIONNER (cf. D5), mais parfaitement légitime pour
  **mesurer a posteriori** la difficulté d'un jeu qu'on a constitué autrement.

### Q2 — Faut-il un split par vendeur, et à quel niveau ?

`phase-4 §40` dit oui. La mesure du §2.a le confirme (`p ≈ 0,002`). Trois
niveaux possibles, du plus faible au plus fort :

1. **même photo brute** (`source_image_id`) — 36/300 aujourd'hui. Coût : ~nul ;
2. **même listing** (`source_ref`) — 32/300. Coût : ~nul ;
3. **même vendeur** (`seller_id`) — 122/300. Coût : réel, cf. Q3.

⚠️ Le niveau 3 est le seul qui ferme vraiment le trou, et c'est aussi celui qui
mord : il faudrait écarter 40 % du jeu actuel, ou re-tirer en excluant les
vendeurs des ancres — ce qui **réduit le pool éligible par classe**.

### ✅ Q3 — RÉPONDUE le 2026-08-26

Par classe, hors ancres :

| | min | p25 | médiane | max |
|---|---:|---:|---:|---:|
| crops disponibles | 7 | 12 | 19 | 149 |
| **dont vendeur jamais vu d'une ancre** | **0** | 6 | 11 | 142 |

| quota d'éval sans contamination vendeur | classes qui tiennent |
|---:|---:|
| 5 | **52 / 60** |
| 10 | 36 / 60 |
| 15 | 19 / 60 |

**3 classes n'ont AUCUN crop non contaminé.** Un split strict par vendeur à
5/classe coûte donc **8 classes** (60 → 52). C'est le prix exact de la
propreté, et il est payable.

### Q4 — À quelle échelle de classes évaluer ?

Tension avec D2/D3, et personne ne l'a posée. La matrice note **60 classes**,
parce que c'est ce qu'ArcFace sait faire. Le produit en aura **671+**. Un
encodeur qui gagne à 60 classes ne gagne pas forcément à 671 — le nombre de
distracteurs est le premier facteur de difficulté d'une tâche de plus-proche-
voisin. **Le classement d'encodeurs mesuré ici pourrait ne pas survivre au
passage à l'échelle**, et rien dans la matrice actuelle ne le dirait.

### Q5 — Le trade-off que le PO accepte est-il celui qu'il croit ?

Il dit : « prendre des crops en éval réduit l'entraînement, donc je ferai plus
de review ». Vrai mais incomplet. Le plancher `MIN_REAL = 10` est déjà mordant :
mesuré le 2026-08-26 sur la cohorte à 68 classes, un quota d'éval de **8/classe
fait tomber 14 classes**, de **10/classe en fait tomber 17**. Ce n'est pas le
temps de review qui limite à court terme, c'est le **pool par classe
aujourd'hui**. Plus de review ne crée pas de crops — il faut **scraper plus**
(`eurio-enrichment`) *avant* de pouvoir prélever plus.

---

## 5. Ce que je recommande, et ce que je ne recommande pas

**❌ Ne pas** relancer un « chantier corpus eBay » : il est fait.

**❌ Ne pas** agrandir le jeu d'éval tant que Q1 n'a pas de réponse. Passer de
300 à 1 200 frames de la même facilité coûte 4× le calcul pour rendre un
McNemar qui restera à la limite — et laisse intacte la contamination par
vendeur, qui vaut 5 points.

**✅ Faire, dans cet ordre** :

1. **Q3 d'abord** — un `SELECT`, zéro calcul. Il dit si Q2 niveau 3 est seulement
   possible. Sans lui, tout le reste est de la conversation ;
2. **Q1 ensuite, par la mesure** — ajouter la netteté (variance du laplacien) au
   parc et refaire le tableau du §2.c. Si elle sépare, on tient la règle de
   sélection que D7 n'a pas su écrire. Si elle ne sépare pas non plus, il faut
   accepter que **le pool eBay détouré ne contient pas de « photo d'utilisateur »
   reconnaissable** — et ça, ce serait le vrai résultat du chantier ;
3. **Q2 seulement après** — le split par vendeur se décide sur les chiffres de
   Q3, pas sur le principe.

⚠️ Et **rien de tout ça ne bloque le bras ArcFace**, qui reste le chemin
critique de la matrice. Le jeu actuel, même imparfait, suffit à comparer
ArcFace et DINO *entre eux* : ses défauts sont les mêmes pour les deux, et le
McNemar est apparié. Ce document sert à savoir ce que le chiffre vaudra, pas à
retarder sa production.

---

## 6. Ce que ce document ne prétend pas

* **Aucune des mesures du §2.b et §2.c n'est significative à 5 %.** Elles
  montrent une absence d'effet là où un effet était promis, ce qui est une
  information ; elles ne prouvent pas l'effet inverse ;
* tout est mesuré avec **un seul encodeur** (`dinov2_vitb14`) et **une seule
  banque**. Un signal qui ne sépare pas DINO pourrait séparer ArcFace ;
* la difficulté est mesurée par le **r@1 d'un plus-proche-voisin sur 60
  classes**. Ce n'est pas « ce que verra l'utilisateur » : le scan réel passe
  par détection + rerank + consensus 5/3.

## 7. Rejouer les mesures

```bash
cd ml
# contamination par vendeur / listing / raw sur le jeu actuel
./.venv/bin/python -m scripts.eval_corpus_gold show

# la matrice DINO elle-même (3 bras, ~4 min sur MPS)
./.venv/bin/python -m scripts.bench_encoder_dino \
  --gold state/validation_gold/matrice_eval_gold.jsonl \
  --anchors-kind matrice60 --models dinov2_vits14 dinov2_vitb14 dinov2_vitl14 \
  --baseline dinov2_vits14 --no-push \
  --out ../docs/work-in-progress/juge-et-banc/matrice-dino.md
```

Les découpages du §2 (par vendeur, par quartile de tilt, par `quality_score`)
ont été produits par des scripts ad-hoc de session, **non committés** : ils
sont à réécrire quand Q1 démarrera, cette fois comme un outil et non comme une
sonde. Leur logique tient en trois lignes — `score_crops` de
`bench_encoder_dino` sur un sous-ensemble, puis un `group by` sur la colonne
qu'on interroge.
