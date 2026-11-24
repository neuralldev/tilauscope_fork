// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The roaster link check, shared by the first setup and Settings: the burner is
// confirmed off, the temperatures arrive live, then the air is raised while the
// operator listens; the roaster is stopped and let go at the end of the test.
// Needs common.js and an esc() helper on the page.
"use strict";
var Check = (function () {
  var box = null, address = "", link = {}, last = {}, answer = "", started = false, everEchoed = false, fromAir = null, waiting = false;
  var TICK = '<svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="10" fill="#A6E3A1"/><path d="M5.5 10.5l3 3 6-6.5" fill="none" stroke="#1E1E2E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var CLOCK = '<svg width="24" height="24" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="8.5" fill="none" stroke="#F9E2AF" stroke-width="1.8"/><path d="M10 5.5V10l3 2" fill="none" stroke="#F9E2AF" stroke-width="1.8" stroke-linecap="round"/></svg>';
  var ALERT = '<svg width="24" height="24" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="9" fill="none" stroke="#F38BA8" stroke-width="1.8"/><path d="M10 5.5v5.5" stroke="#F38BA8" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="14.2" r="1.2" fill="#F38BA8"/></svg>';
  var PROBLEMS = {
    burner_unconfirmed: ["The burner could not be confirmed off", "The roaster did not answer in time, so the tablet let go of it and sent nothing else. Switch the roaster off and on again, keep it close to the tablet, then try again."],
    failed: ["The roaster could not be reached", "Switch it on, keep it close to the tablet, then try again."],
    lost: ["The roaster stopped answering", "The tablet let go of it. Keep it close to the tablet, then try again."],
    bluetooth_off: ["Bluetooth is off", "Turn it on, then try again."],
    denied: ["The tablet needs permission to connect", "Allow it to connect to Bluetooth devices, then try again."]
  };

  function temp(v) { return v == null ? "—" : shownT(v).toFixed(1); }
  function live() { return link.state === "connected"; }
  function finished() { return link.state === "done"; }
  // The last roast still cools the roaster: its link is the roast's until the roaster has stopped.
  function cooling() { return link.state === "cooling"; }

  function burnerPill() {
    if (finished()) return '<div class="ck-pill ok">' + TICK + '<span><b>Roaster stopped</b><small>The test is over: burner, air and drum are off, the link is closed.</small></span></div>';
    if (cooling()) return '<div class="ck-pill warn"><span class="ck-dot pulse" style="background:var(--yellow)"></span><span><b>Cooling the last roast</b>' +
      "<small>Burner off. The roaster cools the beans, then stops by itself.</small></span></div>";
    if (live()) return '<div class="ck-pill ok">' + TICK + '<span><b>Burner off</b><small>Confirmed by the roaster. It stays off during the check.</small></span></div>';
    if (link.state === "connecting" || link.state === "verifying")
      return '<div class="ck-pill"><span class="ck-dot pulse"></span><span><b>' + (link.state === "connecting" ? "Connecting…" : "Making sure the burner is off…") +
        "</b><small>Nothing else is sent before the burner is confirmed off.</small></span></div>";
    return "";
  }

  function temps() {
    var on = (live() || finished() || cooling()) && last.bt != null, rows = [["Beans", last.bt, "var(--blue)", 44], ["Drum", last.et, "var(--red)", 30], ["Room", last.ambient, "var(--sub)", 30]];
    var html = '<div class="ck-temps"><span class="ck-live">' + (!on ? '<span class="ck-dot"></span>No reading' : live() || cooling() ?
      '<span class="ck-dot pulse" style="background:var(--green)"></span>Live from the roaster' : '<span class="ck-dot"></span>Last reading before the stop') + "</span>";
    rows.forEach(function (r) {
      html += '<div class="ck-trow"><span>' + r[0] + '</span><b class="num" style="font-size:' + r[3] + "px;color:" + (on ? r[2] : "var(--line)") + '">' +
        (on ? temp(r[1]) : "—") + "<small> " + deg() + "</small></b></div>";
    });
    return html + "</div>";
  }

  function airCard() {
    var sub = "The tablet raises the air " + (fromAir != null ? "from " + fromAir + " % " : "") + "to " + (link.test_air || 60) + " % for " + (link.test_seconds || 10) + " seconds, then stops the roaster.";
    var running = link.test_left != null;
    if (!live() && !running && !finished()) return '<div class="ck-card wait"><div class="ck-head"><span><b>Air</b><small>' + esc(sub) + '</small></span><button class="ck-btn" disabled>Test</button></div></div>';
    if (answer === "yes" && !running)
      return '<div class="ck-card done"><div class="ck-head"><span><b>Air</b><small>' + (everEchoed ? "Received by the roaster, heard by you." : "Heard by you.") +
        '</small></span><span class="ck-ok">' + TICK + 'Confirmed</span><button class="ck-link" id="ck-again">Test again</button></div></div>';
    if (answer === "no" && !running)
      return '<div class="ck-card warn"><div class="ck-head"><span><b>Air</b><small>Not heard. Check that the roaster is switched on, then test again.</small></span>' +
        '<button class="ck-btn" id="ck-again">Test again</button></div></div>';
    var echoed = running && link.air === link.test_air, html = '<div class="ck-card on"><span><b>Air</b><small>' + esc(sub) + "</small></span>";
    if (running) {
      html += '<div class="ck-line"><span class="ck-k">Sent</span><b class="num">' + link.test_air + ' %</b><span class="ck-bar"><i style="width:' +
        Math.round(100 * (1 - link.test_left / link.test_seconds)) + '%"></i></span><span class="ck-k" style="width:auto">' + link.test_left + " s left</span></div>" +
        '<div class="ck-line"><span class="ck-k">Roaster</span>' + (link.air == null ? '<span class="ck-k" style="width:auto">does not report the air</span>' :
          '<b class="num" style="color:' + (echoed ? "var(--green)" : "var(--sub)") + '">' + link.air + ' %</b><span class="ck-k" style="width:auto;color:' +
          (echoed ? "var(--green)" : "") + '">' + (echoed ? "received" : "waiting") + "</span>") + "</div>";
    }
    if (!running && !finished()) html += '<div class="ck-line"><span class="ck-k" style="width:auto">Starting…</span></div>';
    else html += '<div class="ck-ask"><b>' + (running ? "Do you hear the fan speed up?" : "Did you hear the fan speed up?") + "</b>" +
      (running ? "" : '<button class="ck-link" id="ck-again">Test again</button>') +
      '<button class="ck-btn" id="ck-no">No</button><button class="ck-btn primary" id="ck-yes">' + (running ? "Yes, I hear it" : "Yes, I heard it") + "</button></div>";
    return html + "</div>";
  }

  function problem() {
    if (cooling()) return '<div class="ck-card warn"><div style="display:flex;align-items:center;gap:12px">' + CLOCK +
      "<b>The roaster is still cooling the last roast</b></div><small>To roast back to back, start the next roast from the roast screen: " +
      "the preheat starts from where the roaster is. Otherwise the check starts by itself once the roaster has stopped.</small></div>";
    var p = PROBLEMS[link.state];
    if (!p) return "";
    return '<div class="ck-card bad"><div style="display:flex;align-items:center;gap:12px">' + ALERT + "<b>" + p[0] + '</b></div><small>' + p[1] +
      '</small><button class="ck-btn primary" id="ck-retry" style="align-self:flex-start">Try again</button></div>';
  }

  function draw() {
    if (!box || heldWhilePressed(box, draw)) return;
    var title = answer === "yes" ? "The roaster answers" : "Check the link";
    var lede = answer === "yes" ? "Temperatures arrive and the commands reach the machine. The roaster is stopped." :
      "The tablet reads the temperatures, moves the air for " + (link.test_seconds || 10) + " seconds, then stops the roaster.";
    box.innerHTML = '<div class="ck"><div class="ck-left"><h1>' + title + '</h1><div class="lede">' + lede + "</div>" + burnerPill() + temps() +
      '</div><div class="ck-right">' + problem() + airCard() + "</div></div>";
    var on = function (id, fn) { var el = document.getElementById(id); if (el) el.onclick = fn; };
    on("ck-retry", function () { connect(); });
    on("ck-again", function () { connect(); });
    on("ck-yes", function () { answer = "yes"; changed(); draw(); });
    on("ck-no", function () { answer = "no"; changed(); draw(); });
  }

  function changed() { if (Check.onChange) Check.onChange(); }
  function connect() { link = { state: "connecting" }; answer = ""; started = false; everEchoed = false; fromAir = null; last = {}; send("link_connect", address); draw(); changed(); }

  window.onLink = function (d) {
    if (!box) return;
    if (waiting && d.state === "idle") { waiting = false; connect(); return; } // the roaster has stopped: the check now
    waiting = d.state === "cooling";
    link = d;
    if (d.bt != null) last = d;
    if (d.test_left != null && d.air === d.test_air) everEchoed = true;
    if (d.state === "connected" && d.test_left == null && d.air != null) fromAir = d.air;
    // The test starts by itself once the burner is confirmed off.
    if (live() && !started) { started = true; send("air_test"); }
    draw();
  };

  return {
    onChange: null,
    open: function (container, roasterAddress) { box = container; address = roasterAddress; connect(); },
    close: function () { if (box) send("link_disconnect"); box = null; },
    passed: function () { return answer === "yes"; }
  };
})();
