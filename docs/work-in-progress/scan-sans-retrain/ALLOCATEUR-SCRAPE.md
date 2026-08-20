# L'allocateur de scrape par déficit

> Note de conception, écrite **avant** le script `ml/scripts/allocate_ebay_scrape.py`.
> Toute mesure porte sa requête. Base lue : `ml/state/eurio.replica.db`
> (réplique fraîche du 2026-08-20 03:22). Aucune écriture, aucun appel eBay.
>
> 🔴 **Mise à jour du 2026-08-20 (soir) — ce chantier est passé n°1.** La note
> d'état en tête de [`PREREQUIS.md`](PREREQUIS.md) le place devant tout le
> reste : c'est, avec la protection des photos, l'un des deux seuls chantiers
> qui se comptent en jours. **Le déficit s'est creusé** : le rebuild de la
> banque avec le plancher `min_exemplars=2` (build `365dcab2a253`, 2026-08-20
> 14:27) a ramené **68 classes de plus au canonique seul**. ⚠️ *Le plancher a
> depuis été retiré du code : ces 68 classes reviendront en banque au prochain
> rebuild, et le déficit mesuré ci-dessous se réduira d'autant.* Recompté à
> **17:14 UTC** avec la requête du §« Les deux zéro », mais sur les classes de
> la **nouvelle** banque :
>
> ```
> 547 classes au canonique seul  →  {0: 331, 1: 92, 2: 38, 3-4: 31, 5-7: 23, >=8: 32}
> file ouverte : 6651
> ```
>
> Les chiffres du corps de ce document (**489 / 265 / 6894**) sont ceux du matin
> et **restent valides pour le raisonnement** — la maille, les coûts par groupe,
> la règle d'arrêt, les ~10 jours de quota ne bougent pas. Seuls les effectifs
> ont grossi. **Relance la requête plutôt que de citer un nombre** : la review
> avance pendant qu'on lit.

## Le problème, en une phrase

Les briques existent toutes — découverte eBay, theme-matcher, crop, file de
review triée par DINO, accept 1-clic. Ce qui manque est le composant qui décide,
**à quota donné, quels groupes de découverte scraper et dans quel ordre**.
Aujourd'hui ce choix est fait à la main, pièce par pièce, et il se trompe dans
les deux sens : il sur-scrape des classes déjà pleines et n'a jamais touché la
majorité du catalogue.

## Ce que la base sait déjà

### La maille : le groupe de découverte, pas la classe

Une recherche eBay ne cible **jamais** une classe. `EbayAdapter._resolve_group`
(`ml/sources/ebay/adapter.py:410`) ramène toute requête à un **groupe de
découverte** :

* commémorative → `(2.0, pays, année)` — toutes les commémos-sœurs du pays-année ;
* standard → `(2.0, pays, None)` — toutes les ères de design du pays.

Les 671 classes de la banque `2eur_all` (grain exact :
`training.foundation.anchors._class_specs_2eur_all`) se replient sur
**416 groupes de découverte**, dont **380 portent un déficit**. C'est là que
l'allocation se joue : une décision d'allocation sert plusieurs classes d'un
coup, et son coût ne dépend pas du nombre de classes qu'elle sert.

### Le coût réel d'un groupe

Le quota eBay est **5000 appels/jour** (`sources/_base/sources_registry.py:66`,
`quota_limit=5000`, fenêtre `daily`). Le compteur vrai est dans
`ml/state/eurio.local.db` — pas dans `source_runs.n_calls`, qui ne compte que les
recherches :

```bash
sqlite3 -readonly ml/state/eurio.local.db \
  "select period, calls from api_call_log where source='ebay' order by period;"
# 2026-06-13|1163   2026-06-14|281   2026-06-15|717   2026-08-16|740
```

Un groupe coûte `2 recherches` (marketplaces `EBAY_DE` + `EBAY_ES`,
`sources/ebay/marketplaces.py`) plus **un appel `item/{id}` par annonce retenue**
(`adapter._yield_listing_images`). Croisé avec `discovery_searches` :

| jour | groupes | recherches | Σ `n_kept_results` | appels réels | appels/groupe |
|---|---:|---:|---:|---:|---:|
| 2026-06-13 | 10 commémo (AD 2016-2024, AT 2007) | 20 | 1408 | 1163 | **116** |
| 2026-06-14 | 2 commémo (AT 2009, AT 2012) | 4 (+4 dry) | 283 | 281 | **~138** |
| 2026-06-15 | 3 standard (AT, ES, BE) | 6 | 727 | 717 | **239** |

```sql
select substr(created_at,1,10) d, count(*) n_searches, count(distinct query_q) n_q,
       sum(n_kept_results) kept from discovery_searches group by 1;
```

Constantes de planification retenues : **130 appels par groupe commémoratif,
240 par groupe standard** (le standard ratisse `limit=200` au lieu de 75 —
`SEARCH_LIMIT_STANDARD_MULT`, `queries.py:177`). Ce sont des **estimations**
adossées à 15 groupes observés, pas une loi.

### Le déficit, aujourd'hui

Cible **8 exemplaires**, plafond **10** (`DEFAULT_EXEMPLARS_PER_CLASS = 10`,
`anchors.py:445`) — au-delà, un crop validé n'entre plus dans la banque.

```sql
-- exemplaires par classe (grain banque)
select class_id, count(*) from dino_class_references
 where anchors_kind='2eur_all' and method='fps' group by 1;
```

* 671 classes, **489 à zéro exemplaire**, 64 à exactement 1, 27 à 2, 7 à 3 ;
* déficit total vers 8 : **4622 exemplaires** ;
* **354 groupes** portent ce déficit une fois la file de review déduite
  (338 commémo + 16 standard) → **~47 800 appels, soit ~10 jours de quota**
  pour un balayage complet.

C'est le chiffre qui cadre tout : le problème n'est pas « choisir entre deux
classes », c'est « ordonner dix jours de quota ».

### Le gaspillage actuel, et la règle d'arrêt

Les 55 classes pleines ont une **médiane de 25 crops décidés** pour un plafond de
10. Chaque crop au-delà de 10 est du quota et du temps de review dépensés pour
rien. La règle d'arrêt n'est donc pas un raffinement : c'est le premier gain.

### Les deux « zéro » — et ce que la base ne sait pas

Sur les 489 classes sans exemplaire, **265 n'ont aucun crop en file ouverte** :

```sql
-- crops en file ouverte dont le top1 DINO tombe sur la classe
select p.top1_eurio_id, count(*) from review_queue rq
  join image_asset_dino_predictions p on p.asset_id = rq.image_asset_id
 where rq.status in ('open','in_progress') and p.anchors_kind='2eur_all'
 group by 1;
-- → 265 classes à 0 · 93 à 1 · 49 à 2 · 33 à 3-4 · 25 à 5-7 · 24 à ≥8 (343 crops)
--   file ouverte totale : 6894
```

Jamais scrapées, ou absentes du marché ? **La base répond, et la réponse est
nette** : reconstruction des requêtes de chaque groupe (`build_group_query`, une
par langue de marketplace) confrontée à `discovery_searches` —

```
groupes: 416   déjà cherchés: 49   jamais cherchés: 367   cherchés sans aucun kept: 0
```

et côté statut de source :

```sql
select source, state, count(*) from coin_source_status group by 1,2;
-- bce_official | empty_upstream | 18      ← d'AUTRES sources savent le dire
-- bce_official | ok             | 475
-- ebay_browse  | ok             | 18      ← eBay : 18 lignes, AUCUNE en empty_upstream
-- eurlex_jo    | ok             | 71
-- lmdlp        | empty_upstream | 1
-- lmdlp        | ok             | 337
-- numista_api  | ok             | 689
```

⚠️ Correction du 2026-08-20 : une version antérieure de ce document écrivait
« aucune ligne `empty_upstream` dans toute la base ». **Faux — il y en a 19**,
sur `bce_official` et `lmdlp`. Ce qui est vrai, et c'est le point, est plus
étroit : **aucune pour eBay**. Le mécanisme existe et sert ailleurs ; c'est le
chemin eBay qui ne l'a jamais emprunté.

**Il n'existe pas une seule preuve, dans toute la base, qu'une recherche eBay
soit revenue vide.** 367 des 416 groupes n'ont jamais été interrogés. La
distinction demandée entre « jamais cherché » et « introuvable sur le marché »
n'est donc pas mesurable aujourd'hui — parce que le second cas n'a jamais été
enregistré. L'allocateur ne peut pas hériter de cette information : il doit la
**produire**, en ordonnant les groupes vierges d'abord et en s'appuyant, aux
tours suivants, sur ce que `discovery_searches` aura consigné.

## La fonction d'allocation

Pour chaque classe `c` de la banque :

```
have(c)     = exemplaires 'fps' dans dino_class_references (2eur_all)
pending(c)  = crops en file OUVERTE dont le top1 DINO = c et marge ≥ 0,05
need(c)     = max(0, 8 − have(c) − pending(c))
poids(c)    = need(c) × (2,0 si have(c) == 1 sinon 1,0)
```

Pour chaque groupe `g` :

```
sert(g)  = Σ poids(c) pour c ∈ g
cout(g)  = 130 (commémo) | 240 (standard)
score(g) = sert(g) / cout(g)
```

Remplissage **glouton par score décroissant** jusqu'à épuisement du budget.
Budget par défaut = `5000 − appels du jour` (lu dans `api_call_log`), divisé par
la marge de sécurité **1,3** — la même que le préflight quota du CLI
(`sources/cli.py:119`).

Le facteur 2,0 sur `have(c) == 1` traduit une mesure, pas une intuition : la
courbe références/classe (COURBE-REFERENCES) donne **N=0 : 53,1 %** contre
**N=1 : 50,1 %** en held-out. Une classe à un exemplaire est *pire* qu'une
classe nue. Les 64 classes dans ce cas doivent sortir de là en premier.

## Ce que l'allocateur refuse de faire

1. **Il ne vise jamais 1.** `--min-need` (défaut 2) : une classe dont le besoin
   résiduel est de 1 seul exemplaire ne justifie pas à elle seule le
   financement d'un groupe. Elle est servie en passager, jamais en pilote.
2. **Il ne scrape pas ce qui attend en review.** `pending(c)` est *soustrait* du
   besoin. Mesuré aujourd'hui : **50 classes déficitaires ont déjà, en file
   ouverte et au-dessus de la marge 0,05, de quoi combler tout leur déficit.**
   Pour celles-là le geste est la review, pas le quota. C'est exactement la
   leçon de `es-2euro-juan-carlos-i-t2` (skill `eurio-enrichment`) : un scrape à
   ~400 appels avait rendu 3 crops quand 26 candidats attendaient déjà.
3. **Il ne repasse pas sur un groupe frais.** `--cooldown-days` (défaut 30,
   aligné sur `expected_cadence_days=30` du registre de sources) écarte tout
   groupe dont une requête a tourné récemment.
4. **Il ne dépasse pas le budget**, et il ne le devine pas : le budget vient du
   compteur réel, avec la marge 1,3. ⚠️ Le budget n'était calculé **qu'une
   fois**, avant la première vague (défaut S4) ; et le préflight de
   `sources.cli`, cité plus haut comme la marge de sécurité, est **aveugle d'un
   facteur ~130** — il estime sur `source_runs.n_calls` (mesuré faux : 3 pour
   740 appels réels) et rend `estimate=8, max_safe_batch=4054` pour une vague
   que l'allocateur budgète 1040 (défaut S3, non corrigé : il vit dans
   `serving/sources_routes.py:2150`). Correctif posé le 2026-08-20 dans
   l'allocateur : `execute()` **relit `api_call_log` avant chaque vague** et
   s'arrête si le restant passe sous `coût prévu × 1,3`, sans lancer la vague.
5. **Il n'appelle pas eBay.** `--dry-run` est le défaut — et depuis le
   2026-08-20 il n'est plus décoratif : `--dry-run` n'était **lu nulle part**
   (défaut S2), si bien que `--dry-run --execute --yes` brûlait le quota en
   affichant qu'on ne le brûlait pas. Les deux drapeaux sont désormais
   exclusifs (argparse sort en 2). Le mode réel
   (`--execute --yes`) ne fait qu'invoquer `go-task ml:src:ebay:run` — jamais
   `python -m sources.cli` en direct, pour ne pas perdre `EURIO_CENSUS_RECOVER=1`
   (OFF par défaut, ~77 % du parc bimétal en dépend).
6. **Il n'écrit rien.** La connexion est ouverte en `mode=ro`.

## Ce qu'il ne peut pas savoir

* **Si la pièce existe sur eBay.** Aucune donnée ne le dit (0 recherche vide
  enregistrée sur 416 groupes). Si une commémorative rare de Saint-Marin n'est
  pas en vente, aucune allocation ne la fera apparaître — l'allocateur brûlera
  ~130 appels pour l'apprendre, et c'est le prix de l'information.
  **⚠️ estimation** : les groupes les plus exposés sont ceux à millésime récent
  et faible tirage — LU 2020-2025 (6 groupes, 192 exemplaires de déficit),
  VA 2025, MT 2022. Aucune mesure ne permet aujourd'hui de les distinguer d'un
  groupe simplement jamais cherché.
* **Le rendement d'un groupe.** Mesuré sur 5 runs, par
  `select si.run_id, count(a.id), sum(a.training_eligible=1), <ancres> from source_images si left join image_assets a …` :
  de **7 à 149 ancres** finalement entrées dans la banque, pour 2 à 10 groupes.
  Le run du 2026-08-16 : 740 appels → 801 raws → 661 crops → 62 validés →
  **50 ancres**, soit ~15 appels par exemplaire gagné. Sur un groupe vierge et
  pauvre, ce ratio sera pire, et l'allocateur ne sait pas de combien.
* **Si la review suivra.** Le plan crée des items de review par centaines et
  **6894 attendent déjà**. Le quota n'est pas le goulot le plus étroit du
  système ; l'allocateur ne le prétend pas.
* **Si le crop réussira.** `0 crop` n'est pas une erreur (certificats,
  emballages) et n'est logué que sur les zéros.
* **Les 64 classes à un exemplaire ne seront pas réparées par lui seul.** Le
  mécanisme — le FPS choisit d'abord le crop le plus *diversifiant*, donc le plus
  atypique — relève du **builder**, pas de l'allocation. ⚠️ *Mis à jour le
  2026-08-20 (soir)* : la parade tentée (un plancher `min_exemplars=2`) a été
  **retirée** — la mesure par classe dit qu'un exemplaire unique **aide** sa
  classe. Ce qui reste vrai est mesuré : le creux vient de l'**ordre** du FPS
  (`--rank-order last` rend 77,8 % contre 73,8 % en `vitl14`, à nombre d'ancres
  identique). Le levier est donc l'**amorce du FPS**, non implémentée.
  L'allocateur, lui, priorise ces classes ; il ne les guérit pas.

## Interface

```bash
go-task ml:ebay:allocate                       # dry-run, plan du jour
go-task ml:ebay:allocate -- --budget 20000     # planifier 4 jours de quota
go-task ml:ebay:allocate -- --format json --out /tmp/plan.json
go-task ml:ebay:allocate -- --execute --yes    # geste explicite, lance les runs
```

Le plan sort en groupes, chacun avec **un eurio_id représentant** : c'est la
forme que `--target-eurio-ids` sait consommer, et `_resolve_group` le replie sur
le bon groupe (commémo → `(2.0, pays, année)`, standard → `(2.0, pays, None)`).
Un représentant par groupe : deux ids du même groupe déclencheraient deux
recherches identiques, soit deux fois le coût pour la même moisson.

## Le plan réel du 2026-08-20 (dry-run, aucun appel émis)

`go-task ml:ebay:allocate -- --budget 5000` — budget forcé à un jour plein de
quota pour rendre le plan lisible ; le défaut applique la marge 1,3 et rend
**28 groupes / 3750 appels**.

```
budget planifiable  5000 appels
groupes retenus     37
coût prévu          4920 appels
exemplaires visés   792 sur 3940 de déficit finançable

  #  groupe     kind      cls need zéro N=1 file  coût  score  représentant
------------------------------------------------------------------------------------------------
  1  LU/2025    commémo     6   47    6   0    1   130  0.362  lu-2025-2eur-25th-anniversary-of-the-accession-of-grand-duke-henri-to-the-throne
  2  LU/2023    commémo     4   32    4   0    0   130  0.246  lu-2023-2eur-175th-anniversary-of-the-1848-constitution-and-the-chamber-of-deputies
  3  LU/2024    commémo     4   32    4   0    0   130  0.246  lu-2024-2eur-100th-anniversary-of-the-introduction-of-the-franc-coins-bearing-of-the-image-of-the-feiersteppler
  4  FR/2017    commémo     3   19    1   2    3   130  0.238  fr-2017-2eur-100th-anniversary-of-the-death-of-auguste-rodin
  5  LU/2021    commémo     4   31    4   0    1   130  0.238  lu-2021-2eur-100th-anniversary-of-the-birth-of-grand-duke-jean-hologram
  6  FR/2014    commémo     3   22    2   1    1   130  0.215  fr-2014-2eur-70th-anniversary-of-d-day
  7  IT/2015    commémo     3   21    2   1    2   130  0.215  it-2015-2eur-30th-anniversary-of-the-flag-of-the-european-union
  8  FI/2015    commémo     3   20    2   1    3   130  0.208  fi-2015-2eur-150th-anniversary-of-the-birth-of-artist-akseli-gallen-kallela
  9  VA/std     standard    5   39    4   1    0   240  0.192  va-2002-2eur-standard-john-paul-ii
 10  IT/2018    commémo     2   12    0   2    2   130  0.185  it-2018-2eur-60th-anniversary-of-the-italian-ministry-of-health
  …                                                                        (10 premières lignes sur 37)

Écartés :
  cooldown (< 30 j)      0 groupe(s)
  empty_upstream connu       0 groupe(s)
  hors budget (reportés)     316 groupe(s), 42730 appels
  déficit couvert par la review, pas par le quota : 50 classe(s)

```

Lecture :

* **37 groupes pour 4920 appels**, qui visent **792 exemplaires** — sur les
  **3940** de déficit finançable restant (chiffres du 2026-08-20 **14:05 UTC** ;
  le 20 au matin la même commande rendait 793 sur 3932 — mêmes 37 groupes, même
  coût : c'est la review qui avance sous le plan, pas le plan qui varie). Un jour de quota traite **20 % du
  déficit**, et le reste (**316 groupes, 42 730 appels**) est reporté : le
  balayage complet est un programme de ~10 jours, pas une commande.
* Le Luxembourg occupe 8 des 20 premières places. Ce n'est pas un biais de
  l'allocateur : LU 2020-2025 concentre des classes à trois variantes
  (normale / colorée / hologramme), toutes à zéro exemplaire, toutes servies par
  une seule recherche « 2 euro Luxemburg <année> ». C'est exactement le levier
  que la maille-groupe est censée trouver.
* **FR/2015 est absent du plan, mais PAS pour la raison écrite ici d'abord.**
  Correction du 2026-08-20 : le document affirmait que ses 49 candidats en file
  couvraient tout son déficit. Faux — mesuré à 14:05 UTC,
  `GroupPlan(FR/2015 … served=13.0, need=13, pending=49, score=0,100)`, et le
  détail par classe est `have=[0,0,0,1,2] pending=[5,6,0,10,28]
  need=[3,2,8,0,0]` : les 49 sont un total de GROUPE dont 28 tombent sur une
  seule classe déjà servie, et **trois classes ont encore un besoin**. FR/2015
  sort par le **score** (0,100 contre 0,131 pour le 37ᵉ retenu), pas par la
  soustraction de la review. La règle 2 mord bien — **49 classes déficitaires
  ont un besoin résiduel nul grâce à la file** (`alloc.review_covered`) — mais
  ce groupe n'en est pas l'illustration.
* **Aucun groupe écarté par le cooldown** (la dernière recherche eBay date du
  2026-08-16, et sur 3 groupes seulement), **aucun par `empty_upstream`** : la
  base ne contient toujours aucune preuve d'un marché vide.
* Les commandes imprimées sont **5 vagues de 8 groupes** ; le mode réel les
  enchaîne et s'arrête à la première en échec, pour ne pas brûler la suite.

## Combien de classes sont vraiment introuvables sur eBay

Mesuré le 2026-08-20, en croisant l'état de chaque classe avec l'historique
`discovery_searches` de son groupe (script : `scripts/allocate_ebay_scrape.py`,
fonctions `build_class_states` + `_search_history` + `_group_queries`) :

```
classes à 0 exemplaire ET 0 candidat en file : 357
  dont groupe JAMAIS cherché sur eBay        : 350
  dont groupe déjà cherché, rien récolté     :   7
```

**Sept.** Sept classes seulement — AD 2021-2024, BE 2005, BE 2021 « Carolus V »…
— ont vu leur groupe interrogé sans qu'aucun crop exploitable n'en sorte. Elles
sont les seules candidates crédibles au verdict « absent du marché », et même
pour elles ce n'est pas prouvé : le groupe a pu remonter des annonces attribuées
à une sœur, ou perdues au crop.

Autrement dit : **le problème des classes sans crop n'est pas un problème de
marché, c'est un problème de couverture.** 98 % d'entre elles n'ont jamais été
cherchées. L'allocateur ne peut pas faire apparaître une commémorative rare qui
n'est pas en vente, mais aujourd'hui ce cas est marginal devant le simple fait
qu'on n'a jamais regardé.
