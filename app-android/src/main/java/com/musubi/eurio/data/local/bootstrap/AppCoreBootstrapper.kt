package com.musubi.eurio.data.local.bootstrap

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.util.Log
import androidx.room.withTransaction
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.data.local.EurioDatabase
import com.musubi.eurio.data.local.entities.CatalogMetaEntity
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.data.local.entities.CoinPriceEntity
import com.musubi.eurio.data.local.entities.SharedReverseEntity
import java.io.File

// Bootstrap du catalogue au premier run / mise à jour d'APK : lit app_core.db
// depuis assets/, peuple Room, et marque la version dans catalog_meta.
//
// Version-gate : on compare APP_CORE_VERSION (constante hardcodée par incrément
// à chaque nouveau build) à la valeur stockée dans catalog_meta. Si la version
// packagée est supérieure (ou absente), on flush les tables catalogue et
// réinjecte depuis app_core.db. Les tables vault ne sont jamais touchées.
//
// Le fichier app_core.db est copié dans cacheDir (lecture seule imposée par
// SQLiteDatabase.openDatabase + flag OPEN_READONLY).
class AppCoreBootstrapper(
    private val context: Context,
    private val db: EurioDatabase,
) {
    suspend fun runIfNeeded() {
        val meta = db.metaDao()
        val storedVersion = meta.getInt(KEY_APP_CORE_VERSION)

        // QA : le app_core.db packagé est un sous-ensemble curé régénéré souvent
        // (la source de vérité parité). On le recharge à chaque lancement pour
        // que le catalogue reflète toujours le dernier dump, SANS `pm clear`
        // manuel — le version-gate n'est qu'une optimisation release. Le coffre
        // est re-seedé via le deep link parité, donc le wipe en cascade est sans
        // conséquence en QA.
        val forceReload = BuildConfig.IS_QA

        if (!forceReload && storedVersion != null && storedVersion >= APP_CORE_VERSION) {
            Log.i(TAG, "app_core.db déjà à jour (version=$storedVersion) — skip bootstrap")
            return
        }

        if (forceReload) {
            Log.i(TAG, "Bootstrap app_core.db : QA force-reload (version stockée=$storedVersion ignorée)")
        } else {
            Log.i(TAG, "Bootstrap app_core.db : version stockée=$storedVersion → packagée=$APP_CORE_VERSION")
        }

        val coreDb = extractAndOpen() ?: run {
            Log.e(TAG, "Impossible d'ouvrir app_core.db — skip bootstrap")
            return
        }

        try {
            val coins = queryCoinEntities(coreDb)
            if (coins.isEmpty()) {
                Log.w(TAG, "app_core.db : 0 coins lus — abort bootstrap (export bug?)")
                return
            }
            val prices = queryCoinPriceEntities(coreDb)
            val sharedReverses = querySharedReverseEntities(coreDb)

            Log.i(TAG, "Bootstrap : ${coins.size} coins, ${prices.size} prices, ${sharedReverses.size} shared_reverse rows")

            db.withTransaction {
                // Release : on n'appelle PAS clearCoins() — `DELETE FROM coins`
                // ferait cascader la FK ON DELETE CASCADE de coin_in_vault et
                // viderait le coffre. insertAllCoins est en @Upsert (update en
                // place, pas de delete → pas de cascade). coin_prices /
                // shared_reverse n'ont pas d'enfant côté coffre, on les rafraîchit
                // intégralement.
                // QA : on PURGE les coins pour que le catalogue soit exactement le
                // sous-ensemble packagé (aucun coin résiduel d'un build QA
                // précédent). Le coffre cascadé est re-seedé via le deep link parité.
                if (forceReload) {
                    db.coinDao().clearCoins()
                }
                db.coinPriceDao().clearAll()
                db.sharedReverseDao().clearAll()

                db.sharedReverseDao().insertAll(sharedReverses)
                db.coinDao().insertAllCoins(coins)
                db.coinPriceDao().insertAll(prices)

                meta.putInt(KEY_APP_CORE_VERSION, APP_CORE_VERSION)
                meta.putLong(CatalogMetaEntity.KEY_BOOTSTRAP_AT, System.currentTimeMillis())
            }

            Log.i(TAG, "Bootstrap app_core.db terminé.")
        } finally {
            coreDb.close()
        }
    }

    // Copy the asset to cacheDir so SQLiteDatabase.openDatabase can open it.
    // The copy is overwritten on every run so it stays in sync with the APK asset.
    private fun extractAndOpen(): SQLiteDatabase? {
        val dest = File(context.cacheDir, ASSET_NAME)
        return try {
            context.assets.open(ASSET_NAME).use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            }
            SQLiteDatabase.openDatabase(
                dest.absolutePath,
                null,
                SQLiteDatabase.OPEN_READONLY,
            )
        } catch (t: Throwable) {
            Log.e(TAG, "Extraction/ouverture de $ASSET_NAME échouée", t)
            null
        }
    }

    private fun queryCoinEntities(src: SQLiteDatabase): List<CoinEntity> {
        val coins = mutableListOf<CoinEntity>()
        // Join coin with coin_name_i18n (fr + en) and coin_description_i18n (fr + en)
        // using LEFT JOINs to keep coins without translations.
        val sql = """
            SELECT
                c.eurio_id, c.country, c.country_name, c.year, c.face_value_cents,
                c.is_commemorative, c.collector_only, c.theme, c.design_description,
                c.mintage, c.diameter_mm, c.weight_g, c.thickness_mm, c.composition,
                c.shape, c.edge_lettering, c.design_group_id, c.variant_kind,
                c.canonical_eurio_id, c.shared_reverse_id,
                nfr.title AS name_fr,
                nen.title AS name_en,
                dfr.title AS desc_fr_title,
                den.title AS desc_en_title
            FROM coin c
            LEFT JOIN coin_name_i18n nfr ON nfr.eurio_id = c.eurio_id AND nfr.lang = 'fr'
            LEFT JOIN coin_name_i18n nen ON nen.eurio_id = c.eurio_id AND nen.lang = 'en'
            LEFT JOIN coin_description_i18n dfr ON dfr.eurio_id = c.eurio_id AND dfr.lang = 'fr'
            LEFT JOIN coin_description_i18n den ON den.eurio_id = c.eurio_id AND den.lang = 'en'
        """.trimIndent()
        src.rawQuery(sql, null).use { cursor ->
            while (cursor.moveToNext()) {
                coins += CoinEntity(
                    eurioId = cursor.getString(cursor.getColumnIndexOrThrow("eurio_id")),
                    country = cursor.getString(cursor.getColumnIndexOrThrow("country")) ?: "",
                    countryName = cursor.getString(cursor.getColumnIndexOrThrow("country_name")),
                    year = cursor.getIntOrNull(cursor.getColumnIndexOrThrow("year")),
                    faceValueCents = cursor.getInt(cursor.getColumnIndexOrThrow("face_value_cents")),
                    isCommemorative = cursor.getInt(cursor.getColumnIndexOrThrow("is_commemorative")) != 0,
                    collectorOnly = cursor.getInt(cursor.getColumnIndexOrThrow("collector_only")) != 0,
                    theme = cursor.getString(cursor.getColumnIndexOrThrow("theme")),
                    designDescription = cursor.getString(cursor.getColumnIndexOrThrow("design_description")),
                    mintage = cursor.getLongOrNull(cursor.getColumnIndexOrThrow("mintage")),
                    diameterMm = cursor.getFloatOrNull(cursor.getColumnIndexOrThrow("diameter_mm")),
                    weightG = cursor.getFloatOrNull(cursor.getColumnIndexOrThrow("weight_g")),
                    thicknessMm = cursor.getFloatOrNull(cursor.getColumnIndexOrThrow("thickness_mm")),
                    composition = cursor.getString(cursor.getColumnIndexOrThrow("composition")),
                    shape = cursor.getString(cursor.getColumnIndexOrThrow("shape")),
                    edgeLettering = cursor.getString(cursor.getColumnIndexOrThrow("edge_lettering")),
                    designGroupId = cursor.getString(cursor.getColumnIndexOrThrow("design_group_id")),
                    variantKind = cursor.getString(cursor.getColumnIndexOrThrow("variant_kind")) ?: "standard",
                    canonicalEurioId = cursor.getString(cursor.getColumnIndexOrThrow("canonical_eurio_id")),
                    sharedReverseId = cursor.getString(cursor.getColumnIndexOrThrow("shared_reverse_id")),
                    nameFr = cursor.getString(cursor.getColumnIndexOrThrow("name_fr")),
                    nameEn = cursor.getString(cursor.getColumnIndexOrThrow("name_en")),
                    descFr = cursor.getString(cursor.getColumnIndexOrThrow("desc_fr_title")),
                    descEn = cursor.getString(cursor.getColumnIndexOrThrow("desc_en_title")),
                )
            }
        }
        return coins
    }

    private fun queryCoinPriceEntities(src: SQLiteDatabase): List<CoinPriceEntity> {
        val prices = mutableListOf<CoinPriceEntity>()
        src.rawQuery(
            "SELECT eurio_id, grade, p_low, p_mid, p_high, currency, source, sampled_at FROM coin_price",
            null,
        ).use { cursor ->
            while (cursor.moveToNext()) {
                prices += CoinPriceEntity(
                    eurioId = cursor.getString(cursor.getColumnIndexOrThrow("eurio_id")),
                    grade = cursor.getString(cursor.getColumnIndexOrThrow("grade")) ?: "",
                    pLow = cursor.getIntOrNull(cursor.getColumnIndexOrThrow("p_low")),
                    pMid = cursor.getIntOrNull(cursor.getColumnIndexOrThrow("p_mid")),
                    pHigh = cursor.getIntOrNull(cursor.getColumnIndexOrThrow("p_high")),
                    currency = cursor.getString(cursor.getColumnIndexOrThrow("currency")),
                    source = cursor.getString(cursor.getColumnIndexOrThrow("source")),
                    sampledAt = cursor.getString(cursor.getColumnIndexOrThrow("sampled_at")),
                )
            }
        }
        return prices
    }

    private fun querySharedReverseEntities(src: SQLiteDatabase): List<SharedReverseEntity> {
        val rows = mutableListOf<SharedReverseEntity>()
        src.rawQuery(
            "SELECT id, label, asset_name, map_version FROM shared_reverse",
            null,
        ).use { cursor ->
            while (cursor.moveToNext()) {
                rows += SharedReverseEntity(
                    id = cursor.getString(cursor.getColumnIndexOrThrow("id")),
                    label = cursor.getString(cursor.getColumnIndexOrThrow("label")),
                    assetName = cursor.getString(cursor.getColumnIndexOrThrow("asset_name")),
                    mapVersion = cursor.getIntOrNull(cursor.getColumnIndexOrThrow("map_version")),
                )
            }
        }
        return rows
    }

    companion object {
        private const val TAG = "AppCoreBootstrapper"
        private const val ASSET_NAME = "app_core.db"

        // Increment this constant whenever a new app_core.db is packaged.
        // On first install (storedVersion == null) or when this is higher than
        // the stored value, the catalog tables are flushed and repopulated.
        //
        // ⚠️ Oublier l'incrément ne casse rien de visible : l'app garde son
        // ancien catalogue et log « déjà à jour ». C'est une panne muette, et
        // elle s'est produite — la constante est restée à 1 pendant que
        // app_core.db était régénéré. Tant qu'elle est manuelle, la régénérer
        // et l'incrémenter vont ensemble, dans le même commit.
        //
        // 2 — 2026-08-16 : rafraîchissement de la projection, 5 → 46
        //     design_group et le rattachement de 56 pièces.
        const val APP_CORE_VERSION = 2

        private const val KEY_APP_CORE_VERSION = "app_core_version"
    }
}

// ── Cursor helpers ─────────────────────────────────────────────────────────

private fun android.database.Cursor.getIntOrNull(columnIndex: Int): Int? =
    if (isNull(columnIndex)) null else getInt(columnIndex)

private fun android.database.Cursor.getLongOrNull(columnIndex: Int): Long? =
    if (isNull(columnIndex)) null else getLong(columnIndex)

private fun android.database.Cursor.getFloatOrNull(columnIndex: Int): Float? =
    if (isNull(columnIndex)) null else getFloat(columnIndex)
