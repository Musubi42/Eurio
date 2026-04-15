package com.musubi.eurio.data.local

import android.util.Log
import androidx.room.TypeConverter
import com.musubi.eurio.domain.IssueType
import com.musubi.eurio.domain.ScanSource
import com.musubi.eurio.domain.SetKind

// Converters Room — uniquement ce qu'on stocke vraiment côté local.
// Les JSONB criteria de Supabase sont gardés en String brute et parsés à l'usage.
class Converters {
    @TypeConverter
    fun issueTypeToString(value: IssueType?): String? = value?.wireValue

    @TypeConverter
    fun stringToIssueType(value: String?): IssueType? = IssueType.fromWire(value)

    @TypeConverter
    fun setKindToString(value: SetKind): String = value.wireValue

    @TypeConverter
    fun stringToSetKind(value: String): SetKind {
        val parsed = SetKind.fromWire(value)
        if (parsed == null) {
            Log.w(TAG, "SetKind inconnu en base : '$value' → fallback CURATED (indice d'un schéma obsolète)")
        }
        return parsed ?: SetKind.CURATED
    }

    @TypeConverter
    fun scanSourceToString(value: ScanSource): String = value.wireValue

    @TypeConverter
    fun stringToScanSource(value: String): ScanSource = ScanSource.fromWire(value)

    private companion object {
        const val TAG = "EurioConverters"
    }
}
