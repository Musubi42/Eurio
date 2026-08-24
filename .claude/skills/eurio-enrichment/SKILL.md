---
name: eurio-enrichment
description: Nourrir une classe trop pauvre pour l'entraînement — scrape eBay, crop, ancres DINO. À lire quand le préflight refuse une cohorte, quand une classe manque de crops, ou avant tout `sources.cli --source ebay`.
---

# Enrichir une classe pauvre

> Cette skill couvre le chemin qui va d'un refus de préflight à une classe
> nourrie. Elle s'arrête à la file de review : la suite est dans **`eurio-review`**.

## Deux garde-fous distincts, à ne pas confondre

`training/foundation/preflight.py` classe chaque **classe** en `block` ou `warn` :

| Verdict | Condition | Défaut |
|---|---|---|
| `block` | `seed < m_per_class` — `seed` = **total** des sources réelles (Numista + eBay + réfs officielles) | 4, lisible dans `run.config` |
| `warn` | `n_ebay < MIN_REAL` — seulement les crops eBay | 10 (`store/funnel_constants.py`) |

- La **création d'itération** (`POST /lab/cohorts/{id}/iterations`) refuse sur
  `block` **et** sur `warn` — une cohorte se veut propre (`lab_routes.py`).
- Le **run** d'entraînement, lui, ne s'arrête que sur `block` : son docstring dit
  explicitement que les classes pauvres en eBay n'arrêtent pas le run.

Donc « ça refuse » ne veut pas dire la même chose selon l'endroit. Regarde le
verdict, pas le seuil.

## La règle qui évite la plupart des erreurs

**Compte par CLASSE, jamais par pièce.** La maille est
`COALESCE(design_group_id, eurio_id)`. Une pièce peut avoir 1 crop et sa classe
en avoir 40, parce que ses sœurs de groupe les portent. Le préflight, le bake et
la banque d'ancres raisonnent tous à la classe.

Corollaire vécu (2026-08-17, deux fois dans la même session) : chercher
`fr-2007-2eur-standard-2nd-map` dans les prédictions ne donne **rien**, et ce
n'est pas un manque de données — la banque d'ancres ne porte **qu'une étiquette
par classe** (le représentant du groupe, choisi par `ORDER BY year, eurio_id` —
ici `fr-1999-…`), même si elle contient **plusieurs vecteurs** pour cette classe
(le canonique + ~10 exemplaires validés). Les deux pièces partagent leur face
nationale ; ce qui a changé en 2007 est la face commune, que le modèle ne regarde
pas. Chercher l'étiquette d'un membre, c'est chercher ce qui ne peut pas exister.

## Le flux

```
préflight refuse            →  quelle CLASSE est pauvre, et de combien ?
   ↓
sources.cli --source ebay   →  discover · download · crop · resolve · enqueue
   ↓ (crops en review_queue, sans étiquette sûre)
ancres DINO à jour ?        →  sinon : rebuild + backfill, SINON RIEN NE SORT
   ↓
review  →  voir la skill `eurio-review`
```

## Lancer un enrichissement

```bash
go-task ml:src:ebay:run -- --target-eurio-ids <id1>,<id2> --push
```

⛔ **Passe par la tâche, jamais par `python -m sources.cli` en direct.** La tâche
pose `EURIO_CENSUS_RECOVER=1` (`ml/tasks.yml:717-725`), **OFF par défaut**
(`vision/normalize_snap.py:539`), qui active la passe de récupération
score-guided des bimétal sous-croppés — **~77 % du parc**, validée le
2026-06-15. L'invocation brute la désactive en silence et une grosse part des
raws repart en `zero_crops`. Les autres portes : `ml:src:ebay:dry` (découverte
seule), `ml:src:ebay:limit`, `ml:src:ebay:status`.

🔴 **Mesuré le 2026-08-21 : cette passe n'avait JAMAIS tourné en prod.** Le run
du 2026-08-16 porte 0 crop `detection_method='score_recover'` sur 601, et 54 %
de `zero_crops`. Au grain **annonce** (l'unité de coût eBay, un `item/{id}`
par annonce), 2 950 annonces sur 7 662 n'avaient produit aucun crop — 70 %
montrent une pièce seule plein cadre que YOLO ne voit pas. Le remède, sans un
appel eBay :

```bash
go-task ml:src:ebay:reprocess-zero -- --dry-run            # le périmètre, rien d'écrit
go-task ml:src:ebay:reprocess-zero -- --limit 40 --seed 42 --push
go-task ml:src:ebay:reprocess-zero -- --push               # défaut : classes de banque < 8 fps
```

Le témoin est la **première ligne du log** : `recover=ON tau=0.55 scope=…
listings=N images=M` — sans elle, le script refuse de créer un run (exit 2).
Résultat du 2026-08-21 : 811 annonces rejouées, **669 récupérées (82 %)**,
936 crops dont 923 `score_recover`, 777 en file ouverte, 51 min sur Mac.
Détail, requêtes et ce qui reste à zéro :
`docs/work-in-progress/pipeline-propre/JOURNAL.md`.

- **`--push` est mal nommé** : il ne contrôle **pas** le transport, il choisit la
  **source de lecture/écriture** — une réplique scratch **inscriptible**
  (`staging_store`). C'est pour ça qu'il est le mode normal : sans lui, le
  pipeline écrit la DB pointée par le flip et meurt en `attempt to write a
  readonly database` dès `run_logger.start_run`, **avant le premier appel eBay**.
- Le **push au canonique, lui, est automatique** dès qu'`EURIO_API_URL` est
  configuré, avec ou sans `--push`. `--no-push` est la seule échappatoire.
- ⛔ **`go-task ml:scrape-ebay` est morte** : elle pointe `market/scrape_ebay.py`,
  fichier inexistant. Ne pas l'utiliser, ne pas la « réparer » sans décision.

### Ce que ça coûte, mesuré le 2026-08-17

| | |
|---|---|
| 3 pièces ciblées (FR + ES) | découverte = **1 requête par groupe × marché × langue** — « Frankreich / Francia / Spanien / España » |
| découverte | 1762 listings vus, **801 raws**, **622 crops** |
| review créée | **528 items** (369 lot / 159 single) |
| durée | ~1 h (téléchargement + crop OpenCV) |
| **quota eBay réellement brûlé** | **740 appels** sur 5000/jour |

Le compteur du run (`source_runs.n_calls`) a rapporté **3 appels** — c'est le
compte des requêtes de recherche, pas des hydratations `item/{id}`. Le préflight
quota ment dans le même sens (`estimate: 1`). **Le seul chiffre vrai est dans
`eurio.local.db`** :

```bash
sqlite3 -readonly ml/state/eurio.local.db \
  "select period, calls from api_call_log where source='ebay' order by rowid desc limit 1;"
# 2026-08-16|740
```

⚠️ **La découverte est par GROUPE, jamais par pièce.** Cibler trois pièces
françaises et espagnoles lance les requêtes « 2 euro Frankreich / Francia /
Spanien / España » et ramène tout le 2 € standard de ces pays. C'est le design,
pas un bug : on ne peut pas enrichir une pièce à moindre coût. Prévoir le volume
de review en conséquence, et cadrer l'attente de l'humain qui va trancher.

⚠️ **`--limit` ne réduit pas la découverte** (vérifié) : elle plafonne ailleurs.

## Les ancres DINO — l'étape qu'on oublie et qui décide de tout

Un crop scrapé n'arrive **jamais** avec une étiquette sûre. C'est la banque
d'ancres qui propose une classe. Si elle est périmée, le scrape est du travail
perdu : les crops arrivent en review sans suggestion exploitable.

**Après tout renommage de slug — et il y en a eu — il faut rebâtir.** C'est écrit
dans la description de `ml:dino-anchors:build`, et ça n'avait jamais été fait :

```bash
# 1. rebâtir les deux banques
go-task ml:dino-anchors:build -- --force --kind 2eur_commemo
go-task ml:dino-anchors:build -- --force --kind 2eur_all
# 2. recalculer les prédictions et les pousser au canonique
go-task ml:dino-predictions:backfill -- --kind 2eur_all --force --push
```

⚠️ **Les deux banques ne servent pas la même chose, et ce n'est pas celle qu'on
croit qui alimente la review.** Corrigé le 2026-08-17 :

> ✅ **RÉSOLU le 2026-08-24 — ce bloc décrivait l'état d'avant. Conservé pour la
> trace du défaut, pas pour agir.** Le verdict de review lisait `2eur_commemo`
> **en dur**, une banque sans aucune étiquette de pièce standard (0 sur 446) :
> reconstruire `2eur_all` n'allumait rien dans l'écran de review d'une classe
> courante. Depuis la bascule, `ml/shared/verdict_scope.py:65` porte
> `VERDICT_ANCHORS_KIND = "2eur_all"`, et `2eur_commemo` n'apparaît plus dans
> `serving/review_queue/repository.py`.
>
> **Aujourd'hui : reconstruire `2eur_all` allume bien la review, standards
> compris.**

**Avant de rebâtir, vérifie que c'est nécessaire** — mesuré le 2026-08-19 :
**237 s** d'encodage plus **28 min** de backfill pour les 12454 crops
(`23:20:42 → 23:48:36`, `vitl14` sur MPS). Le `.npz` porte sa date, son encodeur
et son compte :

```bash
cd ml && ./.venv/bin/python -c "
import numpy as np, json
d = np.load('state/foundation_anchors_2eur_all.npz', allow_pickle=True)
print(json.loads(str(d['meta'][0])))"
# {'encoder_version': 'dinov2-vitl14', 'anchors_kind': '2eur_all',
#  'built_at': '2026-08-19T14:36:14+00:00', 'count': 1533, 'dim': 1024, 'bank_id': 'a0fec2b0…'}
```

⚠️ **`bank_id` n'est PAS le `build_id`** de `dino_anchor_builds`, et le rebuild
a d'autres pièges (refus sous devShell, refus faute de migration 0010 au
canonique, `--no-serve`) : lire **`eurio-banque`** §7 avant de le lancer.

L'encodeur doit être celui qu'attend `encoder_version_for_kind(<kind>)` — sinon
`auto_validate` traite la banque comme absente.

Effet mesuré le 2026-08-17 sur les deux classes qui bloquaient la promotion,
**par la requête du §Vérifier ci-dessous** (candidats *par prédiction*,
`2eur_all`, marge ≥ 0,05) :

| Classe | avant reconstruction | après | au 2026-08-17 (soir) |
|---|---|---|---|
| `fr-2euro-standard-t1` | 38 | 38 | **59** |
| `es-2euro-juan-carlos-i-t2` | **0** | 24 | **29** |

Une classe entière était invisible faute d'ancres à jour. Aucun scrape, si gros
soit-il, ne l'aurait débloquée. La troisième colonne dit autre chose : **ces
chiffres bougent d'un jour à l'autre**, donc remesure au lieu de citer.

✅ **Corrigé le 2026-08-19** — cette skill affirmait que `dino_class_references`
était vide partout. Elle ne l'est plus : le rebuild avec le `--db` réparé a
tracé la sélection FPS.

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT anchors_kind, method, COUNT(*), COUNT(DISTINCT class_id)
  FROM dino_class_references GROUP BY 1,2;"
# 2eur_all|canonical|671|671
# 2eur_all|fps|862|182
```

**671 classes, 1533 ancres, 182 classes à exemplaires** (contre 125 avant :
la banque était bâtie sur 6205 assets au lieu de 12454). Lecture, maille et
pièges : **`eurio-banque`**.

### Pièges de ces deux commandes

- **`build_dino_anchors --db` est un leurre.** Le drapeau laisse croire qu'on
  choisit la base ; `Store(path)` hérite du `read_only` de l'environnement, donc
  sous le devShell l'écriture de `dino_class_references` échoue. **Depuis le
  2026-08-19 la commande refuse de démarrer** sous `EURIO_DB_READONLY=1` au lieu
  de mourir après l'encodage — relancer avec `EURIO_DB_READONLY=` , ou
  `--skip-references` pour le `.npz` seul (cf. `eurio-data-writes`).
  ✅ **Le blocage « migration 0008 » est levé** (vérifié le 2026-08-25 : canonique
  et réplique à `0013`, clé 0010 présente). Le refus `CleSansEncodeurError` ne
  concerne plus qu'une base locale créée avant 0010. Détail et la leçon qui
  reste — *mesurer le schéma sur la base qu'on va écrire, pas sur sa réplique* :
  **`eurio-banque`** §7.
- **Un témoin de volume, pas un « 0 erreurs ».** Les deux commandes impriment
  ce qu'elles ont **vu** : `1533` ancres (banque à jour) contre `1250`
  (périmée) ; `12454` candidate assets (base saine) contre `6205` (base
  périmée). Une base périmée répond normalement — elle rend simplement moins de
  lignes. C'est le défaut qui a fait bâtir la banque sur un demi-corpus pendant
  des semaines (`FINDINGS.md` §8.7).
- Le backfill a duré **28 min** pour 12454 crops le 2026-08-19 (`vitl14` sur
  MPS) — l'ancien chiffre « 9095 crops en 1 h 26 » est périmé. Il ne loge rien
  avant la fin ; pour suivre, compter les lignes dans sa base scratch
  (`/tmp/**/dino_scratch.db`), pas dans les logs. ⚠️ **Il sort en code 0 même en
  erreur** (dette M8) : la preuve est
  `store.encoder_bench.calibration_blockers(...) → []`, pas le code de sortie.
- **Une pièce sans `obverse.jpg` n'a pas d'ancre, donc ne peut jamais être
  suggérée.** Le constructeur le dit dans son log (« Skipped N coins (no
  obverse.jpg) »). ✅ **Le trou est bouché depuis le 2026-08-19** — remesuré le
  2026-08-20 : **695 dossiers, 695 `obverse.jpg`, aucun manquant** (et
  `n_no_canonical = 0` dans le build `23c637d93b43`, contre 7 au build
  précédent). L'ancien « 122 sur 688 » est périmé. Le contrôle reste bon marché,
  refais-le avant de conclure qu'une classe est « introuvable » :

  ```bash
  ls ml/datasets/[0-9]*/obverse.jpg | wc -l   # 695 — combien en ont un
  ls -d ml/datasets/[0-9]*        | wc -l     # 695 — combien de pièces au total
  sqlite3 -readonly ml/state/eurio.replica.db \
    "SELECT substr(build_id,1,12), n_no_canonical FROM dino_anchor_builds ORDER BY built_at DESC;"
  # 23c637d93b43|0    ← 0 classe portée par ses seuls crops
  # 42d17f9e7083|7
  ```

## Vérifier que l'enrichissement a servi

Toujours à la classe, et toujours en excluant ce qui est déjà validé :

```sql
select c.design_group_id,
       (select count(*) from image_assets a join source_images s on s.id=a.source_image_id
         where s.source='ebay' and a.training_eligible=1
           and a.eurio_id in (select eurio_id from coins where design_group_id=c.design_group_id)) actuels,
       (select count(*) from image_asset_dino_predictions p join image_assets a2 on a2.id=p.asset_id
         where p.anchors_kind='2eur_all' and a2.training_eligible IS NOT 1
           and coalesce(p.country_spread, p.spread) >= 0.05
           and p.top1_eurio_id in (select eurio_id from coins where design_group_id=c.design_group_id)) candidats
  from coins c where c.design_group_id = '<classe>' group by 1;
```

La condition de **marge** n'est pas décorative — voir `eurio-review`, c'est elle
qui sépare une suggestion utile d'un tirage au sort.

Trois précautions sur ce chiffre, toutes vécues :

1. **Il compte les crops PRÉDITS comme la classe**, pas ceux qui la **ciblent**.
   Les deux populations sont légitimes et différentes ; deux mesures honnêtes de
   « les candidats de `fr-2euro-standard-t1` » ont rendu **59** et **0** pour
   cette seule raison. Dis toujours laquelle tu comptes.
2. **Il inclut des items déjà tranchés.** Joins `review_queue` et ajoute
   `and rq.status in ('open','in_progress')` pour le stock réellement
   exploitable (mesuré : 29 candidats → **26** ouverts sur la classe espagnole).
3. **Un candidat n'est pas un crop gagné.** Il faut encore qu'un humain le
   tranche — voir `eurio-review`. Le run du 2026-08-16 a laissé 528 items
   `open` ; le préflight n'a pas bougé d'un pouce.

### Avant de scraper : vérifie que le scrape est bien le geste

Le préflight distingue `block` (sources réelles < `m_per_class`) de `warn`
(crops eBay < 10). Un `warn` se répare **souvent en review, pas en scrapant** :
mesuré le 2026-08-17 sur `es-2euro-juan-carlos-i-t2` — il manquait **6 crops
acceptés** pour passer le plancher, et **26 candidats attendaient déjà** en file.
Le scrape de la veille avait rendu **3** crops à cette classe, aucun au-dessus de
la marge, pour ~30 min et ~400 appels.

Lance le préflight réel plutôt que de deviner :

```bash
sops exec-env secrets/dev.env 'curl -s -H "Authorization: Bearer $EURIO_API_TOKEN" \
  "http://127.0.0.1:8042/lab/cohorts/<cohort_id>/training-readiness"'
```

Il rend le verdict par classe **et** la raison textuelle. Utile aussi pour voir
que la cohorte est de toute façon bloquée par une **autre** classe : enrichir la
tienne ne la débloquera pas.

### Et vérifie qu'il y a bien un goulot de SCRAPE — mesuré le 2026-08-20

Pour les **489 classes de banque à zéro exemplaire** (671 − 182), le goulot
n'est pas le même partout. Compté sur les crops de la **file ouverte** dont le
top-1 DINO tombe dans la classe (`2eur_all`/`vitl14`, requête complète dans
**`eurio-banque`** §8) :

| crops en file ouverte | 0 | 1 | 2 | 3-4 | 5-7 | ≥ 8 |
|---|---:|---:|---:|---:|---:|---:|
| classes | **305** | 78 | 36 | 26 | 21 | 23 |

- **305 classes n'ont rien en file** → c'est là, et là seulement, que le scrape
  est le geste.
- **78 n'ont qu'un crop** → le valider seul **dégraderait** la classe (la courbe
  donne N=1 à 50,1 % contre N=0 à 53,1 %). Il faut d'abord scraper de quoi en
  avoir trois.
- **23 seulement** peuvent atteindre la cible de 8 sans un appel eBay de plus.

⚠️ Ce compte est *par prédiction*. La même mesure *par cible de scrape*
(`source_images.target_eurio_id`) rend 433 / 9 / 5 / 12 / 10 / 20. Les deux sont
légitimes — dis toujours laquelle tu comptes.

⚠️ Et le plancher `MIN_REAL = 10` du préflight n'est **pas** la cible de la
banque. La courbe dit **8 crops validés par classe** (arbitrage, pas plateau) et
**jamais 1**. Les deux garde-fous répondent à deux voies différentes : le
préflight sert l'entraînement ArcFace (voie A), la banque sert les suggestions
(voie B). Cf. **`eurio-banque`** §3 et §8.

## Ensuite

→ **`eurio-review`** : trancher les crops et les rendre `training_eligible`.
→ **`eurio-banque`** : combien de crops une classe mérite, et ce que coûte un
  rebuild d'ancres.
→ puis **`eurio-run-local`** : monter l'itération et entraîner.

## Ce que cette skill ne couvre PAS

- La banque d'ancres elle-même — maille `class_id`, rangs FPS, seuils, banc
  d'encodeurs, courbe références/classe : **`eurio-banque`**.
- Le détail du pipeline en 8 étapes : `ml/sources/_base/orchestrator.py`.
- La construction des requêtes eBay : `ml/sources/ebay/queries.py` (+ `filters.py`
  pour le funnel et la détection de lots).
- La logique de crop : `ml/sources/_base/steps/detect_crop.py` et
  `ml/vision/normalize_snap.py`. Note : `0 crop` n'est **pas** une erreur (photos
  de certificat, emballages) et **seuls les zéros sont logués** — un log plein de
  « returned 0 crops » ne veut pas dire que rien ne marche. Compter les fichiers
  produits sous `~/.cache/eurio/enrichment-crops` pour savoir. ⚠️ Mais **ne
  conclus pas non plus que les zéros sont des emballages** : mesuré le
  2026-08-21, 70 % étaient des pièces seules plein cadre (cf. §« Lancer un
  enrichissement »).
