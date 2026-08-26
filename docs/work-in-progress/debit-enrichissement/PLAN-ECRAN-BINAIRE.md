# Plan d'implémentation — l'écran de review binaire (« nourrir »)

> Lot **P2** du chantier [`SUIVI.md`](./SUIVI.md). Le constat est dans
> [`../review-autovalidation/REPRENDRE-ICI.md`](../review-autovalidation/REPRENDRE-ICI.md)
> §Session B ; ce document est son plan d'exécution. Aucun code ici — des lots,
> leurs fichiers, leur coût, leur gain et leur risque.
>
> ⚠️ Chaque chiffre porte sa requête. Rejoue-la : la base bouge.

## Le problème, en une phrase

En mode pêche la classe est **donnée** et elle est bonne (99,1 % avec le filtre
pays) ; ce qui peut être faux, c'est le **crop**. L'écran demande pourtant
« quelle pièce est-ce ? », avec dix `eurio_id` et des scores — et cette liste,
biaisée par le biais d'attraction, propose activement les classes **déjà
riches**. Elle pousse donc à détourner un crop vers la classe qui en a le moins
besoin.

**Cible : deux gestes, deux écrans.**

| | Nourrir | Trier à l'aveugle |
|---|---|---|
| Classe | donnée | inconnue |
| Question | « cette photo est-elle une bonne photo de X ? » | « quelle pièce est-ce ? » |
| Gestes | oui · non · je ne sais pas | l'écran actuel |
| Public | **tout le monde, l'ami en premier** | arbitres (`review:arbitrate`) |
| Écran | `/review/nourrir` (à créer) | `/review/peche` (existant, inchangé) |

---

## Ce qui a été re-vérifié au code et en base (2026-08-26)

### 1. Le front réel

`/review/peche` (`PechePage.vue`, 376 l.) n'est **qu'un cadre** : il écrit le
périmètre dans l'URL et monte `SingleReviewView.vue` (1 456 l.) ou
`LotDetailView.vue` (1 735 l.). C'est `SingleReviewView` qui pose la mauvaise
question — `candidates[]`, `group_candidates[]`, `standard_candidates[]`,
`dino_top1`, plus `FreeSelectorPanel` (674 l.), `DinoSuggestions` (584 l.),
`TextSignals` (330 l.), et un `canValidate` qui exige type d'annonce **et** état
numismatique hors contexte cohorte. Rien de tout cela n'a de sens quand la
classe est donnée.

### 2. La contrainte « pas heavy » est déjà satisfaite, et il faut la tenir

`app/router.ts:127` — `/review/peche` est **sans** `meta: heavy` depuis le lot 1
de `review-collaborative-v2`. Tout ce que l'écran consomme est monté sur l'image
**lean** du VPS (`ml/serving/server_serve.py`) :

| Appel | Routeur | Ligne |
|---|---|---|
| `GET /review-queue` (+ `dino-candidates/summary`) | `review_queue_router` | 148 |
| `POST /review-queue/{id}/decide\|reject\|skip` | `review_writes_router` | 153 |
| `GET /class-need` | `class_need_router` | 199 |
| `GET /referential/canonical-thumbs` | `referential` (via `_CANDIDATES`, avec `bind`) | 244 |

Et côté front, `useReviewApi.ts` passe par `fetchEurio` (l.339) / `fetchEurioWrite`
(l.411-423), donc `eurioApi` — **pas** `ML_API`. La nouvelle route hérite de la
même discipline : ni elle ni sa maquette ne portent `meta.heavy`, et la route
d'écriture neuve va dans `serving/review_queue/writes.py` (SQL pur, lean) et
**jamais** dans `review/review_queue_routes.py`, qui n'est pas monté sur le VPS.

### 3. Le vocabulaire des refus est trop pauvre — mais à moitié déjà écrit

`writes.py:52` : `_VALID_TRASH_REASONS = ("not_a_coin", "too_low_quality")`.
En base pourtant :

```sql
sqlite3 -readonly ml/state/eurio.replica.db \
 "SELECT quality_reason, COUNT(*) n FROM image_assets
   WHERE resolution_status='rejected' GROUP BY 1 ORDER BY n DESC;"
```

| `quality_reason` | n |
|---|---:|
| `not_2eur` | 1 572 |
| `face_reverse` | 1 446 |
| **`rejected_in_review`** | **1 430** |
| `consensus_reject` | 74 |
| `vision_standard_gate` | 51 |

**1 430 refus humains ne disent rien.** C'est le signal gratuit que l'écran
binaire récolte — et `face_reverse` existe déjà comme mot, écrit 1 446 fois par
la porte automatique : on le réutilise, on n'invente pas un synonyme.

### 4. Le refus n'est pas un cas limite

```sql
SELECT CASE WHEN decided_eurio_id IS NOT NULL THEN 'accept'
            ELSE COALESCE(decision_notes,'(null)') END k, COUNT(*) n
  FROM review_queue
 WHERE status='done' AND decision_engine_version='human@v1' GROUP BY 1;
-- accept 2929 · rejected 1122 · other 304
```

**27 % du geste humain est un « non ».** La branche « non » mérite autant de
soin que la branche « oui ».

### 5. La cadence : la référence avant/après

⛔ `ReviewStats.median_seconds_per_decision` (`repository.py:856-871`) mesure
`enqueued_at → decided_at` : une **latence de file**, pas une cadence. Elle ne
peut pas servir de référence. La bonne mesure est l'écart entre deux décisions
consécutives d'une même session :

```sql
WITH d AS (SELECT decided_at, LAG(decided_at) OVER (ORDER BY decided_at) prev
             FROM review_queue
            WHERE status='done' AND decision_engine_version='human@v1'),
     s AS (SELECT (julianday(decided_at)-julianday(prev))*86400.0 gap FROM d
            WHERE prev IS NOT NULL
              AND (julianday(decided_at)-julianday(prev))*86400.0 < 300
            ORDER BY 1)
SELECT COUNT(*) n, ROUND(AVG(gap),1) mean_s FROM s;
```

| n (écarts < 300 s) | moyenne | médiane | p25 | p75 |
|---:|---:|---:|---:|---:|
| 4 255 | 9,6 s | 5,0 s | 1,0 s | 10,0 s |

→ **~375 décisions/h à la moyenne, ~720/h à la médiane**
(`ml/state/eurio.replica.db`, 2026-08-26).

### 6. On ne sait pas d'où vient une décision

`decision_engine_version` vaut `human@v1` pour les deux écrans. **Sans marqueur
de surface, le gain est inmesurable** — d'où son entrée dans le lot backend, et
pas dans un « plus tard ».

### 7. « Oui c'est X » a besoin d'un `eurio_id`, la pêche tient un `class_id`

`ml/shared/bank_classes.py:87` (`bank_class_ids_for_class`) et
`builder_class_key_by_eurio_id` (l.117) portent la traduction. Mais
`dino_candidates_summary` rend `bank_class_ids` **et rien d'autre** : ni
l'identifiant à écrire, ni le libellé, ni la vignette. Le front devrait deviner
— donc le back doit le dire.

### 8. Un « non, pas cette pièce » n'a nulle part où aller

`skip` (`writes.py:437`) ne fait que bumper `priority` : **le crop revient**.
Aucune table de négation n'existe (`grep "CREATE TABLE" ml/state/schema.sql`,
80 tables). C'est le seul vrai trou backend du chantier.

### 9. Le filtre a un point d'accroche unique

`ml/shared/dino_scope.py:453` `build_dino_scope` est appelé par les six sites de
la pêche (`repository.py:695, 997, 1363, 1400, 1722` + `review/review_queue_routes.py:680`).
Une exclusion posée là couvre file, compteurs, lots et résumé d'un coup.
Ailleurs, elle produirait le défaut caractéristique du projet : un bandeau qui
annonce 12 au-dessus d'une file qui en sert 9.

### 10. Ce qui se réutilise tel quel

| Existant | Usage |
|---|---|
| `SplitCompare.vue` (68 l.) | canonique \| crop côte à côte — la géométrie visée |
| `useCanonicalThumbs.ts` | URLs CDN sans en-tête : le seul chemin qui marche en PAT |
| `useReviewKeybinds.ts` | garde `isTypingTarget`, à recopier |
| `CoachMarks.vue` (255 l.) | le premier passage |
| `useHeavyGate.ts` | `canArbitrate` — gestes lourds absents pour l'ami (D11) |
| `AccueilMaquettePage.vue` | **le précédent de maquette**, et sa justification (D13) |

---

## Les lots

### L0 — La maquette, avant le réseau · ½ jour

`NourrirVue.vue` (composant **définitif**, props pures, zéro fetch) monté sur
fixtures à `/review/nourrir/maquette`, hors nav, sans `meta.heavy`. Cinq états à
un clic : cas normal, refus déplié, file vide, vignette canonique absente, file
en erreur. Bandeau « Maquette — fixtures, aucun chiffre réel ».

*Fichiers* : `features/review/components/NourrirVue.vue`,
`features/review/fixtures/nourrir.mock.ts`,
`features/review/pages/NourrirMaquettePage.vue`, `app/router.ts`,
`components/SplitCompare.vue` (légendes en props).

*Gain* : aucun en production — c'est la discipline « maquette d'abord dans le
front où il vivra » (R1 §portée, D13). Elle évite de découvrir le mauvais geste
après l'avoir branché sur 6 574 crops.
*Risque* : faible. Le seul piège est de maquetter un composant jetable : il ne
prouverait rien.
*Recette* : aucun `eurio_id`, aucun score, aucun spread dans le DOM.

### L1 — L'écran branché, en oui / je ne sais pas · 1 jour

Route `/review/nourrir?class=<class_id>`, **pas** heavy. Réutilise tel quel
`fetchReviewQueue({dinoClass, dinoRank, needOnly})`, `fetchDinoCandidates`,
`useCanonicalThumbs`. **Les deux gardes de course sont reprises** : `scopeReady`
de `PechePage` (ne rien monter avant que l'URL porte le périmètre) et `loadSeq`
de `SingleReviewView` — elles ferment deux pannes distinctes mesurées le
2026-08-25. *Oui* → `decideReviewItem(id, {eurio_id: decide_eurio_id, face:'obverse'})`
(face figée obverse, comme le bouton « Accept Dino » actuel) ; *je ne sais pas*
→ `skipReviewItem`. Le bouton *non* est **visible et désarmé**. Fenêtre d'undo,
`flushPending`, `beforeunload` recopiés de `SingleReviewView` : la Session A a
établi que perdre une décision est le pire défaut du chantier.

*Fichiers* : `pages/NourrirPage.vue`, `composables/useNourrir.ts`,
`app/router.ts`, `__tests__/nourrir-flush.spec.ts`.

*Gain* : d'une liste de dix + deux champs obligatoires à une touche. Cible sur
la moitié acceptante (2 929 décisions) : écart médian de 5,0 s → **≤ 2,5 s**,
mesuré `surface='nourrir'`. Gain second, décisif : la liste biaisée disparaît,
le détournement vers une classe riche devient impossible depuis cet écran.
*Risque* : moyen. `decide` exige un `eurio_id` — **ne pas laisser le front le
deviner** ; L2 d'abord ou en parallèle.

### L2 — Le contrat backend du refus, et le marqueur de surface · 1,5 jour

Tout dans `serving/review_queue/writes.py` (lean, SQL pur).

1. **Migration `0017_nourrir_negations.sql`** :
   `review_class_negatives(id, image_asset_id, class_id, reason, decided_by,
   decided_at, arbitration_status)`, index unique `(image_asset_id, class_id)`.
2. **`POST /review-queue/{review_id}/not-class` `{class_id, reason}`** : pose une
   négation, **n'écrit pas** `image_assets`, **ne ferme pas** `review_queue`.
   C'est le point de conception du chantier — « pas cette pièce » ne détruit
   jamais un bon crop, il le rend à la file à l'aveugle.
3. **Vocabulaire** : `_VALID_TRASH_REASONS` → `('not_a_coin', 'too_low_quality',
   'face_reverse', 'bad_crop')`.
4. **`surface`** optionnel sur `DecidePayload`/`RejectPayload`, rangé dans
   `decision_metadata_json` (`{"surface":"nourrir"}`).
5. **`dino_candidates_summary`** gagne `decide_eurio_id`, `class_label`,
   `class_thumb_url`.

*Fichiers* : `ml/serving/migrations/0017_nourrir_negations.sql`,
`ml/serving/review_queue/writes.py`, `.../models.py`, `.../repository.py`,
`ml/tests/test_nourrir_negations.py`, `ml/state/schema.sql`.

*Gain* : 1 430 refus muets aujourd'hui ; cible ≥ 90 % des refus de `nourrir`
avec une raison exploitable. Et `surface` est ce qui rend tout le reste
démontrable.
*Risques* : (a) **piège n°1 du repo** — le devShell pose `EURIO_DB_READONLY=1`,
lire `eurio-data-writes` AVANT ; (b) l'API `:8042` garde une connexion
read-only thread-local : contrôler la migration dans un **process neuf** ;
(c) `db_migrate.py` n'a pas de down migration.

### L3 — Un « non » retire le crop de CETTE file, et de ses compteurs · ½ jour

Une clause, un endroit, dans `build_dino_scope` :

```sql
AND NOT EXISTS (SELECT 1 FROM review_class_negatives n
                 WHERE n.image_asset_id = {alias}.asset_id
                   AND n.class_id IN (<class_ids>))
```

Les six appelants restent d'accord. *Test* : poser une négation, rejouer
`GET /review-queue?dino_class=…` **et** `…/dino-candidates/summary` — le crop et
le compteur baissent de 1 ; et le crop reste servi par `GET /review-queue` sans
`dino_class`.

*Fichiers* : `ml/shared/dino_scope.py`, `ml/tests/test_dino_scope_negations.py`.

*Gain* : sans ce lot, l'ami revoit la photo qu'il vient de refuser — la panne
muette qui tue une session. Avec : le « non » vaut pour la classe, **zéro crop
détruit**.
*Risque* : élevé sur l'alias. `build_dino_scope` construit sur `ps`/`si`,
l'appelant sur `a`/`s`. Mauvais alias = soit `no such column` (bruyant, tant
mieux), soit une sous-requête qui ne mord jamais, en silence. **Ce lot ne se
déclare fait que sur un compteur relu en base.**

### L4 — Le « non » et ses quatre raisons · 1 jour

Le bouton *non* déplie 4 pastilles, une touche chacune. Le routage n'est **pas**
uniforme, et c'est l'intérêt :

| Raison affichée | Destin |
|---|---|
| illisible | `reject {reason:'too_low_quality'}` |
| c'est le revers | `reject {reason:'face_reverse'}` (le mot déjà écrit 1 446 fois) |
| mauvais cadrage | `reject {reason:'bad_crop'}` → file de recadrage de l'arbitre |
| pas cette pièce | **`not-class`** — négation, rien de détruit |

Les suggestions (`DinoSuggestions`) passent derrière une touche `S`, repliée par
défaut, et **seulement** pour `review:arbitrate`. Le recadrage manuel reste
absent pour l'ami : geste lourd, `showHeavyGesture` s'en charge (D11).

*Fichiers* : `NourrirVue.vue`, `useNourrir.ts`, `useReviewApi.ts` (ajout
`notClass()`, raison sur `rejectReviewItem`), `useNourrirKeybinds.ts`,
`__tests__/nourrir-reject-reason.spec.ts`.

*Gain* : sur 27 % du travail, on passe d'un bit à une raison typée, à coût
humain nul.
*Risque* : **élevé, et le précédent est écrit** — `LotDetailView.vue` applique
aujourd'hui la raison AU MAUVAIS CROP (curseur avancé avant l'appel, Session A
§4). Capturer l'`id` **avant** toute avance de curseur ; le test dédié est non
négociable.

### L5 — Les portes : qui voit quoi · ½ jour + recette

`gestureHref` (`useClassNeed.ts`) pointe « Trier » vers `/review/nourrir?class=…`.
`/review/peche` reste **inchangée** comme écran « trier à l'aveugle » de
l'arbitre — son entrée de nav est déjà scopée `review:arbitrate`, rien à
retirer. `/review/nourrir` n'entre pas dans la nav : on y arrive par une pièce.

**Comment la contrainte hébergé est satisfaite** : ni la route ni sa maquette ne
portent `meta.heavy`, et les cinq appels de l'écran sont montés sur l'image lean
(tableau du §2). L'ami sur `eurio-admin.musubi.dev` n'a donc aucun geste grisé.

*Recette, deux profils* (PAT restreint = ami, PAT complet = arbitre), la même
qu'au lot D11 : **zéro** occurrence de « local », « :8042 », d'un nom de
machine, d'un `eurio_id` ou d'un score dans le DOM du profil ami.

*Gain* : plus rien à apprendre. Critère : un ami qui n'a jamais vu l'app pose sa
première décision juste en < 60 s, sans explication orale.
*Risque* : basculer avant L4 enverrait l'ami sur un écran où 27 % de son travail
est désarmé. **L5 après L4, jamais avant.**

### L6 — La mesure · ½ jour

Script versionné (pas une requête retapée de mémoire) rejouant la requête de
gaps du §5, découpée par
`json_extract(decision_metadata_json,'$.surface')` → n, moyenne, médiane, p75.
Plus deux contrôles sur le **vrai** sujet : (a) part des décisions posées sur
des classes pauvres (< 2 exemplaires) avant/après ; (b) classes distinctes
nourries par semaine.

*Fichiers* : `ml/scripts/mesure_cadence_review.py`,
`docs/work-in-progress/review-autovalidation/MESURE-NOURRIR.md`.

*Référence posée aujourd'hui* : n=4 255, moyenne 9,6 s, médiane 5,0 s,
p75 10,0 s. *Objectif* : médiane ≤ 2,5 s sur `surface='nourrir'`, à précision au
moins égale (taux d'infirmation à l'arbitrage bulk).
*Risque* : comparer deux populations différentes. La comparaison honnête est
**pêche vs nourrir**, sur des classes de même profil — impossible sans le champ
`surface` de L2.

> ⚠️ Le §1 de `REPRENDRE-ICI.md` a mesuré un facteur **12** entre classes riches
> et pauvres. Si l'écran binaire ne le bouge pas, il aura gagné du temps sans
> déplacer le plafond — et il faut pouvoir le dire.

---

## Ordre et coût

```
L0 ─→ L1 ─┐
          ├─→ L4 ─→ L5
L2 ─→ L3 ─┘
       └────────────→ L6
```

**Total ≈ 5,5 jours.** L2 peut démarrer en parallèle de L0/L1 ; L4 exige L1+L3 ;
L5 exige L4 ; L6 exige L2.

## Ce qui n'est PAS dans ce plan

- Le mode **lot** : `LotDetailView` reste réservé à l'arbitre
  (`funnel_writes.decide_lot` exige `review:arbitrate` depuis le 2026-08-24) —
  et il porte quatre défauts ouverts de la Session A. Le binaire ne s'y applique
  pas tel quel.
- Le **biais d'attraction** lui-même (§1 du constat) : cet écran le rend
  inoffensif *depuis la review*, il ne le résout pas. Le plafond reste le
  plafond.
- La **calibration des seuils sur vitl14** : sujet indépendant, gain de volume.
  Mesuré le 2026-08-26 — cf. [`SUIVI.md`](./SUIVI.md) §4 de la photo de départ.

## Les décisions qui reviennent au PO

| # | Question | Recommandation |
|---|---|---|
| **D15** | « oui c'est X » sur une **courante** écrit quel `eurio_id` ? | Le représentant du groupe de dessin. Ne jamais demander l'année à l'ami — elle n'est pas dans le dessin, et la demander rouvre le puits sans fond. Conséquence assumée : pas de millésime exploitable |
| **D16** | « c'est le revers » **détruit-il** le crop ? | Réutiliser `face_reverse` → `training_eligible=0`, comme la porte `face@v1` (1 446 images). Alternative : les conserver comme faces communes, utiles le jour où le scan devra lire le revers |
| **D17** | « mauvais cadrage » : poubelle ou file de recadrage ? | Alimenter `/crop-recovery`. On ne jette pas des photos payées en quota eBay. Coût : un écran de plus à tenir |
| **D18** | La négation d'un ami passe-t-elle par la **quarantaine** ? | Non — elle ne touche pas le canonique et se défait d'une ligne. Sinon l'ami revoit ce qu'il vient de refuser. Contre-argument : un ami qui se trompe cache un bon crop à toute une classe |
| **D19** | Filtre pays et **rang de pêche** ? | Le filtre pays reste (99,1 %, c'est lui qui autorise la question binaire). Mais `rank=1` prive 272 classes pauvres sur 457 de tout candidat : passe-t-on l'écran de l'ami au **rang 3** ? Le « non » binaire est bon marché — c'est l'argument pour |
| **D20** | Le **nom** affiché | « Nourrir » est un mot de pipeline ; « Trier » désigne désormais l'autre écran. À trancher **avant L0** : la maquette le grave |
| **D21** | L'**ordre de bascule** | Ne pas basculer « Trier » avant L4. Accepte-t-on la période intermédiaire sur l'écran actuel ? |
