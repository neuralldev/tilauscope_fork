// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.app.Application
import android.bluetooth.BluetoothManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/** The roast link on a simulated roaster (audit 2026-10-25): what reaches the machine, command by command. */
@RunWith(RobolectricTestRunner::class)
@Config(shadows = [RecordingGatt::class])
class Tc4LinkTest {
    private val app: Application = RuntimeEnvironment.getApplication()
    private lateinit var link: Tc4Link
    private lateinit var bench: Tc4Bench

    @Before
    fun setUp() {
        shadowOf(app.getSystemService(BluetoothManager::class.java).adapter).setEnabled(true)
        link = Tc4Link(app) {}
        bench = Tc4Bench(link)
    }

    @Test
    fun anEndRoastLeftFromTheLastRoastIsNeverRunAtTheNextStart() {
        val end = listOf("OT1,0", "OT2,100", "UNTIL_BT_BELOW,50", "OFF")
        link.connect(ADDRESS, roast = true, endScript = end)
        bench.disconnected(bench.bringUp())
        assertEquals("reconnecting", bench.state())
        link.command(end) // End roast while the link is away
        link.disconnect(); bench.run()
        assertEquals("idle", bench.state())

        link.connect(ADDRESS, roast = true, endScript = end) // the next roast, same session
        val next = bench.bringUp()
        bench.run(POLL_MS)
        val commands = bench.sent(next)
        assertFalse("stale end script replayed: $commands", commands.any { it == "OT2,100" || it == "OFF" })
    }

    @Test
    fun heatAskedWhileTheLinkIsAwayNeverReachesTheRoasterAfterTheRecovery() {
        link.connect(ADDRESS, roast = true)
        bench.disconnected(bench.bringUp())
        assertEquals("reconnecting", bench.state())
        link.command(listOf("OT1,70", "OT2,40")) // an alarm or the slider while the link is away
        bench.run(500) // the first reconnection attempt
        val next = bench.bringUp()
        bench.run(POLL_MS)
        val commands = bench.sent(next)
        assertFalse("heat replayed after the recovery: $commands", commands.any { it.startsWith("OT1,") && it != "OT1,0" })
        assertEquals(0, bench.field("cmdBurner"))
        assertEquals(true, commands.contains("OT2,40"))
    }
}
