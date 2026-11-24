// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.annotation.SuppressLint
import android.annotation.TargetApi
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.os.Build

/*
 * Android 13's GATT writes throw when the Bluetooth stack dies (Bluetooth switched off): uncaught on a
 * link's thread that closes the whole app, a roast with it. A refused write instead; the link's own loss
 * handling follows, as for any disconnection.
 */

@SuppressLint("MissingPermission") // each link connects only once the permission is granted
@TargetApi(Build.VERSION_CODES.TIRAMISU)
internal fun BluetoothGatt.writeOrRefuse(c: BluetoothGattCharacteristic, value: ByteArray, type: Int): Boolean = try {
    writeCharacteristic(c, value, type) == BluetoothGatt.GATT_SUCCESS
} catch (error: RuntimeException) {
    AppLog.w("TilauScopeGatt", "Write refused: the Bluetooth stack is gone", error)
    false
}

@SuppressLint("MissingPermission")
@TargetApi(Build.VERSION_CODES.TIRAMISU)
internal fun BluetoothGatt.writeOrRefuse(d: BluetoothGattDescriptor, value: ByteArray): Boolean = try {
    writeDescriptor(d, value) == BluetoothGatt.GATT_SUCCESS
} catch (error: RuntimeException) {
    AppLog.w("TilauScopeGatt", "Write refused: the Bluetooth stack is gone", error)
    false
}

/**
 * The wait before searching again for an accessory that does not answer (switched off): 2 s, then longer,
 * so that with the 15 s attempt a search comes every 17 s, 30 s, 1 min, then 2 min. Back to 2 s once it
 * answers, or when a page or its icon asks for it again (Tilau, 2026-11-24).
 */
class RetryDelay {
    private var failures = 0

    fun next(): Long = STEPS_MS[minOf(failures++, STEPS_MS.size - 1)]

    fun reset() { failures = 0 }

    private companion object {
        val STEPS_MS = longArrayOf(2_000, 15_000, 45_000, 105_000)
    }
}
