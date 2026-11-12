// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The Roasts tab, as the desktop's: roasts on two lines under day or coffee
// headings, the desktop's three sorts, the selected roast beside the list with the
// shared summary tiles, and the roast full screen. Read only, but for the roast label
// (label.js), printed from the printer icon at the end of the actions, and a roast
// deleted from the bin a swipe to the right shows.
"use strict";
var RoastsTab = (function () {
  var SORTS = [["recent", "Most recent"], ["oldest", "Oldest first"], ["coffee", "Coffee A–Z"]];
  var rows = [], sort = "recent", filter = null, query = "", selected = null, detail = null, box = null, onOpenCoffee = null;
  var labelPrinter = Label.printer(drawPrint, function (text) { toast(text); });

  function plainText(t) { return (t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  function key(r) { return r.origin + "/" + r.name; }
  function day(epoch) { return new Date(epoch * 1000).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }); }
  function time(epoch) { return new Date(epoch * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }); }

  function shown() {
    var q = plainText(query).trim();
    var list = rows.filter(function (r) {
      return (!filter || r.bean_uuid === filter.uuid) && (!q || plainText(r.title + " " + r.coffee).indexOf(q) >= 0);
    });
    list.sort(function (a, b) {
      if (sort === "oldest") return a.epoch - b.epoch;
      if (sort === "coffee") return a.coffee.localeCompare(b.coffee) || b.epoch - a.epoch;
      return b.epoch - a.epoch;
    });
    return list;
  }

  function tag(r) {
    if (r.simulated) return '<span class="tag sim">simulated · not used by plans</span>';
    if (r.excluded) return '<span class="tag exc">excluded from learning</span>';
    return r.origin === "computer" ? '<span class="tag pc">from the computer</span>' : '<span class="tag">this tablet</span>';
  }
  function dot(r) {
    if (!r.swatch) return '<span class="rdot ring" style="border-color:var(--muted)"></span>';
    return r.ground ? '<span class="rdot" style="background:' + r.swatch + '"></span>' : '<span class="rdot ring" style="border-color:' + r.swatch + '"></span>';
  }
  function row(r) {
    var byCoffee = sort === "coffee", w = r.weight_in_g > 0 ? Math.round(r.weight_in_g) + " g" : "";
    if (byCoffee && w && r.weight_out_g > 0) w += " → " + Math.round(r.weight_out_g) + " g";
    var first = byCoffee ? day(r.epoch) : r.title || r.coffee;
    var second = (byCoffee ? [r.process, w] : [r.process, r.crop || "", w]).filter(Boolean).join(" · ");
    return '<div class="rlane"><button class="rbin" aria-label="Delete the roast">' + BIN + "</button>" +
      '<button class="rr' + (key(r) === selected ? " sel" : "") + (r.simulated ? " rdim" : "") + '" data-k="' + esc(key(r)) + '">' + dot(r) +
      '<span class="rt"><span class="l1"><span>' + esc(first) + '</span><span class="w num">' + time(r.epoch) + '</span></span><span class="l2"><span>' +
      esc(second) + "</span>" + tag(r) + "</span></span></button></div>";
  }

  // A row swiped to the right shows the bin behind it; touching anywhere else closes it.
  var BIN = '<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4h6v3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var OPEN_PX = 84, opened = null;
  function closeSwipe() { if (opened) { opened.classList.remove("open"); opened.querySelector(".rr").style.transform = ""; opened = null; } }
  function swipe(lane) {
    var b = lane.querySelector(".rr"), start = null, dx = 0, moved = false;
    b.addEventListener("pointerdown", function (e) { start = { x: e.clientX, y: e.clientY }; dx = 0; moved = false; });
    b.addEventListener("pointermove", function (e) {
      if (!start) return;
      var x = e.clientX - start.x, y = e.clientY - start.y;
      if (!moved && (Math.abs(x) < 10 || Math.abs(x) < Math.abs(y))) return;
      if (!moved) { moved = true; if (opened !== lane) closeSwipe(); b.setPointerCapture(e.pointerId); lane.classList.add("open"); }
      dx = Math.max(0, Math.min(OPEN_PX, (lane === opened ? OPEN_PX : 0) + x));
      b.style.transition = "none"; b.style.transform = "translateX(" + dx + "px)";
    });
    b.addEventListener("pointerup", function () {
      if (!start) return;
      start = null; b.style.transition = "";
      if (!moved) return;
      if (dx > OPEN_PX / 2) { b.style.transform = "translateX(" + OPEN_PX + "px)"; opened = lane; } else { opened = lane; closeSwipe(); }
    });
    b.addEventListener("pointercancel", function () { start = null; b.style.transition = ""; if (opened !== lane) { lane.classList.remove("open"); b.style.transform = ""; } });
    b.addEventListener("click", function (e) { // the swipe's own release is not a touch on the row
      if (moved) { e.stopImmediatePropagation(); moved = false; return; }
      if (opened === lane) { e.stopImmediatePropagation(); closeSwipe(); }
    }, true);
    lane.querySelector(".rbin").onclick = function () { confirmDelete(rows.filter(function (r) { return key(r) === b.dataset.k; })[0]); };
  }
  document.addEventListener("pointerdown", function (e) { if (opened && !opened.contains(e.target)) closeSwipe(); }, true);

  // The bin asks first; touching outside the card keeps the roast.
  function confirmDelete(r) {
    if (!r) return;
    var el = document.createElement("div");
    el.className = "ce-scrim";
    el.innerHTML = '<div class="ecard rdel"><div class="rdh"><span class="rdi">' + BIN + '</span><span><b>Delete this roast?</b><small>' +
      esc((r.coffee || r.title) + " · " + day(r.epoch) + " · " + time(r.epoch)) + "</small></span></div>" +
      "<p>The roast file is removed from this tablet. The green stock does not change.</p>" +
      (r.origin === "computer" ? '<p class="rdn">For a roast from the computer: only this tablet\'s copy goes; the computer keeps its file.</p>' : "") +
      '<div class="rda"><button class="rdgo" id="rdgo">' + BIN + "Delete</button></div></div>";
    el.onclick = function (e) { if (e.target === el) el.remove(); };
    document.body.appendChild(el);
    $("rdgo").onclick = function () {
      el.remove(); opened = null;
      if (key(r) === selected) { selected = null; $("rdetail").innerHTML = ""; }
      send("delete_roast", JSON.stringify({ origin: r.origin, name: r.name }));
    };
  }

  function renderList() {
    var list = shown(), html = "", head = null;
    var counts = {};
    if (sort === "coffee") list.forEach(function (r) { counts[r.coffee] = (counts[r.coffee] || 0) + 1; });
    list.forEach(function (r) {
      var h = sort === "coffee" ? r.coffee : day(r.epoch);
      if (h !== head) { head = h; html += '<div class="gh">' + esc(h) + (sort === "coffee" ? "<small>" + counts[h] + "</small>" : "") + "</div>"; }
      html += row(r);
    });
    $("rlist").innerHTML = html || '<div class="none">' + (rows.length ? "No roast matches" : "No roast on this tablet yet. Roasts saved after a roast, and those imported from the computer in Settings › BeanCave, show here.") + "</div>";
    opened = null;
    $("rlist").querySelectorAll(".rr").forEach(function (b) { b.onclick = function () { select(b.dataset.k); }; });
    $("rlist").querySelectorAll(".rlane").forEach(swipe);
    $("rsorts").innerHTML = SORTS.map(function (s) { return '<button data-s="' + s[0] + '"' + (s[0] === sort ? ' class="on"' : "") + ">" + s[1] + (s[0] === sort ? " ↓" : "") + "</button>"; }).join("");
    $("rsorts").querySelectorAll("button").forEach(function (b) { b.onclick = function () { sort = b.dataset.s; remember(); renderList(); }; });
    $("rfilter").innerHTML = filter ? '<button class="filt" id="rclear">' + esc(filter.name) + ' ✕</button><span class="sb">' + list.length + " roasts</span>" : "";
    if ($("rclear")) $("rclear").onclick = function () { filter = null; renderList(); };
    if (!selected && list.length) select(key(list[0]));
  }
  function remember() { try { localStorage.setItem("roastSort", sort); } catch (e) { /* the sort is a convenience */ } }

  function select(k) {
    selected = k; detail = null;
    $("rlist").querySelectorAll(".rr").forEach(function (b) { b.classList.toggle("sel", b.dataset.k === k); });
    var i = k.indexOf("/");
    send("get_roast", JSON.stringify({ origin: k.slice(0, i), name: k.slice(i + 1) }));
    $("rdetail").innerHTML = '<div class="none">Reading the roast…</div>';
  }

  // ---------- one roast ----------
  function tiles(d) {
    return '<div class="tiles">' + d.tiles.map(function (t) {
      var sw = t.swatch ? '<i class="' + (t.filled ? "" : "ring") + '" style="background:' + t.swatch + ";border-color:" + t.swatch + '"></i>' : "";
      if (t.caption === "Energy" && t.value !== "—") // the roast's energy: the tile opens its sheet, as the desktop's ›
        return '<button class="tile etap" aria-label="Energy of the roast"><span class="cap">' + esc(t.caption) +
          '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span>' +
          '<span class="val num">' + esc(t.value.replace(" kWh", "")) + '<small>kWh</small></span><span class="sub">' + esc(t.sub) + "</span></button>";
      return '<div class="tile' + (t.value === "—" ? " nr" : "") + '"><span class="cap">' + esc(t.caption) + '</span><span class="val num">' + sw + esc(t.value) +
        '</span><span class="sub">' + esc(t.sub) + "</span></div>";
    }).join("") + "</div>";
  }
  document.addEventListener("click", function (e) {
    if (!selected || !e.target.closest || !e.target.closest(".etap")) return;
    var i = selected.indexOf("/");
    send("get_roast_energy", JSON.stringify({ origin: selected.slice(0, i), name: selected.slice(i + 1) }));
  });
  function curve(d, W, H) {
    var c = d.colours, pts = d.curve, end = Math.max(60, (d.marks.drop || (pts.length ? pts[pts.length - 1][0] : 600)) + 60);
    var levers = Object.keys(d.lanes).filter(function (k) { return c.levers[k]; }), laneH = 30, gap = 6;
    var L = 40, R = 40, T = 54, B = 22 + levers.length * (laneH + gap), pw = W - L - R, ph = H - T - B; // two rows of chips above
    function X(t) { return L + Math.max(0, t) / end * pw; }
    function Y(v) { return T + (1 - (v - 50) / 200) * ph; }
    function RY(r) { return T + (1 - r / 25) * ph; }
    var svg = "", bt = "", et = "", ror = "";
    // The curve is °C; its ticks are round values of the unit shown
    (UNIT === "F" ? [200, 300, 400] : [100, 150, 200, 250]).forEach(function (v) { var y = Y(typedT(v)); svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" stroke="#313244"/><text x="' + (L - 6) + '" y="' + (y + 4) + '" text-anchor="end" font-size="11" fill="#6C7086">' + v + "</text>"; });
    (UNIT === "F" ? [10, 20, 30, 40] : [5, 10, 15, 20, 25]).forEach(function (r) { svg += '<text x="' + (W - R + 6) + '" y="' + (RY(r / shownD(1)) + 4) + '" font-size="11" fill="' + c.grain_rise + '">' + r + "</text>"; }); // RoR scale, per minute
    for (var m = 0; m <= end; m += 120) svg += '<text x="' + X(m) + '" y="' + (T + ph + 15) + '" text-anchor="middle" font-size="11" fill="#6C7086">' + Math.floor(m / 60) + ":" + ("0" + m % 60).slice(-2) + "</text>";
    var bands = [["charge", "dry_end", "rgba(137,220,235,.07)"], ["dry_end", "first_crack", "rgba(249,226,175,.07)"], ["first_crack", "drop", "rgba(243,139,168,.08)"]];
    bands.forEach(function (b) { if (d.marks[b[0]] != null && d.marks[b[1]] != null) svg += '<rect x="' + X(d.marks[b[0]]) + '" y="' + T + '" width="' + (X(d.marks[b[1]]) - X(d.marks[b[0]])) + '" height="' + ph + '" fill="' + b[2] + '"/>'; });
    pts.forEach(function (p) {
      if (p[0] < 0 || p[0] > end) return;
      if (p[1] != null) bt += (bt ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1);
      if (p[2] != null) et += (et ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[2]).toFixed(1);
    });
    // Rate of rise for the picture only: the bean temperature over the last 30 s, from the turning point to the drop
    for (var i = 0, j = 0; i < pts.length; i++) {
      while (j < i && pts[i][0] - pts[j][0] > 30) j++;
      if (pts[i][0] < 60 || (d.marks.drop != null && pts[i][0] > d.marks.drop) || pts[i][1] == null || pts[j][1] == null || pts[i][0] - pts[j][0] < 20) continue;
      var r = (pts[i][1] - pts[j][1]) / (pts[i][0] - pts[j][0]) * 60;
      if (r < 0 || r > 30) continue;
      ror += (ror ? "L" : "M") + X(pts[i][0]).toFixed(1) + " " + RY(r).toFixed(1);
    }
    var points = (d.points || []).filter(function (p) { return p.t >= 0 && p.t <= end; });
    points.forEach(function (p) { // the turning point dotted: computed, not marked
      svg += '<line x1="' + X(p.t) + '" x2="' + X(p.t) + '" y1="' + (T - 4) + '" y2="' + (T + ph) + '" stroke="' + (p.key === "tp" ? "#A6ADC8" : "#7F849C") +
        '" stroke-dasharray="' + (p.key === "tp" ? "1.5 3" : "4 3") + '"/>';
    });
    svg += '<path d="' + ror + '" fill="none" stroke="' + c.grain_rise + '" stroke-width="1.8"/><path d="' + et + '" fill="none" stroke="' + c.air + '" stroke-width="1.8" opacity=".85"/>' +
      '<path d="' + bt + '" fill="none" stroke="' + c.grain + '" stroke-width="3"/>' + milestoneChips(points, X, Y, L, W - R, T, c);
    levers.forEach(function (k, n) {
      var top = T + ph + 22 + n * (laneH + gap), steps = d.lanes[k].slice().sort(function (a, b) { return a[0] - b[0]; }), held = null, path = "";
      steps.forEach(function (s) { if (s[0] <= 0) held = s[1]; });
      var seq = (held != null ? [[0, held]] : []).concat(steps.filter(function (s) { return s[0] > 0 && s[0] <= end; }));
      seq.forEach(function (s, i) { var y = top + laneH - s[1] / 100 * laneH; path += (i ? " H" + X(s[0]).toFixed(1) + " V" : "M" + X(s[0]).toFixed(1) + " ") + y.toFixed(1); });
      if (seq.length) path += " H" + X(d.marks.drop != null ? d.marks.drop : end).toFixed(1);
      svg += '<rect x="' + L + '" y="' + top + '" width="' + pw + '" height="' + laneH + '" rx="6" fill="#1E1E2E"/><path d="' + path + '" fill="none" stroke="' + c.levers[k] + '" stroke-width="1.8"/>' +
        '<text x="' + (L + 6) + '" y="' + (top + 11) + '" font-size="10" font-weight="700" fill="' + c.levers[k] + '">' + k.toUpperCase() + "</text>";
    });
    return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">' + svg + "</svg>";
  }
  // As the desktop's curve: a dot where each milestone happened, and a chip naming it with its bean temperature
  // and time; chips that would overlap take the second row, then give up their time, then their temperature.
  var MILESTONE_NAMES = { charge: "CHARGE", tp: "TP", dry_end: "DRY END", first_crack: "FIRST CRACK", drop: "DROP" };
  function milestoneChips(points, X, Y, left, right, T, c) {
    var svg = "", rows = [left - 1, left - 1];
    points.forEach(function (p) {
      var name = MILESTONE_NAMES[p.key], reading = Math.round(shownT(p.bt)) + " " + deg();
      var s = Math.round(p.t), clock = Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2), placed = null;
      [name + "  " + reading + "  " + clock, name + "  " + reading, name].some(function (text) {
        var w = text.length * 6.6 + 18, x = X(p.t) + 3;
        if (x + w > right) x = X(p.t) - 3 - w; // near the right edge the chip hangs left
        for (var row = 0; row < 2; row++) if (x > rows[row] + 3) { placed = { text: text, w: w, x: x, row: row }; return true; }
        return false;
      });
      if (!placed) placed = { text: name, w: name.length * 6.6 + 18, x: X(p.t) + 3, row: rows[0] <= rows[1] ? 0 : 1 };
      rows[placed.row] = placed.x + placed.w;
      var y = 4 + placed.row * 24;
      svg += '<rect x="' + placed.x.toFixed(1) + '" y="' + y + '" width="' + placed.w.toFixed(1) + '" height="20" rx="10" fill="#313244"/>' +
        '<text x="' + (placed.x + 9).toFixed(1) + '" y="' + (y + 14) + '" font-size="11" font-weight="700" fill="#CDD6F4" xml:space="preserve">' + esc(placed.text) + "</text>";
      var cy = Y(p.bt);
      if (cy >= T && cy <= T + (Y(50) - T))
        svg += '<circle cx="' + X(p.t).toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="6" fill="#11111B"/><circle cx="' + X(p.t).toFixed(1) + '" cy="' + cy.toFixed(1) +
          '" r="4" fill="' + (p.key === "tp" ? "#A6ADC8" : c.grain) + '"/>';
    });
    return svg;
  }
  function when(d) { return d.epoch ? day(d.epoch) + " · " + time(d.epoch) : ""; }
  // The tasting, as the desktop recalls it above a roast; red when it found a defect.
  function tasted(d) {
    return d.tasted ? ' · <span style="color:' + (d.defects.length ? "var(--red)" : "var(--green)") + '">Tasted: ' + esc(d.tasted) + "</span>" : "";
  }
  function actions(d) {
    var hasCoffee = d.bean_uuid && onOpenCoffee && onOpenCoffee(d.bean_uuid, true);
    return '<div class="acts">' + (hasCoffee ? '<button class="btn" id="rcoffee">Open the coffee</button>' : "") +
      (!d.tasting && d.roast_uuid ? '<button class="btn" id="rtaste">Taste</button>' : "") +
      '<button class="rsim" id="rsim" aria-label="Replay as a simulation"><svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M10 9l5 3-5 3z" fill="currentColor"/></svg></button>' +
      '<button class="rfollow" id="rfollow" aria-label="Follow this roast"><svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>' +
      (printable(d) ? '<button class="rprint" id="rprint" aria-label="Print label"><svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">' +
        '<path id="rprinticon" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>' : "") +
      '<button class="rshare" id="rshare" aria-label="Share the roast"><svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5" r="2.6" fill="none" stroke="currentColor" stroke-width="2"/>' +
      '<circle cx="6" cy="12" r="2.6" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="18" cy="19" r="2.6" fill="none" stroke="currentColor" stroke-width="2"/>' +
      '<path d="M8.3 10.8l7.4-4.4M8.3 13.2l7.4 4.4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></div>';
  }
  // A label needs the roast's coffee in the BeanCave and a label printer in the devices.
  function printable(d) { return !!(d.coffee && labelPrinter.device); }
  // Grey until the printer is found, then what it is doing.
  function drawPrint() {
    if (!$("rprint")) return;
    var icon = labelPrinter.icon(true);
    $("rprint").classList.toggle("working", icon.working);
    $("rprint").style.borderColor = icon.colour;
    $("rprint").style.background = icon.colour + "1f";
    $("rprinticon").setAttribute("stroke", icon.colour);
    $("rprinticon").setAttribute("d", icon.path);
  }
  // The desktop's banner above a tasted roast: what was tasted, and Edit.
  function banner(d) {
    if (!d.tasting) return "";
    // The whole banner opens the tasting: a touch screen needs no Edit button.
    return '<button class="tban" id="rtaste"><span>Tasted: <b style="color:' + (d.defects.length ? "var(--red)" : "var(--green)") + '">' + esc(d.tasted) +
      '</b></span><span style="flex:1"></span>' + (d.is_reference ? '<span class="tstar">★ Reference</span>' : "") + '<span class="tchev">›</span></button>';
  }
  // The desktop's tasting form: verdict, what was off, notes, what the next roast changes; the reference star on a Yes.
  function tasteSheet(d) {
    var w = d.words, t = d.tasting || { verdict: "", defects: [], notes: "" };
    var st = { verdict: t.verdict, defects: t.defects.slice(), star: d.is_reference, confirm: false };
    var el = document.createElement("div");
    el.className = "ce-scrim";
    el.onclick = function (e) { if (e.target === el) el.remove(); }; // touching outside closes
    document.body.appendChild(el);
    function next() {
      var hit = w.defects.filter(function (x) { return st.defects.indexOf(x[0]) >= 0; })[0];
      if (hit) return [hit[2], hit[3]];
      if (st.verdict === "yes") return w.same;
      return st.verdict ? w.tick : null;
    }
    function render() {
      var nx = next(), starShown = d.bean_uuid && (st.verdict === "yes" || d.is_reference);
      el.innerHTML = '<div class="tsheet"><h3>Tasting</h3><span class="tsub">' + esc([d.coffee || d.title, d.epoch ? "Roasted " + day(d.epoch) : "",
          d.rest_days != null ? d.rest_days + " days of rest" : ""].filter(Boolean).join(" · ")) + "</span>" +
        '<span class="tq">Would you roast it the same way again?</span><div class="tvrow">' + w.verdicts.map(function (v) {
          return '<button class="tvb' + (st.verdict === v[0] ? " on" : "") + '" data-v="' + v[0] + '">' + esc(v[1]) + "</button>"; }).join("") +
        (starShown ? '<button class="tstarb' + (st.star ? " on" : "") + '" id="tstar" aria-label="' + (st.star ? "Reference roast" : "Make it the reference roast") + '">' + (st.star ? "★" : "☆") + "</button>" : "") + "</div>" +
        '<span class="tq">What was off?<small>optional</small></span><div class="tdgrid">' + w.defects.map(function (x) {
          return '<button class="tdb' + (st.defects.indexOf(x[0]) >= 0 ? " on" : "") + '" data-d="' + x[0] + '">' + esc(x[1]) + "</button>"; }).join("") + "</div>" +
        '<textarea id="tnotes" class="tnotes" placeholder="Notes — e.g. lovely body, fruit fades fast">' + esc(t.notes) + "</textarea>" +
        (nx ? '<div class="tnext"><span>NEXT TIME</span><b>' + esc(nx[0]) + "</b><small>" + esc(nx[1]) + "</small></div>" : "") +
        (st.confirm ? '<div class="tconfirm">Replace the reference roast with this one?<span style="flex:1"></span><button class="btn" id="tno">Keep the ★ one</button><button class="btn pri" id="tyes">Replace</button></div>'
          : '<div class="tacts"><button class="btn pri" id="tsave">✓ Save</button></div>') + "</div>";
      el.querySelectorAll("[data-v]").forEach(function (b) { b.onclick = function () { keepNotes(); st.verdict = st.verdict === b.dataset.v ? "" : b.dataset.v; render(); }; });
      el.querySelectorAll("[data-d]").forEach(function (b) { b.onclick = function () {
        keepNotes(); var i = st.defects.indexOf(b.dataset.d); if (i >= 0) st.defects.splice(i, 1); else st.defects.push(b.dataset.d); render(); }; });
      if ($("tstar")) $("tstar").onclick = function () { keepNotes(); st.star = !st.star; render(); };
      if ($("tsave")) $("tsave").onclick = function () {
        keepNotes();
        if (starShown && st.star && d.has_reference && !d.is_reference) { st.confirm = true; render(); return; }
        save(starShown);
      };
      if ($("tno")) $("tno").onclick = function () { st.star = false; save(true); }; // saved, the reference stays
      if ($("tyes")) $("tyes").onclick = function () { save(true); };
    }
    function keepNotes() { if ($("tnotes")) t.notes = $("tnotes").value; }
    function save(starShown) {
      send("save_tasting", JSON.stringify({ origin: d.origin, name: d.name, verdict: st.verdict, defects: st.defects,
        notes: t.notes, reference: starShown ? st.star : null }));
      el.remove();
    }
    render();
  }
  function wireActions(d) {
    if ($("rtaste")) $("rtaste").onclick = function () { tasteSheet(d); };
    if ($("rcoffee")) $("rcoffee").onclick = function () { closeFull(); onOpenCoffee(d.bean_uuid); };
    $("rshare").onclick = function () { send("roast_share", d.origin + "/" + d.name); };
    $("rsim").onclick = function () { send("simulate", JSON.stringify({ origin: d.origin, name: d.name })); };
    $("rfollow").onclick = function () { send("set_follow", JSON.stringify({ origin: d.origin, name: d.name })); };
    if ($("rprint")) $("rprint").onclick = function () {
      if (labelPrinter.start()) send("roast_label", JSON.stringify({ origin: d.origin, name: d.name }));
    };
  }
  function showDetail(d) {
    detail = d;
    $("rdetail").innerHTML = '<div><h3>' + esc(d.title) + '</h3><span class="when num">' + esc(when(d)) + "</span></div>" + banner(d) +
      '<div class="mini">' + curve(d, 760, 330) + "</div>" + tiles(d) + actions(d);
    wireActions(d);
    doubleTap($("rdetail").querySelector(".mini"), function () { full(d); }); // the curve opens full screen
    if (labelPrinter.state !== "working") labelPrinter.state = null; // "printed" was another roast's label
    labelPrinter.watch(printable(d));
    drawPrint();
  }
  function full(d) {
    box = document.createElement("div");
    box.id = "rview";
    box.innerHTML = '<header><button class="back" id="rback">‹ Roasts</button><span class="brand">' + esc(d.title) + '</span><span class="sb num">' + esc(when(d)) + tasted(d) +
      '</span><span style="flex:1"></span></header><div class="rvbody"><div class="mini big">' + curve(d, 1160, 470) + "</div>" + tiles(d) + "</div>";
    document.body.appendChild(box);
    $("rback").onclick = closeFull;
    doubleTap(box.querySelector(".mini"), closeFull); // and closes it the same way
  }
  // Two taps close in time and place, as a tablet zooms in and out.
  function doubleTap(el, run) {
    var last = null;
    el.addEventListener("pointerup", function (e) {
      if (last && e.timeStamp - last.t < 350 && Math.abs(e.clientX - last.x) < 40 && Math.abs(e.clientY - last.y) < 40) { last = null; run(); return; }
      last = { t: e.timeStamp, x: e.clientX, y: e.clientY };
    });
  }
  function closeFull() { if (box) { box.remove(); box = null; } }

  return {
    init: function (openCoffee) {
      onOpenCoffee = openCoffee;
      try { sort = localStorage.getItem("roastSort") || "recent"; } catch (e) { sort = "recent"; }
      $("rsearch").oninput = function () { query = this.value; renderList(); };
    },
    show: function (coffee) { filter = coffee || null; selected = null; send("get_roasts"); },
    hide: function () { labelPrinter.watch(false); },
    setPrinter: function (device) { labelPrinter.device = device && device.enabled ? device : null; },
    label: function (lines) { labelPrinter.print(lines); },
    rows: function (list) { rows = list; renderList(); },
    roast: function (d) { if (d && d.origin + "/" + d.name === selected) showDetail(d); else if (!d) $("rdetail").innerHTML = '<div class="none">This roast could not be read.</div>'; }
  };
})();
