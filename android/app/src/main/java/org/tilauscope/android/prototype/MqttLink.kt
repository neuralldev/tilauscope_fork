// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import android.os.SystemClock
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.EOFException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLPeerUnverifiedException
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/**
 * The MQTT broker (MQTT-SPEC): MQTT 3.1.1, the subset the desktop uses — connect, subscribe at QoS 1,
 * receive at QoS 0 or 1, ping. One thread owns the socket; while wanted, a lost or refused connection
 * is tried again every 2 s. Messages go to [onMessage] (topic, payload as text); [onState] names
 * the state: connecting, connected, refused (the broker said no), unreachable, idle.
 */
class MqttLink(
    private val onState: (JSONObject) -> Unit,
    private val onMessage: (topic: String, payload: String) -> Unit,
) {
    @Volatile private var wanted: Config? = null
    @Volatile private var socket: Socket? = null
    @Volatile private var current = "idle"
    private var thread: Thread? = null

    /** host, port, user, password, tls; [topics]: what to subscribe to ("#" for every topic). */
    class Config(val host: String, val port: Int, val user: String, val password: String, val tls: Boolean,
                 val topics: List<String>)

    /** Any thread. Connects, or reconnects when the settings changed. */
    @Synchronized
    fun connect(config: Config) {
        if (wanted?.let { sameAs(it, config) } == true && thread?.isAlive == true) {
            state(current) // a page that asks again is told where the link stands
            return
        }
        disconnect()
        wanted = config
        thread = Thread({ run(config) }, "mqtt-link").also { it.isDaemon = true; it.start() }
    }

    /** Any thread. */
    @Synchronized
    fun disconnect() {
        wanted = null
        socket?.let { runCatching { it.close() } } // the reading thread ends on its closed socket
        thread?.interrupt()
        thread = null
    }

    private fun sameAs(a: Config, b: Config) = a.host == b.host && a.port == b.port && a.user == b.user &&
        a.password == b.password && a.tls == b.tls && a.topics == b.topics

    private fun state(value: String) {
        current = value
        onState(JSONObject().put("state", value))
    }

    private fun run(config: Config) {
        while (wanted === config) {
            state("connecting")
            try {
                session(config)
            } catch (error: Exception) {
                if (wanted !== config) break
                AppLog.w(TAG, "Broker ${config.host}:${config.port}: ${error.message}")
                state(if (error is Refused) "refused" else "unreachable")
            }
            try { Thread.sleep(RETRY_MS) } catch (_: InterruptedException) { break }
        }
        if (wanted == null) state("idle")
    }

    private fun session(config: Config) {
        val raw = Socket()
        socket = raw
        var s: Socket = raw
        try {
            raw.connect(InetSocketAddress(config.host, config.port), CONNECT_TIMEOUT_MS)
            raw.soTimeout = KEEPALIVE_S * 1000 / 2
            if (config.tls) {
                val tls = (SSLSocketFactory.getDefault() as SSLSocketFactory)
                    .createSocket(raw, config.host, config.port, true) as SSLSocket
                s = tls
                replace(raw, tls)
                tls.startHandshake()
                // Android's SSLSocket checks the certificate, not that it names this broker.
                if (!HttpsURLConnection.getDefaultHostnameVerifier().verify(config.host, tls.session))
                    throw SSLPeerUnverifiedException("The certificate does not name ${config.host}")
            }
            talk(config, DataInputStream(s.getInputStream()), s.getOutputStream())
        } finally {
            runCatching { s.close() }
            runCatching { raw.close() }
            replace(s, null) // a newer thread may own the field by now
        }
    }

    @Synchronized
    private fun replace(mine: Socket, next: Socket?) { if (socket === mine) socket = next }

    private fun talk(config: Config, input: DataInputStream, output: OutputStream) {
        output.send(mqttConnect(CLIENT_ID, config.user, config.password, KEEPALIVE_S))
        val (type, _, body) = readPacket(input)
        if (type != CONNACK || body.size < 2) throw EOFException("No CONNACK")
        if (body[1].toInt() != 0) throw Refused("CONNACK return code ${body[1]}")
        if (config.topics.isNotEmpty()) output.send(mqttSubscribe(1, config.topics))
        var sent = SystemClock.elapsedRealtime()
        state("connected")
        var quiet = 0
        while (wanted === config) {
            // Only the wait for a packet times out; a pause inside one is a lost link.
            val first = try { input.read() } catch (_: SocketTimeoutException) {
                if (++quiet > 1) throw EOFException("No answer to the ping") // two half keep-alives without a byte
                output.send(PINGREQ_PACKET)
                sent = SystemClock.elapsedRealtime()
                continue
            }
            quiet = 0
            val packet = readPacket(input, first)
            if (packet.type == PUBLISH) {
                val message = mqttPublish(packet.flags, packet.body)
                if (message.packetId != null) {
                    output.send(mqttPubAck(message.packetId))
                    sent = SystemClock.elapsedRealtime()
                }
                if (packet.whole) onMessage(message.topic, message.payload) // a gateway's large retained state is no sensor
            }
            // The broker drops a client that sends nothing for 1.5 keep-alives, however much it receives.
            if (SystemClock.elapsedRealtime() - sent >= KEEPALIVE_S * 1000 / 2) {
                output.send(PINGREQ_PACKET)
                sent = SystemClock.elapsedRealtime()
            }
        }
        runCatching { output.send(DISCONNECT_PACKET) }
    }

    private class Refused(message: String) : Exception(message)

    private fun OutputStream.send(packet: ByteArray) { write(packet); flush() }

    companion object {
        private const val TAG = "TilauScopeMqtt"
        private const val CLIENT_ID = "TilauScope-tablet" // not the desktop's "Tilauscope": both may be connected
        private const val KEEPALIVE_S = 60
        private const val CONNECT_TIMEOUT_MS = 3000 // the desktop's connect timeout
        private const val RETRY_MS = 2000L
    }
}

// MQTT 3.1.1 packets (OASIS standard, §2–3), pure so they can be tested on the computer.

internal const val CONNACK = 2
internal const val PUBLISH = 3
private const val MAX_KEPT = 64 * 1024 // a sensor's message is small; a larger one is read past, its start kept
internal val PINGREQ_PACKET = byteArrayOf(0xC0.toByte(), 0)
internal val DISCONNECT_PACKET = byteArrayOf(0xE0.toByte(), 0)

internal class MqttMessage(val topic: String, val payload: String, val packetId: Int?)

private fun ByteArrayOutputStream.text(value: String) {
    val bytes = value.toByteArray(Charsets.UTF_8)
    write(bytes.size shr 8); write(bytes.size and 0xFF); write(bytes)
}

internal fun remainingLength(length: Int): ByteArray {
    val out = ByteArrayOutputStream()
    var rest = length
    do {
        var byte = rest % 128
        rest /= 128
        if (rest > 0) byte = byte or 0x80
        out.write(byte)
    } while (rest > 0)
    return out.toByteArray()
}

private fun packet(header: Int, body: ByteArray) = byteArrayOf(header.toByte()) + remainingLength(body.size) + body

/** CONNECT with a clean session; user and password only when a user is given. */
internal fun mqttConnect(clientId: String, user: String, password: String, keepAliveS: Int): ByteArray {
    val body = ByteArrayOutputStream()
    body.text("MQTT"); body.write(4) // protocol level 3.1.1
    var flags = 0x02 // clean session
    if (user.isNotEmpty()) flags = flags or 0x80 or (if (password.isNotEmpty()) 0x40 else 0)
    body.write(flags)
    body.write(keepAliveS shr 8); body.write(keepAliveS and 0xFF)
    body.text(clientId)
    if (user.isNotEmpty()) { body.text(user); if (password.isNotEmpty()) body.text(password) }
    return packet(0x10, body.toByteArray())
}

/** SUBSCRIBE to every topic at QoS 1. */
internal fun mqttSubscribe(packetId: Int, topics: List<String>): ByteArray {
    val body = ByteArrayOutputStream()
    body.write(packetId shr 8); body.write(packetId and 0xFF)
    topics.forEach { body.text(it); body.write(1) }
    return packet(0x82, body.toByteArray())
}

internal fun mqttPubAck(packetId: Int) = byteArrayOf(0x40, 2, (packetId shr 8).toByte(), (packetId and 0xFF).toByte())

/** A PUBLISH from its fixed header's flags and its body: topic, packet id at QoS 1 or 2, payload. */
internal fun mqttPublish(flags: Int, body: ByteArray): MqttMessage {
    val topicLength = ((body[0].toInt() and 0xFF) shl 8) or (body[1].toInt() and 0xFF)
    var at = 2 + topicLength
    val topic = String(body, 2, topicLength, Charsets.UTF_8)
    val qos = (flags shr 1) and 3
    val id = if (qos > 0) (((body[at].toInt() and 0xFF) shl 8) or (body[at + 1].toInt() and 0xFF)).also { at += 2 } else null
    return MqttMessage(topic, String(body, at, body.size - at, Charsets.UTF_8), id)
}

/** One packet; a body longer than [MAX_KEPT] is read to its end but only its start is kept ([whole] false). */
internal class Packet(val type: Int, val flags: Int, val body: ByteArray, val whole: Boolean) {
    operator fun component1() = type
    operator fun component2() = flags
    operator fun component3() = body
}

internal fun readPacket(input: InputStream, header: Int = input.read()): Packet {
    if (header < 0) throw EOFException("Broker closed the connection")
    var length = 0
    var multiplier = 1
    while (true) {
        val byte = input.read()
        if (byte < 0) throw EOFException("Broker closed the connection")
        length += (byte and 0x7F) * multiplier
        if (byte and 0x80 == 0) break
        multiplier *= 128
        if (multiplier > 128 * 128 * 128) throw EOFException("Malformed remaining length")
    }
    val body = ByteArray(minOf(length, MAX_KEPT))
    var read = 0
    while (read < body.size) {
        val n = input.read(body, read, body.size - read)
        if (n < 0) throw EOFException("Broker closed the connection")
        read += n
    }
    var rest = length - body.size
    val scratch = ByteArray(8192)
    while (rest > 0) {
        val n = input.read(scratch, 0, minOf(rest, scratch.size))
        if (n < 0) throw EOFException("Broker closed the connection")
        rest -= n
    }
    return Packet(header shr 4, header and 0x0F, body, length <= MAX_KEPT)
}
