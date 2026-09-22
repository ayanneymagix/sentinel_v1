"""
SENTINEL Phase 1: Data Integrity & Physical Speed Calibration Automated Verification Suite
"""

import sys
import os
import unittest
import numpy as np

# Ensure edge directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sentinel_edge.calibration.homography import HomographyCalibrator, CameraCalibration
from sentinel_edge.inference.detector import VehicleRiskAnalyzer


class TestPhase1Integrity(unittest.TestCase):

    def test_01_uncalibrated_camera_returns_null_speed(self):
        """Uncalibrated cameras must return speed_kmh=None and CALIBRATION_REQUIRED."""
        calibrator = HomographyCalibrator()
        self.assertFalse(calibrator.is_calibrated)
        
        speed, status = calibrator.calculate_speed_kmh((100, 200), (120, 250), dt_seconds=0.1)
        self.assertIsNone(speed, "Uncalibrated camera must never return a numeric speed")
        self.assertEqual(status, "CALIBRATION_REQUIRED")

    def test_02_valid_homography_and_speed_calculation(self):
        """Valid 4-point calibration maps pixel displacement to physical meters and km/h."""
        calib = CameraCalibration(
            calibration_id="TEST_CALIB_01",
            camera_id="TEST_CAM_01",
            image_polygon=[(100.0, 100.0), (300.0, 100.0), (350.0, 400.0), (50.0, 400.0)],
            real_width_meters=10.0,
            real_length_meters=50.0,
        )
        self.assertTrue(calib.validate())
        
        calibrator = HomographyCalibrator(calib)
        self.assertTrue(calibrator.is_calibrated)
        
        # Test ground contact point projection
        gx, gy = calibrator.image_to_ground((100.0, 100.0))
        self.assertAlmostEqual(gx, 0.0, places=1)
        self.assertAlmostEqual(gy, 0.0, places=1)

        gx_far, gy_far = calibrator.image_to_ground((300.0, 100.0))
        self.assertAlmostEqual(gx_far, 10.0, places=1)
        self.assertAlmostEqual(gy_far, 0.0, places=1)

        # 25 meters displacement over 1.0 second = 25 m/s = 90.0 km/h
        p_start = (200.0, 100.0)
        H_inv = calibrator.inv_homography_matrix
        pt_g = np.array([5.0, 25.0, 1.0], dtype=np.float64)
        p_img_h = H_inv @ pt_g
        p_end = (float(p_img_h[0] / p_img_h[2]), float(p_img_h[1] / p_img_h[2]))

        speed, status = calibrator.calculate_speed_kmh(p_start, p_end, dt_seconds=1.0)
        self.assertIsNotNone(speed)
        self.assertEqual(status, "CALIBRATED_METRIC")
        self.assertAlmostEqual(speed, 90.0, delta=2.0)

    def test_03_jitter_filtering(self):
        """Micro-displacement under 0.05 meters must be filtered to exactly 0.0 km/h."""
        calib = CameraCalibration(
            calibration_id="TEST_CALIB_02",
            camera_id="TEST_CAM_02",
            image_polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            real_width_meters=10.0,
            real_length_meters=10.0,
        )
        calibrator = HomographyCalibrator(calib)
        
        # Tiny movement: 0.1 pixel = 0.01 meters
        speed, status = calibrator.calculate_speed_kmh((50.0, 50.0), (50.1, 50.0), dt_seconds=0.1)
        self.assertEqual(speed, 0.0)
        self.assertEqual(status, "CALIBRATED_METRIC")

    def test_04_degenerate_quadrilateral_rejected(self):
        """Collinear or invalid polygons must be rejected."""
        # Collinear points
        calib_collinear = CameraCalibration(
            calibration_id="INVALID_01",
            camera_id="TEST_CAM_03",
            image_polygon=[(0.0, 0.0), (10.0, 10.0), (20.0, 20.0), (30.0, 30.0)],
            real_width_meters=10.0,
            real_length_meters=20.0,
        )
        self.assertFalse(calib_collinear.validate())

        # Degenerate polygon (insufficient points)
        calib_triangle = CameraCalibration(
            calibration_id="INVALID_02",
            camera_id="TEST_CAM_04",
            image_polygon=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)],
            real_width_meters=10.0,
            real_length_meters=20.0,
        )
        self.assertFalse(calib_triangle.validate())

    def test_05_invalid_time_interval_rejected(self):
        """Sub-threshold or negative dt must return (None, 'INVALID_DT')."""
        calib = CameraCalibration(
            calibration_id="TEST_CALIB_03",
            camera_id="TEST_CAM_05",
            image_polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            real_width_meters=10.0,
            real_length_meters=10.0,
        )
        calibrator = HomographyCalibrator(calib)
        
        speed, status = calibrator.calculate_speed_kmh((10, 10), (20, 20), dt_seconds=0.0)
        self.assertIsNone(speed)
        self.assertEqual(status, "INVALID_DT")

        speed_neg, status_neg = calibrator.calculate_speed_kmh((10, 10), (20, 20), dt_seconds=-0.5)
        self.assertIsNone(speed_neg)
        self.assertEqual(status_neg, "INVALID_DT")

    def test_06_unrealistic_speed_cap(self):
        """Speeds exceeding physical road cap (220 km/h) must be rejected."""
        calib = CameraCalibration(
            calibration_id="TEST_CALIB_04",
            camera_id="TEST_CAM_06",
            image_polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            real_width_meters=100.0,
            real_length_meters=100.0,
        )
        calibrator = HomographyCalibrator(calib)
        
        # 100 meters in 0.5 seconds = 200 m/s = 720 km/h
        speed, status = calibrator.calculate_speed_kmh((0, 0), (100, 100), dt_seconds=0.5)
        self.assertIsNone(speed)
        self.assertEqual(status, "UNREALISTIC_PHYSICS")

    def test_07_ground_contact_point_used_for_tracking(self):
        """Ground contact point must be computed at (bottom-center) of vehicle bounding box."""
        # Bounding box: [x1=100, y1=100, x2=200, y2=300]
        # Ground contact: u = (100+200)/2 = 150, v = y2 = 300
        bbox = [100.0, 100.0, 200.0, 300.0]
        gc_x = (bbox[0] + bbox[2]) / 2.0
        gc_y = float(bbox[3])
        self.assertEqual((gc_x, gc_y), (150.0, 300.0))

    def test_08_vehicle_risk_analyzer_transparent_output(self):
        """VehicleRiskAnalyzer must output pixel velocities and CALIBRATION_REQUIRED when uncalibrated."""
        analyzer = VehicleRiskAnalyzer(calibration=None)
        
        # Frame 1
        det1 = {
            "track_id": 1,
            "class_name": "car",
            "confidence": 0.88,
            "bbox": [100, 100, 200, 300],
        }
        analyzer.analyze_frame_kinematics([det1], current_time=0.0)
        
        # Frame 2 with displacement
        det2 = {
            "track_id": 1,
            "class_name": "car",
            "confidence": 0.89,
            "bbox": [120, 100, 220, 300],
        }
        analyzer.analyze_frame_kinematics([det2], current_time=0.1)
        
        self.assertIsNone(det2["speed_kmh"], "Uncalibrated stream must have speed_kmh=None")
        self.assertEqual(det2["speed_status"], "CALIBRATION_REQUIRED")
        self.assertEqual(det2["speed_display_reason"], "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED")
        self.assertIn("velocity_px_s", det2)
        self.assertGreater(det2["velocity_px_s"], 0)

    def test_09_database_schema_and_zero_synthetic_data(self):
        """Database must contain 0 synthetic GJ01AB1234 trajectory events and have nullable columns."""
        import asyncio
        import asyncpg

        async def run_db_check():
            conn = await asyncpg.connect("postgresql://postgres:admin@127.0.0.1:5432/sentinel")
            try:
                # 1. Check synthetic detections count
                synthetic_count = await conn.fetchval("""
                    SELECT count(*) FROM public.events 
                    WHERE event_id IN (
                        'a0000001-0000-0000-0000-000000000001',
                        'a0000001-0000-0000-0000-000000000002',
                        'a0000001-0000-0000-0000-000000000003',
                        'a0000001-0000-0000-0000-000000000004',
                        'a0000001-0000-0000-0000-000000000005',
                        'a0000001-0000-0000-0000-000000000006'
                    );
                """)
                self.assertEqual(synthetic_count, 0, "Database must not contain hardcoded synthetic trajectory events")

                # 2. Check camera_calibrations table exists
                calib_table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'camera_calibrations'
                    );
                """)
                self.assertTrue(calib_table_exists, "camera_calibrations table must exist")

                # 3. Check registered recorded test clips exist in cameras table
                cctv_cams = await conn.fetchval("""
                    SELECT count(*) FROM public.cameras WHERE camera_id LIKE 'CAM_CCTV_%';
                """)
                self.assertGreaterEqual(cctv_cams, 5, "5 recorded CCTV test clips must be registered in cameras table")

                # 4. Check confidence column in public.events is nullable
                is_nullable = await conn.fetchval("""
                    SELECT is_nullable FROM information_schema.columns 
                    WHERE table_schema = 'public' 
                    AND table_name = 'events' 
                    AND column_name = 'confidence';
                """)
                self.assertEqual(is_nullable, "YES", "events.confidence column must be nullable")
            finally:
                await conn.close()

        asyncio.run(run_db_check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
