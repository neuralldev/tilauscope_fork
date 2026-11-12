// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// Settings › Alarms (ALARM-SPEC C3): the lists, and the editor of one list. Each alarm is the
// desktop's rule sentence as chips; touch a chip to change it, its number turns it on or off,
// the handle moves it, a swipe left deletes it (with Undo). Every change is saved at once.
"use strict";

var ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  import: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  share: '<path d="M12 15V4M7 9l5-5 5 5M5 14v6h14v-6"/>',
  chev: '<path d="M9 6l6 6-6 6"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  grip: '<circle cx="9" cy="7" r="1.3"/><circle cx="15" cy="7" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="17" r="1.3"/><circle cx="15" cy="17" r="1.3"/>',
  bell: '<path d="M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6zM10 19a2 2 0 0 0 4 0"/>',
  bellx: '<path d="M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6zM10 19a2 2 0 0 0 4 0M4 4l16 16"/>',
  flame: '<path d="M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-3 2-4 2-6 2 1 3 3 3 5 1-1 1-3 0-9z"/>',
  fan: '<circle cx="12" cy="12" r="2"/><path d="M12 10c0-4 1-6 3-6s2 3-1 6M14 12c4 0 6 1 6 3s-3 2-6-1M12 14c0 4-1 6-3 6s-2-3 1-6M10 12c-4 0-6-1-6-3s3-2 6 1"/>',
  drum: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16M4 12h16"/>',
  wind: '<path d="M3 9h12a3 3 0 1 0-3-3M3 15h15a3 3 0 1 1-3 3M3 12h8"/>',
  button: '<rect x="4" y="7" width="16" height="10" rx="5"/><circle cx="12" cy="12" r="2"/>',
  msg: '<path d="M4 5h16v11H9l-5 4z"/>',
  probe: '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM6 11a6 6 0 0 0 12 0M12 17v4"/>',
  link: '<path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
  flag: '<path d="M6 21V4M6 4h11l-2 4 2 4H6"/>',
  temp: '<path d="M10 4a2 2 0 0 1 4 0v10a4 4 0 1 1-4 0z"/>',
  pid: '<path d="M4 18c3-10 6-10 8-6s5 4 8-6"/>',
  undo: '<path d="M9 7L4 12l5 5M4 12h11a5 5 0 0 1 0 10h-2"/>',
  trash: '<path d="M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13"/>'
};
function icon(name, size) {
  return '<svg width="' + (size || 20) + '" height="' + (size || 20) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
}

// Artisan's action codes the tablet edits by picto; the others stay as they are, for the computer.
var SLIDER = { 6: "burner", 3: "air", 4: "drum", 5: "extractor" };
var TILES = [[6, "flame", "burner"], [3, "fan", "air"], [4, "drum", "drum"], [5, "wind", "extractor"],
  [2, "button", "Button"], [0, "msg", "Message"], [26, "wind", "Extractor command"], [27, "probe", "TilauAmbient"]];
var IF_ALARM = 10, START = -1, ON = 9;
var CONDS = ["<", ">", "=", "≠"];

var editing = null; // the list open in the editor (get_alarm_list)
var sheet = null; // {row, zone}: the chip being changed
var undoTimer = null;
var showComputer = false; // the actions only the computer runs, folded under "…"

function onAlarmReply(method, reply) {
  if (method === "get_alarm_list" || method === "edit_alarm" || method === "add_alarm" || method === "delete_alarm" ||
      method === "undo_alarm" || method === "move_alarm" || method === "new_alarm_list") {
    editing = reply;
    renderAlarms();
    return true;
  }
  return false;
}

function renderAlarms() {
  if (editing) { renderEditor(); return; }
  var html = '<div class="al-top"><h1>Alarms</h1><span class="lede" style="margin:0">for every roast</span><span style="flex:1"></span>' +
    '<button class="ib yel" id="al-new" aria-label="New list">' + icon("plus", 22) + '</button>' +
    '<button class="ib" id="al-import" aria-label="Import a list">' + icon("import", 22) + "</button></div>";
  if (!alarms) { $("main").innerHTML = html; return; }
  var rows = alarms.lists.map(function (l) {
    var sub = l.count + (l.not_run ? ' · <span class="nr">' + icon("pid", 12) + " " + l.not_run + "</span>" : "");
    return '<div class="swipe" data-l="' + esc(l.name) + '"><button class="under" aria-label="Delete">' + icon("trash", 22) + "</button>" +
      '<div class="lrow' + (alarms.active === l.name ? " sel" : "") + '"><span class="chk">' + (alarms.active === l.name ? "✓" : "") +
      "</span><span><b>" + esc(l.name) + "</b><small>" + sub + '</small></span><button class="chev" aria-label="Open">' + icon("chev", 22) + "</button></div></div>";
  }).join("");
  rows += '<div class="lrow' + (alarms.active ? "" : " sel") + '" data-none="1"><span class="chk">' + (alarms.active ? "" : "✓") +
    "</span><span><b>None</b><small>no alarm</small></span></div>";
  $("main").innerHTML = html + '<div class="lists">' + rows + "</div>";
  $("al-new").onclick = function () { send("new_alarm_list"); };
  $("al-import").onclick = function () { send("alarms_pick"); };
  document.querySelectorAll(".lists .swipe").forEach(function (s) {
    var name = s.dataset.l;
    swipeable(s, function () { send("delete_alarm_list", name); });
    s.querySelector(".lrow").onclick = function (e) {
      if (e.target.closest(".chev")) { send("get_alarm_list", name); return; }
      send("set_alarm_list", name);
    };
  });
  document.querySelector("[data-none]").onclick = function () { send("set_alarm_list", ""); };
}

// A swipe left on the row shows the bin under it; a touch on the bin deletes, anywhere else closes.
// The rows only let the page scroll vertically (touch-action: pan-y): a horizontal move is ours.
function swipeable(box, onDelete) {
  var row = box.querySelector(".rowin, .lrow"), x0 = null, dx = 0, swiped = false;
  box.addEventListener("pointerdown", function (e) {
    if (e.target.closest(".grip, .under")) return;
    x0 = e.clientX; dx = 0; swiped = false;
  });
  // A swipe is not a touch: the chip or the row under the finger is not opened.
  box.addEventListener("click", function (e) { if (swiped) { e.stopPropagation(); e.preventDefault(); swiped = false; } }, true);
  box.addEventListener("pointermove", function (e) {
    if (x0 == null) return;
    dx = Math.min(0, e.clientX - x0);
    if (dx < -8) { swiped = true; row.style.transition = "none"; row.style.transform = "translateX(" + Math.max(-120, dx) + "px)"; }
  });
  function end() {
    if (x0 == null) return;
    x0 = null;
    row.style.transition = "";
    var open = dx < -60;
    row.style.transform = open ? "translateX(-110px)" : "";
    box.classList.toggle("open", open);
    if (open) setTimeout(function () { document.addEventListener("pointerdown", function close(e) {
      document.removeEventListener("pointerdown", close, true);
      if (!box.querySelector(".under").contains(e.target)) { row.style.transform = ""; box.classList.remove("open"); }
    }, true); }, 0);
  }
  box.addEventListener("pointerup", end);
  box.addEventListener("pointercancel", end);
  box.querySelector(".under").onclick = function () { onDelete(); };
}

// ── one list ──────────────────────────────────────────────────────────
function anchorName(code) {
  if (code === ON) code = START; // ON and START are both the tablet's Start
  var a = editing.anchors.filter(function (x) { return x.code === code; })[0];
  return a ? a.name : "?";
}
function span(s) { return s < 60 ? s + " s" : Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2); }
function sourceName(code) {
  var s = editing.sources.filter(function (x) { return x.code === code; })[0];
  return s ? s.name : "Probe " + code;
}
function momentChip(r) {
  var delay = r.offset > 0 ? " · +" + span(r.offset) : "";
  if (r.anchor === IF_ALARM) return '<span class="c r" data-z="when">' + icon("link", 16) + "#" + (r.guard + 1) + delay + "</span>";
  return '<span class="c t" data-z="when">' + icon(r.anchor === START || r.anchor === ON ? "clock" : "flag", 16) + esc(anchorName(r.anchor)) + delay + "</span>";
}
function conditionChip(r) {
  if (r.source === -3) return "";
  return '<span class="c k" data-z="when">' + icon("temp", 16) + esc(sourceName(r.source)) + " " + CONDS[r.cond] + " " + r.temperature + "</span>";
}
function guardChips(r) {
  var html = "";
  if (r.anchor !== IF_ALARM && r.guard >= 0) html += '<span class="c r" data-z="when">' + icon("link", 16) + "only #" + (r.guard + 1) + "</span>";
  if (r.negguard >= 0) html += '<span class="c r" data-z="when">' + icon("link", 16) + "not #" + (r.negguard + 1) + "</span>";
  return html;
}
function actionChip(r) {
  var skip = r.why && r.on ? " no" : ""; // struck through when the tablet cannot run it; an alarm switched off is only greyed
  if (r.action === -1) return '<span class="c g" data-z="do">' + icon("plus", 16) + "</span>";
  if (SLIDER[r.action]) {
    var pic = { burner: "flame", air: "fan", drum: "drum", extractor: "wind" }[SLIDER[r.action]];
    return '<span class="c a lv-' + SLIDER[r.action] + skip + '" data-z="do">' + icon(pic, 16) + esc(r.text) + " %</span>";
  }
  var tile = TILES.filter(function (t) { return t[0] === r.action; })[0];
  var label = r.action === 2 ? "#" + r.text : r.action === 0 ? "“" + r.text + "”" : r.text;
  if (!tile) {
    var named = editing.computer_actions.filter(function (x) { return x.code === r.action; })[0];
    return '<span class="c a no" data-z="do">' + icon("pid", 16) + esc(named ? named.name : "Action " + r.action) + "</span>";
  }
  return '<span class="c a' + skip + '" data-z="do">' + icon(tile[1], 16) + esc(label) + "</span>";
}

function renderEditor() {
  var e = editing, phase = null;
  var html = '<div class="al-top"><button class="ib" id="ed-back" aria-label="Back">' + icon("back", 22) + '</button><h1>' + esc(e.name) +
    '</h1><span class="lede" style="margin:0">' + e.rows.length + '</span><span style="flex:1"></span>' +
    '<button class="ib yel" id="ed-add" aria-label="New alarm">' + icon("plus", 22) + '</button>' +
    '<button class="ib" id="ed-share" aria-label="Send the list">' + icon("share", 22) + "</button></div><div class=\"alist\" id=\"alist\">";
  e.rows.forEach(function (r, i) {
    if (r.phase !== phase) { phase = r.phase; html += '<div class="ph">' + esc(phase) + "</div>"; }
    html += '<div class="swipe arow' + (r.on ? "" : " off") + '" data-i="' + i + '"><button class="under" aria-label="Delete">' + icon("trash", 22) + "</button>" +
      '<div class="rowin"><span class="grip">' + icon("grip", 20) + '</span><button class="num' + (r.on ? " on" : "") + '" aria-label="On or off">' + r.n + "</button>" +
      momentChip(r) + conditionChip(r) + guardChips(r) +
      '<span class="arrow">→</span>' + actionChip(r) + '<button class="bell' + (r.beep ? " on" : "") + '" aria-label="Beep">' + icon(r.beep ? "bell" : "bellx", 19) +
      "</button></div></div>";
  });
  if (!e.rows.length) html += '<div class="empty-al">' + icon("bell", 40) + "</div>";
  $("main").innerHTML = html + "</div>";
  $("ed-back").onclick = function () { editing = null; closeZone(); send("get_alarms"); };
  $("ed-add").onclick = function () { send("add_alarm", e.name); };
  $("ed-share").onclick = function () { send("alarm_share", e.name); };
  document.querySelectorAll(".arow").forEach(function (box) {
    var i = +box.dataset.i;
    swipeable(box, function () { send("delete_alarm", JSON.stringify({ name: e.name, row: i })); showUndo(i + 1); });
    box.querySelector(".num").onclick = function () { edit(i, { on: e.rows[i].on ? 0 : 1 }); };
    box.querySelector(".bell").onclick = function () { edit(i, { beep: e.rows[i].beep ? 0 : 1 }); };
    box.querySelectorAll("[data-z]").forEach(function (c) { c.onclick = function () { openZone(i, c.dataset.z); }; });
    dragHandle(box, i);
  });
  if (sheet) fillZone();
}
function edit(i, fields) { send("edit_alarm", JSON.stringify({ name: editing.name, row: i, fields: fields })); }

function showUndo(n) {
  var t = $("al-undo");
  t.innerHTML = "Alarm " + n + " deleted <button class=\"und\" aria-label=\"Undo\">" + icon("undo", 20) + "</button>";
  t.style.display = "flex";
  t.querySelector("button").onclick = function () { send("undo_alarm", editing.name); t.style.display = "none"; };
  clearTimeout(undoTimer);
  undoTimer = setTimeout(function () { t.style.display = "none"; }, 6000);
}

// Hold the handle and drag: the row follows the finger, a line shows where it lands.
function dragHandle(box, i) {
  var grip = box.querySelector(".grip");
  grip.addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    grip.setPointerCapture(ev.pointerId);
    var rows = Array.prototype.slice.call(document.querySelectorAll(".arow")), y0 = ev.clientY, target = i;
    box.classList.add("lift");
    function move(e) {
      box.style.transform = "translateY(" + (e.clientY - y0) + "px)";
      target = i;
      rows.forEach(function (r, k) {
        var rect = r.getBoundingClientRect(), mid = rect.top + rect.height / 2;
        if (k < i && e.clientY < mid) target = Math.min(target, k);
        if (k > i && e.clientY > mid) target = Math.max(target, k);
      });
      rows.forEach(function (r, k) { r.classList.toggle("drop-before", k === target && target < i); r.classList.toggle("drop-after", k === target && target > i); });
    }
    function up() {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      box.classList.remove("lift");
      box.style.transform = "";
      rows.forEach(function (r) { r.classList.remove("drop-before", "drop-after"); });
      if (target !== i) send("move_alarm", JSON.stringify({ name: editing.name, from: i, to: target }));
    }
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
  });
}

// ── the zone sheet: the chip touched, changed on the spot ─────────────
function openZone(i, zone) {
  sheet = { row: i, zone: zone };
  showComputer = false;
  fillZone();
  $("zscrim").onclick = closeZone; // a touch above the sheet closes it
  $("zscrim").style.display = "block";
  $("zsheet").style.display = "flex";
}
function closeZone() { sheet = null; $("zscrim").style.display = "none"; $("zsheet").style.display = "none"; }

function stepper(id, value, label) {
  return '<div class="step"><button data-s="' + id + '" data-d="-10">−10</button><button data-s="' + id + '" data-d="-1">−1</button>' +
    '<b>' + label + '</b><button data-s="' + id + '" data-d="1">+1</button><button data-s="' + id + '" data-d="10">+10</button></div>';
}
function fillZone() {
  var r = editing.rows[sheet.row];
  if (!r) { closeZone(); return; }
  var html = '<div class="grab"></div>';
  if (sheet.zone === "when") {
    var anchors = editing.anchors.map(function (a) {
      var on = a.code === r.anchor || (a.code === START && r.anchor === ON);
      return '<button class="seg-b' + (on ? " on" : "") + '" data-anchor="' + a.code + '">' + esc(a.name) + "</button>";
    }).join("");
    var refs = function (field, value) {
      return '<button class="seg-b' + (value < 0 ? " on" : "") + '" data-' + field + '="-1">–</button>' + editing.rows.map(function (x, k) {
        return k === sheet.row ? "" : '<button class="seg-b' + (value === k ? " on" : "") + '" data-' + field + '="' + k + '">#' + (k + 1) + "</button>";
      }).join("");
    };
    var sources = editing.sources.map(function (s) {
      return '<button class="seg-b' + (s.code === r.source ? " on k" : "") + '" data-source="' + s.code + '">' + esc(s.name) + "</button>";
    }).join("");
    html += '<div class="zh">' + icon("flag", 18) + '</div><div class="segs">' + anchors + "</div>" +
      (r.anchor === IF_ALARM ? '<div class="zh">' + icon("link", 18) + '</div><div class="segs">' + refs("guard", r.guard) + "</div>" : "") +
      '<div class="zrow"><span class="zh">' + icon("clock", 18) + "</span>" + stepper("offset", r.offset, r.offset > 0 ? "+" + span(r.offset) : "0") + "</div>" +
      '<div class="zh">' + icon("temp", 18) + '</div><div class="segs">' + sources + "</div>" +
      (r.source !== -3 ? '<div class="zrow"><div class="segs">' + CONDS.map(function (c, k) {
        return '<button class="seg-b' + (k === r.cond ? " on k" : "") + '" data-cond="' + k + '">' + c + "</button>"; }).join("") + "</div>" +
        stepper("temperature", r.temperature, r.temperature) + "</div>" : "") +
      (r.anchor !== IF_ALARM ? '<div class="zrow"><span class="zh">' + icon("link", 18) + ' only</span><div class="segs">' + refs("guard", r.guard) + "</div></div>" : "") +
      '<div class="zrow"><span class="zh">' + icon("link", 18) + ' not</span><div class="segs">' + refs("negguard", r.negguard) + "</div></div>";
  } else {
    var tiles = TILES.map(function (t) {
      var name = SLIDER[t[0]] ? (editing.levers[t[2]] || t[2]) : t[2];
      var off = SLIDER[t[0]] && !editing.levers[t[2]];
      return '<button class="tile' + (t[0] === r.action ? " on" : "") + (off ? " dim" : "") + '" data-action="' + t[0] + '">' + icon(t[1], 28) + "<small>" + esc(name) + "</small></button>";
    }).join("");
    var computer = editing.computer_actions.map(function (a) {
      return '<button class="seg-b dimb' + (a.code === r.action ? " on" : "") + '" data-action="' + a.code + '">' + esc(a.name) + "</button>";
    }).join("");
    var value = "";
    if (SLIDER[r.action]) value = stepper("text", +r.text || 0, (+r.text || 0) + " %");
    else if (r.action === 2) value = '<div class="segs">' + editing.buttons.map(function (b) {
      return '<button class="seg-b' + (String(b.n) === r.text.split("#")[0].trim() ? " on" : "") + '" data-text="' + b.n + '">#' + b.n + (b.command ? " · " + esc(b.command) : "") + "</button>"; }).join("") + "</div>";
    else if (r.action === 0 || r.action === 26 || r.action === 27) value = '<input class="field ztext" id="ztext" value="' + esc(r.text) + '" maxlength="200">';
    var isComputer = !TILES.some(function (t) { return t[0] === r.action; }) && r.action !== -1;
    tiles += '<button class="tile dim' + (isComputer ? " on" : "") + '" id="z-more">' + icon("pid", 28) + "<small>…</small></button>";
    html += '<div class="tiles">' + tiles + '</div><div class="zval">' + value + "</div>" +
      (showComputer || isComputer ? '<div class="segs">' + computer + "</div>" : "");
  }
  $("zsheet").innerHTML = html;
  $("zsheet").querySelectorAll("[data-anchor]").forEach(function (b) { b.onclick = function () {
    var code = +b.dataset.anchor;
    edit(sheet.row, code === IF_ALARM && r.guard < 0 ? { anchor: code, guard: sheet.row ? sheet.row - 1 : -1 } : { anchor: code });
  }; });
  ["guard", "negguard", "source", "cond", "action"].forEach(function (f) {
    $("zsheet").querySelectorAll("[data-" + f + "]").forEach(function (b) { b.onclick = function () {
      var fields = {}; fields[f] = +b.dataset[f];
      if (f === "action" && SLIDER[fields.action] && !(+r.text >= 0 && r.text !== "")) fields.text = "0";
      if (f === "action" && fields.action === 2 && !editing.buttons.length) return;
      edit(sheet.row, fields);
    }; });
  });
  $("zsheet").querySelectorAll("[data-text]").forEach(function (b) { b.onclick = function () { edit(sheet.row, { text: b.dataset.text }); }; });
  $("zsheet").querySelectorAll("[data-s]").forEach(function (b) { b.onclick = function () {
    var f = b.dataset.s, d = +b.dataset.d, fields = {};
    if (f === "offset") fields.offset = Math.max(0, Math.min(3600, r.offset + d));
    else if (f === "temperature") fields.temperature = Math.round((r.temperature + d) * 10) / 10;
    else fields.text = String(Math.max(0, Math.min(100, (+r.text || 0) + d)));
    for (var k in fields) r[k] = fields[k]; // a quick second tap builds on this one, before the answer
    edit(sheet.row, fields);
  }; });
  var more = $("z-more");
  if (more) more.onclick = function () { showComputer = !showComputer; fillZone(); };
  var t = $("ztext");
  if (t) t.onchange = function () { edit(sheet.row, { text: t.value }); };
}
