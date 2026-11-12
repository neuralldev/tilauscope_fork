// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// Settings on the bench: what the operator changed, the link check.
import { test } from "node:test";
import assert from "node:assert/strict";
import { openPage } from "./bench.mjs";

const SKYWALKER = { machine: "skywalker-v2", roaster: { name: "TD5325A", address: "AA:BB:CC:DD:EE:FF" } };
const tab = (page, t) => page.window.document.querySelector(`.tab[data-t="${t}"]`).click();

test("Change (the machine) saves what was changed before opening the assistant (W07)", async (t) => {
  const page = await openPage("settings.html", { config: SKYWALKER });
  t.after(page.close);
  tab(page, "general");
  page.window.document.querySelector('#unit [data-u="F"]').click();
  page.$("redo").click();
  const saved = page.sent("save_setup");
  assert.equal(saved.length, 1, "the change is saved first");
  assert.equal(JSON.parse(saved[0][1]).unit, "F");
  await page.settle();
  assert.deepEqual(page.went, ["setup.html"]);
  const setup = await page.session("get_setup");
  assert.equal(setup.reply.config.unit, "F");
  assert.deepEqual(page.errors, []);
});

test("a link check asked while the roaster cools waits, then starts by itself (B05)", async (t) => {
  const page = await openPage("settings.html", { config: SKYWALKER });
  t.after(page.close);
  tab(page, "devices");
  await page.push("classify_scan", JSON.stringify([{ address: "AA:BB:CC:DD:EE:FF", name: "TD5325A", rssi: -60, uuids: [] }])); // heard
  page.$("test").click();
  assert.equal(page.sent("link_connect").length, 1);
  // The service refuses the check while the roast link cools: the page hears the roast link instead.
  page.window.onLink({ state: "cooling", bt: 120.4, et: 110.2, burner: 0, air: 100 });
  assert.match(page.$("ckbox").textContent, /Cooling the last roast/);
  assert.match(page.$("ckbox").textContent, /120\.4/);
  page.window.onLink({ state: "cooling", bt: 80.1, et: 75.0, burner: 0, air: 100 });
  assert.equal(page.sent("link_connect").length, 1, "nothing asked while it cools");
  page.window.onLink({ state: "idle" }); // the roaster has stopped
  assert.equal(page.sent("link_connect").length, 2, "the check starts once the roast link is let go");
  assert.deepEqual(page.errors, []);
});
