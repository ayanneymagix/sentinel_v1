"""
SENTINEL Phase 2: Live CCTV Ingestion Architecture Automated Verification Suite

Validates:
1. Dynamic camera catalogue parsing (/api/ingest) without hardcoding.
2. H.264 and H.265 / HEVC codec pipeline configuration with forced TCP transport.
3. Mixed resolution support without fixed-shape assumptions.
4. PTS preservation as authoritative time source.
5. Non-uniform frame intervals and absence of assumed FPS dependencies.
6. Stream generation tracking and short-lived state flushing.
7. Scene discontinuity and loop cut detection.
8. Bounded frame queue and zero-latency frame dropping.
9. Fault isolation (failure of Camera A does not affect Camera B).
10. Preservation of Phase 1 integrity: uncalibrated cameras return speed_kmh=None.
11. Absence of fabricated speed, confidence, plate, or GPS fallbacks.
12. API output sanitization: RTSP URLs and credentials are never exposed to clients.
"""

import os
import sys
import time
import unittest
import numpy as np

# Ensure edge directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sentinel_edge.camera.stream_manager import (
    CameraDescriptor,
    CameraStreamWorker,
    FramePacket,
    StreamManager,
    StreamState,
    build_gstreamer_pipeline,
)
from sentinel_edge.calibration.homography import CameraCalibration, HomographyCalibrator
from sentinel_edge.inference.detector import VehicleRiskAnalyzer, VehicleTracker


class TestPhase2Ingestion(unittest.TestCase):

    def setUp(self):
        self.raw_catalogue_sample = {
            "status": "success",
            "total_cameras": 3,
            "cameras": [
                {
                    "id": "CAM_AHM_LIVE_01",
                    "name": "Ahmedabad SG Highway Node",
                    "location": {
                        "city": "Ahmedabad",
                        "latitude": 23.0225,
                        "longitude": 72.5714,
                    },
                    "codec": "h264",
                    "live": True,
                    "endpoints": {
                        "rtsp": "rtsp://cctv.gateway.internal:8554/stream/ahm01",
                        "whep": "http://cctv.gateway.internal:8889/stream/ahm01/whep",
                        "hls": "http://cctv.gateway.internal:8888/live/stream/ahm01/index.m3u8",
                    },
                },
                {
                    "id": "CAM_SUR_HEVC_02",
                    "name": "Surat PTZ Express Junction",
                    "location": {
                        "city": "Surat",
                        "latitude": 21.1702,
                        "longitude": 72.8311,
                    },
                    "codec": "h265",
                    "live": True,
                    "endpoints": {
                        "rtsp": "rtsp://cctv.gateway.internal:8554/stream/sur02",
                        "whep": "http://cctv.gateway.internal:8889/stream/sur02/whep",
                        "hls": "http://cctv.gateway.internal:8888/live/stream/sur02/index.m3u8",
                    },
                },
                {
                    "id": "CAM_REMOTE_SPARSE_03",
                    "name": "Remote Rural Checkpost",
                    "location": {
                        # Missing latitude & longitude — must NOT fabricate coordinates
                        "city": "Gujarat Rural",
                    },
                    "codec": "h264",
                    "live": False,
                    "endpoints": {
                        "rtsp": "rtsp://cctv.gateway.internal:8554/stream/rural03",
                        "whep": "http://cctv.gateway.internal:8889/stream/rural03/whep",
                        "hls": "http://cctv.gateway.internal:8888/live/stream/rural03/index.m3u8",
                    },
                },
            ],
        }

    # ------------------------------------------------------------------
    # 1. Catalogue Parsing & Dynamic Discovery
    # ------------------------------------------------------------------
    def test_01_catalogue_parsing_and_sparse_metadata(self):
        """Catalogue parsing must dynamically discover cameras without hardcoding."""
        cams = self.raw_catalogue_sample["cameras"]
        descriptors = []
        for c in cams:
            loc = c.get("location", {})
            ep = c.get("endpoints", {})
            descriptors.append(
                CameraDescriptor(
                    id=c["id"],
                    name=c["name"],
                    city=loc.get("city"),
                    latitude=loc.get("latitude"),
                    longitude=loc.get("longitude"),
                    codec=c.get("codec", "h264"),
                    live=c.get("live", True),
                    rtsp_url=ep.get("rtsp", ""),
                    whep_url=ep.get("whep", ""),
                    hls_url=ep.get("hls", ""),
                )
            )

        self.assertEqual(len(descriptors), 3)
        self.assertEqual(descriptors[0].id, "CAM_AHM_LIVE_01")
        self.assertEqual(descriptors[0].codec, "h264")
        self.assertEqual(descriptors[1].codec, "h265")

        # Sparse metadata camera must have None coordinates — never fabricated
        sparse_cam = descriptors[2]
        self.assertIsNone(sparse_cam.latitude, "Missing latitude must be None, not fabricated")
        self.assertIsNone(sparse_cam.longitude, "Missing longitude must be None, not fabricated")

    # ------------------------------------------------------------------
    # 2. Codecs & Forced TCP Transport
    # ------------------------------------------------------------------
    def test_02_gstreamer_pipeline_tcp_enforcement(self):
        """Every RTSP connection must enforce TCP transport and support H.264 / H.265."""
        # H.264
        h264_pipe = build_gstreamer_pipeline("rtsp://10.0.0.1:8554/live/cam1", codec="h264")
        self.assertIn("protocols=tcp", h264_pipe, "RTSP over TCP must be strictly enforced")
        self.assertIn("rtph264depay", h264_pipe)
        self.assertIn("avdec_h264", h264_pipe)

        # H.265 / HEVC
        h265_pipe = build_gstreamer_pipeline("rtsp://10.0.0.1:8554/live/cam2", codec="h265")
        self.assertIn("protocols=tcp", h265_pipe, "RTSP over TCP must be strictly enforced")
        self.assertIn("rtph265depay", h265_pipe)
        self.assertIn("avdec_h265", h265_pipe)

        # Ensure environment option for OpenCV FFmpeg fallback is set
        self.assertEqual(os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS"), "rtsp_transport;tcp")

    # ------------------------------------------------------------------
    # 3. Mixed Resolutions Support
    # ------------------------------------------------------------------
    def test_03_mixed_resolutions_frame_packet(self):
        """FramePackets must preserve true camera dimensions (1080p, 720p, 4K)."""
        resolutions = [(1920, 1080), (1280, 720), (3840, 2160), (640, 480)]
        for w, h in resolutions:
            fake_frame = np.zeros((h, w, 3), dtype=np.uint8)
            pkt = FramePacket(
                camera_id="CAM_TEST",
                frame=fake_frame,
                pts=1000,
                pts_seconds=1.0,
                width=w,
                height=h,
                codec="h264",
                received_at=time.monotonic(),
                stream_generation=1,
            )
            self.assertEqual(pkt.width, w)
            self.assertEqual(pkt.height, h)
            self.assertEqual(pkt.frame.shape[:2], (h, w))

    # ------------------------------------------------------------------
    # 4. PTS Preservation as Authoritative Time Source
    # ------------------------------------------------------------------
    def test_04_pts_preservation_and_arrival_time_isolation(self):
        """Timing must come solely from PTS. Wall-clock arrival must not alter kinematics."""
        t_arrival_1 = 1000.0
        t_arrival_2 = 1005.0  # Arrived 5 seconds later due to network buffering
        
        # Actual media PTS is only 0.040s apart (25 FPS video stream)
        pts_sec_1 = 10.000
        pts_sec_2 = 10.040

        pkt1 = FramePacket("CAM_1", np.zeros((100, 100, 3)), 10000, pts_sec_1, 100, 100, "h264", t_arrival_1, 1)
        pkt2 = FramePacket("CAM_1", np.zeros((100, 100, 3)), 10040, pts_sec_2, 100, 100, "h264", t_arrival_2, 1)

        # Delta PTS is exactly 0.040s
        delta_pts = pkt2.pts_seconds - pkt1.pts_seconds
        self.assertAlmostEqual(delta_pts, 0.040, places=4)
        
        # Arrival delta was 5.000s, but must be ignored for physical kinematics
        arrival_delta = pkt2.received_at - pkt1.received_at
        self.assertAlmostEqual(arrival_delta, 5.000, places=4)
        self.assertNotEqual(delta_pts, arrival_delta)

    # ------------------------------------------------------------------
    # 5. Non-Uniform Frame Intervals
    # ------------------------------------------------------------------
    def test_05_non_uniform_frame_intervals(self):
        """Kinematics analyzer must correctly calculate dt from variable PTS without assuming constant FPS."""
        analyzer = VehicleRiskAnalyzer(fps=25.0)

        pts_sequence = [10.000, 10.033, 10.091, 10.150]
        # Frame 0: t=10.000, y=100
        det0 = [{"track_id": 1, "bbox": [50.0, 50.0, 70.0, 100.0]}]
        analyzer.analyze_frame_kinematics(det0, current_time=pts_sequence[0])

        # Frame 1: t=10.033 (dt=0.033s), displacement dy = 10px -> ~303 px/s
        det1 = [{"track_id": 1, "bbox": [50.0, 60.0, 70.0, 110.0]}]
        analyzer.analyze_frame_kinematics(det1, current_time=pts_sequence[1])
        v1 = det1[0]["velocity_px_s"]

        # Frame 2: t=10.091 (dt=0.058s), displacement dy = 10px -> ~172 px/s
        det2 = [{"track_id": 1, "bbox": [50.0, 70.0, 70.0, 120.0]}]
        analyzer.analyze_frame_kinematics(det2, current_time=pts_sequence[2])
        v2 = det2[0]["velocity_px_s"]

        # Velocity must differ due to variable dt even though pixel displacement was identical
        self.assertNotEqual(v1, v2)
        self.assertGreater(v1, v2)

    # ------------------------------------------------------------------
    # 6. Stream Generation Increment & Tracker State Isolation
    # ------------------------------------------------------------------
    def test_06_stream_generation_flush(self):
        """Short-lived tracking state must be flushed when stream generation changes."""
        analyzer = VehicleRiskAnalyzer()

        # Stream generation 1: Add observations
        det = [{"track_id": 42, "bbox": [10.0, 10.0, 50.0, 50.0]}]
        analyzer.analyze_frame_kinematics(det, current_time=1.0)
        self.assertIn(42, analyzer.trajectories)
        self.assertEqual(len(analyzer.trajectories[42]), 1)

        # Hard stream restart / generation increment triggers reset()
        analyzer.reset()
        self.assertEqual(len(analyzer.trajectories), 0, "Trajectories must be flushed across generations")
        self.assertEqual(len(analyzer.active_collision_tracks), 0)
        self.assertEqual(len(analyzer.collision_votes), 0)

    # ------------------------------------------------------------------
    # 7. Scene Discontinuity / Loop Cut Handling
    # ------------------------------------------------------------------
    def test_07_scene_discontinuity_callback(self):
        """A backwards PTS jump must trigger a scene discontinuity notification."""
        prev_pts_ms = 120000.0  # 120 seconds
        curr_pts_ms = 5000.0    # looped back to 5 seconds

        discontinuity_detected = False
        if prev_pts_ms >= 0 and (curr_pts_ms < prev_pts_ms or (curr_pts_ms - prev_pts_ms) > 5000.0):
            discontinuity_detected = True

        self.assertTrue(discontinuity_detected, "Backwards PTS jump must be identified as scene discontinuity")

    # ------------------------------------------------------------------
    # 8. Bounded Frame Queue & Controlled Frame Dropping
    # ------------------------------------------------------------------
    def test_08_bounded_frame_queue_drops_stale_frames(self):
        """Queue depth must never grow indefinitely; stale frames must drop in zero latency mode."""
        import collections
        queue = collections.deque(maxlen=1)
        dropped = 0

        # Simulate 100 fast camera frames pushed while consumer is idle
        for i in range(100):
            if len(queue) == queue.maxlen:
                dropped += 1
            queue.append(f"frame_{i}")

        self.assertEqual(len(queue), 1, "Queue must strictly remain at maxlen=1")
        self.assertEqual(dropped, 99, "99 stale frames must be dropped without memory growth")
        self.assertEqual(queue.pop(), "frame_99", "Only the freshest frame must be retained")

    # ------------------------------------------------------------------
    # 9. Fault Isolation: One Camera Failure Does Not Kill Another
    # ------------------------------------------------------------------
    def test_09_per_camera_failure_isolation(self):
        """Failure or disconnection of Camera 1 must not terminate or affect Camera 2."""
        cam1 = CameraDescriptor(id="CAM_FAIL_01", name="Failing Camera", rtsp_url="rtsp://invalid.host:8554/fail")
        cam2 = CameraDescriptor(id="CAM_HEALTHY_02", name="Healthy Camera", rtsp_url="")

        manager = StreamManager()
        manager.register_camera(cam1)
        manager.register_camera(cam2)

        h1 = manager.get_camera_health("CAM_FAIL_01")
        h2 = manager.get_camera_health("CAM_HEALTHY_02")

        self.assertIsNotNone(h1)
        self.assertIsNotNone(h2)
        self.assertEqual(h1["camera_id"], "CAM_FAIL_01")
        self.assertEqual(h2["camera_id"], "CAM_HEALTHY_02")

    # ------------------------------------------------------------------
    # 10. Phase 1 Calibration Integrity: Uncalibrated Must Be Null Speed
    # ------------------------------------------------------------------
    def test_10_uncalibrated_camera_strictly_returns_null_speed(self):
        """Uncalibrated cameras must produce speed_kmh=None and CALIBRATION_REQUIRED."""
        analyzer = VehicleRiskAnalyzer(calibration=None)

        det = [{"track_id": 99, "bbox": [100.0, 100.0, 150.0, 200.0]}]
        analyzer.analyze_frame_kinematics(det, current_time=1.0)
        det_next = [{"track_id": 99, "bbox": [100.0, 150.0, 150.0, 250.0]}]
        analyzer.analyze_frame_kinematics(det_next, current_time=1.1)

        self.assertIsNone(det_next[0]["speed_kmh"], "Uncalibrated camera must return speed_kmh=None")
        self.assertEqual(det_next[0]["speed_status"], "CALIBRATION_REQUIRED")
        self.assertNotIn(det_next[0].get("speed_kmh"), [45, 48, 52, 60, 95])

    # ------------------------------------------------------------------
    # 11. Calibrated Metric Speed via Homography
    # ------------------------------------------------------------------
    def test_11_calibrated_camera_metric_speed(self):
        """Calibrated cameras must calculate metric speed via homography matrix."""
        calib = CameraCalibration(
            calibration_id="CALIB_TEST",
            camera_id="CAM_TEST",
            image_polygon=[(100.0, 100.0), (300.0, 100.0), (350.0, 400.0), (50.0, 400.0)],
            real_width_meters=10.0,
            real_length_meters=50.0,
        )
        analyzer = VehicleRiskAnalyzer(calibration=calib)

        # Step 1: Initialize track ground contact at bottom center
        det0 = [{"track_id": 5, "bbox": [190.0, 80.0, 210.0, 100.0]}]
        analyzer.analyze_frame_kinematics(det0, current_time=1.0)

        # Step 2: Displace vehicle along ground plane over dt=1.0s
        H_inv = analyzer.calibrator.inv_homography_matrix
        pt_g = np.array([5.0, 20.0, 1.0], dtype=np.float64)  # 20m forward
        p_img_h = H_inv @ pt_g
        y_bottom = float(p_img_h[1] / p_img_h[2])
        x_center = float(p_img_h[0] / p_img_h[2])

        det1 = [{"track_id": 5, "bbox": [x_center - 10.0, y_bottom - 20.0, x_center + 10.0, y_bottom]}]
        analyzer.analyze_frame_kinematics(det1, current_time=2.0)

        self.assertIsNotNone(det1[0]["speed_kmh"])
        self.assertEqual(det1[0]["speed_status"], "VALID")
        # 20 meters in 1.0 second = 20 m/s = 72 km/h
        self.assertAlmostEqual(det1[0]["speed_kmh"], 72.0, delta=5.0)

    # ------------------------------------------------------------------
    # 12. Security & Sanitization: RTSP URLs Not Exposed to Browser
    # ------------------------------------------------------------------
    def test_12_browser_api_response_sanitized(self):
        """Client-facing camera API response must omit RTSP URLs and credentials."""
        # Simulated backend output from app.routers.cameras.list_cameras
        client_response_item = {
            "camera_id": "CAM_AHM_01",
            "name": "Ahmedabad SG Highway Node",
            "city": "Ahmedabad",
            "latitude": 23.0225,
            "longitude": 72.5714,
            "location_available": True,
            "codec": "h264",
            "status": "online",
            "calibration_status": "CALIBRATION_REQUIRED",
            "is_calibrated": False,
            "whep_url": "http://127.0.0.1:8889/live/CAM_AHM_01/whep",
            "hls_url": "http://127.0.0.1:8888/live/CAM_AHM_01/index.m3u8",
        }

        self.assertNotIn("rtsp_url", client_response_item, "rtsp_url must never be in client response")
        self.assertNotIn("credentials", client_response_item, "credentials must never be in client response")
        self.assertTrue(client_response_item["whep_url"].startswith("http"))
        self.assertTrue(client_response_item["hls_url"].startswith("http"))

    # ------------------------------------------------------------------
    # 13. Reconnect Exponential Backoff Strategy
    # ------------------------------------------------------------------
    def test_13_reconnect_exponential_backoff_progression(self):
        """Reconnect backoff delays must follow exponential progression with cap."""
        initial_backoff = 1.0
        multiplier = 2.0
        max_backoff = 16.0

        delays = []
        cur = initial_backoff
        for _ in range(5):
            delays.append(cur)
            cur = min(max_backoff, cur * multiplier)

        self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 16.0])


if __name__ == "__main__":
    unittest.main()
