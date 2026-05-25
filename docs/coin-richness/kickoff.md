# Coin Richness — kickoff

> Objectif produit : que la page détail d'une pièce dans l'admin (puis l'app)
> soit **au moins aussi riche que 2euros.org**, avec en plus un **indice de
> rareté dérivé** (pas éditorial), une **cote temporelle** (history, pas juste
> snapshot), et une **provenance tracée** par source.
>
> Référence inspiration : https://www.2euros.org/2-euros-commemoratives-allemagne/allemagne-presidence-de-breme-au-bundesrat/

## Pourquoi ce dossier existe

2euros.org expose une fiche très complète (cote 3 grades + 90j + tendance,
mintage par atelier × qualité, designer, JOUE, rareté 1-10, tranche A/B).
Après inspection (cf. session 2026-05-25) :

- ils utilisent la **même source que nous** (eBay Browse, annonces à prix fixe)
  → pas besoin de scraper leur snapshot, on a déjà la matière première
- **l'historique n'est pas exposé** côté client : ils stockent en interne, on
  doit construire le nôtre dès maintenant (la valeur ne vient qu'avec le temps)
- côté schéma, on a **déjà 80% de la structure** (`coin_market_quotes`,
  `coin_observations`, `coin_cross_refs`, `coin_canonical_images`, i18n) mais
  **0% du pipeline d'écriture régulier** ni des **vues dérivées**

## Chantiers existants à connecter (ne pas dupliquer)

| Existant | Périmètre | Lien avec coin-richness |
|---|---|---|
| `docs/research/referential-v2.md` | Modèle Type/Variant/MintRelease, grading UNC/TTB/TB (acté 2026-05-15) | Le mintage × atelier × qualité tombe dans MintRelease — on **consomme**, on ne re-modélise pas |
| `docs/phases/phase-2c8-enrichment-admin.md` | Enrichissement BCE/Numista, mintage, filtres `/coins` | Couvre l'enrichissement éditorial (description, mintage agrégé) — on **étend** vers le détail riche |
| `docs/data-harmonization/` | `eurio.db` source canonique | Cadre infrastructurel, on s'y inscrit |

## Mapping 2euros.org ↔ Eurio (synthèse)

| 2euros.org affiche | Notre table | État | Action |
|---|---|---|---|
| Prix UNC / BU / BE snapshot | `coin_market_quotes` (p10/p50/p90 × condition) | ✅ schéma OK | Vérifier remplissage des 3 tiers |
| Prix moyen 90j | `coin_market_quotes` (period) | ✅ schéma | Vue dérivée à exposer |
| Dernier prix + date | `pending_quotes` / `coin_market_quotes` | ✅ | Vue dérivée |
| Tendance % vs 90j | (dérivé) | ⚠️ | Vue calculée, pas de table |
| Sample size | `coin_market_quotes.sample_size` | ✅ | OK |
| Mintage total | `coins.mintage` | ✅ | OK |
| Mintage × atelier × qualité | ❌ | **Manque** | Cf. Chantier C — via MintRelease (referential-v2) |
| Designer / graveur | `coin_observations` (non typé) | ⚠️ | Cf. Chantier D — typer ou normaliser |
| Date d'émission précise | `coins.year` (INTEGER) | ⚠️ | Cf. Chantier D — ajouter `release_date` |
| JOUE ref (C2010/012/05) | `coin_cross_refs(ref_type='joue_code')` | ✅ | Bootstrap |
| Tranche A / B | ❌ | **Manque** | Cf. Chantier D — observation typée |
| Indice de rareté 5/10 | ❌ | **Manque** | Cf. Chantier B — **dérivé**, pas stocké |
| Image obverse/reverse | `coin_canonical_images` | ✅ | OK |
| Pays / année / type | `coins` | ✅ | OK |
| Titre i18n | `coin_names_i18n` 6 langues | ✅ (mieux qu'eux) | OK |

## Chantiers identifiés (à arbitrer)

### A. Pipeline cote temporelle eBay
**Le seul qui a besoin du temps qui passe pour avoir de la valeur** → à
démarrer en premier même si tout n'est pas tranché côté UX.

- Schéma : `coin_market_quotes` déjà prêt (p10/p50/p90 × condition × période)
- Manque : un **run périodique** (cron eBay Browse) qui écrit une ligne par
  (eurio_id, condition, période) à cadence régulière
- Période : quotidienne ? hebdo ? bucket fixe (semaine glissante) vs sliding ?
- Conditions : on a déjà le mapping `condition_raw` → `condition_normalized`
  mais qualité du mapping eBay → grades est bruité (annonces ≠ ventes certifiées)
- Question ouverte : on conserve les **annonces individuelles** (`pending_quotes`)
  combien de temps ? Source primaire pour recalculer history a posteriori si
  on change la formule d'agrégation.

### B. Indice de rareté dérivé
**Pas une colonne, une vue.** Reproductible, défendable, qui bouge avec le
marché.

- Signal disponible : `coins.mintage`, `coin_market_quotes.p50`,
  `coin_market_quotes.sample_size` (proxy volume), ancienneté
- Formule à discuter : log-mintage normalisé × log-prix médian × log-volume,
  borné [0..10] ? Quantiles sur le corpus complet ?
- Question : un score **par grade** (UNC rare ≠ BU rare) ou un score unique ?
- Cadence de recalcul : à chaque run cote ? quotidien ? sur lecture (vue) ?

### C. Mintage par atelier × qualité
Concerne surtout DE (5 ateliers A/D/F/G/J), FR (Pessac), IT (R), ES (M), AT.

- Vit naturellement dans **MintRelease** (referential-v2). À confirmer que le
  modèle prévoit bien `(MintRelease, quality) → count`.
- Source : Numista `/coins/{id}` expose `issuers` + `mintage_details` (à
  vérifier sur free tier — cf. memoire `reference_numista_ratelimit`)
- Backup source : BCE pour le total annuel, sans atelier
- Question : on bloque sur referential-v2 (MintRelease impl) ou on
  bootstrappe une table additive `coin_mintage_breakdown` en attendant ?

### D. Métadonnées éditoriales manquantes
Designer, graveur, date d'émission précise, tranche A/B, JOUE.

- Pattern : `coin_observations(observation_type=…, payload=…)` existe déjà,
  semi-structuré volontaire
- Arbitrage : on **type** (colonne `designer TEXT`, `release_date DATE`) ou
  on **normalise** via `observations` avec types reconnus ?
  - Pour : `release_date` mérite une colonne (filtrable, sortable)
  - Contre : explosion de colonnes faiblement remplies (designer pas pour
    pièces circulation)
- Source : Numista (designer, JOUE en cross-ref), BCE (date émission précise),
  scrape EUR-Lex (texte JOUE complet)

### E. Panel admin riche
Refondre la page détail pièce dans `admin/packages/web/.../coins/` pour
**afficher tout ce qu'on a** + signaler ce qui manque.

- Composants nouveaux : chart cote (sparkline + détail), table mintage
  breakdown, bloc designer/JOUE, bloc rareté avec explainability ("rareté 7/10
  parce que mintage 50k + p50 UNC = 80€ + volume eBay 12/an")
- Frontend-design skill applicable (admin Vue, R1 exempté)
- Question : on attaque ça en parallèle de A-D, ou on attend que la donnée
  soit là pour ne pas designer dans le vide ?

## Ordre de bataille proposé

1. **A en premier** (pipeline cote) — time-sensitive, schéma prêt, livrable
   en ~1-2 chunks
2. **D en deuxième** (métadonnées éditoriales bootstrap depuis Numista/BCE) —
   one-shot, indépendant
3. **C** (mintage breakdown) — dépend de l'avancement referential-v2,
   parallélisable
4. **B** (rareté dérivée) — nécessite A+C remplis pour avoir un signal
5. **E** (admin UI) — à attaquer dès que A produit la première courbe, étoffé
   au fur et à mesure

## Questions ouvertes — à trancher en discussion

1. Cadence pipeline cote : quotidien fixe vs sliding window 7j ?
2. On garde `pending_quotes` combien de temps ? (rejouabilité vs volume)
3. Rareté : score unique ou par grade ?
4. Métadonnées éditoriales : colonnes typées ou observations ?
5. MintRelease : on attend referential-v2 ou table additive en attendant ?
6. Admin UI : design avant ou après data ?

## Ce qu'on a en plus que 2euros.org (à garder visible)

- `design_groups` — émissions communes regroupées
- i18n 6 langues (vs FR/EN chez eux)
- Provenance/trust model par source (`confirmed/bce_only/numista_only/joue_only/manual`)
- Embeddings ArcFace (scan)
