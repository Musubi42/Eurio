package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Une ligne par **scan abouti** — le journal minimal de D5.
 *
 * Sert à répondre à une seule question, celle du critère 4.5 de
 * `docs/work-in-progress/de-la-base-a-la-nef/PLAN.md` : *pendant les sept
 * jours de la piste interne, l'app a-t-elle été utilisée chaque jour par
 * quelqu'un d'autre que le PO ?*
 *
 * Ce que la table porte volontairement :
 *  - `occurredAt` : epoch millis du moment où le scan a abouti.
 *  - `eurioId` : la pièce reconnue, pour distinguer sept scans de la même
 *    pièce d'un vrai usage. Rien de plus.
 *
 * Ce qu'elle ne porte PAS, et pourquoi :
 *  - aucune image, aucune coordonnée, aucun identifiant d'appareil — le
 *    compteur doit rester montrable à un testeur sans discussion ;
 *  - **aucune foreign key vers `coins`** : la migration 3→4 a montré qu'un
 *    changement de catalogue `DROP TABLE coins`, et une cascade effacerait
 *    silencieusement le journal. Un scan a eu lieu même si la pièce disparaît
 *    du catalogue.
 *
 * Rien ne lit cette table dans l'UI (R1 : aucune scène proto ne l'expose).
 * Lecture : cf. `docs/work-in-progress/de-la-base-a-la-nef/PLAY-INTERNE.md`
 * §« Lire le compteur ».
 */
@Entity(
    tableName = "scan_events",
    indices = [Index("occurred_at")],
)
data class ScanEventEntity(
    @PrimaryKey(autoGenerate = true)
    @ColumnInfo(name = "id")
    val id: Long = 0L,

    @ColumnInfo(name = "eurio_id")
    val eurioId: String,

    @ColumnInfo(name = "occurred_at")
    val occurredAt: Long,
)
