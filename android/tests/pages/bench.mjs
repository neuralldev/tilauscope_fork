// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The page bench: a WebView page in jsdom, its TilauBridge played by the app. Each call is routed as
// MainActivity.command routes it (read from MainActivity.kt), run on the real Python core as
// SessionService.run runs it (session_server.py), and answered through onSnapshot, later, as the
// WebView gets it. What leaves for a device (a link, a scale) is only recorded: tests answer with onLink, onScale…
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const HERE = dirname(fileURLToPath(import.meta.url));
const ANDROID = join(HERE, "..", "..");
const ASSETS = process.env.TILAU_ASSETS || join(ANDROID, "app/src/main/assets"); // another copy, to prove a test red
const ACTIVITY = join(ANDROID, "app/src/main/java/org/tilauscope/android/prototype/MainActivity.kt");
const VENV = join(ANDROID, "..", ".venv/bin/python");
const PYTHON = existsSync(VENV) ? VENV : "python3";

// MainActivity.command's plain cases: `"a", "b" -> service.execute(method[, argument])`.
function plainRoutes() {
  const source = readFileSync(ACTIVITY, "utf8");
  const body = source.slice(source.indexOf("private fun command("), source.indexOf("private fun withConnect"));
  const routes = {};
  const entry = /((?:"\w+",\s*)*"\w+")\s*->\s*(?:\n\s*)?service\.execute\((method|"(\w+)")(, argument)?\)\s*$/gm;
  for (const m of body.matchAll(entry))
    for (const name of m[1].match(/"(\w+)"/g).map((s) => s.slice(1, -1))) routes[name] = { to: m[3] || name, arg: !!m[4] };
  return routes;
}
const PLAIN = plainRoutes();

// The cases that read their argument, as MainActivity.command does.
function route(method, arg, folder) {
  const pair = () => arg.split(":");
  switch (method) {
    case "start": return ["start", [arg || "hand"]];
    case "mark": return ["mark", [arg]];
    case "set": { const [k, v] = pair(); return /^-?\d+$/.test(v || "") ? ["set_lever", [k, parseInt(v, 10)]] : null; }
    case "weight": { const [k, v] = pair(); return /^-?\d+$/.test(v || "") ? ["set_weight", [k, parseInt(v, 10)]] : null; }
    case "colour": { const [k, v] = pair(); return isNaN(parseFloat(v)) ? null : ["set_colour", [k, parseFloat(v)]]; }
    case "set_speed": return /^-?\d+$/.test(arg) ? ["set_speed", [parseInt(arg, 10)]] : null;
    case "save": return ["export_alog", [join(folder, "roasts")]];
    case "alarm_share": return ["alarm_list_file", [arg]];
  }
  const plain = PLAIN[method];
  return plain ? [plain.to, plain.arg ? [arg] : []] : null; // null: a device, a picker, a share sheet
}

/** Opens `name` (roast.html…) on a fresh session. `config`: settings over the app's defaults (Settings saved);
 *  `beans`: the BeanCave's green coffees; `prepare`: session calls made before the page opens ([method, ...args]). */
export async function openPage(name, { config = null, beans = null, prepare = [], before = null } = {}) {
  const folder = mkdtempSync(join(tmpdir(), "tilau-pages-"));
  if (config) writeFileSync(join(folder, "overrides.json"), JSON.stringify(config));
  if (beans) {
    mkdirSync(join(folder, "beancave"));
    writeFileSync(join(folder, "beancave", "beancave.json"), JSON.stringify({ green_beans: beans }));
  }
  const python = spawn(PYTHON, [join(HERE, "session_server.py"), folder], { stdio: ["pipe", "pipe", "pipe"] });
  const stderr = [];
  python.stderr.on("data", (d) => stderr.push(String(d)));
  const answers = [];
  createInterface({ input: python.stdout }).on("line", (line) => answers.shift()(JSON.parse(line)));
  const ask = (method, args) => new Promise((resolve) => { answers.push(resolve); python.stdin.write(JSON.stringify({ method, args }) + "\n"); });

  for (const [method, ...args] of prepare) await ask(method, args);
  const page = { calls: [], went: [], errors: [], stderr, folder, commands: [], refused: new Set() };
  let pending = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => page.errors.push(String(e.stack || e)));
  virtualConsole.on("error", (...a) => page.errors.push(a.join(" ")));
  const deliver = (method, result) => {
    try { page.window.onSnapshot && page.window.onSnapshot(method, result === "quiet" ? undefined : result); }
    catch (e) { page.errors.push(String(e.stack || e)); }
  };
  const dom = await JSDOM.fromFile(join(ASSETS, name), {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole,
    beforeParse(window) {
      window.TilauBridge = {
        call(method, arg) {
          page.calls.push([method, arg]);
          const r = route(method, arg, folder);
          if (!r) return;
          if (page.refused.delete(r[0])) { // the session's call fails: the service hands null
            pending.push(Promise.resolve().then(() => deliver(r[0], null)));
            return;
          }
          // Answered later, as the WebView gets it from the service.
          pending.push(ask(r[0], r[1]).then((a) => { page.commands.push(...a.commands); if (a.result !== "quiet") deliver(r[0], a.result); }));
        },
        currency: () => "EUR",
        logInfo: () => '{"bytes":0,"since":""}',
      };
      window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
      // No canvas in jsdom: a 2D context that draws nothing and measures text roughly (the label's layout).
      window.HTMLCanvasElement.prototype.getContext = function () {
        return new Proxy({ measureText: (t) => ({ width: String(t).length * 6, actualBoundingBoxAscent: 8, actualBoundingBoxDescent: 2 }),
          getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(Math.max(0, w * h * 4)), width: w, height: h }) },
          { get: (o, k) => (k in o ? o[k] : () => {}), set: () => true });
      };
      window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
      if (before) before(window);
    },
  });
  page.window = dom.window;
  page.$ = (id) => dom.window.document.getElementById(id);
  await new Promise((resolve) => dom.window.addEventListener("load", resolve));
  dom.window.go = (target) => page.went.push(target); // no navigation in the bench: where the page went
  let clock = 1000;

  /** Every answer delivered, and the answers the answers asked for. */
  page.settle = async () => {
    for (let i = 0; i < 50 && pending.length; i++) { const now = pending; pending = []; await Promise.all(now); }
    await new Promise((r) => setTimeout(r, 0));
  };
  /** `seconds` of the service's 1 Hz tick, each delivered as onSnapshot("tick", …). */
  page.tick = async (seconds = 1) => {
    for (let i = 0; i < seconds; i++) {
      clock += 1;
      await ask("__clock", [clock]);
      const a = await ask("tick", []);
      page.commands.push(...a.commands);
      deliver("tick", a.result);
      await page.settle();
    }
  };
  /** A session call the page did not make (a link state, a reading), as the service makes it. */
  page.session = async (method, ...args) => { const a = await ask(method, args); page.commands.push(...a.commands); return a.result; };
  /** A call the service makes by itself and hands to the page (the scanner's classify_scan…). */
  page.push = async (method, ...args) => { const a = await ask(method, args); page.commands.push(...a.commands); if (a.result !== "quiet") deliver(method, a.result); await page.settle(); };
  /** The session's next `method` fails, as a refused START does. */
  page.refuse = (method) => page.refused.add(method);
  page.sent = (method) => page.calls.filter((c) => c[0] === method);
  page.tap = (el) => {
    const w = dom.window;
    el.dispatchEvent(new w.Event("pointerdown", { bubbles: true }));
    el.dispatchEvent(new w.Event("pointerup", { bubbles: true }));
    el.click();
  };
  page.close = () => { python.stdin.end(); dom.window.close(); rmSync(folder, { recursive: true, force: true }); };
  // Page loaded: MainActivity's onPageFinished asks the service to resync it.
  const first = await ask("__resync", []);
  deliver("snapshot", first.result);
  await page.settle();
  return page;
}
