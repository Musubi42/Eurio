package com.musubi.eurio.debug

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.musubi.eurio.EurioApp
import com.musubi.eurio.data.repository.ScanJournal
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Lit le compteur de scans (D5) et le recrache dans logcat. **Build debug
 * uniquement** — ce fichier vit dans `src/debug/`, il n'est pas compilé dans
 * l'APK release livré aux testeurs.
 *
 *     adb shell am broadcast -a com.musubi.eurio.DUMP_SCAN_JOURNAL \
 *       -n com.musubi.eurio/com.musubi.eurio.debug.ScanJournalDumpReceiver
 *     adb logcat -d ScanJournal:D '*:S'
 *
 * Pourquoi un receiver et pas un écran : R1 interdit d'inventer une scène
 * Android sans équivalent proto. Pourquoi debug seulement : un canal de dump
 * exporté dans le build du Play Store serait une porte ouverte, et
 * `adb shell run-as` est de toute façon indisponible sur un APK non
 * debuggable. Conséquence assumée : **le compteur d'un testeur n'est pas
 * lisible à distance** — cf. `PLAY-INTERNE.md` §« Lire le compteur ».
 */
class ScanJournalDumpReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext as? EurioApp ?: run {
            Log.e(TAG, "contexte inattendu : ${context.applicationContext}")
            return
        }
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val total = app.scanJournalRepository.totalScans()
                val days = app.scanJournalRepository.distinctScanDays()
                Log.i(TAG, "scans aboutis (total) = $total")
                Log.i(TAG, "jours distincts = ${days.size}")
                Log.i(TAG, "plus longue série consécutive = ${ScanJournal.longestConsecutiveRun(days)}")
                days.forEach { Log.i(TAG, "jour $it") }
            } catch (e: Exception) {
                Log.e(TAG, "dump impossible", e)
            } finally {
                pending.finish()
            }
        }
    }

    private companion object {
        const val TAG = "ScanJournal"
    }
}
