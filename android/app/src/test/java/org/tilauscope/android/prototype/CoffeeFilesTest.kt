// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Intent
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import java.io.File
import java.io.InputStream

/** A .tilaucoffee from another app: which intents reach the app, and what is copied into the cache. */
@RunWith(RobolectricTestRunner::class)
class CoffeeFilesTest {
    /** A file manager's provider: a generic type, a display name of its own choosing, a size it may not tell. */
    class Provider : ContentProvider() {
        override fun onCreate() = true
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, order: String?): Cursor =
            MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)).apply { addRow(arrayOf<Any?>(name, size)) }
        override fun getType(uri: Uri) = "application/octet-stream"
        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            opened = true
            return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
        }
        override fun insert(uri: Uri, values: ContentValues?): Uri? = null
        override fun delete(uri: Uri, selection: String?, args: Array<out String>?) = 0
        override fun update(uri: Uri, values: ContentValues?, selection: String?, args: Array<out String>?) = 0

        companion object {
            var name: String? = "x.tilaucoffee"
            var size: Long? = null
            var file: File = File("unset")
            var opened = false
        }
    }

    private val context get() = RuntimeEnvironment.getApplication()
    private val uri: Uri = Uri.parse("content://tilau.files/document/42")
    private val bytes = "PK-a-coffee".toByteArray()

    @Before
    fun provider() {
        Robolectric.setupContentProvider(Provider::class.java, "tilau.files")
        Provider.file = File(context.cacheDir.parentFile, "offered.bin").apply { writeBytes(bytes) }
        Provider.name = "x.tilaucoffee"
        Provider.size = bytes.size.toLong()
        Provider.opened = false
    }

    private fun reaches(intent: Intent) = context.packageManager.queryIntentActivities(intent, 0).any { it.activityInfo.name == MainActivity::class.java.name }

    @Test
    fun aContentUriOfAGenericTypeNamedXTilaucoffeeReachesTheApp() {
        for (type in listOf("application/octet-stream", "application/zip")) {
            assertTrue("opened as $type", reaches(Intent(Intent.ACTION_VIEW).setDataAndType(uri, type)))
            assertTrue("shared as $type", reaches(Intent(Intent.ACTION_SEND).setType(type).putExtra(Intent.EXTRA_STREAM, uri)))
        }
        assertFalse("a text file is not offered to the app", reaches(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "text/plain")))
        assertFalse("nor a file path of another app's choosing",
            reaches(Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse("file:///sdcard/x.tilaucoffee"), "application/octet-stream")))
        val copy = CoffeeFiles.copy(context, CoffeeFiles.uriOf(Intent(Intent.ACTION_VIEW, uri))!!)
        assertNotNull(copy)
        assertEquals(String(bytes), copy!!.readText()) // the same bytes, in the cache
        assertEquals(File(context.cacheDir, CoffeeFiles.FOLDER), copy.parentFile)
        assertNull("only a content URI is read", CoffeeFiles.uriOf(Intent(Intent.ACTION_VIEW, Uri.parse("file:///sdcard/x.tilaucoffee"))))
    }

    @Test
    fun anOversizedFileIsRefusedBeforeAnyByteIsCopied() {
        Provider.size = CoffeeFiles.MAX_BYTES + 1
        assertNull(CoffeeFiles.copy(context, uri))
        assertFalse("the file was never opened", Provider.opened)
        assertFalse(File(context.cacheDir, CoffeeFiles.FOLDER + "/opened" + CoffeeFiles.EXTENSION).exists())
    }

    @Test
    fun aFileThatDoesNotSayItsSizeIsStoppedAtTheCapWhileCopying() {
        Provider.size = null
        val endless = object : InputStream() { override fun read() = 0 }
        shadowOf(context.contentResolver).registerInputStream(uri, endless) // Robolectric hands this stream before the provider's
        assertNull(CoffeeFiles.copy(context, uri))
        assertFalse(File(context.cacheDir, CoffeeFiles.FOLDER + "/opened" + CoffeeFiles.EXTENSION).exists())
    }

    @Test
    fun aHostileDisplayNameNeverLeavesTheCacheFolder() {
        for (name in listOf("../../escape.tilaucoffee", "/data/data/evil.tilaucoffee", "..\\..\\evil.tilaucoffee", "a/../../b.tilaucoffee")) {
            Provider.name = name
            val copy = CoffeeFiles.copy(context, uri)
            assertNotNull(name, copy)
            assertEquals(File(context.cacheDir, CoffeeFiles.FOLDER).canonicalFile, copy!!.canonicalFile.parentFile)
            assertEquals("opened" + CoffeeFiles.EXTENSION, copy.name) // the app names its copy
        }
        assertFalse(File(context.cacheDir.parentFile, "escape.tilaucoffee").exists())
        assertFalse(File(context.cacheDir.parentFile, "evil.tilaucoffee").exists())
    }

    @Test
    fun aFileThatIsNotACoffeeIsNotCopied() {
        for (name in listOf("photo.zip", "tilaucoffee", "x.tilaucoffee.exe", null)) {
            Provider.name = name
            assertNull(name, CoffeeFiles.copy(context, uri))
        }
        assertFalse(Provider.opened)
    }
}
