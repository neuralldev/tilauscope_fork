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
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

/**
 * Niimbot B21S label printer, same protocol and print flow as the desktop driver
 * (niimprint.py, D110M V4 firmware): packets 55 55 type len data xor AA AA, one
 * packet per write without response, an answer to a request is its type + 1.
 * Every exchange runs on one job thread, so the keep-alive never cuts into a
 * print. Two keep-alives in a row without an answer are a lost printer. A print
 * ends PRINTED (the printer reported the label out), FAILED (stopped before any
 * label data was sent) or UNCONFIRMED (sent, never reported out).
 * [onState] receives each change.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
class PrinterLink(private val context: Context, private val onState: (JSONObject) -> Unit) {
    private val jobs = Executors.newSingleThreadScheduledExecutor()
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
    private val answers = LinkedBlockingQueue<Packet>()
    private val written = Semaphore(0)

    // Job thread only, except where noted.
    @Volatile private var gatt: BluetoothGatt? = null
    @Volatile private var channel: BluetoothGattCharacteristic? = null
    @Volatile private var lastStatus: ByteArray? = null // print status (0xB3), set by notifications
    private var address: String? = null
    private var wanted = false
    private var state = "idle"
    private var keepAlive: ScheduledFuture<*>? = null
    private var missed = 0
    private var battery: Int? = null
    private var cover: Int? = null
    private var paper: Int? = null
    private var rollType: Int? = null
    private var labelsLeft: Int? = null
    private var labelsTotal: Int? = null
    private var print: String? = null // sending, printing, printed, unconfirmed, failed
    private var progress = 0
    private var failure: String? = null // no_answer, cover_open

    private class Packet(val type: Int, val data: ByteArray) {
        fun bytes(): ByteArray {
            var sum = type xor data.size
            data.forEach { sum = sum xor (it.toInt() and 0xff) }
            return byteArrayOf(0x55, 0x55, type.toByte(), data.size.toByte()) + data +
                byteArrayOf(sum.toByte(), 0xAA.toByte(), 0xAA.toByte())
        }

        companion object {
            fun parse(raw: ByteArray): Packet? {
                if (raw.size < 7 || raw[0] != 0x55.toByte() || raw[1] != 0x55.toByte()) return null
                if (raw[raw.size - 1] != 0xAA.toByte() || raw[raw.size - 2] != 0xAA.toByte()) return null
                val type = raw[2].toInt() and 0xff
                val length = raw[3].toInt() and 0xff
                if (4 + length > raw.size - 3) return null
                val data = raw.copyOfRange(4, 4 + length)
                var sum = type xor length
                data.forEach { sum = sum xor (it.toInt() and 0xff) }
                return if (sum.toByte() == raw[raw.size - 3]) Packet(type, data) else null
            }
        }
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                jobs.execute { if (g === gatt) g.requestMtu(MTU_REQUEST) }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED || status != BluetoothGatt.GATT_SUCCESS) {
                if (g === gatt) channel = null // a waiting print gives up at once
                jobs.execute { if (g === gatt) drop() }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, value: Int, status: Int) {
            jobs.execute { if (g === gatt) g.discoverServices() }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            jobs.execute {
                if (g !== gatt) return@execute
                val c = g.getService(SERVICE_UUID)?.getCharacteristic(CHANNEL_UUID)
                val cccd = c?.getDescriptor(CCCD_UUID)
                if (cccd == null || !g.setCharacteristicNotification(c, true)) {
                    drop()
                    return@execute
                }
                channel = c
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
            jobs.execute {
                if (g !== gatt) return@execute
                if (status != BluetoothGatt.GATT_SUCCESS) drop() else greet()
            }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            if (g === gatt) written.release()
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
            if (g === gatt) received(value)
        }

        @Deprecated("Called before Android 13 only")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            val value = c.value ?: return
            if (g === gatt) received(value)
        }
    }

    /** Any thread. Keeps looking for the printer until [disconnect]. */
    fun connect(address: String) {
        jobs.execute {
            if (wanted && address == this.address) {
                publish()
                return@execute
            }
            close()
            this.address = address
            wanted = true
            open()
        }
    }

    fun disconnect() {
        jobs.execute {
            wanted = false
            close()
            set("idle")
        }
    }

    fun release() {
        jobs.execute {
            wanted = false
            close()
        }
        jobs.shutdown()
    }

    /** One label: [rows] is the image, 48 bytes a row, most significant bit on the left, 1 = ink. */
    fun printLabel(rows: ByteArray) {
        jobs.execute {
            if (state != "connected" || print == "sending" || print == "printing") return@execute
            print = "sending"
            progress = 0
            failure = null
            publish()
            print = run(rows)
            publish()
        }
    }

    private fun open() {
        val device = address?.let { a -> adapter?.takeIf { it.isEnabled }?.getRemoteDevice(a) } ?: run {
            set("bluetooth_off")
            retryLater() // until Bluetooth is back
            return
        }
        set("connecting")
        val attempt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        gatt = attempt
        jobs.schedule({ if (gatt === attempt && state == "connecting") drop() }, CONNECT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
    }

    /** As the desktop does on connect: the initial packet, a heartbeat, the roll's tag. */
    private fun greet() {
        write(INITIAL_PACKET)
        Thread.sleep(100)
        if (!heartbeat()) {
            drop()
            return
        }
        readRoll()
        missed = 0
        state = "connected"
        publish()
        keepAlive = jobs.scheduleWithFixedDelay({
            if (state != "connected") return@scheduleWithFixedDelay
            if (heartbeat()) missed = 0 else if (++missed >= 2) drop() else return@scheduleWithFixedDelay
            publish()
        }, HEARTBEAT_MS, HEARTBEAT_MS, TimeUnit.MILLISECONDS)
    }

    private fun run(rows: ByteArray): String {
        if (!heartbeat()) return fail("no_answer")
        if ((paper ?: 0) != 0 || (cover ?: 0) != 0) return fail("cover_open")
        if (exchange(SET_LABEL_DENSITY, byteArrayOf(DENSITY.toByte()), 16) == null) return fail("no_answer")
        if (exchange(SET_LABEL_TYPE, byteArrayOf((rollType ?: 0).toByte()), 16) == null) return fail("no_answer")
        val height = rows.size / ROW_BYTES
        // From printStart on, a job may be open on the printer: close it before giving up.
        var ready = exchange(START_PRINT, byteArrayOf(0, 1, 0, 0, 0, 0, 0, 0, 0)) != null
        if (ready) {
            write(Packet(GET_PRINT_STATUS, ByteArray(0)).bytes())
            val size = byteArrayOf((height shr 8).toByte(), height.toByte(), (WIDTH shr 8).toByte(), WIDTH.toByte(), 0, 1) +
                ByteArray(7)
            ready = exchange(SET_DIMENSION, size) != null
        }
        if (!ready) {
            exchange(END_PRINT, byteArrayOf(1))
            return fail("no_answer")
        }
        Thread.sleep(PACKET_INTERVAL_MS)
        val packets = packets(rows, height)
        packets.forEachIndexed { i, packet ->
            if (!write(packet)) return "unconfirmed"
            Thread.sleep(PACKET_INTERVAL_MS)
            val now = 100 * (i + 1) / packets.size
            if (now >= progress + 10 || i == packets.size - 1) {
                progress = now
                publish()
            }
        }
        print = "printing"
        publish()
        exchange(END_PAGE_PRINT, byteArrayOf(1))
        val out = waitLabelOut()
        exchange(END_PRINT, byteArrayOf(1))
        if (out) labelsLeft = labelsLeft?.let { maxOf(0, it - 1) }
        return if (out) "printed" else "unconfirmed"
    }

    private fun fail(reason: String): String {
        failure = reason
        return "failed"
    }

    /** Rows as the desktop encodes them: empty (0x84), a few dots (0x83) or a bitmap (0x85); identical rows repeat. */
    private fun packets(rows: ByteArray, height: Int): List<ByteArray> {
        val out = mutableListOf<ByteArray>()
        var y = 0
        while (y < height) {
            val row = rows.copyOfRange(y * ROW_BYTES, (y + 1) * ROW_BYTES)
            var run = 1
            while (y + run < height && (y + run) % MAX_ROWS_PER_BLOCK != 0 && run < 255 &&
                rows.copyOfRange((y + run) * ROW_BYTES, (y + run + 1) * ROW_BYTES).contentEquals(row)) run++
            val thirds = IntArray(3) { t -> (0 until 16).sumOf { Integer.bitCount(row[t * 16 + it].toInt() and 0xff) } }
            val count = thirds.sum()
            val yy = byteArrayOf((y shr 8).toByte(), y.toByte())
            out += if (count == 0) {
                Packet(PRINT_EMPTY_ROW, yy + byteArrayOf(run.toByte())).bytes()
            } else {
                val header = yy + byteArrayOf(minOf(thirds[0], 255).toByte(), minOf(thirds[1], 255).toByte(),
                    minOf(thirds[2], 255).toByte(), run.toByte())
                if (count <= 6) {
                    val dots = (0 until WIDTH).filter { x -> (row[x / 8].toInt() shr (7 - x % 8)) and 1 == 1 }
                        .flatMap { x -> listOf((x shr 8).toByte(), x.toByte()) }.toByteArray()
                    Packet(PRINT_BITMAP_ROW_INDEXED, header + dots).bytes()
                } else {
                    Packet(PRINT_BITMAP_ROW, header + row).bytes()
                }
            }
            y += run
        }
        return out
    }

    /** Polls the print status until the printer reports the label out; the wait restarts at each label. */
    private fun waitLabelOut(): Boolean {
        val deadline = System.currentTimeMillis() + LABEL_OUT_TIMEOUT_MS
        while (System.currentTimeMillis() < deadline) {
            if (channel == null) return false
            lastStatus = null
            write(Packet(GET_PRINT_STATUS, ByteArray(0)).bytes())
            val polled = System.currentTimeMillis()
            while (System.currentTimeMillis() - polled < STATUS_POLL_MS && lastStatus == null) Thread.sleep(20)
            val s = lastStatus
            if (s != null && s.size >= 4 && (((s[0].toInt() and 0xff) shl 8) or (s[1].toInt() and 0xff)) >= 1) return true
        }
        return false
    }

    private fun heartbeat(): Boolean {
        val data = exchange(HEARTBEAT, byteArrayOf(1))?.data ?: return false
        fun at(i: Int) = data[i].toInt() and 0xff
        when (data.size) { // layouts read by the desktop
            20 -> { paper = at(18) }
            13 -> { cover = at(9); battery = at(10); paper = at(11) }
            19 -> { cover = at(15); battery = at(16); paper = at(17) }
            10 -> { cover = at(8); battery = at(9) }
            9 -> { cover = at(8) }
        }
        return true
    }

    private fun readRoll() {
        val data = exchange(GET_RFID, byteArrayOf(1))?.data ?: return
        if (data.isEmpty() || data[0].toInt() == 0) return
        try {
            var i = 8
            i += 1 + (data[i].toInt() and 0xff) // barcode
            i += 1 + (data[i].toInt() and 0xff) // serial
            if (data.size - i >= 4) {
                labelsTotal = ((data[i].toInt() and 0xff) shl 8) or (data[i + 1].toInt() and 0xff)
                labelsLeft = ((data[i + 2].toInt() and 0xff) shl 8) or (data[i + 3].toInt() and 0xff)
            }
            if (data.size - i >= 5) rollType = data[i + 4].toInt() and 0xff
        } catch (_: IndexOutOfBoundsException) {
            // an unexpected tag layout never breaks the connection
        }
    }

    /** Sends a request and returns the printer's answer to it, or null (none within a second, or a refusal). */
    private fun exchange(type: Int, data: ByteArray, offset: Int = 1): Packet? {
        answers.clear() // whatever is still there answers a request that already gave up
        if (!write(Packet(type, data).bytes())) return null
        Thread.sleep(PACKET_INTERVAL_MS)
        val deadline = System.currentTimeMillis() + ANSWER_MS
        while (true) {
            val left = deadline - System.currentTimeMillis()
            if (left <= 0) return null
            val p = answers.poll(minOf(left, 100), TimeUnit.MILLISECONDS) ?: continue
            if (p.type == type + offset) return p
            if (p.type in ERROR_TYPES) return null
        }
    }

    private fun received(raw: ByteArray) {
        val p = Packet.parse(raw) ?: return
        when (p.type) {
            PRINTER_ACK -> Unit
            PRINT_STATUS_ANSWER -> lastStatus = p.data
            else -> answers.offer(p)
        }
    }

    private fun write(bytes: ByteArray): Boolean {
        val g = gatt ?: return false
        val c = channel ?: return false
        written.drainPermits()
        val accepted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            g.writeOrRefuse(c, bytes, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
        } else {
            c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            @Suppress("DEPRECATION")
            c.value = bytes
            @Suppress("DEPRECATION")
            g.writeCharacteristic(c)
        }
        return accepted && written.tryAcquire(WRITE_MS, TimeUnit.MILLISECONDS)
    }

    private fun close() {
        keepAlive?.cancel(false)
        keepAlive = null
        channel = null
        gatt?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
        battery = null; cover = null; paper = null; rollType = null; labelsLeft = null; labelsTotal = null
        print = null
        failure = null
    }

    private fun drop() {
        val last = print
        val reason = failure
        close()
        // A label being sent or burnt when the link went may be out, or blank.
        print = if (last == "sending" || last == "printing") "unconfirmed" else last
        failure = reason
        set("lost")
        retryLater()
    }

    private fun retryLater() {
        if (wanted) jobs.schedule({ if (wanted && gatt == null) open() }, RECONNECT_MS, TimeUnit.MILLISECONDS)
    }

    private fun set(value: String) {
        state = value
        publish()
    }

    private fun publish() {
        onState(JSONObject().put("state", state).put("battery", battery ?: JSONObject.NULL).put("cover", cover ?: JSONObject.NULL)
            .put("paper", paper ?: JSONObject.NULL).put("roll_type", rollType ?: JSONObject.NULL)
            .put("labels_left", labelsLeft ?: JSONObject.NULL).put("labels_total", labelsTotal ?: JSONObject.NULL)
            .put("print", print ?: JSONObject.NULL).put("progress", progress).put("failure", failure ?: JSONObject.NULL))
    }

    private companion object {
        val SERVICE_UUID: UUID = UUID.fromString("e7810a71-73ae-499d-8c15-faa9aef0c3f2")
        val CHANNEL_UUID: UUID = UUID.fromString("bef8d6c9-9c21-4c9e-b632-bd58c1009f9f")
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        val INITIAL_PACKET = byteArrayOf(0xC1.toByte(), 0x01, 0x01, 0xC1.toByte())
        const val GET_RFID = 0x1A
        const val HEARTBEAT = 0xDC
        const val SET_LABEL_TYPE = 0x23
        const val SET_LABEL_DENSITY = 0x21
        const val START_PRINT = 0x01
        const val END_PRINT = 0xF3
        const val END_PAGE_PRINT = 0xE3
        const val SET_DIMENSION = 0x13
        const val GET_PRINT_STATUS = 0xA3
        const val PRINT_STATUS_ANSWER = 0xB3
        const val PRINT_BITMAP_ROW_INDEXED = 0x83
        const val PRINT_EMPTY_ROW = 0x84
        const val PRINT_BITMAP_ROW = 0x85
        const val PRINTER_ACK = 0xD3
        val ERROR_TYPES = setOf(0x00, 0xDA, 0xDB)
        const val DENSITY = 3
        const val WIDTH = 384
        const val ROW_BYTES = WIDTH / 8
        const val MAX_ROWS_PER_BLOCK = 200
        const val MTU_REQUEST = 247
        const val PACKET_INTERVAL_MS = 20L
        const val ANSWER_MS = 1000L
        const val WRITE_MS = 1000L
        const val STATUS_POLL_MS = 300L
        const val LABEL_OUT_TIMEOUT_MS = 12_000L
        const val HEARTBEAT_MS = 5000L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val RECONNECT_MS = 2000L
    }
}
