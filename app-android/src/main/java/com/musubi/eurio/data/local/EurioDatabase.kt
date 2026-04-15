package com.musubi.eurio.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
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
    version = 1,
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

        @Volatile
        private var instance: EurioDatabase? = null

        fun get(context: Context): EurioDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    EurioDatabase::class.java,
                    DB_NAME,
                )
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
