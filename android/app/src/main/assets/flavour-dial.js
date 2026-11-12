// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The desktop's flavour wheel as a dial: the whole wheel drawn large around a centre
// off the left edge, turned by dragging or by a family button; a tap on a note
// toggles it. Notes are kept as the desktop keeps them: lower case, sorted, comma
// separated, notes outside the wheel included.
"use strict";
var FlavourDial = (function () {
  var CX = -100, CY = 0, RINGS = [[260, 330], [330, 410], [410, 500], [500, 700]], DRAG = 6, R_DRAG = 600;
  var box = null, wheel = null, chosen = null, turn = 0, onUse = null, leaves = [], families = [];

  function lum(hex) { var n = parseInt(hex.slice(1), 16); return 0.299 * (n >> 16) + 0.587 * (n >> 8 & 255) + 0.114 * (n & 255); }
  function pt(r, a) { var t = (a - 90) * Math.PI / 180; return [CX + r * Math.cos(t), CY + r * Math.sin(t)]; }
  function sector(r0, r1, a0, a1) {
    var big = a1 - a0 > 180 ? 1 : 0, p0 = pt(r1, a0), p1 = pt(r1, a1), p2 = pt(r0, a1), p3 = pt(r0, a0);
    return "M" + p0 + "A" + r1 + " " + r1 + " 0 " + big + " 1 " + p1 + "L" + p2 + "A" + r0 + " " + r0 + " 0 " + big + " 0 " + p3 + "Z";
  }
  function text(r, a, label, size, lit, bg, radial) {
    var p = pt(r, a), rot = radial ? a - 90 : a, m = ((a % 360) + 360) % 360;
    if (radial ? m > 180 : m > 90 && m < 270) rot += 180;
    var fill = lit ? (lum(bg) > 160 ? "#11111B" : "#FFFFFF") : "#A6ADC8";
    return '<text x="' + p[0].toFixed(1) + '" y="' + p[1].toFixed(1) + '" transform="rotate(' + rot.toFixed(1) + " " + p[0].toFixed(1) + " " + p[1].toFixed(1) +
      ')" text-anchor="middle" dominant-baseline="central" font-size="' + size + '" font-weight="' + (lit ? 700 : 500) + '" fill="' + fill + '">' + esc(label) + "</text>";
  }

  // Every arc once: [level, name, colour, first leaf, leaf count, notes below]
  function build() {
    var arcs = [], i = 0;
    leaves = []; families = [];
    Object.keys(wheel).forEach(function (fam) {
      var f = wheel[fam], f0 = i, fNotes = [];
      Object.keys(f.groups).forEach(function (grp) {
        var g = f.groups[grp], g0 = i, gNotes = [];
        Object.keys(g.subgroups).forEach(function (sub) {
          var s = g.subgroups[sub], s0 = i, sNotes = [];
          s.notes.forEach(function (n) { arcs.push([3, n, s.color, i, 1, [n.toLowerCase()]]); leaves.push(n.toLowerCase()); sNotes.push(n.toLowerCase()); i++; });
          arcs.push([2, sub, s.color, s0, i - s0, sNotes]); gNotes = gNotes.concat(sNotes);
        });
        arcs.push([1, grp, g.color, g0, i - g0, gNotes]); fNotes = fNotes.concat(gNotes);
      });
      arcs.push([0, fam, f.color, f0, i - f0, fNotes]);
      families.push([fam, f.color, f0, i - f0]);
    });
    return arcs;
  }
  var arcs = [];

  function unit() { return 360 / leaves.length; }
  function draw() {
    var u = unit(), svg = "";
    arcs.forEach(function (a) {
      var a0 = a[3] * u + turn, a1 = a0 + a[4] * u;
      var ring = RINGS[a[0]], lit = a[5].some(function (n) { return chosen[n]; });
      svg += '<path d="' + sector(ring[0], ring[1], a0, a1) + '" fill="' + a[2] + '" fill-opacity="' + (lit ? 1 : .2) + '" stroke="#11111B" stroke-width="1"' +
        (a[0] === 3 ? ' data-n="' + esc(a[5][0]) + '"' : "") + "/>";
      var r = (ring[0] + ring[1]) / 2, room = a[4] * u * Math.PI / 180 * r;
      if (a[0] === 3) svg += text(r, (a0 + a1) / 2, a[1], 12, lit, a[2], true);
      else if (room > 40) svg += text(r, (a0 + a1) / 2, a[1].length > 18 ? a[1].slice(0, 17) + "…" : a[1], a[0] === 0 ? 14 : 12, lit, a[2], false);
    });
    $("fd-svg").innerHTML = svg;
    var tabs = "";
    families.forEach(function (f) {
      var mid = ((f[2] + f[3] / 2) * unit() + turn) % 360, on = Math.abs(((mid + 360) % 360) - 90) < f[3] * unit() / 2;
      tabs += '<button class="fd-tab' + (on ? " on" : "") + '" data-f="' + f[2] + '" style="' + (on ? "border-color:" + f[1] : "") + '"><i style="background:' + f[1] + '"></i>' +
        esc(f[0]) + "<small>" + f[3] + "</small></button>";
    });
    $("fd-tabs").innerHTML = tabs;
    $("fd-tabs").querySelectorAll(".fd-tab").forEach(function (b) {
      b.onclick = function () { var f = families.filter(function (x) { return x[2] === +b.dataset.f; })[0]; face(f[2] + f[3] / 2); draw(); };
    });
    chips();
  }
  function face(leaf) { turn = 90 - leaf * unit(); } // that leaf points right

  function chips() {
    var on = leaves.filter(function (n) { return chosen[n]; }), kept = Object.keys(chosen).filter(function (n) { return chosen[n] && leaves.indexOf(n) < 0; });
    var colour = {};
    arcs.forEach(function (a) { if (a[0] === 3) colour[a[5][0]] = a[2]; });
    $("fd-chips").innerHTML = '<div class="fd-eb">CHOSEN · ' + on.length + "</div>" + (on.length ? '<div class="fd-chips">' + on.map(function (n) {
      return '<button data-n="' + esc(n) + '" style="background:' + colour[n] + ";color:" + (lum(colour[n]) > 160 ? "#11111B" : "#fff") + '">' + esc(n) + " ✕</button>";
    }).join("") + "</div>" : '<div class="fd-none">Tap a note on the dial</div>') +
      (kept.length ? '<div class="fd-eb">KEPT · NOT ON THE WHEEL</div><div class="fd-chips">' + kept.map(function (n) { return '<span>' + esc(n) + "</span>"; }).join("") + "</div>" : "");
    $("fd-chips").querySelectorAll("button").forEach(function (b) { b.onclick = function () { delete chosen[b.dataset.n]; draw(); }; });
  }

  function wire() {
    var svg = $("fd-svg"), start = null, moved = false, startTurn = 0;
    svg.addEventListener("pointerdown", function (e) { start = e.clientY; moved = false; startTurn = turn; });
    svg.addEventListener("pointermove", function (e) {
      if (start == null) return;
      var dy = e.clientY - start;
      if (Math.abs(dy) > DRAG) moved = true;
      if (moved) { turn = startTurn + dy / R_DRAG * 180 / Math.PI; draw(); }
    });
    svg.addEventListener("pointerup", function () { start = null; });
    svg.addEventListener("pointerleave", function () { start = null; });
    svg.addEventListener("click", function (e) { // a tap on a note, never the end of a drag
      var n = !moved && e.target.getAttribute && e.target.getAttribute("data-n");
      if (n) { if (chosen[n]) delete chosen[n]; else chosen[n] = true; draw(); }
    });
  }

  return {
    open: function (data, notes, name, use) {
      wheel = data; onUse = use; arcs = build(); chosen = {};
      (notes || "").split(",").forEach(function (n) { n = n.trim().toLowerCase(); if (n) chosen[n] = true; });
      var first = leaves.filter(function (n) { return chosen[n]; })[0];
      face(first ? leaves.indexOf(first) : families[0][2] + families[0][3] / 2);
      box = document.createElement("div");
      box.id = "fd";
      box.innerHTML = '<div class="ehead"><button class="eback" id="fd-back" aria-label="Back"><svg width="24" height="24" viewBox="0 0 18 18" aria-hidden="true"><path d="M11 4L6 9l5 5" fill="none" stroke="#A6ADC8" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><span class="t"><b>FLAVOUR NOTES — ' + esc(name.toUpperCase()) + '</b><small>Turn the dial with a family or by dragging, tap a note</small></span>' +
        '<span style="flex:1"></span><button class="btn save" id="fd-use">✓ Use these notes</button></div>' +
        '<div class="fd-body"><div class="fd-side"><div id="fd-tabs"></div><div id="fd-chips"></div></div>' +
        '<svg id="fd-svg" viewBox="0 -320 904 640" preserveAspectRatio="xMinYMid meet"></svg></div>';
      document.body.appendChild(box);
      $("fd-back").onclick = function () { box.remove(); };
      $("fd-use").onclick = function () {
        // as the desktop's notes_text: lower case, sorted, comma separated
        var text = Object.keys(chosen).filter(function (n) { return chosen[n]; }).sort().join(", ");
        box.remove(); onUse(text);
      };
      wire(); draw();
    }
  };
})();
