# Reprendre ici — ce que la journée du 2026-08-24 a établi, et les deux sessions qui suivent

> Ce fichier existe parce que tout ce qui suit n'existait que dans une conversation.
> `PROBLEME.md` pose le sujet ; celui-ci porte les **mesures** qui y répondent et le
> découpage du reste-à-faire.
>
> ⚠️ **Chaque chiffre porte sa requête ou son fichier.** Relance-la — la banque a été
> rebâtie deux fois dans la journée, et un nombre cité de mémoire sera faux.

## Ce qui est fait et déployé

**La banque du verdict a basculé** de `2eur_commemo`/vits14 vers `2eur_all`/vitl14
(commits `a37f0f3d`, `f8e6b42d`). Ce qui l'a autorisé — les deux banques rejouées sur le
MÊME gold, même base, même processus, 464 crops labellisés **hors banque** :

| | `2eur_commemo` | `2eur_all` |
|---|---:|---:|
| auto-accepts produits | 104 | **185** |
| dont justes | 104 | 184 |
| précision | 100 % | **99,5 %** |
| top-1 exact (in-scope) | 58,2 % | **92,6 %** |

Avant : **4 237 des 8 496 items ouverts** avaient une prédiction sous la banque du
verdict. La moitié de la file tombait en `unknown` par la règle 1 — pas parce que le
modèle hésitait, mais parce que le JOIN cherchait au mauvais endroit.

La banque a été rebâtie (**1 909 → 2 062 ancres**, build `53d22c38`) et les 16 021
prédictions recalculées. Durée réelle d'un run complet : **~55 min** (7 min d'ancres,
47 min de backfill), et non les 18 min qu'annonçait `ml/tasks.yml` — corrigé.

L'accueil admin porte l'écart de la banque (`GET /dino/drift`, SQL pur, lisible Mac
éteint) et son bouton de rebuild (workstation seulement), avec barre de progression.

## Les trois mesures qui décident de la suite

### 1. Le biais d'attraction — le plafond de l'enrichissement

```sql
-- classes pauvres (< 2 exemplaires) vs riches, et ce que la pêche leur rapporte
WITH ex AS (SELECT class_id, COUNT(*) n FROM dino_class_references
             WHERE anchors_kind='2eur_all' AND method='fps' GROUP BY 1),
     peche AS (SELECT p.top1_eurio_id t, COUNT(*) n FROM review_queue rq
                JOIN image_asset_dino_predictions p ON p.asset_id=rq.image_asset_id
                     AND p.anchors_kind='2eur_all'
               WHERE rq.status='open' GROUP BY 1)
-- …
```

| | classes | avec des candidats en pêche | crops pêchables |
|---|---:|---:|---:|
| pauvres (< 2 exemplaires) | 457 | **185 (40 %)** | 1 228 |
| riches (≥ 2 exemplaires) | 214 | 209 (98 %) | **7 167** |

**~2,7 crops par classe pauvre contre ~34 par classe riche — un facteur 12.** Et
**272 classes pauvres sur 457 n'ont AUCUN candidat**.

C'est auto-renforçant : une classe riche sort en top-1, donc elle est pêchée, donc
nourrie, donc encore mieux reconnue. `/besoin` dit très bien **quelles** classes sont
pauvres ; la pêche, elle, est aveugle à 60 % d'entre elles **par construction** — elle
cherche par `top1`, et une classe qui n'a que son rendu Numista ne sort jamais en top-1.
Le contournement actuel est le scrape ciblé, qui coûte du quota eBay (du vrai argent).

⚠️ Sujet non traité. C'est le plafond de tout le reste.

### 2. Les émissions communes — le pays n'est pas dans le dessin

Les 5 familles **ont** un `design_group_id` (`eu-erasmus-2022`, `eu-eu-flag-2015`,
`eu-emu-2009`, `eu-rome-2007`, `eu-euro-cash-2012`). Mais **la banque ne les replie
pas** : une commémorative = une classe, par construction (`bank_class_ids` rend
`[eurio_id]` dès que `is_commemorative`). La banque porte donc 16 classes pour Erasmus,
14 pour « 10 ans de l'euro ».

Ce que ça coûte, sur les crops validés :

```
commémoratives : 2 461 crops · 2 294 exacts
                 86 erreurs « bon dessin, mauvais pays »  ← 52 % des erreurs
                 79 vraies erreurs
```

Par famille : `eu-euro-cash-2012` **62 %** d'exactitude · `eu-emu-2009` 77 % ·
`eu-eu-flag-2015` 76 % · `eu-rome-2007` 80 % · `eu-erasmus-2022` 96 %.

⛔ **La réponse n'est pas de replier davantage.** Le pays d'une émission commune est
dans la **légende**, pas dans le dessin — aucune banque d'ancres ne le trouvera. Il est
en revanche dans l'annonce, et le filtre `listing_country` est mesuré à **99,1 %** de
précision (`peche-dino/DECISIONS.md` §D9). Décider le pays par le texte pour ces 5
familles, pas par le pixel.

✅ **Sur les STANDARDS, le repli fonctionne et DINO fait les micro-distinctions.**
Recall réel **95,1 %** (337 exacts + 111 « bon groupe » sur 471, 20 vraies erreurs).
Le « 70,3 % » cité en séance était faux : il comptait le repli comme une erreur.

### 3. Le plancher irréductible de la banque

Après un rebuild complet, **8 classes** ont des crops parfaitement éligibles au SQL du
builder et **zéro exemplaire** — `fr-2017-…-rodin` en a 9. Cause : `floor_sim = 0,45`
écarte les crops trop éloignés de leur canonique. Aucun rebuild ne les prendra.

C'est une information réelle (« ces classes ont des photos que le modèle ne reconnaît
pas comme les leurs ») mais c'est un **sujet d'enrichissement, pas de rebuild** — d'où
le fait que `dino_drift.is_stale` ne se calcule plus dessus.

---

## Session A — la review en lot perd du travail humain

**À faire en premier.** Une décision de review est la seule donnée du projet qu'aucun
calcul ne régénère, et elle se perd en silence. Quatre mécanismes indépendants, aucun
ne lève d'erreur :

1. **Rien n'est écrit avant que le lot soit ENTIÈREMENT tranché.** Le lot accumule en
   mémoire ; le POST ne part que si `allDecided`. Aucun `beforeunload`, aucun
   `onBeforeRouteLeave` — fermer l'onglet, passer au lot suivant ou appuyer sur Échap
   perd tout, sans un mot. Le single, lui, flush au démontage
   (`SingleReviewView.vue`, `scheduleCommit`).
2. **Un lot déjà tranché revient comme s'il ne l'était pas.**
   `serving/review_queue/repository.py` — le détail d'un lot fait
   `LEFT JOIN review_queue` **sans** `AND rq.status='open'` (`list_lots`, lui, filtre).
   Les crops `done` reviennent en « en attente », et comme `allDecided` exige de tout
   retrancher, un lot dont un seul crop reste ouvert force à re-décider les N autres.
3. **Le refus est jeté.** `POST /review-queue/lots/{key}/decide` renvoie
   `{done, rejected, skipped, errors[]}`. `errors` est typé côté front et **jamais lu** :
   un lot de 12 crops dont 11 sont refusés affiche « Listing validé · 1 assigné ».
4. **Le menu « Rejeter » applique la raison au MAUVAIS crop** (`LotDetailView.vue`) :
   le handler avance le curseur de façon synchrone avant que `rejectCrop(activeAssetId)`
   s'exécute. Le crop visé reste rejeté sans raison, le suivant reçoit la tienne — et
   compte comme tranché.

À quoi s'ajoute que le backend sert `current_eurio_id` (l'attribution déjà en base) et
que le front ne le lit nulle part : l'information « déjà tranché → X » est dans le
payload, ignorée.

## Session B — le geste de review, côté front

C'est la réponse au constat de `PROBLEME.md`. En mode **pêche**, la classe est donnée
et elle est bonne (99,1 % avec le filtre pays) ; ce qui peut être faux, c'est le
**crop**. L'écran pose pourtant la mauvaise question — « quelle pièce est-ce ? », avec
une liste de dix `eurio_id` et des scores — alors que la vraie est « cette photo est-elle
une bonne photo de X ? ».

Pire : cette liste est biaisée par le §1 ci-dessus. Elle propose activement les classes
**déjà riches**, donc elle pousse à détourner un crop vers la classe qui en a le moins
besoin.

**Deux gestes, deux écrans :**

- **Nourrir** (pêche, classe donnée) — binaire. Canonique de X à gauche, crop à droite,
  trois touches : *oui c'est X* / *non* / *je ne sais pas*. Aucune liste, aucun score,
  aucun `eurio_id` visible. Sur *non*, la raison en un clic (mauvais cadrage · c'est le
  revers · pas cette pièce · illisible) — du signal gratuit, et ça évite le puits sans
  fond du « alors c'est laquelle ? ». Les suggestions passent derrière une touche.
- **Trier à l'aveugle** (pas de classe) — l'écran actuel, réservé aux arbitres.

L'ami ne voit **jamais** que le premier : pas de taxonomie à apprendre, pas de seuil,
pas de spread. C'est aussi la réponse à la question de l'onboarding.

## Le reste, plus petit

- **Calibrer les seuils sur vitl14.** `top1_country_sim_min` (0,55) et
  `country_spread_min` (0,05) viennent de la confusion map **vits14**. Ils tiennent
  (99,5 %), donc ce n'est pas un correctif — c'est un gain de **volume** : le point est
  très conservateur (1 faux sur 185), il y a probablement de la marge pour descendre et
  doubler les auto-acceptations à précision comparable, donc autant d'heures de review
  humaine en moins. Balayage sur le gold, aucun rebuild, puis `set_threshold` en base.
- **L'étape ancres n'a pas de compteur** : 7 min et 3 205 images sans un chiffre à
  l'écran. La boucle d'encodage vit dans `training/foundation/anchors.py`.
- **La carte « modèle de scan »** de l'accueil n'existe pas : il n'y a aucune notion de
  modèle promu au canonique (`promote_iteration` écrit `ml/prod/current/promoted_from.json`,
  un fichier sur la machine de calcul). Trancher d'abord : on trace la promotion en base,
  ou la carte assume d'être locale ?
