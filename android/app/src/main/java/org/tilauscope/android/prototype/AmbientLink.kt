// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
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
 * TilauAmbient probe: the environment frame is read once a second,
 * as on the desktop (17 bytes: 0x5555 | temperature, humidity ×10 int16 |
 * pressure, altitude ×10 int32 | checksum | 0xAAAA). A reading older than 3 s is
 * no reading. The crack counter's commands (the desktop's: calibrations, start,
 * stop) are written on the audio channel between two reads, one at a time;
 * between start and stop the count is read there too, once a second, as the
 * desktop does (9 bytes: 0x5555 | count int32 | checksum | 0xAAAA).
 * A probe with a drop door contact has its frame read next, once a second too (12 bytes:
 * 0x5555 | open | openings uint16 | ms since the last opening uint32 | checksum | 0xAAAA),
 * passed on as is with its read number: the core reads it (wiki/Drop-Door-Contact-Spec.md).
 * The link looks for the probe again whenever it drops.
 * Everything runs on the link's own thread; [onState] receives each change.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
class AmbientLink(private val context: Context, private val onState: (JSONObject) -> Unit) {
    private val thread = HandlerThread("ambient-link").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    private var environment: BluetoothGattCharacteristic? = null
    private var audio: BluetoothGattCharacteristic? = null
    private var door: BluetoothGattCharacteristic? = null // the drop door contact; null on a firmware without it
    private var doorAsked = false // the door is read next, after the environment and the count
    private var doorFrame: String? = null // hex, as the probe sent it
    private var doorAt = 0L
    private var doorSeq = 0
    private var doorOpen: Boolean? = null // the last state logged
    private var doorOpenings = -1
    private val commands = ArrayDeque<Int>() // audio commands still to write
    private var busy = false // a read or a write is in flight: Android runs one at a time
    private var writing: Int? = null // the command in flight
    private var counting = false // start delivered, stop not yet: the count is read, across a dropped link too
    private var countAsked = false // the count is read next, after the environment
    private var cracks: Int? = null
    private var cracksAt = 0L
    private var address: String? = null
    private var wanted = false
    private var state = "idle"
    private var temperature: Double? = null
    private var humidity: Double? = null
    private var pressure: Double? = null
    private var altitude: Double? = null
    private var readAt = 0L
    private var answerAt = 0L // last read answered, valid or not

    private val tick = object : Runnable {
        override fun run() {
            val g = gatt ?: return
            if (state != "connected") return
            // Android reports a probe switched off late: no answer for LOST_MS is a lost link.
            if (SystemClock.elapsedRealtime() - answerAt > LOST_MS) {
                drop()
                return
            }
            if (temperature != null && SystemClock.elapsedRealtime() - readAt > MAX_AGE_MS) {
                temperature = null; humidity = null; pressure = null; altitude = null
                publish()
            }
            if (cracks != null && SystemClock.elapsedRealtime() - cracksAt > MAX_AGE_MS) {
                cracks = null
                publish()
            }
            if (doorFrame != null && SystemClock.elapsedRealtime() - doorAt > MAX_AGE_MS) {
                doorFrame = null
                publish()
            }
            if (!busy) environment?.let { busy = g.readCharacteristic(it) }
            countAsked = counting
            doorAsked = door != null
            handler.postDelayed(this, POLL_MS)
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
                // Matched on its common part: the desktop sources spell the first group two ways.
                val characteristics = g.getService(SERVICE_UUID)?.characteristics
                environment = characteristics?.firstOrNull { it.uuid.toString().endsWith(ENVIRONMENT_SUFFIX) }
                audio = characteristics?.firstOrNull { it.uuid.toString().endsWith(AUDIO_SUFFIX) }
                door = characteristics?.firstOrNull { it.uuid.toString().endsWith(DOOR_SUFFIX) }
                if (environment == null) {
                    drop()
                    return@post
                }
                state = "connected"
                answerAt = SystemClock.elapsedRealtime()
                publish()
                handler.post(tick)
            }
        }

        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
            handler.post { if (g === gatt) answered(c, value, status) }
        }

        @Deprecated("Called before Android 13 only")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            @Suppress("DEPRECATION")
            val value = c.value ?: return
            handler.post { if (g === gatt) answered(c, value, status) }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            handler.post {
                if (g !== gatt) return@post
                busy = false
                when (writing) {
                    START -> if (status == BluetoothGatt.GATT_SUCCESS) counting = true
                    STOP -> counting = false // asked to stop: reading on would read nothing new
                }
                writing = null
                writeNext()
            }
        }
    }

    /** Any thread. Keeps looking for the probe until [disconnect]. */
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

    /** Any thread. One of the crack counter's commands (the desktop's codes), written when the link is free. */
    fun command(code: Int): Boolean = handler.post {
        if (state != "connected" || audio == null) return@post
        commands.addLast(code)
        writeNext()
    }

    /** The audio frame, as the desktop builds it: 0x5555 | command int16 | checksum | 0xAAAA. */
    private fun writeNext() {
        val g = gatt ?: return
        val c = audio ?: return
        if (busy || commands.isEmpty()) return
        val code = commands.removeFirst()
        writing = code
        val low = code and 0xff
        val high = (code shr 8) and 0xff
        val frame = byteArrayOf(0x55, 0x55, low.toByte(), high.toByte(), ((low + high) and 0xff).toByte(), 0xAA.toByte(), 0xAA.toByte())
        busy = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            g.writeOrRefuse(c, frame, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
        } else {
            c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            @Suppress("DEPRECATION")
            c.value = frame
            @Suppress("DEPRECATION")
            g.writeCharacteristic(c)
        }
    }

    fun disconnect(): Boolean = handler.post {
        wanted = false
        counting = false
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
        if (data.size < 17) return
        val bytes = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val sum = (2 until 14).sumOf { data[it].toInt() and 0xff } and 0xff
        if (bytes.getShort(0).toInt() and 0xffff != 0x5555 || bytes.getShort(15).toInt() and 0xffff != 0xAAAA) return
        if (sum != (data[14].toInt() and 0xff)) return
        val temperatureX10 = bytes.getShort(2).toInt()
        if (temperatureX10 !in -100..500) return // outside the room band: the whole reading is dropped
        val humidityX10 = bytes.getShort(4).toInt()
        val pressureX10 = bytes.getInt(6)
        temperature = temperatureX10 / 10.0
        humidity = if (humidityX10 in 0..1000) humidityX10 / 10.0 else null
        pressure = if (pressureX10 > 0) pressureX10 / 10.0 else null
        altitude = bytes.getInt(10) / 10.0 // as the probe computes it, passed on unfiltered (desktop)
        readAt = SystemClock.elapsedRealtime()
        publish()
    }

    /** The crack count frame; the checksum covers the four bytes of the count. */
    private fun parseCracks(data: ByteArray) {
        if (data.size < 9) return
        val bytes = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val sum = (2 until 6).sumOf { data[it].toInt() and 0xff } and 0xff
        if (bytes.getShort(0).toInt() and 0xffff != 0x5555 || bytes.getShort(7).toInt() and 0xffff != 0xAAAA) return
        if (sum != (data[6].toInt() and 0xff)) return
        cracks = bytes.getInt(2).takeIf { it >= 0 } ?: return
        cracksAt = SystemClock.elapsedRealtime()
        publish()
    }

    /** The drop door frame: checked, then passed on whole (the checksum covers its seven data bytes). */
    private fun parseDoor(data: ByteArray) {
        if (data.size < 12) return
        val bytes = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val sum = (2 until 9).sumOf { data[it].toInt() and 0xff } and 0xff
        if (bytes.getShort(0).toInt() and 0xffff != 0x5555 || bytes.getShort(10).toInt() and 0xffff != 0xAAAA) return
        if (sum != (data[9].toInt() and 0xff)) return
        val open = data[2].toInt() == 1
        val openings = bytes.getShort(3).toInt() and 0xffff
        if (open != doorOpen || openings != doorOpenings) AppLog.state("Door", "${if (open) "open" else "closed"} $openings")
        doorOpen = open
        doorOpenings = openings
        doorFrame = data.copyOf(12).joinToString("") { "%02x".format(it) }
        doorAt = SystemClock.elapsedRealtime()
        doorSeq++
        publish()
    }

    private fun answered(c: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
        busy = false
        answerAt = SystemClock.elapsedRealtime()
        if (status == BluetoothGatt.GATT_SUCCESS) {
            when {
                c === audio -> parseCracks(value)
                c === door -> parseDoor(value)
                else -> parse(value)
            }
        }
        val g = gatt
        if (countAsked && commands.isEmpty() && g != null) {
            countAsked = false
            audio?.let { busy = g.readCharacteristic(it) }
        } else if (doorAsked && commands.isEmpty() && g != null) {
            doorAsked = false
            door?.let { busy = g.readCharacteristic(it) }
        }
        writeNext()
    }

    private fun close() {
        handler.removeCallbacks(tick)
        handler.removeCallbacksAndMessages(RECONNECT)
        gatt?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
        environment = null
        audio = null
        door = null
        doorAsked = false
        doorFrame = null
        commands.clear()
        busy = false
        writing = null
        countAsked = false
        cracks = null
        temperature = null; humidity = null; pressure = null; altitude = null
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
        onState(JSONObject().put("state", state)
            .put("temperature_c", temperature ?: JSONObject.NULL)
            .put("humidity_pct", humidity ?: JSONObject.NULL)
            .put("pressure_hpa", pressure ?: JSONObject.NULL)
            .put("altitude_m", altitude ?: JSONObject.NULL)
            .put("cracks", cracks ?: JSONObject.NULL)
            .put("door", doorFrame ?: JSONObject.NULL)
            .put("door_seq", doorSeq)
            .put("door_age_ms", if (doorFrame != null) SystemClock.elapsedRealtime() - doorAt else 0L))
    }

    private companion object {
        val SERVICE_UUID: UUID = UUID.fromString("f3b6e2a0-8c4e-4e1f-9c2d-1a7f5b9a1c01")
        const val ENVIRONMENT_SUFFIX = "-8c4e-4e1f-9c2d-1a7f5b9a1c05"
        const val AUDIO_SUFFIX = "-8c4e-4e1f-9c2d-1a7f5b9a1c04" // the crack counter's channel (read, write)
        const val DOOR_SUFFIX = "-8c4e-4e1f-9c2d-1a7f5b9a1c06" // the drop door contact (read)
        const val START = 0x0001 // the desktop's start and stop of the count
        const val STOP = 0x0002
        const val POLL_MS = 1000L
        const val MAX_AGE_MS = 3000L
        const val LOST_MS = 5000L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val RECONNECT_MS = 2000L
        val RECONNECT = Any()
    }
}
