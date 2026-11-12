// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.ByteArrayInputStream

/** MQTT 3.1.1 packets, against the examples of the OASIS standard. */
class MqttLinkTest {
    private fun bytes(vararg values: Int) = ByteArray(values.size) { values[it].toByte() }

    @Test
    fun remainingLengthUsesSevenBitsPerByte() {
        assertArrayEquals(bytes(0x00), remainingLength(0))
        assertArrayEquals(bytes(0x7F), remainingLength(127))
        assertArrayEquals(bytes(0x80, 0x01), remainingLength(128))
        assertArrayEquals(bytes(0xFF, 0x7F), remainingLength(16_383))
        assertArrayEquals(bytes(0x80, 0x80, 0x01), remainingLength(16_384))
    }

    @Test
    fun connectCarriesTheProtocolTheFlagsAndTheCredentials() {
        val anonymous = mqttConnect("ab", "", "", 60)
        assertArrayEquals(bytes(0x10, 14, 0, 4, 'M'.code, 'Q'.code, 'T'.code, 'T'.code, 4, 0x02, 0, 60, 0, 2, 'a'.code, 'b'.code), anonymous)
        val withUser = mqttConnect("ab", "u", "p", 60)
        assertEquals(0xC2, withUser[9].toInt() and 0xFF) // user, password, clean session
        assertArrayEquals(bytes(0, 1, 'u'.code, 0, 1, 'p'.code), withUser.copyOfRange(withUser.size - 6, withUser.size))
    }

    @Test
    fun subscribeAsksQosOneForEachTopic() {
        assertArrayEquals(bytes(0x82, 7, 0, 1, 0, 2, 'a'.code, '/'.code, 1), mqttSubscribe(1, listOf("a/")))
    }

    @Test
    fun publishesAreReadAtQosZeroAndOneAndAcknowledged() {
        val qos0 = mqttPublish(0, bytes(0, 3, 'a'.code, '/'.code, 'b'.code, '2'.code, '1'.code))
        assertEquals("a/b" to "21", qos0.topic to qos0.payload)
        assertNull(qos0.packetId)
        val qos1 = mqttPublish(0x02, bytes(0, 1, 't'.code, 0x12, 0x34, '{'.code, '}'.code))
        assertEquals(0x1234, qos1.packetId)
        assertEquals("{}", qos1.payload)
        assertArrayEquals(bytes(0x40, 2, 0x12, 0x34), mqttPubAck(0x1234))
    }

    @Test
    fun aPacketIsReadWholeWithItsTypeAndFlags() {
        val (type, flags, body) = readPacket(ByteArrayInputStream(bytes(0x32, 0x80, 0x01) + ByteArray(128)))
        assertEquals(PUBLISH to 2, type to flags)
        assertEquals(128, body.size)
    }

    @Test
    fun aLargeRetainedMessageIsReadPastAndTheNextPacketReads() {
        val big = ByteArray(275_448).also { it[0] = 0; it[1] = 1; it[2] = 't'.code.toByte() }
        val stream = ByteArrayInputStream(bytes(0x31) + remainingLength(big.size) + big + bytes(0x30, 4, 0, 1, 'u'.code, '7'.code))
        val first = readPacket(stream)
        assertEquals(false, first.whole)
        assertEquals("t", mqttPublish(first.flags, first.body).topic) // its start is kept: topic and packet id
        val next = readPacket(stream)
        assertEquals("u" to "7", mqttPublish(next.flags, next.body).let { it.topic to it.payload })
    }
}
