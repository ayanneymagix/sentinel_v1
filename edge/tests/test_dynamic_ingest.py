import os
from unittest.mock import patch, MagicMock
import pytest
from sentinel_edge.camera.dynamic_ingest import (
    CameraDescriptor,
    FramePacket,
    discover_camera_topology,
    stream_camera_frames,
)

SAMPLE_CATALOGUE_PAYLOAD = {
    "status": "success",
    "cameras": [
        {
            "id": "CAM_TEST_01",
            "name": "Junction Alpha",
            "district_id": "DIST_01",
            "substation_id": "SUB_01",
            "location": {"city": "Ahmedabad", "latitude": 23.0225, "longitude": 72.5714},
            "codec": "h264",
            "live": True,
            "endpoints": {
                "rtsp": "rtsp://10.0.0.1:554/live",
                "hls": "/api/hls/CAM_TEST_01/index.m3u8",
                "whep": "/api/webrtc/CAM_TEST_01/whep",
                "fallback_file": "edge/media/mycctv1.mp4",
            },
            "pacing": {"preview_fps": 1.0, "active_fps": 25.0},
        },
        {
            "id": "CAM_TEST_02",
            "name": "Toll Plaza Beta",
            "district_id": "DIST_02",
            "substation_id": "SUB_02",
            "location": {"city": "Surat"},
            "codec": "h265",
            "live": False,
            "endpoints": {},
            "pacing": {},
        },
    ],
}


def test_discover_camera_topology_mocked():
    """Verify dynamic discovery returns valid camera descriptors without hardcoding."""
    with patch("requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_CATALOGUE_PAYLOAD
        mock_get.return_value = mock_resp

        descriptors = discover_camera_topology(api_base_url="http://mocked-gateway:8001")
        assert len(descriptors) == 2

        cam1 = descriptors[0]
        assert cam1.id == "CAM_TEST_01"
        assert cam1.codec == "h264"
        assert cam1.latitude == 23.0225
        assert cam1.longitude == 72.5714
        assert cam1.active_fps == 25.0

        # Camera 2 has missing coordinates — strictly None
        cam2 = descriptors[1]
        assert cam2.id == "CAM_TEST_02"
        assert cam2.codec == "h265"
        assert cam2.latitude is None
        assert cam2.longitude is None


def test_discover_camera_topology_unreachable():
    """When gateway is unreachable, discover_camera_topology returns empty list, zero fabrication."""
    descriptors = discover_camera_topology(api_base_url="http://192.0.2.1:9999", timeout_sec=0.1)
    assert descriptors == []


def test_discover_camera_topology_cameras_json_fallback():
    """Verify fallback to /cameras.json when /api/ingest returns 404."""
    with patch("requests.Session.get") as mock_get:
        # First call to /api/ingest returns 404, second call to /cameras.json returns 200 list
        resp_404 = MagicMock()
        resp_404.status_code = 404

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = [
            {"id": "cam01", "name": "01 Chiman bhai Bridge"},
            {"id": "cam02", "name": "02 Janpath"},
        ]

        mock_get.side_effect = [resp_404, resp_200]

        descriptors = discover_camera_topology(
            api_base_url="https://cctv.corp8.cloud",
            username="test@example.com",
            password="secretpassword",
        )

        assert len(descriptors) == 2
        assert descriptors[0].id == "cam01"
        assert descriptors[0].name == "01 Chiman bhai Bridge"
        assert descriptors[0].codec == "h264"
        assert descriptors[0].live is True
        assert "cam01" in descriptors[0].rtsp_url
        assert "cam01/index.m3u8" in descriptors[0].hls_url
        assert "test%40example.com" in descriptors[0].rtsp_url

        assert descriptors[1].id == "cam02"
        assert descriptors[1].name == "02 Janpath"


def test_stream_camera_frames_pts():
    """Verify frame generator extracts monotonic PTS from valid local fixture."""
    media_path = os.path.abspath("edge/media/mycctv1.mp4")
    if not os.path.exists(media_path):
        pytest.skip(f"Media file not found at {media_path}")

    cam = CameraDescriptor(
        id="CAM_TEST_MEDIA",
        name="Media Cam",
        district_id="DIST_01",
        substation_id="SUB_01",
        city="Ahmedabad",
        latitude=23.0,
        longitude=72.5,
        codec="h264",
        live=False,
        rtsp_url="",
        hls_url="",
        whep_url="",
        fallback_file=media_path,
        preview_fps=25.0,
        active_fps=25.0,
    )

    generator = stream_camera_frames(
        camera=cam,
        is_active=lambda: True,
    )

    packets = []
    for _ in range(5):
        packet = next(generator)
        assert isinstance(packet, FramePacket)
        assert packet.camera_id == cam.id
        assert packet.frame is not None
        assert packet.pts_ms >= 0
        packets.append(packet)

    assert len(packets) == 5
    for i in range(1, len(packets)):
        delta = packets[i].pts_ms - packets[i - 1].pts_ms
        assert delta >= 0
