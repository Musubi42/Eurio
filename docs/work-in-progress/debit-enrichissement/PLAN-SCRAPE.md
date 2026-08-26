# Plan du scrape ciblé — ce sur quoi le PO donne son feu vert

> Lot **P3** du chantier [`SUIVI.md`](./SUIVI.md). Écrit le **2026-08-26**.
> Toutes les mesures viennent de `ml/state/eurio.replica.db` (réplique pull-ée
> le **2026-08-26 20:16:24Z**, `ml/state/eurio.replica.db.sync.json`) et de
> `ml/state/eurio.local.db` (compteurs de quota). Chaque chiffre porte sa
> commande. **Rejoue-la après tout pull** — la base bouge.

## ⛔ À lire avant de dépenser un seul appel

1. **Le goulot n'est plus le scrape.** 307 classes sur 671 sont bloquées par la
   **review**, 265 par le scrape, 99 sont pleines. L'allocateur écarte lui-même
   **89 classes** en disant « déficit couvert par la review, pas par le quota ».
2. **Le facteur limitant n'est pas le quota, c'est la file.** 10 440 items
   ouverts ; les deux derniers scrapes ont créé **1,84** et **1,65 item de
   review par appel eBay**. Un plan à 3 846 appels ajoute **~7 000 items**.
3. **Le cooldown 30 j de l'allocateur est aveugle.** `discovery_searches` n'est
   plus alimentée depuis le **2026-06-16** : les runs par `--target-eurio-ids`
   ne s'y inscrivent pas. L'allocateur peut reproposer un groupe ratissé il y a
   48 h.
4. **`source_runs.n_calls` ment** (8 appels rapportés pour 1 186 réels le
   23/08). Le seul compteur vrai est `api_call_log` dans `ml/state/eurio.local.db`.

---

## A · Le gratuit — `score_recover`, épuisé là où il servait

### A1. Le périmètre restant

```bash
sqlite3 -readonly ml/state/eurio.replica.db "WITH li AS (SELECT substr(si.source_ref,1,instr(si.source_ref,'_img')-1) AS listing, MAX(EXISTS(SELECT 1 FROM image_assets a WHERE a.source_image_id=si.id AND a.storage_status='present')) AS has_asset, MAX(si.crop_status='zero_crops' AND si.storage_path IS NOT NULL) AS has_zero_raw FROM source_images si WHERE si.source='ebay' AND instr(si.source_ref,'_img')>0 GROUP BY 1) SELECT COUNT(*), SUM(has_asset=0), SUM(has_asset=0 AND has_zero_raw=1) FROM li;"
# → 9985|3216|2441
```

| | annonces | images |
|---|---:|---:|
| annonces eBay au total | 9 985 | — |
| sans aucun crop | 3 216 | — |
| **rejouables** (≥ 1 raw en `zero_crops`) | **2 441** | **4 055** |
| déjà rejouées sous `recover=ON` | 306 | 409 |
| **jamais rejouées** | **2 135** | **3 646** |

Décomposition par état de la classe visée × déjà-rejoué :

```bash
cd ml && ./.venv/bin/python -c "import sqlite3; from collections import Counter; from scripts.reprocess_zero_crops import select_lost_listings; conn=sqlite3.connect('file:state/eurio.replica.db?mode=ro',uri=True); conn.row_factory=sqlite3.Row; lost=select_lost_listings(conn,scope='all'); seen=set(r[0] for r in conn.execute('SELECT DISTINCT substr(si.source_ref,1,instr(si.source_ref,\"_img\")-1) FROM source_images si JOIN source_image_runs sir ON sir.source_image_id=si.id JOIN source_runs r ON r.id=sir.run_id WHERE r.started_at>=\"2026-08-21\"')); c=Counter(); im=Counter()
for ll in lost: c[(ll.class_state, ll.listing in seen)]+=1; im[(ll.class_state, ll.listing in seen)]+=ll.n_images
for k in sorted(c): print(k, c[k], im[k])"
```

| état classe | jamais rejouée | déjà rejouée |
|---|---:|---:|
| `deficit` (<8 fps) | **0** | 191 (250 img) |
| `near` (8-9) | 17 (18 img) | 18 (32 img) |
| `full` (≥10) | **1 509 (2 613 img)** | 36 (50 img) |
| `unresolvable` | **609 (1 014 img)** | 61 (78 img) |

### A2. Le dry-run

```
$ go-task ml:src:ebay:reprocess-zero -- --dry-run
[reprocess] scope=deficit · 191 annonce(s) perdue(s) · 250 image(s) à rejouer
  par listing_country : LU 44, DE 33, ES 24, FR 24, VA 14, IT 13, BE 10, MT 9, EE 7, LT 6, CY 4, FI 2, AD 1
  par état de classe  : deficit (<8 fps) 191, 8-9 0, full (>=10) 0, unresolvable 0
  classes visées      : 84

$ go-task ml:src:ebay:reprocess-zero -- --dry-run --scope all
[reprocess] scope=all · 2441 annonce(s) perdue(s) · 4055 image(s) à rejouer
  par listing_country : DE 440, FR 395, AT 298, FI 263, ES 240, BE 220, AD 218, IT 150, CY 98, LU 62, MT 17, EE 16, VA 15, LT 9
  par état de classe  : deficit (<8 fps) 191, 8-9 35, full (>=10) 1545, unresolvable 670
  classes visées      : 167
```

⛔ **Les 250 images du scope par défaut ont DÉJÀ été rejouées sous
`recover=ON`.** Preuve :

```bash
cd ml && ./.venv/bin/python -c "import sqlite3; from scripts.reprocess_zero_crops import select_lost_listings; conn=sqlite3.connect('file:state/eurio.replica.db?mode=ro',uri=True); conn.row_factory=sqlite3.Row; lost=select_lost_listings(conn, scope='deficit'); ids=[i for ll in lost for i in ll.images.values()]; ph=','.join('?'*len(ids)); print(len(lost), len(ids), conn.execute(f'SELECT COUNT(DISTINCT sir.source_image_id) FROM source_image_runs sir JOIN source_runs r ON r.id=sir.run_id WHERE r.started_at>=\"2026-08-21\" AND sir.source_image_id IN ({ph})', ids).fetchone()[0])"
# → 191 250 250   (191 annonces, 250 images, 250 déjà rejouées)
```

### A3. Rendement attendu

Constantes du run de référence `10408fc2d40945e491d656cb0b75d2b5` (2026-08-21,
51 min 09 s / 1 215 images) : **2,53 s/image**, **0,73 crop/image**, **0,60
item de review/image**, 82 % d'annonces récupérées.

| passe | images | durée Mac | crops attendus | items de review | valeur pour la banque |
|---|---:|---:|---:|---:|---|
| `--scope deficit` (défaut) | 250 | 11 min | **~0** — déjà rejouées | ~0 | **nulle** |
| poche `unresolvable` jamais rejouée | 1 014 | **43 min** | ~740 | ~610 | incertaine (cible à retrouver par DINO) |
| poche `full` jamais rejouée | 2 613 | 1 h 50 | ~1 900 | ~1 570 | **nulle** (D3 : on ne gonfle pas les classes pleines) |
| `--scope all` | 4 055 | **2 h 51** | ~2 960 | ~2 430 | marginale, coût review massif |

**Recommandation : ne pas lancer la passe par défaut.** Elle produira un run
vide et un exit 0.

Le seul geste qui a une chance de rapporter est la poche `unresolvable`. Il n'y
a pas de `--scope` pour elle — on passe par `--listing-ids` :

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3
from scripts.reprocess_zero_crops import select_lost_listings
conn=sqlite3.connect('file:state/eurio.replica.db?mode=ro',uri=True); conn.row_factory=sqlite3.Row
lost=[l for l in select_lost_listings(conn, scope='all') if l.class_state=='unresolvable']
print(','.join(l.listing for l in lost))" > /tmp/unresolvable.txt   # 670 annonces, 1092 images
go-task ml:src:ebay:reprocess-zero -- --listing-ids "$(cat /tmp/unresolvable.txt)" --limit 60 --seed 42 --push
```

**Témoin à vérifier en PREMIÈRE LIGNE de log**, sinon le script sort en 2 et ne
crée aucun run :

```
recover=ON tau=0.55 scope=all listings=N images=M
```

Mesurer sur 60 annonces avant d'engager les 610 restantes : si le taux de
récupération tombe sous ~40 %, arrêter — cette poche n'a pas été rejouée parce
qu'elle est structurellement moins bonne (pas de cible résolue).

---

## B · Le payant — le scrape ciblé

### B1. Le besoin, remesuré

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3; from pathlib import Path
from serving.scrape_plan_routes import summarize
conn=sqlite3.connect('file:state/eurio.replica.db?mode=ro',uri=True); conn.row_factory=sqlite3.Row
d=summarize(conn, Path('state/eurio.local.db')).model_dump(); print(d['totals']); print(d['quota'])"
# totals = {'n_classes': 265, 'n_zero': 247, 'n_never_targeted': 241,
#           'n_targeted_no_result': 24, 'sum_need': 2009, 'n_groups': 205,
#           'estimated_calls': 27310, 'estimated_listings_palier1': 1730}
# quota  = {'period':'2026-08-26','limit':5000,'calls':0,'remaining':5000,'safe_budget':3846}
```

`bottleneck=scrape` n'est plus 349 mais **265 classes** (241 jamais ciblées,
24 ciblées sans résultat, 247 à zéro exemplaire), pour **2 009 exemplaires de
déficit** et **205 groupes de découverte = 27 310 appels estimés**.

| pays | classes | à zéro | jamais ciblées | need | groupes | dont std | appels | annonces palier 1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SM | 32 | 32 | 32 | 256 | 23 | 1 | 3 100 | 230 |
| PT | 31 | 31 | 31 | 239 | 19 | 0 | 2 470 | 223 |
| MT | 24 | 24 | 23 | 183 | 15 | 1 | 2 060 | 165 |
| FI | 21 | 19 | 21 | 159 | 16 | 0 | 2 080 | 151 |
| GR | 20 | 19 | 20 | 156 | 13 | 0 | 1 690 | 144 |
| MC | 16 | 16 | 16 | 128 | 15 | 1 | 2 060 | 115 |
| SI | 16 | 16 | 16 | 125 | 15 | 0 | 1 950 | 115 |
| SK | 16 | 16 | 16 | 119 | 15 | 0 | 1 950 | 115 |
| LU | 14 | 14 | 14 | 106 | 12 | 0 | 1 560 | 101 |
| NL | 13 | 13 | 13 | 92 | 10 | 1 | 1 410 | 93 |
| LT | 12 | 12 | 11 | 93 | 9 | 0 | 1 170 | 79 |
| LV | 9 | 9 | 9 | 69 | 8 | 0 | 1 040 | 65 |
| HR | 7 | 6 | 7 | 55 | 5 | 1 | 760 | 50 |
| AD, FR, VA, IE, IT, DE, EE, ES, BG | 30 | 20 | 12 | 229 | 30 | 1 | 3 810 | 86 |
| **TOTAL** | **265** | **247** | **241** | **2 009** | **205** | **6** | **27 310** | **1 730** |

### B2. L'unité de coût réelle — pas « pays × langue »

Le routage est **uniforme** : tout groupe est cherché sur EBAY_DE (allemand)
**puis** EBAY_ES (espagnol), quel que soit le pays de la pièce.

- `ml/sources/ebay/adapter.py:213-217` — « Routage uniforme : EBAY_DE puis
  EBAY_ES … `marketplaces = [(c.marketplace, c.query_lang) for c in discovery_marketplaces()]` »
- `ml/sources/ebay/marketplaces.py:87-93` — « Renvoie les marketplaces à
  interroger en discovery (DE puis ES). Le pays du coin n'entre plus dans la
  décision »

Vérifié dans la donnée :

```bash
sqlite3 -readonly -header -column ml/state/eurio.replica.db "SELECT r.id, substr(r.started_at,1,10), COUNT(*) n_searches, COUNT(DISTINCT json_extract(ds.query_filters_json,'$.group.country')||'/'||COALESCE(json_extract(ds.query_filters_json,'$.group.year'),'std') ) n_groupes FROM discovery_searches ds JOIN source_runs r ON r.id=ds.run_id GROUP BY 1 ORDER BY r.started_at DESC LIMIT 8;"
# n_searches = 2 × n_groupes sur chaque run (20/10, 4/2, 2/1…)
```

> **1 groupe de découverte = 2 recherches + 1 `item/{id}` par annonce retenue
> ≈ 130 appels (commémo) ou 240 (standard).**

Les 2 recherches sont du bruit dans la facture ; **99 % du coût est
l'hydratation**. Vérifié : 1 186 appels pour 1 125 annonces persistées le
2026-08-23.

**205 requêtes de découverte couvrent les 265 classes** — **1,29 classe par
requête** en moyenne. Les meilleures en couvrent 3 (MT/2022, NL/2013, PT/2024 :
3 classes chacune pour 130 appels).

### B3. Quota et coût humain

```bash
sqlite3 -readonly ml/state/eurio.local.db "select period, calls from api_call_log where source='ebay' order by rowid desc limit 6;"
# 2026-08-24|1249 · 2026-08-23|1186 · 2026-08-16|740 · 2026-06-15|717 · 2026-06-14|281 · 2026-06-13|1163
sqlite3 -readonly ml/state/eurio.replica.db "SELECT status, COUNT(*) FROM review_queue GROUP BY 1;"
# done|7486 · open|10440 · skipped|76
sqlite3 -readonly -header -column ml/state/eurio.replica.db "SELECT id, substr(started_at,1,10), n_raws_added, n_crops_added, n_review_enqueued FROM source_runs WHERE source='ebay' ORDER BY started_at DESC LIMIT 3;"
```

| | valeur |
|---|---:|
| quota du jour (2026-08-26) | 5 000, **0 consommé** |
| budget planifiable (marge ×1,3) | **3 846** |
| items de review par appel eBay | **1,65** (24/08) à **1,84** (23/08) — 0,71 le 16/08 |
| file déjà ouverte | **10 440** |
| rendement | **7,18 annonces / exemplaire** (contre 6,6 au 22/08) — il **se dégrade** |

### B4. Le plan d'allocation

```bash
go-task ml:ebay:allocate
# [quota] restant aujourd'hui 5000/5000 → budget planifiable 3846 (marge ×1.3)
# groupes retenus 29 / coût prévu 3770 appels / exemplaires visés 475 sur 3228
# hors budget (reportés) 294 groupe(s), 39760 appels
# déficit couvert par la review, pas par le quota : 89 classe(s)
go-task ml:ebay:allocate -- --budget 100000 --format json --out /tmp/plan.json
# {'cost': 43530, 'n_groups': 323}
```

**Ordre imposé par l'allocateur** (score = besoin × classes servies / coût),
29 groupes pour 3 770 appels :

| rang | groupe | coût | cumul | need | classes | dont scrape | déjà en file |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | MT/2022 | 130 | 130 | 24 | 3 | **3** | 0 |
| 2 | NL/2013 | 130 | 260 | 24 | 3 | **3** | 0 |
| 3 | PT/2024 | 130 | 390 | 24 | 3 | **3** | 0 |
| 4 | IT/2022 | 130 | 520 | 17 | 3 | 1 | 2 |
| 5 | AD/2023 | 130 | 650 | 15 | 2 | 2 | 0 |
| 6 | BE/2023 | 130 | 780 | 11 | 2 | **0** | 3 |
| 7 | FI/2025 | 130 | 910 | 15 | 2 | 2 | 0 |
| 8 | GR/2026 | 130 | 1 040 | 15 | 2 | 2 | 0 |
| 9 | LU/2012 | 130 | 1 170 | 22 | 3 | 1 | 2 |
| 10 | PT/2015 | 130 | 1 300 | 22 | 3 | 2 | 2 |
| 11 | PT/2017 | 130 | 1 430 | 22 | 3 | 3 | 2 |
| 12 | FR/2014 | 130 | 1 560 | 21 | 3 | 2 | 1 |
| … | (17 groupes de plus) | | 3 770 | | 68 | 40 | |

Paliers, si le PO veut arbitrer le budget :

| budget | groupes | appels | classes déficitaires servies | dont `bottleneck=scrape` | exemplaires visés | items de review créés (est.) |
|---:|---:|---:|---:|---:|---:|---:|
| 3 846 (aujourd'hui) | 29 | 3 770 | 68 | 40 | 475 | ~6 900 |
| 5 000 | 38 | 4 940 | 86 | 58 | 619 | ~9 100 |
| 10 000 (2 j) | 76 | 9 990 | 164 | 119 | 1 237 | ~18 300 |
| 20 000 (4 j) | 150 | 19 940 | 292 | 171 | 2 102 | ~36 600 |
| 43 530 (9 j) | 323 | 43 530 | 470 | 265 | 3 228 | ~80 000 |

> ⚠️ Les colonnes « items de review créés » sont des **estimations** au ratio
> 1,84 item/appel mesuré le 23/08 — pas des mesures. Elles servent à arbitrer,
> pas à rendre compte.

---

## C · Ce qui est proposé au feu vert du PO

### Vague 0 — avant tout appel eBay · coût : 0 quota

**Purger la file.** 307 classes sur 671 sont bloquées par la review ;
l'allocateur écarte lui-même 89 classes en disant « déficit couvert par la
review, pas par le quota ». Scraper avant d'avoir entamé les 10 440 items
ouverts, c'est acheter ce qu'on a déjà en stock.

Deux gestes concurrents, tous deux hors quota :
[`PLAN-PECHE-PAYS.md`](./PLAN-PECHE-PAYS.md) (1 193 crops récupérés) et
[`PLAN-ECRAN-BINAIRE.md`](./PLAN-ECRAN-BINAIRE.md) (cadence de review).

### Vague 1 — 3 groupes, ~390 appels, aujourd'hui

Les rangs 1 à 3 : **MT/2022**, **NL/2013**, **PT/2024**. Ce sont les seuls
groupes où **3 classes sur 3** sont en `bottleneck=scrape`, à zéro exemplaire,
**sans rien en file** — rendement maximal, aucun doublon possible.

```bash
go-task ml:src:ebay:run -- --target-eurio-ids \
  mt-2022-2eur-35-years-of-the-erasmus-programme,\
nl-2013-2eur-200-years-kingdom-of-the-netherlands,\
pt-2024-2eur-50-years-of-carnation-revolution --push
```

Puis **immédiatement** :

```bash
sqlite3 -readonly ml/state/eurio.local.db "select period, calls from api_call_log where source='ebay' and period=date('now');"
```

**Attendu ~390 appels.** Si le compteur dit 800, le modèle de coût est faux d'un
facteur 2 et **tout le plan ci-dessus est à refaire** avant d'engager quoi que
ce soit d'autre.

### Vague 2 — 6 groupes, 780 appels · après confrontation du coût réel

Rangs 5, 7, 8, 10, 11, 12 : AD/2023, FI/2025, GR/2026, PT/2015, PT/2017,
FR/2014.

**À écarter** : les rangs 6, 14, 15, 17, 18, 19, 24 — ils ont **0 classe en
`bottleneck=scrape`** (leur déficit est couvert par la file ; le rang 24,
FR/2015, a **77 candidats en attente**).

### Plafond dur recommandé : **1 500 appels aujourd'hui**, pas 3 846

À 1,84 item par appel, 1 500 appels créent déjà **~2 800 items** à trancher sur
une file qui en porte 10 440.

### Avant la vague 3

**Réalimenter `discovery_searches`** sur les runs par `--target-eurio-ids`,
sinon le cooldown 30 j reste aveugle et l'allocateur re-proposera des groupes
ratissés les 23 et 24 août. En attendant, croiser à la main les cibles du plan
avec les `target_eurio_id` des runs `3110a3ba…` (2026-08-23) et `fe5fd8f6…`
(2026-08-24).

---

## D · Les pièges de ce plan

| Piège | Ce qu'il fait |
|---|---|
| `--scope deficit` a l'air d'être le bon geste (c'est le défaut documenté, le dry-run rend 191 annonces) | ses 250 images sont déjà rejouées : run à ~0 crop, exit 0. La preuve d'utilité se prend **avant**, en croisant les images du scope avec `source_image_runs` |
| Le témoin `recover=ON tau=… scope=… listings=N images=M` | prouve que la passe de secours est active, **pas** que le périmètre est neuf |
| `--push` n'est pas un transport | c'est le choix de la base inscriptible (réplique scratch). Sans lui, sous le devShell (`EURIO_DB_READONLY=1`), le script meurt en `attempt to write a readonly database` dans `run_logger.start_run`. Le push au canonique est automatique dès qu'`EURIO_API_URL` est posé |
| Le cooldown 30 j est **aveugle** | `discovery_searches` non alimentée depuis le 2026-06-16 |
| Les coûts 130/240 appels par groupe sont des **estimations** | mesurées sur 15 groupes observés en 3 journées de juin, corroborées grossièrement sur août. Un plan à 3 846 appels peut en coûter 3 000 ou 5 500 |
| `source_runs.n_calls` ment | 8 rapportés pour 1 186 réels le 23/08. Relire `api_call_log` **après chaque vague** |
| `n_targets` d'un run ne dit pas ce qui a été ciblé | 58 `target_eurio_id` distincts pour 3 pièces demandées le 16/08 — `resolve` réattribue la cible à n'importe quel membre du groupe ramené |
| Deux comptes de classes cohabitent | l'allocateur planifie sur **470** classes déficitaires (min-need 2, tous bottlenecks), `scrape_plan_routes` n'en retient que **265** (`bottleneck=scrape` strict). 205 groupes / 27 310 appels et 323 groupes / 43 530 appels ne mesurent pas la même chose |
| La réplique lue ici date du **2026-08-26 20:16 UTC** | tout chiffre est à cette photo. Le refaire après un pull |
