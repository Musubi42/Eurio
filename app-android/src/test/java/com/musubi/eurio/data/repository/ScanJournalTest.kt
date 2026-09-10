package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.ScanEventDao
import com.musubi.eurio.data.local.entities.ScanEventEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

/**
 * D5 — le compteur local de scans aboutis.
 *
 * Ce que ces tests protègent, dans l'ordre où ça a failli déraper :
 *  1. le regroupement par jour se fait en **fuseau local**, pas en UTC ;
 *  2. un scan abouti écrit **une** ligne, avec l'`eurio_id` scanné ;
 *  3. le décorateur [JournalingVaultRepository] journalise **avant** de
 *     déléguer, et journalise **aussi** quand la pièce est déjà possédée
 *     (le délégué, lui, fait no-op — D14) ;
 *  4. la plus longue série consécutive, qui est la mesure du critère 4.5.
 *
 * Le SQL réel du DAO est vérifié séparément, sur device, par
 * `src/androidTest/.../ScanEventDaoTest.kt` : Room ne s'instancie pas sur la
 * JVM sans Robolectric, et l'étape 4 interdit d'ajouter une dépendance.
 */
class ScanJournalTest {

    /** Double en mémoire du DAO — même contrat, sans Android. */
    private class FakeScanEventDao : ScanEventDao {
        val rows = mutableListOf<ScanEventEntity>()
        private var nextId = 1L

        override suspend fun insert(event: ScanEventEntity) {
            rows += event.copy(id = nextId++)
        }

        override suspend fun countAll(): Int = rows.size

        override suspend fun countSince(sinceMillis: Long): Int =
            rows.count { it.occurredAt >= sinceMillis }

        override suspend fun allTimestamps(): List<Long> =
            rows.map { it.occurredAt }.sorted()

        override suspend fun all(): List<ScanEventEntity> =
            rows.sortedBy { it.occurredAt }
    }

    private val paris = ZoneId.of("Europe/Paris")

    // Deux instants du MÊME jour UTC (2026-01-15) qui tombent sur deux jours
    // civils différents à Paris : 11 h 00 le 15, puis 00 h 30 le 16.
    private val paris_jan15_1100 = 1_768_471_200_000L // 2026-01-15T10:00:00Z
    private val paris_jan16_0030 = 1_768_519_800_000L // 2026-01-15T23:30:00Z

    @Test
    fun recordScan_ecritUneLigneHorodateeAvecLaPiece() = runBlocking {
        val dao = FakeScanEventDao()
        val repo = RoomScanJournalRepository(dao, paris) { 1_700_000_000_000L }

        repo.recordScan("fr-2eur-2024-jo")

        assertEquals(1, dao.rows.size)
        assertEquals("fr-2eur-2024-jo", dao.rows[0].eurioId)
        assertEquals(1_700_000_000_000L, dao.rows[0].occurredAt)
        assertEquals(1, repo.totalScans())
    }

    @Test
    fun distinctScanDays_regroupeEnFuseauLocalPasEnUtc() = runBlocking {
        val dao = FakeScanEventDao()
        var clock = paris_jan15_1100
        val repo = RoomScanJournalRepository(dao, paris) { clock }

        repo.recordScan("fr-2eur-2024-jo")
        clock = paris_jan16_0030
        repo.recordScan("de-1eur-2002")

        // Deux jours civils parisiens — donc deux jours au compteur. Un
        // regroupement en UTC, celui qu'un `date(occurred_at/1000,'unixepoch')`
        // dans le DAO aurait donné, n'en verrait qu'un : la série de sept jours
        // se troue sans que personne le voie.
        assertEquals(
            listOf(LocalDate.of(2026, 1, 15), LocalDate.of(2026, 1, 16)),
            repo.distinctScanDays(),
        )
        assertEquals(
            listOf(LocalDate.of(2026, 1, 15)),
            ScanJournal.toDistinctDays(listOf(paris_jan15_1100, paris_jan16_0030), ZoneId.of("UTC")),
        )
    }

    @Test
    fun longestConsecutiveRun_compteLesJoursSuivis() {
        val d = { day: Int -> LocalDate.of(2026, 1, day) }
        assertEquals(0, ScanJournal.longestConsecutiveRun(emptyList()))
        assertEquals(1, ScanJournal.longestConsecutiveRun(listOf(d(3))))
        assertEquals(
            7,
            ScanJournal.longestConsecutiveRun((1..7).map { d(it) }),
        )
        // Un trou au milieu casse la série : 3 puis 2, pas 5.
        assertEquals(
            3,
            ScanJournal.longestConsecutiveRun(listOf(d(1), d(2), d(3), d(5), d(6))),
        )
        // Doublons et désordre ne gonflent pas la mesure.
        assertEquals(
            2,
            ScanJournal.longestConsecutiveRun(listOf(d(9), d(8), d(8), d(9))),
        )
    }

    @Test
    fun journalingVaultRepository_journaliseMemeSiLaPieceEstDejaPossedee() = runBlocking {
        val dao = FakeScanEventDao()
        val journal = RoomScanJournalRepository(dao, paris) { 1_700_000_000_000L }
        val delegate = RecordingVaultRepository(alreadyOwned = setOf("fr-2eur-2024-jo"))
        val repo = JournalingVaultRepository(delegate, journal)

        repo.confirmPossession("fr-2eur-2024-jo", captureId = null)
        repo.confirmPossession("de-1eur-2002", captureId = "capture-1")

        assertEquals(2, dao.rows.size)
        assertEquals(
            listOf("fr-2eur-2024-jo", "de-1eur-2002"),
            dao.rows.map { it.eurioId },
        )
        // Le délégué garde sa sémantique : il a bien été appelé les deux fois,
        // c'est lui qui décide du no-op.
        assertEquals(
            listOf("fr-2eur-2024-jo", "de-1eur-2002"),
            delegate.confirmed,
        )
    }

    @Test
    fun journalingVaultRepository_deleguelesLecturesSansLesJournaliser() = runBlocking {
        val dao = FakeScanEventDao()
        val journal = RoomScanJournalRepository(dao, paris) { 1_700_000_000_000L }
        val delegate = RecordingVaultRepository(alreadyOwned = setOf("fr-2eur-2024-jo"))
        val repo = JournalingVaultRepository(delegate, journal)

        assertTrue(repo.containsCoin("fr-2eur-2024-jo"))
        repo.removeCoin("fr-2eur-2024-jo")

        assertEquals(0, dao.rows.size)
        assertEquals(listOf("fr-2eur-2024-jo"), delegate.removed)
    }

    /** Délégué minimal : enregistre les appels, ne touche à aucune base. */
    private class RecordingVaultRepository(
        private val alreadyOwned: Set<String>,
    ) : VaultRepository {
        val confirmed = mutableListOf<String>()
        val removed = mutableListOf<String>()

        override suspend fun containsCoin(eurioId: String) = eurioId in alreadyOwned
        override suspend fun confirmPossession(eurioId: String, captureId: String?) {
            confirmed += eurioId
        }
        override fun observeTotalCount(): Flow<Int> = flowOf(alreadyOwned.size)
        override fun observeDistinctCoinCount(): Flow<Int> = flowOf(alreadyOwned.size)
        override fun observeVaultCoins(filter: VaultFilter, sort: VaultSort): Flow<List<VaultCoinItem>> =
            flowOf(emptyList())
        override suspend fun removeCoin(eurioId: String) {
            removed += eurioId
        }
        override fun observeAvailableCountries(): Flow<List<String>> = flowOf(emptyList())
    }
}
