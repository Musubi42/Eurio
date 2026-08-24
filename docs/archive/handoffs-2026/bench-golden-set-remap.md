# Remapping du golden set de bench — par preuve visuelle

> Mesuré et tranché le **2026-08-17**. Chaque ligne de la table finale a été
> établie **en regardant la photo**, jamais par ressemblance de chaînes. Deux
> lignes sur onze contredisent ce que le nom de dossier laissait croire — c'est
> la raison d'être de la règle.

## Le constat, chiffré

`ml/datasets/eval_real_norm/` porte **30 dossiers / 180 photos**. Confrontés au
référentiel vivant (`coins.eurio_id` ∪ `coins.design_group_id`) :

| | dossiers | photos |
|---|---|---|
| slug vivant | 16 | 96 |
| **slug mort** | **14** | **84** (47 %) |

### La duplication est bien plus large que « trois paires »

⚠️ **Correction du 2026-08-18.** Une première lecture n'avait comparé que les
dossiers morts *entre eux* (3 paires). En comparant chaque mort à sa **cible
vivante**, le sha256 par fichier donne tout autre chose :

```
30 dossiers · 180 fichiers  →  19 contenus DISTINCTS · 114 photos
8 contenus existent sous plusieurs slugs (3 d'entre eux sous TROIS slugs) :
   at-2002-2eur-standard == at-2002-2eur-standard-1st-map == at-2eur-standard-2002
   be-2007-2eur-standard == be-2007-…-albert-ii-…-1st-portrait == be-2eur-standard-2007
   es-1999-2eur-standard == es-1999-…-juan-carlos-i-1st-type-1st-map == es-2eur-standard-1999
   be-2011-…-100th-international-womens-day == be-2011-…-1st-centenary-…
   es-2016-…-old-town-…                     == es-2016-…-old-city-…
   fr-2016-…-100th-anniversary-…            == fr-2016-…-100-years-since-…
   it-2016-…-2200th-anniversary-…           == it-2016-…-2200-years-since-…
   it-2016-…-550th-anniversary-…            == it-2016-…-550-years-since-…
```

**Conséquence sur toutes les mesures de bench passées :** le golden set annoncé
à 180 photos en porte **114**, et **huit pièces y sont comptées deux ou trois
fois**. Un R@1 mesuré dessus est pondéré par la duplication, pas par le corpus.

Le plan de réconciliation est donc **11 fusions + 3 renommages**, pas
« 84 photos à déplacer ». Seules trois cibles n'existent pas encore :
`mt-2008-2eur-standard-2nd-map`, `fr-1999-2eur-standard-1st-map`, et le
représentant belge — soit **18 photos** de contenu réellement non couvert par un
slug vivant.

## D'où vient le nom de dossier (et pourquoi il ment)

`ml/vision/sync_eval_real.py` nomme le dossier de sortie d'après l'**`eurio_id`
que l'appareil Android portait au moment de la capture**, résolu à travers
`class_manifest.json` s'il existe :

```
<debug_pull>/eurio_debug/eval_real/<eurio_id>/<step>_raw.jpg
      →  ml/datasets/eval_real_norm/<class_id ou eurio_id>/
```

Le nom est donc un instantané du catalogue de l'APK de l'époque, pas une vérité
de référentiel. Il peut mentir **sur le millésime** — et il ment deux fois.

⚠️ **`go-task ml:eval-real:sync` embarque `--clear` en dur** (`ml/tasks.yml:50`).
Le relancer sur un seul `debug_pull/` **efface les 96 photos saines** des autres
captures. Les sources sont toujours là (`debug_pull/`, 7 dossiers), donc rien
n'est irrécupérable — mais ce n'est pas une commande à lancer pour « rafraîchir ».

## La table, établie à l'œil

| Dossier mort | Ce que la photo montre | Cible (`eurio_id`) | Classe (`design_group`) |
|---|---|---|---|
| `at-2002-2eur-standard` | Bertha von Suttner | `at-2002-2eur-standard-1st-map` | `at-2euro-standard-t1` |
| `at-2eur-standard-2002` | ⟵ **capture identique** | idem | idem |
| `be-2007-2eur-standard` | Albert II, 1ᵉʳ portrait, **2007** | `be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait` | `be-2euro-albert-ii-t1` |
| `be-2eur-standard-2007` | ⟵ **capture identique** | idem | idem |
| `es-1999-2eur-standard` | Juan Carlos I, ESPAÑA, **2002** | `es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map` | `es-2euro-juan-carlos-i-t1` |
| `es-2eur-standard-1999` | ⟵ **capture identique** | idem | idem |
| `be-2011-…-womens-day` | deux visages, BE, **2011** | `be-2011-2eur-100th-international-womens-day` | idem (pur renommage) |
| `es-2016-…-old-city-of-segovia…` | aqueduc, ESPAÑA 2016 | `es-2016-2eur-old-town-of-segovia-and-its-aqueduct` | idem (`city`→`town`) |
| `fr-2016-…-100-years-since-the-birth…` | portrait Mitterrand | `fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand` | idem |
| `it-2016-…-2200-years-since-the-death…` | masques, **PLAUTO** | `it-2016-2eur-2200th-anniversary-of-the-death-of-plautus` | idem |
| `it-2016-…-550-years-since-the-death…` | **DONATELLO** | `it-2016-2eur-550th-anniversary-of-the-death-of-donatello` | idem |
| `mt-2008-2eur-standard` | croix de Malte | `mt-2008-2eur-standard-2nd-map` | `mt-2euro-standard-t1` |
| 🔴 `fr-2eur-standard-2007` | arbre RF, **daté 2000** | **`fr-1999-2eur-standard-1st-map`** | `fr-2euro-standard-t1` |
| 🔴 `be-2008-2eur-standard` | Albert II, **2ᵉ portrait, daté 2011** | ⚠️ aucun membre exact — voir ci-dessous | `be-2euro-albert-ii-t2` |

### Les deux lignes où la ressemblance de chaînes se serait trompée

**`fr-2eur-standard-2007` porte une pièce de 2000.** Le nom appelle
`fr-2007-2eur-standard-2nd-map` ; la photo (lisible sur `close_plain` et
`daylight_plain`) montre l'arbre de vie daté **2000**, donc la **1ʳᵉ carte**.
La bonne cible est `fr-1999-2eur-standard-1st-map`. Les deux sont dans le même
`design_group` (`fr-2euro-standard-t1`), donc l'erreur serait restée invisible à
l'évaluation par classe — et fausse dès qu'on évalue à la pièce.

**`be-2008-2eur-standard` porte une pièce de 2011.** 2ᵉ portrait, marques
d'atelier, millésime **2011** net sur `close_plain`. Le référentiel n'a
**aucune** pièce belge entre 2010 et 2013 : le groupe `be-2euro-albert-ii-t2`
s'arrête à ses membres 2008 et 2009. La capture est donc rattachable à la
**classe** mais à aucune **pièce** — c'est un trou de référentiel, pas une
erreur de remapping. À trancher : rattacher au représentant 2008 du groupe, ou
créer la pièce manquante.

## Où consigner ce remapping — la table existe déjà

⛔ **Ce n'est pas `coin_aliases`.** Cette table (69 lignes, colonnes
`lang`/`alias`/`source`/`confidence`) est du **vocabulaire de marché** pour le
theme-matcher eBay. Y écrire des renommages de slug la détournerait.

✅ **C'est `eurio_id_migrations`** (`ml/state/schema.sql:1177`), conçue
exactement pour ça :

```sql
kind        ∈ rename | split | merge | retire
resolution  ∈ deterministic | needs_rematch
status      ∈ pending | applied
old_eurio_id, new_eurio_id, batch_id, reason, decided_by
```

Elle porte **3 lignes** au canonique (le split belge de 2017, batch
`be-2017-split-9281d080`) et elle est classée **patrimoine** par
`wipe_referential.py` — donc jamais effacée. Seul `generate_missing_coins.py`
y écrit aujourd'hui ; il n'existe pas encore de chemin pour y consigner un
renommage décidé à la main.

Les onze lignes ci-dessus s'y écrivent en `kind='rename'`,
`resolution='deterministic'`, `decided_by='preuve-visuelle-2026-08-17'`, et un
`batch_id` unique. Les deux lignes 🔴 méritent `reason` explicite : le nom de
dossier contredisait la photo.

## L'outil existe — `ml/scripts/remap_bench_golden_set.py`

Écrit le 2026-08-18, **`--dry-run` par défaut**, `--apply` obligatoire pour
écrire, `--scope all|fs|journal`, `--emit-sql`. 18 tests, vérifiés en échec sur
le code d'avant.

Ce qu'il garantit :

- **Plan calculé avant toute écriture** ; `merge` seulement si **tous** les
  sha256 par fichier concordent, sinon `RemapRefused` sur **tout** le run — pas
  seulement la ligne fautive.
- **Idempotent** sur `(batch_id, old, new)`, avec un `batch_id` **stable**
  (`bench-golden-remap-2026-08-17`) : un uuid par exécution ne reconnaîtrait pas
  son propre batch au rejeu.
- **14 lignes de journal pour 11 cibles.** Les 14 slugs morts sont 14
  identifiants distincts ; n'en journaliser que 11 laisserait
  `at-2eur-standard-2002`, `be-2eur-standard-2007` et `es-2eur-standard-1999`
  irrésolubles pour qui les rencontrerait plus tard.

### Le cas belge, tranché

Rattachement au représentant 2ᵉ portrait du groupe
(`be-2008-…-2nd-type-2nd-portrait`), mais en **`resolution='needs_rematch'`** et
non `deterministic` : la ligne est vraie **à la classe**, fausse **à la pièce**
(la photo est datée 2011, le référentiel n'a rien entre 2010 et 2013). Un drapeau
`class_level_only` permet à un bench par pièce de l'exclure plutôt que de compter
une fausse réussite. Le bloc s'affiche à chaque exécution, dry-run compris.

## Où l'écriture bute, et ce qu'on fait en attendant

`eurio_id_migrations` vit au **canonique**, et **aucune route `/ingest/*` ne
l'expose** — vérifié sur l'OpenAPI du VPS (13 routes, aucune pour les migrations
d'identité). Le script **refuse** d'écrire le journal (exit 2) plutôt que de le
déposer dans la réplique, que rien ne resynchronise — c'est le silence exact que
décrit `eurio-data-writes`.

Deux chemins :

- **court** — `--emit-sql <fichier>` produit un SQL rejouable
  (`INSERT … WHERE NOT EXISTS`), à appliquer sur `eurio.db` du VPS ;
- **propre** — ouvrir `POST /ingest/eurio-id-migrations` +
  `client.ingest.push_eurio_id_migrations`, sur le modèle de
  `push_referential_fix`.

Le `--scope fs` (renommage des dossiers) n'a **aucune** de ces contraintes :
disque local, applicable immédiatement. **Il n'a pas été lancé.**

## Ce qui reste à faire

1. Lancer `--scope fs --apply` (local, réversible via `debug_pull/`).
2. Choisir le chemin d'écriture du journal (SQL sur le VPS, ou la route
   `/ingest/*` manquante).
3. **Re-mesurer un benchmark** — et republier les chiffres : les R@1 passés
   portent sur 114 photos réelles, pas 180, avec 8 pièces surpondérées.
4. Trancher le sort de la pièce belge 2011 au référentiel (la créer, ou assumer
   le rattachement à la classe).
