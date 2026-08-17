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
sops exec-env secrets/dev.env 'nix develop .#mac --command bash -c \
  "cd ml && .venv/bin/python -m sources.cli --source ebay \
     --target-eurio-ids <id1>,<id2> --push"'
```

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
| découverte | 1762 listings vus, **803 raws**, **622 crops** |
| review créée | **528 items** (369 lot / 159 single) |
| durée | ~1 h (téléchargement + crop OpenCV) |
| quota eBay | 5000/jour, compté dans `eurio.local.db` (`shared/api_quota`, table `api_call_log`) |

Le compteur du run n'a rapporté que **3 appels** — c'est le compte des requêtes de
recherche, pas des appels d'hydratation `item/{id}`. Ne pas s'en servir pour
estimer le quota consommé.

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
# 1. rebâtir les deux banques (2eur_all est celle des suggestions de review)
go-task ml:dino-anchors:build -- --force --kind 2eur_commemo
go-task ml:dino-anchors:build -- --force --kind 2eur_all
# 2. recalculer les prédictions et les pousser au canonique
go-task ml:dino-predictions:backfill -- --kind 2eur_all --force --push
```

Effet mesuré le 2026-08-17 sur les deux classes qui bloquaient une promotion :

| Classe | candidats avant | après reconstruction |
|---|---|---|
| `fr-2euro-standard-t1` | 38 | 38 |
| `es-2euro-juan-carlos-i-t2` | **0** | **24** |

Une classe entière était invisible faute d'ancres à jour. Aucun scrape, si gros
soit-il, ne l'aurait débloquée.

### Pièges de ces deux commandes

- **`build_dino_anchors --db` est un leurre.** Le drapeau laisse croire qu'on
  choisit la base ; `Store(path)` hérite du `read_only` de l'environnement, donc
  sous le devShell l'écriture de `dino_class_references` échoue — **après** les
  4 minutes d'encodage. Le `.npz` est écrit avant, donc le travail coûteux est
  sauvé, mais le job sort en erreur. Lancer avec `EURIO_DB_READONLY=` si on veut
  la traçabilité en base (cf. `eurio-data-writes`).
- Le backfill est **long** : 9095 crops en **1 h 26** (565 ms/crop, `vitl14` sur
  MPS). Il ne loge rien avant la fin ; pour suivre, compter les lignes dans sa
  base scratch (`/tmp/**/dino_scratch.db`), pas dans les logs.
- **Une pièce sans `obverse.jpg` n'a pas d'ancre, donc ne peut jamais être
  suggérée.** Le constructeur le dit dans son log (« Skipped N coins (no
  obverse.jpg) ») ; mesuré sur le Mac le 2026-08-17 : **122 dossiers sur 688**
  n'en ont pas. Vérifier `ml/datasets/<numista_id>/obverse.jpg` avant de conclure
  qu'une classe est « introuvable » :

  ```bash
  ls ml/datasets/[0-9]*/obverse.jpg | wc -l   # combien en ont un
  ls -d ml/datasets/[0-9]*        | wc -l     # combien de pièces au total
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

## Ensuite

→ **`eurio-review`** : trancher les crops et les rendre `training_eligible`.
→ puis **`eurio-run-local`** : monter l'itération et entraîner.

## Ce que cette skill ne couvre PAS

- Le détail du pipeline en 8 étapes : `ml/sources/_base/orchestrator.py`.
- La construction des requêtes eBay : `ml/sources/ebay/queries.py` (+ `filters.py`
  pour le funnel et la détection de lots).
- La logique de crop : `ml/sources/_base/steps/detect_crop.py` et
  `ml/vision/normalize_snap.py`. Note : `0 crop` n'est **pas** une erreur (photos
  de certificat, emballages) et **seuls les zéros sont logués** — un log plein de
  « returned 0 crops » ne veut pas dire que rien ne marche. Compter les fichiers
  produits sous `~/.cache/eurio/enrichment-crops` pour savoir.
