/* ===========================================================================
   tilauscope.org — the live roast instrument.
  =========================================================================== */

(function () {
  "use strict";

  /* --- the roast -------------------------------------------------------- *
   * A 250 g natural Ethiopia on a small electric drum. Charge temperature is
   * what the bean probe reads at the moment the beans land on it, which is
   * the drum, not the beans — hence the dive to the turning point.          */

  var DURATION = 672;          // seconds, charge to drop
  var SPAN     = 700;          // seconds of x axis
  var T_MIN    = 60, T_MAX = 220;   // °C of y axis
  var R_MAX    = 32;           // °C/min, right-hand axis

  var TP = 88;                 // turning point
  var CHARGE_T = 200;          // bean probe reading at charge
  var TP_T = 89;

  // Bean temperature after the turning point.
  var BT = [
    [88, 89], [150, 112], [220, 132], [295, 150],
    [380, 167], [470, 182], [566, 196], [620, 201], [672, 205]
  ];

  // Environment temperature. On a radiant drum the environment probe sits
  // below the bean probe once the charge dive is over — the opposite of a
  // classical roaster, and a thing people misread as a fault.
  var ET = [
    [0, 205], [40, 150], [88, 115], [150, 132], [220, 146], [295, 158],
    [380, 168], [470, 178], [566, 190], [672, 199]
  ];

  var MILESTONES = [
    { t: 88,  label: "TP",  temp: 89 },
    { t: 295, label: "DRY", temp: 150 },
    { t: 566, label: "FC",  temp: 196 },
    { t: 672, label: "DROP", temp: 205 }
  ];

  // What the assistant would be saying at that moment, and the phase it is in.
  var SCRIPT = [
    { from: 0,   phase: "Charge",      say: "Charge now — drum at 200 °C" },
    { from: 88,  phase: "Drying",      say: "Turning point 1:28. Hold the heat — dry end due 4:55." },
    { from: 295, phase: "Maillard",    say: "Dry end on plan. Step the heat down to 70 % at 6:10." },
    { from: 430, phase: "Maillard",    say: "8 s ahead of plan. First crack expected 9:24." },
    { from: 566, phase: "Development", say: "First crack. Drop window opens at 10:58." },
    { from: 640, phase: "Development", say: "Drop in 12 s — projected development 16.5 %." },
    { from: 672, phase: "Dropped",     say: "Dropped 11:12 at 205 °C. Development 16.5 %, on plan." }
  ];

  /* --- interpolation ----------------------------------------------------- *
   * Monotone cubic (Fritsch–Carlson): a plain cubic spline overshoots on a
   * curve that flattens like this one, and an overshoot here would draw a
   * bean temperature that goes back down before the drop.                   */

  function monotone(points) {
    var n = points.length;
    var xs = [], ys = [];
    for (var i = 0; i < n; i++) { xs.push(points[i][0]); ys.push(points[i][1]); }

    var dys = [], dxs = [], ms = [];
    for (i = 0; i < n - 1; i++) {
      var dx = xs[i + 1] - xs[i];
      var dy = ys[i + 1] - ys[i];
      dxs.push(dx); dys.push(dy); ms.push(dy / dx);
    }

    var c1 = [ms[0]];
    for (i = 0; i < ms.length - 1; i++) {
      var m = ms[i], mNext = ms[i + 1];
      if (m * mNext <= 0) {
        c1.push(0);
      } else {
        var dxa = dxs[i], dxb = dxs[i + 1], common = dxa + dxb;
        c1.push(3 * common / ((common + dxb) / m + (common + dxa) / mNext));
      }
    }
    c1.push(ms[ms.length - 1]);

    return function (x) {
      if (x <= xs[0]) { return ys[0]; }
      if (x >= xs[n - 1]) { return ys[n - 1]; }
      var k = n - 2;
      while (k > 0 && xs[k] > x) { k--; }
      var h = xs[k + 1] - xs[k], t = (x - xs[k]) / h;
      var t2 = t * t, t3 = t2 * t;
      return (2 * t3 - 3 * t2 + 1) * ys[k] +
             (t3 - 2 * t2 + t) * h * c1[k] +
             (-2 * t3 + 3 * t2) * ys[k + 1] +
             (t3 - t2) * h * c1[k + 1];
    };
  }

  var btPost = monotone(BT);
  var etAt = monotone(ET);

  function btAt(t) {
    if (t >= TP) { return btPost(t); }
    // The charge dive: an exponential fall from drum temperature onto the beans.
    return TP_T + (CHARGE_T - TP_T) * Math.exp(-4.2 * (t / TP));
  }

  function rorAt(t) {
    if (t < TP) { return 0; }
    var d = 6;
    var a = Math.max(TP, t - d), b = Math.min(DURATION, t + d);
    if (b <= a) { return 0; }
    return (btAt(b) - btAt(a)) / (b - a) * 60;
  }

  function clock(t) {
    var s = Math.max(0, Math.round(t));
    var m = Math.floor(s / 60);
    var r = s % 60;
    return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r;
  }

  function scriptAt(t) {
    var line = SCRIPT[0];
    for (var i = 0; i < SCRIPT.length; i++) {
      if (t >= SCRIPT[i].from) { line = SCRIPT[i]; }
    }
    return line;
  }

  /* --- drawing ----------------------------------------------------------- */

  var canvas = document.querySelector("[data-roast-curve]");
  if (!canvas) { return; }
  var ctx = canvas.getContext("2d");
  if (!ctx) { return; }

  var out = {
    time:  document.querySelector('[data-readout="time"]'),
    bt:    document.querySelector('[data-readout="bt"]'),
    ror:   document.querySelector('[data-readout="ror"]'),
    say:   document.querySelector('[data-readout="say"]'),
    phase: document.querySelector("[data-scope-phase]")
  };

  var W = 0, H = 0;                 // CSS pixels
  var PAD = { top: 26, right: 58, bottom: 34, left: 46 };
  var theme = {};

  function readTheme() {
    var s = getComputedStyle(document.documentElement);
    function v(name, fallback) {
      var got = s.getPropertyValue(name).trim();
      return got || fallback;
    }
    theme = {
      bt:    v("--bt", "#E6D3B5"),
      et:    v("--et", "#89B4FA"),
      ror:   v("--ror", "#F9E2AF"),
      mark:  v("--mark", "#F38BA8"),
      grid:  v("--grid", "rgba(205,214,244,0.07)"),
      faint: v("--ink-faint", "#6C7086"),
      ink:   v("--ink", "#CDD6F4")
    };
  }

  function resize() {
    var rect = canvas.getBoundingClientRect();
    if (!rect.width) { return false; }
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = rect.width;
    H = rect.width * (520 / 1120);
    canvas.style.height = H + "px";
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return true;
  }

  function xOf(t) { return PAD.left + (t / SPAN) * (W - PAD.left - PAD.right); }
  function yOf(temp) {
    var h = H - PAD.top - PAD.bottom;
    return PAD.top + h - ((temp - T_MIN) / (T_MAX - T_MIN)) * h;
  }
  function yOfRor(r) {
    var h = H - PAD.top - PAD.bottom;
    return PAD.top + h - (r / R_MAX) * h;
  }

  function mono(size, weight) {
    return (weight || 400) + " " + size + "px \"JetBrains Mono\", ui-monospace, Menlo, monospace";
  }

  function drawGrid() {
    ctx.save();
    ctx.strokeStyle = theme.grid;
    ctx.lineWidth = 1;
    ctx.fillStyle = theme.faint;
    ctx.font = mono(10, 400);

    var temp;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (temp = 80; temp <= 200; temp += 40) {
      var y = Math.round(yOf(temp)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(PAD.left, y);
      ctx.lineTo(W - PAD.right, y);
      ctx.stroke();
      ctx.fillText(String(temp), PAD.left - 8, y);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (var t = 0; t <= 600; t += 120) {
      var x = Math.round(xOf(t)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, PAD.top);
      ctx.lineTo(x, H - PAD.bottom);
      ctx.stroke();
      ctx.fillText(clock(t), x, H - PAD.bottom + 8);
    }

    // Right-hand axis belongs to the rate of rise, so it is labelled in its
    // own colour rather than the neutral one.
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillStyle = theme.ror;
    for (var r = 8; r <= 24; r += 8) {
      ctx.fillText(String(r), W - PAD.right + 8, yOfRor(r));
    }
    ctx.restore();
  }

  function trace(fn, until, colour, width, dashed) {
    ctx.save();
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (dashed) { ctx.setLineDash([4, 5]); }
    ctx.beginPath();
    var started = false;
    for (var t = 0; t <= until; t += 2) {
      var p = fn(t);
      if (p === null) { started = false; continue; }
      if (!started) { ctx.moveTo(p[0], p[1]); started = true; }
      else { ctx.lineTo(p[0], p[1]); }
    }
    ctx.stroke();
    ctx.restore();
  }

  function drawFlags(until) {
    ctx.save();
    for (var i = 0; i < MILESTONES.length; i++) {
      var m = MILESTONES[i];
      if (m.t > until) { continue; }
      var x = xOf(m.t), y = yOf(m.temp);

      ctx.strokeStyle = theme.mark;
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 4]);
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x, H - PAD.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      ctx.fillStyle = theme.mark;
      ctx.beginPath();
      ctx.arc(x, y, 3.5, 0, Math.PI * 2);
      ctx.fill();

      ctx.font = mono(10, 700);
      ctx.textBaseline = "bottom";
      var atRightEdge = m.t > SPAN * 0.86;
      ctx.textAlign = atRightEdge ? "right" : "left";
      ctx.fillText(m.label, x + (atRightEdge ? -8 : 8), y - 7);
    }
    ctx.restore();
  }

  function render(until) {
    ctx.clearRect(0, 0, W, H);
    drawGrid();

    trace(function (t) { return [xOf(t), yOfRor(rorAt(t))]; }, until, theme.ror, 1.5, true);
    trace(function (t) { return [xOf(t), yOf(etAt(t))]; }, until, theme.et, 1.5, false);
    trace(function (t) { return [xOf(t), yOf(btAt(t))]; }, until, theme.bt, 2.75, false);

    drawFlags(until);

    // The head of the trace, so the eye knows where "now" is.
    if (until < DURATION) {
      ctx.save();
      ctx.fillStyle = theme.bt;
      ctx.beginPath();
      ctx.arc(xOf(until), yOf(btAt(until)), 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // Legend, bottom left, out of the curve's way.
    ctx.save();
    ctx.font = mono(10, 700);
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    var items = [["Bean", theme.bt], ["Environment", theme.et], ["Rate of rise", theme.ror]];
    var lx = PAD.left + 6;
    for (var i = 0; i < items.length; i++) {
      ctx.fillStyle = items[i][1];
      ctx.fillRect(lx, PAD.top + 5, 14, 2);
      ctx.fillText(items[i][0], lx + 20, PAD.top + 6);
      lx += 20 + ctx.measureText(items[i][0]).width + 18;
    }
    ctx.restore();
  }

  function updateReadouts(t) {
    var line = scriptAt(t);
    if (out.time) { out.time.textContent = clock(t); }
    if (out.bt) {
      out.bt.innerHTML = "";
      out.bt.appendChild(document.createTextNode(String(Math.round(btAt(t)))));
      out.bt.appendChild(unit("°C"));
    }
    if (out.ror) {
      out.ror.innerHTML = "";
      out.ror.appendChild(document.createTextNode(rorAt(t).toFixed(1)));
      out.ror.appendChild(unit("°/min"));
    }
    if (out.say) { out.say.textContent = line.say; }
    if (out.phase) { out.phase.textContent = line.phase; }
  }

  function unit(text) {
    var el = document.createElement("span");
    el.className = "unit";
    el.textContent = text;
    return el;
  }

  /* --- the run ----------------------------------------------------------- */

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var lastUntil = DURATION;
  var running = false;

  function play() {
    if (running) { return; }
    running = true;
    var started = null;
    var span = 2600;

    function frame(now) {
      if (started === null) { started = now; }
      var p = Math.min(1, (now - started) / span);
      var eased = 1 - Math.pow(1 - p, 2.4);      // fast start, settles into the drop
      lastUntil = eased * DURATION;
      render(lastUntil);
      updateReadouts(lastUntil);
      if (p < 1) { requestAnimationFrame(frame); }
      else { running = false; }
    }
    requestAnimationFrame(frame);
  }

  function still() {
    lastUntil = DURATION;
    render(lastUntil);
    updateReadouts(DURATION);
  }

  function boot() {
    readTheme();
    if (!resize()) { return; }
    if (reduced.matches) {
      still();
      return;
    }

    // The demonstration now sits below the marketing introduction. Keep it at
    // charge until it is actually visible, otherwise the whole roast would
    // finish while the visitor is still reading the hero.
    lastUntil = 0;
    render(0);
    updateReadouts(0);
    if ("IntersectionObserver" in window) {
      var demoWatcher = new IntersectionObserver(function (entries) {
        if (entries[0] && entries[0].isIntersecting) {
          demoWatcher.disconnect();
          play();
        }
      }, { rootMargin: "0px 0px -18% 0px", threshold: 0.18 });
      demoWatcher.observe(canvas);
    } else {
      play();
    }
  }

  // Redraw on anything that changes the geometry or the palette. The curve is
  // regenerated rather than scaled, so it stays sharp at any width.
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      if (resize()) { render(lastUntil); }
    }, 120);
  });

  function repaint() {
    readTheme();
    render(lastUntil);
  }
  if (window.matchMedia) {
    var dark = window.matchMedia("(prefers-color-scheme: dark)");
    if (dark.addEventListener) { dark.addEventListener("change", repaint); }
  }
  new MutationObserver(repaint).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"]
  });

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () { render(lastUntil); });
  }

  boot();
})();
