package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.ScanEventDao
import com.musubi.eurio.data.local.entities.ScanEventEntity
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Le compteur local de D5 : un scan abouti laisse une trace horodatée.
 *
 * Pourquoi un compteur et pas un ping réseau : l'app est offline-first, et le
 * chantier ouvre la piste interne avec **ce qui existe** (D4). Zéro requête
 * ajoutée, zéro dépendance, rien qui quitte le téléphone.
 *
 * **Il n'y a aucune UI.** R1 interdit d'inventer une scène Android sans
 * équivalent proto ; le geste d'export (partager depuis le Profil) exige une
 * scène que le PO n'a pas encore tranchée. Le compteur se lit aujourd'hui
 * depuis une machine de dev — cf. `PLAY-INTERNE.md` §« Lire le compteur ».
 */
interface ScanJournalRepository {
    /** Enregistre un scan abouti sur la pièce [eurioId]. */
    suspend fun recordScan(eurioId: String)

    /** Nombre total de scans aboutis depuis l'installation. */
    suspend fun totalScans(): Int

    /**
     * Les jours distincts (fuseau local) où au moins un scan a abouti, du plus
     * ancien au plus récent. C'est la mesure exacte du critère 4.5.
     */
    suspend fun distinctScanDays(): List<LocalDate>
}

class RoomScanJournalRepository(
    private val dao: ScanEventDao,
    private val zone: ZoneId = ZoneId.systemDefault(),
    private val now: () -> Long = System::currentTimeMillis,
) : ScanJournalRepository {

    override suspend fun recordScan(eurioId: String) {
        dao.insert(ScanEventEntity(eurioId = eurioId, occurredAt = now()))
    }

    override suspend fun totalScans(): Int = dao.countAll()

    override suspend fun distinctScanDays(): List<LocalDate> =
        ScanJournal.toDistinctDays(dao.allTimestamps(), zone)
}

/**
 * Le regroupement par jour, isolé du DAO pour être testable sans Android.
 *
 * Le bucketing ne peut pas descendre dans SQLite : `date(occurred_at/1000,
 * 'unixepoch')` regrouperait en **UTC**, si bien qu'un scan à 23 h 30 à Paris
 * en hiver tomberait dans la veille et un « sept jours consécutifs » se
 * trouerait sans que personne le voie. Le fuseau local est appliqué ici.
 */
object ScanJournal {
    fun toDistinctDays(timestampsMillis: List<Long>, zone: ZoneId): List<LocalDate> =
        timestampsMillis
            .map { Instant.ofEpochMilli(it).atZone(zone).toLocalDate() }
            .distinct()
            .sorted()

    /**
     * La plus longue série de jours consécutifs présente dans [days].
     * `0` si la liste est vide.
     */
    fun longestConsecutiveRun(days: List<LocalDate>): Int {
        val sorted = days.distinct().sorted()
        if (sorted.isEmpty()) return 0
        var best = 1
        var current = 1
        for (i in 1 until sorted.size) {
            current = if (sorted[i - 1].plusDays(1) == sorted[i]) current + 1 else 1
            if (current > best) best = current
        }
        return best
    }
}

/**
 * Décorateur : toute confirmation de possession laisse d'abord sa trace au
 * journal, puis suit son cours normal.
 *
 * Ce point d'accroche a été choisi parce que c'est le **seul** endroit où le
 * scan est déclaré abouti, et parce qu'il vit dans `data/` : le contrat de
 * l'étape 4 interdit de toucher à `features/`, et la délégation d'interface
 * Kotlin évite d'aller modifier [RoomVaultRepository], dont la sémantique
 * (« no-op si déjà possédée », D14) doit rester intacte.
 *
 * Limite assumée, à connaître avant de lire le compteur : un re-scan d'une
 * pièce **déjà possédée** n'appelle pas `confirmPossession` (le ViewModel
 * court-circuite l'acquittement « déjà dans le coffre »), donc il ne compte
 * pas. Le journal mesure « un scan qui a mené au coffre », pas « une
 * reconnaissance réussie ».
 */
class JournalingVaultRepository(
    private val delegate: VaultRepository,
    private val journal: ScanJournalRepository,
) : VaultRepository by delegate {

    override suspend fun confirmPossession(eurioId: String, captureId: String?) {
        journal.recordScan(eurioId)
        delegate.confirmPossession(eurioId, captureId)
    }
}
