// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The energy sheet of a roast (MQTT-SPEC E2), shared by the roast screen's end card and BeanCave › Roasts:
// the total, each source's power over the roast, the three periods and one line per source. Touching outside closes.
"use strict";
var PROVENANCE = { measured: "measured", estimated: "estimated", mixed: "measured and estimated", none: "not tracked" };
var ENERGY_ICON = '<svg width="34" height="34" viewBox="0 0 24 24" aria-hidden="true" style="flex:none"><circle cx="12" cy="12" r="11" fill="rgba(249,226,175,.12)"/><path d="M13 5l-5 8h4l-1 6 5-8h-4z" fill="none" stroke="#F9E2AF" stroke-width="1.8" stroke-linejoin="round"/></svg>';
var SOURCE_COLOUR = { roaster: "var(--peach)", extractor: "var(--teal)" };
function signedTime(t) { return (t < 0 ? "−" : "") + efmt(Math.abs(t)); }
function energyCurve(e) {
  var origin = e.charge != null ? e.charge : 0, t0 = e.start - origin, t1 = Math.max(e.end - origin, t0 + 60);
  var top = 200;
  Object.keys(e.channels).forEach(function (n) { ["measured", "estimated"].forEach(function (k) { e.channels[n][k].forEach(function (p) { top = Math.max(top, p[1]); }); }); });
  top = Math.ceil(top * 1.1 / 200) * 200;
  var L = 52, R = 812, T = 22, B = 150, X = function (t) { return (L + (t - origin - t0) / (t1 - t0) * (R - L)).toFixed(1); };
  var Y = function (w) { return (B - w / top * (B - T)).toFixed(1); };
  var svg = '<svg width="100%" height="190" viewBox="0 0 820 190" role="img" aria-label="Power in watts over the roast">';
  [0, top / 2, top].forEach(function (w) {
    svg += '<line x1="' + L + '" x2="' + R + '" y1="' + Y(w) + '" y2="' + Y(w) + '" stroke="#313244"' + (w ? ' stroke-dasharray="2 4"' : "") + "/>" +
      '<text x="0" y="' + (+Y(w) + 4) + '" font-size="11" fill="#6C7086">' + Math.round(w) + (w ? " W" : "") + "</text>";
  });
  var step = (t1 - t0) > 1200 ? 240 : 120;
  for (var t = Math.ceil(t0 / step) * step; t <= t1; t += step)
    svg += '<text x="' + X(t + origin) + '" y="176" font-size="11" fill="#6C7086" text-anchor="middle">' + signedTime(t) + "</text>";
  [["CHARGE", e.charge], ["DROP", e.drop]].forEach(function (m) {
    if (m[1] == null) return;
    var x = X(m[1]), w = m[0].length * 7 + 12;
    svg += '<line x1="' + x + '" x2="' + x + '" y1="8" y2="' + (B + 8) + '" stroke="#A6ADC8" stroke-width="1.2" stroke-dasharray="4 3"/>' +
      '<rect x="' + (x - w / 2) + '" y="0" width="' + w + '" height="16" rx="8" fill="#313244"/><text x="' + x + '" y="12" font-size="11" font-weight="600" fill="#CDD6F4" text-anchor="middle">' + m[0] + "</text>";
  });
  Object.keys(e.channels).forEach(function (n) {
    var ch = e.channels[n], colour = SOURCE_COLOUR[n] || "var(--sub)", d = "", last = null;
    ch.measured.forEach(function (p) { // a gap longer than the source's freshness is no reading: the line breaks
      d += (last && p[0] - last <= ch.max_gap_s ? " L" : " M") + X(p[0]) + " " + Y(p[1]); last = p[0];
    });
    if (d) svg += '<path d="' + d + '" fill="none" stroke="' + colour + '" stroke-width="2.4" stroke-linejoin="round"/>';
    d = "";
    ch.estimated.forEach(function (p, i) { // an estimate holds until the next one; -1 ends it
      if (p[1] < 0) return;
      var next = i + 1 < ch.estimated.length ? ch.estimated[i + 1][0] : e.end;
      d += " M" + X(p[0]) + " " + Y(p[1]) + " H" + X(next);
    });
    if (d) svg += '<path d="' + d + '" fill="none" stroke="' + colour + '" stroke-width="2.4" stroke-dasharray="5 4"/>';
  });
  return svg + "</svg>";
}
function showEnergy(e) {
  sheet();
  var chip = { measured: ["var(--green)", "rgba(166,227,161,.10)"], none: ["var(--muted)", "var(--surface)"] }[e.provenance] || ["var(--yellow)", "rgba(249,226,175,.10)"];
  var html = '<div style="display:flex;align-items:center;gap:14px">' + ENERGY_ICON.replace('width="34" height="34"', 'width="40" height="40"') +
    '<span style="display:flex;flex-direction:column;gap:2px;flex:1"><span style="font-size:13px;color:var(--sub)">' + (e.complete ? "Total since Start" : "Known consumption") +
    '</span><span class="num" style="font-size:28px;font-weight:600">' + e.kwh.toFixed(3) + " kWh</span></span>" +
    '<span style="font-size:13px;color:' + chip[0] + ";background:" + chip[1] + ';border-radius:12px;padding:5px 12px">' + PROVENANCE[e.provenance].replace(/^./, function (c) { return c.toUpperCase(); }) + "</span></div>" +
    '<div style="background:var(--surface);border-radius:14px;padding:10px 12px 6px;display:flex;flex-direction:column;gap:4px">' + energyCurve(e) +
    '<div style="display:flex;gap:18px;font-size:12px;color:var(--sub)">' + Object.keys(e.channels).map(function (n) {
      return '<span style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:3px;border-radius:2px;background:' + (SOURCE_COLOUR[n] || "var(--sub)") + '"></span>' + n.replace(/^./, function (c) { return c.toUpperCase(); }) + "</span>";
    }).join("") + "</div></div>" +
    '<div style="display:grid;grid-template-columns:repeat(' + e.periods.length + ',minmax(0,1fr));gap:12px">' + e.periods.map(function (p) {
      var roast = p.name === "Roast", d = roast && e.per_kg_kwh != null ? e.per_kg_kwh.toFixed(2) + " kWh/kg green · " + efmt(p.s) : efmt(p.s);
      return '<div class="etile"' + (roast ? ' style="border:1px solid var(--line)"' : "") + '><span class="k">' + p.name + '</span><span class="v num">' + p.kwh.toFixed(3) +
        ' kWh</span><span class="d num">' + d + "</span></div>";
    }).join("") + "</div><div>" + e.sources.map(function (s) {
      return '<div class="esrc"><span style="width:10px;height:10px;border-radius:5px;background:' + (SOURCE_COLOUR[s.name] || "var(--sub)") + '"></span><span style="flex:1">' +
        s.name.replace(/^./, function (c) { return c.toUpperCase(); }) + '</span><span style="font-size:13px;color:' + (s.provenance === "measured" ? "var(--green)" : s.provenance === "none" ? "var(--muted)" : "var(--yellow)") + '">' +
        PROVENANCE[s.provenance] + '</span><span class="num" style="width:110px;text-align:right;font-weight:600">' + s.kwh.toFixed(3) + " kWh</span></div>";
    }).join("") + "</div>";
  $("energycard").innerHTML = html;
  $("energy").style.display = "flex";
}
function efmt(sec) {
  var s = Math.max(0, Math.round(sec));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
function sheet() {
  if ($("energy")) return;
  var scrim = document.createElement("div");
  scrim.id = "energy"; scrim.className = "escrim";
  scrim.innerHTML = '<div class="ecard" id="energycard"></div>';
  document.body.appendChild(scrim);
  scrim.onclick = function () { scrim.style.display = "none"; };
  $("energycard").onclick = function (e) { e.stopPropagation(); };
}
var EnergySheet = { show: showEnergy, hide: function () { if ($("energy")) $("energy").style.display = "none"; } };
