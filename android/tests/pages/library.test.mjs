// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// BeanCave › Library and the coffee sheet on the bench: the relay is a fake the page bench answers, the files are real packages.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, existsSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { openPage } from "./bench.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const VENV = join(HERE, "..", "..", "..", ".venv/bin/python");
const PYTHON = existsSync(VENV) ? VENV : "python3";

function packages() {
  const folder = mkdtempSync(join(tmpdir(), "tilau-coffee-"));
  const made = spawnSync(PYTHON, [join(HERE, "make_coffee.py"), folder], { encoding: "utf8" });
  assert.equal(made.status, 0, made.stderr);
  return JSON.parse(made.stdout);
}
const SKY = { machine: "skywalker-v2" };
const text = (el) => el.textContent.replace(/\s+/g, " ").trim();

async function libraryPage(t, extra = {}) {
  const made = packages();
  const page = await openPage("beancave.html", {
    config: SKY, beans: [{ name: "Cortes", country: "Honduras", process: "Washed", crop: 2024, weight_left: 1200, uuid: "c0c0c0c0-0000-0000-0000-000000000001" }],
    relay: { index: [made.card, made.other], packages: { [made.card.id]: made.good } }, ...extra });
  t.after(page.close);
  await page.settle();
  return { page, made, doc: page.window.document };
}
const openLibrary = async (page) => { page.tap([...page.window.document.querySelectorAll("#tabs button")].find((b) => b.dataset.t === "library")); await page.settle(); };

const ID3 = "0".repeat(31) + "3";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
// The search asks the relay once the typing pauses (400 ms).
async function typeSearch(page, value) { page.$("lb-search").value = value; page.$("lb-search").oninput(); await wait(450); await page.settle(); }
const asks = (page) => page.sent("library_page").map((c) => JSON.parse(c[1]));
// jsdom lays nothing out: the list as a scrolled one, `top` pixels down a 1000 px list in a 600 px box.
function scrolled(page, top) {
  const rows = page.$("lb-rows");
  Object.defineProperty(rows, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(rows, "clientHeight", { value: 600, configurable: true });
  Object.defineProperty(rows, "scrollTop", { value: top, writable: true, configurable: true });
  rows.dispatchEvent(new page.window.Event("scroll"));
  rows.scrollTop = 0; // back up: the page that answers does not ask the next one by itself
}
function many(made, n) {
  return Array.from({ length: n }, (_, i) => ({ ...made.card, id: (i + 16).toString(16).padStart(32, "0"), name: "Coffee " + i,
    roasted: "2026-10-" + String(28 - i).padStart(2, "0") }));
}
const shortDay = (y, m, d) => new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

test("the Library lists roasts newest first, under a My machine chip and a count", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t, { relay: { index: [{ ...made.card, roasted: "2026-10-01" }, { ...made.other, roasted: "2026-11-02" },
    { ...made.card, id: ID3, name: "Undated" }], packages: { [made.card.id]: made.good } } });
  await openLibrary(page);
  const names = () => [...doc.querySelectorAll("#lb-rows .lb-row b")].map((b) => b.textContent);
  assert.deepEqual(names(), ["Barazilie", "Catuai", "Undated"]); // My machine is off by default: every machine; undated last
  assert.equal(text(page.$("lb-count")), "3 roasts · newest first");
  assert.equal(asks(page)[0].mine, false, "no machine asked by default");
  const chip = page.$("lb-mine");
  assert.equal(text(chip), "My machine");
  assert.equal(chip.getAttribute("aria-pressed"), "false");
  assert.ok(!chip.classList.contains("on"));
  assert.equal(chip.getAttribute("role"), null, "a chip, not a switch");
  assert.equal(chip.querySelector(".switch"), null);
  assert.equal(doc.querySelector("#lb-grid"), null, "no grid of mini curves any more");
  assert.equal(doc.querySelector("#lb-rows .ld, #lb-rows svg"), null, "no coloured dot, no curve in the list");
  page.tap(chip);
  await page.settle();
  assert.equal(chip.getAttribute("aria-pressed"), "true");
  assert.ok(chip.classList.contains("on"));
  assert.deepEqual(names(), ["Catuai", "Undated"]); // Skywalker V2 only
  assert.equal(text(page.$("lb-count")), "2 roasts · newest first");
  page.tap(chip);
  await page.settle();
  assert.equal(chip.getAttribute("aria-pressed"), "false");
  assert.deepEqual(names(), ["Barazilie", "Catuai", "Undated"]);
  assert.equal(text(page.$("lb-count")), "3 roasts · newest first");
  const row = doc.querySelector("#lb-rows .lb-row");
  assert.equal(text(row.querySelector(".d")), shortDay(2026, 11, 2));
  assert.equal(text(row.querySelector(".l2")), "Honduras · Washed");
  assert.equal(text(row.querySelector(".l3")), "Aillio Bullet");
  assert.equal(text(doc.querySelectorAll("#lb-rows .lb-row .d")[2]), "");
  await typeSearch(page, "BARAZ");
  assert.deepEqual(names(), ["Barazilie"]);
  assert.equal(text(page.$("lb-count")), "1 roast · newest first");
  await typeSearch(page, "nothing like it");
  assert.match(text(page.$("lb-side")), /No coffee matches\s*Clear the search, or turn off My machine\./);
  assert.deepEqual(page.errors, []);
});

test("the selected roast loads, then is drawn as the Roasts tab draws a roast, with their tasting and Import", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t, { relay: { index: [made.card, { ...made.other, verdict: "", flavours: [] }], packages: { [made.card.id]: made.good } } });
  const seen = [];
  page.tap([...doc.querySelectorAll("#tabs button")].find((b) => b.dataset.t === "library"));
  page.tap(page.$("lb-mine")); // My machine on: the first row is Catuai
  new page.window.MutationObserver(() => seen.push(text(page.$("lb-side")))).observe(page.$("lb-side"), { childList: true, subtree: true });
  await page.settle();
  assert.ok(seen.some((s) => /Loading the roast card…/.test(s)), "the placeholder while the package is read");
  assert.deepEqual(page.sent("library_card").map((c) => c[1]), [made.card.id]);
  const side = page.$("lb-side");
  const svg = side.querySelector(".mini svg");
  assert.ok(svg, "the roast's own chart");
  const colours = (await page.session("get_setup")).reply.catalogue.colours;
  assert.ok([...svg.querySelectorAll("path")].some((p) => p.getAttribute("stroke") === colours.grain && p.getAttribute("stroke-width") === "3"), "the bean temperature, in its colour");
  assert.ok([...svg.querySelectorAll("text")].some((x) => x.getAttribute("fill") === colours.grain_rise && x.textContent === "15"), "the RoR scale");
  assert.ok([...svg.querySelectorAll("text")].some((x) => x.textContent === "200"), "the temperature scale");
  assert.match(text(svg), /FIRST CRACK/);
  assert.deepEqual([...side.querySelectorAll(".tile .cap")].map(text), ["Roasted weight", "Roast time", "Drop temperature", "Colour"]);
  assert.match(text(side), /THEIR TASTING\s*Liked it · would roast it the same way/);
  assert.match(text(side), /Fruits rouges/);
  assert.match(text(side), /Roasted on a Skywalker V2, like yours/);
  assert.equal(text(page.$("lb-import")), "Import this coffee");
  page.tap(page.$("lb-mine"));
  await page.settle();
  page.tap(doc.querySelectorAll("#lb-rows .lb-row")[1]); // Barazilie: no tasting, another machine, withdrawn from the relay
  assert.match(text(side), /Loading the roast card…/);
  assert.match(text(side), /THEIR TASTING\s*Not tasted/);
  assert.ok(side.querySelector(".lb-verdict.not"), "muted");
  assert.equal(side.querySelector(".chips"), null);
  await page.settle();
  assert.match(text(side), /The roast card could not be loaded: its author withdrew this roast from the library\./);
  assert.equal(side.querySelector(".mini svg"), null);
  assert.match(text(side), /Roasted on a Aillio Bullet\. Use it as a curve to read, not to copy\./);
  assert.ok(side.querySelector(".mach.other"));
  assert.equal(page.$("toast").style.display || "none", "none", "said in the card's place, no dialog nor toast");
  assert.deepEqual(page.errors, []);
});

test("a roast answered after another was selected is kept, not shown; a failure is retried by touching the row again", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t, { relay: { index: [made.card, made.other], packages: { [made.card.id]: made.good, [made.other.id]: made.good } } });
  await openLibrary(page);
  assert.equal(page.$("lb-mine").getAttribute("aria-pressed"), "false");
  const rows = () => doc.querySelectorAll("#lb-rows .lb-row");
  page.tap(rows()[1]); // Barazilie asked…
  page.tap(rows()[0]); // …then Catuai, already read: drawn at once
  assert.ok(page.$("lb-side").querySelector(".mini svg"));
  await page.settle();
  assert.equal(text(page.$("lb-side").querySelector("h3")), "Catuai", "Barazilie's answer did not take the screen");
  page.tap(rows()[1]);
  assert.ok(page.$("lb-side").querySelector(".mini svg"), "kept: drawn at once");
  assert.equal(page.sent("library_card").filter((c) => c[1] === made.other.id).length, 1);

  assert.deepEqual(page.errors, []);
});

test("no connection while a roast loads: the desktop's sentence, and the same row touched again retries", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t, { relay: { index: [made.card], packages: {} } });
  await openLibrary(page);
  assert.match(text(page.$("lb-side")), /its author withdrew this roast from the library\./);
  page.relay({ error: "offline" });
  page.tap(doc.querySelector("#lb-rows .lb-row")); // touched again: asked again
  await page.settle();
  assert.match(text(page.$("lb-side")), /The roast card could not be loaded: the library cannot be reached\. Check the internet connection, then select the roast again\./);
  page.relay({ index: [made.card], packages: { [made.card.id]: made.good } });
  page.tap(doc.querySelector("#lb-rows .lb-row"));
  assert.match(text(page.$("lb-side")), /Loading the roast card…/);
  await page.settle();
  assert.ok(page.$("lb-side").querySelector(".mini svg"), "retried and drawn");
  assert.deepEqual(page.errors, []);
});

test("importing from the library lands on the All list with the coffee selected", async (t) => {
  const { page, made, doc } = await libraryPage(t);
  await openLibrary(page);
  page.tap(page.$("lb-import"));
  await page.settle();
  assert.deepEqual(page.sent("library_get").map((c) => c[1]), [made.card.id]);
  const sheet = page.$("cs");
  assert.ok(sheet, "the same preview sheet as an opened file");
  assert.match(text(sheet), /Catuai SHARED/);
  assert.match(text(sheet), /Nothing on this tablet is replaced\./);
  assert.match(text(sheet), /1 roast.*Its tasting/);
  page.tap(page.$("cs-import"));
  await page.settle();
  assert.equal(page.$("cs"), null, "the sheet is gone");
  assert.equal(doc.querySelector("#libview").classList.contains("hidden"), true);
  assert.equal(doc.querySelector('#seg [data-f="all"]').classList.contains("on"), true, "the list switches to All");
  assert.match(text(doc.querySelector('#seg [data-f="all"]')), /All · 2/);
  const row = doc.querySelector("#list .it.sel");
  assert.equal(row.dataset.u, made.uuid);
  assert.match(text(row), /Catuai SHARED/);
  assert.match(text(row), /0 g/); // it arrives without stock
  assert.equal(text(page.$("toast")), "Coffee imported: Catuai");
  assert.match(text(page.$("sheet")), /THEIR ROAST/);
  assert.ok(page.$("theirs").querySelector("svg.curve"), "their roast is drawn once it is read");
  assert.deepEqual(page.errors, []);
});

test("an opened file shows its sheet, and touching elsewhere closes it: no X", async (t) => {
  const { page, made } = await libraryPage(t);
  page.staged = made.good;
  page.window.coffeeStaged();
  await page.settle();
  const sheet = page.$("cs");
  assert.ok(sheet);
  assert.deepEqual([...sheet.querySelectorAll("button")].map((b) => text(b)), ["Import"]); // no close button
  page.tap(sheet.querySelector(".tsheet")); // inside: stays
  assert.ok(page.$("cs"));
  page.tap(sheet); // elsewhere: closes, and the app drops the staged file
  assert.equal(page.$("cs"), null);
  assert.equal(page.sent("coffee_dismiss").length, 1);
  assert.equal(page.staged, null);
});

test("the sheet opens by itself when the app opens the page on a file", async (t) => {
  const made = packages();
  const page = await openPage("beancave.html", { config: SKY, staged: made.good, hash: "#coffee" });
  t.after(page.close);
  await page.settle();
  assert.equal(page.window.location.hash, "#coffee");
  assert.ok(page.$("cs"), "the preview sheet");
  assert.match(text(page.$("cs")), /Catuai SHARED/);
  assert.deepEqual(page.sent("library_page"), [], "a file opened from another app asks nothing of the library");
});

test("the sheet states: an unreadable file, one from a newer TilauScope, and a cave kept by the computer", async (t) => {
  const { page, made } = await libraryPage(t);
  for (const [file, title, tail] of [[made.bad, "This file cannot be read", /Nothing was changed\..*Ask the roaster to send it again\./],
                                      [made.newer, "This file needs a newer TilauScope", /Update the app/]]) {
    page.staged = file;
    page.window.coffeeStaged();
    await page.settle();
    const sheet = page.$("cs");
    assert.match(text(sheet), new RegExp(title));
    assert.match(text(sheet), tail);
    assert.equal(sheet.querySelector("#cs-import"), null, "nothing to import");
    page.tap(sheet);
  }
  const mine = await libraryPage(t, { config: { ...SKY, cave_owner: "computer" } });
  mine.page.staged = mine.made.good;
  mine.page.window.coffeeStaged();
  await mine.page.settle();
  const sheet = mine.page.$("cs");
  assert.match(text(sheet), /On this tablet only: the next exchange with your computer removes it\./);
  assert.match(text(mine.page.$("cs-send")), /Send the file to the computer/);
  mine.page.tap(mine.page.$("cs-send"));
  assert.equal(mine.page.sent("coffee_file_send").length, 1);
  mine.page.tap(mine.page.$("cs-import")); // the import stays allowed, whoever owns the cave
  await mine.page.settle();
  assert.equal(text(mine.page.$("toast")), "Coffee imported: Catuai");
});

test("the Library's states: loading, no connection with a retry, an empty library", async (t) => {
  const { page, doc } = await libraryPage(t, { relay: { error: "offline" } });
  page.tap([...doc.querySelectorAll("#tabs button")].find((b) => b.dataset.t === "library"));
  assert.match(text(page.$("lb-state")), /Loading the library…/); // before the library answers
  await page.settle();
  assert.match(text(page.$("lb-state")), /The library cannot be reached.*Check the internet connection\. Your own coffees and roasts are not affected\./);
  page.relay({ index: [] });
  page.tap(page.$("lb-retry"));
  await page.settle();
  assert.equal(page.$("lb-browse").classList.contains("hidden"), false);
  assert.match(text(page.$("lb-side")), /No roast in the library yet/, "My machine is off by default");
  page.tap(page.$("lb-mine"));
  await page.settle();
  assert.match(text(page.$("lb-side")), /No coffee matches/, "My machine is on: the relay counts only its roasts");
  assert.equal(page.sent("library_page").length, 3);
});

test("a download that fails says so and leaves the library as it was", async (t) => {
  const { page, made } = await libraryPage(t);
  await openLibrary(page);
  page.relay({ index: [made.card], packages: {} }); // the coffee is gone from the relay
  page.tap(page.$("lb-import"));
  await page.settle();
  assert.equal(text(page.$("toast")), "This coffee is no longer in the library");
  assert.equal(page.$("cs"), null);
  assert.equal(page.$("lb-import").disabled, false);
});

test("the send pictogram on a coffee writes a package for the share sheet; the zone itself stays the editor's", async (t) => {
  const { page, made } = await libraryPage(t);
  const button = page.$("sendcoffee");
  assert.equal(button.getAttribute("aria-label"), "Send this coffee and its roasts to the computer");
  page.tap(button);
  await page.settle();
  assert.deepEqual(page.sent("coffee_send").map((c) => c[1]), ["c0c0c0c0-0000-0000-0000-000000000001"]);
  assert.equal(page.$("ce"), null, "the editor did not open under the pictogram");
  assert.deepEqual(readdirSync(join(page.folder, "cache", "coffee-share")), ["Cortes.tilaucoffee"]);
  assert.deepEqual(page.errors, []);
  void made;
});

test("nothing of the library is asked before its tab is shown, then its first page once", async (t) => {
  const { page, made, doc } = await libraryPage(t);
  page.staged = made.good;
  page.window.coffeeStaged(); // a file from another app
  await page.settle();
  page.tap(page.$("cs"));
  const tab = (name) => page.tap([...doc.querySelectorAll("#tabs button")].find((b) => b.dataset.t === name));
  tab("roasts");
  tab("coffees");
  await page.settle();
  assert.deepEqual(page.sent("library_page"), []);
  tab("library");
  await page.settle();
  assert.deepEqual(asks(page).map((a) => [a.text, a.mine, a.cursor]), [["", false, ""]]);
  tab("coffees");
  tab("library");
  await page.settle();
  assert.equal(page.sent("library_page").length, 1, "shown again: the list stays as it was");
  assert.deepEqual(page.errors, []);
});

test("pages of ten: scrolling near the end adds the next page, the count is the relay's total", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t, { relay: { index: many(made, 23), packages: {} } });
  await openLibrary(page);
  const rows = () => doc.querySelectorAll("#lb-rows .lb-row");
  assert.equal(rows().length, 10);
  assert.equal(text(page.$("lb-count")), "23 roasts · newest first");
  scrolled(page, 100); // far from the end: nothing asked
  assert.equal(page.sent("library_page").length, 1);
  scrolled(page, 300);
  assert.equal(text(page.$("lb-more")), "Loading more…");
  await page.settle();
  assert.equal(rows().length, 20);
  assert.equal(text(rows()[10].querySelector("b")), "Coffee 10");
  assert.equal(page.$("lb-more"), null);
  scrolled(page, 380);
  await page.settle();
  assert.equal(rows().length, 23);
  scrolled(page, 400); // the last page: nothing more to ask
  await page.settle();
  assert.deepEqual(asks(page).map((a) => a.cursor), ["", "10", "20"]);
  assert.equal(text(page.$("lb-count")), "23 roasts · newest first");
  assert.deepEqual(page.errors, []);
});

test("a page that cannot be added says so in the list's last row, touched to try again", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t, { relay: { index: many(made, 12), packages: {} } });
  await openLibrary(page);
  page.relay({ error: "offline" });
  scrolled(page, 400);
  await page.settle();
  assert.equal(text(page.$("lb-more")), "Could not load more. Touch to try again.");
  assert.equal(doc.querySelectorAll("#lb-rows .lb-row").length, 10, "the roasts shown stay");
  assert.equal(page.$("lb-browse").classList.contains("hidden"), false);
  assert.equal(page.$("toast").style.display || "none", "none", "no toast nor dialog");
  page.relay({ index: many(made, 12), packages: {} });
  page.tap(page.$("lb-more"));
  await page.settle();
  assert.equal(doc.querySelectorAll("#lb-rows .lb-row").length, 12);
  assert.equal(page.$("lb-more"), null);
  assert.deepEqual(page.errors, []);
});

test("the search asks the relay once the typing pauses; My machine asks at once; each starts from page one", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t, { relay: { index: [...many(made, 12), { ...made.other, roasted: "2026-11-02" }], packages: {} } });
  await openLibrary(page);
  scrolled(page, 400);
  await page.settle();
  assert.equal(doc.querySelectorAll("#lb-rows .lb-row").length, 13);
  for (const v of ["c", "co", "cof"]) { page.$("lb-search").value = v; page.$("lb-search").oninput(); }
  await wait(200);
  assert.equal(page.sent("library_page").length, 2, "still typing: nothing asked");
  await wait(250);
  await page.settle();
  assert.deepEqual(asks(page).slice(2).map((a) => [a.text, a.cursor]), [["cof", ""]]);
  assert.equal(doc.querySelectorAll("#lb-rows .lb-row").length, 10, "page one of the search, in the list's place");
  page.tap(page.$("lb-mine"));
  assert.deepEqual(asks(page).slice(3).map((a) => [a.text, a.mine, a.cursor]), [["cof", true, ""]], "asked at once");
  await page.settle();
  assert.equal(text(page.$("lb-count")), "12 roasts · newest first");
  assert.deepEqual(page.errors, []);
});

test("a reply the page no longer waits for is dropped", async (t) => {
  const made = packages();
  const { page, doc } = await libraryPage(t);
  await openLibrary(page);
  const names = () => [...doc.querySelectorAll("#lb-rows .lb-row b")].map((b) => b.textContent);
  assert.deepEqual(names(), ["Catuai", "Barazilie"], "off by default: every machine");
  page.tap(page.$("lb-mine")); // mine…
  page.tap(page.$("lb-mine")); // …every machine…
  page.tap(page.$("lb-mine")); // …then mine again, before the first answer
  await page.settle();
  assert.deepEqual(names(), ["Catuai"]);
  assert.equal(text(page.$("lb-count")), "1 roast · newest first");
  const stale = asks(page)[1].seq;
  page.window.onSnapshot("library_page", { reply: { seq: stale, cards: [made.other], next: "", total: 1, machine: "Skywalker V2" } });
  assert.deepEqual(names(), ["Catuai"], "an older page did not take the list");
  assert.deepEqual(page.errors, []);
});
