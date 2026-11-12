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
import kotlin.math.abs

/** A scale link, whatever its brand; any thread. */
interface ScaleDevice {
    fun connect(address: String): Boolean
    fun disconnect(): Boolean
    fun release(): Boolean
    fun tare(): Boolean
}

enum class ScaleKind { ACAIA, DECENT, BOOKOO }

/**
 * The protocol of a scale from the name saved in Settings, as the desktop's registry
 * matches it (tilauscope/scales): an empty name is a Bookoo, recognised by its service alone.
 */
fun scaleKind(name: String): ScaleKind = when {
    name.startsWith("Decent Scale", ignoreCase = true) -> ScaleKind.DECENT
    name.isBlank() || name.startsWith("BOOKOO", ignoreCase = true) -> ScaleKind.BOOKOO
    else -> ScaleKind.ACAIA
}

/** One weight frame: grams, the scale's own stable flag, its battery when it says it. */
data class ScaleFrame(val grams: Double, val stable: Boolean, val battery: Int? = null)

/**
 * When a weight can be taken: at once when the scale flags it stable; otherwise once the reading
 * has stayed within [TOLERANCE_G] of where it settled for [SETTLE_MS] (the hand is off the scale).
 * A reading that flickers across a gram boundary still settles.
 */
class SettledWeight {
    var grams: Double? = null
        private set
    private var scaleSaysStable = false
    private var settledAt: Double? = null // the reading the current hold started from
    private var heldSince = 0L

    fun update(value: Double, stable: Boolean, now: Long) {
        val anchor = settledAt
        if (anchor == null || abs(value - anchor) > TOLERANCE_G) {
            settledAt = value
            heldSince = now
        }
        grams = value
        scaleSaysStable = stable
    }

    fun stable(now: Long) = grams != null && (scaleSaysStable || now - heldSince >= SETTLE_MS)

    fun clear() {
        grams = null
        settledAt = null
        scaleSaysStable = false
    }

    companion object {
        const val SETTLE_MS = 500L
        const val TOLERANCE_G = 0.5
    }
}

/**
 * A scale that streams its weight (~10 a second) on one characteristic and takes short
 * commands on another, as the desktop's ScaleBLE drivers do. Never tried on a device yet.
 * The page hears of a change of gram, of stability or of battery only, as the desktop
 * forwards it. Everything runs on the link's own thread; [onState] receives each change.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
abstract class StreamingScaleLink(private val context: Context, private val onState: (JSONObject) -> Unit) : ScaleDevice {
    protected abstract val serviceUuid: UUID
    protected abstract val notifyUuid: UUID
    protected abstract val writeUuid: UUID
    protected abstract val tareCommand: ByteArray
    protected open val heartbeat: ByteArray? = null // sent every HEARTBEAT_MS when the scale needs one
    protected abstract fun decode(data: ByteArray): ScaleFrame?

    private val thread = HandlerThread("scale-link").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    private var tx: BluetoothGattCharacteristic? = null
    private val queue = ArrayDeque<ByteArray>()
    private var writing = false
    private var writeAt = 0L

    private var address: String? = null
    private var wanted = false
    private var state = "idle"
    private val weight = SettledWeight()
    private var battery: Int? = null
    private var lastRx = 0L
    private var weightAt = 0L
    private var heartbeatAt = 0L
    private var shown: Triple<Long?, Boolean, Int?>? = null // gram, stable, battery last published

    private val tick = object : Runnable {
        override fun run() {
            if (state != "connected") return
            val now = SystemClock.elapsedRealtime()
            if (now - lastRx > RX_STALL_MS) {
                drop()
                return
            }
            if (writing && now - writeAt > WRITE_STALL_MS) writing = false
            if (weight.grams != null && now - weightAt > WEIGHT_MAX_AGE_MS) { weight.clear(); publish() }
            heartbeat?.let { if (now - heartbeatAt >= HEARTBEAT_MS) { heartbeatAt = now; send(it) } }
            handler.postDelayed(this, TICK_MS)
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
                val service = g.getService(serviceUuid)
                val rx = service?.getCharacteristic(notifyUuid)
                tx = service?.getCharacteristic(writeUuid)
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
                state = "connected"
                lastRx = SystemClock.elapsedRealtime()
                heartbeatAt = 0L
                publish()
                handler.post(tick)
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

    override fun tare(): Boolean = handler.post { if (state == "connected") send(tareCommand) }

    private fun open() {
        val device = address?.let { a -> adapter?.takeIf { it.isEnabled }?.getRemoteDevice(a) } ?: run {
            set("bluetooth_off")
            retryLater() // until Bluetooth is back
            return
        }
        battery = null
        weight.clear()
        set("connecting")
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        val attempt = gatt
        handler.postDelayed({ if (gatt === attempt && state == "connecting") drop() }, CONNECT_TIMEOUT_MS)
    }

    private fun receive(value: ByteArray) {
        val now = SystemClock.elapsedRealtime()
        lastRx = now
        val frame = decode(value) ?: return
        weight.update(frame.grams, frame.stable, now)
        weightAt = now
        frame.battery?.let { battery = it }
        val key = Triple(weight.grams?.let { Math.round(it) }, weight.stable(now), battery)
        if (key != shown) publish()
    }

    private fun send(command: ByteArray) {
        queue.addLast(command)
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
        handler.removeCallbacks(tick)
        handler.removeCallbacksAndMessages(RECONNECT)
        gatt?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
        tx = null
        queue.clear()
        writing = false
        weight.clear()
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
        val now = SystemClock.elapsedRealtime()
        val stable = weight.stable(now)
        shown = Triple(weight.grams?.let { Math.round(it) }, stable, battery)
        onState(JSONObject().put("state", state).put("ready", state == "connected")
            .put("weight_g", weight.grams?.let { Math.round(it * 10) / 10.0 } ?: JSONObject.NULL)
            .put("stable", stable).put("battery", battery ?: JSONObject.NULL))
    }

    private companion object {
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val TICK_MS = 1000L
        const val HEARTBEAT_MS = 3000L // the desktop's Decent heartbeat
        const val RX_STALL_MS = 15_000L
        const val WEIGHT_MAX_AGE_MS = 5000L
        const val WRITE_STALL_MS = 1000L
        const val RETRY_MS = 20L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val RECONNECT_MS = 2000L
        val RECONNECT = Any()
    }
}

/** XOR of every byte, the checksum of both Decent and Bookoo frames. */
internal fun xorOf(data: ByteArray, until: Int = data.size): Int {
    var x = 0
    for (i in 0 until until) x = x xor (data[i].toInt() and 0xff)
    return x
}

internal fun withXor(body: ByteArray) = body + byteArrayOf(xorOf(body).toByte())

/** Decent Scale, as tilauscope/scales/decent.py (https://decentespresso.com/decentscale_api). */
class DecentLink(context: Context, onState: (JSONObject) -> Unit) : StreamingScaleLink(context, onState) {
    override val serviceUuid: UUID = UUID.fromString("0000fff0-0000-1000-8000-00805f9b34fb")
    override val notifyUuid: UUID = UUID.fromString("0000fff4-0000-1000-8000-00805f9b34fb")
    override val writeUuid: UUID = UUID.fromString("000036f5-0000-1000-8000-00805f9b34fb")
    override val tareCommand = TARE
    override val heartbeat = HEARTBEAT
    override fun decode(data: ByteArray) = parse(data)

    companion object {
        val TARE = withXor(byteArrayOf(0x03, 0x0F, 0, 0, 0, 0))
        val HEARTBEAT = withXor(byteArrayOf(0x03, 0x0A, 0x03, 0xFF.toByte(), 0xFF.toByte(), 0))

        /** A weight frame (7 bytes, or 10 from firmware 1.2), or null; buttons are not weights. */
        fun parse(data: ByteArray): ScaleFrame? {
            if (data.size != 7 && data.size != 10) return null
            if (data[0] != 0x03.toByte() || xorOf(data, data.size - 1) != (data.last().toInt() and 0xff)) return null
            val type = data[1].toInt() and 0xff
            if (type != 0xCE && type != 0xCA) return null
            val tenths = ((data[2].toInt() shl 8) or (data[3].toInt() and 0xff)).toShort()
            return ScaleFrame(tenths / 10.0, type == 0xCE)
        }
    }
}

/** Bookoo Themis / Mini, as tilauscope/scales/bookoo.py: no stable flag, the battery in each frame. */
class BookooLink(context: Context, onState: (JSONObject) -> Unit) : StreamingScaleLink(context, onState) {
    override val serviceUuid: UUID = UUID.fromString("00000ffe-0000-1000-8000-00805f9b34fb")
    override val notifyUuid: UUID = UUID.fromString("0000ff11-0000-1000-8000-00805f9b34fb")
    override val writeUuid: UUID = UUID.fromString("0000ff12-0000-1000-8000-00805f9b34fb")
    override val tareCommand = TARE
    override fun decode(data: ByteArray) = parse(data)

    companion object {
        val TARE = withXor(byteArrayOf(0x03, 0x0A, 0x01, 0, 0))

        /** A 20-byte weight frame, or null. */
        fun parse(data: ByteArray): ScaleFrame? {
            if (data.size != 20 || data[0] != 0x03.toByte() || data[1] != 0x0B.toByte()) return null
            if (xorOf(data, 19) != (data[19].toInt() and 0xff)) return null
            val hundredths = ((data[7].toInt() and 0xff) shl 16) or ((data[8].toInt() and 0xff) shl 8) or (data[9].toInt() and 0xff)
            val grams = hundredths / 100.0
            return ScaleFrame(if (data[6] == 0x2D.toByte()) -grams else grams, false, data[13].toInt() and 0xff)
        }
    }
}
