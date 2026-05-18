package com.musubi.eurio.data.vault

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException

/**
 * Owns the `vault/` directory under app-private storage and writes
 * archived JPEGs there atomically.
 *
 * Layout:
 *   `<context.filesDir>/vault/<capture-id>.jpg`
 *
 * Atomicity: write to `<filename>.tmp` first, then rename to the final
 * name. If the process dies between the tmp write and the rename, the
 * tmp file is orphan but no partially-written final file exists →
 * Room's `coin_captures` row never references missing/corrupt bytes.
 * [cleanupOrphans] sweeps stale `.tmp` files and any final file no
 * longer referenced by the DB.
 *
 * Thread: all I/O happens on [Dispatchers.IO]. Calls are suspend so
 * the caller doesn't need to wrap.
 */
class VaultFilesystemWriter internal constructor(
    private val vaultDir: File,
) {
    init {
        vaultDir.mkdirs()
    }

    /** Production constructor — vault dir lives under app-private storage. */
    constructor(context: Context) : this(File(context.filesDir, "vault"))

    /** Absolute path of [filename] under the vault dir. The file may or may not exist. */
    fun fileFor(filename: String): File = File(vaultDir, filename)

    /**
     * Atomically write [bytes] to [filename]. Throws [IOException] if
     * either the tmp write or the rename fails; the caller is expected
     * to propagate (we never want to insert a `coin_captures` row that
     * points at missing bytes).
     */
    suspend fun write(filename: String, bytes: ByteArray) = withContext(Dispatchers.IO) {
        require(filename.isNotEmpty()) { "filename must not be empty" }
        require(!filename.contains('/') && !filename.contains('\\')) {
            "filename must be a leaf name, got '$filename'"
        }
        val target = File(vaultDir, filename)
        val tmp = File(vaultDir, "$filename.tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(target)) {
            tmp.delete()
            throw IOException("atomic rename failed for $filename")
        }
    }

    /** Delete a final file. Returns true if the file existed and was deleted. */
    suspend fun delete(filename: String): Boolean = withContext(Dispatchers.IO) {
        File(vaultDir, filename).delete()
    }

    /**
     * Sweep the vault dir: delete any leftover `.tmp` files (orphaned by
     * a crashed write) and any final `.jpg` whose name is not in
     * [knownFilenames]. Cheap to run on app startup or via a periodic
     * worker — directory listing is the only allocation.
     *
     * Returns the count of files removed for observability.
     */
    suspend fun cleanupOrphans(knownFilenames: Set<String>): Int = withContext(Dispatchers.IO) {
        var removed = 0
        vaultDir.listFiles()?.forEach { file ->
            val name = file.name
            val shouldDelete = name.endsWith(".tmp") || name !in knownFilenames
            if (shouldDelete && file.delete()) removed++
        }
        removed
    }
}
