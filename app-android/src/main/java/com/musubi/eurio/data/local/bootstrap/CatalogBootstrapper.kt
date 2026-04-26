package com.musubi.eurio.data.local.bootstrap

import android.content.Context
import android.util.Log
import androidx.room.withTransaction
import com.musubi.eurio.data.local.EurioDatabase
import com.musubi.eurio.data.local.entities.CatalogMetaEntity
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.data.local.entities.CoinSeriesEntity
import com.musubi.eurio.data.local.entities.SetEntity
import com.musubi.eurio.data.local.entities.SetMemberEntity
import com.musubi.eurio.domain.IssueType
import com.musubi.eurio.domain.SetKind
import java.time.Instant
import kotlinx.serialization.json.Json

// Bootstrap du catalogue au premier run : lit catalog_snapshot.json depuis
// assets/, peuple Room, marque bootstrap_at + catalog_version en meta.
//
// Idempotence : si la version packagée est <= à celle déjà en base, on no-op.
// Si elle est supérieure, on flush + repopule (réhydratation catalogue pur,
// les vault_entries ne sont jamais touchés ici).
class CatalogBootstrapper(
    private val context: Context,
    private val db: EurioDatabase,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    suspend fun runIfNeeded() {
        val meta = db.metaDao()
        val currentVersion = meta.getString(CatalogMetaEntity.KEY_CATALOG_VERSION)
        val packagedSnapshot = try {
            loadSnapshotFromAssets() ?: run {
                Log.w(TAG, "Snapshot packagé absent — skip bootstrap")
                return
            }
        } catch (t: Throwable) {
            Log.e(TAG, "Impossible de lire catalog_snapshot.json", t)
            return
        }

        // Garde-fou : un snapshot vide n'a aucune raison d'être appliqué (export bug).
        // On préfère garder la DB précédente plutôt que de wipe sans raison.
        if (packagedSnapshot.coins.isEmpty()) {
            Log.w(TAG, "Snapshot vide (0 coins) — abort bootstrap")
            return
        }

        if (!isPackagedNewer(currentVersion, packagedSnapshot.catalogVersion)) {
            Log.i(TAG, "Catalogue déjà à jour (local=$currentVersion, packagé=${packagedSnapshot.catalogVersion}) — skip")
            return
        }

        Log.i(
            TAG,
            "Bootstrap catalogue : local=$currentVersion → packagé=${packagedSnapshot.catalogVersion} " +
                "(${packagedSnapshot.coins.size} coins, ${packagedSnapshot.sets.size} sets, " +
                "${packagedSnapshot.setMembers.size} members)",
        )

        // withTransaction supporte les suspend functions contrairement à runInTransaction.
        // On ne clear PAS les tables catalogue : REPLACE suffit à mettre à jour les lignes
        // existantes, et on évite ainsi le CASCADE sur vault_entries (les scans user
        // resteraient orphelins si on droppait les coins en masse). Les lignes obsolètes
        // qui n'existent plus dans le snapshot restent en DB — acceptable pour v1 car
        // le catalogue JOUE ne supprime jamais de pièces (cas marginal).
        db.withTransaction {
            db.coinDao().insertAllSeries(packagedSnapshot.coinSeries.map { it.toEntity() })
            db.coinDao().insertAllCoins(packagedSnapshot.coins.map { it.toEntity() })
            db.setDao().insertAllSets(packagedSnapshot.sets.map { it.toEntity() })
            db.setDao().insertAllMembers(packagedSnapshot.setMembers.map { it.toEntity() })

            meta.putString(CatalogMetaEntity.KEY_CATALOG_VERSION, packagedSnapshot.catalogVersion)
            meta.putLong(CatalogMetaEntity.KEY_BOOTSTRAP_AT, System.currentTimeMillis())
        }

        Log.i(TAG, "Bootstrap terminé.")
    }

    // Compare deux timestamps ISO-8601 (UTC ou avec offset). Retourne true si `packaged`
    // est strictement plus récent que `local`. Évite le piège de la comparaison
    // lexicographique qui casse sur offsets mixtes ou millisecondes variables.
    private fun isPackagedNewer(local: String?, packaged: String): Boolean {
        if (local.isNullOrBlank()) return true
        return try {
            Instant.parse(packaged).isAfter(Instant.parse(local))
        } catch (t: Throwable) {
            Log.w(TAG, "Comparaison timestamp catalogue impossible ($local / $packaged) — assume newer", t)
            true
        }
    }

    private fun loadSnapshotFromAssets(): CatalogSnapshot? {
        return context.assets.open(SNAPSHOT_PATH).use { stream ->
            val text = stream.bufferedReader().readText()
            if (text.isBlank()) null else json.decodeFromString(CatalogSnapshot.serializer(), text)
        }
    }

    companion object {
        private const val TAG = "CatalogBootstrapper"
        private const val SNAPSHOT_PATH = "catalog_snapshot.json"
    }
}

// ─────────────── DTO → Entity mappings ───────────────

private fun CoinDto.toEntity(): CoinEntity = CoinEntity(
    eurioId = eurioId,
    numistaId = numistaId,
    country = country,
    year = year,
    faceValue = faceValue,
    issueType = IssueType.fromWire(issueType),
    seriesId = seriesId,
    nameFr = nameFr ?: name,
    nameEn = nameEn ?: name,
    imageObverseUrl = imageObverseUrl,
    imageReverseUrl = imageReverseUrl,
    mintage = mintage,
    isWithdrawn = isWithdrawn,
    withdrawalReason = withdrawalReason,
    designDescription = designDescription,
    themeCode = themeCode,
    obverseCxUv = obverseMeta?.cxUv,
    obverseCyUv = obverseMeta?.cyUv,
    obverseRadiusUv = obverseMeta?.radiusUv,
    reverseCxUv = reverseMeta?.cxUv,
    reverseCyUv = reverseMeta?.cyUv,
    reverseRadiusUv = reverseMeta?.radiusUv,
)

private fun CoinSeriesDto.toEntity(): CoinSeriesEntity = CoinSeriesEntity(
    id = id,
    country = country,
    designationFr = designationI18n?.get("fr") ?: designation,
    designationEn = designationI18n?.get("en"),
    mintingStartedAt = mintingStartedAt,
    mintingEndedAt = mintingEndedAt,
    mintingEndReason = mintingEndReason,
    supersedesSeriesId = supersedesSeriesId,
)

private fun SetDto.toEntity(): SetEntity = SetEntity(
    id = id,
    kind = SetKind.fromWire(kind) ?: SetKind.CURATED,
    nameFr = nameI18n["fr"] ?: nameI18n["en"] ?: id,
    nameEn = nameI18n["en"] ?: nameI18n["fr"] ?: id,
    descriptionFr = descriptionI18n?.get("fr"),
    descriptionEn = descriptionI18n?.get("en"),
    criteriaJson = criteria?.toString(),
    paramKey = paramKey,
    rewardJson = reward?.toString(),
    displayOrder = displayOrder,
    category = category,
    icon = icon,
    expectedCount = expectedCount,
    active = active,
)

private fun SetMemberDto.toEntity(): SetMemberEntity = SetMemberEntity(
    setId = setId,
    coinEurioId = eurioId,
    position = position,
)
