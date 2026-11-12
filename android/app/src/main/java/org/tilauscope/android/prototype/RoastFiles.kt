// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File
import java.io.FileNotFoundException

/**
 * Hands roasts to the app the operator shares them with, read only, for that share
 * alone (granted per intent). Only files of the tablet's roasts folder, of the
 * computer's (path "computer/<name>"), the BeanCave files (path "cave/<name>"), the diagnostic log (path "log/<name>"), or an
 * alarm list as shared, in the unit shown (path "alarms/<name>").
 */
class RoastFiles : ContentProvider() {
    override fun onCreate() = true

    private fun file(uri: Uri): File {
        val sub = if (uri.pathSegments.size == 2) uri.pathSegments[0] else ""
        val folder = File(context!!.filesDir, when (sub) {
            "computer" -> COMPUTER_FOLDER
            "cave" -> SessionService.CAVE_FOLDER
            "alarms" -> ALARMS_FOLDER
            "log" -> LOG_FOLDER
            else -> FOLDER
        }).canonicalFile
        val target = File(folder, uri.lastPathSegment ?: "").canonicalFile
        if (target.parentFile != folder || !target.isFile) throw FileNotFoundException(uri.toString())
        return target
    }

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor =
        ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.MODE_READ_ONLY)

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?,
                       selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
        val target = file(uri)
        return MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)).apply {
            addRow(arrayOf(target.name, target.length()))
        }
    }

    override fun getType(uri: Uri) = if (uri.pathSegments.firstOrNull() == "log") "text/plain" else MIME

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0

    companion object {
        const val FOLDER = "roasts"
        const val COMPUTER_FOLDER = "roasts-computer" // imported from the computer, never sent back as tablet roasts
        const val MIME = "application/octet-stream" // an .alog has no registered type
        const val ALARMS_FOLDER = "alarms-shared" // an alarm list's copy in the unit shown, for the share sheet
        const val LOG_FOLDER = "log-shared" // the diagnostic log as one file, for the share sheet
        fun uri(packageName: String, file: File, computer: Boolean = false): Uri =
            Uri.parse("content://$packageName.roasts/${if (computer) "computer/" else ""}${Uri.encode(file.name)}")
        fun caveUri(packageName: String, file: File): Uri = Uri.parse("content://$packageName.roasts/cave/${Uri.encode(file.name)}")
        fun alarmsUri(packageName: String, file: File): Uri = Uri.parse("content://$packageName.roasts/alarms/${Uri.encode(file.name)}")
        fun logUri(packageName: String, file: File): Uri = Uri.parse("content://$packageName.roasts/log/${Uri.encode(file.name)}")
    }
}
