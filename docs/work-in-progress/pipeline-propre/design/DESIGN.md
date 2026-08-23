# Design — `/besoin`, le poste de pilotage de l'enrichissement DINO

> **⚠️ DOCUMENT DE DESIGN — il dit l'INTENTION, pas l'état.**
> Écrit en phase D6, avant l'implémentation. Tout a été livré depuis (lots 0-6,
> commits `643d6487..64409be8`) : **pour savoir où en est le code, lire
> [`../REPRENDRE-ICI.md`](../REPRENDRE-ICI.md)**, pas ce fichier. Il reste la
> référence sur le PARCOURS, les ÉTATS et le VOCABULAIRE (§5) — et sur ces
> points il fait toujours autorité.
>
> Les maquettes de ce dossier sont **jetables** : HTML statique autonome, elles ne sont pas du code
> de production et ne doivent pas être copiées dans `studio-local`.
>
> Écrit le **2026-08-22**, en session avec le PO. Banque de référence :
> `a55e6594da3247ec80bc609f93342f51`, `built_at 2026-08-22 18:06:22`, 1909
> ancres. **Chaque chiffre porte sa requête ou son champ `ClassNeed`** — et
> chaque chiffre bouge : la banque a été rebâtie deux fois pendant la session,
> et les verdicts de 14 classes ont changé sans qu'un seul crop soit tranché.

---

## 1. Ce que la page répond

Trois questions, dans cet ordre, et aucune autre :

1. **Où j'en suis** — la répartition des 671 classes par nombre d'exemplaires.
2. **Ce que ça coûte de finir** — en crops à trancher, et en annonces eBay.
3. **Qu'est-ce que je fais maintenant** — un geste, cadré, qui s'arrête tout seul.

Ce n'est **pas** `/coins` (qui parle de pièces), **pas** un écran de review (on
n'y tranche rien), **pas** le préflight de cohorte (voie A, `min_real`).

---

## 2. Le parcours, en une page

```
                     ┌──────────────────────────────────────────┐
      j'ouvre  ────►  │  /besoin                                 │
      l'admin        │  ┌────────────────────────────────────┐  │
                     │  │ COUVERTURE  250/671   ███████░░░░░ │  │  ← palier 1
                     │  │ PROFONDEUR  Σ 4 066   ████░░░░░░░░ │  │  ← palier 2
                     │  │ REBUILD     1 451 acquis → 76      │  │  ← la boucle
                     │  └────────────────────────────────────┘  │
                     │                                          │
                     │  ┌── TRANCHER ────┐  ┌── ACHETER ─────┐  │
                     │  │ 908 à portée   │  │ 3 158 à chercher│  │
                     │  │ [▶ prendre]    │  │ [▶ plan] heavy │  │
                     │  └───────┬────────┘  └────────┬───────┘  │
                     │          │                    │          │
                     │  ┌───────┴────────────────────┴───────┐  │
                     │  │  671 lignes · verdict · geste      │  │
                     │  └────────────────────────────────────┘  │
                     └───────────┬──────────────────────────────┘
                                 │  1 clic
                                 ▼
                     ┌──────────────────────────────────────────┐
                     │  /besoin/session  (= la pêche, cadrée)    │
                     │  classe 12/147 · 41 crops · 12 acquis     │
                     │  ┌────────┐                              │
                     │  │ [crop] │  accepter / écarter / passer  │
                     │  └────────┘                              │
                     │  ✓ classe couverte → classe suivante     │
                     └───────────┬──────────────────────────────┘
                                 │  « rendre la main »
                                 ▼
                            retour à /besoin,
                        les compteurs ont bougé
```

**Clics entre « j'ouvre l'admin » et « je tranche le premier crop » : 1.**

---

## 3. Les décisions prises avec le PO

Sept décisions, à verser dans [`../DECISIONS.md`](../DECISIONS.md). Les trois
dernières sont **nouvelles** (D7, D8, D9) ; les quatre premières précisent ou
closent des décisions existantes.

### 3.1 · La Station 1 entre dans la page *(précise O2 §Où elle vit)*

O2 mettait le plan de scrape hors périmètre (« l'allocateur tourne en CLI et ça
suffit »). C'est intenable : **288 des 671 classes ont le verdict `scrape`, et
274 d'entre elles n'ont jamais été visées par une seule annonce eBay.** Une page
qui ne leur propose aucun geste laisse 43 % du catalogue sans réponse.

La page a donc **deux moitiés** : TRANCHER et ACHETER. La moitié ACHETER est
`heavy` (elle a besoin d'`api_call_log` dans `eurio.local.db`, et le préflight
quota de `sources/cli.py` est faux d'un facteur ~130 — les deux réserves de
FLOW-ADMIN §Station 1 doivent être **portées à l'écran**).

### 3.2 · D7 — Deux paliers, pas une cible unique *(nouveau)*

L'A/B médoïde du 2026-08-22 (JOURNAL) change la forme de la courbe :

| N | bras `fps` | bras **médoïde** |
|---:|---:|---:|
| 0 | 76,2 % | 76,0 % |
| 1 | 71,8 % | **86,8 %** |
| 10 | 84,3 % | 88,0 % |

Sous `fps`, la courbe montait tout du long — c'est de là que venait « 8 ». Sous
médoïde, **le premier exemplaire vaut +10,8 points et les neuf suivants +1,2 à
eux tous.**

La page affiche donc **deux barres** :

| palier | définition | état | reste |
|---|---|---|---|
| **1 · couverture** | `have ≥ 1` | **250 / 671** | 147 classes à portée, 274 à scraper |
| **2 · profondeur** | `have ≥ target` (8, ou 5 en émission commune) | Σ `need` **4 066** | 908 à portée |

Le tri par défaut sert le palier 1 : une classe à `0/8` avec 3 candidats passe
devant une classe à `5/8` avec 40.

⚠️ **Réserve à lever.** Le `N` de cette courbe est **plafonné par ce que chaque
classe possède** : à N=1, seules les 250 classes qui ont au moins un exemplaire
bougent. Une courbe « exactement 1 exemplaire partout » est nécessaire pour
confirmer. Elle est demandée à la session ML — cf.
[`QUESTIONS-OUVERTES.md`](QUESTIONS-OUVERTES.md) Q1.

D7 **ne contredit pas D1**, elle la hiérarchise : la cible 8 reste la cible.

### 3.3 · « Parqué » (D3) : la question ouverte est close, rien à construire

D3 laissait le mécanisme à concevoir (« nouvelle `lane`, statut, ou simple
filtre »). **Le troisième terme est déjà implémenté** :

- `need_filter_clause()` (`ml/serving/review_queue/repository.py:123`) calcule
  le complément à la volée depuis `class_need` ;
- `RunParked` (`models.py:200`) le compte en **deux causes** : `full_class`
  (classe à sa cible) et `no_prediction` (pas de top-1 dans `2eur_all` — on
  ignore où le crop tombe, donc on ne le sert pas).

Aucune `lane`, aucun statut, **aucune écriture**, réversible en levant le
filtre. Il manque uniquement le **même compte, global et par classe** : il
n'existe aujourd'hui que par run.

### 3.4 · D9 — `need_only` devient le régime par défaut *(nouveau)*

Exigence du PO, mot pour mot : *« dans les reviews je ne veux absolument pas
avoir à review des crops où la classe a déjà plus de 8 enrichissements ».*

`need_only` existe de bout en bout depuis le 2026-08-21, mais il est **opt-in**
(`?need=1`) et **la pêche ne le passe pas du tout** (`PechePage.vue` ne l'émet
nulle part). Le défaut se **renverse** : la file sert le besoin, et on lève le
filtre explicitement (`?need=0`), jamais l'inverse.

Mesuré ce soir, l'enjeu : **4 804 des 6 574 crops ouverts (73 %) tombent dans
une classe à sa cible.**

```sql
-- via shared.class_need.all_needs(anchors_kind='2eur_all',
--                                 encoder_version='dinov2-vitl14')
-- Σ pending où bottleneck == 'pleine'  → 4804
-- Σ pending où bottleneck == 'review'  → 1770
```

### 3.5 · D8 — `accepted_pending` : ce qui est acquis mais pas encore bâti *(nouveau)*

**Le problème.** Accepter un crop écrit `training_eligible = 1`. Ça n'ajoute
**aucun exemplaire à la banque** : `have` ne bouge qu'au `build_dino_anchors`
suivant. C'est l'arête que FLOW-ADMIN §3 signale comme « la seule qui n'existe
aujourd'hui sous aucune forme ». Conséquence : pendant une session, `have` est
figé, `bottleneck` est figé, et **la file continue de servir une classe qu'on
vient de remplir** — D9 seule ne suffit donc pas à tenir l'exigence du PO.

**Le remède.** `ClassNeed` gagne un champ :

```python
accepted_pending: int   # crops training_eligible=1, storage present, face != reverse,
                        # dont l'asset_id n'est dans AUCUNE ancre de la banque
```

et `bottleneck_for` compte `have + accepted_pending` contre `target`.

Mesuré au moment d'écrire :

```
crops acceptés hors banque                 1 451
  ce qu'un rebuild poserait                   76 exemplaires
  classes qui deviendraient pleines             8
  classes qui sortiraient de zéro              10
  couverture 250/671 → 260/671
```

Le rapport 1 451 → 76 est aussi **la mesure directe de la sur-review** : le
reste tombe dans des classes déjà pleines. Cas extrême mesuré :
`at-2002-2eur-standard-1st-map`, **138 crops acceptés hors banque** pour un
plafond de 10.

**La page affiche ce qu'un rebuild poserait et propose le geste. Elle ne le
déclenche jamais toute seule** — un rebuild déplace les prédictions de toute la
file, donc les verdicts, en pleine session.

### 3.6 · Le pool compté est le pool **scopé**, et O4 devient un prérequis d'O2

Le verdict lit `pending_scoped` (filtres O4 appliqués), pas `pending`. Sans ça,
la page annonce 13 candidats et la pêche en sert 0 — exactement le « badge qui
annonce 4 au-dessus d'une file qui en sert 3 » que `class_need.py` se donne du
mal à éviter.

**La mesure qui rend O4 non optionnel.** En appliquant le filtre pays — *actif
par défaut aujourd'hui* — au pool de chaque classe :

```
classes 'review'                                  293
  que le filtre pays viderait ENTIÈREMENT         147  (50 %)
  crops rendus inatteignables                     558
  LU 14 · PT 13 · GR 12 · VA 12 · MC 10 · FI 9 · LT 9 · SM 9 · LV 8 · MT 8

palier 1 : sur les 147 classes à zéro AVEC candidats,
           120 seraient vidées par le filtre pays        (82 %)
```

VISION §V3 mesurait 137/338 (41 %) ; c'est désormais **50 % des classes en
besoin et 82 % du palier 1**. Autrement dit : **sans le désarmement automatique
d'O4c, le palier 1 fait 27 classes au lieu de 147.**

> **Conséquence sur l'ordre du chantier.** DECISIONS.md ordonne « design O2 + O4
> (D6), puis implémentation ». Il faut préciser : **O4c (le désarmement pays) se
> livre AVANT O2**, sinon O2 affiche un écran faux le jour de son branchement.

Requête de la mesure :

```sql
SELECT p.top1_eurio_id, si.listing_country, COUNT(*)
  FROM review_queue rq
  JOIN image_assets a  ON a.id = rq.image_asset_id
  JOIN source_images si ON si.id = a.source_image_id
  JOIN image_asset_dino_predictions p ON p.asset_id = rq.image_asset_id
       AND p.anchors_kind='2eur_all' AND p.encoder_version='dinov2-vitl14'
 WHERE rq.status='open' AND p.top1_eurio_id IS NOT NULL
 GROUP BY 1,2;
-- puis, par classe : n_same_country == 0 AND pending > 0  →  le filtre vide
```

### 3.7 · Émissions communes (D4) : même écran, variante à la ligne

87 classes, dont **51 à zéro** — mais elles ne pèsent que **7 % de la file en
besoin** (leurs 1 030 crops ouverts sont presque tous dans des classes déjà
pleines). Elles ne justifient pas une seconde surface.

Elles restent dans la liste, avec leur cible 5 et un marqueur `◈`. Ce qui change
est **local à la ligne et à la pêche qu'elle ouvre** : le titre de l'annonce
passe au premier plan devant la vignette, et le pays de la classe est rappelé en
grand. Pas de mode, pas d'onglet.

### 3.8 · Hébergé : lire oui, trancher non

`/besoin` est **entièrement lisible en hébergé** — l'état, les deux paliers, les
671 lignes, les verdicts, le coût du scrape. C'est du SQL pur sur le canonique.

« Prendre » et « plan » sont `heavy` et se grisent avec `LocalOnlyNotice`.

**Constat mesuré, à verser en question ouverte** : la review est `heavy` pour
deux raisons seulement — le **rendu des images** (`${ML_API}/images/…`,
`/referential/canonical/…/thumb` : `useReviewApi.ts:210`, `useLotReview.ts:165`)
et l'**édition de lots** (`add-crop`/`sync-crops`, seuls à toucher cv2). Les
**décisions partent déjà au canonique**. Or les crops vivent dans MinIO, public
en HTTPS. Une review hébergée en mode single n'est donc pas bloquée par
l'architecture. Cf. [`QUESTIONS-OUVERTES.md`](QUESTIONS-OUVERTES.md) Q3.

---

## 4. Les surfaces, état par état

### 4.1 · Le bandeau (haut de `/besoin`)

Trois blocs, toujours visibles, jamais repliés.

| bloc | ce qu'il montre | champ / source |
|---|---|---|
| **COUVERTURE** | `250/671` + histogramme `have` | `ClassNeed.have` |
| **PROFONDEUR** | `Σ 4 066` + `908 à portée` | `Σ need`, `Σ min(need, pending_scoped)` |
| **REBUILD** | build_id, built_at, `1 451 acquis → 76` | `dino_class_references.build_id/built_at`, `Σ accepted_pending` |

**L'en-tête nomme la banque.** `banque a55e6594 · 2eur_all / vitl14 · bâtie le
22/08 18:06`. Non négociable : la banque a été rebâtie deux fois pendant la
session de design, et 14 classes ont changé de verdict sans qu'un crop soit
tranché. Sans cette ligne, deux personnes lisent deux vérités et se croient en
désaccord.

**L'histogramme** — mesuré, c'est la « répartition » que le PO demande :

```
have  0    1   2   3   4   5   6   7   8   9  10
     421  66  35  25  15   9  12   5   3   9  71
     ███████████████████░░░░░░░░░░░░░░░░░░░░████
     └──── palier 1 : 421 à sortir ─────┘   └ pleines ┘
```

### 4.2 · La ligne de classe

```
CLASSE                        BANQUE          CANDIDATS              GOULOT   GESTE
be-2015-…year-for-development  7/8 ███████· +2  72 · 2 masqués pays   review   → prendre
lu-2002-…henri-i-1st-map       1/8 █······  +2  66 · pays désarmé     review   → prendre
ad-2024-…skiing-in-andorra     0/8 ········     2 · 0,214             review   → prendre
va-2019-…sede-vacante          0/8 ········     0 · rien scrapé       scrape   → plan VA
at-2015-…flag ◈                0/5 ·····   +0   7 · le titre décide   review   → prendre
ad-2014-…council-of-europe    10/8 ████████ +16 257 parqués           pleine   — voir
```

Cinq colonnes, chacune adossée à un champ :

- **BANQUE** — `have` / `target`, et `+N` = `accepted_pending` (D8). Le plafond
  `cap` n'apparaît que sur les lignes `pleine`.
- **CANDIDATS** — `pending_scoped`, **et l'effet des filtres en clair**, et la
  meilleure marge (`best_margin`) quand le compte est petit. Un compte seul ment
  par omission.
- **GOULOT** — `bottleneck`, en toutes lettres.
- **GESTE** — **un lien, jamais une action directe.** Enfiler, scraper,
  rebuild sont des écritures : elles ont leur propre bouton, ailleurs.
- Le marqueur **`◈`** signale la famille `emission_commune`.

### 4.3 · Les états

| état | ce qui s'affiche | pourquoi |
|---|---|---|
| **chargement** | la structure avec les compteurs en `…`, jamais un spinner plein écran | la page est un tableau de bord : sa forme doit être stable |
| **vide** (aucune classe) | « la banque `2eur_all / vitl14` ne contient aucune classe » + le build lu | un `all_needs` à zéro ligne veut dire que le couple (kind, encoder) est faux, pas qu'il n'y a rien à faire |
| **erreur** | le message du canonique + le build attendu + « réessayer » | jamais une liste vide silencieuse |
| **`pleine`** | `10/8 ⌐cap 10` · `257 parqués` · geste « — voir » | D2/D3 : on ne sert plus, on ne cache pas |
| **`scrape`** | `0 · rien scrapé` · geste « → plan XX » | O2 propriété 1 : elle dit quand le goulot n'est pas elle |
| **pays désarmé** | `66 · pays désarmé` — le compte EST le pool brut | O4c : le filtre s'est retiré, la ligne le dit |
| **masqué** | `72 · 2 masqués pays` / `9 · 3 masqués ère` — **chaque mention est un lien** qui ramène les masqués | O2 propriété 3 |
| **`image_insuffisante`** | jamais un verdict à part — le marqueur `◈` + la cible 5 | D4 : ces classes se travaillent, avec le texte |
| **marge faible** | quand `best_margin < 0,05`, le compte passe en atténué + infobulle | 73 des 147 classes du palier 1 sont dans ce cas |
| **hébergé** | tous les gestes grisés + `LocalOnlyNotice` ; **tout le reste lisible** | §3.8 |

### 4.4 · La session (`/besoin/session`)

Un bandeau au-dessus de la pêche existante, et rien d'autre de neuf :

```
┌─ SESSION · palier 1 (couverture) ─────────────────────────┐
│ classe 12/147 · 41 crops · 12 exemplaires acquis          │
│ ███░░░░░░░░░░░░░░░░░░░░░░░░░   [ rendre la main ]         │
│ lu-2015-…dynasty · 0/8 · 4 candidats · marge max 0,21     │
└───────────────────────────────────────────────────────────┘
```

Règles :

- **L'arrêt compte `have + accepted_pending`** (D8) contre l'objectif du palier
  courant : 1 en palier 1, `target` en palier 2.
- **`need_only` est actif** (D9) : jamais un crop d'une classe déjà servie.
- **On enchaîne sur la classe suivante de l'ordre** dès l'objectif atteint, ou
  dès que le pool de la classe est épuisé.
- **« Rendre la main » est toujours visible** et ramène à `/besoin`.
- Le périmètre reste **entièrement dans l'URL** (`useQueryScope`) : quitter,
  recharger, revenir en arrière retombe sur la même file.

### 4.5 · La moitié ACHETER

```
┌─ ACHETER · 288 classes · 3 158 exemplaires ───────────────┐
│ 274 n'ont JAMAIS été visées par une annonce eBay          │
│ palier 1 : 274 classes × 1 exemplaire ≈ 1 808 annonces    │
│                                                            │
│ LU  37 classes   VA  27   MT  26   GR  22   SI  16        │
│ SM  28           PT  26   FI  17   SK  14   LT  12        │
│                                                            │
│ ⚠ le préflight quota de sources/cli.py est faux d'un       │
│   facteur ~130 · le budget vrai est dans eurio.local.db    │
│                                    [ ▶ plan LU ]  (local) │
└────────────────────────────────────────────────────────────┘
```

Le rendement affiché vient d'une mesure, pas d'une estimation :

```sql
-- 7 662 annonces eBay (grain listing) → 1 160 exemplaires fps  = 6,6 / exemplaire
WITH l AS (SELECT substr(source_ref,1,instr(source_ref,'_img')-1) k
             FROM source_images WHERE source='ebay' GROUP BY 1)
SELECT COUNT(*) FROM l;                                          -- 7662
SELECT COUNT(*) FROM dino_class_references
 WHERE anchors_kind='2eur_all' AND method='fps';                 -- 1160
-- et 6 249 items tranchés → 2 690 validés  = 2,3 tranchés / validé
```

---

## 5. Le vocabulaire — les mots exacts affichés

Un mot par concept, partout le même. Les synonymes sont ce qui a produit les
pannes muettes de ce dépôt.

| affiché | ce que c'est | jamais dit |
|---|---|---|
| **exemplaire** | une ligne `fps` de `dino_class_references` | « photo », « ancre », « référence » |
| **candidat** | un crop en file ouverte dont le top-1 tombe ici (`pending_scoped`) | « image », « item » |
| **acquis** | `accepted_pending` — validé, pas encore bâti | « validé » tout court |
| **parqué** | hors file par D2/D3, ni fermé ni supprimé | « ignoré », « rejeté », « fermé » |
| **désarmé** | le filtre s'est retiré parce qu'il ne laissait rien (O4c) | « désactivé » |
| **masqué** | écarté par un filtre levable, et compté | « filtré » |
| **couverture** | palier 1 : `have ≥ 1` | — |
| **profondeur** | palier 2 : `have ≥ target` | — |
| **pleine** | `have + accepted_pending ≥ target` | « terminée », « complète » |
| **banque** | la voie B, `dino_class_references` | — |
| **cohorte** | la voie A, `min_real`, l'entraînement ArcFace | — |

### Les deux « N par classe », et comment on évite la confusion

FLOW-ADMIN §4 signale le piège. La page l'évite par **trois** moyens cumulés,
pas un seul :

1. **Un mot différent.** La colonne BANQUE compte des **exemplaires**. La voie A
   compte des **crops validés**. Les deux mots ne se croisent nulle part.
2. **Une place différente.** `n_train_eligible` n'est **pas** une colonne de la
   liste. Il apparaît uniquement dans le **détail** d'une classe, sur sa propre
   ligne, préfixé « cohorte (voie A) ».
3. **Un lien qui sort.** Sur une classe `pleine` que la voie A réclame encore, le
   geste renvoie au **préflight de cohorte**, jamais à la pêche — les deux
   peuvent être en désaccord légitime, et c'est l'écran de cohorte qui a raison
   sur son sujet.

L'en-tête de la page le dit une fois, en toutes lettres : *« cette page compte
les exemplaires de la banque DINO (voie B). L'entraînement ArcFace compte
autrement — voir les cohortes. »*

---

## 6. Ce que la page ne fait pas

- **Aucune écriture au fil d'une lecture.** Enfiler, parquer, scraper, rebuild
  sont des boutons explicites. Rien ne part au canonique parce qu'on a affiché
  une ligne.
- **Aucun auto-accept.** Aucun crop n'entre en banque sans qu'un humain l'ait
  regardé.
- **Aucun périmètre qui rate ne s'ouvre.** Un filtre qui ne trouve rien se
  **désarme et le dit** (O4c) ou affiche zéro **avec sa cause** ; il ne se
  remplace jamais par un pool plus large en silence.
- **Aucun chiffre recalculé localement.** Tout vient de
  `shared.class_need.all_needs` et `shared.class_family`. Le front n'a le droit
  d'additionner que ce que le back lui a donné.
