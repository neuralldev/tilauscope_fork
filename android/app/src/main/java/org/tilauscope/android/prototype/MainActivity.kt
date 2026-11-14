// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.net.Uri
import android.os.IBinder
import android.provider.DocumentsContract
import android.provider.Settings
import android.view.WindowManager
import android.util.Base64
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Hosts the local roast screen (assets/roast.html); the session lives in SessionService. */
class MainActivity : Activity() {
    private var session: SessionService? = null
    private var pageLoaded = false
    private var rendererGone = false // the WebView is dead: it is never saved, the activity is recreated
    private var recording = false // as the session last said; no page change meanwhile
    private val pendingConnects = mutableListOf<() -> Unit>() // every link waiting for the connect permission
    private val asks = ArrayDeque<Pair<Array<String>, Int>>() // permission requests waiting their turn
    private var asking = false
    private var connectRefused = false // the page is told when Android's settings allow it
    private var pickedCave: Pair<String, String>? = null // staged BeanCave files and the picked folder's name, until imported
    private var previewPending = false // the picker returned before the service was bound again
    private var pendingImport: String? = null // a roast folder's preview asked before the service was bound again
    private var pendingAlarms: Pair<String, String>? = null // an alarm list picked before the service was bound again: its copy and name
    private var stagedImport: String? = null // the staged roast files of the folder shown in the preview
    private var staged: File? = null // the coffee file on the preview sheet (opened from another app, or downloaded), until imported or dismissed
    private var coffeeWaiting = false // a coffee was opened while a roast is on: its sheet waits for the roast's end
    private var coffeeHeldTold = false
    private lateinit var web: WebView

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            session = (binder as SessionService.LocalBinder).service.also {
                it.listener = ::deliver
                it.linkListener = ::deliverLink
                it.extractorListener = ::deliverExtractor
                it.ambientListener = ::deliverAmbient
                it.mqttListener = ::deliverMqtt
                it.scaleListener = ::deliverScale
                it.colourListener = ::deliverColour
                it.waterListener = ::deliverWater
                it.printerListener = ::deliverPrinter
                // Back from Android's settings with Bluetooth allowed: the page connects again.
                if (connectRefused && (Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
                        checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED)) {
                    connectRefused = false
                    if (pageLoaded) web.evaluateJavascript("window.onBluetoothAllowed && onBluetoothAllowed()", null)
                }
                // Test hook: adb shell am start ... --ez simulate_readonly true
                if (intent.hasExtra(EXTRA_READONLY)) {
                    it.execute("set_readonly", intent.getBooleanExtra(EXTRA_READONLY, false))
                    intent.removeExtra(EXTRA_READONLY)
                }
                if (pageLoaded) it.resync()
                if (previewPending) {
                    previewPending = false
                    pickedCave?.let { (stage, name) -> it.execute("cave_preview", stage, name) }
                }
                pendingImport?.let { request -> pendingImport = null; it.execute("roasts_preview", request) }
                pendingAlarms?.let { (path, name) -> pendingAlarms = null; it.execute("import_alarms", path, name) }
                openCoffee(it) // `session` is assigned once this block ends
            }
        }

        override fun onServiceDisconnected(name: ComponentName) {
            session = null
        }
    }

    /** Called by the page on a WebView thread; commands run on the main thread. */
    private inner class Bridge {
        @JavascriptInterface
        fun call(method: String, argument: String) {
            runOnUiThread { command(method, argument) }
        }

        /** {"bytes", "since"} of the diagnostic log, for Settings › General. */
        @JavascriptInterface
        fun logInfo(): String = AppLog.info()

        /** ISO code of the system currency, the desktop's default price currency. */
        @JavascriptInterface
        fun currency(): String = try {
            java.util.Currency.getInstance(java.util.Locale.getDefault()).currencyCode
        } catch (error: IllegalArgumentException) {
            "EUR" // a locale without a country, as the desktop's fallback
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AppLog.start(this)
        val background = Color.rgb(30, 30, 46)
        web = WebView(this).apply {
            setBackgroundColor(background)
            settings.javaScriptEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false // an alarm's bell rings on a sample, not on a touch
            addJavascriptInterface(Bridge(), "TilauBridge")
            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    AppLog.w("TilauScopeWeb", "${message.message()} (line ${message.lineNumber()})")
                    return true
                }
            }
            webViewClient = object : WebViewClient() {
                // A page change lets every device go: never while recording.
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = recording

                override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                    pageLoaded = false
                    session?.stopScan() // scanning and the link check belong to the page that asked for them
                    session?.disconnectLink()
                    session?.disconnectExtractor()
                    session?.disconnectAmbient()
                    session?.disconnectScale()
                    session?.disconnectColour()
                    session?.disconnectWater()
                    session?.disconnectPrinter()
                }

                override fun onPageFinished(view: WebView, url: String) {
                    pageLoaded = true
                    session?.resync()
                }

                // The page's renderer died (out of memory, killed): the app and the session live on, the page comes back.
                override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                    AppLog.e("TilauScopeWeb", "Page renderer gone (crash: ${detail.didCrash()}), reopening the page")
                    rendererGone = true
                    recreate()
                    return true
                }
            }
            // Back after Android closed the app in the background: the page it was on. Before the
            // first setup, the app opens on the setup assistant.
            if (savedInstanceState?.let { restoreState(it) } == null) {
                val configured = File(filesDir, SessionService.CONFIG_FILE).exists()
                loadUrl("file:///android_asset/" + if (configured) "roast.html" else "setup.html")
            }
        }
        val root = FrameLayout(this).apply {
            setBackgroundColor(background)
            addView(web)
            setOnApplyWindowInsetsListener { view, insets ->
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
                insets
            }
        }
        setContentView(root)
        if (savedInstanceState == null) acceptCoffee(intent) // opened from another app; a recreated screen has its page already
    }

    /** The app was already running when another app opened a coffee file (the activity is singleTask). */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        acceptCoffee(intent)
    }

    /** A .tilaucoffee offered by an intent is copied into the cache, then shown on the preview sheet. */
    private fun acceptCoffee(offer: Intent) {
        val uri = CoffeeFiles.uriOf(offer) ?: return
        offer.action = null // handled once, not again when the screen is recreated
        offer.data = null
        offer.removeExtra(Intent.EXTRA_STREAM)
        Thread {
            val file = CoffeeFiles.copy(this, uri)
            runOnUiThread {
                if (file == null) {
                    Toast.makeText(this, R.string.coffee_unreadable, Toast.LENGTH_LONG).show()
                } else {
                    staged = file
                    coffeeWaiting = true
                    openCoffee()
                }
            }
        }.start()
    }

    /** Shows the staged coffee on BeanCave's preview sheet. Never over a roast: it waits for the roast's end. */
    private fun openCoffee(bound: SessionService? = session) {
        if (!coffeeWaiting) return
        val service = bound ?: return // asked again once the service is bound
        if (service.running) {
            if (!coffeeHeldTold) {
                coffeeHeldTold = true
                Toast.makeText(this, R.string.coffee_held, Toast.LENGTH_LONG).show()
            }
            return
        }
        coffeeWaiting = false
        coffeeHeldTold = false
        if (pageLoaded && web.url?.contains("beancave.html") == true) web.evaluateJavascript("window.coffeeStaged && coffeeStaged()", null)
        else web.loadUrl("file:///android_asset/beancave.html#coffee")
    }

    private fun dropStaged() {
        staged = null
        File(cacheDir, CoffeeFiles.FOLDER).deleteRecursively()
        File(cacheDir, LIBRARY_FOLDER).deleteRecursively()
    }

    /** The staged file itself, to the computer: the share sheet, from a copy under the provider's folder. */
    private fun sendStagedCoffee() {
        val file = staged ?: return
        Thread {
            val folder = File(cacheDir, RoastFiles.COFFEE_FOLDER).apply { deleteRecursively(); mkdirs() }
            val copy = File(folder, "coffee${CoffeeFiles.EXTENSION}")
            if (runCatching { file.copyTo(copy, overwrite = true) }.isSuccess) runOnUiThread { shareCoffee(copy) }
        }.start()
    }

    private fun shareCoffee(file: File) {
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType(RoastFiles.MIME)
            .putExtra(Intent.EXTRA_STREAM, RoastFiles.coffeeUri(packageName, file))
            .putExtra(Intent.EXTRA_TITLE, file.name).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), file.name))
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (!rendererGone) web.saveState(outState) // a dead page has nothing to keep: the default page opens
    }

    override fun onStart() {
        super.onStart()
        bindService(Intent(this, SessionService::class.java), connection, BIND_AUTO_CREATE)
    }

    override fun onStop() {
        session?.stopScan()
        session?.listener = null
        session?.linkListener = null
        session?.extractorListener = null
        session?.ambientListener = null
        session?.mqttListener = null
        session?.scaleListener = null
        session?.colourListener = null
        session?.waterListener = null
        session?.printerListener = null
        unbindService(connection)
        session = null
        super.onStop()
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }

    private fun command(method: String, argument: String) {
        val service = session ?: return
        when (method) {
            "start" -> {
                // Starting a recording is the explicit user action that enters the foreground.
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                    checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                    PackageManager.PERMISSION_GRANTED) {
                    // Refusal only hides the notification; the service still runs.
                    ask(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 0)
                }
                startForegroundService(Intent(this, SessionService::class.java))
                service.execute("start", argument.ifEmpty { "hand" }) // by hand, the plan or a roast
            }
            "mark" -> service.execute("mark", argument)
            // A malformed argument from the page is ignored: a throw here would close the app.
            "set" -> {
                val parts = argument.split(":")
                val value = parts.getOrNull(1)?.toIntOrNull() ?: return
                service.execute("set_lever", parts[0], value)
            }
            "save" -> service.execute("export_alog", File(filesDir, RoastFiles.FOLDER).absolutePath)
            "share_log" -> shareLog()
            "unmark", "stop", "reset", "toggle_signal", "get_setup", "get_cave", "cave_start_empty", "get_coffees" -> service.execute(method)
            // The desktop's BeanCave folder: the cave comes with the files that depend on it.
            "cave_pick" -> startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), PICK_CAVE)
            "cave_import" -> pickedCave?.let { (stage, name) -> service.execute("cave_import", stage, name) }
            "cave_export" -> sendCave()
            "save_setup", "save_mqtt", "choose_coffee", "save_coffee", "set_roast_setup", "get_roast", "get_plan", "set_plan_choice", "save_tasting", "roast_label", "get_roast_energy" ->
                service.execute(method, argument)
            "get_roasts", "resume_preheat", "resume_follow", "get_alarms", "exit_simulation", "get_energy",
            "resume_auto", "cancel_auto_drop" -> service.execute(method)
            "simulate" -> service.execute(method, argument)
            "mqtt_check" -> service.execute(method, argument)
            "set_speed" -> argument.toIntOrNull()?.let { service.execute(method, it) }
            "set_auto_mark", "set_follow", "delete_roast" -> service.execute(method, argument)
            "set_alarm_list", "get_alarm_list", "edit_alarm", "add_alarm", "delete_alarm", "undo_alarm", "move_alarm",
            "delete_alarm_list" -> service.execute(method, argument)
            "new_alarm_list" -> service.execute(method)
            "alarm_share" -> service.execute("alarm_list_file", argument)
            // An Artisan alarm list (.alrm) from anywhere the tablet reaches: kept, then active.
            "alarms_pick" -> startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType("*/*"), PICK_ALARMS)
            // A folder, not files: the app then says what it holds and asks Import in its own words.
            "roasts_import" -> startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), PICK_ROASTS)
            "roasts_import_confirm" -> stagedImport?.let { service.execute("import_roasts", it) }
            "roasts_import_cancel" -> { stagedImport = null; File(cacheDir, "roast-import").deleteRecursively() }
            "roasts_send" -> sendRoasts()
            // A coffee in one file: the staged package, the library and the coffee sent to the computer.
            "coffee_opened" -> staged?.let { service.execute("coffee_preview", it.absolutePath) }
            "coffee_import" -> staged?.let { service.execute("coffee_import", it.absolutePath) }
            "coffee_dismiss" -> dropStaged()
            "coffee_file_send" -> sendStagedCoffee()
            "coffee_theirs" -> service.execute(method, argument)
            "coffee_send" -> service.execute(method, argument, File(cacheDir, RoastFiles.COFFEE_FOLDER).absolutePath)
            "library_page" -> service.executeSlow(method, argument) // the network: never on the thread that ticks the roast
            "library_get" -> service.executeSlow(method, argument, File(cacheDir, LIBRARY_FOLDER).absolutePath)
            "library_card" -> service.executeSlow(method, argument, File(cacheDir, LIBRARY_CARD_FOLDER).absolutePath)
            "roast_share" -> {
                val parts = argument.split("/", limit = 2)
                val name = parts.getOrNull(1) ?: return
                val (folder, sub) = when (parts[0]) {
                    "computer" -> RoastFiles.COMPUTER_FOLDER to "computer"
                    "shared" -> RoastFiles.SHARED_FOLDER to "shared"
                    else -> RoastFiles.FOLDER to ""
                }
                share(File(File(filesDir, folder), name).absolutePath, sub)
            }
            "scan_start" -> {
                val missing = scanPermissions().filter {
                    checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
                }
                if (missing.isEmpty()) startScan() else ask(missing.toTypedArray(), SCAN_REQUEST)
            }
            "scan_stop" -> service.stopScan()
            "link_connect" -> withConnect { service.connectLink(argument) }
            "app_settings" -> startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", packageName, null)))
            "roast_link_connect" -> withConnect { service.connectRoastLink(argument) }
            "link_drop_test" -> service.dropLinkForTest()
            "extractor_connect", "extractor_test_connect" ->
                withConnect { service.connectExtractor(argument, method == "extractor_connect") }
            "extractor_disconnect" -> service.disconnectExtractor()
            "ambient_connect" -> withConnect { service.connectAmbient(argument) }
            "mqtt_connect" -> service.connectMqtt(argument) // the network, not Bluetooth
            "mqtt_disconnect" -> service.disconnectMqtt()
            // {address, name}: the name says which protocol the scale speaks.
            "scale_connect" -> runCatching { JSONObject(argument) }.getOrNull()?.let { scale ->
                withConnect { service.connectScale(scale.optString("address"), scale.optString("name")) }
            }
            "scale_tare" -> service.tareScale()
            "scale_disconnect" -> service.disconnectScale()
            "colour_connect" -> withConnect { service.connectColour(argument) }
            "water_connect" -> withConnect { service.connectWater(argument) }
            "water_disconnect" -> service.disconnectWater()
            "printer_connect" -> withConnect { service.connectPrinter(argument) }
            "printer_disconnect" -> service.disconnectPrinter()
            "printer_print" -> runCatching { Base64.decode(argument, Base64.DEFAULT) }.getOrNull()?.let { service.printLabel(it) }
            "colour" -> {
                val parts = argument.split(":")
                val value = parts.getOrNull(1)?.toDoubleOrNull() ?: return
                service.execute("set_colour", parts[0], value)
            }
            "weight" -> {
                val parts = argument.split(":")
                val grams = parts.getOrNull(1)?.toIntOrNull() ?: return
                service.execute("set_weight", parts[0], grams)
            }
            "extractor_power" -> service.extractor()?.setPower(argument == "on")
            "extractor_speed" -> argument.toIntOrNull()?.let { service.extractor()?.setSpeed(it) }
            "extractor_mode" -> service.extractor()?.setMode(listOf("STD", "EXT", "FAN").indexOf(argument))
            "extractor_test" -> service.extractor()?.speedTest()
            "link_disconnect" -> service.disconnectLink()
            "air_test" -> service.airTest()
        }
    }

    private fun scanPermissions() = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        listOf(Manifest.permission.BLUETOOTH_SCAN)
    } else {
        listOf(Manifest.permission.ACCESS_FINE_LOCATION)
    }

    private fun startScan() {
        val service = session ?: return
        scanState(if (service.startScan()) "scanning" else "bluetooth_off")
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        val granted = results.isNotEmpty() && results.all { it == PackageManager.PERMISSION_GRANTED }
        when (code) {
            SCAN_REQUEST -> if (granted) startScan() else scanState("denied")
            LINK_REQUEST -> if (granted) {
                if (connectRefused) { // granted at a later prompt: the page drops its warning
                    connectRefused = false
                    if (pageLoaded) web.evaluateJavascript("window.onBluetoothGranted && onBluetoothGranted()", null)
                }
                pendingConnects.toList().forEach { it() }
            } else {
                connectRefused = true
                deliverLink(JSONObject().put("state", "denied"))
                deliverExtractor(JSONObject().put("state", "denied"))
                deliverAmbient(JSONObject().put("state", "denied"))
                deliverScale(JSONObject().put("state", "denied"))
                deliverColour(JSONObject().put("state", "denied"))
                deliverWater(JSONObject().put("state", "denied"))
                deliverPrinter(JSONObject().put("state", "denied"))
            }
        }
        if (code == LINK_REQUEST) pendingConnects.clear()
        asking = false
        asks.removeFirstOrNull()?.let { (next, nextCode) -> ask(next, nextCode) }
    }

    /** Android shows one permission request at a time and drops any other made meanwhile: they wait their turn. */
    private fun ask(permissions: Array<String>, code: Int) {
        if (asking) {
            asks.addLast(permissions to code)
        } else {
            asking = true
            requestPermissions(permissions, code)
        }
    }

    private fun scanState(state: String) {
        if (pageLoaded) web.evaluateJavascript("window.onScanState && onScanState(${JSONObject.quote(state)})", null)
    }

    /** Runs [connect] once Android lets the app connect to Bluetooth devices. */
    private fun withConnect(connect: () -> Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
            pendingConnects.add(connect)
            if (pendingConnects.size == 1) ask(arrayOf(Manifest.permission.BLUETOOTH_CONNECT), LINK_REQUEST)
        } else {
            connect()
        }
    }

    private fun deliverPrinter(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onPrinter && onPrinter($state)", null)
    }

    private fun deliverWater(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onWater && onWater($state)", null)
    }

    private fun deliverColour(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onColour && onColour($state)", null)
    }

    private fun deliverScale(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onScale && onScale($state)", null)
    }

    private fun deliverAmbient(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onAmbient && onAmbient($state)", null)
    }

    private fun deliverMqtt(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onMqtt && onMqtt($state)", null)
    }

    private fun deliverExtractor(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onExtractor && onExtractor($state)", null)
    }

    private fun deliverLink(state: JSONObject) {
        if (pageLoaded) web.evaluateJavascript("window.onLink && onLink($state)", null)
    }

    /** The saved roast goes wherever the operator chooses: Drive, mail, a nearby device… */
    /** The diagnostic log, as one text file, wherever the tester sends it. */
    private fun shareLog() {
        val file = AppLog.export(this, File(filesDir, RoastFiles.LOG_FOLDER))
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
            .putExtra(Intent.EXTRA_STREAM, RoastFiles.logUri(packageName, file))
            .putExtra(Intent.EXTRA_TITLE, file.name).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), file.name))
    }

    private fun share(path: String, sub: String = "") {
        val file = File(path)
        val send = Intent(Intent.ACTION_SEND)
            .setType(RoastFiles.MIME)
            .putExtra(Intent.EXTRA_STREAM, RoastFiles.uri(packageName, file, sub))
            .putExtra(Intent.EXTRA_TITLE, file.name)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(Intent.createChooser(send, file.name))
    }

    /** The tablet's own roasts, all at once, wherever the operator sends them; sorting them is theirs. */
    private fun sendRoasts() {
        val files = File(filesDir, RoastFiles.FOLDER).listFiles { f -> f.name.endsWith(".alog") }.orEmpty()
        if (files.isEmpty()) {
            if (pageLoaded) web.evaluateJavascript("window.onRoastsSent && onRoastsSent(0)", null)
            return
        }
        val send = Intent(Intent.ACTION_SEND_MULTIPLE)
            .setType(RoastFiles.MIME)
            .putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(files.map { RoastFiles.uri(packageName, it) }))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(Intent.createChooser(send, null))
    }

    /** The BeanCave files the tablet holds, sent together wherever the operator chooses. */
    private fun sendCave() {
        val folder = File(filesDir, SessionService.CAVE_FOLDER)
        val files = CAVE_FILES.map { File(folder, it) }.filter { it.isFile }
        if (files.isEmpty()) return
        val send = Intent(Intent.ACTION_SEND_MULTIPLE)
            .setType(RoastFiles.MIME)
            .putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(files.map { RoastFiles.caveUri(packageName, it) }))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(Intent.createChooser(send, null))
    }

    /** The files of a picked folder that [keep] names, copied to [stage]: the folder's name and the copies. */
    private fun copyFolder(tree: Uri, stage: File, keep: (String) -> Boolean): Pair<String, List<File>> = try {
        listFolder(tree, stage, keep)
    } catch (error: RuntimeException) { // a provider that cannot list the folder (cloud, revoked access): nothing copied
        AppLog.w("TilauScopeAndroid", "The picked folder could not be read", error)
        "" to emptyList()
    }

    private fun listFolder(tree: Uri, stage: File, keep: (String) -> Boolean): Pair<String, List<File>> {
        val folderId = DocumentsContract.getTreeDocumentId(tree)
        val folder = contentResolver.query(DocumentsContract.buildDocumentUriUsingTree(tree, folderId),
            arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)
            ?.use { if (it.moveToFirst()) it.getString(0) else null } ?: ""
        stage.deleteRecursively()
        stage.mkdirs()
        val copied = mutableListOf<File>()
        contentResolver.query(DocumentsContract.buildChildDocumentsUriUsingTree(tree, folderId),
            arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)
            ?.use { rows ->
                while (rows.moveToNext()) {
                    val name = File(rows.getString(1) ?: continue).name
                    if (!keep(name)) continue
                    val target = File(stage, name)
                    runCatching {
                        contentResolver.openInputStream(DocumentsContract.buildDocumentUriUsingTree(tree, rows.getString(0)))
                            ?.use { input -> target.outputStream().use { input.copyTo(it) } }
                    }.onSuccess { copied.add(target) }
                }
            }
        return folder to copied
    }

    /** The BeanCave files of the picked folder are staged; the session checks them all before anything is replaced. */
    private fun importCave(tree: Uri) {
        val stage = File(cacheDir, "cave-import")
        // A folder on Drive can take seconds: copied off the main thread.
        Thread {
            val (folder, _) = copyFolder(tree, stage) { it in CAVE_FILES }
            runOnUiThread {
                pickedCave = stage.absolutePath to folder
                session?.execute("cave_preview", stage.absolutePath, folder) ?: run { previewPending = true }
            }
        }.start()
    }

    /** The picked .alrm is copied, then kept by the session under its file's name. */
    private fun importAlarms(uri: Uri) {
        Thread {
            val name = contentResolver.query(uri, arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)
                ?.use { if (it.moveToFirst()) it.getString(0) else null } ?: "Alarms"
            val copy = File(cacheDir, "alarm-import.alrm")
            val copied = runCatching {
                contentResolver.openInputStream(uri)?.use { input -> copy.outputStream().use { input.copyTo(it) } }
            }.isSuccess
            // The picker can return before the session is bound again: kept until it is.
            runOnUiThread { if (copied) session?.execute("import_alarms", copy.absolutePath, name) ?: run { pendingAlarms = copy.absolutePath to name } }
        }.start()
    }

    /** The .alog files of the picked folder are copied to a staging folder; the session previews, then imports, from there. */
    private fun importRoasts(data: Intent) {
        val tree = data.data ?: return
        Thread {
            val (folder, copied) = copyFolder(tree, File(cacheDir, "roast-import")) { it.lowercase().endsWith(".alog") }
            val paths = JSONArray(copied.map { it.absolutePath })
            val request = JSONObject().put("folder", folder).put("paths", paths).toString()
            runOnUiThread {
                stagedImport = paths.toString()
                // The picker can return before the session is bound again: kept until it is.
                session?.execute("roasts_preview", request) ?: run { pendingImport = request }
            }
        }.start()
    }

    @Deprecated("Activity results without AndroidX")
    override fun onActivityResult(request: Int, result: Int, data: Intent?) {
        super.onActivityResult(request, result, data)
        if (request == PICK_ROASTS && result == RESULT_OK && data != null) {
            importRoasts(data)
            return
        }
        val uri = data?.data
        if (result != RESULT_OK || uri == null) return
        when (request) {
            PICK_CAVE -> importCave(uri)
            PICK_ALARMS -> importAlarms(uri)
        }
    }

    private fun deliver(method: String, result: JSONObject?) {
        if (method == "library_get") staged = result?.optJSONObject("reply")?.optString("path")?.takeIf { it.isNotEmpty() }?.let { File(it) }
        if (method == "coffee_import" && result != null) dropStaged()
        if (method == "coffee_send") result?.optString("reply")?.takeIf { it.isNotEmpty() }?.let { shareCoffee(File(it)) }
        if (coffeeWaiting && result != null && result.has("state")) openCoffee() // the roast may have ended
        if (method == "cave_import" && result != null) { pickedCave = null; File(cacheDir, "cave-import").deleteRecursively() }
        if (method == "import_roasts") { stagedImport = null; File(cacheDir, "roast-import").deleteRecursively() }
        if ((method == "stop" || method == "exit_simulation") && result != null) session?.release()
        if (method == "export_alog") result?.optString("reply")?.takeIf { it.isNotEmpty() }?.let(::share)
        if (method == "alarm_list_file") result?.optString("reply")?.takeIf { it.isNotEmpty() }?.let { path ->
            val file = File(path)
            startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType(RoastFiles.MIME)
                .putExtra(Intent.EXTRA_STREAM, RoastFiles.alarmsUri(packageName, file))
                .putExtra(Intent.EXTRA_TITLE, file.name).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), file.name))
        }
        if (result != null && result.has("state")) {
            recording = result.optString("state") == "recording"
            // A roast runs for minutes without a touch: the screen stays on while recording.
            if (recording) {
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            } else {
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
        if (!pageLoaded) return
        val payload = result?.toString() ?: "null"
        web.evaluateJavascript("window.onSnapshot && onSnapshot(${JSONObject.quote(method)}, $payload)", null)
    }

    private companion object {
        const val EXTRA_READONLY = "simulate_readonly"
        const val SCAN_REQUEST = 1
        const val LINK_REQUEST = 2
        const val PICK_CAVE = 3
        const val PICK_ROASTS = 5
        const val PICK_ALARMS = 6
        const val LIBRARY_FOLDER = "coffee-library" // in the cache: the package last downloaded from the library
        const val LIBRARY_CARD_FOLDER = "coffee-library-cards" // in the cache: a selected roast's package, only while it is read
        val CAVE_FILES = listOf("beancave.json", "tastings.json", "brewlog.json") // as tilauscope_mobile.cave.FILES
    }
}
