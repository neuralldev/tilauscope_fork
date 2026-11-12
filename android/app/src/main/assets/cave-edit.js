// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The desktop's zone editors for touch: the same zones, fields, closed lists and
// required fields (the rules come from tilaucore through get_coffees). A field a
// Bluetooth device fills shows that device beside it, as on the desktop: the scale
// for the stock and the density, the AquaGauge for water activity.
"use strict";
var CaveEdit = (function () {
  var TITLES = { essentials: "Essentials", provenance: "Provenance", characteristics: "Characteristics", sensory: "Sensory & notes", all: "New coffee" };
  var LABELS = { name: "Bean name", country: "Country", crop: "Crop year", weight_left: "Stock", farm: "Farm", supplier: "Supplier",
    altitude: "Altitude", price_per_kg: "Price", is_blend: "Type", bean1_ratio: "This bean", bean2_name: "Component 2", bean3_name: "Component 3",
    category: "Category", process: "Process", species: "Species", varieties: "Varieties", density: "Density", last_humidity: "Humidity",
    water_activity: "Water activity", screen_size: "Screen size", sca: "SCA score", flavour_notes: "Flavour notes", tips: "Roasting tips / memo" };
  var UNITS = { weight_left: "g", altitude: "m", bean1_ratio: "%", bean2_ratio: "%", bean3_ratio: "%", density: "g/l", last_humidity: "%" };
  var cave = null, ed = null, devices = {}, sc = null, wt = null, trace = [], measuredAt = null, onSaved = null;

  // ---------- values ----------
  function lists() { return cave.lists; }
  function options(key, v) {
    var L = lists();
    if (key === "country") return [""].concat(L.countries);
    if (key === "category") return [""].concat(L.categories);
    if (key === "species") return [""].concat(L.species);
    if (key === "process") return [""].concat(L.processes[v.category] || [], ["Other"]);
    if (key === "varieties") return [""].concat(L.varieties[v.species] || [], ["Other"]);
    if (key === "bean2_name" || key === "bean3_name") return [""].concat(L.varieties.Arabica || [], ["Other"]);
    return null;
  }
  // As the desktop loads a record: an unlisted variety, process or component shows as Other,
  // an unlisted country, category or species as blank (and a blank country keeps the record's).
  function listed(key, v) {
    var o = options(key, v), value = v[key];
    if (!o || !value || o.indexOf(value) >= 0) return value;
    return o.indexOf("Other") >= 0 ? "Other" : "";
  }
  function load(values) {
    var v = JSON.parse(JSON.stringify(values));
    ["country", "category", "species", "process", "varieties", "bean2_name", "bean3_name"].forEach(function (k) { v[k] = listed(k, v); });
    return v;
  }
  function fields() { return ed.zone === "all" ? Object.keys(cave.zones).reduce(function (a, z) { return a.concat(cave.zones[z]); }, []) : cave.zones[ed.zone]; }
  function missing() { return cave.required.filter(function (k) { return !String(ed.v[k] || "").trim(); }); }
  // the price's currency, as the desktop's price field shows it
  function currency() { var code = cave.currency || systemCurrency(); return cave.currencies[code] || code; }
  // A typed value stays as typed (a decimal comma, an emptied field) until Save reads it; a stored one is formatted.
  function shown(n, decimals) { return typeof n === "string" ? n : n == null || n === 0 ? "" : Number(n).toFixed(decimals); }

  // ---------- form ----------
  function row(n, key, control) {
    var req = ed.zone === "all" && cave.required.indexOf(key) >= 0;
    return '<div class="ce-f" style="grid-row:' + n + '"><label>' + LABELS[key] + (req ? " <i>*</i>" : "") + "</label>" + control + "</div>";
  }
  function textInput(key) {
    return '<input class="ce-in' + (ed.got[key] ? " got" : "") + '" data-k="' + key + '" value="' + esc(ed.v[key]) + '">';
  }
  function numInput(key) {
    var lim = cave.limits[key];
    return '<span class="ce-num"><input class="ce-in short' + (ed.got[key] ? " got" : "") + (ed.bad[key] ? " bad" : "") + '" inputmode="decimal" data-k="' + key + '" data-n="1" value="' +
      esc(shown(ed.v[key], lim[2])) + '" placeholder="—">' + (UNITS[key] ? '<span class="u">' + UNITS[key] + "</span>" : key === "price_per_kg" ? '<span class="u">' + esc(currency()) + "/kg</span>" : "") + "</span>";
  }
  function pickInput(key) {
    var v = ed.v[key], label = v;
    if (key === "screen_size") label = (lists().screen_sizes.filter(function (s) { return s[0] === v; })[0] || ["", "Unknown"])[1];
    return '<button class="ce-in pick' + (v ? "" : " ph") + '" data-p="' + key + '">' + esc(label || "Choose…") + '<span class="chev">›</span></button>';
  }

  function render() {
    var rows = [], cards = [], n = 1, keys = fields();
    function add(html) { rows.push(html.replace("grid-row:N", "grid-row:" + n)); return n++; }
    function section(title) { if (ed.zone === "all") add('<div class="ce-sec" style="grid-row:N">' + title.toUpperCase() + "</div>"); }
    function has(k) { return keys.indexOf(k) >= 0; }
    if (has("name")) {
      section("Essentials");
      add(row("N", "name", textInput("name"))); add(row("N", "country", pickInput("country"))); add(row("N", "crop", numInput("crop")));
      var stock = add(row("N", "weight_left", numInput("weight_left") + (ed.got.weight_left ? '<span class="ce-note">from the scale</span>' : "")));
      cards.push([stock, ["scale"]]);
    }
    if (has("farm")) {
      section("Provenance");
      add(row("N", "farm", textInput("farm"))); add(row("N", "supplier", textInput("supplier")));
      add(row("N", "altitude", numInput("altitude"))); add(row("N", "price_per_kg", numInput("price_per_kg")));
    }
    if (has("category")) {
      section("Characteristics");
      add(row("N", "is_blend", '<span class="ce-seg"><button data-b="0"' + (ed.v.is_blend ? "" : ' class="on"') + '>Single origin</button><button data-b="1"' +
        (ed.v.is_blend ? ' class="on"' : "") + ">Blend</button></span>"));
      if (ed.v.is_blend) {
        add(row("N", "bean1_ratio", numInput("bean1_ratio")));
        add(row("N", "bean2_name", pickInput("bean2_name") + numInput("bean2_ratio")));
        add(row("N", "bean3_name", pickInput("bean3_name") + numInput("bean3_ratio")));
      }
      add(row("N", "category", pickInput("category"))); add(row("N", "process", pickInput("process")));
      add(row("N", "species", pickInput("species"))); add(row("N", "varieties", pickInput("varieties")));
      var dens = add(row("N", "density", numInput("density") + '<button class="ce-mini" id="ce-measure">⚖ Measure</button>'));
      add(row("N", "last_humidity", numInput("last_humidity")));
      var aw = add(row("N", "water_activity", numInput("water_activity")));
      add(row("N", "screen_size", pickInput("screen_size")));
      cards.push(ed.density ? [dens, ["density", "aw"]] : [aw, ["aw"]]);
    }
    if (has("sca")) {
      section("Sensory & notes");
      add(row("N", "sca", numInput("sca")));
      add(row("N", "flavour_notes", textInput("flavour_notes") + '<button class="ce-mini" id="ce-wheel">🎡 Flavours</button>'));
      add(row("N", "tips", '<textarea class="ce-in memo" data-k="tips">' + esc(ed.v.tips) + "</textarea>"));
    }
    var miss = ed.zone === "all" ? missing() : [];
    if (miss.length) add('<div class="ce-callout" style="grid-row:N">Fill the required fields (*): ' + miss.map(function (k) { return LABELS[k].toLowerCase(); }).join(", ") + ".</div>");
    var stacks = cards.map(function (c) {
      return '<div class="ce-devs" style="grid-row:' + c[0] + " / span 8" + '">' + c[1].map(function (d) { return '<div id="ce-dev-' + d + '"></div>'; }).join("") + "</div>";
    });
    $("ce-form").innerHTML = rows.join("") + stacks.join("");
    $("ce-save").disabled = miss.length > 0;
    wire();
    renderDevices();
  }

  function wire() {
    $("ce-form").querySelectorAll("[data-k]").forEach(function (el) {
      el.oninput = function () { ed.v[el.dataset.k] = el.value; ed.got[el.dataset.k] = false; ed.bad[el.dataset.k] = false; el.classList.remove("got", "bad"); gate(); };
      el.onfocus = function () { setTimeout(function () { el.scrollIntoView({ block: "center", behavior: "smooth" }); }, 350); };
    });
    $("ce-form").querySelectorAll("[data-p]").forEach(function (b) { b.onclick = function () { pick(b.dataset.p); }; });
    $("ce-form").querySelectorAll("[data-b]").forEach(function (b) { b.onclick = function () { ed.v.is_blend = b.dataset.b === "1"; render(); }; });
    var m = $("ce-measure"); if (m) m.onclick = function () { ed.density = !ed.density; if (ed.density) wakeScale(); render(); };
    var w = $("ce-wheel"); if (w) w.onclick = function () {
      FlavourDial.open(cave.wheel, ed.v.flavour_notes, ed.v.name || "", function (text) { ed.v.flavour_notes = text; ed.got.flavour_notes = true; render(); });
    };
  }
  function gate() {
    if (ed.zone !== "all") return;
    var miss = missing();
    $("ce-save").disabled = miss.length > 0;
  }

  // ---------- closed lists ----------
  function pick(key) {
    var o = key === "screen_size" ? lists().screen_sizes : options(key, ed.v).map(function (x) { return [x, x || "—"]; });
    var box = document.createElement("div");
    box.className = "ce-scrim";
    box.innerHTML = '<div class="ce-pick"><h3>' + LABELS[key] + (key === "varieties" && ed.v.species ? " <small>" + esc(ed.v.species) + "</small>" : "") + "</h3>" +
      (o.length > 12 ? '<input class="ce-in" id="ce-q" placeholder="Search…">' : "") + '<div class="ce-list" id="ce-list"></div></div>';
    document.body.appendChild(box);
    function fill() {
      var q = plain($("ce-q") ? $("ce-q").value : "").trim();
      $("ce-list").innerHTML = o.filter(function (x) { return !q || plain(x[1]).indexOf(q) >= 0 || x[0] === "Other"; }).map(function (x) {
        return '<button class="ce-opt' + (x[0] === ed.v[key] ? " sel" : "") + (x[0] === "Other" ? " other" : "") + '" data-v="' + esc(x[0]) + '">' + esc(x[1]) + "</button>";
      }).join("");
      $("ce-list").querySelectorAll(".ce-opt").forEach(function (b) {
        b.onclick = function () {
          ed.v[key] = b.dataset.v;
          // as the desktop refills a dependent list: a value the new list lacks is cleared
          if (key === "category" && options("process", ed.v).indexOf(ed.v.process) < 0) ed.v.process = "";
          if (key === "species" && options("varieties", ed.v).indexOf(ed.v.varieties) < 0) ed.v.varieties = "";
          box.remove(); render();
        };
      });
    }
    if ($("ce-q")) $("ce-q").oninput = fill;
    box.onclick = function (e) { if (e.target === box) box.remove(); }; // touching outside closes
    fill();
    var sel = $("ce-list").querySelector(".sel"); // centred in the list only, the form behind stays put
    if (sel) $("ce-list").scrollTop = sel.offsetTop - $("ce-list").offsetTop - $("ce-list").clientHeight / 2 + sel.offsetHeight / 2;
  }

  // ---------- devices ----------
  var card = DeviceCards.card, dot = DeviceCards.dot;
  function scaleReady() { return DeviceCards.ready(sc); }
  function renderDevices() {
    var s = $("ce-dev-scale"), d = $("ce-dev-density"), a = $("ce-dev-aw");
    if (s) DeviceCards.scale(s, sc, { configured: !!devices.scale, use: "Use as stock", hint: "Weigh the whole stock, bag removed or tared.",
      missing: "No scale in Settings › Devices. Type the stock, or pair the scale there.", typing: "You can type the stock meanwhile." },
      function (g) { take("weight_left", g); });
    if (d) DeviceCards.density(d, sc, !!devices.scale, ed.volume, function (v) { ed.volume = v; renderDevices(); }, function (v) { take("density", v); });
    if (a) {
      if (!devices.water) a.innerHTML = card("wait", "💧 WATER ACTIVITY", "", '<div class="ce-hint">No AquaGauge in Settings › Devices. Type the aw, or pair the probe there.</div>');
      else if (!wt || wt.state !== "connected") a.innerHTML = card("wait", "💧 WATER ACTIVITY", dot("var(--muted)") + "probe not connected…", '<div class="ce-hint">Switch the AquaGauge on. You can type the aw meanwhile.</div>');
      else if (wt.measuring) {
        var el = measuredAt ? Math.round((Date.now() - measuredAt) / 1000) : 0;
        a.innerHTML = card("", "💧 WATER ACTIVITY", dot("var(--blue)") + "Measuring · " + Math.floor(el / 60) + ":" + ("0" + el % 60).slice(-2),
          '<div class="ce-read num" style="color:var(--blue)">' + (wt.aw > 0 ? wt.aw.toFixed(3) : "–––") + "</div>" + spark() + '<button class="ce-use" disabled>Use · when the measurement ends</button>');
      } else if (wt.final && wt.aw > 0) {
        a.innerHTML = card("", "💧 WATER ACTIVITY", dot("var(--green)") + "Result", '<div class="ce-read num">' + wt.aw.toFixed(2) + '</div><button class="ce-use" id="ce-use-aw">Use as aw</button>');
        $("ce-use-aw").onclick = function () { take("water_activity", Number(wt.aw.toFixed(2))); };
      } else a.innerHTML = card("", "💧 WATER ACTIVITY", dot("var(--green)") + "connected", '<div class="ce-read dim">––</div><div class="ce-hint">Probe connected — measure to read.</div>');
    }
  }
  function spark() {
    if (trace.length < 2) return '<div class="ce-spark"></div>';
    var lo = Math.min.apply(null, trace), hi = Math.max.apply(null, trace), span = hi - lo || 0.01;
    var pts = trace.map(function (v, i) { return (i / (trace.length - 1) * 300).toFixed(1) + "," + (58 - (v - lo) / span * 52).toFixed(1); }).join(" ");
    return '<div class="ce-spark"><svg width="100%" height="64" viewBox="0 0 300 64" preserveAspectRatio="none"><polyline points="' + pts + '" fill="none" stroke="#89B4FA" stroke-width="2"/></svg></div>';
  }
  function take(key, value) { ed.v[key] = value; ed.got[key] = true; ed.bad[key] = false; render(); }

  window.onScale = function (d) { sc = d; if (ed) renderDevices(); };
  window.onWater = function (d) {
    if (d.measuring && !(wt && wt.measuring)) { trace = []; measuredAt = Date.now(); }
    if (d.measuring && d.aw > 0 && (!wt || d.reading_id !== wt.reading_id)) trace.push(d.aw);
    wt = d;
    if (ed) renderDevices();
  };

  // ---------- open, save, close ----------
  function connectDevices(zone) {
    ed.connected = [];
    if (zone === "essentials" || zone === "all") wakeScale();
    if ((zone === "characteristics" || zone === "all") && devices.water) {
      if (!wt || wt.state !== "connected") ed.connected.push("water");
      send("water_connect", devices.water.address);
    }
    ed.timer = setInterval(function () { if (wt && wt.measuring) renderDevices(); }, 1000);
  }
  function wakeScale() { // the stock field, or Measure for the density
    if (!devices.scale || ed.connected.indexOf("scale") >= 0) return;
    if (!scaleReady()) ed.connected.push("scale");
    send("scale_connect", JSON.stringify({ address: devices.scale.address, name: devices.scale.name }));
  }
  function close() {
    clearInterval(ed.timer);
    // as the desktop: a device the editor woke up is let go again
    if (ed.connected.indexOf("scale") >= 0) send("scale_disconnect");
    if (ed.connected.indexOf("water") >= 0) send("water_disconnect");
    $("ce").remove(); ed = null;
  }
  function save() {
    var bad = null;
    fields().forEach(function (k) {
      var lim = cave.limits[k];
      if (!lim) return;
      var raw = String(ed.v[k] == null ? "" : ed.v[k]).replace(",", ".").trim(), n = raw === "" ? 0 : Number(raw);
      if (isNaN(n) || n < lim[0] || n > lim[1]) { ed.bad[k] = true; bad = bad || LABELS[k] + " is between " + lim[0] + " and " + lim[1]; }
      else ed.v[k] = n;
    });
    if (bad) { render(); toast(bad); return; }
    var values = {};
    fields().forEach(function (k) { values[k] = ed.v[k]; });
    send("save_coffee", JSON.stringify({ uuid: ed.coffee ? ed.coffee.uuid : null, zone: ed.zone, values: values }));
  }

  return {
    setCave: function (c) { cave = c; },
    setDevices: function (d) { devices = { scale: d.scale && d.scale.enabled ? d.scale : null, water: d.water && d.water.enabled ? d.water : null }; },
    open: function (zone, coffee) {
      var values = coffee ? coffee.edit : JSON.parse(JSON.stringify(cave.blank));
      if (!coffee) values.crop = new Date().getFullYear(); // as the desktop proposes for a new bean
      ed = { zone: zone, coffee: coffee, v: load(values), got: {}, bad: {}, density: false, volume: 100 };
      var box = document.createElement("div");
      box.id = "ce";
      box.innerHTML = '<div class="ehead"><button class="eback" id="ce-back" aria-label="Back"><svg width="24" height="24" viewBox="0 0 18 18" aria-hidden="true"><path d="M11 4L6 9l5 5" fill="none" stroke="#A6ADC8" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><span class="t"><b>' + esc((TITLES[zone] + (coffee ? " — " + coffee.name : "")).toUpperCase()) + "</b><small>" +
        (coffee ? "Only this section is changed. Save writes the record immediately." : "Fill what you know — everything can be refined later from the sheet.") +
        '</small></span><span style="flex:1"></span><button class="btn save" id="ce-save">✓ ' + (coffee ? "Save" : "Create") + "</button></div>" +
        '<div class="ce-body"><div class="ce-form" id="ce-form"></div></div>';
      document.body.appendChild(box);
      $("ce-back").onclick = close; // with Save on the screen, leaving it drops the changes
      $("ce-save").onclick = save;
      connectDevices(zone);
      render();
    },
    saved: function (reply) {
      if (!ed) return;
      if (!reply) { toast("The coffee could not be saved"); return; }
      close();
    },
    isOpen: function () { return !!ed; }
  };
})();
