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

Two compact rows along the top carry the actions needed while roasting. The first row keeps the
monitoring, recording, and timer controls together; the second row holds less frequent actions.

| Control | What it does |
|---|---|
| **☰** | The main menu. |
| **Power** | Turns monitoring on and off. |
| **START / STOP** | Starts and stops recording. |
| **RESET** | Clears the current roast. It stays on the secondary row. |
| **BeanCave** | Opens the green-bean database. It stays on the secondary row. |
| **G / E pill** | The operator level — see [Getting started](getting-started.md#guided-or-expert). |
| **⇄** | Switches the control view. |
| **⠿** | A grab strip for moving the window. It runs along the end of the secondary row. |
| **STOP HEAT** | The emergency [heat cut](glossary.md#heat-cut). It appears at the end of the secondary row once monitoring is on, and is described below. |
| Timer | The roast clock. |

These are deliberately large and few. During a roast, the buttons that matter must be hittable
without aiming.

!!! note
    START/STOP will not start a recording if no meter is configured — there would be nothing to
    record. Configure a device, or run the simulator, first.

<!-- CAPTURE 2.2 — the header, cropped, at full width and legible. -->

---

## Cutting the heat in an emergency

If a roast goes wrong — smoke you did not expect, a burner that will not come down, anything that
means the batch has to end now — **STOP HEAT** puts the machine into a safe state in one gesture.
It appears at the end of the secondary row as soon as monitoring is on, and nowhere else, so it is
in the same place whether you are following the guided assistant or driving the controls yourself.

**Hold it down for one second.** A red sweep fills the button while you hold. Releasing early, or
sliding off the button, cancels it — a stray click cannot end a roast.

When it fires, TilauScope:

- stops anything that was driving the heat on your behalf — preheating control, PID, alarms and
  profile playback — so nothing pushes the burner back up a second later;
- sets the burner to zero;
- opens airflow and, if you have an extractor paired, extraction to full.

The drum keeps turning. Stopping it would press the beans against a hot wall, and that is how a
scorch becomes a fire.

The panel then turns red and shows the one thing left to do: **empty the drum into the cooling
tray**. TilauScope does not do this for you — the beans come out by hand, and marking the end of
the roast without them actually leaving the drum would only put a false milestone in your record.
Monitoring and recording keep running, so you can watch the temperature come down.

On a machine TilauScope cannot command, the message asks you to turn the burner off yourself
instead. The heat cut still stops every automation.

**RESET**, or turning monitoring off, releases the red state and gives the panel its normal look
back.

<!-- CAPTURE 2.2b — the panel just after STOP HEAT fires: red border, "HEAT CUT" message, red
     timer. Reproduce with the simulator running, then hold STOP HEAT for one second. -->

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

## The roast curve

The large area on the right is the roast itself, drawn by TilauScope. It is read at a glance and
at arm's length, so it carries what matters during a roast and leaves the rest for
[after](after-the-roast.md).

**What is on it.** The name of the roast above the plot — the batch number and the title you
gave it, exactly as it is filed. The bean temperature as a thick line, its
[rate of rise](glossary.md#ror--rate-of-rise) as a thinner one on its own scale at the right, and
the three phases as coloured grounds beneath both.

**Colours name probes, not quantities.** Each curve carries the colour of the readout it belongs
to — so the bean and its rate are one family, the air and its rate another. Inside a family the
temperature is the solid line and the rate the quieter one, which is why a rate is never mistaken
for the line the roast is read from. Change a curve colour in Artisan's own settings and both the
curve and its readout follow — blue for
[drying](glossary.md#drying--dry), yellow for [Maillard](glossary.md#maillard), red for
[development](glossary.md#development), deepening as the roast advances. Each milestone is marked
where it happened, with its name and the temperature it was marked at. The
[turning point](glossary.md#tp--turning-point) is marked too, even though it is never something
you mark yourself.

The time axis names every minute and rules every second one, so a duration can be read off it
without counting.

**Two views.** Above the curve, a two-part selector: **Full scale** keeps a fixed frame — one
minute before the charge to fourteen minutes — so two roasts can be compared without either one
having been stretched to fit. **Charge to drop** trims the frame to the roast that actually
happened. The selector appears once you stop recording. Not at the drop: the beans are still in
the cooling tray, the frame is still growing under the curve, and a window claiming to end at the
drop would keep being wrong.

The minute before the charge shows the two temperatures only. A rate of rise there is the drum
warming up, not the beans climbing, so the rate starts at the charge.

**Hovering.** Moving the pointer across the curve puts a line at that instant and reports what
every trace held there, including the setting each lever was holding. **Every figure in that row
is named**, in the same words the legend uses for its trace — two rates can appear side by side,
and the one called *Rise* is the same rate of rise the large readout shows.

### What the curve says next

Two cards float over the curve, and only ever one at a time.

Before the charge, while the drum climbs, a **preheat card** reports how far up it is and how
long it has left. It sits against the target line rather than against the climb, so it stays
where you last looked for it instead of travelling up the chart. The chart underneath shows the
same thing: the target as a line, dashed while the drum is still climbing and solid once it is
there, and — as soon as the arrival is close enough to be in frame — a mark on the target line at
the moment the climb is due to meet it.

Once the drum reaches its target the card gives way: the chart says **CHARGE NOW** on the head of
the climb, where you are already looking, and there is nothing left to count down.

Once the roast is running, a **roast card** takes over. It leaves when you stop recording — a
card that says what to do next has nothing to say about a roast that has ended. It names the phase, counts down to the
next milestone, and reports where the roast stands. A dashed marker on the curve shows where that
countdown lands, and the card **steps over that marker** rather than covering it as the bean
walks towards it.

At the Guided level the card has **two faces**, and a small button in the top-left corner of the
curve switches between them:

| Button | The card shows |
|---|---|
| **🎯** | The coach view — the phase, what is coming, and what to do about it. |
| **📊** | The full data view — every figure the roast has produced so far. |

The button appears only at the Guided level. At Expert the full view is the only one, since an
operator reading the whole table has already said which face they want.

<!-- CAPTURE 2.8a — the curve mid-Maillard with the coach card showing and the 🎯 button visible.
CAPTURE 2.8b — the same moment with the 📊 full data card. CAPTURE 2.8c — the preheat card and
the target line, with the arrival mark in frame. -->

### Choosing what is traced

**Right-click anywhere on the curve** to open its options. Display choices are remembered for
future sessions, so the curve returns with the same traces and lever layout the next time you
open TilauScope.

| Option | What it adds |
|---|---|
| **Air temperature** | Traces [ET](glossary.md#et--environmental-temperature) alongside the bean. Unavailable on a roast recorded without an air probe — there would be nothing to draw. |
| **Machine response** | Traces the [machine response](glossary.md#machine-response) — the earliest sign that a burner change has landed. |
| **One lane per channel** | Gives each machine lever its own strip beneath the curve. |
| **Burner traced, others as gestures** | Traces only the burner, and reduces the others to marks at the moments they moved. |
| **Rate of rise** | How much the rise is smoothed — three levels, from responsive to steady. |

The rate scale on the right appears with the roast: before the charge the drum is climbing, not
roasting, and a scale with nothing on it invites reading the drum against the wrong numbers.

The last one is not a display setting. The rate of rise is never stored in a roast file; it is
recalculated every time a roast is opened. Changing the level therefore changes what the rate
**is**, on this roast and on every one opened afterwards.

**The lever strips are drawn live**, throughout the preheat and the roast, and each one carries
its current level in figures at its right edge. Reading a gesture against the curve it caused is
the point of them, and that reading is worth most while the roast is still running. Before the
first move on a channel, the strip shows the level the lever is being held at.

**Replaying a simulated roast**, a small **x1 / x2 / x8** selector sits at the top right of the
curve for as long as the simulation runs. It sets the replay speed directly, in place of clicking
the clock with a modifier key held.

<!-- CAPTURE 2.8d — the right-click menu open over the curve. CAPTURE 2.8e — a roast mid-Maillard
showing the lever strips beneath the curve, in one-lane-per-channel mode, with at least two
gestures already played on the burner. -->

---

the machine rather than sitting at the desk.
## Machine controls

The four machine levers — on a typical setup burner, airflow, drum and extraction — use compact
segmented controls. The filled segments show the current setting in the lever's colour; the
remaining segments show the available range. The percentage remains visible beside the bar, so
colour is never the only indication.

The **−** and **+** buttons move by the machine's own step size. Each click is accepted even when
the previous click was not immediate. Holding either button repeats the action, which is useful
when making a larger adjustment with one hand.

Clicking the percentage opens the roller, where the value can still be selected directly. The
roller is the same precise control used by the previous slider presentation. Whichever way the
value is chosen, it is aligned to the machine's step size before being sent, so the setting shown
is always the one the machine received and the one recorded on the curve.

Beneath both, and always visible, sits the **SV** row — the
[setpoint](glossary.md#sv--setpoint-value) the PID is aiming for. It spans the full width and is
never hidden by the toggle, because the setpoint is not a lever like the others: it is the target
everything else is working towards.

On a read-only machine, these controls are absent entirely — see
[Preparing a roast](preparing-a-roast.md#machines-tilauscope-cannot-drive).

<!-- CAPTURE 2.8 — the segmented control zone, four levers plus the SV row.
CAPTURE 2.9 — the percentage roller open on one control. -->

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
