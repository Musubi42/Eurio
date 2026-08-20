# La courbe « références par classe » — étape 3

> Mesuré le 2026-08-20. Répond à l'[étape 3 de `DECISION.md`](DECISION.md) :
> *« combien de références wild par classe faut-il ? »* — le chiffre qui
> dimensionne le budget de review, donc la trajectoire du projet.
>
> Outil : `ml/scripts/bench_refs_curve.py` (`go-task ml:refs-curve:run`).
> Tests : `ml/tests/test_refs_curve.py` (`go-task ml:refs-curve:test`).
> Lecture seule en base ; aucun run poussé, aucune banque rebâtie.
>
> **Révisé le 2026-08-20 après vérification adversariale.** Trois corrections
> de fond, toutes appuyées sur une mesure qui contredit la première rédaction :
> le **« coude à N=8 » ne survit pas à un maillage plus fin** et n'est donc plus
> présenté comme un plateau mesuré (§3.5) ; la population held-out **n'est pas
> un plancher prudent**, elle est plus facile de ~5,5 points pour une raison qui
> n'a rien à voir avec la fuite (§5) ; et le gold et la banque **ne tirent pas
> leur vérité de la même colonne**, divergeant sur 5 assets (§5.3). Le reste du
> document — l'appariement `.npz` ↔ base, les effectifs, les niveaux de la
> courbe, la validation du harnais contre le banc officiel — a été recompté
> indépendamment et **tient**.

---

## 🔴 Mise à jour du 2026-08-20 (soir) — la courbe a servi à décider, la décision a coûté, et elle est ANNULÉE

**Ce document a produit une règle : « jamais UN seul exemplaire, zéro ou deux ».
Elle a été implémentée (`min_exemplars = 2`), la banque a été rebâtie avec, le
re-bench a dit qu'elle DÉGRADE — puis la mesure par classe l'a réfutée et le
plancher a été retiré le soir même.**

| held-out, N=10 (= la banque servie) | avant plancher · 1533 ancres, 182 classes à exemplaires | après · **1495 ancres, 124 classes** | delta |
|---|---:|---:|---:|
| `dinov2_vits14` | 75,5 % | **74,1 %** | **−1,4** |
| `dinov2_vitl14` | 85,7 % | **84,8 %** | **−0,9** |

Le contrôle qui autorise la comparaison : **à N=0 les deux banques sont
identiques** (671 canoniques, zéro exemplaire) et rendent le même score à 0,1 pt
près — 53,1 → 53,2 % (`vits14`), 76,1 → 76,2 % (`vitl14`). Les deux populations
held-out sont donc comparables, malgré leur passage de **1100 à 1179 crops**.
*(Rejouable : `go-task ml:refs-curve:run -- --model dinov2_vits14 --refs 0 2 8 10` ;
le rapport de ce re-run n'a pas été persisté sur disque.)*

**La faute de raisonnement, à ne pas refaire.** Le point N=1 de la courbe
ci-dessous (50,1 % contre 53,1 % à N=0) signifie *« TOUTES les classes plafonnées
à un exemplaire »*. Il ne dit **rien** de la situation réelle, où 68 classes en
avaient un et 114 en avaient plus. On a extrapolé d'un **agrégat** à une **règle
par classe** — c'est le vice de raisonnement, pas la mesure. Consigné au journal
des croyances de [`VISION.md`](../../model-efficiency/VISION.md).

**Réserves qui empêchaient de conclure sur ce seul delta** : la banque n'a pas
changé que par le plancher — le FPS a rejoué sur un pool qui avait bougé
(10 classes ont gagné des exemplaires), les crops fuités sont passés de 858 à
779, et 1495 ancres offrent mécaniquement moins de matière que 1533. Curiosité
**non expliquée** : à N=2 la nouvelle banque est **meilleure** (55,9 % contre
54,6 %) avec moins de lignes ; elle ne perd qu'à N=8 et N=10. Le geste qui
tranchait est une mesure **par classe** — il a été fait, cf. ci-dessous.

### ✅ Suite du 2026-08-20 (soir) — la mesure par classe a été faite, le plancher est RETIRÉ

Le geste réclamé ci-dessus a été posé **sans rebuild**, en restreignant la
courbe : `bench_refs_curve.py` a reçu `--bank-classes` (le plafond N ne
s'applique qu'à ces classes), `--gold-classes` (seuls ces crops sont notés),
`--rank-order last` (sonde de mécanisme), et une comparaison appariée par palier
(McNemar exact, `shared/stats/paired.py`).

1. **La population visée est inévaluable** : les classes sans exemplaire mais à
   pool non vide totalisent 77 crops dans le gold, dont **61 sont le crop qui
   deviendrait leur ancre** — il reste **16 crops held-out**.
2. **Un exemplaire unique AIDE sa classe.** Proxy = les 57 classes riches
   plafonnées à 1, 1073 crops : `vitl14` 67,6 → **69,1 %** (p=0,048), `vits14`
   41,6 → **45,5 %** (p=4,5e-10).
3. **Le creux à N=1 vient de l'ORDRE du FPS, pas du nombre.** Non significatif en
   `vits14` (p=0,279) ; en `vitl14`, à nombre d'ancres identique,
   `--rank-order last` rend **77,8 %** au lieu de 73,8 %.

**Décision** : `min_exemplars` revient à **1** (plancher **inactif**) pour les
deux couples. Le mécanisme reste entier et testé ; reposer 2 est une ligne dans
`dino_thresholds`. Le vrai levier — amorcer le FPS au médoïde — n'est **pas**
implémenté.

⚠️ **La banque servie porte encore le plancher, le code ne l'applique plus** :
le prochain rebuild changera sa forme, et le garde P1 ne le signalera pas.

### ⛔ Cette courbe ne simule pas le builder (défaut S6)

`ml/scripts/bench_refs_curve.py` tronque la banque par rang FPS et **n'a aucune
notion de `min_exemplars`** (`grep -n min_exemplars ml/scripts/bench_refs_curve.py`
→ rien). Un palier N est « **toutes** les classes plafonnées à N », jamais « ces
classes-ci à N, les autres pleines » — c'est exactement la confusion qui a fait
poser le plancher. La courbe mesure le **rendement d'un exemplaire
supplémentaire** ; elle ne prédit pas la forme d'une banque réelle.

✅ **Depuis le 2026-08-20 (soir), le script sait poser la question par classe** :
`--bank-classes @fichier` (le plafond ne s'applique qu'à ces classes),
`--gold-classes @fichier` (seuls ces crops sont notés), `--rank-order last`
(sonde de mécanisme). Chaque palier porte en outre sa p-value de McNemar
exact — un écart de courbe sans elle ne se cite plus.

---

## ⚠️ Quatre avertissements avant tout chiffre

1. **C'est la tâche REVIEW, pas la tâche SCAN.** Le gold est fait de photos de
   vendeurs eBay. ⚠️ **La distinction n'est PAS « nettes contre floues »** — une
   bonne part des photos eBay sont floues, prises de loin, avec du reflet. Elle
   est plus étroite et plus solide : une photo eBay est **cadrée par un vendeur
   qui veut montrer la pièce** — statique, pièce entière, *choisie* parmi
   plusieurs. Une frame de scan n'est choisie par personne : elle est prise au
   vol, en main, dans le flux vidéo. La courbe du scan sera donc différente et
   exige le corpus de capture — aujourd'hui **0 capture versionnée**, pour
   **2 264 images device non protégées**
   ([`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md)).
   Rien ici ne dispense de `PROTOCOLE-CAPTURE.md`.
2. **858 des 1958 crops du gold sont eux-mêmes des lignes de la banque.**
   Les noter contre elle, c'est mesurer une similarité de 1,0 avec soi-même.
   Toutes les courbes de ce document sont mesurées **held-out** : 1100 crops
   sur 72 classes. La version fuitée est donnée en annexe, uniquement pour
   chiffrer l'écart — elle vaut **+10,4 points** de global@1 à N=10.
3. **La sélection FPS est celle de `dinov2-vitl14`.** Les rangs viennent du
   build `23c637d93b4349e496a2c4b78b741458` ; on fait varier le *nombre* de
   références à *sélection constante*. C'est ce qui isole la variable étudiée,
   mais un vrai build à N exemplaires avec un autre encodeur choisirait des
   crops un peu différents. ⚠️ estimation : écart probablement petit (le FPS
   optimise la diversité d'apparence, pas l'encodeur), **non mesuré**.
4. **Il n'y a pas de plateau mesuré.** La première version de ce document
   annonçait un « coude à N=8 ». Le maillage fin le dissout (§3.5) et l'analyse
   appariée montre que le segment 8 → 10 rapporte encore un gain
   **statistiquement significatif** (+1,55 pt, 34 crops gagnés contre 17
   perdus, McNemar `z=2,38`, `p≈0,017`). « Viser 8 » reste l'arbitrage
   coût/bénéfice recommandé — mais c'est un **arbitrage**, pas la lecture d'un
   plateau, et **rien n'est mesuré au-delà de N=10**.

---

## 1. Comment la mesure est faite sans rebâtir la banque

Rebâtir la banque sept fois coûterait 7 × 4 minutes d'encodage, et la review
se sert de la banque servie pendant ce temps. On s'en passe :

- les 1533 ancres sont **déjà décrites** par
  `ml/state/foundation_anchors_2eur_all.npz` (`eurio_ids` = class_id de banque,
  `asset_ids`, `source_paths`) ;
- `dino_class_references` porte le **`rank`** de chaque ligne : l'ordre du
  *farthest-point sampling*, rang 1 = l'exemplaire le plus diversifiant ;
- donc on encode **une seule fois** les 1533 sources + les 1958 crops du gold,
  puis pour chaque N on **sous-échantillonne la matrice en mémoire**
  (canoniques + lignes `fps` de rang ≤ N) et on rescore.

Coût réel : **67 s** en `dinov2_vits14`, **6 min 48** en `dinov2_vitl14` — pour
les 7 paliers et les 3 populations à la fois.

### L'appariement `.npz` ↔ base a été vérifié, pas supposé

C'est l'hypothèse dont tout dépend. Mesurée le 2026-08-20 sur
`ml/state/eurio.replica.db` :

```
build 23c637d93b4349e496a2c4b78b741458 (2eur_all, dinov2-vitl14, 2026-08-19T14:36:14)
  .npz : 1533 lignes — 671 canoniques, 862 exemplaires, 671 classes
  base : 1533 lignes — canonical 671, fps 862
  asset_id présents dans le .npz et absents en base : 0
  asset_id présents en base et absents du .npz : 0
  class_id canoniques, différence symétrique : 0
  eurio_ids du .npz == class_id de la ligne de base : 862/862, 0 écart
  rangs fps contigus 1..k : 182 classes sur 182, 0 trou
```

`built_at` du `.npz` (`2026-08-19T14:36:14+00:00`) est celui du build. Le garde
`check_bank_matches_build` refait ces comparaisons **à chaque run** et refuse de
produire un chiffre si elles échouent. Vérifié sur le vrai point d'entrée :

```
$ ./.venv/bin/python -m scripts.bench_refs_curve --db state/eurio.db --refs 0 --limit 5
RuntimeError: Aucun build tracé dans dino_anchor_builds pour (2eur_all, dinov2-vitl14)
  — sans les rangs FPS il n'y a pas de courbe possible. Rafraîchir la réplique.   exit=1
$ EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python -m scripts.bench_refs_curve --refs 0 --limit 5
banque servie ↔ build 23c637d93b43… : 862 exemplaires appariés, 671 canoniques — hypothèse vérifiée   exit=0
```

---

## 2. Les deux lectures — et pourquoi elles se rejoignent ici

Toutes les classes n'ont pas 10 exemplaires. Répartition dans la banque
(`SELECT COUNT(*) … GROUP BY class_id` sur les lignes `fps`) :

| exemplaires | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| classes | 64 | 27 | 7 | 9 | 6 | 5 | 1 | 2 | 6 | 55 |

Donc « la courbe à N=10 » et « la courbe à N=1 » ne portent pas sur la même
population. Deux lectures, jamais mélangées :

| Lecture | Population | Question à laquelle elle répond |
|---|---|---|
| **variable** | toutes les classes held-out, plafonnées à ce qu'elles ont — 1100 crops / 72 classes | ce que vit l'utilisateur : à N demandé, une classe pauvre n'apporte toujours que ce qu'elle a |
| **constante** | seules les classes à 10 exemplaires — 1055 crops / 52 classes | ce qui isole l'effet du nombre : ici le N demandé est le N obtenu |

**Elles donnent presque le même chiffre, et ce n'est pas une bonne nouvelle.**
1055 des 1100 crops held-out (96 %) appartiennent déjà aux 52 classes pleines.
La raison est structurelle : un crop n'est held-out que s'il **n'a pas** été
retenu comme exemplaire — une classe qui n'a qu'un crop validé le voit partir
dans la banque et **disparaît de l'évaluation**. Les 64 classes à 1 exemplaire
ne sont donc quasiment pas observables.

Conséquence à assumer : **la lecture « variable » ne mesure pas ce que vit
l'utilisateur sur le catalogue entier** — elle ne le pourrait pas avec ce
corpus. Ce que l'utilisateur vit sur une classe pauvre, c'est la ligne N=0 ou
N=1 du tableau, appliquée aux **489 classes de banque qui n'ont aucun
exemplaire** (§4). Cette limite se lèvera avec la review, pas avec une
meilleure statistique.

---

## 3. Les courbes

### 3.1 `dinov2_vits14` — le candidat embarqué (22,1 M params, 16 ms/img)

Population **variable** (1100 crops, 72 classes) :

| N réf./classe | lignes de banque | global@1 | global@5 | pays@1 | pays@5 |
|---:|---:|---:|---:|---:|---:|
| 0 | 671 | 53,1 % | 75,5 % | 84,8 % | 95,5 % |
| 1 | 853 | **50,1 %** | 73,3 % | 78,2 % | 95,4 % |
| 2 | 971 | 54,6 % | 78,1 % | 81,4 % | 97,0 % |
| 3 | 1062 | 57,3 % | 80,9 % | 82,6 % | 97,8 % |
| 5 | 1221 | 66,4 % | 87,9 % | 89,0 % | 99,2 % |
| 8 | 1417 | **73,9 %** | 94,3 % | 92,5 % | 99,5 % |
| 10 | 1533 | 75,5 % | 95,0 % | 93,5 % | 99,5 % |

Population **constante** (1055 crops, 52 classes) :

| N | global@1 | global@5 | pays@1 | pays@5 |
|---:|---:|---:|---:|---:|
| 0 | 52,0 % | 74,6 % | 84,2 % | 95,4 % |
| 1 | 48,7 % | 72,2 % | 77,5 % | 95,2 % |
| 2 | 53,6 % | 77,3 % | 80,9 % | 96,9 % |
| 3 | 56,5 % | 80,2 % | 82,2 % | 97,7 % |
| 5 | 65,9 % | 87,5 % | 88,8 % | 99,1 % |
| 8 | **73,8 %** | 94,1 % | 92,5 % | 99,4 % |
| 10 | 75,5 % | 94,9 % | 93,5 % | 99,5 % |

Sur ce maillage, le segment 8 → 10 ne rapporte plus que **0,77 point** de
global@1 par référence ajoutée (0,81 en population constante), contre
2,5 points/réf sur le segment 5 → 8. ⚠️ **Ce n'est pas un plateau** : le
maillage fin (§3.5) montre que ce « 0,77 » moyenne un palier nul (8 → 9) et un
palier significatif (9 → 10).

### 3.2 `dinov2_vitl14` — l'encodeur de production (304,4 M, 122 ms/img)

Population **variable** :

| N | global@1 | global@5 | pays@1 | pays@5 |
|---:|---:|---:|---:|---:|
| 0 | 76,1 % | 88,4 % | 91,5 % | 97,4 % |
| 1 | **72,5 %** | 88,3 % | 86,6 % | 98,0 % |
| 2 | 74,5 % | 90,9 % | 87,6 % | 99,2 % |
| 3 | 76,1 % | 92,1 % | 89,2 % | 99,5 % |
| 5 | 79,6 % | 94,2 % | 92,0 % | 99,5 % |
| 8 | **84,4 %** | 95,9 % | 95,1 % | 99,6 % |
| 10 | 85,7 % | 96,4 % | 96,1 % | 99,5 % |

Population **constante** : 75,6 / 71,7 / 73,7 / 75,6 / 79,3 / 84,2 / 85,7 %
en global@1 pour N = 0/1/2/3/5/8/10 — à moins d'un point de la variable partout.

Même profil, même arbitrage : segment 8 → 10 à 0,68 point/réf sur ce maillage
— avec la même réserve qu'en §3.5, non rejouée en vitl14 (⚠️ estimation : mêmes
ordres de grandeur, la forme de la courbe étant identique entre encodeurs ;
**non mesuré**, ~7 min de run).

### 3.3 Ce que la comparaison des deux encodeurs établit

**La forme de la courbe ne dépend pas de l'encodeur.** Les deux présentent
exactement le même profil — creux à N=1, remontée, écrasement progressif du
rendement au-delà de N≈7 — avec un décalage de niveau constant. C'est le résultat le plus solide du document :
il autorise à décider du **budget de review** indépendamment du choix
d'encodeur, qui reste ouvert.

Corollaire pour le chantier on-device : **8 références par classe rachètent
presque tout l'écart de taille**. `vits14` à N=8 (73,9 % @1, 94,3 % @5) dépasse
`vitl14` à N=1 (72,5 % / 88,3 %) et le talonne à N=3 (76,1 % / 92,1 %) — 2,2
points de moins en @1, mais **2,2 points de PLUS en @5** — pour 14× moins de
paramètres et 7,6× moins de temps. On échange du modèle contre de
la donnée, et c'est le sens même de la voie B ([ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md)).

### 3.4 Le creux à N=1 — la seule surprise, et elle est reproductible

**Ajouter la première référence FPS FAIT BAISSER la précision** : −3,0 points en
vits14 (53,1 → 50,1), −3,6 en vitl14 (76,1 → 72,5), et −6,6 / −4,9 sur la bande
pays. Le phénomène est identique sur les deux encodeurs, sur les deux
populations, et présent aussi sur la courbe fuitée en bande pays. Ce n'est pas
du bruit d'échantillonnage.

L'explication tient à ce qu'est le rang 1 : le FPS choisit **le plus
diversifiant**, c'est-à-dire le crop le plus éloigné du canonique — donc le
plus atypique (angle, éclairage, usure). Seul dans la banque, il agit comme un
faux attracteur : il capte des requêtes d'autres classes avant que ses frères
de rang 2, 3, 4 ne viennent délimiter le nuage de sa propre classe.

⚠️ **Hypothèse non mesurée** : on n'a pas vérifié que les erreurs à N=1 sont
bien des captures par les exemplaires de rang 1. La mesure serait cheap
(compter les top-1 dont la ligne gagnante est une ligne `fps` de rang 1 alors
que la vérité est ailleurs) — à faire avant d'en tirer une règle de sélection.

**Conséquence opérationnelle immédiate** : ne pas mettre **un seul** crop wild
dans la banque d'une classe. Soit zéro (canonique seul), soit trois ou plus.
Le seuil de rentabilité est franchi entre N=1 et N=2 ; la banque ne repasse
au-dessus du canonique seul qu'à **N=2** en vits14, et seulement à **N=5** en
vitl14 — où N=3 rend *exactement* le chiffre de N=0 (76,09 % dans les deux cas,
`courbe-vitl14.json`). Autrement dit : en encodeur de production, **les trois
premières références validées ne rapportent rien du tout**. Elles ne sont pas
perdues — elles sont ce sur quoi la quatrième et la cinquième s'appuient — mais
une classe laissée à 1, 2 ou 3 exemplaires est une classe où l'effort de review
n'a encore rien produit.

### 3.5 🔴 Le « coude à N=8 » ne survit pas au maillage fin — correction

**C'était le résultat le plus vendeur du document, et il était un artefact du
choix des paliers.** Les paliers par défaut sautent de 5 à 8 à 10 : le gain
moyen y vaut 2,52 pt/réf puis 0,77, d'où le verdict « coude à 8 ». Relancé sur
un maillage régulier, **le même détecteur, sur les mêmes données, ne trouve plus
de coude du tout** :

```
$ EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python -m scripts.bench_refs_curve \
    --model dinov2_vits14 --refs 4 5 6 7 8 9 10
population variable : [(4, 62.64), (5, 66.36), (6, 71.18), (7, 72.18),
                       (8, 73.91), (9, 74.09), (10, 75.45)]
knees {'variable': None, 'constante': None}
« Aucun coude dans la plage mesurée : chaque référence supplémentaire
  rapporte encore ≥ 1 point »
```

| segment | 4→5 | 5→6 | 6→7 | 7→8 | 8→9 | 9→10 |
|---|---:|---:|---:|---:|---:|---:|
| points de global@1 par référence | 3,72 | **4,82** | 1,00 | 1,73 | **0,18** | 1,36 |

Le rendement **oscille**, il ne décroît pas proprement. Et le seuil du
détecteur — 1 point de global@1 par référence — est **sous le plancher de
bruit** : sur 1100 crops held-out, 1 point vaut **11 crops**.

**L'analyse appariée, crop par crop, tranche ce que la moyenne cachait.**
Sonde de vérification (réutilise `score_crops` et `subsample_indices`, aucune
écriture), `dinov2_vits14`, population variable :

| segment | gagnés | perdus | net | Δ global@1 | McNemar `z` | lecture |
|---|---:|---:|---:|---:|---:|---|
| 5 → 6 | 63 | 10 | +53 | +4,82 pt | 6,20 | gain massif |
| 6 → 7 | 27 | 16 | +11 | +1,00 pt | 1,68 | non concluant |
| 7 → 8 | 23 | 4 | +19 | +1,73 pt | 3,66 | **significatif** |
| 8 → 9 | 9 | 7 | +2 | +0,18 pt | 0,50 | **bruit pur** |
| 9 → 10 | 25 | 10 | +15 | +1,36 pt | 2,54 | **significatif** |
| 8 → 10 | 34 | 17 | +17 | +1,55 pt | 2,38 | **significatif**, `p≈0,017` |

**Ce qui est réellement établi**, et qu'on peut écrire sans se tromper : *le
rendement chute d'un facteur ~4 entre N=5-6 et N=7 ; au-delà il devient
indiscernable palier par palier sur 1100 crops, tout en restant significatif
sur deux paliers cumulés.* Le segment que la première rédaction proposait
d'abandonner (8 → 10) rapporte un gain réel et mesurable.

**Conséquences sur les recommandations** :

- « viser 8 » reste défendable — comme **arbitrage coût/bénéfice** (2,5 pt/réf
  avant, ~0,8 après), pas comme lecture d'un plateau ;
- « **ne pas dépasser 10** » n'est appuyé par **aucune mesure** : 9 → 10 gagne
  encore 1,36 pt significatif, et le plafond `exemplars_per_class = 10` est une
  borne du build, pas un résultat ;
- résoudre le coude à ±1 référence demanderait soit plus de crops held-out,
  soit un seuil choisi **au-dessus du bruit** et justifié. Le détecteur
  `diminishing_returns()` garde sa valeur (il refuse un faux coude à N=0), mais
  son seuil de 1 pt/réf est à revoir.

⚠️ L'analyse appariée n'a été faite qu'en `dinov2_vits14`, population variable.

---

## 4. La traduction opérationnelle — le budget de review

### 4.1 Un crop validé ≈ une référence

Mesuré sur la réplique, en comparant le pool de crops décidés par classe au
nombre de lignes `fps` retenues :

```
classes dont le pool de crops décidés ≥ 8  : 65
classes dont la banque porte ≥ 8 exemplaires : 63     → 97 % de conversion
classes dont le pool ≥ 10                   : 57
classes dont la banque porte 10 exemplaires : 55      → 96 %
```

Le plancher de validité (`floor_sim = 0.45`) et le plafond
(`exemplars_per_class = 10`) ne coupent quasiment rien. **Valider un crop de
plus sur une classe pauvre, c'est ajouter une référence de plus** — au taux de
change près de ~3 %.

### 4.2 Combien de crops pour amener une classe pauvre au niveau utile

| Cible | ce que ça achète (vits14, held-out) | crops à valider **par classe partant de zéro** |
|---|---|---:|
| N = 0 | 53,1 % @1 · 75,5 % @5 | 0 |
| N = 1 | **régression** — à éviter | 1 |
| N = 3 | 57,3 % @1 · 80,9 % @5 | ~3 |
| N = 5 | 66,4 % @1 · 87,9 % @5 | ~5 |
| **N = 8** | **73,9 % @1 · 94,3 % @5** | **~8** |
| N = 10 | 75,5 % @1 · 95,0 % @5 | ~10 |

**La règle : viser 8 crops validés par classe et ne jamais s'arrêter à 1.**
Huit est un **arbitrage** — au-delà, le rendement tombe d'environ 2,5 à ~0,8
point par référence — et non un plateau : 9 → 10 rapporte encore 1,36 point
significatif (§3.5). Au-delà de 10 rien n'est mesuré, et le plafond
`exemplars_per_class` fait que les crops supplémentaires ne rentrent plus dans
la banque du tout — ils servent
l'entraînement ArcFace (voie A), pas la banque (voie B). Or la médiane du pool
des 55 classes déjà pleines est de **25 crops décidés** : ces classes ont été
sur-reviewées d'un facteur 2,5 pour la voie B.

### 4.3 Le budget total, mesuré

`SELECT` sur les 671 classes de banque, en comptant ce qui manque à chacune :

| Cible | crops à valider (671 classes) | dont classes à zéro exemplaire |
|---|---:|---:|
| N = 3 | 1 622 | 489 |
| N = 5 | 2 805 | 489 |
| **N = 8** | **4 622** | 489 |
| N = 10 | 5 848 | 489 |

Repère : **1 958 crops décidés au total depuis le début du projet**. Amener le
catalogue entier à N=8 demande donc **2,4× tout ce qui a été reviewé jusqu'ici**.

**489 classes sur 671 (73 %) sont aujourd'hui à N=0**, c'est-à-dire au
canonique Numista seul. 🔴 **Depuis le rebuild à plancher du 2026-08-20 14:27,
c'est 547 sur 671 (82 %)** — le plancher a ramené 68 classes de plus au régime
canonique-seul, et **331 d'entre elles n'ont aucun crop en file ouverte**
(mesuré le 2026-08-20 à 17:14 UTC ; requête dans la skill `eurio-banque` §8).
Le budget ci-dessous est donc une **borne basse**. C'est là qu'est le gisement, et il est très inégal :
les 3 000 premiers crops (N=5 partout) valent plus que les 1 200 derniers
(N=8 → N=10, dont on vient de mesurer qu'ils rapportent 0,8 point/réf).

**Ordre de priorité qui découle de la courbe** — de la plus rentable à la
moins :

1. amener les 489 classes de 0 à 3 (le seul palier où l'on quitte le régime
   « canonique seul » sans passer par la régression de N=1) ;
2. amener toutes les classes de 3 à 8 (le segment à 2,5 points/réf) ;
3. ne rien faire au-delà de 8 tant que le point 1 n'est pas fini — **par
   arbitrage de budget, pas parce que ça ne rapporterait plus** : 8 → 10 vaut
   encore +1,55 pt (§3.5). C'est la comparaison qui décide : ~1 300 crops pour
   +1,5 pt sur les classes déjà riches, contre ~1 600 crops pour sortir 489
   classes du régime « canonique seul ».

### 4.4 Ce que ce budget ne couvre pas

Il suppose qu'il **existe** 8 crops scrapables et tranchables par classe. Ce
n'est pas acquis pour les commémoratives rares : c'est le sujet de
`eurio-enrichment`, pas de ce document. Le budget est une borne *inférieure*
de l'effort.

---

## 5. Annexe — les deux populations, et ce qui les sépare vraiment

La courbe « fuitée » note les 1958 crops du gold, y compris les 858 qui **sont**
des lignes de la banque. C'est le protocole du banc d'encodeurs actuel
(`ml/scripts/bench_encoder_dino.py`).

| N | vits14 fuité | vits14 held-out | écart | vitl14 fuité | vitl14 held-out | écart |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 47,7 % | 53,1 % | −5,4 | 70,5 % | 76,1 % | −5,6 |
| 3 | 65,5 % | 57,3 % | +8,2 | 79,0 % | 76,1 % | +2,9 |
| 5 | 75,5 % | 66,4 % | +9,1 | 84,3 % | 79,6 % | +4,7 |
| 8 | 83,6 % | 73,9 % | +9,7 | 89,7 % | 84,4 % | +5,3 |
| 10 | **85,9 %** | **75,5 %** | **+10,4** | **91,6 %** | **85,7 %** | **+5,9** |

### 5.1 ⚠️ La ligne N=0 ne mesure PAS une fuite — correction

**À N=0, la banque est faite des seuls canoniques : aucune fuite n'est
possible.** Et l'écart subsiste : held-out 53,1 % contre 47,7 % sur les 1958
crops (vits14), 76,1 % contre 70,5 % (vitl14). Les 858 crops écartés valent
donc **40,8 %** à eux seuls — `(934 − 584) / 858`.

La cause est structurelle et n'a rien à voir avec la fuite : **le FPS retient
les crops les plus diversifiants, donc les plus atypiques, donc les plus
durs** — et ce sont exactement ceux qu'on exclut en passant en held-out. La
population held-out est **mesurablement plus facile de ~5,5 points**.

Conséquence à assumer : **la courbe held-out n'est pas un plancher prudent.**
Son niveau absolu est optimiste lui aussi, pour une raison différente de celle
qui gonfle la courbe fuitée. Les deux biais jouent en sens contraire selon le
palier — la fuite l'emporte dès N=1 — ce qui interdit de corriger l'une par un
décalage constant. ⚠️ **estimation** : rien ne garantit que l'écart de 5,5 pts
soit stable aux paliers supérieurs, **non mesuré** ailleurs qu'à N=0.

### 5.2 Ce que la fuite coûte, aux paliers où elle existe

Deux choses à en tirer.

**Première : le harnais est validé.** Les valeurs fuitées à N=10 — 85,9 % @1 /
97,2 % @5 / 96,0 % pays@1 pour vits14, et 91,6 % / 97,9 % / 97,4 % pour
vitl14 — **reproduisent au dixième de point** le tableau publié dans
[`BENCH-ENCODEURS.md`](BENCH-ENCODEURS.md). Ce script mesure bien la même
chose que le banc officiel, à la population près.

**Seconde : les chiffres publiés du banc d'encodeurs sont gonflés par la
fuite** — de 10,4 points pour vits14, de 5,9 pour vitl14. Et l'écart n'est pas
uniforme : il est **presque deux fois plus grand pour le petit encodeur**, ce
qui rétrécit l'écart apparent entre les deux (5,7 points en fuité, 10,2 en
held-out). ⚠️ Le **classement** des encodeurs n'est pas retourné pour autant
— dans les deux régimes vitl14 devance vits14 — et le McNemar de
`BENCH-ENCODEURS.md` reste valide sur sa propre population. Mais un seuil
d'auto-acceptation calibré sur le régime fuité serait optimiste.

**À faire (hors périmètre de cette mission)** : ajouter au banc d'encodeurs une
bande held-out, ou au minimum tracer `n_leaked` dans `encoder_bench_runs`. Le
défaut n'est pas dans le classement, il est dans le niveau absolu — et c'est le
niveau absolu qu'on lit quand on décide si le scan est « assez bon ».

### 5.3 🔴 Le gold et la banque ne tirent pas leur vérité de la même colonne

Trouvé en vérifiant la courbe, **hors de son périmètre mais réel**. Le gold est
bâti sur `review_queue.decided_eurio_id` (`selection_sql` du sidecar
`encoder_bench_gold.meta.json`) ; la banque, sur `image_assets.eurio_id`
(`_candidate_crops_for_class`, `training/foundation/anchors.py:794-818`). Les
deux colonnes **divergent sur 5 assets** de l'intersection — donc **5 ancres de
la banque portent une classe que la review contredit**, des faux attracteurs
par construction.

Exemple : `e7d4caa900364c67aa9a53f697591087` — gold
`de-2020-2eur-german-polish-reconciliation` (décidé le 2026-06-15 par `admin`),
`image_assets.eurio_id` `de-2020-2eur-brandenburg-the-bundeslander-series`
(`resolution_status='manual'`), ligne `fps` de rang 2 du build `23c637d93b43`.
Les quatre autres : `5602672b…` et `d3af872b…` (fi-2016 von Wright contre
fi-2016 Eino Leino), `dc16d9e7…` (fi-2017 indépendance contre fi-2009 Porvoo),
`e8ef3523…` (Brandebourg, même cas).

**Impact sur cette courbe : négligeable** (5 sur 862, tous dans la population
fuitée puisque exclus du held-out). **Impact ailleurs : non tranché** — on n'a
pas déterminé laquelle des deux colonnes a raison, ni si `image_assets.eurio_id`
a été requalifié après le gel du gold (sidecar `db_mtime`
`2026-08-19T00:22:48Z`, décisions de juin). Trancher demande de lire le journal
de requalification au canonique. Consigné en **Q13** de
[`FINDINGS.md`](FINDINGS.md) §8.10.

---

## 6. Ce qui reste ouvert

- **La courbe du scan.** Corpus de capture vide. Rien de ce document ne
  transfère automatiquement à une frame caméra.
- **Le creux à N=1 n'est qu'expliqué, pas démontré** (§3.4). La sonde est
  cheap ; si l'hypothèse tient, elle suggère de ne pas prendre le rang 1 seul
  mais un exemplaire *médian* quand une classe n'en a qu'un.
- **Au-delà de N=10**, rien n'est mesuré : le plafond
  `exemplars_per_class = 10` est celui du build, pas une limite du protocole.
  Un build à 20 dirait s'il existe un plateau, et **où**. La question est
  devenue plus pressante depuis §3.5 : puisque 9 → 10 rapporte encore 1,36 pt
  significatif, on ne sait tout simplement pas ce qu'on laisse sur la table.
  Le coût est un rebuild de banque — donc une décision, pas un run de plus.
- **Le seuil du détecteur de coude** (1 pt/réf) est sous le plancher de bruit
  de la population held-out (1 pt = 11 crops). À choisir au-dessus du bruit,
  et à justifier, avant de refaire dire « coude » à ce script (§3.5).
- **Le désaccord gold ↔ banque sur 5 assets** (§5.3) : quelle colonne fait foi.
- **L'effet de la sélection FPS** vs. une sélection aléatoire de N crops :
  non mesuré. C'est ce qui dirait si le FPS mérite sa complexité.
