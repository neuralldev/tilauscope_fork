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

test("a roast that cannot be deleted between roasts is not blamed on a roast on screen (P4-40)", async (t) => {
  const page = await openPage("beancave.html", { beans: [GUJI] });
  t.after(page.close);
  page.window.onSnapshot("delete_roast", null); // the session's call failed: the service hands null
  const said = page.$("toast").textContent;
  assert.ok(!/finish the roast on screen/.test(said), said);
  assert.match(said, /could not be deleted/);
});

test("the coffee the operator picked stays picked when the list is read again (P4-41)", async (t) => {
  const HUILA = { ...GUJI, name: "Huila", uuid: "0f8e6c1a-2b3c-4d5e-8f90-a1b2c3d4e5f6" };
  const page = await openPage("beancave.html", { beans: [GUJI, HUILA] });
  t.after(page.close);
  await page.settle();
  const doc = page.window.document;
  const pick = (uuid) => doc.querySelector('#list .it[data-u="' + uuid + '"]');
  const other = [GUJI, HUILA].find((c) => !pick(c.uuid).classList.contains("sel"));
  pick(other.uuid).click();
  page.window.send("get_coffees"); // as after a roast is deleted
  await page.settle();
  assert.ok(pick(other.uuid).classList.contains("sel"), "the operator's pick was dropped");
  assert.deepEqual(page.errors, []);
});
