import os
import sys
import unittest
import numpy as np
import cv2
import time

# Ensure edge directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sentinel_edge.inference.vehicle_classifier import VehicleAttributeClassifier
from sentinel_edge.tracking.multi_camera import MultiCameraReIDTracker


class TestVehicleClassifierAndReID(unittest.TestCase):

    def setUp(self):
        self.classifier = VehicleAttributeClassifier()
        self.multicam_tracker = MultiCameraReIDTracker()

    def test_color_and_subtype_classification(self):
        # Create a synthetic white vehicle crop (60x100) -> SUV aspect ratio
        white_crop = np.full((100, 60, 3), 245, dtype=np.uint8)
        color_name, rgb = self.classifier.extract_dominant_color(white_crop)
        self.assertIn(color_name, ["White", "Pearl Silver", "Granite Grey"])
        self.assertEqual(len(rgb), 3)

        attrs = self.classifier.classify(
            crop=white_crop,
            base_class="car",
            bbox=[0, 0, 60, 100],
            track_id=42,
        )
        self.assertIn(attrs.body_subtype, ["Sedan", "SUV", "Hatchback"])
        self.assertIsNotNone(attrs.make)
        self.assertIn(attrs.color, ["White", "Pearl Silver", "Granite Grey"])
        self.assertEqual(len(attrs.appearance_embedding), 32)

        # Check make determinism
        attrs2 = self.classifier.classify(
            crop=white_crop,
            base_class="car",
            bbox=[0, 0, 60, 100],
            track_id=42,
        )
        self.assertEqual(attrs.make, attrs2.make, "Make estimation must be deterministic per track")

    def test_appearance_embedding(self):
        sample_crop = np.random.randint(50, 200, (80, 80, 3), dtype=np.uint8)
        emb = self.classifier.compute_appearance_embedding(sample_crop, aspect_ratio=1.0)
        self.assertEqual(len(emb), 32, "Embedding vector must be 32-dimensional")
        # Embedding should be normalized (L2 norm ~ 1.0)
        norm = np.linalg.norm(emb)
        self.assertAlmostEqual(norm, 1.0, places=2)

    def test_multicamera_exact_plate_matching(self):
        t0 = time.time()
        # Cam 01 registers plate GJ01AB1234
        v1 = self.multicam_tracker.update_vehicle_observation(
            camera_id="cam01",
            camera_name="01 Chiman bhai Bridge",
            track_id=10,
            plate="GJ01AB1234",
            full_name="White Hyundai Creta",
            make="Hyundai",
            body_subtype="SUV",
            color="White",
            appearance_embedding=[0.1] * 32,
            timestamp=t0,
            direction="Northbound",
        )
        self.assertEqual(v1.global_id, "SENTINEL-GJ01AB1234")
        self.assertEqual(len(v1.journey), 1)

        # Cam 02 registers same plate 15 seconds later
        v2 = self.multicam_tracker.update_vehicle_observation(
            camera_id="cam02",
            camera_name="02 Subhash Bridge",
            track_id=88,
            plate="GJ01AB1234",
            full_name="White Hyundai Creta",
            make="Hyundai",
            body_subtype="SUV",
            color="White",
            appearance_embedding=[0.1] * 32,
            timestamp=t0 + 15.0,
            direction="Eastbound",
        )
        self.assertEqual(v2.global_id, "SENTINEL-GJ01AB1234")
        self.assertEqual(len(v2.journey), 2, "Journey should have 2 camera hops")
        self.assertEqual(v2.journey[0].camera_id, "cam01")
        self.assertEqual(v2.journey[1].camera_id, "cam02")

    def test_multicamera_visual_reid_matching(self):
        t0 = time.time()
        # Create identical embedding representing same unplated vehicle
        emb = np.random.randn(32).astype(np.float32)
        emb = emb / np.linalg.norm(emb)
        emb_list = emb.tolist()

        # Cam 01 observes vehicle without plate
        v1 = self.multicam_tracker.update_vehicle_observation(
            camera_id="cam01",
            camera_name="01 Chiman bhai Bridge",
            track_id=5,
            plate=None,
            full_name="White Hyundai SUV",
            make="Hyundai",
            body_subtype="SUV",
            color="White",
            appearance_embedding=emb_list,
            timestamp=t0,
            direction="Northbound",
        )
        self.assertTrue(v1.global_id.startswith("SENTINEL-GJ-V"))
        self.assertEqual(len(v1.journey), 1)

        # Cam 02 observes same vehicle 30 seconds later (no plate, identical visual appearance)
        v2 = self.multicam_tracker.update_vehicle_observation(
            camera_id="cam02",
            camera_name="02 Subhash Bridge",
            track_id=99,
            plate=None,
            full_name="White Hyundai SUV",
            make="Hyundai",
            body_subtype="SUV",
            color="White",
            appearance_embedding=emb_list,
            timestamp=t0 + 30.0,
            direction="Eastbound",
        )
        self.assertEqual(v1.global_id, v2.global_id, "Must re-identify vehicle across cameras via visual embedding")
        self.assertEqual(len(v2.journey), 2, "Journey should record the cross-camera transit hop")
        self.assertEqual(v2.journey[0].camera_id, "cam01")
        self.assertEqual(v2.journey[1].camera_id, "cam02")


if __name__ == "__main__":
    unittest.main()
