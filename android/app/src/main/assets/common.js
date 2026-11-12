// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// Shared by every page: the bridge to the session service and the start screen.
"use strict";
var $ = function (id) { return document.getElementById(id); };
var send = function (method, arg) { if (window.TilauBridge) TilauBridge.call(method, arg || ""); };
var go = function (page) { location.href = page; };
// Text for HTML, attribute values included: imported file names and coffee records may hold quotes.
function esc(t) {
  return String(t == null ? "" : t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
// A block rebuilt under the finger loses its tap: the click goes to an ancestor. A block rebuilt by live data
// (a scale, a scan, the link) waits while it is pressed and is rebuilt once the press has ended, its click first.
var pressed = null, heldRebuilds = [];
document.addEventListener("pointerdown", function (e) { pressed = e.target; }, true);
function pressEnded() {
  if (!pressed) return;
  pressed = null;
  setTimeout(function () { var todo = heldRebuilds; heldRebuilds = []; todo.forEach(function (h) { h.fn(); }); }, 0);
}
document.addEventListener("pointerup", pressEnded, true);
document.addEventListener("pointercancel", pressEnded, true);
// True when `el` is pressed: `fn` (the rebuild, latest one kept) then runs once the press ends.
function heldWhilePressed(el, fn) {
  if (!pressed || !el || !el.contains(pressed)) return false;
  heldRebuilds = heldRebuilds.filter(function (h) { return h.el !== el; }).concat([{ el: el, fn: fn }]);
  return true;
}
// The temperature unit chosen in Settings › General (UNIT-SPEC): the tablet keeps °C, the screens show
// this one. Each page takes it from the session's answers; a label with class "deg" follows it.
var UNIT = "C";
function setUnit(unit) {
  if (unit !== "C" && unit !== "F") return;
  UNIT = unit;
  document.querySelectorAll(".deg").forEach(function (el) { el.textContent = deg(); });
}
function deg() { return UNIT === "F" ? "°F" : "°C"; }
function shownT(c) { return UNIT === "F" ? c * 1.8 + 32 : c; } // a temperature
function shownD(c) { return UNIT === "F" ? c * 1.8 : c; } // a rate of rise or a difference
function typedT(v) { return UNIT === "F" ? (v - 32) / 1.8 : v; } // a temperature typed, back to °C

// The system currency: purchase prices are in it until one is chosen, as on the desktop.
var systemCurrency = function () { return (window.TilauBridge && TilauBridge.currency && TilauBridge.currency()) || "EUR"; };

// The start screen covers the page until the session answers for the first time.
(function () {
  var splash = document.createElement("div");
  splash.id = "splash";
  splash.setAttribute("aria-label", "Starting");
  splash.innerHTML =
    '<div class="bean"><svg viewBox="0 0 512 512" width="132" height="132" aria-hidden="true">' +
    '<defs><mask id="spcrease" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512">' +
    '<rect x="0" y="0" width="512" height="512" fill="#fff"/>' +
    '<path d="M 256,104 C 294,170 218,212 256,256 C 294,300 218,342 256,408" fill="none" stroke="#000" stroke-width="36" stroke-linecap="round"/>' +
    '</mask></defs><g transform="rotate(-28 256 256)"><path mask="url(#spcrease)" fill="currentColor" ' +
    'd="M 256,51 C 338.8,51 406,142.8 406,256 C 406,369.2 338.8,461 256,461 C 173.2,461 106,369.2 106,256 C 106,142.8 173.2,51 256,51 Z"/></g></svg></div>' +
    '<div style="margin-top:28px;font-size:30px;font-weight:600;letter-spacing:.3px">TilauScope</div>' +
    '<div style="margin-top:8px;font-size:15px;color:var(--sub)">Getting the roaster ready…</div>' +
    '<div class="bar"><i></i></div>' +
    '<div style="position:absolute;bottom:24px;font-size:12px;color:var(--muted)">Android Lab · 0.1.0 prototype</div>';
  document.body.insertBefore(splash, document.body.firstChild);
})();

function splashDone() { $("splash").classList.add("done"); }

var audio = null, audioOut = null;
// TilauScope's signature, Bloom: a warm major chord opening note after note. The full take greets the app's
// launch; the short one rings an alarm's bell.
function soundEngine() {
  if (audioOut) return audioOut;
  var comp = audio.createDynamicsCompressor(), master = audio.createGain(), verb = audio.createConvolver(), wet = audio.createGain();
  comp.threshold.value = -18; comp.ratio.value = 3; master.gain.value = 0.8; wet.gain.value = 0.28;
  var len = Math.floor(audio.sampleRate * 1.8), ir = audio.createBuffer(2, len, audio.sampleRate); // a small room
  for (var ch = 0; ch < 2; ch++) {
    var d = ir.getChannelData(ch);
    for (var i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3.2);
  }
  verb.buffer = ir;
  master.connect(comp); comp.connect(audio.destination); verb.connect(wet); wet.connect(master);
  audioOut = [master, verb];
  return audioOut;
}
function bloomVoice(freq, at, peak, decay, sweep) {
  var g = audio.createGain(), f = audio.createBiquadFilter();
  g.gain.setValueAtTime(0.0001, at);
  g.gain.exponentialRampToValueAtTime(peak, at + 0.06);
  g.gain.exponentialRampToValueAtTime(0.0001, at + decay);
  f.type = "lowpass";
  f.frequency.setValueAtTime(500, at);
  f.frequency.exponentialRampToValueAtTime(4200, at + sweep);
  f.connect(g);
  soundEngine().forEach(function (n) { g.connect(n); });
  [[1, 1], [2, 0.22], [3, 0.08]].forEach(function (h) { // the note, a quiet octave and twelfth, each a detuned pair
    [-6, 6].forEach(function (cents) {
      var o = audio.createOscillator(), og = audio.createGain();
      o.frequency.value = freq * h[0]; o.detune.value = cents; og.gain.value = h[1] / 2;
      o.connect(og); og.connect(f);
      o.start(at); o.stop(at + decay + 0.1);
    });
  });
}
function tilauSound(short) {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === "suspended") audio.resume(); // created before any touch, it starts silent
    var t = audio.currentTime + 0.05;
    (short ? [65, 69, 72] : [53, 60, 65, 69, 79]).forEach(function (note, k) { // F4 A4 C5, or F3 C4 F4 A4 G5
      bloomVoice(440 * Math.pow(2, (note - 69) / 12), t + k * (short ? 0.07 : 0.11), short ? 0.16 : 0.13,
                 short ? 0.85 : 2.5, short ? 0.4 : 1.2);
    });
  } catch (e) { /* no sound on this device */ }
}

// Once per launch of the app: the page changes keep the window's name, a new launch starts without it.
if (window.name !== "tilauscope-started") {
  window.name = "tilauscope-started";
  tilauSound(false);
}
