# Acquisition tests (SPEC §7, M2) — spec, 2026-10-22

To validate before any test is run or any code changed. M2 asks: record at least 60 minutes,
15 of them screen off; Bluetooth permission flows and refusal; Bluetooth and Wi-Fi off/on;
malformed frames, repeated temperature, packet gaps; reconnection; several BLE devices at
once. No false freshness, no fabricated sample.

## 1. What exists (read in the code)

- **The roast clock counts ticks.** `SessionService` calls `advance(1)` with
  `scheduleWithFixedDelay(1 s)`; `Demo.advance` adds 1 s to `now` per call. A tick therefore
  lasts 1 s **plus** the time the Python call takes, and the roast time falls behind the wall
  clock. No wake lock is held: screen off, MagicOS may suspend the CPU and the ticks with it,
  while BLE notifications still arrive.
- **Freshness**: a reading older than 3 s (`Session.STALE_AFTER_S`, read on `time.monotonic`)
  is stale; a sample is taken only from a fresh reading (gap otherwise, `test_link`).
- **Roast link frames** are parsed in Kotlin (`Tc4Link.parse`): three numbers needed, else the
  line is dropped. `"NaN"` and `"Infinity"` parse as numbers. The Python TC4 decoder tested in
  `test_core` is the TCP primitive's, not the one used on the tablet.
- **Reconnection**: the roast link retries by address (0.5, 1, then 2 s); `dropForTest`
  forces a loss. The accessories have their own links.
- **Already validated**: rotation, app switch, `kill -9` → read-only interrupted roast
  (M1, 2026-10-11); a link loss during an empty-drum roast (A0, 2026-10-16).
- **Not exercised**: long screen off with Doze, notification permission refused, Bluetooth
  switched off during a roast, malformed frames on the tablet's parser.

## 1b. Before the tests: a reliable clock, no sleep during a roast (operator, 2026-10-22)

Proposal v2, to validate before code. The tick count came from M0's deterministic simulator
(one simulated second per call) and was kept when the real link arrived; nothing requires it.

1. **Roast time = the real clock, as Artisan's `timex`.** Each tick the service passes
   `SystemClock.elapsedRealtime()` (it counts while the CPU sleeps); the roast time is that
   clock minus its value at Start, in fractional seconds. Every sample, milestone, lever
   setting and alarm carries that time (read in Python on `CLOCK_BOOTTIME`, Android's
   `elapsedRealtime`). The tick stays at a fixed delay of 1 s, one sample per tick: with the time
   from the clock a slow tick no longer stretches the roast, and a fixed rate would replay a burst
   of ticks when Android uncaches the process. A tick under 0.5 s after the previous one
   samples nothing.
2. **A late tick**: its sample carries its real time, so the curve shows the gap; nothing is
   filled in. RoR is already computed on time, not on the sample count.
3. **The tablet reports its lateness.** A gap between two samples above 2 s is a late
   sampling: counted with its longest gap, written in the log, kept in the `.alog`
   (`tilau_late_sampling`: count, longest gap in s) and shown in the roast summary when there
   was one. Live (operator, 2026-10-22): the link pill turns peach with a clock picto,
   "<roaster> · tablet late N s" (N = the late gap), for 30 s after the last late sample; the
   red link-lost state wins over it (mockup V7h9AsDXMNdBFgemUjACq1). The cooling state keeps
   its own peach dot without the tint or the picto.
   Why the heat tests showed no gap: with the tick count a late tick stretched the second
   instead of leaving a hole, so lateness could not show; only a lost link left gaps.
4. **Replay unchanged**: simulated seconds, ×1/2/8, pause. The synthetic machine (no roaster
   declared) follows the real clock as a roast does, so T1/T2 can run without the roaster.
   `advance(n)` stays for the tests.
5. **No CPU sleep while a roast is active**: the service holds a partial wake lock while
   recording (preheat included, an interrupted roast excluded), renewed for 60 s at each tick so a
   stalled worker lets it lapse; released otherwise and when the service is destroyed.
6. **Screen kept on** while recording (`FLAG_KEEP_SCREEN_ON`, already in place since M1), as
   on the desktop: the operator follows the curve and moves the levers (operator,
   2026-10-22, essential). The power key still turns it off; the roast goes on (point 5).
7. **Background without restriction is a prerequisite** (operator, 2026-10-23): the app's
   battery use unrestricted / its launch managed by hand, set once by the operator in
   Android's settings and stated in the guide. Nothing specific to one Android brand in the
   code: the app runs on any Android.

*Done and validated 2026-10-23* on the Honor Pad 9 with the Skywalker V2 (points 1–6), see
VALIDATION.

## 2. Tests proposed

| # | Test | How | Pass |
|---|---|---|---|
| T1 | Clock drift, screen on | 20 min recording, no roaster declared (synthetic machine); roast time read against the wall clock | gap ≤ 1 s |
| T2 | Screen off | Same, 60 min with 15 min screen off (`adb` power key), then `dumpsys deviceidle force-idle` | roast time = wall time ± 1 s; samples continuous or an honest gap, never a fabricated one |
| T3 | Bluetooth off/on | Accessories that are powered (AirWave, TilauAmbient…), synthetic roaster; `cmd bluetooth_manager disable` 30 s, then enable | readings go stale within 3 s, gap in the curve, each device reconnects by itself, no crash |
| T4 | Permissions | `pm revoke` Bluetooth (scan, connect) and notifications, then open the app and start | the app asks, explains, keeps working without the refused device; no crash |
| T5 | Frames | Kotlin unit test of `Tc4Link.parse`: short line, letters, NaN/Infinity, empty fields, merged lines, oversized line, repeated identical frame | malformed: dropped, never a sample; repeated: kept as a real reading |
| T6 | Concurrent devices | T3's devices connected together during T2's hour | each device's readings in the file, no lost link |

*T3 and T6 dropped* (operator, 2026-10-23): every accessory switches itself off after a few
minutes, none can be left on beside the tablet; their links are exercised in real roasts.
*T1 and T2 covered* by the roast of 2026-10-23 (ACQUISITION-SPEC 1b, VALIDATION).
*Bluetooth lost with the real roaster covered* (operator, 2026-10-23): A0, and the roast of
2026-10-23 where the link dropped for 17 s, the roaster cut its burner and the tablet reconnected.
*T3 done after all* 2026-10-23 (the operator switched TilauAmbient and the scale on): Bluetooth
off 30 s then on, outside a roast. Two defects found and fixed: (1) the app closed — the scale's
heartbeat wrote through Android 13's `writeCharacteristic`, which throws `DeadSystemException`
when the stack dies, uncaught on the link's thread; every link had it, the roaster's included
(13 writes, now through `writeOrRefuse` in Gatt.kt: a refused write, the link's loss handling
follows). (2) No accessory came back: a reconnection attempt made while Bluetooth was off stopped
at "bluetooth_off"; the six self-reconnecting links now keep trying every 2 s (the roaster's link
already did during a roast). After both: no crash, Ambient and scale back within 20 s.
*T4, part 1 fixed and validated* 2026-10-23: permission requests wait their turn (one at a
time, as Android shows them), and every link waiting for the connect permission connects once it
is granted (only the last one did). Part 2 done and validated the same day (mockup V7h9AsDXMNdBFgemUjACq1, board "Bluetooth not
allowed"): the link pill turns red, "Bluetooth not allowed"; a card over the curve says what
is cut and opens Android's page of the app; back with Bluetooth allowed, the page connects its
devices again, the roast link included when a roast records.
*TCP kept in M2* (operator, 2026-10-23): the network accessories will come as on the desktop, MQTT
first, and Matter for example — their own spec when started.
*T4 found* 2026-10-23 (part 2 to fix, mockup first): Start asks for notifications while
the roast screen asks for Bluetooth at once — Android drops the second request, the Bluetooth
question never shows; refused, the roast screen stays on "Connecting to …" with no word of it
(it does not handle the link's "denied").
*T5 done* 2026-10-23: `tc4Frame` / `tc4Lines` (Tc4Link.kt), 5 Kotlin unit tests. Two defects
fixed: "NaN" and "Infinity" read as temperatures (a NaN put into the link's JSON throws on the
link's thread); a partial line with no end of line grew without limit (dropped past 256
characters).

T1–T4 and T6 run on the Honor Pad 9 over `adb`, by me, with **no roaster heating**: the
roaster stays undeclared or switched off. T5 runs on the computer.

## 3. Decisions to take (operator)

1. **Real roaster**: the reconnection with the real Skywalker was validated in A0; is a
   Bluetooth-off test on the real roaster wanted (empty drum, operator present), or does T3
   with the accessories suffice?
2. **TCP and Wi-Fi**: no network device in the stack. Drop "one named TCP device" and the
   Wi-Fi off/on test from M2?
3. **If T1/T2 show a drift**: the fix is a spec of its own (time from the monotonic clock
   instead of the tick count, and/or a partial wake lock while recording). To discuss with
   the measurements, before any code.
4. **Accessories for T3/T6**: which ones can be powered near the tablet during the test?
