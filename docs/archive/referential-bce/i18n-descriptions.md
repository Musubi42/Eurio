# Axe i18n — titres + descriptions officiels BCE (24 langues UE)

> Chantier BCE, axe 4 (descriptions multilingues). Livré 2026-05-29.
> Voir aussi `kickoff.md` (vue d'ensemble) et la mémoire `project_bce_pipeline`.

## Objectif

La BCE publie chaque pièce commémorative dans les **24 langues officielles de
l'UE** (`comm_{year}.{lang}.html`), avec un **titre** (Feature) et une
**description** traduits par la BCE elle-même. On les récolte dans la table
`coin_descriptions_i18n` pour alimenter l'i18n des fiches commémoratives.

Hors périmètre de cet axe : le **tirage** (issuing volume) et la **date
d'émission** (lang-invariants) — ils ont leurs propres axes et ne sont **pas**
écrits par ce harvester.

## Schéma (`coin_descriptions_i18n`)

`schema.sql` — 1 row par `(eurio_id, source, lang)` :

| Colonne | Note |
|---|---|
| `eurio_id` | FK coins, ON DELETE CASCADE |
| `source` | registry id (`bce_official`) |
| `lang` | CHECK sur les **24 langues UE** (bg…sv) |
| `title` | titre officiel BCE (NOT NULL) |
| `description` | description officielle (nullable) |
| `method` / `model` / `confidence` | `scrape` / NULL / `canon` |
| `fetched_at` | datetime |

Différences avec les tables i18n existantes :
- `coin_names_i18n` = titres **Numista**, 6 langues app, 1 row/(eurio_id,lang).
- `coin_topics` = topic court multi-source, 6 langues, sans description.
- `coin_descriptions_i18n` = source **officielle BCE**, **24 langues**, garde
  **titre + description appariés** (la BCE les fournit ensemble par langue).

## Parser language-agnostic (le point dur)

Les labels diffèrent dans les 24 langues (« Feature » / « Dessin commémoratif »
/ « Anlass der Ausgabe »…) et **le séparateur n'est pas fiable** : `:` (EN/FR),
`.` (letton « Apraksts. »), ou **aucun** (maltais « Volum tal-ħruġ 2 miljun »).
Un parser « 1 champ = 1 `<p>` par position » casse aussi car **les descriptions
s'étalent parfois sur plusieurs `<p>`** (ex. France 2017 ruban rose).

Signal fiable retenu : **chaque champ est `<p><strong>Label…</strong> valeur</p>`**.
Les `<strong>` balisent les labels dans toutes les langues. Un `<p>` sans
`<strong>` en tête = continuation de la description.

Stratégie (`referential/scrape_bce_images.py`) :

1. **EN = langue d'ancrage.** `parse_bce_page` identifie les champs par leur
   **label anglais** (fiable même quand un champ de tête manque — ex. 2e coin
   LU 2023 sans `Feature`, correctement sauté). Chaque coin porte `_block_index`
   (position document, stable inter-langues) et `_field_order` (ordre des champs
   détectés). Le matching `eurio_id` réutilise `BceAdapter._match_entry` (même
   logique que le pipeline images → cohérence).
2. **23 autres langues = mapping par position.** `parse_bce_lang_blocks` rend
   `{block_index: [valeurs positionnelles]}` ; le harvester les mappe au
   `_field_order` EN du même bloc. **Garde-fou** : si le nombre de valeurs ≠ au
   nombre de champs EN, le coin est **sauté pour cette langue et journalisé**
   (pas de fallback silencieux — doctrine trust model).

Non-régression validée : sur les snapshots EN existants, le nouveau parser est
un **sur-ensemble strict** de l'ancien (0 coin perdu/ajouté, descriptions
multi-paragraphes désormais complètes).

## Lancer

```bash
go-task ml:scrape-bce-i18n                       # 2004→année-1, 24 langues
go-task ml:scrape-bce-i18n -- --year 2007        # une année
go-task ml:scrape-bce-i18n -- --langs fr,de,it   # sous-ensemble de langues
go-task ml:scrape-bce-i18n -- --dry-run          # sans écriture DB
```

Idempotent (UPSERT par clé). Snapshots HTML cachés par (année, langue, jour)
sous `ml/datasets/sources/bce_comm_{year}_{lang}_{date}.html` → re-run instantané
le même jour. BCE = scrap gratuit, rate limit poli 1,1 req/s.

## Matcher : assignation 1-to-1 par (country, year)

Le matcher `BceAdapter` décidait pièce par pièce sans savoir qu'un eurio_id
était déjà pris → **sur-matching** : dans une (country, year) à 2 pièces, la 2e
(libellé BCE éloigné de son slug) volait l'eurio_id de la 1re. Corrigé via
`BceAdapter.match_group` (partagé avec le pipeline images) :

- groupe à **1 bloc** → comportement historique (`_assign_one` : override → floor → gap) ;
- groupe à **≥2 blocs** → overrides forcés, puis **assignation optimale** (score
  total max, force brute sur ces petits groupes), chaque appariement ≥ plancher.
  Un greedy se trompe (ES 2014 : « Change of the Head of State » score un poil
  plus haut sur Park Güell que la vraie pièce UNESCO) ; l'optimal récupère le bon.

6 `MANUAL_BCE_OVERRIDES` ajoutés pour les 2es pièces dont le bon eurio_id est
sous le plancher (sans quoi elles restent non-matchées) : LU 2012 William IV,
ES 2014 King accession, LT/EE 2018 joint balte, AD 2021 elderly, MT 2024 Citadel.

## Stats du run initial (2026-05-29)

Années 2004–2025 (22), 24 langues :

- **11 345 rows**, **474 eurio_id** distincts × 24 langues, **0 collision**.
- **11 334 avec description**, **11 titre-seul** (page non-EN omet la
  description → jamais le volume à la place ; cf. règle d'alignement).
- **1 lang-année sautée** : `bg/2022` (23 blocs ≠ 30 EN — page bulgare divergente).
- **2 rows sautées sans titre** : PT 2021 Tokyo, bloc vide dans `da`+`mt` seulement.
- **0 description suspecte** (post-check : aucune ne ressemble à un volume/date).

Effet de bord positif du fix matcher : **+41 coins** correctement matchés (rejetés
à tort par l'ancien gap-guard comme « ambigus » alors qu'ils sont 2 pièces
distinctes), non-matchés **59 → 19**. Bénéficie aussi au pipeline images.

### Divergences restantes (notées, hors périmètre)

- **EE 2020 « Tartu Peace Treaty »** : pièce réelle **absente du référentiel**
  (gap). Reste non-matchée tant que le coin n'est pas ajouté.
- **19 coins EN non matchés** : limite connue du matcher slug (zero-canon).

## Reste à faire

- Front : afficher la description BCE localisée sur la fiche commémo (la galerie
  d'images Numista+BCE est déjà branchée).
- Axes **tirage** + **date d'émission** (facts lang-invariants, scrape EN unique).
- Coins sans titre BCE (ex. LU 2023 #2) : non représentés ici (titre NOT NULL) —
  décision assumée.
