# Pêche filtrée par pays — plan d'implémentation

> Écrit le **2026-08-26**. Toutes les mesures ont été **rejouées ce jour** sur
> `sqlite3 -readonly ml/state/eurio.replica.db` (réplique du canonique,
> rapatriée le 26/08 à 23:20 ; dernières prédictions `2eur_all` du
> **2026-08-24 23:30:56** ; **2 062 ancres**, **671 classes**, **10 076 crops
> ouverts**). Chaque chiffre porte sa requête — recopie la requête, jamais le
> nombre.
>
> Lot **P1** du chantier [`SUIVI.md`](./SUIVI.md).
> Suite de [`../peche-dino/CONSTAT.md`](../peche-dino/CONSTAT.md) et de
> [`../peche-dino/DECISIONS.md`](../peche-dino/DECISIONS.md) §D9, et de
> [`../review-autovalidation/REPRENDRE-ICI.md`](../review-autovalidation/REPRENDRE-ICI.md) §1 et §2.

---

## 0. Ce que la re-vérification change au constat

### 0.a Le filtre `listing_country` est DÉJÀ livré et actif par défaut

La première question posée à ce plan — « filtre dur ou re-classement ? » — est
à moitié périmée. Vérifié au code, pas de mémoire :

| fichier | ligne | signature |
|---|---:|---|
| `ml/serving/review_queue/repository.py` | 653 | `list_queue(… dino_country_only: bool = True)` |
| idem | 950 | `_lot_scope(… dino_country_only: bool = True)` |
| idem | 1112 | `list_lots(…)` |
| idem | 1333 | `dino_candidates_summary(…)` |
| idem | 1607 | `lot_siblings(…)` |
| idem | 1653 | `get_lot_detail(…)` |
| `ml/shared/dino_scope.py` | 453 | `build_dino_scope(… country_only: bool = False)` |

`build_dino_scope` porte le filtre, son **désarmement** quand il viderait la
file (`country_disarmed`), et le compte de ce qu'il masque
(`n_hidden_by_country`). Le front l'expose et le dit
(`PecheBar.vue` l.140-149, `PechePage.vue` l.57 : `?pays=tous`).

**Le reste-à-faire n'est donc pas le filtre. C'est le re-classement — jamais
fait, et c'est là qu'est le gain.**

### 0.b Le biais d'attraction s'est AGGRAVÉ

```sql
-- rejoué le 2026-08-26 (temp tables, ~0,2 s)
CREATE TEMP TABLE ex AS SELECT class_id, COUNT(*) n FROM dino_class_references
  WHERE anchors_kind='2eur_all' AND method='fps' GROUP BY 1;
CREATE TEMP TABLE cls AS SELECT DISTINCT class_id FROM dino_class_references
  WHERE anchors_kind='2eur_all';
CREATE TEMP TABLE peche AS SELECT p.top1_eurio_id t, COUNT(*) n FROM review_queue rq
  JOIN image_asset_dino_predictions p ON p.asset_id=rq.image_asset_id
       AND p.anchors_kind='2eur_all'
 WHERE rq.status='open' GROUP BY 1;
SELECT CASE WHEN COALESCE(ex.n,0)>=2 THEN 'riches' ELSE 'pauvres' END bucket,
       COUNT(*) classes,
       SUM(CASE WHEN COALESCE(peche.n,0)>0 THEN 1 ELSE 0 END) avec_candidats,
       SUM(CASE WHEN COALESCE(peche.n,0)=0 THEN 1 ELSE 0 END) sans_candidat,
       SUM(COALESCE(peche.n,0)) crops,
       ROUND(1.0*SUM(COALESCE(peche.n,0))/COUNT(*),2) par_classe
  FROM cls LEFT JOIN ex ON ex.class_id=cls.class_id
           LEFT JOIN peche ON peche.t=cls.class_id GROUP BY 1;
```

| | classes | avec candidat | **sans aucun** | crops pêchables | par classe |
|---|---:|---:|---:|---:|---:|
| pauvres (< 2 ex.) | 457 | 242 | **215** | 1 926 | **4,21** |
| riches (≥ 2 ex.) | 214 | 209 | 5 | 8 150 | **38,08** |

**Facteur 9,0** (le constat du 24/08 disait 12, et **272** orphelines : elles
sont **215** aujourd'hui — 57 classes ont gagné un candidat).

Et sur les trois classes témoins, la part du pool venant du bon pays a **chuté** :

```sql
SELECT p.top1_eurio_id, COUNT(*) pool,
       ROUND(100.0*SUM(si.listing_country = UPPER(SUBSTR(p.top1_eurio_id,1,2)))
             /COUNT(*),1) pct_bon_pays
  FROM review_queue rq JOIN image_assets a ON a.id=rq.image_asset_id
  JOIN source_images si ON si.id=a.source_image_id
  JOIN image_asset_dino_predictions p ON p.asset_id=a.id AND p.anchors_kind='2eur_all'
 WHERE rq.status='open' AND p.top1_eurio_id IN (
   'it-2002-2eur-standard-1st-map','it-2008-2eur-standard-2nd-map',
   'es-2010-2eur-standard-juan-carlos-i-2nd-type-2nd-map',
   'be-2014-2eur-standard-philippe') GROUP BY 1;
```

| classe | pool 20/08 → 26/08 | bon pays 20/08 → **26/08** |
|---|---|---|
| IT `standard-t1` | 123 → **137** | 50 % → **43,1 %** |
| BE `philippe-t1` | 80 → **130** | 55 % → **29,2 %** |
| ES `juan-carlos-i-t2` | 76 → **107** | 18 % → **5,6 %** |

⚠️ Personne ne l'a vu, parce que ce chiffre n'est publié nulle part.

---

## 1. Où brancher le pays — la réponse en trois temps

### Temps 1 · Filtre dur : fait (D9), ne pas y revenir

### Temps 2 · Le re-classement, là où il est légitime — et il l'est à un seul endroit

Les seuls `design_group` 2 € **multi-pays** du catalogue sont exactement les
5 familles d'émission commune :

```sql
SELECT design_group_id, COUNT(DISTINCT country) pays, COUNT(*) membres
  FROM coins WHERE design_group_id IS NOT NULL AND face_value=2.0
 GROUP BY 1 HAVING COUNT(DISTINCT country)>1 ORDER BY pays DESC;
-- eu-eu-flag-2015 19 pays / 21 membres · eu-erasmus-2022 19/19
-- eu-euro-cash-2012 18/18 · eu-emu-2009 16/16 · eu-rome-2007 13/13
-- total : 5 groupes, 87 membres. Aucun autre.
```

C'est la borne naturelle de la règle : **un crop ne peut être re-classé que
vers un frère de son propre groupe de dessin.** Hors de ces 5 familles, il n'y
a pas de frère : la question ne se pose pas.

**La règle R2, la meilleure des 5 variantes mesurées.** Un crop dont la
prédiction pointe une classe de l'un des 5 groupes entre dans le périmètre de
pêche du **frère du groupe dont `coins.country = source_images.listing_country`**,
sauf si le titre nomme ≥ 2 pays.

```sql
-- population : crops tranchés par un humain, top-1 dans une des 5 familles
CREATE TEMP TABLE gold AS
 SELECT a.id aid, a.eurio_id verite, si.listing_country lc, si.id sid,
        p.top1_eurio_id t1, cg.design_group_id grp,
        (SELECT COUNT(*) FROM json_each(lts.countries_json)) nb_txt
   FROM image_assets a
   JOIN source_images si ON si.id=a.source_image_id
   JOIN image_asset_dino_predictions p ON p.asset_id=a.id AND p.anchors_kind='2eur_all'
   JOIN coins cg ON cg.eurio_id=p.top1_eurio_id
   LEFT JOIN listing_text_signals lts ON lts.source_image_id=si.id
  WHERE a.resolution_status='manual' AND a.eurio_id IS NOT NULL
    AND cg.design_group_id IN ('eu-erasmus-2022','eu-eu-flag-2015','eu-emu-2009',
                               'eu-rome-2007','eu-euro-cash-2012');
CREATE TEMP TABLE r AS SELECT g.*,
 (SELECT s.eurio_id FROM coins s WHERE s.design_group_id=g.grp AND s.country=g.lc
   LIMIT 1) cible FROM gold g;
```

| variante | n | exacts | % |
|---|---:|---:|---:|
| **R0** aucun routage (l'existant) | 397 | 282 | **71,0** |
| **R1** routage sur `listing_country` | 397 | 358 | 90,2 |
| **R2** = R1 + garde « titre à ≥ 2 pays » | 397 | **364** | **91,7** |
| R3 routage sur le pays du TEXTE seul | 397 | 353 | 88,9 |
| R4 = R2 + pas de routage si `is_lot` | 397 | 363 | 91,4 |

Détail de R1 sur les crops **effectivement déplacés** : 122 crops, **96
deviennent justes**, **20 étaient déjà justes et cassent** → net **+76**
(R2 : +82). Par famille :

| famille | n | avant | après R1 | % avant → après |
|---|---:|---:|---:|---|
| `eu-emu-2009` | 114 | 81 | 101 | 71,1 → **88,6** |
| `eu-euro-cash-2012` | 101 | 62 | 89 | 61,4 → **88,1** |
| `eu-eu-flag-2015` | 69 | 49 | 66 | 71,0 → **95,7** |
| `eu-rome-2007` | 63 | 47 | 54 | 74,6 → **85,7** |
| `eu-erasmus-2022` | 50 | 43 | 48 | 86,0 → **96,0** |

Résiduel après routage (39 crops) : **21** « bon dessin, mais le pays de
l'annonce n'est pas celui de la pièce » (coffret multi-pays), **17** mauvais
dessin (hors famille prédite), 1 autre.

**Ce que ça ouvre sur la file ouverte** :

```sql
-- même construction, sur review_queue.status='open'
-- crops ouverts des 5 familles ............................. 1 541
--   masqués aujourd'hui par le filtre pays .................. 1 310  (85 %)
--   effectivement re-routés par R2 .......................... 1 193  (91 % des masqués)
--   dont atterrissant sur une classe PAUVRE ..................  464
-- classes pauvres servies après routage .....................   24
-- classes pauvres à ZÉRO candidat qui en gagnent ............   11
-- classes distinctes atteintes : 59 → 52  (le routage concentre)
```

👉 **Complémentarité exacte** : les 1 193 crops re-routés sont, par
construction (`cible ≠ t1` ⟹ `lc ≠ pays(t1)`), **exactement ceux que le filtre
pays masque déjà**. Le filtre les sort d'une file ; le routage les met dans la
bonne. Les deux mécanismes ne se contredisent pas — le second récupère ce que
le premier jette.

### Temps 3 · Les courantes ne sont PAS re-classées — jetées, et c'est mesuré

```sql
SELECT COUNT(*) n, SUM(cv.country=si.listing_country) verite_pays_annonce,
       SUM(cv.country=ct.country) verite_pays_predit,
       SUM(cv.country=si.listing_country AND cv.is_commemorative=0) dont_courante
  FROM image_assets a
  JOIN source_images si ON si.id=a.source_image_id
  JOIN image_asset_dino_predictions p ON p.asset_id=a.id AND p.anchors_kind='2eur_all'
  JOIN coins ct ON ct.eurio_id=p.top1_eurio_id
  JOIN coins cv ON cv.eurio_id=a.eurio_id
 WHERE a.resolution_status='manual' AND a.eurio_id IS NOT NULL
   AND ct.is_commemorative=0 AND ct.country <> si.listing_country;
-- n=71 · vérité dans le pays PRÉDIT 40 · dans le pays de l'ANNONCE 30
--      · dont une COURANTE du pays de l'annonce : 12
```

Router une courante vers la courante du pays de l'annonce serait juste
**12 fois sur 71 — 17 %**. Et contre-intuitivement, quand le modèle et
l'annonce se contredisent sur une courante, **c'est le modèle qui a plus
souvent raison** (40 contre 30).

**Décision : les courantes du mauvais pays restent masquées, comptées, et
ramenables d'un clic — le comportement déjà livré. Elles ne sont pas routées.**

### ⛔ Le routage est une SUGGESTION, jamais une réécriture

`image_asset_dino_predictions.top1_eurio_id` alimente l'auto-validation
(`ml/training/foundation/auto_validate.py`, règle 4 : `top1 != target →
divergent`), dont la barre mesurée est **99,5 %**
(`review-autovalidation/REPRENDRE-ICI.md`). Le routage vaut **91,7 %**.
Le réécrire ferait entrer une règle de qualité inférieure dans un chemin
d'**écriture automatique**, sans un mot à l'écran. Le routage vit dans
`dino_scope.py` (périmètre) et dans les builders de candidats de
`repository.py` (suggestion affichée), pas en base.

---

## 2. Le pays des 5 familles par le texte — et pourquoi le texte n'est qu'un garde

`listing_text_signals` est remplie sur **10 076 / 10 076** crops ouverts.
Sur les 397 crops gold des 5 familles : 397 ont une ligne, **305** portent au
moins un pays, **299** exactement un.

```sql
SELECT COUNT(*) n, SUM(pays_texte = lc) accord FROM (
  SELECT g.lc, (SELECT json_extract(lts.countries_json,'$[0]')
                  FROM listing_text_signals lts
                 WHERE lts.source_image_id=g.sid
                   AND json_array_length(lts.countries_json)=1) pays_texte
    FROM gold g) WHERE pays_texte IS NOT NULL;
-- n = 299 · accord = 299   →  100 %
```

**Le texte et `listing_country` sont d'accord 299 fois sur 299.** Le texte
n'apporte donc aucune information de pays au-dessus de `listing_country` sur
cette population — et R3 (routage sur le texte seul) est *moins* bon que R1
(88,9 % contre 90,2 %), parce qu'il abandonne les 92 crops dont le titre ne
nomme aucun pays (79 d'entre eux sont pourtant justes après R1).

**Ce que le texte apporte, c'est le VETO** :

| pays nommés dans le titre | n | justes après R1 |
|---:|---:|---:|
| 0 | 92 | 79 |
| 1 | 299 | 279 |
| **5** | **6** | **0** |

Un titre qui nomme 5 pays est un coffret européen : `listing_country` y est un
artefact de la recherche, et router sur lui est faux **6 fois sur 6**. D'où la
garde de R2, qui vaut **+6 crops** (90,2 → 91,7 %).

**Où le brancher** : dans `ml/shared/dino_scope.py`, à côté de
`_era_predicate` — qui lit déjà `listing_text_signals` avec la même sémantique
« le silence n'est pas une contradiction ».

⚠️ **Piège à écrire dans le docstring** : `listing_country` n'est *pas* le pays
du vendeur ni celui de l'annonce, c'est **celui que la recherche visait**
(`ml/sources/ebay/adapter.py:601`, `listing_country=group.country`). La règle
hérite de ce biais. Elle marche quand même — 99,1 % de précision en filtre
(D9), 91,7 % en routage — mais quiconque la lira croira autre chose.

---

## 3. Atteindre les 215 orphelines — l'entonnoir, chiffré

Précision d'une **paire** (crop, classe) proposée, sur 3 253 crops gold :

```sql
SELECT 'top1' r, COUNT(*) paires, SUM(json_extract(j.value,'$.eurio_id')=g.verite) justes
  FROM gold_all g JOIN json_each(g.tk) j WHERE j.key<1;  -- puis <3, <5
```

| générateur de candidats | paires | justes | **précision** |
|---|---:|---:|---:|
| top-1 *(la pêche actuelle)* | 3 253 | 2 885 | **88,7 %** |
| top-3 | 9 759 | 3 017 | 30,9 % |
| top-5 | 16 265 | 3 053 | 18,8 % |
| texte seul (pays + année du titre) | 4 865 | 2 010 | 41,3 % |
| **top-5 ∩ pays+année du texte** | **2 187** | **1 960** | **89,6 %** |
| dont top-1 ∩ texte | 1 875 | 1 854 | 98,9 % |
| dont top-3 ∩ texte | 2 112 | 1 939 | 91,8 % |

**Le résultat qui compte : l'intersection texte × rang-5 est aussi précise que
le top-1** (89,6 % contre 88,7 %), tout en atteignant des classes que le top-1
ne propose jamais. C'est le lot 3.

Sur les **courantes**, à la maille classe (`COALESCE(design_group_id, eurio_id)`),
la même construction s'effondre : top-1 91,7 % · top-1 ∩ pays 97,9 % ·
top-3 ∩ pays **67,7 %** · top-5 ∩ pays **59,1 %**. Le pays ne distingue pas les
ères d'un même pays. → **le palier texte est réservé aux commémoratives.**

### L'entonnoir sur les 215 orphelines

```sql
-- z = classes pauvres (<2 ex.) ET absentes de tout top1 de la file ouverte
SELECT COUNT(*) FROM z;                                          -- 215
-- atteintes par top-3 ................ 140 classes /   771 paires
-- atteintes par top-5 ................ 177 classes / 2 082 paires
-- top-5 ∩ pays+année du texte .........   5 classes /    19 paires
-- texte seul (pays+année), sans rang ..  58 classes / 1 452 paires
-- union top-5 ∪ texte ................ 190 classes atteignables
-- AUCUNE piste ne les atteint .........  25 classes
```

Trois enseignements, tous décisifs :

1. **La pêche par top-k marche pour la couverture, pas pour la précision.**
   Le top-5 atteint 177 des 215, mais à 18,8 % par paire.
2. **L'intersection à haute précision est inopérante ici** : 5 classes sur 215.
   Le texte et le modèle sont rarement d'accord sur une classe que le modèle
   ne connaît pas — c'est la définition même d'une orpheline.
3. **25 classes sont hors de portée de toute règle automatique.** Seul le
   scrape ciblé les atteindra, et il coûte du quota eBay.

Les orphelines par pays (les 38 jamais vues dans aucun top-5) :
PT 6 · MT 5 · SK 4 · SI 4 · MC 3 · GR 3 · LU 2 · HR 2 · FI 2 · SM 1 · NL 1 · LV 1 —
exactement les pays les plus pauvres en ancres, comme le note déjà
`_probe` dans `dino_scope.py`.

👉 **Conclusion pour le lot 4** : pas de file de décision unitaire, mais une
**planche de tri visuel bornée**, qui annonce sa précision. À 19 %, une planche
de 30 vignettes rend ~6 crops justes. Ce geste n'a jamais été chronométré :
**le mesurer sur 5 classes avant de construire les 190.**

---

## 4. Les lots

| # | titre | coût | gain mesuré | risque |
|---|---|---|---|---|
| **0** | Script de mesure rejouable | 0,5 j | condition de mesurabilité des lots 1–4 | — |
| **1** | Routage pays sur les 5 familles | 2–3 j | 71,0 % → **91,7 %** ; **1 193** crops récupérés, **464** vers des classes pauvres, **11** orphelines nourries | moyen |
| **2** | Garde-fou : pas de routage des courantes | 0,5 j | évite une règle juste 17 % du temps | — |
| **3** | Palier « texte » : top-5 ∩ pays+année | 1,5–2 j | **89,6 %** de précision, **+1 336** paires / **175** classes hors top-1, dont **530** / **75** pauvres | faible-moyen |
| **4** | Planche orphelines bornée | 3–4 j | **190 des 215** atteignables, à 19–41 % par paire | **élevé** |

### Lot 0 · Le script de mesure rejouable

**Fichiers** : `ml/scripts/measure_routage_pays.py` (nouveau, stdlib, lecture
seule sur la réplique) · `ml/tasks.yml` (`mesure:routage-pays`).

**Quoi** : rejouer les 12 mesures de ce document et sortir un tableau. Sans
lui, chaque lot se juge sur un chiffre recopié. La banque a bougé deux fois
entre le 24/08 et le 26/08 et **trois** des chiffres du constat étaient
périmés (272 → 215, facteur 12 → 9, ES 18 % → 5,6 %).

### Lot 1 · Le routage par pays d'annonce sur les 5 familles

**Fichiers** : `ml/shared/dino_scope.py` (prédicat de routage + garde titre +
extension de `_probe` pour compter les routés comme elle compte les masqués) ·
`ml/serving/review_queue/repository.py` (périmètre, et le candidat suggéré dans
`_build_dino_top1_candidate` / `_fetch_group_candidates`) ·
`ml/review/review_queue_routes.py` · `ml/tests/test_dino_scope.py` ·
`ml/tests/test_review_queue_dino_peche.py` · front `PecheBar.vue`,
`PechePage.vue`, `useReviewApi.ts`.

**Coût** : 2–3 j. 1 j de SQL + tests, 0,5 j de câblage, 0,5 j de front
(pastille « routé depuis BE » sur le crop — sinon l'opérateur ne comprendra pas
pourquoi un crop d'annonce belge est dans une file lituanienne), 0,5 j de
recette mesurée.

**Gain** : exactitude 71,0 % → **91,7 %** (397 crops gold, +82 net) ;
**1 193** des 1 310 crops aujourd'hui masqués (91 %) reviennent dans une file ;
**464** atterrissent sur une classe pauvre ; **11** classes pauvres à zéro
candidat en gagnent.

**Risque** — moyen, trois points :
- 20 crops gold justes sur 397 deviennent faux (net +82, mais régression
  visible) ;
- le nombre de classes distinctes servies dans les 5 familles passe de **59 à
  52** : le routage concentre sur les pays effectivement scrapés, et une classe
  d'un pays jamais scrapé perd ses (faux) candidats. **L'écran doit le dire**,
  comme le désarmement du filtre pays le dit déjà ;
- `listing_country` = pays visé par la recherche, pas pays du vendeur.

### Lot 2 · Le garde-fou

**Fichiers** : `ml/shared/dino_scope.py` (constante des groupes routables +
docstring) · `ml/tests/test_dino_scope.py` · `DECISIONS.md`.

**Coût** : 0,5 j. **Gain** : évite une extension « naturelle » du lot 1 qui
serait juste **12 fois sur 71**. Un test échoue si la table des groupes
routables reçoit un groupe mono-pays ou une courante.

### Lot 3 · Le palier « texte »

**Fichiers** : `ml/shared/dino_scope.py` (prédicat, à côté de `_era_predicate`)
· `repository.py` · `review_queue_routes.py` · `test_dino_scope.py` ·
`PecheBar.vue`, `PechePage.vue`.

**Coût** : 1,5–2 j. Le SQL est court ; le coût est dans les tests
(`DINO_RANKS` devient rang × mode, et le `422` sur rang inconnu doit continuer
de lever) et dans l'infobulle de précision, comme les paliers de marge.

**Gain** : **89,6 %** de précision par paire (2 187 paires gold), contre 88,7 %
pour le top-1. Sur la file ouverte : 3 633 paires / 251 classes / 3 004 crops,
dont l'ajout réel hors top-1 est **1 336 paires sur 175 classes**, dont
**530 paires sur 75 classes pauvres**.

**Risque** : faible-moyen. Ne couvre que **5 des 215** orphelines — ne pas le
vendre comme la réponse à la couverture. Et c'est un quatrième palier dans une
barre qui en a trois : à mesurer à l'usage avant d'en ajouter un cinquième.

### Lot 4 · La planche orphelines

**Fichiers** : `ml/shared/orphan_scope.py` (nouveau) · `repository.py` ·
`review_queue_routes.py` · `OrphelinesPage.vue` (nouveau) · `app/router.ts`
(`meta: { heavy: true }` si la page tape `:8042`).

**Coût** : 3–4 j, et **le plus incertain**. Page dédiée plutôt qu'un mode de
plus sur `/review/peche`, pour que le contrat « ici, la plupart des
propositions sont fausses » soit lisible à l'entrée. Union `top-5 ∪ texte`,
bornée à 30 crops par classe, triée par rang puis accord texte.

**Gain** : **190 des 215** orphelines deviennent atteignables sans un euro de
quota eBay. Si l'opérateur trouve 2 crops justes par classe, la banque passe de
457 à ~267 classes pauvres.

**Risque — élevé, à jouer en dernier** :
- le temps humain n'est **pas mesuré** : à 18,8 % par paire, une planche de 30
  rend ~6 crops justes ; personne n'a chronométré ce geste. **Mesurer sur 5
  classes AVANT de construire les 190** ;
- une file majoritairement fausse fatigue, et la décision de review est la
  seule donnée du projet qu'aucun calcul ne régénère ;
- les 25 restantes ne relèvent que du scrape ciblé — coût **non chiffré ici**.

---

## 5. Ce qui revient au PO

1. **Suggestion ou réécriture ?** Recommandation ferme : suggestion. Ne jamais
   toucher `top1_eurio_id` — il alimente l'auto-validation (barre 99,5 %) et le
   routage vaut 91,7 %.
2. **Casser 20 crops pour en gagner 96 ?** Net +82 sur 397. Régression visible
   assumée ou non.
3. **Le routage alimente-t-il l'auto-validation des 5 familles ?** Non
   recommandé. La variante haute (routage restreint au top-1 avec accord
   texte) vaut 98,9 % sur 1 875 paires — toujours sous la barre, et à mesurer
   spécifiquement avant tout arbitrage.
4. **Les courantes du mauvais pays : jetées définitivement ?** Oui selon la
   mesure (17 %). Le PO acte que ce stock ne sera récupéré que par l'œil.
5. **Combien de temps humain pour la planche orphelines ?** Il faut une borne
   par classe (proposition : 30 crops) et une borne de session.
6. **Les 25 classes hors de portée : scrape ciblé ou abandon ?** Décision de
   dépense (quota eBay = argent réel), rendement par classe non chiffré ici.
7. **Ordre des lots.** Recommandé : 0 → 1 → 2 → 3, mesurer, puis 4. Le lot 1
   est le seul dont le gain est grand, mesuré et bon marché.
8. **Publier le biais d'attraction en continu** (~0,5 j, hors lots). Il s'est
   aggravé en 48 h sur les trois classes témoins et personne ne l'a vu, parce
   qu'il n'est affiché nulle part. À mettre à l'accueil admin, à côté de
   `GET /dino/drift`.

---

## 6. Ce que ce plan ne traite pas

- La confusion des standards à portrait entre eux : sujet d'encodeur et de
  banque (`../banque-dino/`, `../juge-et-banc/`), pas d'écran. Le routage n'y
  peut rien — la mesure §1 Temps 3 le démontre.
- Le scrape ciblé et son quota : [`PLAN-SCRAPE.md`](./PLAN-SCRAPE.md) et la
  skill `eurio-enrichment`.
- Les pannes de perte de travail humain en review en lot : `Session A` de
  `../review-autovalidation/REPRENDRE-ICI.md`, et le **lot 0** de
  [`SUIVI.md`](./SUIVI.md). **Elles passent avant tout ce document** — une
  décision de review perdue ne se régénère pas.
