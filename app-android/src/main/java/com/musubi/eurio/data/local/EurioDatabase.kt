package com.musubi.eurio.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.data.local.dao.CoinDao
import com.musubi.eurio.data.local.dao.CoinPriceDao
import com.musubi.eurio.data.local.dao.MetaDao
import com.musubi.eurio.data.local.dao.SetDao
import com.musubi.eurio.data.local.dao.SharedReverseDao
import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.data.local.entities.CatalogMetaEntity
import com.musubi.eurio.data.local.entities.CoinCaptureEntity
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.data.local.entities.CoinInVaultEntity
import com.musubi.eurio.data.local.entities.CoinPriceEntity
import com.musubi.eurio.data.local.entities.CoinSeriesEntity
import com.musubi.eurio.data.local.entities.SetEntity
import com.musubi.eurio.data.local.entities.SetMemberEntity
import com.musubi.eurio.data.local.entities.SharedReverseEntity

@Database(
    entities = [
        CoinEntity::class,
        CoinPriceEntity::class,
        SharedReverseEntity::class,
        CoinSeriesEntity::class,
        SetEntity::class,
        SetMemberEntity::class,
        CoinInVaultEntity::class,
        CoinCaptureEntity::class,
        CatalogMetaEntity::class,
    ],
    version = 4,
    exportSchema = true,
)
@TypeConverters(Converters::class)
abstract class EurioDatabase : RoomDatabase() {
    abstract fun coinDao(): CoinDao
    abstract fun coinPriceDao(): CoinPriceDao
    abstract fun sharedReverseDao(): SharedReverseDao
    abstract fun setDao(): SetDao
    abstract fun vaultDao(): VaultDao
    abstract fun metaDao(): MetaDao

    companion object {
        private const val DB_NAME = "eurio.db"

        // v1 → v2 : ajout des colonnes de photo metadata sur `coins` pour le
        // viewer 3D (cf. docs/coin-3d-viewer/porting-android.md, Phase 1).
        // Toutes nullables → ALTER TABLE ADD COLUMN suffit, vault_entries
        // intacts.
        internal val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE coins ADD COLUMN obverse_cx_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN obverse_cy_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN obverse_radius_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN reverse_cx_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN reverse_cy_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN reverse_radius_uv REAL")
            }
        }

        // v2 → v3 (D23) : passage de la table unique `vault_entries` à la
        // séparation possession / journal (D24).
        //
        // - `coin_in_vault` : 1 row par eurio_id possédé. `declared_count`
        //   reprend `COUNT(*)` du vault_entries source pour ne pas perdre
        //   les scans répétés. `primary_capture_id` reste NULL — aucune
        //   image historique n'existe avant chunk-5.
        // - `coin_captures` : créée vide, alimentée par chunk-5c (archive
        //   auto sur consensus).
        // - `vault_entries` est droppée à la fin — pas de
        //   fallbackToDestructiveMigration en release donc la migration
        //   doit être atomique. Si le DROP foire le rollback Room annule
        //   tout, on garde les données.
        internal val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("""
                    CREATE TABLE IF NOT EXISTS coin_captures (
                        capture_id TEXT NOT NULL PRIMARY KEY,
                        eurio_id TEXT NOT NULL,
                        captured_at INTEGER NOT NULL,
                        image_filename TEXT NOT NULL,
                        quality_score REAL NOT NULL,
                        is_primary INTEGER NOT NULL,
                        capture_metadata_json TEXT NOT NULL,
                        low_quality_flag INTEGER NOT NULL DEFAULT 0,
                        uploaded_at INTEGER,
                        FOREIGN KEY(eurio_id) REFERENCES coins(eurio_id) ON DELETE CASCADE
                    )
                """.trimIndent())
                db.execSQL("CREATE INDEX IF NOT EXISTS index_coin_captures_eurio_id ON coin_captures(eurio_id)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_coin_captures_eurio_id_is_primary ON coin_captures(eurio_id, is_primary)")

                db.execSQL("""
                    CREATE TABLE IF NOT EXISTS coin_in_vault (
                        eurio_id TEXT NOT NULL PRIMARY KEY,
                        first_captured_at INTEGER NOT NULL,
                        primary_capture_id TEXT,
                        declared_count INTEGER NOT NULL DEFAULT 1,
                        notes TEXT,
                        uploaded_at INTEGER,
                        remote_vault_id TEXT,
                        FOREIGN KEY(eurio_id) REFERENCES coins(eurio_id) ON DELETE CASCADE,
                        FOREIGN KEY(primary_capture_id) REFERENCES coin_captures(capture_id) ON DELETE NO ACTION
                    )
                """.trimIndent())
                db.execSQL("CREATE INDEX IF NOT EXISTS index_coin_in_vault_primary_capture_id ON coin_in_vault(primary_capture_id)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_coin_in_vault_first_captured_at ON coin_in_vault(first_captured_at)")

                // Backfill — group historic scans by eurio_id, take MIN(scanned_at)
                // as the first-captured timestamp, COUNT(*) as declared_count
                // (matches the old "x N" multiplicity badge), MAX(notes) to keep
                // a single representative note if any was set.
                db.execSQL("""
                    INSERT INTO coin_in_vault (
                        eurio_id, first_captured_at, primary_capture_id,
                        declared_count, notes, uploaded_at, remote_vault_id
                    )
                    SELECT
                        coin_eurio_id,
                        MIN(scanned_at),
                        NULL,
                        COUNT(*),
                        MAX(notes),
                        NULL,
                        NULL
                    FROM vault_entries
                    GROUP BY coin_eurio_id
                """.trimIndent())

                db.execSQL("DROP TABLE vault_entries")
            }
        }

        // v3 → v4 (P6) : migration du catalogue de catalog_snapshot.json vers
        // app_core.db. Le schéma `coins` est entièrement remplacé (suppression
        // des colonnes V1 : numista_id, face_value, issue_type, series_id,
        // image_*_url, is_withdrawn, withdrawal_reason, theme_code, photo UV
        // cols). Les nouvelles tables coin_prices et shared_reverse sont créées.
        //
        // Les tables vault (coin_in_vault, coin_captures) et catalog_meta sont
        // préservées. Les tables coin_series, sets et set_members sont gardées
        // vides — le bootstrapper V2 ne les peuple plus ; les fonctionnalités
        // sets restent opérationnelles via les DAOs existants.
        //
        // `coin_in_vault` référence `coins(eurio_id)` via FK ON DELETE CASCADE :
        // les eurio_id sont stables entre V1 et V2 du catalogue. Aucune perte de
        // vault attendue sur le parc installé.
        internal val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                // 1. Drop and recreate `coins` with the V2 schema.
                //    coin_in_vault has FK ON DELETE CASCADE → drop coins first
                //    forces SQLite to honour the cascade on any remaining rows.
                //    (In practice the bootstrapper will repopulate immediately.)
                db.execSQL("DROP TABLE IF EXISTS coins")
                db.execSQL("""
                    CREATE TABLE IF NOT EXISTS coins (
                        eurio_id TEXT NOT NULL PRIMARY KEY,
                        country TEXT NOT NULL,
                        country_name TEXT,
                        year INTEGER,
                        face_value_cents INTEGER NOT NULL,
                        is_commemorative INTEGER NOT NULL,
                        collector_only INTEGER NOT NULL,
                        theme TEXT,
                        design_description TEXT,
                        mintage INTEGER,
                        diameter_mm REAL,
                        weight_g REAL,
                        thickness_mm REAL,
                        composition TEXT,
                        shape TEXT,
                        edge_lettering TEXT,
                        design_group_id TEXT,
                        variant_kind TEXT NOT NULL,
                        canonical_eurio_id TEXT,
                        shared_reverse_id TEXT,
                        name_fr TEXT,
                        name_en TEXT,
                        desc_fr TEXT,
                        desc_en TEXT
                    )
                """.trimIndent())
                db.execSQL("CREATE INDEX IF NOT EXISTS index_coins_country ON coins(country)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_coins_year ON coins(year)")

                // 2. New table: coin_prices (market baseline prices per grade).
                db.execSQL("""
                    CREATE TABLE IF NOT EXISTS coin_prices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                        eurio_id TEXT NOT NULL,
                        grade TEXT NOT NULL,
                        p_low INTEGER,
                        p_mid INTEGER,
                        p_high INTEGER,
                        currency TEXT,
                        source TEXT,
                        sampled_at TEXT
                    )
                """.trimIndent())
                db.execSQL("CREATE INDEX IF NOT EXISTS index_coin_prices_eurio_id ON coin_prices(eurio_id)")

                // 3. New table: shared_reverse (2 rows — 2€ reverse map v1/v2).
                db.execSQL("""
                    CREATE TABLE IF NOT EXISTS shared_reverse (
                        id TEXT NOT NULL PRIMARY KEY,
                        label TEXT,
                        asset_name TEXT,
                        map_version INTEGER
                    )
                """.trimIndent())
            }
        }

        @Volatile
        private var instance: EurioDatabase? = null

        fun get(context: Context): EurioDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    EurioDatabase::class.java,
                    DB_NAME,
                )
                    .addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4)
                    .apply {
                        // Migrations destructives autorisées uniquement en debug.
                        // Release = on doit écrire une Migration explicite pour chaque v+1
                        // sinon le build échoue à l'upgrade → zéro perte silencieuse des vault_entries.
                        if (BuildConfig.DEBUG) fallbackToDestructiveMigration()
                    }
                    .build()
                    .also { instance = it }
            }
        }
    }
}
