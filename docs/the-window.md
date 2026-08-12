# The TilauScope window

!!! abstract "Artisan does / TilauScope adds"
    **Artisan does** — one dense window: curve, LCD readouts, event sliders, alarm table,
    message line at the bottom. Everything is present at once, sized for a desk and a mouse.

    **TilauScope adds** — a separate roasting window built for the moment the drum is turning:
    large readouts that change colour as a temperature approaches its limit, machine controls in
    the form that suits the hand, phase blocks whose targets can be adjusted on the spot, and a
    live column on the right showing what just fired.

This chapter describes the window itself. What the assistant *says* inside it is
[The guided roast](the-guided-roast.md); this is the furniture.

<!-- CAPTURE 2.1 — the whole TilauScope window mid-roast, at a comfortable size, with the
sidebar expanded. This is the reference screenshot for the entire documentation. -->

---

## The header

A single strip along the top carries the actions needed while roasting, in the order they are
used:

| Control | What it does |
|---|---|
| **☰** | The main menu. |
| **Power** | Turns monitoring on and off. |
| **START / STOP** | Starts and stops recording. |
| **RESET** | Clears the current roast. |
| **BeanCave** | Opens the green-bean database. |
| **G / E pill** | The operator level — see [Getting started](getting-started.md#guided-or-expert). |
| **⤢** | Docks or detaches the assistant. |
| Timer | The roast clock. |

These are deliberately large and few. During a roast, the buttons that matter must be hittable
without aiming.

!!! note
    START/STOP will not start a recording if no meter is configured — there would be nothing to
    record. Configure a device, or run the simulator, first.

<!-- CAPTURE 2.2 — the header, cropped, at full width and legible. -->

---

## The readouts

Three large readouts sit above the control panel: **bean temperature**, **environmental
temperature**, and **rate of rise** — the last one larger than the other two, because it is the
number that dictates what to do next.

They are not passive digits. **Each readout changes background colour as its value approaches a
limit**: neutral while there is margin, then dark yellow as the value enters the approach band,
orange, then deep red at the limit — and once the limit is passed, the background **pulses red**.
A temperature running away is visible peripherally, without reading the number.

Below them, a row of **extra counters** shows the readings of whatever additional devices are
configured, each with its name above its value — colour, humidity, crack count, whatever the
setup provides.

<!-- CAPTURE 2.3 — the three readouts in neutral state. CAPTURE 2.4 — the same readouts with one
in the red/approach state, ideally the BT readout near its limit. CAPTURE 2.5 — the extra
counters row on a setup with at least two extra devices. -->

---

## The phase blocks

Three blocks — **DRYING PHASE**, **MAILLARD PHASE**, **FINISHING PHASE** — show the roast's
progress through its phases, each in its own colour: blue for
[drying](glossary.md#drying--dry), yellow for [Maillard](glossary.md#maillard), red for
[development](glossary.md#development). Each block carries a subtitle with its target.

**A phase target can be adjusted directly on its block**, with the scroll wheel or a trackpad
swipe over it. No dialog, no menu: the correction is made where the number is displayed, while
the roast continues.

When the roast reaches its end, the same area is taken over by the drop and cooling message, so
the instruction of the moment occupies the space that the phase blocks no longer need.

<!-- CAPTURE 2.6 — the three phase blocks mid-Maillard, with the active phase visibly current.
CAPTURE 2.7 — the same area showing the drop/cooling message instead. -->

---

## Machine controls, in two forms

The four machine levers — on a typical setup burner, airflow, drum and extraction — can be
displayed in **two different shapes**, and the choice is yours. A **slim vertical bar at the
right edge of the control zone** switches between them: click it, and the controls change form.
Its tooltip says what it does: *Toggle: horizontal sliders ↔ card controls*.

**Slider rows** — one row per lever: name, a horizontal slider, **−** and **+** step buttons, and
the current percentage. The steppers move by the machine's own step size, so a click is always a
valid setting. Precise, compact, and familiar to an Artisan user.

**Control cards** — one card per lever, each an upright block with **▲** at the top, the value in
the middle, **▼** at the bottom, and the lever's name underneath. Big targets, no dragging, and
usable without looking closely. This is the form to prefer on a touchscreen, or when standing at
the machine rather than sitting at the desk.

Clicking the value itself, in either form, opens a roller to dial the number in directly.

!!! tip
    The two forms are the same controls, not two modes: whichever is on screen, the value sent to
    the machine is identical, and switching between them never changes the window's size. Pick
    the shape that suits how you actually stand while roasting.

Beneath both, and always visible, sits the **SV** row — the
[setpoint](glossary.md#sv--setpoint-value) the PID is aiming for. It spans the full width and is
never hidden by the toggle, because the setpoint is not a lever like the others: it is the target
everything else is working towards.

On a read-only machine, these controls are absent entirely — see
[Preparing a roast](preparing-a-roast.md#machines-tilauscope-cannot-drive).

<!-- CAPTURE 2.8 — the control zone in slider-row form, four levers plus the SV row.
CAPTURE 2.9 — the same zone in card form, same values, so the two can be compared side by side.
CAPTURE 2.10 — the value roller open on one control. -->

---

## The live column on the right

A column along the right edge reports what the application is doing, so nothing happens silently.
It is opened and closed by the **slim grip strip** at its edge — a chevron pointing **›** when
collapsed and **‹** when open — and it fades rather than jumping, so the eye is not pulled away
from the curve.

### LIVE EVENTS

The upper part is titled **LIVE EVENTS**, with a count of what it holds and a **✕** to clear it.
Each entry arrives as a card:

- **Triggered alarms** — the alarm that fired, with its condition and the milestone it was
  anchored to, colour-coded by what it acts on: PID, air, drum, burner, or an external command.
  Rather than discovering after the roast that an alarm fired, you see it land.
- **Fired events** — each press of an event button, tagged **EVT** with its command and the time.

Cards fade in as they arrive and stack newest-first, so the column reads as a running account of
the roast.

### ARTISAN messages

Below the events sits a section headed **ARTISAN**: the messages Artisan itself emits — the ones
that, in Artisan, flash once in the status bar and are gone. Here they are **kept**, timestamped,
newest highlighted and older ones dimmed, up to the last forty, with a button to clear them.

**Routine noise is filtered out**, so the section holds what has operational meaning rather than
every internal notice. When something unexpected happens mid-roast, the explanation is usually
already sitting in this list — which is the whole point of keeping it.

<!-- CAPTURE 2.11 — the sidebar expanded, showing at least one triggered-alarm card and one fired
event. CAPTURE 2.12 — the ARTISAN message section with several messages, newest highlighted.
CAPTURE 2.13 — the grip strip in both states, collapsed and expanded. -->

---

## The event buttons

Artisan's event buttons are also available as a **floating panel** that can be moved and resized
freely, and that remembers its position and size between sessions. Pressing a button fires its
command and posts a card in **LIVE EVENTS**, so a manual action leaves the same trace as an
automatic one.

Placing it where your hand naturally goes — beside the machine, not beside the curve — is the
point of it floating.

<!-- CAPTURE 2.14 — the floating event panel, positioned away from the main window. -->

---

## Window behaviour

The window is frameless, with its own title bar, and can be resized from its corner grip. The
assistant can be docked in place of the control panel or floated as a separate window, and the
control zone keeps a fixed height so that switching control forms, or docking the assistant,
never resizes the window underneath your hands.

---

## While the app is working

Anything that takes more than a moment — reading a folder of roast files, exporting, searching
for a Bluetooth device, downloading an update — reports itself the same way everywhere, so there
is nothing new to recognise each time.

A **turning ring** means the app is busy and cannot say how long it will take. A ring that
**fills**, or a bar that fills, means the end is known, and the count beside it says how far
along it is — *47 of 312*, never a bare percentage. The ring turns **green with a tick** when the
work finishes, and stops on **red** when it does not, with the text saying what to do about it.
A red one stays until it is read; it never disappears on its own.

Where the indicator appears tells you whether you can carry on working. In the corner of a
window, it is a small badge and the window stays usable; you can keep browsing, and cancel from
the badge if the work allows it. In the middle of the screen, the work must finish before
anything else is touched.

Cancelling stops what has not started yet, never what is already out in the world. On a
printer, **✕** stops the run after the label currently coming out of the head, and the badge
then says how many were actually printed. Label printing is described in
[Labels and QR](labels-and-qr.md#while-a-label-is-printing).

Short actions do not announce themselves at all: below roughly half a second nothing is shown,
because an indicator that flashes reads as a glitch rather than as work.

!!! note "During a roast"
    The app never opens a window of its own accord while the drum is turning. Anything it starts
    on its own goes to the corner badge, where it can be ignored. A window opened deliberately
    from the coffee database is a different matter — that one was asked for.

If the computer is set to reduce motion in its accessibility settings, nothing turns: the same
indicators breathe gently instead. TilauScope follows the system setting; there is nothing to
configure.

---

## Next

- What the assistant reports inside this window: see [The guided roast](the-guided-roast.md).
- Setting up a batch before you get here: see [Preparing a roast](preparing-a-roast.md).
