package com.musubi.eurio.features.dev.status

import java.io.File

/**
 * Generic read-only scanner for the ephemeral debug categories (photo_snaps,
 * scan_sessions, bench) surfaced by `/dev/status` (cf.
 * docs/operations/debug-data-taxonomy.md §6.3). Unlike the capture-cohort view —
 * which is structured against [com.musubi.eurio.features.scan.CaptureProtocol] —
 * these categories have no fixed protocol, so we just dump a flat
 * "tree + count + size" summary.
 *
 * Strictly read-only : walks the filesystem, never writes nor deletes.
 */
object DebugCategoryReader {

    /** A debug category (one sub-directory) with its aggregate counts + entries. */
    data class Category(
        val label: String,
        /** True if the directory exists on disk (vs. never written / already cleaned). */
        val present: Boolean,
        val fileCount: Int,
        val totalBytes: Long,
        /** Immediate children, newest-name last (sorted), for a flat dump. */
        val entries: List<Entry>,
    )

    /** One immediate child of a category dir (a session/snap folder or a loose file). */
    data class Entry(
        val name: String,
        val isDirectory: Boolean,
        val fileCount: Int,
        val totalBytes: Long,
    )

    /**
     * Scan [dir] into a [Category]. A null or missing directory yields an
     * empty, `present = false` category (so the UI can show "vide / non écrit").
     */
    fun read(label: String, dir: File?): Category {
        if (dir == null || !dir.isDirectory) {
            return Category(label, present = false, fileCount = 0, totalBytes = 0L, entries = emptyList())
        }
        val children = dir.listFiles()?.sortedBy { it.name } ?: emptyList()
        val entries = children.map { child ->
            if (child.isDirectory) {
                val (count, bytes) = walk(child)
                Entry(child.name, isDirectory = true, fileCount = count, totalBytes = bytes)
            } else {
                Entry(child.name, isDirectory = false, fileCount = 1, totalBytes = child.length())
            }
        }
        return Category(
            label = label,
            present = true,
            fileCount = entries.sumOf { it.fileCount },
            totalBytes = entries.sumOf { it.totalBytes },
            entries = entries,
        )
    }

    /** Recursively count regular files + total bytes under [root]. */
    private fun walk(root: File): Pair<Int, Long> {
        var count = 0
        var bytes = 0L
        root.walkTopDown().forEach { f ->
            if (f.isFile) {
                count++
                bytes += f.length()
            }
        }
        return count to bytes
    }

    /** Human-readable byte size (B / KB / MB), single source for the status screen. */
    fun formatBytes(bytes: Long): String = when {
        bytes >= 1_000_000L -> "%.1f MB".format(bytes / 1_000_000.0)
        bytes >= 1_000L -> "%.0f KB".format(bytes / 1_000.0)
        else -> "$bytes B"
    }
}
