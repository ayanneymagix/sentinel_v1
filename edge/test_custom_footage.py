"""
SENTINEL: State-Level CCTV Footage Perception & ANPR Pipeline
Runs real-time vehicle detection (YOLOv8 + ByteTrack), ALPR (EasyOCR),
dynamic risk priority scoring (High/Red, Medium/Yellow, Low/Green),
and non-blocking asynchronous backend event dispatching with exponential backoff.

Usage:
    python test_custom_footage.py --video "./media/mycctv.mp4"
    python test_custom_footage.py --video "./media/mycctv.mp4" --no-gui
"""

import argparse
import base64
import logging
import os
import queue
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
load_dotenv()

import cv2
import httpx

# Ensure local edge module imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sentinel_edge.camera.stream_manager import CameraStreamWorker, CameraDescriptor
from sentinel_edge.inference.detector import VehicleTracker, TrackedDetection, VehicleRiskAnalyzer
from sentinel_edge.alpr.engine import ALPREngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel.edge.runner")


class ThreadedEventDispatcher:
    """
    High-performance, non-blocking asynchronous event dispatcher.
    Runs HTTP transmissions in a dedicated background worker thread with exponential backoff retry.
    Ensures zero frame blocking during transient network glitches or server restarts (WinError 10061).
    """

    def __init__(self, backend_urls: list[str], max_queue_size: int = 250):
        self.backend_urls = backend_urls
        self.active_backend_url = backend_urls[0]
        self.queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def dispatch(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait((event_type, payload))
        except queue.Full:
            # Drop oldest low-priority live detection to prevent buffer overflow
            try:
                self.queue.get_nowait()
                self.queue.put_nowait((event_type, payload))
            except Exception:
                pass

    def _worker_loop(self) -> None:
        with httpx.Client(timeout=3.0) as client:
            while self.running:
                try:
                    item = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                event_type, payload = item
                self._send_with_retry(client, event_type, payload)
                self.queue.task_done()

    def _send_with_retry(
        self,
        client: httpx.Client,
        event_type: str,
        payload: dict[str, Any],
        max_retries: int = 3,
        initial_delay: float = 0.25,
    ) -> bool:
        delay = initial_delay

        for attempt in range(max_retries):
            # Try active backend URL, fallback to alternates if connection refused
            for base_url in self.backend_urls:
                try:
                    url = f"{base_url.rstrip('/')}/api/events"
                    res = client.post(url, json=payload)
                    if res.status_code in (200, 201, 202):
                        self.active_backend_url = base_url
                        return True
                    elif res.status_code >= 500:
                        logger.warning("Backend returned HTTP %d on attempt %d", res.status_code, attempt + 1)
                except (httpx.ConnectError, httpx.ConnectTimeout, ConnectionRefusedError, OSError) as conn_err:
                    # Target machine actively refused or server restarting
                    pass
                except Exception as ex:
                    logger.debug("Dispatch exception: %s", ex)

            # Exponential backoff delay before retry
            time.sleep(delay)
            delay = min(delay * 2.0, 2.5)

        return False

    def stop(self) -> None:
        self.running = False


class WatchlistSyncer:
    """
    Periodically synchronizes the eGujCop Watchlist from the cloud backend.
    """

    def __init__(self, backend_urls: list[str], sync_interval: float = 15.0):
        self.backend_urls = backend_urls
        self.sync_interval = sync_interval
        self.watchlist_plates: set[str] = set()
        self.running = True
        self.syncer_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.syncer_thread.start()

    def _sync_loop(self) -> None:
        while self.running:
            self.fetch_watchlist()
            time.sleep(self.sync_interval)

    def fetch_watchlist(self) -> None:
        with httpx.Client(timeout=3.0) as client:
            for base_url in self.backend_urls:
                try:
                    url = f"{base_url.rstrip('/')}/api/v1/watchlist"
                    res = client.get(url)
                    if res.status_code == 200:
                        data = res.json()
                        plates = set()
                        for item in data:
                            raw_p = item.get("license_plate") or item.get("plate")
                            if raw_p:
                                clean = "".join(c for c in raw_p.upper() if c.isalnum())
                                plates.add(clean)
                        self.watchlist_plates = plates
                        logger.info("Watchlist synced from %s: %d active flagged plates", base_url, len(plates))
                        return
                except Exception:
                    pass

    def get_plates(self) -> set[str]:
        return self.watchlist_plates

    def stop(self) -> None:
        self.running = False


def parse_args():
    parser = argparse.ArgumentParser(description="Sentinel State-Level CCTV AI Perception Runner")
    parser.add_argument(
        "--video",
        type=str,
        default=os.getenv("TEST_VIDEO_SOURCE", "data/cam01.mp4"),
        help="Path to video file, camera ID, or RTSP URL to process.",
    )
    parser.add_argument(
        "--camera-id",
        type=str,
        default="CAM_AHM_01",
        help="Camera ID (e.g. CAM_AHM_01, CAM_SUR_01, CAM_VAD_01)",
    )
    parser.add_argument(
        "--city",
        type=str,
        default="Ahmedabad",
        help="City of the camera (Ahmedabad, Surat, Vadodara, Rajkot)",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default="http://127.0.0.1:8000",
        help="URL of Sentinel backend API (defaults to port 8000, auto-probes 8001)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run in headless mode without opening the OpenCV visual preview window",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Frame stride (process 1 out of every N frames to optimize throughput)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.20,
        help="YOLO vehicle detection confidence threshold (default: 0.20 for state-wide precision)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Inference image size (default: 640, use 960 for low-light night intersection)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Maximum frames to process before exiting (useful for automated benchmarks)",
    )
    return parser.parse_args()


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    args = parse_args()
    video_source = args.video

    # Resolve video source path
    if not video_source.startswith("rtsp://") and not video_source.startswith("http://"):
        if not os.path.isabs(video_source):
            local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), video_source)
            if os.path.exists(local_path):
                video_source = local_path

        if not os.path.exists(video_source):
            # Resolve live camera from dynamic ingest topology
            try:
                from sentinel_edge.camera.dynamic_ingest import discover_camera_topology
                gateway_url = os.getenv("CCTV_GATEWAY_URL", "https://cctv.corp8.cloud")
                cams = discover_camera_topology(gateway_url)
                cam_id = args.camera_id if args.camera_id and args.camera_id != "camera" else video_source
                matched = next((c for c in cams if c.id == cam_id), None)
                if matched and matched.rtsp_url:
                    video_source = matched.rtsp_url
                    print(f"[SENTINEL] Connected to live camera RTSP source for {matched.id}: {matched.name}")
                elif cams and cams[0].rtsp_url:
                    video_source = cams[0].rtsp_url
                    print(f"[SENTINEL] Connected to primary live camera RTSP: {cams[0].name}")
            except Exception as e:
                print(f"[SENTINEL] Could not resolve live RTSP source: {e}")

    if not os.path.exists(video_source) and not video_source.startswith("rtsp://") and not video_source.startswith("http://"):
        print(f"\n[ERROR] Video file or live stream not found: {video_source}")
        return

    # Backend URLs with automatic fallback between port 8001 and 8000
    primary_url = args.backend_url.rstrip("/")
    secondary_url = "http://127.0.0.1:8000" if "8001" in primary_url else "http://127.0.0.1:8001"
    backend_urls = [primary_url, secondary_url]

    print("======================================================================")
    print("SENTINEL: STATE-LEVEL CCTV FOOTAGE PERCEPTION & ANPR RUNNER")
    print("======================================================================")
    print(f"Target Video Source: {video_source}")
    print(f"Camera ID:           {args.camera_id} ({args.city})")
    print(f"Primary Backend:     {primary_url} (Fallback: {secondary_url})")
    print(f"Visual Display HUD:  {'DISABLED (Headless)' if args.no_gui else 'ENABLED (Q: Quit, Space: Pause)'}")
    print("======================================================================\n")

    # 1. Initialize Threaded Non-blocking Event Dispatcher & Watchlist Syncer
    print("[1/5] Initializing Non-Blocking Event Dispatcher & Watchlist Syncer...")
    dispatcher = ThreadedEventDispatcher(backend_urls=backend_urls)
    watchlist_syncer = WatchlistSyncer(backend_urls=backend_urls, sync_interval=15.0)
    watchlist_syncer.fetch_watchlist()
    print("  [OK] Asynchronous dispatcher active (Resilient to backend restarts).")

    # 2. Initialize YOLOv8 Vehicle Tracker (ByteTrack)
    model_path = "./models/yolo26n.pt"
    if not os.path.exists(model_path):
        model_path = os.path.join(os.path.dirname(__file__), "models", "yolo26n.pt")

    # Probe source FPS to calibrate kinematics and time deltas
    src_fps = 25.0
    try:
        probe_cap = cv2.VideoCapture(video_source)
        cap_fps = probe_cap.get(cv2.CAP_PROP_FPS)
        if cap_fps and 5.0 <= cap_fps <= 120.0:
            src_fps = float(cap_fps)
        probe_cap.release()
    except Exception:
        pass

    print(f"[2/5] Loading YOLOv8 Vehicle Detection & ByteTrack Tracker (conf={args.conf}, imgsz={args.imgsz}, fps={src_fps:.2f})...")
    tracker = VehicleTracker(
        model_path=model_path,
        confidence=args.conf,
        classes=[0, 1, 2, 3, 5, 7],  # Person, Bicycle, Car, Motorcycle, Bus, Truck
        tracker="bytetrack.yaml",
        image_size=args.imgsz,
        fps=src_fps,
        camera_id=args.camera_id if getattr(args, "camera_id", None) else "cam01",
        camera_name=f"Camera {getattr(args, 'camera_id', 'cam01')}",
    )
    print("  [OK] Vehicle Tracker initialized successfully.")

    # 3. Initialize ALPR Engine (Plate Detector + OCR)
    plate_model_path = "./models/license_plate.pt"
    if not os.path.exists(plate_model_path):
        plate_model_path = os.path.join(os.path.dirname(__file__), "models", "license_plate.pt")

    print("[3/5] Loading ALPR Plate Detector & EasyOCR Engine (sveyek Video-ANPR Architecture)...")
    alpr_engine = None
    try:
        alpr_engine = ALPREngine(
            plate_model_path=plate_model_path,
            detector_confidence=0.60,
            detector_image_size=640,
            ocr_gpu=False,
            temporal_observations=15,
            temporal_minimum_votes=5,
            min_blur_score=45.0,
        )
        print("  [OK] ALPR Engine initialized successfully (Temporal Consensus & Laplacian Quality Gate Active).")
    except Exception as e:
        print(f"  [WARNING] ALPR Engine could not be loaded: {e}. Running vehicle tracking only.")

    # 4. Open Video Stream via Zero-Latency CameraStream
    print("[4/5] Initializing Video Stream Grabber...")
    def on_stream_reset():
        tracker.reset()
        if alpr_engine:
            alpr_engine.reset()

    descriptor = CameraDescriptor(
        id=args.camera_id,
        name=f"Camera {args.camera_id}",
        rtsp_url=str(video_source),
        codec="h264",
        live=True,
    )
    stream = CameraStreamWorker(
        descriptor=descriptor,
        queue_size=1,
        on_pts_reset=on_stream_reset,
    )
    stream.start()
    print("  [OK] Camera stream opened.")

    # Registered Test Camera Metadata (Strict explicit identity - zero silent defaults)
    registered_cameras = {
        "CAM_AHM_MYCCTV": {"city": "Ahmedabad", "lat": 23.0225, "lon": 72.5714, "name": "Ahmedabad SG Highway Corridor (mycctv.mp4)"},
        "CAM_AHM_MYCCTV1": {"city": "Ahmedabad", "lat": 23.0039, "lon": 72.5850, "name": "Ahmedabad Ring Road Intersection (mycctv1.mp4)"},
        "CAM_VAD_MYCCTV2": {"city": "Vadodara", "lat": 22.3129, "lon": 73.1926, "name": "Vadodara Highway Junction (mycctv2.mp4)"},
        "CAM_GND_MYCCTV3": {"city": "Gandhinagar", "lat": 23.2156, "lon": 72.6369, "name": "Gandhinagar Secretariat Corridor (mycctv3.mp4)"},
        "CAM_AHM_MYCCTV4": {"city": "Ahmedabad", "lat": 23.0125, "lon": 72.5645, "name": "Ahmedabad SP Ring Road Crash Corridor (mycctv4.mp4)"},
        "CAM_AHM_01": {"city": "Ahmedabad", "lat": 23.0039, "lon": 72.5850, "name": "Ahmedabad Surveillance Node 01"},
    }

    cam_info = registered_cameras.get(args.camera_id)
    if not cam_info:
        # Match by video filename if custom camera ID was not given
        base_vname = os.path.basename(video_source).lower()
        if "mycctv1" in base_vname:
            cam_info = registered_cameras["CAM_AHM_MYCCTV1"]
        elif "mycctv2" in base_vname:
            cam_info = registered_cameras["CAM_VAD_MYCCTV2"]
        elif "mycctv3" in base_vname:
            cam_info = registered_cameras["CAM_GND_MYCCTV3"]
        elif "mycctv4" in base_vname:
            cam_info = registered_cameras["CAM_AHM_MYCCTV4"]
        elif "mycctv" in base_vname:
            cam_info = registered_cameras["CAM_AHM_MYCCTV"]

    if cam_info:
        lat = cam_info["lat"]
        lon = cam_info["lon"]
        camera_city = cam_info["city"]
        camera_name = cam_info["name"]
    else:
        # Strict rule: If location metadata does not exist, location is None (LOCATION UNAVAILABLE)
        lat = None
        lon = None
        camera_city = args.city
        camera_name = args.camera_id

    frame_count = 0
    start_time = time.monotonic()
    emitted_plates: set[str] = set()
    emitted_collisions: set[tuple[int, int]] = set()
    plate_by_track: dict[int, str] = {}
    alpr_attempts: dict[int, int] = {}
    alpr_details_by_track: dict[int, dict] = {}
    paused = False

    print("\n[5/5] Processing CCTV Frames in Real-Time...")
    print("      -> Open your browser to http://localhost:5173/ or http://localhost:8001/dashboard/ to view live radar!\n")

    try:
        while True:
            if not paused:
                packet = stream.read(timeout=0.5)
                if packet is None or packet.frame is None:
                    time.sleep(0.01)
                    continue

                frame = packet.frame
                pts_ms = (packet.pts * 1000.0) if packet.pts is not None else (frame_count * 40.0)

                frame_count += 1
                if args.max_frames and frame_count > args.max_frames:
                    print(f"\n[INFO] Reached requested max frames ({args.max_frames}). Exiting cleanly.")
                    break
                if frame_count % args.stride != 0:
                    continue

                h, w = frame.shape[:2]
                curr_mono_time = time.monotonic()
                fps = frame_count / max(1.0, time.monotonic() - start_time)
                video_time_seconds = round(pts_ms / 1000.0, 3) if pts_ms > 0 else round(frame_count / src_fps, 3)

                # Sync watchlist with tracker risk analyzer
                active_watchlist = watchlist_syncer.get_plates()
                tracker.update_watchlist(active_watchlist)

                # -----------------------------------------------------------------
                # Safe Tracker Unpacking: handles tuple, list, or custom objects
                # -----------------------------------------------------------------
                track_res = tracker.track(frame, current_time=video_time_seconds)
                if isinstance(track_res, tuple) and len(track_res) == 2:
                    raw_detections, latency_ms = track_res
                elif isinstance(track_res, list):
                    raw_detections = track_res
                    latency_ms = 35.0
                else:
                    raw_detections = []
                    latency_ms = 35.0

                processed_detections = []
                high_risk_hits = []
                incident_snapshot_base64 = None

                # Check if any detection triggers an incident snapshot
                has_critical_incident = any(
                    (getattr(d, "collision_detected", False) or
                     getattr(d, "risk_priority", "LOW") == "HIGH" or
                     (isinstance(d, dict) and (d.get("collision_detected") or d.get("risk_priority") == "HIGH")))
                    for d in raw_detections
                )

                if has_critical_incident:
                    try:
                        snap_frame = cv2.resize(frame, (960, 540)) if (w > 1280 or h > 720) else frame
                        _, snap_buf = cv2.imencode('.jpg', snap_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                        incident_snapshot_base64 = base64.b64encode(snap_buf).decode('utf-8')
                    except Exception as snap_err:
                        logger.debug("Snapshot encoding error: %s", snap_err)

                # Iterate through detected vehicles
                # Iterate through detected vehicles
                for i, det in enumerate(raw_detections):
                    # Safe attribute/dict unpacking
                    if isinstance(det, dict):
                        track_id = det.get("track_id")
                        bbox = det.get("bbox", [0, 0, 0, 0])
                        norm_bbox = det.get("norm_bbox")
                        cls_name = det.get("object_type", det.get("class_name", "vehicle"))
                        conf = float(det.get("confidence", 0.0))
                        risk_level = str(det.get("risk_level", "LOW")).upper()
                        risk_priority = det.get("risk_priority", risk_level)
                        risk_color = det.get("risk_color", "#10b981")
                        risk_reason = det.get("risk_reason", "Standard Patrol Track")
                        raw_vx = det.get("vx")
                        vx = float(raw_vx) if raw_vx is not None else 0.0
                        raw_vy = det.get("vy")
                        vy = float(raw_vy) if raw_vy is not None else 0.0
                        raw_spd = det.get("speed")
                        speed = float(raw_spd) if raw_spd is not None else 0.0
                        raw_hdg = det.get("heading_deg")
                        heading_deg = float(raw_hdg) if raw_hdg is not None else None
                        raw_acc = det.get("acceleration")
                        acceleration = float(raw_acc) if raw_acc is not None else 0.0
                        collision_detected = bool(det.get("collision_detected", False))
                        collision_partner_id = det.get("collision_partner_id")
                        make = det.get("make")
                        model_subtype = det.get("model_subtype")
                        color = det.get("color")
                        full_name = det.get("full_name")
                        color_rgb = det.get("color_rgb")
                        trajectory = det.get("trajectory", [])
                        direction = det.get("direction")
                        global_id = det.get("global_id")
                        journey_length = det.get("journey_length", 1)
                        appearance_embedding = det.get("appearance_embedding")
                        is_reid_match = det.get("is_reid_match", False)
                    else:
                        track_id = getattr(det, "track_id", None)
                        bbox = getattr(det, "bbox", [0, 0, 0, 0])
                        norm_bbox = getattr(det, "norm_bbox", None)
                        cls_name = getattr(det, "class_name", getattr(det, "object_type", "vehicle"))
                        conf = float(getattr(det, "confidence", 0.0))
                        risk_level = str(getattr(det, "risk_level", "LOW")).upper()
                        risk_priority = getattr(det, "risk_priority", risk_level)
                        risk_color = getattr(det, "risk_color", "#10b981")
                        risk_reason = getattr(det, "risk_reason", "Standard Patrol Track")
                        raw_vx = getattr(det, "vx", 0.0)
                        vx = float(raw_vx) if raw_vx is not None else 0.0
                        raw_vy = getattr(det, "vy", 0.0)
                        vy = float(raw_vy) if raw_vy is not None else 0.0
                        raw_spd = getattr(det, "speed", 0.0)
                        speed = float(raw_spd) if raw_spd is not None else 0.0
                        raw_hdg = getattr(det, "heading_deg", None)
                        heading_deg = float(raw_hdg) if raw_hdg is not None else None
                        raw_acc = getattr(det, "acceleration", 0.0)
                        acceleration = float(raw_acc) if raw_acc is not None else 0.0
                        collision_detected = bool(getattr(det, "collision_detected", False))
                        collision_partner_id = getattr(det, "collision_partner_id", None)
                        make = getattr(det, "make", None)
                        model_subtype = getattr(det, "model_subtype", None)
                        color = getattr(det, "color", None)
                        full_name = getattr(det, "full_name", None)
                        color_rgb = getattr(det, "color_rgb", None)
                        trajectory = getattr(det, "trajectory", [])
                        direction = getattr(det, "direction", None)
                        global_id = getattr(det, "global_id", None)
                        journey_length = getattr(det, "journey_length", 1)
                        appearance_embedding = getattr(det, "appearance_embedding", None)
                        is_reid_match = getattr(det, "is_reid_match", False)

                    if collision_detected or risk_level == "CRITICAL":
                        risk_level = "CRITICAL"
                        risk_priority = "HIGH"
                        risk_color = "#ef4444"

                    if not norm_bbox:
                        norm_bbox = [
                            max(0.0, min(1.0, bbox[0] / max(1, w))),
                            max(0.0, min(1.0, bbox[1] / max(1, h))),
                            max(0.0, min(1.0, bbox[2] / max(1, w))),
                            max(0.0, min(1.0, bbox[3] / max(1, h))),
                        ]

                    alpr_track_id = int(track_id) if track_id is not None else (100000 + i)

                    # Check if plate was already recognized for this track
                    recognized_plate = plate_by_track.get(alpr_track_id)

                    # Crop vehicle region for ALPR if not yet recognized
                    px1 = max(0, int(bbox[0]))
                    py1 = max(0, int(bbox[1]))
                    px2 = min(w, int(bbox[2]))
                    py2 = min(h, int(bbox[3]))

                    if (
                        recognized_plate is None
                        and alpr_engine is not None
                        and alpr_attempts.get(alpr_track_id, 0) < 12
                        and (frame_count % 2 == 0)
                        and (px2 - px1) > 40
                        and (py2 - py1) > 40
                    ):
                        alpr_attempts[alpr_track_id] = alpr_attempts.get(alpr_track_id, 0) + 1
                        vehicle_crop = frame[py1:py2, px1:px2]
                        try:
                            alpr_res = alpr_engine.process(
                                track_id=alpr_track_id,
                                vehicle_crop=vehicle_crop,
                                timestamp=pts_ms / 1000.0,
                                frame_shape=(h, w),
                                vehicle_bbox=bbox,
                            )
                            if alpr_res:
                                if alpr_res.recognized and alpr_res.plate_text:
                                    recognized_plate = alpr_res.plate_text
                                    plate_by_track[alpr_track_id] = recognized_plate

                                raw_blur = getattr(alpr_res, "blur_score", None)
                                raw_conf = getattr(alpr_res, "plate_confidence", None)
                                alpr_details_by_track[alpr_track_id] = {
                                    "plate": recognized_plate or getattr(alpr_res, "plate_text", None),
                                    "vote_count": getattr(alpr_res, "vote_count", 0),
                                    "is_finalized": getattr(alpr_res, "is_finalized", False),
                                    "blur_score": round(float(raw_blur), 1) if raw_blur is not None else None,
                                    "confidence": round(float(raw_conf), 2) if raw_conf is not None else None,
                                }
                        except Exception as alpr_err:
                            logger.debug("ALPR error on track %s: %s", alpr_track_id, alpr_err)

                    # Evaluate dynamic risk priority with plate data
                    if recognized_plate:
                        clean_p = "".join(c for c in recognized_plate.upper() if c.isalnum())
                        if clean_p in active_watchlist:
                            risk_level = "HIGH"
                            risk_priority = "HIGH"
                            risk_color = "#ef4444"
                            risk_reason = f"eGujCop Watchlist Match ({recognized_plate})"
                            high_risk_hits.append((track_id, recognized_plate, risk_reason))

                    # Strict rule: Never fabricate ALPR results or confidence
                    alpr_info = alpr_details_by_track.get(alpr_track_id) or {
                        "plate": recognized_plate,
                        "vote_count": 0,
                        "is_finalized": False,
                        "blur_score": None,
                        "confidence": None,
                    }

                    velocity_px_s = float(det.get("velocity_px_s", det.get("speed", 0.0)))
                    speed_kmh = det.get("speed_kmh")
                    speed_status = str(det.get("speed_status", "CALIBRATION_REQUIRED"))
                    speed_display_reason = det.get("speed_display_reason", "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED")
                    calibration_id = det.get("calibration_id")
                    collision_evidence = det.get("collision_evidence")

                    kinematics_info = {
                        "velocity_px_s": round(velocity_px_s, 2),
                        "speed_kmh": speed_kmh,
                        "speed_status": speed_status,
                        "speed_display_reason": speed_display_reason,
                        "calibration_id": calibration_id,
                        "vx_px_s": float(det.get("vx_px_s", vx)),
                        "vy_px_s": float(det.get("vy_px_s", vy)),
                        "heading_deg": round(heading_deg, 1) if heading_deg is not None else None,
                        "accel_px_s2": float(det.get("accel_px_s2", acceleration)),
                        "collision_detected": collision_detected,
                        "collision_partner_id": collision_partner_id,
                        "collision_evidence": collision_evidence,
                        # Compatibility:
                        "speed": round(velocity_px_s, 2),
                        "vx": round(vx, 2),
                        "vy": round(vy, 2),
                        "acceleration": round(acceleration, 2),
                    }

                    # Append to processed detections payload
                    det_dict = {
                        "track_id": track_id,
                        "object_type": cls_name,
                        "confidence": round(conf, 3),
                        "bbox": [round(c, 1) for c in bbox],
                        "norm_bbox": [round(c, 4) for c in norm_bbox],
                        "plate": recognized_plate,
                        "alpr_details": alpr_info,
                        "kinematics": kinematics_info,
                        "velocity_px_s": round(velocity_px_s, 2),
                        "speed_kmh": speed_kmh,
                        "speed_status": speed_status,
                        "speed_display_reason": speed_display_reason,
                        "calibration_id": calibration_id,
                        "risk_level": risk_level,
                        "risk_priority": risk_priority,
                        "risk_color": risk_color,
                        "risk_reason": risk_reason,
                        "video_time_seconds": round(video_time_seconds, 3),
                        "vx_px_s": float(det.get("vx_px_s", vx)),
                        "vy_px_s": float(det.get("vy_px_s", vy)),
                        "vx": round(vx, 2),
                        "vy": round(vy, 2),
                        "speed": round(velocity_px_s, 2),
                        "heading_deg": round(heading_deg, 1) if heading_deg is not None else None,
                        "acceleration": round(acceleration, 2),
                        "collision_detected": collision_detected,
                        "collision_partner_id": collision_partner_id,
                        "collision_evidence": collision_evidence,
                        "make": make,
                        "model_subtype": model_subtype,
                        "color": color,
                        "full_name": full_name,
                        "color_rgb": color_rgb,
                        "trajectory": trajectory,
                        "direction": direction,
                        "global_id": global_id,
                        "journey_length": journey_length,
                        "appearance_embedding": appearance_embedding,
                        "is_reid_match": is_reid_match,
                    }
                    processed_detections.append(det_dict)

                    # ---------------------------------------------------------
                    # Draw Dynamic Risk-Coded Bounding Box & Trajectory in OpenCV
                    # ---------------------------------------------------------
                    if not args.no_gui:
                        # Draw vehicle trajectory trail
                        if trajectory and len(trajectory) >= 2:
                            pts_poly = np.array(trajectory, np.int32).reshape((-1, 1, 2))
                            cv2.polylines(frame, [pts_poly], False, (0, 240, 255), 2)

                        # Color: BGR format for OpenCV
                        if risk_level in ("CRITICAL", "HIGH") or risk_priority == "HIGH":
                            box_bgr = (0, 0, 255)       # Red
                        elif risk_level == "MEDIUM" or risk_priority == "MEDIUM":
                            box_bgr = (0, 200, 255)     # Amber/Yellow
                        else:
                            box_bgr = (0, 220, 100)     # Green

                        # Draw rectangle
                        cv2.rectangle(frame, (px1, py1), (px2, py2), box_bgr, 2)

                        # Label badge
                        tid_str = f"#{track_id}" if track_id is not None else "#?"
                        if speed_kmh is not None:
                            speed_str = f"{int(speed_kmh)}km/h"
                        else:
                            speed_str = f"{int(velocity_px_s)}px/s [UNCALIB]"
                        display_name = full_name if full_name else cls_name.upper()
                        dir_str = f"[{direction}]" if direction else ""
                        header_lbl = f"{tid_str} {display_name} {dir_str} {speed_str}".strip()
                        if global_id:
                            header_lbl = f"[{global_id}] " + header_lbl
                        if recognized_plate:
                            header_lbl += f" | {recognized_plate}"

                        # Badge background
                        (lw, lh), _ = cv2.getTextSize(header_lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 2)
                        cv2.rectangle(frame, (px1, max(0, py1 - lh - 8)), (px1 + lw + 8, py1), box_bgr, -1)
                        text_color = (255, 255, 255) if risk_priority == "HIGH" else (0, 0, 0)
                        cv2.putText(frame, header_lbl, (px1 + 4, max(14, py1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, text_color, 2)

                        # Draw risk reason if not normal
                        if risk_level != "LOW":
                            cv2.putText(frame, risk_reason, (px1, min(h - 5, py2 + 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, box_bgr, 1)

                    # ---------------------------------------------------------
                    # Kinematic Accident Collision Alert Dispatch
                    # ---------------------------------------------------------
                    if collision_detected:
                        pair_key = tuple(sorted([track_id or 0, collision_partner_id or 0]))
                        if pair_key not in emitted_collisions:
                            emitted_collisions.add(pair_key)
                            collision_payload = {
                                "event_id": str(uuid.uuid4()),
                                "node_id": "EDGE_LOCAL_TEST",
                                "camera_id": args.camera_id,
                                "event_type": "VEHICLE_COLLISION",
                                "risk_level": "CRITICAL",
                                "risk_reason": risk_reason,
                                "confidence": None,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "video_time_seconds": round(video_time_seconds, 3),
                                "latitude": lat,
                                "longitude": lon,
                                "frame_number": frame_count,
                                "inference_latency_ms": float(latency_ms),
                                "detections": processed_detections,
                                "incident_snapshot_base64": incident_snapshot_base64,
                                "metadata": {
                                    "city": args.city,
                                    "source": video_source,
                                    "risk_level": "CRITICAL",
                                    "risk_priority": "HIGH",
                                    "risk_reason": risk_reason,
                                    "video_time_seconds": round(video_time_seconds, 3),
                                    "detections": processed_detections,
                                    "collision": {
                                        "primary_track_id": track_id,
                                        "partner_track_id": collision_partner_id,
                                        "velocity_px_s": velocity_px_s,
                                        "speed_kmh": speed_kmh,
                                        "speed_status": speed_status,
                                        "evidence_factors": collision_evidence,
                                    },
                                    "incident_snapshot_base64": incident_snapshot_base64,
                                },
                            }
                            dispatcher.dispatch("VEHICLE_COLLISION", collision_payload)
                            print(f"  [💥 CRITICAL COLLISION] Between Track #{track_id} & #{collision_partner_id} at {video_time_seconds:.2f}s!")

                    # ---------------------------------------------------------
                    # Send High-Priority Alert when a plate is spotted
                    # ---------------------------------------------------------
                    if recognized_plate and recognized_plate not in emitted_plates:
                        emitted_plates.add(recognized_plate)
                        is_threat = (risk_priority == "HIGH" or risk_level == "HIGH")

                        event_payload = {
                            "event_id": str(uuid.uuid4()),
                            "node_id": "EDGE_LOCAL_TEST",
                            "camera_id": args.camera_id,
                            "event_type": "THREAT_DETECTED" if is_threat else "ALPR_DETECTED",
                            "risk_level": "HIGH" if is_threat else "LOW",
                            "risk_reason": risk_reason,
                            "confidence": min(1.0, max(0.0, float(conf))),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "video_time_seconds": round(video_time_seconds, 3),
                            "latitude": lat,
                            "longitude": lon,
                            "frame_number": frame_count,
                            "inference_latency_ms": float(latency_ms),
                            "detections": processed_detections,
                            "incident_snapshot_base64": incident_snapshot_base64 if is_threat else None,
                            "metadata": {
                                "city": args.city,
                                "source": video_source,
                                "risk_level": "HIGH" if is_threat else "LOW",
                                "risk_priority": risk_priority,
                                "risk_reason": risk_reason,
                                "video_time_seconds": round(video_time_seconds, 3),
                                "detections": processed_detections,
                                "incident_snapshot_base64": incident_snapshot_base64 if is_threat else None,
                                "alpr": {
                                    "plate": recognized_plate,
                                    "track_id": track_id,
                                    "plate_confidence": alpr_info.get("confidence") if alpr_info else None,
                                    "vote_count": alpr_info.get("vote_count", 0) if alpr_info else 0,
                                    "blur_score": alpr_info.get("blur_score") if alpr_info else None,
                                },
                            },
                        }
                        dispatcher.dispatch(event_payload["event_type"], event_payload)
                        status_prefix = "[🚨 THREAT ALERT]" if is_threat else "[VEHICLE DETECTED]"
                        print(f"  {status_prefix} Track #{track_id} | Plate: {recognized_plate} | Priority: {risk_priority}")

                # -------------------------------------------------------------
                # Broadcast Live Detection Frame with Bounding Boxes to Dashboard
                # -------------------------------------------------------------
                if processed_detections or (frame_count % 10 == 0):
                    # Compute highest risk tier in this frame
                    top_risk_level = "LOW"
                    top_risk_reason = "Standard Patrol Track"
                    for d in processed_detections:
                        lvl = d.get("risk_level", "LOW")
                        if lvl == "CRITICAL":
                            top_risk_level = "CRITICAL"
                            top_risk_reason = d.get("risk_reason", "CRITICAL: VEHICLE COLLISION")
                            break
                        elif lvl == "HIGH" and top_risk_level != "CRITICAL":
                            top_risk_level = "HIGH"
                            top_risk_reason = d.get("risk_reason", top_risk_reason)
                        elif lvl == "MEDIUM" and top_risk_level == "LOW":
                            top_risk_level = "MEDIUM"
                            top_risk_reason = d.get("risk_reason", top_risk_reason)

                    # Calculate real frame-level confidence from detections
                    frame_conf = max((d.get("confidence") for d in processed_detections if d.get("confidence") is not None), default=None)

                    live_frame_payload = {
                        "event_id": str(uuid.uuid4()),
                        "node_id": "EDGE_LOCAL_TEST",
                        "camera_id": args.camera_id,
                        "event_type": "LIVE_DETECTION",
                        "risk_level": top_risk_level,
                        "risk_reason": top_risk_reason,
                        "confidence": frame_conf,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "video_time_seconds": round(video_time_seconds, 3),
                        "fps": round(fps, 2),
                        "latitude": lat,
                        "longitude": lon,
                        "frame_number": frame_count,
                        "inference_latency_ms": float(latency_ms),
                        "detections": processed_detections,
                        "incident_snapshot_base64": incident_snapshot_base64,
                        "metadata": {
                            "city": args.city,
                            "source": video_source,
                            "risk_level": top_risk_level,
                            "risk_reason": top_risk_reason,
                            "frame_width": w,
                            "frame_height": h,
                            "video_time_seconds": round(video_time_seconds, 3),
                            "fps": round(fps, 2),
                            "detections": processed_detections,
                            "incident_snapshot_base64": incident_snapshot_base64,
                        },
                    }
                    dispatcher.dispatch("LIVE_DETECTION", live_frame_payload)

                if frame_count % 30 == 0:
                    fps = frame_count / max(1.0, time.monotonic() - start_time)
                    print(f"  [RADAR] Frame #{frame_count} | Active Tracks: {len(processed_detections)} | Plates: {len(emitted_plates)} | FPS: {fps:.1f}")

                # Draw Overlay HUD Watermark
                if not args.no_gui:
                    fps = frame_count / max(1.0, time.monotonic() - start_time)
                    cv2.putText(frame, f"SENTINEL EDGE RADAR | FPS: {fps:.1f} | CAM: {args.camera_id}", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
                    cv2.putText(frame, f"Tracks: {len(processed_detections)} | Plates Recognized: {len(emitted_plates)} | Watchlist: {len(active_watchlist)}", (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
                    try:
                        cv2.imshow("Sentinel CCTV Perception HUD", frame)
                    except Exception as gui_err:
                        print(f"  [NOTE] GUI preview unavailable ({gui_err}). Switching to Headless Mode.")
                        args.no_gui = True

            # Key controls
            if not args.no_gui:
                try:
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        print("\n[INFO] User quit video preview.")
                        break
                    elif key == ord(" "):
                        paused = not paused
                        print(f"\n[INFO] Video {'PAUSED' if paused else 'RESUMED'}.")
                except Exception:
                    args.no_gui = True

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        stream.stop()
        if not args.no_gui:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        watchlist_syncer.stop()
        dispatcher.stop()
        print(f"\nFinished processing. Total unique license plates recognized: {len(emitted_plates)}")


if __name__ == "__main__":
    main()
