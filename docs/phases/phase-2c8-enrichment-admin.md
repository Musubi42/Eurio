# Phase 2C.8 — Enrichissement multi-sources + panel admin

> **Objectif** : brancher les données BCE (images, descriptions, mintage) sur Supabase, enrichir `coins.mintage` depuis BCE et Numista, étendre le schéma `coin_market_prices` pour accueillir LMDLP avec qualité, et refondre les filtres de la page `/coins` avec sources + pays cumulables.
>
> **Prérequis** : Phase 2C.7 (sync Supabase canonique) terminée. Le scraper BCE a déjà tourné : 449 pièces ont `observations.bce_comm` dans le référentiel JSON.
>
> **Dernier run BCE** : 2026-04-26 · 493 pièces parsées · 449 enrichies · stages {2: 256, 3: 199, 5: 38}

---

## Contexte de session

En session du 2026-04-26, les sujets suivants ont émergé d'une revue du scraper BCE :

1. La donnée BCE est de très haute qualité — description officielle du design, image haute résolution, feature (thème officiel), volume d'émission.
2. Numista reprend vraisemblablement ses descriptions depuis la BCE → descriptions souvent identiques dans les deux sources.
3. Le champ `coins.mintage` est nul pour toutes les pièces malgré les données disponibles (BCE + Numista).
4. `coin_market_prices` n'accueille que eBay — LMDLP doit devenir une seconde source de prix, avec notion de qualité numismatique.
5. La page `/coins` a des filtres basiques ; il faut des filtres cumulables par source et par pays.

---

## 2C.8.1 — URL BCE dans `cross_refs`

**Effort** : ~20 min · `ml/referential/scrape_bce_images.py`

Le scraper ne stocke pas l'URL de la page BCE dans `cross_refs`, ce qui empêche d'afficher un bouton "BCE" dans les références externes de la page admin.

### À faire

Dans `enrich_entry_with_image()`, ajouter :
```python
bce_year_url = f"https://www.ecb.europa.eu/euro/coins/comm/html/comm_{coin['year']}.en.html"
entry["cross_refs"]["bce_comm_url"] = bce_year_url
```

**Limite connue** : URL au niveau de l'année, pas d'ancre par pièce (les pages BCE n'ont pas d'ancres individuelles).

**Re-run** : relancer `go-task ml:scrape-bce` pour rétropeupler les 449 entrées existantes.

**Admin** : dans `CoinDetailPage.vue`, le champ `refs.bce_comm_url` est déjà couvert par `crossRefLinks` si on ajoute le cas :
```ts
if (refs.bce_comm_url) links.push({ label: 'BCE', url: refs.bce_comm_url })
```

---

## 2C.8.2 — Sync `bce_comm` → Supabase `source_observations`

**Effort** : ~30 min · `ml/export/sync_to_supabase.py`

Les données `observations.bce_comm` existent dans le référentiel JSON mais ne sont pas remontées dans Supabase. Sans ce sync, rien n'est visible côté admin.

### À faire dans `referential_to_observations_rows()`

Ajouter le cas `bce_comm` en suivant le même pattern que `wikipedia` :

```python
bce_comm = obs.get("bce_comm")
if isinstance(bce_comm, dict):
    rows.append({
        "eurio_id": eurio_id,
        "source": "bce_comm",
        "source_native_id": None,
        "observation_type": "coin_info",
        "payload": bce_comm,
        # payload contient : image_url, feature, description,
        #                     issuing_volume, issuing_date, fetched_at
    })
```

**Relancer** `go-task ml:sync-supabase` (ou équivalent) après la modification.

---

## 2C.8.3 — Mintage : BCE + Numista → `coins.mintage`

**Effort** : ~1h · `ml/export/sync_to_supabase.py` + `ml/referential/enrich_from_numista.py`

La colonne `coins.mintage` (`number | null`) est nulle sur toutes les pièces. Deux sources ont la donnée.

### Source BCE (parsing string → integer)

`observations.bce_comm.issuing_volume` = `"1 million coins"` (string libre).

Parser dans `referential_to_coins_rows()` (ou équivalent dans sync) :

```python
import re

def parse_bce_mintage(issuing_volume: str | None) -> int | None:
    if not issuing_volume:
        return None
    s = issuing_volume.lower().replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(million|billion)?", s)
    if not m:
        return None
    val = float(m.group(1))
    if m.group(2) == "million":
        val *= 1_000_000
    elif m.group(2) == "billion":
        val *= 1_000_000_000
    return int(val)
```

**Règle de merge** : Numista (valeur entière directe) prime sur BCE (parsé) car plus précise. Ne pas écraser une valeur Numista existante avec un BCE approché.

### Source Numista

`enrich_from_numista.py` ne fetche pas actuellement le mintage depuis l'API Numista (champ `mintage` exposé par le endpoint `/type/{id}`). À ajouter dans la boucle d'enrichissement.

**Note** : le rate limit Numista (2000 calls/mois, épuisé en avril 2026) implique de faire ce fetch lors des runs planifiés habituels, pas en standalone.

---

## 2C.8.4 — Images BCE → Supabase Storage

**Effort** : ~2h · nouveau script `ml/referential/fetch_bce_images.py`

Les images BCE sont à 540px — qualité officielle, ne pas redimensionner. Uploader telles quelles dans Supabase Storage.

### Comportement attendu

```
Pour chaque entrée avec observations.bce_comm.image_url
  et sans images.obverse existant :
  1. GET image_url (ecb.europa.eu JPG)
  2. Upload vers Supabase Storage :
     bucket  : coin-images
     path    : {eurio_id}/obverse_bce.jpg    (JPG natif, 540px)
  3. Écrire entry["images"]["obverse"] = public_cdn_url
  4. Écrire entry["images"]["obverse_source"] = "bce_comm"
  5. Patch coins.images dans Supabase
```

**Ne pas** écraser une image `obverse` Numista déjà présente (Numista prime sur BCE comme source d'image).

**Pas de thumbnail** : pas de downscale, pas de `obverse_thumb`. La BCE n'expose que l'avers — pas de revers à attendre.

**Tâche go-task** à créer :
```yaml
fetch-bce-images:
  desc: "Download + upload BCE coin images for entries without obverse"
  cmds:
    - "{{.VENV}}/python referential/fetch_bce_images.py {{.CLI_ARGS}}"
```

---

## 2C.8.5 — `coin_market_prices` : LMDLP comme seconde source

**Effort** : ~1h · migration Supabase + `ml/export/sync_to_supabase.py` + admin

### Migration Supabase

Ajouter une colonne `quality` à la table `coin_market_prices` :

```sql
ALTER TABLE coin_market_prices
  ADD COLUMN quality text;
-- Valeurs LMDLP observées : 'UNC', 'BU FDC', 'BE Proof', 'BE Polissage inversé'
-- Null pour les entrées eBay (qualité non fetchée pour l'instant)
```

### Schema LMDLP dans `coin_market_prices`

Contrairement à eBay (P25/P50/P75 sur plusieurs ventes), LMDLP expose des prix catalogue par ligne :

| colonne | valeur LMDLP |
|---|---|
| `source` | `'lmdlp'` |
| `quality` | `'UNC'` / `'BU FDC'` / `'BE Proof'` / `'BE Polissage inversé'` |
| `p50` | prix catalogue LMDLP (une seule valeur → mettre en p50) |
| `p25`, `p75` | `null` (pas de distribution sur une seule observation) |
| `samples_count` | `1` |
| `in_stock` | booléen depuis `lmdlp_variants.in_stock` |

**Clé d'upsert** : `(eurio_id, source, quality)` — une ligne par pièce × qualité.

### Sync depuis le référentiel

Dans `sync_to_supabase.py`, ajouter une fonction `referential_to_market_prices_rows()` qui itère sur `observations.lmdlp_variants` et produit des lignes `coin_market_prices`.

### Affichage admin

Dans `CoinDetailPage.vue`, afficher LMDLP dans une section séparée de eBay — ne jamais fusionner les deux. Exemple de layout :

```
Prix de marché eBay       Prix catalogue LMDLP
P25 / P50 / P75           UNC      : 28 €
30 annonces analysées     BU FDC   : 45 €
                          BE Proof : 89 €
```

---

## 2C.8.6 — Filtres cumulables sur `/coins`

**Effort** : ~2h · `admin/packages/web/src/features/coins/pages/CoinsPage.vue` + requête Supabase

### Filtres par source de données

Chaque filtre "source" correspond à l'existence d'une ligne dans `source_observations` pour `eurio_id` :

| Filtre | Condition Supabase |
|---|---|
| Numista | `cross_refs->>'numista_id' IS NOT NULL` |
| BCE | entrée `source = 'bce_comm'` dans `source_observations` |
| Wikipedia | entrée `source = 'wikipedia'` dans `source_observations` |
| LMDLP | entrée `source = 'lmdlp'` dans `source_observations` |
| eBay | entrée dans `coin_market_prices` avec `source = 'ebay'` |
| Image | `images->>'obverse' IS NOT NULL` |

Les filtres sont **cumulables** (AND) et indépendants — aucun n'est exclusif.

### Filtre par pays

Multi-select sur la colonne `coins.country` (ISO2 : `FR`, `DE`, `IT`, `ES`, `BE`, ...).

Implémenter comme une liste de checkboxes ou pills dans la sidebar / toolbar. Cumulable avec les filtres sources.

### Implémentation suggérée

Côté Vue : un objet `filters` réactif avec `sources: Set<string>`, `countries: Set<string>`, `hasImage: boolean | null`. Construire dynamiquement la query Supabase en ajoutant les clauses `.eq()`, `.in()`, `.not()` selon ce qui est activé.

Pour les filtres source qui nécessitent un JOIN sur `source_observations` :
```ts
// Exemple : filtrer les coins qui ont BCE
.in('eurio_id',
  supabase.from('source_observations')
    .select('eurio_id')
    .eq('source', 'bce_comm')
)
```
Ou via une vue Supabase matérialisée `coins_sources` si les performances posent problème sur 2 600+ rows (probablement pas nécessaire).

---

## Ordre d'exécution recommandé

```
2C.8.1  URL BCE cross_refs      → trivial, 20 min, unblock le bouton admin
2C.8.2  Sync bce_comm → Supabase → socle, sans ça rien n'est visible
2C.8.5  Migration + LMDLP       → schema change Supabase à faire tôt
2C.8.4  Images BCE              → download pipeline, indépendant
2C.8.3  Mintage BCE + Numista   → enrichissement colonnes, indépendant
2C.8.6  Filtres CoinsPage       → front-only, dernier
```

## Gotchas

- **Ne pas downscaler les images BCE** : déjà à 540px, qualité suffisante, pas de traitement.
- **Numista mintage prime sur BCE** : ne pas écraser une valeur précise avec une approximation parsée.
- **LMDLP et eBay ne fusionnent jamais** : deux sections distinctes dans l'UI, deux sources dans `coin_market_prices`.
- **Filtre BCE sur `/coins`** passe par `source_observations`, pas directement sur `coins` — prévoir le join ou une vue.
- **`bce_comm_url` est une URL par année** : ne pas documenter comme un lien direct vers la pièce, juste vers la page de l'année.
- **Re-run du scraper BCE nécessaire** après 2C.8.1 pour rétropeupler les `bce_comm_url` dans le référentiel JSON.
