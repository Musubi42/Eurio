---
title: Stratégie prix de marché eBay
date: 2026-04-26
status: actif
---

# Stratégie prix de marché eBay

## Ce qu'on peut faire (et ce qu'on ne peut pas)

### API disponible : Browse API (application token, pas de compte user)

Le client OAuth2 dans `market/ebay_client.py` utilise `client_credentials` — ce qui
donne accès aux **annonces actives** (Buy It Now en cours sur EBAY_FR), pas aux
ventes conclues.

### Ce qu'on ne peut PAS récupérer sans upgrade

| Données | API requise | Accessible ? |
|---|---|---|
| Prix de ventes conclues | Marketplace Insights API | ❌ Payant / partenaire eBay |
| Historique sold listings | Browse API `?filter=buyingOptions:{AUCTION}` + completed | ❌ Non exposé côté public |
| Prix auction réalisés | Commerce API | ❌ Seller only |

**Conséquence** : nos P25/P50/P75 représentent le **marché actif** (prix demandés),
pas les prix réellement payés. C'est une approximation suffisante pour notre cas
d'usage (indiquer à l'utilisateur si sa pièce vaut ~2€ ou ~15€), mais pas un
historique de transactions réelles.

---

## Modèle d'observation

### La date canonique = `fetched_at` (moment du fetch), pas la date d'annonce

`itemOriginDate` (date de publication de l'annonce sur eBay) est une propriété
individuelle de chaque listing, déjà utilisée dans le calcul de velocity weighting
(`listing_weight()` dans `market/scrape_ebay.py`). Elle ne sert pas de date
d'observation de marché.

**Pourquoi `fetched_at` :**

- Chaque run mensuel = un snapshot du marché actif à ce moment-là
- Comparable dans le temps : run du 26 avril 2026, run du 26 mai 2026, etc.
- Sémantique claire : "le 26 avril 2026, le marché actif EBAY_FR montrait P50=5.90€
  pour fr-2015-70e-anniversaire-paix"
- C'est ce qu'on construit : une série temporelle d'*observations de marché*,
  pas un registre de transactions

### Schéma Supabase

Table `coin_market_prices` — une ligne par observation, **on insère toujours**
(jamais d'upsert écrasant) pour conserver l'historique complet :

```sql
coin_market_prices (
  id               bigserial PRIMARY KEY,
  eurio_id         text        NOT NULL,  -- FK coins(eurio_id)
  source           text        NOT NULL,  -- 'ebay'
  p25              numeric(8,2),
  p50              numeric(8,2),
  p75              numeric(8,2),
  samples_count    int,
  with_sales_count int,
  query_used       text,
  fetched_at       timestamptz NOT NULL DEFAULT now()
)
```

L'admin lit la ligne la plus récente via `DISTINCT ON (eurio_id, source) ORDER BY fetched_at DESC`.

---

## Scope

- **Inclus** : commémoratives 2€, `is_commemorative=true, face_value=2.0`
- **Exclus** : pièces de circulation (valeur faciale ≈ prix marché, pas d'intérêt)
- **Exclus pour l'instant** : joint-issues `country='eu'` (query cross-country plus complexe)
- **Pays par défaut** : FR, DE, IT, ES, GR — environ 300 commémoratives
- **Full run** : ~500 commémoratives × ~3 calls = ~1500 calls eBay (quota 5000/jour)

## Budget eBay — données empiriques

| Run | Date | Calls consommés | Pièces ciblées | Enrichies |
|---|---|---|---|---|
| 1 (test) | 2026-04-13 | 30 | 30 | 30 |
| 2 (full commemos avec numista_id) | 2026-04-26 | 127 | 127 | 116 |

**Ratio observé :** ~1 call/pièce en moyenne (certaines déclenchent une expansion de groupe → 2-3 calls).  
**Capacité restante après run 2 :** ~4 870 calls sur 5 000/jour.  
**Run full (~500 commemos) :** estimation ~500–1 000 calls = 10–20% du quota journalier.

Rapport du premier run : `docs/research/phase-2c4-ebay-run.md`.

## Quota tracking

**Numista** — déjà instrumenté dans `ml/referential/numista_keys.py` :
- `_MONTHLY_LIMIT = 1800` (soft limit conservative, quota API réel ~2000/mois)
- `KeyManager.quota_status()` retourne `calls_this_month`, `remaining`, `exhausted` par clé
- Stocké en SQLite (`ml/state/training.db`, table `numista_key_usage`)

**eBay** — pas encore instrumenté :
- `EbayClient.call_count` est un compteur en mémoire par run, non persisté
- Pour du suivi inter-runs, il faudra une table SQLite similaire à `numista_key_usage`
- Alternative : interroger l'eBay Analytics API (`getRateLimits`) — mais ajoute une dépendance

---

## Filtres anti-bruit (voir `market/scrape_ebay.py`)

- Regex NOISE_PATTERNS : lots, coffrets, proof, BU, argent/or, colorisée, rouleaux
- Prix < 0.8× valeur faciale → rejeté (below_face)
- Prix > 500× valeur faciale → rejeté (above_extreme)
- Devise non-EUR → rejeté

## Velocity weighting

Chaque listing est pondéré par `log(1 + ventes_par_an) × trust_vendeur`.
Pondère les vendeurs actifs et fiables. Les listings sans historique de vente
contribuent quand même (floor weight = 0.05) pour ne pas biaiser vers les
nouveaux vendeurs uniquement.
