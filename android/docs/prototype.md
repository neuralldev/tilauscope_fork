# Using the Android prototype

> **Artisan does** — record and control roasts on the desktop.
>
> **TilauScope adds** — an isolated Android development prototype for tablets.
> It finds your roaster and accessories over Bluetooth and checks the link with
> the Skywalker V2; roasts are still recorded from a simulated roaster.

The Android build requires the developer setup described in the [README](../README.md).
It is not an installer delivered with the Mac or Windows edition.

Open **TilauScope Android Lab**. The screen is shown in landscape only. While the
app prepares its engine, a start screen shows the TilauScope bean and **Getting the
roaster ready…** while TilauScope's signature sound plays, once per launch (turn the
media volume up to hear it); the roast screen replaces it as soon as the app is ready. The badge
**Simulation** in the header reminds you that the roaster, its curve and its
settings are simulated: the curve is a software test, not a suggested roast.

## First setup

Without a configuration, the app opens on the first setup in four steps:

1. **Machine** — choose your roaster. Machines the tablet cannot drive yet are
   listed below, greyed out. **Later** goes straight to the roast screen.
2. **Connection** — switch the roaster on and keep it close to the tablet. The
   first time, Android asks whether the app may look for nearby devices. Touch
   your roaster when it appears.
3. **Check** — the tablet connects to the roaster and checks the link (see
   [Checking the roaster link](#checking-the-roaster-link)). **Skip the check**
   goes on without it.
4. **Devices** — switch on the accessories you use; each one found nearby can be
   added. **Finish** saves the setup and opens the roast screen.

Nothing is saved before **Finish**.

Before the first roast, let the app run in the background without restriction: in Android's
settings for the app, set its battery use to unrestricted, or its launch management to
manual, as your Android version names it. Otherwise Android may pause the app for a few
seconds during a roast, screen off, and the roaster link drops.

## Checking the roaster link

The check first makes sure the burner is off: the roaster must confirm it before
anything else is sent. **Burner off** then appears, and the bean, drum and room
temperatures arrive live from the roaster.

The tablet then raises the air to 60 % for 10 seconds; the screen shows what was
sent and what the roaster reports. Listen to the fan and answer **Do you hear the
fan speed up?**. At the end of the 10 seconds the tablet stops the roaster (burner,
air and drum) and lets go of it: **Roaster stopped** appears and the last readings
stay on screen. **Test again** runs the whole check again.

If the burner cannot be confirmed off, or the roaster cannot be reached, the
tablet lets go of it and sends nothing else; switch the roaster off and on, then
select **Try again**. Leaving the check also stops the roaster.

## Settings

The gear in the header opens **Settings**, between roasts only:

- **General** — your machine (**Change** reopens the first setup), your name, the
  **Temperature unit** (°C or °F: readings, curves, targets typed, alarms and summaries; the
  roast file stays in °C and the desktop converts it on opening), and the
  milestones the tablet marks for you when you roast without the plan:
  - **Charge detection** (on by default, as Artisan's Auto CHARGE) marks Charge when the
    bean temperature drops as the beans go in, by hand and when you follow a roast;
  - **Dry end detection** marks Dry end from the bean temperature, by hand only, around
    the trade's 158 °C read in your roaster's probe (150 °C on the Skywalker V2);
  - **Crack detection** has TilauAmbient listen to the cracks at every roast and marks
    First crack, by hand only, around 195 °C in the same way (185 °C on the Skywalker V2).
- **Controls** — the name shown for each control (only the extractor can be
  renamed) and the step of each tap, 5 % by default. Colours follow the theme.
- **Devices** — the roaster link and the accessories. The tablet looks for them
  while this page is open. **Test** on the roaster runs the link check, **Test**
  on the extractor runs the extractor check, **Test** on the water activity meter
  runs the water activity check, **Test** on the label printer runs the printer
  check; a **Test** button stays grey while its device
  is not heard nearby. **Forget** removes a device.
- **Network** — the MQTT broker and the sensors read through it. Type the broker's host, port,
  user and password (**TLS** for an encrypted broker); its state shows under **Broker**:
  connected, refused (check the user and password) or not reachable. **＋** adds a sensor:
  its name, its topic, the field to read when the message is a JSON object (empty for a
  message that is the value itself), what it feeds — room temperature (°C or °F), room
  humidity, pressure, roaster power or extractor power — and a multiplier and a divider. While
  the page is open, each sensor shows its last value; its sheet shows it too, and how long ago
  it came; a topic just typed shows its value at its next message, unless the broker keeps the
  last one. With **TLS**, the broker's certificate must name its host. Touch a sensor to change
  it; the bin deletes it. Every change is saved at once, between roasts.
- **Alarms** — your Artisan alarm lists (`.alrm`). **＋** creates a list, **⤓** imports
  one from the files the tablet reaches. Touch a list to use it in every roast, whatever
  the coffee, or **None** for no alarm; its chevron opens it; swipe it left to delete it.
  Each list says how many of its alarms the tablet does not run (for example a PID row:
  the preheat is set in Roast Setup).

  In an open list, each alarm reads as on the desktop: when it fires, then what it does.
  Touch the moment to choose the milestone, the delay, a temperature condition and the
  alarms it follows or waits for; touch the action to choose a lever and its value, an
  event button, a message, an extractor or TilauAmbient command. Touch the alarm's number
  to turn it on or off (green when on), the bell for its beep; hold the handle to move it;
  swipe it left to delete it, **Undo** brings it back. **＋** adds an alarm, **⤴** sends
  the list. Every change is saved at once, in the file the desktop reads.

Changes apply when you go back to the roast screen.

## Checking the extractor

The extractor check connects to the AirWave and shows its inlet and catalyst
temperatures, its mode and whether it is on. The tablet then changes the speed
for 10 seconds (to 60 %, or to 30 % if it already runs at 60 % or more); the
mode never changes. Answer **Do you hear the extractor speed change?**. The speed
is then put back; an extractor that was off is switched on for the check and off
again after. The tablet then lets go of it.

## Checking the water activity meter

The water activity check connects to the AquaGauge and only listens: nothing is
sent to it. Fill the meter's cup with green beans, close it and start a
measurement on the meter. For about 2 minutes the value shown is intermediate:
it moves with its curve (water activity on the left axis, time below, the
storage zone limits dashed) and its storage zone. When the meter stops sending,
the last value is the result: water activity with its storage zone (**Too dry**
below 0.45, **Optimal**, **To watch** from 0.60, **Mould risk** from 0.65, as on
the desktop) and **Check done**. A new measurement replaces it. The reading is
not saved yet; the green coffee cave will keep it on the bean. If the meter
stops answering during a measurement (switched off, out of range), the check
says so and the measurement is discarded; the tablet reconnects by itself.

## Checking the label printer

The printer check connects to the B21S and shows its battery, whether the cover
is closed, the roll type and the labels left (read from the roll's tag). Load a
30 mm roll, close the cover and press **Print test label**: the label shown is
exactly the one printed (the TilauScope bean, a test sentence, the date and a
frame). Sending takes a few seconds, then the printer reports the label out and
the check is done. **Not confirmed** means the printer never reported it: check
the label before printing again, it may be correct or blank. If the bottom line
falls outside the label, reload the roll and print again.

## Printing a roast label

The roast label is the desktop's 30 mm label: origin and farm, the coffee, its
process, altitude, density and SCA score (a line without a value is left out),
the roast date and the coffee's tasting notes. It needs the roast's coffee in
the BeanCave, Dry end, First crack and Drop marked, and the label printer in
Settings › Devices. A printer icon offers it in two places: beside **Roast
complete** once the roast is over, and at the end of a roast's buttons in the
BeanCave's Roasts tab. The icon stays grey while the tablet looks for the
printer and turns violet once it is found; a touch prints, the icon pulses, then
shows a tick when the label is out. A problem (printer not found, cover open, no
answer, a label that may be blank) shows in a short message at the bottom.

## BeanCave

Settings › **BeanCave** holds your green coffees and their tastings in the same
files as TilauScope on a computer: `beancave.json`, with `tastings.json` and
`brewlog.json` when the computer has them. They always move together.

- **Stock kept by** — *This tablet* when you roast with the tablet only (the tablet
  keeps the coffees and their stock); *A computer* when TilauScope desktop keeps
  them (the tablet holds a read-only copy; what changes on the tablet waits under
  **To send back**). Applied when you go back to the roast screen.
- **Import the BeanCave…** — pick the BeanCave folder of TilauScope (for example
  copied to the tablet). Every file in it is checked first: a folder without
  `beancave.json`, or with a file that cannot be read, is refused and nothing
  changes. Over an existing BeanCave, both are compared (coffees, stock, tastings)
  before **Replace**; **Send first…** keeps a copy.
- **Send the BeanCave…** — Android's share sheet with the tablet's BeanCave files,
  exactly as the tablet holds them. Put them in the BeanCave folder of TilauScope
  to use them on the computer.
- The tastings show in the roast memory of a coffee and above a roast in the Roasts
  tab ("Tasted: …"). A tap on that banner, or **Taste** on a roast not tasted yet,
  opens the computer's tasting: would you roast it the same way again, what was off,
  notes, and what the next roast will change. On a Yes, ☆ makes the roast the
  coffee's reference (one per coffee). Tastings and the reference go back with the
  BeanCave files, whoever keeps the coffees. The app never asks you to taste.
- **Start empty** (tablet owner only) — a BeanCave with no coffee yet.
- **Currency** — the currency of purchase prices, from the same list as the
  desktop; the tablet's system currency until you choose one. Choosing does not
  convert the prices, it names their currency.

The bean button beside Settings on the roast screen opens the **BeanCave screen**:
your coffees in stock (or all of them), a search, and the selected coffee's sheet
with the same zones as on the computer. **Roast this coffee** goes back to the roast
screen and shows the coffee in the header with the stock left, in peach when the
green weight asks more than the stock (the roast is not blocked). The saved roast
carries the coffee's title and its link to the bean, as a roast made from Roast
Setup on the computer. The choice stays for the next roasts and changes between
roasts only.

When **Stock kept by** is *This tablet*, a tap on a zone of the sheet (marked ›) opens
its editor (a tap on the flavour notes edits the score, notes and memo) and **+ New coffee**
adds one; a new coffee needs its name, country, category, process, species and
varieties. Lists are picked, never typed. A field a device can fill shows that
device beside it: the scale for the stock (**Use as stock** once the weight is
stable) and, with **⚖ Measure**, for the density (choose the container's volume,
tare it empty, fill it); the AquaGauge for water activity (**Use as aw** once the
measurement ends). **🎡 Flavours** opens the flavour wheel as a dial: drag it or tap
a family to turn it, tap notes to choose them; notes that are not on the wheel are
kept.

The bean sheet's **Roast memory** shows the coffee's last real roast as on the
computer (date, level, weight, development, loss, colour); **All N roasts →** opens
the **Roasts** tab on that coffee. **Roasts** (beside **Coffees** at the top of the
BeanCave) lists every roast the tablet holds on two lines, under day or coffee
headings, sorted **Most recent**, **Oldest first** or **Coffee A–Z** (the arrow marks
the sort in use). Each roast says where it comes from: *from the computer*, *this
tablet*, *simulated · not used by plans*. The selected roast shows beside the list:
its curve with the settings lanes and the same summary tiles as on the computer
(roasted weight, roast time, drop temperature, colour, energy). As on the computer, each
milestone — Charge, the turning point (dotted: it is computed, not marked), Dry end, First crack,
Drop — has a dot on the bean curve and a chip with its bean temperature and time; close chips take
a second row. A double tap on the curve opens it full screen, another closes it. **Open the
coffee**, the share icon and the replay, follow and label icons act on the roast. When the roast
has an energy record (or a saved power curve), the **Energy** tile gives the roast's kWh from Charge to
Drop (its line says **Charge → Drop**; the sheet's total adds the preheat and the cooling) and where
it comes from; touching it opens the energy sheet. A roast recorded in
°F on the computer is read in the unit shown.

To delete a roast, swipe its row to the right: a bin appears behind it, and touching anywhere
else, or swiping back, closes the row. The bin asks first, and touching outside the card keeps the
roast. The roast file leaves the tablet; for a roast from the computer only the tablet's copy goes,
and the computer keeps its file. The green stock does not change. The roast list, each coffee's
roast memory, the plan and the preheat learning read the roasts left; a coffee whose reference
roast is deleted loses its ★. A roast is deleted between roasts only, never during a roast or a
simulation.

In Settings › BeanCave, **Roasts**: **Import from the computer…** asks for a folder
(Android's picker: open it, then *Use this folder*), says how many of its roast files
are new, already on the tablet or not roasts, and imports them with **Import**.
**Send the tablet's roasts…** hands the roasts made on the tablet to Android's share
sheet (a folder, Google Drive, a message). The app never deletes a roast.

**Roast Setup › Plan** shows the plan of the next roast as the computer does: choose
the **Roast level** and **What is this coffee for?** (Filter, Omni, Espresso; both are
kept for the next roasts). The roadmap gives charge, dry end, first crack and drop with
their temperature, time and burner, air and drum settings, then the weight to aim for
after cooling and the plan's notes. When the coffee has a reference roast (the star
of a tasting), a yellow ★ line under the roadmap says the plan follows it; when it cannot
serve this batch, a grey ☆ line says why (another weight, another level, not tasted Yes…). Beside it, the planned bean temperature and rate of
rise over the band of this coffee's past roasts at that level, from the tablet and the
computer (simulated roasts are never used). The plan follows the weight typed in Setup,
the room probe when it answers (otherwise 20 °C and 50 %), its air pressure, and its altitude (otherwise
sea level). Without a machine in Settings there is no plan.

## The roast screen

The curve fills the left of the screen: bean temperature, ET and rate of rise
(RoR), with the temperature scale on the left and the RoR scale on the right.
Under the curve, one lane per setting shows each change you made as a step, with
the new level beside it and the level held now at the end.

The chosen coffee and its Roast Setup are kept when the app is closed and reopened,
as long as the BeanCave still holds the coffee.

With the roaster declared in Settings › General, **Start** connects to it
(its air and drum start) and the roast reads its temperatures; the pill at the top left
names it. The burner starts at 0: only the burner buttons raise it. Each setting shows
the roaster's echo (✓) once the roaster has taken it; the drum has no echo and shows
what was sent. Charge, Drop and End roast send the machine's own commands. End roast
cools the roaster before stopping it: burner off, cooling on, air at 100 % and drum at
80 %, then, once the bean temperature is under 50 °C, the cooling is ended as the desktop's
**Cool end** does and the roaster is switched off. The pill
reads **Cooling the roaster…** and the temperatures stay live meanwhile. Starting the next
roast while it cools stops the cooling and takes the roaster back. If the link drops, the roaster stops its burner by itself, the
tablet reconnects on its own and the recording goes on with a gap; once back, the
burner stays at 0 and a banner asks you to raise it again. For a test with an empty
drum, a long press on the roaster pill drops the link the same way.

With **Preheat** on in Roast Setup (its target comes from the plan's charge; it follows
the bean or the air probe), Start also starts the preheat: TilauPID drives the
burner, never above 80 %, and the screen shows the target, the time to reach it, then
**CHARGE NOW**. Touching the burner pauses the preheat and keeps your value; **Resume
preheat** gives the burner back to it. Touching a lever during the preheat never switches
off the automatic milestones: they take over at Charge. What it learns is kept at Charge. If the roaster
stops answering, the preheat stops it safely, cooling it first.

What the roast follows is drawn in the background, from Charge: the plan, or the roast
you follow. Its bean temperature and rate of rise are dashed, its dry end, first crack and
drop dotted (*DRY*, *FC*, *DROP*), and its burner, air and drum steps dashed in the lanes.
During the roast a chip names it (*Plan · Medium Light · Filter*, or *Following ·* the
roast's title). It is not re-anchored when the roast runs ahead or behind. A roast made by
hand shows nothing behind it.

The turning point is drawn as on the desktop once found: a dotted line down to the bean
curve, a dot on it and **TP** with its time.

The right-hand panel reads from top to bottom:

- the current phase, the time spent in it and the roast clock;
- **Beans** and **RoR** side by side, with ET under the bean temperature (both to one
  decimal) and the
  change of RoR over the last minute under the RoR. RoR is shown from its first
  positive value after Charge until Drop;
- the **Burner** and **Air** controls;
- the **Drum** and **Extractor** values, which you change less often;
- the milestones and the button for the next one.

## Recording a roast

<!-- CAPTURE — the roast screen before Start, The plan chosen: the three choices over the curve, the plan dashed behind, the Start button in the plan's colour -->

Before the roast, choose what it follows with the three choices at the top of the curve:

- **By hand** — you mark the milestones; your alarm list runs. The detections of
  Settings › General (Charge, Dry end, Crack) mark their milestones if they are on.
- **The plan** — the milestones checked AUTO in Roast Setup › Plan mark themselves; the
  alarms do not run. Offered once the plan is ready (a coffee, a roast level, a weight).
- **A roast** — the burner, air, drum and extractor move as in the roast followed: the
  coffee's ★ reference, or the roast picked with the follow picto in BeanCave › Roasts.
  Charge marks itself with Charge detection on; you mark the other milestones; the alarms
  do not run. Offered once there is a roast to follow.

The curve shows the plan or the roast chosen, and the large button names the choice and
what it runs: **Start by hand**, **Follow the plan** or **Follow a roast**. Every roast
starts on **By hand**: the choice is never kept from one roast to the next.

Select the large button to start. The first time, Android asks whether the app may send
notifications; the notification **Session in progress** keeps the roast running
when you leave the screen. Refusing the permission only hides that notification.
While a roast is recorded, the screen stays on; turned off with the power key, the roast
goes on. The roast time is the tablet's clock, as on the desktop.

The large button always names the next step: **Charge**, **Dry end**, **First
crack**, **Drop**, then **End roast**, which stops the recording after cooling.
The milestone row above it shows the times already marked. The arrow button
beside it undoes the last milestone.

**Stop** in the header is an emergency stop: it ends the recording at once.

<!-- CAPTURE — the roast screen just after an automatic Dry end: the toast "Dry end · marked automatically" over the curve -->

A milestone the tablet marks for you shows a toast: *Dry end · marked automatically*.
Following the plan, the first touch on a lever after Charge switches the automatic
milestones off for the rest of the roast (*Auto milestones off · you mark them*); during the
preheat a touch leaves them armed. By hand, touching the levers is the roast itself: only
undoing a milestone switches the detections off.

Following a roast, its moves are played at the same bean temperature after the turning
point, at the same time before it, and the levers glide between two moves as Artisan's
replay does. The first touch on a lever gives the levers back to you for the rest of the
roast (*Following off · the levers are yours*).

<!-- CAPTURE — the roast screen in the first minute, Crack detection on: the chip "Crack counter · empty drum · 26 s" in the header -->

With Crack detection on, or the plan's First crack on AUTO, TilauAmbient calibrates twice:
on the empty drum 20 s after Start, then on the beans 1:30 after Dry end, then counts the
cracks until Drop. A chip in the header shows each 30-second calibration
(*Crack counter · empty drum · 26 s*). First crack needs the counter: without TilauAmbient
it is not marked for you.

## Changing a setting

- **− 5** and **+ 5** move the burner or the air by one step of the machine.
- Touch the value to open a wheel, scroll, and touch a value to choose it. Touch
  outside the wheel to close it without a change.
- Touch **Drum** or **Extractor** to open their controls; touch outside to close.
  The drum is normally set at charge.

After each change the setting reads **Sending…** until the roaster confirms it,
then shows the confirmed value. On a roaster that exposes no burner, air or drum
command, only the extractor is shown.

### The AirWave extractor

When an AirWave is in the setup, the roast screen connects to it by itself. The
dot on the **Extractor** chip is green while it is connected; the chip shows its
speed, **Off**, or **—** when it is not answering. Touch the chip to open its
panel:

- **On** and **Off** start and stop the extractor;
- **− 5** and **+ 5** (or the value, which opens the wheel) set the speed from 30
  to 100 %;
- **STD**, **EXT** and **FAN** choose its mode;
- **Inlet** and **Catalyst** show its temperatures.

A change made on the extractor itself appears on the tablet too. While a roast is
recorded, each confirmed change is a setting on the extractor lane (off counts as
0). If the extractor stops answering, the panel reads **Looking for it…** and the
tablet reconnects by itself.

### Room conditions

When a TilauAmbient probe is in the setup, the header shows **Room** with the
room temperature and humidity, updated every second. A dash replaces them when
the probe has given no reading for 3 seconds; an old value is never shown. The
reading at **Charge** (temperature, humidity and pressure) is kept with the roast
and shown in the summary as **Room at charge**.

MQTT room sensors (Settings › Network) give the room when TilauAmbient does not read: each
reading on its own, valid 10 minutes after its last message, as such sensors report when the
value changes. TilauAmbient always wins while it reads. A reading no sensor gives stays empty,
in the header, at Charge and in the roast file.

### Energy

With a real roaster, the tablet counts the energy of the session from Start to the end of the
roast, the preheat included, as the desktop counts it from monitoring on: from the MQTT sensors
that feed **Roaster power** and **Extractor power** (Settings › Network), each reading taken when
it arrives. Without a reading of the roaster, its power is estimated from the burner between
Charge and Drop, from the Skywalker V2's measured curve; a reading always wins. The record goes
into the roast file, where the desktop's energy sheet reads it. A simulated roast has none, nor
a roast restored after the app was closed during it.

### Weights

Before the roast starts, the **Green** chip holds the weight of the green coffee.
Touch it to weigh: the scale shows the weight live, rounded to the gram, with
**Stable** or **Settling…**. **Tare** zeroes the scale; **Use** takes the weight once
it is stable. **Enter by hand** opens the wheel instead, in whole grams from 50 to
1000 g; without a scale the wheel opens directly.

When the roast is over, the summary shows the weight: **Weigh roasted** takes the
roasted weight the same way, then the summary shows both weights and the weight
lost in percent. **Weigh again** replaces the roasted weight.

### Colour

The summary also shows the roast colour, whole beans and ground apart. Start a
measurement on the colour meter itself: the reading appears with its roast level
(for example **Light**) and asks **Which sample?**; touch **Whole beans** or
**Ground**. A reading taken before the roast is over waits in the summary. Touch a
value to enter or change it by hand on the wheel, from 20 to 130 on the SCA scale.

## Alarms during the roast

With a list chosen in Settings › Alarms, its alarms fire as on the desktop: at a
milestone or TP after a delay, after another alarm, or when a temperature crosses a
value. An alarm does what your hand would do: the setting is recorded and confirmed by
the roaster, and a burner alarm pauses the preheat. It can also press one of the
roaster's event buttons (cooling on, for example), command the AirWave extractor, send
the crack counter's commands to TilauAmbient and show a message over the curve. An alarm
with its bell on plays the short take of TilauScope's signature sound, on the media volume.

A step an alarm made carries a yellow dot in its lane, and a toast names the alarm
for a few seconds. The **Alarms** chip in the header counts the alarms fired; touch it
to see the list. What has fired is greyed with its time, a yellow **now** line shows
where the roast is, and the next alarm is outlined. Touch anywhere else to close it.
End roast still cools the roaster first, whatever the list says.

## Simulating a roast

To work without the roaster, replay a recorded roast. In **BeanCave › Roasts**, choose a
roast and touch the replay picto beside the label printer: the roast screen opens in
simulation, with that roast's curve. No device is connected; your levers, alarm list and
preheat stay the ones you use with the roaster, and nothing is taken from the stock.

The header reads **Simulation**. Next to it, a bar shows where the replay is in the roast,
preheat included, with its speed: **1×**, **2×** or **8×**, and **⏸** to pause (touch it
again to resume at the same speed). While paused, nothing is recorded and the preheat
waits. Choose what the roast follows and start it as on a real roast. A simulation follows
the roast it replays: **A roast** plays its levers back without a pick in BeanCave.

From Charge, the replayed curve answers the burner and the air: a burner higher or lower
than in the replayed roast raises or lowers the rate of rise, felt after a few seconds as
on the roaster, and the air does the same during Maillard only. Levers left as they are
make a different roast from the one replayed. At 2× or 8×, the replay slows to 1× by itself
30 seconds before its beans go in, so that you can mark Charge; choose a speed again to go
on faster.

**Exit** takes the place of Stop: the simulated roast is dropped, never saved, and the
levers return to where they were. To try the end of a roast, let the replay run to Drop
and end the roast as usual; a simulated roast is saved as simulated and never used by the
plans.

## When something goes wrong

If the sensor stops sending readings, the curve is covered by **No signal from the
sensor**. The curve keeps a gap for the missing time; nothing is filled in.
Milestones wait for the signal to return; settings remain available.

If Bluetooth is not allowed for the app, the link pill turns red, **Bluetooth not allowed**, and a
card over the curve says so. **Android settings** opens the app's page in Android's settings:
allow **Nearby devices**, come back, and the roaster and the accessories connect. Allowing it
when Android asks again also clears the warning.

If the tablet itself falls behind (more than 2 s without a reading taken), the link pill turns
peach with a clock, **tablet late** and the gap in seconds, for 30 s. The curve keeps the gap.
The roast summary counts these moments under **Tablet late**; it usually means Android paused
the app: check that its battery use is unrestricted (see [First setup](#first-setup)).

If Android closes the app during a roast, the next start shows that roast again
with **This roast was interrupted**. It can be saved, but it cannot be continued.

## After the roast

When the roast ends, a summary shows the total time, first crack, development and
drop temperature. With a real roaster, it also shows **Energy**: the roast's kWh, Charge to
Drop, the kWh per kg of green and whether it was measured or estimated. Touch it for the energy
sheet: the total since Start (*Known consumption* when an expected source gave nothing), the
power of the roaster and of the extractor over the session with Charge and Drop (a dotted line is
an estimate), the energy of the preheat, the roast and the cooling, and one line per source.
Touching outside closes it. **Save roast** saves it as a TilauScope roast file (`.alog`) and
opens Android's share sheet: send it to your computer by Drive, mail or a nearby
device, then open it in TilauScope on the desktop like any other roast — curve,
milestones, settings, weights, colours, room conditions and the extractor and
probe curves. A roast from the simulated roaster is marked as simulated, so the
desktop never learns from it. **New roast** starts a fresh session. If the roast is not saved
yet, a touch on New roast asks to save it first and **Save, then new roast** does both;
holding New roast for 5 seconds skips the save and the roast is discarded.

The existing desktop phone-piloting workflow remains separate and still requires
a running computer. Recording from the real roaster and the accessories belongs to
later development milestones.
