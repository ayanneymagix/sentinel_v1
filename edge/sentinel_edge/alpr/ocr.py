from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple
import cv2
import numpy as np
import easyocr

from .validator import PlateValidator

logger = logging.getLogger("sentinel.edge.alpr.ocr")


class PlateOCR:
    """
    OpenCV + EasyOCR Advanced Plate Perception Engine.
    Implements:
    1. Quality Gate: Laplacian variance blur detection & geometric size thresholding.
    2. Enhancement Pipeline: Grayscale, Bilateral Noise Filtering, and CLAHE adaptive contrast.
    3. Positional character extraction & candidate ranking.
    """

    MIN_WIDTH = 60
    MIN_HEIGHT = 18
    DEFAULT_BLUR_THRESHOLD = 45.0  # Minimum Laplacian variance for legible OCR

    def __init__(
        self,
        languages: Optional[List[str]] = None,
        gpu: bool = False,
        min_blur_score: float = DEFAULT_BLUR_THRESHOLD,
    ) -> None:
        self.languages = languages or ["en"]
        self.gpu = gpu
        self.min_blur_score = float(min_blur_score)
        logger.info(
            "Initializing Advanced ALPR OCR | languages=%s | gpu=%s | min_blur=%.1f",
            self.languages,
            self.gpu,
            self.min_blur_score,
        )
        self.reader = easyocr.Reader(self.languages, gpu=self.gpu)
        # Pre-instantiate CLAHE object
        self.clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))

    @staticmethod
    def calculate_blur_score(image: np.ndarray) -> float:
        """
        Calculate variance of the Laplacian to evaluate image focus / sharpness.
        Higher values (> 45.0) indicate sharp, high-contrast edges suitable for OCR.
        """
        if image is None or image.size == 0:
            return 0.0
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        OpenCV Enhancement Pipeline:
        1. Resizes plate to standardized height (~72px) maintaining aspect ratio.
        2. Converts to Grayscale.
        3. Applies Bilateral Filtering (removes camera noise while preserving sharp character contours).
        4. Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) to overcome shadows and headlight glare.
        Returns: (enhanced_image, blur_score)
        """
        h, w = image.shape[:2]

        # Calculate blur variance on raw image first
        blur_score = self.calculate_blur_score(image)

        # Scale to optimal character recognition height (72px)
        target_h = 72
        scale = target_h / max(1, h)
        target_w = max(60, int(w * scale))
        resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_CUBIC)

        # Convert to Grayscale
        if len(resized.shape) == 3:
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        else:
            gray = resized

        # Bilateral filter: d=9, sigmaColor=75, sigmaSpace=75
        # Preserves crisp character edges while flattening sensory noise
        filtered = cv2.bilateralFilter(gray, 9, 75, 75)

        # CLAHE contrast enhancement
        enhanced = self.clahe.apply(filtered)

        return enhanced, blur_score

    def read(self, plate_image: np.ndarray) -> Tuple[Optional[str], float, float]:
        """
        Execute OCR reading on cropped plate image with strict Quality Gating.
        Returns: (recognized_plate_text, ocr_confidence, blur_score)
        """
        if plate_image is None or plate_image.size == 0:
            return None, 0.0, 0.0

        h, w = plate_image.shape[:2]

        # 1. Quality Gate: Size Check
        if w < self.MIN_WIDTH or h < self.MIN_HEIGHT:
            logger.debug("Discarding undersized plate crop (%dx%d < %dx%d)", w, h, self.MIN_WIDTH, self.MIN_HEIGHT)
            return None, 0.0, 0.0

        # 2. Quality Gate: Blurriness Check
        enhanced, blur_score = self.preprocess(plate_image)
        if blur_score < self.min_blur_score:
            logger.debug("Discarding blurry plate crop (Laplacian Var=%.1f < %.1f)", blur_score, self.min_blur_score)
            return None, 0.0, blur_score

        # 3. EasyOCR Text Recognition on Enhanced Image
        try:
            results = self.reader.readtext(enhanced, detail=1, paragraph=False)
        except Exception as e:
            logger.exception("EasyOCR inference error: %s", e)
            return None, 0.0, blur_score

        if not results:
            return None, 0.0, blur_score

        candidates: List[Tuple[str, float]] = []
        for res in results:
            if len(res) < 3:
                continue
            raw_text = res[1]
            conf = float(res[2])
            cleaned = PlateValidator.clean(raw_text)
            if cleaned and len(cleaned) >= 4:
                candidates.append((cleaned, conf))

        if not candidates:
            return None, 0.0, blur_score

        # If multiple text boxes detected, concatenate if adjacent or take highest confidence
        if len(candidates) > 1:
            # Sort candidates by x-coordinate if available, or take longest combined
            combined = "".join(c[0] for c in candidates)
            combined_conf = sum(c[1] for c in candidates) / len(candidates)
            if 8 <= len(combined) <= 11:
                return combined, combined_conf, blur_score

        # Return best candidate
        best_candidate, best_conf = max(candidates, key=lambda item: (len(item[0]) >= 8, item[1]))
        return best_candidate, best_conf, blur_score
