# tests/check_images.py
"""
Image Quality Checker for Traffic Detection
============================================
Analyzes images and reports quality metrics relevant to YOLO detection.

Metrics are split into three tiers:

    CRITICAL     : resolution, file size, exposure
                   → can produce FAIL → image is unusable
    QUALITY      : brightness, contrast, sharpness, aspect ratio
                   → can produce WARN → image may affect accuracy
    INFORMATIONAL: noise, saturation, channel balance
                   → always shown, never affects verdict
                   → useful context but unreliable as hard filters

Verdicts
--------
    GOOD       : no FAIL, 0–1 WARN
    ACCEPTABLE : no FAIL, 2+ WARN
    UNUSABLE   : any FAIL

Usage
-----
    python tests/check_images.py
    python tests/check_images.py --folder data/raw
    python tests/check_images.py --save
"""

import cv2
import os
import sys
import argparse
import numpy as np
from datetime import datetime


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

T = {
    # CRITICAL
    "min_width"            : 480,
    "min_height"           : 360,
    "warn_width"           : 640,
    "warn_height"          : 480,
    "min_size_kb"          : 50,
    "warn_size_kb"         : 100,
    "max_overexposed_pct"  : 20.0,    # % pixels > 250
    "warn_overexposed_pct" : 5.0,
    "max_underexposed_pct" : 20.0,    # % pixels < 5
    "warn_underexposed_pct": 5.0,

    # QUALITY
    "min_brightness"       : 20,      # relaxed from 40
    "warn_brightness_low"  : 50,
    "warn_brightness_high" : 200,
    "max_brightness"       : 230,
    "min_contrast"         : 15,      # relaxed from 20
    "warn_contrast"        : 30,
    "min_sharpness"        : 15,      # relaxed from 30
    "warn_sharpness"       : 60,      # relaxed from 80
    "min_aspect"           : 0.5,
    "max_aspect"           : 4.0,
}


# ---------------------------------------------------------------------------
# Compute metrics
# ---------------------------------------------------------------------------

def compute_metrics(img_path : str) -> dict | None :

    file_size_kb = os.path.getsize(img_path) / 1024
    img = cv2.imread(img_path)

    if img is None :
        return None

    h, w  = img.shape[:2]
    gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv   = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    total = h * w

    laplacian = cv2.Laplacian(gray, cv2.CV_64F)

    edges_loose = cv2.Canny(gray, 10,  50)
    edges_tight = cv2.Canny(gray, 100, 200)
    loose_count = max(cv2.countNonZero(edges_loose), 1)

    b, g, r = cv2.mean(img)[:3]

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


# ---------------------------------------------------------------------------
# Assess metrics – three-tier system
# ---------------------------------------------------------------------------

def assess(m : dict) -> dict :
    """
    Returns dict with keys 'critical', 'quality', 'informational'.
    Each is a list of (label, value_str, status) tuples.
    Status: PASS / WARN / FAIL.
    Informational items always have status INFO.
    """

    critical     = []
    quality      = []
    informational = []

    def chk(bucket, label, value_str, ok, warn=None) :
        if not ok :
            status = "FAIL"
        elif warn is not None and not warn :
            status = "WARN"
        else :
            status = "PASS"
        bucket.append((label, value_str, status))

    def info(label, value_str) :
        informational.append((label, value_str, "INFO"))

    # ── CRITICAL ──────────────────────────────────────────────────────────

    chk(critical,
        f"width            (min {T['min_width']}px)",
        f"{m['width']}px",
        m["width"]  >= T["min_width"],
        m["width"]  >= T["warn_width"],
    )
    chk(critical,
        f"height           (min {T['min_height']}px)",
        f"{m['height']}px",
        m["height"] >= T["min_height"],
        m["height"] >= T["warn_height"],
    )
    chk(critical,
        f"file size        (min {T['min_size_kb']}KB)",
        f"{m['file_size_kb']}KB",
        m["file_size_kb"] >= T["min_size_kb"],
        m["file_size_kb"] >= T["warn_size_kb"],
    )
    chk(critical,
        f"overexposed      (max {T['max_overexposed_pct']}%)",
        f"{m['overexposed_pct']}%",
        m["overexposed_pct"] < T["max_overexposed_pct"],
        m["overexposed_pct"] < T["warn_overexposed_pct"],
    )
    chk(critical,
        f"underexposed     (max {T['max_underexposed_pct']}%)",
        f"{m['underexposed_pct']}%",
        m["underexposed_pct"] < T["max_underexposed_pct"],
        m["underexposed_pct"] < T["warn_underexposed_pct"],
    )

    # ── QUALITY ───────────────────────────────────────────────────────────

    chk(quality,
        f"brightness       (target {T['warn_brightness_low']}–{T['warn_brightness_high']})",
        f"{m['brightness']}",
        T["min_brightness"] <= m["brightness"] <= T["max_brightness"],
        T["warn_brightness_low"] <= m["brightness"] <= T["warn_brightness_high"],
    )
    chk(quality,
        f"contrast         (min {T['min_contrast']} std dev)",
        f"{m['contrast']}",
        m["contrast"] >= T["min_contrast"],
        m["contrast"] >= T["warn_contrast"],
    )
    chk(quality,
        f"sharpness        (min {T['min_sharpness']} Lap.var)",
        f"{m['sharpness']}",
        m["sharpness"] >= T["min_sharpness"],
        m["sharpness"] >= T["warn_sharpness"],
    )
    chk(quality,
        f"aspect ratio     ({T['min_aspect']}–{T['max_aspect']})",
        f"{m['aspect_ratio']}",
        T["min_aspect"] <= m["aspect_ratio"] <= T["max_aspect"],
    )

    # ── INFORMATIONAL ─────────────────────────────────────────────────────
    # Shown for context only – never affects verdict.
    # Noise and channel balance are heuristic and unreliable as hard filters,
    # especially for high-resolution or non-ideal lighting conditions.

    info("noise ratio      (0 = clean, 1 = noisy)", str(m["noise_ratio"]))
    info("saturation       (HSV S mean)",  str(m["saturation"]))
    info("channel balance  (RGB std dev)", str(m["channel_imbalance"]))
    info("resolution", f"{m['width']}×{m['height']}  {m['megapixels']}MP")

    return {
        "critical"      : critical,
        "quality"       : quality,
        "informational" : informational,
    }


def overall_verdict(checks : dict) -> str :
    """
    Verdict is based only on CRITICAL and QUALITY tiers.
    Informational metrics are never counted.
    """
    c_statuses = [s for _, _, s in checks["critical"]]
    q_statuses = [s for _, _, s in checks["quality"]]

    if "FAIL" in c_statuses :
        n = c_statuses.count("FAIL")
        return f"UNUSABLE   ({n} critical failure{'s' if n>1 else ''})"

    warns = q_statuses.count("WARN") + c_statuses.count("WARN")
    if warns >= 2 :
        return f"ACCEPTABLE ({warns} quality warnings)"
    elif warns == 1 :
        return f"ACCEPTABLE (1 quality warning)"
    return "GOOD"


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

LINES = []

def _log(line="") :
    print(line)
    LINES.append(line)

def _header(title) :
    _log(f"\n{'='*70}")
    _log(f"  {title}")
    _log(f"{'='*70}")

def report_image(img_path : str) -> tuple[dict | None, str] :

    name = os.path.basename(img_path)
    _log(f"\n{'─'*70}")
    _log(f"  {name}")
    _log(f"{'─'*70}")

    m = compute_metrics(img_path)

    if m is None :
        _log("  [FAIL] Cannot read image – file may be corrupt.")
        return None, "UNUSABLE   (unreadable)"

    checks  = assess(m)
    verdict = overall_verdict(checks)

    _log("  CRITICAL")
    for label, value, status in checks["critical"] :
        _log(f"    {label:<45} {value:<16} [{status}]")

    _log("  QUALITY")
    for label, value, status in checks["quality"] :
        _log(f"    {label:<45} {value:<16} [{status}]")

    _log("  INFORMATIONAL  (context only – not counted in verdict)")
    for label, value, _ in checks["informational"] :
        _log(f"    {label:<45} {value}")

    _log(f"\n  ► {verdict}")

    return m, verdict


def summary_table(results : list) :

    _header("SUMMARY TABLE")
    _log(f"  {'Image':<22} {'Resolution':>14} {'Size':>7} {'Bright':>7} {'Sharp':>8}  Verdict")
    _log("  " + "─" * 82)

    for name, m, verdict in results :
        if m is None :
            _log(f"  {name:<22} {'UNREADABLE':>14}")
            continue
        res = f"{m['width']}×{m['height']}"
        _log(
            f"  {name:<22}"
            f" {res:>14}"
            f" {m['file_size_kb']:>6.0f}KB"
            f" {m['brightness']:>7.1f}"
            f" {m['sharpness']:>8.1f}"
            f"  {verdict}"
        )

    _log("")
    _log("  Verdict guide:")
    _log("    GOOD       – suitable for detection and validation")
    _log("    ACCEPTABLE – usable, note any warnings in report")
    _log("    UNUSABLE   – discard, critical quality issue")
    _log("")
    _log("  Note: noise ratio, saturation, and channel balance are shown")
    _log("  as context only and do not affect the verdict.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() :

    parser = argparse.ArgumentParser(description="Image quality checker for traffic detection")
    parser.add_argument("--folder", default="data/raw")
    parser.add_argument("--save",   action="store_true")
    args = parser.parse_args()

    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    folder       = os.path.join(PROJECT_ROOT, args.folder)

    _log(f"Image Quality Report – Traffic Detection")
    _log(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _log(f"Folder    : {folder}")

    images = sorted([
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])

    if not images :
        _log(f"\n[ERROR] No images found in {folder}")
        return

    _log(f"Images    : {len(images)} found\n")

    results = []
    for img_path in images :
        name          = os.path.basename(img_path)
        m, verdict    = report_image(img_path)
        results.append((name, m, verdict))

    summary_table(results)

    if args.save :
        out = os.path.join(PROJECT_ROOT, "data", "validation", "image_quality_report.txt")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f :
            f.write("\n".join(LINES))
        print(f"\nReport saved to: {out}")


if __name__ == "__main__" :
    main()