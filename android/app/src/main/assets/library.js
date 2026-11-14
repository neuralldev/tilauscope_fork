// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// BeanCave › Library, and the sheet a .tilaucoffee opens on (a file from another app, or a coffee of the library).
// The pages never name a path: the app keeps the file it staged, the page only asks to preview or import it.
"use strict";
var LibraryTab = (function () {
  var ICON = {
    down: '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 20h14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    send: '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l16-7-6 16-3-7-7-2z" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/></svg>',
    warn: '<svg width="30" height="30" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4l9 16H3z" fill="none" stroke="#F9E2AF" stroke-width="2" stroke-linejoin="round"/><path d="M12 10v5m0 2.5v.5" stroke="#F9E2AF" stroke-width="2.2" stroke-linecap="round"/></svg>',
    machine: '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 4.5v15M4.5 12h15" stroke="currentColor" stroke-width="1.4"/></svg>'
  };
  // Their tasting in the desktop's words (library_tab.verdict_sentence)
  var VERDICT = { yes: "Liked it · would roast it the same way", almost: "Almost · would change a little", no: "Did not like it · would roast it differently" };
  var grain = "var(--text)"; // the bean temperature colour of the roast screen (the shared display colours), set once Settings answers
  var phase = "idle";          // idle, loading, ready, error
  var failure = "";            // the library's error kind, when phase is error
  var cards = [], total = 0, machine = "", selected = null, getting = null, mine = false; // My machine: off until the operator turns it on
  var next = "", more = "";    // the relay's cursor to the page after the last one shown; more: "", loading, failed
  var seq = 0, waiting = 0, appending = false, typed = null; // the page call awaited (older replies are dropped), the search's debounce
  var roastOf = {}, failed = {}, asked = []; // a card's roast as the Roasts tab draws it, its last failure, the cards being read
  var theirs = {};             // a coffee's shared roast by uuid, asked once
  var seen = null;             // the sheet on screen, for its Import

  function mmss(s) { return Math.floor(s / 60) + ":" + ("0" + Math.round(s % 60)).slice(-2); }
  function dayOf(iso) {
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short" }).toUpperCase();
  }

  // The roast curve of a card: bean temperature CHARGE to DROP, first crack dashed.
  function curve(c, w, h) {
    var lo = 80, hi = 210, pad = 8;
    c.curve.forEach(function (p) { lo = Math.min(lo, p[1] - 5); hi = Math.max(hi, p[1] + 5); });
    var pts = c.curve.map(function (p) {
      return (pad + p[0] / c.total_s * (w - 2 * pad)).toFixed(1) + "," + (h - pad - (p[1] - lo) / (hi - lo) * (h - 2 * pad)).toFixed(1);
    }).join(" ");
    var fx = pad + (c.total_s - c.after_fc_s) / c.total_s * (w - 2 * pad);
    return '<svg class="curve" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="Roast curve of ' + esc(c.name) + '">' +
      (c.after_fc_s > 0 ? '<line x1="' + fx.toFixed(1) + '" y1="' + pad + '" x2="' + fx.toFixed(1) + '" y2="' + (h - pad) + '" style="stroke:var(--line)" stroke-width="1" stroke-dasharray="3 4"/>' : "") +
      '<polyline points="' + pts + '" fill="none" style="stroke:' + grain + '" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/></svg>';
  }
  function tiles(c) {
    return '<div class="tl num" style="grid-template-columns:repeat(4,minmax(0,1fr))">' + tile(c.batch_g + " g", "Batch") + tile(mmss(c.total_s), "Roast") +
      tile(c.after_fc_s > 0 ? mmss(c.after_fc_s) : "—", "After first crack") + tile(Math.round(shownT(c.drop_c)) + " " + deg(), "Drop") + "</div>";
  }
  // As the desktop's: another machine is a curve to read, not to copy.
  function machineLine(c) {
    if (!c.roaster) return "";
    var name = esc(c.roaster_name || c.roaster);
    if (c.other_machine) return '<div class="mach other">' + ICON.machine + "<span>Roasted on a " + name + ". Use it as a curve to read, not to copy.</span></div>";
    return '<div class="mach">' + ICON.machine + "<span>Roasted on a " + name + (c.same_machine ? ", like yours" : "") + "</span></div>";
  }
  function roastDay(iso) { // the operator's short date; the day as written, whatever the time zone
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
  }
  function where(c) { return [c.country, c.process, c.crop ? "crop " + c.crop : ""].filter(Boolean).join(" · "); }
  function chipsOf(list) { return list.length ? '<div class="chips">' + list.map(function (f) { return "<span>" + esc(f) + "</span>"; }).join("") + "</div>" : ""; }

  // ── the sheet ──────────────────────────────────────────────────────────────
  function closeSheet(dismiss) {
    var s = $("cs");
    if (s) s.remove();
    if (dismiss && seen) send("coffee_dismiss");
    seen = null;
  }
  function openSheet(inner) {
    closeSheet(false);
    var s = document.createElement("div");
    s.id = "cs"; s.className = "ce-scrim";
    s.innerHTML = inner;
    s.onclick = function (e) { if (e.target === s) closeSheet(true); }; // touching elsewhere closes it: no X
    document.body.appendChild(s);
  }
  function sheet(r) {
    if (!r || r.state !== "ok") { // damaged, or written by a newer TilauScope
      var newer = r && r.state === "newer";
      openSheet('<div class="tsheet" style="align-items:center;text-align:center;gap:16px;padding:30px 36px">' + ICON.warn +
        "<h3>" + (newer ? "This file needs a newer TilauScope" : "This file cannot be read") + "</h3>" +
        "<p class=\"sb\" style=\"font-size:15px\">" + (newer ? "Update the app, then open the file again." : "It is damaged or incomplete. Nothing was changed.") + "</p>" +
        (newer ? "" : '<p class="sb" style="font-size:15px">Ask the roaster to send it again.</p>') + "</div>");
      seen = {}; // a staged file to drop when the sheet is closed
      return;
    }
    var c = r.card, computer = r.owner === "computer";
    var counts = [r.roasts + (r.roasts === 1 ? " roast" : " roasts")];
    if (r.tastings) counts.push(r.tastings === 1 ? "Its tasting" : r.tastings + " tastings");
    if (r.settings) counts.push(r.settings + (r.settings === 1 ? " brew setting" : " brew settings"));
    openSheet('<div class="tsheet" role="dialog" aria-label="' + esc(r.name) + '"><h3>' + esc(r.name) + ' <span class="blendtag">' + (r.mode === "move" ? "MOVED" : "SHARED") + "</span></h3>" +
      '<div class="sb" style="font-size:15px">' + esc(where(r)) + "</div>" + (c ? curve(c, 590, 150) + tiles(c) + machineLine(c) : "") +
      chipsOf(counts) +
      (computer ? '<div class="mach other">On this tablet only: the next exchange with your computer removes it.</div>' : "") +
      '<div class="tacts" style="justify-content:space-between">' +
      (computer ? '<button class="btn ico" id="cs-send">' + ICON.send + "Send the file to the computer</button>" : '<span class="sb" style="font-size:15px">Nothing on this tablet is replaced.</span>') +
      '<button class="go ico" id="cs-import">' + ICON.down + "Import</button></div>" +
      "</div>");
    seen = r;
    $("cs-import").onclick = function () { this.disabled = true; send("coffee_import"); };
    if ($("cs-send")) $("cs-send").onclick = function () { send("coffee_file_send"); };
  }

  // ── a coffee that came with a roast: the zone THEIR ROAST of its sheet ──────
  function theirsZone(c) {
    var t = theirs[c.uuid];
    if (!t) { theirs[c.uuid] = { asked: true }; send("coffee_theirs", c.uuid); }
    var card = t && t.card;
    return '<div class="zone acc" id="theirs"><div class="zh acc">THEIR ROAST</div>' +
      (card ? curve(card, 700, 190) + tiles(card) + machineLine(card) : '<span class="dim">' + (t && !t.asked ? "Their roast cannot be read" : "Reading their roast…") + "</span>") + "</div>";
  }
  function theirsDay(c) { var t = theirs[c.uuid]; return t && t.shared_on ? " " + dayOf(t.shared_on) : ""; }
  function theirsArrived(r) { if (r && r.uuid) theirs[r.uuid] = r; }
  function forgetTheirs() { theirs = {}; }

  // ── the Library tab ────────────────────────────────────────────────────────
  // A page of the relay's search: the first one replaces the list, a cursor's is added below it.
  function ask(cursor) {
    waiting = ++seq; appending = !!cursor;
    send("library_page", JSON.stringify({ text: $("lb-search").value, mine: mine, cursor: cursor, seq: seq }));
  }
  function first() { phase = "loading"; draw(); ask(""); }
  function search() { clearTimeout(typed); more = ""; ask(""); }
  function loadMore() {
    if (phase !== "ready" || !next || waiting) return;
    more = "loading"; ask(next); draw();
  }
  function nearEnd() { var r = $("lb-rows"); return r.scrollHeight > 0 && r.scrollTop + r.clientHeight >= r.scrollHeight - 240; }
  function pick() { return cards.filter(function (c) { return c.id === selected; })[0]; }

  function state(title, text, retry) {
    $("lb-browse").classList.add("hidden");
    $("lb-state").classList.remove("hidden");
    $("lb-state").innerHTML = '<div class="empty"><b' + (phase === "loading" ? ' class="pulse"' : "") + ">" + title + "</b>" + (text ? "<p>" + text + "</p>" : "") +
      (retry ? '<button class="btn" id="lb-retry">Try again</button>' : "") + "</div>";
    if (retry) $("lb-retry").onclick = first;
  }

  // The desktop's sentences for a roast card that could not be loaded (library_tab.failure_sentence, "card").
  function cardFailure(kind) {
    if (kind === "offline") return "The roast card could not be loaded: the library cannot be reached. Check the internet connection, then select the roast again.";
    if (kind === "unknown") return "The roast card could not be loaded: its author withdrew this roast from the library.";
    return "The roast card could not be loaded. Select the roast again to try once more.";
  }
  function row(c) {
    return '<button class="lb-row' + (c.id === selected ? " sel" : "") + '" data-id="' + esc(c.id) + '"><span class="l1"><b>' + esc(c.name) + '</b><span class="d">' +
      esc(roastDay(c.roasted)) + '</span></span><span class="l2">' + esc([c.country, c.process].filter(Boolean).join(" · ")) + '</span><span class="l3">' +
      esc(c.roaster_name || c.roaster || "") + "</span></button>";
  }
  // The selected card's roast: the Roasts tab's own picture once its package is read, a sentence until then or in its place.
  function roastZone(c) {
    var d = roastOf[c.id];
    if (d) return '<div class="mini">' + RoastsTab.curve(d, 760, 330) + "</div>" + RoastsTab.tiles(d);
    if (failed[c.id]) return '<div class="mini lb-msg">' + esc(cardFailure(failed[c.id])) + "</div>";
    if (asked.indexOf(c.id) < 0) { asked.push(c.id); send("library_card", c.id); }
    return '<div class="mini lb-msg">Loading the roast card…</div>';
  }
  function detail(c) {
    var verdict = VERDICT[c.verdict];
    $("lb-side").innerHTML = '<div><h3>' + esc(c.name) + '</h3><span class="when">' + esc([c.country, c.process, roastDay(c.roasted)].filter(Boolean).join(" · ")) + "</span></div>" +
      roastZone(c) + '<div class="lb-bar"><div class="lb-said"><div class="zh">THEIR TASTING</div>' +
      '<div class="lb-verdict' + (verdict ? "" : " not") + '">' + (verdict || "Not tasted") + "</div>" + chipsOf(c.flavours) + "</div>" +
      '<button class="go ico" id="lb-import"' + (getting ? " disabled" : "") + ">" + ICON.down + "Import this coffee</button></div>" + machineLine(c);
    $("lb-import").onclick = function () { getting = c.id; draw(); send("library_get", c.id); };
  }

  function draw() {
    if (phase === "loading") { state("Loading the library…"); return; }
    if (phase === "error") {
      if (failure === "offline") state("The library cannot be reached", "Check the internet connection. Your own coffees and roasts are not affected.", true);
      else state("The library cannot answer now", "Try again in a few minutes. Your own coffees and roasts are not affected.", true);
      return;
    }
    if (phase !== "ready") return;
    $("lb-state").classList.add("hidden");
    $("lb-browse").classList.remove("hidden");
    var chip = $("lb-mine"), on = mine && !!machine;
    chip.classList.toggle("on", on);
    chip.setAttribute("aria-pressed", String(on));
    chip.disabled = !machine; // no machine set in Settings: nothing to match
    $("lb-count").textContent = total === 1 ? "1 roast · newest first" : total + " roasts · newest first";
    var rows = $("lb-rows"), top = rows.scrollTop;
    if (!cards.length) {
      rows.innerHTML = "";
      $("lb-side").innerHTML = $("lb-search").value.trim() || on ? '<div class="empty"><b>No coffee matches</b><p>Clear the search, or turn off My machine.</p></div>'
        : '<div class="empty"><b>No roast in the library yet</b></div>';
      return;
    }
    rows.innerHTML = cards.map(row).join("") + (more === "loading" ? '<div class="lb-more" id="lb-more">Loading more…</div>' :
      more === "failed" ? '<button class="lb-more" id="lb-more">Could not load more. Touch to try again.</button>' : "");
    rows.scrollTop = top;
    rows.querySelectorAll(".lb-row").forEach(function (b) {
      b.onclick = function () { selected = b.dataset.id; delete failed[selected]; draw(); }; // touching the row again after a failure retries
    });
    if (more === "failed") $("lb-more").onclick = loadMore;
    detail(pick());
  }

    function setColours(c) { if (c && c.grain) { grain = c.grain; if (phase === "ready") draw(); } }

  // Nothing of the library is asked before the tab is first shown; then its first page, once (Try again asks it again).
  function show() { if (phase === "idle") first(); }

  function reply(method, r) {
    if (method === "library_page") {
      if (r ? r.seq !== waiting : !waiting) return; // a page asked before the search changed (no answer at all: the one awaited)
      waiting = 0;
      if (!r || r.error) {
        if (appending) more = "failed"; // said in the list's last row: the roasts shown stay
        else { phase = "error"; failure = r && r.error || "unknown"; }
        draw();
        return;
      }
      if (!appending) { cards = []; $("lb-rows").scrollTop = 0; }
      cards = cards.concat(r.cards); total = r.total; next = r.next || ""; machine = r.machine; more = ""; phase = "ready";
      if (!pick()) selected = cards.length ? cards[0].id : null;
      draw();
      if (nearEnd()) loadMore(); // a page that does not fill the list: the next one at once
    } else if (method === "library_card") { // kept whichever roast is selected now, drawn only when it still is
      var id = r && r.id || asked[0]; // no answer at all: the oldest call, the app runs them in turn
      asked = asked.filter(function (a) { return a !== id; });
      if (r && r.detail) roastOf[id] = r.detail; else failed[id] = r && r.error || "local";
      if (id === selected && phase === "ready") draw();
    } else if (method === "library_get") {
      getting = null; draw();
      if (r && r.path) { send("coffee_opened"); return; }
      toast(!r ? "This coffee could not be downloaded" : r.error === "offline" ? "No connection: the coffee was not downloaded" :
        r.error === "unknown" ? "This coffee is no longer in the library" : "This coffee could not be downloaded");
    }
  }

  function init() {
    $("lb-search").oninput = function () { clearTimeout(typed); if (phase === "ready") typed = setTimeout(search, 400); };
    $("lb-mine").onclick = function () { mine = !mine; if (phase === "ready") search(); };
    $("lb-rows").onscroll = function () { if (nearEnd()) loadMore(); };
  }

  return { setColours: setColours, init: init, show: show, reply: reply, sheet: sheet, closeSheet: closeSheet, theirsZone: theirsZone, theirsDay: theirsDay,
           theirsArrived: theirsArrived, forgetTheirs: forgetTheirs, ICON: ICON };
})();
