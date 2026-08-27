# Suivi — le débit d'enrichissement, étape par étape

> **Le document de pilotage de ce chantier.** Ouvert le **2026-08-26** à la
> demande du PO, sur le modèle de
> [`../juge-et-banc/SUIVI-MATRICE.md`](../juge-et-banc/SUIVI-MATRICE.md). Il dit
> où on en est, ce qui est décidé, ce qui reste, et sur quelle machine.
>
> Mets-le à jour à chaque étape franchie. **Un suivi qui ment est pire que pas
> de suivi.** Tout chiffre porte sa requête — recopie la requête, jamais le
> nombre.

## ⏱️ OÙ ON EN EST — 2026-08-26, fin de session

**Le goulot a changé de côté et personne ne l'avait vu : ce n'est plus le
scrape, c'est la review.** 307 classes sur 671 attendent un humain, 265
attendent un appel eBay. La file ouverte porte **10 440 items**, et la machine
n'a plus auto-accepté un seul crop depuis le **2026-07-08**.

| | |
|---|---|
| **verdict** | le débit est plafonné par la **review humaine**, pas par le quota eBay ni par le crop. Le gratuit (`score_recover`) est **épuisé là où il servait**, et les seuils d'auto-accept sont **quasi inertes** — la marge n'est pas où on la croyait |
| **fait** | 4 photos de départ chiffrées et rejouables · 1 script neuf (`sweep_verdict_thresholds.py`) · lot 0 (colmatage review en lot) et lot 5 (matrice) écrits et testés · 3 plans d'exécution |
| **pas fait** | **rien n'est déployé**, rien n'est commité, aucune migration appliquée, aucun scrape lancé, aucun seuil changé. Le lot 0 porte **un bloquant de déploiement** (§Vérification adversariale) |
| **machine** | Mac (mesures, réplique read-only). Le VPS n'a **pas** été touché. Le PC n'a pas servi |
| **données** | réplique `ml/state/eurio.replica.db`, **faits arrêtés au 2026-08-24 23:31** — le fichier a été resynchronisé le 26/08 à 20:16-20:28, la date du fichier ne dit rien de la fraîcheur des faits |

### ⛔ Les trois choses à savoir avant de toucher quoi que ce soit

1. **Le lot 0 ne peut pas être déployé front-d'abord.** `isActionable()` exige
   `review_kind`/`review_status`, deux champs que le canonique **déployé ne sert
   pas** (`curl -s https://eurio-api.musubi.dev/openapi.json` → `LotCrop` n'a ni
   l'un ni l'autre). Front seul en avance = écran de review en lot **mort**,
   avec un message plausible et faux. Back d'abord, obligatoirement.
2. **`PUT /lab/dino-thresholds` sur `top1_country_sim_min` /
   `country_spread_min` répond 200, journalise, et ne change RIEN.** Ces seuils
   sont trois littéraux en dur. Panne muette de manuel.
3. **`go-task ml:src:ebay:reprocess-zero` (scope par défaut) produira un run
   vide et un exit 0** : ses 250 images ont déjà été rejouées sous `recover=ON`
   les 21/23/24 août.

## L'objectif, en une phrase

Augmenter le **débit de crops validés** — pour que le modèle reconnaisse de plus
en plus de pièces — en gardant la **matrice d'encodeurs** comme instrument de
mesure permanent, par quatre leviers : mieux scraper eBay, mieux cropper, mieux
reconnaître, mieux auto-valider.

---

## La photo de départ — 2026-08-26 (données arrêtées au 2026-08-24 23:31)

> C'est la **ligne de base**. Dans un mois, on rejoue ces requêtes et on
> compare. Chaque bloc porte sa commande exacte.

### 0 · La fraîcheur des faits (à jouer en premier, toujours)

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
 select 'rq_max_enqueued', max(enqueued_at) from review_queue
 union all select 'rq_max_decided', max(decided_at) from review_queue
 union all select 'ia_max_fetched', max(fetched_at) from image_assets;"
```

| clé | valeur |
|---|---|
| `rq_max_enqueued` | 2026-08-24 23:31:02 |
| `rq_max_decided` | 2026-08-24T23:03:34Z |
| `ia_max_fetched` | 2026-08-24 23:24:19 |

→ **aucune activité d'enrichissement, de review ni de scrape depuis 2 jours.**
Le débit de départ est mesuré sur un système à l'arrêt.

### 1 · Couverture de la banque

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, collections, sys; sys.path.insert(0,'.')
from shared.class_need import all_needs
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True); c.row_factory = sqlite3.Row
n = all_needs(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')
print('classes', len(n))
print('bottleneck', dict(collections.Counter(x.bottleneck for x in n)))
print('sum need', sum(x.need for x in n))
print('couverture have>=1', sum(1 for x in n if x.have>=1))
print('scoped', sum(x.pending_scoped for x in n), '/ brut', sum(x.pending for x in n))"
```

| Grandeur | Valeur |
|---|---:|
| classes de la banque | 671 |
| couverture `have ≥ 1` | **269 / 671** (40,1 %) |
| classes à zéro exemplaire | 402 |
| Σ `need` | **3 921** |
| bottleneck `pleine` | 99 |
| bottleneck **`review`** | **307** |
| bottleneck `scrape` | 265 |

Complément (même connexion, `all_needs`) :

```bash
print('accepted_pending', sum(x.accepted_pending for x in n), 'accepted_by_model', sum(x.accepted_by_model for x in n))
print('rebuild_would_place', sum(min(x.need,x.accepted_pending) for x in n))
print('coverage_acquired', sum(1 for x in n if x.have+x.accepted_pending>=1))
print('sum_reachable', sum(min(x.need,x.pending_scoped) for x in n if x.bottleneck!='pleine'))
```

| Grandeur | Valeur |
|---|---:|
| acquis pas encore bâtis (`accepted_pending`) | 62 |
| ce qu'un rebuild poserait | **54** → couverture 269 **→ 282** |
| `accepted_by_model` | 1 577 |
| « à portée de la file » (`sum_reachable`) | 1 022 |
| classes `scrape` **jamais visées** (`pending = 0`) | **216** |

Besoin par pays (classes non pleines, `need` cumulé), top 12 :
LU 382 · VA 310 · PT 296 · SM 291 · MT 260 · GR 250 · FI 238 · IT 176 ·
FR 174 · LT 162 · SK 161 · SI 159.

**Banque servie** — `sqlite3 -readonly -header -column ml/state/eurio.replica.db
"select * from dino_anchor_builds order by built_at desc limit 3;"` :
build `53d22c388ee744c599a3e24fe1f76830`, `2eur_all` / `dinov2-vitl14`, bâti le
**2026-08-24 20:41:15**, 671 classes, 2 062 lignes (671 canoniques + 1 391
exemplaires), cap 10, `min_exemplars=1 (source=code)`, amorce médoïde,
0 classe ramenée au canonique seul.

⚠️ **Écart avec l'instantané figé de
[`../pipeline-propre/REPRENDRE-ICI.md:26`](../pipeline-propre/REPRENDRE-ICI.md)** :

| | doc (figé) | joué le 2026-08-26 |
|---|---:|---:|
| bottleneck `pleine` / `review` / `scrape` | 109 / 213 / 349 | 99 / **307** / 265 |
| Σ need | 4 066 | 3 921 |
| couverture | 250 | 269 |
| file brute | 6 371 | **10 440** |

Le doc le dit lui-même : **rejouer, ne pas recopier.**

### 2 · La file de review ouverte

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, sys; sys.path.insert(0,'.')
from shared.class_need import all_needs
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True); c.row_factory = sqlite3.Row
n = all_needs(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')
n_open = c.execute(\"SELECT COUNT(*) AS n FROM review_queue WHERE status='open'\").fetchone()['n']
print('n_open', n_open, '| pending total', sum(x.pending for x in n))
print('parked.full_class', sum(x.pending for x in n if x.bottleneck=='pleine'))
print('pending_scoped', sum(x.pending_scoped for x in n))
print('scoped non pleines', sum(x.pending_scoped for x in n if x.bottleneck!='pleine'))
print('hidden era', sum(x.n_hidden_by_era for x in n), 'pays', sum(x.n_hidden_by_country for x in n), 'denom', sum(x.n_hidden_by_denom for x in n))
print('country_disarmed classes', sum(1 for x in n if x.country_disarmed))"
```

| Grandeur | Valeur |
|---|---:|
| items ouverts | **10 440** |
| parqués (`parked.full_class`, classes à leur cible) | 6 587 |
| parqués sans prédiction (`no_prediction`) | 0 |
| écartés par l'**ère** | 3 248 |
| écartés par le **pays** | 2 233 |
| écartés par la **dénomination** | **0** (porte sans appelant — défaut connu) |
| `pending_scoped` | 4 959 |
| — dont classes pleines (non servies) | 2 423 |
| — **réellement servis** | **2 536** |
| classes à garde-pays désarmée | 100 / 671 |

Contrôle d'identité : `10 440 − 3 248 − 2 233 = 4 959 = pending_scoped`.

Structure lane × statut —
`sqlite3 -readonly -header -column ml/state/eurio.replica.db "select lane, status, count(*) n from review_queue group by 1,2 order by n desc;"` :
`manual` 9 691 open / 6 962 done / 59 skipped · `auto_accept` 749 open /
524 done / 17 skipped.

### 3 · L'auto-accept — arrêté depuis le 2026-07-08

```bash
sqlite3 -readonly -header -column ml/state/eurio.replica.db "select decided_by, decision_engine_version, count(*) n, min(decided_at) d0, max(decided_at) d1 from review_queue where lane='auto_accept' and status='done' group by 1,2 order by n desc;"
sqlite3 -readonly -header -column ml/state/eurio.replica.db "select substr(decided_at,1,7) mois, count(*) n from review_queue where decided_by='auto_dino' group by 1 order by 1;"
```

| Grandeur | Valeur |
|---|---:|
| tranchés par la machine (`decided_by='auto_dino'`) | **235** |
| période | 2026-06-02 23:02 → **2026-07-08 17:42** (juin 196, juillet 39) |
| depuis le 2026-07-08 | **0** |
| moteur | `auto_dino@s0.55-d0.05` |
| `lane=auto_accept` done tranchés **à la main** | 289 (admin 283, un reviewer 6) |

Seuils actifs — `sqlite3 -readonly ml/state/eurio.replica.db "select count(*) from dino_thresholds;"` → **0 ligne**.
Tout vient de `ml/shared/dino_threshold_defaults.py`, `DEFAULTS[('2eur_all','dinov2-vitl14')]` :

| clé | valeur | source |
|---|---:|---|
| `top1_country_sim_min` | 0,55 | code |
| `country_spread_min` | 0,05 | code |
| `spread_uncertain_max` | 0,02 | code |
| `spread_confident_min` | 0,05 | code |
| `spread_auto_accept_min` | 0,10 | code |
| `min_exemplars` | 1 (plancher inactif) | code |

`dino_threshold_changes` ne porte que **2 lignes** : la pose puis le retrait du
plancher `min_exemplars=2` le 2026-08-20.

### 4 · Le verdict d'auto-validation, balayé sur le gold

Script **neuf**, laissé dans l'arbre, read-only : `ml/scripts/sweep_verdict_thresholds.py`.
Il mute `DINO_VERDICT_THRESHOLDS` **en mémoire** et rappelle la vraie
`compute_auto_validate_verdict_from_row` — il note la règle réelle, pas une
copie.

```bash
cd ml && ./.venv/bin/python -m scripts.sweep_verdict_thresholds \
  --sim-grid 0.0:0.70:0.05 --spread-grid 0.0:0.12:0.01 --csv /tmp/sweep.csv
```

Population : **466 crops** (811 labellisés du gold − les ancres de la banque).
Gold : `ml/state/validation_gold/verdict_gold.jsonl`, 1 009 entrées dont 811
labellisées, committé par `9432fa23` (15 juin 2026), **non gitignoré**.

| sim_min | spread_min | n_auto | justes | faux | précision |
|---:|---:|---:|---:|---:|---:|
| 0,00 | 0,000 | 192 | 191 | 1 | 99,48 % |
| 0,55 | 0,000 | 191 | 190 | 1 | 99,48 % |
| 0,55 | 0,030 | 190 | 189 | 1 | 99,47 % |
| **0,55** | **0,050** | **186** | **185** | **1** | **99,46 %** ← point actuel |
| 0,55 | 0,080 | 174 | 173 | 1 | 99,43 % |
| 0,55 | 0,110 | 152 | 152 | 0 | 100,00 % |
| 0,70 | 0,050 | 184 | 183 | 1 | 99,46 % |

**Résultat central : les deux seuils sont quasi inertes.** Les désarmer
complètement rapporte **+6 auto-accepts sur 186 (+3,2 %)**, pas ×2.
`sim_min` est **strictement inerte de 0,00 à 0,50** (sim minimale observée :
0,5317).

Pourquoi (script de diagnostic, même population de 466) : sur les 192 crops qui
passent les 4 premières règles, **1 seul** a une sim < 0,55 et **5** un spread
< 0,05. Le volume est plafonné par les règles 1 à 4 :
`divergent` 89 · `auto_candidate` 192 · `partial` 105 · `unknown` 80 ;
raisons de non-auto : « Top1 Dino != cible » 88 · « Pas de target connu » 80 ·
« texte non comparé » 66 · « texte partial » 39 · « Texte contredit » 1.

L'unique faux positif est toujours le même : asset `a224e061d0d24765831f85b99e8934cc`,
décidé `fi-2016-…-eino-leino`, vrai `fi-2016-…-georg-henrik-von-wright`,
sim 0,8729, spread 0,1036. Le premier point de grille qui l'écarte est
`spread_min = 0,11` — au prix de 18 % du volume.

**Le vrai levier n'est pas un seuil, c'est la règle du texte** :

| point | règle | gold : auto / justes / précision | file ouverte |
|---|---|---:|---:|
| **actuel** | sim ≥ 0,55 · spread ≥ 0,05 · texte **convergent** | 186 / 185 / 99,46 % | 1 656 |
| seuils désarmés | sim ≥ 0 · spread ≥ 0 · texte convergent | 192 / 191 / 99,48 % | 2 236 |
| **A** | sim ≥ 0,55 · spread ≥ 0,05 · texte **≠ contradict** | **284 / 283 / 99,65 %** | **2 121 (+28 %)** |
| B | sim ≥ 0,55 · spread ≥ **0,11** · texte ≠ contradict | 222 / 222 / **100 %** | 1 266 (−24 %) |

Détail de A : texte `convergent` 186/185 · texte `NULL` 61/61 (100 %) ·
texte `partial` 37/37 (100 %). Wilson 95 % sur 283/284 : **[98,03 % ; 99,94 %]**
→ au pire ~42 faux sur 2 121, contre ~33 aujourd'hui sur 1 656 (même borne
appliquée à 185/186 : ≥ 97,02 %).

⚠️ **Le gold n'est pas représentatif de la file ouverte sur la dimension qui
compte.** Sur le gold, **1,1 %** des éligibles ont un spread < 0,05 ; sur les
10 440 items ouverts, **26 %** (755 sur 2 904). Une courbe plate sur le gold
entre 0 et 0,05 ne dit rien de la file. Volume LIVE mesuré (même JOIN que
`auto_validate._SIGNALS_SQL`, `status='open'`), texte convergent seul | tous
textes non-contradict : `0,55/0,05` → 1 656 | 2 121 · `0,55/0,03` → 1 867 |
2 406 · `0,55/0,02` → 1 974 | 2 549 · `0,55/0,00` → 2 184 | 2 825 ·
`0,55/0,11` → 987 | 1 266.

**Le gold est périmé par le bas** : 811 labellisés de juin contre **2 599**
crops décidés-admin en base, dont **1 301** hors banque et prédits — soit
**2,8×** la population évaluable actuelle.

```bash
sqlite3 -readonly ml/state/eurio.replica.db "select count(distinct image_asset_id) from review_queue where decided_by='admin' and decided_eurio_id is not null;"   # 2599
sqlite3 -readonly ml/state/eurio.replica.db "SELECT COUNT(*) FROM (SELECT DISTINCT rq.image_asset_id aid FROM review_queue rq WHERE rq.decided_by='admin' AND rq.decided_eurio_id IS NOT NULL AND rq.image_asset_id NOT IN (SELECT asset_id FROM dino_class_references WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14' AND asset_id IS NOT NULL) AND rq.image_asset_id IN (SELECT asset_id FROM image_asset_dino_predictions WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14'));"   # 1301
```

### 5 · Les crops validés eBay

```bash
sqlite3 -readonly -header -column ml/state/eurio.replica.db "select count(*) n_crops, count(distinct ia.eurio_id) n_eurio from image_assets ia join source_images si on si.id=ia.source_image_id where ia.training_eligible=1 and si.source='ebay';"
```

→ **2 968 crops** sur **290 `eurio_id`** distincts.

Distribution à la maille `COALESCE(design_group_id, eurio_id)` (592 classes au
catalogue `coins`) :

```bash
sqlite3 -readonly -header -column ml/state/eurio.replica.db "
with elig as (
  select COALESCE(c.design_group_id, c.eurio_id) as class_id, count(*) n
  from image_assets ia
  join source_images si on si.id=ia.source_image_id
  join coins c on c.eurio_id = ia.eurio_id
  where ia.training_eligible=1 and si.source='ebay'
  group by 1),
allc as (select distinct COALESCE(design_group_id, eurio_id) as class_id from coins)
select case when coalesce(e.n,0)=0 then '0'
            when e.n between 1 and 3 then '1-3'
            when e.n between 4 and 7 then '4-7'
            when e.n between 8 and 9 then '8-9'
            else '10+' end as bucket, count(*) n_classes
from allc a left join elig e on e.class_id=a.class_id group by 1 order by 1;"
```

| crops par classe | classes | part |
|---|---:|---:|
| 0 | **342** | 57,8 % |
| 1–3 | 104 | 17,6 % |
| 4–7 | 58 | 9,8 % |
| 8–9 | 20 | 3,4 % |
| 10+ | **68** | 11,5 % |
| *(8 et plus)* | *88* | *14,9 %* |

### 6 · Le parc eBay et le gratuit restant

```bash
sqlite3 -readonly ml/state/eurio.replica.db "WITH li AS (SELECT substr(si.source_ref,1,instr(si.source_ref,'_img')-1) AS listing, MAX(EXISTS(SELECT 1 FROM image_assets a WHERE a.source_image_id=si.id AND a.storage_status='present')) AS has_asset, MAX(si.crop_status='zero_crops' AND si.storage_path IS NOT NULL) AS has_zero_raw FROM source_images si WHERE si.source='ebay' AND instr(si.source_ref,'_img')>0 GROUP BY 1) SELECT COUNT(*), SUM(has_asset=0), SUM(has_asset=0 AND has_zero_raw=1) FROM li;"
```

→ `9985|3216|2441` : **9 985 annonces**, **3 216 sans aucun crop**, **2 441
rejouables** (4 055 images).

| | annonces | images |
|---|---:|---:|
| annonces eBay | 9 985 | — |
| `source_images` (raws) | — | 20 845 |
| sans aucun crop | 3 216 | 9 320 |
| **rejouables** (≥ 1 raw `zero_crops`) | **2 441** | **4 055** |
| déjà rejouées sous `recover=ON` | 306 | 409 |
| **jamais rejouées** | **2 135** | **3 646** |

Décomposition par état de la classe visée × déjà-rejoué (`select_lost_listings(conn, scope='all')`
croisé avec `source_image_runs` sur les runs ≥ 2026-08-21) :

| état classe | jamais rejouée | déjà rejouée |
|---|---:|---:|
| `deficit` (<8 fps) | **0** | 191 (250 img) |
| `near` (8-9) | 17 (18 img) | 18 |
| `full` (≥10) | **1 509 (2 613 img)** | 36 |
| `unresolvable` | **609 (1 014 img)** | 61 |

Méthodes de détection sur les 17 625 crops eBay
(`select ia.detection_method, count(*) … group by 1`) :
`yolo+hough+rimrefine` 9 143 · `yolo+hough+polish+rimrefine` 3 627 ·
**`score_recover` 3 262 (18,5 %)** · `manual` 2 575 · autres 118.

**Débit machine** du run de référence `10408fc2d40945e491d656cb0b75d2b5`
(2026-08-21, 13:07:44 → 13:58:53, 1 215 images, 771 annonces, 888 crops,
735 items de review) : **2,53 s/image**, **0,73 crop/image**, **0,60 item de
review/image**, 82 % d'annonces récupérées.

### 7 · Le quota eBay et le coût humain d'un scrape

```bash
sqlite3 -readonly ml/state/eurio.local.db "select period, calls from api_call_log where source='ebay' order by rowid desc limit 6;"
```

→ `2026-08-24|1249` · `2026-08-23|1186` · `2026-08-16|740` · `2026-06-15|717` ·
`2026-06-14|281` · `2026-06-13|1163`. **Aucune ligne 2026-08-26.**
`summarize()` : `quota = {'period':'2026-08-26','limit':5000,'calls':0,'remaining':5000,'safe_budget':3846}`.

```bash
sqlite3 -readonly -header -column ml/state/eurio.replica.db "SELECT id, substr(started_at,1,10), n_raws_added, n_crops_added, n_review_enqueued FROM source_runs WHERE source='ebay' ORDER BY started_at DESC LIMIT 3;"
```

| run | date | raws | crops | items de review | items / appel |
|---|---|---:|---:|---:|---:|
| `fe5fd8f6…` | 2026-08-24 | 2 606 | 2 709 | 2 067 | **1,65** |
| `3110a3ba…` | 2026-08-23 | 1 998 | 2 631 | 2 177 | **1,84** |
| `10408fc2…` | 2026-08-21 | 0 | 888 | 735 | (recover) |

→ un plan à **3 846 appels ajouterait ~7 000 items** à une file qui en compte
déjà 10 440 : **+67 % de backlog en une journée de scrape.**

**Rendement remesuré** (`summarize()` → `measured_yield`) : **7,18 annonces par
exemplaire fps** (9 986 annonces / 1 391 exemplaires), contre 6,6 au 2026-08-22
— **il se dégrade**.

---

## Les décisions prises, et qu'on ne rouvre pas

| # | Décision | Date |
|---|---|---|
| **D1** | **Le goulot est la review, pas le scrape.** 307 classes bloquées par un humain contre 265 par le quota ; l'allocateur écarte lui-même 89 classes en disant « déficit couvert par la review, pas par le quota ». Toute vague de scrape passe **après** une purge de file | 2026-08-26 |
| **D2** | **On ne lance pas `reprocess-zero --scope deficit`.** Ses 250 images sont déjà rejouées sous `recover=ON` : rendement attendu **zéro**, run vide, exit 0 | 2026-08-26 |
| **D3** | **On ne gonfle pas les classes pleines.** Les 1 509 annonces `full` jamais rejouées (2 613 images, ~1 h 50 de Mac, ~1 570 items de review) ne sont **pas** rejouées | 2026-08-26 |
| **D4** | **Les deux seuils d'auto-accept ne bougent pas.** Mesuré inertes : les désarmer rapporte +3,2 %. Rien dans la courbe ne justifie une baisse, et la seule qui rapporterait (spread 0,05 → 0,03) repose sur **4 crops étiquetés** | 2026-08-26 |
| **D5** | **`top1_eurio_id` n'est jamais réécrit par une règle de routage.** Il alimente l'auto-validation (barre 99,5 %) ; le routage pays vaut 91,7 %. Le routage est une **suggestion** (périmètre + candidat affiché), jamais une écriture | 2026-08-26 |
| **D6** | **Les courantes du mauvais pays ne sont pas routées** — mesuré juste **12 fois sur 71 (17 %)**, et quand le modèle et l'annonce se contredisent sur une courante c'est le **modèle** qui a plus souvent raison (40 contre 30). Elles restent masquées, comptées, ramenables d'un clic | 2026-08-26 |
| **D7** | **Le palier texte (`top-5 ∩ pays+année`) est réservé aux commémoratives.** Sur les courantes il s'effondre : top-3 ∩ pays 67,7 %, top-5 ∩ pays 59,1 % — le pays ne distingue pas les ères d'un même pays | 2026-08-26 |
| **D12** | **Les helpers de rejet vivent dans `store/`, pas dans `steps/enqueue`.** Ils sont du SQL pur, mais `enqueue` tire `training` : le canonique — seul writer — ne pouvait pas les atteindre, donc toute passe corrective devait réécrire le rejet | 2026-08-27 |
| **D11** | **Le seuil de face passe de 0,065 à 0,000**, et la provenance de `face` entre en base (migration 0017). Le seuil ne rachetait aucun faux positif : la marge max des 514 avers du gold est −0,0507 | 2026-08-27 |
| **D10** | **La bande pays reste préférée au top-1 global, et on ne rouvre pas.** Banc à l'aveugle sur la population divergente de la file ouverte : **19 contre 3**, `p = 0,00086`. L'hypothèse inverse était de l'assistant, la mesure l'a démentie | 2026-08-27 |
| **D9bis** | **La divergence `top1_country ≠ top1_global` est un signal d'ABSTENTION, pas d'arbitrage.** Les deux voies se trompent ensemble dans **63 %** des cas | 2026-08-27 |
| **D8** | **La matrice d'encodeurs reste l'instrument de mesure permanent**, et ne se rejoue pas à chaque changement : `gold_version` + `eval_corpus` + `quantization` identifient un run. Décisions détaillées : [`../juge-et-banc/SUIVI-MATRICE.md`](../juge-et-banc/SUIVI-MATRICE.md) §Lot 5 | 2026-08-26 |

---

## Les lots

| # | Lot | État réel | Machine | Où |
|---|---|---|---|---|
| **L0** | **Colmater la review en lot** (4 fuites : flush partiel, crops déjà tranchés re-servis, erreurs muettes, raison de rejet au mauvais crop) | 🟠 **écrit, testé, NON déployé — et porte un bloquant de déploiement** (front exige 2 champs que le canonique ne sert pas) | Mac | `admin/packages/studio-local/src/features/review/`, `ml/serving/review_queue/`, `ml/store/decisions.py` |
| **L5** | **Durcir la matrice d'encodeurs** (garde vendeur testé, garde quasi-doublon, migrations 0015 `quantization`+`eval_corpus` et 0016 `inputs_digest`) | 🟠 **écrit, testé, NON déployé.** ~~débris de mutation~~ → sans objet, vérifié le 2026-08-27 (§adversarial, B2) | Mac | `ml/scripts/select_eval_holdout.py`, `ml/scripts/bench_encoder_dino.py`, `ml/serving/migrations/0015_*.sql`, `0016_*.sql` |
| **M1** | **Balayage des seuils du verdict** — script rejouable | ✅ **fait**, laissé dans l'arbre, non commité | Mac | `ml/scripts/sweep_verdict_thresholds.py` |
| **P1** | **Pêche filtrée par pays** — routage sur les 5 familles d'émission commune | 📋 **plan écrit, 0 ligne de code** | — | [`PLAN-PECHE-PAYS.md`](./PLAN-PECHE-PAYS.md) |
| **P2** | **Écran de review binaire (« nourrir »)** | 📋 **plan écrit, 0 ligne de code** | — | [`PLAN-ECRAN-BINAIRE.md`](./PLAN-ECRAN-BINAIRE.md) |
| **P3** | **Scrape ciblé** — allocation, coût, volume de review créé | 📋 **plan écrit, attend le feu vert du PO** | — | [`PLAN-SCRAPE.md`](./PLAN-SCRAPE.md) |

Aucun de ces lots n'est commité. Aucun n'est déployé. `git status` de la session
montre plusieurs agents ayant travaillé **dans le même arbre** : ne pas
attribuer les fichiers en vrac au moment de committer.

---

## ⛔ Ce que la vérification adversariale a trouvé — rien n'est adouci

### Bloquants

| # | Lot | Défaut | Preuve |
|---|---|---|---|
| **B1** | L0 | **`isActionable()` exige `review_kind`/`review_status`, que le canonique DÉPLOYÉ ne sert pas.** Aucun repli. Front seul en avance = review en lot morte, avec un message plausible et **faux** | `curl -s https://eurio-api.musubi.dev/openapi.json` → `LotCrop props: ['asset_id','bbox','candidate_eurio_ids','crop_index','crop_url','current_eurio_id','dino_spread','matches_dino_class','phash','review_id']`. Probe monté sur le harness sans ces champs : `totalActionable = 0`, `lotAlreadyDecided = true`, texte rendu « Lot déjà tranché ». Les **7 787 crops** `kind='lot' AND status='open'` deviennent invisibles. ⚠️ Vaut **aussi en `pnpm dev` local** : `eurio-api.ts:15` a pour base par défaut `https://eurio-api.musubi.dev` |
| ~~**B2**~~ | L5 | ~~débris de mutation `# MUTATION` dans `bench_encoder_dino.py`~~ — ⛔ **SANS OBJET, vérifié le 2026-08-27.** Le code porte bien `"quantization": _quantization_of(encoder)` (`bench_encoder_dino.py:552`). C'était une **course entre deux vérificateurs parallèles** : celui chargé de rejouer une mutation avait cassé cette ligne au moment où un autre lisait le fichier. La leçon vaut pour le prochain workflow : **ne jamais faire rejouer une mutation par un agent pendant qu'un autre lit le même arbre** | `grep -n quantization ml/scripts/bench_encoder_dino.py` → 470 (def), 552 (**site d'appel**), 754 (lecture). Suite complète : `2456 passed` |

### Majeurs

| # | Lot | Défaut | Preuve / mesure |
|---|---|---|---|
| **M1** | L0 | **`normalizeDecideErrors` fabrique `asset_id: ''`, que `.filter(Boolean)` élimine** : contre le canonique actuel (qui renvoie des chaînes), les décisions **refusées** sont vidées comme les autres. La promesse « les échecs restent rejouables » est fausse exactement dans la fenêtre qu'elle prétend couvrir | OpenAPI live : `LotDecideResponse.errors = {"items":{"type":"string"}}`. → `failed = new Set([''].filter(Boolean))` = ∅ → `decisions.a7` jeté |
| **M2** | L0 | **Un crop encore OUVERT en file `single` est classé « déjà tranché », désactivé, sorti de la progression.** `apply_lot_decide` ne regarde pourtant que `status='open'`, jamais `kind` : ces crops **étaient** décidables depuis l'écran de lot | **207 crops dans 109 listings** (requête CTE sur `_LISTING_KEY_SQL`, réplique du 26/08). Variante : **1 515 listings** affichent « Lot déjà tranché » alors qu'ils ont du travail ouvert. **9 listings** n'ont plus aucune row lot ouverte mais gardent des rows single ouvertes |
| **M3** | L0 | **`flushOnLeave()` avale l'échec réseau** (`console.error` seul) alors que `load()` a déjà remis `decisions = {}`. Le défaut 1 n'est pas fermé, il est **déplacé** : de « on n'envoie rien » vers « on envoie et on ne regarde pas si c'est passé ». Aucun test ne couvre ce chemin (`lot-flush.spec.ts` n'utilise que `mockResolvedValue`) | 401 / 502 / timeout 30 s → 6 décisions perdues, aucun toast, aucune `error.value` |
| **M4** | L0 | **Le verrou `submitting` est global au composant, pas au listing** : tant que le POST du lot précédent est en vol, tout flush du lot courant est un **no-op silencieux** (`return null`, ni toast ni erreur) | `beforeunload` pendant un flush lent → `keepalive` rend `null`, l'onglet part avec le tri. Cliquer « Valider » dans cette fenêtre ne fait **rien** |
| **M5** | L0 | **Un crop créé par « + Crop manuel » peut naître inactionnable.** `_kind_for_source_image` peut renvoyer `'single'` ; le nouveau front le refuse et affiche « déjà tranché » sur un crop créé à la seconde d'avant | Terrain propice : **7 717 `source_images`** à 0 crop, `is_lot_suspected=0`, sans signal `'lot'` |
| **M6** | L5 | **Le seul écrivain de production de `inputs_digest` n'est couvert par aucun test.** Mutation jouée : `self._store.update_iteration(iteration.id, inputs_digest=digest)` → `pass` → `pytest tests -q -p no:randomly` = **2456 passed** | `ml/serving/iteration_runner.py:951`. NULL est défini comme « bakée avant 0016 » : la valeur est plausible, le PUT répond 200, la suite reste verte |
| **M7** | L5 | **Les deux câblages producteurs de `quantization` et `eval_corpus` sont hors test.** Mutations jouées (les deux) → **2456 passed**. `build_run(..., quantization=result.get("quantization","fp32"))` est un défaut plausible qui **masque une absence** | `ml/scripts/bench_encoder_dino.py:753`. Un `result["quantization"]` (KeyError) serait bruyant ; le `.get()` rend le défaut muet |
| **M8** | L5 | **`--apply` n'est pas idempotent**, et le bump `SELECTION_RULE_VERSION` 2→3 invite à le rejouer. `_POOL_SQL` filtre `AND a.eval_corpus IS NULL` (l.164) : les 260 crops v2 sont invisibles du pool → un second `--apply` prélève **5 nouveaux crops par classe** | ~520 assets porteraient `eval_corpus='matrice-encodeurs-2026-08'` quand le gold `9bc08e19b83c` n'en décrit que 260. Et `ml/store/funnel.py:136` retire du training tout crop portant un `eval_corpus` : ~260 crops éligibles perdus **en silence**, avec `{"updated": 205}` et exit 0 |
| **M9** | L5 | **`inputs_digest` est effaçable au canonique par un upsert last-writer-wins**, et il est le premier champ que cet effacement détruit **irréversiblement** | `ml/store/iterations.py:270` (`inputs_digest = excluded.inputs_digest`) + `IterationSnapshot.inputs_digest = None` par défaut. Une note posée depuis le Mac sur une réplique périmée écrase le digest posé par le PC. PUT 200, aucun chemin ne le recalcule |
| **M10** ✅ | L5 | ~~corrigé le 2026-08-27 dans `SUIVI-MATRICE.md`~~ — **le document de pilotage affirmait une chose que la mesure contredit** : « le garde quasi-doublon n'est pas redondant avec le garde vendeur ». Sur la donnée d'aujourd'hui il n'écarte **rien** de plus | `selectionner()` en process neuf : deux gardes → 43 classes / 215 picks ; vendeur seul → 43 / 215 (différence symétrique des `asset_id` = **0**) ; doublon seul → 60 / 300 ; aucun garde → 61 / 305. `SELECT COUNT(*) FROM source_images WHERE source='ebay' AND seller_id IS NULL` → **5** sur ~20 845, et **0** d'entre elles ne porte d'ancre. Le « +0,5 pt » annoncé vaut **0** |

### Mineurs

| # | Lot | Défaut |
|---|---|---|
| m1 | L0 | Une décision **modifiée** pendant un POST en vol est jetée : la boucle de nettoyage compare les clés (`assetId in flushed`), jamais les valeurs. Résultat : une décision humaine remplacée par son ancienne version, sans trace |
| m2 | L0 | **Deux mutations restent VERTES** : le harness mocke `useLotReview` en entier. (a) retirer `opts` de `eurioApi.post` (le POST perd `keepalive`) → `14 passed`. (b) `normalizeDecideErrors` → `return []` → `14 passed`. Les deux maillons présentés comme le filet ne sont verrouillés par rien |
| m3 | L0 | Le chiffre pivot « 751 lots re-servaient 2 303 crops » est annoncé **sans sa requête**. Reconstitution : **797 / 2 507**. Idem « 303/303 rejets en `other` » : la requête donnée rend **304** |
| m4 | L5 | `eval_corpus` est écrite mais **invisible à la lecture** : `GET /lab/encoder-bench/runs` ne filtre que sur `anchors_kind`/`encoder_version`. Deux runs de corpus différents se lisent côte à côte comme une régression de 22 points |
| m5 | L5 | La clé `n_ecartes_vendeur` du plan JSON **change de sens sans changer de nom** (`n_hors_doublons - len(cands)` au lieu de `n_hors_ancres - len(cands)`). Un plan v2 et un plan v3 archivés côte à côte portent la même clé avec deux définitions |

---

## Le reste-à-faire — honnête

### Déclaré NON FAIT par les agents

**Lot 0**

- Aucune passe de réparation de données sur le défaut 4 (raison de rejet au
  mauvais crop) : 303 (304 aujourd'hui) rejets de lot en base sont tous en
  `other`, le menu n'a jamais servi. Conforme au plan.
- **Vérification #3 non jouée** (curl sur le canonique déployé,
  `jq '[.images[].crops[] | select(.review_status=="open" and .review_kind=="lot")] | length'`) :
  le correctif back n'est pas déployé, et déployer est interdit. C'est la seule
  preuve que l'écran réel change de comportement.
- **Vérification #4 non jouée** (à la main dans le front : ouvrir un lot mixte,
  décider, Échap, recharger). Un test de composant n'est pas un écran.
- `onBeforeRouteLeave` volontairement non ajouté (la vue a deux hôtes).
- 3 tests Python rouges dans la suite au moment du lot, **étrangers** à lui
  (travail en vol d'agents parallèles).

**Lot 5**

- **Aucune migration appliquée.** 0015 et 0016 sont écrites et testées en local,
  **jamais jouées sur le canonique**.
- **La matrice n'a pas été rejouée** (2 h de calcul). Les runs en base gardent
  `quantization='fp32'` et `eval_corpus=NULL`.
- **Le hold-out n'a pas été re-prélevé.** `SELECTION_RULE_VERSION` passe à 3, le
  corpus servi a été prélevé en v2.
- **Axe int8 non mesuré.** Aucun chemin de quantisation dans `_load_model`.
- **Dette `provisional` non fermée** (son prédicat croit quatre champs déclarés
  par l'appelant) — et 0015 empile deux colonnes sur cette table.
- Pas de colonne `eval_corpus_version` (choix documenté).
- Risque d'ordre `ALTER ADD COLUMN` sans `IF NOT EXISTS` — crash bruyant au boot
  si un Store inscriptible s'ouvre avant l'API.

**Balayage des seuils**

- Aucune écriture en base. `dino_thresholds` est toujours vide.
- Le gold **n'a pas été rebuildé** (le geste coûte une commande et triple la
  population évaluable : 466 → 1 301).

### À faire, par ordre de dépendance

| # | Geste | Coût | Bloque quoi |
|---|---|---|---|
| ~~**R1**~~ | ✅ **sans objet** — le code était intact, B2 était un artefact de course entre vérificateurs (2026-08-27) | — | — |
| ~~**R6**~~ | ✅ **fait le 2026-08-27** — gold rebâti (466 → 1 309 crops évaluables), balayage rejoué, `--text-gate` ajouté. Q1 est instruite | — | — |
| ~~**R2**~~ | ✅ **fait le 2026-08-27** — `SUIVI-MATRICE.md` porte la mesure honnête (0 pick écarté sous le garde vendeur, tableau des 4 combinaisons) et la raison pour laquelle le garde reste en place | — | — |
| **R3** | **Fermer B1** : soit un repli côté front (`review_status === undefined` ⇒ actionnable), soit un ordre de déploiement **back puis front** écrit et tenu | 0,5 j | tout déploiement du lot 0 |
| **R4** | **Fermer M2** : `isActionable` ne doit pas exiger `kind==='lot'` — le back ne le fait pas | 0,5 j | 207 crops dans 109 listings |
| **R5** | **Fermer M1/M3/M4/m1** : contrat d'erreurs typé côté back **avant** le front, verrou par listing, signal visible sur l'échec de flush | 1 j | la perte de travail humain (le pire défaut du projet) |
| **R6** | **Rebuild du gold** (`scripts/verdict_gold.py build`) puis rejouer le balayage — 466 → 1 301 crops évaluables | 1 h | toute décision de seuil ou de règle de texte |
| **R7** | **Trancher M8** : rendre `--apply` idempotent ou refuser un second apply sur le même nom de corpus | 0,5 j | tout re-prélèvement de hold-out |
| **R8** | **Corriger le défaut de manuel** : `PUT /lab/dino-thresholds` accepte deux clés sans effet — soit brancher le verdict sur `store.dino_thresholds.resolve()`, soit répondre **400** | 0,5–1 j | toute croyance qu'un seuil est réglable |
| **R9** | **Réalimenter `discovery_searches`** sur les runs par `--target-eurio-ids` — le cooldown 30 j est **aveugle** depuis le 2026-06-16 | 0,5 j | la vague 3 du scrape |
| **R10** | Lots P1 / P2 / P3, dans l'ordre décidé par le PO | cf. plans | — |

---

## ⚖️ Les décisions qui attendent le PO

| # | Question | Ce que ça coûte | Ce que ça rapporte | Recommandation |
|---|---|---|---|---|
| ~~**Q1**~~ ✅ | ⚠️ **Chiffres RÉVISÉS le 2026-08-27 sur le gold rebâti (1 309 crops)** — voir §Gold rebâti. Le « +28 % à précision améliorée » de cette ligne datait des 466 crops. Vrais chiffres : **+489 items (+26,9 %)**, précision ponctuelle **99,81 → 99,74** (elle BAISSE), borne de Wilson **98,93 → 99,04** (elle monte). Le préalable R6 est levé. **Change-t-on la règle du texte** de `convergent` à `≠ contradict` (point A) ? C'est un changement de **règle**, pas de seuil : il touche l'étape 5 de `_verdict_from_signals` **et** sa copie lean, puis il faut redéployer `eurio-api` | 2 fichiers du même commit + un déploiement VPS. Borne Wilson basse : au pire ~42 faux sur 2 121, contre ~33 sur 1 656 aujourd'hui | **+465 items auto-acceptés** sur la file ouverte (1 656 → 2 121, +28 %), à précision **améliorée** (99,65 % vs 99,46 % sur le gold) | **Rebuild le gold d'abord (R6)**, puis trancher. Le point A est le seul gain de volume mesuré |
| **Q2** | **Feu vert sur la vague 1 du scrape** (4 groupes, ~520 appels) ? | ~520 appels sur 5 000 · ~900 items de review créés | 3 groupes où **3 classes sur 3** sont `bottleneck=scrape`, à zéro exemplaire, **sans rien en file** | **Oui**, mais avec la vérification du coût réel immédiatement après (cf. `PLAN-SCRAPE.md` §Vague 1) |
| **Q3** | **Plafond d'appels du jour** : 1 500 (recommandé) ou 3 846 (le budget) ? | à 1,84 item/appel : 1 500 → ~2 800 items ; 3 846 → **~7 000 items** sur une file qui en a 10 440 | plus d'appels = plus de classes servies | **1 500**. Le facteur limitant n'est pas le quota, c'est la file |
| **Q4** | **Rejoue-t-on la poche `unresolvable`** (609 annonces jamais rejouées, 1 014 images) ? | ~43 min de Mac, ~610 items de review créés | ~740 crops, **valeur incertaine** (cible à retrouver par DINO) | **Essai borné à 60 annonces**, mesurer le taux de récupération ; sous ~40 %, arrêter |
| **Q5** | **Applique-t-on les migrations 0015 / 0016** au canonique ? | un `docker compose up -d --build` + redémarrage. ~~⚠️ Corriger B2 d'abord~~ — B2 est sans objet (2026-08-27), le câblage est en place | la matrice devient comparable dans le temps (`quantization`, `eval_corpus`, `inputs_digest`) | **Oui.** Procédure et vérification SQL : `SUIVI-MATRICE.md` §Ce qu'il faut lancer |
| **Q6** | **Casse-t-on 20 crops pour en gagner 96** (routage pays, lot P1) ? | 20 crops gold justes deviennent faux ; les classes servies dans les 5 familles passent de 59 à **52** (le routage concentre) | 71,0 % → **91,7 %** d'exactitude ; **1 193** crops récupérés, **464** vers des classes pauvres, **11** orphelines nourries | **Oui.** Net **+82 sur 397**. Mais l'écran doit **dire** la concentration, comme il dit déjà le désarmement du filtre pays |
| **Q7** | **Combien de temps humain pour la planche orphelines** (lot P1/L4) ? | geste **jamais chronométré** ; à 18,8 % par paire, une planche de 30 rend ~6 crops justes ; une file majoritairement fausse fatigue | **190 des 215** orphelines atteignables sans un euro de quota | **Mesurer sur 5 classes AVANT de construire les 190** |
| **Q8** | **Les 25 classes hors de portée de toute règle** : scrape ciblé ou abandon ? | quota eBay = argent réel ; rendement par classe **non chiffré** | 25 classes de plus dans la banque | non tranché — dépense à arbitrer |
| **Q9** | **D15–D21 de l'écran binaire** (nom de l'écran, destin de « c'est le revers », de « mauvais cadrage », quarantaine des négations d'un ami, rang de pêche, ordre de bascule) | cf. [`PLAN-ECRAN-BINAIRE.md`](./PLAN-ECRAN-BINAIRE.md) §Les décisions qui reviennent au PO | idem | **D20 (le nom) doit être tranché AVANT L0** : la maquette le grave |
| **Q10** | **Ordre général des chantiers** | — | — | **La perte de travail humain passe avant tout** (R3–R5). Une décision de review perdue ne se régénère pas ; un crop non scrapé, si |

---

---

## 🔬 L'audit du 2026-08-27 — où la métadonnée eBay entre dans la suggestion

> Ouvert sur une intuition du PO : *« les suggestions pure DINO sont bien souvent
> bonnes, mais celles avec année, pays et dénomination donnent de mauvais résultats ;
> on ne peut pas faire confiance à la donnée eBay et on la traite mal. »*
> **Départage : la donnée eBay est bonne, le traitement était mauvais** — et le
> mécanisme qui nuit vraiment n'utilise même pas de donnée eBay.

### A · La bande pays ne vient pas d'eBay, elle vient de nous

`sources/_base/steps/auto_validate.py:754-757` — le pays qui restreint la bande est
`source_images.target_eurio_id[:2]`, **la cible du scrape**, pas `listing_country`
(`grep listing_country` : aucune occurrence dans la chaîne de prédiction). Les trois
autres points d'entrée dupliquent ces mêmes lignes (`serving/crop_edit.py:458` et
`:702`, `review/review_queue_routes.py:2769`).

C'est un **prior auto-réalisateur** : la bande ne peut jamais proposer autre chose que
le pays cherché. Et `_resolve_signals` la préfère au top-1 global partout — verdict,
lane, suggestion affichée.

Exactitude sur les crops tranchés par un humain (`decided_by='admin'`, bande présente) :

| | n | global@1 | bande@1 |
|---|---:|---:|---:|
| tous | 2 310 | 88,0 % | **90,9 %** |
| décision = pays de la cible | 2 278 | 88,0 % | **92,2 %** |
| **décision ≠ pays de la cible** | **32** | **90,6 %** | **0,0 %** |

Par verdict texte (même population, bande présente) :

| verdict | n | bande@1 | global@1 | divergences | bande gagne | global gagne |
|---|---:|---:|---:|---:|---:|---:|
| `convergent` | 1 445 | **96,3 %** | 92,0 % | 76 | **65** | 3 |
| `partial` | 408 | 88,5 % | **90,2 %** | 43 | 15 | **22** |
| `contradict` | 305 | 64,6 % | 63,9 % | 18 | 6 | 4 |
| `(NULL)` | 151 | **99,3 %** | 92,7 % | 11 | **10** | 0 |

Quatre politiques de bande, mêmes 2 607 crops : bande toujours (actuelle) **91,25 %** ·
global seul 88,68 % · bande si `convergent`/`NULL` **91,45 %** · bande si le titre
confirme le pays 91,37 %. **+0,2 point** — rien.

### ⛔ Pourquoi cette mesure ne peut PAS trancher, et ce qui la trancherait

Deux contaminations structurelles :

1. l'humain tranche **en voyant la suggestion de la bande en premier**
   (`serving/review_queue/repository.py:518`) ;
2. les crops hors-cible finissent `skipped` ou sans `decided_eurio_id`. La divergence
   bande/global vaut **6,4 % sur la file tranchée** contre **46,9 % sur la file
   ouverte** (3 346 crops).

La bande cache exactement les cas qui la mettraient en défaut, donc ils ne sont jamais
étiquetés. **Le banc à l'aveugle** répond à ça : 60 crops tirés des divergents de la
file ouverte, les deux canoniques côte à côte dans un ordre tiré d'un hash de
l'`asset_id` (27/60 avec le global à gauche), aucun `eurio_id` affiché, titre eBay
derrière un dépliant dont l'ouverture est **enregistrée**. Réponses : A · B · aucune ·
indécidable. En attente du PO.

> **La phrase à retenir : la bande est bonne pour la justesse de la review et mauvaise
> pour la couverture de l'enrichissement.** Elle gagne 2,9 points sur « ai-je bien
> classé ce crop », et elle coûte l'accès à toute pièce trouvée dans une annonce d'un
> autre pays — c'est-à-dire le gisement des 272 classes pauvres sans candidat. Le code
> optimise le premier objectif ; le chantier vise le second.

### B · Le verdict texte n'influence pas les suggestions — vérifié

`vs_target_verdict` n'est lu qu'en trois endroits (`serving/review_queue/service.py:95`,
`training/foundation/auto_validate.py:137`, `review/validation/experts.py:117`) et
**jamais** dans la construction de `top_k_json` / `top_k_country_json`.

### C · Le veto année est justifié — la première lecture était fausse

Toutes les **665** contradictions de la file ouverte portent sur le seul axe **année**
(zéro pays, zéro dénomination). J'en ai d'abord conclu que le veto se pénalisait
lui-même. **La mesure dit le contraire** : sur les crops en `contradict`, l'exactitude
de DINO tombe de **96,3 % à 64,6 %**. La contradiction d'année est un vrai signal de
difficulté. On la garde armée.

En revanche `partial` fait **90,2 %** en global contre 92,0 % pour `convergent` — 1,8
point. C'est une **seconde ligne de preuve**, indépendante du balayage sur le gold
(37/37), en faveur du passage à `≠ contradict` (Q1).

### D · Les quatre défauts d'extraction — corrigés, non déployés

Trouvés sur 10 crops regardés à l'œil, l'extraction était fautive **4 fois sur 10**
alors que **8 titres sur 10 étaient justes et aucun ne mentait**. Deux titres étaient
même plus justes que notre cible de scrape (ils annonçaient 2025 et 2026 pendant que le
pipeline cherchait 2011 et 2014).

| # | Défaut | Volume mesuré sur la file ouverte | Correctif |
|---|---|---:|---|
| 1 | `\b` en borne droite de `YEAR_RE` refusait « **2016R** » (millésime collé à la lettre d'atelier) | 15 crops gagnent une année | borne droite `(?![\d])`, borne **gauche gardée** `\b` pour refuser « KM2016 » |
| 2 | Aucun nom de pays **espagnol** (« alemania », « luxemburgo », « chipre »…) alors qu'EBAY_ES est un marché de découverte | **1 640 crops** gagnent un pays (14 % de la file) | 16 pays ajoutés à `COUNTRY_NAMES` |
| 3 | « Sammlerbox … 3D-Druck » ne portait aucun marqueur de rejet | 3 crops | catégorie `accessory`, **volontairement étroite** |
| 4 | Une **plage** de millésimes (« 2004 bis 2022 ») produisait un `contradict` sur un titre honnête | cf. transitions ci-dessous | `years_are_range` → l'axe année devient `absent` |

⚠️ **Ce que le n°3 ne fait PAS.** `rejected_markers_json` n'est lu que pour
l'**affichage** (`serving/bench_routes.py:454`, `review_queue/models.py:325`) : le
marqueur rend l'accessoire visible à l'humain, il ne le retire pas de la file. Et le
gisement est de **3 crops**, pas un gisement : l'hypothèse « on jette du temps de review
dans des boîtes en plastique » est **démentie** — les 1 213 crops portant
blister/coincard/capsule contiennent presque toujours une vraie pièce, et c'est
pourquoi le marqueur les exclut explicitement.

⚠️ **Ce que le n°4 ne fait PAS non plus.** `is_lot` n'est **pas** touché : le
multi-années y a été testé puis retiré parce qu'il sur-capturait les offres « au choix »
(`sources/text_signals/extractor.py::_extract_lot`). On ne rouvre pas cette décision.

**Simulation du recalcul, 100 % en lecture** (`scratchpad/simulate_backfill.py`, ré-extrait
en mémoire depuis `listing_title`, n'écrit rien) — 11 378 crops ouverts, dont **7 118
avec une cible connue** :

| verdict | avant | après | Δ |
|---|---:|---:|---:|
| `convergent` | 4 999 | **5 435** | **+436** |
| `partial` | 1 265 | 1 071 | −194 |
| `contradict` | 642 | 612 | −30 |
| non calculé | 212 | 0 | −212 |

**1 487 verdicts changent sur 7 118 (21 %).** Les deux mouvements dominants :
`partial → convergent` **755** (les pays espagnols complètent le 3/3) et
`convergent → partial` **445** (une plage de millésimes ne confirme plus l'année — c'est
correct, et ça retire du convergent).

> **Le résultat qui compte : corriger l'extracteur rapporte +436 crops `convergent`,
> soit autant que changer la règle du texte (+465) — mais en étant plus JUSTE, pas plus
> permissif.** Les deux gains se cumulent et ne sont pas redondants.
>
> ⚠️ `convergent` n'est pas `auto_candidate` : il reste les portes sim / spread /
> `top1 == cible`. Ne pas annoncer +436 auto-acceptations.

### E · Le bump de version, sans lequel tout ça est inerte

`EXTRACTOR_VERSION` passe de **`v2` à `v3`** (`sources/_base/steps/text_signal.py:47`).
Le code portait déjà la convention : *« Le bump force la ré-extraction des rows v1
(l'idempotence est clé sur version). »* Sans lui, les **22 423 rows `v2`** en base
restent périmées **et** `backfill_text_signals.py` sans `--force` les saute toutes en
annonçant « Selected 0 » et un exit 0 — panne parfaitement muette. Un test le verrouille.

✅ Vérifié : les **24 rows `extractor_version='manual'`** (corrections humaines) sont
épargnées **même en `--force`** — le garde est dans `steps/text_signal.py:95-104`, pas
dans le script. Ma crainte d'un écrasement était infondée.

**État : 17 tests neufs, 9 mutations jouées et rouges, chacune sur le bon test. Suite
complète `2472 passed`. Rien n'est commité, rien n'est déployé, aucun backfill lancé.**

---

## 🎯 Le banc à l'aveugle, joué — 2026-08-27

**60 crops, tous tirés des divergents de la file ouverte. Le PO a répondu sans savoir
quelle canonique venait de quelle voie** (ordre tiré d'un hash de l'`asset_id`, 27/60
avec le global à gauche, aucun `eurio_id` affiché, titre eBay ouvert **1 seule fois**).

| Réponse | n | part |
|---|---:|---:|
| **la bande pays avait raison** | **19** | 31,7 % |
| le top-1 global avait raison | **3** | 5,0 % |
| **aucune des deux** | **38** | **63,3 %** |
| indécidable à l'œil | 0 | 0 % |

### D10 · La bande pays ne bouge pas. Question fermée.

Sur les 22 crops tranchés : **19 contre 3**, test binomial bilatéral **p = 0,00086**.

⚠️ **C'est l'inverse de l'hypothèse qui a motivé ce banc**, et elle était de moi : j'avais
écrit que la bande, structurellement incapable de proposer un autre pays que la cible du
scrape, serait mise en défaut sur la population divergente. Elle y gagne au contraire
**plus nettement** que sur la population déjà tranchée (+2,9 pts là-bas, 19-3 ici).

**Conséquence : on ne touche pas à `_resolve_signals`.** Les politiques P1/P2/P3 mesurées
plus haut (global seul, bande conditionnelle…) sont écartées — non pas faute de preuve,
mais parce que la preuve manquante est arrivée et qu'elle va dans l'autre sens.

**Ce qui reste vrai malgré ça, et qu'il ne faut pas jeter avec l'hypothèse** : la bande
demeure incapable de proposer une classe hors du pays cherché. Ce n'est plus un défaut de
JUSTESSE — c'en est un de COUVERTURE, et il se traite par le plan
[`PLAN-PECHE-PAYS.md`](./PLAN-PECHE-PAYS.md), pas en dégradant la suggestion.

### 🔴 Le vrai résultat : 63 % du temps, les DEUX voies se trompent

C'est le chiffre qui compte, et personne ne l'attendait. Sur la population divergente,
`top1_country ≠ top1_global` n'est **pas** un signal « l'une des deux a raison » —
c'est un signal **« DINO est perdu »**. Il y a **3 346 crops** dans ce cas en file
ouverte (46,9 % des crops ouverts prédits).

⚠️ **Limite de méthode, assumée : ce banc ne dit pas si la bonne réponse était offerte.**
Il départage les deux candidats montrés ; un « aucune des deux » peut vouloir dire « DINO
est perdu » **ou** « la vraie classe n'était dans aucune des deux voies ». Les deux
lectures sont compatibles avec 38, et le protocole choisi ne les sépare pas. Le savoir
coûterait un étiquetage libre de ces 38 crops.

### Les revers — l'observation du PO est réelle, et elle a ouvert un défaut

> *« Y'a eu pas mal de revers de pièces dans le lot de ce banc. »*

Elle explique une **minorité** des 38, pas la majorité — et il faut le dire ainsi. Marge
de face (`face_margin`, stockée, τ = 0,065) sur les 60 :

| réponse | n | marge moyenne | marge max | marge > 0 | marge > 0,03 |
|---|---:|---:|---:|---:|---:|
| aucune des deux | 38 | −0,1009 | **+0,1194** | **10** | **5** |
| bande | 19 | −0,1851 | −0,0695 | 0 | 0 |
| global | 3 | −0,2928 | −0,0970 | 0 | 0 |

Les 22 crops tranchés sont **tous** franchement des avers. Parmi les 38, **10 ont une
marge positive** et l'un dépasse τ — donc il est un revers **selon le détecteur
lui-même**, tout en étant étiqueté `obverse`.

#### Le défaut, mesuré en trois points

1. **L'étiquette de face est écrite UNE FOIS et ne se corrige jamais.**
   `sources/_base/steps/auto_validate.py:874` :
   `UPDATE image_assets SET face=? WHERE id=? AND face IS NULL`. Une marge recalculée qui
   dit l'inverse ne peut plus rien changer.
2. **La comparaison est structurellement asymétrique.** `auto_validate.py:828` appelle
   `_decide_face(rev_sim, all_pred.top1_sim)` : la « reverse-ness » est le max cosinus sur
   **34 ancres** (`foundation_anchors_reverse_2eur.npz`, bâti le **2026-06-13**), l'
   « obverse-ness » le max sur **2 062**. Plus la banque des avers grossit, plus
   `top1_sim` monte, plus la marge s'effondre — et **τ n'a pas bougé depuis juin** pendant
   que la banque passait de ~1 250 à 2 062 ancres (**+65 %**).
   *(Vérifié et écarté : l'encodeur des deux banques est bien le même, `dinov2-vitl14`,
   dim 1024. Ce n'était pas une désynchronisation d'encodeur.)*
3. **Le désaccord est déjà en base.** Étiquette stockée contre ce que la marge dit
   aujourd'hui, sur les assets ayant une marge :

   | stocké | la marge dit | n |
   |---|---|---:|
   | `obverse` | reverse | **237** |
   | `reverse` | obverse | **343** |
   | `(NULL)` | reverse | **289** |

   Et dans la **file ouverte**, **290 crops** ont une marge ≥ τ : **198 sans aucune
   étiquette de face**, 92 étiquetés `obverse`. Aucun d'eux ne peut être attribué à une
   classe nationale — un revers commun ne ressemble à aucun avers. Ils occupent du temps
   humain pour rien. 308 de plus sont dans la zone grise 0,040–0,065.

⚠️ **Ce que le détecteur fait BIEN, à ne pas casser** : 1 875 revers ont été attrapés sur
le parc, dont 1 700 tranchés avec **0 attribution** — ils sortent bien de la file. Le
défaut est un problème de **faux négatifs et de dérive**, pas d'inefficacité.

### Ce que le banc change à l'ordre des travaux

| | avant le banc | après |
|---|---|---|
| bande pays | à trancher (Q-bande) | ✅ **tranchée : on n'y touche pas** (D10) |
| divergence bande/global | soupçon de nuisance | **signal d'abstention** : 3 346 crops où DINO est probablement perdu |
| face / revers | non identifié | **défaut neuf** : écriture unique, comparaison 34 vs 2 062, τ figé depuis juin |

---

## 🔧 Le défaut de face — corrigé, non déployé (2026-08-27)

Ouvert par l'observation du PO sur le banc. Trois causes **cumulées**, et il
fallait les trois pour produire l'effet : une étiquette fausse ET définitive.

### Ce qui n'était PAS le problème — écarté par la mesure, pas par l'intuition

| Soupçon | Verdict |
|---|---|
| La banque d'ancres est empoisonnée par des revers étiquetés avers | ❌ **Faux.** 0 ancre servie au-dessus de τ ; 6 assets validés seulement dans la bande concernée |
| Les deux banques sont désynchronisées d'encodeur | ❌ **Faux.** Les deux sont en `dinov2-vitl14`, dim 1024 |
| Le détecteur ne marche pas | ❌ **Faux.** 1 875 revers attrapés, 1 700 tranchés, **0 attribué** — il sort bien les revers de la file |
| Le garde d'écriture unique est l'erreur | ❌ **Faux.** Il protège les verdicts humains, et il doit continuer |

### Cause 1 · Le seuil dérive avec la taille de la banque des AVERS

`_decide_face(rev_sim, all_pred.top1_sim)` (`auto_validate.py`) compare un max
sur **34 ancres de revers** à un max sur **2 062 ancres d'avers**. Un max sur
plus de vecteurs est plus haut par construction : **chaque rebuild de la banque
des avers rabote la marge**, à τ constant.

Re-mesuré avec l'instrument du dépôt, MÊME gold, MÊME τ
(`python -m scripts.bench_face_recall`) :

| segment | 2026-06-13 | **2026-08-27** | écart |
|---|---:|---:|---:|
| avers confirmés (contrôle FP) | 0 % | **0 %** | — |
| revers faciles | 100 % | **80,0 %** | **−20 pts** |
| revers durs | 73,3 % | **40,0 %** | **−33,3 pts** |

Pendant ce temps la banque passait d'environ 1 250 à 2 062 ancres (**+65 %**).
Personne ne l'a vu : **aucun rebuild ne le disait.**

### Cause 2 · τ était trop haut, et ne rachetait rien

Balayage fin (`--taus=-0.055:0.02:0.005`, ajouté au banc, rejouable) :

| τ | FP (514 avers) | revers durs | revers faciles |
|---:|---:|---:|---:|
| −0,050 | 0,0 % | 93,3 % | 100 % |
| **0,000** ✅ | **0,0 %** | **53,3 %** | **100 %** |
| +0,065 (ancien) | 0,0 % | 40,0 % | 80,0 % |

**La marge MAXIMALE des 514 avers confirmés est −0,0507** : aucun n'atteint
zéro. Les 0,065 ne rachetaient donc **aucun** faux positif — ils coûtaient
13 points de rappel dur et 20 de rappel facile pour rien.

**Retenu : τ = 0,000.** Pas −0,050 (qui rendrait 93,3 %) : ce serait coller au
maximum observé du contrôle, statistique instable sur 514 points, et un faux
« reverse » jette un avers identifiable — l'asymétrie de coût qui fondait la
prudence de juin reste vraie. Zéro garde 0,05 de marge **et** n'est pas une
constante calibrée : c'est la frontière naturelle « ce crop ressemble plus au
revers commun qu'à n'importe quel avers national ». Un seuil qui a un sens
survit mieux à la dérive qu'un nombre.

### Cause 3 · L'étiquette était écrite une seule fois, sans savoir par qui

`WHERE id=? AND face IS NULL`. L'intention était juste — ne jamais écraser un
verdict humain — mais **la colonne ne distinguait pas l'humain de la machine**,
donc protéger l'un gelait l'autre. Combiné à la dérive : une étiquette machine
décidée sous un τ périmé le restait à jamais.

**Migration 0017 — `image_assets.face_source`** (`'pipeline'` recalculable /
`'human'` intouchable). Le précédent du dépôt est
`listing_text_signals.extractor_version='manual'` : la provenance vit dans une
colonne, pas dans une convention.

Le backfill est **exact**, pas heuristique : `review_queue.decided_face` est la
trace durable du geste humain. Vérifié — 3 284 assets en portent un, tous ont
une face, et les deux sont cohérents. `decided_face='unknown'` (162) n'immunise
pas : ce n'est pas un jugement sur la face.

⚠️ **Le piège fermé au passage** : `_ensure_column` seul poserait la colonne à
NULL sur une base antérieure — donc **tous les verdicts humains deviendraient
écrasables**. L'ALTER sans son backfill *installerait* le défaut au lieu de le
corriger. Le bootstrap rejoue donc le backfill, et **uniquement à la création de
la colonne** (`_ensure_column` retourne désormais un booléen). Un test le
verrouille, mutation jouée.

### L'alarme est posée à la CAUSE

`build_anchors_2eur_all` crie désormais à chaque rebuild : *« la banque des
avers vient de bouger, le seuil de face est calibré contre sa taille, rejoue
`bench_face_recall` »*. Sans ça la prochaine dérive sera aussi muette.

### Ce que la passe corrective produirait — simulé sur une COPIE, rien écrit

`scripts/recompute_faces.py` (dry-run par défaut) relit la marge **déjà en
base** — aucun ré-encodage, quelques secondes au lieu de 40 min de MPS.

| transition | n |
|---|---:|
| `obverse` → `reverse` | **1 380** |
| `(NULL)` → `reverse` | 560 |
| `(NULL)` → `obverse` | 2 252 |
| `unknown` → `obverse` | 55 |
| `reverse` → `obverse` | 51 |
| **total** | **4 298** |

> ### 🎯 **1 051 crops sortent de la file de review ouverte.**
> Des revers communs qu'aucune canonique nationale ne peut matcher, et sur
> lesquels un humain perdait son temps à coup sûr. Et 51 crops écartés à tort
> du training reviennent.

⚠️ **Limite** : la passe corrige le VERDICT, pas la marge. Une marge calculée
contre une banque périmée reste périmée — c'est le backfill de prédictions qui
la rafraîchit.

⛔ **Rien n'est appliqué.** La migration n'est pas jouée au canonique, la passe
n'a tourné qu'en dry-run sur une copie. `--apply` échouerait sur Mac (réplique
read-only, Direction A) et l'autopull l'écraserait en deux minutes.

**État : 9 tests neufs + 2 réécrits, 8 mutations jouées et rouges chacune sur le
bon test, suite `2483 passed`.**

---

## 🚀 Déployé au canonique — 2026-08-27

**Commit `edd708c4`, poussé sur `github/repo-cleanup`, `eurio-api` rebâti et
redémarré.** Le front n'est **pas** déployé : il porte le lot 0 avec 5 défauts
majeurs non corrigés (B1, M1–M5). Ordre respecté : back seul.

### Les trois migrations sont passées ensemble

Le canonique était à `0014` ; elles s'appliquent au démarrage, donc **0015, 0016
et 0017 sont parties d'un bloc** — `schema.sql` porte d'ailleurs les trois DDL
dans le même fichier. C'est le **Q5** du suivi, tranché de fait par ce
déploiement.

```
db_migrate: applied 3 migration(s):
  ['0015_encoder_bench_quantization_eval_corpus.sql',
   '0016_iteration_inputs_digest.sql',
   '0017_image_assets_face_source.sql']
```

Backfill de provenance, vérifié **sur le canonique** :

| `face_source` | `face` | n |
|---|---|---:|
| `human` | obverse | **3 122** — protégés |
| `pipeline` | obverse | 13 489 |
| `pipeline` | reverse | 3 764 |

Trois invariants relus dans un process neuf, tous à **0** : verdicts humains
altérés · face posée sans provenance · désaccord restant entre la marge et
l'étiquette.

### La passe corrective — appliquée

`recompute_faces.py --apply`, joué **dans le conteneur** contre
`/var/lib/eurio/eurio.db`. C'est `shared/face_rule.py` (stdlib pur) qui l'a rendu
possible : `ml/scripts/` n'est pas copié dans l'image lean et
`steps/auto_validate` y est inimportable (`cv2`, `torch`).

**4 298 faces réécrites** — exactement le dry-run, au crop près :

| transition | n |
|---|---:|
| `obverse` → `reverse` | 1 380 |
| `(NULL)` → `obverse` | 2 252 |
| `(NULL)` → `reverse` | 560 |
| `unknown` → `obverse` | 55 |
| `reverse` → `obverse` | 51 |

**Réversible** : photo des 4 298 lignes AVANT la passe (id, face, face_source,
marge) dans `/var/lib/eurio/face_avant_2026-08-27.csv` (265 Ko) — sans elle les
transitions `NULL → X` étaient irréversibles.

### ⛔ Ce que la passe NE fait PAS — et ma phrase d'avant était prématurée

J'ai annoncé « 1 051 crops sortent de la file ». **Ils n'en sortent pas.** La
passe corrige l'ÉTIQUETTE ; le routage « revers → rejeté » se fait à l'enqueue,
jamais rétroactivement (`auto_validate.py`, en toutes lettres). Et `list_queue`
n'a **aucun** prédicat sur `face` : les revers restent servis à l'humain.

Mesuré après la passe : crops ouverts étiquetés `reverse` **1 → 1 052**, file
ouverte totale **11 377, inchangée**.

| | n |
|---|---:|
| ouverts étiquetés `reverse` | 1 052 |
| encore `needs_review` | 1 052 |
| restaurés à la main (sticky, à épargner) | 8 |
| **rejetables** | **1 044** |

### Le geste qui reste, et pourquoi il n'a pas été fait

Le mécanisme EXISTE — `_reject_crop_terminal` + recalcul de `route_reason`,
utilisés par `scripts/backfill_face.py`. Deux obstacles :

1. `backfill_face.py` ne traite que les crops à `face IS NULL` **et** ré-encode
   avec DINO. Après la passe il n'y a plus de `face IS NULL` : il ne trouverait
   rien à faire ;
2. les helpers de rejet vivent dans `sources/_base/steps/enqueue`, qui importe
   `review.review_lanes`, qui importe `training.foundation.auto_validate` —
   **inimportable dans l'image lean** (`No module named 'training'`).

⛔ **Réécrire le rejet en SQL serait une seconde copie de la règle**, libre de
diverger : exactement ce que `shared/face_rule.py` vient d'éliminer. On ne le
fait pas.

**Le correctif propre est le même geste que pour la face** : sortir la moitié
stdlib de `review_lanes` (`DEFAULT_LANE`, `VERDICT_TO_LANE`, `verdict_to_lane`)
dans un module léger, laisser `compute_lane` (qui a besoin de `training`) où il
est. `enqueue` devient alors importable dans le lean, et la passe de rejet peut
tourner au canonique sans dupliquer une ligne. **Décision du PO** — c'est un
refactor plus un second déploiement.

⚠️ **Note de doc** : la skill `eurio-vps-deploy` annonce `review_queue (cv2)`
comme skip attendu. Mesuré aujourd'hui : c'est `review_queue
(ModuleNotFoundError: No module named 'training')`, et `referential` n'est plus
skippé du tout. Pré-existant, vérifié identique avant/après ce commit — la skill
est périmée sur la raison, pas sur le nombre.

---

## ✅ Les 1 044 sont encaissés — 2026-08-27

Le geste que la section précédente laissait ouvert est fait. Commit `60dbe004`,
`eurio-api` redéployé, passe appliquée au canonique.

### Le refactor qui l'a rendu possible

Les trois helpers de rejet (`_reject_crop_terminal`,
`_route_decision_for_source_image`, `_kind_for_source_image`) sont du **SQL
pur** — mais ils habitaient `sources/_base/steps/enqueue`, qui importe
`review_lanes` et `review.validation.*`, lesquels tirent `training.foundation`.
Dans l'image lean, `import enqueue` lève `No module named 'training'`.

⚠️ **Découper `review_lanes` n'aurait pas suffi** : mesuré, les trois modules
`review.validation.{consensus,experts,persist}` tirent `training` eux aussi. La
bonne cible n'était pas le module intermédiaire, c'étaient **les helpers
eux-mêmes**.

Ils descendent donc dans **`store/review_routing.py`** — même famille que
`store/faces.py`, « write-half SQL-pure ». `enqueue` les ré-importe sous ses
anciens noms privés : **une seule définition**, tous les appelants historiques
tiennent (`backfill_face`, `backfill_denom`, `crop_edit`, `auto_validate`). Deux
tests verrouillent la propriété : le module ne doit rien importer d'indisponible
dans le lean, et le corps ne doit pas revenir dans `enqueue`.

`serving/crop_edit.py` gagne au passage un import local lean-safe.

### La passe de rejet

`scripts/reject_reverse_backlog.py`, dry-run par défaut. Elle **épargne les deux
sticky**, et c'est le cœur de sa prudence :

| épargné | pourquoi |
|---|---|
| `resolution_status != 'needs_review'` | déjà tranché par un humain ou le consensus |
| `decision_notes = 'restored'` | **ré-ouvert à la main** — un geste humain délibéré |

Le rejet reste **ré-ouvrable** par `/restore`, comme celui de l'enqueue.

### Le résultat, relu dans un process neuf

| | avant | **après** |
|---|---:|---:|
| **file ouverte** | 11 377 | **10 333** |
| ouverts étiquetés `reverse` | 1 052 | **8** — exactement les sticky |
| rejets estampillés `face_backlog@tau0.0-2026-08-27` | 0 | **1 044** |
| listings `route_reason='face_reverse'` | 985 | **1 838** |
| assets `face_reverse` avec `training_eligible=1` | — | **0** |
| événements `face_reverse` tracés | — | 2 636 |

> ### 🎯 **−1 044 crops dans la file, soit −9,2 %.**
> Des revers communs qu'aucune canonique nationale ne peut matcher. Le temps
> humain annoncé est cette fois **réellement** encaissé — et le chiffre est
> mesuré sur la file, pas déduit d'une étiquette.

**Réversible** : photo des 1 044 lignes AVANT rejet dans
`/var/lib/eurio/rejet_revers_avant_2026-08-27.csv`, à côté de
`face_avant_2026-08-27.csv`.

**État : 7 tests neufs, 7 mutations jouées et rouges chacune sur son test, suite
`2491 passed`.**

---

## 🔁 Gold rebâti, balayage rejoué — 2026-08-27 (R6 fait)

C'était le préalable qu'on s'était donné avant de trancher **Q1**. Il est levé.

```bash
cd ml && PYTHONPATH=. ./.venv/bin/python scripts/verdict_gold.py build \
  --db state/eurio.replica.db
```

| | avant | **après** |
|---|---:|---:|
| entrées du gold | 1 009 | **3 383** |
| labellisées | 811 | **2 607** |
| **population évaluable** (hors ancres) | 466 | **1 309** |

Les 1 391 ancres de la banque restent exclues : elles se reconnaissent
elles-mêmes et gonfleraient la précision.

### ✅ Ce que le gold élargi CONFIRME — les seuils sont bien inertes

```bash
PYTHONPATH=. ./.venv/bin/python -m scripts.sweep_verdict_thresholds \
  --db state/eurio.replica.db --sim-grid 0.0:0.70:0.05 --spread-grid 0.0:0.12:0.01
```

| sim / spread | n_auto | faux | précision |
|---|---:|---:|---:|
| 0,55 / 0,050 — **en vigueur** | **526** | 1 | **99,81 %** |
| 0,55 / 0,000 — désarmés | 555 | 2 | 99,64 % |
| 0,55 / 0,110 | 420 | **0** | 100 % |

Désarmer les deux seuils rapporte **+29 (+5,5 %)**. La conclusion du petit gold
(+3,2 %) tient sur **2,8× la population** : **D4 est confirmée, on n'y touche
pas.**

### 🔴 Ce que le gold élargi CORRIGE — la précision du point A

**Nouvelle option `--text-gate any`** sur le balayage. Elle ne recopie pas la
règle : au point 5, `texte ≠ contradict` équivaut à **aucune condition de
texte**, la règle 2 ayant déjà renvoyé les contradictions en `divergent`. La
mesure DÉRIVE donc de la sortie de la vraie fonction — un `partial` dont les
deux critères Dino passent ne peut avoir qu'une cause : la porte texte.

| porte texte | n_auto | justes | faux | précision | **Wilson 95 %** |
|---|---:|---:|---:|---:|---|
| `convergent` — en vigueur | 526 | 525 | 1 | **99,81 %** | [98,93 ; 99,97] |
| **`≠ contradict` — point A** | **755** | 753 | 2 | **99,74 %** | **[99,04 ; 99,93]** |

⚠️ **Le suivi affirmait que le point A AMÉLIORAIT la précision (99,46 → 99,65).
C'était un artefact des 466 crops.** Sur 1 309, la précision ponctuelle
**baisse** de 0,07 point.

**Mais la borne basse de Wilson MONTE** — 98,93 → **99,04**. Au pire cas, le
point A est *au moins aussi bon*, parce que la mesure porte sur 43 % de crops
en plus. C'est le chiffre à retenir : le point estimé bouge dans le bruit, la
borne, elle, s'améliore.

### Le volume, sur la file réelle d'aujourd'hui

Mesuré sur les **10 333** crops ouverts (après le rejet des 1 044 revers) :

| | auto_candidate |
|---|---:|
| règle en vigueur | 1 819 |
| **point A** | **2 308** |
| | **+489, +26,9 %** |

### ⚠️ Ce que cette mesure ne dit PAS

Les signaux texte en base sont encore en **`v2`** : l'extracteur `v3` est
déployé mais **aucun backfill n'a tourné**. Les deux armes sont comparées sur
les mêmes signaux, donc le départage est honnête — mais les valeurs absolues
bougeront après le backfill. La simulation en lecture donnait
`convergent` **4 999 → 5 435 (+436)** sur les crops à cible connue : les deux
gains se cumulent et ne sont pas redondants.

### 👉 Q1 est instruite, elle attend ta décision

| | pour | contre |
|---|---|---|
| volume | **+489 items** auto-acceptables (+26,9 %) | |
| précision | borne de Wilson **améliorée** (99,04 vs 98,93) | point estimé −0,07 pt |
| coût | 2 fichiers du même commit + un déploiement VPS | touche l'étape 5 **et** sa copie lean |
| réversible | oui, un commit | |

---

## 🎬 Q1 en code + backfill v3 — 2026-08-27, et une prédiction démentie

Joués **séparément, avec une mesure entre les deux** — sinon l'écart n'aurait
été attribuable ni à l'un ni à l'autre.

### Étape 1 · Q1 déployée

`text_verdict == "convergent"` retiré de l'étape 5, dans **les deux copies** (le
legacy et le port lean). Le veto de l'étape 2 ne bouge pas.

Corollaire qui simplifie : au point 5, `texte ≠ contradict` équivaut à **aucune
condition de texte**, la règle 2 ayant déjà sorti les contradictions.

| file ouverte (10 333) | avant Q1 | **après Q1** |
|---|---:|---:|
| **`auto_candidate`** | 1 819 | **2 308** |
| | | **+489, +26,9 %** |

**Exactement la prédiction**, au crop près.

Deux trous de test comblés au passage : un test du lean affirmait l'ancien
contrat, et **aucun test lean ne posait de `listing_text_signals`** — retirer le
VETO du port n'aurait donc fait rougir personne.

### Étape 2 · Backfill v3

`backfill_text_signals.py`, joué dans le conteneur : **22 838 extraits, 24
sautés** (les `manual`, garde tenu), **0 erreur**, 27,6 s. Photo avant dans
`/var/lib/eurio/text_signals_avant_v3_2026-08-27.csv`.

Ce que les correctifs d'extraction rapportent, mesuré par différence :

| | |
|---|---:|
| annonces gagnant un **pays** | **3 001** |
| annonces gagnant une **année** | 38 |
| verdicts texte changés | **3 485** sur 22 505 |
| crops ouverts en `contradict` | 665 → **537** |

Transitions principales : `partial → convergent` **1 770**, `∅ → convergent`
496, `convergent → partial` 433.

### 🔴 Ma prédiction était fausse : les deux gains ne se cumulent PAS

J'avais écrit *« les deux gains se cumulent et ne sont pas redondants »* et
recommandé le backfill « dans la foulée, les deux s'additionnent ».

**Mesuré : `auto_candidate` reste à 2 308. Le backfill n'en ajoute aucun.**

Et c'est logique, une fois dit : **Q1 a retiré la condition de texte de
l'étape 5**, donc la distinction `convergent` / `partial` / `absent` — celle que
les 3 001 pays gagnés viennent améliorer — **n'entre plus dans la décision
d'auto-acceptation**. Q1 a subsumé la contribution de l'extracteur à ce
compteur-là. Les +436 `convergent` prédits sont bien arrivés (1 770 + 496
transitions), ils ne servent simplement plus à ça.

⚠️ **La leçon de méthode** : j'ai additionné deux gains mesurés séparément sans
vérifier qu'ils passaient par le même goulot. Ils y passaient. C'est précisément
pour ça qu'on a joué les deux étapes séparément avec une mesure entre — sans ça,
on aurait attribué le +489 aux deux, et cru le backfill utile là où il ne l'est
pas.

### Ce que le backfill apporte quand même, et ce n'est pas rien

- **128 crops ouverts ne sont plus faussement contredits** (665 → 537). Ils ne
  deviennent pas auto-acceptables — ils échouent ailleurs — mais ils ne portent
  plus une accusation fausse, et le veto redevient un signal fiable ;
- les signaux texte alimentent **autre chose que l'auto-acceptation** :
  `listing_kind` (donc la détection de lot), le funnel du banc, et le routage
  pays du [`PLAN-PECHE-PAYS.md`](./PLAN-PECHE-PAYS.md) — qui, lui, lit
  explicitement `countries_json`. Les 3 001 pays gagnés y comptent ;
- l'extracteur est en `v3` partout : la prochaine évolution de règle repartira
  d'une base saine, pas d'un parc à moitié périmé.

### État servi au canonique après les deux étapes

| verdict, file ouverte 10 333 | n |
|---|---:|
| `auto_candidate` | **2 308** |
| `partial` | 843 |
| `divergent` | 3 313 |
| `unknown` | 3 869 |

Signaux texte : **23 032 en `v3`**, 24 `manual` épargnés.

## Les pièges de ce chantier — à ne pas re-payer

| Piège | Ce qu'il fait |
|---|---|
| La date du fichier `eurio.replica.db` **ment** sur la fraîcheur des faits | resynchronisé le 26/08 20:28, faits arrêtés au 24/08 23:31. Toujours vérifier par `max(enqueued_at)` / `max(fetched_at)`, jamais par `ls` |
| `dino_anchor_banks` **n'existe pas** | c'est `dino_anchor_builds`, et sa colonne est `anchors_kind`, pas `kind` |
| `pending_scoped` ne veut **pas** dire « servi » | 4 959, dont 2 423 dans des classes pleines. Le servable est **2 536** |
| `parked.full_class` (6 587) et les écartés (5 481) **se chevauchent** | les additionner dépasse le total ouvert. Deux découpages de la même file |
| `lane='auto_accept'` ne veut pas dire « décidé par la machine » | 289 des 524 done ont été tranchés à la main. Le seul compteur machine est `decided_by='auto_dino'` |
| `dino_thresholds` est **vide** | lire cette table pour connaître les seuils actifs rend zéro ligne, pas les valeurs en vigueur |
| Deux **mailles** cohabitent | la banque indexe 671 classes, `coins` en rend 592 par `COALESCE(design_group_id, eurio_id)`. 2 948 crops éligibles vus par `class_need` ≠ 2 968 vus par le COALESCE. Piège Q13, en tête de `ml/shared/class_need.py` |
| Le grain « annonce » ≠ le grain `source_images` | 20 845 raws pour 9 216–9 985 annonces selon l'extraction. L'identifiant est le 2e champ de `source_ref` (`ebay_v1|<itemId>|<n>_img<k>`) |
| Sous-requêtes corrélées sur cette base | `where source_image_id in (select …)` **ne termine pas** en 120 s. LEFT JOIN + GROUP BY |
| `n_hidden_by_denom = 0` partout | pas une panne : la porte dénomination **n'a aucun appelant**. Un filtre déployé qui ne mord jamais rend le même code HTTP qu'un filtre absent |
| Le témoin `recover=ON tau=… scope=… listings=N images=M` | prouve que la passe de secours est active, **pas** que le périmètre est neuf |
| `--push` n'est pas un transport | c'est le choix de la base inscriptible. Sans lui, sous le devShell (`EURIO_DB_READONLY=1`), le script meurt en `attempt to write a readonly database` |
| `source_runs.n_calls` **ment** | 8 appels rapportés pour 1 186 réels le 23/08. Le seul compteur vrai est `api_call_log` dans `ml/state/eurio.local.db` |
| `n_targets` d'un run ne dit pas ce qui a été ciblé | 58 `target_eurio_id` pour 3 pièces demandées le 16/08 — `resolve` réattribue la cible |
| `sim_min` est inerte de 0,00 à 0,50 | le faire varier produit une colonne de chiffres identiques qui **a l'air** d'une mesure |
| Le gold fige `dino_in_scope` | il vaut pour la banque d'origine. `replay_gold` le recalcule ; un script maison qui lirait le champ figé mesurerait la mauvaise population sans le dire |
| Ne pas exclure les crops qui **sont** des ancres | ils se reconnaissent eux-mêmes. 345 du gold à retirer |
| L'API `:8042` garde une connexion read-only **thread-local** | lancée avant une écriture, elle sert des chiffres périmés sans le dire. Recalculer dans un **process neuf** |
| Deux comptes de classes cohabitent côté scrape | l'allocateur planifie sur **470** classes déficitaires (min-need 2, tous bottlenecks), `scrape_plan_routes` n'en retient que **265** (`bottleneck=scrape` strict) |

---

## Journal

| Date | Ce qui s'est passé |
|---|---|
| 2026-08-26 | **Chantier ouvert.** Document de pilotage créé sur le modèle de `SUIVI-MATRICE.md`, à la demande du PO. Quatre leviers nommés : scraper, cropper, reconnaître, auto-valider. |
| 2026-08-26 | **Photo de départ prise** — couverture 269/671, Σ need 3 921, file ouverte 10 440, auto-accept machine à l'arrêt depuis le 2026-07-08, 2 968 crops eBay validés sur 290 `eurio_id`. Toutes les requêtes sont dans ce document. |
| 2026-08-26 | ⚠️ **Le bottleneck a basculé** : `scrape 349 / review 213` (doc figé du 23/08) → **`scrape 265 / review 307`**. La file brute a gonflé de 6 371 à 10 440. **Personne ne l'avait vu** — le doc `pipeline-propre/REPRENDRE-ICI.md` sert un instantané figé. |
| 2026-08-26 | **Balayage des seuils du verdict joué** (script neuf `sweep_verdict_thresholds.py`, 466 crops). **La prémisse de la mission est démentie** : désarmer les deux seuils rapporte **+3,2 %**, pas ×2. `sim_min` est strictement inerte sous 0,50. |
| 2026-08-26 | ⚠️ **Panne muette de manuel trouvée** : `PUT /lab/dino-thresholds` accepte `top1_country_sim_min` / `country_spread_min`, répond 200, journalise dans `dino_threshold_changes` — **et ne change rien**. Les seuils sont trois littéraux en dur. |
| 2026-08-26 | **Le vrai levier identifié** : la règle du texte, pas les seuils. `texte ≠ contradict` → 284/283 sur le gold (99,65 %), **2 121 items** sur la file ouverte contre 1 656. C'est un changement de **règle**, posé au PO comme tel (Q1). |
| 2026-08-26 | **Le gratuit est épuisé là où il servait.** `reprocess-zero --scope deficit` : ses 250 images ont **déjà** été rejouées sous `recover=ON`. Rendement attendu **zéro**, run vide, exit 0. Ce qui reste nourrit des classes pleines (1 509 annonces) ou des cibles non résolvables (609). |
| 2026-08-26 | **Le coût du payant chiffré** : 265 classes `bottleneck=scrape`, 205 groupes de découverte, **27 310 appels** estimés. Plan complet : 43 530 appels / 323 groupes. Quota du jour : 5 000, **0 consommé**. |
| 2026-08-26 | ⚠️ **L'unité de coût n'est pas « pays × langue »** mais le groupe de découverte : routage **uniforme** DE puis ES (`marketplaces.py:87`), et 99 % du coût est l'**hydratation** (`item/{id}`), pas la recherche. |
| 2026-08-26 | ⚠️ **Le cooldown 30 j de l'allocateur est aveugle** : `discovery_searches` n'est plus alimentée depuis le **2026-06-16**, les runs par `--target-eurio-ids` ne s'y inscrivent pas. L'allocateur peut reproposer un groupe ratissé il y a 48 h. |
| 2026-08-26 | **Lot 0 écrit et testé** (colmatage review en lot, 4 fuites, 14 tests front + 48 tests Python de périmètre, 9 mutations rouges). **Non déployé.** |
| 2026-08-26 | **Lot 5 écrit et testé** (matrice : garde vendeur testé, garde quasi-doublon, migrations 0015/0016, suite `2456 passed`). **Non déployé, aucune migration appliquée.** |
| 2026-08-26 | ⛔ **Vérification adversariale : deux bloquants.** (B1) le lot 0 exige deux champs que le canonique déployé ne sert pas — front seul en avance = review en lot **morte**. (B2) un **débris de mutation** `# MUTATION` laissé dans `bench_encoder_dino.py:551` : `_quantization_of` n'a plus aucun appelant, et `SUIVI-MATRICE.md` affirme le contraire. |
| 2026-08-26 | ⚠️ **Le suivi de l'autre chantier ment sur un point mesurable** (M10) : le garde quasi-doublon n'écarte **rien** de plus que le garde vendeur sur la donnée d'aujourd'hui (différence symétrique = 0 ; 5 `source_images` à `seller_id IS NULL`, dont 0 porteuse d'ancre). Le « +0,5 pt » annoncé vaut 0. |
| 2026-08-26 | **Trois plans écrits** : `PLAN-PECHE-PAYS.md`, `PLAN-ECRAN-BINAIRE.md`, `PLAN-SCRAPE.md`. Aucun code. Rien de commité, rien de déployé, rien de scrapé. |
| 2026-08-27 | ✅ **B2 est sans objet** : le code portait bien `"quantization": _quantization_of(encoder)`. Le bloquant venait d'une **course entre deux vérificateurs parallèles** — celui qui rejouait une mutation avait cassé la ligne pendant qu'un autre lisait l'arbre. Règle pour les prochains workflows : la lentille « mutation » ne doit pas partager son arbre de travail avec les autres lentilles. |
| 2026-08-27 | ✅ **M10 corrigé** dans `SUIVI-MATRICE.md` : le garde quasi-doublon n'écarte **0** pick de plus que le garde vendeur (différence symétrique des `asset_id` = 0 ; 5 `source_images` à `seller_id IS NULL`, dont 0 porteuse d'ancre). Le « +0,5 pt » portait sur le corpus **v1**, prélevé sans garde vendeur. Le garde reste en place — il ferme un trou réel — mais il ne justifie aucun chiffre. |
| 2026-08-27 | **Arbre vérifié cohérent après la session multi-agents** : `2456 passed` (Python, +64 tests), `14 passed` (vitest front, 4 fichiers neufs), `vue-tsc --noEmit` propre, `pnpm build` en 4,16 s. |
| 2026-08-27 | **Audit visuel de 10 crops** (sous-agent, images regardées). L'intuition du PO est départagée : **la donnée eBay est bonne — 8 titres sur 10 justes, 0 trompeur — c'est notre EXTRACTION qui est fautive, 4 fois sur 10.** |
| 2026-08-27 | ⚠️ **La bande pays ne vient pas d'eBay** : `target_eurio_id[:2]`, la cible du scrape (`auto_validate.py:754`). Prior auto-réalisateur. Elle gagne 2,9 pts en moyenne et tombe à **0 %** sur les 32 crops dont la décision sort du pays cherché. **Mais la mesure ne peut pas trancher** : divergence 6,4 % sur la file tranchée contre **46,9 %** sur la file ouverte. |
| 2026-08-27 | **Banc à l'aveugle publié** — 60 crops divergents de la file ouverte, ordre tiré d'un hash, aucun `eurio_id` visible, ouverture du titre enregistrée. En attente du PO. C'est la seule population qui peut trancher la bande. |
| 2026-08-27 | ⚠️ **Correction d'une de mes lectures** : j'ai d'abord écrit que le veto année se pénalisait lui-même. Faux — sur les crops en `contradict`, DINO tombe de **96,3 % à 64,6 %**. Le veto reste armé. |
| 2026-08-27 | **Les 4 défauts d'extraction corrigés** (millésime collé, 16 pays espagnols, marqueur accessoire, plage de millésimes) + bump `EXTRACTOR_VERSION` v2 → **v3**. Simulation en lecture : **1 487 verdicts changent sur 7 118**, `convergent` **4 999 → 5 435 (+436)**. Autant que le changement de règle, mais par justesse et non par permissivité. 17 tests, 9 mutations rouges, **2472 passed**. |
| 2026-08-27 | ❌ **Hypothèse démentie, la mienne** : « on jette du temps de review dans des boîtes en plastique ». Mesuré : **1 seul** item accessoire dans la file (3 après correctif). Les 1 213 blister/coincard/capsule contiennent une vraie pièce. Le marqueur est une correction de justesse, pas un gain de volume — et il ne filtre rien, `rejected_markers_json` n'est lu que pour l'affichage. |
| 2026-08-27 | **Banc à l'aveugle joué par le PO — 60 crops.** Bande **19**, global **3**, aucune des deux **38**, indécidable 0, titre ouvert 1 fois. Binomial bilatéral **p = 0,00086**. |
| 2026-08-27 | ⚠️ **Mon hypothèse est démentie.** J'avais prédit que la bande pays serait mise en défaut sur la population divergente ; elle y gagne **plus nettement** qu'ailleurs. **D10 : on ne touche pas à `_resolve_signals`**, et les politiques P1/P2/P3 sont écartées. |
| 2026-08-27 | 🔴 **Le résultat que personne n'attendait : 63 % du temps les DEUX voies se trompent.** La divergence est un signal d'abstention (« DINO est perdu »), pas d'arbitrage — 3 346 crops concernés en file ouverte. ⚠️ Le banc ne sépare pas « DINO est perdu » de « la vraie classe n'était pas offerte ». |
| 2026-08-27 | **Défaut neuf trouvé grâce à l'observation du PO sur les revers.** L'étiquette `face` est écrite UNE FOIS (`auto_validate.py:874`, `AND face IS NULL`) et la marge la compare à **34 ancres de revers contre 2 062 d'avers** (`:828`), avec un τ figé au **2026-06-13** pendant que la banque des avers grossissait de 65 %. En base : **237 `obverse` que la marge dit revers**, **343 `reverse` qu'elle dit avers**, **289 sans étiquette qu'elle dit revers**. Dans la file ouverte, **290 crops** ont une marge ≥ τ (198 sans étiquette). Écarté après vérification : ce n'est PAS une désynchronisation d'encodeur (les deux banques sont en `dinov2-vitl14`, dim 1024). |
| 2026-08-27 | ⚠️ **Nuance à ne pas perdre** : les revers expliquent une **minorité** des 38 (10 marges positives, 5 au-delà de τ/2), pas la majorité. Et le détecteur fait bien son travail par ailleurs — 1 875 revers attrapés, 1 700 tranchés, 0 attribué. Le défaut est la dérive et l'écriture unique, pas l'inefficacité. |
| 2026-08-27 | **Défaut de face attaqué.** Trois causes cumulées : (1) le seuil dérive avec la taille de la banque des AVERS — 34 ancres de revers contre 2 062 d'avers — rappel des revers durs **73,3 % → 40,0 %** entre juin et août, τ inchangé ; (2) τ = 0,065 ne rachetait **aucun** faux positif (marge max des 514 avers confirmés : **−0,0507**) ; (3) l'étiquette était écrite une seule fois sans savoir par qui. |
| 2026-08-27 | **Corrigé** : τ → **0,000** (frontière naturelle, 0,05 de marge, pas une constante calibrée) · **migration 0017 `face_source`** avec backfill exact depuis `review_queue.decided_face` · les deux écrivains gardent sur la PROVENANCE · alarme de dérive posée dans `build_anchors_2eur_all`, à la cause · `--taus` ajouté au banc pour le rendre balayable. |
| 2026-08-27 | **Simulé sur une copie de la réplique** : 4 298 faces changent, dont 1 380 `obverse → reverse` et 51 `reverse → obverse` (crops rendus au training). **1 051 crops sortent de la file ouverte.** Rien d'appliqué : migration non jouée au canonique, passe en dry-run. |
| 2026-08-27 | ❌ **Trois de mes soupçons écartés par la mesure** : la banque d'ancres n'est PAS empoisonnée (0 ancre au-dessus de τ), les deux banques ne sont PAS désynchronisées d'encodeur, et le détecteur n'est PAS inefficace (1 875 revers attrapés, 0 attribué). Le défaut est la dérive et l'écriture unique. |
| 2026-08-27 | ⚠️ **Piège fermé** : `_ensure_column` seul aurait posé `face_source` à NULL sur une base antérieure, rendant **tous les verdicts humains écrasables** — l'ALTER sans son backfill installe le défaut au lieu de le corriger. `_ensure_column` retourne désormais un booléen et le bootstrap rejoue le backfill à la création seule. Mutation jouée. |
| 2026-08-27 | **DÉPLOYÉ.** Commit `edd708c4` poussé, `eurio-api` rebâti. Les migrations **0015, 0016 et 0017** appliquées ensemble (le canonique était à 0014) — Q5 tranché de fait. Backfill vérifié sur le canonique : **3 122 verdicts humains protégés**, 0 face sans provenance. Le FRONT n'est pas déployé (lot 0, 5 majeurs ouverts). |
| 2026-08-27 | **Passe corrective appliquée au canonique** : **4 298 faces réécrites**, identique au dry-run. Photo de l'état AVANT dans `/var/lib/eurio/face_avant_2026-08-27.csv` — la passe est réversible. Trois invariants relus dans un process neuf, tous à 0. |
| 2026-08-27 | ⚠️ **Ma phrase « 1 051 crops sortent de la file » était prématurée.** La passe corrige l'étiquette, pas le routage : `list_queue` n'a aucun prédicat sur `face`, et le rejet `face_reverse` se fait à l'enqueue, jamais rétroactivement. Mesuré après : ouverts `reverse` 1 → **1 052**, file totale **11 377 inchangée**. **1 044 sont rejetables** (8 restaurés à la main à épargner). |
| 2026-08-27 | **Le geste de rejet reste à faire, et il est bloqué proprement** : les helpers (`_reject_crop_terminal`) vivent dans `enqueue`, qui importe `review_lanes`, qui importe `training` — inimportable dans l'image lean. Réécrire le rejet en SQL créerait une seconde copie de la règle. Correctif propre : sortir la moitié stdlib de `review_lanes`, comme on vient de le faire pour `face_rule`. **Attend le PO** (refactor + second déploiement). |
| 2026-08-27 | **Refactor `store/review_routing.py`.** ⚠️ Découper `review_lanes` seul n'aurait PAS suffi : `review.validation.{consensus,experts,persist}` tirent `training` eux aussi. La bonne cible était les helpers, pas le module intermédiaire. Une seule définition, deux tests la verrouillent. Commit `60dbe004`, redéployé. |
| 2026-08-27 | ✅ **Les 1 044 encaissés.** File ouverte **11 377 → 10 333 (−9,2 %)**, ouverts `reverse` **1 052 → 8** (exactement les sticky restaurés à la main), 853 listings re-routés, 0 asset `face_reverse` resté `training_eligible=1`. Photo avant rejet dans `/var/lib/eurio/rejet_revers_avant_2026-08-27.csv`. Suite `2491 passed`, 7 mutations rouges. |
| 2026-08-27 | **R6 fait — gold rebâti.** 1 009 → **3 383 entrées**, 811 → **2 607 labellisées**, population évaluable **466 → 1 309** (×2,8). Les 1 391 ancres restent exclues. |
| 2026-08-27 | ✅ **D4 confirmée sur 2,8× la population** : désarmer les deux seuils rapporte **+29 (+5,5 %)**, contre +3,2 % sur le petit gold. Les seuils sont bien inertes, on n'y touche pas. |
| 2026-08-27 | 🔴 **Correction : le point A n'améliore PAS la précision.** Le suivi annonçait 99,46 → 99,65 — artefact des 466 crops. Sur 1 309 : **99,81 → 99,74**, elle baisse de 0,07 pt. **Mais la borne basse de Wilson MONTE** (98,93 → 99,04) : au pire cas le point A est au moins aussi bon, la mesure portant sur 43 % de crops en plus. |
| 2026-08-27 | **Volume du point A sur la file d'aujourd'hui** (10 333 ouverts, après le rejet des revers) : 1 819 → **2 308 auto_candidate, +489 (+26,9 %)**. ⚠️ Signaux texte encore en `v2` — l'extracteur `v3` est déployé, aucun backfill n'a tourné. Les deux arbres sont comparés sur les mêmes signaux, le départage est honnête ; les valeurs absolues bougeront après. |
| 2026-08-27 | **`--text-gate {convergent,any}` ajouté au balayage.** Il ne recopie pas la règle : au point 5, `texte ≠ contradict` équivaut à AUCUNE condition de texte (la règle 2 a déjà sorti les contradictions), et la mesure dérive de la sortie de la vraie fonction. |
| 2026-08-27 | **Q1 passée en code et déployée.** Le texte devient un VETO, il n'est plus une condition. Les deux copies changent (legacy + port lean) ; une mutation qui n'en change qu'une rougit. `auto_candidate` sur la file : 1 819 → **2 308 (+489)**, exactement la prédiction. Deux trous de test comblés — aucun test lean ne posait de `listing_text_signals`, donc retirer le veto du port n'aurait fait rougir personne. Suite `2503 passed`, 7 mutations rouges. |
| 2026-08-27 | **Backfill v3 joué au canonique** : 22 838 extraits, 24 `manual` épargnés, 0 erreur, 27,6 s. **3 001 annonces gagnent un pays**, 38 une année, 3 485 verdicts changent. Crops ouverts en `contradict` : 665 → **537**. Photo avant dans `text_signals_avant_v3_2026-08-27.csv`. |
| 2026-08-27 | 🔴 **Ma prédiction est démentie : les deux gains ne se cumulent PAS.** `auto_candidate` reste à **2 308** après le backfill. Q1 ayant retiré la condition de texte de l'étape 5, la distinction `convergent`/`partial` — celle que les 3 001 pays améliorent — n'entre plus dans l'auto-acceptation. **Leçon : j'ai additionné deux gains sans vérifier qu'ils passaient par le même goulot.** C'est pour ça qu'on a joué les deux étapes séparément avec une mesure entre — sans quoi le +489 aurait été attribué aux deux. |
| 2026-08-27 | **Ce que le backfill apporte quand même** : 128 crops ouverts ne sont plus faussement contredits, le veto redevient fiable, et les signaux servent ailleurs — `listing_kind`, le funnel, et le routage pays du plan pêche qui lit `countries_json`. |
