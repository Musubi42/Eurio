package com.musubi.eurio.domain

// Mirror de l'enum PostgreSQL `issue_type` défini dans
// supabase/migrations/20260415_cleanup_and_coin_series.sql
enum class IssueType(val wireValue: String, val labelFr: String) {
    CIRCULATION("circulation", "Circulation"),
    COMMEMO_NATIONAL("commemo-national", "Commémo nationale"),
    COMMEMO_COMMON("commemo-common", "Commémo commune"),
    STARTER_KIT("starter-kit", "Starter kit"),
    BU_SET("bu-set", "Brillant universel"),
    PROOF("proof", "Belle épreuve");

    companion object {
        fun fromWire(value: String?): IssueType? =
            value?.let { v -> entries.firstOrNull { it.wireValue == v } }
    }
}
