// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.app.Application
import android.bluetooth.BluetoothManager
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/** The roast link on a Skywalker V1's SkyCommand box: its own channels, `OT1;50` commands, LF-ended frames. */
@RunWith(RobolectricTestRunner::class)
@Config(shadows = [RecordingGatt::class])
class SkyCommandLinkTest {
    private val app: Application = RuntimeEnvironment.getApplication()
    private lateinit var link: Tc4Link
    private lateinit var bench: Tc4Bench

    @Before
    fun setUp() {
        RecordingGatt.offeredServices = listOf(RecordingGatt.SKYCOMMAND)
        shadowOf(app.getSystemService(BluetoothManager::class.java).adapter).setEnabled(true)
        link = Tc4Link(app) {}
        bench = Tc4Bench(link, RecordingGatt.SKY_RX, eol = "\n")
    }

    @After
    fun tearDown() {
        RecordingGatt.offeredServices = RecordingGatt.V2
    }

    @Test
    fun theBoxIsReachedAndItsBurnerVerifiedAtZeroInItsOwnWriting() {
        link.connect(ADDRESS, roast = true)
        val g = bench.bringUp() // LF-ended frames: the burner echo is read and the link connects
        val sent = bench.sent(g)
        assertEquals("CHAN;1200", sent.first())
        assertTrue("burner not asserted off: $sent", sent.contains("OT1;0"))
        assertFalse("comma command sent to the box: $sent", sent.any { it.startsWith("OT") && it.contains(",") })
    }

    @Test
    fun theLeversReachTheBoxAsItReadsThem() {
        link.connect(ADDRESS, roast = true)
        val g = bench.bringUp()
        link.command(listOf("OT1,55", "OT2,40", "DRUM,100")); bench.run()
        val sent = bench.sent(g)
        assertTrue("commands not sent as CMD;value: $sent", sent.containsAll(listOf("OT1;55", "OT2;40", "DRUM;100")))
        assertEquals(55, bench.field("cmdBurner"))
    }

    @Test
    fun lettingGoStopsTheBox() {
        link.connect(ADDRESS)
        val g = bench.bringUp()
        link.disconnect(); bench.run()
        val sent = bench.sent(g)
        assertEquals(listOf("OT1;0", "OFF"), sent.takeLast(2))
    }
}
