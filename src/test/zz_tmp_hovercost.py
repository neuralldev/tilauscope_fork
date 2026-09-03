import time
from PyQt6.QtWidgets import QWidget, QLineEdit, QVBoxLayout

QSS = """
QLineEdit {{
    border: 2px solid rgb({r}, 180, 200);
    border-radius: 5px;
    padding: 3px;
    background-color: #181825;
    color: #CDD6F4;
    }}
QToolTip {{ color: #CDD6F4; background: #313244; border: 1px solid #45475A; }}
"""

def test_zz_measure(qapp):
    host = QWidget()
    lay = QVBoxLayout(host)
    fields = []
    for _ in range(24):
        e = QLineEdit()
        lay.addWidget(e)
        fields.append(e)
    # realistic: a big parent sheet the child must resolve against
    big = "\n".join(
        f"QWidget#w{i} {{ background:#1E1E2E; color:#CDD6F4; border:1px solid #313244; }}"
        for i in range(300))
    host.setStyleSheet(big + "\nQLineEdit { background:#181825; border:1px solid #45475A; }")
    host.resize(400, 800)
    host.show()
    qapp.processEvents()

    w = fields[0]
    # warm up
    for i in range(5):
        w.setStyleSheet(QSS.format(r=i))
    qapp.processEvents()

    N = 200
    t0 = time.perf_counter()
    for i in range(N):
        w.setStyleSheet(QSS.format(r=i % 255))
    t1 = time.perf_counter()
    per_call_ms = (t1 - t0) / N * 1000
    frames = 250 / 16.7  # a 250 ms animation at ~60 fps
    print(f"\n[MEASURE] setStyleSheet on one field: {per_call_ms:.3f} ms/call")
    print(f"[MEASURE] one hover fade ({frames:.0f} frames): {per_call_ms*frames:.1f} ms of restyle")
    print(f"[MEASURE] crossing 24 fields: {per_call_ms*frames*24:.0f} ms total")

    # forced style resolution: setStyleSheet is lazy, the parse lands at repaint
    t0 = time.perf_counter()
    for i in range(N):
        w.setStyleSheet(QSS.format(r=i % 255))
        w.ensurePolished()
        w.grab()
    t1 = time.perf_counter()
    forced = (t1 - t0) / N * 1000
    print(f"[MEASURE] with forced polish+paint: {forced:.3f} ms/call")
    print(f"[MEASURE] one forced fade (15 frames): {forced*frames:.1f} ms")
    print(f"[MEASURE] crossing 24 fields, forced: {forced*frames*24:.0f} ms")

    # cost of the f-string alone, to separate parse cost from string build
    t0 = time.perf_counter()
    for i in range(N):
        QSS.format(r=i % 255)
    t1 = time.perf_counter()
    print(f"[MEASURE] string build alone: {(t1-t0)/N*1000:.4f} ms/call")
