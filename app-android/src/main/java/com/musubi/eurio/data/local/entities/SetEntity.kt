package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import com.musubi.eurio.domain.SetKind

@Entity(
    tableName = "sets",
    indices = [
        Index("category"),
        Index("display_order"),
    ],
)
data class SetEntity(
    @PrimaryKey
    @ColumnInfo(name = "id")
    val id: String,

    @ColumnInfo(name = "kind")
    val kind: SetKind,

    @ColumnInfo(name = "name_fr")
    val nameFr: String,

    @ColumnInfo(name = "name_en")
    val nameEn: String,

    @ColumnInfo(name = "description_fr")
    val descriptionFr: String?,

    @ColumnInfo(name = "description_en")
    val descriptionEn: String?,

    // Le criteria JSON est stocké brut. Parsé uniquement à l'usage si besoin
    // (Phase 3 = on s'appuie sur set_members pré-matérialisé, pas sur le DSL runtime).
    @ColumnInfo(name = "criteria_json")
    val criteriaJson: String?,

    @ColumnInfo(name = "param_key")
    val paramKey: String?,

    // reward stocké en JSON brut (parsé en Phase 5)
    @ColumnInfo(name = "reward_json")
    val rewardJson: String?,

    @ColumnInfo(name = "display_order")
    val displayOrder: Int,

    @ColumnInfo(name = "category")
    val category: String,

    @ColumnInfo(name = "icon")
    val icon: String?,

    @ColumnInfo(name = "expected_count")
    val expectedCount: Int?,

    @ColumnInfo(name = "active")
    val active: Boolean = true,

    // Phase 3 : horodatage de la première complétion de ce set par l'utilisateur.
    // Null tant que non complété. Permet de déclencher la célébration une seule fois.
    @ColumnInfo(name = "completed_at")
    val completedAt: Long? = null,
)
