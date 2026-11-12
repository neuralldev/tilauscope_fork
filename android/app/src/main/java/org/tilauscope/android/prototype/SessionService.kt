// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.TimeUnit

/**
 * Sole owner of the session: it outlives activity recreation, and in the
 * foreground (after an explicit user action) it outlives leaving the screen.
 * Never restarted by the system after process death: the journal is restored
 * read-only on the next start instead.
 */
class SessionService : Service() {
    inner class LocalBinder : Binder() {
        val service get() = this@SessionService
    }

    /** Main thread only. A null result means the operation failed. */
    var listener: ((method: String, result: JSONObject?) -> Unit)? = null

    /** Main thread only. Each change of the roaster link. */
    var linkListener: ((JSONObject) -> Unit)? = null

    /** Main thread only. Each change of the extractor link. */
    var extractorListener: ((JSONObject) -> Unit)? = null

    /** Main thread only. Each reading (or loss) of the ambient probe. */
    var ambientListener: ((JSONObject) -> Unit)? = null

    /** Main thread only. Each change of the MQTT broker link. */
    var mqttListener: ((JSONObject) -> Unit)? = null

    /** Main thread only. Each weight (or loss) of the scale. */
    var scaleListener: ((JSONObject) -> Unit)? = null

    /** Main thread only. Each reading (or loss) of the colour meter. */
    var colourListener: ((JSONObject) -> Unit)? = null

    /** Main thread only. Each value (or loss) of the water activity meter. */
    var waterListener: ((JSONObject) -> Unit)? = null

    /** Main thread only. Each change of the label printer. */
    var printerListener: ((JSONObject) -> Unit)? = null

    private val binder = LocalBinder()
    private val worker = Executors.newSingleThreadScheduledExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var engine: PyObject? = null // accessed only by worker
    private var since = 0 // samples already delivered to the listener; worker only
    private val scanner by lazy { BleScanner(this) { batch -> execute("classify_scan", batch.toString()) } }
    val bluetoothEnabled get() = scanner.enabled
    private var link: Tc4Link? = null // main thread only
    private var linkRoast = false // the roast link: it outlives the page, ends with the roast
    private var linkState: String? = null // last state handed to the session
    private var releaseWhenIdle = false // the roast ended while the roaster still cools: leave once it is let go
    private var extractor: AirWaveLink? = null // main thread only
    private var extractorRoast = false // the roast screen holds the link: its values are settings
    private var extractorLevel: Int? = null // last level handed to the session
    private var ambient: AmbientLink? = null // main thread only
    private var scale: ScaleDevice? = null // main thread only
    private var scaleBrand: ScaleKind? = null // the protocol of [scale]
    private var colour: ColourLink? = null // main thread only
    private var water: AquaGaugeLink? = null // main thread only
    private var printer: PrinterLink? = null // main thread only
    private var mqtt: MqttLink? = null // main thread only
    private val awake by lazy { // worker, and onDestroy
        getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "TilauScope:roast")
            .apply { setReferenceCounted(false) }
    }

    override fun onBind(intent: Intent) = binder

    override fun onCreate() {
        super.onCreate()
        AppLog.start(this)
        // About once a second; a live roast reads its time from the real clock, so the delay never stretches it.
        worker.scheduleWithFixedDelay({ run("tick") }, 1, 1, TimeUnit.SECONDS)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL,
            getString(R.string.session_channel), NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.session_notification))
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        return START_NOT_STICKY
    }

    fun execute(method: String, vararg args: Any) {
        try {
            worker.execute { run(method, *args) }
        } catch (gone: RejectedExecutionException) {
            AppLog.i("TilauScopeAndroid", "Dropped after the service ended: $method")
        }
    }

    /** Sends the whole curve again, for a newly attached screen. */
    fun resync() {
        worker.execute {
            since = 0
            run(null)
        }
    }

    /** Main thread. False when Bluetooth is off; permissions are the caller's job. */
    fun startScan() = scanner.start()

    fun stopScan() = scanner.stop()

    private fun roasterLink() =
        link ?: Tc4Link(this) { state -> AppLog.state("Roaster", state.optString("state")); main.post { onLink(state) } }.also { link = it }

    /** Main thread. The caller has checked BLUETOOTH_CONNECT. The link check of Settings. */
    fun connectLink(address: String) {
        if (linkRoast) return // the roast link still cools the roaster: the check waits until it is let go
        linkRoast = false
        roasterLink().connect(address)
    }

    /** Main thread. The roast link: readings into the session, its commands to the roaster.
     *  [request]: {"address", "end": the script that cools then stops the roaster when let go}. */
    fun connectRoastLink(request: String) {
        val json = JSONObject(request)
        val end = json.optJSONArray("end") ?: JSONArray()
        linkRoast = true
        linkState = null
        releaseWhenIdle = false
        roasterLink().connect(json.getString("address"), roast = true, endScript = List(end.length()) { end.getString(it) })
    }

    /** Main thread. Lets the link check go; the roast link ends with the roast. */
    fun disconnectLink() {
        if (!linkRoast) link?.disconnect()
    }

    /** Main thread. Test of the recovery, empty drum only: the roast link drops as for real. */
    fun dropLinkForTest() {
        if (linkRoast) link?.dropForTest()
    }

    private fun onLink(state: JSONObject) {
        if (linkRoast) {
            val now = state.optString("state")
            if (now != linkState || state.optBoolean("recovered")) {
                linkState = now
                execute("link_state", JSONObject().put("state", now).put("recovered", state.optBoolean("recovered")).toString())
            }
            if ((now == "connected" || now == "cooling") && !state.isNull("bt")) { // shown live while cooling
                execute("link_reading", JSONObject().put("bt", state.get("bt")).put("et", state.opt("et") ?: JSONObject.NULL)
                    .put("burner", state.opt("burner") ?: JSONObject.NULL).put("air", state.opt("air") ?: JSONObject.NULL).toString())
            }
            if (now == "idle") {
                linkRoast = false
                if (releaseWhenIdle) release()
            }
        }
        linkListener?.invoke(state)
    }

    fun airTest() {
        link?.airTest()
    }

    /** Main thread. [roast]: kept for the roast screen, whose changes are recorded. */
    fun connectExtractor(address: String, roast: Boolean) {
        extractorRoast = roast
        extractorLevel = null
        val current = extractor ?: AirWaveLink(this) { state -> AppLog.state("Extractor", state.optString("state")); main.post { onExtractor(state) } }.also { extractor = it }
        current.connect(address, roast)
    }

    fun disconnectExtractor() {
        extractorRoast = false
        extractor?.disconnect()
    }

    fun extractor(): AirWaveLink? = extractor

    /** Main thread. Readings also reach the session, which keeps the one at CHARGE. */
    fun connectAmbient(address: String) {
        val current = ambient ?: AmbientLink(this) { state -> AppLog.state("Ambient", state.optString("state")); main.post { onAmbient(state) } }.also { ambient = it }
        current.connect(address)
    }

    fun disconnectAmbient() {
        ambient?.disconnect()
    }

    /** Main thread. [request]: host, port, user, password, tls and the topics to subscribe to. */
    fun connectMqtt(request: String) {
        val json = JSONObject(request)
        val topics = json.optJSONArray("topics") ?: JSONArray()
        val link = mqtt ?: MqttLink({ state -> AppLog.state("MQTT", state.optString("state")); main.post { mqttListener?.invoke(state) } }) { topic, payload ->
            execute("mqtt_message", JSONObject().put("topic", topic).put("payload", payload).toString())
        }.also { mqtt = it }
        link.connect(MqttLink.Config(json.getString("host"), json.optInt("port", 1883), json.optString("user"),
            json.optString("password"), json.optBoolean("tls"), List(topics.length()) { topics.getString(it) }))
    }

    fun disconnectMqtt() {
        mqtt?.disconnect()
    }

    /** Main thread. The protocol follows the scale's saved [name]; another brand replaces the link. */
    fun connectScale(address: String, name: String) {
        val kind = scaleKind(name)
        if (kind != scaleBrand) {
            scale?.release()
            val onState = { state: JSONObject ->
                AppLog.state("Scale", state.optString("state") + if (state.optBoolean("ready")) ", ready" else "")
                main.post { scaleListener?.invoke(state) }; Unit
            }
            scale = when (kind) {
                ScaleKind.ACAIA -> AcaiaLink(this, onState)
                ScaleKind.DECENT -> DecentLink(this, onState)
                ScaleKind.BOOKOO -> BookooLink(this, onState)
            }
            scaleBrand = kind
        }
        scale?.connect(address)
    }

    fun disconnectScale() {
        scale?.disconnect()
    }

    fun tareScale() {
        scale?.tare()
    }

    fun connectColour(address: String) {
        val current = colour ?: ColourLink(this) { state -> AppLog.state("Colour meter", state.optString("state")); main.post { colourListener?.invoke(state) } }.also { colour = it }
        current.connect(address)
    }

    fun disconnectColour() {
        colour?.disconnect()
    }

    fun connectWater(address: String) {
        val current = water ?: AquaGaugeLink(this) { state -> AppLog.state("Water meter", state.optString("state")); main.post { waterListener?.invoke(state) } }.also { water = it }
        current.connect(address)
    }

    fun disconnectWater() {
        water?.disconnect()
    }

    fun connectPrinter(address: String) {
        val current = printer ?: PrinterLink(this) { state -> AppLog.state("Printer", state.optString("state")); main.post { printerListener?.invoke(state) } }.also { printer = it }
        current.connect(address)
    }

    fun disconnectPrinter() {
        printer?.disconnect()
    }

    fun printLabel(rows: ByteArray) {
        printer?.printLabel(rows)
    }

    /** Accessory values for the curves of the roast; only the ones read just now. */
    private fun extras(state: JSONObject, channels: Map<String, String>) {
        val values = JSONObject()
        channels.forEach { (from, to) -> if (!state.isNull(from) && state.has(from)) values.put(to, state.get(from)) }
        if (values.length() > 0) execute("extra_readings", values.toString())
    }

    private fun onAmbient(state: JSONObject) {
        if (AMBIENT_KEYS.none { state.isNull(it) }) {
            execute("ambient_reading", JSONObject().apply { AMBIENT_KEYS.forEach { put(it, state.get(it)) } }.toString())
        }
        if (!state.isNull("cracks")) execute("crack_count", state.getInt("cracks"))
        if (state.has("door") && !state.isNull("door")) {
            execute("door_frame", state.getString("door"), state.getInt("door_seq"), state.getLong("door_age_ms").toInt())
        }
        extras(state, mapOf("temperature_c" to "room_c", "humidity_pct" to "room_rh",
            "pressure_hpa" to "pressure_hpa", "altitude_m" to "altitude_m"))
        ambientListener?.invoke(state)
    }

    private fun onExtractor(state: JSONObject) {
        if (state.optString("state") == "connected") extras(state, mapOf("inlet" to "inlet_c", "catalyst" to "catalyst_c"))
        // Off is recorded as 0, like a lever at its lowest.
        if (extractorRoast && state.optString("state") == "connected" && !state.isNull("power") && !state.isNull("speed")) {
            val level = if (state.getBoolean("power")) state.getInt("speed") else 0
            if (level != extractorLevel) {
                extractorLevel = level
                execute("device_lever", "extractor", level)
            }
        }
        extractorListener?.invoke(state)
    }

    /**
     * Runs a command, then delivers a snapshot holding only the new samples; the
     * setup and scan calls deliver their own answer under "reply" instead.
     */
    private fun run(method: String?, vararg args: Any) {
        // The operator's commands by name only: their arguments can hold the MQTT password.
        if (method != null && method !in UNLOGGED_METHODS && method !in QUIET_METHODS) AppLog.i("TilauScopeSession", method)
        val result = try {
            synchronized(Python::class.java) {
                if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
            }
            val demo = engine ?: Python.getInstance().getModule("tilauscope_mobile.demo")
                .callAttr("Demo", File(filesDir, "session.journal").absolutePath,
                    File(filesDir, CONFIG_FILE).absolutePath, File(filesDir, CAVE_FOLDER).absolutePath)
                .also { engine = it }
            val answer = if (method != null) demo.callAttr(method, *args) else null
            // The roaster's commands leave in order, then End roast lets the roast link go.
            val commands = JSONArray(demo.callAttr("take_commands").toString())
            if (commands.length() > 0 || method == "stop") {
                val list = List(commands.length()) { commands.getString(it) }
                main.post {
                    if (linkRoast) {
                        link?.command(list)
                        if (method == "stop") link?.disconnect()
                    }
                }
            }
            // What the alarms ask of the extractor and the crack counter, sent as their own buttons would.
            val devices = JSONArray(demo.callAttr("take_device_commands").toString())
            if (devices.length() > 0) main.post {
                for (i in 0 until devices.length()) {
                    val c = devices.getJSONObject(i)
                    if (c.optString("device") == "ambient") { ambient?.command(c.optInt("value")); continue }
                    if (c.optString("device") != "extractor") continue
                    val value = c.optString("value")
                    when (c.optString("op")) {
                        "power" -> extractor?.setPower(value == "on")
                        "speed" -> value.toIntOrNull()?.let { extractor?.setSpeed(it) }
                        "mode" -> extractor?.setMode(listOf("STD", "EXT", "FAN").indexOf(value))
                    }
                }
            }
            if (method in QUIET_METHODS) return // nothing for the screen
            if (method in TEXT_REPLY_METHODS) {
                JSONObject().put("reply", answer.toString()) // plain text, such as a file path
            } else if (method in REPLY_METHODS) {
                JSONObject().put("reply", JSONTokener(answer.toString()).nextValue())
            } else {
                JSONObject(demo.callAttr("snapshot", since).toString())
                    .also { since = it.getInt("sample_count") }
            }
        } catch (error: Exception) {
            AppLog.e("TilauScopeAndroid", "Session operation failed: $method", error)
            null
        }
        if (result != null && result.has("state")) holdAwake(result.optString("state") == "recording" && !result.optBoolean("interrupted"))
        main.post { listener?.invoke(method ?: "snapshot", result) }
    }

    /** Worker. The CPU stays awake while a roast records, screen off included; each tick renews the hold,
     *  so a stalled worker lets it lapse. */
    private fun holdAwake(recording: Boolean) {
        if (recording) awake.acquire(AWAKE_HOLD_MS) else if (awake.isHeld) awake.release()
    }

    /** Leaves the foreground; the service ends once the screen unbinds. */
    fun release() {
        releaseWhenIdle = linkRoast // a hot roaster is cooled first, its link held in the foreground
        if (releaseWhenIdle) return
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        scanner.stop()
        link?.release() // burner off and roaster stopped before the link goes
        extractor?.release()
        ambient?.release()
        scale?.release()
        colour?.release()
        water?.release()
        printer?.release()
        mqtt?.disconnect()
        worker.shutdown() // finish an in-flight atomic save or journal write
        if (awake.isHeld) awake.release() // a tick still in flight renews it for 60 s at most
        super.onDestroy()
    }

    companion object {
        const val CONFIG_FILE = "config.json"
        const val CAVE_FOLDER = "beancave"
        private val REPLY_METHODS = setOf("get_setup", "save_setup", "save_mqtt", "classify_scan",
    "get_cave", "cave_preview", "cave_import", "cave_start_empty", "get_coffees", "save_coffee", "get_plan", "set_plan_choice", "save_tasting",
    "get_roasts", "get_roast", "import_roasts", "roasts_preview", "roast_label", "get_alarms", "set_alarm_list", "import_alarms",
    "get_alarm_list", "edit_alarm", "add_alarm", "delete_alarm", "undo_alarm", "move_alarm", "new_alarm_list", "delete_alarm_list",
    "simulate", "set_auto_mark", "set_follow", "mqtt_check", "get_energy", "get_roast_energy", "delete_roast")
        private val TEXT_REPLY_METHODS = setOf("export_alog", "alarm_list_file")
        private val UNLOGGED_METHODS = setOf("tick", "classify_scan") // once a second, or each scan batch
        private val QUIET_METHODS = setOf("ambient_reading", "crack_count", "door_frame", "extra_readings", "link_reading", "mqtt_message")
        private val AMBIENT_KEYS = listOf("temperature_c", "humidity_pct", "pressure_hpa")
        private const val CHANNEL = "session"
        private const val NOTIFICATION_ID = 1
        private const val AWAKE_HOLD_MS = 60_000L
    }
}
