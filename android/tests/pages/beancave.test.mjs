// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The BeanCave's coffee editor on the bench.
import { test } from "node:test";
import assert from "node:assert/strict";
import { openPage } from "./bench.mjs";

const GUJI = { name: "Guji Kurume", country: "Ethiopia", process: "Natural", crop: 2025, sca: 88.0, varieties: "Kurume",
  water_activity: 0.59, weight_left: 2000.0, uuid: "a82364a8-e9ad-447c-a3d8-5f49111dc3ee", density: 712.0, last_humidity: 11.5 };

test("a decimal comma typed in the editor survives a redraw and is saved (W02)", async (t) => {
  const page = await openPage("beancave.html", { beans: [GUJI], prepare: [["choose_coffee", GUJI.uuid]] });
  t.after(page.close);
  const doc = page.window.document;
  const zone = [...doc.querySelectorAll("#sheet [data-z]")].find((z) => z.querySelector(".zh") && /CHARACTERISTICS/.test(z.textContent));
  assert.ok(zone, "the coffee's sheet shows its characteristics");
  zone.click();
  const moisture = () => doc.querySelector('#ce [data-k="last_humidity"]');
  moisture().value = "12,3";
  moisture().oninput();
  const measure = doc.querySelector("#ce-measure"); // the density measure opens: the form is drawn again
  assert.ok(measure, "the density measure in the form");
  measure.click();
  assert.equal(moisture().value, "12,3");
  page.$("ce-save").click();
  const saved = page.sent("save_coffee").map((c) => JSON.parse(c[1]));
  assert.equal(saved.length, 1);
  assert.equal(saved[0].values.last_humidity, 12.3);
  await page.settle();
  assert.deepEqual(page.errors, []);
});
