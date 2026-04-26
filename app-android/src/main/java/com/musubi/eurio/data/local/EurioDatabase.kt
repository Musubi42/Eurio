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
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.data.local.entities.CoinSeriesEntity
import com.musubi.eurio.data.local.entities.SetEntity
import com.musubi.eurio.data.local.entities.SetMemberEntity
import com.musubi.eurio.data.local.entities.VaultEntryEntity

@Database(
    entities = [
        CoinEntity::class,
        CoinSeriesEntity::class,
        SetEntity::class,
        SetMemberEntity::class,
        VaultEntryEntity::class,
        CatalogMetaEntity::class,
    ],
    version = 2,
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
        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE coins ADD COLUMN obverse_cx_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN obverse_cy_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN obverse_radius_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN reverse_cx_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN reverse_cy_uv REAL")
                db.execSQL("ALTER TABLE coins ADD COLUMN reverse_radius_uv REAL")
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
                    .addMigrations(MIGRATION_1_2)
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
