# Hardware and peripherals

!!! abstract "Artisan does / TilauScope adds"
    **Artisan does** — talks to a roaster, a scale, and whatever generic serial or Bluetooth
    device its own device dialog can be pointed at.

    **TilauScope adds** — recognition of a set of specific devices by name, so pairing one
    is a search-and-confirm step rather than a manual device-dialog configuration, plus a
    place in **Configuration → SENSORS** to see, add or remove every paired device at once.

Every device fiche below follows the same shape: what it adds, how it pairs, what changes on
screen once it is paired, and its known limits. Setup fields for a device live in
[Configuration](configuration.md#-sensors--every-coupled-device); this chapter is the
reference for what each device *is*.

!!! note
    Pairing any Bluetooth device here can be done from the first-time setup wizard's
    Hardware step (see [Getting started](getting-started.md#first-time-setup)) or later from
    **Configuration → SENSORS** — both use the same scan. A device removed from SENSORS is
    unpaired immediately.

---

## Roaster link

**What it adds.** A live, two-way link to the roaster: readings in, control levers out. Set
once as the [machine profile](preparing-a-roast.md#telling-tilauscope-which-machine-it-is);
everything downstream — the roast plan, the guided recommendations, the slider labels —
follows from it.

**Pairing.** TilauScope's own roaster link (used by the Skywalker range) connects by USB
cable by default, and needs no pairing beyond plugging it in and selecting the model.
Connecting it over Bluetooth instead is also supported — select the model and pair it like
any other Bluetooth device — and TilauScope switches to that link automatically once paired.

**What changes on screen.** Every control slider follows the machine's own range and step,
and the guided assistant's recommendations name gestures that machine actually has.

**Known limits.** A roaster without a supported control link still works in
[read-only mode](preparing-a-roast.md#machines-tilauscope-cannot-drive): readings only, no
sliders, guidance becomes advice rather than a control to move.

!!! note "Older Skywalker models"
    An earlier Skywalker generation connects over a different Bluetooth link than the one
    described above. It is recognised, but its setup is closer to a generic Bluetooth device
    than to the guided pairing the current model gets.

<!-- CAPTURE 9.1 — the roaster model picker, list open. CAPTURE 9.2 — sliders on a paired
machine vs. the same panel in read-only mode. -->

---

## AirWave — smoke extractor

**What it adds.** Extracts smoke and, above roughly 30% output, cools the drum — see
[The guided roast](the-guided-roast.md#airflow-by-phase) for how airflow is used through a
roast.

**Pairing.** Bluetooth, found and confirmed the same way as any other paired device.

**What changes on screen.** The damper slider is claimed automatically for AirWave control
the moment it is paired, and stays available even on a read-only roaster, since the extractor
is a separate device from the roaster link itself.

**Known limits.** Fan output below its practical minimum has little effect; the useful range
starts around 30%.

<!-- CAPTURE 9.3 — the damper slider labelled for AirWave once paired. -->

---

## Omniflux — colour and crack sensor

**What it adds.** Reads roast colour and listens for cracks acoustically, feeding
[automatic first-crack marking](preparing-a-roast.md#automating-the-start) and the
[after-the-roast colour record](after-the-roast.md#weight-colour-and-notes).

**Pairing.** Two distinct paths exist, and they behave differently:

- **A genuine Omniflux unit** connects over a wired sensor link and needs its channels set up
  once in Artisan's own generic sensor configuration, matched to a specific register layout —
  this is the one device in this chapter that is not set up from
  [Configuration → SENSORS](configuration.md#-sensors--every-coupled-device). TilauScope
  detects it automatically once that configuration matches, and quietly does nothing if it
  doesn't.
- **An AirWave can be switched into emulating one**, from a checkbox in the AirWave's own
  SENSORS entry, so a roasting phase feed reaches whatever is listening for it without a
  second physical sensor.

**What changes on screen.** Colour readings and crack detection feed the same milestones and
records as a real Omniflux, whichever path supplies them.

**Known limits.** The wired setup path has no TilauScope screen of its own — it depends on
Artisan's generic sensor configuration being entered correctly, with no on-screen confirmation
if it is not.

<!-- CAPTURE 9.4 — the AirWave's "emulate Omniflux" checkbox. -->

---

## TilauAmbient — ambient probe

**What it adds.** Room temperature, humidity and pressure during roasting (the
[AMBIENT window](preparing-a-roast.md#what-the-coffee-and-the-room-are-doing)), and an
acoustic source for [automatic first-crack marking](preparing-a-roast.md#automating-the-start).

**Pairing.** Bluetooth, found and confirmed the same way as any other paired device.

**What changes on screen.** The AMBIENT window appears during roast preparation; crack
detection gains a second possible source alongside Omniflux.

**Known limits.** This is TiLau's own probe design — it needs its own firmware installed
before it will be found at all, unlike the off-the-shelf devices in this chapter. Its
crack-listening sensitivity is a setting of its own, independent of the general first-crack
detection settings in [Configuration → DETECTION](configuration.md#-detection--milestone-tuning).

<!-- CAPTURE 9.5 — the AMBIENT window with a live reading. -->

---

## Acaia scale

**What it adds.** Live weight capture wherever a weight is entered — batch weight, stock,
brew dosing — instead of a typed approximation.

**Pairing.** Bluetooth. Unlike every other device in this chapter, a scale is not paired from
SENSORS: it is set up the first time it is needed, from the first-time setup wizard's
Hardware step, or directly where a weight is captured.

**What changes on screen.** A small floating scale reading appears next to any field that
accepts a captured weight; clicking the value writes it in.

**Known limits.** Two scales can be paired at once (for instance, one for green weight and
one for a brew), never more.

<!-- CAPTURE 9.6 — a floating scale reading beside a weight field. -->

---

## Niimbot printer

**What it adds.** Prints roast, bean and sack labels — see
[Labels and QR](labels-and-qr.md#printing-on-the-niimbot).

**Pairing.** Bluetooth. Once paired, TilauScope remembers this exact printer and reconnects
to it directly next time, rather than searching again.

**What changes on screen.** A live printer status indicator appears wherever a label can be
printed.

**Known limits.** Requires the specific supported Niimbot model — see
[Labels and QR](labels-and-qr.md#printing-on-the-niimbot) for paper sizes and constraints.

---

## AquaGauge — water activity meter

**What it adds.** A direct water activity reading for a coffee's storage record — see
[Sacks, stock and conservation](sacks-and-storage.md#measuring-water-activity).

**Pairing.** Bluetooth, found and confirmed the same way as any other paired device.

**What changes on screen.** A floating live reading appears next to the water activity field
whenever it is being edited.

**Known limits.** One coffee at a time — there is no batch-measurement mode.

---

## Colour meter

**What it adds.** A direct roast-colour reading, feeding the same colour fields as a typed or
judged value in the [after-the-roast record](after-the-roast.md#weight-colour-and-notes).

**Pairing.** Bluetooth, found and confirmed the same way as any other paired device.

**What changes on screen.** A live reading button appears next to the colour fields in the
roast result form once paired.

**Known limits.** This is a different product from Omniflux above, and a different pairing —
having one does not register the other.

---

## Network sensors (MQTT)

**What it adds.** A way to bring in a reading from any sensor able to publish to a shared
network broker, rather than only Bluetooth devices TilauScope recognises by name — used today
for [storage-room humidity tracking](sacks-and-storage.md#storage-room-humidity).

**Pairing.** Not Bluetooth: a broker address is set once in
[Configuration → INTEGRATIONS](configuration.md#-integrations--outside-services), then each
reading is picked out by naming which topic carries it.

**What changes on screen.** Wherever a network reading is used, a **⚙ configure** control
sets or tests which topic and value feed it.

**Known limits.** Read-only: TilauScope reads a value a sensor publishes, it does not
configure or control the sensor itself.

<!-- CAPTURE 9.7 — a network-sensor configure dialog with a live test reading. -->

---

## Pairing and scanning, in general

Every Bluetooth device above is found the same way: TilauScope scans continuously in short
bursts while a pairing screen is open, so a device can be turned on after the screen is
already open and still be found. **Configuration → SENSORS** lists what is currently paired
per device family, with a control to unassign one — done immediately, with no confirmation
step to undo it.

Devices seen nearby but not recognised, or recognised but not yet assigned to a role, are
listed separately in the same screen, so a device that isn't working can be told apart from a
device that was never found at all.

<!-- CAPTURE 9.8 — the SENSORS tab, an assigned device and an "other hardware nearby" entry
both visible. -->

---

## Alarms: sentences, badges and a timeline

Alarms appear in three different places, each answering a different question:

- Written as **rule sentences**, they say *when* an alarm fires — see
  [The guided roast](the-guided-roast.md#alerts).
- As **colour-coded badges** in the live column, they say *what just fired* — see
  [The TilauScope window](the-window.md).
- As a **visual timeline**, opened from the alarm editor, they lay out every configured alarm
  against the roast clock at a glance, to check a whole set for gaps or overlaps before
  roasting rather than while it matters.

<!-- CAPTURE 9.9 — the alarm visual timeline, several alarms configured across the roast. -->

---

## Next

- Setting up a paired device's parameters: see [Configuration](configuration.md).
- The window controls a paired device ends up driving: see [The TilauScope window](the-window.md).
- Any unfamiliar term: see the [Glossary](glossary.md).
