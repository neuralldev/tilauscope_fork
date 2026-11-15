// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The roaster's frames (ACQUISITION-SPEC T5): a malformed line is never a reading. */
class Tc4FrameTest {
    @Test
    fun aFrameGivesTheTemperaturesThenTheEchoes() {
        val frame = tc4Frame("21.5,180.2,175.3,65,40")!!
        assertEquals(listOf(21.5, 180.2, 175.3), listOf(frame.ambient, frame.et, frame.bt))
        assertEquals(65 to 40, frame.burner to frame.air)
        assertNull(tc4Frame(" 21.5 , 180.2 , 175.3 ")!!.burner) // no echo: none read
    }

    @Test
    fun malformedLinesAreDropped() {
        for (line in listOf("", "21.5,180.2", "21.5,,175.3", "a,b,c", "21.5,NaN,175.3", "21.5,180.2,Infinity",
                "21.5,180.2,-Infinity", "#ERR", "21.5;180.2;175.3")) {
            assertNull(line, tc4Frame(line))
        }
        assertNull(tc4Frame("21.5,180.2,175.3,NaN")!!.burner) // a bad echo is no echo
    }

    @Test
    fun aRepeatedFrameIsAReadingEachTime() {
        val buffer = StringBuilder()
        assertEquals(listOf("21.5,180.2,175.3", "21.5,180.2,175.3"), tc4Lines(buffer, "21.5,180.2,175.3\r\n21.5,180.2,175.3\r\n"))
    }

    @Test
    fun linesAreJoinedAcrossChunksAndSplitWhenMerged() {
        val buffer = StringBuilder()
        assertEquals(emptyList<String>(), tc4Lines(buffer, "21.5,18"))
        assertEquals(listOf("21.5,180.2,175.3", "21.6,180.4,175.9"), tc4Lines(buffer, "0.2,175.3\r\n21.6,180.4,175.9\r\n21"))
        assertEquals("21", buffer.toString())
    }

    @Test
    fun lfEndedLinesReadAsCrlfOnes() { // the SkyCommand box (Skywalker V1) ends its frames with LF alone
        val buffer = StringBuilder()
        assertEquals(listOf("0,201.5,201.5,40,60", "0,202.0,202.0,40,60"),
            tc4Lines(buffer, "0,201.5,201.5,40,60\n0,202.0,202.0,40,60\r\n0,2"))
        assertEquals("0,2", buffer.toString())
    }

    @Test
    fun commandsAreWrittenAsTheBridgeReadsThem() {
        assertEquals("OT1,50", tc4Wire("OT1,50", semicolon = false))
        assertEquals("OT1;50", tc4Wire("OT1,50", semicolon = true))
        assertEquals("COOL;100", tc4Wire("COOL,100", semicolon = true))
        for (unchanged in listOf("READ", "OFF", "CHAN;1200")) assertEquals(unchanged, tc4Wire(unchanged, semicolon = true))
    }

    @Test
    fun aRunawayLineIsDroppedAndTheNextFrameReads() {
        val buffer = StringBuilder()
        assertEquals(emptyList<String>(), tc4Lines(buffer, "x".repeat(300)))
        assertEquals(0, buffer.length)
        assertEquals(listOf("21.5,180.2,175.3"), tc4Lines(buffer, "21.5,180.2,175.3\r\n"))
    }
}
