# backend/app/services/ai_service.py

"""
AIService
=========
Bridge between the Flask backend and the AI detection module.

Responsibilities
----------------
- Decode raw image bytes into numpy arrays for the detector
- Route calls to the appropriate TrafficDetector method
- Encode annotated images back to base64 for the frontend
- Provide safe fallback metrics when a single direction fails,
  so one bad image does not block the entire analysis request

This service does NOT contain detection logic – that lives in
ai_module/detector.py. It only handles I/O and error isolation.
"""

import sys
import os
import logging
import traceback

import cv2
import numpy as np
import base64
from typing import Dict, Any

# ---------------------------------------------------------------------------
# Path setup – add ai_module to sys.path so detector can be imported
# without installing it as a package.
# ---------------------------------------------------------------------------

_AI_MODULE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ai_module')
)

if _AI_MODULE_PATH not in sys.path :
    sys.path.insert(0, _AI_MODULE_PATH)

try :
    from detector import TrafficDetector
except ImportError as e :
    raise ImportError(
        f"Could not import TrafficDetector from '{_AI_MODULE_PATH}'. "
        f"Make sure ai_module/detector.py exists. Original error: {e}"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Fallback metrics returned when a single direction image fails to process.
# Zeros are safe defaults – the decision maker treats missing directions as
# empty lanes, which is better than crashing the entire request.
_FALLBACK_METRICS : Dict[str, Any] = {
    "vehicle_count"          : 0,
    "vehicle_breakdown"      : {},
    "weighted_vehicle_score" : 0.0,
    "density_ratio"          : 0.0,
    "annotated_image_base64" : "",
}

# JPEG encoding quality for annotated images sent to the frontend.
_JPEG_QUALITY = 85


# ---------------------------------------------------------------------------
# AIService
# ---------------------------------------------------------------------------

class AIService :

    def __init__(self) :
        """
        Initialize the service and load the YOLO detector.

        The model path is resolved relative to this file's location,
        assuming the standard project directory layout:

            project_root/
            ├── ai_module/
            │   ├── detector.py
            │   └── models/
            │       └── yolov8m_finetuned.pt   ← loaded here
            └── backend/
                └── app/
                    └── services/
                        └── ai_service.py      ← this file
        """

        model_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ai_module', 'models', 'yolov8m_finetuned.pt')
        )

        logger.info(f"[AIService] Loading detector from: {model_path}")
        self.detector = TrafficDetector(model_path)
        logger.info("[AIService] Detector ready.")


    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _decode_image(self, image_bytes : bytes, source_label : str = "image") -> np.ndarray :
        """
        Decode raw bytes into a BGR numpy array.

        Parameters
        ----------
        image_bytes  : raw bytes from a multipart upload or file read.
        source_label : human-readable label used in error messages
                       (e.g. "north", "south").

        Returns
        -------
        np.ndarray : BGR image ready for OpenCV / YOLO processing.

        Raises
        ------
        ValueError : if the bytes cannot be decoded as a valid image.
        """

        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None :
            raise ValueError(
                f"Failed to decode image bytes for '{source_label}'. "
                f"The data may be corrupted or in an unsupported format."
            )

        return image


    def _encode_annotated(self, annotated : np.ndarray) -> str :
        """
        Encode a BGR annotated image to a base64 JPEG string.

        The base64 string can be embedded directly in a JSON response
        and displayed by the frontend as: <img src="data:image/jpeg;base64,...">

        Parameters
        ----------
        annotated : BGR numpy array with YOLO bounding boxes drawn.

        Returns
        -------
        str : base64-encoded JPEG string.

        Raises
        ------
        ValueError : if OpenCV fails to encode the image.
        """

        encode_params = [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
        ok, encoded   = cv2.imencode(".jpg", annotated, encode_params)

        if not ok :
            raise ValueError("cv2.imencode failed to produce a JPEG output.")

        return base64.b64encode(encoded.tobytes()).decode("utf-8")


    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def analyze_image(self, image_bytes : bytes) -> Dict[str, Any] :
        """
        Analyze a single image and return traffic metrics (no visualization).

        Use this when you need metrics only and do not need bounding boxes –
        it is slightly faster than analyze_image_with_boxes because it skips
        the annotation and base64 encoding steps.

        Parameters
        ----------
        image_bytes : raw image bytes.

        Returns
        -------
        dict with keys:
            vehicle_count           : int
            vehicle_breakdown       : dict[str, int]
            weighted_vehicle_score  : float
            density_ratio           : float
        """

        image = self._decode_image(image_bytes)
        return self.detector.analyze_image(image)


    def analyze_image_with_boxes(self, image_bytes : bytes, direction : str = "image") -> Dict[str, Any] :
        """
        Analyze a single image and return metrics plus a YOLO-annotated frame.

        The annotated image is encoded as a base64 JPEG string and added to
        the metrics dict under the key 'annotated_image_base64'.

        Parameters
        ----------
        image_bytes : raw image bytes.
        direction   : label used in error messages (e.g. "north").

        Returns
        -------
        dict with keys:
            vehicle_count           : int
            vehicle_breakdown       : dict[str, int]
            weighted_vehicle_score  : float
            density_ratio           : float
            annotated_image_base64  : str  – base64 JPEG string
        """

        image                    = self._decode_image(image_bytes, direction)
        metrics, annotated       = self.detector.analyze_image_with_visualization(image)
        metrics["annotated_image_base64"] = self._encode_annotated(annotated)

        return metrics


    def analyze_multiple_images(self, images : Dict[str, bytes], with_boxes : bool = True) -> Dict[str, Dict[str, Any]] :
        """
        Analyze images for all four intersection directions.

        Each direction is processed independently. If one fails, it receives
        fallback zero-metrics so the overall request can still proceed.
        The failure is logged with a full traceback for debugging.

        Parameters
        ----------
        images     : dict mapping direction name to raw image bytes.
                     Expected keys: 'north', 'south', 'east', 'west'.
        with_boxes : if True (default), returns annotated images alongside
                     metrics. Set to False for metrics-only (faster).

        Returns
        -------
        dict mapping each direction name to its metrics dict.
        """

        results = {}

        for direction, image_bytes in images.items() :

            try :
                if with_boxes :
                    results[direction] = self.analyze_image_with_boxes(image_bytes, direction)
                else :
                    results[direction] = self.analyze_image(image_bytes)

            except Exception :
                logger.error(
                    f"[AIService] Failed to analyze direction '{direction}':\n"
                    + traceback.format_exc()
                )
                results[direction] = dict(_FALLBACK_METRICS)

        return results