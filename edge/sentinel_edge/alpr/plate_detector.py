from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np

from ultralytics import YOLO

logger = logging.getLogger("sentinel.edge.alpr.detector")


@dataclass(frozen=True)
class PlateDetection:
    bbox: tuple[int, int, int, int]
    confidence: float
    width: int
    height: int
    area: int


class PlateDetector:
    """
    YOLOv8-based High-Precision License Plate Localization.
    Implements size quality gating (width >= 60px) and strict confidence thresholds (> 0.60).
    """

    MIN_PLATE_WIDTH = 60
    MIN_PLATE_HEIGHT = 18

    def __init__(self, model_path: str, confidence: float = 0.60, image_size: int = 640) -> None:
        if not model_path:
            raise ValueError("ALPR plate model path cannot be empty")
        self.model_path = model_path
        self.confidence = float(confidence)
        self.image_size = int(image_size)
        logger.info("Loading ALPR plate detector | model=%s | conf=%.2f", model_path, self.confidence)
        self.model = YOLO(model_path)

    def detect(self, vehicle_crop: np.ndarray) -> Optional[PlateDetection]:
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        h, w = vehicle_crop.shape[:2]
        if w < self.MIN_PLATE_WIDTH or h < self.MIN_PLATE_HEIGHT:
            return None

        try:
            results = self.model.predict(
                source=vehicle_crop,
                conf=self.confidence,
                imgsz=self.image_size,
                verbose=False,
            )
        except Exception as e:
            logger.exception("Error during plate detection inference: %s", e)
            return None

        if not results:
            return None

        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            return None

        best: Optional[PlateDetection] = None
        for box in result.boxes:
            confidence = float(box.conf[0].item())
            if confidence < self.confidence:
                continue

            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int).tolist()
            x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
            x2, y2 = max(0, min(x2, w)), max(0, min(y2, h))

            box_w = x2 - x1
            box_h = y2 - y1

            # Quality gate: Discard if plate is too small to yield reliable OCR
            if box_w < self.MIN_PLATE_WIDTH or box_h < self.MIN_PLATE_HEIGHT:
                continue

            candidate = PlateDetection(
                bbox=(x1, y1, x2, y2),
                confidence=confidence,
                width=box_w,
                height=box_h,
                area=box_w * box_h,
            )
            if best is None or confidence > best.confidence:
                best = candidate

        return best

    @staticmethod
    def crop_plate(vehicle_crop: np.ndarray, detection: PlateDetection) -> Optional[np.ndarray]:
        """
        Crop localized plate region with gentle padding to preserve edge characters.
        """
        if vehicle_crop is None or vehicle_crop.size == 0 or detection is None:
            return None

        h, w = vehicle_crop.shape[:2]
        x1, y1, x2, y2 = detection.bbox

        # 4% horizontal, 6% vertical margin to prevent clipping outer border characters
        pad_x = max(2, int(0.04 * (x2 - x1)))
        pad_y = max(2, int(0.06 * (y2 - y1)))

        px1 = max(0, x1 - pad_x)
        py1 = max(0, y1 - pad_y)
        px2 = min(w, x2 + pad_x)
        py2 = min(h, y2 + pad_y)

        plate = vehicle_crop[py1:py2, px1:px2]
        if plate.size == 0 or plate.shape[1] < PlateDetector.MIN_PLATE_WIDTH or plate.shape[0] < PlateDetector.MIN_PLATE_HEIGHT:
            return None

        return plate
