// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The label printer check from Settings: the tablet connects, shows what the
// printer reports and prints one test label drawn here, on a 30 mm roll.
// Needs common.js, label.js, check styles (common.css) and an esc() helper on the page.
"use strict";
var PrinterCheck = (function () {
  var box = null, address = "", name = "", link = {}, wasConnected = false, label = null;
  var W = Label.W, H = Label.H;
  var TICK = '<svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="10" fill="#A6E3A1"/><path d="M5.5 10.5l3 3 6-6.5" fill="none" stroke="#1E1E2E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var ALERT = '<svg width="24" height="24" viewBox="0 0 20 20" aria-hidden="true" style="flex:none"><circle cx="10" cy="10" r="9" fill="none" stroke="#F38BA8" stroke-width="1.8"/><path d="M10 5.5v5.5" stroke="#F38BA8" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="14.2" r="1.2" fill="#F38BA8"/></svg>';
  var PROBLEMS = {
    lost: ["The printer could not be reached", "Switch it on, keep it close to the tablet, then try again."],
    bluetooth_off: ["Bluetooth is off", "Turn it on, then try again."],
    denied: ["The tablet needs permission to connect", "Allow it to connect to Bluetooth devices, then try again."]
  };
  var FAILURES = {
    no_answer: ["The printer did not answer", "Nothing was printed. Keep it close to the tablet, then print again."],
    cover_open: ["The cover is open", "Close the printer cover, then print again. Nothing was printed."]
  };
  // Roll types as the printer reports them from the roll's tag (desktop Niimprint_PaperType).
  var ROLLS = { 1: "Labels with gaps", 2: "Black", 3: "Continuous", 4: "Perforated", 5: "Transparent", 6: "PVC tag", 10: "Black mark gap", 11: "Heat shrink tube" };
  // The TilauScope bean, as on the start screen and the desktop labels (512 × 512 box).
  var BEAN = "M 256,51 C 338.8,51 406,142.8 406,256 C 406,369.2 338.8,461 256,461 C 173.2,461 106,369.2 106,256 C 106,142.8 173.2,51 256,51 Z";
  var CREASE = "M 256,104 C 294,170 218,212 256,256 C 294,300 218,342 256,408";

  function stamp() {
    var d = new Date(), p = function (n) { return ("0" + n).slice(-2); };
    return p(d.getDate()) + "-" + p(d.getMonth() + 1) + "-" + d.getFullYear() + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  // Draws the label, then keeps it black or white only: the preview is what prints.
  function draw1bit(when) {
    var c = document.createElement("canvas"), g = c.getContext("2d");
    c.width = W; c.height = H;
    g.fillStyle = "#fff"; g.fillRect(0, 0, W, H);
    g.fillStyle = g.strokeStyle = "#000";
    g.lineWidth = 3; g.strokeRect(3.5, 3.5, W - 7, H - 7);
    g.save(); g.translate(14, 16); g.scale(60 / 512, 60 / 512);
    g.translate(256, 256); g.rotate(-28 * Math.PI / 180); g.translate(-256, -256);
    g.fill(new Path2D(BEAN));
    g.globalCompositeOperation = "destination-out"; g.lineWidth = 36; g.lineCap = "round"; g.stroke(new Path2D(CREASE));
    g.restore();
    g.fillStyle = "#000"; g.textBaseline = "alphabetic";
    g.font = "bold 30px sans-serif"; g.fillText("TilauScope", 84, 46);
    g.font = "600 20px sans-serif"; g.fillText("Test label · 30 mm", 84, 72);
    g.font = "18px sans-serif";
    var words = "If this text is sharp and the frame complete, the printer is ready.".split(" "), line = "", y = 112;
    words.forEach(function (w) {
      var next = line ? line + " " + w : w;
      if (g.measureText(next).width > W - 32 && line) { g.fillText(line, 16, y); y += 24; line = w; } else line = next;
    });
    g.fillText(line, 16, y);
    g.fillRect(14, H - 50, W - 28, 2);
    g.font = "18px sans-serif"; g.fillText(when, 16, H - 20);
    var tag = "B21S"; g.fillText(tag, W - 16 - g.measureText(tag).width, H - 20);
    return Label.oneBit(c);
  }

  function pill() {
    if (link.print === "printed") return '<div class="ck-pill ok">' + TICK + "<span><b>Check done</b><small>The printer confirmed the label.</small></span></div>";
    if (link.state === "connected") return '<div class="ck-pill ok">' + TICK + "<span><b>Connected</b><small>The printer answers.</small></span></div>";
    if (link.state === "connecting") return '<div class="ck-pill"><span class="ck-dot pulse"></span><span><b>Connecting…</b></span></div>';
    return "";
  }

  function stats() {
    if (link.state !== "connected") return "";
    var open = (link.cover || 0) !== 0 || link.paper === 2, cover = link.paper === 1 ? "No paper" : open ? "Open" : link.cover == null && link.paper == null ? "—" : "Closed";
    var tiles = [["Battery", link.battery == null ? "—" : link.battery + " / 5"], ["Cover", cover],
      ["Roll", link.roll_type == null ? "No tag read" : ROLLS[link.roll_type] || "Type " + link.roll_type],
      ["Labels left", link.labels_left == null ? "—" : link.labels_left + (link.labels_total ? " / " + link.labels_total : "")]];
    return '<div class="pc-stat">' + tiles.map(function (t) {
      return "<div><span>" + t[0] + '</span><b class="num"' + (t[0] === "Cover" && cover !== "Closed" && cover !== "—" ? ' style="color:var(--peach)"' : "") + ">" + esc(t[1]) + "</b></div>";
    }).join("") + "</div>";
  }

  function preview() { return '<img class="pc-label" src="' + label.url + '" width="' + W + '" height="' + H + '" alt="Test label">'; }

  function printCard() {
    var p = link.print;
    if (p === "sending" || p === "printing")
      return '<div class="ck-card on"><b>Printing…</b>' + preview() + '<div class="pc-prog"><div><span>' + (p === "sending" ? "Sending the label to the printer" : "The printer is printing the label") +
        '</span><span class="num">' + (p === "sending" ? link.progress + " %" : "") + '</span></div><div class="ck-bar"><i style="width:' + (p === "sending" ? link.progress : 100) + '%"></i></div></div>' +
        "<small>Keep the tablet close until the label is out.</small></div>";
    if (p === "printed")
      return '<div class="ck-card"><div style="display:flex;align-items:center;gap:12px">' + TICK + "<b>The label is out</b></div><small>Check that the text is sharp and the frame complete.</small>" +
        preview() + '<button class="ck-btn" id="pk-print" style="align-self:flex-start">Print again</button></div>';
    var head = "";
    if (p === "unconfirmed")
      head = '<div class="ck-card warn"><b>Not confirmed — check the label</b><small>Check the label before printing it again — the printer did not confirm it, so it may have come out correctly or blank.</small></div>';
    if (p === "failed") {
      var f = FAILURES[link.failure] || FAILURES.no_answer;
      head = '<div class="ck-card bad"><div style="display:flex;align-items:center;gap:12px">' + ALERT + "<b>" + f[0] + "</b></div><small>" + f[1] + "</small></div>";
    }
    return head + '<div class="ck-card on"><b>Test label</b><small>Load a 30 mm roll and close the cover. One label is used.</small>' + preview() +
      '<button class="ck-btn primary" id="pk-print" style="align-self:flex-start">' + (p ? "Print again" : "Print test label") + "</button></div>";
  }

  function problem() {
    var p = link.state === "lost" && wasConnected ? ["The printer stopped answering", link.print === "unconfirmed" ?
      "The label may have come out correctly or blank. Switch the printer on and keep it close to the tablet: the tablet reconnects by itself." :
      "Switch the printer on and keep it close to the tablet: the tablet reconnects by itself."] : PROBLEMS[link.state];
    if (!p) return "";
    return '<div class="ck-card bad"><div style="display:flex;align-items:center;gap:12px">' + ALERT + "<b>" + p[0] + "</b></div><small>" + p[1] +
      '</small><button class="ck-btn primary" id="pk-retry" style="align-self:flex-start">Try again</button></div>';
  }

  function draw() {
    if (!box) return;
    var right = problem() || (link.state === "connected" ? printCard() : "");
    box.innerHTML = '<div class="ck"><div class="ck-left"><h1>Check the label printer</h1><div class="lede">The tablet connects to ' + esc(name) +
      ", reads its state and prints one test label.</div>" + pill() + stats() + '</div><div class="ck-right">' + right + "</div></div>";
    var on = function (id, fn) { var el = document.getElementById(id); if (el) el.onclick = fn; };
    on("pk-retry", connect);
    on("pk-print", function () {
      label = draw1bit(stamp());
      send("printer_print", Label.base64(label.rows));
    });
  }

  function connect() { link = { state: "connecting" }; wasConnected = false; send("printer_connect", address); draw(); }

  window.onPrinter = function (d) {
    if (!box) return;
    if (d.state === "connected") wasConnected = true;
    link = d;
    draw();
  };

  return {
    open: function (container, device) { box = container; address = device.address; name = device.name || "the printer"; label = draw1bit(stamp()); connect(); },
    close: function () { if (box) send("printer_disconnect"); box = null; }
  };
})();
