from __future__ import annotations

import collections
import logging
import math
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from ultralytics import YOLO

from sentinel_edge.calibration.homography import CameraCalibration, HomographyCalibrator
try:
    from sentinel_edge.inference.vehicle_classifier import VehicleAttributeClassifier
    from sentinel_edge.tracking.multi_camera import multi_camera_tracker
except ImportError:
    from .vehicle_classifier import VehicleAttributeClassifier
    from ..tracking.multi_camera import multi_camera_tracker

logger = logging.getLogger("sentinel.edge.tracker")


def calculate_iou(box_a: list[float], box_b: list[float]) -> tuple[float, float]:
    """
    Calculates exact geometric Intersection over Union (IoU) and intersection area
    between two bounding boxes [x1, y1, x2, y2].
    IoU = Area(A ∩ B) / Area(A ∪ B)
    """
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h

    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union_area = area_a + area_b - inter_area

    if union_area <= 0.0:
        return 0.0, 0.0
    return inter_area / union_area, inter_area


class TrackedDetection(dict):
    """
    Unified detection dictionary supporting both attribute access (.track_id, .bbox, etc.)
    and dict subscript access. Guarantees safety against AttributeError.
    """
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            if name == "class_name":
                return self.get("object_type", "vehicle")
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle", "bike", "vehicle"}


def compute_approach_cosine(hist_a: list[dict[str, Any]], hist_b: list[dict[str, Any]]) -> float:
    """
    Computes trajectory directional cosine similarity between the net displacement vectors
    of vehicles A and B over their approach window.
    Returns:
      <= 0.65: Cross-traffic, angled intersection, or head-on collision.
      >  0.65: Parallel lane queueing / same-direction traffic stream.
    """
    win = min(len(hist_a), len(hist_b), 25)
    if win < 3:
        return 1.0

    dx_a = hist_a[-1]["smooth_cx"] - hist_a[-win]["smooth_cx"]
    dy_a = hist_a[-1]["smooth_cy"] - hist_a[-win]["smooth_cy"]
    mag_a = math.hypot(dx_a, dy_a)

    dx_b = hist_b[-1]["smooth_cx"] - hist_b[-win]["smooth_cx"]
    dy_b = hist_b[-1]["smooth_cy"] - hist_b[-win]["smooth_cy"]
    mag_b = math.hypot(dx_b, dy_b)

    if mag_a > 15.0 and mag_b > 15.0:
        return (dx_a * dx_b + dy_a * dy_b) / (mag_a * mag_b)

    # If one is stationary, evaluate moving vehicle's instantaneous approach samples
    cos_samples = []
    for k in range(1, win + 1):
        pa, pb = hist_a[-k], hist_b[-k]
        spa, spb = pa.get("speed", 0.0), pb.get("speed", 0.0)
        if spa > 15.0 and spb > 15.0:
            cos_samples.append((pa["vx"] * pb["vx"] + pa["vy"] * pb["vy"]) / (spa * spb))

    if cos_samples:
        return sum(cos_samples) / len(cos_samples)
    return 1.0


class VehicleRiskAnalyzer:
    """
    Gujarat Police CCTV Diamond V12 Kinematic Collision & Risk Assessment Engine:
    1. Centroid EMA Smoothing: Eliminates frame-by-frame tracker jitter.
    2. Kinetic Approach & Momentum Transfer: Collisions require high kinetic approach energy ((prior_va + prior_vb) >= 150 px/s).
    3. Trajectory Cosine Separation: Distinguishes crossing/angled collisions (cos <= 0.65) from same-lane queues (cos > 0.65).
    4. Structural Penetration & Deceleration Shock: Real impacts drop combined speed precipitously (speed_drop >= 110 px/s).
    5. Duplicate Detection Filtering: Rejects duplicate overlapping bounding boxes (IoU >= 0.50, d_norm <= 0.25).
    6. Strict 2-Vehicle Wreckage Anchor: Wreckage tracking is strictly locked to {tid_a, tid_b}, immune to queue absorption.
    """

    def __init__(
        self,
        fps: float = 25.0,
        ema_alpha: float = 0.65,
        min_vote_threshold: int = 2,
        calibration: Optional[CameraCalibration] = None,
    ):
        self.fps = max(1.0, fps)
        self.ema_alpha = ema_alpha
        self.min_vote_threshold = min_vote_threshold
        self.calibration = calibration
        self.calibrator: Optional[HomographyCalibrator] = (
            HomographyCalibrator(calibration) if calibration else None
        )

        self.trajectories: dict[int, list[dict[str, Any]]] = {}
        self.watchlist_plates: set[str] = set()
        self.active_collision_tracks: set[int] = set()
        self.collision_votes: dict[tuple[int, int], int] = {}
        self.anomaly_votes: dict[int, int] = {}
        self.incidents: list[dict[str, Any]] = []
    def reset(self) -> None:
        """Flushes short-lived tracking and kinematic state (called on generation change/discontinuity)."""
        self.trajectories.clear()
        self.active_collision_tracks.clear()
        self.collision_votes.clear()
        self.anomaly_votes.clear()
        self.incidents.clear()
        logger.info("VehicleRiskAnalyzer short-lived state flushed")

    def set_calibration(self, calibration: Optional[CameraCalibration]) -> None:
        """Dynamically attach or update camera homography calibration."""
        self.calibration = calibration
        self.calibrator = HomographyCalibrator(calibration) if calibration else None
        # Per Phase 3 Step 7: Reset velocity state when calibration changes
        self.reset()
        logger.info(
            "Camera calibration updated for risk analyzer | camera_id=%s | active=%s",
            calibration.camera_id if calibration else "None",
            calibration.is_active if calibration else False,
        )

    def update_watchlist(self, plates: set[str] | list[str]) -> None:
        """Update active eGujCop flagged plates (normalized alphanumeric)."""
        self.watchlist_plates = {
            "".join(c for c in p.upper() if c.isalnum())
            for p in plates if p
        }

    def is_watchlist_match(self, plate: str | None) -> bool:
        if not plate:
            return False
        clean = "".join(c for c in plate.upper() if c.isalnum())
        return clean in self.watchlist_plates

    def assess_risk(
        self,
        track_id: int | None,
        bbox: list[float],
        frame_shape: tuple[int, int] | None = None,
        plate: str | None = None,
        current_time: float = 0.0,
    ) -> tuple[str, str, str]:
        """Single-vehicle standalone assessment."""
        if self.is_watchlist_match(plate):
            return "HIGH", "#ef4444", f"eGujCop Watchlist Match ({plate})"

        if track_id is not None and track_id in self.active_collision_tracks:
            return "CRITICAL", "#ef4444", "CRITICAL: VEHICLE COLLISION (Stationary Incident Vehicle)"

        return "LOW", "#10b981", "Standard Patrol Track"

    def analyze_frame_kinematics(
        self,
        detections: list[TrackedDetection],
        frame_shape: tuple[int, int] | None = None,
        current_time: float = 0.0,
    ) -> None:
        """
        Batch Kinematic Analysis with Centroid EMA Smoothing, Trajectory Cosines,
        Kinetic Momentum Thresholds, Strict 2-Vehicle Wreckage Tracking, and
        Physically Validated Homography Speed Calibration.
        """
        if not detections:
            return

        # ---------------------------------------------------------------------
        # 1. Centroid EMA Smoothing & Kinematics
        # ---------------------------------------------------------------------
        for det in detections:
            track_id = getattr(det, "track_id", det.get("track_id") if isinstance(det, dict) else None)
            bbox = getattr(det, "bbox", det.get("bbox") if isinstance(det, dict) else [0, 0, 0, 0])
            raw_cx = (bbox[0] + bbox[2]) / 2.0
            raw_cy = (bbox[1] + bbox[3]) / 2.0
            w = max(1.0, bbox[2] - bbox[0])
            h = max(1.0, bbox[3] - bbox[1])
            scale = math.sqrt(w * h)

            # Ground contact point approximation: Bottom-center of vehicle bounding box
            # DO NOT use centroid for physical road plane speed estimation
            gc_x = raw_cx
            gc_y = float(bbox[3])

            if track_id is not None:
                if track_id not in self.trajectories:
                    self.trajectories[track_id] = []
                history = self.trajectories[track_id]
                prev = history[-1] if history else None
                if prev:
                    smooth_cx = self.ema_alpha * raw_cx + (1.0 - self.ema_alpha) * prev["smooth_cx"]
                    smooth_cy = self.ema_alpha * raw_cy + (1.0 - self.ema_alpha) * prev["smooth_cy"]
                    # Mandatory Phase 2 & 3 Rule: dt is strictly derived from PTS (current_pts - prev_pts)
                    # Never use wall-clock arrival time or assumed FPS for physical timing.
                    raw_dt = current_time - prev["time"]

                    if raw_dt <= 0.0 or raw_dt > 5.0:
                        # Timing anomaly or PTS discontinuity (> 5s gap or backwards jump)
                        dt = max(0.001, raw_dt)
                        vx_px_s, vy_px_s, velocity_px_s, theta, accel_px_s2 = 0.0, 0.0, 0.0, 0.0, 0.0
                        speed_kmh = None
                        speed_status = "INVALID_TIMING"
                        speed_display_reason = f"PTS discontinuity detected (dt={raw_dt:.3f}s)"
                        calibration_id = self.calibrator.calibration.id if (self.calibrator and self.calibrator.calibration.is_active) else None
                    else:
                        dt = raw_dt
                        # Internal image-space pixel velocity (strictly isolated from km/h)
                        vx_px_s = (smooth_cx - prev["smooth_cx"]) / dt
                        vy_px_s = (smooth_cy - prev["smooth_cy"]) / dt
                        velocity_px_s = math.hypot(vx_px_s, vy_px_s)
                        theta = math.atan2(vy_px_s, vx_px_s)
                        prev_vel = prev.get("velocity_px_s", prev.get("speed", 0.0))
                        accel_px_s2 = (velocity_px_s - prev_vel) / dt

                        # Physical road-plane speed calculation via Planar Homography Matrix
                        if self.calibrator and self.calibrator.calibration.is_active:
                            prev_gc = prev.get("ground_contact", (prev["smooth_cx"], prev["bbox"][3]))
                            speed_val, raw_status, reason = self.calibrator.compute_ground_speed(
                                prev_image_point=prev_gc,
                                curr_image_point=(gc_x, gc_y),
                                dt_seconds=dt,
                            )
                            if raw_status == "VALID":
                                speed_kmh = speed_val
                                speed_status = "VALID"
                                speed_display_reason = None
                            elif raw_status == "INVALID_MEASUREMENT" and reason and "Delta timestamp" in str(reason):
                                speed_kmh = None
                                speed_status = "INVALID_TIMING"
                                speed_display_reason = reason
                            else:
                                speed_kmh = None
                                speed_status = "INVALID_MEASUREMENT"
                                speed_display_reason = reason
                            calibration_id = self.calibrator.calibration.id
                        else:
                            speed_kmh = None
                            speed_status = "CALIBRATION_REQUIRED"
                            speed_display_reason = "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED"
                            calibration_id = None
                else:
                    smooth_cx, smooth_cy = raw_cx, raw_cy
                    vx_px_s, vy_px_s, velocity_px_s, theta, accel_px_s2 = 0.0, 0.0, 0.0, 0.0, 0.0
                    if self.calibrator and self.calibrator.calibration.is_active:
                        speed_kmh = None
                        speed_status = "INSUFFICIENT_TRACK_HISTORY"
                        speed_display_reason = "Tracking history initializing"
                        calibration_id = self.calibrator.calibration.id
                    else:
                        speed_kmh = None
                        speed_status = "CALIBRATION_REQUIRED"
                        speed_display_reason = "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED"
                        calibration_id = None

                heading_deg = (math.degrees(theta) + 360) % 360
                history.append({
                    "time": current_time,
                    "smooth_cx": smooth_cx,
                    "smooth_cy": smooth_cy,
                    "ground_contact": (gc_x, gc_y),
                    "w": w,
                    "h": h,
                    "scale": scale,
                    "vx": vx_px_s,
                    "vy": vy_px_s,
                    "speed": velocity_px_s,
                    "vx_px_s": vx_px_s,
                    "vy_px_s": vy_px_s,
                    "velocity_px_s": velocity_px_s,
                    "speed_kmh": speed_kmh,
                    "speed_status": speed_status,
                    "theta": theta,
                    "heading_deg": heading_deg,
                    "accel": accel_px_s2,
                    "accel_px_s2": accel_px_s2,
                    "bbox": bbox,
                })
                if len(history) > 60:
                    history.pop(0)

                # Strict metric naming isolation
                det["velocity_px_s"] = round(velocity_px_s, 2)
                det["vx_px_s"] = round(vx_px_s, 2)
                det["vy_px_s"] = round(vy_px_s, 2)
                det["accel_px_s2"] = round(accel_px_s2, 2)
                det["speed_kmh"] = speed_kmh
                det["speed_status"] = speed_status
                det["speed_display_reason"] = speed_display_reason
                det["calibration_id"] = calibration_id

                # Backward compatibility for internal consumers
                det["vx"] = round(vx_px_s, 2)
                det["vy"] = round(vy_px_s, 2)
                det["speed"] = round(velocity_px_s, 2)
                det["heading_deg"] = round(heading_deg, 1)
                det["acceleration"] = round(accel_px_s2, 2)
                det["smooth_cx"] = smooth_cx
                det["smooth_cy"] = smooth_cy
                det["scale"] = scale
                det["collision_detected"] = False
                det["collision_partner_id"] = None
                det["collision_evidence"] = None
                det["risk_level"] = "LOW"
                det["risk_priority"] = "LOW"
                det["risk_color"] = "#10b981"
                det["risk_reason"] = "Standard Patrol Track"
            else:
                det["velocity_px_s"] = 0.0
                det["vx_px_s"] = 0.0
                det["vy_px_s"] = 0.0
                det["accel_px_s2"] = 0.0
                det["speed_kmh"] = None
                det["speed_status"] = "CALIBRATION_REQUIRED" if not (self.calibrator and self.calibrator.calibration.is_active) else "INSUFFICIENT_TRACK_HISTORY"
                det["speed_display_reason"] = "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED" if not (self.calibrator and self.calibrator.calibration.is_active) else "Track ID unassigned"
                det["calibration_id"] = self.calibrator.calibration.id if self.calibrator else None
                det["vx"] = 0.0
                det["vy"] = 0.0
                det["speed"] = 0.0
                det["heading_deg"] = 0.0
                det["acceleration"] = 0.0
                det["smooth_cx"] = raw_cx
                det["smooth_cy"] = raw_cy
                det["scale"] = scale
                det["collision_detected"] = False
                det["collision_partner_id"] = None
                det["collision_evidence"] = None
                det["risk_level"] = "LOW"
                det["risk_priority"] = "LOW"
                det["risk_color"] = "#10b981"
                det["risk_reason"] = "Standard Patrol Track"

        # ---------------------------------------------------------------------
        # 2. Pairwise Kinetic Impact Dynamics
        # ---------------------------------------------------------------------
        num_dets = len(detections)
        for i in range(num_dets):
            det_a = detections[i]
            cls_a = getattr(det_a, "class_name", det_a.get("class_name", ""))
            if cls_a not in VEHICLE_CLASSES and det_a.get("object_type") not in VEHICLE_CLASSES:
                continue
            tid_a = getattr(det_a, "track_id", det_a.get("track_id"))
            if tid_a is None:
                continue

            for j in range(i + 1, num_dets):
                det_b = detections[j]
                cls_b = getattr(det_b, "class_name", det_b.get("class_name", ""))
                if cls_b not in VEHICLE_CLASSES and det_b.get("object_type") not in VEHICLE_CLASSES:
                    continue
                tid_b = getattr(det_b, "track_id", det_b.get("track_id"))
                if tid_b is None:
                    continue

                bbox_a = getattr(det_a, "bbox", [0, 0, 0, 0])
                bbox_b = getattr(det_b, "bbox", [0, 0, 0, 0])
                cx_a = det_a.get("smooth_cx", (bbox_a[0] + bbox_a[2]) / 2.0)
                cy_a = det_a.get("smooth_cy", (bbox_a[1] + bbox_a[3]) / 2.0)
                cx_b = det_b.get("smooth_cx", (bbox_b[0] + bbox_b[2]) / 2.0)
                cy_b = det_b.get("smooth_cy", (bbox_b[1] + bbox_b[3]) / 2.0)

                d_curr = math.hypot(cx_a - cx_b, cy_a - cy_b)
                iou, _ = calculate_iou(bbox_a, bbox_b)
                char_scale = 0.5 * (det_a.get("scale", 50.0) + det_b.get("scale", 50.0))
                d_norm = d_curr / max(1.0, char_scale)

                # Filter duplicate bounding boxes predicted on the exact same vehicle
                if (iou >= 0.50 and d_norm <= 0.25) or d_norm < 0.10 or iou > 0.65:
                    continue
                if d_norm > 1.15:
                    continue

                pair_key = tuple(sorted([tid_a, tid_b]))
                hist_a = self.trajectories.get(tid_a, [])
                hist_b = self.trajectories.get(tid_b, [])

                frame_hit = False
                hit_reason = ""

                if len(hist_a) >= 3 and len(hist_b) >= 3:
                    prior_va = max([p["speed"] for p in hist_a[:-min(2, len(hist_a))]], default=det_a.get("speed", 0.0))
                    prior_vb = max([p["speed"] for p in hist_b[:-min(2, len(hist_b))]], default=det_b.get("speed", 0.0))
                    v_comb = det_a.get("speed", 0.0) + det_b.get("speed", 0.0)
                    had_high_approach = ((prior_va + prior_vb) >= 150.0) and (prior_va >= 55.0 or prior_vb >= 55.0)

                    win = min(len(hist_a), len(hist_b), 15)
                    past_a = hist_a[-win]
                    past_b = hist_b[-win]
                    d_past = math.hypot(past_a["smooth_cx"] - past_b["smooth_cx"], past_a["smooth_cy"] - past_b["smooth_cy"])
                    d_past_norm = d_past / max(1.0, char_scale)
                    scale_collapsed = (d_past_norm - d_norm >= 0.12) or (d_past_norm > 1.20 * d_norm)

                    speed_drop = (prior_va + prior_vb) - v_comb
                    cos_sim = compute_approach_cosine(hist_a, hist_b)
                    is_cross_or_angled = (cos_sim <= 0.65)

                    # Condition A: Crossing / Angled Collision (mycctv4, mycctv1)
                    if is_cross_or_angled and had_high_approach:
                        # Sub-condition 1: Direct collapse with low post-impact velocity
                        if scale_collapsed and (iou >= 0.06 or d_norm <= 0.80) and v_comb < 65.0 and speed_drop >= 110.0:
                            frame_hit = True
                            hit_reason = f"CRITICAL: VEHICLE COLLISION (Cross Impact cos={cos_sim:.2f}, PostImpactSpeed={int(v_comb)}px/s)"
                        # Sub-condition 2: High-energy structural penetration with severe momentum transfer
                        elif (iou >= 0.14 or d_norm <= 0.50) and scale_collapsed and speed_drop >= 180.0:
                            frame_hit = True
                            hit_reason = f"CRITICAL: VEHICLE COLLISION (Structural Impact IoU={iou:.2f}, SpeedDrop={int(speed_drop)}px/s)"

                    # Condition B: Same-Lane Rear-End Crash (cos_sim > 0.65)
                    elif not is_cross_or_angled and had_high_approach:
                        if (iou >= 0.28 or d_norm <= 0.35) and speed_drop >= 120.0 and v_comb < 35.0 and scale_collapsed:
                            frame_hit = True
                            hit_reason = f"CRITICAL: VEHICLE COLLISION (Rear-End Crash IoU={iou:.2f}, SpeedDrop={int(speed_drop)}px/s)"

                if frame_hit:
                    self.collision_votes[pair_key] = self.collision_votes.get(pair_key, 0) + 1
                else:
                    self.collision_votes[pair_key] = max(0, self.collision_votes.get(pair_key, 0) - 1)

                votes = self.collision_votes.get(pair_key, 0)
                if votes >= self.min_vote_threshold and (iou > 0.02 or d_norm <= 0.85):
                    self.active_collision_tracks.add(tid_a)
                    self.active_collision_tracks.add(tid_b)

                    evidence = {
                        "trajectory_cosine": round(float(cos_sim), 3) if 'cos_sim' in locals() else None,
                        "box_iou": round(float(iou), 3),
                        "speed_drop_px_s": round(float(speed_drop), 1) if 'speed_drop' in locals() else None,
                        "approach_energy_px_s": round(float(prior_va + prior_vb), 1) if 'prior_va' in locals() else None,
                        "temporal_votes": int(votes),
                        "detection_status": "CONFIRMED_KINEMATIC_IMPACT",
                        "severity": "CRITICAL",
                    }

                    det_a["collision_detected"] = True
                    det_a["collision_partner_id"] = tid_b
                    det_a["collision_evidence"] = evidence
                    det_a["risk_level"] = "CRITICAL"
                    det_a["risk_priority"] = "HIGH"
                    det_a["risk_color"] = "#ef4444"
                    det_a["risk_reason"] = hit_reason or "CRITICAL: VEHICLE COLLISION (Confirmed Dynamic Impact)"

                    det_b["collision_detected"] = True
                    det_b["collision_partner_id"] = tid_a
                    det_b["collision_evidence"] = evidence
                    det_b["risk_level"] = "CRITICAL"
                    det_b["risk_priority"] = "HIGH"
                    det_b["risk_color"] = "#ef4444"
                    det_b["risk_reason"] = hit_reason or "CRITICAL: VEHICLE COLLISION (Confirmed Dynamic Impact)"

                    mid_x = (cx_a + cx_b) / 2.0
                    mid_y = (cy_a + cy_b) / 2.0
                    self._create_or_touch_incident(mid_x, mid_y, char_scale, current_time, tid_a, tid_b, bbox_a, bbox_b, reason=hit_reason)

        # ---------------------------------------------------------------------
        # 3. Incident Zone Wreckage Tracking (Strict Locked 2-Vehicle Rule)
        # ---------------------------------------------------------------------
        current_frame_tids = {
            getattr(d, "track_id", d.get("track_id"))
            for d in detections
            if getattr(d, "track_id", d.get("track_id")) is not None
        }

        for inc in self.incidents:
            if current_time - inc["last_seen"] > 45.0:
                continue

            anchor_x, anchor_y, r_fixed = inc["anchor_cx"], inc["anchor_cy"], inc["radius"]
            crashed_tids = inc["crashed_tids"]
            last_boxes = inc["last_boxes"]

            for det in detections:
                cls_name = getattr(det, "class_name", det.get("class_name", ""))
                if cls_name not in VEHICLE_CLASSES and det.get("object_type") not in VEHICLE_CLASSES:
                    continue
                tid = getattr(det, "track_id", det.get("track_id"))
                if tid is None:
                    continue

                d_to_anchor = math.hypot(det.get("smooth_cx", 0.0) - anchor_x, det.get("smooth_cy", 0.0) - anchor_y)
                if d_to_anchor > r_fixed:
                    continue

                # Case 1: Confirmed wreckage track
                if tid in crashed_tids:
                    if det.get("speed", 0.0) < 125.0:
                        inc["last_seen"] = current_time
                        inc["last_boxes"][tid] = det.get("bbox")
                        self.active_collision_tracks.add(tid)
                        partner = next(iter(crashed_tids - {tid}), None)
                        det["collision_detected"] = True
                        det["collision_partner_id"] = partner
                        det["risk_level"] = "CRITICAL"
                        det["risk_priority"] = "HIGH"
                        det["risk_color"] = "#ef4444"
                        det["risk_reason"] = "CRITICAL: VEHICLE COLLISION (Incident Zone Wreckage)"

                # Case 2: ByteTrack Re-ID for a lost wreckage vehicle
                else:
                    missing_tids = [t for t in crashed_tids if t not in current_frame_tids]
                    for m_tid in missing_tids:
                        prev_box = last_boxes.get(m_tid)
                        if prev_box:
                            iou_reid, _ = calculate_iou(det.get("bbox", [0, 0, 0, 0]), prev_box)
                            if iou_reid >= 0.40 and det.get("speed", 0.0) < 65.0:
                                crashed_tids.remove(m_tid)
                                crashed_tids.add(tid)
                                inc["last_boxes"][tid] = det.get("bbox")
                                inc["last_seen"] = current_time
                                self.active_collision_tracks.add(tid)
                                partner = next(iter(crashed_tids - {tid}), None)
                                det["collision_detected"] = True
                                det["collision_partner_id"] = partner
                                det["risk_level"] = "CRITICAL"
                                det["risk_priority"] = "HIGH"
                                det["risk_color"] = "#ef4444"
                                det["risk_reason"] = "CRITICAL: VEHICLE COLLISION (Incident Zone Wreckage)"
                                break

    def _create_or_touch_incident(
        self,
        cx: float,
        cy: float,
        scale: float,
        current_time: float,
        tid_a: int,
        tid_b: int,
        bbox_a: list[float],
        bbox_b: list[float],
        reason: str = "",
    ) -> None:
        radius = min(95.0, max(50.0, 1.3 * scale))
        for inc in self.incidents:
            if math.hypot(inc["anchor_cx"] - cx, inc["anchor_cy"] - cy) < radius:
                inc["last_seen"] = current_time
                return

        logger.info(
            "💥 INCIDENT CREATED at t=%.2fs | Anchor=(%d, %d) | Tracks=[%s, %s] | Reason: %s",
            current_time,
            int(cx),
            int(cy),
            tid_a,
            tid_b,
            reason,
        )
        self.incidents.append({
            "anchor_cx": cx,
            "anchor_cy": cy,
            "radius": radius,
            "t_start": current_time,
            "last_seen": current_time,
            "crashed_tids": {tid_a, tid_b},
            "last_boxes": {tid_a: bbox_a, tid_b: bbox_b},
        })


class VehicleTracker:
    """
    YOLO + ByteTrack wrapper with Centroid EMA, Trajectory Cosines,
    Kinetic Momentum Collisions, and Strict 2-Vehicle Wreckage Tracking.
    """

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.15,
        classes: list[int] = [0, 1, 2, 3, 5, 7],
        tracker: str = "bytetrack.yaml",
        image_size: int = 480,
        fps: float = 25.0,
        calibration: Optional[CameraCalibration] = None,
        camera_id: str = "cam01",
        camera_name: str = "Traffic Camera",
    ):
        self.model_path = model_path
        self.confidence = confidence
        self.classes = classes
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.classifier = VehicleAttributeClassifier()
        self.trajectories: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=30))
        
        # Resolve custom Sentinel ByteTrack configuration
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        resolved_tracker = tracker
        candidates = [
            tracker,
            os.path.join(base_dir, tracker),
            os.path.join(base_dir, "config", "bytetrack_sentinel.yaml"),
            os.path.join(os.path.dirname(base_dir), "edge", "config", "bytetrack_sentinel.yaml"),
        ]
        for cand in candidates:
            if cand and os.path.exists(cand) and cand.endswith(".yaml"):
                resolved_tracker = os.path.abspath(cand)
                break

        self.tracker = resolved_tracker
        self.image_size = image_size
        self.fps = fps
        self.current_stream_generation: Optional[int] = None
        self.risk_analyzer = VehicleRiskAnalyzer(fps=fps, calibration=calibration)

        logger.info("Loading YOLO model: %s", model_path)
        self.model = YOLO(model_path)
        logger.info(
            "Tracker initialized | camera=%s (%s) | tracker=%s | classes=%s | conf=%.2f | imgsz=%d | fps=%.2f | calibrated=%s",
            camera_id,
            camera_name,
            tracker,
            classes,
            confidence,
            image_size,
            fps,
            bool(calibration and calibration.is_active),
        )

    def set_calibration(self, calibration: Optional[CameraCalibration]) -> None:
        """Forward camera homography calibration to the risk analyzer."""
        self.risk_analyzer.set_calibration(calibration)

    def update_watchlist(self, plates: set[str] | list[str]) -> None:
        """Forward watchlist plates to risk analyzer."""
        self.risk_analyzer.update_watchlist(plates)

    def track(
        self,
        frame: Any,
        current_time: float = 0.0,
        stream_generation: Optional[int] = None,
    ) -> tuple[list[TrackedDetection], float]:
        start_time = time.perf_counter()

        # Support canonical FramePacket
        if hasattr(frame, "frame") and hasattr(frame, "pts_seconds"):
            pts_seconds = float(frame.pts_seconds)
            gen = getattr(frame, "stream_generation", None)
            raw_frame = frame.frame
        else:
            pts_seconds = float(current_time)
            gen = stream_generation
            raw_frame = frame

        # Stream generation boundary check: isolate tracker state across reconnects
        if gen is not None:
            if self.current_stream_generation is not None and gen != self.current_stream_generation:
                logger.info("Stream generation changed (%s -> %s). Flushing tracker state.", self.current_stream_generation, gen)
                self.reset()
            self.current_stream_generation = gen

        try:
            results = self.model.track(
                source=raw_frame,
                persist=True,
                tracker=self.tracker,
                classes=self.classes,
                conf=self.confidence,
                imgsz=self.image_size,
                verbose=False,
            )
        except Exception:
            logger.exception("YOLO tracking inference failed")
            raise

        latency_ms = (time.perf_counter() - start_time) * 1000
        detections: list[TrackedDetection] = []

        if not results:
            return detections, latency_ms

        result = results[0]
        if result.boxes is None:
            return detections, latency_ms

        boxes = result.boxes
        names = self.model.names
        frame_h, frame_w = raw_frame.shape[:2] if hasattr(raw_frame, "shape") else (1080, 1920)

        for i in range(len(boxes)):
            try:
                cls_id = int(boxes.cls[i].item()) if boxes.cls is not None else -1
                confidence = float(boxes.conf[i].item()) if boxes.conf is not None else 0.0

                bbox_tensor = boxes.xyxy[i]
                bbox = [
                    float(bbox_tensor[0].item()),
                    float(bbox_tensor[1].item()),
                    float(bbox_tensor[2].item()),
                    float(bbox_tensor[3].item()),
                ]

                norm_bbox = [
                    max(0.0, min(1.0, bbox[0] / max(1, frame_w))),
                    max(0.0, min(1.0, bbox[1] / max(1, frame_h))),
                    max(0.0, min(1.0, bbox[2] / max(1, frame_w))),
                    max(0.0, min(1.0, bbox[3] / max(1, frame_h))),
                ]

                track_id = None
                if boxes.id is not None:
                    try:
                        track_id = int(boxes.id[i].item())
                    except Exception:
                        track_id = None

                if isinstance(names, dict):
                    object_type = names.get(cls_id, str(cls_id))
                else:
                    object_type = names[cls_id] if 0 <= cls_id < len(names) else str(cls_id)

                center_x = (bbox[0] + bbox[2]) / 2.0
                center_y = (bbox[1] + bbox[3]) / 2.0

                detection = TrackedDetection(
                    object_type=object_type,
                    class_name=object_type,
                    class_id=cls_id,
                    confidence=confidence,
                    bbox=bbox,
                    norm_bbox=norm_bbox,
                    track_id=track_id,
                    center=[center_x, center_y],
                    risk_level="LOW",
                    risk_priority="LOW",
                    risk_color="#10b981",
                    risk_reason="Standard Patrol Track",
                    plate=None,
                )
                detections.append(detection)

            except Exception:
                logger.exception("Failed to parse detection | index=%s", i)

        # Batch kinematic physics analysis with EMA smoothing, momentum transfer, and locked incident tracking
        self.risk_analyzer.analyze_frame_kinematics(
            detections=detections,
            frame_shape=(frame_h, frame_w),
            current_time=pts_seconds,
        )

        # Fine-grained Vehicle Attributes, Trajectory Heading & Multi-Camera Re-ID
        for det in detections:
            tid = det.get("track_id")
            bbox = det.get("bbox", [0, 0, 0, 0])
            cx = det.get("smooth_cx", det.get("center", [0, 0])[0])
            cy = det.get("smooth_cy", det.get("center", [0, 0])[1])

            # 1. Trajectory & Heading Angle Vector
            if tid is not None:
                self.trajectories[tid].append((cx, cy))
                traj_list = list(self.trajectories[tid])
            else:
                traj_list = [(cx, cy)]
            det["trajectory"] = traj_list

            heading_deg = None
            direction = "Stationary / Slow"
            if len(traj_list) >= 3:
                dx = traj_list[-1][0] - traj_list[0][0]
                dy = traj_list[-1][1] - traj_list[0][1]
                mag = math.hypot(dx, dy)
                if mag > 10.0:
                    # Navigation bearing: 0 deg = North (-Y), 90 deg = East (+X), 180 deg = South (+Y), 270 deg = West (-X)
                    angle = (math.atan2(dx, -dy) * 180.0 / math.pi) % 360.0
                    heading_deg = round(angle, 1)

                    if angle >= 337.5 or angle < 22.5:
                        direction = "Northbound"
                    elif 22.5 <= angle < 67.5:
                        direction = "North-East"
                    elif 67.5 <= angle < 112.5:
                        direction = "Eastbound"
                    elif 112.5 <= angle < 157.5:
                        direction = "South-East"
                    elif 157.5 <= angle < 202.5:
                        direction = "Southbound"
                    elif 202.5 <= angle < 247.5:
                        direction = "South-West"
                    elif 247.5 <= angle < 292.5:
                        direction = "Westbound"
                    else:
                        direction = "North-West"
                elif det.get("speed_kmh") and det["speed_kmh"] > 4.0:
                    direction = "Moving"
            elif det.get("speed_kmh") and det["speed_kmh"] > 4.0:
                direction = "Moving"

            det["heading_deg"] = heading_deg
            det["direction"] = direction

            # 2. Extract visual perception crop for attribute classification
            crop = None
            if hasattr(raw_frame, "shape") and len(raw_frame.shape) >= 2:
                x1 = max(0, min(int(round(bbox[0])), frame_w - 1))
                y1 = max(0, min(int(round(bbox[1])), frame_h - 1))
                x2 = max(0, min(int(round(bbox[2])), frame_w))
                y2 = max(0, min(int(round(bbox[3])), frame_h))
                if x2 > x1 and y2 > y1:
                    crop = raw_frame[y1:y2, x1:x2]

            # 3. Vehicle Classification: Make, Body Subtype, Dominant Color, Appearance Vector
            attr = self.classifier.classify(
                crop=crop,
                base_class=det.get("object_type", "vehicle"),
                bbox=bbox,
                track_id=tid,
            )
            det["make"] = attr.make
            det["model_subtype"] = attr.body_subtype
            det["color"] = attr.color
            det["full_name"] = attr.full_name
            det["color_rgb"] = list(attr.color_rgb)
            det["appearance_embedding"] = attr.appearance_embedding

            # 4. Multi-Camera Re-ID Global Registration & Journey Mapping
            speed_val = det.get("speed_kmh")
            global_veh = multi_camera_tracker.update_vehicle_observation(
                camera_id=self.camera_id,
                camera_name=self.camera_name,
                track_id=tid if tid is not None else 0,
                plate=det.get("plate"),
                full_name=attr.full_name,
                make=attr.make,
                body_subtype=attr.body_subtype,
                color=attr.color,
                appearance_embedding=attr.appearance_embedding,
                timestamp=pts_seconds if pts_seconds > 0 else time.time(),
                direction=direction,
                speed_kmh=speed_val,
            )
            det["global_id"] = global_veh.global_id
            det["journey_length"] = len(global_veh.journey)
            det["is_reid_match"] = len(global_veh.journey) > 1

        return detections, latency_ms

    def reset(self) -> None:
        """Reset tracker state and kinematics."""
        try:
            self.model.predictor = None
            self.risk_analyzer.reset()
            self.trajectories.clear()
            logger.info("Tracker state reset")
        except Exception:
            logger.exception("Failed to reset tracker state")

    def metrics(self) -> dict[str, Any]:
        return {
            "model": self.model_path,
            "tracker": self.tracker,
            "confidence": self.confidence,
            "classes": self.classes,
            "image_size": self.image_size,
            "fps": self.fps,
        }