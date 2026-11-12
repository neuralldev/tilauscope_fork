// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.bluetooth.BluetoothManager
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ServiceController
import org.robolectric.annotation.Config

/** The session service around the roast link (audit 2026-10-25): the roaster's cooling outlives the screen. */
@RunWith(RobolectricTestRunner::class)
@Config(shadows = [RecordingGatt::class])
class SessionServiceTest {
    private lateinit var controller: ServiceController<SessionService>
    private lateinit var service: SessionService

    @Before
    fun setUp() {
        controller = Robolectric.buildService(SessionService::class.java).create().startCommand(0, 1)
        service = controller.get()
        shadowOf(service.getSystemService(BluetoothManager::class.java).adapter).setEnabled(true)
    }

    private fun main() = shadowOf(Looper.getMainLooper()).idle()

    private fun link(): Tc4Bench =
        Tc4Bench(SessionService::class.java.getDeclaredField("link").apply { isAccessible = true }.get(service) as Tc4Link)

    /** A roast linked to the roaster, then End roast: the link cools the hot roaster before stopping it. */
    private fun cooling(): Tc4Bench {
        val end = JSONArray(listOf("OT1,0", "OT2,100", "UNTIL_BT_BELOW,50", "OFF"))
        service.connectRoastLink(JSONObject().put("address", ADDRESS).put("end", end).toString())
        val bench = link()
        bench.bringUp(bt = 180.0)
        main()
        bench.link.disconnect(); bench.run(); main() // what the result of "stop" does
        assertEquals("cooling", bench.state())
        return bench
    }

    @Test
    fun theSessionStaysInTheForegroundUntilTheRoasterHasCooled() {
        val bench = cooling()
        service.release() // the result of "stop" reaches the screen
        assertFalse("left the foreground while the roaster cools", shadowOf(service).isStoppedBySelf)
        bench.frame(bench.gatt(), 45.0, 0) // cooled: the end script finishes, OFF, the link lets go
        bench.run(1000); main()
        assertEquals("idle", bench.state())
        assertTrue(shadowOf(service).isStoppedBySelf)
    }

    @Test
    fun aLateCallAfterTheServiceIsGoneIsDropped() {
        controller.destroy()
        service.execute("link_state", "{}") // a link's last state, posted while the service ended
    }

    @Test
    fun aBackToBackRoastTakesTheCoolingRoasterAndKeepsTheSession() {
        val bench = cooling()
        service.release() // the last roast's result
        val gatt = bench.gatt()
        val end = JSONArray(listOf("OT1,0", "OT2,100", "UNTIL_BT_BELOW,50", "OFF"))
        service.connectRoastLink(JSONObject().put("address", ADDRESS).put("end", end).toString()); bench.run()
        assertEquals("verifying", bench.state())
        bench.run(10); bench.frame(gatt, 150.0, 0); bench.run(VERIFY_WAIT_MS); main()
        assertEquals("connected", bench.state()) // the same link, the burner verified at 0: the preheat starts from there
        val sent = bench.sent(gatt)
        assertTrue(sent.contains("CLDN,OF"))
        assertFalse("the roaster was stopped: $sent", sent.contains("OFF"))
        bench.link.disconnect(); bench.run(); main() // this roast ends too, and cools
        bench.frame(gatt, 45.0, 0); bench.run(1000); main()
        assertFalse("the earlier roast's release ended this session", shadowOf(service).isStoppedBySelf)
    }

    @Test
    fun theLinkCheckNeverTakesTheRoasterWhileItCools() {
        val bench = cooling()
        val gatt = bench.gatt()
        service.connectLink(ADDRESS); bench.run(); main()
        assertEquals("cooling", bench.state())
        assertFalse("the cooling was stopped: ${bench.sent(gatt)}", bench.sent(gatt).contains("OFF"))
    }
}
