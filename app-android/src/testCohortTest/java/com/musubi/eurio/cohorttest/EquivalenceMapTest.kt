package com.musubi.eurio.cohorttest

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Parity tests for [EquivalenceMap] vs `ml/eval/equivalence.py`. Mirrors
 * `ml/tests/test_equivalence.py` 1:1 — these verrouillent le **contrat**
 * de la règle d'équivalence design_group côté Android. Si ces tests
 * échouent ou divergent du bench Python, le matcher cohort-test produit
 * un verdict R@1 eq incohérent avec le bench. Cf.
 * `feedback_output_contract_parity.md`.
 */
class EquivalenceMapTest {

    private fun makeMap(): EquivalenceMap = EquivalenceMap(
        eurioToGroup = mapOf(
            "be-2007-2eur-treaty-of-rome" to "treaty-of-rome-2007",
            "de-2007-2eur-treaty-of-rome" to "treaty-of-rome-2007",
            "fr-2007-2eur-treaty-of-rome" to "treaty-of-rome-2007",
            "at-2002-2eur-standard" to null,
            "at-2008-2eur-standard" to null,
            "es-1999-2eur-standard" to null,
        ),
    )

    @Test
    fun strict_match_is_equivalent() {
        val m = makeMap()
        assertTrue(m.areEquivalent("at-2002-2eur-standard", "at-2002-2eur-standard"))
    }

    @Test
    fun same_design_group_is_equivalent() {
        val m = makeMap()
        assertTrue(
            m.areEquivalent(
                "be-2007-2eur-treaty-of-rome",
                "de-2007-2eur-treaty-of-rome",
            ),
        )
        assertTrue(
            m.areEquivalent(
                "fr-2007-2eur-treaty-of-rome",
                "be-2007-2eur-treaty-of-rome",
            ),
        )
    }

    @Test
    fun different_groups_not_equivalent() {
        val m = makeMap()
        assertFalse(
            m.areEquivalent(
                "at-2002-2eur-standard",
                "es-1999-2eur-standard",
            ),
        )
    }

    @Test
    fun null_group_means_no_equivalence_beyond_strict() {
        val m = makeMap()
        // Both have design_group=null → only strict eurio_id match counts.
        assertFalse(
            m.areEquivalent(
                "at-2002-2eur-standard",
                "at-2008-2eur-standard",
            ),
        )
    }

    @Test
    fun one_has_group_one_doesnt_not_equivalent() {
        val m = makeMap()
        assertFalse(
            m.areEquivalent(
                "be-2007-2eur-treaty-of-rome",
                "at-2002-2eur-standard",
            ),
        )
    }

    @Test
    fun unknown_eurio_id_not_equivalent() {
        val m = makeMap()
        // Unknown predicted → not equivalent to anything except strict self.
        assertFalse(
            m.areEquivalent("xx-9999-2eur-mystery", "at-2002-2eur-standard"),
        )
        assertTrue(
            m.areEquivalent("xx-9999-2eur-mystery", "xx-9999-2eur-mystery"),
        )
    }

    @Test
    fun design_group_lookup() {
        val m = makeMap()
        assertEquals(
            "treaty-of-rome-2007",
            m.designGroup("be-2007-2eur-treaty-of-rome"),
        )
        assertNull(m.designGroup("at-2002-2eur-standard"))
        assertNull(m.designGroup("xx-9999-2eur-mystery"))
    }

    @Test
    fun roundtrip_json() {
        val m = makeMap()
        val text = m.toJson()
        val m2 = EquivalenceMap.fromJson(text)
        assertEquals(m.eurioToGroup, m2.eurioToGroup)
        // Re-test a representative case to make sure the loaded map works.
        assertTrue(
            m2.areEquivalent(
                "be-2007-2eur-treaty-of-rome",
                "de-2007-2eur-treaty-of-rome",
            ),
        )
    }
}
