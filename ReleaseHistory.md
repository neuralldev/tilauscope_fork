## [4.1.0] 2026-07-14
build 39
* ⚡ [feat(packaging)] : a release built locally is now announced publicly like an automated one — once the installer is uploaded, the download page and the release notes are published without any manual step
* ⚡ [feat(packaging)] : the local macOS build can now sign and notarize the DMG like the automated release does — set CODESIGN_IDENTITY (plus the Apple API key variables) before running build-tilauscope-macos.sh and it produces a DMG that opens without the security warning; without them the build is unchanged
* 🐛 [fix(packaging)] : the generated protobuf modules (src/proto) were excluded from the repository by a stray ignore rule, so every packaged build shipped without them — the Ikawa roaster support was broken in the installers. They are now part of the build for both macOS and Windows
* 🐛 [fix(beancave)] : the Roast Viewer no longer sticks the roast day at the end of the bean name — "Yellow Caturra Natural Dry Process **13**", "… Fermentation **23**". The date stamp in the filename was being trimmed one digit short, leaving the day glued to the name, which also meant two roasts of the same bean never looked like the same bean
* 🐛 [fix(beancave)] : in the Roast Viewer, the roasts of a given bean are now really listed newest first. The list was meant to sort by bean then by date, but the date part did nothing until the roast profiles had been re-indexed — until then the files stayed in raw disk order, which is why several roasts of the same bean looked shuffled. The date is now read from the filename as well, so the order holds from the moment the window opens
* ⚡ [feat(beancave)] : the Roast Viewer now shows the roast date in brackets after the bean name — "Yellow Caturra Natural Dry Process 2024 [2026/05/13 18:47]"
* 🐛 [fix(artisan)] : curve smoothing works again after the latest Artisan update moved it out of the graph module — the Bean Cave roast list, the roast plan and Artisan's own profile comparator all failed with "no attribute 'smooth_list'" when reading a roast file
* 🐛 [fix(brew)] : accepting a taste correction in the dial-in now tells you it worked. "Apply to next brew" had no hover and no pressed state, and confirmed itself with a tiny "Saved ✓" after clearing the verdict that justified it — so a correction that was in fact applied and written to the bean looked like a click that did nothing. The button now reacts to the mouse, and the confirmation names the bean and restates the change (Grind 702 → 744 µm · Temp 90 → 89 °C)
* ⚡ [feat(artisan)] : fetch latest updates from artisan
* 🐛 [fix(remote)] : quitting TilauScope can no longer hang while the remote-control server shuts down — the shutdown is now capped at a couple of seconds
* 🐛 [fix(remote)] : the paired-phones store is now hardened against a rare timing overlap — pairing a phone at the exact moment you rename or revoke another one can no longer drop the change
* 🐛 [fix(remote)] : the live phone feed is now sturdier under load — an update in flight can no longer be discarded early, so frames aren't silently lost
* 🐛 [fix(remote)] : the live phone feed is now steadier when a phone reads slowly — updates to a given phone are sent one at a time instead of possibly overlapping, which could drop a frame or garble the connection under a bad wifi link
* 🐛 [fix(remote)] : an iPad now shows up as "iPad" in the paired-phones list instead of "Mac" (iPads report themselves as a desktop Mac, so they were mislabelled)
* 🐛 [fix(remote)] : renaming a phone while the pairing screen is open now updates the list right away instead of only after you reopen it
* 🐛 [fix(remote)] : the pairing QR code now visibly dims when its code expires (it never actually greyed out before, only the countdown text changed)
* ⚡ [feat(remote)] : you can now rename a paired phone yourself — a pencil next to each phone in the pairing screen turns its name into an editable field (Enter to save), so a device the automatic naming couldn't identify can be given a name like "Kitchen phone"
* ⚡ [feat(remote)] : a paired phone is now labelled by what it actually is — "iPhone · Safari", "iPad · Safari", "Android · Chrome" — instead of a generic "Web", with a short code to tell two identical phones apart. The name is worked out automatically when the phone pairs (re-pair an older phone to give it the new label)
* 🐛 [fix(remote)] : a phone that scans the pairing QR code now actually shows up in the "Paired phones" list. The list only ever refreshed when the pairing screen was first opened, and the phone's token was written on a background thread the screen couldn't yet see, so a freshly paired phone stayed invisible. The list now updates on its own the moment a phone pairs, and revoking still works immediately
* ⚡ [feat(remote)] : remote control is now gated by pairing — Settings ▸ Remote control ▸ "Pair a phone…" opens a pairing screen with a QR code (and link) to scan on the phone, the list of paired phones, and a Revoke button for each. Once paired a phone reconnects on its own; unpaired devices are refused. Home-network tool — the link is unencrypted, so pair only on your own wifi
* ⚡ [feat(remote)] : with remote control on, a connected phone now sees the roast live — bean and environment temperature, rate of rise, current phase and milestones update every second (read-only for now). Nothing is computed or sent while no phone is connected, so an idle roast is unaffected
* ⚡ [feat(remote)] : you can now turn phone remote-control on from the configuration (General tab ▸ "Remote control (phone piloting)"), with its own port — off by default, takes effect after a restart
* ⚡ [feat(remote)] : groundwork for phone remote-control — an opt-in control server (WebSocket, auto-discovered on the local network via Bonjour, with a built-in browser test page) now starts when remote control is enabled in the settings. Disabled by default, no live piloting yet — the phone still only observes
* ⚡ [feat(remote)] : the built-in web server (the target of phone QR-code scans, and the groundwork for the upcoming phone remote-control) now runs for the whole app session instead of only while the Bean Cave window is open — it starts with TilauScope/Artisan and stops when you quit, so it no longer depends on having opened the Bean Cave first
* 🐛 [fix(beancave)] : what you record in "Roast finished!" is now actually written back into the roast file. The form filled Artisan's live roast in memory but never saved it, so the roasted weight, colours, batch number and notes were lost as soon as you moved on — the Roast Viewer, the Advanced Stats and the roast card all kept showing the values from before your edit. The profile is now saved to the same file on OK, and the viewer, the roast list and the reference statistics refresh immediately (a save failure is now reported instead of passing silently)
* 🐛 [fix(beancave)] : the Advanced Stats now use the ground-coffee Agtron reading when you measured one. They only ever read the whole-bean value, so a roast measured on ground coffee showed "not present" or the wrong roast level, and the light/medium/dark judgement behind the phase advice was based on the wrong number. When both readings exist the card shows them side by side with their delta (ground 62 · whole 54 · Δ 8); roasts measured on whole beans only are unaffected
* 🐛 [fix(tilaupid)] : the preheating status no longer stays stuck on "TilauPID is initializing, please wait..." for the whole preheat. It was waiting for Artisan's own PID to confirm the set-point, but that confirmation only ever arrives when Artisan's PID control is configured — on a slider-driven roaster it never came. The status now reads the target straight from TilauPID, so it switches to "PREHEATING TILAUPID 180 °C" as soon as the preheat really starts
* 🐛 [fix(ui)] : the preheating message no longer shows raw HTML tags — "182 °C&lt;br&gt;&lt;br&gt;PREPARE YOURSELF TO &lt;b&gt;CHARGE&lt;/b&gt;…" now renders as proper lines, and the temperature and its unit stay together instead of the "°C" being pushed alone onto the next line
* 🐛 [fix(controls)] : changing the SV no longer springs back to the previous value. The new value never reached Artisan's own SV slider unless Artisan's PID control was configured, so the periodic resync kept restoring the old one
* 🐛 [fix(controls)] : during a guided preheat the SV row is now disabled, with a tooltip saying it is driven by TilauPID. The set-point shown there is the PID's own target and was rewritten every second, so any change you made appeared to be ignored — it is now visibly read-only until the preheat ends
* ⚡ [feat(ui)] : the slider rows are packed closer together — each row carried about 11 px of padding above and below, spreading the four controls over more height than they needed. The row pitch drops from roughly 58 to 38 px, so the control zone is more compact without shrinking any click target
* 🐛 [fix(ui)] : the SV row is now aligned with the four sliders above it — it was shifted to the left and its + button ran past the right edge of the panel
* 🐛 [fix(ui)] : long status messages in the phase panel now wrap inside the box instead of running past both edges of the window
* ⚡ [feat(controls)] : the SV (set-point) control now behaves like the other sliders — the set-point is sent to the PID only when you let go, not at every intermediate value. Dragging the SV slider from 180 to 200 used to retarget the PID at 181, 182, 183… all the way up; it now sends 200 once. The SV reading follows your gesture live as before
* ⚡ [feat(controls)] : clicking + / − several times in a row on a control now sends a single command to the roaster with the final value instead of one per click. The displayed value still moves instantly at every click, but the app waits 300 ms after your last one before acting — so going from 70% to 75% in five quick taps drives the machine once and leaves one event on the curve instead of five. Applies to the big control cards, the slider steppers, the value roller and the assistant's quick-adjust buttons; dragging a slider still takes effect the instant you release it
* 🐛 [fix(roast)] : the First Crack forecast marker (yellow dashed vertical line + red dot) no longer reappears superimposed on the live curve after you mark FC. It correctly disappears when the bean temperature passes the predicted point, but marking FC made it pop back onto the current position; past FC there is no forward FC forecast, so the marker now stays hidden and only the phase text annotation remains
build 38
* 🐛 [fix(difluid)] : AirWave fan buttons built as "IO Command" events (e.g. `airwave(FAN,30)`, `airwave(FAN,{})` for the ±5% steps) now actually change the fan speed. The command interpreter only understood the `airwave(SET,…)` / `airwave(GET,…)` forms and silently ignored the direct `airwave(<target>,<value>)` form your buttons use, so pressing them did nothing while the fan slider and the "Difluid AirWave Command" mode/power buttons worked. The direct form is now honoured for FAN, MODE, POWER and any other target
* 🐛 [fix(difluid)] : the AirWave can now be controlled again after you stop and restart monitoring within the same session. Previously, the first time you pressed ON the extractor responded to every command, but after an OFF and a second ON it went deaf — fan, power and mode commands all did nothing and only quitting and relaunching the app brought it back. The extractor only accepts commands once it has exchanged a "hostname" handshake, which it normally requests itself on connection; on a quick reconnect it skips that request, so the app kept waiting for a handshake that never came and silently blocked every command. The app now performs the handshake itself — both when the connection is (re)established and, as a safety net, on the first command after reconnecting — so control works on the second, third and every subsequent ON
* 🐛 [fix(insights)] : the app could crash while you were setting up or starting a roast. The pre-roast INSIGHTS panel was building its notes and target plan on a background thread, but that work reaches into shared app state and text-translation machinery that is only safe to touch from the main thread — so it silently corrupted memory and the app fell over at a random moment a little later (often only when you closed the setup window). The insights are now computed on the main thread, guarded by the same brief delay that already waits for you to stop typing, so there is no crash and no visible change beyond a momentary pause while the plan is worked out
* 🐛 [fix(beancave)] : browsing the roast list in the Roast Viewer no longer loses your place when the list refreshes on its own. Every few minutes the app re-indexes your roast files in the background and rebuilds the list; it was clearing the list first and only then trying to remember which roast you had highlighted, so it always came back empty and snapped the selection back to the first roast. It now records the highlighted roast and the scroll position before the rebuild and restores both afterwards, so a background refresh leaves your cursor exactly where it was
* 🐛 [fix(beancave)] : the roast list no longer ends up with two roasts highlighted at once. Because the list allows multi-selection, each time the app programmatically re-selected a roast (at startup and after a background refresh) it was adding to the highlight instead of replacing it, so you could see the first roast and the restored one both selected. Restoring a selection now clears the previous one first
* 🐛 [fix(tilaupid)] : the roast setup only arms the START-time preheat PID when TilauPID is enabled AND a target temperature is set. Enabling TilauPID with an empty target used to arm the START button with a bogus 0° target; now that case leaves the START button untouched so the PID does not fire
* 🐛 [fix(tilaupid)] : the preheat target is now sent as a whole degree (e.g. 200 instead of 200.0) — a preheat set-point to a tenth of a degree makes no sense
* 🐛 [fix(tilaupid)] : reopening the roast setup now correctly restores the TilauPID checkbox and target — it was reading the START command from the wrong action list, so a saved preheat looked disabled every time the dialog was reopened
* ⚡ [feat(tilaupid)] : every guided preheat now stamps the set-point it used directly into the roast file as a dedicated field. This is the robust record the preheat assist reads back — it no longer depends on the on-graph marker surviving or on reverse-engineering the set-point from alarm text. Loading and re-saving a roast keeps the field; a fresh roast that doesn't use the guided preheat carries no field
* ⚡ [feat(tools)] : new `tools/analysis/preheat_alog_repair.py` — backfills the preheat marker into older roasts that were recorded before the marker bug was fixed. It recovers the set-point that was actually used from the roast's stored alarm commands, and only when the drum genuinely reached that temperature before charge, then writes repaired copies to a separate folder (originals are never touched; runs as a dry-run report until you pass an output folder). This turns your pre-fix roasts back into usable learning material for the preheat assist
* 🐛 [fix(tilaupid)] : the guided preheat now actually records its "preheat started" marker in the roast file. It was firing the marker at the very instant recording began — before the first data point existed — so Artisan silently discarded it every single time, and no roast ever carried proof the assist drove its preheat (which in turn meant none could be learned from). The marker is now written on the first reading after START, and the target temperature it stores is encoded correctly so it reads back as the real set-point instead of a ~10× value. Existing roast files are unaffected; new guided preheats will carry the marker
* 🐛 [fix(preheat)] : the preheat assist now learns only from roasts where the guided preheat actually ran. If a past roast has no record that the assist drove the preheat, the drum was brought up to temperature by hand — that roast can't teach the assist how to steer the burner to a target, so it is left out of the learning instead of being reverse-engineered from the warm-up curve. In practice the assist's target and hold-power learning now rest exclusively on genuine guided preheats
* 🐛 [fix(preheat)] : the preheat assist now reads your roast history from the folder you actually configured, not a guessed location. It used to probe a handful of default paths and could latch onto the wrong folder (or the current working directory) that happened to contain stray `.alog` files; it now uses the same configured roast-log directory as the rest of the app, so its learning always looks at your real roasts
* 🐛 [fix(preheat)] : corrected how the preheat assist groups your past roasts and where it reads the hold power. It was filing almost every roast under one target temperature because it read a stored preset button instead of the temperature the drum actually reached — so a library of roasts at 170, 180 and 190 all looked like "180". And it estimated hold power from sparse burner marks whose last reading before charge was often a stale full-power value left over from the warm-up climb, not the gentle heat that actually holds the drum steady. It now groups roasts by the temperature the drum genuinely held at before charge, and reads hold power only from the continuous burner-power log — the one trustworthy source. Most older roasts predate that log, so for those targets the assist keeps its physical opening estimate until enough burner-logged roasts build up, rather than seeding a wrong number
* 🐛 [fix(preheat)] : the preheat assist can finally read your roast history. It learns from past `.alog` files, but a decoding step was tripping over the multi-line notes stored in the bean field and throwing almost every file away — on a 92-roast library only 3 were actually read. And the few it did read were measured wrong: it read "overshoot" and "hold power" across the whole roast — the fire and peak heat of the roast itself — instead of only the warm-up before the beans go in. Both are fixed: the same library now yields 82 usable roasts, and only the genuine pre-charge hold counts, so the assist's learning and its starting guess for each target rest on real preheat data
* ⚡ [feat(preheat)] : the preheat assist now starts already informed by your past roasts instead of from a blank slate. For each target temperature it reads from the continuous burner-power log how much heat the roaster actually needed to simply hold there, and uses that as its opening guess — so an assisted preheat behaves sensibly from the start and improves from there. Only roasts that genuinely reached and held the target, logged their burner power, and were recorded after the burner was recalibrated are used; everything else falls back to a safe physical estimate. Overshoot-anticipation is learned from your own assisted preheats as they accumulate (older roasts never recorded their setpoint, so it can't be read back from them). Running a preheat in the simulator still changes nothing the assist remembers, so you can dry-run it freely
* ⚡ [feat(tools)] : new `tools/analysis/preheat_corpus_report.py` — prints, per target temperature, what your .alog history implies about the preheat: the hold power the drum needed, the typical overshoot, and how fast it rose. Lets you check the assist's starting point against real roasts before trusting it, without opening the app
build 37
* 🐛 [fix(preheat)] : the preheat assist no longer overshoots the target and sits stuck above it. It used to keep the burner partly on even after reaching the set temperature and only slammed off two degrees too high, so the empty drum settled hot and never came back down. It now steers on where the temperature is *heading* — easing the burner off as it closes in and letting the drum fall back to the exact target, learning per set-point how much heat it takes to simply hold there. Set-points learned by the old behaviour are reset once so they can be relearned cleanly; your roast files are untouched
build 36
* 🐛 [fix(beancave)] : the sack label dialogs now follow the same button style as the rest of the Storage tab. They were drawn with a flat filled variant that made every button look like the main action — including Remove, which destroys a label
* ⚡ [feat(beancave)] : sack labels can now be assigned and taken back from the Storage tab itself. Attaching a label used to be possible only while creating a lot in the New sack assistant, and detaching one only from the bean form — so the tab that lists your stock could show a bag's number but never let you touch it. The bean fiche now offers the labels available to you, recycled ones first with the date they were freed, then those you printed and never used. Only labels TilauScope knows about can be picked, so a bag can never end up carrying a number the app has no record of; a label printed elsewhere is registered once from the sack labels tool and then appears here like any other. A bean with no label, on a setup with no label to give, shows nothing at all
* ⚡ [feat(beancave)] : a bean whose stock reaches zero now offers to give its labels back. Until now those numbers stayed attached to a bean that had left the Storage tab, so they never returned to the free pool and could not be found anywhere — you printed new ones instead of reusing what was on the shelf. Emptying a bean now asks, and a banner at the top of the Storage tab reports every label still held by an out-of-stock bean so the ones already lost can be recovered in one pass. Keeping them attached stays possible, and the banner will simply ask again
build 35
* ⚡ [feat(brew_advisor)] : espresso pre-infusion is now described as the two gestures it really is. On a paddle or lever machine, water first flows in until the puck is saturated, then the flow stops and the puck sits while pressure equalises — two different things the plan reported as one number, leaving you to guess when your hand should move. The plan now says « paddle to pre-infusion: water fills the puck, ~3 s », then « hold there — nothing flows, ~5 s », then when to open fully, with lever wording on an E61 or a manual group. The wetting follows your dose (a deeper basket takes longer to soak) and a still-degassing bean lengthens the hold, not the fill. Machines that run their own pre-infusion keep a single line: there is no gesture to decompose. Shot times are unchanged
* 🐛 [fix(brew_advisor)] : on a paddle or lever machine the plan no longer shows both « pre-wet » and the wetting phase at 0:00 — one action was being listed twice, neither with a duration
* ⚡ [feat(brew_advisor)] : you can now enter a shot result by hand when no Acaia can be used. Machines with a scale built into the drip tray — La Marzocco Mini and the like — leave no room for one under the cup, which made the whole feedback loop unreachable: no debrief, no time-aware diagnosis, nothing recorded. Type the shot time and the weight in the cup and everything downstream behaves exactly as after a live brew. Offered on espresso only, and only while no scale is connected; the journal marks the row as hand-entered so a later analysis can tell the two apart
* 🐛 [fix(brew_advisor)] : the brew controls are now resynchronised whenever the recipe changes, not only when a scale connects or disconnects. They depend on the method (only espresso is offered an auto-stop), but the first synchronisation ran before the first recipe existed — and with no scale on the line nothing ever corrected it
* 🐛 [fix(brew_advisor)] : a dose you set by hand on espresso is no longer forgotten when you switch method and come back. Reopening on the dialled-in dose is right when you arrive on a pressure method, but doing it again after you have deliberately typed another one silently undid your change. Your gesture now wins until you accept a new dial-in at that dose
* ⚡ [feat(tools)] : new `tools/analysis/export_brew_log.py` — exports the brew journal to CSV so the grind-to-flow relation can be examined outside the app, one row per extraction plus one per consecutive pair. Brews that cannot fairly be compared are exported with the reason rather than dropped
* ⚡ [feat(brew_advisor)] : TilauScope now tells you whether your last grind change actually did anything. A « previous attempt » panel compares your two most recent brews of that bean and method — the grind you moved, the drain time it produced, and whether the bed really responded. When it did not, it says so plainly and lists what it can come from, without ever picking your next setting for you. It stays quiet until there are two brews to compare, and refuses to compare two brews at doses more than 10 % apart
* ⚡ [feat(brew_advisor)] : accepting a taste correction now also records that extraction in the brew journal — the setting it ran on, the time and drain it produced, and your verdict. This is what will later let TilauScope tell you whether a grind change actually did anything, instead of assuming it did. Nothing is read back yet, and a bean never linked to a roast is simply skipped
* ⚡ [feat(brew_advisor)] : on a pour-over or an immersion, TilauScope now measures how long the bed took to drain after your last pour — the flat tail of the weight curve. It is the only part of the total time your grind actually controls; the rest is your pour schedule. Measured at the end of the brew, from the curve already on screen, and nothing is guessed when no scale was connected
* ⚡ [feat(brew_log)] : groundwork for the brew journal — a `brewlog.json` file now sits beside your bean library and can record a measured extraction. Nothing writes to it yet and nothing reads it back; the bean library itself is untouched and keeps its current size. Its absence is a normal state, and a damaged journal never stops you brewing
* 🐛 [fix(brew_advisor)] : auto-stop is now offered on espresso only, where it is armed by default. On a pour-over or an immersion the scale weighs the whole assembly, so it reached the target at the end of the last pour — before the bed had finished draining — and cut the brew short. Soft methods now end when you decide it has stopped dripping. A shot still stops on its own at the target yield, which no hand can match
* ⚡ [feat(brew_advisor)] : the « your dial-in » badge now tells you how old that dial-in is — « today », « 6 d », « 2 mo ». The date was already being recorded and never shown, so a recipe could carry a correction saved a season ago with nothing on screen to say so. Hovering gives the exact date, and past three months it adds a caution: that setting was dialled on a different roast of the bean, and the green has aged since — taste before trusting it. A dial-in saved before TilauScope kept dates says its age is unknown rather than guessing
* ⚡ [feat(brew_advisor)] : water activity is now judged in one place. The Storage tab owns the aw doctrine, so the brew advice reads the same zones — including the thresholds you set yourself. A bean could previously read « optimal » in Storage and « high moisture » in the advisor at the same aw, and widening your storage window changed nothing in the brew advice. The note now tells you which zone you are in and stays silent when the bean sits in your optimal window
* ⚡ [feat(brew_advisor)] : an espresso or moka dial-in reopens on the dose it was built on. On a pressure brewer the dose is not a preference — the basket sets it — so reopening on the method default silently changed the puck the whole dial-in was made for. Filter methods keep starting from the method default, where the dose is your free choice of cup size, and changing the dose by hand still wins everywhere
* 🐛 [fix(beancave)] : the brew advisor no longer refuses to open on a roast whose numbers were stored as text. A .alog is read without any schema, so an older profile, one that has been repaired, or one produced by another tool can hold its colour or its weight loss as text — and a single such field used to abort the whole window. Values are now read defensively at the door: what can be read is used, what cannot is treated as unknown
* 🐛 [fix(beancave)] : the water-activity field no longer claims to be a percentage. aw is a ratio between 0 and 1, but the field read « 0.52 % » — enough to make you type 52 and hit an unexplained ceiling. It now reads « 0.52 aw », with a tooltip giving the usual specialty range
* 🐛 [fix(beancave)] : roast loss is measured against the green charge again in the reference profiles. When a roast carried no recorded loss the value was rebuilt against the roasted weight instead, which overstated every one of them (a real 15 % read 17.6 %) and pushed some roasts past the plausibility limit, silently dropping them from the averages your bean is compared to. Roasts whose loss was stored as text are also read correctly now instead of being skipped
* 🐛 [fix(brew_advisor)] : accepting a taste correction now clears the tasting you just reported. It stayed ticked, so reporting a second fault on the next cup re-diagnosed the old one alongside it and offered a fix that folded the already-applied adjustment in a second time. Each cup is now judged on its own, exactly like a new extraction
* 🐛 [fix(brew_advisor)] : the grinder offset learned across your beans now needs four different beans to agree, not four dial-ins. A single bean dialled in on four brew methods used to unlock it on its own — four readings of the same coffee, which naturally agree with each other and looked like solid evidence. Each bean now counts once, whatever the number of methods it has been dialled in on
* 🐛 [fix(brew_advisor)] : a taste correction that could not be written to your bean library no longer reports « Saved ✓ ». The correction still applies to the recipe on screen, but the message now says plainly that it will not be there next time, instead of letting you lose a dial-in earned over several cups
* 🐛 [fix(brew_advisor)] : « Refine (AI) » no longer breaks the recipe it refines — an AI ratio change moved the water shown but left the pour steps and the auto-stop on the old target, was silently dropped on espresso, and had no lower bound at all (a run of refinements could reach a ratio of 1:-0.5 and a negative water amount). AI refinements now go through the same path as a taste dial-in, so they are bounded and keep the pour plan in step
* ⚡ [feat(brew_advisor)] : « Refine (AI) » now tells the model the shot time and the espresso style, so it stops reasoning about a classic long shot when you are pulling a turbo
* 🐛 [fix(brew_advisor)] : clicking a dose arrow no longer sends the value racing to the end of the range — on macOS this window could lose the mouse release that stops the arrow repeating, and the dose ran away on a single click. Each click is now exactly one gram, and typing a value or using the keyboard arrows is unchanged for a bigger jump
* 🐛 [fix(brew_advisor)] : the window is wide enough for its own controls again — adding the espresso machine and style selectors pushed the top row past the window's minimum width, so on macOS the method, machine and style fields were squeezed and their text truncated. The minimum width is now measured from the row itself rather than hardcoded, which also accounts for macOS system fonts and cannot be silently broken by a future control
* ⚡ [feat(brew_advisor)] : the espresso ratio now follows the roast instead of sitting at 1:2 for everything — it was the only ratio in the advisor that never moved, while the filter ratio has always tracked the roast. A light roast is dense and poorly soluble and needs a long shot to reach a decent yield; a dark roast is very soluble and releases its bitterness early, so it is cut short. The advisor now goes from 1:3.0 on a very light roast down to 1:1.5 on a dark one, and the shot time follows (42 s to 19 s) because at a given dose and grind the bed sets the flow: a longer ratio is paid for in time. The reference shot is untouched — a medium-light roast still reads 1:2.0 in 28 s
* ⚡ [feat(brew_advisor)] : new « Style » selector for espresso — « Classic long » keeps the grind the roast asks for and lets the shot run as long as the ratio needs, « Turbo » fixes the shot around 25 s and opens the grind to get the flow. Your choice is remembered. Turbo comes with a warning: it needs a machine that holds its pressure, otherwise the shot reads sour rather than fast
* 🐛 [fix(brew_advisor)] : beans already dialled in for espresso keep working with the new roast-dependent ratio — an old dial-in recorded the ratio the advisor produced at the time (always 1:2), and reading that as a correction you had made would have pinned every dialled bean back to 1:2 and cancelled the new behaviour. Old dial-ins now restore their grind and temperature only; ratio corrections made from now on are kept in full
* 🐛 [fix(brew_advisor)] : the pour schedule is now one you can actually execute — the pour deadlines were counted from the start of the bloom, so whatever the bloom did not use was all you had left: a V60 asked for ~100 g in 15 s (6.5 g/s) and a Pulsar for up to 28 g/s. Deadlines now come from how long the water really takes to pour, so a 13 g V60 reads bloom, pour by 1:13, pour by 1:36, drawdown at 3:00
* 🐛 [fix(brew_advisor)] : bigger batches no longer keep the small-batch clock — the pour windows were fixed while the water grows with the dose, so a 30 g V60 claimed the same 3:00 as a 13 g one; the announced time now follows the schedule (3:27 for 30 g) instead of contradicting it
* 🐛 [fix(brew_advisor)] : the live tracker no longer says you are « behind » from the first second on immersion brews — the AeroPress expected all the water in within 10 s (over 20 g/s) and the Weber Bird within 15 s; filling a vessel is now given the time a kettle actually needs
* 🐛 [fix(brew_advisor)] : the flow curve is readable again — the graph's flow scale was fixed at 10 g/s for every filter brew, so a normal pour-over at 3-4 g/s was drawn flat along the bottom; the scale now follows the brew you are making
* 🐛 [fix(brew_advisor)] : the advisor no longer tells you to widen and tighten the ratio at the same time — when two effects pull opposite ways it now says so, and that the ratio shown is already the balance of both
* ⚡ [feat(brew_advisor)] : the advisor warns when a recipe will not fit the brewer — a 60 g dose asks an AeroPress for 930 g of water and an espresso basket for a 60 g dose; it warns rather than refuses, in case your brewer is a large model
* 🐛 [fix(brew_advisor)] : after a balanced cup the panel no longer claims the dial-in is « saved » while still offering the button to save it
* 🐛 [fix(brew_advisor)] : a « too thin » verdict now really reaches the cup — accepting it lowered the water shown on the recipe but left the pour steps, the graph corridor and the auto-stop driving to the old amount, so the brew silently undid the very correction you had just accepted
* 🐛 [fix(brew_advisor)] : a « too thin » dial-in is no longer forgotten when you reopen a bean — only grind and temperature were being restored, so a bean dialled in on water came back to the generic recipe, and worse, was treated as never dialled in and received a grind change you never asked for
* 🐛 [fix(brew_advisor)] : « too thin » now works on espresso and moka — the fix was quietly discarded for pressure brewing, so the button appeared, promised nothing and changed nothing; the ratio step is also sized to the brew you are making, so one notch means the same thing in the cup at 1:2 as at 1:16
* 🐛 [fix(brew_advisor)] : dial-ins that only changed water or temperature no longer count as evidence about your grinder — they were padding the sample count used to learn the setup offset and could unlock it on evidence they do not carry
* ⚡ [feat(brew_advisor)] : the Dial-in advisor recipe is far easier to read — the numbers you actually act on (dose, water or yield, ratio, temperature, grind, time) now sit in a row of large tiles across the top instead of being buried in a uniform text table, secondary context (roast level, bloom, agitation, target EY) moved to discreet chips, and the brew protocol became a real step list with a coloured rail, time badge and target-weight pill per step
* ⚡ [feat(brew_advisor)] : the advisor's diagnostics are now folded away behind a « N diagnostics » line you click to open — they used to fill most of the panel and pushed the recipe itself out of view
* ⚡ [feat(brew_advisor)] : the live extraction graph now shows the recipe itself as a shaded corridor behind your pour, so you can see whether you are on plan instead of watching a bare rising line — a « on plan / N g ahead / N g behind » indicator tells you where you stand at a glance, and the graph gained a real time and weight scale with a tick for each step
* ⚡ [feat(brew_advisor)] : the brew protocol now follows you live — the current step lights up and past steps tick off automatically as the timer runs, so you never lose your place mid-pour; a progress bar and a « % of target » readout sit under the weight
* ⚡ [feat(brew_advisor)] : when you stop the brew, a summary appears with what you actually got (dose → yield, real ratio, time, average flow), how far that was from the target, and a suggestion pointing at the grinder when the brew ran fast or slow
* 🐛 [fix(brew_advisor)] : the extraction graph's flow curve no longer jumps around while you pour — it was rescaling itself continuously, which looked like flow changes that never happened; it now uses a fixed scale suited to the brew method
* 🐛 [fix(brew_advisor)] : the separate floating scale window is gone — it repeated the weight and timer already shown right beside it in the extraction panel, where they are now displayed larger
* 🐛 [fix(brew_advisor)] : « Start brew » and « Auto-stop » are no longer offered when the scale is not actually connected — the check only looked at whether a scale was set up in the settings, so starting a brew with the scale off ran a timer that never received a single weight. The advisor now looks for your scale by itself as soon as it opens and simply shows « Searching for the scale… » until it answers: switch the scale on and the brew controls appear on their own, with nothing to click. Losing the scale in the middle of a brew is announced instead of passing unnoticed
* 🐛 [fix(brew_advisor)] : stopping a brew no longer disconnects the scale — it stays on the line for the next brew and is only released when you close the advisor, and a scale that was already connected before you opened the advisor is left alone entirely
* ⚡ [feat(brew_advisor)] : the advisor now learns from the cup — a « How does it taste? » section sits permanently under the protocol, so you can give your verdict in one tap (sour / bitter / harsh / thin / balanced) on any recipe, with or without a scale, whether or not you used the live extraction tracking. When a brew time was measured it reads the taste together with that time and diagnoses far more precisely; without one it says so and tells you what to check instead of pretending to know. Sour on a fast brew is under-extraction and it offers a finer grind; sour on a *slow* brew is channelling, where grinding finer makes things worse, so it tells you to fix the distribution instead and changes nothing. Sour and bitter at once is uneven extraction, again a distribution problem rather than a grind one
* ⚡ [feat(brew_advisor)] : an accepted correction is saved on the bean, so the next time you brew that coffee the advisor opens on the setting that actually tasted right — marked « ✓ your dial-in » — instead of the generic recommendation. Corrections build up over successive brews and are capped so a bad cup can never send the recipe somewhere absurd
* ⚡ [feat(brew_advisor)] : once several of your beans have needed the same correction in the same direction, the advisor concludes it is your setup rather than the beans and applies it up front to coffees you have not dialled in yet — shown as « ⌁ setup runs ~6% coarse — adjusted », with the number of dial-ins it learned from in the tooltip. It is deliberately cautious: it needs at least four dial-ins that agree on a direction, ignores corrections that merely average out to something, and espresso is learned separately from filter. A bean with its own dial-in keeps it and is never adjusted twice
* 🐛 [fix(brew_advisor)] : a dial-in now follows the roast instead of freezing a grind size — it is remembered as an adjustment relative to what the advisor recommends, so re-roasting the same bean darker keeps your correction while still coarsening the grind as that roast needs. Previously it pinned the exact grind from the first roast, which pulled later roasts of the same bean well off target
* 🐛 [fix(brew_advisor)] : a bean past its freshness window no longer gets brewing corrections — staling cannot be brewed back, so the advisor says the cup is explained by the bean and leaves the recipe alone
* 🐛 [fix(brew_advisor)] : espresso shot timings are now built from your machine's own profile instead of a fixed 28 s — a Slayer or lever with a 24 s low-flow pre-brew used to show that pre-brew, the pre-infusion and full pressure all starting at 0:00 inside a shot that ended at 0:28, which cannot happen. The protocol now runs the clock through pre-brew → pre-infusion → full pressure → stop, and the shot length follows (a lever light roast reads 0:55, a dark roast on an E61 reads 0:25); a classic medium-light E61 shot is unchanged at 28 s
* 🐛 [fix(brew_advisor)] : a roast whose .alog only carries a partial phase breakdown no longer skews the brew advice — an incomplete file can imply a 100 % development ratio, which was read as an extremely long development; implausible ratios now fall back to development time instead
* ⚡ [feat(brew_advisor)] : brew advice now reads the development ratio (DTR) of the roast rather than raw development seconds — 2 minutes of development means something very different on a 6-minute roast than on a 14-minute one, and the ratio is what the roast side already works in. Roasts outside the usual 15-25 % band get their brew ratio adjusted as before; roasts with no phase breakdown still fall back to development time
* 🐛 [fix(brew_advisor)] : the recipe is now locked while a brew is running — nudging the dose mid-pour used to move the auto-stop target under you, blank the step checklist and leave the graph showing a plan the pour was no longer following; the brew is now carried out against the recipe as it stood when you pressed Start
* 🐛 [fix(brew_advisor)] : changing the method, dose or water after a brew now clears the graph — the previous pour's curve and stop marker stayed drawn on top of the new recipe's target corridor, as if that curve belonged to it; the timer, weight, flow, percentage, progress bar and step ticks are reset with it
* 🐛 [fix(brew_advisor)] : starting a new brew no longer shows the previous brew's weight, percentage and progress bar until the first drop lands
* 🐛 [fix(brew_advisor)] : an AI refinement that arrives after you have already started brewing is discarded instead of rewriting the recipe mid-pour
* 🐛 [fix(brew_advisor)] : a protocol step and its target weight no longer disagree by a gram (« Pour to 144 g » next to a « 145 g » target) — the step text was truncating where the target was rounding
build 34
* ⚡ [feat(label_printer)] : the roast label preview now has a « Copies » counter (default 1) so you can print several identical labels in one go — the printer status shows « Printing copy 2/3 » as it works and the remaining-labels count drops by the number actually printed
* ⚡ [feat(beancave)] : a new « Stockage » tab watches how your green coffee is keeping — each bean in stock is shown with its water-activity (aw) level colour-coded into a conservation zone (too dry / optimal / to watch / mould risk), most-at-risk beans first, so you can tell at a glance what needs attention
* ⚡ [feat(beancave)] : the Stockage tab reads the real humidity and temperature of your storage room from a Bluetooth-out-of-range sensor over MQTT and tells you, per bean, whether it is gaining moisture, drying out or stable — and the equilibrium moisture it is drifting toward
* ⚡ [feat(beancave)] : each bean now has a storage conditioning setting (vacuum / GrainPro / Ecotact / sealed jar / open bag) — sealed conditionings correctly suspend the drift estimate since the bag barely exchanges with the room, so you are never warned about a drift that cannot happen
* ⚡ [feat(beancave)] : you can measure a bean's aw with the AquaGauge straight from its conservation fiche, and the sack-label tool now lives in the Stockage tab (moved out of File Management) so everything about your stored bags is in one place
* 🐛 [fix(beancave)] : the Stockage tab now reads the storage sensor even when you are not roasting — it opens its own MQTT connection to the broker instead of relying on the roast-time connection (which only exists while monitoring is ON), so the ambient shows up while you browse your stock; connection and read attempts are now logged for troubleshooting
* ⚡ [feat(beancave)] : a « configurer » button on the Stockage ambient banner sets the storage-sensor MQTT source — humidity and temperature can point to different topics (and a field or dotted path within each payload), with a live « Tester » that shows the raw reading so you pick the right field
* ⚡ [feat(brew_advisor)] : the Dial-in advisor can now print a 50×30 mm recipe label on the Niimbot B21S in one click — it shows the bean (name, process and colour level) with a small pictogram of the target brew method; espresso prints the key numbers large (dose / yield / ratio / temp / grind / time), while V60 and the other gentle methods print the full timed protocol (bloom and pours with their target weights). Printing status shows live next to the button, and the button is disabled unless the 50×30 mm roll is loaded
* 🐛 [fix(label_printer)] : Niimbot B21S labels print correctly again after the printer's firmware update — the label was ejecting completely blank because the updated firmware speaks a newer print protocol (D110M) that burns the label only after the page is closed; the app was ending the job a fraction of a second too early. The whole print sequence was ported to the new protocol and now waits for the printer to report the page as fully printed before finishing
* 🐛 [fix(label_printer)] : reconnecting the Niimbot B21S after its firmware update no longer crashes TilauScope — the printer now returns a longer roll-identification block and the reader was assuming the old fixed size
* ⚡ [feat(label_printer)] : Niimbot B21S label printing is now near-instant to prepare — the image is encoded in one vectorised pass instead of pixel-by-pixel, removing the long pause before the printer starts
* 🐛 [fix(label_printer)] : printing a label or a batch of sack labels no longer greys out the window behind a blocking pop-up — printing progress now shows live in the printer status banner (« Printing… 120/240 »), the window stays usable, and once printing finishes it comes back to the front and clicks work immediately (the old pop-up could leave the window stuck in the background on macOS)
* ⚡ [feat(label_printer)] : the printer status now really shows the roll size and how many labels are left (e.g. « B21S 50×30mm · 43/120 labels left ») from the moment the printer connects — it was previously falling back to a short « B21S: 50x30 » that hid the remaining-labels count
* 🐛 [fix(devices)] : a TRP roaster wired over a bare serial line (no USB chipset, e.g. an Arduino on two pins) now connects reliably — TilauScope waits for the serial line to settle after opening the port and no longer gives up on the handshake if the controller answers a moment late, so temperatures read instead of staying blank
build 32
* ⚡ [feat(devices)] : the SENSORS tab now ends with an « Other hardware detected nearby » section (like the first-run assistant) — nearby gear that is recognisable but not wired up is listed for reference: known third-party devices (Santoker, IKAWA, ColorTrack, BlueDOT, Skycommand, RoastSeeNEXT) and any of your own sensors seen but left unassigned; identification only, no pairing or configuration
* ⚡ [feat(onboarding)] : the first-run setup assistant now shows a « Other Artisan BLE devices detected » section at the end of the hardware step — any nearby roaster or accessory that Artisan natively supports over Bluetooth (Santoker, Santoker R, IKAWA, ColorTrack, BlueDOT, Skycommand, Lebrew RoastSeeNEXT) is identified by name for reference; it is recognition only, no pairing or configuration
* 🐛 [fix(devices)] : forgetting a detected device (🗑) now keeps it instantly re-selectable in the dropdown instead of leaving an empty list until the next scan cycle
* 🐛 [fix(devices)] : the SENSORS tab no longer shows a horizontal scrollbar — device rows fit the window and the dropdowns still show the full device id
* 🐛 [fix(devices)] : the sensor device dropdowns now use the dark Catppuccin style instead of a white system popup
* ⚡ [feat(devices)] : the SENSORS tab now detects your gear automatically in the background — each device shows a live status (scanning… / detected ✓ / assigned) and a single detected device is selected for you; a 🗑 button forgets a device. The per-device Scan buttons are gone, and a configured device that is simply switched off keeps its assignment
* 🐛 [fix(main)] : the Artisan window now reopens at its last windowed size instead of maximized/full screen when the app starts directly on it
build 31
build 30
build 29
* ⚡ [feat(onboarding)] : a first-run setup assistant now guides new users through a 5-step wizard on their very first launch — temperature unit, roaster (which loads the matching device profile when one is bundled — the Skywalker V2 loads its USB profile by default, or its BLE profile if the roaster is detected over Bluetooth), hardware (roaster, extraction, scale, ambient probe, Lebrew AquaGauge and colour reader are searched for live over Bluetooth and shown as detected the moment they are seen — even on a brand-new install; anything already set up also shows as detected), the folders for your BeanCave database and roast logs (pre-filled with your existing folders when you re-run it), then hands off to creating the first green bean; settings are applied only when you finish (skipping changes nothing), and the assistant applies the Catppuccin theme, axes, curve styles and smoothing. Replayable anytime via TilauScope → « Redo First-Time Setup... »
* ⚡ [feat(artisan)] : fetched artisan continuous build update (new roasters, correction of code)
build 28
* ⚡ [feat(beancave)] : a new « Card » button in the Roasts tab exports the selected roast as a shareable landscape image (JPEG, 1200×630) — green bean identity, roast level, duration/DTR/charge/weight loss and the BT·ET·RoR curve with its milestones; unlike « Snapshot » (raw curve PNG) this is a composed image ready to post
* ⚡ [feat(beancave)] : a new « Card » button in the Green Beans tab exports the selected bean sheet as a shareable landscape image (JPEG, 1200×630) sized for social networks — origin, name, process, flavour notes and key metrics laid out in the TilauScope style; empty fields are simply left out
* ⚡ [feat(macos)] : the macOS DMG is now signed with a Developer ID certificate and notarized by Apple — macOS no longer refuses to open TilauScope with "the app is damaged and can't be opened", and no right-click/Open workaround is needed on first launch
build 27
build 26
* 🐛 [fix(i18n)] : fixed several TilauScope screens (BeanCave sheet, sack wizard, zone editors, catalogue, label printer, event actions, coach advice) where translatable text went through local `_tr()`/`tr()` shortcuts instead of `QApplication.translate(...)` directly — those strings were invisible to the translation extractor and would never appear in the French UI
* ⚡ [feat(perf)] : the in-roast automation banner and the cooling-page back-to-back hint no longer re-translate their text on every 1 Hz refresh — the strings are now pre-translated once when the panel is built, matching the pattern already used everywhere else in the guided assistant
* 🐛 [fix(i18n)] : the "New bean (expert)" zone title in BeanCave's new-bean editor was invisible to the translation extractor (it was picked dynamically instead of as a literal) and would never be translated; the sack wizard's page-step titles are also no longer re-translated on every page navigation
* 🐛 [fix(events)] : roast-milestone buttons configured as "WebSocket Command" or "TilauScope Ambient Command" now fire the correct action — they were mis-mapped and triggered the Stepper and Difluid AirWave actions instead
* 🐛 [fix(devices)] : the Difluid AirWave roast-stage echo works again — it silently failed on every sample and never told the AirWave which phase (CHARGE/DRY/FCS/…) the roast was in
* 🐛 [fix(devices)] : the tilauambient() command action now reaches the ambient probe instead of being gated behind the Difluid AirWave connection
* 🐛 [fix(beancave)] : opening the roast setup/result dialog no longer crashes when the scale subsystem is unavailable — the "scale not available" fallback was itself raising an error
* 🐛 [fix(ports)] : closing the Ports/MQTT configuration dialog no longer crashes when MQTT was enabled but no client is running

build 25
* ⚡ [feat(tools)] : Release Manager — "Release → main" reworked: it stamps and commits the release files, merges continuous into main (without touching the working tree) to trigger the release build action, and once main accepted the push it bumps the build number in ReleaseHistory.md and __init__.py ready for the next cycle
* ⚡ [feat(tools)] : Release Manager — the push button now commits pending changes first (asks for a commit message, pre-filled with version + build) before pushing to continuous
* 🐛 [fix(tools)] : Release Manager — "Push → continuous" is now reliable: it pushes with a fully-qualified refspec (a stray tag named like the branch no longer breaks or misroutes the push) and warns before pushing when there is nothing to push or when uncommitted changes would be left behind
* 🐛 [fix(devices)] : on Windows, the scanned Cyberroaster (and any BLE device) is no longer forgotten after restarting the app — Windows MAC addresses were silently dropped when saving the settings, only macOS-style identifiers were kept
* 🐛 [fix(devices)] : the roaster device selector now always reads "Skywalker v2 (identifier)" — a fresh scan showed the raw firmware name (e.g. TD5325A_V3.1.2BLE) while reopening the dialog showed a different label; the section title and scan messages now say Skywalker v2 as well
build 24
build 23
* 🐛 [fix(devices)] : the Cyberroaster Scan button finds the roaster again — every scan silently timed out to "No Cyberroaster found" since a recent BLE rework; its scan now goes through the same BLE stack as every other device
* 🐛 [fix(devices)] : all BLE Scan buttons now have a hard timeout — a hung system Bluetooth scan can no longer freeze the configuration dialog
* ⚡ [feat(tools)] : translation editor — restored the "Purge vanished" button (removes obsolete strings from the .ts file) and the "AI translate" button (translates all remaining todo strings in background batches using the AI provider configured in TilauScope), both lost in an earlier refactor
* 🐛 [fix(tools)] : translation editor — "Next todo" now jumps to the next untranslated string after the current one (it always went back to the first), and editing a French translation no longer makes the selection jump to another string while typing
* ⚡ [feat(beancave)] : scan a label QR code with your phone — TilauScope now runs a read-only record web server (reachable as tilauscope.local on the local network, port configurable): pointing the phone camera at a label opens the roast page (curve image, weights, loss, Agtron, DTR, key times, tasting notes, link to the source bean) or the green-bean page directly in the phone browser
* ⚡ [feat(label)] : printed label QR codes now encode the phone-scannable web address (roast and green-bean labels) — older labels remain scannable with the desktop 📷 SCAN button
* 🐛 [fix(beancave)] : the 📷 SCAN webcam decoder is now far more robust — it decodes from the camera frames with an automatic fallback to the on-screen preview, selects the camera's highest resolution (a 14 mm label QR needs every pixel), retries mirrored images, and a TILAU_QR_DEBUG=1 mode shows the capture pipeline state in the scan window and saves what the decoder sees to a snapshot for troubleshooting
* 🐛 [fix(packaging)] : the Windows build keeps Qt6Multimedia.dll (it was stripped as a size optimization before the QR scanner existed) — without it the 📷 SCAN camera would not start in the setup.exe build; camera-permission error messages now point to the right privacy screen per platform (macOS / Windows)
* 🔒 [feat(web)] : the record web server is hardened against attacks — strict URL validation (malformed identifiers never reach the application), security headers on every response (CSP, nosniff, anti-framing), no framework version disclosure, GET-only, and curve rendering moved off the request loop so a burst of requests cannot stall other clients
* ⚡ [feat(beancave)] : new 📷 SCAN button in the BeanCave header — scan a label QR code with the webcam (camera on only while the scan window is open) to open the matching record: a roast label shows a read-only roast card (BT/ET curve with key events, weights and loss, Agtron, DTR, key times, tasting notes, link to the source bean sheet) and a green-bean label jumps to that bean in the catalogue; storage-sack QR codes are recognized and announced for a future version
* 🐛 [fix(beancave)] : the QR scan window now reliably triggers the macOS camera authorization prompt (native AVFoundation request, with the Qt permission API as fallback) — previously the camera silently refused to start and the window could hang on "waiting for authorization"
* ⚡ [feat(config)] : the record web server port for the upcoming phone scan (encoded in printed label QR codes) is now configurable in the TilauScope options, General tab (default 8123)
* ⚡ [feat(label)] : roast PDF label now carries a traceability QR code (bottom-right, 14 mm) encoding the Artisan roast UUID, with a discreet ROAST ID text beside it — ready for a future scan-to-open-record reader; QR colors blend with the label palette (both roast and green bean labels) instead of black-on-white
* 🐛 [fix(label)] : roast PDF label pills now show the bean's flavour notes (with cupping notes as fallback) instead of the roasting notes taken during the session
* 🐛 [fix(pid)] rework learning stage
* ⚡ [feat(core)] : app now runs on Python 3.14 — Bluetooth availability check fixed for the new asyncio behaviour, build pipelines updated
* 🐛 [fix(build)] : local Windows build now always uses the project venv's Python and PyInstaller, preventing broken setup.exe ("Python magic pattern mismatch")
build 22
build 21
* ✨ [feat(beancave)] first version of app mode
build 20
* 🐛 [fix(tc4ble)] : scanning for a Skywalker V2 connection in the device configuration no longer crashes with "A coroutine object is required", and a full-length scan no longer times out prematurely — the BLE discovery now runs reliably
* 🐛 [fix(devices)] : a failed or empty BLE device scan (any device, on macOS or Windows) no longer crashes the app — it now falls back gracefully to the "No … found" message
* ✨ [feat(tilauscope)] added Skycommand support
* ⚡ [feat(beancave)] : green beans can now carry sack labels — the bean form shows the attached sack ids as chips, clicking a chip's ✕ marks the physical bag as empty and returns the label to a reusable pool for a future sack; entirely optional, beans without sacks look and behave exactly as before
* ⚡ [feat(beancave)] : new "Sack ID labels" tool in the File Management tab — print a numbered batch of sack labels (QR + human-readable id, 50×30 mm Niimbot roll, editable prefix and next number), reprint a single damaged label without touching the counter, and manage the pool of released labels ready for reuse; the counter only advances by the number of labels actually printed
* ⚡ [feat(beancave)] : new "New sack" guided assistant, launched from the "+ New sack" button in the catalogue action bar — register an incoming bag step by step (new bean, restock of an existing bean, or a new crop copied from its previous record), optionally pre-filled by AI from a supplier URL; the sack-number step is fully skippable, available labels are offered in the list, and a review screen with per-section ✎ Edit lets you adjust anything before the record is created; visuals follow the Roast Setup language (titled zones, selectable cards, all actions in the bottom bar)
* ⚡ [feat(beancave)] : the new-sack assistant now supports blends — a Type zone (single origin / blend) with up to three components and ratios, shown in the review; the AI extraction also detects blends (default ratios 50/50 or 34/33/33 when not stated, extra components moved to the tips) and only returns varieties from the normed lists
* 🐛 [fix(beancave)] : batch-printed sack labels are now remembered and offered at the assistant's identification step until they are assigned to a bean — previously only labels released from an emptied sack were proposed
* ⚡ [feat(beancave)] : the Free sacks tab now shows every available label (released and printed-not-assigned) and gains an "I already have this label" field to register labels printed earlier without reprinting them
* 🐛 [fix(beancave)] : text fields in the new-sack assistant (bean name, farm, supplier, flavour notes) now use the available width instead of staying at their minimum size
* 🐛 [fix(beancave)] : the assistant's Category field moved next to Process on the Characteristics step (category drives the process list — they now live side by side), and the print shortcuts of the Sack ID step open the label tool directly on the matching tab
* ⚡ [feat(beancave)] : the assistant's Flavour notes field gains the Flavor Wheel selector button, same wheel as the bean form
* 🐛 [fix(beancave)] : the Update button no longer wears the accent colour — "+ New sack" is the single highlighted action of the bar, Update now looks like Add/Clear
* 🐛 [fix(beancave)] : input fields of the new-sack assistant now show a visible focus state (accent border + lighter background) so you can see where you are typing
* ⚡ [feat(beancave)] : the new-sack assistant now shows the live Acaia scale window next to the weight step — when scale 1 is configured, a floating ⚖ reading appears on the Essentials page; click the value to capture the exact sack weight into the active field (new bean, restock or new crop), double-click to tare, same behaviour as Roast Setup
* ⚡ [feat(beancave)] : the Characteristics ✎ editor reconnects the measuring instruments — a 💧 water-activity annex window (same style as the scale one) appears automatically when the AquaGauge probe is configured, click the live reading to fill the field; a new « ⚖ Measure » button next to Density opens the scale-piloted density measurement window targeting the editor's field; the 💧 window also appears in the expert Add form (below the ⚖ scale window), while density measurement stays exclusive to the targeted editor where the scale is free
* ⚡ [feat(beancave)] : the "In stock" filter of the catalogue list is now remembered — reopening BeanCave restores the filter exactly as you left it
* 🐛 [fix(tilauscope)] : every remaining native system popup now uses the TilauScope styled dialog — headless-mode restart notice, MQTT connection test, Niimbot print warning, updater messages and the crash-report confirmation
* 🐛 [fix(devices)] : saving the device configuration after an empty BLE scan no longer destroys the stored device identity — the "No … devices found" placeholder text was saved as the device address for the AquaGauge, RoastSee C1 and Cyberroaster, which made the device undetectable forever; the dialog now only accepts a genuine BLE identifier (macOS UUID or Windows MAC) and keeps the previous one otherwise; re-scan once with the probe awake to restore it
* 🐛 [fix(beancave)] : the 💧 water-activity window now seeds with the probe's last reading at opening and shows the live connection state ("probe connected — measure to read" / "probe not connected…") — the AquaGauge only notifies on measurement events, so the window previously looked dead until a new measure completed
* 🐛 [fix(beancave)] : the expert Add form is now usable — required fields (name, country, category, process, species, varieties) are marked with * and the Create button stays greyed out until they are filled, crop year defaults to the current year, the selectors got readable widths (process/species/varieties were collapsing to a few pixels), the window opens wider and anchored near the top of the screen, and the delete confirmation now uses the styled dialog like every other message
* ⚡ [feat(beancave)] : the catalogue action bar now matches the validated design — « + New sack » (single highlighted action) | Roast · Label · QR | Add … Delete; Update, Clear, Flavors and AI disappear from the bar (their jobs moved into the sheet's ✎ zone editors), Add opens a full expert form on a blank record (all sections stacked, ⚖ scale capture on the stock field), and the header prefix reads "Bean:" instead of "Editing:"
* ⚡ [feat(beancave)] : the ✎ buttons of the bean sheet now open targeted zone editors — small dialogs editing only that section (Essentials with live ⚖ Acaia capture on the stock field, Provenance, Characteristics with blend components and category-driven process list, Sensory with the Flavor Wheel); Save writes the record immediately, Cancel leaves it untouched
* ⚡ [feat(beancave)] : the bean details pane is now a readable sheet instead of a permanent form — a hero card (name, origin, stat tiles for stock, crop with age colour, SCA and roast count) followed by Provenance, Characteristics (including blend composition), Sensory (flavour notes as chips + tips) and Sacks zones; each zone has a ✎ Edit button that opens the editing form, and saving or selecting a bean returns to the sheet
* ⚡ [feat(beancave)] : the green beans catalogue is now a readable rich list — each bean shows on three compact lines (name with BLEND and harvest-age badges, origin · process · crop, stock pill and attached sack labels), out-of-stock beans are dimmed, with a live search field (name, country, farm, supplier) and an "In stock" filter on top; replaces the 28-column table squeezed into the left pane
* ⚡ [feat(beancave)] : the catalogue list now colour-codes stock at a glance — out-of-stock beans are dimmed, and the crop year turns orange when the harvest is 2 years old and red at 3 years or more, both in the list and directly on the Crop field of the bean form (unset crop years are ignored)
build 19
build 18
* 🐛 [fix(tilauscope)] search on github then google drive for build
build 17
* 🐛 [fix(tilauscope)] build process
build 16
build 15
* 🐛 [fix(plan)] : the learned first-crack temperature is now adjusted for charge temperature using linear regression — the historical FC correlation with initial charge (higher charge → higher FC) was invisible to the old median-based model, causing +9°C prediction errors on lighter charges and −8°C errors on heavier charges; the plan now learns the regression slope/offset from the corpus and adjusts the FC prediction using the planned charge temperature, yielding ±2°C accuracy across the charge range instead of ±9°C; this fix stabilizes cross-roast learning (child roasts no longer amplify biases from parent roasts)

## [4.1.0] 2026-07-04
build 14
* 🐛 [fix(tilauambient)] crack counter variable was not loaded because of variable renamed was missing
* 🐛 [fix(roastsetup)] tilauambient probe was not correctly mapped (wrong variable name after rename)
* 🐛 [fix(roast properties)] missing code to handle custom buttons, added and ok
build 13
* ⚡ [feat(assistant)] : the roast summary now tells you what the NEXT plan will do about colour — when a bean lands off its Agtron target it shows a "Colour → next plan" line (e.g. "Colour 62 · target 56 — too light by 6 pts → Next plan: +2°C at drop · ≈ +4 pt DTR"), reading your hand-measured bean colour when you've logged it and the model's prediction otherwise, and it stays hidden when no colour is available; it is display only — the actual correction still comes from the plan's own colour learning, this line just makes its direction and rough size legible before the next roast
* ⚡ [feat(assistant)] : the coach now speaks in "one notch" and waits for the fire to answer — when your RoR drifts and the burner is off the plan, it suggests a single ~5% step toward the plan (e.g. "burner 75% → one notch to 70% (plan 60%)") instead of naming the full 15% gap, which read like "cut it all at once" and led to pumping the burner; and after any burner move it now holds its directional advice for the machine's real settling time (~55 s on the Skywalker instead of ~28 s, matching the measured fire response) unless the drift keeps worsening — the crash alert is never delayed
* ⚡ [feat(plan)] : the charge temperature now follows the batch size — small batches are started cooler (down to −10°C at ≤275 g, easing back to no change at ≥325 g), matching the two charge regimes seen across your own roasts (~175°C for small batches vs ~185°C for full ones); the turning-point estimate follows, and a "Small batch" note explains the adjustment (large batches are unchanged)
* ⚡ [feat(plan)] : the anticipated heater ramp now descends from the right place at the right time — the learned burner values are measured at the MIDDLE of each phase, but the ramp used to apply them at the START of the phase (Maillard value already at dry-end), pulling the fire down half a phase too early; the drying heat is now held to ~75% of drying, eased to the Maillard value at mid-Maillard, then to the pre-first-crack value, all in clean ≤5% steps placed at their true bean-temperature threshold (no more 6-10% jumps in the steep final stretch); the pre-first-crack burner level is now learned from your own past roasts of this bean (the fire actually held at first crack), falling back to the plan's own calculation when there's no history — the plan reports the pre-FC source
* ⚡ [feat(plan)] : the drum speed is now a SETUP parameter — one single value chosen at charge from batch weight (dominant) and bean density (~250 g → 70-75%, ≥300 g → 80-85%, calibrated on the owner's own roasts), and it no longer moves during the roast: the per-phase drum changes (faster in drying, slower in Maillard) and their DRY END / FC START alarm lines are gone — every in-roast drum move shakes the bean bed around the probe and blinds the RoR reading for 30-45 s; the charge line still sets the drum and the DROP line still speeds it up for cooling
* 🐛 [fix(plan)] : the "Heater ramp (anticipated)" line of the plan PDF no longer overflows the right edge of the page — with the fine progressive staircase the chain of steps can be long, and it was printed on a single non-wrapping line; it now wraps cleanly under its column and flows to the next page when needed
* ⚡ [feat(plan)] : the plan's "RoR at drop" target is now realistic — it is learned from your own past roasts of the same bean (colour-matched, ≥2 roasts), and when there is no history it falls back to profession good-practice values per machine type (a fast FIR/NIR roaster drops with a much livelier RoR, ~4-5.5°C/min, than a classic drum, ~2-3.5°C/min); the old target could sit 2-3× below reality on the Skywalker, which made the development coach cry "above plan" on healthy roasts and skewed the DROP countdown and projected DTR — the plan PDF now reports the Drop RoR source (learned / blend / table)
* ⚡ [feat(autopilot)] : AUTO mode is withdrawn from the app for now — the AUTO chip no longer appears and the mode cannot be armed; a real-roast trial showed its in-roast correction layer chases the RoR (the consequence) instead of driving the settings (the cause), and the whole subject is being redesigned from the ground up on the offline bench before it comes back
* 🐛 [fix(assistant)] : the RoR crash alert in the Development phase now actually works — the old detector's threshold was tuned 3× too steep and never fired on a real development crash (0 of 21 in the roast corpus); it now watches the RoR loss over a sliding 15 s window and only fires on a frank crash, its advice is "support with AIR, never cut the fire", and any drum speed change mutes the alert for 30 s (a drum move corrupts the RoR measurement itself and caused false readings on 64 of 81 roasts)
* 🐛 [fix(assistant)] : the guided assistant now roasts to the TARGET you chose in setup, not a stale one — the roast-level target (e.g. Light) picked in Roast Setup never reached the assistant's own target selector, which stayed stuck on whatever it showed before (e.g. Medium Dark from a loaded background), so the guided plan was built for the wrong roast level; Roast Setup now hands its target to the assistant, and the live target wins over any background
* 🐛 [fix(assistant)] : the assistant now shows the bean you are actually setting up, not a stale one — when a past roast was still loaded as a background/comparison profile, its bean overrode your live selection (you picked Kojoyo but the panel showed 74110), because the background had priority over the live roast; the live selection now wins, and the background is only used as a fallback when the live roast carries no bean identity (simulator replay still follows the replayed profile)
* ⚡ [feat(plan)] : the plan now auto-tunes the charge temperature per bean to land the early RoR peak in its sweet spot (~15-16°C/min) — a bean whose past roasts consistently peak too high (an overshoot that runs the whole roast hot and risks the post-first-crack crash) is started a few degrees cooler next time, and one that peaks low a few degrees hotter; it learns from that bean's own history (≥2 roasts), stays inside a dead-band so on-target beans are untouched, and is capped at ±10°C so it only ever nudges — the roaster's own charge/soak logic keeps the final say
build 12
* 🐛 [fix(autopilot)] : AUTO no longer disarms itself at auto-CHARGE — the preheat→roast handoff briefly moves the burner (as the beans go in the probe dips and the preheat PID pushes heat for an instant before it is cut), which AUTO mistook for a manual takeover and paused; a short grace window right after CHARGE now lets that handoff settle without pausing, then manual-takeover detection resumes normally
* 🐛 [fix(autopilot)] : the airflow now visibly climbs through development again — it was going nearly flat because the modelled gap between the Maillard and development airflow targets is often small, so there was almost nothing to ramp; development airflow now also opens in proportion to how far the burner comes down across development (airflow supports the reaction as the fire drops — the roaster doctrine), giving a gentle progressive rise even when the static target is low, capped so it never over-opens (learned/base targets still win when they ask for more)
* 🐛 [fix(assistant)] : a glitch in a single per-tick page refresh can no longer crash the app during a live roast — the whole panel refresh is now wrapped so any unexpected error is logged and the tick is skipped, exactly like the AUTO engine already was
* 🐛 [fix(autopilot)] : resuming AUTO after you paused it and nudged a slider now treats your new setting as the baseline (the correction engine re-zeroes its running trims and re-reads its targets from the current position, instead of carrying over stale trims from before the pause)
* 🐛 [fix(autopilot)] : AUTO no longer moves the extraction slider if the AirWave dropped its connection mid-roast (the correction engine could still act on a stale reading); the extraction lever is only driven while the AirWave is actually present
* 🐛 [fix(autopilot)] : AUTO no longer risks stalling the roast by leaving an extraction brake applied — if the RoR spiked (triggering an extraction brake) and then dropped straight through the target without ever settling back in band, the brake used to stay on while AUTO added air/heat to fight the sag, pumping heat away exactly when the reaction needed it; the extraction brake is now walked back toward its plan value the moment RoR drops below band, with priority over everything else (it can never go below the plan value)
* 🐛 [fix(autopilot)] : the burner no longer "stops moving" mid-roast under AUTO — the progressive turning-point→pre-first-crack staircase was silently overwritten about a minute in (when the plan re-anchors on the real turning point) by a coarse two-step ramp, which held the drying heat all the way into Maillard and then dropped it in one brutal jump; the re-anchoring now rebuilds the exact same fine progressive staircase (and the turning-point re-anchor leaves it untouched), so the gentle step-by-step burner descent you validated actually runs on every roast
* 🐛 [fix(autopilot)] : plan generation no longer crashes for a roaster that has airflow control but no burner control (the airflow ramp referenced a burner-only value)
* 🐛 [fix(autopilot)] : AUTO now approaches every target PROGRESSIVELY, from the turning point onward — a roaster's settings are never changed brutally by tens of percent. Four fixes from simulator testing: (1) the burner is now a continuous gentle staircase from just after the turning point all the way to first crack — it holds the drying heat briefly, then eases down step by step through drying and Maillard (never a jump at dry-end), reaching the pre-first-crack target about a minute before FC (this replaces an abrupt drop such as 60→48 in one move); (2) the development airflow and burner keep climbing/easing the same gentle way instead of jumping at first crack, and the burner carries over smoothly from its pre-FC value; (3) the "drifting vs plan" percentage is now coherent — AUTO compares your RoR to the plan's actual modelled RoR curve at that exact point (it previously used a crude flat average that produced nonsensical figures like "+84% vs plan" when the roast was tracking fine); the whole burner shape is modelled on your own past roasts
* ⚡ [feat(autopilot)] : airflow is now progressive milestone-to-milestone under AUTO — it holds low through drying and early Maillard, then opens gently in ~5% steps from mid-Maillard (when browning smoke arrives) to help clear the smoke, and rises more intensely from first crack into development to support the reaction as the burner comes down; the whole airflow shape is learned from your own past roasts of the same bean, and carries over smoothly across first crack (no jump)
* ⚡ [feat(autopilot)] : development is no longer flat under AUTO — the burner eases down and the airflow rises across the development phase (with a gentle AirWave extraction bump when present) to support the reaction and chase smoke to the extractor; this DEV trajectory is LEARNED from your own past roasts of the same bean (same quality gates as the other learned values) and falls back to a corpus-calibrated gentle ramp when history is thin — the plan reports "learned (n=N)" or "default" as the Dev Profile Source
* 🐛 [fix(assistant)] : two AUTO cockpit fixes from simulator testing — the "Mark DRY END" button no longer lights up right at CHARGE (before the turning point the falling probe temperature crossed the target from above; it now waits for the TP), and pausing AUTO now returns the panel to the detailed phase pages with their ± quick-adjust controls (in anchored Guided mode the cockpit left no reachable lever); tapping any lever tile in the cockpit is the new take-over gesture (pauses AUTO instantly)
* ⚡ [feat(assistant)] : while AUTO drives, the assistant now switches to a dedicated COCKPIT view — four big elements and nothing else: the AUTO PILOTING banner (phase + timer), one plain-words status (ON PLAN ✓ / DRIFTING ↑↓ / PAUSED), the last action card (what + when — the why stays in the event log), four lever tiles that light up for 10 s when the machine moves them, and a milestone progress bar with ETA; the detailed phase pages remain the manual/guided view. Milestone detections (DRY END / FC START) are marked automatically while AUTO is armed, and the cockpit carries one contextual milestone button (DRY END / FC START / DROP) that turns prominent near the plan target — so milestones can always be marked from the panel even when the detectors can't fire (e.g. the acoustic FC detector in simulator mode); in Development, when BT reaches the plan's drop target a 10 s cancelable auto-DROP countdown runs in the action card (the button becomes "✕ Cancel auto-DROP"), then DROP is marked and the cooling hand-off follows
* ⚡ [feat(assistant)] : AUTO now corrects the roast continuously (stage-2 trim) — between milestones the engine calibrated on the owner's 81 historical roasts nudges the levers when the RoR drifts from the plan line: airflow first to support a sagging RoR, heater in small gap-scaled steps, extraction as the brake for runaways with a mandatory release once the RoR is back (stall protection); one bounded action at a time, never during another action's settling window, trims reset at every milestone, and a RoR crash now pauses AUTO immediately (the guardrail is fed even in cockpit view)
build 11
* 🐛 [fix(build)] : the Windows executable no longer crashes at launch with "No module named 'scipy._external.array_api_compat.numpy.fft'" — scipy 1.18 moved its vendored compatibility layer and the Windows packaging spec now bundles it
* ⚡ [feat(assistant)] : new opt-in AUTO mode (v1a) — an AUTO chip next to the ▶ button lets the roast plan drive the levers itself: phase settings (airflow, drum, extraction, heater) are applied at each milestone and the heater ramp steps fire automatically when their BT threshold is crossed; touching any slider instantly pauses AUTO (tap the chip to resume), stopping the assistant disarms it, arming is refused when the plan confidence is low, the chip is absent on read-only roasters, and every automatic action is reported in the coach line and logged as a regular Artisan event; at DROP the cooling settings are applied automatically (burner cut, airflow and extraction high, drum fast) and AUTO disarms itself — the roast is over, the operator has full control back
* 🐛 [fix(assistant)] : the Development page header no longer garbles at First Crack — the long DTR sub-line (target / DROP ETA / final / RoR / predicted color) now lays out on two controlled lines instead of word-wrapping mid-digits with its last line clipped, and the freshly activated phase page gets one full repaint (stale pixels from the previous page could remain visible underneath the transparent labels)
* 🐛 [fix(beancave)] : opening BeanCave when the app started on the Artisan window (BeanCave home mode off) now hides Artisan behind it instead of leaving it visible in the background — the Artisan window comes back automatically when BeanCave is closed
* 🐛 [fix(beancave)] : repairing or auto-tagging a roast profile no longer slowly corrupts its bean description — the ALog Repair save path double-escaped the file on every write, piling up backslashes in the multi-line "beans" field (and mangling accented letters) across successive saves; profiles are now written in Artisan's exact native format, so the text stays clean no matter how many times it is re-saved
* 🐛 [fix(roaster)] : saving TilauScope configuration no longer force-opens Artisan's slider dock — toggling the read-only checkbox (or any save) now only updates which sliders are shown, and leaves the dock's own open/closed state exactly as you left it in Artisan's View menu
* 🐛 [fix(assistant)] : the classic slider rows no longer stretch apart after toggling the read-only checkbox on and off — they stay packed at the top of the control zone instead of spreading out to fill the height
* 🐛 [fix(assistant)] : in card (big-slider) mode the value tooltip now uses the dark theme instead of the default white system style
* ⚡ [feat(airwave)] : configuring an AirWave in TilauScope configuration now automatically maps the Damper slider onto it — the slider is renamed "Airwave", ranged 30–100 % with the DiFluid "FAN {}" command, and kept available even on a read-only roaster; power on / standby and the fan mode (standard / boosted) stay driven by your alarms as an expert control
* ⚡ [feat(roaster)] : TilauScope configuration gained a "Read-only (monitoring only)" checkbox next to the roaster — tick it for a machine you drive by hand (Artisan only records ET/BT) and every control slider is hidden here and in Artisan; untick it and your previous slider configuration is restored untouched. This is an explicit choice, so a hand-built or hot-rodded roaster is never wrongly locked down
* ⚡ [feat(assistant)] : the TilauScope control panel now mirrors Artisan's slider visibility — any slider disabled on the Artisan side (or hidden by a read-only roaster) disappears from both the classic slider rows and the card view instead of showing a useless control
* 🐛 [fix(brew)] : closing TilauScope to return to BeanCave no longer crashes with a "wrapped C/C++ object ... has been deleted" error when the brew-ready notification had already auto-closed itself — the stop request is now guarded and the stale reference cleared
* 🐛 [fix(build)] : the macOS build no longer carries a stale "4.0.4" version — Info.plist had the old version hard-coded (the packaged app was corrected by the build spec, but the leftover value was confusing and could ship if the spec changed); it now matches the release version
build 10
* 🐛 [fix(brew)] : opening TilauScope from BeanCave and coming back no longer logs a "BrewToast: 'TilauScope' object has no attribute 'values'" error — the startup brew-ready notification was being handed the TilauScope window instead of the roast metadata cache, so it silently failed; it now receives the correct data (and shows nothing rather than erroring when the cache isn't ready)
* 🐛 [fix(beancave)] : the "🌡 TilauAmbient probe" button now actually detects the probe — it is managed by BeanCave the same way as the Lebrew AquaGauge (connects on open, enables the button on connect, disconnects on close) instead of checking a device handle that was never populated
* ⚡ [feat(beancave)] : the two ambient sources are now mutually exclusive and driven by probe detection — when the TilauAmbient probe is connected its button is enabled and "Online weather" is greyed out (the probe is the live source); when no probe is detected, "Online weather" is enabled and the probe button is greyed. Both react together the moment the probe connects or disconnects
* ⚡ [feat(beancave)] : the Roasting plan tab gained a "🌡 TilauAmbient probe" button next to "Online weather" — when the TilauAmbient probe is connected, one click fills the temperature, humidity and pressure fields with its live readings; the button stays greyed out with an explanatory tooltip when the probe isn't detected, and its state refreshes each time you open the tab
* ⚡ [feat(beancave)] : the Roasting plan tab was redesigned as a guided 3-step flow (Bean → Conditions → Target & plan) with a progress header that lights up as you complete each step — ambient readings now sit in four labelled fields with the "Fill from online weather" button right beneath the fields it fills, the batch weight is set apart in its own highlighted field, and the probe-deviation offsets are tucked into a collapsible "advanced" panel (hidden by default)
* 🐛 [fix(beancave)] : the redesigned Roasting plan tab now renders correctly — it no longer stretches across the whole window (the flow is centered at a readable fixed width and scrolls vertically instead of compacting when the advanced probe-offsets panel is expanded), the ambient and batch values are always visible in their fields (including those pulled from a reference roast or the weather button), the weather and Generate buttons are sized sensibly instead of spanning the full width, the weather button label is legible, and the redundant plan-output text box was removed (the plan is delivered as a PDF, alarm set and background curve)
* 🐛 [fix(i18n)] : fixed the French "%n note(s) selected" flavor-wheel counter — its plural entry was malformed (which also broke the translation build); it now shows the correct singular/plural form and a spelling typo was corrected
* 🐛 [fix(brew)] : two-finger vertical scrolling now works on the Brew Planning timeline — a vertical trackpad swipe scrolls the lanes vertically when there are more roasts than fit on screen (it previously only ever moved the view sideways), while horizontal swipe and the mouse wheel keep their left-to-right behaviour
* 🐛 [fix(brew)] : polished the timeline roast card — the "Brew this coffee" button no longer renders with a tiny font the first time a card opens, the card's rounded corners are now transparent (no black square behind them), and stray trailing bar characters that could appear after the SCA / altitude values are stripped
* ⚡ [feat(brew)] : the Brew Planning timeline now shows the best day to drink each roast — each degassing bar fades in from a faint "just ready" edge to a bright glow at the theoretical peak (marked by a white line), then continues as a hatched "near-peak, drink soon" tail before the coffee is no longer shown; peak days are calibrated on the resting literature (≈8 days for a medium roast, earlier for dark, later for very light)
* ⚡ [feat(brew)] : the timeline gained a Filter / Espresso target selector (top-right, remembered between sessions) — picking Espresso shifts every window a few days later, since pressure brewing tolerates residual CO₂ less well, so the bars match whichever way you actually brew
* ⚡ [feat(brew)] : each roast bar now has a "☕ Brew this coffee" button in its hover card — one click opens the Brew Advisor already loaded with that roast (and selects it in the bean list); roasts without a colour reading or a linked green bean are dimmed and show why they can't be brewed
* 🐛 [fix(brew)] : the startup "brew-ready" notification now agrees with the Brew Advisor on the rest window — it keeps listing a roast for the couple of weeks past its peak with a "DRINK SOON" tag (instead of dropping it the moment the peak window closed) and no longer flags the last days of the optimal window as "STALE SOON"; freshness (fresh / peak / drink-soon / stale) is now read from a single shared source so the toast, the advisor and the planning timeline can never give contradictory degassing advice
build 9
build 8
* 🐛 [fix(beancave)] : the BeanCave window is now kept fully on-screen — a window position/size remembered from a larger or different monitor is shrunk and nudged back into the current display instead of opening partly off-screen (and it no longer floods the log with "Unable to set geometry" warnings)
* 🐛 [fix(bluetooth)] : on a computer with no Bluetooth adapter (e.g. a desktop PC without a dongle) the device scanner no longer floods the log with a repeating "No Bluetooth adapter found" error every few seconds — it now detects the missing adapter on the first scan, logs it once, and stops scanning for the session instead of retrying endlessly
* ⚡ [feat(assistant)] : in Simulator mode the assistant's green-bean dropdown now lists ALL beans instead of only those in stock — so any past roast can be replayed for testing regardless of remaining weight; the list rebuilds automatically when the simulator is switched on or off while TilauScope is open, and already reflects the simulator state when TilauScope opens
* 🐛 [fix(assistant)] : Expert mode no longer starts with alarms wrongly suppressed — when TilauScope opened directly in Expert (saved level), the status line built before the level was known, defaulted to Guided, printed "🔕 ALARM-SET='…' SUSPENDED" AND actually silenced the alarms; Expert now applies its "alarms active, no 🔕/SUSPENDED" state from the very first paint. Switching level (Guided ↔ Expert) while OFFLINE also refreshes the status line immediately instead of leaving the previous banner stale
* ⚡ [perf(assistant)] : the live roast panel now does less redundant work on the real-time sampling path — the RoR readout only restyles when its colour band actually changes (it was re-parsing its style on every reading, even while merely monitoring between roasts), the drying advice and phase-progress bars no longer recompute identical values every cycle, the extra-counters panel refreshes at ≤ 1 Hz instead of on every reading, and the BT/ET min/max sub-line only redraws when a new extreme is reached; no visible change, just a lighter CPU load during roasting
* 🐛 [fix(routine-check)] : the cleaning-cycle roast history now honours the weight unit stored in each profile — batches recorded in Kg/lb/oz were previously read as if they were grams (a 250 g roast logged in Kg showed 0.00 kg), skewing the total and average; scanning also no longer misreads an unconfigured log folder and the auto-close timer no longer starts if you were already scrolling the list
* 🐛 [fix(flavor-wheel)] : the flavor selector's title and "N notes selected" counter are now translatable (the counter previously never localized), and the close button uses the theme palette instead of hardcoded colors
build 7
* ⚡ [feat(alarms)] : in Guided mode TilauScope is now the sole control authority — your alarms are still evaluated but their actions (heater/fan/SV/PID changes, milestone auto-marking, pop-ups, beeps) no longer fire, so they can't fight the roast plan; the status banner shows "🔕 ALARM-SET='…' SUSPENDED" when a set is loaded. Switch to Expert to hand alarm control back to yourself.
build 6
build 5
* 🐛 [fix(devices)] : a TRP roaster controller that announces its machine profile at connection now auto-selects the matching roaster in TilauScope (thermal indices, BT offsets, etc.) instead of requiring you to pick it manually in the device settings — recognized models each carry a stable ID so this keeps working even if the display name changes
build 4
* ✨ [feat(tilaulogger)] TRP in tilalogger is now detected
build 3
* ⚡ [feat(logger)] : the TilauScope logger's serial panel now has a "🤝 HELLO" button and auto-probes every new connection — sending the TRP handshake and, once a controller answers, replacing the plain "connected" status with the identified device and resolved roaster profile (or "generic" if unrecognized), making it obvious at a glance whether the wire is talking TRP
* ⚡ [feat(events)] : Serial Command actions (buttons/sliders) now support a `trp(<command>)` wrapper — e.g. `trp(SET HEATER {})` — to dialogue with a TRP roaster with the correct line termination, regardless of which device is currently selected
* ⚡ [feat(devices)] : new "TRP Roaster" serial device — connects any roaster controller speaking the Tilauscope Roaster Protocol (USB serial) over the standard Serial Port configuration, the same as any other serial meter; the controller identifies itself and its machine at connection, so a single device works across roaster models without a dedicated driver per machine. An optional "TRP Roaster (Heater/Fan)" extra device exposes the heater/fan readback
* 🐛 [fix(build)] : the build script now stamps BOTH the version and the build number into artisanlib/__init__.py, derived from the top `## [X.Y.Z]` / `build N` of this file (single source of truth) — previously it only bumped the build and left `__version__` frozen (stuck at 4.0.5 while the release was 4.1.0), so the app title bar and the What's New version gating showed a stale version
build 2
* 🐛 [fix(whatsnew)] : the What's New dialog now handles version jumps — updating across several releases at once shows the accumulated notes of every skipped version (up to your installed build), instead of only the single newest block; it also fixes a parsing bug where only the first rubric of a version was shown rather than the whole version. Tracking is now version-based (which version you last saw) rather than a content hash
build 1
* ⚡ [feat(assistant)] : on roasters that expose no controls to Artisan (they only report ET/BT), the assistant now hides the slider bar and the one-tap adjustment buttons — which could do nothing — and shows a read-only "Recommended settings — Burner 60% · Air 30% · Drum 75%" line per phase instead; milestone-marking buttons and the AirWave control stay available
* ⚡ [feat(assistant)] : in Guided mode, milestone detection now suggests instead of marking silently — when the DRY END or first-crack detector fires, the assistant surfaces a one-tap "👂 detected — tap to confirm" prompt (prominent button + single beep) so you stay in control of the mark. Expert mode keeps full hands-free auto-marking as before; a QSettings escape hatch (tilauscope/milestone_automark) can also force auto-marking in Guided
* ⚡ [feat(roast_plan)] : the per-phase heater is now learned from your past roasts — the median burner % you actually held through drying, Maillard and development (from same-bean, same-target-colour roasts) replaces the grid preset from the 3rd matched roast (blended from the 2nd); it already reflects your process/humidity/altitude tweaks on this machine, so those grid corrections are dropped to avoid double-counting, while the back-to-back heat-soak still applies on top. The plan PDF shows whether the heater came from your history or the grid
* ⚡ [feat(assistant)] : one-tap heater ramp — during Maillard, when the planned burner step comes due a "Set burner {N}%" button appears (amber as it approaches the trigger temperature, green once reached) and applies the value to the burner in a single tap; the assistant still never touches the machine without your click, and the info chip ("next 50% @168°") keeps announcing the upcoming step
* 🐛 [fix(assistant)] : the DRY END and FC marking buttons now light up in lockstep with the graph's "approaching" alert — the button now reads the exact same proximity signal the graph shows (Artisan's predictive engine, plus the acoustic first-crack burst) instead of its own diverging estimate, which could disagree badly (graph "1C in 0:52" while the button stayed dark); the temperature gap remains a fallback when the graph isn't publishing a prediction
* 🐛 [fix(assistant)] : the Maillard action buttons no longer overflow the panel — the "SC start" button moved to the Development page where second crack actually happens (it was dead weight on Maillard, and previously unreachable on Development), keeping each phase to a row that fits
* ⚡ [feat(roast_plan)] : the plan now knows how much to trust itself — a confidence level (low/medium/high, shown on the PDF) derived from how much of the plan is learned from your history and how consistent that history is; the coach's RoR verdict and the end-of-roast trajectory thresholds adapt accordingly: forgiving on a fresh bean (grid plan), demanding on a bean you've mastered, and a noisy history (scattered measurements) is automatically downgraded rather than trusted
* 🐛 [fix(roast_plan)] : a never-roasted bean no longer shows "learned (n=N)" — when a bean has a BeanCave identity and no roast file carries it, the plan now correctly uses the grid instead of silently borrowing history from other coffees whose filename shares a word (variety names like "Caturra" matched other lots); the fuzzy name matching remains available for legacy beans without an identity, and legacy files can be re-linked to a bean via Repair ALogs
## [4.0.4] 2026-06-15
build 222
* ⚡ [feat(roast_plan)] : the drop temperature is now learned from your measured roast colours — each past roast of the bean with a colour reading (result form or colorimeter) teaches where it actually lands, corrected to the current target via the fleet-measured slope; adopted progressively like the learned FC (median from the 3rd roast, blended from the 2nd), kept within the style band ±3 °C, and the plan's action notes explain the adjustment
* ⚡ [feat(assistant)] : new "🚫 Exclude from learning" toggle in the end-of-roast summary — flag a botched roast (recovered stall, mis-marked milestone) and the plan learning (FC, timings, drop colour, master curve) will skip it forever; the flag travels with the saved roast file
* ⚡ [feat(roast_plan)] : back-to-back heat-soak correction — from batch 2 the plan lowers the charge temperature (preheat SV) and the initial dry burner according to the machine's thermal mass and the minutes elapsed since the previous DROP (exponential decay, ~−6 °C max on the Skywalker right after a drop, neutral after ~50 min); the plan notes explain the applied correction
* ⚡ [feat(assistant)] : the preheat page shows the active heat-soak correction under the SV countdown, and the cooling page's back-to-back advice now says what the next plan will correct and when the drum becomes thermally neutral ("next batch: charge −4.2° — neutral in ~22 min")
* ⚡ [feat(assistant)] : back-to-back armed relaunch — when a next batch is planned the cooling page offers a "Restart batch" button: below the between-batch temperature it relaunches immediately, above it a click ARMS the relaunch (amber "⏳ Armed", click again to cancel) and the sequence fires by itself when cooling crosses the threshold; the batch path skips the result form — the roast is saved incomplete silently (weight/colour to be filled later in Repair ALogs while the next batch roasts) — then reset, same bean and green weight re-injected, straight to preheat with the heat-soak-corrected plan, at any operator level
* ⚡ [feat(beancave)] : the Repair ALogs window now has a "🚫 Exclude from learning" toggle — flag or re-admit any past roast file for plan learning without reopening it in Artisan; excluded files show a 🚫 marker in the list and the flag is written immediately
* 🐛 [fix(artisan)] : the tilau_simulated and tilau_exclude_learning flags now survive an open-and-resave cycle — they are loaded with the profile, rewritten at save, and cleared on RESET so a fresh roast never inherits them; previously resaving a simulated roast silently laundered it back into plan learning
* 🐛 [fix(roast_plan)] : plan learning no longer trains on simulated roasts — profiles recorded under the Simulator were already flagged at save for the adaptive PID, but the plan's historical analysis (FC temperature, phase timings, master curve) still ingested them
* 🐛 [fix(assistant)] : the DRY END and FC START buttons no longer disable themselves once the bean temperature passes the theoretical target — marking the milestone is a mandatory manual operation; they now stay clickable past the target and turn amber to signal the mark is due
* 🐛 [fix(assistant)] : the Maillard static "RoR is high" ceiling (12 °C/min) no longer intercepts the plan-based verdict — with a plan target it hid the on-plan/deviation grading, the quantified burner advice and the post-adjustment ⏳ hold entirely; it now only applies as a fallback when no plan exists
* ⚡ [feat(assistant)] : the RoR verdict is now plan-first — when a plan target exists, ok/warn/crit is graded on the deviation from that target (±15/30%) instead of the generic phase bands, so a roast tracking its plan no longer reads "drifting" just because the planned slope sits outside the one-size-fits-all band
* ⚡ [feat(assistant)] : heater advice is now quantified against the plan — "burner 75% vs plan 60%" (live slider vs the planned phase heater) replaces the bare "reduce heater" whenever the gap points in the direction of the fault
* ⚡ [feat(assistant)] : the coach is now inertia-aware — after any burner move (operator or automatic ramp alarm) directional advice pauses for the machine's actuator lag ("⏳ burner 75→65% — effect in ~25 s", ~28 s on the Skywalker) and resumes early only if the deviation keeps worsening; crash alerts are never paused
* 🐛 [fix(assistant)] : anchored assistant pages are no longer clipped on the right — the hero metric's info line (now longer with the live "plan ±" read-out) was forcing the panel wider than its host; it wraps to a second line instead of silently truncating every page
* 🐛 [fix(roast_plan)] : the roast plan PDF report now fits on a single A4 page — the closing note no longer spills onto a second page, even when the AirWave rows are present (tightened row heights and section spacing, fonts unchanged)
* ⚡ [feat(roast_plan)] : the plan is now alive — at each real milestone (TP, DRY END, FIRST CRACK) the remaining planned curve, phase times, RoR targets and heater ramp re-anchor on the measured point; delays are absorbed (never chased by compressing the remaining phases), the drop temperature (colour) is untouchable and the projected DTR is steered back into the style band, with a warning when it can't be reached
* ⚡ [feat(assistant)] : a one-shot coach notice announces each plan re-anchoring ("Plan re-anchored at DRY END (+0:38 vs plan) — FC forecast 8:45, projected DTR 21.4%"); the end-of-roast trajectory verdict keeps comparing against the initial plan, so the report stays honest
* ⚡ [feat(roasters)] : development thermal-inertia coefficients revised per machine — graduated across the Kaleido family by batch mass, tabletop Cormorants no longer inherit the shop gas-drum value, IKAWA lowered — so heater-cut anticipation and drop targeting track each machine's real momentum (Skywalker values unchanged, empirically calibrated)
* 🐛 [fix(beancave)] : the probe deviation offsets are calibration deltas in °C by contract — the settings group no longer mislabels them with the display unit on Fahrenheit installs
* 🐛 [fix(roast_plan)] : historical roast analysis now respects each log's temperature unit — the quality filters (cold-charge, machine fingerprint), the master-curve BT series and the crash/flick sensitivity previously assumed °C logs, so Fahrenheit logs passed cold-charge checks they should fail, could be misclassified as radiant/drum, and over-triggered crash/flick notes
* 🐛 [fix(assistant)] : remaining Fahrenheit fallbacks aligned (default charge/ambient temperatures, DROP/FC countdown guards); BeanCave's "low RoR into first crack" advice now also fires on Fahrenheit logs; plans injected into an alog now declare their temperature unit
* 🐛 [fix(detection)] : Dry End auto-detection now works on Fahrenheit installs — the detection window is resolved in the roast's own unit (±9 °F, profession fallback band converted; it previously stayed in °C so the detector never armed) and the RoR morphology thresholds scale with the unit
* 🐛 [fix(preheat)] : on Fahrenheit installs the preheat SV was read in °C by the assistant page, the "close to target" banner and the SV slider mirror — the assistant declared "SV reached" (and latched the CHARGE button) on a cold drum; all readers now go through a unit-aware accessor
* 🐛 [fix(roast_plan)] : Fahrenheit installs now get a correct roast plan — all plan maths run in °C internally and are converted once on output; previously the dry-end anchor mixed °C and °F, producing a broken planned curve, a doubled "End of Dry" temperature, a wrong estimated TP and unscaled RoR targets
* ⚡ [feat(roast_plan)] : heater reductions are now staged through Maillard and applied ahead of first crack — earlier on high-inertia machines — via bean-temperature-triggered steps instead of a single late step at the FC event; the plan PDF shows the anticipated ramp
* ⚡ [feat(roast_plan)] : the "prepare to drop" alert now fires ~20 s before the planned drop temperature (bean-temperature based) instead of a static popup at first crack
* ⚡ [feat(assistant)] : development-phase DROP countdown now models the RoR deceleration (no more optimistic ETA) and shows the projected final DTR; the DTR verdict is based on where the roast will land, not where it currently is
* 🐛 [fix(roast_plan)] : exporting the alarm file no longer fails on roasters with a fixed-speed drum; drum slider alarms are skipped entirely for those machines
* 🐛 [fix(roasters)] : heater/airflow capability flags were always reported as present regardless of the machine definition
* ⚡ [feat(roast_plan)] : historical roasts are now matched by the bean's exact identity (BeanCave uuid stored in each log) instead of fuzzy filename matching — different lots of the same origin are no longer mixed together
* ⚡ [feat(roast_plan)] : the historical master curve and crash/flick notes now only use past roasts of a comparable batch size (±25% of the planned charge) — a 250 g batch no longer pollutes the reference envelope of a 450 g plan
* ⚡ [feat(roast_plan)] : the first-crack temperature is now learned from your past roasts of the same bean on the same machine (median of measured FC, adopted from the 3rd roast, blended from the 2nd) instead of a fixed per-colour grid value; the plan PDF shows whether FC came from history or from the grid, and the heater ramp, planned curve and drop targets all re-anchor on it
* ⚡ [feat(roast_plan)] : cross-roast calibration — planned drying/Maillard durations now follow the measured timings of your past roasts of the same bean (kept within the professional style window ±0.5 min), so the assistant coaches against a realistic clock instead of a one-size-fits-all grid
* ⚡ [feat(roast_plan)] : when a bean consistently dries or browns slower/faster than the style window, the plan now nudges the phase heater (bounded ±5%, from the 3rd roast) and explains the adjustment in the plan's action notes; the PDF shows whether phase timings came from history or the grid
* ⚡ [feat(assistant)] : ambient-triggered plan regenerations during preheat/drying no longer re-read the whole roast-log directory — the historical analysis (same bean, target and batch weight) is now cached for the session, keeping the UI responsive
* 🐛 [fix(assistant)] : the development-phase "RoR crash — DROP now" alert no longer fires (and beeps) through the normal finish of a dark roast — the crash threshold now follows the plan's target drop RoR (0.6×, floor 0.8 °/min) instead of a fixed 3 °/min
* ⚡ [feat(assistant)] : drying and Maillard pages now track the planned curve live — a "plan +0:15 / −0:40" read-out shows how far ahead/behind the roast is, and the RoR verdict compares against the planned slope at the current curve position instead of the static phase average (early Maillard no longer falsely reads "above plan")
* 🐛 [fix(assistant)] : the predicted colour in the end-of-roast summary is now frozen at DROP — it no longer drifts lighter minute after minute while the beans cool (the model was being fed the falling cooling-tray temperature and a still-running clock)
* 🐛 [fix(assistant)] : removed the development-page Omniflux colour-bias computation — it compared the sensor's raw reading (~465, not on the Agtron scale) against the 0–130 model prediction, accumulating a meaningless bias on every refresh without ever using it
* ⚡ [feat(assistant)] : the Maillard page now announces the next anticipated heater step ("next 48% @170°") so the automatic ramp no longer moves the sliders by surprise, and its first-crack countdown models the RoR deceleration toward the planned FC slope (the baked-risk projection no longer under-warns)
* ⚡ [feat(assistant)] : the drying page now warns when the projected drying time overruns the plan (which is calibrated to the bean's own history) by 20%/40% — the time-based counterpart of the Maillard baked-risk check
* ⚡ [feat(assistant)] : lighter live plan-tracking — the per-second plan-curve lookup no longer copies curve arrays on every temperature sample, keeping the guided display smooth on slower machines
* 🐛 [fix(assistant)] : the batch weight handed to the roast plan is now converted to grams from the user's Artisan weight unit (Kg/lb/oz) — a non-gram unit previously produced a wrong plan and silently disabled all history-based learning (batch filter, learned FC, timings); the same conversion now also feeds the roast result form
* 🐛 [fix(assistant)] : Fahrenheit mode is now handled correctly throughout the assistant — all RoR bands, temperature spans and slope thresholds scale ×1.8 (preheat, drying, Maillard, crash detector), the cooling "beans not cooling" alert works again (its RoR thresholds were converted as absolute temperatures, making it unreachable), and the predicted-colour model converts BT to °C before applying its calibrated coefficients; Celsius behaviour is unchanged
build 221
* 🎨 [ui(build)] : release manager & translation editor redesigned — toolbar split into readable rows (no more clipped buttons/fields), Source and Translation boxes now grow to fit long strings, a full-width readable status bar replaces the tiny bottom-left text, the build/wiki counters no longer truncate, and "Purge vanished" is moved away from Save
* 🐛 [fix(build)] : translation editor — the search box is usable again; typing no longer steals focus to the translation field after the first character, and the search now spans every context (it auto-jumps to the first context that has a match and shows a per-context result count)
* 🐛 [fix(build)] : translation editor — "Purge vanished" no longer discards unsaved translations; it now prompts to save first and writes a timestamped backup of every .ts file before deleting anything
* 🐛 [fix(build)] : translation editor — unsaved changes are now visible (● in the window title and on the Save button, which is greyed out when nothing is pending)
* 🐛 [fix(build)] : translation editor — clearing/filtering to an empty result now empties the edit panel instead of leaving it editable on a stale message from another context
* 🐛 [fix(simulator)] : starting the simulator on a profile with no recorded curve (e.g. a roast plan) no longer silently blanks every reading (BT/ET/counters all "-.-") — it now aborts with a clear message asking you to open a past roast recording first
* 🐛 [fix(displayscope)] : returning to Artisan while a roast/simulation is still sampling no longer orphans the graph — the curves keep drawing and re-opening TilauScope no longer crashes
* ⚡ [feat(canvas)] : faster roast-graph annotation refresh — colour palettes and phase-title map are now built once instead of on every update, and a redundant label resize per frame was removed
* 🐛 [fix(canvas)] : roast annotation no longer skips a frame or drops the rest of a graph redraw when a temperature reading is momentarily missing
build 220
build 219
* ⚡ [feat(canvas)] : in Guided mode the roast graph annotation can now be switched between a simplified coach view (one key message + verdict per phase) and the full expert data table, via a small toggle pinned to the top-left corner of the graph
* 🐛 [fix(canvas)] : coach view no longer advises "Ready to DROP" early in development — the drop verdict now follows the development ratio reaching its target, not just bean temperature, so an under-developed roast correctly reads "let it ride"
* 🐛 [fix(canvas)] : in the Maillard phase the coach now warns "1C approaching" from the predicted time-to-first-crack instead of staying on "Steady browning" until the very last moment (no microphone required)
* 🐛 [fix(devices)] : the roaster model dropdown in Tilau Configuration now uses the dark Mocha background instead of showing through as transparent/white behind the list
* 🐛 [fix(devices)] : the two checkboxes in the "Overlay & Notifications" box are no longer cramped together — they now have proper spacing and padding
build 218
* ⚡ [feat(whats_new)] : the What's New window now reads a short, dedicated user changelog instead of the full developer history — it shows only the latest version's highlights, downloads a tiny file, and re-appears only when those highlights actually change (no longer on every build)
build 217
* 🐛 [fix(tilaupid)] : heater/fan power changes from the preheat PID are now marked as special events in Artisan again — every change is recorded with its real power level instead of being collapsed into the first event
build 216
* 🐛 [fix(roast_properties)] : the TilauPID preheat command now fires on the Artisan START button instead of the ON (monitor) button, and the legacy command left on ON/OFF is cleared automatically
* ⚡ [feat(beancave)] : new "Data" button on the Roast Viewer tab opens a readable Data Reader window — milestones, special events and data columns laid out clearly, with a left-side navigator to jump milestone to milestone, a phase metrics overview (drying / Maillard / DTR), a Time axis starting from the very beginning of the recording so the preheat phase is explorable too, and an All / Milestones / Events filter
* 🐛 [fix(beancave)] : opening the Roast Result dialog no longer reloads the profile from disk when it is already the open roast in Artisan — your unsaved edits (ground/whole colour, weights…) are kept instead of reverting to 0
* ⚡ [feat(roast_assistant)] : la liste des grains de l'assistant ne propose plus que les grains en stock (stock > 0)
* ⚡ [feat(beancave)] : le bouton "roast" est grisé quand le grain sélectionné est en rupture de stock (stock à 0)
* 🐛 [fix(canvas)] : live events — température BT affichée avec un seul "C" au lieu de "CC" (self.mode était concaténé deux fois)
* ⚡ [feat(roast_assistant)] : en mode Guided, le bouton start/stop de l'assistant est masqué — l'assistant démarre et s'arrête automatiquement avec le bouton START/STOP d'Artisan ; le bouton reste visible uniquement en mode Expert
build 215
* ⚡ [feat(canvas)] : annotation — palette de couleur consolidée : 6 clés mortes supprimées de _format_annotation_text, 2 de _get_pid_text ; BT colorié sur l'approche de la cible (pas le Target fixe) en phases CHARGE/DE ; BT et ET coloriés indépendamment en phase DROP ; DEV Ratio coloré en jaune/rouge si sous-développé et drop imminente ; FC counter à 3 paliers blanc/jaune/rouge calés sur le seuil de burst auto-FC configuré
* 🐛 [fix(canvas)] : annotation phase FC/SCs/SCe — BT passe en rouge lors de l'approche de la drop temp (et non au dépassement) ; si phases[3] n'est pas configuré BT reste blanc au lieu d'être rouge en permanence
* 🐛 [fix(canvas)] : labels "DEV Time" et "DEV Ratio" distincts dans l'annotation FC (les deux affichaient "Development Phase")
* 🐛 [fix(canvas)] : Agtron et RoC sur deux lignes séparées dans toutes les phases (uniformise le format CHARGE/DE sur celui de FC)
* 🐛 [fix(canvas)] : guard Omniflux uniformisé sur hasattr() dans toutes les phases ; suppression de l'entrée morte "init" dans _phase_map
build 213
build 212
* ⚡ [feat(ai_support)] : le sélecteur de modèle IA est maintenant un champ libre — le bouton "↗ Browse" interroge l'API du fournisseur pour lister les modèles disponibles (fallback sur la liste par défaut si pas de clé ou si l'API est indisponible)
build 211
* 🐛 [fix(tilauscope_types)] : all three non-Agtron colour conversions corrected against authoritative sources — Tonino formula revised from the 13-pair OLS fit in the official Tonino-App calibration files (was off by ~30 Agtron points at a medium-dark roast); ColorTrack corrected to native pass-through after the SCAA cupping standard (SCAA_COFFEE_COLOR.pdf) confirms CT=62 ↔ Agtron Gourmet=63 within ±1 tolerance — it is effectively the same scale; Probat Colorette 3b corrected from the SCAA anchor (Col3b=96 ↔ Agtron=63, scale 0–200 per Probat) using a proportional-through-origin formula — the previous formula gave 95.8 where the calibrated reference is 63.0
* ⚡ [feat(brew_advisor)] : the degassing / rest window is now a single shared model used by both the Brew Advisor and the Brew Planning timeline, so the two can no longer disagree — it is roast-coupled on BOTH ends (dark roasts are ready sooner and go stale sooner, light roasts are ready later and hold longer: dark d+2→14, medium d+3→18, light d+5→25, very light d+7→30) based on the published finding that a light roast degasses about 3× slower than a dark one
* ⚡ [feat(brew_advisor)] : espresso and moka now expect a slightly longer rest than filter for the same beans (window shifted +3 days), because pressure brewing is more sensitive to residual CO₂ — the pre-infusion length follows the same roast/method-aware window
* 🐛 [fix(roast_timeline)] : the Brew Planning timeline now reads roast colour through the same shared converter as the rest of the app — non-Agtron meters (ColorTrack/Colorette/Tonino) are approximated instead of being discarded to a generic medium, a genuinely missing reading shows "N/A" with a neutral medium window, and the legend reflects the four evidence-based degassing bands
* ⚡ [feat(tilauscope_types)] : roast-colour → Agtron conversion is now centralised in one shared function used by the whole app (Brew Advisor, roast plan, roast assistant, brew-planning timeline) — they can no longer drift apart with three slightly different formulas. Agtron is the only normalised roast-level scale, so other meters (Tonino, ColorTrack, Colorette) are APPROXIMATED rather than rejected (an approximation is more useful than no value); the coefficients are flagged as empirical and pending validation. Only a genuinely missing reading falls back to a neutral medium-light level instead of defaulting to the darkest one
* 🐛 [fix(brew_advisor)] : brew temperature is now a coarse anchor set only by roast level and shown in whole degrees — the sub-degree tweaks for water, weight-loss and bean development were removed because, at a fixed strength and extraction, brew temperature has little sensory impact (grind, time and ratio are the real levers); the displayed temperature no longer implies a false 0.1° precision
* ⚡ [feat(brew_advisor)] : water guidance now treats hardness on two correct axes instead of one "hard/soft" slider — GH (calcium/magnesium) raises extraction (grind slightly coarser when high), while KH (bicarbonate/alkalinity) buffers and mutes acidity (flagged as a flavour effect), reflecting the published water-chemistry research
* 🐛 [fix(brew_advisor)] : dropped unsupported folklore adjustments — process (natural/washed) no longer caps or floors the temperature, variety (Geisha) no longer changes the grind, and origin is judged by measured altitude only rather than a hard-coded country list
* 🐛 [fix(brew_advisor)] : the "stale coffee" advice no longer claims a finer/hotter brew "recovers sweetness" (oxidative staling is largely irreversible) — it now simply flags that the cup will read flat; the freshness window is also coupled to roast level, since darker roasts degas faster and are ready sooner
* 🐛 [fix(brew_advisor)] : the water-balance note no longer appears when you have entered no water information at all — the advisor only comments on water when you pick a profile or enter a GH/KH measurement, instead of silently asserting a "balanced SCA" water it cannot know
* 🐛 [fix(brew_advisor)] : the espresso pre-infusion length now uses the same roast-aware freshness window as the rest advice — a still-degassing light roast gets the longer saturation for a few more days than a dark roast, which is ready sooner
* 🐛 [fix(brew_advisor)] : tidied internal consistency — an unknown roast colour now reads "N/A" in the AI refinement context (instead of 0), and AI temperature tweaks are rounded to whole degrees like the rest of the recipe
* 🐛 [fix(brew_advisor)] : espresso and moka recipes no longer show a nonsensical "stir / high agitation" instruction for high-altitude or uneven-roast beans — agitation advice now only overrides the puck/pre-heat prep for brew methods where you actually agitate a slurry (pour-over, immersion, etc.)
* 🐛 [fix(brew_advisor)] : the optional AI refinement is now anchored on extraction science instead of generic "world-class barista" intuition — it is told to reason from the real levers (grind/time/ratio → TDS & extraction yield, temperature being a weak lever at fixed extraction), to treat water as GH vs KH separately, and not to invent process/variety rules or claim staling can be brewed away
build 210
* ⚡ [feat(roast_asssistant)] : the end-of-roast ROAST SUMMARY now adds a "Trajectory vs plan" read-out — for each phase (drying / maillard / development) it shows how far your actual bean-temp curve ran above or below your planned curve (e.g. "+6° hotter"), colour-coded, with a one-line plain-language verdict; the comparison is time-normalised so it judges the curve shape, not whether the roast ran a little longer or shorter, and the block only appears when a roast plan curve is available
* ⚡ [feat(beancave)] : the multi-roast Advanced Stats dot plot gains two Roast Area (AUC) rows — total roast area and development-phase area per roast, shown as a consistency spread (each row scaled to its own range, reference roast ringed) so area drift between batches stands out; only added when the roasts carry AUC data, and works on any roaster, not just one model
* 🐛 [fix(beancave)] : the coach advice that compares a value to a threshold (DTR, weight loss) no longer drops its trailing text — the "less than / greater than" symbols were being swallowed as HTML by the advice panel, so "DTR low … (11.4% < 12%, 1.0 min)" lost everything after the percentage; the symbols are now escaped and the stray parenthesis removed
* 🐛 [fix(beancave)] : the drying and Maillard phase checks now allow a 30-second grace band around the learned range, so a minor drift past your usual range (e.g. 4.3 min against a 4.6–6.7 min range) reads as on-target instead of raising a warning; development keeps its hard professional floor
* 🐛 [fix(beancave)] : corrected the roast-level DTR direction (it was inverted) — lighter roasts run a lower development ratio and darker roasts a higher one, so a light roast at a low DTR is no longer wrongly flagged as short development; and when the absolute development time is adequate, a low ratio is now reported as information ("the ratio is low because the front is long") instead of a contradictory "extend development" warning that clashed with the on-target development time
* 🐛 [fix(beancave)] : the weight-loss summary badge and the Coach's Advice now use one shared window so they can no longer disagree (a light natural at 13.6% was showing "Normal" in the badge yet "Low" in the advice) — the floor follows the roast level and a high-retention process (natural/honey/anaerobic) only widens the upper bound rather than raising the floor
* ⚡ [feat(beancave)] : the single-roast Coach's Advice is now roast-level aware end to end — drop temperature, weight loss and development are judged against the window expected for the target colour (light / medium / dark) instead of a one-size-fits-all medium assumption, so a deliberately light roast (low drop temperature) is no longer flagged as under-developed; development time follows the professional-convention window per level in absolute minutes (a sound light development of 1:00–1:30 reads on-target, independent of the development ratio), while drying and Maillard are compared to your own past roasts at the same colour; the wording is softened to observations ("shorter than usual / your usual range / standard for this level") with the red flag reserved for cases where two independent signals (low drop temperature and short development ratio) agree — the drop-temperature cross-check now also works in °F
* ⚡ [feat(beancave)] : the single-roast analysis now reads the rate-of-rise at the onset of first crack — a flat or negative RoR entering FC is flagged as a stall/crash risk (lost momentum into development), independent of roaster type
* ⚡ [feat(beancave)] : the multi-roast comparison adds a difference strip under the chart — each roast's bean-temperature gap to the reference (ΔBT) is drawn against a flat zero line, so small divergences (a couple of °C) that are invisible in the overlay stand out; in the Aligned view it shows the pure shape difference per phase
* ⚡ [feat(beancave)] : the multi-roast Advanced Stats now opens with a plain-language analysis — a couple of sentences that judge how consistent the roasts are, call out the single biggest difference (drop temperature, development time/ratio or total time), comment on whether the development ratios sit in the usual window, and flag any RoR crash or flick after first crack (a sign of stalled, uneven development) — above the dot plot and the notable-differences list
* ⚡ [feat(beancave)] : the multi-roast Advanced Stats tab was simplified for home roasters — the dense comparison table is replaced by a dot plot (one row per metric: total/drying/maillard/development time, DTR, drop temperature, weight loss; one dot per roast, the reference ringed) topped by a short "notable differences" summary
* 🐛 [fix(beancave)] : all the new multi-roast comparison text (chart axes, phase ribbon, dot plot, analysis and coach advice) is now translatable — strings reuse existing translation entries where they exist instead of adding duplicates — and the temperature/RoR thresholds it relies on (consistency verdict, drop spread, RoR crash/flick detection, RoR target) are scaled for Fahrenheit so the analysis reads correctly in °F as well as °C
* 🐛 [fix(beancave)] : hovering in the Consistency/Aligned views now matches what is drawn — in Consistency the tooltip and markers stick to the reference roast (no more phantom markers for roasts shown only as a band, plus a BT spread readout), and in Aligned the tooltip/markers show BT only (RoR/ET are hidden in that view)
* ⚡ [feat(beancave)] : the multi-roast comparison header now states which view is active (Overlay / Consistency / Aligned), the Overlay/Consistency/Aligned toggles have distinct icons, and each carries an explanatory tooltip describing what the view is for and how to read it
* ⚡ [feat(beancave)] : the multi-roast comparison gains an "Aligned" view (second toggle on the chart, mutually exclusive with Consistency) — it time-warps every roast so their milestones (CHARGE, TP, DRY END, FC start, DROP) line up with the reference, letting you compare the bean-temperature shape phase by phase regardless of how long each phase actually took; only BT is shown (RoR is hidden because warping time distorts its scale)
* ⚡ [feat(beancave)] : the multi-roast comparison gains a "Consistency" view (toggle on the chart, top-left next to the zoom button) — instead of every curve, it draws the reference roast as a solid line with a shaded min–max band across all the roasts — for both bean temperature and RoR — so you can see at a glance how repeatable your roasts are (the band tightens where you are consistent, widens where you drift)
* ⚡ [feat(beancave)] : the multi-roast comparison now shows a phase-balance ribbon under the chart — one horizontal bar per roast split into Drying / Maillard / Development percentages (the development share is the DTR), with the roast name and total time on the left, for an at-a-glance read of how the phase balance differs between roasts without reading the curves
* ⚡ [feat(beancave)] : when exactly two roasts are compared, each milestone box on the chart now also shows the time/temperature gap (Δt / ΔT) of the reference versus the other roast — the comparison data sits right next to the curve where it is useful; with three or more roasts the boxes stay clean (label, temperature, time only)
* 🐛 [fix(beancave)] : the comparison milestone boxes now sit just above their point on the curve instead of being pinned to the top of the chart — in full-screen/zoom they no longer float far away from the curve with a big empty gap
* 🐛 [fix(beancave)] : the Advanced Stats comparison table row labels are slightly brighter for better legibility on the dark background
* ⚡ [feat(beancave)] : in the multi-roast comparison the reference roast is now drawn bold and fully opaque while the other roasts are dimmed back, so the curve you care about stands out instead of competing with a stack of equally bright colours
* 🐛 [fix(beancave)] : the multi-roast comparison legend no longer squashes the chart when many roasts are compared — roast names are truncated and the legend is kept to at most two rows, so the plotting area stays a sensible height
* 🐛 [fix(beancave)] : the Roast Viewer curves are drawn with thinner lines (single and comparison views) — the previous thicker strokes looked heavy and blurred detail where curves overlap
* ⚡ [feat(beancave)] : in the multi-roast comparison view each roast now gets its own distinct colour (instead of near-identical shades of the same hue that made overlapping curves impossible to tell apart) — the data type is shown by line style instead: BT solid, RoR dashed, ET a thin dotted line; the bottom legend reflects this exactly
* ⚡ [feat(beancave)] : the multi-roast comparison view was redesigned for legibility (inspired by HiBean) — the old cluttered 3-entries-per-roast legend is gone, replaced by a compact bottom legend (one coloured chip per roast, the reference tagged "ref", plus a BT/RoR/ET line-style reminder); the key milestones (CHARGE, TP, DRY END, FC start, DROP) of the reference roast are now marked with discreet guide lines and a clean top label band showing each milestone's temperature and time, kept readable whatever the number of roasts compared (the milestone gaps versus the reference move to the Advanced Stats table rather than crowding the chart)
* ⚡ [feat(beancave)] : the Roast Viewer chart text is now larger and more legible — titles, axis labels, tick numbers, event markers and legends were bumped up from the previous tiny 7–9px sizes and centralised so they stay consistent across the single and comparison views
* ⚡ [feat(beancave)] : the Roast Viewer curves are now easier to read — the temperature axis auto-fits each roast (keeping a little headroom above the bean-temp peak) instead of always spanning a fixed 0–300°, so the curve fills the chart instead of sitting in the lower third; the RoR lines are thicker, the axis labels higher-contrast, the chart background matches the dark theme (no more black margins), and the rendering is sharper on Retina/HiDPI screens — applied to both single and multi-roast comparison views
* 🐛 [fix(roast_plan_model)] : roast plans now respect a Fahrenheit Artisan setup — the engine was always computing in °C because it read the temperature unit from a wrong attribute, so °F users got plans with °C numbers; it now reads the live unit correctly
* 🐛 [fix(roast_plan_model)] : generating a plan for a bean with an empty/symbol-only name no longer crashes the whole plan generation (historical-log matching guarded against a divide-by-zero)
* 🐛 [fix(roast_plan_model)] : historical roasts where First Crack was never marked no longer mislabel their Maillard phase as Development — ambiguous segments are now excluded from the crash/flick phase statistics instead of being miscounted
* 🐛 [fix(roast_plan_model)] : the computed RoR-at-drop now always stays below the development-average RoR (guaranteed deceleration into the drop) even on very gentle profiles, where it previously could be reported slightly higher
* 🔧 [chore(roast_plan_model)] : phase-duration variables that actually hold minutes are renamed from the misleading `*_in_sec` suffix to `*_min`, removing a latent ×60 trap for future edits (no behaviour change)
* 🐛 [fix(roast_plan_model)] : the colour-based drop-temperature correction is now bounded to ±6 °C — for very light targets it previously computed an unphysical -20 °C shift (only hidden by the later clamp); the ±6 envelope matches the drop-vs-Agtron slope measured across 144 real roasts and avoids over-shifting dark drops
* 🐛 [fix(main)] : starting the simulator with no file open now displays the profile you pick in the file dialog on the chart — previously the curve stayed blank unless the file had been loaded beforehand
* 🐛 [fix(canvas)] : clicking the chart's axis labels no longer pops open Artisan's Roast Properties dialog — the single-click upper-left-corner shortcut is disabled (double-click to open the online roast link is unchanged)
* 🐛 [fix(roast_properties)] : auto-saved roast filenames no longer contain stray '~' characters and doubled separators — the default filename template now uses Artisan's single-leading-tilde token syntax (e.g. "Title_26-06-21_1702.alog" instead of "Title - 2025~_26~-06~-21~_17~02~.alog")
* ⚡ [feat(tilaupid)] : the preheat approach is now governed by a continuous law (the burner tracks a target rate-of-rise that eases off as the drum nears the target) instead of fixed power steps — this removes the ~1 Hz burner on/off oscillation near setpoint and gives a gentler, lower-overshoot approach (verified by replaying a real roast: bang-bang swings dropped from 9 to 1, the remaining one being the normal cut at target)
* 🐛 [fix(tilaupid)] : the preheat burner is now hard-capped at 80% — adaptive learning can only lower it, never raise it above the cap, preventing the radiant element from being driven hot enough to trip the roaster's thermal cutoff
* 🐛 [fix(tilaupid)] : added an absolute over-temperature safety cut — if the drum runs more than 2°C past the target, the burner is force-cut (and the damper opened when fan-assist is on) regardless of phase, reclaiming control before the roaster's own shutdown
* 🐛 [fix(tilaupid)] : the burner command is now smoothed (deadband + slew-rate limit) to stop the ~1 Hz on/off oscillation near setpoint; an emergency cut to 0 still applies instantly
* 🐛 [fix(tc4ble)] : ET et BT du Skywalker correctement inversés — les sondes physiques du firmware sont en ordre inverse (field[1]=tambour, field[2]=grains), la calibration est désormais alignée
* ⚡ [feat(tilaupid)] : the preheat hold power now adapts — it is scaled by ambient conditions (±15%, e.g. more power in a cold room) and, once enough roasts exist at a given setpoint, converges to the learned hold level; only the steady hold is affected, not the ramp or braking
build 209
build 208
* 🐛 [fix(displayscope)] : the header no longer jitters every second — the timer now uses a bundled monospaced font (JetBrains Mono) with a fixed width, so the control buttons stay put as the digits change
* 🐛 [fix(tilaupid)] : running a preheat in Simulator no longer trains the real PID — no learned correction is stored while simulating, and a roast saved while simulating is tagged and skipped by the learning scan (reading your learned profile still works, so simulations stay realistic)
* 🐛 [fix(tilaupid)] : preheat cross-roast learning now reads the channel the PID actually followed (BT or ET, from the roast's saved PID source) instead of always reading the wrong channel — past-roast metrics are no longer computed on the unused signal
* ⚡ [feat(roast_properties)] : the TilauPID setup card now lets you pick the PID input channel (BT or ET) inline with the target temperature — the choice is applied to Artisan's PID source at OK
* 🐛 [fix(tilaupid)] : the preheat PID now actually re-applies its ambient (temperature/humidity) correction during the roast — it was computed once at start and silently never refreshed
* 🐛 [fix(canvas)] : invalid ET/BT readings no longer leak as a fake 0°C value to TilauScope — prevents false post-DROP cooling detection and bogus min BT tracking
* 🐛 [fix(canvas)] : the dEVENT math symbols (dCHARGE, dDRY…) now use the correct bounds check for the CHARGE event
* 🐛 [fix(canvas)] : tidy dead code (duplicate MQTT 910 device, unused LCD formatter, screen-saver thread-state test) with no behaviour change
build 207
build 206
* 🐛 [fix(beancave)] : sorting the bean table by a column no longer risks acting on the wrong bean — roast, edit, delete and QR now always target the bean you actually selected
* 🐛 [fix(beancave)] : accented text (bean names, notes) in roast profiles saved by Artisan now displays correctly instead of garbled characters
* 🐛 [fix(beancave)] : roasted-weight totals are now normalised to grams across profiles saved in different units (g/Kg/lb/oz) instead of being summed blindly
* 🐛 [fix(roast_properties)] : the preheat PID command is now correctly assigned to the ON button as an IO Command (previously landed on OFF with the wrong command type); legacy entries on OFF are cleaned up
* 🐛 [fix(roast_assistant)] : live ambient temperature read from a T1 extra device now uses the correct probe channel instead of always reading T2
* 🐛 [fix(roast_assistant)] : a genuine 0.0 ambient reading is no longer discarded as "missing"
* 🐛 [fix(displayscope)] : the F2–F8 keyboard shortcuts (DRY END, FC, SC, DROP, COOL) now mark their milestones again — they were silently inactive
* 🐛 [fix(displayscope)] : the roast assistant now stops automatically when you STOP the roast from the main button, not only from its own toggle
* 🐛 [fix(displayscope)] : remove the leftover hidden PID button and its L/R shortcuts — PID is now handled entirely through Artisan
* 🐛 [fix(displayscope)] : auto cooling detection now arms whichever way DROP is marked (TilauScope, keyboard or Artisan's own button)
* 🐛 [fix(displayscope)] : mirroring Artisan's slider values into TilauScope no longer pushes spurious actions back to Artisan
* ⚡ [feat(displayscope)] : a red-on-amber notice now appears in the status zone whenever the roast is driven by an Artisan automation — PID (from CHARGE), Replay Events, Auto-DROP or Playback Aid
* 🐛 [fix(displayscope)] : the automation warning dialog no longer pops up again when pressing STOP — it now only appears at START
build 205
* ⚡ [feat(displayscope)] : operator level selector — single compact button in header toggling Guided ↔ Expert (letter + colour), defaults to Guided
* ⚡ [feat(displayscope)] : remove the engage/anchor assistant buttons from the main button bar — Guided anchors the assistant by default and floats it from the advice zone, Expert is main panel only
* ⚡ [feat(roast_assistant)] : anchor/float toggle relocated to the GREEN BEAN header of the advice zone, shown in Guided level
* 🐛 [fix(roast_assistant)] : keep all assistant tooltips dark-styled when embedded in anchored mode (anchor button, green-bean/target dropdowns, start/stop, and any descendant via a body-level rule)
* 🐛 [fix(displayscope)] : stop the window from growing when toggling the controls between sliders and cards — the control zone height is now locked so the switch is size-neutral
* 🐛 [fix(displayscope)] : block START when no device is configured — show a clear message instead of Artisan's blocking manual temperature dialog
* ⚡ [feat(displayscope)] : guided assistant auto-starts and anchors automatically from the Beancave → RoastSetup workflow
* 🐛 [fix(roast_assistant)] : always identify the current bean on TilauScope open, not only when assistant is already anchored
build 204
* 🐛 [fix(displayscope)] : rebuild the main menu without stripping Artisan's native menubar, so entries persist
* ⚡ [feat(displayscope)] : anchor the roast assistant in place of the main control panel via a header toggle
* ⚡ [feat(roast_assistant)] : make the assistant body detachable for floating or anchored hosting
* 🐛 [fix(roast_assistant)] : keep the assistant body themed after returning from anchored to floating
* 🐛 [fix(roast_assistant)] : size the anchored panel to the active page to remove the spurious scrollbar
* 🐛 [fix(roast_assistant)] : restore green-bean identification when opening the assistant in anchored mode
* ⚡ [feat(tilau_intelligence)] : fuse FC+SC crack counters pre-fire to absorb build-dependent channel attribution
* ⚡ [feat(tilau_intelligence)] : expose offset-corrected SC count after first crack for downstream consumers
* 🐛 [fix(tilau_intelligence)] : drop colour and RoC from first-crack triggering (DryEnd-only signals)
* 🐛 [fix(tilau_intelligence)] : remove dead channel-name lists superseded by classify_extra_channel
* 🐛 [fix(tc4ble)] : prevent stale poll/watchdog tasks from resurrecting after a fast BLE reconnect
* 🐛 [fix(beancave)] : restore water-activity label color on Lebrew AquaGauge power-off (full stylesheet + forced repaint)
* 🐛 [fix(tilaulogger)] : convert remaining source UI strings to English so translations are driven from the .ts catalogs
* 🐛 [fix(roast_assistant)] : correct initial phase resolution when activating mid-roast (post-CHARGE now opens Drying instead of Summary)
* ⚡ [feat(tilaulogger)] : alerting layer — per-source error counters, clickable sticky and collapsed-zone alert badges
* ⚡ [feat(tilaulogger)] : observability actions — manual marker, global render pause, snapshot-to-file, and on-demand garbage collection
* ⚡ [feat(tilaulogger)] : dashboard adds per-source freshness/cadence, open sockets & file-descriptor counts, and 60 s trend sparklines (CPU/memory/bus/UI-latency)
* ⚡ [feat(tilaulogger)] : per-zone live filtering with text/regex matching and level chips, backed by a buffered re-render
* ⚡ [feat(tilaulogger)] : global Ctrl+F search across zones with match navigation and highlighting
* ⚡ [feat(tilaulogger)] : central signal bus normalising all log sources into routed, per-level colourised zones with bounded buffers
* ⚡ [feat(tilau_intelligence)] : position-anchored First Crack detection (plan/profession window, pop-burst advancer gated at/above target, colour confirmation hook)
* 🐛 [fix(tilau_intelligence)] : crack-counter pops can no longer trigger FC on pre-FC over-count noise (burst must be at/above the target, never below)
* ⚡ [feat(displayscope)] : show event type and signed/percent offset value in extra-button tooltips
* 🐛 [fix(displayscope)] : correct extra-button action name lookup (account for Artisan action-code gap)
* 🐛 [fix(canvas)] : support extended event types (±%, types 10-13) in etypesf
* ⚡ [feat(main)] : Add GPLv3-compliant TilauScope fork attribution in About dialog
* 🐛 [fix(artisancore)] : integrates all the current fixes from current artisan version
* ⚡ [feat(tilaupid_adaptative)] : persistent cross-roast integral corrector for fuzzy-zone onset with anti-windup and SV-bucketed memory
* 🐛 [fix(tilaupid)] : inertia-aware power taper on predictive overshoot, removing the slow end-of-preheat creep
* 🐛 [fix(tilaupid_adaptative)] : slow-approach now self-corrects over roasts; undershoot and braking duration drive de-braking
* 🐛 [fix(tilaupid_adaptative)] : a below-SV plateau is no longer counted as a stable hold
* 🐛 [fix(tilaulogger)] : debug monitor window can now be sent to the background instead of always floating on top
* 🐛 [fix(util)] restore full-precision weight conversion constants
* 🐛 [fix(util)] guard weight/volume conversions against negative unit indices
build 203
* 🐛 [fix(alarms)] : AI audit model corrected — offset 0 carries no time trigger; offset 0 without a condition is reported as a dead alarm
* ⚡ [feat(alarms)] : local validation flags alarms that can never fire (offset 0 with no condition)
* 🐛 [fix(canvas)] : alarm trigger read the wrong sensor (selected by the From event instead of the configured source), causing wrong-channel comparisons, missed offsets and possible crashes during sampling
build 202
* ⚡ [feat(alarms)] : new rule-sentence alarm editor — each alarm reads as a plain sentence of editable chips, optionally grouped by roast phase, replacing the legacy table editor and the visual timeline (both decommissioned)
* ⚡ [feat(alarms)] : inline floating editor for every token (timing, condition, action, guard) with live commit and non-blocking consistency warnings, no layout shift
* ⚡ [feat(alarms)] : drag-and-drop to reorder alarms and to re-anchor them across phases
* ⚡ [feat(alarms)] : event-button actions show the target button content, and guard references are tracked by stable id so reordering never breaks them
* ⚡ [feat(alarms)] : AI consistency audit panel that reasons with the real alarm-loop firing model (tick cadence, one-shot, anchor + offset, guard timing, armed-latch conditions) and proposes concrete corrections instead of narrating the set
* ⚡ [feat(i18n)] : alarm editor reuses existing Artisan translation contexts where strings already exist, leaving only module-specific labels to translate
build 201
* 🐛 [fix(mqttbridge)] Fix bool payload serialization for switch commands (str(True) → "true"), default retain=False for commands
* 🐛 [fix(main)] Fix tilaumqtt signal type (str→object) to support bool/int/float values, add INFO-level trace for command path
* 🐛 [fix(main)] Coerce MQTT command value to bool/int/float/str before signal emit
* 🐛 [fix(canvas)] : sync airflow and drum sliders to the controller state on Skywalker (re)connect
* ⚡ [feat(tc4ble)] : expose live burner/airflow duty echoes as actuator extra-device channels
* 🐛 [fix(tc4ble)] : send integer OT duty and restore the dropped BLE write so slider commands reach the roaster
* 🐛 [fix(tc4ble)] : cancel in-flight BLE connect on teardown to prevent a half-open link blocking reconnection on macOS
* 🐛 [fix(settings)] : preserve TilauScope high-id devices through the extradevices range clamp so the mapping survives save/reload
* 🐛 [fix(canvas)] : harden LCD update — isolate TilauScope LCD signal emits so a failing display slot no longer aborts the remaining LCD refresh
build 198
🐛 [fix(roast_properties)] : default save filename now includes roast title alongside batch number and date/time
* ⚡ [feat(roast_properties)] : compute dev time and DTR from timeindex when statisticstimes is not yet available (pre-STOP)
* 🐛 [fix(label_printer)] : add _FONT_SCALE boost (×1.2) to global font scaling for improved legibility on printed A4 labels
* 🐛 [fix(displayscope)] Always hide Artisan message label on TilauScope open, not only during active roast
build 197
* 🐛 [fix(displayscope)] Prevent closing TilauScope while Artisan sampling is active
* 🐛 [fix(displayscope)] Close roast assistant panel when switching back from TilauScope to Artisan
* 🐛 [fix(displayscope)] Fix Artisan palette not restored on TilauScope close — defer LCD and canvas refresh to match existing deferred redraw timing
* ⚡ [feat(tilaulogger)] : add artisan.log live tail section (200 lines, 5s polling, Start/Stop control, rotation-aware)
* ⚡ [feat(tilaulogger)] : add baud rate selector (9600–921600) with QSettings persistence for port and baud
* ⚡ [feat(tilaulogger)] : replace auto-connect on port change with explicit Connect/Disconnect button
build 196
* 🐛 [fix(displayscope)] : fix residual blank space on Artisan canvas after closing TilauScope — defer matplotlib redraw until Qt layout is fully settled
* 🐛 [fix(roast_asssistant)] : fix Windows geometry warning loop on panel resize by replacing adjustSize() with explicit resize() avoiding MINMAXINFO conflict
* 🐛 [fix(roast_asssistant)] : suppress Dry End and AirWave STD buttons during post-charge stabilization by applying existing stabilizing guard to near_dry computation
build 195
* 🐛 [fix(roast_plan_model)]: generate_roast_plan no longer crashes when RoasterContext is None — guard drum-speed computation (drum_min_setting/drum_step_rpm) with generic fallbacks, completing ctx=None safety
* ⚡ [feat(canvas/main/alog_repair)]: device index — stable TilauScope extradevice remapping across Artisan version updates via tilau_name_map annotation in .alog profiles and additional feature to remap all from alog repair routine
* ⚡ [feat(alog_repair)]: batch "Stamp device map" action to retrofit tilau_name_map on legacy alogs using extraname1 label matching
build 194
* ⚡ [feat(tilaulogger)]: migrate TilauscopeLoggerWindow to frameless Catppuccin Mocha style with card shell, drag-to-move and QSizeGrip
* 🐛 [fix(tilaulogger)]: replace hardcoded hex colors with THEME constants throughout
* ⚡ [feat(tilaulogger)]: replace QToolBar with inline HBoxLayout controls row
* ⚡ [feat(tilaulogger)]: add port refresh button to serial controls row
build 193
* ⚡ [feat(menu_extension)]: consolidate all TilauScope actions into dedicated TilauScope menu
* 🐛 [fix(main)]: remove TilauScope actions from Config and Tools menus
* ⚡ [feat(devices)]: refactor TilauscopeConfigDlg to frameless Catppuccin Mocha style with custom title bar, drag-to-move and QSizeGrip
* ⚡ [feat(devices)]: restructure config tabs to General / Sensors / Detection / Integrations semantic layout
* ⚡ [feat(devices)]: add QCollapsibleWidget with animated expand/collapse for AirWave PID section
* ⚡ [feat(devices)]: disambiguate acoustic device threshold (TilauAmbient) from global FC algorithm threshold with distinct labels and tooltips
* 🐛 [fix(devices)]: consolidate BLE scan logic into single _start_scan() helper, eliminating per-device boilerplate
* 🐛 [fix(devices)]: fix bleTilauScopeautomarkFC desync with TilauScopeFCMarkFlag on save
* 🐛 [fix(devices)]: remove duplicate setMinimumSize() call and dead org_* snapshot attributes
* ⚡ [feat(mqttbridge)] Refactor TilauscopeMQTTClient to delegate paho transport to artisanlib.mqttport, eliminating duplicate MQTT stack while preserving independent broker connection
* ⚡ [feat(alog_repair)] : AlogRepairDialog and _AgtronPicker adopt TilauScope frameless Catppuccin Mocha chrome (container QFrame, custom title bar, drag-to-move, QSizeGrip resize, WA_TranslucentBackground)
build 192
* 🐛 [fix(artisan)] : latest artisan 4.0.4 roaster scope fixes
build 191
* ⚡ [feat(roast_insights)] : map roast-plan output (Target DTR, Total Time, First Crack Temp) and a roast-level weight-loss estimate into the INSIGHTS predicted targets
* ⚡ [feat(roast_properties)] : run TilauScopeRoastPlan in the INSIGHTS worker thread with an Agtron target-level selector; heuristics render instantly, plan-derived targets patch in place when ready
* 🐛 [fix(roast_insights)] : distinguish "enter green weight" from "roaster optimal capacity unknown" in the load note instead of a single misleading message
* ⚡ [feat(roast_insights)] : add Qt-free pre-roast insights engine mapping green-bean physical params (density, moisture, water activity, process) and setup load to phase implications, RoR cheat-sheet and a heuristic roast strategy
* ⚡ [feat(roast_properties)] : add ⓘ INSIGHTS tab to RoastSetupDialog with a non-blocking worker-thread panel (generation-token stale-result guard, 250 ms debounce, macOS-safe teardown) that recomputes live on field edits
build 190
* ⚡ [feat(roast_properties)] : move Physical properties block to OPTIONS tab and reduce RoastSetupDialog default height for small screens
* ⚡ [feat(beancave)] : add scale-piloted density measurement window (flask button next to density field) — live density = net×1000/volume with fixed volume selector (50/100/200/250/500 ml), signal-based density_picked/tare interface, secondary net weight + TARE
* 🐛 [fix(beancave)] : preserve roasted total weight when updating an existing green bean (stock edit no longer resets it to 0)
build 189
* 🐛 [fix(roast_properties)] : stash roast title and beans on aw at setup so reset() on ON/RESET cannot discard them
* 🐛 [fix(displayscope)] : restore stashed title and beans at DROP, fixing save filename falling back to batch designation and preserving .alog bean uuid linkage
* 🐛 [fix(roast_properties)] : rebuild qmc.weight as list to fix tuple item-assignment crash on roast result save
* 🐛 [fix(roast_properties)] : resolve roasted bean from qmc.beans (uuid lookup, text-parse fallback) when caller passes None/empty bean
* 🐛 [fix(displayscope)] : delegate end-of-roast bean resolution to RoastResultDialog instead of injecting an empty GreenBean*
🐛 [fix(roast_properties)] : rebuild qmc.weight as list to fix tuple item-assignment crash on roast result save
* 🐛 [fix(roast_properties)] : resolve roasted bean from qmc.beans (uuid lookup, text-parse fallback) when caller passes None/empty bean
* 🐛 [fix(displayscope)] : delegate end-of-roast bean resolution to RoastResultDialog instead of injecting an empty GreenBean
build 188
* ⚡ [feat(brew_advisor)] : first beta version released
* 🐛 [fix(beancave)] Marker context menu not showing intermediate events on Artisan files where unset slots default to 0: treat val==0 as unset (Artisan native convention) across all timeindex filtering logic
* 🐛 [fix(brew_advisor_dialog)] : retry AI refinement with backoff on transient provider errors (429/500/502/503/504 + network), absorbing Gemini overload 503s; persistent failure is silently ignored as designed
* ⚡ [feat(brew_advisor)] : Qt-free brewing engine — 7 methods anchored by roast level, pure modifier pipeline (density, weight-loss, development, process, origin, variety, water, rest, moisture, spread), code-based output for full i18n
* ⚡ [feat(brew_advisor)] : machine-aware espresso profile — 8 machine families driving pre-wet / pre-infusion / low-flow pre-brew / manual preheat / cooling flush, combined with roast level and degassing
* ⚡ [feat(brew_advisor_dialog)] : frameless two-column Catppuccin dialog with signal-based BrewAdvisorService — method/dose/water/machine selectors, live gram-scaled recipe, translated protocol & diagnostics, QSettings persistence, reserved Acaia live-extraction zone
* ⚡ [feat(brew_advisor_dialog)] : opt-in bounded AI refinement pass (gated on configured engine), merged inline with graceful no-op on empty/error/invalid JSON
* ⚡ [feat(beancave)] : route Barista Expert view to BrewAdvisorDlg, building BrewInput from roast + green-bean signals incl. days-off-roast degassing
* 🐛 [fix(beancave)] : fix legacy expert-recommendation bugs — to_agtron closure ignoring its argument, inverted weight-loss temperature sign, case-sensitive process/variety matching
* ⚡ [feat(brew_advisor)] : add Qt-free brewing engine — 7 methods (Espresso, V60, French Press, AeroPress, Pulsar, Weber Bird, Moka) anchored by roast level with pure modifier pipeline (density, weight-loss, development, process, origin, variety, water, rest, moisture, spread)
* ⚡ [feat(brew_advisor_dialog)] : add interactive Catppuccin dialog with signal-based BrewAdvisorService — method/dose/water selectors, live gram-scaled recipe, per-method pour protocol and diagnostics
* ⚡ [feat(beancave)] : route Barista Expert view to BrewAdvisorDlg, building BrewInput from roast + green-bean signals incl. days-off-roast degassing
* 🐛 [fix(beancave)] : fix expert-recommendation bugs — to_agtron closure ignoring its argument, inverted weight-loss temperature sign, case-sensitive process/variety matching, duplicated spread div 
* 🐛 [fix(roast_timeline)] : Brew planning bars now positioned from the .alog roastepoch instead of the file mtime, which shifted on copy/sync and clustered every roast near today
* 🐛 [fix(roast_timeline)] : Brew Ready toast recommendations now use roastepoch as the roast date, fixing wrong age/window computation on synced logs
* ⚡ [feat(beancave)] Right-click on BT curve in mono mode opens a contextual menu to reposition Artisan timeindex markers (CHARGE, DRY END, FC start/end, SC start/end, DROP, COOL end); candidates are filtered by click zone; markers, stats and save button update live after each move; an ephemeral overlay button commits the changes back to the .alog file
* 🐛 [fix(beancave)] BT/ET hover marker colors inverted: replace hardcoded 'green'/'red' with _PLOT_PALETTE values
* 🐛 [fix(beancave)] RuntimeError on rapid roast selection: guard _cancel_alog_thread mono path against deleted C++ QThread object
* 🐛 [fix(beancave)] Navigation reset to first file after background cache refresh: _on_alog_list_ready preserves current selection on subsequent refreshes
build 187
* ⚡ [feat(roast_asssistant)] Cache all static translated strings in Page widget __init__ to eliminate 100+ QApplication.translate() calls from 1Hz refresh() hot-paths
* 🐛 [fix(roast_asssistant)] Fix _PreheatPage: format() called inside translate key string caused untranslatable dynamic key on every cycle
* 🐛 [fix(roast_asssistant)] Fix RoasterPhysicsAdvisor.get_phase_advice(): raw English strings in advice.append() were not going through QApplication.translate()
* 🐛 [fix(whats_new)]: fix crash on app close during release notes fetch — disconnect worker signals and stop QThread with quit()+wait(2000) in closeEvent; connect parent.destroyed to trigger clean shutdown before Qt implicit child destruction
build 186
* ⚡ [feat(beancave)] Roast viewer list: display names now always prefixed with date/time (from roastepoch or filename pattern), use meta.title as base label when available, sort chronologically DESC
* ⚡ [feat(beancave)] Roast viewer list: automatic deduplication — colliding display names get [filename_stem] disambiguation suffix
* ⚡ [feat(alogmanager)] AlogMetadata: add roastepoch field extracted from .alog content (fallback to mtime) for reliable chronological sorting
* 🐛 [fix(beancave)] Roast viewer list: fix double-# in batch tag when batch_prefix already contains '#'
* 🐛 [fix(beancave)] Roast viewer list: fix filename pattern #N_YY-MM-DD_HHMM not matched by previous date regex
build 185
* ⚡ [feat(roast_properties)] : batch tracking in RoastSetupDialog (forecast) and RoastResultDialog (locked editor with explicit unlock); activation delegated from setup, counter assignment left to Artisan DROP
* ⚡ [feat(roast_asssistant)] : live batch identity badge in the bean header, refreshed from qmc on DROP
* ⚡ [feat(tilauscope_types)] : add format_batch_label() helper for Artisan batch identity rendering
* 🐛 [fix(tilau_updater)] : verify downloaded installer presence and integrity (size, content-length match, HTML-page rejection, min-size floor, Windows MZ magic) before offering install
* 🐛 [fix(tilau_updater)] : honor thread interruption mid-stream so Cancel aborts the download immediately and the worker cleans up its own partial file
* 🐛 [fix(tilau_updater)] : emit typed, localized error messages per failure cause (timeout, connection lost, HTTP status, disk-write error) instead of a generic exception string
* 🐛 [fix(tilau_updater)] : suppress spurious download-error dialog after user cancellation and guard installer presence at launch time to avoid inconsistent message display
* 🐛 [fix(tilauambient)] : rename get_ambiEnt to get_ambient to match the comm.py sampling-loop caller, restoring ambient acquisition
* 🐛 [fix(comm)] : downgrade per-cycle TILAUSCOPE12/34/56 read logs from info to debug to keep the real-time sampling path quiet
* 🐛 [fix(tilauambient)] : guard polled BLE reads (askAmbient, getCrackCounter) so disconnect/Core Bluetooth errors return an invalid reading instead of propagating into the Artisan sampling loop
* 🐛 [fix(tilauambient)] : add ambient temperature plausibility gate (-10..50 °C); out-of-band BME280 glitches now invalidate the whole reading, protecting sampling and roast-plan generation
* 🎨 [ui(tilauscope)] french translation
build 184
* ⚡ [feat(alog_repair)] : add weight-loss % badge with hard out≥in validation, dynamic weight-unit labels, ambient temp/humidity fields (audited for historical-analysis quality), color-system selector and Agtron prefill
* ⚡ [feat(alog_repair)] : add "show incomplete only" filter, "next incomplete" navigation with auto-advance after Record, and an explicit "Missing:" summary line
* ⚡ [feat(alog_repair)] : add plausibility "Check:" hints for present-but-unusual values with range placeholders/tooltips, kept visually distinct from the empty-field highlight
* 🐛 [fix(alog_repair)] : guard against overwriting a different existing file on rename, and prompt on unsaved changes when switching profiles or closing
* 🐛 [fix(beancave)] : prevent RuntimeError on BeanCave reopen when indexer QThread C++ object is pending deleteLater
* 🐛 [fix(beancave)] : suppress matplotlib legend warning when alog events panel has no labelled artists
build 183
* 🎨 [ui(repair alog)] french translation
build 182
* ⚡ [feat(alog_repair)] : new ALog Repair window — audit incomplete roast profiles, auto-match/link a green bean, complete empty fields and rewrite+rename to the canonical Artisan filename on Record
* ⚡ [feat(beancave)] : add "Repair ALogs" button to the File Management tab, opening the repair window and refreshing the metadata cache on completion
* 🐛 [fix(tilau_intelligence)] : collision-safe extra-device classification (RoC vs Color, SC vs FC, token-exact short codes) shared by FC and DryEnd detectors
* ⚡ [feat(roast_properties)] : enable Auto Dry End / Auto First Crack toggles, persisted via the TilauScope detection flags
* ⚡ [feat(roast_properties)] : block Auto Dry End activation when no Dry-phase BT target is configured
* 🐛 [fix(canvas)] : reset and re-discover FirstCrackDetector at monitor-on and CHARGE so FC auto-mark re-arms each roast
* 🐛 [fix(canvas)] : re-configure DryEndDetector after reset at CHARGE to keep the Agtron signal alive
* 🐛 [fix(tilau_intelligence)] : ignore the -1 crack-counter sentinel to prevent a phantom first crack
* ⚡ [feat(roast_properties)] : enable Auto Dry End / Auto First Crack toggles, wired to TilauScope detection flags (load/save like device config)
* 🐛 [fix(canvas)] : reset FirstCrackDetector at CHARGE so FC auto-mark re-arms across roasts
* 🐛 [fix(canvas)] : re-configure DryEndDetector after reset at CHARGE to keep the Agtron signal active
* 🐛 [fix(tilau_intelligence)] : ignore negative crack-counter sentinel (-1) to prevent a phantom first crack
build 181
* 🐛 [fix(niimprint)] : restore Niimbot heartbeat polling by adding poll_status(), which calls poll() and emits status_updated (previous code called a non-existent method, silently failing every 5 s)
* 🐛 [fix(beancave)] : join the Niimbot heartbeat poll thread before np.stop() to remove a use-after-free race on the BLE object during dialog close
* 🐛 [fix(beancave)] : make closeEvent the authoritative shutdown path — set is_shutting_down under the mutex, disconnect BLE signals and stop the Lebrew AG manager before np.stop(); remove the dead, buggy when_finished()
* 🐛 [fix(beancave)] : guard trigger_cache_refresh against re-entrancy to prevent orphaned indexer threads and concurrent writes to the metadata cache
* ⚡ [feat(canvas/displayscope)] : decouple TilauScope live data from the qmc sample loop via tilauUpdateSignal (code, display, raw, state) with an exception-guarded slot
* 🐛 [fix(displayscope)] : carry raw float values to TilauScope readouts, removing the float→str→float round-trip that fed rounded values to alert/min-max/RoR/phase logic
* 🐛 [fix(displayscope)] : isolate TilauScope UI updates so an exception can no longer abort Artisan's native LCD refresh for the cycle
* 🐛 [fix(displayscope)] : ButtonManager now holds artisan_conf per instance with an instance-level _onclick, removing shared class-level state
* 🐛 [fix(displayscope)] : correct inconsistent indentation in the ET (data==11) update branch
build 180
* 🐛 [fix(beancave)] guard index of files found return None was not correctly trapped
* 🐛 [fix(beancave)] : replace WindowStaysOnTopHint with Tool flag on Windows to fix crash on open
* 🐛 [fix(beancave)] : guard _safe_raise / changeEvent / eventFilter re-raise logic to macOS only
build 179
* 🐛 [fix(roasters)] : add missing dev_thermal_inertia_factor and expected_tp_bt fields to Roaster, RoasterContext, and the from_roaster builder — fixes plan generation crash "'RoasterContext' object has no attribute 'dev_thermal_inertia_factor'"
* 🐛 [fix(roast_asssistant)] : near_dry / near_fc now require BT to be below the target (approaching from below) — fixes "Dry end" and "MODE STD" buttons lighting up at charge when BT starts above dry-end temp, and guards against a false near_fc trigger if BT overshoots FC temp
* ⚡ [feat(roast_asssistant)] : AirWave mode button keeps the current-phase mode (Dry → MODE FAN, Maillard → MODE STD), clickable for a ~30s grace window after the phase event (CHARGE / DRY END) as a catch-up, disabled afterwards and when the device is offline; the click re-asserts the live fan speed ("MODE X, FAN <slider>") to avoid turbulence from a stale value
* 🐛 [fix(roast_plan_model)] : clamp the dry RoR target to the CHARGE→DRY ideal band so the plan target stays consistent with the live phase classifier (no "on plan" reading as warn)
* 🐛 [fix(roast_asssistant)] : remove the duplicated "%" on the Airflow and AirWave cards — the value strings already carry their own unit, so the card unit is now empty
* ⚡ [feat(roast_asssistant)] : AirWave mode button is enable-on-approach — disabled by default, lit only near the upcoming transition (→ MODE STD near dry-end, → MODE EXT near FC) and only when the device is online
* ⚡ [feat(roast_asssistant)] : after a mode change, re-assert the live fan speed in the same command ("MODE X, FAN <slider>") so the device can't restore a stale fan value and spike turbulence
* ⚡ [feat(roast_asssistant)] : pull-aware integrated-airflow advice via inlet_air_mode — pull machines get "keep low to conserve heat" in dry, push machines "moderate for even drying"
* ⚡ [feat(roast_asssistant)] : AirWave card proposes the per-phase mode (FAN/STD/EXT) when an AirWave device is detected; no mode suggestion when absent
* ⚡ [feat(roast_asssistant)] : pass airwave_present (from bleAirwaveDevice) to the plan generator so the AirWave/extraction recommendation is gated on detection
* 🐛 [fix(roast_asssistant)] : read drum airflow from the integrated ventilation slider (0) and reclass the AirWave card as extraction/smoke status from the damper slider (2) — removes the conflation that treated the AirWave fan as the browning lever and gave inverted dry-phase advice
* ⚡ [feat(roast_asssistant)] : AirWave extraction card flags airflow above ~30% as cooling the drum (Skywalker-specific observed threshold, _AIRWAVE_COOLING_PCT)
* 🐛 [fix(roast_asssistant)] : drive RoR status from dual-sided per-phase bands (get_ror_color_by_phase) — a too-high RoR now escalates correctly per phase (notably in development), replacing the phase-blind ±band and the above_is_crit=False that hid high-RoR risk
* 🐛 [fix(roast_asssistant)] : make _RoRCrashDetector sample-rate invariant — normalise the fall slope by real elapsed time and express the confirmation window in seconds (MIN_DURATION_SEC) instead of assuming 1 Hz ticks; dt derived from qmc.delay
* ⚡ [feat(tilauscope_types)] : add get_ror_color_by_phase + get_ror_ideal_band — dual-sided, phase-specific RoR (bean-temperature, °C/min) classifier with °F scaling; kept distinct from get_roc_color which handles Rate-of-Colour (Agtron/min)
* ⚡ [feat(roasters)] : add inlet_air_mode (push/pull) to AirflowControl + RoasterContext (default push); Skywalker/Cyberroaster set to pull to flag drum-airflow/extraction coupling for the planner and assistant
build 178
* 🐛 [fix(tilauscope)] drop button text is directly accessible with its subtext
build 177
* 🐛 [fix(roast plan)] sub text at drop was missing a prefix variable and crashing the roast
* 🐛 [fix(roast_plan_model)] : stop double-applying the charge BT deviation — it was added both to the grid bounds (via _adjust_deviation) and to the value, pinning charge temp to the clamp floor and nullifying the process/density/weight/altitude adjustments; now applied once, charge responds to bean parameters within bounds
* 🐛 [fix(roast_plan_model)] : correct turning-point detection — use BT minimum (RoR zero-crossing) instead of the RoR minimum, which is the steepest-cooling point and systematically mislocated the TP
* 🐛 [fix(roast_plan_model)] : make crash/flick detection sample-rate invariant — derive per-log dt from recorded timex (median interval) instead of assuming 1 Hz windows; reads the actual recorded sampling, not the current Artisan setting
* ⚡ [feat(roast_plan_model)] : prominence-based crash/flick detection via scipy.signal.find_peaks — ranks RoR dips/bumps by physical prominence (°C/min), eliminates false positives from normal monotonic RoR decline, and makes severity physically meaningful and comparable across roasts* 🐛 [fix(roast_plan_model)] : derive maillard & development RoR from grid geometry — displayed RoR now matches the actual planned BT curve instead of contradictory standalone formulas; removed dead circular maillard_ror_effective computation
* 🐛 [fix(roast_plan_model)] : make DTR target reachable for FIR light/very-light by widening the development window; report achievable DTR when the dev clamp binds, eliminating silent target-vs-result divergence
* ⚡ [feat(roast_plan_model)] : geometry-authoritative plan engine — grid temps/times are the single source of truth, all RoR/DTR values derived from it (former formulas kept only as validation bounds)
build 176
* 🐛 [fix(beancave)] set BeancaveDlg as parent of TilauAlarmDlg — fixes macOS focus returning to Artisan main window on alarm editor close
* 🐛 [fix(visualalarm)] remove WindowStaysOnTopHint from AlarmTimelineDialog — was corrupting macOS NSWindow level stack on close
* 🐛 [fix(beancave)] _safe_raise: recursive parent walk, exclude self, deferred retry loop — fixes BeancaveDlg falling behind on close of any descendant Tool dialog
* 🐛 [fix(visualalarm)] add missing COOL END, FC END, SC START, SC END event milestones to timeline — alarms on those events were anchored at position 0 (near ON)
* 🐛 [fix(visualalarm)] fix infinite loop risk in IF ALARM parent resolution using visited-set guard
* ⚡ [feat(visualalarm)] add zoom in/out (0.3×–2.0×) via ⊕/⊖ buttons, Ctrl+scroll and macOS pinch gesture — all content scales proportionally including fonts, cards and milestone spacing
* ⚡ [feat(alarms)] add Visual Timeline button to alarm editor toolbar — opens AlarmTimelineDialog as singleton with current saved alarm state
* 🐛 [fix(alarms)] save alarm table state to qmc before opening visual timeline to ensure displayed data reflects unsaved edits
* ⚡ [feat(difluid)] : pre-connection dedup command queue — last-write-wins keyed on (function,command), drained in last-occurrence order on BLE connect
* 🐛 [fix(difluid)] : clear pending command queue on bleStop to prevent stale commands on zombie connection
* 🐛 [fix(difluid)] : fix speed_changed_signal typo — was silently failing on fan speed notify
* ⚡ [feat(canvas)] : handle Airwave unsolicited BLE notifications — fan speed syncs damper slider, mode and power state tracked in qmc
build 175
* ✨ [feat(tilauscope)] new modules
build 174
build 173
build 172
* 🐛 [fix(canvas/TilauController)] : fix isFinished/isRunning missing parentheses, QWidget→QObject, dangling thread ref after deleteLater
* 🐛 [fix(canvas/TilauWorkerThread)] : remove cross-thread qmc flag — use QThread requestInterruption/isInterruptionRequested, no additional imports
* ⚡ [feat(tilauscope/menu_extension)] : centralized TilauScope menu extension module with single apply() hook in set_menu()
* 🐛 [fix(tilauscope/menu_extension)] : fix TilauScope top-level menu not appearing on macOS — QMenu parented to aw + direct aw.viewMenu reference replacing fragile title-search
* 🐛 [fix(beancave)] replace BeanHelper class with load_cave_beans() module-level function — removes duplicated load/save logic and latent AttributeError on _show_message
* 🐛 [fix(beancave)] remove dead methods oldkeyPressEvent and oldcloseEvent
* 🐛 [fix(beancave)] remove orphaned _BleInitWorker class (replaced by TilauBLEScanner)
* ⚡ [feat(beancave)] add _launch_worker() helper to factor out QThread boilerplate; refactor _start_roaster_load and list_alog_files
* 🐛 [fix(roast_properties)] remove unused bean_helper parameter from RoastSetupDialog.__init__
* 🐛 [fix(roast_asssistant)] replace BeanHelper instantiation in populate_bean_list with load_cave_beans()
* 🐛 [fix(artisan_message_ticker)] _is_roast_noise: remove redundant strip() call — single strip/lower reused for both length check and prefix match
* 🐛 [fix(artisan_message_ticker)] move import types to module level — remove deferred import inside install() method body
* 🐛 [fix(artisan_message_ticker)] ArtisanMessageHook.install: remove unnecessary MethodType/lambda double-wrapper — assign closure directly as instance attribute
* 🐛 [fix(displayscope)] TriggeredAlarmBadge: promote EVENT_NAMES, CAT_COLORS, ALARM_CONDS, event_positions to class-level constants — built once, shared across instances
* 🐛 [fix(displayscope)] AlarmSidebar: build ACTION_LIST once at init (28 translate() + 4 etypesf() calls) and pass shared reference to each TriggeredAlarmBadge
* 🐛 [fix(displayscope)] phase progress bar: fix silent TypeError caused by str key used as range() bound — replace with numeric index loop (past=100%, active=computed, future=0%)
* 🐛 [fix(displayscope)] BT cycle: deduplicate float(value) from 3 calls to 1, reuse fv across alert/minmax/phase/cooling logic
* 🐛 [fix(displayscope)] SV slider sync: move pidcontrol.sv check from unconditional path to TIMER-only path after frequency cap (1×/s max vs 3-4×/s)
* 🐛 [fix(displayscope)] check_sliders_update: pre-compute Artisan slider refs as tuple at build_ui — remove per-cycle list allocation
* 🐛 [fix(displayscope)] check_sliders_update: guard tilauPreheatingPid None check before .active access to prevent AttributeError
* 🐛 [fix(tilaupid_adaptative)] StabilisationDetector._check_stable: remove redundant deque-to-list copy, pass deque directly to statistics.mean/stdev — eliminates per-cycle heap allocation
* 🐛 [fix(tilaupid)] extract map_source closure as TilauPreheatPID._map_ambient_source static method, resolve qmc once per call — removes per-cycle closure reallocation and redundant attribute chain lookups
* 🐛 [fix(roast_plan_model)] : fix _calculate_rpm_percentage fallback crash on None params and remove redundant double-rounding
build 171
* ⚡ [feat(roasters)] : add dev_thermal_inertia_factor and expected_tp_bt to Roaster and RoasterContext
* ⚡ [feat(roast_plan_model)] : replace RoasterBasicPlanPerPhase prior grid — arithmetic consistency, monotone progression, industry-calibrated fc/drop/dry temps
* ⚡ [feat(roast_plan_model)] : scale drop_bt_temperature within plan bounds using dev_thermal_inertia_factor
* 🐛 [fix(roast_plan_model)] : replace hardcoded expected_tp=100°C with ctx.expected_tp_bt (radiant SW: 95°C measured)
* 🐛 [fix(roast_plan_model)] : replace hardcoded dry_end_bt=160°C with roast_constraints.dry_temp from plan grid
* 🐛 [fix(roast_plan_model)] : recalibrate weight_adj coefficient 0.15→0.27 from empirical data (r=0.46, n=83)
* 🐛 [fix(roasters)] : recalibrate SW/Cyberroaster bt_offsets from [-10,-10,-10,-10] to [-13,-8,-10,-12.5] on 68 real roasts
* 🐛 [fix(roast_plan_model)] : exclude alogs with missing ambient data, low charge BT, or wrong machine fingerprint from historical analysis
* 🔧 [build(artisan)] added latest artisan updates from continuous buid (May 2026)
* ⚡ [feat(routine_check)] cleaning cycle bar graduates from accent blue → warning orange → critical red between 50% and 100% usage
* ⚡ [feat(routine_check)] scroll interaction cancels auto-close timer and hides countdown bar — manual dismiss required after user scrolls the roast history
build 170
* ⚡ [feat(timeline)] roast timeline v2, new design, new concept to browse ready roasts (planning function of beancave)
RoastViewer)]: roast name and date now displayed above the curve after selecting a roast from the list
* 🐛 [fix(beancave/AlogListWorker)]: fix roast list sort order — sort now based on formatted display name (alpha ASC, date DESC) instead of raw filename items
build 169
* ⚡ [feat(tilaulogger)] added inline connection status labels next to ESP32 Flow and Application Flow zone titles — color-coded indicators for serial (inactive/switching/connected/error) and TCP (inactive/receiving) states
* ⚡ [feat(tilaulogger)] added debug level toggle button and status label in toolbar — activates/deactivates DEBUG logging across all modules without the hidden ALT+CTRL+click gesture
* 🐛 [ui(tilauscope)] status now display if auto-mark of DE or FCs has been engaged on tilauscope side config/setup (see config menu) 
* 🐛 [fix(tilaulogger)] moved full widget setup from setModal() into __init__() — prevented double-init and inconsistent worker state on open
* 🐛 [fix(tilaulogger)] eliminated TCP server race condition using threading.Event (_tcp_ready) — closeEvent now waits for tcp_server to be fully assigned before shutdown
* 🐛 [fix(tilaulogger)] made TCP shutdown synchronous and bounded (2s join) — replaced fire-and-forget daemon thread that caused crash on window close
* 🐛 [fix(tilaulogger)] fixed infinite loop in TCPLogHandler recv reassembly — added EOF guard (if not more: return) on partial reads
* 🐛 [fix(tilauscope)] better handling of real time sampling when roast is not yet started (monitor on but not started)
* ⚡ [perf(b21s)] new b21S background task to poll it and avoid BLE drops
* ⚡ [perf(b21S support with additional guards)] improved B21 support, label have been refactored too
* 🎨 [ui(roast assist)] update french translation
✨ [feat(live_events)] new ArtisanMessageTicker widget at the bottom of the Live Events sidebar captures Artisan messages during recording
✨ [feat(live_events)] messages displayed as a scrollable history — most recent highlighted in Artisan blue, older entries in white
✨ [feat(live_events)] ArtisanMessageHook intercepts sendmessage_internal without modifying artisanlib/ — hook installed at TilauScope open, removed at close
🎨 [ui(live_events)] ticker header uses the Artisan icon (SVG inline #63B8DD) — portable across DMG and EXE builds
🎨 [ui(live_events)] message counter + ✕ clear button in ticker header, consistent with LIVE EVENTS panel style
✨ [feat(live_events)] noise filter discards low-value messages (file I/O, settings, export, colors…) — only operational roast messages shown
🎨 [ui(tilauscope)] Artisan messagelabel hidden while recording in TilauScope mode, restored on STOP or window close
build 168
* 🐛 [fix(tilauscope)] Floating annotation: removed dead code referencing non-existent tilau_annotation in on_leave_canvas
* 🐛 [fix(tilauscope)] PID annotation: header_color now reflects active PID mode (Manual/Ramp-Soak/Scheduling) instead of constant fallback
* 🐛 [fix(annotation)] ID Ramp/Soak: elapsed time in current segment now correctly computed using rs_t0 offset (time_pidON or CHARGE depending on RStimeAfterCHARGE)
* 🐛 [fix(annotation)] changed DTR in DEV to add target and colorPID Ramp/Soak: rslen now counts actually configured segments (svValues/svRamps/svSoaks) instead of RSLen-1
* 🐛 [fix(annotation)] Annotation HTML: BT/SV delta color fixed (CSS property was color= instead of color:)
* 🐛 [fix(annotation)] Annotation HTML: SCs and SCe rows now correctly appended to table (html += instead of html +)
* 🎨 [ui(annotations)] Roast phase annotation: title is now dynamic per phase (Preheat/Drying/Maillard/Development/Cooling) instead of hardcoded "Roasting Phase"
* 🎨 [ui(annotations)] Omniflux display: Agtron and RoC now rendered with independent colors (grain color vs browning speed)
* 🎨 [ui(annotations)] Prediction bar: EMA smoothing (α=0.2) + 3s dead band added to eliminate visual jitter on the vertical line and intersection point
* 🐛 [feat(core)] get_agtron_color(agtron): new public function returning SCA Gourmet grain color hex from Agtron value
* 🐛 [feat(core)] get_roc_color(roc): new public function returning Omniflux browning speed color (blue→green→gold→red)
* 🐛 [fix(roast_assistant)] Drying phase: Gap ET/BT card neutralized during post-TP grace period to prevent false "Low Delta" alerts on FIR/NIR roasters
* 🐛 [fix(roast_assistant)] Drying/Maillard/Development phases: Agtron card_color hidden when Omniflux is not connected, eliminating phantom values
* 🐛 [fix(roast_assistant)] Development phase: card_color hidden when neither live sensor nor predictive model data is available
* 🐛 [fix(roast_assistant)] Development phase: btn_drop subtitle is now adaptive based on decision source (color / DTR / temperature)
* 🐛 [fix(roast_assistant)] Drying phase: btn_dry_end no longer activates during post-CHARGE BT drop or within the first 60 seconds (stabilizing guard)
build 167
* 🐛 [fix(roast properties)] typo on a variable name
build 166
* 🐛 [fix(roast_assistant)] dev page was not correctly C/F aware
* 🐛 [fix(roast_assistant)] RoR crash detector got dead code forgotten
* 🐛 [fix(roast_assistant)] maillard phase was not C/F aware
* 🐛 [fix(roast_assistant)] ema color was frozen after 10 cycles
* 🐛 [fix(roast_assistant)] fixed pre and post roast variable probing to RT
* 🐛 [fix(roast_assistant)] pid was not moving slider anymore due to changed init
* 🐛 [fix(roast_assistant)] charge button which was disabled if pid overshoots
* 🐛 [fix(roast_assistant)] fixed DTR prediction to display the expected DTR based on prediction
* 🐛 [fix(roast_assistant)] initial RoR had a warning after TP, now waits for it to raise before triggering an alert
* 🐛 [fix(ai_support)] engine is being reworked to correctly handle multiple providers
* ♻️ [refactor(aiengine)] changed name of tilau variables so that they canno tinterfere with (future) artisan variable names
build 165
* 🐛 [fix(beancave)] bean identification y AI is reinforced
* 🐛 [fix(roast properties)] roast propoerties now have AI analysis
* 🐛 [fix(visual alarms)] ai integrationre factored and prompt redesigned
* 🐛 [fix(core)] ai factory rebuilded from scratch to be shared between modules
* 🐛 [fix(config)] all ai engines now supported
build 164
* 🐛 [fix(beancave)] autodetection of niimbot printer now save printer in device configuration to faster reconnection
build 163
* ✨ [feat(tilauscope)] ble unified loop for scanning on macos
* 🎨 [ui(beancave)] redesign of main database display
* 🐛 [fix(beancave)] updated expand/collapse zone of curves in second tab
* ✨ [feat(tilauscope)] Dry end detection, aurtomarking on artisan
* 🐛 [fix(colortracker)] bug on omniflux data detection on first crack detection
build 162
* 🐛 [fix(tilauscope)] added a cooling stage and changed messages
build 161
* 🐛 [fix(tilauscope)] focus guard on macos
build 160
build 159
* 🐛 [fix(muliple modules)] temporary array where to read ambients
* 🐛 [fix(roast_assist)] slider labels in QuickAdjust buttons now read from `aw.qmc.etypes` instead of hardcoded strings, matching the main panel behaviour
* 🎨 [ui(roast_assist)] QuickAdjust button colors now follow `aw.qmc.EvalueColor` per-slider identity, consistent with the main control panel
* 🐛 [fix(roast_assist)] missing `alarm_source_list` attribute on `TriggeredAlarmBadge` causing crash on DROP and any alarm with a defined source; list now built at init from Artisan `alarmsource` convention (`-3=None, -2=ΔET, -1=ΔBT, 0=ET, 1=BT, 2+=extra devices`)
* 🐛 [fix(roast_assist)] `_DryingPage._QuickAdjustRow` block was partially truncated by a prior patch, causing `_ctx_row` undefined error and indentation crash at line 1120
* 🔧 [refactor(roast_assist)] `QGraphicsOpacityEffect` moved to module-level import; lazy in-method import removed, return type annotation no longer a string literal
* 🔧 [refactor(roast_assist)] `RoastDataBridge` forward reference now resolved via `TYPE_CHECKING` guard import from `tilauscope.roast_bridge`; `# noqa: F821` rustine removed
build 158
* 🎨 [ui(tilauscope)] updated french translation
* 🐛 [fix(difluid)] error while reading the new constant array, convert to values from string was not done
* ✨ [feat(roast_assist)] alert banner in preheat mode is now displayed without scrolling required
* ✨ [feat(roast_assist)] humidity is now taken in consideration regarding RoR advices
* ✨ [feat(roast_assist)] assistant detecs Airwave and manage a card in manual mode
* ✨ [feat(Roast Plan)] Improved card for Maillard and Development
* ✨ [feat(Roast Plan)] RoR crash detector monitoring
* 🐛 [fix(roast_assist)] bug in DTR real time evaluation
* ✨ [feat(roast assistant)] moved to signal oriented assistant to minimize impact on cpu and be thread safe
* 🐛 [fix(roast plan)] fixed a few issues, minor and average impact
* 🐛 [fix(mqttbridge)] prevent deadlock and inter access race by removing sleep loops
* 🐛 [fix(mqttbridge)] multiple changes in loop management to support Paho module better
build 157
* 🐛 [fix(logger)] resizing window could lead to crash at some occasions while roasting was on
* 🐛 [fix(logger)] tilaulogger is now correctly handling deletion of threads
* 🐛 [fix(tilauscope)] switched back to system menu as it was not working fine on certain windows version
* 🐛 [fix(tilauscope)] broken swappanel button
build 156
* 🔧 [build(tilauscope)] update french translation for new features
build 155
build 154
* 🐛 [fix(release manager)] changed the way the logged features and fixes are stored
* 🐛 [fix(build)] bump
build 153-152
* 🐛 [fix(beancave)] window stays on top and does not blink on macos
* ✨ [feat(pidonet)] new strategy to use airwave pid
* ✨ [feat(beancave)] curve viewer goes into compare mode automatically if multiple curves are selected
* 🐛 [fix(beancave)] prevent artisan crash uupon closing beacuse of unfinished background threads
* 🐛 [fix(tilmauscope)] drag window now correctly sticks to the mouse
* 🐛 [fix(tilaupid)] fixed display of pid target and initializing phase
* 🐛 [fix(tilaupid)] deadlock due to event logging in artisan fixed
* 🐛 [fix(tilauscope)] using signal from artisan to mark evnt prevent cases of hangs
* ✨ [feat(tilauscope)] live events gets a counter on top and a clear buton to clean the zone
* ✨ [feat(tilauscope)] mouse wheel can be used to raise/lower sliders
* ✨ [feat(tilauscope)] average, min and max values of ET,BT and RoR displayed when passig the mouse oveer them
* ✨ [feat(tilauscope)] change phase target with mouse wheel over the phase zone
* ✨ [feat(tilauscope)] ET and BT counters have been enlarged for easier reading
* ✨ [feat(tilauscope)] buttons are now graphics with SVG shapes to make it smarter
* ✨ [feat(tilauscope)] live events now stack button calls as well
* ✨ [feat(tilauscope)] now rebuilds dynamically buttons and extracounters on artisan change
* 🐛 [fix(tilauscope)] extra counters in ON but not started are now in sync with Artisan
* 🐛 [fix(tilauambiant)] was reading counters on start mode from wrong variable
* 🐛 [fix(what's new)] was not detecting always that it should not appear again
build 146-151
* 🔧 [build(ambiant)] bump
* ✨ [feat(updater)] tilauambiant v2 support
* 🐛 [fix(updater)] typo on error message when google drive is not accessible
* 🐛 [fix(beancave)] change icon file
* 🐛 [fix(beancave)] changed logo for printing labels
* 🐛 [fix(beancave)] rollback to windo stacking
* 🐛 [fix(beancave)] locked beancave on top to avoid windo display flick on macos
build 143
* 🐛 [fix(beancave)] labels problem with rendering fixed
* 🐛 [fix(beancave)] set print label feature to point on Download directory by default
* ✨ [feat(beancave)] new labels to print for both green and roasted beans
* 🎨 [ui(beancave)] display a message when starting a new roast and plan is ready
build 141-142
* 🐛 [fix(roast plan)] roaster was not taken from the combo but from the main session
* 🐛 [fix(roast plan)] roast plan was failing if there was no roasting session existing yet for a green bean
* 🐛 [fix(tilaupid)] rebuilding of learning model cache
* 🐛 [fix(tilaupid)] guarding multiple ambient data collection
* 🐛 [fix(tilaupid)] finish to move to adaptative pid
build 137
* 🐛 [fix(artisan)] new init variable
build 136
* 🐛 [fix(displayscope)] probedeviation support before first define
* ✨ [feat(artisan)] inject current artisan update
build 134-135
* 🐛 [fix(tilauscope)] Ensure that whenever anything changes structural parameters inside a child widget, an explicit cache reset or custom signal forces layout invalidation
* 🐛 [fix(tilauscope)] guard widget hiding with additional tests
* 🐛 [fix(tilauscope)] clamping % of phase
* 🐛 [fix(label printer)] guard if computed value or totallloss where not found
* 🐛 [fix(label printer)] typo on font family name
* 🐛 [fix(label printer)] qrcode was not correctly taking crop information
build 132-133
* ♻️ [refactor(bump)] bumping
* 🐛 [fix(beancave)] when printing, and an error occurred the thread was not correctly finished
* 🐛 [fix(beancave)] detection of niimbot paper style could output an error message even if no eror in some cases
* 🐛 [fix(beancave)] support for aqua guage, a guard was inverted
* 🐛 [fix(beancave)] windows acrylic support, test was inverted
* 🐛 [fix(niimprint)] in case data is none from alog which should not happen raise an error
* 🐛 [fix(niimprint)] in label generation beans field was incorrectly set and never retrieving the green bean even if present
* 🐛 [fix(niimprint)] guard on last plot data being empty following a malformed alog file
* 🐛 [fix(niimprint)] guard against malformed rfid answers
* 🐛 [fix(niimprint)] improved error code detection
* 🐛 [fix(niimprint)] rfid not sent in certain case by heartbeat
* 🐛 [fix(roast assistant)] fixed problem where no beans were listed if either color or green bean was selected
* 🐛 [fix(roast manager)] more simple initialization of code
* 🐛 [fix(roast assistant)] adjusted warning message on heater which was wrong for 80-85% heater
* 🐛 [fix(roast assistant)] correctly set phase for FCe, SCs, SCe
* 🐛 [fix(roast assistant)] roast assistant was not raising alerts on banner with tips
* 🐛 [fix(roast assistant)] wrong variable used on color failing in bean list
* 🐛 [fix(roast assistant)] mising f prefix on debug string (no impact)
* 🐛 [fix(roast assistant)] prevent crash on roast assistant if ror is not given by artisan
* 🐛 [fix(roast assistant)] guard on the case no roaster is being defined at first time
* 🐛 [fix(roast properties)] reorder close cascade of windows of roast setup
* 🐛 [fix(roast properties)] in roast setup, crop migth be wrong
* 🐛 [fix(roast properties)] guarded detaching before attaching ambiant probe
* 🐛 [fix(roast properties)] update of defect % is now guarded properly
* 🐛 [fix(roast properties)] add guard on connected scale
* 🐛 [fix(roast properties)] wrong variable checked for pressure on validation of roast start
* 🐛 [fix(roast properties)] selection of temp would display °C and not °C/°F depending on unit
* 🐛 [fix(roast properties)] operator precedence error on temp color display
build 130
* 🐛 [fix(roast feature of beancave)] fix condition where tilaumabiant is not defined
build 128
* 🐛 [fix(roast setup)] ambients were not set to the correct variables in artisan canvas
build 126
* ✨ [feat(roast plan)] added target color and roaster to plan in pdf
* ♻️ [refactor(beancave)] total refactored of caching (roast plan todo)
* 🐛 [fix(roast properties)] added main phase data as a simple summary on top
* ✨ [feat(beancave)] now list roasts is alphabetical order of beans, then descending on date with the latest first
* 🐛 [fix(beancave)] prevent windows from blinkling due to safe_raise flags
* 🐛 [fix(beancave)] niimbot printer was crashing beancave
* 🐛 [fix(roast properties)] cheked if both color are there to compute delta
-* 🐛 [fix(roast properties)] cheked if weight is here on green beans to compute delta
* 🎨 [ui(beancave)] rewroked roast properties and setup size and organization of tabs
build 119
* 🐛 [fix(roast setup)] roasting button is now enabled only when a weight is set
* 🐛 [fix(ui)] roast list is now listed in agtron ascending order
* 🐛 [fix(ui)] combobox on macos is now clean without system border
* 🐛 [fix(roast setup)] tooltip stylesheet
* 🐛 [fix(roast setup)] ambiant probe real time display
* 🐛 [fix(roast setup)] french translation
* ✨ [feat(roast setup)] improve roast setup from bean cave by adding more features but in a user friendly way
build 114
* 🐛 [fix(beancave)] cancelling threads in the background
* 🐛 [fix(beancave)] roast scale can now call TARE on double click
build 112
* ✨ [feat(bump)] bump version
* ✨ [feat(beancave)] added roast properties concept to test
build 110
* 🐛 [fix(beancave)] general optimization of background tasks in beancave
* 🐛 [fix(beancave)] upon loading correctly select the green bean if any
* 🐛 [fix(beancave)] upon loading correctly select the current file in the roast view file
* ♻️ [refactor(beancave)] add uuid helper feature
* ✨ [feat(beancave)] open beancave directly pointing on green bean and roast details if a profile is being loaded in artisan
build 109
* ✨ [feat(beancave)] first verison of roast setup
* ✨ [feat(beancave)] integration of acaia scale in roast setup from green beans
* ✨ [feat(beancave)] roast from green bean, set all useful information to roast properties
* 🎨 [ui(roasting)] auto mark first crack flag added
* 🐛 [fix(roasting)] auto mark first crack flag added to general flag for tilau intelligence routine
build 106
* 🐛 [fix(ui)] bump
* 🐛 [fix(devices)] general tab was not correctly saved
* ✨ [feat(ui)] moved all settings to a dedicated tab
* ✨ [feat(pidoverET)] in Airwave support, enhanced version that uses different DeltaET per phase as intervals
* ✨ [feat(roaster)] added custom roaster Skywalker V1 - THE BEAST Edition
* 🎨 [ui(floating annotation)] changed background to be semi transparent to be easier to read
* ✨ [feat(crack detection)] version 1 or combined crack detection and color change if available
build 102
* 🐛 [fix(canvas)] bump
* 🐛 [fix(canvas)] major change in the way to handle the floating annotation, does not disappear anymore when projection is finished
* 🐛 [fix(ui)] roaster selection fails on windows build
* ✨ [feat(tilauscope)] crack counter detection logic support
build 100
* 🐛 [fix(tilauscope)] annotation was not shifting screen as expected
* ✨ [feat(roast_assistant)] roast asssitant leveraging on roaster capacity database concept (first run)
build 98
* 🐛 [fix(tilauscope)] bump
* ✨ [feat(tilauscope)] smola roasters support
* ✨ [feat(tilauscope)] kaleido roasters support
* ♻️ [refactor(beancave)] moved styling before creation of gui object to accelerate startup
* ✨ [feat(beancave)] process to ble detection and initialization in a background thread
* ✨ [feat(beancave)] process of redraw claculation in background thread
* ✨ [feat(beancave)] process of alog list in backgound thread
* 🐛 [fix(beancave)] defer roast plan combo build in a backgound task to prevent screen from locking
* 🐛 [fix(beancave)] defer alog scanning in a background taxk
* ✨ [feat(general)] updated ci/cd file list
build 96
* 🎨 [ui(beancave)] bump
* 🎨 [ui(beancave)] combo boxes from plan generation are now populated with adequate values
* 🎨 [ui(beancave)] added a checkbox to manually override the values of deviation from roaster to use your value set
* ✨ [feat(beancave)] reworked all plan algorithm to be totally agnostic from roaster
* ✨ [feat(beancave)] added roaster type support in roast plans to adapt to the machine
* ✨ [feat(beancave)] added roaster type support
build 94
* 🐛 [fix(beancave)] bump
* 🐛 [fix(roast asssistant)] reworked algorithm to buffer RoC and RoR information to avoid noise
* 🐛 [fix(roast asssistant)] bug fix on development page
* 🐛 [fix(roast asssistant)] bug fix on maillard page
* 🐛 [fix(roast asssistant)] multiple bug fixes and color management support for omnifluc
build 92
* 🔧 [build(tilauscope)] bump version
* ♻️ [refactor(tilauscope)] refactored button management for better control of states
* 🐛 [fix(tilauscope)] fixed roast assistant bug first phase, ror was freezing the assistant
* ♻️ [refactor(tilauscope)] refactored stylesheets for buttons to optimze for speed
* ✨ [feat(tilauscope)] added swap panel feature to swap control and live events panels
* 🐛 [fix(tilauscope)] floating annotation now correctly shift from right to left of graphic bar
build 90
* 🐛 [fix(beancave)] bump
* 🐛 [fix(beancave)] fixed bug on dev time not displayed in the annotation
* 🐛 [fix(tilauscope)] phase counter progress bar was not displaying phase correctly
* 🐛 [fix(general)] add latest artisan 4.0.4 changes/fixes
build 87
* ✨ [feat(beancave)] mapping table is being computed to speed up bean identification
* ✨ [feat(beancave)] popuklate beans is not parsing in backgound to identify uuid vs alogs
* ✨ [feat(beancave)] Roast plan improvement by selecting green bean and roasts directly in tab
build 85
* 🐛 [fix(tilauscope)] roast assistant now correctly identify omniflux data for computation, previous version was not
build 83
* 🐛 [fix(tilauscope)] extra counters were not correctly displayed but correctly stored
* 🐛 [fix(pid)] fix a crash when stop was hit close to start and tilaupid object was not fully initialized
build 81
* ♻️ [refactor(general)] misc comestical issues fix
* 🐛 [fix(tilauscope)] fixed detection of bean type in roast asssitant to detect which bean is actually used
build 80
* 🐛 [fix(tilauscope)] fixed interval to display message to load the beans when preheating with pid
build 79
* 🎨 [ui(tilauscope)] reworked roast assistant to take less space moving start/stop button
* 🐛 [fix(tilauscope)] broken simulator information due to string + float type error concatenation
* 🐛 [fix(beancave)] comuting of drying phase % versus plan / prediction revised
build 78
* 🐛 [fix(beancave)] adjusting alert banner text size and colors
* 🐛 [fix(tilauscope)] preheating phase heater % was not computed due to wrong reference
* 🐛 [fix(tilauscope)] roast assistant font was too slow due to a too large search/replace
build 75
* 🐛 [fix(beancave)] bump
* 🐛 [fix(tilauscope)] fixed reset enabled/disabled state which was sometimes stuck disabled
* 🐛 [fix(tilauscope)] removed artisan pid button, will think at a better way
* 🐛 [fix(tilauscope)] changed buttons stylesheet which was not working very well
* 🐛 [fix(tilauscope)] fiexed broken bean list in roast assistant
* ✨ [feat(general)] changed tilaudebug logger to consume less cpu and flush less (ervery 5s)
* ✨ [feat(pid)] pid one ET based on airwave has now slower rampup while changing phase to avoid stalling or abrupt raise
* 🐛 [fix(beancave)] exporting to llm values were partially shifted of columns, plus change in names
* ✨ [feat(pid)] integration of omniflux data from modbus in pidonET chain processing
* 🎨 [ui(tilauscope)] extra event panel is now resizable and postition/size are retained in settings
* 🐛 [fix(tilauscope)] update extra devices list if there were change in Artisan menu
* 🐛 [fix(general)] integrated latest Artisan Roaster Scope updates
* 🎨 [ui(beancave)] commented search for new version
* 🎨 [ui(beancave)] commented update uuid
* 🐛 [fix(beancave)] prevent printing to B21S to be activating upon scanning for directory change
build 73
* 🐛 [fix(tilauscope)] broken whats new, missing declaration
build 72
* 🐛 [fix(tilauscope)] LCD are now correctly handling digit changes from 0, 1, 2 and 3 and not resizing 
* 🐛 [fix(tilauscope)] The live event panel state is now retained at startup
* 🐛 [fix(tilauscope)] What's new has now a checkbox to forget about displayig the window
* ✨ [feat(beancave)] french translation of roast details
* ✨ [feat(beancave)] refactoring of roast details and improved coach advices

build 71
* ♻️ [refactor(tilauscope)] french translation of live events

build 70
* ✨ [feat(tilauscope)] manual rebuild (out of credit on github)

build 69
* ✨ [feat(tilauscope)] foldable live events
* ✨ [feat(tilauscope)] what's new now hides if asked to hide
* ✨ [feat(build)] build are now notifying for a new version on the discord server general channel

build 68
* 🐛 [fix(tilauscope)] tilauscope window was sometimes shifting afrer having switched to another app (mouse event management)
* 🐛 [fix(tilauscope)] phase timers were off from a few seconds, now align to artisan timer
* 🎨 [ui(tilauscope)] annotations being moved 100% to html with color tresholds
* •  [fixed(pid)] changed treshold from 10% to 5% to warn about charge. 10% was too far due to the curve slope
*    [fixed(slider)] fixed a problem where the sliders were alwaus moving by 1 and not by 5 or 10 like defined in Artisan
* 🎨 [ui(tilauscope)] changed for fancy annotation during roast 

build 67
* ✨ [feat(tilauscope)] add release not at startup of Tilauscope addon

* ✨ [build(core)] full ci/cd done with github action to automate exe/dmg generation

build 66
*    [feat(tilauscope)] bigcards and sliders live change to pilot roast

build 65
* 🎨 [ui(tilauscope)] adapt display style to the rest of the software
* ✨ [feat(tilauscope)] check if any background replay features are set before starting to roast and warn user
* ✨ [feat(tilauscope)] tilaupid status during preheat now warn that charge is close
* ✨ [feat(tilauscope)] enlarged status on two lines

build 64
* ✨ [feat(tilauscope)] when offline before roasting in status line diplays alarm set for info
* ✨ [feat(tilauscope)] extended information on phases target displayed as default
* ✨ [feat(tilauscope)] release management
* ✨ [feat(beancave)] added a button now triggers an assistant to help user
* ✨ [fix(beancave)] hoover on fields has been reworked to be homogen on all fields, also double spins

build 63
* removed unnecessary message if beancave directory is initialized and json file not yet created
* fixed bug in alog count of beancave due to log with missing variable case
* concept version of *** to be discover sometime :-) 

build 34
* fixed tooltip on fields which was messed by the border highlighting added recently
* fixed nasty bug of beancase closing after export/computing of cave content unexpectedly (without saving)

build 33

build 32
* roast plan ambiant temp selecion field in F was limited to 50 as in C, now correctly span to 122°F
* alog and beancave directory selection has been enhanced to check for write permission and also refresh gui correctly after selection

build 31
* fixed the pid on/off stop and timer reset when stopping a roast

build 30
* since the ci/cd engine has moved to pyinstaller , setting file was missing in the spec file, it now added for macos
* added explanation on how to use the roast plan generation in the text box where it is generated so that at first time it is displayed

build 29
* fixed power button status text update in tilauscope which was broken by another modification

build 28
* added aditiona control for alog and beancave directory for correctly handling path structure in windows
* specific encoding changed for all read/write file depending on platform to avoid problem of windows
* correctly hide new-style floating annotation in BeanCave and canvas when switching app or tab
* additional strengthening of existing beans in BeanCave procedures

build 27

build 26
* fix Tilauscope slider interval init, which was sometimes using float values from Artisan; forced to int (thank you SeaOry)

build 25
* fix DiFluid event recording, which was broken (x10 value) by an optimization routine; now sends the correct value
* Tilaupid go live; works very well to preheat on Skywalker V2
* DiFluid PID on ET was broken by a remapping; feature restored
* fixed floating window in BeanCave not always being displayed in the first minute of data
* fixed a bug where aset files were loaded by the roast viewer listbox, which obviously should not happen
* drag/drop in BeanCave now fixes the shifting jump bug
* changed colors of main curves on BeanCave preview to be easier to read; floating window now follows the mouse

build 23
* fixed missing f-string in advanced stats that was not displaying advised values in coach advice fields
* planning is now correctly centered on BeanCave window when opened

build 22
* added blinking timer when paused and not started
* added logic to properly close BeanCave from Close and Tilauscope buttons
* added a button for roast assistant on the main interface
* added a button for BeanCave on the main interface

build 21
* few screen optimizations for Tilauscope and compacting on the left to use less space

build 5
* next stage of roast assistant (called with SHIFT+A on Tilauscope)
* fix bug in loading deviation settings which were not loaded in BeanCave after a change
* water activity support in BeanCave is now working
* roast assistant (beta): press SHIFT+A when in Tilauscope mode only; window is on the right, select a bean from BeanCave and target color

build 2
* added standard Artisan Roaster Scope 4.0.4 features (see Artisan RS release notes attached for further information)
* new Qt 6.11 framework is used for improved Qt stability

ABOUT TILAUSCOPE
 
TilauScope is a functional extension built on top of Artisan Roaster Scope, the exceptional open-source roasting application created by Rafael Cobo, Marko Luther, Dave Baxter and contributors.
Artisan is a remarkably powerful platform — the result of years of dedicated work by its core developers, who have built one of the most complete and professional roast monitoring tools available. TilauScope does not seek to compete with or replace that work. It exists because of it.
Where Artisan excels at giving professionals and advanced users precise, granular control over every aspect of the roast, its depth can feel overwhelming for home roasters just starting out. TilauScope bridges that gap.
Designed primarily for amateur and home roasters, TilauScope adds an opinionated layer of guided assistance on top of Artisan's foundation: smarter event detection, contextual alerts, streamlined workflows, and hardware integrations tailored to the home setup — all while preserving the full power of Artisan underneath.
TilauScope is not a fork in the disruptive sense. It is a respectful extension — surgically additive, keeping its footprint minimal on Artisan's core so that upstream improvements can continue to flow in. The original authors remain the authors of what matters most.
If you roast at home and find Artisan's richness both inspiring and intimidating, TilauScope is for you.