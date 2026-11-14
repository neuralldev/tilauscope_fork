// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import java.io.File

/**
 * A .tilaucoffee opened from, or shared by, another app. Such a file arrives as a content:// URI whose type is
 * generic (octet-stream, zip): only the display name says what it is. It is copied into the app's cache before
 * anything reads it, under a name of the app's own: what the other app calls it never builds a path.
 */
object CoffeeFiles {
    const val EXTENSION = ".tilaucoffee"
    const val FOLDER = "coffee-open"
    const val MAX_BYTES = 64L shl 20 // as tilaucore.coffee_share.MAX_PACKAGE_BYTES: a larger file is not copied at all

    /** The file an intent offers: the data of a view, the stream of a share. Only a content URI: no file path of another app's choosing. */
    fun uriOf(intent: Intent): Uri? {
        val uri = when (intent.action) {
            Intent.ACTION_VIEW -> intent.data
            Intent.ACTION_SEND ->
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
                else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_STREAM)
            else -> null
        }
        return uri?.takeIf { it.scheme == ContentResolver.SCHEME_CONTENT }
    }

    /** What the provider says of the file: its display name and its size (-1 when it does not say). */
    private fun described(resolver: ContentResolver, uri: Uri): Pair<String?, Long> {
        try {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use {
                if (it.moveToFirst()) return it.getString(0) to (if (it.isNull(1)) -1L else it.getLong(1))
            }
        } catch (error: RuntimeException) { // a provider that refuses or has gone
        }
        return null to -1L
    }

    /** The copy in the cache, or null: not a .tilaucoffee by its display name, over the cap, or unreadable. */
    fun copy(context: Context, uri: Uri): File? {
        val (name, size) = described(context.contentResolver, uri)
        val shown = name ?: uri.lastPathSegment ?: ""
        if (!shown.lowercase().endsWith(EXTENSION) || size > MAX_BYTES) return null // refused before a byte is read
        val folder = File(context.cacheDir, FOLDER).apply { deleteRecursively(); mkdirs() }
        val target = File(folder, "opened$EXTENSION")
        return try {
            val input = context.contentResolver.openInputStream(uri) ?: return null
            input.use { source ->
                target.outputStream().use { out ->
                    val buffer = ByteArray(1 shl 16)
                    var total = 0L
                    while (true) {
                        val n = source.read(buffer)
                        if (n < 0) break
                        total += n
                        if (total > MAX_BYTES) { // a provider that did not say its size
                            target.delete()
                            return null
                        }
                        out.write(buffer, 0, n)
                    }
                }
            }
            target
        } catch (error: Exception) { // IOException, SecurityException, a provider that dies mid-copy
            target.delete()
            null
        }
    }
}
