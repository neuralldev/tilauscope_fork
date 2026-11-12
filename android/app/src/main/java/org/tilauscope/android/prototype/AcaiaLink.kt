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
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import kotlin.math.pow

/**
 * Acaia scale of the current family (Lunar, Pearl, Pyxis…), same protocol as the
 * desktop driver: frames EF DD | type | length | data | two checksums. The scale
 * asks for an ID with INFO messages until it has taken one (a lost ID is sent
 * again until its STATUS arrives), then weights are asked once, and again only
 * after [WEIGHT_REQUEST_MS] without one. A heartbeat keeps the link alive.
 * Everything runs on the link's own thread; [onState] receives each change.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
class AcaiaLink(private val context: Context, private val onState: (JSONObject) -> Unit) : ScaleDevice {
    private val thread = HandlerThread("acaia-link").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    private var tx: BluetoothGattCharacteristic? = null
    private val queue = ArrayDeque<ByteArray>()
    private var writing = false
    private var writeAt = 0L
    private val buffer = ArrayList<Byte>()

    private var address: String? = null
    private var wanted = false
    private var state = "idle"
    private var infoReceived = false
    private var idSent = false
    private var battery: Int? = null
    private var unit = UNIT_G
    private var requestedAt: Long? = null
    private var weight: Double? = null
    private var stable = false
    private var lastRx = 0L
    private var weightAt = 0L

    private val heartbeat = object : Runnable {
        override fun run() {
            if (state != "connected") return
            val now = SystemClock.elapsedRealtime()
            if (now - lastRx > RX_STALL_MS) {
                drop()
                return
            }
            if (writing && now - writeAt > WRITE_STALL_MS) writing = false
            if (weight != null && now - weightAt > WEIGHT_MAX_AGE_MS) { weight = null; publish() }
            send(MSG_SYSTEM, byteArrayOf(2, 0))
            handler.postDelayed(this, HEARTBEAT_MS)
        }
    }

    /** Asks for weights again once [WEIGHT_REQUEST_MS] passed without one, whatever else the scale sends. */
    private val weightWatch = object : Runnable {
        override fun run() {
            if (state != "connected") return
            requestWeights(SystemClock.elapsedRealtime())
            handler.postDelayed(this, WEIGHT_WATCH_MS)
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
                val service = g.getService(SERVICE_UUID)
                val rx = service?.getCharacteristic(NOTIFY_UUID)
                tx = service?.getCharacteristic(WRITE_UUID)
                val cccd = rx?.getDescriptor(CCCD_UUID)
                if (tx == null || cccd == null || !g.setCharacteristicNotification(rx, true)) {
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
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    drop()
                    return@post
                }
                state = "connected" // the scale now sends INFO and waits for the ID
                lastRx = SystemClock.elapsedRealtime()
                publish()
                handler.post(heartbeat)
                handler.post(weightWatch)
            }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            handler.post {
                if (g !== gatt) return@post
                writing = false
                drain()
            }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
            handler.post { if (g === gatt) receive(value) }
        }

        @Deprecated("Called before Android 13 only")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            val value = c.value ?: return
            handler.post { if (g === gatt) receive(value) }
        }
    }

    /** Any thread. Keeps looking for the scale until [disconnect]. */
    override fun connect(address: String): Boolean = handler.post {
        if (wanted && address == this.address) {
            publish()
            return@post
        }
        close()
        this.address = address
        wanted = true
        open()
    }

    override fun disconnect(): Boolean = handler.post {
        wanted = false
        close()
        set("idle")
    }

    override fun release(): Boolean = handler.post {
        wanted = false
        close()
        thread.quitSafely()
    }

    override fun tare(): Boolean = handler.post { if (state == "connected" && idSent) send(MSG_TARE, byteArrayOf(0)) }

    private fun open() {
        val device = address?.let { a -> adapter?.takeIf { it.isEnabled }?.getRemoteDevice(a) } ?: run {
            set("bluetooth_off")
            retryLater() // until Bluetooth is back
            return
        }
        infoReceived = false; idSent = false; battery = null; unit = UNIT_G
        requestedAt = null; weightAt = 0L; weight = null; stable = false
        buffer.clear()
        set("connecting")
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        val attempt = gatt
        handler.postDelayed({ if (gatt === attempt && state == "connecting") drop() }, CONNECT_TIMEOUT_MS)
    }

    private fun receive(value: ByteArray) {
        lastRx = SystemClock.elapsedRealtime()
        buffer.addAll(value.toList())
        while (true) {
            var start = -1
            for (i in 0 until buffer.size - 1) {
                if (buffer[i] == HEADER1 && buffer[i + 1] == HEADER2) { start = i; break }
            }
            if (start < 0) { if (buffer.size > 1) buffer.subList(0, buffer.size - 1).clear(); return }
            if (start > 0) buffer.subList(0, start).clear()
            if (buffer.size < 4) return
            val type = buffer[2].toInt() and 0xff
            if (type !in setOf(CMD_SYSTEM, CMD_INFO, CMD_STATUS, CMD_EVENT)) {
                buffer.subList(0, 2).clear()
                continue
            }
            val length = buffer[3].toInt() and 0xff
            val end = 3 + length + 2 // header, type, then length byte + data, then two checksums
            if (length < 1) { buffer.subList(0, 2).clear(); continue }
            if (buffer.size < end) return
            val frame = buffer.subList(0, end).toByteArray()
            buffer.subList(0, end).clear()
            val data = frame.copyOfRange(3, 3 + length)
            if (frame.copyOfRange(3 + length, end).contentEquals(checksums(data))) handle(type, data)
        }
    }

    private fun handle(type: Int, data: ByteArray) {
        when (type) {
            CMD_INFO -> {
                infoReceived = true
                // The scale repeats INFO until it has taken the ID; a STATUS ends the handshake.
                if (!idSent || battery == null) sendId()
            }
            CMD_STATUS -> if (infoReceived) {
                if (data.size > 1) battery = data[1].toInt() and 0x7f
                if (data.size > 2) unit = data[2].toInt() and 0x7f
                publish()
            }
            CMD_EVENT -> if (data.size > 2 && (data[1].toInt() and 0xff) == EVENT_WEIGHT) {
                weightEvent(data.copyOfRange(2, data.size))
            }
        }
        requestWeights(SystemClock.elapsedRealtime())
    }

    /** Once the ID is sent: weights asked for, again only when none has come for [WEIGHT_REQUEST_MS]. */
    private fun requestWeights(now: Long) {
        val asked = requestedAt
        if (!idSent || asked != null && now - maxOf(weightAt, asked) < WEIGHT_REQUEST_MS) return
        sendEvent(byteArrayOf(0, 1))
        requestedAt = now
    }

    private fun weightEvent(payload: ByteArray) {
        if (payload.size < 6) return
        // The protocol's weight: a little-endian 32-bit count, its number of decimals, then flags
        // (bit 0 set: still moving, bit 1 set: negative), in the unit the scale reported.
        val count = ByteBuffer.wrap(payload, 0, 4).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xffffffffL
        val decimals = payload[4].toInt()
        val flags = payload[5].toInt()
        val inScaleUnit = if (decimals in 1..4) count / 10.0.pow(decimals) else count.toDouble()
        val grams = inScaleUnit * when (unit) { UNIT_KG -> 1000.0; UNIT_OZ -> GRAMS_PER_OZ; else -> 1.0 }
        weight = if (flags and 0x02 != 0) -grams else grams
        stable = flags and 0x01 == 0
        weightAt = SystemClock.elapsedRealtime()
        publish()
    }

    private fun sendId() {
        idSent = true
        send(MSG_IDENTIFY, ByteArray(15) { 0x2d })
    }

    private fun sendEvent(payload: ByteArray) = send(MSG_EVENT, byteArrayOf((payload.size + 1).toByte()) + payload)

    private fun send(type: Int, payload: ByteArray) {
        queue.addLast(byteArrayOf(HEADER1, HEADER2, type.toByte()) + payload + checksums(payload))
        drain()
    }

    private fun drain() {
        val g = gatt ?: return
        val characteristic = tx ?: return
        if (writing) return
        val chunk = queue.removeFirstOrNull() ?: return
        val type = if (characteristic.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE != 0)
            BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE else BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
        val accepted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            g.writeOrRefuse(characteristic, chunk, type)
        } else {
            characteristic.writeType = type
            @Suppress("DEPRECATION")
            characteristic.value = chunk
            @Suppress("DEPRECATION")
            g.writeCharacteristic(characteristic)
        }
        if (accepted) {
            writing = true
            writeAt = SystemClock.elapsedRealtime()
        } else {
            queue.addFirst(chunk)
            handler.postDelayed({ drain() }, RETRY_MS)
        }
    }

    private fun close() {
        handler.removeCallbacks(heartbeat)
        handler.removeCallbacks(weightWatch)
        handler.removeCallbacksAndMessages(RECONNECT)
        gatt?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
        tx = null
        queue.clear()
        writing = false
        weight = null
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
        // Ready once the handshake ended (STATUS) or a weight came: a scale that kept the ID of an earlier
        // connection streams weights without INFO nor STATUS, as the desktop reads them too.
        onState(JSONObject().put("state", state).put("ready", state == "connected" && (battery != null || weight != null))
            .put("weight_g", weight?.let { Math.round(it * 10) / 10.0 } ?: JSONObject.NULL)
            .put("stable", stable).put("battery", battery ?: JSONObject.NULL))
    }

    private companion object {
        val SERVICE_UUID: UUID = UUID.fromString("49535343-fe7d-4ae5-8fa9-9fafd205e455")
        val NOTIFY_UUID: UUID = UUID.fromString("49535343-1e4d-4bd9-ba61-23c647249616")
        val WRITE_UUID: UUID = UUID.fromString("49535343-8841-43f4-a8d4-ecbe34729bb3")
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val HEADER1 = 0xEF.toByte()
        const val HEADER2 = 0xDD.toByte()
        const val MSG_SYSTEM = 0
        const val MSG_TARE = 4
        const val MSG_IDENTIFY = 11
        const val MSG_EVENT = 12
        const val CMD_SYSTEM = 0
        const val CMD_INFO = 7
        const val CMD_STATUS = 8
        const val CMD_EVENT = 12
        const val EVENT_WEIGHT = 5
        const val UNIT_KG = 1
        const val UNIT_G = 2
        const val UNIT_OZ = 5
        const val GRAMS_PER_OZ = 28.349523125
        const val HEARTBEAT_MS = 5000L
        const val RX_STALL_MS = 15_000L
        const val WEIGHT_MAX_AGE_MS = 5000L
        const val WEIGHT_REQUEST_MS = 2000L
        const val WEIGHT_WATCH_MS = 500L
        const val WRITE_STALL_MS = 1000L
        const val RETRY_MS = 20L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val RECONNECT_MS = 2000L
        val RECONNECT = Any()

        /** Even-position and odd-position byte sums. */
        fun checksums(payload: ByteArray): ByteArray {
            var even = 0
            var odd = 0
            payload.forEachIndexed { i, b -> if (i % 2 == 0) even = (even + (b.toInt() and 0xff)) and 0xff else odd = (odd + (b.toInt() and 0xff)) and 0xff }
            return byteArrayOf(even.toByte(), odd.toByte())
        }
    }
}
