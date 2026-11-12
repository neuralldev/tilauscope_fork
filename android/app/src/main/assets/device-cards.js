// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// Device cards beside a field the device fills, as the desktop's floating readings:
// the scale (a weight, or a density over a known volume). Shared by the coffee
// editor and Roast Setup.
"use strict";
var DeviceCards = (function () {
  var VOLUMES = [50, 100, 200, 250, 500];
  function card(cls, eyebrow, status, body) {
    return '<div class="ce-dev' + (cls ? " " + cls : "") + '"><div class="ce-eb">' + eyebrow + (status ? '<span class="st">' + status + "</span>" : "") + "</div>" + body + "</div>";
  }
  function dot(c) { return '<span class="ce-dot" style="background:' + c + '"></span>'; }
  function ready(sc) { return !!sc && sc.ready && sc.weight_g != null; }
  return {
    card: card, dot: dot, ready: ready,
    // o: {configured, use, hint, missing, typing}; onUse(grams) once the weight is stable
    scale: function (el, sc, o, onUse) {
      if (heldWhilePressed(el, function () { DeviceCards.scale(el, sc, o, onUse); })) return;
      if (!o.configured) el.innerHTML = card("wait", "⚖ SCALE", "", '<div class="ce-hint">' + o.missing + "</div>");
      else if (!ready(sc)) el.innerHTML = card("wait", "⚖ SCALE", dot("var(--muted)") + "Connecting…", '<div class="ce-read dim">–– <small>g</small></div><div class="ce-hint">Switch the scale on. ' + o.typing + "</div>");
      else el.innerHTML = card("", "⚖ SCALE", dot(sc.stable ? "var(--green)" : "var(--yellow)") + (sc.stable ? "stable" : "settling"),
        '<div class="ce-read num">' + Math.round(sc.weight_g) + ' <small>g</small></div><button class="ce-use"' + (sc.stable ? "" : " disabled") + ">" + o.use + "</button>" +
        (o.hint ? '<div class="ce-hint">' + o.hint + "</div>" : ""));
      var b = el.querySelector(".ce-use"); if (b) b.onclick = function () { onUse(Math.round(sc.weight_g)); };
    },
    // the net weight in a container of `volume` ml, as the desktop's density window
    density: function (el, sc, configured, volume, onVolume, onUse) {
      if (heldWhilePressed(el, function () { DeviceCards.density(el, sc, configured, volume, onVolume, onUse); })) return;
      var net = ready(sc) ? sc.weight_g : null, dens = net > 0 ? Math.round(net * 1000 / volume) : null;
      el.innerHTML = !configured ? card("wait", "⚖ DENSITY", "", '<div class="ce-hint">No scale in Settings › Devices: pair it there to measure density.</div>') :
        card("", "⚖ DENSITY", ready(sc) ? dot("var(--green)") + "net " + Math.round(net) + " g" : dot("var(--muted)") + "Connecting…",
          '<div class="ce-read num' + (dens ? "" : " dim") + '">' + (dens || "–––") + ' <small>g/l</small></div><div class="ce-vols">' + VOLUMES.map(function (v) {
            return '<button data-vol="' + v + '"' + (v === volume ? ' class="on"' : "") + ">" + v + " ml</button>";
          }).join("") + '</div><div class="ce-row"><span class="ce-hint">Tare the empty container, then fill it to the line.</span><button class="ce-tare">TARE</button></div>' +
          '<button class="ce-use"' + (dens ? "" : " disabled") + ">Use as density</button>");
      el.querySelectorAll("[data-vol]").forEach(function (b) { b.onclick = function () { onVolume(+b.dataset.vol); }; });
      var t = el.querySelector(".ce-tare"); if (t) t.onclick = function () { send("scale_tare"); };
      var u = el.querySelector(".ce-use"); if (u && dens) u.onclick = function () { onUse(dens); };
    }
  };
})();
