package com.musubi.eurio.domain

// Comment une pièce a été ajoutée au vault local.
enum class ScanSource(val wireValue: String) {
    SCAN("scan"),
    MANUAL_ADD("manual_add");

    companion object {
        fun fromWire(value: String?): ScanSource =
            value?.let { v -> entries.firstOrNull { it.wireValue == v } } ?: SCAN
    }
}
