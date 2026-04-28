---
title: Gestion temporelle — sources
date: 2026-04-26
status: draft
---

# Gestion temporelle

C'est le sujet le plus dense de la page `/sources`. La temporalité a **trois
niveaux** distincts, qui se prêtent chacun à un signal UI différent.

## Niveau 1 — Cadence de fetch ("quand a-t-on fetché pour la dernière fois ?")

Question : *"il s'est passé combien de temps depuis le dernier passage sur
chaque source ?"*

### Source de vérité

| Source | Marker | Calcul |
|---|---|---|
| Numista | `ml/state/sources_runs.json` (à créer) | `last_run_at` mis à jour à chaque run de `enrich_from_numista`, `batch_match_numista`, `batch_fetch_images` |
| eBay | `ml/datasets/sources/ebay_{date}.json` mtime | `MAX(mtime)` du dossier filtré sur `ebay_*.json` |
| LMDLP / MdP / BCE / Wikipedia | `ml/datasets/sources/{source}_{date}.{json,html}` mtime | idem |

Pourquoi un marker JSON pour Numista et pas pour les autres : Numista n'écrit
pas un snapshot par run (il enrichit `eurio_referential.json` directement,
champ par champ). Le seul moyen propre d'avoir un timestamp "dernière fois
qu'on est passé par cette source" est d'écrire un marker à la fin de chaque
script. Pour les autres, le snapshot daté est déjà la trace.

### Format `sources_runs.json`

```json
{
  "numista": {
    "last_run_at": "2026-04-26T14:32:11Z",
    "last_run_kind": "batch_match",
    "last_run_calls": 87,
    "last_run_added_coins": 3
  },
  "ebay": { ... },
  "lmdlp": { ... }
}
```

`last_run_kind` distingue les usages de Numista (match vs enrichissement vs
images), parce que les cadences attendues ne sont pas les mêmes (voir
"Cadence recommandée" plus bas).

### Cadence recommandée par source

| Source | Cadence | Justification |
|---|---|---|
| Numista (match nouvelles pièces) | **À chaque sortie commémorative** | Déclenchement manuel quand Raphaël découvre une sortie. La page indique "X jours depuis le dernier match" pour rappeler |
| Numista (enrichissement) | Mensuelle | Métadonnées stables, pas urgent |
| Numista (images) | Idem | Idem |
| eBay | **Mensuelle** | Marché actif évolue lentement, et le quota est "respectable" (~500-1000 calls/run) |
| LMDLP / MdP | Trimestrielle | Cotation collectionneur stable |
| BCE | À chaque nouveau commémo (rare) | Annonces officielles |
| Wikipedia | Annuelle | Backfill paresseux |

L'UI affiche ces cadences comme des **seuils** : le badge devient `⚠ overdue`
si on dépasse 1.5× la cadence cible.

## Niveau 2 — Détection nouvelles pièces ("la source a-t-elle changé ?")

Question : *"depuis le dernier run, est-ce qu'on a vu apparaître de nouvelles
pièces dans cette source ?"*

C'est ici que le **delta** devient un outil produit, pas juste un dashboard.
Quand Raphaël lance le script de match Numista, l'admin doit lui montrer :

> Numista — run 2026-04-26  
> **+3 nouvelles pièces détectées** (vs 2026-04-13)  
>   • DE-2026-30e-anniversaire-traité-élysée  
>   • IT-2026-bicentenaire-victor-emmanuel  
>   • LV-2026-jeux-olympiques

Et symétriquement : si le run trouve 0 nouvelle pièce alors qu'on sait qu'une
sortie est annoncée → signal que la source ne l'a pas encore indexée, ou que
notre query ne la matche pas.

### Implémentation

**Pour Numista** : on a déjà l'identifiant canonique (`cross_refs.numista_id`).
Le delta est trivial :

```python
nids_before = {c.cross_refs.numista_id for c in coins if c.cross_refs.numista_id}
# run du script
nids_after = {c.cross_refs.numista_id for c in coins if c.cross_refs.numista_id}
added_nids = nids_after - nids_before
```

On stocke le résultat dans `sources_runs.json` (`last_run_added_coins`).

**Pour eBay** : pas pertinent au sens "nouvelle pièce", parce qu'eBay ne
définit pas le périmètre — c'est `eurio_referential` qui dit quelles pièces
existent. Le delta utile pour eBay est niveau 3 (évolution prix).

**Pour BCE** : delta sur la liste des commémos annoncées par année. Le scrape
existe déjà par année, on compare deux snapshots `bce_comm_2026_<date>.html`
parsés.

**Pour LMDLP / MdP** : delta sur la liste des `eurio_id` couverts par le
snapshot. Si un nouveau commémo apparaît dans LMDLP avant qu'on l'ait dans le
référentiel → signal fort.

### Affichage UI

Dans la carte `/sources` de chaque source, sous "dernier fetch" :

```
Numista · API
✅ healthy · quota 1247/1800 (mensuel)
Dernier fetch: il y a 13 jours (2026-04-13)
└─ +3 pièces détectées · 2 enrichies · 1 en review
```

Le clic sur le delta ouvre la liste détaillée (modal ou panneau latéral V1.5).

## Niveau 3 — Évolution des prix ("le marché a-t-il bougé ?")

Question : *"sur les pièces qu'on suit déjà, comment les prix ont-ils évolué
entre les deux derniers runs ?"*

### Pourquoi c'est critique

Côté **admin /sources** : c'est la validation que le scrape eBay fonctionne.
Si on relance et que tous les prix bougent de ±0.5% → cohérent avec le marché
réel. Si tout bouge de ±50% ou si 80% des pièces passent à `null` → bug ou
changement d'API.

Côté **app Android (V2 produit)** : c'est la fonctionnalité produit. Quand
l'utilisateur scanne sa pièce, on lui montre la cote actuelle ET son
évolution :

```
2€ Allemagne · Traité de l'Élysée (2013)
Cote actuelle: P50 5.90€  (P25 4.20€ — P75 8.50€)
   ▁▂▃▅▅▆▇   +12% sur 6 mois
```

Cette sparkline tire directement sur `coin_market_prices` (table INSERT-only,
une ligne par run).

### Métriques de delta (admin)

Pour chaque run eBay, on calcule sur l'échantillon **stable** (pièces présentes
dans les deux runs) :

| Métrique | Formule | Affichage |
|---|---|---|
| `n_stable` | pièces présentes dans run N et N-1 | "112 pièces stables" |
| `n_new` | pièces enrichies pour la 1ère fois | "+4 nouvelles cotes" |
| `n_dropped` | pièces enrichies en N-1, plus en N | "−1 perdue" (signal de bruit) |
| `delta_p50_median` | médiane de `(p50_N - p50_N-1) / p50_N-1` | "+1.2% prix médian" |
| `delta_p50_p10` / `delta_p50_p90` | percentiles 10/90 du delta | indicateur de dispersion |

Si `delta_p50_median` > 10% en valeur absolue, badge `⚠ swing important` —
généralement signal d'un changement d'algorithme ou d'un échantillon trop
petit.

### Stockage : snapshot mensuel local pré-calculé (pas de query Supabase live)

**Décision :** on ne fait **aucun call Supabase** pour calculer le delta
côté admin. Raphaël tourne sur Supabase free tier ; un poll 10s qui fait des
queries Supabase pour 500 coins = risque de cramer le quota egress.

À la place, chaque run `scrape_ebay.py` écrit, en plus de l'INSERT Supabase
habituel, un **snapshot local mensuel** :

```
ml/state/price_snapshots/
  ebay_2026-03.json        ← snapshot du run de mars
  ebay_2026-04.json        ← snapshot du run d'avril (le dernier)
```

Format `ebay_YYYY-MM.json` :

```json
{
  "source": "ebay",
  "period": "2026-04",
  "fetched_at": "2026-04-26T14:32:11Z",
  "coins": {
    "fr-2015-70e-anniversaire-paix":  { "p25": 4.20, "p50": 5.90, "p75": 8.50, "samples": 18 },
    "de-2013-traite-elysee":           { "p25": 3.80, "p50": 5.10, "p75": 7.20, "samples": 22 },
    ...
  }
}
```

Convention `period` :
- Si plusieurs runs eBay tombent dans le même mois civil, on **écrase** le
  snapshot du mois (idempotent : le dernier run du mois gagne)
- Le snapshot Supabase `coin_market_prices` reste lui INSERT-only — aucune
  perte de granularité côté app

Le delta affiché par `/sources/status` = comparaison entre les 2 derniers
fichiers `ml/state/price_snapshots/ebay_*.json` (par ex. `2026-03` vs `2026-04`).
Lecture filesystem, ~10ms, **zéro call Supabase**.

### Granularité historique

Pour la sparkline app Android, `coin_market_prices` Supabase conserve
**toute** l'historique (INSERT-only). Pas de purge — chaque run = une ligne
par coin enrichi. Volume estimé : 500 coins × 12 runs/an × ~5 ans = 30 000
lignes max, négligeable.

Pour la page admin, on n'affiche que **delta entre les 2 derniers snapshots
mensuels locaux**. Les graphes long-terme par coin restent côté app, qui lit
directement Supabase.

### Symétrie avec les autres sources

Le pattern `ml/state/price_snapshots/{source}_{period}.json` est généralisable
si on ajoute d'autres sources de prix plus tard (LMDLP cotation, MdP). Pour
l'instant seul eBay produit des prix, donc seul eBay écrit dans ce dossier.

## Niveau 4 (bonus) — Heartbeat "j'attends une nouvelle pièce"

Cas d'usage que Raphaël a mentionné : il découvre à la main qu'une nouvelle
commémo sort (réseau social, annonce BCE, hasard). Il veut un endroit dans
l'admin qui lui dit *immédiatement* : "ok, lance `numista:match` pour la
chercher".

Implémentation : dans la carte Numista, un encart "Match récent" :

```
Numista — Match nouvelles pièces
Dernier match: il y a 13 jours
[ Lancer la commande →  go-task ml:numista-match ]   ← copy-to-clipboard
```

Le bouton ne lance pas le script (V1 lecture seule), il copie la commande à
coller dans un terminal. Le bouton "Fetch" V2 prendra sa place.

## Schéma de l'API exposée

L'endpoint `GET /sources/status` (voir `backend.md`) retourne, pour chaque
source :

```json
{
  "id": "ebay",
  "type": "api",
  "quota": { ... },
  "temporal": {
    "last_run_at": "2026-04-26T14:32:11Z",
    "days_since_last_run": 0,
    "expected_cadence_days": 30,
    "overdue": false,
    "delta": {
      "n_stable": 112,
      "n_new": 4,
      "n_dropped": 1,
      "delta_p50_median_pct": 1.2,
      "delta_p50_p10_pct": -8.4,
      "delta_p50_p90_pct": 12.7,
      "swing_warning": false
    }
  },
  "coverage": { "enriched": 116, "total": 517 }
}
```

Pour les sources sans delta de prix (Numista, LMDLP, MdP, BCE), `delta` ne
contient que `n_new` / `n_dropped` (sur la couverture de pièces).
