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

* The **green beans catalogue is now a readable list** — each bean on three compact lines with stock, origin and freshness badges (blend, harvest age), a live **search** field and an **"In stock"** filter, replacing the old 28-column table.
* The **bean sheet is now read-first**: a clear presentation in zones (Essentials with stat tiles, Provenance, Characteristics, Sensory, Sacks) where each zone has its own **✎ Edit** dialog — including live **scale capture** on the stock field and the Flavor Wheel for tasting notes. The **Add** button opens a full expert form with required-field guidance.
* New **"New sack" assistant** guides you step by step when a bag of green coffee arrives: register a brand-new bean, **restock** an existing one, or start a fresh sheet for a **new crop year** — with a final review screen before anything is saved.
* The assistant can **pre-fill the whole bean sheet from a supplier web page** (AI): paste the URL, review, done. Blends are detected and their component ratios filled in automatically.
* New **sack labels**: print small QR-coded ID labels (single or in batches) for your physical bags, and attach them to a bean. When a bag is emptied its label is **released and recycled** — freed and already-printed labels are offered first the next time you register a sack. Labelling stays entirely **optional**.
* A **"Sack labels" tool** (File Management tab) handles batch printing, reprints, and the pool of free labels — including re-registering labels you printed before.
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
