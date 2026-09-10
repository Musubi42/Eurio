package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import com.musubi.eurio.data.local.entities.ScanEventEntity

/**
 * Accès au journal des scans aboutis (D5).
 *
 * Écriture unique : [insert], appelée par
 * [com.musubi.eurio.data.repository.ScanJournalRepository]. Aucune suppression
 * n'est exposée — le journal est append-only le temps de la piste interne ;
 * l'utilisateur qui veut l'effacer désinstalle l'app.
 */
@Dao
interface ScanEventDao {

    @Insert
    suspend fun insert(event: ScanEventEntity)

    @Query("SELECT COUNT(*) FROM scan_events")
    suspend fun countAll(): Int

    @Query("SELECT COUNT(*) FROM scan_events WHERE occurred_at >= :sinceMillis")
    suspend fun countSince(sinceMillis: Long): Int

    /**
     * Tous les horodatages, du plus ancien au plus récent. C'est la sortie
     * brute que le dump de debug sérialise ; le regroupement par jour se fait
     * hors DAO (fuseau horaire local), dans [com.musubi.eurio.data.repository.ScanJournal].
     */
    @Query("SELECT occurred_at FROM scan_events ORDER BY occurred_at ASC")
    suspend fun allTimestamps(): List<Long>

    @Query("SELECT * FROM scan_events ORDER BY occurred_at ASC")
    suspend fun all(): List<ScanEventEntity>
}
