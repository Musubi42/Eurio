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
import com.musubi.eurio.data.local.dao.MetaDao
import com.musubi.eurio.data.local.dao.SetDao
import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.data.local.entities.CatalogMetaEntity
import com.musubi.eurio.data.local.entities.CoinCaptureEntity
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.data.local.entities.CoinInVaultEntity
import com.musubi.eurio.data.local.entities.CoinSeriesEntity
import com.musubi.eurio.data.local.entities.SetEntity
import com.musubi.eurio.data.local.entities.SetMemberEntity

@Database(
    entities = [
        CoinEntity::class,
        CoinSeriesEntity::class,
        SetEntity::class,
        SetMemberEntity::class,
        CoinInVaultEntity::class,
        CoinCaptureEntity::class,
        CatalogMetaEntity::class,
    ],
    version = 3,
    exportSchema = true,
)
@TypeConverters(Converters::class)
abstract class EurioDatabase : RoomDatabase() {
    abstract fun coinDao(): CoinDao
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

        @Volatile
        private var instance: EurioDatabase? = null

        fun get(context: Context): EurioDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    EurioDatabase::class.java,
                    DB_NAME,
                )
                    .addMigrations(MIGRATION_1_2, MIGRATION_2_3)
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
