# ai_module/detector.py

"""
TrafficDetector

Purpose
-------
Analyze a single camera image and extract traffic metrics.

The detector DOES NOT make traffic decisions. 
It only converts an image into measurable traffic statistics.

Metrics produced
----------------
vehicle_count
vehicle_breakdown
weighted_vehicle_score
density_ratio

Features
--------
- YOLO vehicle detection
- Optional cropping of road region
- Hybrid density estimation using Canny edges
"""

import cv2
import numpy as np
from ultralytics import YOLO
from collections import defaultdict


class TrafficDetector :

    def __init__(self, model_path : str, crop_enabled : bool = False, crop_region : dict = None) :
        """
        Initialize the detector.

        Parameters
        ----------
        model_path : path to YOLO model
        crop_enabled : enable / disable cropping
        crop_region : dictionary defining crop ratios
        """

        self.model = YOLO(model_path)

        # Vehicle classes considered in traffic analysis
        self.vehicle_classes = [ "bicycle", "motorcycle", "car", "bus", "truck"]

        # Vehicle weights for congestion impact
        self.vehicle_weights = { "bicycle" : 1, "motorcycle" : 1, "car" : 2, "bus" : 4, "truck" : 5 }

        # Cropping configuration
        self.crop_enabled = crop_enabled

        if crop_region is None :
            self.crop_region = {
                "top" : 0.0,
                "bottom" : 1.0,
                "left" : 0.0,
                "right" : 1.0
            }
        else :
            self.crop_region = crop_region


    def _crop_image(self, image : np.ndarray) :
        """
        Crop the image according to configured ratios.
        """

        h, w = image.shape[ : 2]

        top     = int(h * self.crop_region["top"])
        bottom  = int(h * self.crop_region["bottom"])
        left    = int(w * self.crop_region["left"])
        right   = int(w * self.crop_region["right"])

        return image[top : bottom, left : right]


    def _compute_edge_density(self, image : np.ndarray, boxes) :
        """
        Hybrid density estimation using:

        1. YOLO detection for large vehicles (car, bus, truck)
        2. Canny edge detection for small vehicle clusters
        3. Removing large vehicle areas from edge mask
        4. Zone-based density estimation (near / mid / far)

        This avoids double counting large vehicles and focuses
        edge detection on dense motorcycle clusters.
        """

        img_h, img_w = image.shape[ : 2]

        # -------------------------------------------------
        # 1. Collect large vehicle bounding boxes from YOLO
        # -------------------------------------------------

        large_boxes = []

        if boxes is not None :

            for box in boxes :

                cls_id = int(box.cls[0])
                label = self.model.names[cls_id]

                if label in [ "car", "bus", "truck" ] :

                    x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                    large_boxes.append((x1, y1, x2, y2))

        # -------------------------------------------------
        # 2. Edge detection pipeline
        # -------------------------------------------------

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        # -------------------------------------------------
        # 3. Remove large vehicle regions from edge mask
        # -------------------------------------------------

        for (x1, y1, x2, y2) in large_boxes :
            cv2.rectangle(edges, (x1, y1), (x2, y2), 0, -1)

        # -------------------------------------------------
        # 4. Close small edge gaps
        # -------------------------------------------------

        kernel = np.ones((5, 5), np.uint8)
        closed_edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        # -------------------------------------------------
        # 5. Define vertical zones
        # -------------------------------------------------

        y_start = int(img_h * 0.25)
        zone_h = (img_h - y_start) // 3
        zones = {
            "far" : (y_start, y_start + zone_h),
            "mid" : (y_start + zone_h, y_start + 2 * zone_h),
            "near" : (y_start + 2 * zone_h, img_h)
        }
        densities = {}

        # -------------------------------------------------
        # 6. Compute density per zone
        # -------------------------------------------------

        for zone_name, (y1, y2) in zones.items() :

            # Create road mask for zone
            zone_mask = np.ones((y2 - y1, img_w), dtype = np.uint8) * 255

            # Remove large vehicle areas from road mask
            for (bx1, by1, bx2, by2) in large_boxes :
                inter_y1 = max(y1, by1) - y1
                inter_y2 = min(y2, by2) - y1

                if inter_y1 < inter_y2 :
                    cv2.rectangle(zone_mask, (bx1, inter_y1), (bx2, inter_y2), 0, -1)

            # Actual road area
            actual_road_area = cv2.countNonZero(zone_mask)

            # Edge pixels in zone
            zone_edges = closed_edges[y1 : y2, 0 : img_w]
            white_pixels = cv2.countNonZero(zone_edges)
            if actual_road_area > 0 :
                density = white_pixels / actual_road_area
            else :
                density = 0
            densities[zone_name] = density

        # -------------------------------------------------
        # 7. Weighted density combination
        # -------------------------------------------------

        density_ratio = (
            0.5 * densities["near"] +
            0.3 * densities["mid"] +
            0.2 * densities["far"]
        )

        return density_ratio


    def analyze_image(self, image : np.ndarray) :
        """
        Analyze one camera image.

        Returns
        -------
        dict containing traffic metrics.
        """

        if self.crop_enabled :
            image = self._crop_image(image)

        results = self.model(image)
        counts = defaultdict(int)
        boxes = results[0].boxes

        if boxes is not None :
            for cls in boxes.cls :
                label = self.model.names[int(cls)]
                if label in self.vehicle_classes :
                    counts[label] += 1

        vehicle_count = sum(counts.values())
        weighted_score = 0

        for vehicle_type, count in counts.items() :
            weighted_score += count * self.vehicle_weights[vehicle_type]

        density_ratio = self._compute_edge_density(image, boxes)

        return {
            "vehicle_count"             : vehicle_count,
            "vehicle_breakdown"         : dict(counts),
            "weighted_vehicle_score"    : weighted_score,
            "density_ratio"             : density_ratio
        }
        

    def analyze_image_with_visualization(self, image) :
        """
        Analyze image and also return YOLO annotated visualization.
        """

        original = image.copy()

        if self.crop_enabled :
            image = self._crop_image(image)

        results = self.model(image)
        annotated = results[0].plot()
        metrics = self.analyze_image(original)

        return metrics, annotated