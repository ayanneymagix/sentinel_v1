from __future__ import annotations

import logging
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .validator import PlateValidator

logger = logging.getLogger("sentinel.edge.alpr.temporal")


@dataclass
class PlateObservation:
    text: str
    confidence: float
    timestamp: float
    bbox_area: float = 0.0
    center_dist: float = 0.0
    blur_score: float = 50.0
    quality_weight: float = 1.0


class TemporalPlateAggregator:
    """
    Advanced Video-ANPR Temporal Voting & Aggregation Engine (sveyek architecture).
    
    Key Features:
    1. Track-ID Based Rolling Buffers: Stores the last N observations for each ByteTrack track_id.
    2. Best-Frame Geometric Weighting: Prioritizes plate reads with larger pixel areas
       and positions closer to the camera optical center (least perspective skew).
    3. Confidence-Weighted Consensus Voting: Accumulates weighted votes per candidate string
       and applies position-wise character alignment voting to eradicate single-character OCR flicker.
    4. Minimum Read Accumulation Gate: Requires at least `minimum_votes` (default 5)
       valid OCR reads before declaring a finalized plate decision.
    """

    def __init__(self, max_observations: int = 15, minimum_votes: int = 5) -> None:
        if max_observations < 1 or minimum_votes < 1:
            raise ValueError("max_observations and minimum_votes must be >= 1")
        self.max_observations = int(max_observations)
        self.minimum_votes = int(minimum_votes)
        self._observations: Dict[int, deque[PlateObservation]] = defaultdict(
            lambda: deque(maxlen=self.max_observations)
        )
        self._finalized_plates: Dict[int, Tuple[str, float]] = {}

    def add(
        self,
        track_id: int,
        text: str,
        confidence: float,
        timestamp: float,
        bbox_area: float = 0.0,
        center_dist: float = 0.0,
        blur_score: float = 50.0,
    ) -> None:
        """
        Record a validated OCR read for a tracked vehicle.
        Computes the frame geometric quality weight based on perspective & scale.
        """
        if not text:
            return

        tid = int(track_id)
        # Normalize and fuzzy-correct plate string
        clean_text = PlateValidator.fuzzy_correct(text)
        if not clean_text or len(clean_text) < 6:
            return

        # Best-frame quality weighting:
        # 1. Bounding box scale bonus: larger plates have higher optical fidelity (up to +50% weight)
        area_factor = min(1.0, max(0.0, bbox_area / 6000.0)) * 0.50

        # 2. Optical center proximity: plates near center suffer less lens distortion (up to +30% weight)
        center_penalty = min(1.0, max(0.0, center_dist)) * 0.30

        # 3. Sharpness variance bonus (Laplacian Var > 100 adds up to +20% weight)
        blur_factor = min(1.0, max(0.0, blur_score / 200.0)) * 0.20

        quality_weight = float(confidence) * (1.0 + area_factor + blur_factor) * (1.0 - center_penalty)

        obs = PlateObservation(
            text=clean_text,
            confidence=float(confidence),
            timestamp=float(timestamp),
            bbox_area=float(bbox_area),
            center_dist=float(center_dist),
            blur_score=float(blur_score),
            quality_weight=quality_weight,
        )

        self._observations[tid].append(obs)

    def best(self, track_id: int) -> Tuple[Optional[str], float, int, bool]:
        """
        Compute the confidence-weighted temporal consensus plate for a track.
        Returns: (best_plate_text, average_confidence, vote_count, is_finalized)
        """
        tid = int(track_id)

        # Return cached finalized decision if already locked with high confidence
        if tid in self._finalized_plates:
            plate, conf = self._finalized_plates[tid]
            count = len(self._observations.get(tid, []))
            return plate, conf, count, True

        observations = self._observations.get(tid)
        if not observations:
            return None, 0.0, 0, False

        vote_count = len(observations)

        # -------------------------------------------------------------
        # 1. Whole-String Confidence-Weighted Accumulation
        # -------------------------------------------------------------
        string_weights: Dict[str, float] = defaultdict(float)
        string_counts: Dict[str, int] = defaultdict(int)
        string_raw_confs: Dict[str, List[float]] = defaultdict(list)

        for obs in observations:
            string_weights[obs.text] += obs.quality_weight
            string_counts[obs.text] += 1
            string_raw_confs[obs.text].append(obs.confidence)

        # Top candidate by total weighted score
        best_str = max(string_weights.keys(), key=lambda s: string_weights[s])
        best_str_score = string_weights[best_str]
        avg_conf = sum(string_raw_confs[best_str]) / max(1, len(string_raw_confs[best_str]))

        # -------------------------------------------------------------
        # 2. Position-Wise Character Alignment Consensus
        # -------------------------------------------------------------
        # Find dominant string length among observations
        length_counts: Dict[int, int] = defaultdict(int)
        for obs in observations:
            length_counts[len(obs.text)] += 1

        dominant_len = max(length_counts.keys(), key=lambda l: length_counts[l])

        # If we have multiple reads of the dominant length, perform character voting
        dominant_reads = [obs for obs in observations if len(obs.text) == dominant_len]
        if len(dominant_reads) >= 3 and dominant_len in (9, 10, 11):
            char_votes: List[Dict[str, float]] = [defaultdict(float) for _ in range(dominant_len)]
            for obs in dominant_reads:
                for idx, char in enumerate(obs.text):
                    char_votes[idx][char] += obs.quality_weight

            consensus_chars = []
            for idx in range(dominant_len):
                best_char = max(char_votes[idx].keys(), key=lambda c: char_votes[idx][c])
                consensus_chars.append(best_char)

            consensus_str = "".join(consensus_chars)
            # Validate and fuzzy-correct the consensus string
            corrected_consensus = PlateValidator.fuzzy_correct(consensus_str)
            if PlateValidator.is_valid_strict(corrected_consensus):
                best_str = corrected_consensus

        # Final check against PlateValidator
        final_plate, is_valid = PlateValidator.validate_and_format(best_str)
        if not final_plate:
            final_plate = best_str

        # -------------------------------------------------------------
        # 3. Finalization Gate: Minimum 5 Valid Reads
        # -------------------------------------------------------------
        is_finalized = (vote_count >= self.minimum_votes and avg_conf >= 0.50)

        if is_finalized and is_valid:
            self._finalized_plates[tid] = (final_plate, avg_conf)
            logger.info(
                "🔒 [ALPR FINALIZED] Track #%d -> Plate: %s (Conf: %.3f, Votes: %d/%d)",
                tid,
                final_plate,
                avg_conf,
                vote_count,
                self.minimum_votes,
            )

        return final_plate, avg_conf, vote_count, is_finalized

    def is_finalized(self, track_id: int) -> bool:
        """Check if vehicle track has finalized its license plate."""
        return int(track_id) in self._finalized_plates

    def get_finalized(self, track_id: int) -> Optional[Tuple[str, float]]:
        """Retrieve locked plate text and confidence if finalized."""
        return self._finalized_plates.get(int(track_id))

    def clear_track(self, track_id: int) -> None:
        """Release buffered memory for an exited vehicle track."""
        tid = int(track_id)
        self._observations.pop(tid, None)
        self._finalized_plates.pop(tid, None)

    def clear(self) -> None:
        """Clear all tracks."""
        self._observations.clear()
        self._finalized_plates.clear()
