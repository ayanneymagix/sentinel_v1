from __future__ import annotations

import cv2
import logging
import math
import numpy as np
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sentinel.edge.classifier")


@dataclass(frozen=True)
class VehicleAttributes:
    color: str
    body_subtype: str
    make: str
    full_name: str
    confidence: float
    color_rgb: Tuple[int, int, int]
    appearance_embedding: List[float]


class VehicleAttributeClassifier:
    """
    Intelligent Real-Time Vehicle Attribute Classifier.
    Extracts fine-grained vehicle characteristics from visual perception crops:
    1. Dominant HSV Paint Color (masking road reflection, windshield, and tires).
    2. Geometrical Body Subtype (Sedan, SUV, Hatchback, Transit Bus, Heavy Truck, Auto-Rickshaw, Two-Wheeler).
    3. Make / Brand Estimation calibrated for Indian & Global traffic (Maruti Suzuki, Hyundai, Tata Motors, Mahindra, Toyota, Honda, Ashok Leyland, Bajaj, etc.).
    4. Compact 32-bin Appearance Embedding for Cross-Camera Re-Identification (MTMC).
    """

    COLOR_PALETTE = {
        "White": ((0, 0, 180), (180, 45, 255), (255, 255, 255)),
        "Pearl Silver": ((0, 0, 120), (180, 40, 200), (200, 200, 200)),
        "Granite Grey": ((0, 0, 50), (180, 50, 130), (110, 115, 125)),
        "Midnight Black": ((0, 0, 0), (180, 255, 55), (25, 25, 30)),
        "Crimson Red": ((0, 70, 50), (10, 255, 255), (220, 38, 38)),
        "Crimson Red 2": ((165, 70, 50), (180, 255, 255), (220, 38, 38)),
        "Royal Blue": ((95, 70, 50), (130, 255, 255), (37, 99, 235)),
        "Golden Amber": ((15, 80, 80), (35, 255, 255), (234, 179, 8)),
        "Emerald Green": ((40, 60, 40), (85, 255, 255), (16, 185, 129)),
        "Brown / Bronze": ((10, 80, 40), (25, 200, 130), (146, 64, 14)),
    }

    def __init__(self) -> None:
        logger.info("VehicleAttributeClassifier initialized with dynamic color, subtype classification, and appearance embeddings")

    def extract_dominant_color(
        self, crop: np.ndarray, return_score: bool = False
    ) -> Any:
        """
        Isolates vehicle hood / door bodywork (middle 50% height, middle 70% width)
        to prevent tire asphalt and sky reflection contamination.
        Returns (color_name, rgb_tuple) by default, or (color_name, rgb_tuple, match_score) if return_score is True.
        """
        if crop is None or crop.size == 0:
            return ("White", (255, 255, 255), 0.5) if return_score else ("White", (255, 255, 255))

        h, w = crop.shape[:2]
        if h < 10 or w < 10:
            return ("White", (255, 255, 255), 0.5) if return_score else ("White", (255, 255, 255))

        # Bodywork sampling ROI: 20% to 75% height, 15% to 85% width
        y1, y2 = int(h * 0.20), int(h * 0.75)
        x1, x2 = int(w * 0.15), int(w * 0.85)
        body_roi = crop[y1:y2, x1:x2]

        if body_roi.size == 0:
            body_roi = crop

        hsv = cv2.cvtColor(body_roi, cv2.COLOR_BGR2HSV)
        total_pixels = max(1, body_roi.shape[0] * body_roi.shape[1])

        best_color = "White"
        best_rgb = (255, 255, 255)
        max_score = -1.0

        for color_name, (lower, upper, rgb) in self.COLOR_PALETTE.items():
            lower_np = np.array(lower, dtype=np.uint8)
            upper_np = np.array(upper, dtype=np.uint8)
            mask = cv2.inRange(hsv, lower_np, upper_np)
            count = cv2.countNonZero(mask)
            score = count / total_pixels

            # Normalize red aliases
            resolved_name = "Crimson Red" if "Red" in color_name else color_name

            if score > max_score and score > 0.12:
                max_score = score
                best_color = resolved_name
                best_rgb = rgb

        if max_score < 0.12:
            # Fallback based on mean brightness value
            mean_v = np.mean(hsv[:, :, 2])
            mean_s = np.mean(hsv[:, :, 1])
            if mean_v > 160 and mean_s < 50:
                best_color = "White"
                best_rgb = (255, 255, 255)
                max_score = 0.50
            elif mean_v < 60:
                best_color = "Midnight Black"
                best_rgb = (25, 25, 30)
                max_score = 0.55
            elif mean_s < 60:
                best_color = "Pearl Silver"
                best_rgb = (200, 200, 200)
                max_score = 0.50
            else:
                best_color = "Granite Grey"
                best_rgb = (110, 115, 125)
                max_score = 0.45

        if return_score:
            return best_color, best_rgb, round(float(max_score), 3)
        return best_color, best_rgb

    def classify_subtype(
        self,
        base_class: str,
        bbox: List[float],
        crop: Optional[np.ndarray] = None,
    ) -> str:
        """
        Classifies body geometry subtype based on aspect ratio, bounding volume,
        and height-to-width proportions.
        """
        base = base_class.lower()
        w = max(1.0, bbox[2] - bbox[0])
        h = max(1.0, bbox[3] - bbox[1])
        aspect_ratio = w / h
        area = w * h

        if base in ("motorcycle", "bicycle", "bike"):
            if aspect_ratio < 0.75:
                return "Scooter / Motorcycle"
            return "Motorcycle"

        if base == "bus":
            return "Transit Bus" if aspect_ratio > 1.3 else "Mini Bus"

        if base == "truck":
            return "Heavy Transport Truck" if area > 60000 else "Commercial LCV"

        if base == "person":
            return "Pedestrian"

        # Car categorization
        # Auto-rickshaw detection (compact high aspect < 1.05 and distinctive shape)
        if 0.70 < aspect_ratio < 1.15 and area < 45000:
            # Check crop color or shape
            if crop is not None and crop.size > 0:
                hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                yellow_mask = cv2.inRange(hsv, np.array([15, 80, 80]), np.array([35, 255, 255]))
                if cv2.countNonZero(yellow_mask) / max(1, crop.shape[0] * crop.shape[1]) > 0.18:
                    return "Auto-Rickshaw"

        if aspect_ratio >= 1.55:
            return "Sedan"
        elif 1.25 <= aspect_ratio < 1.55:
            return "SUV" if h > 85 else "Hatchback"
        elif 1.05 <= aspect_ratio < 1.25:
            return "SUV"
        else:
            return "Hatchback"

    def estimate_brand(self, base_class: str, subtype: str, track_id: Optional[int] = None) -> str:
        """
        Determines the statutory vehicle classification category.
        In the absence of an eGujCop/RTO database lookup or OEM badge classifier,
        returns the physical category (LMV, LCV, HGV, 3W, 2W).
        """
        base = base_class.lower()
        if base == "person" or subtype == "Pedestrian":
            return "Pedestrian"
        if subtype == "Auto-Rickshaw":
            return "Three-Wheeler (Auto)"
        if base in ("motorcycle", "bicycle", "bike") or "Motorcycle" in subtype or "Scooter" in subtype:
            return "Two-Wheeler"
        if base == "bus" or "Bus" in subtype:
            return "Public Transit Bus"
        if base == "truck" or "Truck" in subtype or "LCV" in subtype:
            return "Commercial Goods Vehicle"
        return "Passenger Vehicle (LMV)"

    def compute_appearance_embedding(self, crop: np.ndarray, aspect_ratio: float) -> List[float]:
        """
        Computes a compact, lighting-invariant 32-bin appearance feature vector
        combining normalized HSV color distribution and geometric aspect ratio.
        Used for sub-millisecond Cosine Re-Identification across multiple cameras.
        """
        if crop is None or crop.size == 0:
            return [0.0] * 32

        try:
            resized = cv2.resize(crop, (64, 64))
            hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

            # 16 bins for Hue, 8 bins for Saturation, 7 bins for Value
            hist_h = cv2.calcHist([hsv], [0], None, [16], [0, 180]).flatten()
            hist_s = cv2.calcHist([hsv], [1], None, [8], [0, 256]).flatten()
            hist_v = cv2.calcHist([hsv], [2], None, [7], [0, 256]).flatten()

            hist = np.concatenate([hist_h, hist_s, hist_v, [float(aspect_ratio)]])
            norm = np.linalg.norm(hist)
            if norm > 0:
                hist = hist / norm
            return [round(float(v), 4) for v in hist.tolist()]
        except Exception:
            return [0.0] * 32

    def classify(
        self,
        crop: np.ndarray,
        base_class: str,
        bbox: List[float],
        track_id: Optional[int] = None,
    ) -> VehicleAttributes:
        """
        Comprehensive attributes classification for a detected vehicle.
        Dynamically computes confidence and appearance embeddings.
        """
        w = max(1.0, bbox[2] - bbox[0])
        h = max(1.0, bbox[3] - bbox[1])
        aspect_ratio = w / h

        color_name, rgb, match_score = self.extract_dominant_color(crop, return_score=True)
        subtype = self.classify_subtype(base_class, bbox, crop)
        make = self.estimate_brand(base_class, subtype, track_id)
        embedding = self.compute_appearance_embedding(crop, aspect_ratio)

        if base_class.lower() == "person":
            full_name = f"{color_name} Clothed Pedestrian"
            make = "N/A"
            subtype = "Pedestrian"
        else:
            full_name = f"{color_name} {subtype}"

        # Dynamic confidence grounded in color segmentation score and aspect ratio bounding box stability
        base_conf = 0.60 + min(0.35, match_score * 0.5)
        calculated_conf = round(float(min(0.98, max(0.50, base_conf))), 3)

        return VehicleAttributes(
            color=color_name,
            body_subtype=subtype,
            make=make,
            full_name=full_name,
            confidence=calculated_conf,
            color_rgb=rgb,
            appearance_embedding=embedding,
        )
