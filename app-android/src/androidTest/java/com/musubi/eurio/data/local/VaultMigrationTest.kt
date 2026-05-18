package com.musubi.eurio.data.local

import android.content.ContentValues
import androidx.room.Room
import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Chunk-5a — verifies that the destructive v2→v3 migration preserves
 * user data. The risk this guards against is silent loss of the
 * `vault_entries` table on first release-upgrade — we explicitly do NOT
 * use `fallbackToDestructiveMigration` in release, so this migration is
 * the only path forward.
 *
 * Assertions:
 *  - declared_count = COUNT(*) of source vault_entries grouped by eurio_id.
 *  - first_captured_at = MIN(scanned_at) per group.
 *  - primary_capture_id is NULL for every backfilled row (no historic JPEG).
 *  - vault_entries is dropped.
 *  - coin_captures is created and empty.
 */
@RunWith(AndroidJUnit4::class)
class VaultMigrationTest {

    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        EurioDatabase::class.java,
        emptyList(),
        FrameworkSQLiteOpenHelperFactory(),
    )

    private val dbName = "vault-migration-test.db"

    @Test
    fun migrate2to3_preservesDeclaredCount() {
        // ─── Seed v2 ─────────────────────────────────────────────────
        helper.createDatabase(dbName, 2).use { db ->
            // Two distinct coins; coin A scanned 3 times, coin B once.
            // Insert coins parents first to satisfy FK.
            db.insert("coins", android.database.sqlite.SQLiteDatabase.CONFLICT_ABORT, ContentValues().apply {
                put("eurio_id", "fr-2eur-2024-jo")
                put("country", "FR")
                put("is_withdrawn", 0)
            })
            db.insert("coins", android.database.sqlite.SQLiteDatabase.CONFLICT_ABORT, ContentValues().apply {
                put("eurio_id", "de-1eur-2002")
                put("country", "DE")
                put("is_withdrawn", 0)
            })

            // 3 scans for coin A, spread in time.
            listOf(1_700_000_000_000L, 1_700_001_000_000L, 1_700_002_000_000L)
                .forEach { ts ->
                    db.insert("vault_entries", android.database.sqlite.SQLiteDatabase.CONFLICT_ABORT, ContentValues().apply {
                        put("coin_eurio_id", "fr-2eur-2024-jo")
                        put("scanned_at", ts)
                        put("source", "scan")
                        put("confidence", 0.95f)
                    })
                }
            // 1 scan for coin B.
            db.insert("vault_entries", android.database.sqlite.SQLiteDatabase.CONFLICT_ABORT, ContentValues().apply {
                put("coin_eurio_id", "de-1eur-2002")
                put("scanned_at", 1_700_003_000_000L)
                put("source", "scan")
                put("confidence", 0.88f)
            })
        }

        // ─── Run migration ──────────────────────────────────────────
        helper.runMigrationsAndValidate(
            dbName,
            3,
            true,
            EurioDatabase.MIGRATION_2_3,
        ).use { db ->
            // declared_count must reflect COUNT(*) of source rows.
            db.query("SELECT eurio_id, first_captured_at, primary_capture_id, declared_count FROM coin_in_vault ORDER BY eurio_id").use { c ->
                assertEquals(2, c.count)

                c.moveToNext()
                assertEquals("de-1eur-2002", c.getString(0))
                assertEquals(1_700_003_000_000L, c.getLong(1))
                assertNull(c.getString(2))
                assertEquals(1, c.getInt(3))

                c.moveToNext()
                assertEquals("fr-2eur-2024-jo", c.getString(0))
                // MIN(scanned_at) for coin A
                assertEquals(1_700_000_000_000L, c.getLong(1))
                assertNull(c.getString(2))
                assertEquals(3, c.getInt(3))
            }

            // coin_captures created and empty.
            db.query("SELECT COUNT(*) FROM coin_captures").use { c ->
                c.moveToNext()
                assertEquals(0, c.getInt(0))
            }

            // vault_entries dropped.
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='vault_entries'").use { c ->
                assertEquals(0, c.count)
            }
        }
    }

    @Test
    fun migrate2to3_emptyVaultEntries_producesEmptyCoinInVault() {
        helper.createDatabase(dbName, 2).close()
        helper.runMigrationsAndValidate(
            dbName,
            3,
            true,
            EurioDatabase.MIGRATION_2_3,
        ).use { db ->
            db.query("SELECT COUNT(*) FROM coin_in_vault").use { c ->
                c.moveToNext()
                assertEquals(0, c.getInt(0))
            }
            db.query("SELECT COUNT(*) FROM coin_captures").use { c ->
                c.moveToNext()
                assertEquals(0, c.getInt(0))
            }
        }
    }

    @Test
    fun fullChain_v1ThroughV3_appliesBothMigrations() {
        // Bootstrap from v1 (pre-3D-photo-meta columns) → ensures both
        // MIGRATION_1_2 and MIGRATION_2_3 chain cleanly.
        helper.createDatabase(dbName, 1).close()
        helper.runMigrationsAndValidate(
            dbName,
            3,
            true,
            EurioDatabase.MIGRATION_1_2,
            EurioDatabase.MIGRATION_2_3,
        ).use { db ->
            // Both new tables present.
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('coin_in_vault', 'coin_captures') ORDER BY name").use { c ->
                assertEquals(2, c.count)
            }
            // v1→v2 added obverse_cx_uv to coins — should still be there.
            db.query("PRAGMA table_info(coins)").use { c ->
                val names = generateSequence { if (c.moveToNext()) c.getString(1) else null }.toList()
                assertTrue("coins.obverse_cx_uv missing after full chain", "obverse_cx_uv" in names)
            }
        }
    }

    @Test
    fun openLatestSchemaPostMigration_succeeds() {
        // After migrating, opening a real EurioDatabase against the
        // migrated file must not throw or trigger a re-build. This is
        // what would actually happen in prod on user upgrade.
        helper.createDatabase(dbName, 2).use { db ->
            db.insert("coins", android.database.sqlite.SQLiteDatabase.CONFLICT_ABORT, ContentValues().apply {
                put("eurio_id", "fr-2eur-2024-jo")
                put("country", "FR")
                put("is_withdrawn", 0)
            })
            db.insert("vault_entries", android.database.sqlite.SQLiteDatabase.CONFLICT_ABORT, ContentValues().apply {
                put("coin_eurio_id", "fr-2eur-2024-jo")
                put("scanned_at", 1L)
                put("source", "scan")
            })
        }

        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val realDb = Room.databaseBuilder(ctx, EurioDatabase::class.java, dbName)
            .addMigrations(EurioDatabase.MIGRATION_1_2, EurioDatabase.MIGRATION_2_3)
            .build()
        try {
            // Force-open the DB to trigger migration validation.
            realDb.openHelper.writableDatabase
            // Sanity check: the row survived the migration as a single
            // coin_in_vault entry with declared_count=1.
            realDb.openHelper.writableDatabase
                .query("SELECT declared_count FROM coin_in_vault WHERE eurio_id='fr-2eur-2024-jo'").use { c ->
                    c.moveToNext()
                    assertEquals(1, c.getInt(0))
                }
        } finally {
            realDb.close()
        }
    }
}
