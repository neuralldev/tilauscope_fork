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

/**
 * DiFluid AirWave link, same protocol as the desktop driver: frames
 * DF DF | function | command | length | data | checksum on one characteristic.
 * Nothing is commanded before the tablet has given its host name, which the
 * extractor asks for after connecting. Power, speed (30–100 %) and mode are
 * confirmed by the frames the extractor sends back; it also reports changes made
 * on its own knob. The test changes the speed only, never the mode.
 * Everything runs on the link's own thread; [onState] receives each change.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
class AirWaveLink(private val context: Context, private val onState: (JSONObject) -> Unit) {
    private val thread = HandlerThread("airwave-link").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    private var dialog: BluetoothGattCharacteristic? = null
    private var mtu = 20
    private val queue = ArrayDeque<ByteArray>()
    private var writing = false
    private var writeAt = 0L
    private var closing: String? = null
    private var shutdown = false
    private val buffer = ArrayList<Byte>()

    private var address: String? = null
    private var keep = false // reconnect by itself (roast screen), not during a test
    private var state = "idle"
    private var ready = false
    private var power: Boolean? = null
    private var speed: Int? = null
    private var mode: Int? = null
    private var inlet: Double? = null
    private var catalyst: Double? = null
    private var lastRx = 0L
    private var wantSpeed: Int? = null // asked by the operator, not yet confirmed
    private var wantAt = 0L
    private var testEnd = 0L
    private var testSpeed = 0
    private var restoreSpeed = 0
    private var restoreOff = false

    private val tick = object : Runnable {
        override fun run() {
            if (state != "connected") return
            val now = SystemClock.elapsedRealtime()
            if (now - lastRx > RX_STALL_MS) {
                drop("lost")
                return
            }
            if (writing && now - writeAt > WRITE_STALL_MS) writing = false
            request(TEMPERATURE)
            handler.postDelayed(this, POLL_MS)
        }
    }

    private val endTest = Runnable {
        if (testEnd == 0L) return@Runnable
        testEnd = 0L
        command(FAN, restoreSpeed)
        if (restoreOff) command(STATUS, 0)
        publish()
        close("done")
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            handler.post {
                if (g !== gatt) return@post
                if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                    g.requestMtu(MTU_REQUEST)
                } else if (newState == BluetoothProfile.STATE_DISCONNECTED || status != BluetoothGatt.GATT_SUCCESS) {
                    drop(if (state == "connected") "lost" else "failed")
                }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, value: Int, status: Int) {
            handler.post {
                if (g !== gatt) return@post
                mtu = if (status == BluetoothGatt.GATT_SUCCESS) value - 3 else 20
                g.discoverServices()
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            handler.post {
                if (g !== gatt) return@post
                val characteristic = g.services.flatMap { it.characteristics }.firstOrNull { it.uuid == DIALOG_UUID }
                val cccd = characteristic?.getDescriptor(CCCD_UUID)
                if (cccd == null || !g.setCharacteristicNotification(characteristic, true)) {
                    drop("failed")
                    return@post
                }
                dialog = characteristic
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
                    drop("failed")
                    return@post
                }
                // The extractor asks for the host name after a fresh connect, but
                // not always after a quick reconnect: give it first, then read the state.
                sendHostName()
                request(STATUS)
                request(POSITION)
                request(FAN)
                request(TEMPERATURE)
                state = "connected"
                lastRx = SystemClock.elapsedRealtime()
                publish()
                handler.postDelayed(tick, POLL_MS)
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

    /** Any thread. [keep]: look for the extractor again whenever the link drops. */
    fun connect(address: String, keep: Boolean): Boolean = handler.post {
        if (gatt != null) {
            if (address == this.address && this.keep == keep && state == "connected") {
                publish()
                return@post
            }
            close("idle")
            handler.postDelayed({ connect(address, keep) }, CLOSE_WAIT_MS + RETRY_MS)
            return@post
        }
        this.address = address
        this.keep = keep
        open()
    }

    /** Any thread. Lets go of the extractor, which keeps running as it is. */
    fun disconnect(): Boolean = handler.post {
        keep = false
        handler.removeCallbacksAndMessages(RECONNECT)
        if (gatt != null) close("idle") else set("idle")
    }

    fun release(): Boolean = handler.post {
        shutdown = true
        keep = false
        handler.removeCallbacksAndMessages(RECONNECT)
        if (gatt != null) close("idle") else thread.quitSafely()
    }

    fun setPower(on: Boolean): Boolean = handler.post {
        if (!ready || testEnd != 0L) return@post
        command(STATUS, if (on) 1 else 0)
    }

    fun setSpeed(value: Int): Boolean = handler.post {
        if (!ready || testEnd != 0L) return@post
        val clamped = value.coerceIn(SPEED_MIN, SPEED_MAX)
        wantSpeed = clamped
        wantAt = SystemClock.elapsedRealtime()
        command(FAN, clamped)
        publish()
    }

    /** The extractor applies the mode's own speed: the chosen speed is given again after it. */
    fun setMode(value: Int): Boolean = handler.post {
        if (!ready || testEnd != 0L || value !in 0..2) return@post
        command(POSITION, value)
        val keepSpeed = speed
        if (keepSpeed != null) handler.postDelayed({ if (ready && speed != keepSpeed) command(FAN, keepSpeed) }, MODE_SETTLE_MS)
    }

    /** Changes the speed for the test, then puts speed and power back and lets go. */
    fun speedTest(): Boolean = handler.post {
        val current = speed
        if (!ready || testEnd != 0L || current == null || power == null) return@post
        restoreSpeed = current
        restoreOff = power == false
        testSpeed = if (current < TEST_SPEED) TEST_SPEED else SPEED_MIN
        if (restoreOff) command(STATUS, 1)
        command(FAN, testSpeed)
        testEnd = SystemClock.elapsedRealtime() + TEST_MS
        handler.postDelayed(endTest, TEST_MS)
        publish()
    }

    private fun open() {
        val device = address?.let { a -> adapter?.takeIf { it.isEnabled }?.getRemoteDevice(a) } ?: run {
            set("bluetooth_off")
            retryLater() // until Bluetooth is back
            return
        }
        ready = false
        power = null; speed = null; mode = null; inlet = null; catalyst = null
        buffer.clear()
        set("connecting")
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        val attempt = gatt
        handler.postDelayed({ if (gatt === attempt && state == "connecting") drop("failed") }, CONNECT_TIMEOUT_MS)
    }

    // The host name is 30 bytes, zero padded.
    private fun sendHostName() {
        val name = ByteArray(30)
        HOST_NAME.toByteArray(Charsets.UTF_8).copyInto(name)
        write(frame(DEVICE_SETTING, HOST_NAME_COMMAND, name))
        ready = true
    }

    private fun request(command: Int) = write(frame(DEVICE_ACTIONS, command, ByteArray(0)))

    private fun command(command: Int, value: Int) = write(frame(DEVICE_ACTIONS, command, byteArrayOf(value.toByte())))

    private fun frame(function: Int, command: Int, data: ByteArray): ByteArray {
        val head = byteArrayOf(0xDF.toByte(), 0xDF.toByte(), function.toByte(), command.toByte(), data.size.toByte()) + data
        return head + head.sumOf { it.toInt() and 0xff }.toByte()
    }

    private fun receive(value: ByteArray) {
        buffer.addAll(value.toList())
        while (true) {
            var start = -1
            for (i in 0 until buffer.size - 1) {
                if (buffer[i] == PREAMBLE && buffer[i + 1] == PREAMBLE) { start = i; break }
            }
            if (start < 0) { if (buffer.size > 1) buffer.subList(0, buffer.size - 1).clear(); return }
            if (start > 0) buffer.subList(0, start).clear()
            if (buffer.size < 5) return
            val end = 6 + (buffer[4].toInt() and 0xff)
            if (buffer.size < end) return
            val bytes = buffer.subList(0, end).toByteArray()
            buffer.subList(0, end).clear()
            val sum = bytes.copyOfRange(0, end - 1).sumOf { it.toInt() and 0xff } and 0xff
            if (sum == (bytes[end - 1].toInt() and 0xff)) handle(bytes[2].toInt(), bytes[3].toInt(), bytes.copyOfRange(5, end - 1))
        }
    }

    private fun handle(function: Int, command: Int, data: ByteArray) {
        lastRx = SystemClock.elapsedRealtime()
        if (function == DEVICE_SETTING && command == HOST_NAME_COMMAND) {
            sendHostName() // the extractor asks who is connecting
            return
        }
        if (function != DEVICE_ACTIONS || data.isEmpty()) return
        val number = data.fold(0) { acc, b -> (acc shl 8) or (b.toInt() and 0xff) }
        when (command) {
            STATUS -> power = number == 1
            POSITION -> mode = number
            FAN -> {
                speed = number
                // Confirmed, or turned on the extractor itself once the request has had its time.
                if (number == wantSpeed || SystemClock.elapsedRealtime() - wantAt > PENDING_MS) wantSpeed = null
            }
            TEMPERATURE -> if (data.size >= 8) {
                val values = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
                inlet = Math.round(values.getFloat(0) * 10) / 10.0
                catalyst = Math.round(values.getFloat(4) * 10) / 10.0
            }
            else -> return
        }
        publish()
    }

    private fun write(data: ByteArray) {
        for (offset in data.indices step mtu) queue.addLast(data.copyOfRange(offset, minOf(data.size, offset + mtu)))
        drain()
    }

    private fun drain() {
        val g = gatt ?: return
        val characteristic = dialog ?: return
        if (writing) return
        val chunk = queue.removeFirstOrNull()
        if (chunk == null) {
            closing?.let { finish(it) }
            return
        }
        val accepted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            g.writeOrRefuse(characteristic, chunk, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
        } else {
            characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
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

    /** Lets go once what is queued is written (or after a short wait). */
    private fun close(final: String) {
        handler.removeCallbacks(tick)
        closing = final
        val current = gatt
        handler.postDelayed({ if (gatt === current && closing != null) finish(final) }, CLOSE_WAIT_MS)
        drain()
    }

    private fun finish(final: String) {
        gatt?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
        dialog = null
        queue.clear()
        writing = false
        closing = null
        ready = false
        if (final != "done") { power = null; speed = null; mode = null; inlet = null; catalyst = null }
        set(final)
        if (shutdown) thread.quitSafely()
    }

    /** The link is already gone; on the roast screen the extractor is looked for again. */
    private fun drop(final: String) {
        handler.removeCallbacks(tick)
        handler.removeCallbacks(endTest)
        testEnd = 0L
        queue.clear()
        finish(final)
        retryLater()
    }

    private fun retryLater() {
        if (keep && !shutdown) handler.postAtTime({ if (keep && gatt == null) open() }, RECONNECT,
            SystemClock.uptimeMillis() + RECONNECT_MS)
    }

    private fun set(value: String) {
        state = value
        publish()
    }

    private fun publish() {
        val left = if (testEnd == 0L) JSONObject.NULL
            else ((testEnd - SystemClock.elapsedRealtime() + 999) / 1000).coerceAtLeast(0)
        onState(JSONObject().put("state", state).put("ready", ready)
            .put("power", power ?: JSONObject.NULL).put("speed", speed ?: JSONObject.NULL)
            .put("want_speed", wantSpeed ?: JSONObject.NULL)
            .put("mode", mode?.let { MODES.getOrNull(it) } ?: JSONObject.NULL)
            .put("inlet", inlet ?: JSONObject.NULL).put("catalyst", catalyst ?: JSONObject.NULL)
            .put("test_speed", testSpeed).put("test_from", restoreSpeed)
            .put("test_seconds", TEST_MS / 1000).put("test_left", left))
    }

    private companion object {
        val DIALOG_UUID: UUID = UUID.fromString("0000aa01-0000-1000-8000-00805f9b34fb")
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val PREAMBLE = 0xDF.toByte()
        const val DEVICE_SETTING = 1
        const val DEVICE_ACTIONS = 3
        const val HOST_NAME_COMMAND = 1
        const val POSITION = 0
        const val FAN = 1
        const val STATUS = 2
        const val TEMPERATURE = 3
        val MODES = listOf("STD", "EXT", "FAN")
        const val HOST_NAME = "TilauScope"
        const val SPEED_MIN = 30
        const val SPEED_MAX = 100
        const val TEST_SPEED = 60
        const val TEST_MS = 10_000L
        const val MTU_REQUEST = 185
        const val POLL_MS = 1000L
        const val RX_STALL_MS = 5000L
        const val WRITE_STALL_MS = 1000L
        const val RETRY_MS = 20L
        const val PENDING_MS = 2000L
        const val MODE_SETTLE_MS = 600L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val CLOSE_WAIT_MS = 600L
        const val RECONNECT_MS = 2000L
        val RECONNECT = Any()
    }
}
