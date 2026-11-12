// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.app.Application
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.os.HandlerThread
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadow.api.Shadow
import java.time.Duration

/** The Acaia link on a simulated Lunar (2026-10-25): weights shown whatever the handshake did. */
@RunWith(RobolectricTestRunner::class)
@Config(shadows = [RecordingGatt::class])
class AcaiaLinkTest {
    private val app: Application = RuntimeEnvironment.getApplication()
    private val states = mutableListOf<JSONObject>()
    private lateinit var link: AcaiaLink

    @Before
    fun setUp() {
        shadowOf(app.getSystemService(BluetoothManager::class.java).adapter).setEnabled(true)
        link = AcaiaLink(app) { states.add(it) }
    }

    private fun field(name: String): Any? = AcaiaLink::class.java.getDeclaredField(name).apply { isAccessible = true }.get(link)

    private fun run() = shadowOf((field("thread") as HandlerThread).looper).idleFor(Duration.ofMillis(10))

    private fun bytes(hex: String) = hex.split(" ").map { it.toInt(16).toByte() }.toByteArray()

    @Test
    fun aScaleThatKeptItsIdSendsWeightsWithoutStatusAndTheyAreUsed() {
        link.connect("60:8A:10:38:F8:E1"); run()
        val g = field("gatt") as BluetoothGatt
        val cb = Shadow.extract<RecordingGatt>(g).gattCallback
        cb.onConnectionStateChange(g, BluetoothGatt.GATT_SUCCESS, BluetoothProfile.STATE_CONNECTED); run()
        cb.onServicesDiscovered(g, BluetoothGatt.GATT_SUCCESS); run()
        cb.onDescriptorWrite(g, RecordingGatt.ACAIA_RX.getDescriptor(java.util.UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")),
            BluetoothGatt.GATT_SUCCESS); run()
        // A Lunar that still holds the ID of an earlier connection: weight events only, no INFO, no STATUS
        // (frame captured on the tablet: 387.7 g, stable).
        cb.onCharacteristicChanged(g, RecordingGatt.ACAIA_RX, bytes("ef dd 0c 0c 05 25 0f 00 00 01 00 07 00 00 02 39 16")); run()
        val last = states.last()
        assertTrue("weights arrive but the scale is never ready: $last", last.getBoolean("ready"))
        assertEquals(387.7, last.getDouble("weight_g"), 0.01)
    }

    @Test
    fun weightsAreAskedOnceThenAgainOnlyAfterTwoSecondsWithoutOne() {
        link.connect("60:8A:10:38:F8:E1"); run()
        val g = field("gatt") as BluetoothGatt
        val shadow = Shadow.extract<RecordingGatt>(g)
        val cb = shadow.gattCallback
        cb.onConnectionStateChange(g, BluetoothGatt.GATT_SUCCESS, BluetoothProfile.STATE_CONNECTED); run()
        cb.onServicesDiscovered(g, BluetoothGatt.GATT_SUCCESS); run()
        cb.onDescriptorWrite(g, RecordingGatt.ACAIA_RX.getDescriptor(java.util.UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")),
            BluetoothGatt.GATT_SUCCESS); run()
        val requests = { shadow.written.split("\u000C\u0003\u0000\u0001").size - 1 } // EVENT frame asking for weights
        val info = bytes("ef dd 07 05 02 00 00 00 05 02")
        val weight = bytes("ef dd 0c 0c 05 25 0f 00 00 01 00 07 00 00 02 39 16")
        val idle = { ms: Long -> shadowOf((field("thread") as HandlerThread).looper).idleFor(Duration.ofMillis(ms)) }

        cb.onCharacteristicChanged(g, RecordingGatt.ACAIA_RX, info); run()
        assertEquals("the ID taken, weights are asked for", 1, requests())
        cb.onCharacteristicChanged(g, RecordingGatt.ACAIA_RX, info); run()
        assertEquals("no second request right away", 1, requests())
        repeat(4) { idle(1000); cb.onCharacteristicChanged(g, RecordingGatt.ACAIA_RX, weight); run() }
        assertEquals("weights flowing: nothing more to ask", 1, requests())
        idle(1500); cb.onCharacteristicChanged(g, RecordingGatt.ACAIA_RX, info); run()
        assertEquals("1.5 s without a weight is not yet a silence", 1, requests())
        idle(1100); run() // the watch looks every half second
        assertEquals("2 s without a weight, the scale silent: asked again", 2, requests())
        idle(800); run()
        assertEquals("not twice within 2 s", 2, requests())
        idle(1500); run()
        assertEquals("still no weight 2 s after asking: asked once more", 3, requests())
    }
}
