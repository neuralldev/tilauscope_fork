// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.content.Context
import android.os.Build
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The app's own diagnostic log, what a tester sends with a problem (Settings › General): the start, the
 * operator's commands by name, the devices' states, the roaster's orders, every error with its trace.
 * Two files of 2 MB at most, the older dropped first. Never a password; a Bluetooth address keeps only
 * its maker's half. Each line also goes to Android's log.
 */
object AppLog {
    private const val MAX_BYTES = 2_000_000L
    private val lock = Any()
    private val stamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.ROOT)
    private val address = Regex("\\b([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}):[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\\b")
    private var current: File? = null
    private var older: File? = null
    private val states = HashMap<String, String>()

    /** Once per process: the files, then a line saying which app on which tablet. */
    fun start(context: Context) {
        synchronized(lock) {
            if (current != null) return
            val folder = File(context.filesDir, "log").apply { mkdirs() }
            current = File(folder, "tilauscope.log")
            older = File(folder, "tilauscope.1.log")
        }
        i("TilauScope", "Start ${version(context)} on ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}")
    }

    fun version(context: Context): String = context.packageManager.getPackageInfo(context.packageName, 0)
        .let { "${it.versionName}-${it.longVersionCode}" }

    fun i(tag: String, message: String) { Log.i(tag, message); write("I", tag, message, null) }
    fun w(tag: String, message: String, error: Throwable? = null) { Log.w(tag, message, error); write("W", tag, message, error) }
    fun e(tag: String, message: String, error: Throwable? = null) { Log.e(tag, message, error); write("E", tag, message, error) }

    /** A device's state, written when it changes. */
    fun state(device: String, state: String) {
        val changed = synchronized(lock) { (states.put(device, state) != state) }
        if (changed && state.isNotEmpty()) i("TilauScopeDevices", "$device: $state")
    }

    private fun write(level: String, tag: String, message: String, error: Throwable?) {
        synchronized(lock) {
            val file = current ?: return
            try {
                if (file.length() > MAX_BYTES) {
                    older?.delete()
                    file.renameTo(older!!)
                }
                val text = "${stamp.format(Date())} $level $tag: $message" + (error?.let { "\n" + it.stackTraceToString() } ?: "")
                file.appendText(address.replace(text, "$1:**:**:**") + "\n")
            } catch (failed: Exception) {
                Log.w("TilauScopeLog", "The diagnostic log could not be written", failed)
            }
        }
    }

    /** Both files, older first. */
    fun files(): List<File> = synchronized(lock) { listOfNotNull(older, current).filter { it.exists() } }

    /** The log as one file in [folder], named for the app's version, for the share sheet. */
    fun export(context: Context, folder: File): File {
        folder.mkdirs()
        folder.listFiles()?.forEach { it.delete() }
        val target = File(folder, "TilauScope-Android-${version(context)}-log.txt")
        synchronized(lock) { target.outputStream().use { out -> files().forEach { f -> f.inputStream().use { it.copyTo(out) } } } }
        return target
    }

    /** {"bytes", "since"}: the size of the log and its first line's date, for Settings. */
    fun info(): String {
        val all = files()
        val since = all.firstOrNull()?.useLines { lines -> lines.firstOrNull()?.take(10) } ?: ""
        return """{"bytes":${all.sumOf { it.length() }},"since":"$since"}"""
    }
}
