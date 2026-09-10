package com.musubi.eurio.data.local

import androidx.room.Room
import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.musubi.eurio.data.local.entities.ScanEventEntity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * D5 — le SQL réel du journal de scans, sur device.
 *
 * Le pendant JVM (`src/test/.../ScanJournalTest.kt`) couvre la logique de
 * regroupement ; ici on vérifie ce qu'aucun double ne peut vérifier : que la
 * table existe après migration, que les requêtes du DAO renvoient ce qu'elles
 * annoncent, et que la migration 4→5 **ne perd pas le coffre**.
 */
@RunWith(AndroidJUnit4::class)
class ScanEventDaoTest {

    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        EurioDatabase::class.java,
        emptyList(),
        FrameworkSQLiteOpenHelperFactory(),
    )

    private val dbName = "scan-events-migration-test.db"

    @Test
    fun dao_compteEtRestitueLesEvenements() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(context, EurioDatabase::class.java).build()
        val dao = db.scanEventDao()

        assertEquals(0, dao.countAll())

        dao.insert(ScanEventEntity(eurioId = "fr-2eur-2024-jo", occurredAt = 1_000L))
        dao.insert(ScanEventEntity(eurioId = "de-1eur-2002", occurredAt = 3_000L))
        dao.insert(ScanEventEntity(eurioId = "fr-2eur-2024-jo", occurredAt = 2_000L))

        assertEquals(3, dao.countAll())
        assertEquals(2, dao.countSince(2_000L))
        assertEquals(listOf(1_000L, 2_000L, 3_000L), dao.allTimestamps())
        assertEquals(
            listOf("fr-2eur-2024-jo", "fr-2eur-2024-jo", "de-1eur-2002"),
            dao.all().map { it.eurioId },
        )
        // autoGenerate : chaque ligne reçoit un id distinct non nul.
        assertEquals(3, dao.all().map { it.id }.toSet().size)
        assertTrue(dao.all().all { it.id > 0 })

        db.close()
    }

    @Test
    fun migrate4to5_creeScanEventsSansToucherAuCoffre() {
        helper.createDatabase(dbName, 4).use { db ->
            db.execSQL(
                "INSERT INTO coin_in_vault (eurio_id, first_captured_at, primary_capture_id, declared_count) " +
                    "VALUES ('fr-2eur-2024-jo', 1700000000000, NULL, 2)"
            )
        }

        val migrated = helper.runMigrationsAndValidate(
            dbName,
            5,
            true,
            EurioDatabase.MIGRATION_4_5,
        )

        migrated.query("SELECT COUNT(*) FROM scan_events").use { c ->
            assertTrue(c.moveToFirst())
            assertEquals(0, c.getInt(0))
        }
        migrated.query("SELECT eurio_id, declared_count FROM coin_in_vault").use { c ->
            assertTrue(c.moveToFirst())
            assertEquals("fr-2eur-2024-jo", c.getString(0))
            assertEquals(2, c.getInt(1))
            assertEquals(1, c.count)
        }
        migrated.close()
    }
}
