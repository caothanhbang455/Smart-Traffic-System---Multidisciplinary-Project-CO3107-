# ai_module/detector.py

"""
TrafficDetector
===============
Analyzes a single camera image and extracts structured traffic metrics.

This module sits at the start of the AI pipeline:

    Camera image → TrafficDetector → metrics dict → TrafficState → DecisionMaker

The detector does NOT make traffic decisions. Its only job is to convert
a raw image into measurable, numeric traffic statistics.

Metrics produced
----------------
vehicle_count           : total number of detected vehicles
vehicle_breakdown       : per-class counts (motorcycle, car, bus, etc.)
weighted_vehicle_score  : congestion-weighted sum (truck counts more than a bicycle)
density_ratio           : hybrid density estimate combining YOLO + Canny edge detection

Design notes
------------
- YOLO is run exactly once per public method call. Both analyze_image() and
  analyze_image_with_visualization() share _extract_metrics(), which accepts
  already-computed YOLO results. This avoids running inference twice.

- The hybrid density estimator compensates for a known YOLO limitation:
  occluded or small vehicles (especially motorcycles in dense clusters) are
  often missed by bounding-box detection. Canny edge density catches the
  visual texture of these clusters. Large vehicles detected by YOLO are
  subtracted from the edge mask to avoid double-counting.
"""

import cv2
import numpy as np
from ultralytics import YOLO
from collections import defaultdict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Vehicle classes we care about for traffic analysis.
# All other COCO classes (person, traffic light, umbrella, etc.) are ignored.
VEHICLE_CLASSES = ["bicycle", "motorcycle", "car", "bus", "truck"]

# Congestion impact weights per vehicle class.
# Reflects how much road space and flow disruption each type causes.
# Motorcycle = 1 (small, agile), truck = 5 (large, slow-moving).
VEHICLE_WEIGHTS = {
    "bicycle"    : 1,
    "motorcycle" : 1,
    "car"        : 2,
    "bus"        : 4,
    "truck"      : 5,
}

# Classes treated as "large vehicles" for Canny mask exclusion.
# These are reliably detected by YOLO and would corrupt edge density
# if their bounding box regions were double-counted.
LARGE_VEHICLE_CLASSES = ["car", "bus", "truck"]

# Canny edge detection thresholds (low, high).
CANNY_LOW  = 50
CANNY_HIGH = 150

# Gaussian blur kernel applied before Canny to reduce noise.
BLUR_KERNEL = (5, 5)

# Morphological close kernel to fill small gaps in edge contours.
MORPH_KERNEL = np.ones((5, 5), np.uint8)

# Fraction of image height to discard from the top before zone analysis.
# The top 25% typically contains sky, overhead signs, and buildings –
# not relevant to road-level traffic density.
ZONE_TOP_RATIO = 0.25

# Density weights per zone. Near-zone traffic has the strongest influence
# on the current intersection state; far-zone vehicles may not arrive
# within the current light cycle and are discounted accordingly.
ZONE_WEIGHTS = {
    "near" : 0.5,   # bottom third of usable image
    "mid"  : 0.3,   # middle third
    "far"  : 0.2,   # top third (after discarding sky)
}


# ---------------------------------------------------------------------------
# TrafficDetector
# ---------------------------------------------------------------------------

class TrafficDetector :

    def __init__(self,
                 model_path   : str  = "yolov8m.pt",
                 crop_enabled : bool = False,
                 crop_region  : dict = None) :
        """
        Initialize the detector.

        Parameters
        ----------
        model_path   : path to YOLO .pt weights file.
                       Falls back to yolov8n.pt if the file is not found.
        crop_enabled : if True, each image is cropped before inference
                       using the ratios defined in crop_region.
        crop_region  : dict with keys "top", "bottom", "left", "right",
                       each a float in [0, 1] representing a fraction of
                       the image dimension. Defaults to full image (no crop).
        """

        try :
            self.model = YOLO(model_path)
        except Exception as e :
            print(f"[TrafficDetector] Warning: could not load '{model_path}'. "
                  f"Falling back to yolov8n.pt. Reason: {e}")
            self.model = YOLO("yolov8n.pt")

        self.crop_enabled = crop_enabled
        self.crop_region  = crop_region or {
            "top"    : 0.0,
            "bottom" : 1.0,
            "left"   : 0.0,
            "right"  : 1.0,
        }


    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _crop_image(self, image : np.ndarray) -> np.ndarray :
        """
        Crop the image to the configured region.

        Converts fractional crop_region ratios into pixel coordinates
        and returns the sliced sub-image.
        """

        h, w = image.shape[ : 2]

        top    = int(h * self.crop_region["top"])
        bottom = int(h * self.crop_region["bottom"])
        left   = int(w * self.crop_region["left"])
        right  = int(w * self.crop_region["right"])

        return image[top : bottom, left : right]


    def _collect_large_boxes(self, boxes) -> list :
        """
        Extract pixel-space bounding boxes for large vehicle classes.

        Used by the Canny density estimator to mask out regions that YOLO
        has already accounted for, preventing double-counting.

        Parameters
        ----------
        boxes : ultralytics Boxes object from results[0].boxes, or None.

        Returns
        -------
        list of (x1, y1, x2, y2) integer tuples in pixel coordinates.
        """

        if boxes is None :
            return []

        large_boxes = []

        for box in boxes :
            label = self.model.names[int(box.cls[0])]
            if label in LARGE_VEHICLE_CLASSES :
                x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                large_boxes.append((x1, y1, x2, y2))

        return large_boxes


    def _compute_edge_density(self, image : np.ndarray, boxes) -> float :
        """
        Hybrid density estimation: YOLO bounding boxes + Canny edges.

        Why this exists
        ---------------
        YOLO detects individual vehicles well when they are visible and
        separated. But dense clusters of motorcycles and bicycles are
        frequently missed due to occlusion and small apparent size.
        Canny edge detection captures the visual texture of these clusters
        as a proxy for density – more edge pixels in a region means more
        visual complexity, which correlates with congestion.

        To avoid double-counting, the bounding box regions of large vehicles
        already detected by YOLO (car, bus, truck) are masked out of the
        edge image before density is computed.

        Zone weighting
        --------------
        After discarding the top ZONE_TOP_RATIO of the image, the remainder
        is split into three equal vertical zones:

            far   weight 0.2  (vehicles far from the stop line)
            mid   weight 0.3
            near  weight 0.5  (vehicles closest to the stop line)

        Each zone's density = edge pixels / available road pixels.
        The final density_ratio is the weighted sum across all zones.

        Parameters
        ----------
        image : the (possibly cropped) BGR image.
        boxes : ultralytics Boxes object from results[0].boxes, or None.

        Returns
        -------
        float : weighted density ratio (dimensionless, roughly 0.0–0.3+).
        """

        img_h, img_w = image.shape[ : 2]

        # -- Step 1: collect large vehicle boxes for masking ----------------
        large_boxes = self._collect_large_boxes(boxes)

        # -- Step 2: Canny edge detection -----------------------------------
        gray    = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, BLUR_KERNEL, 0)
        edges   = cv2.Canny(blurred, CANNY_LOW, CANNY_HIGH)

        # -- Step 3: mask out large vehicle bounding boxes ------------------
        # Fill detected car/bus/truck regions with black so their internal
        # edges are not counted (YOLO already tracks those vehicles).
        for (x1, y1, x2, y2) in large_boxes :
            cv2.rectangle(edges, (x1, y1), (x2, y2), 0, thickness = -1)

        # -- Step 4: morphological close to connect broken edge contours ----
        closed_edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, MORPH_KERNEL)

        # -- Step 5: define vertical zones ----------------------------------
        y_start = int(img_h * ZONE_TOP_RATIO)
        zone_h  = (img_h - y_start) // 3

        zones = {
            "far"  : (y_start,              y_start + zone_h),
            "mid"  : (y_start + zone_h,     y_start + 2 * zone_h),
            "near" : (y_start + 2 * zone_h, img_h),
        }

        # -- Step 6: compute edge density per zone --------------------------
        densities = {}

        for zone_name, (y1, y2) in zones.items() :

            zone_h_px = y2 - y1

            # Road mask starts fully white (every pixel = road).
            # Large vehicle areas are punched out so density is measured
            # only over actual visible road surface.
            road_mask = np.full((zone_h_px, img_w), 255, dtype = np.uint8)

            for (bx1, by1, bx2, by2) in large_boxes :

                # Clip the bounding box coordinates into this zone's
                # local coordinate space (y1 of zone = row 0 in mask).
                inter_y1 = max(y1, by1) - y1
                inter_y2 = min(y2, by2) - y1

                if inter_y1 < inter_y2 :
                    cv2.rectangle(road_mask, (bx1, inter_y1), (bx2, inter_y2), 0, thickness = -1)

            road_area   = cv2.countNonZero(road_mask)
            edge_pixels = cv2.countNonZero(closed_edges[y1 : y2, :])

            densities[zone_name] = (edge_pixels / road_area) if road_area > 0 else 0.0

        # -- Step 7: weighted combination across zones ----------------------
        density_ratio = sum(ZONE_WEIGHTS[zone] * densities[zone] for zone in ZONE_WEIGHTS)
        return density_ratio


    def _extract_metrics(self, image : np.ndarray, results) -> dict :
        """
        Compute all traffic metrics from a pre-run YOLO result object.

        This is the shared core used by both public analyze methods.
        Accepting an already-computed results object means YOLO inference
        only happens once per call, regardless of whether visualization
        is also requested.

        Parameters
        ----------
        image   : the (possibly cropped) image that was passed to YOLO.
        results : list of ultralytics Result objects from self.model(image).

        Returns
        -------
        dict with keys:
            vehicle_count           : int
            vehicle_breakdown       : dict[str, int]
            weighted_vehicle_score  : float
            density_ratio           : float
        """

        boxes  = results[0].boxes
        counts = defaultdict(int)

        if boxes is not None :
            for cls in boxes.cls :
                label = self.model.names[int(cls)]
                if label in VEHICLE_CLASSES :
                    counts[label] += 1

        vehicle_count  = sum(counts.values())

        weighted_score = sum(
            count * VEHICLE_WEIGHTS[vehicle_type]
            for vehicle_type, count in counts.items()
        )

        density_ratio = self._compute_edge_density(image, boxes)

        return {
            "vehicle_count"          : vehicle_count,
            "vehicle_breakdown"      : dict(counts),
            "weighted_vehicle_score" : weighted_score,
            "density_ratio"          : density_ratio,
        }


    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def analyze_image(self, image : np.ndarray) -> dict :
        """
        Analyze one camera image and return traffic metrics.

        Parameters
        ----------
        image : BGR numpy array (as loaded by cv2.imread or decoded from bytes).

        Returns
        -------
        dict with keys:
            vehicle_count           : int   – total vehicles detected
            vehicle_breakdown       : dict  – per-class counts
            weighted_vehicle_score  : float – congestion-weighted total
            density_ratio           : float – hybrid YOLO+Canny density
        """

        if self.crop_enabled :
            image = self._crop_image(image)

        results = self.model(image)
        return self._extract_metrics(image, results)


    def analyze_image_with_visualization(self, image : np.ndarray) -> tuple[dict, np.ndarray] :
        """
        Analyze one camera image and return both metrics and an annotated frame.

        YOLO inference runs exactly once. The same results object is used
        for the bounding-box visualization and the metrics computation.

        Parameters
        ----------
        image : BGR numpy array.

        Returns
        -------
        metrics   : dict – same structure as analyze_image()
        annotated : np.ndarray – BGR image with YOLO bounding boxes drawn
        """

        if self.crop_enabled :
            image = self._crop_image(image)

        # Single YOLO inference – shared for both visualization and metrics.
        results   = self.model(image)
        annotated = results[0].plot()
        metrics   = self._extract_metrics(image, results)

        return metrics, annotated