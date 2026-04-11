# Phase 3 — Le Coffre & Valorisation

> Objectif : l'utilisateur peut ajouter des pièces scannées à sa collection, voir la valeur de son portefeuille, consulter les prix de marché et l'historique.

---

## 3.1 — Stockage local (Room)

### Entités Room

```kotlin
@Entity(tableName = "user_coins")
data class UserCoinEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val numistaId: Int,
    val name: String,
    val country: String,
    val year: Int?,
    val faceValue: Double,
    val type: String,          // "circulation" | "commemorative"
    val rarity: String?,       // "common" | "uncommon" | "rare" | "very_rare"
    val scanImagePath: String?, // Photo prise par l'utilisateur
    val addedAt: Long = System.currentTimeMillis(),
    val valueAtAddition: Double?,
    val currentValue: Double?
)

@Entity(tableName = "cached_prices")
data class CachedPriceEntity(
    @PrimaryKey val numistaId: Int,
    val priceMedian: Double?,
    val priceP25: Double?,
    val priceP75: Double?,
    val source: String,
    val updatedAt: Long
)
```

### DAO

```kotlin
@Dao
interface UserCoinDao {
    @Query("SELECT * FROM user_coins ORDER BY addedAt DESC")
    fun getAll(): Flow<List<UserCoinEntity>>

    @Query("SELECT COUNT(*) FROM user_coins")
    fun getCount(): Flow<Int>

    @Query("SELECT SUM(currentValue) FROM user_coins")
    fun getTotalValue(): Flow<Double?>

    @Query("SELECT DISTINCT country FROM user_coins")
    fun getCountries(): Flow<List<String>>

    @Insert
    suspend fun insert(coin: UserCoinEntity)

    @Delete
    suspend fun delete(coin: UserCoinEntity)

    @Query("SELECT * FROM user_coins WHERE country = :country")
    fun getByCountry(country: String): Flow<List<UserCoinEntity>>
}
```

### Pourquoi Room et pas Supabase directement ?

- **Offline first** : le coffre fonctionne sans réseau
- **Performance** : lecture instantanée, pas de latence réseau
- **Sync Supabase** : en Phase 5, quand l'utilisateur crée un compte

---

## 3.2 — Écrans du Coffre (Compose)

### Vue principale

```
┌──────────────────────────────────────┐
│  Mon Coffre                          │
│                                       │
│  💰 Valeur totale : 47,80 €          │
│  📈 +24% depuis le début             │
│  🪙 12 pièces · 6 pays               │
│                                       │
│  [Filtres : Tous ▼] [Grille|Liste]   │
│                                       │
│  ┌────┐  ┌────┐  ┌────┐             │
│  │ 🪙 │  │ 🪙 │  │ 🪙 │             │
│  │2€DE│  │1€FR│  │2€IT│             │
│  │4,20€│  │1,00€│ │2,30€│            │
│  └────┘  └────┘  └────┘             │
│  ┌────┐  ┌────┐  ┌────┐             │
│  │ ...│  │ ...│  │ ...│             │
│  └────┘  └────┘  └────┘             │
│                                       │
│  [____] [Scan] [Coffre] [Profil]     │
└──────────────────────────────────────┘
```

### Composables

```kotlin
@Composable
fun VaultScreen(viewModel: VaultViewModel) {
    val coins by viewModel.coins.collectAsStateWithLifecycle()
    val totalValue by viewModel.totalValue.collectAsStateWithLifecycle()
    val stats by viewModel.stats.collectAsStateWithLifecycle()

    Column {
        // Header stats
        VaultHeader(totalValue, stats)

        // Filtres
        FilterBar(
            countries = stats.countries,
            onFilterChanged = viewModel::setFilter
        )

        // Grille de pièces
        LazyVerticalGrid(columns = GridCells.Fixed(3)) {
            items(coins) { coin ->
                CoinCard(coin, onClick = { /* navigate to detail */ })
            }
        }
    }
}
```

### Filtres

```kotlin
enum class CoinFilter {
    ALL, BY_COUNTRY, BY_VALUE, BY_YEAR, BY_RARITY
}
```

---

## 3.3 — Fiche pièce détaillée

### Données affichées

```
┌──────────────────────────────────────┐
│  [← Retour]                          │
│                                       │
│  [Image obverse]    [Image reverse]   │
│                                       │
│  2€ Commémorative Allemagne 2006      │
│  Schleswig-Holstein (Holstentor)      │
│                                       │
│  Pays : Allemagne                     │
│  Année : 2006                         │
│  Tirage : 30 000 000                  │
│  Rareté : Peu courante               │
│                                       │
│  ─── Valorisation ───                 │
│  Valeur faciale : 2,00 €             │
│  Valeur marché : 3,50 € — 5,20 €    │
│  (P25-P75, source eBay, maj. 07/04)  │
│  Delta : +75% à +160%                │
│                                       │
│  ─── Historique (12 mois) ───        │
│  [      Graphe sparkline       ]     │
│  Min: 2,80€  Médian: 4,20€  Max: 8€ │
│                                       │
│  ─── Tendance ───                     │
│  → Stable sur 3 mois                 │
│  Projection 1 an : ~4,50€            │
│  (estimation indicative)              │
│                                       │
│  [ Supprimer du Coffre ]  [ Partager ]│
└──────────────────────────────────────┘
```

---

## 3.4 — Pipeline de prix eBay

### Supabase Edge Function (cron hebdomadaire)

```typescript
// supabase/functions/update-prices/index.ts

import { createClient } from '@supabase/supabase-js'

Deno.serve(async () => {
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY)

  // 1. Récupérer toutes les pièces du catalogue
  const { data: coins } = await supabase.from('coins').select('*')

  for (const coin of coins) {
    // 2. Construire la requête eBay
    const query = buildEbayQuery(coin) // ex: "2 euro germany 2006 commemorative"

    // 3. Fetch eBay Browse API
    const sales = await fetchEbaySoldItems(query)

    // 4. Calculer les percentiles
    const prices = sales.map(s => s.price).sort()
    const p25 = percentile(prices, 25)
    const p50 = percentile(prices, 50)
    const p75 = percentile(prices, 75)

    // 5. Insert dans price_history
    await supabase.from('price_history').insert({
      coin_id: coin.id,
      price_median: p50,
      price_p25: p25,
      price_p75: p75,
      source: 'ebay',
      recorded_at: new Date().toISOString().split('T')[0]
    })
  }

  return new Response('OK')
})
```

### Scheduling via pg_cron

```sql
-- Dans Supabase SQL Editor
SELECT cron.schedule(
  'update-prices-weekly',
  '0 3 * * 1',  -- Chaque lundi à 3h du matin
  $$SELECT net.http_post(
    url := 'https://xxxxx.supabase.co/functions/v1/update-prices',
    headers := '{"Authorization": "Bearer SERVICE_KEY"}'::jsonb
  )$$
);
```

### Sync prix vers l'app

L'app récupère les prix au lancement (ou toutes les 24h) :

```kotlin
class PriceRepository(
    private val supabase: SupabaseClient,
    private val priceDao: CachedPriceDao
) {
    suspend fun syncPrices() {
        val prices = supabase.from("price_history")
            .select() {
                order("recorded_at", Order.DESCENDING)
                limit(count = 1)  // Dernier prix par pièce
            }
            .decodeList<PriceDto>()

        priceDao.upsertAll(prices.map { it.toEntity() })
    }
}
```

---

## 3.5 — Graphe sparkline

Librairie recommandée : **Vico** (bibliothèque de graphes pour Compose, moderne et légère).

```kotlin
@Composable
fun PriceSparkline(priceHistory: List<PricePoint>) {
    // Vico chart avec les prix médians sur 12 mois
    // X = date, Y = prix médian
    // Ligne avec gradient sous la courbe
    // Min/Max/Médian en légende
}
```

---

## 3.6 — Projection v1

Régression linéaire simple côté app :

```kotlin
fun linearProjection(history: List<PricePoint>): Projection? {
    if (history.size < 6) return null  // Pas assez de données

    // Moindres carrés
    val (slope, intercept) = linearRegression(history)

    val current = history.last().price
    val projected1y = current + slope * 52   // 52 semaines
    val projected5y = current + slope * 260

    return Projection(
        current = current,
        oneYear = projected1y,
        fiveYears = projected5y,
        trend = when {
            slope > 0.02 -> Trend.UP
            slope < -0.02 -> Trend.DOWN
            else -> Trend.STABLE
        }
    )
}
```

---

## 3.7 — Livrables Phase 3

- [ ] Room DB : entités + DAO + migrations
- [ ] Ajout au coffre depuis le scan (1 tap)
- [ ] Écran Coffre : grille, filtres, valeur totale, stats
- [ ] Fiche pièce détaillée (infos + prix + graphe)
- [ ] Edge Function cron eBay (prix hebdomadaires)
- [ ] Sync prix Supabase → cache local
- [ ] Graphe sparkline (Vico)
- [ ] Projection v1 (régression linéaire)
- [ ] Fallback Numista pour pièces sans prix eBay

---

## Durée estimée

**10-14 jours**
- 3-4 jours : Room DB + écrans Coffre (Compose)
- 3-4 jours : Edge Function eBay + sync prix
- 2-3 jours : fiche pièce + graphe sparkline
- 2-3 jours : projection + polish
