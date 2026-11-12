// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

package org.tilauscope.android.prototype

import org.junit.Assert.assertEquals
import org.junit.Test

/** The roast link's queued commands (audit 2026-10-25 B02): heat is never re-applied after a dropped link. */
class Tc4ScriptTest {
    @Test
    fun heatGivenWhileTheLinkIsAwayIsNeverKeptForTheRecovery() {
        val asked = listOf("OT1,70", "OT2,40", "OT1,0", "OT3,80", "OT1, 12.5", "ot1,5", "EVT,3", "OFF")
        assertEquals(listOf("OT2,40", "OT1,0", "OT3,80", "EVT,3", "OFF"), keptWhileAway(asked))
    }
}
