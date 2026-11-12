# TilauScope Android — autonomous TCP/BLE edition

Status: architecture accepted in principle on 2026-09-19; implementation starts
with milestone M0 below. This is a separate experimental application, not an
Android release of the complete desktop application. Detailed production UI and
individual device support remain to be validated.

## 1. Goal and boundary

Record and eventually guide a roast on an Android tablet without a computer,
using network devices or Bluetooth Low Energy GATT devices. Start with a tablet
in landscape, then validate portrait and phone layouts. Work offline after
installation; cloud services and accounts are not prerequisites.

A roast made on the tablet must move to desktop TilauScope without any loss or
conversion: it is saved as a desktop `.alog` (Artisan profile keys plus the
fork's `tilau_*` keys), and green coffee uses the desktop BeanCave structures
(`BeanCaveContainer` / `GreenBean`, same JSON). The tablet journal stays an
internal crash-recovery file only.

Excluded: USB serial, Bluetooth Classic/SPP, desktop driver bundles, full Artisan
UI parity, unattended roasting, automatic resumption of heater output after a
disconnect. Modbus TCP and MQTT are separate protocols to implement, not automatic
consequences of having a TCP socket.

The existing phone remote-control feature is a different product path: it still
requires desktop TilauScope to own acquisition and control.

## 2. Desktop preservation contract

- All Android source, build configuration, tests and prototype documentation live
  under `android/`; the only shared edit for M0 is a release-history entry.
- No edits, moves, imports or symlinks involving `src/artisanlib/`,
  `src/tilauscope/`, desktop requirements, installers, root Makefile or desktop CI.
- Android has its own package name, dependency manifest and application ID.
  It never reads/writes desktop settings, BeanCave storage or roast directories.
- Build/debug outputs stay inside the new project (normal Gradle/SDK caches are
  external development tooling). The existing desktop build does not invoke it.
- Core tests run with only `android/python` on PYTHONPATH. An import-boundary test
  rejects dependencies outside the standard library and the mobile package.
- Future shared-code extraction is a separate desktop change, requiring desktop
  regression tests. M0 deliberately does not refactor existing business modules.

## 3. Architecture

```text
Touch interface (future local WebView, based on the existing mobile design)
                             |
Android host: permissions, lifecycle, private storage, document export
                             |
Single session worker / future foreground connected-device service
                             |
Python core: samples, quality, RoR, milestones, recording, later guidance
                             |
Device-specific protocol adapters
          |                                      |
 TCP / Modbus TCP / MQTT                  Android BLE GATT
```

Use Kotlin for Android integration and Chaquopy for Python. The final interface
may reuse the existing phone client's layout and chart concepts, but must have
a local data adapter: its current WebSocket pairing/control code assumes a
desktop server. Do not import its Python module or expose a LAN control server
just to embed an interface.

M1 replaces the M0 diagnostic screen with the approved tablet roast screen: a
local WebView page receiving incremental snapshots (new samples only) from the
session service at 1 Hz, and sending commands back through a JavaScript bridge.
The approved mockup is the "Android roast screen" artifact, compact v3 layout.

The session worker owns mutable state. Device callbacks enqueue timestamped
events; they never mutate the UI or session concurrently. UI reads coherent
snapshots at roughly 1 Hz. File serialization, protocol work and later learning
must stay off the main Android thread.

Current prototype toolchain: Python 3.14, Chaquopy 17.0.0, Android Gradle Plugin
8.9.2, Gradle 8.11.1, Kotlin 2.1.20, JDK 17, compile/target SDK 35, min SDK 26;
ARM64 devices and x86_64 emulator. These are development pins, not a claim of
Play Store readiness. Recheck target-API and native-library requirements before
distribution. M0 contains no third-party Python packages.

## 4. Implemented versus planned

| Capability | M0 source status | Production gate |
|---|---|---|
| Android host calling Python | Foreground session service and WebView roast screen (M1); run on emulator and Honor tablet | Real device data |
| Deterministic simulation | CLI and Android adapter | Not a physical roast model |
| Samples, RoR, freshness, basic milestones | Standalone Python implementation | Compare approved recorded reference cases |
| Local persistence | Atomic demo JSON checkpoint; JSON-lines journal restored read-only after process death (M1) | Recovery tested on real roasts |
| TCP | Read-only byte stream; loopback tests | Named device protocol and real network test |
| TC4/BLE | Native GATT link to the Skywalker V2: burner-off verification at every connection, live temperatures recorded, burner/air/drum commands confirmed by echo, burner monitor, reconnection during a roast without re-applying heat, setup commands at the milestones, stop; link check (air test) in Settings (A0 validated 2026-10-16, empty drum) | A roast with beans |
| AirWave | Native GATT link: host name, power, speed, mode, inlet/catalyst readings, knob changes; confirmed values recorded as extractor settings; Settings check | Recorded on a real roast; no duct guard, PID or Omniflux emulation (not wanted) |
| TilauAmbient | Native GATT read of the environment frame once a second; header pill; reading at Charge kept with the roast | Crack counter and its calibrations (later) |
| Scale (Acaia, current family) | Native GATT handshake (ID resent until STATUS), weight notifications, tare, heartbeat; green weight before the roast, roasted weight and loss in the summary; wheel entry without a scale | Other Acaia families and other brands; green coffee stock (BeanCave) |
| Colour meter (RoastSee C1) | Native GATT notifications; whole and ground colours sorted by the operator, kept apart, named by the desktop roast-level scale; wheel entry | Other colour meter brands |
| Water activity meter (RoastSee AquaGauge) | Native GATT notifications, listen only; intermediate values live, final after 2 s of silence; desktop storage zones; Settings check | Stored on the bean by the green coffee cave; meaning of the `dew` field |
| BLE scan/connect/permissions | One scanner (name prefix or service UUID), runtime scan and connect permissions; Android 12+ tested | Android 8–11, refusal and Bluetooth-off flows |
| Modbus TCP / MQTT | Specified only | Address/topic mapping and reconnect semantics per device |
| Heater/fan commands, PID, guidance | Burner, air and drum sent to the real roaster and acknowledged by its echo (simulated without a roaster); no PID or guidance yet | Preheat PID (PREHEAT-SPEC P2) |
| `.alog` interchange | Export on Save roast with Android sharing; Artisan keys, events with the desktop types, extra devices with `tilau_name_map`, `computed` by the desktop rules, `tilau_simulated`; opened in desktop TilauScope | AUC/RoR/energy fields; desktop → tablet import |
| BeanCave and accessories | Later milestones | Per-device and data-model tests |

The roaster link check never commands the burner above 0. During a roast the
roaster's burner, air and drum and the AirWave are driven for real (simulated when no
roaster is declared); the core records the commanded value, never the echo, and never
re-applies heat after a dropped link (MACHINE-SPEC §7). The TCP helper is a development primitive, not a generic
driver for every network roaster.

## 5. Session and data contracts

Internal time is elapsed seconds from a local monotonic origin; temperatures are
Celsius and RoR is °C/min. Never derive recording time from UI refresh count or
wall-clock corrections. The deterministic demo advances a synthetic clock.

M0 accepts strictly increasing receipt timestamps and finite positive BT, with
optional ET. Invalid or missing BT does not refresh data quality. Constant BT
received in new frames is fresh telemetry; a frozen sensor which keeps reporting
needs a separate plausibility detector and must not be confused with link loss.

At a 3-second receive gap, the prototype marks telemetry stale and suppresses RoR.
It clears the RoR window when fresh data resumes. The 20-second least-squares RoR
needs a 5-second span; this is a prototype display algorithm, not numerical parity
with Artisan and not a control signal. Device-specific thresholds and filters
must be validated before control is enabled.

M0 lifecycle: `idle -> recording -> stopped`; each roast uses a new session.
Basic manual markers are CHARGE, DRY END, FIRST CRACK and DROP. CHARGE must precede
other markers, repeats and backward phase progression are rejected; skipped
intermediate markers are allowed. Internal absence is an absent mapping entry,
not an Artisan sentinel. DROP and recorder stop are distinct operations.

The JSON checkpoint identifies `format=tilauscope-mobile-session`,
`schema_version=1`, `simulated`, state, samples and milestone indices. It is not
an `.alog`, and simulated sessions must never enter thermal or cooking learning.
M0 saves explicitly using a temporary file and atomic replacement. M1 adds a
JSON-lines journal (`format=tilauscope-mobile-journal`, schema 1): every event is
flushed, fsync is forced on milestones and stop and otherwise bounded to 5 s. On
start, an existing journal is replayed and shown read-only; an interrupted session
is never resumed, because the monotonic clock origin is lost. A truncated last line
is ignored; any other unreadable journal is renamed `.unreadable`.

`.alog` export (2026-10-13) was checked against the desktop loader: sample
arrays, units, metadata, event numbering, CHARGE sentinel -1 versus later marker
sentinel 0, and extra-device stable names. A later marker at index 0 must not be
silently exported as unmarked. Preserve ground/whole colour categories separately.

## 6. TCP and BLE integration

TCP: explicit endpoint and device profile; bounded receive buffers and operation
timeouts; cancellation closes the socket. M0 does not retry automatically or send
bytes. Next drivers must specify framing, request/response correlation, units,
invalid values and source sequence handling. After reconnect, discard partial
frames and obsolete callbacks; never replay queued actuator writes. MQTT control
must not replay retained heater commands.

BLE: prefer a small native Android GATT adapter unless a Bleak spike proves the
whole packaging/permission path. The documented Bleak Android backend uses
BeeWare/Briefcase and Toga permission handling in addition to Chaquopy and Java
static proxies. `pip install bleak` alone is not the integration plan.

The adapter must own one coordinated scanner, service/characteristic discovery,
CCCD subscription, serialized GATT operations, MTU-aware writes and connection
generations. Filter discovery by device capabilities; do not continuously start
and stop scans. Store Android device identity independently of macOS UUIDs.
Capture timestamps on receipt; queued old-generation packets must not look fresh.

For Android 12+, request BLUETOOTH_SCAN / BLUETOOTH_CONNECT at runtime. Handle
denial, revocation and Bluetooth-off explicitly. Android 8–11 requires the older
permission/location path. Do not declare `neverForLocation` without checking its
filtering impact on supported devices. Add INTERNET for the network milestone.
The scan asks for BLUETOOTH_SCAN (`neverForLocation`, Android 12+) or fine
location (Android 8–11); the link check asks for BLUETOOTH_CONNECT. The
foreground service relies on CHANGE_NETWORK_STATE (a normal permission) and asks
for POST_NOTIFICATIONS.

The first hardware milestones require a foreground `connectedDevice` service
started by an explicit foreground user action, its notification, the appropriate
manifest permissions/types and an API-specific permission flow. Test screen-off,
Doze, app switching and OEM battery management. This service does not guarantee
survival after force-stop or process termination; devices need their own failsafe.

### First device candidates

| Device/protocol | Proposed order | Evidence still required |
|---|---|---|
| One TCP device | First network validation | Model/firmware, endpoint, protocol, sensor and command mapping |
| TilauAmbient BLE | First acquisition candidate | Actual GATT services, captured frames, sustained Android notifications |
| TC4 BLE bridge TD5325A | First roaster-control candidate | Burner-off handshake, fresh echo verification, disconnection behavior |
| BeanCave (`beancave.json`) | Import / export of the desktop file unchanged (Android file picker); stock owner setting | Coffee picked for the roast, `uuid:` link, stock and movements, editing on the tablet (see CAVE-SPEC.md) |
| Printer (Niimbot B21S) | Settings check only: 30 mm test label | Roast, sack and bean labels with the green coffee cave; other roll sizes | Separate profiles and real-device tests |

TCP model selection is still open; do not invent a generic wire format or imply
Modbus compatibility. Omniflux stays outside BLE acquisition. Bluetooth Classic
SPP is outside this project even when the product name includes “Bluetooth”.

The offline TC4 decoder uses the existing `CHAN;1200` mapping: ambient, ET, BT,
burner echo, airflow echo. On the Skywalker V2 tested from Android the second field
is the bean probe and the third the drum probe (VALIDATION, 2026-10-13); the live
link reads them that way. The desktop reads them the other way round and restores
them with Artisan's ET/BT swap setting, which the Android app does not have. ET below BT is valid on the Skywalker. Connecting
starts the air and the drum; `OFF` (same command set as the V1 firmware) stops the
whole machine. Existing desktop code warns
that connection/initialization can energize the burner. A live driver must port
and validate the complete protection sequence before it can connect: subscribe,
initialize, command burner off, confirm a fresh post-command echo with bounded
retries, then expose readiness. Missing echo is unknown, never zero. Preserve
the operator's 80% planning ceiling. Recovery requires an explicit control policy
and must not silently restore a previous heater setpoint.

## 7. Delivery milestones and acceptance

1. **M0 — isolation and executable core (this batch).** Specification, Android
   diagnostic host, standalone simulator, session model, TCP primitive, offline
   TC4 decoder, tests and build instructions. No device-control claim.
2. **M1 — Android runtime.** Build/install an APK; implement service ownership,
   durable journaling and activity recreation (done 2026-10-11). Tactile roast
   screen from the approved mockup with its snapshot adapter (done 2026-10-12).
   First setup assistant, Settings and Bluetooth detection (done 2026-10-13).
   Skywalker V2 link check: burner verified off, live temperatures, 10 s air test,
   stop (done 2026-10-13). AirWave extractor driven from the roast screen and
   checked from Settings (done 2026-10-13). TilauAmbient room conditions in the
   header and at Charge (done 2026-10-13). Green and roasted weights with the
   scale or by hand (done 2026-10-13). Whole and ground colours with the C1 or by
   hand (done 2026-10-13).
3. **M2 — acquisition.** One named TCP device and one BLE sensor. Record at least
   60 minutes, including 15 minutes screen-off; exercise BLE permission flows and refusal,
   Bluetooth/Wi-Fi off/on, malformed frames, repeated temperature, packet gaps,
   reconnect and concurrent BLE devices. No false freshness or fabricated samples.
4. **M3 — manual roasting.** Device-specific actuator controls and feedback,
   explicit disconnect state, safe reconnect, milestones and recovery. Test
   burner-off confirmation and faults on a supervised bench before a real roast.
   Reopen exported `.alog` files in desktop TilauScope and compare data/events.
5. **M4 — guidance and ecosystem.** Extract selected logic behind plain-data APIs;
   compare against a curated corpus before introducing shared desktop imports.
   Add BeanCave, accessories and automation only after their own validation.

Before distribution: test ARM64 native-library compatibility (including 16 KB
page-size devices), supported OS versions, signing/update path, storage export via
Android's document picker, accessibility and translations. Translations go through
the desktop's single circuit (strings extracted into the `.ts` catalogue and edited in
the same tool), not a separate set of Android resources (operator, 2026-10-16: one system;
later). Desktop Qt translation conventions continue to apply to desktop code.

## 8. Documentation and validation record

Prototype instructions are in `README.md` and `docs/prototype.md` in this project.
No released desktop workflow, screenshot or glossary entry changes. Do not insert
future Android functionality into the published desktop manual as if available.

Automated checks: session lifecycle, irregular sampling, stale data, constant BT,
milestones, atomic checkpoint failure, TC4 framing/generation/invalid data, TCP
EOF/timeout/cancellation and import isolation. These do not replace Android builds
or physical-device tests. Record actual verification in `VALIDATION.md`.

## 9. References checked on 2026-09-19

- [Chaquopy Android integration](https://chaquo.com/chaquopy/doc/current/android.html)
  and [version compatibility](https://chaquo.com/chaquopy/doc/current/versions.html).
- [AGP 8.9 toolchain requirements](https://developer.android.com/build/releases/agp-8-9-0-release-notes).
- [Bleak Android backend and integration prerequisites](https://bleak.readthedocs.io/en/latest/backends/android.html).
- [Android Bluetooth permissions](https://developer.android.com/develop/connectivity/bluetooth/bt-permissions).
- [Android background BLE communication](https://developer.android.com/develop/connectivity/bluetooth/ble/background).
- Local architecture references: `../src/tilauscope/roast_bridge.py`,
  `../src/tilauscope/tc4ble.py`, `../src/tilauscope/webclient.py`,
  `../src/tilauscope/roast_plan_model.py`. Consult them; do not import them.
