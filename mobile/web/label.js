// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

// The B21S labels drawn on the tablet. The roast label follows the desktop's 30 mm
// layout line for line (NiimbotLabelBuilder._build_30mm in src/tilauscope/label_printer.py),
// with its texts from the core (tilaucore.roast_label), DejaVu Sans, and Pillow's own measures
// (label-metrics.js): lines break and shorten where the desktop's do. Every label is then
// kept black or white: the preview is what prints. Needs label-metrics.js.
"use strict";
var Label = (function () {
  var W = 384, H = 240, PAD = 10; // 30 mm at 203 dpi; the print head is 384 dots wide
  var VALUE = 24, SUBTITLE = 16, GRAPH = 12, VALUE_SIZES = [20, 18, 16, 14, 12, 10]; // the desktop's Pillow sizes
  var fonts = null, probe = document.createElement("canvas").getContext("2d");

  /** The desktop's label fonts (copied into the app at build time), loaded once. */
  function ready() {
    if (!fonts) {
      fonts = Promise.all([new FontFace("LabelSans", "url(fonts/DejaVuSans.ttf)"),
                           new FontFace("LabelSans", "url(fonts/DejaVuSans-Bold.ttf)", { weight: "700" })]
        .map(function (face) { document.fonts.add(face); return face.load(); }));
    }
    return fonts;
  }

  function font(size, bold) {
    var key = (bold ? "b" : "") + size;
    return { css: (bold ? "700 " : "") + size + "px LabelSans", ascent: LABEL_METRICS.ascent[key], glyphs: LABEL_METRICS.glyphs[key] };
  }
  // [advance, ink right, ink bottom] of a character; one Pillow was not asked about is measured here.
  function glyph(ch, f) {
    if (f.glyphs[ch]) return f.glyphs[ch];
    probe.font = f.css;
    var m = probe.measureText(ch), advance = Math.round(m.width);
    return [advance, advance, f.ascent + Math.max(0, Math.round(m.actualBoundingBoxDescent))];
  }
  // textbbox()[2]: the pen's end or the furthest ink, whichever is further right.
  function width(text, f) {
    var pen = 0, right = 0;
    for (var ch of text) { var m = glyph(ch, f); right = Math.max(right, pen + m[1]); pen += m[0]; }
    return Math.max(pen, right);
  }
  // textbbox()[3]: from the line's top to the lowest ink.
  function bottom(text, f) {
    var low = 0;
    for (var ch of text) low = Math.max(low, glyph(ch, f)[2]);
    return low;
  }
  // Each character where Pillow puts it: at the pen, on the baseline one ascent below the top.
  function draw(g, text, x, y, f) {
    g.font = f.css;
    for (var ch of text) { g.fillText(ch, x, y + f.ascent); x += glyph(ch, f)[0]; }
  }

  function adaptingLine(g, label, value, x, y, maxWidth, labelFont) {
    var labelText = label ? label + ": " : "", labelWidth = width(labelText, labelFont), maxValue = maxWidth - labelWidth;
    var best = font(VALUE_SIZES[VALUE_SIZES.length - 1]);
    for (var i = 0; i < VALUE_SIZES.length; i++) {
      var f = font(VALUE_SIZES[i]);
      if (width(value, f) <= maxValue) { best = f; break; }
    }
    if (width(value, best) > maxValue) {
      while (value && width(value + "…", best) > maxValue) value = value.slice(0, -1);
      value += "…";
    }
    draw(g, labelText, x, y, labelFont);
    draw(g, value, x + labelWidth, y, best);
    return bottom("Ag", labelFont) + 2;
  }

  function wrapped(g, text, x, y, maxWidth, maxY, f) {
    var line = "", lineHeight = bottom("Ag", f) + 1;
    text.split(" ").forEach(function (word) {
      if (y < 0) return; // stopped: the label is full
      var next = (line + " " + word).trim();
      if (width(next, f) <= maxWidth) { line = next; return; }
      if (line) {
        if (y + lineHeight > maxY) { y = -1; return; }
        draw(g, line, x, y, f);
        y += lineHeight;
      }
      line = word;
    });
    if (y >= 0 && line && y + lineHeight <= maxY) draw(g, line, x, y, f);
  }

  /** The 30 mm roast label from the core's lines (origin_farm, bean, details, date, notes_header, notes). */
  function roast30(lines) {
    var c = document.createElement("canvas"), g = c.getContext("2d");
    c.width = W; c.height = H;
    g.fillStyle = "#fff"; g.fillRect(0, 0, W, H);
    g.fillStyle = "#000"; g.textBaseline = "alphabetic";
    var textWidth = W - 2 * PAD, y = PAD, value = font(VALUE), subtitle = font(SUBTITLE, true), graph = font(GRAPH);

    var originFarm = lines.origin_farm;
    while (width(originFarm, value) > textWidth && originFarm.length > 3) originFarm = originFarm.slice(0, -1);
    if (originFarm !== lines.origin_farm) originFarm = originFarm.trimEnd() + "…";
    draw(g, originFarm, PAD, y, value);
    y += bottom(originFarm, value) + 1;

    var bean = lines.bean;
    while (width(bean, subtitle) > textWidth && bean.length > 6) bean = bean.slice(0, -1);
    draw(g, bean, PAD, y, subtitle);
    y += bottom(bean, subtitle) + 2;

    for (var i = 0; i < lines.details.length; i++) {
      if (y + bottom("Ag", subtitle) > H - PAD * 4) break;
      y += adaptingLine(g, lines.details[i][0], lines.details[i][1], PAD, y, textWidth, subtitle);
    }
    y += 2;
    draw(g, lines.date, PAD, y, subtitle);
    y += bottom(lines.date, subtitle) + 2;
    draw(g, lines.notes_header, PAD, y, graph);
    y += bottom(lines.notes_header, graph) + 1;
    wrapped(g, lines.notes, PAD, y, textWidth, H - PAD, graph);
    return c;
  }

  /** Keeps the canvas black or white; the rows are 48 bytes each, most significant bit on the left, 1 = ink. */
  function oneBit(c) {
    var g = c.getContext("2d"), img = g.getImageData(0, 0, c.width, c.height), px = img.data;
    var rows = new Uint8Array(c.width / 8 * c.height);
    for (var i = 0; i < c.width * c.height; i++) {
      var ink = px[i * 4] * 0.299 + px[i * 4 + 1] * 0.587 + px[i * 4 + 2] * 0.114 < 128 && px[i * 4 + 3] > 127;
      px[i * 4] = px[i * 4 + 1] = px[i * 4 + 2] = ink ? 0 : 255; px[i * 4 + 3] = 255;
      if (ink) rows[i >> 3] |= 0x80 >> (i & 7);
    }
    g.putImageData(img, 0, 0);
    return { url: c.toDataURL(), rows: rows };
  }

  function base64(bytes) { var s = ""; for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]); return btoa(s); }

  var PRINTER_ICON = "M7 9V3h10v6M7 17H4v-7h16v7h-3M7 14h10v7H7z", PRINTED_ICON = "M6 13.5l4.5 4.5L20 8";
  var NOT_FOUND = "Label printer not found: turn it on, the tablet finds it by itself";
  var PROBLEMS = {
    cover_open: "The printer cover is open: close it, then touch the printer again",
    no_answer: "The printer did not answer, nothing was printed: touch the printer again",
    unconfirmed: "Check the label, it may be blank: touch the printer to print again"
  };

  /** The label printer seen from a page: looked for while its icon shows, so the icon says whether
   *  it is there, then one roast label at a time. onChange() redraws the icon; toast() says a problem. */
  function printer(onChange, toast) {
    var link = {}, jobSeen = false, watching = false, ctl = { device: null, state: null };
    function set(state) { ctl.state = state; if (PROBLEMS[state]) toast(PROBLEMS[state]); onChange(); }
    function found() { return link.state === "connected"; }
    /** Looks for the printer while [on] (the link reconnects by itself), lets it go otherwise. */
    ctl.watch = function (on) {
      on = !!(on && ctl.device);
      if (on === watching) return;
      watching = on; link = {}; ctl.state = null;
      send(on ? "printer_connect" : "printer_disconnect", on ? ctl.device.address : "");
      onChange();
    };
    /** True when a label can be asked for now; says why not otherwise. */
    ctl.start = function () {
      if (ctl.state === "working") return false;
      if (!found()) { toast(NOT_FOUND); return false; }
      jobSeen = false;
      set("working");
      return true;
    };
    /** The core's lines for the label asked for (null when it could not make them). */
    ctl.print = function (lines) {
      if (!lines) { set(null); toast("No label for this roast: it needs its coffee in the BeanCave and Dry end, First crack and Drop marked"); return; }
      ready().then(function () {
        if (!found()) { set(null); toast(NOT_FOUND); return; }
        send("printer_print", base64(oneBit(roast30(lines)).rows));
      }, function () { set(null); toast("The label could not be drawn"); });
    };
    /** The icon: grey until the printer is found, then its state. */
    ctl.icon = function (enabled) {
      var colour = !enabled || (!found() && ctl.state !== "working" && !PROBLEMS[ctl.state]) ? "#6C7086"
        : ctl.state === "printed" ? "#A6E3A1" : PROBLEMS[ctl.state] ? "#FAB387" : "#CBA6F7";
      return { colour: colour, path: ctl.state === "printed" ? PRINTED_ICON : PRINTER_ICON, working: ctl.state === "working" };
    };
    window.onPrinter = function (s) {
      link = s;
      if (ctl.state === "working") {
        if (s.state === "connected" && (s.print === "sending" || s.print === "printing")) jobSeen = true;
        else if (s.state === "connected" && jobSeen && s.print) // an earlier label's outcome is not this one's
          return set(s.print === "printed" ? "printed" : s.print === "failed" ? (s.failure === "cover_open" ? "cover_open" : "no_answer") : "unconfirmed");
        else if (s.state !== "connected") {
          if (jobSeen) return set("unconfirmed");
          toast(NOT_FOUND);
          return set(null);
        }
      }
      onChange();
    };
    return ctl;
  }

  return { W: W, H: H, ready: ready, roast30: roast30, oneBit: oneBit, base64: base64, printer: printer };
})();
