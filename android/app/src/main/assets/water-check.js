// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The water activity meter check from Settings: the tablet connects and listens.
// A measurement is started on the meter, its intermediate values stream live, and
// the last one is final once the meter falls silent; the check is then done.
// Nothing is sent to the meter and nothing is saved.
// Needs common.js, check styles (common.css), an esc() helper and the page's setup (get_setup reply).
"use strict";
var WaterCheck = (function () {
  var box = null, address = "", name = "", link = {}, trace = [], startedAt = 0, timer = null, wasConnected = false;
  var TICK = '<svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="10" fill="#A6E3A1"/><path d="M5.5 10.5l3 3 6-6.5" fill="none" stroke="#1E1E2E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var ALERT = '<svg width="24" height="24" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="9" fill="none" stroke="#F38BA8" stroke-width="1.8"/><path d="M10 5.5v5.5" stroke="#F38BA8" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="14.2" r="1.2" fill="#F38BA8"/></svg>';
  var PROBLEMS = {
    lost: ["The meter could not be reached", "Switch it on, keep it close to the tablet, then try again."],
    bluetooth_off: ["Bluetooth is off", "Turn it on, then try again."],
    denied: ["The tablet needs permission to connect", "Allow it to connect to Bluetooth devices, then try again."]
  };
  // Storage zones of the desktop (storage_advisor.classify_aw, shared library): lower bound, name, colour.
  var ZONES = [];

  function zone(aw) { var z = ZONES[0]; ZONES.forEach(function (r) { if (aw >= r[0]) z = r; }); return z; }
  function clock(s) { return Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2); }

  function pill() {
    if (link.final) return '<div class="ck-pill ok">' + TICK + "<span><b>Check done</b><small>A full measurement reached the tablet.</small></span></div>";
    if (link.state === "connected") return '<div class="ck-pill ok">' + TICK + "<span><b>Connected</b><small>The tablet listens to the meter.</small></span></div>";
    if (link.state === "connecting") return '<div class="ck-pill"><span class="ck-dot pulse"></span><span><b>Connecting…</b></span></div>';
    return "";
  }

  function waiting() {
    return '<div class="ck-card on"><b>Measure a sample</b><ol class="wc-steps"><li>Fill the meter\'s cup with green beans.</li>' +
      "<li>Close it and start a measurement on the meter.</li><li>The result appears here when the meter has finished.</li></ol>" +
      '<div class="wc-wait"><span class="ck-dot pulse" style="background:var(--blue)"></span>Waiting for the meter…</div></div>' +
      '<div class="ck-card wait"><b style="color:var(--muted)">Reading</b><small>No measurement yet.</small></div>';
  }

  // The measurement so far: aw on the left axis, time below, the desktop's zone limits dashed.
  function spark() {
    if (trace.length < 2) return "";
    var lo = Math.min.apply(null, trace), hi = Math.max.apply(null, trace), pad = Math.max(0, 0.02 - (hi - lo)) / 2;
    lo -= pad; hi += pad;
    var n = trace.length, y = function (v) { return 4 + 62 * (hi - v) / (hi - lo); };
    var pts = trace.map(function (v, i) { return (i * 400 / (n - 1)).toFixed(1) + "," + y(v).toFixed(1); });
    var end = pts[n - 1].split(","), lines = "", tags = "";
    ZONES.forEach(function (r) {
      if (r[0] <= lo || r[0] >= hi) return;
      lines += '<line x1="0" x2="400" y1="' + y(r[0]).toFixed(1) + '" y2="' + y(r[0]).toFixed(1) + '" stroke="var(' + r[2] + ')" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>';
      tags += '<span class="wc-limit" style="top:' + (y(r[0]) / 70 * 100).toFixed(1) + "%;color:var(" + r[2] + ')">' + r[0].toFixed(2) + "</span>";
    });
    return '<div class="wc-spark"><div class="wc-axis num"><span>' + hi.toFixed(2) + "</span><span>" + lo.toFixed(2) + '</span></div><div class="wc-plot"><svg viewBox="0 0 400 70" preserveAspectRatio="none" aria-hidden="true">' +
      lines + '<polyline fill="none" stroke="#89B4FA" stroke-width="2.5" stroke-linejoin="round" vector-effect="non-scaling-stroke" points="' + pts.join(" ") + '"/></svg>' +
      '<i class="wc-end" style="left:100%;top:' + (end[1] / 70 * 100).toFixed(1) + '%"></i>' + tags +
      '<div class="wc-time num"><span>0:00</span><span>' + clock(Math.round((Date.now() - startedAt) / 1000)) + "</span></div></div></div>";
  }

  function scale(aw) {
    var bar = "", ticks = "";
    ZONES.forEach(function (r, i) {
      var to = i + 1 < ZONES.length ? ZONES[i + 1][0] : 1;
      bar += '<i style="width:' + (to - r[0]) * 100 + "%;background:var(" + r[2] + ')"></i>';
      if (i) ticks += '<span style="left:' + r[0] * 100 + '%">' + r[0].toFixed(2) + "</span>";
    });
    return '<div class="wc-scale"><div class="wc-bar">' + bar + '</div><div class="wc-marker" style="left:' + aw * 100 + '%"></div><div class="wc-ticks num"><span style="left:0">0.00</span>' +
      ticks + '<span style="left:100%">1.00</span></div></div><div class="wc-legend">' +
      ZONES.map(function (r) { return '<span><i style="background:var(' + r[2] + ')"></i>' + r[1] + "</span>"; }).join("") + "</div>";
  }

  function reading() {
    // The meter opens each measurement with a few 0.000 values while it settles.
    var live = link.measuring, has = link.aw > 0, z = has ? zone(link.aw) : null;
    var head = live ? '<span class="wc-head"><span class="ck-dot pulse" style="background:var(--blue)"></span><span>Measuring · <span class="num">' +
      clock(Math.round((Date.now() - startedAt) / 1000)) + "</span></span></span>" : '<span class="wc-head">Water activity</span>';
    return '<div class="ck-card' + (live ? " on" : "") + '"><div class="wc-top">' + head + (z ? '<span class="wc-zone" style="color:var(' + z[2] + ')">● ' + z[1] + "</span>" : "") + "</div>" +
      '<div class="wc-row"><div class="wc-big"><span class="v num" style="color:' + (live ? "var(--sub)" : "var(--text)") + '">' + (has ? link.aw.toFixed(2) : "—") +
      '</span><span class="u">aw</span></div>' + (live ? spark() : "") + "</div>" + (live || !has ? "" : scale(link.aw)) +
      (live ? '<div class="wc-note">' + (has ? "Intermediate value. A measurement usually takes about 2 minutes." : "The meter is starting its measurement.") + "</div>" : "") + "</div>" +
      (live ? "" : '<div class="wc-note">Not saved yet: the green coffee cave will keep it on the bean.</div>');
  }

  function problem() {
    var p = link.state === "lost" && wasConnected ? ["The meter stopped answering",
      "The measurement was interrupted. Switch the meter on and keep it close to the tablet: the tablet reconnects by itself."] : PROBLEMS[link.state];
    if (!p) return "";
    return '<div class="ck-card bad"><div style="display:flex;align-items:center;gap:12px">' + ALERT + "<b>" + p[0] + "</b></div><small>" + p[1] +
      '</small><button class="ck-btn primary" id="wk-retry" style="align-self:flex-start">Try again</button></div>';
  }

  function draw() {
    if (!box) return;
    var right = problem() || (link.state === "connected" ? (link.aw == null ? waiting() : reading()) : "");
    box.innerHTML = '<div class="ck"><div class="ck-left"><h1>Check the water activity meter</h1><div class="lede">The tablet connects to ' + esc(name) +
      " and shows each measurement it sends.</div>" + pill() + (link.final ? '<div class="ck-card"><small>Measure again on the meter to replace the reading.</small></div>' : "") +
      '</div><div class="ck-right">' + right + "</div></div>";
    var retry = document.getElementById("wk-retry");
    if (retry) retry.onclick = connect;
  }

  function connect() { link = { state: "connecting" }; trace = []; wasConnected = false; send("water_connect", address); draw(); }

  window.onWater = function (d) {
    if (!box) return;
    if (d.state === "connected") wasConnected = true;
    if (d.measuring && !link.measuring) { trace = []; startedAt = Date.now(); } // a new measurement starts
    if (d.measuring && d.aw > 0 && d.reading_id !== link.reading_id) trace.push(d.aw);
    // The meter streams about 8 values a second: while it measures, the page is redrawn once a second.
    var changed = d.state !== link.state || d.measuring !== link.measuring || d.final !== link.final;
    link = d;
    if (!changed) return;
    clearInterval(timer);
    if (d.measuring) timer = setInterval(draw, 1000);
    draw();
  };

  return {
    open: function (container, device) {
      var t = setup.catalogue.aw_zones;
      ZONES = [[0, "Too dry", "--yellow"], [t.dry, "Optimal", "--green"], [t.warn, "To watch", "--peach"], [t.risk, "Mould risk", "--red"]];
      box = container; address = device.address; name = device.name || "the meter"; connect(); },
    close: function () { clearInterval(timer); if (box) send("water_disconnect"); box = null; }
  };
})();
