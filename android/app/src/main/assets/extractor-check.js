// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The extractor check from Settings: the tablet connects and gives its name, the
// temperatures and the mode arrive live, then the speed changes for 10 s (the
// mode never changes). Speed and power are put back and the extractor let go.
// Needs common.js, check.js styles (common.css) and an esc() helper on the page.
"use strict";
var ExtractorCheck = (function () {
  var box = null, address = "", name = "", link = {}, last = {}, answer = "", started = false, everEchoed = false, wasOff = false;
  var TICK = '<svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="10" fill="#A6E3A1"/><path d="M5.5 10.5l3 3 6-6.5" fill="none" stroke="#1E1E2E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var ALERT = '<svg width="24" height="24" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="9" fill="none" stroke="#F38BA8" stroke-width="1.8"/><path d="M10 5.5v5.5" stroke="#F38BA8" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="14.2" r="1.2" fill="#F38BA8"/></svg>';
  var PROBLEMS = {
    failed: ["The extractor could not be reached", "Switch it on, keep it close to the tablet, then try again."],
    lost: ["The extractor stopped answering", "Keep it close to the tablet, then try again."],
    bluetooth_off: ["Bluetooth is off", "Turn it on, then try again."],
    denied: ["The tablet needs permission to connect", "Allow it to connect to Bluetooth devices, then try again."]
  };

  function live() { return link.state === "connected" && link.ready; }
  function finished() { return link.state === "done"; }

  function pill() {
    if (finished()) return '<div class="ck-pill ok">' + TICK + "<span><b>Check done</b><small>Speed and power are back as they were; the link is closed.</small></span></div>";
    if (live()) return '<div class="ck-pill ok">' + TICK + "<span><b>Connected</b><small>The extractor accepted the tablet as TilauScope.</small></span></div>";
    if (link.state === "connecting") return '<div class="ck-pill"><span class="ck-dot pulse"></span><span><b>Connecting…</b></span></div>';
    return "";
  }

  function readings() {
    var on = (live() || finished()) && last.inlet != null;
    var rows = [["Inlet", on ? shownT(last.inlet).toFixed(1) + "<small> " + deg() + "</small>" : "—"], ["Catalyst", on && last.catalyst != null ? shownT(last.catalyst).toFixed(1) + "<small> " + deg() + "</small>" : "—"],
      ["Mode", (live() || finished()) && last.mode ? last.mode : "—"], ["Power", (live() || finished()) && last.power != null ? (last.power ? "On" : "Off") : "—"]];
    var html = '<div class="ck-temps"><span class="ck-live">' + (!on ? '<span class="ck-dot"></span>No reading' : live() ?
      '<span class="ck-dot pulse" style="background:var(--green)"></span>Live from the extractor' : '<span class="ck-dot"></span>Last reading') + "</span>";
    rows.forEach(function (r) {
      html += '<div class="ck-trow"><span>' + r[0] + '</span><b class="num" style="font-size:' + (r[0] === "Inlet" || r[0] === "Catalyst" ? 30 : 20) + "px;color:" + (on ? "var(--text)" : "var(--line)") + '">' + r[1] + "</b></div>";
    });
    return html + "</div>";
  }

  function speedCard() {
    var running = link.test_left != null;
    var sub = running || finished() ? "The tablet changes the speed from " + link.test_from + " % to " + link.test_speed + " % for " + link.test_seconds + " seconds, then puts it back." +
      (wasOff ? " It is switched on for the check and off again after." : "") :
      "The tablet changes the speed for 10 seconds, then puts it back. The mode does not change.";
    if (!live() && !running && !finished()) return '<div class="ck-card wait"><div class="ck-head"><span><b>Speed</b><small>' + esc(sub) + '</small></span><button class="ck-btn" disabled>Test</button></div></div>';
    if (answer === "yes" && !running)
      return '<div class="ck-card done"><div class="ck-head"><span><b>Speed</b><small>' + (everEchoed ? "Confirmed by the extractor, heard by you." : "Heard by you.") +
        '</small></span><span class="ck-ok">' + TICK + 'Confirmed</span><button class="ck-link" id="xk-again">Test again</button></div></div>';
    if (answer === "no" && !running)
      return '<div class="ck-card warn"><div class="ck-head"><span><b>Speed</b><small>Not heard. Check that the extractor is switched on, then test again.</small></span>' +
        '<button class="ck-btn" id="xk-again">Test again</button></div></div>';
    var echoed = running && link.speed === link.test_speed, html = '<div class="ck-card on"><span><b>Speed</b><small>' + esc(sub) + "</small></span>";
    if (running) {
      html += '<div class="ck-line"><span class="ck-k">Sent</span><b class="num">' + link.test_speed + ' %</b><span class="ck-bar"><i style="width:' +
        Math.round(100 * (1 - link.test_left / link.test_seconds)) + '%"></i></span><span class="ck-k" style="width:auto">' + link.test_left + " s left</span></div>" +
        '<div class="ck-line"><span class="ck-k">Extractor</span><b class="num" style="color:' + (echoed ? "var(--green)" : "var(--sub)") + '">' +
        (link.speed == null ? "—" : link.speed + " %") + '</b><span class="ck-k" style="width:auto;color:' + (echoed ? "var(--green)" : "") + '">' + (echoed ? "confirmed" : "waiting") + "</span></div>";
    }
    if (!running && !finished()) html += '<div class="ck-line"><span class="ck-k" style="width:auto">Starting…</span></div>';
    else html += '<div class="ck-ask"><b>' + (running ? "Do you hear the extractor speed change?" : "Did you hear the extractor speed change?") + "</b>" +
      (running ? "" : '<button class="ck-link" id="xk-again">Test again</button>') +
      '<button class="ck-btn" id="xk-no">No</button><button class="ck-btn primary" id="xk-yes">' + (running ? "Yes, I hear it" : "Yes, I heard it") + "</button></div>";
    return html + "</div>";
  }

  function problem() {
    var p = PROBLEMS[link.state];
    if (!p) return "";
    return '<div class="ck-card bad"><div style="display:flex;align-items:center;gap:12px">' + ALERT + "<b>" + p[0] + "</b></div><small>" + p[1] +
      '</small><button class="ck-btn primary" id="xk-retry" style="align-self:flex-start">Try again</button></div>';
  }

  function draw() {
    if (!box) return;
    box.innerHTML = '<div class="ck"><div class="ck-left"><h1>Check the extractor</h1><div class="lede">The tablet connects to ' + esc(name) +
      ", reads its temperatures, and changes its speed for 10 seconds.</div>" + pill() + readings() +
      '</div><div class="ck-right">' + problem() + speedCard() + "</div></div>";
    var on = function (id, fn) { var el = document.getElementById(id); if (el) el.onclick = fn; };
    on("xk-retry", connect);
    on("xk-again", connect);
    on("xk-yes", function () { answer = "yes"; draw(); });
    on("xk-no", function () { answer = "no"; draw(); });
  }

  function connect() { link = { state: "connecting" }; last = {}; answer = ""; started = false; everEchoed = false; send("extractor_test_connect", address); draw(); }

  window.onExtractor = function (d) {
    if (!box) return;
    link = d;
    if (d.inlet != null || d.mode != null) last = d;
    if (d.test_left != null && d.speed === d.test_speed) everEchoed = true;
    // The test starts by itself once power and speed are known.
    if (live() && !started && d.power != null && d.speed != null) { started = true; wasOff = d.power === false; send("extractor_test"); }
    draw();
  };

  return {
    open: function (container, device) { box = container; address = device.address; name = device.name || "the extractor"; connect(); },
    close: function () { if (box) send("extractor_disconnect"); box = null; }
  };
})();
