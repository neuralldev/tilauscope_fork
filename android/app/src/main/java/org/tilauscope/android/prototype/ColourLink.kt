// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import org.json.JSONObject
import java.util.UUID

/**
 * RoastSee C1 colour meter, same protocol as the desktop driver: a measurement
 * is started on the meter itself and arrives as a notification (type 0x01, then
 * the value ×100 as a big-endian uint16). The meter does not say whether it read
 * whole beans or ground coffee; the operator does. The meter is otherwise
 * silent and Android reports it switched off late, so the characteristic is read
 * every [KEEPALIVE_MS]: no answer within [LOST_MS] is a lost link. The link
 * looks for the meter again whenever it drops. [onState] receives each change and each reading.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
class ColourLink(private val context: Context, private val onState: (JSONObject) -> Unit) {
    private val thread = HandlerThread("colour-link").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    private var address: String? = null
    private var wanted = false
    private var state = "idle"
    private var reading: Double? = null
    private var readingId = 0 // tells the page a new measurement from a repeated value
    private var answerAt = 0L // last sign of life: a read answer or a notification

    private val keepAlive = object : Runnable {
        override fun run() {
            val g = gatt ?: return
            if (state != "connected") return
            if (SystemClock.elapsedRealtime() - answerAt > LOST_MS) {
                drop()
                return
            }
            g.getService(SERVICE_UUID)?.getCharacteristic(DIALOG_UUID)?.let { g.readCharacteristic(it) }
            handler.postDelayed(this, KEEPALIVE_MS)
        }
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            handler.post {
                if (g !== gatt) return@post
                if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                    g.discoverServices()
                } else if (newState == BluetoothProfile.STATE_DISCONNECTED || status != BluetoothGatt.GATT_SUCCESS) {
                    drop()
                }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            handler.post {
                if (g !== gatt) return@post
                val characteristic = g.getService(SERVICE_UUID)?.getCharacteristic(DIALOG_UUID)
                val cccd = characteristic?.getDescriptor(CCCD_UUID)
                if (cccd == null || !g.setCharacteristicNotification(characteristic, true)) {
                    drop()
                    return@post
                }
                val enable = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    g.writeOrRefuse(cccd, enable)
                } else {
                    @Suppress("DEPRECATION")
                    cccd.value = enable
                    @Suppress("DEPRECATION")
                    g.writeDescriptor(cccd)
                }
            }
        }

        override fun onDescriptorWrite(g: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
            handler.post {
                if (g !== gatt) return@post
                if (status != BluetoothGatt.GATT_SUCCESS) drop() else {
                    answerAt = SystemClock.elapsedRealtime()
                    set("connected")
                    handler.postDelayed(keepAlive, KEEPALIVE_MS)
                }
            }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
            handler.post { if (g === gatt) parse(value) }
        }

        @Deprecated("Called before Android 13 only")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            val value = c.value ?: return
            handler.post { if (g === gatt) parse(value) }
        }

        // Any answer, even a refusal, proves the meter is there.
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
            handler.post { if (g === gatt) answerAt = SystemClock.elapsedRealtime() }
        }

        @Deprecated("Called before Android 13 only")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            handler.post { if (g === gatt) answerAt = SystemClock.elapsedRealtime() }
        }
    }

    /** Any thread. Keeps looking for the meter until [disconnect]. */
    fun connect(address: String): Boolean = handler.post {
        if (wanted && address == this.address) {
            publish()
            return@post
        }
        close()
        this.address = address
        wanted = true
        open()
    }

    fun disconnect(): Boolean = handler.post {
        wanted = false
        close()
        set("idle")
    }

    fun release(): Boolean = handler.post {
        wanted = false
        close()
        thread.quitSafely()
    }

    private fun open() {
        val device = address?.let { a -> adapter?.takeIf { it.isEnabled }?.getRemoteDevice(a) } ?: run {
            set("bluetooth_off")
            retryLater() // until Bluetooth is back
            return
        }
        set("connecting")
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        val attempt = gatt
        handler.postDelayed({ if (gatt === attempt && state == "connecting") drop() }, CONNECT_TIMEOUT_MS)
    }

    private fun parse(data: ByteArray) {
        answerAt = SystemClock.elapsedRealtime()
        if (data.size < 3 || data[0].toInt() != READ_COLOUR) return
        val raw = ((data[1].toInt() and 0xff) shl 8) or (data[2].toInt() and 0xff)
        reading = Math.round(raw / 10.0) / 10.0 // ×100 on the wire, kept to the tenth
        readingId++
        publish()
    }

    private fun close() {
        handler.removeCallbacks(keepAlive)
        handler.removeCallbacksAndMessages(RECONNECT)
        gatt?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
    }

    private fun drop() {
        close()
        set("lost")
        retryLater()
    }

    private fun retryLater() {
        if (wanted) handler.postAtTime({ if (wanted && gatt == null) open() }, RECONNECT,
            SystemClock.uptimeMillis() + RECONNECT_MS)
    }

    private fun set(value: String) {
        state = value
        publish()
    }

    private fun publish() {
        onState(JSONObject().put("state", state).put("reading", reading ?: JSONObject.NULL).put("reading_id", readingId))
    }

    private companion object {
        val SERVICE_UUID: UUID = UUID.fromString("bc41e50b-91cd-4916-9152-02d52446ac3a")
        val DIALOG_UUID: UUID = UUID.fromString("0000ff03-0000-1000-8000-00805f9b34fb")
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val READ_COLOUR = 1
        const val KEEPALIVE_MS = 5000L
        const val LOST_MS = 8000L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val RECONNECT_MS = 2000L
        val RECONNECT = Any()
    }
}
