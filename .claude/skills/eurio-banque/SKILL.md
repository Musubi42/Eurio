---
name: eurio-banque
description: La banque d'ancres DINO — comment la lire, ce qu'elle vaut, ce qu'elle coûte à rebâtir. À lire AVANT de toucher à la banque d'ancres, aux seuils DINO, ou de comparer deux encodeurs.
---

# La banque d'ancres DINO

> Un backbone **gelé** encode chaque classe en quelques vecteurs. Une classe
> nouvelle coûte des lignes de données, pas un réentraînement — c'est la voie B
> de [ADR-008](../../../docs/adr/008-deux-voies-backbone-gele-et-arcface.md).
> Tout ce qui suit est mesuré sur `ml/state/eurio.replica.db` le **2026-08-20
> (17:13 UTC)**, et **chaque chiffre porte sa requête** : recopie-la plutôt que
> le nombre.
>
> 🔴 **Le fait le plus important de cette skill, en tête** : la règle « jamais UN
> seul exemplaire » a été implémentée (`min_exemplars = 2`), la banque rebâtie
> avec — **1533 → 1495 ancres, 182 → 124 classes à exemplaires**, 68 classes
> ramenées au canonique seul — puis **RETIRÉE le soir même** après mesure. Le
> défaut est revenu à `min_exemplars = 1`, c'est-à-dire **plancher inactif** ; le
> mécanisme, lui, est resté entier et testé. Le §3 dit pourquoi le raisonnement
> était faux, ce qui reste vrai, et ce que la mesure restreinte a montré.
>
> ⚠️ **Décalage à connaître avant de toucher quoi que ce soit : la banque SERVIE
> porte encore le plancher, le code ne l'applique plus.** Le build `365dcab2a253`
> a été bâti avec `min_exemplars=2` (colonne « 1 » vide, 68 classes au canonique
> seul) ; le prochain rebuild **changera la forme de la banque** — ces classes
> retrouveront leur exemplaire — et **le garde P1 ne le signalera pas** : il
> compte les classes à ≥ 2 exemplaires (`USEFUL_MIN_REFS`), un compte que le
> retour à 1 laisse invariant. C'est voulu (le garde est délibérément découplé du
> plancher), mais l'inversion sera donc **silencieuse**.

⛔ **Lis d'abord `eurio-data-writes`.** Sous Direction A le devShell pose
`EURIO_DB_PATH=…/eurio.replica.db` et `EURIO_DB_READONLY=1`. `ml/state/eurio.db`
(6205 assets) et `eurio.work*.db` sont **périmées** — voir le piège (a).

---

## 1. Quatre banques, pas une

`training/foundation/anchors.py` — vérifié en exécutant
`encoder_version_for_kind` :

| kind | encodeur | ce qu'elle contient | qui la lit |
|---|---|---|---|
| `2eur_all` | **`dinov2-vitl14`** | 2 € commémo **+** courantes | **tout** : suggestions ET verdict d'auto-validation (`shared/verdict_scope.py`), backfill, banc, courbe |
| `2eur_commemo` | `dinov2-vits14` | commémoratives seules | **plus rien depuis le 2026-08-24**. Ses 7 780 prédictions restent en base et lisibles ; le verdict la lisait avant la bascule |
| `2eur_standard` | `dinov2-vits14` | groupes de dessin courants | historique — `.npz` du 2026-06-11, **aucune ligne en base** |
| `reverse_2eur` | `dinov2-vitl14` | revers (gate `face`) | `backfill_face`, `bench_face_recall` — `.npz` du 2026-06-13 |

*(Les chemins `ml/state/…` supposent qu'on est à la racine du dépôt ; les
snippets Python commencent par `cd ml`.)*

⛔ **`anchors_kind` et `encoder_version` sont indissociables.** Vérifié :

```bash
sqlite3 -readonly ml/state/eurio.replica.db \
  "SELECT anchors_kind, encoder_version, COUNT(*) FROM dino_class_references GROUP BY 1,2;"
# 2eur_all|dinov2-vitl14|1495        ← une seule paire tracée en base
sqlite3 -readonly ml/state/eurio.replica.db \
  "SELECT anchors_kind, encoder_version, COUNT(*) FROM image_asset_dino_predictions GROUP BY 1,2;"
# 2eur_all|dinov2-vitl14|12454
# 2eur_commemo|dinov2-vits14|7780
```

Basculer le seul `kind` (ou le seul encodeur) donne un JOIN à **zéro ligne** —
donc tout en `unknown`, sans la moindre erreur. Détail des conséquences côté
review : **`eurio-review`** §« la review est aveugle sur les standards ».

### Les deux artefacts sur disque, aux rôles distincts

```
state/foundation_anchors_2eur_all.npz                    ← la banque SERVIE (slot unique par kind)
state/foundation_anchors_2eur_all__dinov2-vitl14.npz     ← l'artefact de BANC (un par kind × encodeur)
```

`--no-serve` bâtit l'artefact **sans** toucher la banque servie : c'est ce qu'il
faut pour un bras de banc. Sans le drapeau, la banque servie est remplacée —
comportement voulu d'un rebuild de prod, journalisé en WARNING.

Lire le `.npz` (aucun modèle chargé, ~1 s) :

```bash
cd ml && ./.venv/bin/python -c "
import numpy as np, json
d = np.load('state/foundation_anchors_2eur_all.npz', allow_pickle=True)
print(d.files)                     # matrix, eurio_ids, source_paths, asset_ids, meta
print(json.loads(str(d['meta'][0])))
print(d['matrix'].shape)"
# ['matrix', 'eurio_ids', 'source_paths', 'asset_ids', 'meta']
# {'encoder_version': 'dinov2-vitl14', 'anchors_kind': '2eur_all',
#  'built_at': '2026-08-20T14:27:56+00:00', 'count': 1495, 'dim': 1024,
#  'bank_id': '74e57b2c568d4a53ab476946cc71d27b'}
# (1495, 1024)
```

⚠️ **`bank_id` du `.npz` n'est PAS le `build_id` de `dino_anchor_builds`**
(`74e57b2c…` contre `365dcab2a253`). Le seul appariement fiable est
l'**ensemble des `asset_id`** — c'est exactement ce que fait
`scripts.bench_refs_curve::check_bank_matches_build`, et il refuse de mesurer
quand les deux divergent.

---

## 2. Comment on la lit en base

Deux tables, depuis la migration 0007 :

- **`dino_class_references`** — une ligne par vecteur. `method` ∈
  `canonical` (l'avers Numista, `asset_id IS NULL`) / `fps` (un crop validé,
  choisi par *farthest-point sampling*) / `manual_pin` / `manual_exclude`.
  `rank` porte l'**ordre du FPS** : rang 1 = le crop le plus diversifiant.
- **`dino_anchor_builds`** — une ligne par build : `build_id`, `built_at`,
  `n_classes`, `n_rows`, `n_canonical`, `n_exemplars`, `n_no_canonical`,
  `exemplars_per_class`, `floor_sim`, `host`.

```bash
sqlite3 -readonly ml/state/eurio.replica.db \
 "SELECT substr(build_id,1,12), anchors_kind, encoder_version, built_at,
         n_classes, n_rows, n_canonical, n_exemplars, n_no_canonical
    FROM dino_anchor_builds ORDER BY built_at DESC;"
# 365dcab2a253|2eur_all|dinov2-vitl14|2026-08-20T14:27:56+00:00|671|1495|671|824|0
#   note : min_exemplars=2 (source=code); 68 classes ramenées au canonique seul;
#          0 sans canonique gardées sous le plancher
# 23c637d93b43|2eur_all|dinov2-vitl14|2026-08-19T14:36:14+00:00|671|1533|671|862|0
# 42d17f9e7083|2eur_all|dinov2-vitl14|2026-08-19T00:28:21+00:00|671|1250|664|586|7
```

### ⛔ La maille est `class_id`, jamais `eurio_id`

C'est le piège de lecture le plus fréquent, et il ne lève rien : compter par
`eurio_id` donne **677 / 130** là où la banque a **671 classes / 124 classes à
exemplaires**.

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT COUNT(*), COUNT(DISTINCT class_id), COUNT(DISTINCT eurio_id)
  FROM dino_class_references WHERE anchors_kind='2eur_all';"
# 1495|671|677          ← 6 eurio_id de plus que de classes
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT COUNT(DISTINCT class_id), COUNT(DISTINCT eurio_id)
  FROM dino_class_references WHERE anchors_kind='2eur_all' AND method='fps';"
# 124|130
```

Pourquoi : `class_id` est l'**`eurio_id` du représentant** de la classe —
la commémorative elle-même, ou pour une courante le premier membre de son
groupe (`ORDER BY year, eurio_id`, `_class_specs_2eur_all`) — et `eurio_id`
nomme le **membre du groupe dont vient le crop**. ✅ **Corrigé le 2026-08-21** :
cette skill disait `class_id = COALESCE(design_group_id, eurio_id)` ; c'est
faux, vérifié — **0** `class_id` de la banque est un `design_group_id`
(`SELECT COUNT(*) FROM (SELECT DISTINCT class_id FROM dino_class_references
WHERE anchors_kind='2eur_all') WHERE class_id IN (SELECT design_group_id FROM
coins WHERE design_group_id IS NOT NULL)` → 0). La traduction depuis une pièce
passe par `shared/bank_classes.py`, jamais par un `COALESCE` naïf. Six classes
portent des crops venus de plusieurs membres, tous repliés sur le représentant. Chercher l'étiquette d'un membre
— `fr-2007-2eur-standard-2nd-map` — ne rend **rien**, et ce n'est pas un manque
de données (cf. `eurio-enrichment` §« la règle qui évite la plupart des
erreurs »).

Le même repli existe dans le gold du banc : **105 crops sur 1958 (5,4 %)** ont
un `class_id` différent de leur `eurio_id` ; les ignorer plafonnerait le recall
à 94,6 % sur **tous** les encodeurs, sans rien signaler
(`go-task ml:bench-gold:show`).

### L'état mesuré aujourd'hui

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT n, COUNT(*) FROM (SELECT class_id, COUNT(*) n FROM dino_class_references
  WHERE anchors_kind='2eur_all' AND method='fps' GROUP BY 1) GROUP BY 1 ORDER BY 1;"
```

| exemplaires | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| classes | **0** | 28 | 9 | 12 | 5 | 5 | 1 | 2 | 5 | 57 |

**671 − 124 = 547 classes (82 %) sont au canonique Numista seul.** La colonne
« 1 » est vide — mais **ce n'est plus « par construction »** : c'est le plancher
`min_exemplars=2` du build `365dcab2a253` qui l'a vidée, en ramenant 68 classes
au canonique seul, et **ce plancher a depuis été retiré du code** (défaut 1,
inactif). ⛔ **Ne lis donc pas cette colonne comme une propriété du builder** :
au prochain rebuild elle se remplira à nouveau. Lis le §3 avant d'en conclure
quoi que ce soit — le plancher a coûté ~1 point de held-out et sa prémisse a été
réfutée par une mesure restreinte.

*Pour comparaison, la même requête sur le build précédent (`23c637d93b43`,
1533 ancres, 182 classes à exemplaires) donnait : 64 / 27 / 7 / 9 / 6 / 5 / 1 /
2 / 6 / 55, soit 489 classes au canonique seul.*

⚠️ **Ces comptes sont ceux d'une minute, pas des constantes.** La réplique est
re-pull-ée et la file de review avance pendant qu'on lit : le 2026-08-20, entre
09 h et 16 h, 64 items sont passés de `open` à `done`, la file ouverte est
tombée de 6894 à 6830, et trois classes ont changé de strate. Les chiffres
ci-dessus sont vérifiés le **2026-08-20 à 13:58 UTC** sur la réplique pull-ée à
03:22 UTC. Relance la requête plutôt que de citer le tableau, et donne
l'horodatage **à la minute** avec le chiffre — sinon personne ne peut dire si
un écart est une erreur ou six heures de review.

---

## 3. Ce qu'elle vaut — la courbe références/classe

Source : [`COURBE-REFERENCES.md`](../../../docs/work-in-progress/scan-sans-retrain/COURBE-REFERENCES.md),
rejouable par `go-task ml:refs-curve:run` (lecture seule, aucun rebuild).

`dinov2_vits14`, **held-out**, population variable (1100 crops / 72 classes),
mesurée sur la banque **d'avant le plancher** (1533 ancres) :

```
N=0 : 53,1 %   N=1 : 50,1 % ← RÉGRESSION   N=2 : 54,6 %   N=3 : 57,3 %
N=5 : 66,4 %   N=8 : 73,9 %                N=9 : 74,1 %   N=10 : 75,5 %
```

`dinov2_vitl14`, mêmes paliers N = 0/1/2/3/5/8/10 : 76,1 / **72,5** / 74,5 /
76,1 / 79,6 / 84,4 / 85,7 % (N=9 non mesuré en vitl14).

**La forme ne dépend pas de l'encodeur** — même creux à N=1, même écrasement du
rendement, décalage de niveau constant. C'est ce qui autorise à décider du
**budget de review** sans avoir tranché l'encodeur.

⛔ **Il n'y a pas de plateau mesuré.** « Coude à N=8 » était un artefact du
maillage 5/8/10 ; sur 4..10 le détecteur ne trouve plus rien, et l'analyse
appariée donne 8→9 = bruit (`z=0,50`) mais 9→10 significatif (+1,36 pt,
`z=2,54`). « Viser 8 » est un **arbitrage coût/bénéfice**, pas une lecture de
plateau. (La description de `ml:refs-curve:run` dans `ml/tasks.yml` disait
encore « coude à N=8 pour les DEUX encodeurs » ; corrigée le 2026-08-20.)

⛔ **La courbe ne simule pas ce que le builder produit** (défaut S6).
`scripts/bench_refs_curve.py` tronque la banque par rang FPS et n'a aucune
notion de `min_exemplars` (`grep -n min_exemplars ml/scripts/bench_refs_curve.py`
→ rien). Un palier N est « **toutes** les classes plafonnées à N », jamais « ces
classes-ci à N, les autres pleines ». La courbe mesure le **rendement d'un
exemplaire supplémentaire** ; elle ne prédit pas la forme d'une banque réelle.
C'est exactement la confusion qui a fait poser le plancher.

✅ **Ce que le script sait faire depuis le 2026-08-20 (soir)**, et qui permet de
poser la question par classe au lieu de l'agrégat :

| drapeau | effet |
|---|---|
| `--bank-classes @fichier` | le plafond `N` ne s'applique **qu'à ces classes** ; les autres gardent toute leur banque |
| `--gold-classes @fichier` | seuls les crops de ces classes sont **notés** |
| `--rank-order last` | garde les rangs FPS les **moins** diversifiants au lieu des plus — sonde de mécanisme, ne correspond à aucun build possible |

Chaque palier est en outre comparé au précédent par **McNemar exact**
(`shared/stats/paired.py`) : un écart de courbe sans sa p-value ne se cite plus.

### 🔴 « Jamais UN seul crop » — la règle a été appliquée, puis RETIRÉE

**Lis ce bloc en entier avant de t'appuyer sur la règle : elle n'est plus en
vigueur dans le code, et la mesure la contredit dans le sens où elle
l'affirmait.**

Le plancher `min_exemplars = 2` a été posé, la banque rebâtie avec (build
`365dcab2a253`, 2026-08-20 14:27 : 1533 → **1495** ancres, 182 → **124** classes
à exemplaires, 68 classes ramenées au canonique seul), P3 refait contre elle
(12 454 prédictions, 0 périmée). Re-bench held-out à N=10, c'est-à-dire sur la
banque réellement servie :

| held-out, N=10 | avant plancher | après | delta |
|---|---:|---:|---:|
| `dinov2_vits14` | 75,5 % | **74,1 %** | **−1,4** |
| `dinov2_vitl14` | 85,7 % | **84,8 %** | **−0,9** |

Le contrôle qui autorise la comparaison : **à N=0 les deux banques sont
identiques** (671 canoniques, aucun exemplaire) et rendent le même score à
0,1 pt près — 53,1 → 53,2 % et 76,1 → 76,2 % — bien que la population held-out
soit passée de 1100 à **1179** crops (crops fuités : 858 → **779**, requête au
§3 plus bas).

⛔ **La faute de raisonnement, à ne jamais refaire.** Le point N=1 de la courbe
(50,1 % contre 53,1 % à N=0) décrit une banque où **TOUTES** les classes sont
plafonnées à un exemplaire. Il ne dit rien du cas réel — 68 classes à un
exemplaire, 114 plus riches. **On a extrapolé d'un agrégat à une règle par
classe.** Règle de travail qui en sort : *un point de courbe agrégée ne
justifie jamais une règle appliquée classe par classe tant qu'elle n'a pas été
mesurée dans le régime mixte où elle s'appliquera.*

⚠️ **Ce delta seul n'aurait pas suffi à conclure.** La banque n'a pas changé que
par le plancher : le FPS a rejoué sur un pool qui avait bougé (10 classes ont
gagné des exemplaires), et 1495 ancres offrent mécaniquement moins que 1533.
Curiosité **non expliquée** : à **N=2** la nouvelle banque est *meilleure*
(55,9 % contre 54,6 % en `vits14`) avec moins de lignes ; elle ne perd qu'à N=8
et N=10.

### ✅ Le geste qui a tranché : une mesure PAR CLASSE, pas un delta d'agrégat

Le plancher a été **retiré le 2026-08-20 (soir)** sur trois mesures, toutes
appariées (McNemar exact), toutes rejouables en lecture seule. Elles sont
reproductibles telles quelles :

**1. La population que le plancher visait est inévaluable.** Les classes sans
exemplaire mais à pool éligible non vide totalisent **77 crops** dans le gold,
dont **61 sont précisément le crop qui deviendrait leur ancre** : il reste
**16 crops held-out pour ~70 classes**. Aucun verdict n'est possible sur elles,
et le dire est le premier résultat.

**2. Donner à 57 classes riches exactement UN exemplaire AMÉLIORE leurs propres
crops.** C'est la mesure qui n'avait jamais été faite, et elle renverse la
prémisse.

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 \
  --bank-classes @rich57.txt --gold-classes @rich57.txt
# 1073 crops · 54 classes : N=0 67,6 %  N=1 69,1 % (p=0,0479)  N=2 72,0 % (p=3,9e-07)
#   --model dinov2_vits14 : 41,6 %      45,5 % (p=4,5e-10)     52,4 % (p=1,2e-25)
# rich57.txt = les class_id à 10 exemplaires fps de la banque servie
```

⚠️ C'est un **PROXY** : ce ne sont pas les 68 classes pauvres, faute de crops
pour les noter (résultat 1). L'argument qu'il est *conservateur* — le rang 1
d'une classe riche est choisi dans un pool de dix, donc plus atypique que
l'unique crop d'une classe pauvre qui n'a pas de choix — est un raisonnement
sur le code du FPS, **pas une mesure**.

**3. Le creux à N=1 vient de l'ORDRE du FPS, pas du nombre.** Sur la banque
courante il n'est même pas significatif en `vits14` (53,2 → 52,1 %, **p=0,279**,
du bruit) ; il l'est en `vitl14` (76,2 → 73,8 %, p=0,0056). Mais à **nombre
d'ancres strictement identique** (795 lignes, un exemplaire par classe), garder
le rang le **moins** diversifiant au lieu du plus fait disparaître le creux :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 3 --rank-order last
# 76,2 %  77,8 %  78,4 %  80,9 %   ← contre 73,8 % au rang 1 en ordre `first`
```

Le mécanisme « le rang 1 du FPS est un faux attracteur parce qu'il est
atypique », jusqu'ici inféré, est donc **mesuré**. Le plancher soignait ce
symptôme en **supprimant des données**. Le vrai levier — amorcer le FPS
autrement (médoïde plutôt que point le plus lointain) — **n'est pas
implémenté** : `--rank-order last` est une sonde, pas un builder.

**4. L'autre moitié de l'effet, à ne pas taire** : l'exemplaire d'une classe
*coûte* aux crops des **autres** classes (vitl14 88,5 → 88,0 % à N=1, → 87,6 % à
N=2). Mais ce coût **croît avec le nombre d'ancres** : c'est de la concurrence
entre voisins, pas une pathologie du « un seul ». Il ne justifie donc pas un
plancher.

**5. Pourquoi l'agrégat trompait** : 1073 des 1179 crops held-out (**91 %**)
appartiennent aux 57 classes à 10 exemplaires, et 85 seulement à des classes
sans exemplaire. Un held-out agrégé est **une mesure des classes riches
déguisée en mesure de la banque** — et un plancher se juge sur les classes
pauvres, que ce gold ne sait presque pas voir.

### Ce qui reste vrai du raisonnement d'origine

Que le **rang 1 du FPS est le crop le plus atypique de sa classe** — ça, c'est
mesuré (point 3). Ce qui est faux est la conclusion qu'on en tirait : « donc
zéro vaut mieux qu'un ». Non — un exemplaire, même atypique, **aide sa classe**.

**Ce n'est plus encodé dans le code**, `shared/dino_threshold_defaults.py` :
`min_exemplars = 1` (**plancher INACTIF**) pour les deux couples. Le mécanisme
est resté entier dans `anchors.build_anchors_2eur_all` — résolution en base
avant les ~4 min d'encodage, clamp, WARNING sur valeur fractionnaire, note de
build qui dit ACTIF/INACTIF — et il est couvert par 14 tests
(`ml/tests/test_plancher_exemplaires.py`). **Reposer 2 se fait en une ligne dans
`dino_thresholds`**, sans toucher au code.

✅ **Ce rebuild a eu lieu : le compte réel est 68**, écrit par le build dans
`dino_anchor_builds.note` (`min_exemplars=2 (source=code); 68 classes ramenées
au canonique seul; 0 sans canonique gardées sous le plancher`). *(C'est la
banque encore servie ; un rebuild d'aujourd'hui, plancher inactif, écrirait
`0 classes ramenées au canonique seul`.)* Le paragraphe qui suit garde sa valeur
de **méthode** — il explique pourquoi ni « 64 » ni
« 182 → 118 » ne pouvaient être prédits, et 68 ≠ 64.

⚠️ **Ce que ce rebuild donnerait ne se déduit PAS d'un compte de pool.** On a
d'abord écrit « les 64 classes à un exemplaire y passeront toutes, 182 → 118 » ;
c'était faux et l'erreur est instructive. Compté avec les vraies fonctions du
builder (`_class_specs_2eur_all` puis `_candidate_crops_for_class`) sur la
réplique le **2026-08-20 à 13:58 UTC** : `{'<=1': 61, '>=2': 3}` — trois
italiennes (`it-2018-…ministry-of-health` pool 2, `it-2023-…air-force` pool 4,
`it-2025-…jubilee-year-2025` pool 4) n'ont un exemplaire unique que parce que
`floor_sim=0.45` a rejeté les autres, pas parce que le pool est vide. Et le pool
bouge d'heure en heure : ces trois-là ont gagné leurs crops dans l'heure qui a
précédé la mesure. **Ce qui décide est la sortie du FPS, donc l'encodage.** Le
seul chiffre qui fera foi est celui que le prochain build écrira dans
`dino_anchor_builds.note` (`plancher : N classes ramenées au canonique seul`).
« 182 → 118 » est une borne de couverture, pas un compte.

⛔ **Le plancher est un COMPTE : ne le pose jamais fractionnaire.**
`min_exemplars = 1,9` franchissait les bornes `[0, 50]`, ressortait
`source='db'` — donc *réglé* à l'écran — et le builder le relisait `int(1.9)`
= **1**, exactement le régime interdit. Corrigé le 2026-08-20 (défaut S1) :
`store.dino_thresholds.set_threshold` refuse une valeur non entière pour cette
clé (400), et le builder journalise en WARNING une ligne fractionnaire déjà en
base au lieu de la tronquer en silence. ⚠️ Ce garde **reste utile après le
retour à 1** : le défaut est la troncature silencieuse, pas la valeur qu'elle
produisait.

### Les deux régimes — et pourquoi la fuite GONFLE

**779 des 1958 crops du gold *sont* des lignes de la banque** (858 avant le
plancher — la fuite a baissé en même temps que la banque). Les noter contre
elle mesure une similarité de 1,0 avec soi-même.

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, json
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
gold = {json.loads(l)['asset_id'] for l in open('state/validation_gold/encoder_bench_gold.jsonl')}
anc  = {a for (a,) in c.execute(\"SELECT asset_id FROM dino_class_references \"
        \"WHERE anchors_kind='2eur_all' AND asset_id IS NOT NULL\")}
print(len(gold), len(gold & anc))"
# 1958 779        ← 1179 crops held-out
```

À N=10, global@1 :

| modèle | fuité (1958) | held-out | écart |
|---|---:|---:|---:|
| `dinov2_vitl14` | 91,6 % | **85,7 %** (1100 crops) | +5,9 |
| `dinov2_vits14` | 85,9 % | **75,5 %** (1100 crops) | +10,4 |

⚠️ Ces quatre chiffres sont ceux de la banque **d'avant le plancher** (1533
ancres). Sur la banque servie aujourd'hui, le held-out vaut **84,8 %**
(`vitl14`) et **74,1 %** (`vits14`) sur **1179** crops ; le fuité n'a pas été
re-mesuré. Le **sens** du biais, lui, ne change pas.

**Le point gratuit profite surtout au modèle faible** : la fuite rétrécit
l'écart apparent entre les deux (5,7 pts en fuité, **10,2 en held-out**). Elle
ne retourne pas le classement — dans les deux régimes vitl14 devance vits14 —
mais elle fausse le **niveau absolu**, et c'est le niveau absolu qu'on lit
quand on décide si le scan est « assez bon ». Les chiffres publiés dans
[`BENCH-ENCODEURS.md`](../../../docs/work-in-progress/scan-sans-retrain/BENCH-ENCODEURS.md)
sont ceux du régime **fuité** : le banc note le gold entier.

⚠️ **Et le held-out n'est pas un plancher prudent pour autant.** À N=0 aucune
fuite n'est possible et l'écart subsiste (53,1 % contre 47,7 %) : le FPS retient
les crops les plus atypiques, **donc les plus durs**, et ce sont exactement ceux
qu'on exclut. La population held-out est plus facile de ~5,5 points. Les deux
biais jouent en sens contraire — on ne corrige pas l'un par un décalage.

---

## 4. Les seuils — où ils vivent, ce qu'ils valent

Depuis 2026-08-19 les seuils sont **en base**, scopés par couple
`(banque, encodeur)` : table `dino_thresholds`, défauts stdlib dans
`shared/dino_threshold_defaults.py`, résolution par `store/dino_thresholds.py`.

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, store.dino_thresholds as dt
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
r = dt.resolve(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')
print(r.values); print(r.source)"
# {'top1_country_sim_min': 0.55, 'country_spread_min': 0.05, 'spread_uncertain_max': 0.02,
#  'spread_confident_min': 0.05, 'spread_auto_accept_min': 0.1, 'min_exemplars': 1}
# {…: 'code', …}      ← 'code' partout : la table est VIDE dans la réplique
#                        min_exemplars: 1 = PLANCHER INACTIF (cf. §3)
```

⚠️ `source` dit d'où vient chaque valeur. **`'code'` aujourd'hui pour les six
clés** — donc `dino_thresholds` n'a encore aucune ligne au canonique. Lis
toujours `source`, pas seulement `values` : un seuil réglé qui retomberait en
silence sur le défaut déplacerait le taux de faux positifs sans laisser de
trace.

⛔ **Un seuil appartient à un encodeur.** Les sims de vits14 et vitl14 ne sont
pas sur la même échelle ; 0,55 calibré sur l'un ne veut rien dire pour l'autre.
C'est pourquoi la clé est un couple.

### Le palier `spread ≥ 0,10` n'est PAS gonflé par la fuite

C'est la question qu'on se pose forcément après le §3, et elle a été mesurée.
Précision du top-1 (`top1_eurio_id == truth_eurio_id`, gold `0ecbb1d70e3c`,
prédictions `2eur_all`/`dinov2-vitl14` en base) :

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, json
from collections import Counter
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
gold = {json.loads(l)['asset_id']: json.loads(l)['truth_eurio_id']
        for l in open('state/validation_gold/encoder_bench_gold.jsonl')}
anc = {a for (a,) in c.execute(\"SELECT asset_id FROM dino_class_references \"
       \"WHERE anchors_kind='2eur_all' AND asset_id IS NOT NULL\")}
st = Counter()
for aid, t1, sp in c.execute('''SELECT asset_id, top1_eurio_id, spread
      FROM image_asset_dino_predictions
     WHERE anchors_kind=? AND encoder_version=?''', ('2eur_all','dinov2-vitl14')):
    if aid not in gold or sp is None or sp < 0.10: continue
    g = 'ancre' if aid in anc else 'hors banque'
    st[(g,'n')] += 1; st[(g,'ok')] += (t1 == gold[aid])
for g in ('hors banque','ancre'):
    print(g, st[(g,'n')], '%.1f%%' % (100*st[(g,'ok')]/st[(g,'n')]))"
# hors banque 500 98.4%
# ancre       744 97.4%          ← rejoué le 2026-08-20 à 21:0x UTC
```

**98,4 % hors banque contre 97,4 % sur les ancres** : le palier tient, et il
tient *mieux* sur les crops que la banque n'a jamais vus. La discipline
d'abstention (D4 de
[`DECISION.md`](../../../docs/work-in-progress/scan-sans-retrain/DECISION.md))
n'est pas un artefact de fuite.

⚠️ **Ces deux chiffres sont sur `spread` global, et la vérité y est
`truth_eurio_id`. Ce n'est PAS la métrique du verdict de review**, qui utilise
`COALESCE(country_spread, spread)`. Sur cette métrique-là, à même palier de
0,10, la précision hors banque **tombe** — rejoué le **2026-08-20 en fin de
session** sur `ml/state/eurio.replica.db`, mêmes 1958 crops du gold
`0ecbb1d70e3c`, banque servie `365dcab2a253` :

| marge | vérité | hors banque | ancre |
|---|---|---:|---:|
| `spread` | `truth_eurio_id` | **500 → 98,4 %** | 744 → 97,4 % |
| `COALESCE(country_spread, spread)` | `truth_eurio_id` | **768 → 84,5 %** | 754 → 97,3 % |
| `spread` | `class_id` | 🔍 non reproduit | 🔍 non reproduit |
| `COALESCE(country_spread, spread)` | `class_id` | 🔍 non reproduit | 🔍 non reproduit |

Le script ci-dessus rend la **première** ligne ; la deuxième s'obtient en
remplaçant `sp` par `csp if csp is not None else sp` (ajoute `country_spread` au
`SELECT`).

🔍 **Les deux lignes `class_id` sont volontairement retirées de la table plutôt
que recopiées.** Elles y figuraient à `99,4 % / 99,4 %` et **ne se reproduisent
pas** : le `class_id` du gold est le *eurio_id représentant* du groupe de dessin
(`ORDER BY year, eurio_id`), et `dino_class_references.class_id` l'est
**aussi** (vérifié le 2026-08-21, cf. §2) — mais `coins` raisonne en
`COALESCE(design_group_id, eurio_id)`, et les requêtes de ce tableau mélangeaient
les deux. Vérifié : sur les 1958 crops du gold, 546 ont un `class_id` différent
de `COALESCE(design_group_id, eurio_id)` de leur `truth_eurio_id`, et même en
repliant sur le représentant il en reste 99 (à expliquer : ce reste est le vrai
résidu Q13). **Diagnostic posé dans
`docs/work-in-progress/pipeline-propre/VISION.md` §V4** ; les deux lignes
seront recalculées avec `bank_classes` avant d'être citées.

⚠️ **Effectifs 463/821 → 500/744** : la version précédente de ce tableau datait
du 2026-08-20 13:58 UTC, soit **avant** le rebuild de 14:27 ; elle cohabitait
avec des comptes post-rebuild. Les pourcentages, eux, n'ont pas bougé.

L'écart entre les deux marges n'est pas cosmétique — la marge pays fait entrer
268 crops de plus au-dessus du palier, et **ces crops-là sont moins bien
classés** (84,5 % contre 98,4 %). Dis toujours de laquelle des lignes tu parles,
ou tu compareras deux choses distinctes.

---

## 5. Les trois pièges — une session chacun

### (a) ⛔ Le chemin de base codé en dur

`FINDINGS.md` §8.7. Un entrypoint déclare `DB_PATH = ML_DIR/"state"/"eurio.db"`
et ignore `EURIO_DB_PATH`. **La banque servie a été bâtie pendant des semaines
sur 6205 assets au lieu de 12454** → 125 classes à exemplaires au lieu de 182.

Pourquoi c'est invisible : **une base périmée répond normalement**. Elle rend
des lignes bien formées, simplement moins nombreuses. Pire, `Store()` sur un
chemin inexistant **crée le fichier et bootstrappe le schéma** — sur le VPS, dix
scripts annonçaient « 0 candidats, 0 erreurs » sur une base vide qu'ils venaient
de créer.

Deux formes, toutes deux vivantes dans le repo :

```python
DB_PATH = ML_DIR / "state" / "eurio.db"                            # ⛔ littéral
Store(resolve_db_path(args.db))                                    # ⛔ le --db est un LEURRE
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")   # ✅ repli = la réplique
```

`resolve_db_path` rend `EURIO_DB_PATH` **quel que soit son argument** : sa place
est sur le **défaut**, jamais autour d'`args.db`.

**Les trois contrôles, dans cet ordre :**

1. Le **témoin de volume** dans la sortie du script. `12454` = sain, `6205` =
   base périmée, `1495` ancres = banque à jour (build `365dcab2a253`),
   `1533` / `1250` = périmée. Un script qui
   ne dit pas combien il a vu ne peut pas être vérifié.
2. **Exécuter le point d'entrée, pas le prédicat.** `import m; print(m.DB_PATH)`
   prouve la constante, jamais le câblage :
   ```bash
   env -u EURIO_DB_PATH -u EURIO_DB_READONLY ./.venv/bin/python -m scripts.<x> --help
   EURIO_DB_PATH=/tmp/ailleurs.db          ./.venv/bin/python -m scripts.<x> --help
   ```
3. `go-task ml:encoder-bench:test` — 13 fichiers, dont
   `tests/test_db_path_defaults_cli.py` qui garde la convention **par AST**.
   ⚠️ Il ne garde que la liste qu'on lui donne, et ~39 entrypoints portent
   encore un littéral (dette **C12/M4**).
   ⚠️ **`test_schema_mirror.py` en fait partie, et c'est celui qui rougit après
   toute migration.** Il exige que le DDL d'une migration soit **recopié à
   l'identique** dans `ml/state/schema.sql` *et* déclaré dans son
   `MIROIR_ATTENDU`. Vécu le 2026-08-20 : `0011` ajoute `min_exemplars` au
   `CHECK` de `dino_thresholds`, les deux tests tombent, réparés le même jour.
   Une migration livrée sans son miroir, c'est deux tests rouges qu'on croit
   hérités de quelqu'un d'autre. **Relève ta baseline avant de commencer** —
   `./.venv/bin/python -m pytest tests -q -p no:randomly` rendait *1878 passed,
   0 failed* le 2026-08-20 à 15:39.

### (b) ⛔ Le garde qui ne garde pas

`FINDINGS.md` §8.9 — **sept instances en deux jours**, chaque fois la suite au
vert. On protège le chemin qu'on **a en tête** et jamais celui qui est
**réellement emprunté**. Et la maladie se déplace à chaque correctif : on ferme
le câblage, le prédicat reste faux ; on ferme le prédicat, le détecteur est
aveugle ; on ferme l'écriture, ce sont les **lecteurs** qui deviennent faux.

**Le cas le plus instructif : un garde appelé, sur le bon chemin, qui calcule
faux.** Le bloqueur P3 compare « les prédictions sont-elles postérieures au
build ? » — en **chaînes**, entre deux formats. Reproductible aujourd'hui :

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT SUM(computed_at < '2026-08-20T14:27:56+00:00'),
       SUM(datetime(computed_at) < datetime('2026-08-20T14:27:56+00:00'))
  FROM image_asset_dino_predictions
 WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14';"
# 12454|0
```

⚠️ **Le littéral doit être le `built_at` du build qui a précédé les
prédictions.** Cette skill a porté jusqu'au 2026-08-20 au soir celui du build du
**19** (`2026-08-19T14:36:14+00:00`), alors que les prédictions datent du **20** :
la même requête rendait alors `0|0` et donnait à lire que le défaut n'existait
pas. Prends le `built_at` avec `SELECT built_at FROM dino_anchor_builds ORDER BY
built_at DESC LIMIT 1`, ne recopie pas une date.

`'2026-08-19 23:48:36'` contre `'2026-08-19T14:36:14+00:00'` : l'espace vaut
`0x20`, le `T` vaut `0x54`, donc **toute prédiction paraît antérieure à tout
build du même jour**. Le code (`store/encoder_bench._p3_blockers`) est corrigé ;
la requête écrite dans `GESTE-P3.md` et `PREREQUIS.md` ne l'est **toujours
pas** — ne la recopie pas.

Le contrôle qui fait foi, une commande :

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3; from store.encoder_bench import calibration_blockers
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
print('vitl14:', calibration_blockers(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14'))
print('vits14:', calibration_blockers(c, anchors_kind='2eur_all', encoder_version='dinov2-vits14'))"
# vitl14: []                                  ← aucun bloqueur, banque + prédictions à jour
# vits14: ['P3: aucun build trace …',
#          'P1: couverture utile insuffisante … 0 classes a 2 exemplaires ou plus (attendu >= 118) …']
```

Les bloqueurs d'un encodeur **candidat** sont normaux et par construction :
aucune banque n'a jamais été bâtie sous lui.

Les quatre questions à se poser en posant un garde, dans cet ordre :

1. **Qui écrit vraiment ?** L'inventaire (grep + AST), pas la liste de mémoire.
2. **Le garde est-il en aval de tous ces écrivains ?** Sinon, le descendre dans
   la porte — ou mieux, le remplacer par une contrainte de schéma.
3. **Quelle entrée le fait rendre `[]` à tort ?** Un champ déclaré par
   l'appelant traité comme un fait ; pire, un état sûr encodé par une
   **absence** (`gold_sample_n=None` = « gold entier » ⇒ omettre le champ
   désarme le bloqueur).
4. **Ce correctif rend-il possible un état que le reste du code croit
   impossible ?** C'est la question qui manquait : mettre l'encodeur dans la PK
   (0010) est juste, vérifié, et rend faux **trois lecteurs qu'il n'a pas
   touchés** (Q6/Q8).

### (c) ⛔ La régression à N=1

Traitée au §3. C'est le seul des trois qui soit une propriété de la **donnée**
et pas du code — et **sa parade en dur a été retirée** : le plancher
`min_exemplars` a valu 2 pendant une journée, la mesure restreinte l'a réfuté,
le défaut est revenu à 1. Ce qui reste du piège est le mécanisme mesuré : *le
rang 1 du FPS est le crop le plus atypique de sa classe*. Le levier qui le
corrigerait — amorcer le FPS au médoïde — **n'est pas implémenté**.

---

## 6. Ce qu'on croyait, et qui est faux

| Croyance | Ce qui a été mesuré |
|---|---|
| **DINOv3 > DINOv2** (les benchmarks publics le disaient : +24 % rel. de mAP en recherche d'instance, +10,8 pts sur Met, arXiv 2508.10104) | **Réfuté.** À taille égale (21,6 M contre 22,1 M), `vit_small_p16.dinov3` **78,7 %** contre `dinov2_vits14` **85,9 %** en régime fuité — et `convnext_tiny.dinov3` (27,8 M) plafonne à 81,5 %. McNemar apparié contre `vitl14` : `p ≤ 3,6e-15` sur les trois. Écart **plus large encore en held-out** ⚠️ *(62,6 % et 67,7 % rapportés par la mission du 2026-08-20 ; ces deux nombres ne sont écrits nulle part dans le dépôt et je n'ai pas pu les reproduire — les regénérer avec `ml:refs-curve:run --model timm:… --refs 10` avant de les citer)* |
| « un benchmark public sur une tâche qui **ressemble** à la nôtre transfère » | **Non** — et surtout quand elle ressemble. C'est le résultat de méthode le plus réutilisable du chantier |
| « le gold est propre, la fuite dégraderait le chiffre » | La fuite **gonfle**, et davantage le modèle faible (§3) |
| « coude à N=8 » | Artefact du maillage (§3) |
| « `dino_class_references` est vide partout » (vrai jusqu'au 2026-08-18) | **1495 lignes** dans la réplique depuis le rebuild du 20 à 14:27 (1533 après celui du 19 à 16:36) |
| « le plancher `min_exemplars=2` va améliorer la banque, la courbe le dit » | **Réfuté par la mesure le 2026-08-20** : appliqué, il fait **−1,4 pt** (`vits14`) et **−0,9 pt** (`vitl14`) en held-out à N=10. Le vice est dans l'inférence, pas dans la courbe : **un agrégat extrapolé en règle par classe** (§3). Plancher **retiré** le soir même (défaut revenu à 1) |
| « un exemplaire unique est PIRE que pas d'exemplaire du tout » | **Réfuté dans le sens où on l'affirmait** : donner à 57 classes riches exactement un exemplaire fait **67,6 → 69,1 %** (`vitl14`, p=0,048) et **41,6 → 45,5 %** (`vits14`, p=4,5e-10) sur leurs propres crops (§3, point 2) |
| « le creux à N=1 est réel, donc il faut un plancher » | Le creux vient de l'**ordre** du FPS, pas du nombre : à nombre d'ancres identique, `--rank-order last` le fait disparaître (**77,8 %** contre 73,8 % en `vitl14`). Et en `vits14` il n'est même pas significatif (**p=0,279**) (§3, point 3) |
| « le corpus de scan est vide, 0 photo » | **Faux sur le fond.** 0 capture *versionnée*, mais **2 264 images device** existent (114 `ml/datasets/eval_real_norm`, 2 150 `debug_pull`) — non labellisées, **non répliquées**, ni sur MinIO ni en sauvegarde (`docs/work-in-progress/scan-quality/DURABILITE-CORPUS.md`) |

⚠️ Réserve à porter avec le tableau d'encodeurs : **c'est la tâche REVIEW**,
pas la tâche SCAN. ⚠️ **La distinction n'est PAS « nettes contre floues »** —
beaucoup de photos eBay sont floues, de loin, avec du reflet. Elle est plus
étroite : une photo eBay est **cadrée par un vendeur qui veut montrer la
pièce** (statique, pièce entière, *choisie* parmi plusieurs) ; une frame de scan
n'est choisie par personne. Côté corpus, l'état juste est **0 capture
versionnée pour 2 264 images device non protégées**. Ce classement
décide quel encodeur sert la review ; il ne décide **pas** ce qui part dans
l'APK. Et le FPS a choisi ses crops dans l'espace de `vitl14` : un DINOv3 avec
sa propre banque n'a pas été mesuré (**H13**).

---

## 7. Les gestes, et ce qu'ils coûtent

### Rebâtir la banque

```bash
# depuis la RACINE du dépôt (go-task, jamais task)
go-task ml:dino-anchors:build -- --force --kind 2eur_all              # remplace la banque SERVIE
go-task ml:dino-anchors:build -- --force --kind 2eur_all --no-serve   # artefact de banc seul
```

- **237 s** au rebuild du 2026-08-19 16:36 (source : `FINDINGS.md` §10 ; la
  table `dino_anchor_builds` ne trace pas de durée).
- ⛔ **Sous le devShell (`EURIO_DB_READONLY=1`) la commande refuse de
  démarrer** — le traçage en base est une écriture. Relancer avec
  `EURIO_DB_READONLY=` , ou `--skip-references` pour le `.npz` seul.
- ⛔ **Et aujourd'hui elle refusera de tracer, même hors devShell** : le
  canonique est à la migration **0008**, `dino_class_references` a l'ancienne
  clé. Vérifié :
  ```bash
  cd ml && ./.venv/bin/python -c "
  import sqlite3; from store.dino_references import _exige_encodeur_dans_la_cle
  c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
  try: _exige_encodeur_dans_la_cle(c); print('clé 0010 présente')
  except Exception as e: print(type(e).__name__, str(e)[:120])"
  # CleSansEncodeurError dino_class_references a l'ancienne clé primaire
  # (['anchors_kind', 'asset_id', 'class_id', 'eurio_id']) : `encoder_version` n'en fait pas…
  ```
  Le refus est **bruyant et nomme sa migration** — c'est le bon comportement,
  pas une panne. Les migrations **0009, 0010, 0011 ne sont pas appliquées au
  canonique** ; c'est le redémarrage de `eurio-api` sur le VPS qui les applique
  (**`eurio-vps-deploy`**). À faire **avant** tout premier build d'un encodeur
  candidat, sinon ce build écraserait les références de la production (M1).

  🔍 **Contradiction observée le 2026-08-20, non expliquée — ne t'appuie pas sur
  ce garde comme sur un fait.** Le build `365dcab2a253` du 20 août 14:27 **a
  bien tracé** ses 1495 lignes au canonique (elles sont dans la réplique, avec
  la ligne de `dino_anchor_builds` et sa note), alors que le prédicat ci-dessus
  lève toujours `CleSansEncodeurError` sur cette même réplique et que
  `_schema_migrations` y annonce encore `0008`. L'un des trois est faux : soit
  le canonique porte la clé 0010 sans que la réplique la reflète, soit le pull
  de réplique reconstruit son propre schéma, soit le chemin d'écriture emprunté
  n'est pas celui qu'on croit. **Mesure-le avant de conclure** ; le geste qui
  tranche est de lire le `PRAGMA index_list`/`table_info` du canonique lui-même,
  pas de la réplique.
  ```bash
  sqlite3 -readonly ml/state/eurio.replica.db \
    "SELECT * FROM _schema_migrations ORDER BY 1 DESC LIMIT 1;"   # 0008_dino_thresholds.sql|…
  ```

### Recalculer les prédictions (le geste P3)

```bash
go-task ml:dino-predictions:backfill -- --kind 2eur_all --force --push
```

**Obligatoire après tout rebuild** — sinon la file de review continue de trier
sur les vecteurs de l'ancienne banque.

- **~28 à 41 min** pour 12454 crops (`vitl14` sur MPS) — deux exécutions
  mesurées : 23:20:42 → 23:48:36 le 19 août (28 min), puis 14:28:14 → 15:09:34
  le 20 août contre la banque à plancher (41 min). Mesurés en base :
  ```bash
  sqlite3 -readonly ml/state/eurio.replica.db "
  SELECT COUNT(*), MIN(computed_at), MAX(computed_at) FROM image_asset_dino_predictions
   WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14';"
  # 12454|2026-08-20 14:28:14|2026-08-20 15:09:34
  ```
- Sous `--push` (actif par défaut dès qu'`EURIO_API_URL` est posée, donc dans le
  devShell) le script **pull une réplique scratch neuve** et `--db` est ignoré.
- ⚠️ **M8 : le backfill sort en code 0 même en erreur.** La preuve retenue est
  `calibration_blockers → []`, pas le code de sortie.

### Comparer deux encodeurs

```bash
go-task ml:bench-gold:show                      # ce que contient le gold figé
go-task ml:bench-gold:diff                      # le gold a-t-il dérivé de la base ?
go-task ml:encoder-bench:run -- --models dinov2_vitl14 dinov2_vits14 \
                                --baseline dinov2_vitl14 --out /tmp/bench.md
```

- Le run du 2026-08-20 : 4 modèles × (1958 crops + 1533 ancres) — la banque
  **d'avant le plancher** ; ses niveaux absolus ne décrivent plus la production. Durée horloge
  non tracée ; **≈ 10 min de pur encodage** recalculé depuis les `ms_per_img`
  des payloads (3491 images × (121,7+16,2+16,4+22,3) ms). ⚠️ estimation.
- ⛔ **`--out <un fichier suivi>` fait un `write_text()` du rapport ENTIER** —
  il n'append pas, il **remplace**. Un rerun pointé sur `BENCH-ENCODEURS.md`
  détruit son en-tête humain. Écrire ailleurs, puis recoller le corps.
- Le banc **ré-encode** banque et crops à chaque run : il ne lit aucune
  prédiction stockée. P3 ne peut donc pas fausser le **classement** ; il bloque
  seulement la proposition de seuil.
- ⚠️ **Le run du 2026-08-20 n'a PAS été tracé au canonique.** Ses quatre
  payloads rejouables sont sur disque, et la table cible n'existe pas :
  ```bash
  ls ml/state/encoder_bench_pending/    # 4 JSON du run 20260820T011143Z
  sqlite3 -readonly ml/state/eurio.replica.db \
    "SELECT COUNT(*) FROM sqlite_master WHERE name='encoder_bench_runs';"   # 0
  ```
  ⚠️ Le lien de cause est **inféré, non prouvé** : la migration 0009 n'est pas
  appliquée au canonique, donc le `POST /ingest/encoder-bench` n'avait nulle
  part où écrire. Le script sort alors en code 1 et dépose le payload — c'est
  le comportement documenté, pas un accident.
- ⚠️ **`bank_build_id` d'un run n'est pas une preuve de la banque utilisée.**
  Les 4 payloads du 20 août portent `bank_n_anchors=1533` (la banque du build
  `23c637d93b43`) et `bank_build_id=42d17f9e7083` — un build qui n'a tracé que
  **1250** lignes. Le banc lit les vecteurs dans le `.npz` et l'identifiant en
  base ; sur une réplique en retard les deux divergent sans un mot.

### La courbe

```bash
go-task ml:refs-curve:run -- --model dinov2_vits14 --refs 0 1 2 3 5 8 10
go-task ml:refs-curve:run -- --model dinov2_vits14 --refs 4 5 6 7 8 9 10   # maillage fin
go-task ml:refs-curve:run -- --include-leaked                              # chiffrer l'écart
```

**Lecture seule** : ni base, ni `.npz`, ni push. Elle **ne rebâtit rien** — un
seul encodage, puis sous-échantillonnage de la matrice en mémoire par le `rank`
FPS. **67 s** en vits14, **6 min 48** en vitl14 pour les 7 paliers et les 3
populations (source : COURBE §1). Le garde `check_bank_matches_build` refuse de
mesurer si le `.npz` et le build tracé divergent :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db \
  ./.venv/bin/python -m scripts.bench_refs_curve --refs 0 --limit 5
# banque servie ↔ build 23c637d93b4349e496a2c4b78b741458 : 862 exemplaires appariés,
#   671 canoniques — hypothèse vérifiée
```

---

## 8. Le budget de review qui découle de tout ça

Ordre de priorité, de la plus rentable à la moins (COURBE §4.3) :

1. amener les **547 classes à N=0** (489 avant le plancher) jusqu'à **3** — le seul palier qui quitte le
   régime canonique-seul sans passer par la régression de N=1 (≈ 1 622 crops) ;
2. amener toutes les classes de 3 à **8** — le segment à ~2,5 pts/réf
   (≈ 4 622 crops au total) ;
3. au-delà de 8 : **par arbitrage de budget**, pas parce que ça ne rapporterait
   plus (8→10 vaut encore +1,55 pt significatif).

Repère : **1958 crops décidés depuis le début du projet**. Amener le catalogue
entier à N=8 demande **2,4× tout ce qui a été reviewé jusqu'ici**.

⚠️ Et ce budget suppose qu'il **existe** 8 crops scrapables par classe. Ce n'est
pas acquis. Mesuré sur les classes à zéro exemplaire, en
comptant les crops de la **file ouverte** dont le top-1 DINO tombe dans la
classe :

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3
from collections import Counter
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
poor = [r[0] for r in c.execute('''SELECT class_id FROM dino_class_references
  WHERE anchors_kind=? GROUP BY class_id HAVING SUM(method=\'fps\')=0''', ('2eur_all',))]
byc = dict(c.execute('''SELECT COALESCE(co.design_group_id, co.eurio_id), COUNT(*)
    FROM review_queue rq
    JOIN image_asset_dino_predictions p ON p.asset_id = rq.image_asset_id
    JOIN coins co ON co.eurio_id = p.top1_eurio_id
   WHERE rq.status IN (\'open\',\'in_progress\')
     AND p.anchors_kind=? AND p.encoder_version=? GROUP BY 1''',
   ('2eur_all','dinov2-vitl14')))
b = Counter()
for p in poor:
    n = byc.get(p, 0)
    b['0' if n==0 else '1' if n==1 else '2' if n==2 else '3-4' if n<=4
      else '5-7' if n<=7 else '>=8'] += 1
print(len(poor), dict(b))"
# 547 {'0': 331, '1': 92, '2': 38, '3-4': 31, '5-7': 23, '>=8': 32}
#            ↑ mesuré 2026-08-20 à 17:14 UTC, APRÈS le rebuild à plancher.
#              Avant lui, à ~09:00 : 489 {'0': 305, '1': 78, '2': 36, '3-4': 26,
#              '5-7': 21, '>=8': 23} ; rejouée à 13:43 : 489 {'0': 306, ...}.
#              Le total bouge quand la banque est rebâtie, la répartition bouge
#              en continu : c'est la review qui avance. RELANCE la requête, ne
#              cite pas ces nombres à sec.
```

**331 des 547 n'ont aucun crop en file ouverte** : pour elles le goulot est le
**scrape**, pas la review (→ `eurio-enrichment`) — c'est le chantier n°1 de la
note d'état de `PREREQUIS.md`, ~10 jours de quota eBay. **92 n'en ont qu'un** ;
le plancher les tenait hors banque — **il ne le fait plus** (défaut revenu à 1,
§3), et la mesure restreinte dit qu'un exemplaire unique **aide** sa classe.
Elles entreront donc en banque au prochain rebuild. Seules **32** peuvent viser la cible dès
aujourd'hui.

⚠️ Ce compte est *par prédiction* (crops que DINO **rattache** à la classe), pas
*par cible de scrape*. La même mesure par `source_images.target_eurio_id` rend
433 / 9 / 5 / 12 / 10 / 20. Les deux sont légitimes ; **dis toujours laquelle tu
comptes** — c'est le motif qui a rendu « 59 » et « 0 » pour la même classe.

---

## Ensuite

→ **`eurio-review`** : ce que la banque change à l'écran de review, et pourquoi
  le verdict est aveugle sur les pièces courantes.
→ **`eurio-enrichment`** : quand le goulot est le scrape et pas la review.
→ **`eurio-data-writes`** : dès qu'une écriture répond `readonly database` ou
  `503 canonical_readonly`.
→ **`eurio-vps-deploy`** : appliquer 0009/0010/0011 au canonique.
→ **`eurio-verify`** : avant de déclarer qu'un correctif de banque marche.

Et deux problèmes **posés par écrit, non résolus**, qui touchent directement ce
que la banque sert — ils n'ont pas de skill, ces liens sont leur porte d'entrée :

→ [`docs/work-in-progress/review-autovalidation/PROBLEME.md`](../../../docs/work-in-progress/review-autovalidation/PROBLEME.md)
  — 90 % des reviews demandent un geste humain sur le **crop**, pas sur la
  classe. Améliorer l'encodeur ne touche pas ce goulot.
→ [`docs/work-in-progress/scan-quality/DURABILITE-CORPUS.md`](../../../docs/work-in-progress/scan-quality/DURABILITE-CORPUS.md)
  — les 2 264 images device n'ont aucune réplique.

Et pour l'état complet du chantier, l'ordre des gestes qui attendent le PO et
ce que le plancher a coûté : la **note d'état en tête de**
[`PREREQUIS.md`](../../../docs/work-in-progress/scan-sans-retrain/PREREQUIS.md).

## Ce que cette skill ne couvre PAS

- La **construction** de la banque, pas à pas : `ml/training/foundation/anchors.py`
  (`build_anchors_2eur_all`, `_candidate_crops_for_class`, `farthest_point_select`).
- Le **verdict** d'auto-validation et l'écran de review : `eurio-review`,
  `ml/serving/review_queue/service.py`.
- Le **corpus de scan** et son plan de capture (P5) :
  `docs/work-in-progress/scan-sans-retrain/PROTOCOLE-CAPTURE.md`,
  `go-task ml:scan-corpus:prescribe`. **0 capture versionnée** — rien ici ne dit
  ce que vaudra la banque sur une frame caméra. Sa **durabilité** (2 264 images
  device sans réplique) est un problème posé et non résolu :
  `docs/work-in-progress/scan-quality/DURABILITE-CORPUS.md`.
- La **voie A** (ArcFace, cohorte, bake, entraînement) : `eurio-cohort`,
  `eurio-run-local`, `eurio-promote`.
- Le registre de dette complet (D1..D16, M1..M11, Q1..Q17) :
  [`FINDINGS.md`](../../../docs/work-in-progress/scan-sans-retrain/FINDINGS.md) §8.
