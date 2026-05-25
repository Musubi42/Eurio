# Chantier D — Métadonnées éditoriales

> Objectif : remplir les champs `designer / graveur / release_date /
> tranche A-B / JOUE` sur les ~500 commémos, afin que la page détail admin
> (et l'app à terme) soit aussi complète que 2euros.org sur ces axes.

## État des lieux (2026-05-25)

### Ce qu'on a déjà

| Champ | Stockage actuel | Couverture |
|---|---|---|
| `coins.year` | INTEGER | 688/688 ✅ |
| `coins.design_description` | TEXT | partiel |
| `coin_observations(legacy_import)` payloads divers | semi-structuré | wiki 2628, lmdlp 278+, ebay 116, bce-mintage non extrait |
| `coin_cross_refs` | typé `(ref_type, ref_value)` | wikipedia_url 2628, lmdlp_url 278, bce_comm_url 41, **joue_code 0** |
| BCE adapter `issuing_date` | **collecté** mais non persisté | ~493 pièces scrapées |
| Numista scrape | composition/diameter/weight/obverse_desc/reverse_desc | 683/688 |

### Les vrais gaps

| Champ | État | Source disponible |
|---|---|---|
| **release_date** (jour précis) | ❌ jamais persisté | BCE `issuing_date` ✅ déjà scrapé, juste à brancher |
| **JOUE code** (ex. `C2010/012/05`) | ❌ aucun en DB | Numista API (full `/coins/{id}`) ou scrape EUR-Lex |
| **Designer** (Bodo Broschat…) | ❌ aucun en DB | Numista API (`designers` array dans full coin) |
| **Graveur** (souvent ≠ designer) | ❌ aucun en DB | Numista API idem |
| **Tranche A / B** | ❌ aucun en DB | Manuel, ~10 pièces DE 2007-2008 |

## Questions à trancher

### Q1 — Colonnes typées vs `coin_observations` ?

Trois patterns possibles sur la table `coins` :

**(a) Colonnes typées first-class**
```sql
ALTER TABLE coins ADD COLUMN release_date TEXT;        -- ISO YYYY-MM-DD
ALTER TABLE coins ADD COLUMN edge_variant TEXT;        -- 'A' | 'B' | NULL
-- designer/engraver : table fille (multi)
```
- ➕ filtrable, sortable, lisible dans n'importe quel client SQL
- ➕ contraintes possibles (CHECK, format)
- ➖ explosion potentielle si on en ajoute 10 (mais on en a 4 ici)

**(b) Tout dans `coin_observations`** (statu quo)
- ➕ zéro migration, additif
- ➖ pour filtrer "pièces 2007 avec tranche A", il faut un JSON1 query lourd
- ➖ pas de contrainte de format

**(c) Mix : colonnes typées pour les filtrables, observations pour le reste**
- `release_date`, `edge_variant` → colonnes
- `designer`, `engraver` → table fille (multi-valeurs)
- JOUE → déjà prévu en `cross_refs(ref_type='joue_code')`

**Proposition** : **(c)**. `release_date` mérite une colonne (sort/filter sur
page admin). `edge_variant` mérite une colonne (filtrable, contrainte CHECK).
Designer/graveur en table fille (une pièce peut avoir 2 designers, 1 graveur,
ou inversement). JOUE déjà couvert par `cross_refs`.

### Q2 — Schéma `designer` / `engraver` ?

Numista expose un array `designers` avec `name` et `role` (designer | engraver |
sculptor). On modélise :

```sql
CREATE TABLE coin_credits (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('designer','engraver','sculptor')),
  name       TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'numista',
  position   INTEGER NOT NULL DEFAULT 0,    -- ordre d'affichage
  PRIMARY KEY (eurio_id, role, name)
);
CREATE INDEX idx_coin_credits_name ON coin_credits(name);
```

- ➕ multi-rôles, multi-personnes
- ➕ index sur `name` pour requête inverse ("toutes les pièces de Luc Luycx")
- ➖ table de plus

**Question** : on garde cette structure ou on simplifie en `coin_observations` ?
**Proposition** : table dédiée. Requête inverse "pièces de X" est utile UX et
ne se fait pas raisonnablement sur JSON.

### Q3 — JOUE : code seul ou texte complet ?

2euros.org affiche juste le **code** `C2010/012/05` avec lien vers EUR-Lex. Le
texte officiel JOUE décrit le design en termes juridiques (utile pour audit
"image vs description officielle").

**Option a** : code seul dans `cross_refs(ref_type='joue_code', ref_value='C2010/012/05')`
**Option b** : code + texte complet dans `coin_observations(observation_type='joue_official', payload={code, text, url})`

**Proposition** : **(a) pour démarrer** (code + URL EUR-Lex calculable depuis le code).
Texte complet = nice-to-have, on l'ajoutera si on en a usage (validation
description vs design). Pas la peine de scraper 500 PDF JOUE pour rien.

### Q4 — `release_date` : précision et fallback ?

BCE expose la **date exacte d'émission** (ex. 29/01/2010). Mais pour les
pièces circulation (non-commémo) → seulement l'année.

**Proposition** :
- `release_date TEXT` ISO format `YYYY-MM-DD` quand connu
- `release_date_precision TEXT CHECK (precision IN ('day','month','year'))` →
  permet d'afficher "29 janvier 2010" vs "janvier 2010" vs "2010"
- `release_date` NULL pour les pièces circulation (year suffit déjà via
  `coins.year`)

Alternative plus simple : juste `release_date TEXT NULL`, format flexible
(YYYY, YYYY-MM, YYYY-MM-DD). ISO 8601 partial dates → SQLite gère sans souci.
Pas de colonne precision séparée.

**Proposition** : ISO partial dates, sans colonne precision dédiée. Simple,
suffisant.

### Q5 — Tranche A/B : où ?

C'est un attribut de **variant** au sens numismatique (deux moules d'edge
différents pour la même pièce). Concerne ~10 commémos DE 2007-2008.

Trois options :
- **(a)** colonne `coins.edge_variant TEXT` → mais alors une pièce = une ligne,
  donc on perd l'info qu'**une même pièce a été frappée avec les deux**
- **(b)** table `coin_edge_variants(eurio_id, variant CHECK IN ('A','B'), mintage, notes)` →
  modèle propre, on peut avoir 2 lignes pour la même pièce
- **(c)** dans `coin_observations(observation_type='edge_variant')` → semi-structuré

**Proposition** : **(b) table dédiée**, alignée sur referential-v2 (qui prévoit
des Variants). Petit volume, schéma propre. Si referential-v2 livre une
table `coin_variants` plus générale, on migrera dedans.

### Q6 — Bootstrap source

| Champ | Source primaire | Coût | Source backup |
|---|---|---|---|
| release_date | BCE (déjà scrapé) | 0 | Numista API |
| JOUE code | Numista API `/coins/{id}` | ~500 calls Numista | scrape EUR-Lex par année |
| Designer / Engraver | Numista API idem | mutualisé avec JOUE | aucun |
| Edge variant A/B | curation manuelle (~10 pièces) | 30 min humain | wikipedia |

**Numista API rate limit** : mémoire `reference_numista_ratelimit` = ~2000
calls/mois free plan. 500 commémos = 25 % de notre budget mensuel pour
récupérer designer + JOUE en un coup. Acceptable si on le fait **une fois**
et qu'on stocke tout.

**Proposition** :
- D.1 : brancher `issuing_date` BCE → `release_date` (gratuit, immédiat)
- D.2 : run Numista API one-shot pour designer + JOUE sur les 500 commémos (~500 calls)
- D.3 : curation manuelle A/B (admin sait quelles pièces — DE 2007/2008 mémorial Rome + DE 2008 Hambourg + AT 2007 ToR)

### Q7 — Multilingue ?

Designer names = invariant ("Luc Luycx", "Bodo Broschat") → pas i18n.
JOUE = code invariant. Edge variant = lettre.
**`release_date_precision` "month" → label "janvier"** dépend de la langue UI
→ formaté côté admin/app, pas stocké.

Conclusion : pas de besoin i18n sur ces champs. ✅

## Schéma proposé — synthèse

```sql
-- Migration additive
ALTER TABLE coins ADD COLUMN release_date TEXT;       -- ISO partial: YYYY|YYYY-MM|YYYY-MM-DD

CREATE TABLE IF NOT EXISTS coin_credits (
  eurio_id TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  role     TEXT NOT NULL CHECK (role IN ('designer','engraver','sculptor')),
  name     TEXT NOT NULL,
  source   TEXT NOT NULL DEFAULT 'numista',
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (eurio_id, role, name)
);
CREATE INDEX idx_coin_credits_name ON coin_credits(name);

CREATE TABLE IF NOT EXISTS coin_edge_variants (
  eurio_id TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  variant  TEXT NOT NULL CHECK (variant IN ('A','B')),
  mintage  INTEGER,
  notes    TEXT,
  PRIMARY KEY (eurio_id, variant)
);

-- JOUE : utilise cross_refs existant
-- INSERT INTO coin_cross_refs(eurio_id, ref_type, ref_value)
--   VALUES ('de-2010-2eu-breme', 'joue_code', 'C2010/012/05');
```

## Livrables — découpage

| # | Chunk | Effort | Bloqué par |
|---|---|---|---|
| D.1 | Migration schéma (3 changements additifs) | ~30 min | rien |
| D.2 | Brancher BCE `issuing_date` → `coins.release_date` + backfill ~493 pièces | ~1 h | D.1 |
| D.3 | Script `bootstrap_numista_credits.py` — pull `/coins/{id}` × 500, parse designers + JOUE, insert | ~3 h | D.1, quota Numista |
| D.4 | Curation manuelle edge A/B (~10 pièces, UI ou seed JSON) | ~30 min | D.1 |
| D.5 | Endpoint API admin : enrichir réponse `/api/coins/{id}` avec credits + edge + release | ~1 h | D.1-D.4 |
| D.6 | UI admin : bloc "Détails" sur page coin (designer, gravure, JOUE link, release date, edge) | ~2 h | D.5 |

D.1 + D.2 + D.4 + D.5 + D.6 = **livrable complet sans Numista API** (release
date + edge variant + JOUE manuel pour les pièces emblématiques).

D.3 = run one-shot, peut tourner en background pendant qu'on fait D.5/D.6.

## ⚠️ Révision 2026-05-25 (post-Chantier C — doctrine SQLite-only + provenance first-class)

Une décision structurelle prise en Chantier C **modifie** ce qui avait été
tranché ici :

- **`coins.release_date` typé → ANNULÉ.** Remplacé par
  `coin_observations(observation_type='release_date', source=...)` pour
  capturer **BCE et Numista en parallèle** sans masquer la divergence.
- **`coin_credits.source` passe en PK** (avant : default 'numista'). Deux
  sources peuvent attribuer un rôle à des personnes différentes — on garde
  les deux lignes, on ne tranche pas silencieusement.
- **JOUE dans `cross_refs`** : tient toujours, déjà source-aware
  (`ref_type='joue_code'` + provenance implicite par le script qui insère).
- **`coin_edge_variants`** : tient. Petit volume, source unique (curation
  manuelle) suffit.

Cf. `chantier-C-mintage.md` §"Pattern : identity + observations par source".

## Décisions tranchées (2026-05-25)

| # | Question | Décision |
|---|---|---|
| Q1 | Stockage | **Mix typé + table fille** : `release_date` typé sur `coins`, `edge_variant` en table dédiée, credits en table fille, JOUE dans `cross_refs` |
| Q2 | Credits | **Table dédiée `coin_credits`** (multi-rôles, index sur `name` pour requête inverse) |
| Q3 | JOUE | **Code seul** dans `cross_refs(ref_type='joue_code')`, URL EUR-Lex calculée à l'affichage |
| Q4 | release_date | **ISO partial dates** (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`), pas de colonne `precision` séparée |
| Q5 | Edge variant | **Table dédiée `coin_edge_variants`** (PK composite, 1 pièce peut avoir A+B) |
| Q6 | Ordre chunks | **D.1 → D.2 → (D.3 ‖ D.4) → D.5 → D.6** |
| Q7 | Quota Numista | ✅ **500 calls one-shot autorisés** (25 % du quota mensuel free tier) |

## Risques

- **Numista API gracieuse mais ratelimit dur** : 500 calls / 2000 mensuel =
  25 %. Si on doit re-run (bug parsing), on double. Mitigation : cache local
  des payloads JSON full (comme on fait déjà pour BCE HTML snapshots).
- **Designers manquants chez Numista** : certaines pièces très récentes ou
  obscures n'ont pas l'info. Champ restera NULL — c'est OK.
- **JOUE pas systématique** : certaines pièces 2004-2006 n'ont pas de JOUE
  (Allemagne a publié rétroactivement). Marquage `NULL` acceptable.
- **Tranche A/B mal documentée** : pour quelques pièces, la répartition
  exacte des ateliers entre A et B est sujette à débat. On capture ce qu'on
  trouve, on marque source.
