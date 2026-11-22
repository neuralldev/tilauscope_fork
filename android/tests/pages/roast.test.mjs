// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The roast screen on the bench: the operator's touches, the real core's answers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { openPage } from "./bench.mjs";

const SKYWALKER = { machine: "skywalker-v2", roaster: { name: "TD5325A", address: "AA:BB:CC:DD:EE:FF" } };

async function roastScreen(config = SKYWALKER) {
  const page = await openPage("roast.html", { config });
  return page;
}

test("a started roast opens the roaster's link once, after the session records (W10)", async (t) => {
  const page = await roastScreen();
  t.after(page.close);
  page.tap(page.$("act"));
  assert.equal(page.sent("roast_link_connect").length, 0, "the link opens on the session's answer, not on the touch");
  await page.settle();
  const links = page.sent("roast_link_connect");
  assert.equal(links.length, 1);
  assert.equal(JSON.parse(links[0][1]).address, "AA:BB:CC:DD:EE:FF");
  assert.ok(JSON.parse(links[0][1]).end.includes("OFF"), "the link carries the end roast");
  assert.deepEqual(page.errors, []);
});

test("a refused start opens no link (W10)", async (t) => {
  const page = await roastScreen();
  t.after(page.close);
  page.refuse("start");
  page.tap(page.$("act"));
  await page.settle();
  assert.equal(page.sent("roast_link_connect").length, 0);
  assert.equal(page.$("toast").textContent, "Not possible right now");
  assert.deepEqual(page.errors, []);
});

test("two quick taps on + ask two steps, not the same value twice (W11)", async (t) => {
  const page = await roastScreen();
  t.after(page.close);
  const plus = page.window.document.querySelector("#mainlevers .plus");
  const before = page.sent("set").length;
  page.tap(plus);
  page.tap(plus); // before the first answer
  const asked = page.sent("set").slice(before).map((c) => c[1]);
  assert.equal(asked.length, 2);
  const [first, second] = asked.map((a) => parseInt(a.split(":")[1], 10));
  assert.ok(second > first, asked.join(" then "));
  await page.settle();
  const lever = asked[0].split(":")[0];
  assert.equal(page.window.snap.levers[lever].value, second);
});

test("a failed get_setup leaves the screen working (W12)", async (t) => {
  const page = await roastScreen();
  t.after(page.close);
  page.window.onSnapshot("get_setup", null);
  await page.tick(1);
  assert.deepEqual(page.errors, []);
});

test("before Start the plan is asked again when the green weight changes (W03)", async (t) => {
  const page = await roastScreen();
  t.after(page.close);
  await page.tick(1);
  const asked = page.sent("get_plan").length;
  await page.tick(1);
  assert.equal(page.sent("get_plan").length, asked, "nothing changed: not asked again");
  await page.session("set_weight", "green", 300);
  await page.tick(1);
  assert.equal(page.sent("get_plan").length, asked + 1);
});

test("the green weight is not rebuilt under the finger, then shows the scale (W06)", async (t) => {
  const page = await roastScreen();
  t.after(page.close);
  const chip = page.$("greenchip");
  chip.dispatchEvent(new page.window.Event("pointerdown", { bubbles: true }));
  page.window.onScale({ state: "connected", ready: true, weight_g: 412.3, stable: true, battery: 80 });
  assert.equal(page.$("greenchip"), chip, "rebuilt while pressed: the tap would be lost");
  chip.dispatchEvent(new page.window.Event("pointerup", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 5));
  assert.notEqual(page.$("greenchip"), chip);
  assert.match(page.$("greenchip").textContent, /412/);
});

test("while the link is away the roaster's levers are locked, the extractor is not (A03)", async (t) => {
  const page = await roastScreen({ ...SKYWALKER, devices: { extractor: { name: "AirWave 1234", address: "11:22:33:44:55:66", enabled: true } } });
  t.after(page.close);
  page.tap(page.$("act"));
  await page.settle();
  await page.session("link_state", JSON.stringify({ state: "connected" }));
  await page.tick(1);
  const burnerPlus = () => page.window.document.querySelector("#mainlevers .plus");
  assert.equal(burnerPlus().disabled, false);
  await page.session("link_state", JSON.stringify({ state: "reconnecting" }));
  await page.tick(1);
  assert.equal(burnerPlus().disabled, true);
  const extractor = page.window.chips.extractor;
  assert.ok(extractor, "the extractor's chip is on the screen");
  assert.equal(extractor.el.disabled, false, "the extractor is another machine: still free");
  const before = page.sent("set").length;
  page.tap(burnerPlus());
  assert.equal(page.sent("set").length, before, "a locked lever sends nothing");
  assert.deepEqual(page.errors, []);
});

test("AUTO and the guided bubble: chip, toast, countdown and Wait (GUIDED-SPEC G4)", async (t) => {
  const page = await roastScreen({ machine: "skywalker-v2" }); // the simulated roaster: samples without a link
  t.after(page.close);
  const auto = page.window.document.querySelector('#modes button[data-mode="auto"]');
  assert.ok(auto, "AUTO is a START face");
  page.tap(page.$("act"));
  await page.settle();
  await page.tick(5); // a few samples recorded
  const at = page.window.snap.last_sample_s; // milestones on recorded samples: the chart draws them
  assert.ok(at != null, "samples recorded");
  const w = page.window, base = { ...page.window.snap, milestone_s: { charge: at, dry_end: at, first_crack: at } }; // in development
  const pilot = { state: "paused", drop_in: null, beeps: 0, flash: [], seq: 0, text: null };
  w.onSnapshot("tick", { ...base, pilot, guide: { tone: "guide", title: "Burner 65 %", sub: "Now · next: burner 60 % at 168°" } });
  assert.equal(page.$("guide").classList.contains("hidden"), false);
  assert.equal(page.$("guidet").textContent, "Burner 65 %");
  assert.equal(page.$("autochip").classList.contains("paused"), true);
  page.tap(page.$("autochip"));
  assert.equal(page.sent("resume_auto").length, 1, "the paused chip resumes AUTO");
  w.onSnapshot("tick", { ...base, pilot: { ...pilot, state: "armed", drop_in: 7, seq: 1, text: "Burner 55 %", flash: ["burner"] }, guide: null });
  assert.equal(page.$("guide").classList.contains("hidden"), true, "AUTO speaks through its toast");
  assert.match(page.$("alarmtoast").textContent, /Burner 55 %/);
  assert.equal(page.$("actlabel").textContent, "Dropping in 7");
  assert.equal(page.$("wait").classList.contains("hidden"), false);
  page.tap(page.$("wait"));
  assert.equal(page.sent("cancel_auto_drop").length, 1);
  assert.deepEqual(page.errors, []);
});

test("the next roast's first AUTO event is not told as a toast (GUIDED-SPEC G4)", async (t) => {
  const page = await roastScreen({ machine: "skywalker-v2" });
  t.after(page.close);
  page.tap(page.$("act"));
  await page.settle();
  await page.tick(5);
  const at = page.window.snap.last_sample_s, w = page.window;
  const base = { ...w.snap, milestone_s: { charge: at, dry_end: at } };
  w.onSnapshot("tick", { ...base, pilot: { state: "armed", drop_in: null, beeps: 0, flash: [], seq: 6, text: "Burner 55 %" }, guide: null });
  w.onSnapshot("tick", { ...base, state: "idle", pilot: null, guide: null }); // a new roast
  w.$("alarmtoast").classList.add("gone");
  w.onSnapshot("tick", { ...base, pilot: { state: "armed", drop_in: null, beeps: 0, flash: [], seq: 1, text: "Back on the levers" }, guide: null });
  assert.equal(page.$("alarmtoast").classList.contains("gone"), true, "AUTO armed at START is not news");
  assert.deepEqual(page.errors, []);
});

test("a page reloaded during a roast does not recompute the plan on the session's worker (audit P2-20)", async (t) => {
  const page = await openPage("roast.html", { config: SKYWALKER, prepare: [["start"]] }); // the session already records
  t.after(page.close);
  await page.settle();
  assert.equal(page.sent("get_setup").length, 1);
  assert.equal(page.sent("get_plan").length, 0, "the plan is drawn from the snapshot while the roast records");
  assert.deepEqual(page.errors, []);
});

test("the ΔET of its setting, the forecast of the next milestone and the time in development (Tilau, 2026-11-22)", async (t) => {
  const page = await roastScreen({ machine: "skywalker-v2", det_curve: true }); // the simulated roaster
  t.after(page.close);
  page.tap(page.$("act")); // Start
  await page.settle();
  await page.tick(3);
  page.tap(page.$("act")); // Charge
  await page.settle();
  await page.tick(150);
  assert.notEqual(page.$("detp").getAttribute("d"), "", "the ET's RoR is drawn");
  assert.match(page.$("btnote").textContent, /ΔET [+−]\d/);
  const f = page.window.snap.forecast;
  assert.equal(f && f.milestone, "dry_end");
  assert.notEqual(page.$("fcp").getAttribute("d"), "", "the forecast line is drawn");
  assert.match(page.$("labels").textContent, /DRY END \d+:\d\d/);
  assert.match(page.$("steps").querySelector(".time.eta").textContent, /^~\d+:\d\d$/, "the next milestone shows when it is due");
  assert.ok(page.$("devcap").classList.contains("hidden"));
  await page.session("mark", "dry_end");
  await page.session("mark", "first_crack");
  await page.tick(30);
  assert.equal(page.window.snap.forecast, null, "nothing left to forecast after First crack");
  assert.equal(page.$("fcp").getAttribute("d"), "");
  assert.ok(!page.$("devcap").classList.contains("hidden"), "the time in development is the readout");
  assert.ok(page.$("phase").classList.contains("hidden"));
  assert.match(page.$("devtime").textContent, /^0:(29|30|31)$/);
  assert.match(page.$("devpct").textContent, /^\d+ %$/);
  assert.deepEqual(page.errors, []);
});

test("without its setting the ΔET is neither drawn nor read", async (t) => {
  const page = await roastScreen({ machine: "skywalker-v2" });
  t.after(page.close);
  page.tap(page.$("act"));
  await page.settle();
  await page.tick(3);
  page.tap(page.$("act"));
  await page.settle();
  await page.tick(120);
  assert.equal(page.$("detp").getAttribute("d"), "");
  assert.doesNotMatch(page.$("btnote").textContent, /ΔET/);
  assert.deepEqual(page.errors, []);
});

test("the crack counter's chip names what it hears and each crack is a tick on the curve", async (t) => {
  const ambient = { ambient: { name: "TilauAmbient", address: "11:22:33:44:55:66", enabled: true } };
  const page = await roastScreen({ machine: "skywalker-v2", crack_detection: true, devices: ambient });
  t.after(page.close);
  page.tap(page.$("act")); // Start
  await page.settle();
  await page.tick(25); // CAL1 at Start + 20 s, listening to the empty drum
  assert.match(page.$("cracktext").textContent, /empty drum/);
  page.tap(page.$("act")); // Charge
  await page.settle();
  await page.tick(5);
  await page.session("mark", "dry_end");
  await page.tick(132); // CAL2 at Dry end + 90 s, the probe's Start 40 s later
  assert.match(page.$("cracktext").textContent, /LISTENING/);
  await page.session("crack_count", 0);
  await page.tick(1);
  await page.session("crack_count", 3);
  await page.tick(1);
  const chip = page.$("crackchip");
  assert.ok(chip.classList.contains("count"));
  assert.match(page.$("cracktext").textContent, /FIRST CRACKS/);
  assert.equal(chip.querySelector(".cn").textContent, "3");
  assert.equal(page.$("crackp").getAttribute("d").match(/M/g).length, 3, "one tick per crack");
  assert.deepEqual(page.errors, []);
});

test("while recording, BeanCave, Settings and the name give their room to the roast (Tilau, 2026-11-22)", async (t) => {
  const page = await roastScreen({ machine: "skywalker-v2" });
  t.after(page.close);
  await page.tick(1);
  const shown = () => ["gear", "cavebtn", "brand"].map((id) => !page.$(id).classList.contains("hidden"));
  assert.deepEqual(shown(), [true, true, true]);
  page.tap(page.$("act")); // Start
  await page.settle();
  await page.tick(2);
  assert.deepEqual(shown(), [false, false, false]);
  await page.session("stop");
  await page.tick(1);
  assert.deepEqual(shown(), [true, true, true]);
  assert.deepEqual(page.errors, []);
});
