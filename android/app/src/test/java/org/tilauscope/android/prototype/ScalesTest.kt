// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The frames of the desktop drivers (tilauscope/scales/decent.py, bookoo.py), read the same way. */
class ScalesTest {
    private fun bytes(vararg values: Int) = ByteArray(values.size) { values[it].toByte() }
    private fun withXor(vararg values: Int): ByteArray {
        val body = bytes(*values)
        return body + byteArrayOf(body.fold(0) { acc, b -> acc xor (b.toInt() and 0xff) }.toByte())
    }

    @Test
    fun theProtocolFollowsTheSavedName() {
        assertEquals(ScaleKind.DECENT, scaleKind("Decent Scale 1A2B"))
        assertEquals(ScaleKind.BOOKOO, scaleKind("BOOKOO_SC 01"))
        assertEquals(ScaleKind.BOOKOO, scaleKind("")) // recognised by its service alone
        assertEquals(ScaleKind.ACAIA, scaleKind("LUNAR-123456"))
    }

    @Test
    fun decentWeightsAreSignedTenthsWithTheScalesOwnStableFlag() {
        val stable = DecentLink.parse(withXor(0x03, 0xCE, 0x04, 0xD2, 0x00, 0x00))!!
        assertEquals(123.4, stable.grams, 1e-9)
        assertTrue(stable.stable)
        val changing = DecentLink.parse(withXor(0x03, 0xCA, 0xFF, 0x9C, 0x00, 0x00, 0x00, 0x00, 0x00))!! // 10-byte firmware
        assertEquals(-10.0, changing.grams, 1e-9)
        assertFalse(changing.stable)
    }

    @Test
    fun decentRejectsWhatTheDesktopRejects() {
        assertNull(DecentLink.parse(bytes(0x03, 0xCE, 0x04, 0xD2, 0x00, 0x00, 0x00))) // checksum
        assertNull(DecentLink.parse(withXor(0x04, 0xCE, 0x04, 0xD2, 0x00, 0x00))) // header
        assertNull(DecentLink.parse(withXor(0x03, 0xCE, 0x04, 0xD2, 0x00))) // length
        assertNull(DecentLink.parse(withXor(0x03, 0xAA, 0x01, 0x01, 0x00, 0x00))) // a button, not a weight
    }

    @Test
    fun decentCommandsAreTheDesktops() {
        assertArrayEquals(bytes(0x03, 0x0F, 0, 0, 0, 0, 0x0C), DecentLink.TARE)
        assertArrayEquals(withXor(0x03, 0x0A, 0x03, 0xFF, 0xFF, 0x00), DecentLink.HEARTBEAT)
    }

    @Test
    fun bookooWeightsAreSignedHundredthsWithoutStableFlag() {
        fun frame(sign: Int) = withXor(0x03, 0x0B, 0, 0, 0, 0, sign, 0x00, 0x30, 0x39, 0, 0, 0, 87, 0, 0, 0, 0, 0)
        val positive = BookooLink.parse(frame(0x2B))!!
        assertEquals(123.45, positive.grams, 1e-9)
        assertFalse(positive.stable)
        assertEquals(87, positive.battery)
        assertEquals(-123.45, BookooLink.parse(frame(0x2D))!!.grams, 1e-9)
        val broken = frame(0x2B).also { it[19] = (it[19] + 1).toByte() }
        assertNull(BookooLink.parse(broken))
        assertNull(BookooLink.parse(frame(0x2B).copyOf(19)))
    }

    @Test
    fun bookooTareIsTheDesktops() {
        assertArrayEquals(withXor(0x03, 0x0A, 0x01, 0x00, 0x00), BookooLink.TARE)
    }

    @Test
    fun anUnflaggedWeightIsStableOnceItHasHeld() {
        val weight = SettledWeight()
        weight.update(250.2, false, 1_000)
        assertFalse(weight.stable(1_000))
        weight.update(250.4, false, 1_200) // within the tolerance: the hold goes on
        assertTrue(weight.stable(1_000 + SettledWeight.SETTLE_MS))
        weight.update(251.0, false, 1_400) // moved: the hold starts again
        assertFalse(weight.stable(1_500))
        weight.update(251.0, true, 1_500) // flagged by the scale: stable at once
        assertTrue(weight.stable(1_500))
    }

    @Test
    fun aReadingFlickeringAcrossAGramStillSettles() {
        val weight = SettledWeight()
        var now = 1_000L
        for (grams in listOf(249.4, 249.6, 249.4, 249.6, 249.5, 249.6)) {
            weight.update(grams, false, now)
            now += 100
        }
        assertTrue(weight.stable(1_000 + SettledWeight.SETTLE_MS))
    }
}
