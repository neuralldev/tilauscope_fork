# TilauScope 4.2

This release rewrites how the roast plan reasons about heat, and finishes turning TilauScope into an application of its own.

## 🔥 The roast plan now reasons about the bean, not just the curve

* **The burner is held to what the coffee needs, not to a grid.** Maillard reactions absorb heat: cutting the burner there does not slow the roast down gently, it starves the reaction while bean temperature keeps climbing on the drum's own heat. The plan now works out that demand from the batch itself — its process first, then variety and origin, then density, moisture, water activity and the room the machine is breathing — and keeps the heat above it for the whole phase. Washed coffees are held highest and longest; naturals and fermented lots, whose sugars are already part-broken-down, are released earlier.
* **The development setting is reached after first crack, never before it.** The plan used to ask for it a full minute early, which is the classic way to produce a flat, bread-like cup while the curve still looks perfectly correct.
* **The plan replays your own hand before dry end.** When your past roasts of a coffee show you bringing the burner down during drying to put a flattening rate of rise back on a slope, the plan now schedules that descent — starting as early as you actually start, in steps the size of yours, landing on the value you actually land on. A coffee you have never had to correct keeps its charge setting straight through drying.
* **The plan says when a roast is not achievable** instead of printing numbers that cannot be held: when the rate of rise would have to climb through Maillard rather than fall, when it would have to collapse before first crack, or when the burner would have to come down faster than you can see what you are doing. In each case it names the setup that caused it and stops there — a chain reaction is not recovered mid-roast, and the answer belongs to the next roast.
* **Charge temperature is set by the process** — washed, natural, decaf — rather than by the target roast level, and small batches now charge at the same temperature as any other.
* **Phase durations follow standard practice**: drying is about half the roast, development is the professional duration for the target level, Maillard is the balance. Drying is never planned under 4:30 nor Maillard under 3:00; below that the roast is not reachable on a drum of this size. The development ratio is now reported as a consequence rather than targeted.
* **The plan states the rate of rise it expects to arrive at first crack with**, not only the Maillard average — an average says nothing about where the roast lands, and the landing is what sets first crack.
* Planned burner power now respects each machine's own safe ceiling, and never plans below the point where the burner stops being a usable lever.

## 🖥️ TilauScope is now its own application

* The main window carries a **TilauScope title bar** in the Catppuccin theme, extended to the menu bar, dropdown menus, tooltips and scrollbars.
* macOS identifies TilauScope as itself rather than borrowing Artisan's identity, so the two no longer compete over which one opens a roast file, and links back to a roast from an exported report open the right application.
* Starting TilauScope while a copy is already running now **says so and closes the copy you just started**, instead of quietly opening a second window that competed with the first for the meter, the Bluetooth devices and the bean database.

## 📡 MQTT and preheating

* **MQTT sensors are managed in Configuration ▸ INTEGRATIONS**, under the broker they belong to, edited in place. Each sensor declares the unit it publishes in, and temperatures are converted on arrival into the unit the session is working in.
* TilauScope can now **ask a gateway for a reading** instead of waiting for one — a plug reporting once a minute no longer leaves its channel empty for most of the roast. Brokers can be reached over **TLS**, and sensors keep reporting after a connection drops and comes back.
* The roast graph shows a **Preheat panel** while TilauPID heats the machine — setpoint, the temperature being steered on, the gap left, rate of rise, applied power and time remaining — turning to *Ready to charge* once the band is reached.

## 🏷️ End of roast and labels

* The end-of-roast form can **print the roast label as a PDF on the spot**, from the weight and colour just entered, and asks once before closing if you have not printed one.
* A curve snapshot now opens as soon as it is saved, like the roast card already did.

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
* Three experience levels are available: **Guided**, **Standard**, and **Expert**. In Guided mode, the assistant automatically opens, starts, and closes with the START/STOP button, letting you focus on roasting instead of the interface.
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

💡 **Tip:** You can switch between **Guided**, **Standard**, and **Expert** modes at any time from the assistant header.
