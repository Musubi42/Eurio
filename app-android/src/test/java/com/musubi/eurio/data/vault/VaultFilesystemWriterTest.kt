package com.musubi.eurio.data.vault

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * JVM unit tests for [VaultFilesystemWriter]. Uses [TemporaryFolder] as
 * the vault root so we don't need an Android [android.content.Context].
 */
class VaultFilesystemWriterTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var vaultDir: File
    private lateinit var writer: VaultFilesystemWriter

    @Before
    fun setUp() {
        vaultDir = tmp.newFolder("vault")
        writer = VaultFilesystemWriter(vaultDir)
    }

    @Test
    fun write_persistsBytes_andNoTmpRemains() = runBlocking {
        val payload = byteArrayOf(0x01, 0x02, 0x03, 0x04)
        writer.write("cap-1.jpg", payload)

        val target = File(vaultDir, "cap-1.jpg")
        assertTrue("final file should exist", target.exists())
        assertArrayEquals(payload, target.readBytes())
        assertFalse("tmp file should be gone", File(vaultDir, "cap-1.jpg.tmp").exists())
    }

    @Test
    fun write_overwritesExistingFile() = runBlocking {
        writer.write("cap-1.jpg", byteArrayOf(0))
        writer.write("cap-1.jpg", byteArrayOf(1, 2, 3))

        assertArrayEquals(byteArrayOf(1, 2, 3), File(vaultDir, "cap-1.jpg").readBytes())
    }

    @Test(expected = IllegalArgumentException::class)
    fun write_rejectsPathTraversal() = runBlocking<Unit> {
        writer.write("../escape.jpg", byteArrayOf(0))
    }

    @Test(expected = IllegalArgumentException::class)
    fun write_rejectsEmptyFilename() = runBlocking<Unit> {
        writer.write("", byteArrayOf(0))
    }

    @Test
    fun delete_returnsFalseForMissing() = runBlocking {
        assertFalse(writer.delete("never-existed.jpg"))
    }

    @Test
    fun cleanupOrphans_removesTmpAndUnknownFinals_keepsKnown() = runBlocking {
        // Seed: known final, unknown final, orphan tmp.
        File(vaultDir, "keep.jpg").writeBytes(byteArrayOf(1))
        File(vaultDir, "drop.jpg").writeBytes(byteArrayOf(2))
        File(vaultDir, "orphan.jpg.tmp").writeBytes(byteArrayOf(3))

        val removed = writer.cleanupOrphans(setOf("keep.jpg"))

        assertEquals(2, removed)
        assertTrue(File(vaultDir, "keep.jpg").exists())
        assertFalse(File(vaultDir, "drop.jpg").exists())
        assertFalse(File(vaultDir, "orphan.jpg.tmp").exists())
    }

    @Test
    fun cleanupOrphans_emptyDir_returnsZero() = runBlocking {
        assertEquals(0, writer.cleanupOrphans(emptySet()))
    }
}
