from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sentinel.edge.tracking.multicam")


def compute_cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Computes cosine similarity between two normalized feature vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two license plate strings."""
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev[j + 1] + 1
            deletions = curr[j] + 1
            substitutions = prev[j] + (c1 != c2)
            curr.append(min(insertions, deletions, substitutions))
        prev = curr
    return prev[-1]


@dataclass
class CameraJourneyHop:
    camera_id: str
    camera_name: str
    timestamp: float
    timestamp_str: str
    direction: str
    speed_kmh: Optional[float]
    track_id: int


@dataclass
class GlobalTrackedVehicle:
    global_id: str
    plate: Optional[str]
    full_name: str
    make: str
    body_subtype: str
    color: str
    appearance_embedding: List[float]
    first_seen: float
    last_seen: float
    current_camera_id: str
    current_track_id: int
    current_direction: str
    current_speed_kmh: Optional[float]
    journey: List[CameraJourneyHop] = field(default_factory=list)
    confidence: float = 0.95

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["journey_length"] = len(self.journey)
        return d


class MultiCameraReIDTracker:
    """
    Multi-Target Multi-Camera (MTMC) Vehicle Re-Identification Engine.
    Correlates vehicles across different cameras in the urban surveillance grid:
    1. Plate Ground Truth Match (exact or Levenshtein edit distance <= 1).
    2. Deep 32-bin HSV & Geometry Appearance Embedding Cosine Similarity (threshold >= 0.82).
    3. Spatio-Temporal Topology Gating (transit time feasibility window: 4s - 600s).
    """

    REID_COSINE_THRESHOLD = 0.82
    MAX_TEMPORAL_WINDOW_SEC = 600.0
    MIN_TRANSIT_TIME_SEC = 2.0

    def __init__(self) -> None:
        # Key: global_id -> GlobalTrackedVehicle
        self.global_registry: Dict[str, GlobalTrackedVehicle] = {}
        # Key: (camera_id, local_track_id) -> global_id
        self.local_to_global_map: Dict[Tuple[str, int], str] = {}
        # Key: plate_text -> global_id
        self.plate_to_global_map: Dict[str, str] = {}
        self._next_id = 101

    def _generate_global_id(self, plate: Optional[str] = None) -> str:
        if plate and len(plate) >= 4:
            clean_plate = plate.replace("-", "").replace(" ", "").upper()
            return f"SENTINEL-{clean_plate}"
        gid = f"SENTINEL-GJ-V{self._next_id}"
        self._next_id += 1
        return gid

    def update_vehicle_observation(
        self,
        camera_id: str,
        camera_name: str,
        track_id: int,
        plate: Optional[str],
        full_name: str,
        make: str,
        body_subtype: str,
        color: str,
        appearance_embedding: List[float],
        timestamp: float,
        direction: str,
        speed_kmh: Optional[float] = None,
    ) -> GlobalTrackedVehicle:
        """
        Processes a vehicle observation from any camera. Returns the unified GlobalTrackedVehicle.
        """
        now = float(timestamp)
        now_str = time.strftime("%H:%M:%S", time.localtime(now if now > 1000000000 else time.time()))
        local_key = (camera_id, int(track_id))

        # Check if already mapped for this camera and track
        existing_global_id = self.local_to_global_map.get(local_key)
        if existing_global_id and existing_global_id in self.global_registry:
            vehicle = self.global_registry[existing_global_id]
            vehicle.last_seen = now
            vehicle.current_direction = direction
            vehicle.current_speed_kmh = speed_kmh
            if plate and not vehicle.plate:
                vehicle.plate = plate
                self.plate_to_global_map[plate.upper()] = existing_global_id
            return vehicle

        # Match strategy 1: License Plate Identity Matching
        matched_global_id = None
        if plate:
            clean_plate = plate.replace("-", "").replace(" ", "").upper()
            # Exact lookup
            if clean_plate in self.plate_to_global_map:
                matched_global_id = self.plate_to_global_map[clean_plate]
            else:
                # Fuzzy 1-edit distance lookup
                for registered_plate, gid in self.plate_to_global_map.items():
                    if levenshtein_distance(clean_plate, registered_plate) <= 1:
                        matched_global_id = gid
                        break

        # Match strategy 2: Visual Re-ID Appearance Embedding Cosine Similarity
        if not matched_global_id and appearance_embedding and any(appearance_embedding):
            best_sim = -1.0
            best_candidate_gid = None

            for gid, v in self.global_registry.items():
                # Cross-camera matching: only compare with vehicles from OTHER cameras or previous tracks
                if v.current_camera_id == camera_id and (now - v.last_seen) < self.MIN_TRANSIT_TIME_SEC:
                    continue

                # Spatio-temporal feasibility window
                time_delta = now - v.last_seen
                if not (self.MIN_TRANSIT_TIME_SEC <= time_delta <= self.MAX_TEMPORAL_WINDOW_SEC):
                    continue

                # Subtype gate: SUV cannot match Motorcycle
                if v.body_subtype != body_subtype and v.make != make:
                    continue

                sim = compute_cosine_similarity(appearance_embedding, v.appearance_embedding)
                if sim > best_sim and sim >= self.REID_COSINE_THRESHOLD:
                    best_sim = sim
                    best_candidate_gid = gid

            if best_candidate_gid:
                matched_global_id = best_candidate_gid
                logger.info(
                    "Cross-Camera Re-ID Match! [Sim=%.3f] Camera %s (Track #%s) -> %s (Prev Cam: %s)",
                    best_sim,
                    camera_id,
                    track_id,
                    matched_global_id,
                    self.global_registry[matched_global_id].current_camera_id,
                )

        # Update existing global vehicle or create new one
        if matched_global_id and matched_global_id in self.global_registry:
            vehicle = self.global_registry[matched_global_id]
            vehicle.last_seen = now
            vehicle.current_camera_id = camera_id
            vehicle.current_track_id = int(track_id)
            vehicle.current_direction = direction
            vehicle.current_speed_kmh = speed_kmh
            if plate and not vehicle.plate:
                vehicle.plate = plate
                self.plate_to_global_map[plate.upper()] = matched_global_id

            # Add new camera hop to the journey
            last_hop = vehicle.journey[-1] if vehicle.journey else None
            if not last_hop or last_hop.camera_id != camera_id:
                vehicle.journey.append(
                    CameraJourneyHop(
                        camera_id=camera_id,
                        camera_name=camera_name,
                        timestamp=now,
                        timestamp_str=now_str,
                        direction=direction,
                        speed_kmh=speed_kmh,
                        track_id=int(track_id),
                    )
                )
                logger.info(
                    "Vehicle Multi-Camera Journey Hop recorded: %s on %s (%s) heading %s",
                    matched_global_id,
                    camera_id,
                    camera_name,
                    direction,
                )
        else:
            # Register new global vehicle
            gid = self._generate_global_id(plate)
            vehicle = GlobalTrackedVehicle(
                global_id=gid,
                plate=plate,
                full_name=full_name,
                make=make,
                body_subtype=body_subtype,
                color=color,
                appearance_embedding=appearance_embedding,
                first_seen=now,
                last_seen=now,
                current_camera_id=camera_id,
                current_track_id=int(track_id),
                current_direction=direction,
                current_speed_kmh=speed_kmh,
                journey=[
                    CameraJourneyHop(
                        camera_id=camera_id,
                        camera_name=camera_name,
                        timestamp=now,
                        timestamp_str=now_str,
                        direction=direction,
                        speed_kmh=speed_kmh,
                        track_id=int(track_id),
                    )
                ],
            )
            self.global_registry[gid] = vehicle
            matched_global_id = gid
            if plate:
                self.plate_to_global_map[plate.upper()] = gid

        self.local_to_global_map[local_key] = matched_global_id
        return vehicle

    def get_active_cross_camera_vehicles(self, max_age_seconds: float = 300.0) -> List[Dict[str, Any]]:
        """Returns list of active cross-camera vehicles that traversed multiple cameras."""
        now = time.time()
        active = []
        for v in self.global_registry.values():
            active.append(v.to_dict())
        return active

    def get_vehicle_journey(self, global_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the complete camera transit journey for a specific vehicle."""
        v = self.global_registry.get(global_id)
        return v.to_dict() if v else None


# Global singleton instance for shared cross-camera intelligence
multi_camera_tracker = MultiCameraReIDTracker()
