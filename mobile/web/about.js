// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// Settings › General › About TilauScope: the version, the licence, the source, and the parts the app is built
// with, each opening its licence. The texts are in licenses/ beside the pages; the app reads one on demand
// (call "licence", answered by onLicence) since a page cannot read a file itself.

// Per app ("ios", "android"): what each one bundles, its version when known (ios/Python.xcframework/VERSIONS,
// the Chaquopy Python target of android/app/build.gradle.kts). A part an app lacks has no entry for it.
var BUILT_WITH = [
  { name: "Python", role: "The engine that runs the roast", licence: "PSF License", file: "Python-PSF.txt", v: { ios: "3.14.10", android: "3.14.0" } },
  { name: "Chaquopy", role: "Python on Android", licence: "MIT License", file: "Chaquopy-MIT.txt", v: { android: "17.0.0" } },
  { name: "Kotlin standard library", role: "The Android app itself", licence: "Apache License 2.0", file: "Apache-2.0.txt", v: { android: "2.1.20" } },
  { name: "OpenSSL", role: "Secure connections to the community library", licence: "Apache License 2.0", file: "Apache-2.0.txt", v: { ios: "3.5.9", android: "3.0.18" } },
  { name: "Certificate authorities (certifi)", role: "Trusted sites for the community library", licence: "Mozilla Public License 2.0", file: "certifi-MPL-2.0.txt", v: { ios: "", android: "" } },
  { name: "SQLite", role: "Part of Python on Android", licence: "Public domain", file: "SQLite-public-domain.txt", v: { android: "3.50.4" } },
  { name: "DejaVu Sans", role: "The roast label's font", licence: "Bitstream Vera licence", file: "DejaVu-Fonts.txt", v: { ios: "", android: "" } },
  { name: "JetBrains Mono", role: "The roast card's figures", licence: "SIL Open Font License 1.1", file: "JetBrainsMono-OFL.txt", v: { ios: "", android: "" } },
  { name: "libffi", role: "Part of Python", licence: "MIT License", file: "libffi-MIT.txt", v: { ios: "3.4.7", android: "" } },
  { name: "mpdecimal", role: "Part of Python: decimal numbers", licence: "BSD 2-Clause License", file: "mpdecimal-BSD-2-Clause.txt", v: { ios: "4.0.0", android: "" } },
  { name: "XZ Utils", role: "Part of Python: compression", licence: "BSD Zero Clause License", file: "XZ-0BSD.txt", v: { ios: "5.6.4", android: "" } },
  { name: "Zstandard", role: "Part of Python: compression", licence: "BSD 3-Clause License", file: "Zstandard-BSD-3-Clause.txt", v: { ios: "1.5.7", android: "" } },
  { name: "bzip2", role: "Part of Python: compression", licence: "bzip2 licence, BSD-style", file: "bzip2.txt", v: { ios: "1.0.8", android: "" } }
];
var OWN_LICENCE = "TilauScope-AGPL-3.0.txt";

// {platform, version, build} from the app; a page opened outside it shows the iPad's list.
function aboutApp() {
  try { if (window.TilauBridge && TilauBridge.about) return JSON.parse(TilauBridge.about()); } catch (e) { /* outside the app */ }
  return { platform: "ios", version: "", build: "" };
}

var ABOUT_ICON = '<svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true" style="flex:none"><circle cx="12" cy="12" r="9" fill="none" stroke="#A6ADC8" stroke-width="1.8"/>' +
  '<path d="M12 11v6" stroke="#A6ADC8" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="7.6" r="1.1" fill="#A6ADC8"/></svg>';
var CHEVRON = '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" style="flex:none"><path d="M9 6l6 6-6 6" fill="none" stroke="#6C7086" stroke-width="2.2" stroke-linecap="round"/></svg>';

function versionText(app) { return app.version ? "Version " + app.version + (app.build ? " (" + app.build + ")" : "") : ""; }

// The last row of General: it opens the About page in place.
function aboutRow() {
  var shown = versionText(aboutApp());
  return '<button class="row" id="about" style="width:100%;text-align:left">' + ABOUT_ICON +
    '<span class="k" style="flex:1;width:auto"><b>About TilauScope</b><small>' + (shown ? esc(shown) + " · " : "") + "free software · the parts it is built with</small></span>" + CHEVRON + "</button>";
}

function renderAbout() {
  var app = aboutApp();
  var parts = BUILT_WITH.filter(function (p) { return app.platform in p.v; });
  $("main").innerHTML = '<div class="about">' +
    '<div class="about-side"><button id="about-back" class="about-back">‹ General</button>' +
    '<div class="about-id"><div class="about-logo"><svg width="34" height="34" viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="12" rx="6.5" ry="9" transform="rotate(-28 12 12)" fill="#94B87A"/>' +
    '<path d="M9 5.5c3 3 3 10 0 13" transform="rotate(-28 12 12)" stroke="#1E1E2E" stroke-width="1.6" fill="none"/></svg></div>' +
    "<div><b>TilauScope</b><small>" + esc(versionText(app)) + "</small></div></div>" +
    '<div class="panel about-free"><b>Free software</b><p>You may use, study, share and change TilauScope under the GNU Affero General Public License, version 3 or later. It comes with no warranty.</p>' +
    '<div class="about-btns"><button class="btn" id="about-own" style="color:var(--blue);border-color:transparent;background:rgba(137,180,250,.14)">Read the licence</button>' +
    '<button class="btn" id="about-source">Source code ↗</button></div></div>' +
    '<p class="about-note">© 2026 Tilau · Roast files use the format of Artisan Roaster Scope, so roasts move between the tablet and the desktop.</p></div>' +
    '<div class="about-parts"><b>Built with</b><p>Each part keeps its own licence. Tap one to read it.</p><div class="panel">' +
    parts.map(function (p, i) {
      var v = p.v[app.platform];
      return '<button class="row" data-part="' + i + '" style="width:100%;text-align:left"><span class="k" style="flex:1;width:auto"><b>' + esc(p.name + (v ? " " + v : "")) +
        "</b><small>" + esc(p.role + " · " + p.licence) + "</small></span>" + CHEVRON + "</button>";
    }).join("") + "</div></div></div>";
  $("about-back").onclick = function () { aboutOpen = false; render(); };
  $("about-own").onclick = function () { openLicence("TilauScope", "GNU Affero General Public License 3.0", "", OWN_LICENCE); };
  $("about-source").onclick = function () { send("open_source"); };
  $("main").querySelectorAll("[data-part]").forEach(function (b) {
    var p = parts[+b.dataset.part];
    b.onclick = function () { openLicence(p.name + (p.v[app.platform] ? " " + p.v[app.platform] : ""), p.licence, p.role, p.file); };
  });
}

// The licence in a sheet, its text when the app has read it; touching elsewhere closes it.
var licenceAsked = null;
function openLicence(title, licence, role, file) {
  licenceAsked = file;
  openSheet('<div class="lic-head"><h3>' + esc(title) + "</h3><span>" + esc(licence) + "</span></div>" +
    '<p class="lic-sub">' + (role ? esc(role) + ". " : "") + "Tap outside to close.</p>" +
    '<pre class="lic-text" id="lic-text">…</pre>', function () { licenceAsked = null; });
  send("licence", file);
}

window.onLicence = function (file, text) {
  if (file !== licenceAsked || !$("lic-text")) return;
  $("lic-text").textContent = text || "This licence text is missing from the app.";
};
