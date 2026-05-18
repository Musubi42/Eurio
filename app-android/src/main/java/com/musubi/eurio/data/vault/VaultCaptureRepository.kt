package com.musubi.eurio.data.vault

import android.util.Log
import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.data.local.entities.CoinCaptureEntity
import com.musubi.eurio.domain.scan.quality.FrameScore

/**
 * Façade over [VaultDao] + [VaultFilesystemWriter] that implements
 * D24's "archive ≠ possession" split.
 *
 * - [archive] is called automatically by [PendingArchiveBuffer] when a
 *   consensus aligns with a pending JPEG. It writes the file to disk,
 *   inserts a [CoinCaptureEntity] row, and promotes the primary capture
 *   **only** if the coin is already possessed and the new capture has
 *   a higher quality score. It never creates `coin_in_vault` — that's
 *   the user's explicit decision via the AcceptedCard.
 *
 * - Possession (`confirmPossession`) lives on [VaultRepository]; that
 *   path accepts an optional `captureId` so the most recent capture
 *   immediately becomes the primary when the user taps "Ajouter au
 *   coffre".
 *
 * - [revertPrimary] backs the snackbar D17 (chunk-5d) "Annuler la
 *   promotion" — restores the previous primary without deleting the
 *   newer capture.
 */
class VaultCaptureRepository(
    private val dao: VaultDao,
    private val filesystem: VaultFilesystemWriter,
) {

    sealed class ArchiveResult {
        data class Success(
            val captureId: String,
            val filename: String,
            val isPossessed: Boolean,
            val promoted: Boolean,
            /**
             * The previous primary capture id, surfaced so the snackbar D17
             * "Annuler" action can call [revertPrimary] without re-querying
             * the DAO. Non-null only when [promoted] is true.
             */
            val previousPrimaryId: String?,
        ) : ArchiveResult()

        data class Failure(val cause: String) : ArchiveResult()
    }

    /**
     * Archive a captured frame (D24 — never touches `coin_in_vault`).
     *
     * Order of operations:
     *   1. Write the JPEG file first — Room must never reference missing bytes.
     *   2. Look up existing possession + primary for [eurioId] to compute
     *      promotion intent.
     *   3. Insert the [CoinCaptureEntity] row with the resolved
     *      `is_primary` flag baked in.
     *   4. If we just promoted an existing primary, call
     *      [VaultDao.promotePrimary] to swap the flag on the old row and
     *      update the pointer in `coin_in_vault`.
     */
    suspend fun archive(
        eurioId: String,
        captureId: String,
        jpegBytes: ByteArray,
        score: FrameScore,
        metadata: CaptureMetadata,
    ): ArchiveResult {
        val filename = "$captureId.jpg"
        try {
            filesystem.write(filename, jpegBytes)
        } catch (e: Exception) {
            Log.e(TAG, "filesystem write failed for $filename", e)
            return ArchiveResult.Failure("filesystem write: ${e.message}")
        }

        val existingVault = dao.getVault(eurioId)
        val existingPrimary = existingVault?.primaryCaptureId
            ?.let { dao.getCapture(it) }

        // Three promotion paths:
        //  - Auto-fill : possession exists but primary_capture_id is NULL
        //    (post-D23 migration). Silent — the user doesn't know it was
        //    missing.
        //  - Quality   : possession exists with a primary, but the new
        //    capture has a strictly higher aggregate score. Snackbar D17
        //    will fire from chunk-5d on this branch only.
        //  - Pending possession : no vault row yet. Inserted capture with
        //    is_primary = true so `confirmPossession(captureId)` later
        //    picks it up without a second write. If the user dismisses
        //    instead, the row stays orphan (D24 expected behavior).
        val autoFillEmptyPrimary = existingVault != null && existingPrimary == null
        val promotesByQuality = existingPrimary != null &&
            score.aggregate > existingPrimary.qualityScore
        val isPending = existingVault == null
        val shouldBePrimary = autoFillEmptyPrimary || promotesByQuality || isPending

        val capture = CoinCaptureEntity(
            captureId = captureId,
            eurioId = eurioId,
            capturedAt = System.currentTimeMillis(),
            imageFilename = filename,
            qualityScore = score.aggregate,
            isPrimary = shouldBePrimary,
            captureMetadataJson = CaptureMetadata.encode(metadata),
            lowQualityFlag = !score.passes.all,
        )

        try {
            dao.insertCapture(capture)
        } catch (e: Exception) {
            // Roll back the file so we don't leave a dangling JPEG.
            filesystem.delete(filename)
            Log.e(TAG, "insertCapture failed", e)
            return ArchiveResult.Failure("insertCapture: ${e.message}")
        }

        if (shouldBePrimary && existingVault != null) {
            // promotePrimary swaps is_primary across siblings + bumps
            // primary_capture_id on coin_in_vault.
            dao.promotePrimary(eurioId, captureId)
        }

        return ArchiveResult.Success(
            captureId = captureId,
            filename = filename,
            isPossessed = existingVault != null,
            promoted = promotesByQuality,
            previousPrimaryId = if (promotesByQuality) existingPrimary?.captureId else null,
        )
    }

    /**
     * Snackbar D17 undo path. Restores the previous primary capture as
     * the active one — does not delete the new capture. No-op if the
     * vault row is gone (user removed the coin while the snackbar was
     * showing).
     */
    suspend fun revertPrimary(eurioId: String, previousPrimaryId: String) {
        val vault = dao.getVault(eurioId) ?: return
        dao.setPrimary(eurioId, previousPrimaryId)
        dao.upsertVault(vault.copy(primaryCaptureId = previousPrimaryId))
    }

    private companion object {
        const val TAG = "VaultCaptureRepo"
    }
}
