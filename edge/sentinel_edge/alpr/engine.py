from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np

from .ocr import PlateOCR
from .plate_detector import PlateDetector
from .temporal import TemporalPlateAggregator
from .validator import PlateValidator

logger = logging.getLogger("sentinel.edge.alpr.engine")


@dataclass(frozen=True)
class ALPRResult:
    track_id: int
    plate_text: Optional[str]
    plate_confidence: float
    detector_confidence: float
    recognized: bool
    timestamp: float
    vote_count: int = 0
    is_finalized: bool = False
    blur_score: float = 0.0


class ALPREngine:
    """
    State-Grade Automated License Plate Recognition (ALPR) Engine.
    Conforms to Gujarat Police Model 2 & Model 4 mandate and sveyek Video-ANPR architecture:
    
    1. YOLOv8 Plate Detector with strict confidence gating (> 0.60).
    2. Blurriness Quality Gate (Laplacian Variance >= 45.0) & Size Gate (width >= 60px).
    3. Bilateral Noise Filtering + CLAHE Adaptive Histogram Equalization.
    4. Best-Frame Geometric Weighting (perspective scale & center proximity).
    5. Track-ID Temporal Rolling Buffer with Character Consensus Voting.
    6. Strict Indian Plate Regex Validation and Positional Fuzzy Correction.
    """

    def __init__(
        self,
        plate_model_path: str,
        detector_confidence: float = 0.60,
        detector_image_size: int = 640,
        ocr_gpu: bool = False,
        temporal_observations: int = 15,
        temporal_minimum_votes: int = 5,
        min_blur_score: float = 45.0,
    ) -> None:
        self.detector = PlateDetector(
            model_path=plate_model_path,
            confidence=detector_confidence,
            image_size=detector_image_size,
        )
        self.ocr = PlateOCR(
            languages=["en"],
            gpu=ocr_gpu,
            min_blur_score=min_blur_score,
        )
        self.temporal = TemporalPlateAggregator(
            max_observations=temporal_observations,
            minimum_votes=temporal_minimum_votes,
        )
        self.min_blur_score = min_blur_score
        logger.info(
            "ALPREngine online | detector_conf=%.2f | min_votes=%d | min_blur=%.1f",
            detector_confidence,
            temporal_minimum_votes,
            min_blur_score,
        )

    def process(
        self,
        track_id: int,
        vehicle_crop: np.ndarray,
        timestamp: Optional[float] = None,
        frame_shape: Optional[Tuple[int, int]] = None,
        vehicle_bbox: Optional[List[float]] = None,
    ) -> ALPRResult:
        """
        Process a vehicle crop from the live camera stream.
        Optimized to save compute: checks finalized state, plate confidence, and blur gates
        before invoking EasyOCR.
        """
        tid = int(track_id)
        current_ts = time.monotonic() if timestamp is None else float(timestamp)

        # Optimization: If track already has a finalized plate, return cached result immediately
        finalized = self.temporal.get_finalized(tid)
        if finalized:
            plate_str, conf = finalized
            return ALPRResult(
                track_id=tid,
                plate_text=plate_str,
                plate_confidence=conf,
                detector_confidence=1.0,
                recognized=True,
                timestamp=current_ts,
                vote_count=self.temporal.minimum_votes,
                is_finalized=True,
                blur_score=100.0,
            )

        if vehicle_crop is None or vehicle_crop.size == 0:
            return ALPRResult(tid, None, 0.0, 0.0, False, current_ts)

        # -------------------------------------------------------------
        # 1. Plate Localization via YOLOv8 (Confidence Gate > 0.60)
        # -------------------------------------------------------------
        detection = self.detector.detect(vehicle_crop)
        if detection is None or detection.confidence < 0.60:
            best_t, best_c, count, is_fin = self.temporal.best(tid)
            return ALPRResult(
                track_id=tid,
                plate_text=best_t,
                plate_confidence=best_c,
                detector_confidence=detection.confidence if detection else 0.0,
                recognized=bool(best_t and is_fin),
                timestamp=current_ts,
                vote_count=count,
                is_finalized=is_fin,
            )

        # -------------------------------------------------------------
        # 2. Crop Plate & Blur Quality Gate
        # -------------------------------------------------------------
        plate_crop = self.detector.crop_plate(vehicle_crop, detection)
        if plate_crop is None:
            best_t, best_c, count, is_fin = self.temporal.best(tid)
            return ALPRResult(tid, best_t, best_c, detection.confidence, bool(best_t and is_fin), current_ts, count, is_fin)

        blur_score = self.ocr.calculate_blur_score(plate_crop)
        if blur_score < self.min_blur_score:
            # Discard blurry frame immediately to save compute
            best_t, best_c, count, is_fin = self.temporal.best(tid)
            return ALPRResult(tid, best_t, best_c, detection.confidence, bool(best_t and is_fin), current_ts, count, is_fin, blur_score)

        # -------------------------------------------------------------
        # 3. Geometric Best-Frame Metrics
        # -------------------------------------------------------------
        bbox_area = float(detection.area)
        center_dist = 0.20  # Default moderate proximity
        if frame_shape and vehicle_bbox:
            h_f, w_f = frame_shape[:2]
            cx = (vehicle_bbox[0] + vehicle_bbox[2]) / 2.0
            cy = (vehicle_bbox[1] + vehicle_bbox[3]) / 2.0
            fcx, fcy = w_f / 2.0, h_f / 2.0
            max_r = math.hypot(fcx, fcy)
            center_dist = math.hypot(cx - fcx, cy - fcy) / max(1.0, max_r)

        # -------------------------------------------------------------
        # 4. OCR Reading on Enhanced Plate Crop
        # -------------------------------------------------------------
        raw_text, ocr_confidence, blur_score = self.ocr.read(plate_crop)

        # -------------------------------------------------------------
        # 5. Validation & Temporal Buffering
        # -------------------------------------------------------------
        if raw_text:
            corrected = PlateValidator.fuzzy_correct(raw_text)
            if corrected and len(corrected) >= 6:
                self.temporal.add(
                    track_id=tid,
                    text=corrected,
                    confidence=ocr_confidence,
                    timestamp=current_ts,
                    bbox_area=bbox_area,
                    center_dist=center_dist,
                    blur_score=blur_score,
                )

        # -------------------------------------------------------------
        # 6. Consensus Temporal Query
        # -------------------------------------------------------------
        best_text, best_confidence, vote_count, is_finalized = self.temporal.best(tid)

        if is_finalized and best_text:
            logger.info(
                "🎯 [ALPR RECOGNIZED] Track #%d -> Plate: %s (Confidence: %.3f, Votes: %d)",
                tid,
                best_text,
                best_confidence,
                vote_count,
            )

        return ALPRResult(
            track_id=tid,
            plate_text=best_text,
            plate_confidence=best_confidence,
            detector_confidence=detection.confidence,
            recognized=bool(best_text and (is_finalized or vote_count >= self.temporal.minimum_votes)),
            timestamp=current_ts,
            vote_count=vote_count,
            is_finalized=is_finalized,
            blur_score=blur_score,
        )

    def clear_track(self, track_id: int) -> None:
        """Clear memory for track that left camera FOV."""
        self.temporal.clear_track(track_id)

    def reset(self) -> None:
        """Reset temporal state upon video loop or camera reconnection."""
        self.temporal.clear()
