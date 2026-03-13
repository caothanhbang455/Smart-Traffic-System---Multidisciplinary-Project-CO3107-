# backend/app/services/ai_service.py

import sys
import os
import cv2
import numpy as np
from typing import Dict, Any

# Thêm đường dẫn đến ai_module
ai_module_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ai_module')
sys.path.append(ai_module_path)

from detector import TrafficDetector

class AIService:
    def __init__(self):
        # Đường dẫn đến model YOLO
        model_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'yolov8m.pt')
        self.detector = TrafficDetector(model_path)

    def analyze_image(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Phân tích một ảnh từ bytes.

        Args:
            image_bytes: Bytes của ảnh

        Returns:
            Dict chứa metrics: vehicle_count, vehicle_breakdown, weighted_vehicle_score, density_ratio
        """
        # Chuyển bytes thành numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            raise ValueError("Không thể decode ảnh")

        # Phân tích ảnh
        return self.detector.analyze_image(image)

    def analyze_multiple_images(self, images: Dict[str, bytes]) -> Dict[str, Dict[str, Any]]:
        """
        Phân tích nhiều ảnh (4 hướng).

        Args:
            images: Dict với key là hướng ('north', 'south', 'east', 'west'), value là bytes của ảnh

        Returns:
            Dict với key là hướng, value là metrics
        """
        results = {}
        for direction, image_bytes in images.items():
            try:
                results[direction] = self.analyze_image(image_bytes)
            except Exception as e:
                print(f"Lỗi phân tích ảnh {direction}: {e}")
                # Trả về metrics mặc định nếu lỗi
                results[direction] = {
                    "vehicle_count": 0,
                    "vehicle_breakdown": {},
                    "weighted_vehicle_score": 0.0,
                    "density_ratio": 0.0
                }
        return results