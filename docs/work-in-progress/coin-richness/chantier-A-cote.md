# Chantier A — Pipeline cote temporelle eBay

> Objectif : disposer d'une **série temporelle de cotation par pièce × grade**,
> consommable par l'admin (sparkline + moyenne 90j + tendance %) et l'app
> Android (à terme). Démarrer maintenant car chaque jour sans run = un point
> d'historique perdu.

## État des lieux (2026-05-25)

### Ce qui existe déjà ✅

- **Table** `coin_market_quotes` : p10/p50/p90 × condition × période × source
  (unique sur `source, eurio_id, period_start, condition_raw`)
- **Step pipeline** `ml/sources/_base/steps/price_aggregate.py` :
  - tourne à la fin de chaque run eBay (après `enqueue`)
  - filtre `listing_kind = 'single'` (exclut lots, coffrets, slabs)
  - dédup N images → 1 listing
  - agrège via `sources/pricing/aggregate.py` avec **pondération vélocité**
    (recency + sales/an) et clean outliers
  - écrit une ligne par (eurio_id, condition) par run
- **Mapping condition** : `listing_text_signals.condition_normalized` →
  grades **TB / TTB / UNC** (cohérent referential-v2, ≠ 2euros.org BE/BU/UNC)

### État réel de la donnée

```
coin_market_quotes : 42 lignes, 24 pièces, du 2026-05-20 au 2026-05-22
conditions présentes : TB (8), TTB (10), UNC (24)
runs eBay : 15 runs entre 2026-05-16 et 2026-05-22, aucun depuis 3 jours
```

→ **Pas de cron**. Les runs sont déclenchés manuellement. Couverture 24/524.

### Le vrai gap

| Bloc | État |
|---|---|
| Schéma | ✅ prêt |
| Logique d'agrégation | ✅ prête |
| Pipeline d'écriture | ✅ branché, qualité OK |
| **Cadence automatique** | ❌ aucun cron |
| **Buckets temporels propres** | ⚠️ `period_start = run.started_at`, donc buckets de forme aléatoire (un run = une période) |
| **Couverture** | ❌ 24/524 pièces |
| **Vues dérivées** (90j avg, tendance %) | ❌ |
| **Exposition admin** | ❌ pas de chart, pas d'historique affiché |

## Questions à trancher

### Q1 — Cadence

Trois options :

**(a) Daily cron** (1 run par jour)
- ➕ historique propre, point par jour
- ➕ tendance % calculable simplement
- ➖ ~524 coins × ratelimit eBay → faisable mais consommateur de quota
- ➖ certaines pièces rares n'ont aucune nouvelle annonce sur 24h (bruit)

**(b) Weekly cron** (1 run par semaine, bucket calendaire)
- ➕ chaque pièce a ~assez d'annonces nouvelles pour une stat significative
- ➕ économe en quota eBay
- ➖ tendance % moins fine
- ➖ user attend des numéros qui bougent

**(c) Sliding window 7j, refresh quotidien**
- A chaque run quotidien, on agrège les 7 derniers jours d'annonces collectées
- ➕ stable (moins bruyant), réactif (refresh tous les jours)
- ➖ logique d'agrégation à reprendre : aujourd'hui un run agrège **ses
  propres** listings ; là on agrégerait **tous les listings de la fenêtre**

**Proposition** : (c) sliding window. Aligné sur le comportement 2euros.org
("Prix moyen 90 jours"). Implique de découpler `period_start/period_end` du
`run.started_at/now` et de stocker une ligne par (eurio_id, condition, **date
de calcul**, **fenêtre**).

### Q2 — Granularité des buckets

Une fois (c) tranché : on garde **1 ligne par jour de calcul** (sliding 7j) ?
Ou on garde **un point par semaine calendaire** (lundi 00:00 → dimanche 23:59) ?

- Daily snapshot : 524 coins × 3 grades × 365 jours = **574k lignes/an**.
  SQLite encaisse sans souci. Sparkline lisse.
- Weekly snapshot : 524 × 3 × 52 = **82k lignes/an**. Plus économe, sparkline
  en escaliers.

**Proposition** : daily snapshot, sliding 7j. Quitte à downsampler à la
lecture si la sparkline le demande.

### Q3 — Rétention des annonces brutes (`pending_quotes` + `source_images`)

Si on change la formule d'agrégation (velocity weight tuning, outlier filter,
nouveau mapping condition), on veut **rejouer l'historique**.

- Garder `source_images` indéfiniment : coût = lignes SQLite + chemins MinIO
- Aujourd'hui : `pending_quotes` est promu, source_images conservé sans TTL
- Risque : volume MinIO en croissance non-bornée

**Proposition** : on garde 1 an glissant **complet** (toute l'annonce + image),
on garde **5 ans en métadonnées seules** (prix + condition + listing kind +
date) sans l'image. Permet rejeu agrégation sans coût MinIO infini.

### Q4 — Mapping condition eBay → grade Eurio

Aujourd'hui : `listing_text_signals.condition_normalized` produit TB/TTB/UNC.
2euros.org affiche **BE / BU / UNC** (qualités numismatiques officielles BCE).

Question : on **garde notre mapping interne TB/TTB/UNC** (referential-v2,
acté 2026-05-15) et on **expose une projection** vers BE/BU/UNC à
l'affichage ? Ou on aligne sur BE/BU/UNC partout ?

- Pour interne : TB/TTB/UNC est le langage du collectionneur (grading
  numismatique général)
- Pour BE/BU/UNC : strict euro-spécifique (Belle Épreuve, Brillant
  Universel, Uncirculated) — c'est la classification BCE officielle

**Proposition** : creuser dans une session dédiée — c'est un sujet
referential-v2, pas Chantier A. Pour A on prend tel quel ce qui sort de
`condition_normalized`.

### Q5 — Couverture

24/524 pièces ont une cote. Le bottleneck c'est la **discovery eBay** (pas
le pipeline cote). Cf. `project_discovery_groupee` — chunks 1-6 livrés.

Question : on attend que discovery couvre les 524 avant de lancer le cron,
ou on lance le cron sur les pièces déjà découvertes et on étoffe au fil ?

**Proposition** : on lance sur l'existant. Une pièce sans donnée affiche
"Pas encore de cotation". Vaut mieux 24 pièces avec history que 524 avec
zéro point.

### Q6 — Quotidien ou run unique journalier ?

Un cron quotidien = un `source_run` eBay par jour. Le run fait sa discovery
+ enrich + price_aggregate. Avec sliding 7j, le price_aggregate doit
**ignorer** la fenêtre du run et regarder les 7 derniers jours de
`source_images` (peu importe leur run d'origine).

→ Implique un step **séparé** `price_recompute` qui tourne en parallèle de
la discovery (ou en post-traitement quotidien indépendant).

**Proposition** : séparer. La discovery garde sa cadence propre (peut-être
plus lente). Le `price_recompute` tourne **chaque jour à heure fixe** et
agrège toutes les annonces vues les 7 derniers jours, indépendamment de
quand elles ont été découvertes.

## Schéma — changement proposé

Aujourd'hui :
```sql
UNIQUE (source, eurio_id, period_start, condition_raw)
period_start = run.started_at  -- forme du run
```

Proposé : ajouter une notion de **snapshot quotidien**.

```sql
ALTER TABLE coin_market_quotes
  ADD COLUMN snapshot_date TEXT;   -- 'YYYY-MM-DD' du jour de calcul
ALTER TABLE coin_market_quotes
  ADD COLUMN window_days INTEGER DEFAULT 7;

-- Nouveau unique (sans casser l'ancien chemin run-attached)
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmq_snapshot
  ON coin_market_quotes (source, eurio_id, snapshot_date, condition_raw)
  WHERE snapshot_date IS NOT NULL;
```

L'ancien chemin `price_aggregate` continue à écrire avec `snapshot_date = NULL`
(run-attached, audit). Le nouveau chemin `price_recompute` écrit avec
`snapshot_date = 'YYYY-MM-DD'` + `window_days = 7`.

**Question** : on garde les deux chemins en parallèle, ou on migre tout sur
snapshots et on supprime le run-attached ?
- Pour les deux : audit traçable par run + série temporelle indépendante
- Contre : duplication, complexité lecture

**Proposition** : **un seul chemin**, snapshot-based. Le `run_id` reste en
colonne (le run qui a *déclenché* le recompute), mais la clé d'unicité
devient `(source, eurio_id, snapshot_date, condition_raw)`. Plus simple,
plus lisible.

## Vues dérivées (côté lecture, pas de table)

```sql
-- Prix moyen 90j (vue inline)
SELECT eurio_id, condition_normalized,
       AVG(p50) AS avg_p50_90d,
       MAX(snapshot_date) AS last_snapshot
  FROM coin_market_quotes
 WHERE snapshot_date >= date('now', '-90 days')
 GROUP BY eurio_id, condition_normalized;

-- Tendance % (last 30d vs prev 60d)
WITH last30 AS (
  SELECT eurio_id, condition_normalized, AVG(p50) AS p
    FROM coin_market_quotes
   WHERE snapshot_date >= date('now', '-30 days')
   GROUP BY 1, 2
),
prev60 AS (
  SELECT eurio_id, condition_normalized, AVG(p50) AS p
    FROM coin_market_quotes
   WHERE snapshot_date >= date('now', '-90 days')
     AND snapshot_date <  date('now', '-30 days')
   GROUP BY 1, 2
)
SELECT l.eurio_id, l.condition_normalized,
       (l.p - p.p) / p.p AS trend_pct
  FROM last30 l JOIN prev60 p USING (eurio_id, condition_normalized);
```

→ pas de table, pas de cache. Si lent un jour, on caches dans
`coin_market_quotes_rollup` plus tard.

## Livrables proposés (à découper en chunks)

| # | Chunk | Effort | Sortie |
|---|---|---|---|
| A.1 | Migration schéma `snapshot_date` + `window_days` | ~30 min | Colonnes ajoutées, ancien chemin marqué deprecated |
| A.2 | Step `price_recompute` (sliding 7j) | ~2 h | Nouveau step, testable hors run |
| A.3 | Cron quotidien (`go-task ml:price-recompute`) | ~1 h | Tâche planifiée, log structuré |
| A.4 | Vues dérivées + endpoint API admin | ~2 h | `/api/coins/{id}/market` : history + 90j + tendance |
| A.5 | UI admin : sparkline + cards (90j, last, %) | ~3 h | Réutilisé dans Chantier E |
| A.6 | Backfill : convertir les 42 lignes run-attached existantes | ~30 min | Snapshots historiques (avec une asterisk "pre-cron") |

A.1-A.3 = **livre une série temporelle qui démarre demain**, indépendant du reste.
A.4-A.5 = exposition.
A.6 = bonus, pas bloquant.

## Décisions tranchées (2026-05-25)

| # | Question | Décision |
|---|---|---|
| Q1 | Cadence | **Weekly, bucket calendaire lundi 00:00 → dimanche 23:59** |
| Q2 | Granularité | Déduit Q1 : **1 point par semaine** (~52/an/pièce/grade) |
| Q3 | Rétention annonces | **1 an complet + 5 ans métadata** |
| Q4 | Mapping conditions | Renvoyé à referential-v2 (TB/TTB/UNC tel quel pour A) |
| Q5 | Couverture lancement | **Attendre discovery complète des 524** avant cron |
| Q6 | Schéma | **Snapshot-only**, ancien chemin run-attached migré |

### Implications

- **Q1 weekly** : `window_days = 7` calendaire. Le `price_recompute` tourne
  une fois par semaine (lundi matin) sur la semaine précédente complète.
  Volume estimé : 524 × 3 grades × 52 = **82k lignes/an**.
  - Sparkline en escaliers (~52 points/an sur 1 an d'historique).
  - Tendance % : last 4 semaines vs prev 8 semaines (≈ équivalent 30j/60j).
- **Q5 bloqué par discovery** : ⚠️ **Chantier A dépend de la complétion
  discovery groupée** (cf. `project_discovery_groupee`, chunks 1-6 livrés
  mais couverture actuelle 24/524). On **prépare le pipeline** (A.1-A.4)
  mais on **n'allume le cron** (A.5) qu'une fois discovery proche de 100 %.
  → Cf. section "Dépendance discovery" ci-dessous.
- **Q6 snapshot-only** : migration en une passe, suppression de l'écriture
  run-attached dans `price_aggregate`. `run_id` reste en colonne (audit :
  quel recompute a écrit cette ligne), unique key devient
  `(source, eurio_id, snapshot_date, condition_raw)`.

## Dépendance discovery (impact Q5)

Le cron ne s'allume **que quand** discovery a une couverture acceptable. À
définir avec un seuil concret :

- **Option strict** : 100 % des 524 ont ≥ 10 annonces sur 30j → délai
  potentiellement long (certaines pièces rares ne génèrent jamais 10 annonces/mois)
- **Option pragma** : 90 % des 524 ont ≥ 3 annonces sur 30j → seuil
  atteignable, on accepte que 10 % de pièces très rares affichent
  "estimation faible"

À trancher au moment de l'allumage, pas maintenant. **Action concrète** :
ajouter une **task "go/no-go cron cote"** au chantier discovery pour qu'il
nous notifie quand le seuil est franchi.

## Livrables — découpage révisé

| # | Chunk | Effort | Bloqué par discovery ? |
|---|---|---|---|
| A.1 | Migration schéma `snapshot_date` + `window_days` + nouvelle unique key | ~30 min | non |
| A.2 | Step `price_recompute` (weekly, calendaire) — calculable manuellement | ~2 h | non |
| A.3 | Backfill : convertir les 42 lignes run-attached existantes en snapshots hebdo | ~30 min | non |
| A.4 | Vues dérivées + endpoint API admin (`/api/coins/{id}/market`) | ~2 h | non |
| A.5 | Cron hebdo (`go-task ml:price-recompute-weekly`) | ~1 h | **OUI** — attendre seuil discovery |
| A.6 | UI admin : sparkline + cards (avg 4w/12w, last, tendance) | ~3 h | non (affiche les snapshots existants) |

A.1-A.4 + A.6 = **livrables immédiats**, indépendants de discovery. Permettent
de valider le pipeline + UI sur les 24 pièces déjà couvertes (mode manuel,
`go-task ml:price-recompute-weekly --once`).

A.5 (cron) = attend le go discovery.

## Note d'écart vs reco initiale

Mes recos étaient sliding 7j daily (Q1) et "lancer sur 24/524" (Q5). Décisions
finales = weekly + attendre discovery complète. Conséquences :

- **Sparkline plus pauvre** au début (1 point/semaine au lieu d'1/jour) →
  acceptable, on a 52 points/an, ça reste lisible
- **Délai d'allumage cron** dépendant de discovery → pas un blocage produit
  puisque tout l'outillage (pipeline + UI) sera prêt avant
- **Bénéfice** : stat plus robuste (volume hebdo > volume jour), moins de
  bruit sur pièces faible volume, moins de "estimation faible" affiché à
  l'utilisateur

## Risques

- **Quota eBay Browse** : ratelimit déjà tendu (cf. mémoire `reference_numista_ratelimit` côté Numista, mais eBay aussi). 524 × daily = volume. Le `price_recompute` **ne fait pas d'appel eBay** (il lit `source_images` déjà collecté) → safe. La discovery garde sa cadence à part.
- **Bruit sur faible volume** : pièce avec 1 annonce sur 7j → p10/p50/p90 dégénérés. Marquer `sample_size < 3` comme "estimation faible".
- **Stationnarité** : marché euro commémo bouge peu sur semaines/mois (sauf events) → tendance % souvent ~0. Pas un bug, un fait.
