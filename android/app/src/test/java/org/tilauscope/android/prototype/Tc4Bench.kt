// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothProfile
import android.os.HandlerThread
import org.junit.Assert.assertEquals
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.annotation.RealObject
import org.robolectric.shadow.api.Shadow
import org.robolectric.shadows.ShadowBluetoothGatt
import java.time.Duration
import java.util.UUID

// The roaster's characteristics and the link's timings, as Tc4Link declares them.
private val RX_UUID: UUID = UUID.fromString("0000ff01-0000-1000-8000-00805f9b34fb")
private val TX_UUID: UUID = UUID.fromString("0000ff02-0000-1000-8000-00805f9b34fb")
private val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
const val VERIFY_WAIT_MS = 400L
const val POLL_MS = 1000L
const val ADDRESS = "AA:BB:CC:DD:EE:FF"

/** The roaster's GATT as the link sees it: every write kept, each acknowledged as the stack would. */
@Implements(BluetoothGatt::class)
class RecordingGatt : ShadowBluetoothGatt() {
    @RealObject lateinit var real: BluetoothGatt
    val written = StringBuilder()

    @Implementation
    override fun requestMtu(mtu: Int) = true

    @Implementation
    override fun discoverServices() = true

    @Implementation
    override fun getServices(): List<BluetoothGattService> = listOf(SERVICE, ACAIA)

    @Implementation
    override fun getService(uuid: UUID): BluetoothGattService? = getServices().firstOrNull { it.uuid == uuid }

    @Implementation
    override fun setCharacteristicNotification(c: BluetoothGattCharacteristic, enable: Boolean) = true

    @Implementation
    override fun writeCharacteristic(c: BluetoothGattCharacteristic, value: ByteArray, type: Int): Int {
        written.append(String(value, Charsets.US_ASCII))
        gattCallback.onCharacteristicWrite(real, c, BluetoothGatt.GATT_SUCCESS)
        return BluetoothGatt.GATT_SUCCESS
    }

    companion object {
        val RX = BluetoothGattCharacteristic(RX_UUID, BluetoothGattCharacteristic.PROPERTY_NOTIFY, 0).apply {
            addDescriptor(BluetoothGattDescriptor(CCCD_UUID, BluetoothGattDescriptor.PERMISSION_WRITE))
        }
        val TX = BluetoothGattCharacteristic(TX_UUID, BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE, 0)
        val SERVICE = BluetoothGattService(UUID.randomUUID(), BluetoothGattService.SERVICE_TYPE_PRIMARY).apply {
            addCharacteristic(RX)
            addCharacteristic(TX)
        }
        // The Acaia scale's serial service, as AcaiaLink declares it.
        val ACAIA_RX = BluetoothGattCharacteristic(UUID.fromString("49535343-1e4d-4bd9-ba61-23c647249616"),
            BluetoothGattCharacteristic.PROPERTY_NOTIFY, 0).apply {
            addDescriptor(BluetoothGattDescriptor(CCCD_UUID, BluetoothGattDescriptor.PERMISSION_WRITE))
        }
        val ACAIA = BluetoothGattService(UUID.fromString("49535343-fe7d-4ae5-8fa9-9fafd205e455"),
            BluetoothGattService.SERVICE_TYPE_PRIMARY).apply {
            addCharacteristic(ACAIA_RX)
            addCharacteristic(BluetoothGattCharacteristic(UUID.fromString("49535343-8841-43f4-a8d4-ecbe34729bb3"),
                BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE, 0))
        }
    }
}

/** A Tc4Link driven as the Skywalker would answer it, on the link's own thread and simulated clock. */
class Tc4Bench(val link: Tc4Link) {
    fun field(name: String): Any? = Tc4Link::class.java.getDeclaredField(name).apply { isAccessible = true }.get(link)

    fun run(ms: Long = 0) {
        val looper = shadowOf((field("thread") as HandlerThread).looper)
        if (ms > 0) looper.idleFor(Duration.ofMillis(ms)) else looper.idle()
    }

    fun gatt() = field("gatt") as BluetoothGatt
    fun state() = field("state") as String
    private fun shadow(g: BluetoothGatt): RecordingGatt = Shadow.extract(g)
    private fun callback(g: BluetoothGatt): BluetoothGattCallback = shadow(g).gattCallback

    /** Connection, subscription and the burner verified at 0 on a fresh echo, as the roaster answers. */
    fun bringUp(bt: Double = 150.0): BluetoothGatt {
        run()
        val g = gatt()
        callback(g).onConnectionStateChange(g, BluetoothGatt.GATT_SUCCESS, BluetoothProfile.STATE_CONNECTED); run()
        callback(g).onMtuChanged(g, 185, BluetoothGatt.GATT_SUCCESS); run()
        callback(g).onServicesDiscovered(g, BluetoothGatt.GATT_SUCCESS); run()
        callback(g).onDescriptorWrite(g, RecordingGatt.RX.getDescriptor(CCCD_UUID), BluetoothGatt.GATT_SUCCESS); run()
        run(10)
        frame(g, bt, 0)
        run(VERIFY_WAIT_MS)
        assertEquals("connected", state())
        return g
    }

    fun frame(g: BluetoothGatt, bt: Double, burner: Int) {
        callback(g).onCharacteristicChanged(g, RecordingGatt.RX, "21.0,180.0,$bt,$burner,40\r\n".toByteArray()); run()
    }

    fun disconnected(g: BluetoothGatt) {
        callback(g).onConnectionStateChange(g, BluetoothGatt.GATT_SUCCESS, BluetoothProfile.STATE_DISCONNECTED); run()
    }

    fun sent(g: BluetoothGatt) = shadow(g).written.split("\n").filter { it.isNotBlank() }
}
