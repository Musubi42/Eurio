# Architecture — Harmonisation des données Eurio

> Doc de design **verrouillé 2026-05-22**, issu du brainstorm sur le kickoff
> (`kickoff.md`). Fige les décisions ; le découpage en chunks vit dans
> `plan.md`. Quand une décision change, l'amender ici.

## Le problème, en une phrase

La donnée Eurio vivait dans une constellation de JSON éparpillés sans
synchronisation ni source de vérité imposée — un re-scrape corrigeait un
fichier sans se propager aux autres. Résultat concret : la commémo BE 2017
« université de Gand » portait l'ID Numista de Liège.

## Décision centrale — une base SQLite canonique

`ml/state/eurio.db` (ex-`training.db`, renommée car le nom était trompeur :
c'est le **dorsal de données** d'Eurio, pas seulement l'entraînement) devient
**la source de vérité unique**. Elle absorbe la constellation de JSON.

- Elle vit sur le **PC local** (heavy lifting : scrape, training, images).
- Elle est **plus portable** que les JSON épars : un seul fichier `.db` à
  copier vers une machine GPU. La contrainte de portabilité du kickoff est
  honorée, et mieux servie.
- `eurio_referential.json` ne disparaît pas mais **cesse d'être une vérité** :
  il devient un *export généré optionnel* (`SELECT … → JSON`).

### Ce qui reste fichier

- Les **snapshots de scrape bruts** (`ml/datasets/sources/*.html`) — provenance
  immuable, fichier par nature.
- Les **projections sortantes** : `catalog_snapshot.json`, le push Supabase.

### Ce qui se dissout en tables

| JSON aujourd'hui | Devient |
|---|---|
| `eurio_referential.json` | table `coins` **canonique** (plus un miroir) + tables filles, à la place du blob `raw_payload_json` |
| `coin_catalog.json` | table `numista_catalog` (scrape référentiel brut) |
| `numista_manual_resolutions.json`, `*_review_queue.json` | lignes d'arbitrage explicites |
| gold du bench (`discovery_bench/*.jsonl`) | tables |
| `experiment_cohorts.eurio_ids_json` (blob JSON dans une colonne) | table de jointure `cohort_members` |

## Identité — `eurio_id` prime

- **`eurio_id` = clé primaire de `coins`.** C'est l'identité qui prime :
  toute la donnée d'une pièce se retrouve depuis son `eurio_id`.
- **`numista_id` = colonne `UNIQUE`**, un attribut, pas le maître.
- Les FK rayonnent depuis `coins` : `source_images.target_eurio_id`,
  `image_assets.eurio_id`, `training_run_classes.class_id`, `cohort_members`…

## Deux natures de sources

| Nature | Rôle | Aujourd'hui | Demain |
|---|---|---|---|
| **Sources référentielles** | *dictent quelles pièces existent* | Numista (seul) | + BCE, etc. |
| **Sources d'enrichissement** | ajoutent images + prix à des pièces connues ; n'inventent jamais de pièce | eBay | + autres |

À nommer **génériquement** dans le code : « source référentielle », jamais
« source Numista ». Numista est l'implémentation du jour, pas le concept.

### Génération directe `numista_catalog → coins`

`coins` est **généré 1:1** depuis le catalogue de la source référentielle, sur
`numista_id`. Un `numista_id` = une entrée. **Le matcher flou
(`batch_match_numista.py`) est retiré** : il n'existait que parce que le
référentiel avait été bootstrappé depuis Wikipedia *puis* Numista raccroché
par-dessus. On inverse : la source référentielle génère, Wikipedia/BCE ne font
qu'enrichir des champs.

> **Cause racine BE 2017** : Numista a deux IDs distincts et stables (124813
> Gand, 108778 Liège). Le matcher flou a collé 108778 sur l'entrée Gand ;
> l'arbitrage humain `108778 → …-university-of-liege` a été *silencieusement
> ignoré* (`batch_match_numista.py:247`) car cet `eurio_id` n'existait pas — la
> couche d'arbitrage sait *pointer* vers de l'existant, pas *constater une
> création*. La génération directe supprime mécaniquement ce trou.

## Cycle de vie d'une pièce

Deux états, **par pièce** (`eurio_id`) :

```
referenced  ──►  trained
```

- **referenced** — existe dans la source référentielle. Connue.
- **trained** — le `design_group` de la pièce a été inclus dans un run
  d'entraînement réussi ; le modèle sait la reconnaître.

L'« éligibilité à une cohorte » (assez d'images pour entraîner) n'est **pas un
état** mais une **condition calculée** à la volée.

### L'état est calculé, mais matérialisé

La vérité de l'état est une **dérivation** (`trained` se lit depuis
`training_run_classes` en expansant `design_group → membres`). Mais on ne
recalcule pas à chaque lecture : on **matérialise** le résultat dans une
colonne `status` sur `coins`, recalculée par **une commande idempotente**
déclenchée sur **événement** (fin d'un run, sync). Lectures gratuites, écritures
rares et événementielles.

### La propagation n'est PAS conditionnée par l'état

L'app embarque **toutes** les pièces, même `referenced` non `trained` :
lorsqu'une pièce n'est pas reconnue par l'IA, l'app propose un sélecteur manuel
pour aider l'utilisateur à la trouver. Donc la propagation reste
**inconditionnelle et idempotente**. Le flag de cycle de vie est un **attribut**
que les consommateurs lisent (le scan : « IA attendue » vs « fallback
sélecteur » ; le sélecteur de cohorte : « éligible ou pas »), **pas une vanne**.

## Images — origines et augmentation

Sur `image_assets`, un champ `origin` :

| `origin` | Quoi |
|---|---|
| `canonical` | l'image de référence Numista |
| `collected` | photo scrapée (eBay & co), vraie photo terrain |
| `synthetic` | image canonique transformée (3D/2D, salissures, tilt, rotation) |

L'**augmentation n'est pas une origine** : c'est une *transformation* appliquée
au moment de bâtir le set d'entraînement — y compris par-dessus des images
`collected` pour en avoir davantage.

## Le tableau final

```
  sources référentielles (Numista API, demain BCE…)  ┐
  snapshots de scrape immuables  sources/*.html      ├─ ingestion ─┐
  sources d'enrichissement (eBay → blobs MinIO) ─────┘             ▼
                                                          ┌──────────────────┐
                                                          │   eurio.db       │  CANONIQUE
                                                          │   (PC local)     │  + DB de travail
                                                          └────────┬─────────┘
                                            projections descendantes, idempotentes
                                       ┌───────────────┼────────────────┐
                                       ▼               ▼                ▼
                                   Supabase     catalog_snapshot   export GPU = copie du .db
                                  (app prod)      (app offline)     (+ eurio_referential.json)
```

- **MinIO** (S3 sur VPS) stocke les blobs d'images ; `eurio.db` porte la ligne
  avec la clé/URL MinIO. Déjà le cas (`source_images.storage_path`).
- Les projections sont **strictement descendantes** : jamais de flux retour
  ad hoc. Une correction se fait dans `eurio.db`, puis on régénère.

## Migration d'identité (split / merge / rename)

Un `numista_id` est stable → un re-scrape ne peut **jamais** orpheliner. Un
*rename* ne touche que le slug cosmétique. Un *split* (Gand/Liège) = deux
entrées au lieu d'une, constatées automatiquement par la génération directe.
Les dérivés épinglés à un `eurio_id` (gold du bench, cohortes, embeddings)
rejouent un **journal de migration** au lieu de s'orpheliner en silence.

## Questions encore ouvertes

- **Versioning du canonique.** `eurio.db` est gitignoré (binaire 21 Mo). Les
  *décisions humaines* irremplaçables (overrides de split, arbitrages) doivent
  être versionnées — mécanisme à trancher (table exportée en JSON versionné ?
  journal de migration committé ?).
- **`eurio_id` dérivé** : slug cosmétique dérivé déterministe de
  `numista_id` + métadonnées, figé par une carte versionnée — forme exacte à
  spécifier au Chunk 1.
- **Schéma exact** des tables filles (observations, images, i18n, arbitrages) —
  Chunk 1.
