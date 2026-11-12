// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// Roast Setup on the bench: a coffee chosen in the BeanCave, the real core's answers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { openPage } from "./bench.mjs";

const GUJI = { name: "Guji Kurume", country: "Ethiopia", process: "Natural", crop: 2025, sca: 88.0, varieties: "Kurume",
  water_activity: 0.59, weight_left: 2000.0, uuid: "a82364a8-e9ad-447c-a3d8-5f49111dc3ee", density: 712.0, last_humidity: 11.5 };
const SKYWALKER = { machine: "skywalker-v2", roaster: { name: "TD5325A", address: "AA:BB:CC:DD:EE:FF" }, preheat_on: true };

async function roastSetup(config = SKYWALKER) {
  return openPage("roast-setup.html", { config, beans: [GUJI], prepare: [["choose_coffee", GUJI.uuid]] });
}
const sentSetup = (page) => page.sent("set_roast_setup").map((c) => JSON.parse(c[1]));

test("a preheat target out of range is refused with the session's words (W09)", async (t) => {
  const page = await roastSetup();
  t.after(page.close);
  assert.deepEqual(page.errors, []);
  page.$("green").value = "250";
  page.$("phtarget").value = "999";
  page.$("phtarget").oninput();
  page.$("ready").click();
  assert.equal(sentSetup(page).length, 0);
  assert.equal(page.$("toast").textContent, "A preheat target is between 50 and 300 °C");
  assert.ok(page.$("phtarget").classList.contains("bad"));
  page.$("phtarget").value = "abc";
  page.$("ready").click();
  assert.equal(sentSetup(page).length, 0, "a target that is no number is refused too");
});

test("the plan's charge offered as target is sent as not typed, the operator's own as typed (W04)", async (t) => {
  const page = await roastSetup();
  t.after(page.close);
  page.$("green").value = "250";
  page.$("phtarget").value = "200"; // as fill() shows the plan's charge: no input event
  page.$("ready").click();
  page.$("phtarget").value = "205";
  page.$("phtarget").oninput(); // typed by the operator
  page.$("ready").click();
  const [offered, typed] = sentSetup(page).map((s) => s.preheat);
  assert.equal(offered.typed, false);
  assert.equal(typed.typed, true);
  assert.equal(typed.target, 205);
  await page.settle();
  assert.deepEqual(page.errors, []);
});

test("in °F the plan's chart is graduated in °F (W05)", async (t) => {
  const page = await roastSetup({ ...SKYWALKER, unit: "F" });
  t.after(page.close);
  page.$("green").value = "250";
  page.window.document.querySelector('#tabs [data-t="plan"]').click();
  await page.settle();
  page.window.document.querySelector('[data-level="Medium"]').click(); // a level: the plan is drawn
  await page.settle();
  const chart = page.$("pchart");
  assert.ok(chart, "the plan's chart is shown");
  const labels = [...chart.querySelectorAll("text")].map((e) => e.textContent);
  for (const tick of ["200", "300", "400", "°F", "°F/min"]) assert.ok(labels.includes(tick), `${tick} missing: ${labels.join(" ")}`);
  assert.ok(!labels.includes("250"), "a °C tick in a °F chart");
});
