// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.net.Uri
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.io.File
import java.io.FileNotFoundException

/** A coffee package sent stays an hour (audit 2026-11-21, P4-39): the app it went to may read it later. */
@RunWith(RobolectricTestRunner::class)
class RoastFilesShareTest {
    private val context get() = RuntimeEnvironment.getApplication()

    @Test
    fun aPackageSentStaysAnHourThenGoes() {
        val first = File(RoastFiles.shareFolder(context.cacheDir), "a.tilaucoffee").apply { writeText("a") }
        val second = File(RoastFiles.shareFolder(context.cacheDir), "b.tilaucoffee").apply { writeText("b") }
        assertTrue("the next package deleted the one sent before", first.exists() && second.exists())
        RoastFiles.shareFolder(context.cacheDir, System.currentTimeMillis() + RoastFiles.SHARE_KEPT_MS + 60_000)
        assertFalse("a package over an hour old is cleared", first.exists() || second.exists())
    }

    @Test
    fun aPackageInItsFolderIsServedAndNothingOutsideIs() {
        val provider = Robolectric.setupContentProvider(RoastFiles::class.java, "${context.packageName}.roasts")
        val file = File(RoastFiles.shareFolder(context.cacheDir), "Huila.tilaucoffee").apply { writeText("pk") }
        val uri = RoastFiles.coffeeUri(context.packageName, file)
        assertEquals("pk", provider.openFile(uri, "r").let { pfd ->
            java.io.FileInputStream(pfd.fileDescriptor).use { it.readBytes().decodeToString() } })
        for (bad in listOf("coffee/../x", "coffee/a/../../roasts/x.alog", "coffee/..%2F..%2Fx/y")) {
            val refused = runCatching { provider.openFile(Uri.parse("content://${context.packageName}.roasts/$bad"), "r") }
            assertTrue(bad, refused.exceptionOrNull() is FileNotFoundException)
        }
    }
}
