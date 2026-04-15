package com.musubi.eurio.domain

// Mirror de l'enum PostgreSQL `set_kind`.
enum class SetKind(val wireValue: String) {
    STRUCTURAL("structural"),
    CURATED("curated"),
    PARAMETRIC("parametric");

    companion object {
        fun fromWire(value: String?): SetKind? =
            value?.let { v -> entries.firstOrNull { it.wireValue == v } }
    }
}
