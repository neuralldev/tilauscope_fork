// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebView
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import java.io.File

/** The screen around the session (audit 2026-10-25): a dead page renderer never takes the app with it. */
@RunWith(RobolectricTestRunner::class)
class MainActivityTest {
    private fun screen() = run {
        val app = RuntimeEnvironment.getApplication()
        val service = Robolectric.buildService(SessionService::class.java).create().get()
        shadowOf(app).setComponentNameAndServiceForBindService(ComponentName(app, SessionService::class.java),
            service.onBind(Intent(app, SessionService::class.java)))
        Robolectric.buildActivity(MainActivity::class.java).setup()
    }

    @Test
    fun aFolderTheProviderCannotListGivesNothingInsteadOfClosingTheApp() {
        val activity = screen().get()
        val copy = MainActivity::class.java.getDeclaredMethod("copyFolder", Uri::class.java, File::class.java,
            kotlin.jvm.functions.Function1::class.java).apply { isAccessible = true }
        val keep: (String) -> Boolean = { true }
        val picked = Uri.parse("content://com.example.cloud/document/1") // not a tree a picker would give back
        assertEquals("" to emptyList<File>(), copy.invoke(activity, picked, File(activity.cacheDir, "stage"), keep))
    }

    @Test
    fun aDeadPageRendererIsHandledAndThePageComesBack() {
        val controller = screen()
        val web = MainActivity::class.java.getDeclaredField("web").apply { isAccessible = true }.get(controller.get()) as WebView
        val gone = object : RenderProcessGoneDetail() {
            override fun didCrash() = true
            override fun rendererPriorityAtExit() = 0
        }
        assertTrue("the renderer's death would kill the app", shadowOf(web).webViewClient.onRenderProcessGone(web, gone))
        controller.recreate() // what the handler asks for: a new page, the session untouched
    }
}
