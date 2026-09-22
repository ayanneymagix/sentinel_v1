"""
SENTINEL Phase 3: Real Camera Physical Speed Calibration Automated Verification Suite
=====================================================================================
Comprehensive 12-Item Test Suite validating:
1. Planar homography coordinate mapping and invertibility
2. Ground-contact point projection (bottom-center anchor)
3. Known-distance physical transformation
4. Monotonic PTS-based dt calculation across frame drops
5. Physical speed formula (m/s to km/h) & numerical precision
6. Micro-motion jitter filtering (< 0.05m -> 0.0 km/h)
7. Uncalibrated state behavior (speed_kmh=None, CALIBRATION_REQUIRED)
8. Single-frame track behavior (speed_kmh=None, INSUFFICIENT_TRACK_HISTORY)
9. PTS discontinuity handling (gap > 5s or dt <= 0 triggers INVALID_TIMING)
10. Stream generation reset handling (velocity state flushed on reconnect)
11. Invalid calibration geometry rejection (collinear, degenerate, zero/negative dims)
12. Per-camera calibration isolation (cam01 calibrated, cam02 remains uncalibrated)
"""

import math
import os
import shutil
import sys
import tempfile
import unittest
import numpy as np

# Ensure edge package is in python search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sentinel_edge.calibration.homography import (
    CameraCalibration,
    HomographyCalibrator,
    CalibrationStorage,
    validate_calibration_geometry,
)
from sentinel_edge.inference.detector import VehicleRiskAnalyzer, TrackedDetection


class TestPhase3SpeedCalibration(unittest.TestCase):
    """Authoritative Phase 3 Camera Speed Calibration Test Suite."""

    def setUp(self):
        # Standard realistic trapezoidal road perspective for 1080p camera
        # Simulating cam01 (01 Chiman bhai Bridge road segment)
        # 4 corners in image: [top-left, top-right, bottom-right, bottom-left]
        self.image_polygon = [
            [600.0, 350.0],   # P1: Far Left
            [950.0, 350.0],   # P2: Far Right
            [1300.0, 850.0],  # P3: Near Right
            [300.0, 850.0],   # P4: Near Left
        ]
        self.real_width = 7.0    # 2 lanes = 7.0 meters
        self.real_length = 30.0  # 30.0 meters road segment

        self.calib_cam01 = CameraCalibration(
            id="CALIB_CAM01_TEST",
            camera_id="cam01",
            image_width=1920,
            image_height=1080,
            ground_plane_points=self.image_polygon,
            real_width_meters=self.real_width,
            real_length_meters=self.real_length,
        )

    # -------------------------------------------------------------------------
    # TEST 1: Homography Coordinate Mapping & Invertibility
    # -------------------------------------------------------------------------
    def test_01_homography_coordinate_mapping(self):
        """Homography maps pixels to ground coordinates (meters) and inverts with < 1e-4m error."""
        calibrator = HomographyCalibrator(self.calib_cam01)
        self.assertTrue(calibrator.is_calibrated)
        self.assertIsNotNone(calibrator.H)
        self.assertIsNotNone(calibrator.inv_homography_matrix)

        # 1. Forward mapping of calibration vertices to canonical rectangle
        # P1 (top-left) -> (0, 0)
        gx1, gy1 = calibrator.image_to_ground(self.image_polygon[0][0], self.image_polygon[0][1])
        self.assertAlmostEqual(gx1, 0.0, places=3)
        self.assertAlmostEqual(gy1, 0.0, places=3)

        # P2 (top-right) -> (7.0, 0)
        gx2, gy2 = calibrator.image_to_ground(self.image_polygon[1][0], self.image_polygon[1][1])
        self.assertAlmostEqual(gx2, self.real_width, places=3)
        self.assertAlmostEqual(gy2, 0.0, places=3)

        # P3 (bottom-right) -> (7.0, 30.0)
        gx3, gy3 = calibrator.image_to_ground(self.image_polygon[2][0], self.image_polygon[2][1])
        self.assertAlmostEqual(gx3, self.real_width, places=3)
        self.assertAlmostEqual(gy3, self.real_length, places=3)

        # P4 (bottom-left) -> (0, 30.0)
        gx4, gy4 = calibrator.image_to_ground(self.image_polygon[3][0], self.image_polygon[3][1])
        self.assertAlmostEqual(gx4, 0.0, places=3)
        self.assertAlmostEqual(gy4, self.real_length, places=3)

        # 2. Invertibility check: World (X, Y) -> Image (u, v) -> World (X', Y')
        test_world_points = [
            (1.5, 5.0),
            (3.5, 15.0),
            (5.0, 25.0),
        ]
        H_inv = calibrator.inv_homography_matrix
        for X_w, Y_w in test_world_points:
            w_vec = np.array([X_w, Y_w, 1.0], dtype=np.float64)
            img_h = H_inv @ w_vec
            u = float(img_h[0] / img_h[2])
            v = float(img_h[1] / img_h[2])

            # Forward project back to ground
            X_rec, Y_rec = calibrator.image_to_ground(u, v)
            err = math.hypot(X_rec - X_w, Y_rec - Y_w)
            self.assertLess(err, 1e-4, f"Inversion roundtrip error {err:.6f}m exceeds tolerance 1e-4m")

    # -------------------------------------------------------------------------
    # TEST 2: Ground-Contact Point Projection
    # -------------------------------------------------------------------------
    def test_02_ground_contact_point_projection(self):
        """Ground contact point must strictly be bottom-center anchor ((x1+x2)/2, y2)."""
        # Bounding box of a vehicle: [left=500, top=600, right=700, bottom=800]
        bbox = [500.0, 600.0, 700.0, 800.0]
        expected_gc_x = 600.0  # (500 + 700) / 2
        expected_gc_y = 800.0  # bottom edge y2

        analyzer = VehicleRiskAnalyzer(calibration=self.calib_cam01)
        det = TrackedDetection({
            "track_id": 101,
            "bbox": bbox,
            "class_name": "car",
            "confidence": 0.92,
        })
        analyzer.analyze_frame_kinematics([det], current_time=1.0)

        # Check recorded ground contact point in analyzer trajectories
        traj = analyzer.trajectories[101]
        self.assertEqual(len(traj), 1)
        gc = traj[0]["ground_contact"]
        self.assertEqual(gc, (expected_gc_x, expected_gc_y))
        
        # Confirm it is NOT the bounding box center (600, 700)
        self.assertNotEqual(gc, (600.0, 700.0))
        # Confirm it is NOT the top-left (500, 600)
        self.assertNotEqual(gc, (500.0, 600.0))

    # -------------------------------------------------------------------------
    # TEST 3: Known-Distance Physical Transformation
    # -------------------------------------------------------------------------
    def test_03_known_distance_transformation(self):
        """Pixel distances along width and length transform exactly to physical meters."""
        calibrator = HomographyCalibrator(self.calib_cam01)

        # 1. Width across top (far road edge)
        gx1, gy1 = calibrator.image_to_ground(self.image_polygon[0][0], self.image_polygon[0][1])
        gx2, gy2 = calibrator.image_to_ground(self.image_polygon[1][0], self.image_polygon[1][1])
        d_width_far = math.hypot(gx2 - gx1, gy2 - gy1)
        self.assertAlmostEqual(d_width_far, self.real_width, delta=0.01)

        # 2. Width across bottom (near road edge)
        gx4, gy4 = calibrator.image_to_ground(self.image_polygon[3][0], self.image_polygon[3][1])
        gx3, gy3 = calibrator.image_to_ground(self.image_polygon[2][0], self.image_polygon[2][1])
        d_width_near = math.hypot(gx3 - gx4, gy3 - gy4)
        self.assertAlmostEqual(d_width_near, self.real_width, delta=0.01)

        # 3. Length along left lane curb
        d_len_left = math.hypot(gx4 - gx1, gy4 - gy1)
        self.assertAlmostEqual(d_len_left, self.real_length, delta=0.01)

        # 4. Diagonal length across calibration zone
        d_diag = math.hypot(gx3 - gx1, gy3 - gy1)
        expected_diag = math.hypot(self.real_width, self.real_length)
        self.assertAlmostEqual(d_diag, expected_diag, delta=0.01)

    # -------------------------------------------------------------------------
    # TEST 4: PTS-Based dt Calculation Across Frame Drops
    # -------------------------------------------------------------------------
    def test_04_pts_based_dt_calculation(self):
        """Speed calculation strictly uses monotonic PTS delta t, resilient to frame drops."""
        calibrator = HomographyCalibrator(self.calib_cam01)
        analyzer = VehicleRiskAnalyzer(calibration=self.calib_cam01)

        # Vehicle traveling down the center of the lane at constant physical speed
        # Real speed: 18.0 m/s = 64.8 km/h
        # Suppose PTS sequence has uneven intervals due to dropped frames:
        # t0 = 10.000s -> Y = 5.0m
        # t1 = 10.040s (dt = 0.040s, 1 frame at 25fps) -> Y = 5.0 + 18*0.04 = 5.72m
        # t2 = 10.120s (dt = 0.080s, 1 dropped frame)  -> Y = 5.72 + 18*0.08 = 7.16m
        H_inv = calibrator.inv_homography_matrix

        def world_to_bbox(X_w, Y_w):
            w_vec = np.array([X_w, Y_w, 1.0], dtype=np.float64)
            img_h = H_inv @ w_vec
            u = float(img_h[0] / img_h[2])
            v = float(img_h[1] / img_h[2])
            # Bounding box with bottom center at (u, v)
            return [u - 30.0, v - 80.0, u + 30.0, v]

        bbox0 = world_to_bbox(3.5, 5.0)
        bbox1 = world_to_bbox(3.5, 5.72)
        bbox2 = world_to_bbox(3.5, 7.16)

        # Frame 0 (t = 10.000)
        det0 = TrackedDetection({"track_id": 42, "bbox": bbox0, "class_name": "car", "confidence": 0.9})
        analyzer.analyze_frame_kinematics([det0], current_time=10.000)
        self.assertEqual(det0.speed_status, "INSUFFICIENT_TRACK_HISTORY")

        # Frame 1 (t = 10.040, dt = 0.040s)
        det1 = TrackedDetection({"track_id": 42, "bbox": bbox1, "class_name": "car", "confidence": 0.9})
        analyzer.analyze_frame_kinematics([det1], current_time=10.040)
        self.assertEqual(det1.speed_status, "VALID")
        self.assertIsNotNone(det1.speed_kmh)
        self.assertAlmostEqual(det1.speed_kmh, 64.8, delta=1.0)

        # Frame 2 (t = 10.120, dt = 0.080s with 1 dropped frame)
        det2 = TrackedDetection({"track_id": 42, "bbox": bbox2, "class_name": "car", "confidence": 0.9})
        analyzer.analyze_frame_kinematics([det2], current_time=10.120)
        self.assertEqual(det2.speed_status, "VALID")
        self.assertIsNotNone(det2.speed_kmh)
        # Must still compute 64.8 km/h regardless of dt=0.080s vs 0.040s
        self.assertAlmostEqual(det2.speed_kmh, 64.8, delta=1.0)

    # -------------------------------------------------------------------------
    # TEST 5: Physical Speed Formula (m/s to km/h) & Precision
    # -------------------------------------------------------------------------
    def test_05_speed_calculation_formula(self):
        """Verify speed = (displacement_meters / dt_seconds) * 3.6 with numerical precision."""
        calibrator = HomographyCalibrator(self.calib_cam01)

        # Point A: (3.5, 10.0) -> Point B: (3.5, 23.888889)
        # Displacement = 13.888889 meters
        # dt = 1.0 second
        # v = 13.888889 m/s = 50.0 km/h exactly
        H_inv = calibrator.inv_homography_matrix
        def to_img(X, Y):
            res = H_inv @ np.array([X, Y, 1.0], dtype=np.float64)
            return (float(res[0] / res[2]), float(res[1] / res[2]))

        pt_a = to_img(3.5, 10.0)
        pt_b = to_img(3.5, 23.888889)

        speed, status, reason = calibrator.compute_ground_speed(pt_a, pt_b, dt_seconds=1.0)
        self.assertEqual(status, "VALID")
        self.assertIsNone(reason)
        self.assertEqual(speed, 50.0)

        # dt = 0.5s -> 100.0 km/h
        speed_half, status_half, _ = calibrator.compute_ground_speed(pt_a, pt_b, dt_seconds=0.5)
        self.assertEqual(status_half, "VALID")
        self.assertEqual(speed_half, 100.0)

    # -------------------------------------------------------------------------
    # TEST 6: Jitter Threshold Filtering (< 0.05m -> 0.0 km/h)
    # -------------------------------------------------------------------------
    def test_06_jitter_threshold_filtering(self):
        """Displacements under 0.05 meters (bounding box jitter) yield exactly 0.0 km/h."""
        calibrator = HomographyCalibrator(self.calib_cam01)
        H_inv = calibrator.inv_homography_matrix

        def to_img(X, Y):
            res = H_inv @ np.array([X, Y, 1.0], dtype=np.float64)
            return (float(res[0] / res[2]), float(res[1] / res[2]))

        pt_base = to_img(3.5, 15.0)
        # Jitter shift: 0.03 meters (< 0.05m threshold)
        pt_jitter = to_img(3.5, 15.03)

        speed_jitter, status_jitter, _ = calibrator.compute_ground_speed(pt_base, pt_jitter, dt_seconds=0.04)
        self.assertEqual(status_jitter, "VALID")
        self.assertEqual(speed_jitter, 0.0, "Jitter under 0.05m must report 0.0 km/h")

        # Real motion: 0.06 meters (> 0.05m threshold)
        pt_motion = to_img(3.5, 15.06)
        speed_real, status_real, _ = calibrator.compute_ground_speed(pt_base, pt_motion, dt_seconds=0.04)
        self.assertEqual(status_real, "VALID")
        # 0.06m / 0.04s = 1.5 m/s = 5.4 km/h
        self.assertAlmostEqual(speed_real, 5.4, delta=0.2)

    # -------------------------------------------------------------------------
    # TEST 7: Uncalibrated State Behavior (CALIBRATION_REQUIRED)
    # -------------------------------------------------------------------------
    def test_07_calibration_required_state_behavior(self):
        """Uncalibrated cameras strictly output speed_kmh=None and CALIBRATION_REQUIRED."""
        analyzer = VehicleRiskAnalyzer(calibration=None)
        self.assertIsNone(analyzer.calibrator)

        # Multi-frame tracking
        det1 = TrackedDetection({"track_id": 5, "bbox": [100, 100, 200, 300], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det1], current_time=0.0)
        self.assertIsNone(det1.speed_kmh)
        self.assertEqual(det1.speed_status, "CALIBRATION_REQUIRED")

        det2 = TrackedDetection({"track_id": 5, "bbox": [120, 120, 220, 320], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det2], current_time=0.1)
        self.assertIsNone(det2.speed_kmh, "Uncalibrated camera must never output numeric speed_kmh")
        self.assertEqual(det2.speed_status, "CALIBRATION_REQUIRED")
        self.assertEqual(det2.speed_display_reason, "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED")
        # Pixel velocity is preserved for internal kinematics/collision shocks
        self.assertGreater(det2.velocity_px_s, 0.0)

    # -------------------------------------------------------------------------
    # TEST 8: Insufficient Track History (INSUFFICIENT_TRACK_HISTORY)
    # -------------------------------------------------------------------------
    def test_08_insufficient_track_history(self):
        """Single-frame detection on calibrated camera produces INSUFFICIENT_TRACK_HISTORY."""
        analyzer = VehicleRiskAnalyzer(calibration=self.calib_cam01)

        det_new = TrackedDetection({
            "track_id": 99,
            "bbox": [500, 600, 600, 750],
            "class_name": "truck",
            "confidence": 0.85,
        })
        analyzer.analyze_frame_kinematics([det_new], current_time=100.0)

        self.assertIsNone(det_new.speed_kmh)
        self.assertEqual(det_new.speed_status, "INSUFFICIENT_TRACK_HISTORY")
        self.assertIn("history initializing", det_new.speed_display_reason)

    # -------------------------------------------------------------------------
    # TEST 9: PTS Discontinuity Handling (INVALID_TIMING)
    # -------------------------------------------------------------------------
    def test_09_pts_discontinuity_handling(self):
        """PTS backwards jump (dt <= 0) or gap (> 5s) triggers INVALID_TIMING and flushes state."""
        analyzer = VehicleRiskAnalyzer(calibration=self.calib_cam01)

        # Frame 1: t = 10.0
        det1 = TrackedDetection({"track_id": 7, "bbox": [600, 500, 700, 650], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det1], current_time=10.0)

        # Frame 2: PTS jump backwards (t = 9.5, dt = -0.5s)
        det2 = TrackedDetection({"track_id": 7, "bbox": [610, 510, 710, 660], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det2], current_time=9.5)
        self.assertIsNone(det2.speed_kmh)
        self.assertEqual(det2.speed_status, "INVALID_TIMING")

        # Frame 3: PTS huge gap (t = 25.0, dt = 15.5s > 5.0s)
        det3 = TrackedDetection({"track_id": 7, "bbox": [620, 520, 720, 670], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det3], current_time=25.0)
        self.assertIsNone(det3.speed_kmh)
        self.assertEqual(det3.speed_status, "INVALID_TIMING")

    # -------------------------------------------------------------------------
    # TEST 10: Stream Generation Reset Handling
    # -------------------------------------------------------------------------
    def test_10_stream_generation_reset(self):
        """Stream generation reconnect or reset flushes velocity state to prevent speed spikes."""
        analyzer = VehicleRiskAnalyzer(calibration=self.calib_cam01)

        # Vehicle moving before disconnect
        det1 = TrackedDetection({"track_id": 12, "bbox": [500, 500, 600, 650], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det1], current_time=5.0)

        det2 = TrackedDetection({"track_id": 12, "bbox": [520, 520, 620, 670], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det2], current_time=5.1)
        self.assertEqual(det2.speed_status, "VALID")

        # Simulating edge stream reconnect: analyzer.reset() is called
        analyzer.reset()
        self.assertEqual(len(analyzer.trajectories), 0)

        # Vehicle reappears after reconnect
        det3 = TrackedDetection({"track_id": 12, "bbox": [700, 700, 800, 850], "class_name": "car"})
        analyzer.analyze_frame_kinematics([det3], current_time=15.0)
        # Must be treated as new track history, NOT compared against frame before reset
        self.assertIsNone(det3.speed_kmh)
        self.assertEqual(det3.speed_status, "INSUFFICIENT_TRACK_HISTORY")

    # -------------------------------------------------------------------------
    # TEST 11: Invalid Calibration Geometry Rejection
    # -------------------------------------------------------------------------
    def test_11_invalid_calibration_rejection(self):
        """Rejects degenerate quads: collinear points, crossed polygon, non-positive dimensions."""
        # Case A: Collinear points (flat line)
        collinear_pts = [[100, 100], [200, 100], [300, 100], [400, 100]]
        valid_a, err_a = validate_calibration_geometry(collinear_pts, 3.5, 20.0)
        self.assertFalse(valid_a)
        self.assertIn("contour area", err_a.lower())

        # Case B: Concave polygon (non-convex quadrilateral rejected)
        concave_pts = [[100, 100], [500, 100], [300, 300], [500, 500]]
        valid_b, err_b = validate_calibration_geometry(concave_pts, 3.5, 20.0)
        self.assertFalse(valid_b)
        self.assertIn("convex", err_b.lower())

        # Case C: Non-positive real width / length
        normal_pts = [[100, 100], [300, 100], [350, 400], [50, 400]]
        valid_c1, err_c1 = validate_calibration_geometry(normal_pts, -5.0, 20.0)
        self.assertFalse(valid_c1)
        self.assertIn("strictly positive", err_c1.lower())

        valid_c2, err_c2 = validate_calibration_geometry(normal_pts, 3.5, 0.0)
        self.assertFalse(valid_c2)
        self.assertIn("strictly positive", err_c2.lower())

        # Case D: CameraCalibration.validate() directly
        bad_calib = CameraCalibration(
            id="BAD_CALIB",
            camera_id="cam_bad",
            ground_plane_points=collinear_pts,
            real_width_meters=3.5,
            real_length_meters=20.0,
        )
        self.assertFalse(bad_calib.validate())

    # -------------------------------------------------------------------------
    # TEST 12: Per-Camera Calibration Isolation
    # -------------------------------------------------------------------------
    def test_12_per_camera_calibration_isolation(self):
        """Calibrating cam01 does NOT affect cam02; isolation is strictly preserved."""
        # cam01 has active calibration
        analyzer_cam01 = VehicleRiskAnalyzer(calibration=self.calib_cam01)
        # cam02 has NO calibration
        analyzer_cam02 = VehicleRiskAnalyzer(calibration=None)

        # Same synthetic vehicle displacement applied to both
        det_a1 = TrackedDetection({"track_id": 1, "bbox": [500, 600, 600, 750], "class_name": "car"})
        det_a2 = TrackedDetection({"track_id": 1, "bbox": [505, 620, 605, 770], "class_name": "car"})
        analyzer_cam01.analyze_frame_kinematics([det_a1], current_time=0.0)
        analyzer_cam01.analyze_frame_kinematics([det_a2], current_time=0.1)

        det_b1 = TrackedDetection({"track_id": 1, "bbox": [500, 600, 600, 750], "class_name": "car"})
        det_b2 = TrackedDetection({"track_id": 1, "bbox": [505, 620, 605, 770], "class_name": "car"})
        analyzer_cam02.analyze_frame_kinematics([det_b1], current_time=0.0)
        analyzer_cam02.analyze_frame_kinematics([det_b2], current_time=0.1)

        # cam01 yields valid physical speed
        self.assertEqual(det_a2.speed_status, "VALID")
        self.assertIsNotNone(det_a2.speed_kmh)
        self.assertGreater(det_a2.speed_kmh, 0.0)

        # cam02 remains uncalibrated with null speed
        self.assertEqual(det_b2.speed_status, "CALIBRATION_REQUIRED")
        self.assertIsNone(det_b2.speed_kmh)

        # Test persistence isolation via CalibrationStorage
        temp_dir = tempfile.mkdtemp()
        try:
            saved_file = CalibrationStorage.save_to_file(self.calib_cam01, config_dir=temp_dir)
            self.assertTrue(os.path.exists(saved_file))
            self.assertTrue(saved_file.name.endswith("cam01.json"))

            # Ensure cam02 config does not exist
            loaded_cam02 = CalibrationStorage.load_from_file("cam02", config_dir=temp_dir)
            self.assertIsNone(loaded_cam02)

            # Ensure cam01 loads accurately
            loaded_cam01 = CalibrationStorage.load_from_file("cam01", config_dir=temp_dir)
            self.assertIsNotNone(loaded_cam01)
            self.assertEqual(loaded_cam01.camera_id, "cam01")
        finally:
            shutil.rmtree(temp_dir)

    # -------------------------------------------------------------------------
    # TEST 13: Fresh Production Camera Has No Calibration & Speed Suppressed
    # -------------------------------------------------------------------------
    def test_13_fresh_production_camera_has_no_calibration(self):
        """Production Safety: Fresh camera has 0 calibration, no assumed defaults, speed suppressed."""
        prod_config_dir = CalibrationStorage.get_default_config_dir()
        
        # 1. Verify production config directory has no synthetic or test configs active for cam01
        cam01_prod_file = prod_config_dir / "cam01.json"
        self.assertFalse(
            cam01_prod_file.exists(),
            "Production safety violation: cam01.json must not exist in production config dir without explicit operator field calibration"
        )
        
        # 2. Loading calibration for fresh production camera yields None
        loaded = CalibrationStorage.load_from_file("cam01")
        self.assertIsNone(loaded, "Uncalibrated production camera must return None from CalibrationStorage")

        # 3. Production risk analyzer default state suppresses physical speed
        prod_analyzer = VehicleRiskAnalyzer(calibration=loaded)
        self.assertFalse(prod_analyzer.calibrator is not None and prod_analyzer.calibrator.is_calibrated)

        # 4. Multi-frame track with substantial pixel displacement
        det1 = TrackedDetection({"track_id": 999, "bbox": [400, 500, 500, 650], "class_name": "car"})
        det2 = TrackedDetection({"track_id": 999, "bbox": [450, 580, 550, 730], "class_name": "car"})
        prod_analyzer.analyze_frame_kinematics([det1], current_time=0.0)
        prod_analyzer.analyze_frame_kinematics([det2], current_time=0.1)

        self.assertIsNone(det2.speed_kmh, "Production speed must be None when uncalibrated")
        self.assertEqual(det2.speed_status, "CALIBRATION_REQUIRED")
        self.assertEqual(det2.speed_display_reason, "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED")

        # 5. Production safety: Default dimensions are rejected if missing or non-positive
        valid_none, err_none = validate_calibration_geometry(self.image_polygon, real_width=None, real_length=None)
        self.assertFalse(valid_none)
        self.assertTrue("provided" in err_none.lower() or "positive" in err_none.lower())

        valid_zero, err_zero = validate_calibration_geometry(self.image_polygon, real_width=0.0, real_length=30.0)
        self.assertFalse(valid_zero)
        self.assertIn("positive", err_zero.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
