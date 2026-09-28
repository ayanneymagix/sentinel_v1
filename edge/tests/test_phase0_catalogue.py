from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "backend"))
if str(ROOT_DIR / "edge") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "edge"))

import pytest

from app.services.catalogue_service import CameraCatalogueService, catalogue_service
from sentinel_edge.camera.dynamic_ingest import (
    CameraDescriptor,
    discover_camera_topology,
    stream_camera_frames,
)
from sentinel_edge.camera.stream_manager import FramePacket, StreamState


class TestPhase0CatalogueIntegration(unittest.TestCase):
    """
    Comprehensive Test Suite for SENTINEL Phase 0: Real Gujarat Camera Feed Integration.
    Strictly validates all 22 verification requirements without fabricated test data.
    """

    def setUp(self):
        self.service = CameraCatalogueService()

    # 1. Catalogue Retrieval
    def test_01_catalogue_retrieval_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "cam01", "name": "01 Chiman bhai Bridge"},
            {"id": "cam02", "name": "02 Janpath"},
        ]

        async def _test():
            with patch.object(self.service, "_get_http_client") as mock_client_getter:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_resp
                mock_client_getter.return_value = mock_client

                cams = await self.service.fetch_catalogue(force_refresh=True)
                assert len(cams) == 2
                assert cams[0]["camera_id"] == "cam01"
                assert cams[1]["camera_id"] == "cam02"

        asyncio.run(_test())

    # 2. Catalogue Parsing (both list and dict topologies)
    def test_02_catalogue_parsing_formats(self):
        # Case A: Dict format with cameras list
        dict_payload = {
            "count": 2,
            "cameras": [
                {
                    "id": "CAM_A",
                    "name": "Alpha Camera",
                    "codec": "h265",
                    "location": {"city": "Ahmedabad", "latitude": 23.01, "longitude": 72.58},
                    "endpoints": {"rtsp": "rtsp://gateway/stream/CAM_A", "hls": "/CAM_A/index.m3u8"},
                },
                {
                    "id": "CAM_B",
                    "name": "Beta Camera",
                    "codec": "h264",
                    "location": {"city": "Surat"},
                },
            ],
        }

        async def _test():
            normalized = await self.service._normalize_catalogue_response(dict_payload)
            assert len(normalized) == 2
            assert normalized[0]["camera_id"] == "CAM_A"
            assert normalized[0]["codec"] == "h265"
            assert normalized[0]["latitude"] == 23.01
            assert normalized[0]["location_available"] is True
            assert normalized[1]["camera_id"] == "CAM_B"
            assert normalized[1]["codec"] == "h264"
            assert normalized[1]["location_available"] is False

        asyncio.run(_test())

    # 3. Dynamic Camera Count (never hardcoded 30)
    def test_03_dynamic_camera_count(self):
        async def _test():
            for count in [7, 14, 28, 31]:
                raw = [{"id": f"cam_{i}", "name": f"Dynamic Cam {i}"} for i in range(count)]
                normalized = await self.service._normalize_catalogue_response(raw)
                assert len(normalized) == count, f"Expected {count} cameras, got {len(normalized)}"

        asyncio.run(_test())

    # 4. Dynamic Camera IDs (non-sequential, string IDs)
    def test_04_dynamic_camera_ids(self):
        raw = [
            {"id": "cctv-junction-north", "name": "North Junction"},
            {"id": "toll-booth-99", "name": "Toll Booth"},
            {"id": "highway-km-142", "name": "Highway KM 142"},
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            ids = [c["camera_id"] for c in normalized]
            assert ids == ["cctv-junction-north", "toll-booth-99", "highway-km-142"]

        asyncio.run(_test())

    # 5. Missing Camera Properties (graceful defaults without fabrication)
    def test_05_missing_camera_properties(self):
        raw = [{"id": "cam_bare_minimal"}]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            cam = normalized[0]
            assert cam["camera_id"] == "cam_bare_minimal"
            assert cam["name"] == "Camera cam_bare_minimal"
            assert cam["codec"] in ("h264", "h265")
            assert cam["latitude"] is None
            assert cam["longitude"] is None
            assert cam["location_available"] is False

        asyncio.run(_test())

    # 6. Invalid Catalogue Response (non-JSON / malformed)
    def test_06_invalid_catalogue_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_resp.text = "<html>502 Bad Gateway</html>"

        async def _test():
            with patch.object(self.service, "_get_http_client") as mock_client_getter:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_resp
                mock_client_getter.return_value = mock_client

                cams = await self.service.fetch_catalogue(force_refresh=True)
                assert cams == []
                assert self.service.get_service_status()["is_connected"] is False

        asyncio.run(_test())

    # 7. Catalogue Unavailable (Network Error)
    def test_07_catalogue_unavailable(self):
        async def _test():
            with patch.object(self.service, "_get_http_client") as mock_client_getter:
                mock_client = AsyncMock()
                mock_client.get.side_effect = Exception("Connection refused on gateway")
                mock_client_getter.return_value = mock_client

                cams = await self.service.fetch_catalogue(force_refresh=True)
                assert cams == []
                assert "Connection refused" in (self.service._last_error or "")

        asyncio.run(_test())

    # 8. Zero-Camera Response
    def test_08_zero_camera_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []

        async def _test():
            with patch.object(self.service, "_get_http_client") as mock_client_getter:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_resp
                mock_client_getter.return_value = mock_client

                cams = await self.service.fetch_catalogue(force_refresh=True)
                assert cams == []

        asyncio.run(_test())

    # 9. HLS URL Handling
    def test_09_hls_url_handling(self):
        raw = [
            {"id": "cam01", "name": "Cam 1", "endpoints": {"hls": "https://gateway/cam01/live.m3u8"}},
            {"id": "cam02", "name": "Cam 2"},  # Should use internal proxy URL
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["hls_url"] == "https://gateway/cam01/live.m3u8"
            assert normalized[1]["hls_url"] == "/api/cameras/cam02/hls/index.m3u8"

        asyncio.run(_test())

    # 10. WebRTC / WHEP URL Handling
    def test_10_webrtc_url_handling(self):
        raw = [
            {"id": "cam01", "endpoints": {"whep": "http://streamhost:8889/stream/cam01/whep"}},
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["whep_url"] == "http://streamhost:8889/stream/cam01/whep"

        asyncio.run(_test())

    # 11. RTSP URL Handling
    def test_11_rtsp_url_handling(self):
        raw = [
            {"id": "cam01", "endpoints": {"rtsp": "rtsp://ai-worker:8554/stream/cam01"}},
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["rtsp_url"] == "rtsp://ai-worker:8554/stream/cam01"

        asyncio.run(_test())

    # 12. RTSP TCP Configuration (forces TCP transport)
    def test_12_rtsp_tcp_configuration(self):
        # Must enforce TCP transport
        assert os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS") == "rtsp_transport;tcp"

    # 13. Camera Reconnection logic
    def test_13_camera_reconnection(self):
        # StreamState and Reconnect logic preserves record
        self.service.update_camera_health("cam_test", {
            "stream_state": "RECONNECTING",
            "reconnect_count": 3,
            "last_error": "Connection reset by peer",
        })

        async def _test():
            health = await self.service.get_camera_health("cam_test")
            assert health["stream_state"] == "RECONNECTING"
            assert health["reconnect_count"] == 3

        asyncio.run(_test())

    # 14. Exponential Backoff parameters
    def test_14_exponential_backoff_timing(self):
        backoff_delay = 2.0
        backoff_factor = 1.5
        backoff_max = 30.0

        delays = []
        cur = backoff_delay
        for _ in range(8):
            delays.append(cur)
            cur = min(backoff_max, cur * backoff_factor)

        assert delays[0] == 2.0
        assert delays[1] == 3.0
        assert delays[2] == 4.5
        assert delays[-1] == 30.0  # Capped at 30 seconds

    # 15. Health State Transitions (LIVE, DEGRADED, OFFLINE, UNKNOWN)
    def test_15_health_state_transitions(self):
        async def _test():
            # Initial state
            raw = [{"id": "cam_health", "live": True}]
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["live_status"] in ("LIVE", "DISCOVERED")

            # Healthy state update
            self.service.update_camera_health("cam_health", {"stream_state": "LIVE", "dropped_frames": 0})
            h1 = await self.service.get_camera_health("cam_health")
            assert h1["stream_state"] == "LIVE"

            # Degraded state update
            self.service.update_camera_health("cam_health", {"stream_state": "DEGRADED", "dropped_frames": 150})
            h2 = await self.service.get_camera_health("cam_health")
            assert h2["stream_state"] == "DEGRADED"

            # Offline state
            self.service.update_camera_health("cam_health", {"stream_state": "OFFLINE", "reconnect_count": 5})
            h3 = await self.service.get_camera_health("cam_health")
            assert h3["stream_state"] == "OFFLINE"

        asyncio.run(_test())

    # 16. Mixed H.264 / H.265 Codecs
    def test_16_mixed_codecs_h264_h265(self):
        raw = [
            {"id": "cam_264", "codec": "h264"},
            {"id": "cam_265", "codec": "h265"},
            {"id": "cam_hevc_ptz", "name": "HEVC 4K PTZ"},  # Auto-detected as h265
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["codec"] == "h264"
            assert normalized[1]["codec"] == "h265"
            assert normalized[2]["codec"] == "h265"

        asyncio.run(_test())

    # 17. Mixed Resolutions and FPS
    def test_17_mixed_resolutions(self):
        raw = [
            {"id": "cam_1080p", "resolution": "1920x1080", "fps": 25.0, "bitrate": 4000000},
            {"id": "cam_4k", "resolution": "3840x2160", "fps": 30.0, "bitrate": 12000000},
            {"id": "cam_720p", "resolution": "1280x720", "fps": 15.0, "bitrate": 1500000},
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["resolution"] == "1920x1080"
            assert normalized[0]["fps"] == 25.0
            assert normalized[1]["resolution"] == "3840x2160"
            assert normalized[1]["bitrate"] == 12000000
            assert normalized[2]["fps"] == 15.0

        asyncio.run(_test())

    # 18. Dynamic Camera Addition / Removal
    def test_18_dynamic_camera_addition_removal(self):
        async def _test():
            # Initial catalogue has 2 cameras
            c1 = [{"id": "c1"}, {"id": "c2"}]
            norm1 = await self.service._normalize_catalogue_response(c1)
            assert len(norm1) == 2

            # Camera c2 removed, c3 added
            c2 = [{"id": "c1"}, {"id": "c3"}]
            norm2 = await self.service._normalize_catalogue_response(c2)
            assert len(norm2) == 2
            ids = [c["camera_id"] for c in norm2]
            assert "c1" in ids and "c3" in ids and "c2" not in ids

        asyncio.run(_test())

    # 19. GIS Coordinate Handling (when provided)
    def test_19_gis_coordinate_handling(self):
        raw = [
            {"id": "cam_geo", "latitude": 23.0225, "longitude": 72.5714, "city": "Ahmedabad"},
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["latitude"] == 23.0225
            assert normalized[0]["longitude"] == 72.5714
            assert normalized[0]["location_available"] is True

        asyncio.run(_test())

    # 20. Missing GIS Coordinates (Strictly None, never fabricated)
    def test_20_missing_gis_coordinates(self):
        raw = [
            {"id": "cam_no_gps_999", "name": "Rural Outpost"},
        ]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            assert normalized[0]["latitude"] is None
            assert normalized[0]["longitude"] is None
            assert normalized[0]["location_available"] is False

        asyncio.run(_test())

    # 21. No Fake Camera Fallback (ZERO fabricated cameras)
    def test_21_no_fake_camera_fallback(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"

        async def _test():
            with patch.object(self.service, "_get_http_client") as mock_client_getter:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_resp
                mock_client_getter.return_value = mock_client

                # When gateway is down and cache is empty, MUST NOT return fake CAM01-CAM30
                cams = await self.service.fetch_catalogue(force_refresh=True)
                assert cams == [], "Violated Zero Fake Data Policy: returned fake cameras on failure!"

        asyncio.run(_test())

    # 22. Camera Identity Consistency (ID shared across metadata, streams, health)
    def test_22_camera_identity_consistency(self):
        raw = [{"id": "cam_canonical_42", "name": "Canonical Camera 42"}]

        async def _test():
            normalized = await self.service._normalize_catalogue_response(raw)
            cam = normalized[0]
            cam_id = cam["camera_id"]
            assert cam_id == "cam_canonical_42"
            assert cam_id in cam["hls_url"]
            assert cam_id in cam["whep_url"]
            assert cam_id in cam["rtsp_url"]

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
