package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import com.musubi.eurio.data.local.entities.CoinCaptureEntity
import com.musubi.eurio.data.local.entities.CoinInVaultEntity
import com.musubi.eurio.data.local.entities.VaultCoinWithCoin
import kotlinx.coroutines.flow.Flow

/**
 * Atomic vault ops. The "archive ≠ possession" split (D24) lives in
 * [com.musubi.eurio.data.repository.VaultCaptureRepository], not here —
 * intentionally no `insertCaptureAndUpsertVault` helper, so a misplaced
 * archive can never silently create a possession row.
 */
@Dao
abstract class VaultDao {

    // ── coin_in_vault ──────────────────────────────────────────────────

    @Query("SELECT * FROM coin_in_vault WHERE eurio_id = :eurioId")
    abstract suspend fun getVault(eurioId: String): CoinInVaultEntity?

    @Query("SELECT COUNT(*) > 0 FROM coin_in_vault WHERE eurio_id = :eurioId")
    abstract suspend fun containsCoin(eurioId: String): Boolean

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun upsertVault(vault: CoinInVaultEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun upsertVaultAll(rows: List<CoinInVaultEntity>)

    @Query("DELETE FROM coin_in_vault WHERE eurio_id = :eurioId")
    abstract suspend fun removeCoin(eurioId: String)

    @Query("DELETE FROM coin_in_vault")
    abstract suspend fun clearAll()

    // ── coin_captures ──────────────────────────────────────────────────

    @Query("SELECT * FROM coin_captures WHERE capture_id = :captureId")
    abstract suspend fun getCapture(captureId: String): CoinCaptureEntity?

    @Query(
        """
        SELECT * FROM coin_captures
        WHERE eurio_id = :eurioId AND is_primary = 1 LIMIT 1
        """
    )
    abstract suspend fun getPrimaryCapture(eurioId: String): CoinCaptureEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    abstract suspend fun insertCapture(capture: CoinCaptureEntity)

    @Query(
        """
        UPDATE coin_captures
        SET is_primary = (capture_id = :newPrimaryId)
        WHERE eurio_id = :eurioId
        """
    )
    abstract suspend fun setPrimary(eurioId: String, newPrimaryId: String)

    /**
     * Promote a capture to primary atomically: flip `is_primary` on the right
     * row + update the pointer in `coin_in_vault`. Pre-condition: the vault
     * row for `eurioId` already exists (caller responsibility — repository
     * pre-checks). Lifting this to the repository keeps the DAO free of
     * domain logic.
     */
    @Transaction
    open suspend fun promotePrimary(eurioId: String, newPrimaryId: String) {
        val vault = getVault(eurioId)
            ?: error("promotePrimary called on non-possessed eurioId=$eurioId — repository bug")
        setPrimary(eurioId, newPrimaryId)
        upsertVault(vault.copy(primaryCaptureId = newPrimaryId))
    }

    // ── Queries used by the coffre UI and stats screens ────────────────

    @Query("SELECT COUNT(*) FROM coin_in_vault")
    abstract fun observeTotalCount(): Flow<Int>

    @Query("SELECT eurio_id FROM coin_in_vault")
    abstract fun observeAllEurioIds(): Flow<List<String>>

    /**
     * Distinct coin count = row count in D24 (one row per eurio_id). Kept
     * as a separate method for the existing call sites — the two flows
     * happen to return the same value today but stay independent in case
     * we re-introduce a journal aggregate (e.g. via [observeCaptureCount]).
     */
    @Query("SELECT COUNT(*) FROM coin_in_vault")
    abstract fun observeDistinctCoinCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM coin_captures")
    abstract fun observeCaptureCount(): Flow<Int>

    @Query(
        """
        SELECT COUNT(*) FROM coin_in_vault v
        INNER JOIN set_members sm ON sm.coin_eurio_id = v.eurio_id
        WHERE sm.set_id = :setId
        """
    )
    abstract suspend fun countOwnedInSet(setId: String): Int

    @Transaction
    @Query("SELECT * FROM coin_in_vault ORDER BY first_captured_at DESC")
    abstract fun observeAllWithCoin(): Flow<List<VaultCoinWithCoin>>

    @Query(
        """
        SELECT DISTINCT c.country FROM coin_in_vault v
        INNER JOIN coins c ON v.eurio_id = c.eurio_id
        ORDER BY c.country
        """
    )
    abstract fun observeAvailableCountries(): Flow<List<String>>
}
