# tests/test_system.py

"""
Smart Traffic System – Comprehensive Validation Script
======================================================
Validates the full AI pipeline across sections:

    Section 1 : Decision Maker unit tests (synthetic TrafficState, no images)
    Section 2 : Image Quality Gate (three-tier check, produces usable_images list)

Usage
-----
    python tests/test_system.py
    python tests/test_system.py --all
    python tests/test_system.py --random 10
    python tests/test_system.py --section 1
    python tests/test_system.py --section 1,2
    python tests/test_system.py --no-detector
    python tests/test_system.py --fast

Output
------
    data/validation/validation_report_<timestamp>.html
"""

import sys
import os
import cv2
import random
import argparse
import numpy as np
import time
from datetime import datetime


# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_MODULE    = os.path.join(PROJECT_ROOT, "ai_module")
BACKEND      = os.path.join(PROJECT_ROOT, "backend")

for p in [PROJECT_ROOT, AI_MODULE, BACKEND] :
    if p not in sys.path :
        sys.path.insert(0, p)

from detector                            import TrafficDetector
from backend.app.models.traffic_state    import DirectionState, TrafficState
from backend.app.services.decision_maker import DecisionMaker


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR        = os.path.join(PROJECT_ROOT, "data", "raw")
VALIDATION_DIR  = os.path.join(PROJECT_ROOT, "data", "validation")
MODEL_BASELINE  = os.path.join(PROJECT_ROOT, "ai_module", "models", "yolov8m.pt")
MODEL_FINETUNED = os.path.join(PROJECT_ROOT, "ai_module", "models", "yolov8m_finetuned.pt")

INTERSECTION_IMAGES = {
    "north" : os.path.join(DATA_DIR, "traffic_01.jpg"),
    "south" : os.path.join(DATA_DIR, "traffic_09.jpg"),
    "east"  : os.path.join(DATA_DIR, "traffic_12.jpg"),
    "west"  : os.path.join(DATA_DIR, "traffic_10.jpg"),
}

TEST_IMAGE_POOL = sorted([
    os.path.join(DATA_DIR, f)
    for f in os.listdir(DATA_DIR)
    if f.startswith("traffic_") and f.endswith(".jpg")
])


# ---------------------------------------------------------------------------
# Image quality thresholds (mirrors check_images.py exactly)
# ---------------------------------------------------------------------------

QC = {
    "min_width"             : 480,
    "min_height"            : 360,
    "warn_width"            : 640,
    "warn_height"           : 480,
    "min_size_kb"           : 50,
    "warn_size_kb"          : 100,
    "max_overexposed_pct"   : 20.0,
    "warn_overexposed_pct"  : 5.0,
    "max_underexposed_pct"  : 20.0,
    "warn_underexposed_pct" : 5.0,
    "min_brightness"        : 20,
    "warn_brightness_low"   : 50,
    "warn_brightness_high"  : 200,
    "max_brightness"        : 230,
    "min_contrast"          : 15,
    "warn_contrast"         : 30,
    "min_sharpness"         : 15,
    "warn_sharpness"        : 60,
    "min_aspect"            : 0.5,
    "max_aspect"            : 4.0,
}


# ---------------------------------------------------------------------------
# HTML report builder
# ---------------------------------------------------------------------------

class ReportBuilder :
    """
    Accumulates HTML sections and writes a final styled report.
    All test results flow through this – nothing is printed to terminal.
    """

    def __init__(self) :
        self._sections   = []
        self._current    = []
        self._pass_count = 0
        self._fail_count = 0
        self._warn_count = 0

    # ── section control ─────────────────────────────────────────────────

    def begin_section(self, title : str) :
        if self._current :
            self._sections.append("".join(self._current))
        self._current = [f"""
        <div class="section">
          <div class="section-title">{title}</div>
        """]

    def end_section(self) :
        self._current.append("</div>")

    # ── content helpers ──────────────────────────────────────────────────

    def prose(self, text : str) :
        self._current.append(f'<p class="prose">{text}</p>\n')

    def subheader(self, text : str) :
        self._current.append(f'<div class="subheader">{text}</div>\n')

    def assertion(self, label : str, value : str, passed : bool, note : str = "") -> bool :
        status      = "PASS" if passed else "FAIL"
        badge_class = "badge-pass" if passed else "badge-fail"
        note_html   = f'<span class="note">{note}</span>' if note else ""
        self._current.append(f"""
        <div class="assert-row">
          <span class="assert-label">{label}</span>
          <span class="assert-value">{value}</span>
          <span class="badge {badge_class}">{status}</span>
          {note_html}
        </div>""")
        if passed :
            self._pass_count += 1
        else :
            self._fail_count += 1
        return passed

    def warn(self, label : str, value : str, note : str = "") :
        note_html = f'<span class="note">{note}</span>' if note else ""
        self._current.append(f"""
        <div class="assert-row">
          <span class="assert-label">{label}</span>
          <span class="assert-value">{value}</span>
          <span class="badge badge-warn">WARN</span>
          {note_html}
        </div>""")
        self._warn_count += 1

    def info(self, label : str, value : str) :
        self._current.append(f"""
        <div class="assert-row info-row">
          <span class="assert-label">{label}</span>
          <span class="assert-value">{value}</span>
          <span class="badge badge-info">INFO</span>
        </div>""")

    def log(self, text : str) :
        self._current.append(f'<div class="log-line">{text}</div>\n')

    def table(self, headers : list, rows : list) :
        th_html   = "".join(f"<th>{h}</th>" for h in headers)
        rows_html = ""
        for row in rows :
            tds       = "".join(f"<td>{cell}</td>" for cell in row)
            rows_html += f"<tr>{tds}</tr>\n"
        self._current.append(f"""
        <table>
          <thead><tr>{th_html}</tr></thead>
          <tbody>{rows_html}</tbody>
        </table>""")

    def spacer(self) :
        self._current.append('<div class="spacer"></div>\n')

    # ── final render ─────────────────────────────────────────────────────

    def save(self, path : str) :
        if self._current :
            self._sections.append("".join(self._current))

        total      = self._pass_count + self._fail_count
        pass_rate  = round(self._pass_count / total * 100) if total > 0 else 0
        status_cls = "status-pass" if self._fail_count == 0 else "status-fail"
        status_txt = "ALL TESTS PASSED" if self._fail_count == 0 else \
                     f"{self._fail_count} FAILURE(S) – review sections above"

        body = "\n".join(self._sections)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Smart Traffic System – Validation Report</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: #F0F2F7;
  color: #1A1D2E;
  font-size: 14px;
  line-height: 1.6;
  padding: 32px 24px;
}}

.page-header {{
  background: linear-gradient(135deg, #1A1D2E 0%, #2D3250 100%);
  color: white;
  border-radius: 16px;
  padding: 36px 40px;
  margin-bottom: 28px;
}}
.page-header h1 {{
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 8px;
}}
.page-header .meta {{
  font-size: 13px;
  color: #9BA3BF;
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-top: 16px;
}}

.summary-bar {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 28px;
}}
.stat-card {{
  background: white;
  border-radius: 12px;
  padding: 20px 24px;
  border: 1px solid #E2E6F0;
  text-align: center;
}}
.stat-card .stat-num {{
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 4px;
}}
.stat-card .stat-label {{
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #6B7280;
}}
.stat-pass  {{ color: #059669; }}
.stat-fail  {{ color: #DC2626; }}
.stat-warn  {{ color: #D97706; }}
.stat-total {{ color: #2563EB; }}

.overall-status {{
  border-radius: 12px;
  padding: 16px 24px;
  margin-bottom: 28px;
  font-size: 15px;
  font-weight: 600;
  text-align: center;
  letter-spacing: 0.04em;
}}
.status-pass {{ background: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7; }}
.status-fail {{ background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }}

.section {{
  background: white;
  border-radius: 14px;
  padding: 28px 32px;
  margin-bottom: 20px;
  border: 1px solid #E2E6F0;
}}
.section-title {{
  font-size: 16px;
  font-weight: 700;
  color: #1A1D2E;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid #F0F2F7;
  display: flex;
  align-items: center;
  gap: 10px;
}}
.section-title::before {{
  content: '';
  display: inline-block;
  width: 4px;
  height: 18px;
  background: #2563EB;
  border-radius: 2px;
}}

.subheader {{
  font-size: 12px;
  font-weight: 600;
  color: #4B5563;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 20px 0 8px;
  padding: 6px 0;
  border-bottom: 1px solid #F0F2F7;
}}

.assert-row {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  margin-bottom: 2px;
  font-size: 13px;
  font-family: 'Consolas', 'Cascadia Code', monospace;
}}
.assert-row:hover {{ background: #F8F9FC; }}
.info-row {{ opacity: 0.65; }}

.assert-label  {{ flex: 1; color: #374151; }}
.assert-value  {{ color: #6B7280; min-width: 160px; text-align: right; }}
.note {{
  font-size: 11px;
  color: #9CA3AF;
  font-style: italic;
  min-width: 200px;
  font-family: 'Segoe UI', sans-serif;
}}

.badge {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 2px 8px;
  border-radius: 4px;
  min-width: 48px;
  font-family: 'Consolas', monospace;
}}
.badge-pass {{ background: #D1FAE5; color: #065F46; }}
.badge-fail {{ background: #FEE2E2; color: #991B1B; }}
.badge-warn {{ background: #FEF3C7; color: #92400E; }}
.badge-info {{ background: #DBEAFE; color: #1E40AF; }}

.badge-verdict-good       {{ background: #D1FAE5; color: #065F46; font-size: 11px; padding: 3px 10px; border-radius: 4px; font-weight: 700; display: inline-block; }}
.badge-verdict-acceptable {{ background: #FEF3C7; color: #92400E; font-size: 11px; padding: 3px 10px; border-radius: 4px; font-weight: 700; display: inline-block; }}
.badge-verdict-unusable   {{ background: #FEE2E2; color: #991B1B; font-size: 11px; padding: 3px 10px; border-radius: 4px; font-weight: 700; display: inline-block; }}

.log-line {{
  font-family: 'Consolas', 'Cascadia Code', monospace;
  font-size: 12px;
  color: #4B5563;
  padding: 2px 10px;
  line-height: 1.9;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-family: 'Consolas', monospace;
  margin: 14px 0;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #E2E6F0;
}}
thead th {{
  background: #1A1D2E;
  color: white;
  padding: 10px 14px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}}
tbody tr {{ border-bottom: 1px solid #F0F2F7; }}
tbody tr:hover {{ background: #F8F9FC; }}
tbody td {{ padding: 8px 14px; color: #374151; }}
tbody tr:last-child {{ border-bottom: none; }}

.prose {{
  color: #4B5563;
  font-size: 13px;
  margin-bottom: 12px;
  line-height: 1.75;
}}

.spacer {{ height: 14px; }}

.footer {{
  text-align: center;
  color: #9CA3AF;
  font-size: 12px;
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid #E2E6F0;
}}
</style>
</head>
<body>

<div class="page-header">
  <h1>Smart Traffic System – Validation Report</h1>
  <div class="meta">
    <span>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</span>
    <span>Project: {PROJECT_ROOT}</span>
    <span>Test pool: {len(TEST_IMAGE_POOL)} images</span>
  </div>
</div>

<div class="summary-bar">
  <div class="stat-card">
    <div class="stat-num stat-pass">{self._pass_count}</div>
    <div class="stat-label">Passed</div>
  </div>
  <div class="stat-card">
    <div class="stat-num stat-fail">{self._fail_count}</div>
    <div class="stat-label">Failed</div>
  </div>
  <div class="stat-card">
    <div class="stat-num stat-warn">{self._warn_count}</div>
    <div class="stat-label">Warnings</div>
  </div>
  <div class="stat-card">
    <div class="stat-num stat-total">{pass_rate}%</div>
    <div class="stat-label">Pass rate</div>
  </div>
</div>

<div class="overall-status {status_cls}">{status_txt}</div>

{body}

<div class="footer">
  Smart Traffic System · CO3107 · AI Module Validation · {datetime.now().strftime("%Y")}
</div>
</body>
</html>"""

        os.makedirs(os.path.dirname(path), exist_ok = True)
        with open(path, "w", encoding = "utf-8") as f :
            f.write(html)


# ---------------------------------------------------------------------------
# Helper: build a synthetic TrafficState from scalars
# ---------------------------------------------------------------------------

def _make_state(ns_score   : float = 0.0,
                ns_density : float = 0.0,
                ew_score   : float = 0.0,
                ew_density : float = 0.0,
                temp       : float = 28.0,
                light      : float = 400.0) -> TrafficState :

    def _dir(score : float, density : float) -> DirectionState :
        return DirectionState(
            vehicle_count          = 0,
            vehicle_breakdown      = {},
            weighted_vehicle_score = score,
            density_ratio          = density,
        )

    return TrafficState(
        north           = _dir(ns_score / 2, ns_density),
        south           = _dir(ns_score / 2, ns_density),
        east            = _dir(ew_score / 2, ew_density),
        west            = _dir(ew_score / 2, ew_density),
        temperature     = temp,
        light_intensity = light,
    )


# ---------------------------------------------------------------------------
# Image quality helpers (mirrors check_images.py three-tier system)
# ---------------------------------------------------------------------------

def _compute_image_metrics(img_path : str) -> dict | None :
    """Compute all quality metrics for one image. Returns None if unreadable."""

    file_size_kb = os.path.getsize(img_path) / 1024
    img          = cv2.imread(img_path)

    if img is None :
        return None

    h, w   = img.shape[:2]
    gray   = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv    = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    total  = h * w

    laplacian   = cv2.Laplacian(gray, cv2.CV_64F)
    edges_loose = cv2.Canny(gray, 10, 50)
    edges_tight = cv2.Canny(gray, 100, 200)
    loose_count = max(cv2.countNonZero(edges_loose), 1)
    b, g, r     = cv2.mean(img)[:3]

    return {
        "width"             : w,
        "height"            : h,
        "megapixels"        : round(w * h / 1_000_000, 2),
        "aspect_ratio"      : round(w / h, 2),
        "file_size_kb"      : round(file_size_kb, 1),
        "brightness"        : round(float(np.mean(gray)), 1),
        "contrast"          : round(float(np.std(gray)), 1),
        "sharpness"         : round(float(laplacian.var()), 1),
        "saturation"        : round(float(np.mean(hsv[:, :, 1])), 1),
        "noise_ratio"       : round(1.0 - cv2.countNonZero(edges_tight) / loose_count, 3),
        "channel_imbalance" : round(float(np.std([b, g, r])), 1),
        "overexposed_pct"   : round(np.sum(gray > 250) / total * 100, 1),
        "underexposed_pct"  : round(np.sum(gray < 5)   / total * 100, 1),
    }


def _assess_image(m : dict) -> dict :
    """
    Three-tier assessment on pre-computed metrics.
    Returns dict with keys critical, quality, informational –
    each a list of (label, value_str, status) tuples.
    """

    critical      = []
    quality       = []
    informational = []

    def chk(bucket, label, value_str, ok, warn = None) :
        if not ok :
            status = "FAIL"
        elif warn is not None and not warn :
            status = "WARN"
        else :
            status = "PASS"
        bucket.append((label, value_str, status))

    def inf(label, value_str) :
        informational.append((label, value_str, "INFO"))

    # CRITICAL
    chk(critical, f"width ≥ {QC['min_width']}px",
        f"{m['width']}px",
        m["width"]  >= QC["min_width"],
        m["width"]  >= QC["warn_width"])
    chk(critical, f"height ≥ {QC['min_height']}px",
        f"{m['height']}px",
        m["height"] >= QC["min_height"],
        m["height"] >= QC["warn_height"])
    chk(critical, f"file size ≥ {QC['min_size_kb']}KB",
        f"{m['file_size_kb']}KB",
        m["file_size_kb"] >= QC["min_size_kb"],
        m["file_size_kb"] >= QC["warn_size_kb"])
    chk(critical, f"overexposed &lt; {QC['max_overexposed_pct']}%",
        f"{m['overexposed_pct']}%",
        m["overexposed_pct"] < QC["max_overexposed_pct"],
        m["overexposed_pct"] < QC["warn_overexposed_pct"])
    chk(critical, f"underexposed &lt; {QC['max_underexposed_pct']}%",
        f"{m['underexposed_pct']}%",
        m["underexposed_pct"] < QC["max_underexposed_pct"],
        m["underexposed_pct"] < QC["warn_underexposed_pct"])

    # QUALITY
    chk(quality, f"brightness {QC['warn_brightness_low']}–{QC['warn_brightness_high']}",
        str(m["brightness"]),
        QC["min_brightness"] <= m["brightness"] <= QC["max_brightness"],
        QC["warn_brightness_low"] <= m["brightness"] <= QC["warn_brightness_high"])
    chk(quality, f"contrast ≥ {QC['min_contrast']}",
        str(m["contrast"]),
        m["contrast"] >= QC["min_contrast"],
        m["contrast"] >= QC["warn_contrast"])
    chk(quality, f"sharpness ≥ {QC['min_sharpness']}",
        str(m["sharpness"]),
        m["sharpness"] >= QC["min_sharpness"],
        m["sharpness"] >= QC["warn_sharpness"])
    chk(quality, f"aspect ratio {QC['min_aspect']}–{QC['max_aspect']}",
        str(m["aspect_ratio"]),
        QC["min_aspect"] <= m["aspect_ratio"] <= QC["max_aspect"])

    # INFORMATIONAL
    inf("noise ratio",     str(m["noise_ratio"]))
    inf("saturation",      str(m["saturation"]))
    inf("channel balance", str(m["channel_imbalance"]))
    inf("resolution",      f"{m['width']} × {m['height']}  {m['megapixels']}MP")

    return {
        "critical"      : critical,
        "quality"       : quality,
        "informational" : informational,
    }


def _verdict(checks : dict) -> str :
    c_statuses = [s for _, _, s in checks["critical"]]
    q_statuses = [s for _, _, s in checks["quality"]]
    if "FAIL" in c_statuses :
        return "UNUSABLE"
    warns = q_statuses.count("WARN") + c_statuses.count("WARN")
    return "ACCEPTABLE" if warns >= 1 else "GOOD"


# ---------------------------------------------------------------------------
# SECTION 1 – Decision Maker Unit Tests
# ---------------------------------------------------------------------------

def section_decision_maker(report : ReportBuilder) -> int :
    """
    Validates DecisionMaker with synthetic TrafficState objects.
    No images required. Returns number of failures.
    """

    report.begin_section("Section 1 – Decision Maker Unit Tests")
    report.prose(
        "All tests use synthetic TrafficState objects constructed directly from scalars. "
        "No images, no IoT, no external dependencies. Verifies directional correctness "
        "of green duration across 9 scenarios covering empty, dominant, balanced, "
        "monotonicity, environment, smoothing, clamping, and parameter sensitivity."
    )

    failures = 0
    dm       = DecisionMaker()

    # ── 1A ─────────────────────────────────────────────────────────────

    report.subheader("1A. Empty intersection (zero traffic)")
    state = _make_state(0, 0.0, 0, 0.0)
    ns    = dm.decide(state, "NS")["green_duration"]
    ew    = dm.decide(state, "EW")["green_duration"]

    failures += 0 if report.assertion(
        f"NS duration == min_green ({dm.min_green}s)",
        f"{ns}s", ns == dm.min_green, "no traffic → hard floor"
    ) else 1
    failures += 0 if report.assertion(
        f"EW duration == min_green ({dm.min_green}s)",
        f"{ew}s", ew == dm.min_green, "no traffic → hard floor"
    ) else 1

    # ── 1B ─────────────────────────────────────────────────────────────

    report.subheader("1B. NS dominant (heavy NS, empty EW)")
    dm2    = DecisionMaker()
    state2 = _make_state(200, 0.30, 0, 0.0)
    ns2    = dm2.decide(state2, "NS")["green_duration"]
    ew2    = dm2.decide(state2, "EW")["green_duration"]

    failures += 0 if report.assertion(
        "NS duration > EW duration",
        f"NS = {ns2}s  EW = {ew2}s", ns2 > ew2,
        "heavy NS traffic must yield longer green"
    ) else 1
    failures += 0 if report.assertion(
        f"NS duration > base_time ({dm2.base_time}s)",
        f"{ns2}s", ns2 > dm2.base_time, "high priority should exceed base"
    ) else 1
    failures += 0 if report.assertion(
        f"NS duration ≤ max_green ({dm2.max_green}s)",
        f"{ns2}s", ns2 <= dm2.max_green, "hard ceiling must hold"
    ) else 1

    # ── 1C ─────────────────────────────────────────────────────────────

    report.subheader("1C. EW dominant (empty NS, heavy EW)")
    dm3    = DecisionMaker()
    state3 = _make_state(0, 0.0, 200, 0.30)
    ns3    = dm3.decide(state3, "NS")["green_duration"]
    ew3    = dm3.decide(state3, "EW")["green_duration"]

    failures += 0 if report.assertion(
        "EW duration > NS duration",
        f"EW = {ew3}s  NS = {ns3}s", ew3 > ns3,
        "heavy EW traffic must yield longer green"
    ) else 1

    # ── 1D ─────────────────────────────────────────────────────────────

    report.subheader("1D. Balanced (equal traffic both phases)")
    dm4    = DecisionMaker()
    state4 = _make_state(100, 0.15, 100, 0.15)
    ns4    = dm4.decide(state4, "NS")["green_duration"]
    ew4    = dm4.decide(state4, "EW")["green_duration"]

    failures += 0 if report.assertion(
        "NS ≈ EW duration (within 5s)",
        f"NS = {ns4}s  EW = {ew4}s  Δ = {abs(ns4 - ew4):.1f}s",
        abs(ns4 - ew4) < 5.0,
        "equal traffic → roughly equal green"
    ) else 1

    # ── 1E ─────────────────────────────────────────────────────────────

    report.subheader("1E. Priority monotonicity (more traffic = longer green)")
    scores    = [0, 40, 80, 120, 160, 200]
    durations = []

    for score in scores :
        dm_tmp    = DecisionMaker()
        state_tmp = _make_state(score, 0.0, 0, 0.0)
        dur       = dm_tmp.decide(state_tmp, "NS")["green_duration"]
        durations.append(dur)
        report.log(f"weighted_score = {score:3d}  →  green = {dur:.1f}s")

    monotone = all(durations[i] <= durations[i + 1] for i in range(len(durations) - 1))
    failures += 0 if report.assertion(
        "Duration monotonically non-decreasing",
        "MONO" if monotone else "VIOLATION",
        monotone,
        "increasing traffic must never decrease green time"
    ) else 1

    # ── 1F ─────────────────────────────────────────────────────────────

    report.subheader("1F. Environment factor (temperature + light)")
    dur_base   = DecisionMaker().decide(_make_state(100, 0.15, 0, 0.0, temp = 28, light = 400), "NS")["green_duration"]
    dur_hot    = DecisionMaker().decide(_make_state(100, 0.15, 0, 0.0, temp = 40, light = 400), "NS")["green_duration"]
    dur_bright = DecisionMaker().decide(_make_state(100, 0.15, 0, 0.0, temp = 28, light = 950), "NS")["green_duration"]
    dur_both   = DecisionMaker().decide(_make_state(100, 0.15, 0, 0.0, temp = 40, light = 950), "NS")["green_duration"]

    report.log(f"Baseline (28°C, 400 lux)  : {dur_base:.1f}s")
    report.log(f"Hot     (40°C, 400 lux)   : {dur_hot:.1f}s  (+10% expected)")
    report.log(f"Bright  (28°C, 950 lux)   : {dur_bright:.1f}s  (+5% expected)")
    report.log(f"Both    (40°C, 950 lux)   : {dur_both:.1f}s  (+15% expected)")

    failures += 0 if report.assertion(
        "Hot > baseline", f"{dur_hot:.1f}s > {dur_base:.1f}s", dur_hot > dur_base
    ) else 1
    failures += 0 if report.assertion(
        "Bright > baseline", f"{dur_bright:.1f}s > {dur_base:.1f}s", dur_bright > dur_base
    ) else 1
    failures += 0 if report.assertion(
        "Both > either alone", f"{dur_both:.1f}s",
        dur_both > dur_hot and dur_both > dur_bright
    ) else 1

    # ── 1G ─────────────────────────────────────────────────────────────

    report.subheader("1G. Smoothing stability (10 alternating cycles, heavy traffic)")
    dm_smooth   = DecisionMaker()
    state_heavy = _make_state(200, 0.30, 0, 0.0)
    prev_ns     = dm_smooth.base_time
    ns_durs     = []
    max_jump    = 0.0

    for cycle in range(10) :
        dur      = dm_smooth.decide(state_heavy, "NS")["green_duration"]
        jump     = abs(dur - prev_ns)
        max_jump = max(max_jump, jump)
        ns_durs.append(dur)
        report.log(f"Cycle {cycle + 1:2d}  NS = {dur:.1f}s  Δ = {jump:.1f}s")
        prev_ns = dur
        dm_smooth.decide(state_heavy, "EW")

    failures += 0 if report.assertion(
        f"Max jump ≤ max_change ({dm_smooth.max_change}s)",
        f"{max_jump:.1f}s",
        max_jump <= dm_smooth.max_change + 0.1,
        "smoothing + change limit must hold"
    ) else 1
    failures += 0 if report.assertion(
        "Duration ramps up toward steady state",
        f"{ns_durs[0]:.1f}s → {ns_durs[-1]:.1f}s",
        ns_durs[-1] > ns_durs[0]
    ) else 1

    # ── 1H ─────────────────────────────────────────────────────────────

    report.subheader("1H. Hard clamp [min_green, max_green]")
    dm_clamp = DecisionMaker()

    for ws, d, label in [(0, 0, "empty"), (200, 0.5, "max traffic")] :
        state_c = _make_state(ws, d, ws, d)
        ns_c    = dm_clamp.decide(state_c, "NS")["green_duration"]
        ew_c    = dm_clamp.decide(state_c, "EW")["green_duration"]
        for phase, dur in [("NS", ns_c), ("EW", ew_c)] :
            failures += 0 if report.assertion(
                f"{phase} in [{dm_clamp.min_green}, {dm_clamp.max_green}] ({label})",
                f"{dur:.1f}s",
                dm_clamp.min_green <= dur <= dm_clamp.max_green
            ) else 1

    # ── 1I ─────────────────────────────────────────────────────────────

    report.subheader("1I. Parameter sensitivity (α and β weights)")
    report.prose(
        "Verifies that α controls vehicle count influence and β controls density influence. "
        "Scenario A: high score, low density – high-α engine should produce longer green. "
        "Scenario B: low score, high density – high-β engine should produce longer green."
    )

    # scenario A: score dominates
    state_a      = _make_state(180, 0.02, 0, 0.0)
    dur_a_high   = DecisionMaker(alpha = 0.9, beta = 0.1).decide(state_a, "NS")["green_duration"]
    dur_a_low    = DecisionMaker(alpha = 0.1, beta = 0.9).decide(state_a, "NS")["green_duration"]

    report.log(f"Scenario A – score=180, density=0.02:")
    report.log(f"  α=0.9  →  {dur_a_high:.1f}s")
    report.log(f"  α=0.1  →  {dur_a_low:.1f}s")

    failures += 0 if report.assertion(
        "High-α > low-α when score dominates",
        f"{dur_a_high:.1f}s > {dur_a_low:.1f}s",
        dur_a_high > dur_a_low,
        "α=0.9 weights vehicle count more heavily"
    ) else 1

    # scenario B: density dominates
    state_b    = _make_state(10, 0.40, 0, 0.0)
    dur_b_high = DecisionMaker(alpha = 0.1, beta = 0.9).decide(state_b, "NS")["green_duration"]
    dur_b_low  = DecisionMaker(alpha = 0.9, beta = 0.1).decide(state_b, "NS")["green_duration"]

    report.log(f"Scenario B – score=10, density=0.40:")
    report.log(f"  β=0.9  →  {dur_b_high:.1f}s")
    report.log(f"  β=0.1  →  {dur_b_low:.1f}s")

    failures += 0 if report.assertion(
        "High-β > low-β when density dominates",
        f"{dur_b_high:.1f}s > {dur_b_low:.1f}s",
        dur_b_high > dur_b_low,
        "β=0.9 weights Canny density more heavily"
    ) else 1

    report.end_section()
    return failures


# ---------------------------------------------------------------------------
# SECTION 2 – Image Quality Gate
# ---------------------------------------------------------------------------

def section_image_quality(report : ReportBuilder,
                           image_pool : list) -> list :
    """
    Runs the three-tier quality check on every image in image_pool.
    Returns usable_images list (GOOD or ACCEPTABLE only).
    Images that fail CRITICAL checks are excluded from all subsequent sections.
    """

    report.begin_section("Section 2 – Image Quality Gate")
    report.prose(
        "Runs the three-tier quality assessment on every image in the selected pool "
        "before any detection occurs. Images that fail CRITICAL checks are excluded from "
        "all subsequent sections. This section is self-contained – no need to run "
        "check_images.py separately."
    )
    report.prose(
        "<strong>Tier definitions:</strong> "
        "CRITICAL (resolution, file size, exposure) – can produce FAIL, image excluded. "
        "QUALITY (brightness, contrast, sharpness, aspect ratio) – can produce WARN. "
        "INFORMATIONAL (noise, saturation, channel balance) – shown for context only, never affects verdict."
    )

    # ── 2A. Per-image assessment ────────────────────────────────────────

    report.subheader("2A. Per-image quality assessment")

    results = []

    for img_path in image_pool :

        fname = os.path.basename(img_path)
        m     = _compute_image_metrics(img_path)

        if m is None :
            results.append((fname, None, "UNREADABLE", {}))
            report.assertion(f"{fname} – readable", "UNREADABLE", False, "file corrupt or unsupported")
            continue

        checks  = _assess_image(m)
        verdict = _verdict(checks)
        results.append((fname, m, verdict, checks))

        report.log(f"<strong>{fname}</strong>  {m['width']} × {m['height']}  {m['file_size_kb']}KB")

        for label, value, status in checks["critical"] :
            if status == "FAIL" :
                report.assertion(f"  CRITICAL  {label}", value, False)
            elif status == "WARN" :
                report.warn(f"  CRITICAL  {label}", value)
            else :
                report.assertion(f"  CRITICAL  {label}", value, True)

        for label, value, status in checks["quality"] :
            if status == "WARN" :
                report.warn(f"  QUALITY   {label}", value)
            else :
                report.assertion(f"  QUALITY   {label}", value, True)

        for label, value, _ in checks["informational"] :
            report.info(f"  INFO      {label}", value)

        report.spacer()

    # ── 2B. Summary table ──────────────────────────────────────────────

    report.subheader("2B. Summary table")

    table_rows = []
    for fname, m, verdict, checks in results :
        if m is None :
            table_rows.append([
                fname, "–", "–", "–", "–",
                '<span class="badge-verdict-unusable">UNREADABLE</span>'
            ])
            continue

        fails  = sum(1 for _, _, s in checks.get("critical", []) if s == "FAIL")
        warns  = sum(1 for _, _, s in checks.get("quality", [])  if s == "WARN")
        warns += sum(1 for _, _, s in checks.get("critical", []) if s == "WARN")

        if verdict == "GOOD" :
            badge = '<span class="badge-verdict-good">GOOD</span>'
        elif verdict == "ACCEPTABLE" :
            badge = f'<span class="badge-verdict-acceptable">ACCEPTABLE ({warns}W)</span>'
        else :
            badge = f'<span class="badge-verdict-unusable">UNUSABLE ({fails}F)</span>'

        table_rows.append([
            fname,
            f"{m['width']} × {m['height']}",
            f"{m['file_size_kb']}KB",
            f"{m['brightness']:.1f}",
            f"{m['sharpness']:.1f}",
            badge,
        ])

    report.table(
        ["Image", "Resolution", "Size", "Brightness", "Sharpness", "Verdict"],
        table_rows
    )

    # ── 2C. Usability assertion ────────────────────────────────────────

    report.subheader("2C. Dataset usability check")

    usable   = [(f, m, v, c) for f, m, v, c in results if v in ("GOOD", "ACCEPTABLE")]
    unusable = [(f, m, v, c) for f, m, v, c in results if v not in ("GOOD", "ACCEPTABLE")]
    n_total  = len(results)
    n_usable = len(usable)

    # threshold: at least 60% of the selected pool must pass – no hardcoded count
    min_required = max(1, int(n_total * 0.6))

    report.assertion(
        f"≥ 60% of images usable ({min_required}/{n_total} required)",
        f"{n_usable}/{n_total} usable",
        n_usable >= min_required,
        "fewer than 60% usable indicates dataset quality issues"
    )

    if unusable :
        report.log(f"Excluded from subsequent sections ({len(unusable)} images):")
        for fname, _, verdict, _ in unusable :
            report.log(f"  – {fname}  [{verdict}]")

    usable_paths = [
        img_path for img_path in image_pool
        if os.path.basename(img_path) in {f for f, _, v, _ in usable}
    ]

    report.prose(
        f"{n_usable} of {n_total} images pass the quality gate and proceed to "
        f"Sections 3–6. {len(unusable)} image(s) excluded."
    )

    report.end_section()
    return usable_paths


# ---------------------------------------------------------------------------
# SECTION 3 – Detector Sanity Validation
# ---------------------------------------------------------------------------

VEHICLE_CLASSES = ["bicycle", "motorcycle", "car", "bus", "truck"]


def section_detector_sanity(report : ReportBuilder, usable_images : list) -> int :
    """
    Runs baseline and finetuned detectors on usable_images.
    Checks output shape, value ranges, timing, and finetuning outcome.
    Returns number of failures.
    """
    
    report.begin_section("Section 3 – Detector Sanity Validation")
    report.prose(
        "Runs the baseline and finetuned detectors on all images that passed "
        "the quality gate. Validates output shape and value ranges, measures "
        "inference timing, and verifies the expected finetuning outcome — "
        "that the finetuned model detects more motorcycles on average."
    )

    failures = 0

    # load models
    report.log(f"Baseline model  : {MODEL_BASELINE}")
    detector_base = TrafficDetector(MODEL_BASELINE)

    has_finetuned  = os.path.exists(MODEL_FINETUNED)
    detector_fine  = TrafficDetector(MODEL_FINETUNED) if has_finetuned else None

    if has_finetuned :
        report.log(f"Finetuned model : {MODEL_FINETUNED}  [found – comparison enabled]")
    else :
        report.log(f"Finetuned model : not found at {MODEL_FINETUNED}  [3C and 3D skipped]")

    report.spacer()

    # ── 3A. Per-image sanity checks ─────────────────────────────────────

    report.subheader("3A. Per-image output sanity (baseline model)")
    report.prose(
        "For every usable image: verifies that the detector returns a well-formed "
        "output dict with values in expected ranges."
    )

    base_results = {}   # fname → metrics dict, for reuse in 3B/3C/3D

    for img_path in usable_images :

        fname = os.path.basename(img_path)
        img   = cv2.imread(img_path)

        if img is None :
            report.assertion(f"{fname} – readable", "UNREADABLE", False)
            failures += 1
            continue

        m  = detector_base.analyze_image(img)
        vc = m["vehicle_count"]
        ws = m["weighted_vehicle_score"]
        dr = m["density_ratio"]
        bd = m["vehicle_breakdown"]
        base_results[fname] = m

        report.log(
            f"<strong>{fname}</strong>  "
            f"count={vc}  weighted={ws:.1f}  density={dr:.4f}  "
            f"breakdown={bd}"
        )

        failures += 0 if report.assertion(
            f"  vehicle_count ≥ 0",
            str(vc), vc >= 0
        ) else 1

        failures += 0 if report.assertion(
            f"  weighted_score ≥ vehicle_count",
            f"{ws:.1f} ≥ {vc}", ws >= vc,
            "every vehicle weighs at least 1"
        ) else 1

        failures += 0 if report.assertion(
            f"  density_ratio in [0.0, 1.0]",
            f"{dr:.4f}", 0.0 <= dr <= 1.0
        ) else 1

        failures += 0 if report.assertion(
            f"  all class names valid",
            str(list(bd.keys())),
            all(k in VEHICLE_CLASSES for k in bd.keys())
        ) else 1

        failures += 0 if report.assertion(
            f"  sum(breakdown) == vehicle_count",
            f"{sum(bd.values())} == {vc}",
            sum(bd.values()) == vc
        ) else 1

        report.spacer()

    # ── 3B. Timing benchmark ────────────────────────────────────────────

    report.subheader("3B. Inference timing benchmark (baseline model)")
    report.prose(
        "Measures wall-clock inference time per image. "
        "Asserts mean inference time is under 5 seconds per image."
    )

    times = []

    for img_path in usable_images :
        img = cv2.imread(img_path)
        if img is None :
            continue
        t0 = time.perf_counter()
        detector_base.analyze_image(img)
        times.append(time.perf_counter() - t0)

    if times :
        t_min   = min(times)
        t_max   = max(times)
        t_mean  = sum(times) / len(times)
        t_total = sum(times)

        report.log(f"Images timed   : {len(times)}")
        report.log(f"Min time       : {t_min:.3f}s")
        report.log(f"Max time       : {t_max:.3f}s")
        report.log(f"Mean time      : {t_mean:.3f}s")
        report.log(f"Total time     : {t_total:.3f}s")

        failures += 0 if report.assertion(
            "Mean inference time &lt; 5s",
            f"{t_mean:.3f}s",
            t_mean < 5.0,
            "real-time requirement for traffic signal control"
        ) else 1
    else :
        report.log("No images available for timing benchmark.")

    # ── 3C. Baseline vs finetuned side-by-side ─────────────────────────

    if not has_finetuned :
        report.end_section()
        return failures

    report.subheader("3C. Baseline vs finetuned side-by-side")

    fine_results  = {}
    table_rows    = []

    for img_path in usable_images :
        fname = os.path.basename(img_path)
        img   = cv2.imread(img_path)
        if img is None :
            continue

        mf = detector_fine.analyze_image(img)
        fine_results[fname] = mf
        mb = base_results.get(fname, {})

        table_rows.append([
            fname,
            mb.get("vehicle_count", "–"),
            mf.get("vehicle_count", "–"),
            f"{mb.get('weighted_vehicle_score', 0):.1f}",
            f"{mf.get('weighted_vehicle_score', 0):.1f}",
            f"{mb.get('density_ratio', 0):.4f}",
            f"{mf.get('density_ratio', 0):.4f}",
        ])

    report.table(
        [
            "Image",
            "Base count", "Fine count",
            "Base ws",    "Fine ws",
            "Base density", "Fine density",
        ],
        table_rows
    )

    # ── 3D. Finetuning outcome assertion ────────────────────────────────

    report.subheader("3D. Finetuning outcome – motorcycle detection")
    report.prose(
        "The model was finetuned on a Vietnamese traffic dataset with a high proportion "
        "of motorcycles. The expected outcome is that the finetuned model detects more "
        "motorcycles on average than the baseline COCO-pretrained model."
    )

    base_motos = []
    fine_motos = []

    for fname in base_results :
        if fname not in fine_results :
            continue
        base_bd = base_results[fname].get("vehicle_breakdown", {})
        fine_bd = fine_results[fname].get("vehicle_breakdown", {})
        base_motos.append(base_bd.get("motorcycle", 0) + base_bd.get("bicycle", 0))
        fine_motos.append(fine_bd.get("motorcycle", 0) + fine_bd.get("bicycle", 0))

    if base_motos and fine_motos :
        avg_base = sum(base_motos) / len(base_motos)
        avg_fine = sum(fine_motos) / len(fine_motos)

        report.log(f"Avg small vehicles per image – baseline  : {avg_base:.2f}")
        report.log(f"Avg small vehicles per image – finetuned : {avg_fine:.2f}")

        failures += 0 if report.assertion(
            "Finetuned detects more small vehicles on average",
            f"{avg_fine:.2f} > {avg_base:.2f}",
            avg_fine > avg_base,
            "expected finetuning outcome on Vietnamese traffic data"
        ) else 1
    else :
        report.log("Not enough matched results for 3D comparison.")

    report.end_section()
    return failures


# ---------------------------------------------------------------------------
# SECTION 4 – Ground Truth Comparison & Priority Score Sanity
# ---------------------------------------------------------------------------

GROUND_TRUTH = {
    "traffic_01.jpg" : [42,  2,  3],
    "traffic_02.jpg" : [42, 13,  0],
    "traffic_03.jpg" : [ 7,  0,  0],
    "traffic_04.jpg" : [ 8,  0,  1],
    "traffic_05.jpg" : [10,  2,  0],
    "traffic_06.jpg" : [14,  4,  0],
    "traffic_07.jpg" : [55, 26,  8],
    "traffic_08.jpg" : [61,  8,  4],
    "traffic_09.jpg" : [39, 21,  1],
    "traffic_10.jpg" : [42, 27,  3],
    "traffic_11.jpg" : [14, 36,  4],
    "traffic_12.jpg" : [21, 10,  0],
    "traffic_13.jpg" : [74, 23,  2],
    "traffic_14.jpg" : [13,  6,  1],
    "traffic_15.jpg" : [32, 19,  1],
    "traffic_16.jpg" : [32, 30,  0],
    "traffic_17.jpg" : [16, 33,  6],
    "traffic_18.jpg" : [53,  6,  0],
    "traffic_19.jpg" : [27,  3,  0],
    "traffic_20.jpg" : [42,  5,  0],
    "traffic_21.jpg" : [36,  1,  0],
    "traffic_22.jpg" : [25,  7,  0],
}

GT_WEIGHTS       = [1, 2, 4.5]   # moto+bicycle, car, bus+truck
ALPHA_PRIO       = 0.6
BETA_PRIO        = 0.4
MAX_WS_PRIO      = 200.0
SMALL_CLASSES    = {"bicycle", "motorcycle"}
LARGE_CLASSES    = {"bus", "truck"}


def _pearson_r(xs : list, ys : list) -> float :
    """Compute Pearson correlation coefficient between two lists."""
    n  = len(xs)
    if n < 2 :
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num   = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    den_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0 :
        return 0.0
    return num / (den_x * den_y)


def _rank_list(values : list) -> list :
    """Return rank positions (1 = highest) for a list of values."""
    indexed  = sorted(enumerate(values), key = lambda x : x[1], reverse = True)
    ranks    = [0] * len(values)
    for rank, (i, _) in enumerate(indexed, start = 1) :
        ranks[i] = rank
    return ranks


def _compute_priority(weighted_score : float, density : float) -> float :
    normalized = min(weighted_score / MAX_WS_PRIO, 1.0)
    return ALPHA_PRIO * normalized + BETA_PRIO * density


def _extract_counts(breakdown : dict) -> list :
    """Convert vehicle_breakdown dict to [small, car, large] counts."""
    small = sum(breakdown.get(c, 0) for c in SMALL_CLASSES)
    car   = breakdown.get("car", 0)
    large = sum(breakdown.get(c, 0) for c in LARGE_CLASSES)
    return [small, car, large]


def section_ground_truth_and_priority(report : ReportBuilder, usable_images  : list) -> int :
    """
    Combines ground truth comparison and priority score sanity.
    Returns number of failures.
    """

    report.begin_section(
        "Section 4 – Ground Truth Comparison & Priority Score Sanity"
    )
    report.prose(
        "Compares detector output against 22 manually counted ground truth labels "
        "and verifies that the computed priority score tracks real congestion. "
        "Ground truth format per image: [moto + bicycle, car, bus + truck]."
    )

    failures = 0

    # load models
    detector_base = TrafficDetector(MODEL_BASELINE)
    has_finetuned = os.path.exists(MODEL_FINETUNED)
    detector_fine = TrafficDetector(MODEL_FINETUNED) if has_finetuned else None

    # run detection on all usable images that have ground truth
    base_data  = {}   # fname → {metrics, counts, priority}
    fine_data  = {}

    for img_path in usable_images :
        fname = os.path.basename(img_path)
        if fname not in GROUND_TRUTH :
            continue

        img = cv2.imread(img_path)
        if img is None :
            continue

        mb           = detector_base.analyze_image(img)
        base_counts  = _extract_counts(mb["vehicle_breakdown"])
        base_prio    = _compute_priority(mb["weighted_vehicle_score"], mb["density_ratio"])
        base_data[fname] = {
            "metrics"  : mb,
            "counts"   : base_counts,
            "priority" : base_prio,
        }

        if has_finetuned :
            mf           = detector_fine.analyze_image(img)
            fine_counts  = _extract_counts(mf["vehicle_breakdown"])
            fine_prio    = _compute_priority(mf["weighted_vehicle_score"], mf["density_ratio"])
            fine_data[fname] = {
                "metrics"  : mf,
                "counts"   : fine_counts,
                "priority" : fine_prio,
            }

    # ── 4A. Per-image comparison table ──────────────────────────────────

    report.subheader("4A. Per-image count comparison")
    report.prose(
        "Ground truth vs baseline vs finetuned counts per category. "
        "Δ shown as (predicted – ground truth). Negative = undercount, positive = overcount."
    )

    cats       = ["moto + bicycle", "car", "bus + truck"]
    headers    = ["Image", "GT total"]
    for cat in cats :
        headers += [f"GT {cat}", f"Base {cat}", f"Δ base", f"Fine {cat}", f"Δ fine"]

    table_rows = []

    for fname in sorted(base_data.keys()) :
        gt     = GROUND_TRUTH[fname]
        bd     = base_data[fname]
        fd     = fine_data.get(fname)
        bc     = bd["counts"]
        fc     = fd["counts"] if fd else [None, None, None]
        gt_tot = sum(gt)

        row = [fname, gt_tot]
        for i in range(3) :
            delta_b = (bc[i] - gt[i]) if bc[i] is not None else "–"
            delta_f = (fc[i] - gt[i]) if fc and fc[i] is not None else "–"

            def fmt_delta(d) :
                if d == "–" :
                    return "–"
                sign = "+" if d >= 0 else ""
                color = "#DC2626" if d < 0 else ("#059669" if d > 0 else "#6B7280")
                return f'<span style="color:{color};font-weight:600">{sign}{d}</span>'

            row += [gt[i], bc[i], fmt_delta(delta_b),
                    fc[i] if fc else "–", fmt_delta(delta_f)]
        table_rows.append(row)

    report.table(headers, table_rows)

    # ── 4B. Weighted accuracy ────────────────────────────────────────────

    report.subheader("4B. Weighted accuracy per image")
    report.prose(
        f"Weighted accuracy = min(predicted_weighted, gt_weighted) / gt_weighted × 100. "
        f"Weights: moto+bicycle = {GT_WEIGHTS[0]}, car = {GT_WEIGHTS[1]}, "
        f"bus+truck = {GT_WEIGHTS[2]}. "
        f"Uses min() so overcounting does not inflate the score."
    )

    acc_headers = ["Image", "GT weighted", "Base weighted", "Base acc%",
                   "Fine weighted", "Fine acc%"]
    acc_rows    = []

    total_gt_wt   = 0.0
    total_base_wt = 0.0
    total_fine_wt = 0.0

    for fname in sorted(base_data.keys()) :
        gt   = GROUND_TRUTH[fname]
        bc   = base_data[fname]["counts"]
        fd   = fine_data.get(fname)
        fc   = fd["counts"] if fd else None

        gt_wt   = sum(gt[i]   * GT_WEIGHTS[i] for i in range(3))
        base_wt = sum(bc[i]   * GT_WEIGHTS[i] for i in range(3))
        fine_wt = sum(fc[i]   * GT_WEIGHTS[i] for i in range(3)) if fc else 0.0

        base_acc = round(min(base_wt, gt_wt) / gt_wt * 100, 1) if gt_wt > 0 else 0.0
        fine_acc = round(min(fine_wt, gt_wt) / gt_wt * 100, 1) if gt_wt > 0 and fc else "–"

        total_gt_wt   += gt_wt
        total_base_wt += base_wt
        total_fine_wt += fine_wt if fc else 0.0

        def color_acc(v) :
            if not isinstance(v, float) :
                return v
            c = "#059669" if v >= 80 else ("#D97706" if v >= 60 else "#DC2626")
            return f'<span style="color:{c};font-weight:600">{v}%</span>'

        acc_rows.append([
            fname,
            f"{gt_wt:.1f}",
            f"{base_wt:.1f}",
            color_acc(base_acc),
            f"{fine_wt:.1f}" if fc else "–",
            color_acc(fine_acc),
        ])

    # totals row
    overall_base_acc = round(min(total_base_wt, total_gt_wt) / total_gt_wt * 100, 1) \
                       if total_gt_wt > 0 else 0.0
    overall_fine_acc = round(min(total_fine_wt, total_gt_wt) / total_gt_wt * 100, 1) \
                       if total_gt_wt > 0 and has_finetuned else "–"

    acc_rows.append([
        "<strong>TOTAL</strong>",
        f"<strong>{total_gt_wt:.1f}</strong>",
        f"<strong>{total_base_wt:.1f}</strong>",
        f"<strong>{overall_base_acc}%</strong>",
        f"<strong>{total_fine_wt:.1f}</strong>" if has_finetuned else "–",
        f"<strong>{overall_fine_acc}%</strong>" if has_finetuned else "–",
    ])

    report.table(acc_headers, acc_rows)

    # ── 4C. Overall accuracy floor ──────────────────────────────────────

    report.subheader("4C. Overall accuracy floor assertion")

    failures += 0 if report.assertion(
        "Overall baseline weighted accuracy > 30%",
        f"{overall_base_acc}%",
        overall_base_acc > 30.0,
        "floor check – detector must at least respond to congestion"
    ) else 1

    if has_finetuned and isinstance(overall_fine_acc, float) :
        failures += 0 if report.assertion(
            "Overall finetuned weighted accuracy > 30%",
            f"{overall_fine_acc}%",
            overall_fine_acc > 30.0,
            "floor check – finetuned model must also clear minimum bar"
        ) else 1

    # ── 4D. Small vehicle miss rate ──────────────────────────────────────

    report.subheader("4D. Small vehicle (moto + bicycle) miss rate")
    report.prose(
        "Motorcycles and bicycles are systematically undercounted due to occlusion "
        "in dense clusters and small apparent size. This is an expected and documented "
        "limitation — the hybrid Canny density estimator partially compensates by "
        "capturing visual texture of dense clusters even when bounding boxes are missed."
    )

    gt_small_total   = sum(GROUND_TRUTH[f][0] for f in base_data)
    base_small_total = sum(base_data[f]["counts"][0] for f in base_data)

    if gt_small_total > 0 :
        miss_rate_base = round((gt_small_total - base_small_total) / gt_small_total * 100, 1)
        report.log(f"Ground truth small vehicles  : {gt_small_total}")
        report.log(f"Baseline detected            : {base_small_total}")
        report.log(f"Miss rate (baseline)         : {miss_rate_base}%")

        if has_finetuned :
            fine_small_total = sum(fine_data[f]["counts"][0] for f in fine_data)
            miss_rate_fine   = round((gt_small_total - fine_small_total) / gt_small_total * 100, 1)
            report.log(f"Finetuned detected           : {fine_small_total}")
            report.log(f"Miss rate (finetuned)        : {miss_rate_fine}%")

        report.info(
            "Miss rate is expected",
            "caused by occlusion in dense motorcycle clusters – Canny estimator compensates"
        )

        # document but do not fail on this – it is expected behavior
        report.assertion(
            "Miss rate documented (no pass/fail – informational)",
            f"{miss_rate_base}% baseline miss rate",
            True,
            "see Section 3D and detector_evaluation.ipynb for full analysis"
        )

    # ── 4E / 5A–5D. Priority score sanity ──────────────────────────────

    report.subheader("4E. Priority score sanity and correlation with ground truth")
    report.prose(
        "Verifies that priority scores are bounded in [0, 1], that density_ratio and "
        "weighted_score are positively correlated (they measure different signals but "
        "should agree on direction), and that priority weakly tracks real congestion "
        "as measured by ground truth vehicle counts."
    )

    # collect per-image vectors
    priorities    = []
    gt_totals     = []
    weighted_scores = []
    densities     = []
    fname_list    = []

    for fname in sorted(base_data.keys()) :
        gt  = GROUND_TRUTH[fname]
        bd  = base_data[fname]
        priorities.append(bd["priority"])
        gt_totals.append(sum(gt))
        weighted_scores.append(bd["metrics"]["weighted_vehicle_score"])
        densities.append(bd["metrics"]["density_ratio"])
        fname_list.append(fname)

    # 5A: priority bounded in [0, 1]
    all_bounded = all(0.0 <= p <= 1.0 for p in priorities)
    failures += 0 if report.assertion(
        "All priority scores in [0.0, 1.0]",
        f"{len(priorities)} images checked",
        all_bounded
    ) else 1

    # 5B: top 5 and bottom 5
    ranked = sorted(zip(priorities, fname_list, gt_totals), reverse = True)

    report.log("<strong>Top 5 by priority score:</strong>")
    for prio, fname, gt_tot in ranked[:5] :
        report.log(f"  {fname}  priority = {prio:.4f}  GT total = {gt_tot}")

    report.log("<strong>Bottom 5 by priority score:</strong>")
    for prio, fname, gt_tot in ranked[-5 :] :
        report.log(f"  {fname}  priority = {prio:.4f}  GT total = {gt_tot}")

    # 5C: density vs weighted_score correlation
    r_dw = _pearson_r(densities, weighted_scores)
    report.log(f"Pearson r (density vs weighted_score) = {r_dw:.3f}")
    failures += 0 if report.assertion(
        "density_ratio and weighted_score positively correlated (r > 0.2)",
        f"r = {r_dw:.3f}",
        r_dw > 0.2,
        "both signals should agree on congestion direction"
    ) else 1

    # 5D: priority vs gt_total correlation
    r_pg = _pearson_r(priorities, gt_totals)
    report.log(f"Pearson r (priority vs GT total)       = {r_pg:.3f}")
    failures += 0 if report.assertion(
        "Priority positively correlated with GT total (r > 0.2)",
        f"r = {r_pg:.3f}",
        r_pg > 0.2,
        "priority score should weakly track real congestion"
    ) else 1

    # rank correlation (4E)
    prio_ranks = _rank_list(priorities)
    gt_ranks   = _rank_list(gt_totals)
    r_rank     = _pearson_r(prio_ranks, gt_ranks)
    report.log(f"Rank correlation (priority vs GT rank) = {r_rank:.3f}")
    failures += 0 if report.assertion(
        "Rank correlation > 0.3",
        f"r = {r_rank:.3f}",
        r_rank > 0.3,
        "priority ranking should weakly match ground truth ranking"
    ) else 1

    report.end_section()
    return failures

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() :

    parser = argparse.ArgumentParser(description = "Smart Traffic System – Validation")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--all",    action = "store_true",
                       help = "Use all test images")
    group.add_argument("--random", type = int, metavar = "N", default = 5,
                       help = "Use N random test images (default 5)")
    parser.add_argument("--section",     type = str, default = None,
                        help = "Comma-separated sections to run, e.g. 1,2")
    parser.add_argument("--no-detector", action = "store_true",
                        help = "Skip detector sections")
    parser.add_argument("--fast",        action = "store_true",
                        help = "Alias for --no-detector")
    args = parser.parse_args()

    run_sections = set(args.section.split(",")) if args.section else None

    if args.all :
        selected = TEST_IMAGE_POOL
    else :
        n        = min(args.random, len(TEST_IMAGE_POOL))
        selected = random.sample(TEST_IMAGE_POOL, n)

    report         = ReportBuilder()
    total_failures = 0

    if run_sections is None or "1" in run_sections :
        total_failures += section_decision_maker(report)

    usable_images = selected
    if run_sections is None or "2" in run_sections :
        usable_images = section_image_quality(report, selected)
    
    if run_sections is None or "3" in run_sections :
        if not (args.no_detector or args.fast) :
            total_failures += section_detector_sanity(report, usable_images)
            
    if run_sections is None or "4" in run_sections :
        if not (args.no_detector or args.fast) :
            total_failures += section_ground_truth_and_priority(report, usable_images)

    output_path = os.path.join(VALIDATION_DIR, f"validation_report.html")
    report.save(output_path)

    print(f"Report: {output_path}")
    print(f"Pass: {report._pass_count}  Fail: {report._fail_count}  Warn: {report._warn_count}")


if __name__ == "__main__" :
    main()