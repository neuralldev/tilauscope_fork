# TilauScope Android prototype

Independent sources for an autonomous TCP/BLE edition. Start with [the specification](SPEC.md).
The current Android screen is a simulation harness, not a device-control application.

| Directory | Purpose |
|---|---|
| `app/` | Kotlin activity and Chaquopy Android configuration |
| `python/tilauscope_mobile/` | Standard-library-only session core, demo, TCP reader, offline TC4 decoder |
| `tests/` | Independent core, transport and isolation checks |
| `docs/` | Prototype usage, separate from the desktop manual |

## Run without Android tooling

From the repository root, using Python 3.14 (no pip installation required):

```sh
PYTHONPATH=android/python:src python3 -m unittest discover -s android/tests -v
PYTHONPATH=android/python:src python3 -m tilauscope_mobile --seconds 600
PYTHONPATH=android/python:src python3 -m tilauscope_mobile --seconds 600 --output /tmp/tilauscope-demo.json
```

Without a tablet or a roaster, `make android` runs the three benches: the Python core, with whole roasts on a
virtual Skywalker (`tests/virtual_roaster.py`); the WebView pages in jsdom, the real core behind a fake bridge
(`tests/pages`, Node 22, `npm ci` there once); and the Kotlin links on a simulated GATT (Robolectric, JDK 17/21).

Tests use temporary files and loopback TCP sockets, never real devices. If running
from `android/`, use `PYTHONPATH=python:../src` and `-s tests` instead. Only the shared
`src/tilaucore` (standard library) comes from the desktop: do not install the desktop
requirements.

The optional independent package install is `python3 -m pip install ./android`
inside a dedicated virtual environment. The APK packages `android/python`
directly; it does not need that install.

## Build the diagnostic APK

Required: JDK 17 or 21, Gradle **8.11.1**, Android SDK Platform 35 / Build Tools 35.0.0,
Python 3.14 and internet access for the first dependency resolution. This project
uses AGP 8.9.2, Kotlin 2.1.20 and Chaquopy 17.0.0. See the official toolchain
references in the specification. Native Python and Java build tooling are separate.
Android Studio's bundled JDK 25 is rejected by Gradle 8.11.1: point `JAVA_HOME` to a
JDK 17 or 21 when building from the command line.

1. Install those tools or use Android Studio to install the SDK components.
2. Set `ANDROID_HOME` to your SDK or create `android/local.properties` with
   `sdk.dir=/absolute/path/to/Android/sdk` (ignored by Git).
3. From the repository root, run:

   ```sh
   android/gradlew -p android :app:assembleDebug
   ```

4. Install `android/app/build/outputs/apk/debug/app-debug.apk` on an ARM64 device
   (Android 8 or newer) or x86_64 emulator. Launch **TilauScope Android Lab**.

The Gradle 8.11.1 wrapper is included; do not use a desktop build script.
SDK/build caches may use normal user tool directories. No desktop application dependencies are altered.

The roast screen is a local WebView page (`app/src/main/assets/roast.html`) fed
once a second by the session service. It drives a simulated roaster: curve, RoR,
milestones, burner/air/drum/extractor settings with a simulated machine echo, and
settings lanes. A saved roast is `demo-session.json` in private app storage
(visible through Android Studio's Device Explorer on a debug build). No real
device connection exists yet. Start the simulated read-only roaster with
`adb shell am start -n org.tilauscope.android.prototype/.MainActivity --ez simulate_readonly true`.
WebView console messages are logged under the `TilauScopeWeb` tag.
A foreground service owns the session, which survives rotation and app switching
and is journaled to `session.journal`. After process death, the next start restores
it read-only; it is never resumed.
See [prototype usage](docs/prototype.md) and [verification status](VALIDATION.md).

## Next implementation step

M1 is done: service ownership, journaling and the tactile roast screen (see
[VALIDATION.md](VALIDATION.md)). The first setup assistant and Settings detect the
roaster and accessories over Bluetooth, and a link check connects to the
Skywalker V2 (burner confirmed off first), shows its temperatures and raises the
air for 10 s, then stops the machine. The AirWave extractor is driven for real
from the roast screen (power, speed, mode, inlet and catalyst temperatures) and
can be checked from Settings. The TilauAmbient probe shows the room temperature
and humidity in the header and its reading at Charge is kept with the roast. The
Acaia scale (or the wheel, without it) records the green and roasted weights, and
the C1 colour meter (or the wheel) the whole and ground colours. The AquaGauge
water activity meter and the B21S label printer can be checked from Settings,
ready for the green coffee cave. Settings › BeanCave imports and exports the
desktop's `beancave.json` unchanged (see [CAVE-SPEC.md](CAVE-SPEC.md) for the rest
of the cave and the roast plan). The
roast curve itself still runs on the simulated
roaster: recording from the real machine is the next step (M2).

Save roast exports a desktop `.alog` and shares it. There is no resumption of an
interrupted session, connection to
the other accessories, Modbus/MQTT driver, PID, or production roast guidance yet.
