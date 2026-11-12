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
