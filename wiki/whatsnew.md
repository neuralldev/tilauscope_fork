# TilauScope 4.2

This release turns the roasting window into the application itself — TilauScope now draws your roast with its own curve — and rewrites how the roast plan reasons about heat.

## 🖥️ TilauScope is now its own application

* **The application opens directly in the TilauScope roasting window**, not on the Artisan canvas.
* **TilauScope draws the roast itself.** The curve is no longer borrowed from Artisan: it keeps a fixed frame so two roasts can be compared without either being stretched, and switches to a charge-to-drop view once the roast has an end. The coach card, the preheat monitor, the countdown to the next milestone and the milestone forecast marker come with it. Artisan's own graph stops being drawn while the roasting window is up, which is most of what a sampling second used to cost.
* **The roast being shown is named above the curve** — batch number and title, exactly as it is filed. The time axis names every minute, the curves take their colours from the readouts beside them (one colour per probe, the rate always the quieter of the two), and **air temperature can be traced alongside the bean** from the curve's right-click menu.
* **The lever strips are drawn live**, through the preheat and the roast, each carrying its current level in figures — a lever held at zero no longer looks like an empty strip.
* **A compact two-line header** carries the monitoring and roast controls with readable state labels, and **machine controls use colour-segmented sliders** with more forgiving step buttons; clicking the percentage still opens the value roller.
* **An emergency heat cut works in one gesture.** Hold it one second: every automation stops, the burner goes to zero, airflow and extraction open, the drum keeps turning and the panel asks you to empty it.
* While a simulation runs, an **x1 / x2 / x8 selector** at the top right of the curve sets the replay speed.
* **Event buttons and alarms can now drive the graph view** — zoom, pan, center, clamp, follow mode, home, back and forward.
* The main window carries a **TilauScope title bar** in the Catppuccin theme, extended to the menu bar, dropdown menus, tooltips and scrollbars.
* macOS identifies TilauScope as itself rather than borrowing Artisan's identity, so the two no longer compete over which one opens a roast file, and links back to a roast from an exported report open the right application.
* Starting TilauScope while a copy is already running now **says so and closes the copy you just started**, instead of quietly opening a second window that competed with the first for the meter, the Bluetooth devices and the bean database.

## 🔥 The roast plan now reasons about the bean, not just the curve

* **The plan is built the other way round on a radiant electric roaster.** Phase durations used to come from a style table, and the rates of rise were whatever those durations happened to imply — the two never had to agree. The rate-of-rise envelope is now the input — 16°C/min leaving the turning point, 12 entering Maillard, 8 a minute before first crack, 5-6 entering it — and the durations are what that envelope costs. A batch with further to climb takes longer on its own, with no rule written for it: 250 g dries in 3:50 and 400 g in 5:40, where every batch used to be given the same 4:59.
* **The burner is held to what the coffee needs, not to a grid.** Maillard reactions absorb heat: cutting the burner there does not slow the roast down gently, it starves the reaction while bean temperature keeps climbing on the drum's own heat. The plan works out that demand from the batch itself — its process first, then variety and origin, then density, moisture, water activity and the room the machine is breathing — and keeps the heat above it for the whole phase. Washed coffees are held highest and longest; naturals and fermented lots, whose sugars are already part-broken-down, are released earlier.
* **The plan never asks for a burner setting the machine cannot sustain the roast with.** On the Skywalker V2 that floor is 45% — below it the element still heats but the rate of rise gives way. The old "below 45% no longer sustains" warning is gone with it: the plan stops going there instead of warning you afterwards.
* **Development is planned on the window a radiant machine actually needs** — 0:45 to 1:00 for a light roast, about 1:30 for a medium light one, where the plan used to ask for up to 1:42. The minute given back goes into Maillard, where the sugars have longer to develop. The development setting is reached after first crack, never before it.
* **The drop temperature is worked out from the slope leaving first crack** instead of read off a colour table. On 92 recorded Skywalker roasts, drop lands 11.4°C above first crack; the plan used to ask for 22.
* **The turning point follows the batch size**, which is what actually decides it — charge half a drum and the temperature dives some 25°C less far. The drying rate of rise follows: a 250 g plan asked for 14°C/min where roasts of that size really run at 10.
* **The airflow has its own column on the Skywalker V2** — 35% drying, 45% Maillard, 50% development — and climbs one machine notch at a time as dry end approaches instead of jumping in a single move. Air on this roaster supports the reaction; what strips heat from the drum is the extractor, not the intake fan.
* **The exported alarm programme now arms all three control ramps**, not only the burner. The airflow opening through Maillard and the whole development ramp were computed, printed and shown by the assistant, but never fired on the machine.
* **Bean humidity and water activity are no longer treated as one measurement taken twice.** Humidity is how much water there is, so it owns the energy side — drying time, burner, charge temperature, push through first crack, Maillard length. Water activity is how freely that water leaves, so it owns the airflow. A missing one is never guessed from the other.
* **Density now sets the charge temperature and the initial power.** A washed coffee at 800 g/l charges at 192°C, at 600 g/l at 178, where every plan used to start from the middle of a 10°C process band and could never charge more than 5°C above reference.
* **The burner you start on is learned from roasts of the same process at the same batch size**, whatever the coffee was — three or four roasts instead of one or two, and a far better answer to how this machine heats. Maillard and development stay learned from the coffee, because those follow the colour you are aiming for.
* **Small batches are learned from like any other roast again.** The plan used to discard every roast under 270 g on the assumption the bean probe had lost contact; loading with the rear of the roaster slightly raised keeps the bed forward and the probe immersed.
* A coffee whose roasts recorded no slider movements — driven on the PID, or with event logging off — **no longer falls back to a pure grid plan**: first crack, phase timings and the drop are learned from them, and the plan reports partial history rather than claiming full support.
* **The plan says when a roast is not achievable** instead of printing numbers that cannot be held: when the rate of rise would have to climb through Maillard rather than fall, when it would have to collapse before first crack, when the burner would have to come down faster than you can see what you are doing, or when a drying setting would push the turning point later than printed. In each case it names the setup that caused it and stops there.
* **Phase durations follow standard practice**: drying is about half the roast, development is the professional duration for the target level, Maillard is the balance — and Maillard is never longer than drying. The development ratio is reported as a consequence rather than targeted.

## 🌡️ Preheating and TilauPID

* The roast graph shows a **Preheat panel** while TilauPID heats the machine — setpoint, the temperature being steered on, the gap left, rate of rise, applied power and time remaining — turning to *Ready to charge* once the band is reached, then giving way once the drum is at temperature.
* **The chart shows when the drum is due to reach its target**, as a short tick on the target line itself, as soon as the arrival is close enough to be in view.
* **A preheat PID ON/OFF selector sits in the graph toolbar** and mirrors the live state; choosing OFF stops preheating control at once. The setpoint follows the charge temperature of the selected roast plan.
* The preheat annotation shows **how much TilauPID has learned for that setpoint**.
* **TilauPID settles onto the target instead of switching around it.** It anticipates the temperature still to come, varies its learned holding power continuously between setpoints, and applies a deliberately slow final trim only once the machine is genuinely stable.
* **Preheating learning is safer.** Invalid, frozen or missing probe readings cut the heater and cannot train the controller. An optional offline thermal model must first predict three complete real preheats successfully in shadow — with no authority over the heater — before it may contribute a bounded starting estimate.
* The PID learns from **more of your archive** when recent usable preheats are scarce, and spends its reading budget only on roasts that can teach it something.

## 🫘 BeanCave

* **🌱 New crop** starts the next harvest of the coffee selected. Origin, farm, process, variety, altitude and blend are inherited and shown for checking; only the new year, the weight received and the supplier are asked, and the name stays the same — the harvest year is what tells the two records apart. Density, humidity and water activity start **empty**, with the previous crop's figure shown beside each field for reference only: a stale figure carried over silently is indistinguishable from a fresh one, and the roast plan cannot tell them apart either. Water activity can be read straight from an AquaGauge, and the weight from the scale. An optional *This crop replaces the previous one* sets the old bag's stock to zero.
* **Density, humidity and water activity read back what the figure means**, in plain words after the value — *790 g/l (dense)*, *12.4 % (moist)*, *0.54 (typical)* — amber outside the usual range, red when a water activity is high enough to be a storage risk. The bands are the ones the roast plan and the coach already use, so a value can never read *normal* in one place and be flagged in the other.
* **The coach judges a roast against the same fundamentals as the plan.** Weight loss, DTR, drop temperature and phase durations now use the same 8 roast-level categories and target ranges; crash and flick warnings use the same peak detection the plan uses on your history; and when several roasts are compared, each is judged against its own roast-level target rather than one fixed figure for the whole group.
* The **File Management** tab is gone: *Update Roast Counts* moved into *Roast Profile Maintenance…*, and the duplicated or unused entries beside it were removed. The unused green-bean *Volume* field is gone too — density already carries what it meant.

## 📡 MQTT

* **MQTT sensors are managed in Configuration ▸ INTEGRATIONS**, under the broker they belong to, edited in place. Each sensor declares the unit it publishes in, and temperatures are converted on arrival into the unit the session is working in.
* TilauScope can now **ask a gateway for a reading** instead of waiting for one — a plug reporting once a minute no longer leaves its channel empty for most of the roast. Brokers can be reached over **TLS**, and sensors keep reporting after a connection drops and comes back.

## ⏰ Alarms and roast files

* **Alarm programmes can be saved under a name and reloaded** from a *Presets* menu, with rename and delete, replacing the old fixed-slot Alarm Sets tab. Reopening the editor mid-roast marks which alarms have already fired, with the time, refreshed live.
* **A roast file records one of three plan-learning states** — *Admitted*, *Not reviewed* or *Excluded* — instead of a single on/off switch that could only say "excluded". The verdict now sits at the top of the editing panel, and survives opening and re-saving the profile in Artisan.
* ***Repair ALogs* opens on its full list at once** — 0.03 s on a 97-roast folder, where it used to read every profile whole and take three to five seconds every time. On a very large or network folder it fills the list as it reads, with a progress bar and **Cancel**.

## ⏱️ Speed

* **The roast folder is indexed once and kept current**, instead of being read in full by every screen that needs it. The index updates on its own when a roast is saved and is rebuilt when the roast folder changes.
* Typing a weight or a temperature in the roast setup **no longer freezes the window** — every keystroke used to rebuild the plan from nothing and re-read the whole roast folder.
* The plan built at the start of a roast **reads only the roasts that can inform it** — same bean, or same process and batch size.
* The maintenance window opens straight away instead of spending 20 to 30 seconds reading every roast on file.

## 🎨 One look, and clearer progress

* **Every long operation reports itself the same way.** A turning ring means the app is busy without knowing for how long, a filling ring or bar means the end is known and says *47 of 312* rather than a bare percentage, green with a tick means finished, red means stopped — with the text saying what to do and staying until it is read. Indicators in a corner leave the window usable; only work that must not be interrupted holds the screen, and the app never opens a window of its own accord while the drum is turning.
* **Label printing reports in that same pill**, and a run of several labels can be stopped from it — **✕** ends the run after the label currently coming out of the head, and only the labels actually printed count against the roll. A successful print no longer opens a window to say so; the only message that still interrupts is the roll running low.
* If the computer is set to **reduce motion**, nothing turns any more — the indicators breathe gently instead. Nothing to configure, on macOS and Windows alike.
* **Every TilauScope window now draws from one shared set of colours and styles** — 47 of them, from the roast preparation window to the configuration window, BeanCave, the alarm editor and the wizards. Tooltips look the same wherever they come from, secondary text is a touch lighter and easier to read, and *Delete* keeps its red outline instead of turning into a solid red block. The colours that identify a measurement rather than a state — the BT, ET, RoR, heater and setpoint chips, the curve colours — deliberately keep their own values.
* **Configuration → GENERAL → Diagnostics** gains **Check progress indicators…**, a window showing every indicator the application uses so their drawing and animation can be confirmed on a given screen. It changes no setting and starts no real work.

## 🏷️ End of roast, labels and brewing

* The end-of-roast form can **print the roast label as a PDF on the spot**, from the weight and colour just entered, and asks once before closing if you have not printed one.
* **The post-roast result window is laid out in two columns** — 940 by about 620, where it was 600 by 861 and 141 px too tall for a 1366×768 laptop, which pushed *Save roast* off the screen. Nothing was removed: the fields to fill are on the left, the notes on the right, and the middle scrolls on a shorter screen while the title and the buttons stay put.
* A curve snapshot now opens as soon as it is saved, like the roast card already did.
* A new espresso style, ***Modern (high-flow basket)***, joins Classic and Turbo — a fixed 3 s bloom then 7 s soak, followed by a fast 9-bar pull of 10-20 s. It targets medium-light roasts and lighter; darker roasts, or a machine with no pre-infusion, fall back to Classic timing with a note explaining why.

## 🌍 Translations

* German, Spanish, Italian, Simplified and Traditional Chinese are **complete again** — the sack, storage and new-crop screens added some 113 labels each, which were showing in English inside an otherwise translated interface.

---

# TilauScope 4.1

A major update that makes TilauScope easier for beginners while providing more powerful tools to explore and improve your roasts. Here's what's new.

## ☕ Roasting Assistant
* The roast plan now **anticipates heat reductions before first crack**: power decreases are staged throughout the Maillard phase and triggered using bean temperature (earlier on high-thermal-mass roasters), preventing first crack from "crushing" the curve because the reduction happened too late.
* During development, the **DROP countdown** now accounts for the natural slowing of the roast curve (no more overly optimistic estimates) and displays the **projected final DTR**. You always know where your roast is expected to finish, not just where it is now.
* The plan's **historical references** (master curve and crash/flick alerts) now use only your previous roasts of the **exact same bean** (BeanCave identity) and with a **comparable batch size**, eliminating misleading reference curves caused by comparing 250 g batches with 450 g batches.
* **First crack temperature is now learned from your own roasting history**. From the second roast of a bean onward, the plan uses the actual first crack temperature measured on your machine instead of a theoretical value. Heat ramps, planned curve, and drop targets are automatically adjusted. The PDF report indicates whether the value comes from your history or the reference database.
* **Automatic heat reductions are now announced.** During Maillard, the assistant displays the next scheduled step (for example, *"Next 48% @170°C"*), so the power slider no longer moves unexpectedly. If drying is projected to take significantly longer than planned for that bean, the coach warns you before the profile becomes flat.
* **You always know how you're tracking against the plan.** During Drying and Maillard, the assistant displays your lead or delay relative to the planned curve (for example, *"Plan +0:15"*) and evaluates your RoR against the expected slope **at that exact point on the curve**, eliminating misleading "above plan" messages early in Maillard.
* **The roast plan continuously self-calibrates.** Expected Drying and Maillard durations are now based on your measured roasts of the same bean while remaining within professional roasting guidelines. If a bean consistently dries or browns too slowly or too quickly, TilauScope automatically adjusts the phase heat profile (within safe limits, from the third roast onward) and explains the reason in the action notes.
* Two experience levels are available: **Guided** and **Expert**. In Guided mode, the assistant automatically opens, starts, and closes with the START/STOP button, letting you focus on roasting instead of the interface.
* The assistant can be **docked** in place of the main panel or **detached** into a floating window.
* The bean list now displays only beans that are **actually in stock**.
* **AirWave** airflow recommendations are adapted to each roast phase, with alerts when airflow begins cooling the drum.
* At the end of each roast, a **"Actual Curve vs Plan"** summary shows, phase by phase, whether the roast ran hotter or cooler than planned.
* In Guided mode, a small button at the top right of the graph lets you switch between a simplified **Coach View** (one key recommendation plus a phase verdict) and the complete **Expert View**, avoiding information overload.

## 📊 BeanCave & Roast Viewer

* **Scan a label, open the record.** Roast and green-bean labels now carry a QR code you can scan two ways: the new **📷 SCAN** button in BeanCave opens a webcam scanner (the camera runs only while the window is open) and shows a **roast card** — curve with key events, weights and loss, Agtron, DTR, tasting notes, and a link to the source bean sheet; or point your **phone's camera** at the label and the record page opens right in the phone browser (TilauScope running on the same Wi-Fi network, address `tilauscope.local`).
* The **green beans catalogue is now a readable list** — each bean on three compact lines with stock, origin and freshness badges (blend, harvest age), a live **search** field and an **"In stock"** filter, replacing the old 28-column table.
* The **bean sheet is now read-first**: a clear presentation in zones (Essentials with stat tiles, Provenance, Characteristics, Sensory, Sacks) where each zone has its own **✎ Edit** dialog — including live **scale capture** on the stock field and the Flavor Wheel for tasting notes. The **Add** button opens a full expert form with required-field guidance.
* New **"New sack" assistant** guides you step by step when a bag of green coffee arrives: register a brand-new bean, **restock** an existing one, or start a fresh sheet for a **new crop year** — with a final review screen before anything is saved.
* The assistant can **pre-fill the whole bean sheet from a supplier web page** (AI): paste the URL, review, done. Blends are detected and their component ratios filled in automatically.
* New **sack labels**: print small QR-coded ID labels (single or in batches) for your physical bags, and attach them to a bean. When a bag is emptied its label is **released and recycled** — freed and already-printed labels are offered first the next time you register a sack. Labelling stays entirely **optional**.
* A **"Sack labels" tool** (Stockage tab) handles batch printing, reprints, and the pool of free labels — including re-registering labels you printed before.
* **Labels are now managed where you watch your stock.** The Stockage tab's bean fiche lets you attach a label and take it back: the labels available to you are offered directly — recycled ones first with the date they were freed, then those you printed and never used. You pick from that list rather than typing a number, so a bag can never carry an ID the app has no record of; a label printed elsewhere is registered once from the sack labels tool and joins the list. When a bean's stock reaches zero, TilauScope offers to **give its labels back to the pool**, and a banner reports any label still held by an out-of-stock bean so old ones can be recovered in one pass. A setup that never labels its bags sees none of this.
* New **"Stockage" tab** watches how your green coffee keeps. Each bean in stock shows its **water activity (aw)** colour-coded into a conservation zone (too dry / optimal / to watch / mould risk), most-at-risk first. Set how each bean is **conditioned** (vacuum, GrainPro, Ecotact, sealed jar, open bag), and if you place a humidity sensor in your storage room (read over MQTT), TilauScope tells you whether each bean is **gaining moisture, drying out or stable** — sealed bags are correctly left out since they barely exchange with the room. Measure a bean's aw with the AquaGauge right from its fiche.
* New **"Data"** button opens a dedicated window for exploring roast milestones, events, and measurements, with easy navigation between milestones.
* Completely redesigned **multi-roast comparison**. Each roast has its own color and three visualization modes:

  * **Overlay**
  * **Consistency** (min/max band to visualize repeatability)
  * **Aligned** (aligns roast milestones to compare curve shapes)
* New **phase balance banner** (Drying / Maillard / Development) with a **plain-language analysis** of your batch consistency.
* The **Coach** now adapts its recommendations to your target roast level (light, medium, or dark) instead of relying on a single generic reference.
* **Bean density measurement** is now assisted by a connected scale.
* The **Roasting plan** tab is now a guided **3-step flow** (Bean → Conditions → Target). A progress header lights up as you fill each step, ambient readings sit in compact tiles with **"Fill from online weather"** right where it belongs, batch weight has its own field, and the advanced probe-offset settings stay tucked away until you need them.
* New **"Repair ALog"** tool restores incomplete roast profiles.

## 🫖 Brew Advisor — New

* Brewing recipes for **seven brewing methods** (Espresso, V60, French Press, AeroPress, Moka, and more), automatically adjusted for roast level, coffee dose, and bean freshness.
* **Degassing / resting recommendations** based on roast level, with lighter roasts requiring longer resting periods.
* Water recommendations based on the correct **GH / KH** hardness parameters instead of a simple "hard" or "soft" classification.
* **Machine-specific espresso profiles**, with optional **AI-assisted fine tuning**.
* A **Brew Planning timeline** shows all your roasts on a calendar of their resting windows: each bar glows brightest on the **best day to drink**, then fades into a "drink soon" tail. Switch the **Filter / Espresso** target to shift every window, and click **☕ Brew this coffee** on any roast to jump straight into the Brew Advisor already loaded with it.

### Did that change actually do anything?

Dialling in a coffee usually means changing the grind, tasting again, and *assuming* the change did something. TilauScope now checks.

* **A « previous attempt » panel compares your last two brews** of that coffee on that method: the grind you moved, the flow it produced, and whether the bed really responded. When a step changed nothing, it says so plainly and lists what it can come from — play on that step of your grinder, a different dose or pour, a bean still degassing. It never picks your next setting for you: that call stays yours.
* **It measures the part of the time your grind actually controls.** On a pour-over, the total time is mostly *your* pour schedule — two identical grinds give different times if you pour differently. Only the final drain reflects the coffee bed, so that is what TilauScope now reads off the weight curve. On espresso the pump is fixed and the shot time is already that measurement. When no scale was connected, it says the flow was not measured rather than showing you a number that means nothing.
* **Every tasted brew is kept**, in its own journal beside your bean library, so the picture builds up as you brew. Nothing is read back into your recipes automatically — this is evidence for you to judge, not a machine correcting itself.

### Espresso

* **The ratio now follows the roast.** It was the only ratio in the advisor that never moved, sitting at 1:2 for everything, while filter ratios have always tracked the roast. A light roast is dense and poorly soluble and needs a long shot to reach a decent yield; a dark roast is very soluble and releases its bitterness early, so it is cut short. The advisor now runs from **1:3.0 on a very light roast down to 1:1.5 on a dark one**, and the shot time follows (42 s to 19 s) — because at a given dose and grind the bed sets the flow, so a longer ratio is paid for in time. The reference shot is untouched: a medium-light roast still reads 1:2.0 in 28 s.
* **New « Style » selector.** *Classic long* keeps the grind the roast asks for and lets the shot run as long as the ratio needs. *Turbo* fixes the shot around 25 s and opens the grind to get the flow — with a warning, because it needs a machine that holds its pressure, otherwise the shot reads sour rather than fast. Your choice is remembered.
* **A dialled-in espresso reopens on the dose it was dialled on.** On a pressure brewer the dose is not a preference — the basket sets it — so starting from the method default silently changed the puck the whole dial-in was made for. Filter methods still open on their default, where the dose is your free choice of cup size.
* **Pre-infusion is now described as the two gestures it really is.** On a paddle or lever machine, water first flows in until the puck is saturated, then the flow stops and the puck sits while pressure equalises. Those are two different things, and the plan reported them as one number — leaving you to guess when your hand should move. It now reads *« paddle to pre-infusion: water fills the puck, ~3 s »*, then *« hold there — nothing flows, ~5 s »*, then when to open fully, with lever wording on an E61. The wetting follows your dose, since a deeper basket takes longer to soak; a bean still degassing lengthens the hold rather than the fill, because what it needs is to sit. Machines that run their own pre-infusion keep a single line: there is no gesture to decompose.
* **You can record a shot without an Acaia.** Machines with a scale built into the drip tray — a La Marzocco Mini and its kind — leave no room for one under the cup, which put the whole feedback loop out of reach: no debrief, no time-aware diagnosis, nothing kept. Type the shot time and the weight in the cup and everything behaves as after a live brew. Offered on espresso only, where the shot time *is* the coffee bed; on a pour-over the total time is mostly your own pour schedule, so a typed number there would tell you nothing.
* **Auto-stop is now offered on espresso only**, where it is armed by default. On a pour-over or an immersion the scale weighs the whole assembly, so it reached the target at the end of the last pour — before the bed had finished draining — and cut the brew short. Soft methods now end when you decide it has stopped dripping.

### Smaller things you'll notice

* **Your saved dial-ins now show their age** — « today », « 6 d », « 2 mo ». Hovering gives the exact date, and past three months it adds a caution: that setting was dialled on a different roast of the bean, and the green has aged since. Taste before trusting it.
* **Water activity is judged in one place.** The Storage tab owns the aw doctrine, so brewing advice now reads the same zones — including any thresholds you set yourself. A bean could previously read « optimal » in Storage and « high moisture » in the advisor at the same value.
* **Reporting a taste now starts from a clean slate each cup.** Your previous report stayed ticked, so a second fault was diagnosed alongside the one you had already fixed.

## 🔥 Preheating & Control

* New **progressive preheating algorithm** that gradually slows heating as the target temperature is approached, while automatically adapting holding power to room conditions and your roasting history.
* Select the control sensor (**BT or ET**) directly from the roast settings.
* A new **automation banner** clearly indicates when the roast is being controlled by an automation process.

## ⏰ Alarms

* New **sentence-based alarm editor** where every alarm reads like a clear sentence, can be grouped by roast phase, and reordered using drag-and-drop.
* New **visual alarm timeline** and **AI-powered consistency audit**.

## 🧰 Preparation & Quality of Life

* New **Insights** tab in the settings window provides an estimated roast outcome before you even start roasting.
* **Batch tracking** follows each roast from preparation through the final result.
* Optional automatic detection of **Dry End** and **First Crack**.
* All TilauScope tools are now grouped into a dedicated menu, the configuration window has been reorganized, and the label printer has been made more reliable.

---

💡 **Tip:** You can switch between **Guided** and **Expert** modes at any time from the assistant header.
