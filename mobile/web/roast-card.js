// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The roast card, the desktop's (Roasts › Export › Roast card, src/tilauscope/beancave_roast_card.py): a
// 3200 × 1800 PNG handed to the system's share sheet. What it shows comes from the core (call "roast_card":
// tilaucore.roast_card through tilauscope_mobile.roasts.card_data); this draws it on the desktop's layout,
// with the system's sans serif and the desktop's JetBrains Mono for the figures (fonts/, copied at build).
var RoastCard = (function () {
  var W = 2400, H = 1350, SCALE = 4 / 3;
  // The desktop card's colours (tilauscope_types THEME, the probe hues, the phases)
  var BG = "#1E1E2E", SURFACE = "#181825", BORDER = "#313244", RAISED = "#45475A";
  var TEXT = "#CDD6F4", MUTED = "#A6ADC8", FAINT = "#6C7086";
  var BLUE = "#89B4FA", PEACH = "#FAB387", RISE = "#457ed9", PHASES = ["#89DCEB", "#F9E2AF", "#F38BA8"];
  // Plot frame, lanes, key moments rows (tilaucore.roast_card ROW_Y0, ROW_STEP)
  var X0 = 150, X1 = 1730, Y0 = 300, LANE_H = 52, LANE_GAP = 14, ROW_Y0 = 392, ROW_STEP = 39;
  var SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', MONO = '"CardMono", monospace';
  var NAMES = { charge: "Charge", tp: "TP", dry: "Dry end", fc: "First crack", drop: "Drop" };
  var fonts = null, ctx = null;

  // The figures' font; a font not loaded leaves the monospace fallback, and is tried again next time.
  function loadFonts() {
    if (!fonts) {
      fonts = Promise.resolve().then(function () {
        return Promise.all([new FontFace("CardMono", "url(fonts/JetBrainsMono-Regular.ttf)"),
                            new FontFace("CardMono", "url(fonts/JetBrainsMono-Bold.ttf)", { weight: "700" })]
          .map(function (face) { return face.load().then(function (f) { document.fonts.add(f); }); }));
      }).catch(function () { fonts = null; });
    }
    return fonts;
  }

  function sans(size, bold) { return (bold ? "700 " : "") + size + "px " + SANS; }
  function mono(size, bold) { return (bold ? "700 " : "") + size + "px " + MONO; }
  function alpha(hex, a) { // a QColor with its alpha (0-255)
    var n = parseInt(hex.slice(1), 16);
    return "rgba(" + (n >> 16 & 255) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + (a / 255).toFixed(3) + ")";
  }
  function pyRound(x) { var r = Math.round(x); return Math.abs(x % 1) === 0.5 && r % 2 ? r - 1 : r; } // Python's round
  function mmss(s) { s = Math.max(0, pyRound(s)); return Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2); }
  function fixed(v, digits) { return v.toFixed(digits); } // as Python's f"{v:.{digits}f}", -0.0 included

  function elide(text, max) {
    if (ctx.measureText(text).width <= max) return text;
    while (text && ctx.measureText(text + "…").width > max) text = text.slice(0, -1);
    return text + "…";
  }
  // Draw on a baseline; returns the drawn width.
  function draw(x, baseline, text, font, color, align, maxW) {
    ctx.font = font;
    if (maxW) text = elide(text, maxW);
    var width = ctx.measureText(text).width;
    if (align === "right") x -= width;
    else if (align === "center") x -= width / 2;
    ctx.fillStyle = color;
    ctx.fillText(text, x, baseline);
    return width;
  }
  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function rrect(x, y, w, h, r, fill, stroke) {
    roundRect(x, y, w, h, r);
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
  }
  function line(x1, y1, x2, y2, color, width, dash) {
    ctx.beginPath();
    ctx.setLineDash(dash || []);
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.stroke();
    ctx.setLineDash([]);
  }
  function dot(x, y, r, fill, stroke, width) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke(); }
  }
  // Points (null breaks the line) as round-capped segments.
  function polyline(points, color, width) {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    var segment = [];
    points.concat([null]).forEach(function (p) {
      if (p) { segment.push(p); return; }
      if (segment.length > 1) {
        ctx.beginPath();
        ctx.moveTo(segment[0][0], segment[0][1]);
        for (var i = 1; i < segment.length; i++) ctx.lineTo(segment[i][0], segment[i][1]);
        ctx.stroke();
      }
      segment = [];
    });
    ctx.lineCap = "butt";
    ctx.lineJoin = "miter";
  }

  function dateLabel(d) {
    if (!(d.epoch > 0)) return d.date;
    var when = new Date(d.epoch * 1000);
    return when.getDate() + " " + when.toLocaleString(undefined, { month: "short" }) + " " + when.getFullYear() + " · " +
      ("0" + when.getHours()).slice(-2) + ":" + ("0" + when.getMinutes()).slice(-2);
  }

  // ── header ───────────────────────────────────────────────────────────────
  function header(d) {
    ctx.letterSpacing = "2px"; // the desktop's 8 % tracking of the kicker
    draw(64, 82, d.kicker, sans(24), MUTED, "left", 560);
    ctx.letterSpacing = "0px";
    var size = 62; // a long name shrinks before it is cut
    ctx.font = sans(size, true);
    while (size > 40 && ctx.measureText(d.name).width > 560) { size -= 2; ctx.font = sans(size, true); }
    draw(64, 150, d.name, sans(size, true), TEXT, "left", 560);
    draw(64, 198, [dateLabel(d), d.roaster].filter(Boolean).join(" · "), sans(26), MUTED, "left", 560);
    line(640, 56, 640, 210, BORDER, 2);

    var f = d.figures, dash = "—", dev = PHASES[2];
    var colourLabel = !d.agtron ? "Colour" : d.basis === "ground" ? "Colour · ground"
      : d.basis === "estimated" ? "Colour · ground (est.)" : "Colour · whole bean";
    var columns = [
      [["Total duration", f.duration, TEXT], ["Development", f.development, dev], ["Development rise", f.rise, dev]],
      [["Green weight", f.green, TEXT], ["Roasted weight", f.roasted, TEXT], ["Weight loss", f.loss, TEXT]],
      [[colourLabel, d.agtron ? "Agtron " + d.agtron_text : dash, TEXT], ["Energy", d.energy || dash, TEXT]]
        .concat(f.ambient.length ? [["Ambient", f.ambient.join(" · "), TEXT]] : [])
    ];
    columns.forEach(function (column, ci) {
      column.forEach(function (row, ri) {
        var x = 690 + ci * 560, y = 90 + ri * 54, value = row[1];
        var width = draw(x + 500, y, value, mono(value.length <= 16 ? 28 : 22, true), row[2], "right");
        draw(x, y, row[0], sans(26), MUTED, "left", Math.max(80, 480 - Math.floor(width)));
        if (ci === 2 && ri === 0 && d.agtron) dot(x + 500 - width - 22, y - 9, 9, d.swatch);
      });
    });
  }

  // ── curve, phases, lanes ─────────────────────────────────────────────────
  function chart(d) {
    rrect(32, 248, 1790, 1040, 18, SURFACE, BORDER);
    var unit = d.figures.unit, total = d.total, lanes = d.lanes, s = d.scales;
    var lanesH = lanes.length * (LANE_H + LANE_GAP) - (lanes.length ? LANE_GAP : 0);
    var y1 = 1262 - 42 - 34 - lanesH - (lanes.length ? 90 : 70);
    function X(t) { return X0 + t / total * (X1 - X0); }
    function Y(v) { return y1 - (v - s.low) / (s.high - s.low) * (y1 - Y0); }
    function R(v) { return y1 - v / s.rhigh * (y1 - Y0); }
    var at = {}; // each milestone's time
    d.moments.forEach(function (m) { at[m.key] = m.t; });
    var bounds = [0, at.dry, at.fc, total];

    // phase grounds, grid, axes
    for (var p = 0; p < 3; p++) {
      if (bounds[p] != null && bounds[p + 1] != null) {
        ctx.fillStyle = alpha(PHASES[p], 18);
        ctx.fillRect(X(bounds[p]), Y0, X(bounds[p + 1]) - X(bounds[p]), y1 - Y0);
      }
    }
    for (var v = s.low; v <= s.high; v += s.step) {
      line(X0, Y(v), X1, Y(v), BORDER, 1);
      draw(X0 - 14, Y(v) + 8, String(v), mono(22), FAINT, "right");
    }
    for (var r = 0; r <= s.rhigh; r += s.rstep) draw(X1 + 14, R(r) + 8, String(r), mono(22), RISE);
    draw(X0 - 14, Y0 - 24, unit, sans(22), FAINT, "right");
    draw(X1 + 14, Y0 - 24, unit + "/min", sans(22), RISE);
    d.moments.slice(1, -1).forEach(function (m) { line(X(m.t), Y0, X(m.t), y1, RAISED, 1.5, [6, 3]); });

    // curves, clipped to the plot
    ctx.save();
    ctx.beginPath();
    ctx.rect(X0 - 8, Y0 - 8, X1 - X0 + 16, y1 - Y0 + 8);
    ctx.clip();
    function points(series, place) { return series.map(function (v, i) { return v == null ? null : [X(d.t[i]), place(v)]; }); }
    polyline(points(d.ror, R), RISE, 2.7);
    polyline(points(d.et, Y), PEACH, 2.4);
    polyline(points(d.bt, Y), BLUE, 3.4);
    ctx.restore();

    // peak rate of rise after the turning point
    if (d.peak) {
      dot(X(d.peak.t), R(d.peak.r), 5, RISE);
      draw(X(d.peak.t), R(d.peak.r) - 18, fixed(d.peak.r, 1) + " " + unit + "/min", mono(22, true), RISE, "center");
    }

    // milestones: dot on the bean curve and a callout on two alternating rows
    d.moments.forEach(function (m, n) {
      if (m.bt == null) return;
      var x = X(m.t), y = Y(m.bt), row = Y0 + (n % 2 === 0 ? 26 : 79), label = NAMES[m.key].toUpperCase();
      var figures = mmss(m.t) + " · " + fixed(m.bt, 0) + " " + unit;
      ctx.font = sans(22, true);
      var width = ctx.measureText(label).width + 10;
      ctx.font = mono(22);
      width += ctx.measureText(figures).width;
      var left = m.key === "charge" ? x + 8 : m.key === "drop" ? x - width - 8 : x - width / 2;
      left = Math.min(Math.max(left, X0 + 4), X1 - width - 4);
      line(x, row + 12, x, y - 9, alpha(MUTED, 128), 1);
      var drawn = draw(left, row, label, sans(22, true), TEXT);
      draw(left + drawn + 10, row, figures, mono(22), MUTED);
      dot(x, y, 6.5, BG, BLUE, 3);
    });

    // phase strip
    var names = ["Drying", "Maillard", "Development"], sy = y1 + 20;
    if (d.phases.every(function (v) { return v != null; })) {
      for (var q = 0; q < 3; q++) {
        var left = X(bounds[q]), width = X(bounds[q + 1]) - X(bounds[q]) - 3, length = d.phases[q];
        rrect(left, sy, width, 46, 4, alpha(PHASES[q], 56));
        ctx.fillStyle = PHASES[q];
        ctx.fillRect(left, sy, width, 4);
        var figures = mmss(length) + " · " + fixed(length / total * 100, 1) + " %";
        if (width >= 360) {
          var drawn = draw(left + 12, sy + 31, names[q], sans(22, true), PHASES[q]);
          draw(left + 22 + drawn, sy + 31, figures, mono(22), TEXT);
        } else {
          draw(left + 12, sy + 31, figures, mono(22, true), PHASES[q], "left", Math.floor(width) - 16);
        }
      }
    } else {
      ctx.fillStyle = BORDER;
      ctx.fillRect(X0, sy, X1 - X0, 10);
    }

    // settings lanes
    var ly = sy + 70;
    lanes.forEach(function (lane) {
      var colour = lane.color, bottom = ly + LANE_H, steps = lane.steps;
      draw(X0 - 14, ly + LANE_H / 2 + 8, lane.name, sans(22, true), colour, "right", 130);
      line(X0, bottom, X1, bottom, BORDER, 1);
      function LY(v) { return bottom - Math.max(0, Math.min(100, v)) / 100 * LANE_H; }
      function LX(t) { return X0 + t / total * (X1 - X0); }
      var path = [[LX(steps[0][0]), LY(steps[0][1])]];
      for (var i = 1; i < steps.length; i++) path.push([LX(steps[i][0]), LY(steps[i - 1][1])], [LX(steps[i][0]), LY(steps[i][1])]);
      path.push([X1, LY(steps[steps.length - 1][1])]);
      ctx.beginPath();
      path.forEach(function (pt, k) { if (k) ctx.lineTo(pt[0], pt[1]); else ctx.moveTo(pt[0], pt[1]); });
      ctx.lineTo(X1, bottom);
      ctx.lineTo(path[0][0], bottom);
      ctx.closePath();
      ctx.fillStyle = alpha(colour, 30);
      ctx.fill();
      ctx.beginPath();
      path.forEach(function (pt, k) { if (k) ctx.lineTo(pt[0], pt[1]); else ctx.moveTo(pt[0], pt[1]); });
      ctx.strokeStyle = colour;
      ctx.lineWidth = 2.5;
      ctx.stroke();
      var lastX = -1e9, lastV = null;
      steps.forEach(function (step) {
        var x = LX(step[0]), v = step[1];
        if (x - lastX < 70 || v === lastV) return;
        lastX = x; lastV = v;
        draw(x + 4, LY(v) - 6, String(v), mono(19), colour);
      });
      ly += LANE_H + LANE_GAP;
    });

    // time axis and legend
    var ty = (lanes.length ? ly - LANE_GAP : sy + 46) + 34, tick = total <= 900 ? 60 : 120;
    for (var t = 0; t <= Math.floor(total); t += tick) draw(X(t), ty, mmss(t), mono(22), FAINT, "center");
    var lx = X0;
    [["Bean temperature", BLUE], ["Air temperature", PEACH], ["Rate of rise", RISE]].forEach(function (item) {
      ctx.fillStyle = item[1];
      ctx.fillRect(lx, 1251, 26, 5);
      lx += 36 + draw(lx + 36, 1262, item[0], sans(22), MUTED) + 30;
    });
  }

  // ── key moments ──────────────────────────────────────────────────────────
  function moments(d) {
    rrect(1846, 248, 522, 1040, 18, SURFACE, BORDER);
    draw(1874, 300, "Key moments", sans(26, true), TEXT);
    [["Time", 1874, "left"], ["Bean", 2036, "right"], ["Rise", 2136, "right"], ["Event", 2168, "left"]].forEach(function (h) {
      draw(h[1], 344, h[0], sans(20), FAINT, h[2]);
    });
    var colours = { charge: TEXT, tp: MUTED, dry: PHASES[0], fc: PHASES[1], drop: PHASES[2] };
    d.rows.forEach(function (row, n) {
      var y = ROW_Y0 + n * ROW_STEP;
      if (row.milestone) rrect(1860, y - 27, 494, 36, 6, alpha(BORDER, 140));
      draw(1874, y, mmss(row.t), mono(22), MUTED);
      draw(2036, y, row.bean == null ? "—" : fixed(row.bean, 1), mono(22), BLUE, "right");
      draw(2136, y, row.rise == null ? "—" : fixed(row.rise, 1), mono(22), RISE, "right");
      draw(2168, y, row.milestone ? NAMES[row.key] : row.text, sans(22, row.milestone),
           row.milestone ? colours[row.key] : row.color, "left", 190);
    });
  }

  // The card as a canvas, 3200 × 1800.
  function paint(d) {
    var canvas = document.createElement("canvas");
    canvas.width = Math.round(W * SCALE);
    canvas.height = Math.round(H * SCALE);
    ctx = canvas.getContext("2d");
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(SCALE, SCALE);
    ctx.textBaseline = "alphabetic";
    header(d);
    if (d.frame) {
      chart(d);
      moments(d);
    } else {
      rrect(32, 248, 2336, 1040, 18, SURFACE, BORDER);
      draw(W / 2, 780, "Charge or drop not marked", sans(30), MUTED, "center");
    }
    draw(64, 1328, "TilauScope", sans(22, true), FAINT);
    return canvas;
  }

  // The card drawn and handed to the app's share sheet: send("card_share", {file, png}); false when it could not be.
  function share(d, send) {
    return Promise.resolve().then(loadFonts).then(function () {
      var png = paint(d).toDataURL("image/png").split(",")[1];
      send("card_share", JSON.stringify({ file: d.file, png: png }));
      return true;
    }).catch(function () { return false; });
  }

  // The icon, as in BeanCave › Roasts and at the end of the roast: a frame holding a curve.
  var ICON = '<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.5" ' +
    'fill="none" stroke="currentColor" stroke-width="2"/><path d="M6 15.5c2.2-1 3.4-4.5 6-4.5s3.2 2.4 6-1.5" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

  // The icon's touch, on either page: one card at a time; the icon pulses from the touch until the share sheet
  // opens (the app's onCardShared), a card not made is said in a toast. An app that never answers (the page
  // reloaded under its call) frees the icon after 15 s, silently: the sheet may well have opened.
  // `ask(button, argument)` on the touch, `reply(card)` with the answer to "roast_card".
  var NO_ANSWER_MS = 15000;
  function sharer(send, toast) {
    var button = null, busy = false, timer = null;
    function done(ok) {
      busy = false;
      clearTimeout(timer);
      if (button) button.classList.remove("working");
      if (!ok) toast("The roast card could not be made");
    }
    window.onCardShared = done;
    return {
      ask: function (el, argument) {
        if (busy) return;
        busy = true;
        button = el;
        el.classList.add("working");
        timer = setTimeout(function () { done(true); }, NO_ANSWER_MS);
        send("roast_card", argument || "");
      },
      reply: function (card) {
        if (!card) { done(false); return; }
        share(card, send).then(function (ok) { if (!ok) done(false); });
      }
    };
  }

  return { paint: paint, share: share, sharer: sharer, ICON: ICON };
})();
