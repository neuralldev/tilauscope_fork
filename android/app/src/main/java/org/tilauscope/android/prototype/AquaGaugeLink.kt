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
import android.util.Log
import org.json.JSONObject
import java.util.UUID

/**
 * RoastSee AquaGauge water activity meter, same protocol as the desktop driver:
 * nothing is written to it. A measurement is started on the meter, which streams
 * "aw=0.659,dew=63.887" lines while it measures (about 2 minutes); a 15-byte
 * signature arrives on connect. The "dew" value is not shown on the meter and its
 * unit is unknown, so it is not used. As on the desktop, the measurement is final
 * when no line arrives for [FINAL_QUIET_MS]; a meter switched off falls silent
 * too, and Android reports the loss late, so the silence is confirmed by reading
 * the characteristic: no answer within [ANSWER_MS] is a lost meter and an
 * interrupted measurement. The same read every [KEEPALIVE_MS] watches an idle
 * link. The link looks for the meter again whenever it drops. [onState]
 * receives each change and each value.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
class AquaGaugeLink(private val context: Context, private val onState: (JSONObject) -> Unit) {
    private val thread = HandlerThread("aquagauge-link").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    private var address: String? = null
    private var wanted = false
    private var state = "idle"
    private var aw: Double? = null
    private var measuring = false
    private var final = false // the last value closed a measurement
    private var readingId = 0 // tells the page a new value from a repeated one
    private var onAnswer: (() -> Unit)? = null // what a read answer confirms

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
                    set("connected")
                    keepAlive()
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
            handler.post { if (g === gatt) answered() }
        }

        @Deprecated("Called before Android 13 only")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            handler.post { if (g === gatt) answered() }
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
        aw = null
        final = false
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
        // Raw frames with their time: the cadence of the stream is not documented.
        Log.d(TAG, "${SystemClock.elapsedRealtime()} ${data.joinToString("") { "%02x".format(it) }}")
        if (data.contentEquals(SIGNATURE)) return
        val match = LINE.find(String(data, Charsets.US_ASCII).trim('\u0000')) ?: return
        val value = match.groupValues[1].toDouble()
        if (value < 0.0 || value > 1.0) return
        aw = value
        measuring = true
        final = false
        readingId++
        // A line also proves the meter is there: a pending read confirms nothing more.
        handler.removeCallbacksAndMessages(ANSWER)
        onAnswer = null
        handler.removeCallbacksAndMessages(FINAL)
        handler.postAtTime({
            probe {
                measuring = false
                final = true
                publish()
            }
        }, FINAL, SystemClock.uptimeMillis() + FINAL_QUIET_MS)
        publish()
    }

    private fun probe(then: () -> Unit) {
        val g = gatt ?: return
        onAnswer = then
        handler.postAtTime({ drop() }, ANSWER, SystemClock.uptimeMillis() + ANSWER_MS)
        g.getService(SERVICE_UUID)?.getCharacteristic(DIALOG_UUID)?.let { g.readCharacteristic(it) }
    }

    private fun answered() {
        handler.removeCallbacksAndMessages(ANSWER)
        onAnswer?.invoke()
        onAnswer = null
        if (!measuring) keepAlive()
    }

    private fun keepAlive() {
        handler.removeCallbacksAndMessages(FINAL)
        handler.postAtTime({ probe {} }, FINAL, SystemClock.uptimeMillis() + KEEPALIVE_MS)
    }

    private fun close() {
        handler.removeCallbacksAndMessages(RECONNECT)
        handler.removeCallbacksAndMessages(FINAL)
        handler.removeCallbacksAndMessages(ANSWER)
        onAnswer = null
        measuring = false
        gatt?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
    }

    private fun drop() {
        if (!final) aw = null // an interrupted measurement is not a result
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
        onState(JSONObject().put("state", state).put("aw", aw ?: JSONObject.NULL)
            .put("measuring", measuring).put("final", final).put("reading_id", readingId))
    }

    private companion object {
        const val TAG = "AquaGauge"
        val SERVICE_UUID: UUID = UUID.fromString("000000ff-0000-1000-8000-00805f9b34fb")
        val DIALOG_UUID: UUID = UUID.fromString("0000ff01-0000-1000-8000-00805f9b34fb")
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        val SIGNATURE = ByteArray(15) { it.toByte() }
        val LINE = Regex("""aw=([-+]?\d*\.\d+|\d+),dew=([-+]?\d*\.\d+|\d+)""")
        const val FINAL_QUIET_MS = 2000L
        const val ANSWER_MS = 3000L
        const val KEEPALIVE_MS = 5000L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val RECONNECT_MS = 2000L
        val RECONNECT = Any()
        val FINAL = Any() // the silence that ends a measurement, or the next idle read
        val ANSWER = Any()
    }
}
