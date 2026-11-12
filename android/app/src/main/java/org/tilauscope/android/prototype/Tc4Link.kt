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
 * TC4-over-BLE link to the Skywalker V2 (bridge TD5325A), same protocol and
 * safety sequence as the desktop transport (`tc4ble`): connecting alone may switch
 * the burner on, so OT1,0 is asserted and verified on a fresh echo before anything
 * else, at every connection. Connecting also starts the air and the drum; letting go
 * on purpose sends OT1,0 then OFF, which stops the whole machine.
 *
 * Two uses. The link check (Settings) never commands the burner above 0. The roast
 * link ([connect] with roast) sends the session's commands; the burner is held to
 * what was commanded (an echo above it is corrected at once, twice raises an alert).
 * When it drops or goes silent during the roast, the roaster emergency-stops by
 * itself; the link reconnects by address (0.5, 1, then 2 s between attempts) and,
 * once the burner is verified at 0 again, sends the air and drum back but never the
 * burner: it is held at its echo and reported as `recovered`.
 * Let go on purpose while roasting (End roast, the app closing), the roaster is cooled
 * first: the end script given at [connect] (burner 0, cooling, air full, drum 80 %, then
 * a wait until the bean probe is under its threshold) runs on the real readings, then
 * OFF. No valid bean reading never counts as cooled: the roaster is not stopped on a guess.
 * A new roast started while it cools takes the same link: the cooling stops (CLDN,OF),
 * the burner is verified at 0, and the preheat starts from where the roaster is.
 * Everything runs on the link's own thread; [onState] receives each change.
 */
@SuppressLint("MissingPermission") // the caller has checked BLUETOOTH_CONNECT
class Tc4Link(private val context: Context, private val onState: (JSONObject) -> Unit) {
    private val thread = HandlerThread("tc4-link").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    private var tx: BluetoothGattCharacteristic? = null
    private var mtu = 20
    private val queue = ArrayDeque<ByteArray>()
    private var writing = false
    private var writeAt = 0L
    private var closing: String? = null // final state once the queue has drained
    private var shutdown = false
    private val buffer = StringBuilder()

    private var state = "idle"
    private var ambient: Double? = null
    private var bt: Double? = null
    private var et: Double? = null
    private var burner: Int? = null
    private var burnerAt = 0L
    private var air: Int? = null
    private var lastRx = 0L
    private var testEnd = 0L

    // The roast link: what was commanded, and whether a dropped link is to be recovered.
    private var address: String? = null
    private var roast = false
    private var live = false // connected at least once in this roast: a drop is recovered
    private var cmdBurner = 0
    private var cmdAir: Int? = null
    private var cmdDrum: Int? = null
    private var mismatch = 0
    private var reconnectDelay = 0L
    private var recovered = false // one-shot: published once after a recovery
    private var alert: String? = null // one-shot: published once
    private var endScript: List<String> = emptyList() // what letting go of a hot roast runs first
    private val script = ArrayDeque<String>() // commands still to send, a wait among them
    private var afterScript: String? = null // the final state once the script has run

    private val tick = object : Runnable {
        override fun run() {
            if (state != "connected" && state != "cooling") return
            val now = SystemClock.elapsedRealtime()
            if (now - lastRx > RX_STALL_MS) {
                // A silent link: in a roast it is dropped and reconnected (never stopped on purpose).
                if (roast) lost() else close("lost")
                return
            }
            if (writing && now - writeAt > WRITE_STALL_MS) writing = false // no write callback came back
            send(READ)
            handler.postDelayed(this, POLL_MS)
        }
    }

    private val endTest = Runnable {
        if (testEnd == 0L) return@Runnable
        testEnd = 0L
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
                val all = g.services.flatMap { it.characteristics }
                val rx = all.firstOrNull { it.uuid == RX_UUID }
                tx = all.firstOrNull { it.uuid == TX_UUID }
                val cccd = rx?.getDescriptor(CCCD_UUID)
                if (tx == null || cccd == null || !g.setCharacteristicNotification(rx, true)) {
                    drop("failed")
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
                    drop("failed")
                    return@post
                }
                // Subscribed first so the burner echo can be checked.
                if (state != "reconnecting") state = "verifying"
                publish()
                buffer.clear()
                burner = null
                send(CHAN_INIT)
                verify(0)
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

    /** Any thread. Replaces a previous link, which is let go safely first. [roast]: the roast link. */
    fun connect(address: String, roast: Boolean = false, endScript: List<String> = emptyList()): Boolean = handler.post {
        if (roast && state == "cooling" && gatt != null && address == this.address) {
            // Back to back: the cooling stops and the next roast takes this link, its burner verified at 0.
            script.clear()
            afterScript = null
            send(COOLING_OFF)
            this.roast = true
            this.endScript = endScript
            live = false
            cmdBurner = 0; cmdAir = null; cmdDrum = null; mismatch = 0; reconnectDelay = 0L
            set("verifying")
            verify(0)
            return@post
        }
        if (gatt != null) {
            close("idle")
            handler.postDelayed({ connect(address, roast, endScript) }, CLOSE_WAIT_MS + RETRY_MS)
            return@post
        }
        this.address = address
        this.roast = roast
        this.endScript = endScript
        script.clear() // nothing left from an earlier roast reaches this one
        afterScript = null
        live = false
        cmdBurner = 0; cmdAir = null; cmdDrum = null; mismatch = 0; reconnectDelay = 0L
        resetReadings()
        set("connecting")
        open()
    }

    private fun open() {
        val device: BluetoothDevice = adapter?.takeIf { it.isEnabled }?.getRemoteDevice(address) ?: run {
            if (roast) retry() else set("bluetooth_off")
            return
        }
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        val attempt = gatt
        handler.postDelayed({
            if (gatt === attempt && (state == "connecting" || state == "reconnecting")) drop("failed")
        }, CONNECT_TIMEOUT_MS)
    }

    /** Any thread. Raises the air for the test, then stops the roaster and lets go. */
    fun airTest(): Boolean = handler.post {
        if (state != "connected" || roast || testEnd != 0L) return@post
        send("OT2,$TEST_AIR")
        testEnd = SystemClock.elapsedRealtime() + TEST_MS
        handler.postDelayed(endTest, TEST_MS)
        publish()
    }

    /** Any thread. The roast link's commands, in order (OTn,<value>, EVT,<n>, OFF, UNTIL_BT_BELOW,<°C>). */
    fun command(commands: List<String>): Boolean = handler.post {
        if (!roast) return@post
        // While away, kept for the recovery, the heat excepted: the burner stays at 0 until the operator raises it.
        script.addAll(if (state == "connected" || state == "cooling") commands else keptWhileAway(commands))
        runScript()
    }

    /** Sends the script in order; a wait holds the rest until the bean probe is under its value. */
    private fun runScript() {
        while (script.isNotEmpty() && (state == "connected" || state == "cooling")) {
            val head = script.first()
            if (head.startsWith(UNTIL)) {
                val below = head.substringAfter(",").toDoubleOrNull() ?: Double.NEGATIVE_INFINITY
                val now = bt
                if (now == null || now <= 0.0 || now >= below) return // no valid reading is not cooled
                AppLog.i(TAG, "Cooled: bean probe $now °C under $below °C")
                script.removeFirst()
                continue
            }
            val cmd = normalise(script.removeFirst())
            track(cmd)
            send(cmd)
        }
        if (script.isEmpty()) afterScript?.let { final -> afterScript = null; close(final) }
    }

    /** Let go on purpose: a hot roast is cooled first (its end script), then stopped and closed. */
    private fun letGoCooled(final: String) {
        if (roast && state == "connected" && (script.isNotEmpty() || endScript.isNotEmpty())) {
            if (script.isEmpty()) script.addAll(endScript)
            AppLog.i(TAG, "Let go hot: $script")
            roast = false // ending: no reconnection, no recovery
            live = false
            afterScript = final
            set("cooling")
            runScript()
            return
        }
        roast = false
        live = false
        if (gatt != null) close(final) else {
            script.clear() // no link to run it on: an end script never waits for the next roast
            afterScript = null
            if (state != "idle") set("idle")
        }
    }

    /** Any thread. Test of the recovery: lets the roast link go at once, as a real drop (no stop sent). */
    fun dropForTest(): Boolean = handler.post {
        if (roast && state == "connected") lost()
    }

    /** Any thread. Burner off, the roast cooled first, machine stopped, then the link is let go. */
    fun disconnect(): Boolean = handler.post {
        handler.removeCallbacksAndMessages(RECONNECT)
        letGoCooled("idle")
    }

    /** Any thread. As [disconnect], then the link's thread ends. */
    fun release(): Boolean = handler.post {
        shutdown = true
        handler.removeCallbacksAndMessages(RECONNECT)
        if (gatt != null) letGoCooled("idle") else thread.quitSafely()
    }

    private fun verify(attempt: Int) {
        if (attempt == VERIFY_TRIES) {
            AppLog.e(TAG, "Burner OFF unconfirmed after $VERIFY_TRIES attempts (last echo $burner)")
            alert = "burner_unconfirmed"
            close("burner_unconfirmed")
            return
        }
        val sentAt = SystemClock.elapsedRealtime()
        send("OT1,0")
        send(READ)
        val current = gatt
        handler.postDelayed({
            if (gatt !== current || (state != "verifying" && state != "reconnecting")) return@postDelayed
            // Only a zero read back after this command counts.
            if (burner == 0 && burnerAt > sentAt) {
                cmdBurner = 0
                mismatch = 0
                if (roast && live) {
                    // Back into a live roast: the mechanical state again, never the heat.
                    cmdAir?.let { send("OT2,$it") }
                    cmdDrum?.let { send("OT3,$it") }
                    recovered = true
                    AppLog.i(TAG, "Roast link recovered: air=$cmdAir drum=$cmdDrum, burner held at 0")
                }
                if (roast) live = true
                reconnectDelay = 0L
                state = "connected"
                lastRx = SystemClock.elapsedRealtime()
                publish()
                handler.postDelayed(tick, POLL_MS)
                runScript() // what was asked while the link was away (a cooling, a stop)
            } else {
                verify(attempt + 1)
            }
        }, VERIFY_WAIT_MS)
    }

    private fun receive(value: ByteArray) {
        for (line in tc4Lines(buffer, String(value, Charsets.US_ASCII))) parse(line)
    }

    private fun parse(line: String) {
        val frame = tc4Frame(line) ?: return
        ambient = frame.ambient
        et = frame.et
        bt = frame.bt
        burner = frame.burner
        burnerAt = SystemClock.elapsedRealtime()
        air = frame.air
        lastRx = burnerAt
        // The burner never above what was commanded (0 for the link check): corrected at once.
        val echo = burner
        if ((state == "connected" || state == "cooling") && echo != null && echo > cmdBurner) {
            AppLog.w(TAG, "Burner echo $echo above the commanded $cmdBurner, asserting it again")
            send("OT1,$cmdBurner")
            mismatch++
            if (mismatch == 2) alert = "burner_overshoot"
        } else if (echo != null) {
            mismatch = 0
        }
        if (script.isNotEmpty()) runScript()
        if (state == "connected" || state == "cooling") publish()
    }

    /** Whole numbers, as the firmware wants them (OT2,25 not OT2,25.0); the burner within 0–100. */
    private fun normalise(raw: String): String {
        val head = raw.substringBefore(",").trim()
        val value = raw.substringAfter(",", "").trim().toDoubleOrNull() ?: return raw.trim()
        if (!head.uppercase().startsWith("OT")) return raw.trim()
        val whole = Math.round(value).toInt()
        return "$head,${if (head.equals("OT1", true)) whole.coerceIn(0, 100) else whole}"
    }

    private fun track(cmd: String) {
        val value = cmd.substringAfter(",", "").toIntOrNull() ?: return
        when (cmd.substringBefore(",").uppercase()) {
            "OT1" -> cmdBurner = value
            "OT2" -> cmdAir = value
            "OT3" -> cmdDrum = value
        }
    }

    private fun send(command: String) {
        if (command != READ) AppLog.i(TAG, "→ $command ($state)") // every order to the roaster, the 1 Hz read excepted
        val data = (command + "\n").toByteArray(Charsets.US_ASCII)
        for (offset in data.indices step mtu) queue.addLast(data.copyOfRange(offset, minOf(data.size, offset + mtu)))
        drain()
    }

    private fun drain() {
        val g = gatt ?: return
        val characteristic = tx ?: return
        if (writing) return
        val chunk = queue.removeFirstOrNull()
        if (chunk == null) {
            closing?.let { finish(it) }
            return
        }
        val accepted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            g.writeOrRefuse(characteristic, chunk, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
        } else {
            characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            @Suppress("DEPRECATION")
            characteristic.value = chunk
            @Suppress("DEPRECATION")
            g.writeCharacteristic(characteristic)
        }
        if (accepted) {
            writing = true
            writeAt = SystemClock.elapsedRealtime()
        } else { // the stack is busy: try the same chunk again shortly
            queue.addFirst(chunk)
            handler.postDelayed({ drain() }, RETRY_MS)
        }
    }

    /** Queues the stop, then lets go once it is written (or after a short wait). */
    private fun close(final: String) {
        script.clear()
        afterScript = null
        handler.removeCallbacks(tick)
        handler.removeCallbacks(endTest)
        testEnd = 0L
        send("OT1,0")
        send(OFF)
        closing = final
        val current = gatt
        handler.postDelayed({ if (gatt === current && closing != null) finish(final) }, CLOSE_WAIT_MS)
    }

    private fun finish(final: String) {
        letGo(gatt)
        closing = null
        resetReadings()
        // The roast link keeps trying, as the desktop's reconnect driver does.
        if (roast && !shutdown) retry() else set(final)
        if (shutdown) thread.quitSafely()
    }

    /** The link is already gone: nothing can be written any more. */
    private fun drop(final: String) {
        handler.removeCallbacks(tick)
        handler.removeCallbacks(endTest)
        testEnd = 0L
        queue.clear()
        if (!roast) { // not recovered: what was still to run goes with the link
            script.clear()
            afterScript = null
        }
        finish(final)
    }

    /** The roast link went away or went silent: the roaster has stopped its burner; reconnect. */
    private fun lost() {
        handler.removeCallbacks(tick)
        queue.clear()
        letGo(gatt)
        resetReadings()
        retry()
    }

    private fun retry() {
        state = "reconnecting"
        publish()
        reconnectDelay = if (reconnectDelay == 0L) RECONNECT_FIRST_MS else minOf(RECONNECT_CAP_MS, reconnectDelay * 2)
        handler.postAtTime({ if (roast && gatt == null && state == "reconnecting") open() },
            RECONNECT, SystemClock.uptimeMillis() + reconnectDelay)
    }

    private fun letGo(g: BluetoothGatt?) {
        g?.let {
            it.disconnect()
            it.close()
        }
        gatt = null
        tx = null
        queue.clear()
        writing = false
    }

    private fun resetReadings() {
        ambient = null; bt = null; et = null; burner = null; air = null
        buffer.clear()
    }

    private fun set(value: String) {
        state = value
        publish()
    }

    private fun publish() {
        val left = if (testEnd == 0L) JSONObject.NULL
            else ((testEnd - SystemClock.elapsedRealtime() + 999) / 1000).coerceAtLeast(0)
        onState(JSONObject().put("state", state).put("roast", roast)
            .put("bt", bt ?: JSONObject.NULL).put("et", et ?: JSONObject.NULL)
            .put("ambient", ambient ?: JSONObject.NULL)
            .put("burner", burner ?: JSONObject.NULL).put("air", air ?: JSONObject.NULL)
            .put("recovered", recovered).put("alert", alert ?: JSONObject.NULL)
            .put("test_air", TEST_AIR).put("test_seconds", TEST_MS / 1000).put("test_left", left))
        recovered = false
        alert = null
    }

    private companion object {
        const val TAG = "TilauScopeTc4"
        val RX_UUID: UUID = UUID.fromString("0000ff01-0000-1000-8000-00805f9b34fb") // telemetry
        val TX_UUID: UUID = UUID.fromString("0000ff02-0000-1000-8000-00805f9b34fb") // commands
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        val RECONNECT = Any() // token of the pending reconnection
        const val UNTIL = "UNTIL_BT_BELOW" // pseudo-command of the end script, never sent
        const val CHAN_INIT = "CHAN;1200"
        const val READ = "READ"
        const val OFF = "OFF" // heater, air, drum and cooling off
        const val COOLING_OFF = "CLDN,OF" // the cooling stops; air and drum stay as they are
        const val MTU_REQUEST = 185
        const val VERIFY_TRIES = 6
        const val VERIFY_WAIT_MS = 400L
        const val POLL_MS = 1000L
        const val RX_STALL_MS = 3000L
        const val WRITE_STALL_MS = 1000L
        const val RETRY_MS = 20L
        const val CONNECT_TIMEOUT_MS = 15_000L
        const val CLOSE_WAIT_MS = 600L
        const val RECONNECT_FIRST_MS = 500L
        const val RECONNECT_CAP_MS = 2000L
        const val TEST_AIR = 60
        const val TEST_MS = 10_000L
    }
}

/** A roaster frame after CHAN;1200: ambient, ET, BT, burner echo, air echo (drum probe first, as the desktop reads it). */
internal class Tc4Frame(val ambient: Double, val et: Double, val bt: Double, val burner: Int?, val air: Int?)

/** Null for a malformed line (the three temperatures must be finite numbers): it is never a reading. */
internal fun tc4Frame(line: String): Tc4Frame? {
    val parts = line.split(",")
    fun number(i: Int) = parts.getOrNull(i)?.trim()?.toDoubleOrNull()?.takeIf { it.isFinite() }
    val ambient = number(0) ?: return null
    val et = number(1) ?: return null
    val bt = number(2) ?: return null
    return Tc4Frame(ambient, et, bt, number(3)?.toInt(), number(4)?.toInt())
}

/** Appends [chunk] to [buffer] and takes out its whole lines; a partial line longer than any frame is dropped. */
internal fun tc4Lines(buffer: StringBuilder, chunk: String): List<String> {
    buffer.append(chunk)
    val lines = mutableListOf<String>()
    while (true) {
        val end = buffer.indexOf("\r\n")
        if (end < 0) break
        lines.add(buffer.substring(0, end))
        buffer.delete(0, end + 2)
    }
    if (buffer.length > TC4_MAX_PARTIAL) buffer.clear()
    return lines
}

private const val TC4_MAX_PARTIAL = 256

/** What the roast link keeps of commands given while it is away: never heat, the roaster cut it by itself. */
internal fun keptWhileAway(commands: List<String>): List<String> = commands.filterNot { cmd ->
    cmd.substringBefore(",").trim().equals("OT1", true) && (cmd.substringAfter(",", "").trim().toDoubleOrNull() ?: 0.0) > 0.0
}
