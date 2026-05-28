package com.musubi.eurio.features.scan

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tests pour CaptureProtocol focalisés sur la directive `# mode=ablation` qui
 * bascule entre les 6 steps LEGACY × 1 photo et les 5 steps ABLATION × 4 photos.
 *
 * Pas de Context Android : on appelle directement `parseCsv` (internal).
 */
class CaptureProtocolTest {

    @After
    fun reset() {
        CaptureProtocol.resetForTests()
    }

    @Test
    fun `csv sans directive reste en LEGACY`() {
        val csv = listOf(
            "eurio_id;numista_id;display_name",
            "fr-2018-2eur-simone-veil;141382;Simone Veil",
            "be-2020-2eur-jan-van-eyck;217733;Jan van Eyck",
        )
        val coins = CaptureProtocol.applyCsvForTests(csv)
        assertEquals(2, coins.size)
        assertEquals(CaptureProtocol.Mode.LEGACY, CaptureProtocol.mode)
        assertEquals(6, CaptureProtocol.steps.size)
        assertEquals(1, CaptureProtocol.photosPerStep)
    }

    @Test
    fun `directive mode=ablation bascule en ABLATION`() {
        val csv = listOf(
            "# mode=ablation",
            "eurio_id;numista_id;display_name",
            "fr-2018-2eur-simone-veil;141382;Simone Veil",
        )
        @Suppress("UNUSED_VARIABLE")
        val coins = CaptureProtocol.applyCsvForTests(csv)
        assertEquals(1, coins.size)
        assertEquals(CaptureProtocol.Mode.ABLATION, CaptureProtocol.mode)
        assertEquals(5, CaptureProtocol.steps.size)
        assertEquals(4, CaptureProtocol.photosPerStep)
    }

    @Test
    fun `directive mode=legacy force LEGACY explicitement`() {
        val csv = listOf(
            "# mode=legacy",
            "eurio_id;numista_id;display_name",
            "fr-2018-2eur-simone-veil;141382;Simone Veil",
        )
        CaptureProtocol.applyCsvForTests(csv)
        assertEquals(CaptureProtocol.Mode.LEGACY, CaptureProtocol.mode)
    }

    @Test
    fun `ABLATION conditions matchent BenchProtocol`() {
        val csv = listOf("# mode=ablation", "fr;1;Test")
        CaptureProtocol.applyCsvForTests(csv)
        val expectedIds = listOf("bright_plain", "bright_textured", "dim",
                                  "oblique", "glare_specular")
        assertEquals(expectedIds, CaptureProtocol.steps.map { it.id })
    }

    @Test
    fun `totalSnaps inclut photosPerStep`() {
        val csv = listOf(
            "# mode=ablation",
            "fr-1;1;a", "fr-2;2;b", "fr-3;3;c",
        )
        CaptureProtocol.applyCsvForTests(csv)
        // 3 coins × 5 conditions × 4 photos = 60
        assertEquals(60, CaptureProtocol.totalSnaps)
    }

    @Test
    fun `commentaire non-directive est ignoré`() {
        val csv = listOf(
            "# just a comment",
            "# mode=ablation",
            "fr-1;1;a",
        )
        CaptureProtocol.applyCsvForTests(csv)
        assertEquals(CaptureProtocol.Mode.ABLATION, CaptureProtocol.mode)
    }

    @Test
    fun `directive avec espaces autour est tolérée`() {
        val csv = listOf(
            "#  mode=ablation  ",
            "fr-1;1;a",
        )
        CaptureProtocol.applyCsvForTests(csv)
        assertEquals(CaptureProtocol.Mode.ABLATION, CaptureProtocol.mode)
    }

    @Test
    fun `directive valeur inconnue n'écrase pas le default`() {
        val csv = listOf(
            "# mode=garbage",
            "fr-1;1;a",
        )
        CaptureProtocol.applyCsvForTests(csv)
        // Reste LEGACY (default initial), pas de crash
        assertEquals(CaptureProtocol.Mode.LEGACY, CaptureProtocol.mode)
    }

    @Test
    fun `LEGACY conditions inchangées (zero régression)`() {
        val csv = listOf("fr-1;1;a")
        CaptureProtocol.applyCsvForTests(csv)
        val expectedIds = listOf("bright_plain", "dim_plain", "daylight_plain",
                                  "bright_textured", "tilt_plain", "close_plain")
        assertEquals(expectedIds, CaptureProtocol.steps.map { it.id })
    }
}
