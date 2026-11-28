// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The panels that measure a roast again: the colour series and the roasted weight. One panel at a time,
// floating over the page; only its Save / Use keeps a value, a touch outside closes it and keeps nothing.
// The same panels on the roast summary (roast.html) and on a saved roast (BeanCave › Roasts).
//
// Colour series: 1 to 5 readings of the same sample, averaged. Once full, the next reading overwrites
// the first slot and goes round; a slot tapped to redo takes the next reading in place. Whole beans or
// ground is chosen by the operator for each panel: Save waits for it. The meter measures on its own button; the page hands each new reading
// to MeasureSheets.reading().
"use strict";
var MeasureSheets = (function () {
  var COUNT_KEY = "tilau_colour_count", WEIGH_MIN = 1, WEIGH_MAX = 1000, COLOUR_MIN = 20, COLOUR_MAX = 130;
  var el = null, kind = null, o = null; // the open panel, "colour" or "weigh", its options
  var series = null, basis = null, size = 3, meter = null, sc = null, byHand = false;
  try { size = Math.min(5, Math.max(1, parseInt(localStorage.getItem(COUNT_KEY), 10) || 3)); } catch (e) {}

  function levelOf(v) {
    var l = (o && o.levels) || [];
    for (var i = 0; i < l.length; i++) if (v >= l[i][1] && v <= l[i][2]) return l[i];
    return null;
  }
  function swatch(v) { var l = levelOf(v); return l ? l[3] : "var(--overlay)"; }
  function mean() {
    var r = series.readings;
    return r.length ? Math.round(r.reduce(function (a, b) { return a + b; }, 0) / r.length * 10) / 10 : null;
  }
  function open(k, options) {
    close();
    kind = k; o = options || {};
    el = document.createElement("div");
    el.id = "msheet";
    el.className = k;
    document.body.appendChild(el);
  }
  function close() {
    if (!el) return;
    var done = o.onClose;
    el.remove(); el = null; kind = null; o = null; series = null; byHand = false;
    if (done) done();
  }

  // ---------- colour ----------
  function meterLine() {
    var live = meter && meter.state === "connected";
    return '<span class="st" style="color:' + (live ? "var(--green)" : "var(--muted)") + '">● ' +
      (live ? "Colour meter connected" : o.configured ? "Colour meter not answering" : "No colour meter") + "</span>";
  }
  function renderColour() {
    var r = series.readings, n = r.length, full = n === size, m = mean(), next = series.redo != null ? series.redo : full ? series.next : n;
    var h = '<div class="ms-left"><div class="ms-head"><span class="t">Colour</span>' + meterLine() + "</div>" +
      '<div class="ms-row"><div class="ms-seg">' + [["whole", "Whole beans"], ["ground", "Ground"]].map(function (b) {
        return '<button data-basis="' + b[0] + '"' + (basis === b[0] ? ' class="on"' : "") + ">" + b[1] + "</button>";
      }).join("") + '</div><div class="ms-seg n">' + [1, 2, 3, 4, 5].map(function (k) {
        return '<button data-count="' + k + '"' + (k === size ? ' class="on"' : "") + (k < n ? " disabled" : "") + ">" + k + "</button>";
      }).join("") + "</div></div>" +
      '<div class="ms-slots" style="grid-template-columns:repeat(' + size + ',minmax(0,1fr))">';
    for (var i = 0; i < size; i++) {
      var v = r[i], has = v != null, nx = i === next;
      h += '<button class="ms-slot' + (nx ? " next" : has ? "" : " empty") + '" data-slot="' + i + '"' + (has ? "" : " disabled") +
        '><span class="no">NO.' + (i + 1) + '</span><i style="background:' + (has ? swatch(v) : "var(--overlay)") + '"></i><span class="sv num"' +
        (has ? "" : ' style="color:var(--line)"') + ">" + (has ? v.toFixed(1) : "—") + '</span><span class="no">' +
        (nx ? (has ? "next" : "measure") : has ? "tap to redo" : "") + "</span></button>";
    }
    h += "</div>";
    if (n) {
      var mn = Math.min.apply(null, r), mx = Math.max.apply(null, r);
      var lo = Math.floor(Math.min(mn, m - 6) - 2), hi = Math.ceil(Math.max(mx, m + 6) + 2);
      var pos = function (x) { return ((x - lo) / (hi - lo) * 100).toFixed(1) + "%"; };
      h += '<div class="ms-track" style="background:linear-gradient(90deg,' + swatch(lo) + "," + swatch((lo + hi) / 2) + "," + swatch(hi) + ')">' +
        r.map(function (x) { return '<i style="left:' + pos(x) + '"></i>'; }).join("") + '<b style="left:' + pos(m) + '"></b></div>' +
        '<div class="ms-ends num"><span>' + lo + " darker</span><span>lighter " + hi + "</span></div>";
    }
    // Typed by hand, as a reading of the meter: no meter, or a meter that does not talk to the tablet
    h += '<div class="ms-type"><input class="ms-in num" type="number" inputmode="decimal" min="' + COLOUR_MIN + '" max="' + COLOUR_MAX +
      '" placeholder="Type a reading"><button class="ms-btn" data-add="1">Add</button></div>';
    var l = n ? levelOf(m) : null;
    h += '</div><div class="ms-right"><div class="ms-card"><span class="k">' + (n === 0 ? "Measure on the colour meter" : n === 1 ? "Reading" : "Average of " + n) +
      '</span><span class="m num"' + (n ? "" : ' style="color:var(--line)"') + ">" + (n ? m.toFixed(1) : "—") + '</span><span class="ms-lvl">' +
      (l ? '<i style="background:' + l[3] + '"></i>' + esc(l[0]) : "") + '</span><span class="k sp">Spread <b class="num">' +
      (n > 1 ? "± " + ((mx - mn) / 2).toFixed(1) : "—") + '</b></span></div><button class="ms-save' + (full && basis ? " full" : "") + '" data-save="1"' + (n && basis ? "" : " disabled") +
      ">" + (!n ? "Save" : !basis ? "Choose whole beans or ground" : "Save as " + (basis === "ground" ? "ground" : "whole beans") + (full ? "" : " (" + n + " of " + size + ")")) + "</button></div>";
    el.innerHTML = h;
    el.querySelectorAll("[data-basis]").forEach(function (b) { b.onclick = function () { basis = b.dataset.basis; renderColour(); }; });
    el.querySelectorAll("[data-count]").forEach(function (b) {
      b.onclick = function () {
        size = +b.dataset.count; series.next = 0; series.redo = null;
        try { localStorage.setItem(COUNT_KEY, String(size)); } catch (e) {}
        renderColour();
      };
    });
    el.querySelectorAll("[data-slot]").forEach(function (b) {
      b.onclick = function () { series.redo = +b.dataset.slot; renderColour(); }; // the old value counts until measured again
    });
    el.querySelector("[data-add]").onclick = function () {
      var v = Math.round(Number(el.querySelector(".ms-in").value) * 10) / 10;
      if (v >= COLOUR_MIN && v <= COLOUR_MAX) add(v);
      else toast("A colour reading is between " + COLOUR_MIN + " and " + COLOUR_MAX);
    };
    el.querySelector("[data-save]").onclick = function () {
      if (!basis) return;
      var keep = o.onSave, b = basis, v = mean();
      close();
      keep(b, v);
    };
  }

  function add(v) {
    var r = series.readings;
    if (series.redo != null) { r[series.redo] = v; if (r.length === size) series.next = (series.redo + 1) % size; series.redo = null; }
    else if (r.length < size) { r.push(v); series.next = 0; }
    else { r[series.next] = v; series.next = (series.next + 1) % size; }
    // a value being typed stays through the redraw
    var typed = typing() ? el.querySelector(".ms-in").value : null;
    renderColour();
    if (typed !== null) { var i = el.querySelector(".ms-in"); i.value = typed; i.focus(); }
  }
  function typing() { var i = el && el.querySelector(".ms-in"); return !!i && document.activeElement === i; }

  // ---------- roasted weight ----------
  function scaleLive() { return !!sc && sc.ready && sc.weight_g != null; }
  function renderWeigh() {
    var live = o.configured && scaleLive(), g = live ? Math.round(sc.weight_g) : null, ok = live && sc.stable && g > 0;
    var h = '<div class="ms-head"><i class="dot" style="background:var(--peach)"></i><span class="t">Roasted weight</span><span class="st" style="color:' +
      (live ? "var(--green)" : "var(--muted)") + '">● ' + (live ? "Scale connected" : o.configured ? "Scale not answering" : "No scale") + "</span></div>";
    if (live && !byHand) {
      h += '<div class="ms-big"><b class="num" style="color:' + (sc.stable ? "var(--text)" : "var(--yellow)") + '">' + g + '</b><span class="u">g</span><span style="flex:1"></span>' +
        '<span class="st" style="color:' + (sc.stable ? "var(--green)" : "var(--yellow)") + '">● ' + (sc.stable ? "Stable" : "Settling…") + "</span></div>" +
        '<div class="ms-btns"><button class="ms-btn" data-tare="1">Tare</button><button class="ms-btn use" data-use="1"' + (ok ? "" : " disabled") + ">Use " + g + " g</button></div>";
    } else {
      h += '<div class="ms-btns"><input class="ms-in num" type="number" inputmode="numeric" min="' + WEIGH_MIN + '" max="' + WEIGH_MAX + '" placeholder="grams">' +
        '<button class="ms-btn use" data-typed="1">Use</button></div>';
    }
    h += '<div class="ms-foot"><span>Saved: <b class="num">' + esc(o.saved || "—") + '</b></span><span style="flex:1"></span>' +
      (live && !byHand ? '<button class="ms-link" data-hand="1">Enter by hand</button>' : "") + "</div>";
    el.innerHTML = h;
    var b;
    if ((b = el.querySelector("[data-tare]"))) b.onclick = function () { send("scale_tare"); };
    if ((b = el.querySelector("[data-use]"))) b.onclick = function () { if (ok) use(g); };
    if ((b = el.querySelector("[data-hand]"))) b.onclick = function () { byHand = true; renderWeigh(); };
    if ((b = el.querySelector("[data-typed]"))) b.onclick = function () {
      var v = Math.round(Number(el.querySelector(".ms-in").value));
      if (v >= WEIGH_MIN && v <= WEIGH_MAX) use(v);
      else toast("The roasted weight is between " + WEIGH_MIN + " and " + WEIGH_MAX + " g");
    };
  }
  function use(g) { var keep = o.onUse; close(); keep(g); }

  // A touch outside the open panel closes it: nothing is kept.
  document.addEventListener("pointerdown", function (e) {
    if (el && !el.contains(e.target)) close();
  }, true);

  return {
    /** {levels, configured, onSave(basis, value), onClose}: an empty series, waiting for the meter. */
    colour: function (options) { open("colour", options); series = { readings: [], next: 0, redo: null }; basis = null; renderColour(); },
    /** A new reading of the meter: false when no colour panel is open to take it. */
    reading: function (v) {
      if (kind !== "colour" || typeof v !== "number" || !(v > 0)) return false; // a state without a value is no reading
      add(v);
      return true;
    },
    meter: function (state) { meter = state; if (kind === "colour" && !typing()) renderColour(); }, // a value being typed stays
    /** {configured, saved (text), onUse(grams), onClose}. */
    weigh: function (options) { open("weigh", options); renderWeigh(); },
    scale: function (state) {
      sc = state;
      // a value typed by hand is not wiped by the scale's next reading
      if (kind === "weigh" && !typing()) renderWeigh();
    },
    isOpen: function (k) { return kind === k; },
    close: close
  };
})();
