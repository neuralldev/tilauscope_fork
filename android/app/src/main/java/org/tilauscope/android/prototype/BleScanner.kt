// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject

/**
 * Detection only: listens to advertisements, never connects. One scanner for the
 * app, main thread only. Every second it hands over what was heard recently.
 */
class BleScanner(context: Context, private val onBatch: (JSONArray) -> Unit) {
    private class Heard(val name: String?, val rssi: Int, val uuids: List<String>, val at: Long)

    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
    private val main = Handler(Looper.getMainLooper())
    private val heard = mutableMapOf<String, Heard>()
    private var scanning = false

    val enabled get() = adapter?.isEnabled == true

    private val callback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val record = result.scanRecord
            var name = record?.deviceName
            var uuids = record?.serviceUuids?.map { it.toString() } ?: emptyList()
            if (name == null && uuids.isEmpty()) {
                // Android drops a whole advertisement on one malformed field (the AirWave
                // sends a one-byte manufacturer field): read the raw fields instead.
                val parsed = parse(record?.bytes ?: ByteArray(0))
                name = parsed.first
                uuids = parsed.second
            }
            heard[result.device.address] = Heard(name, result.rssi, uuids, SystemClock.elapsedRealtime())
        }
    }

    private val tick = object : Runnable {
        override fun run() {
            val now = SystemClock.elapsedRealtime()
            heard.entries.removeAll { now - it.value.at > FORGET_MS }
            val batch = JSONArray()
            heard.forEach { (address, h) ->
                batch.put(JSONObject().put("address", address).put("name", h.name ?: JSONObject.NULL)
                    .put("rssi", h.rssi).put("uuids", JSONArray(h.uuids)))
            }
            onBatch(batch)
            if (scanning) main.postDelayed(this, 1000)
        }
    }

    /** Caller has checked the permissions; false when Bluetooth is off or missing. */
    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        val scanner = adapter?.takeIf { it.isEnabled }?.bluetoothLeScanner ?: return false
        if (scanning) return true
        heard.clear()
        scanner.startScan(null, ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), callback)
        scanning = true
        main.postDelayed(tick, 1000)
        return true
    }

    @SuppressLint("MissingPermission")
    fun stop() {
        if (!scanning) return
        scanning = false
        main.removeCallbacks(tick)
        runCatching { adapter?.bluetoothLeScanner?.stopScan(callback) } // Bluetooth may be off by now
    }

    companion object {
        private const val FORGET_MS = 10_000L
        private const val BASE_UUID = "-0000-1000-8000-00805f9b34fb"

        /** Local name and service UUIDs from raw advertising fields, skipping what does not parse. */
        fun parse(bytes: ByteArray): Pair<String?, List<String>> {
            var name: String? = null
            val uuids = mutableListOf<String>()
            var i = 0
            while (i < bytes.size) {
                val length = bytes[i].toInt() and 0xff
                if (length == 0 || i + length >= bytes.size) break
                val type = bytes[i + 1].toInt() and 0xff
                val data = bytes.copyOfRange(i + 2, i + 1 + length)
                when (type) {
                    0x08, 0x09 -> if (name == null || type == 0x09) name = String(data, Charsets.UTF_8)
                    0x02, 0x03 -> for (j in 0 until data.size - 1 step 2) {
                        val short = (data[j].toInt() and 0xff) or ((data[j + 1].toInt() and 0xff) shl 8)
                        uuids += "%08x".format(short) + BASE_UUID
                    }
                    0x06, 0x07 -> for (j in 0 until data.size - 15 step 16) {
                        val hex = data.copyOfRange(j, j + 16).reversed().joinToString("") { "%02x".format(it) }
                        uuids += "${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-" +
                            "${hex.substring(16, 20)}-${hex.substring(20)}"
                    }
                }
                i += length + 1
            }
            return name to uuids
        }
    }
}
