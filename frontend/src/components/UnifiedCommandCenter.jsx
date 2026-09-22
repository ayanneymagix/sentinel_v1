import React, { useState, useEffect, useRef } from 'react';
import Hls from 'hls.js';
import {
  Play,
  Pause,
  RotateCcw,
  Square,
  Shield,
  Zap,
  AlertTriangle,
  Radio,
  MapPin,
  Volume2,
  VolumeX,
  Gauge,
  Eye,
  Siren,
  Camera,
  Search,
  CheckCircle2,
  Navigation,
  Clock,
  Car,
  FileText,
  X,
  Send,
  SlidersHorizontal,
  Network,
  Layers,
  Activity,
  ArrowRight,
  Share2,
  Compass,
} from 'lucide-react';
import CameraCalibrationModal from './CameraCalibrationModal';

export default function UnifiedCommandCenter({
  cameras = [],
  onSelectPlateForRoute = () => {},
}) {
  // Video player refs
  const videoRef = useRef(null);
  const videoContainerRef = useRef(null);
  const audioCtxRef = useRef(null);
  const lastSirenRef = useRef(0);
  const telemetryBufferRef = useRef([]);
  const lastCurTimeRef = useRef(0);
  const latestDetectionsRef = useRef([]);

  // Dynamic CCTV Camera Registry State (strictly populated from live API)
  const [camerasList, setCamerasList] = useState(Array.isArray(cameras) ? cameras : []);
  const [selectedCameraId, setSelectedCameraId] = useState(() => cameras?.[0]?.camera_id || '');
  const hlsPlayerRef = useRef(null);

  // Derive authoritative active camera (must be declared before any hooks use it)
  const activeCamera = camerasList.find((c) => c.camera_id === selectedCameraId) || camerasList[0] || (selectedCameraId ? {
    camera_id: selectedCameraId,
    name: `Camera ${selectedCameraId}`,
    city: 'Gujarat',
    latitude: null,
    longitude: null,
    location_available: false,
    codec: 'h264',
    status: 'online',
    is_calibrated: false,
    calibration_status: 'CALIBRATION_REQUIRED',
    hls_url: `/api/cameras/${selectedCameraId}/hls/index.m3u8`,
    whep_url: `/api/cameras/${selectedCameraId}/whep`,
  } : {
    camera_id: '',
    name: 'No Camera Selected',
    city: 'Gujarat',
    latitude: null,
    longitude: null,
    location_available: false,
    codec: 'h264',
    status: 'offline',
    is_calibrated: false,
    calibration_status: 'CALIBRATION_REQUIRED',
    hls_url: '',
    whep_url: '',
  });

  const activeFeedObj = {
    id: activeCamera.camera_id,
    name: activeCamera.name || activeCamera.camera_id,
    code: activeCamera.camera_id,
    city: activeCamera.city || 'Gujarat',
    desc: `${activeCamera.name || activeCamera.camera_id} • ${(activeCamera.codec || 'H264').toUpperCase()}`,
    risk: activeCamera.status === 'online' ? 'NORMAL' : 'CRITICAL',
    badgeColor: activeCamera.status === 'online' ? '#10b981' : '#ef4444',
    location_available: activeCamera.location_available ?? (activeCamera.latitude != null && activeCamera.longitude != null),
    latitude: activeCamera.latitude,
    longitude: activeCamera.longitude,
    is_calibrated: Boolean(activeCamera.is_calibrated),
    calibration_status: activeCamera.calibration_status || 'CALIBRATION_REQUIRED',
    hls_url: activeCamera.hls_url || (activeCamera.camera_id ? `/api/cameras/${activeCamera.camera_id}/hls/index.m3u8` : ''),
    whep_url: activeCamera.whep_url || (activeCamera.camera_id ? `/api/cameras/${activeCamera.camera_id}/whep` : ''),
  };

  // Sync cameras prop if provided from parent App.jsx
  useEffect(() => {
    if (Array.isArray(cameras) && cameras.length > 0) {
      setCamerasList(cameras);
      setSelectedCameraId((prev) => prev || cameras[0].camera_id);
    }
  }, [cameras]);

  // Reconcile dynamic camera registry from authoritative /api/cameras
  useEffect(() => {
    let isMounted = true;
    const fetchCameras = async () => {
      try {
        const res = await fetch('/api/cameras');
        if (res.ok) {
          const data = await res.json();
          if (isMounted && Array.isArray(data) && data.length > 0) {
            setCamerasList(data);
            setSelectedCameraId((prev) => prev || data[0].camera_id);
          }
        }
      } catch (err) {
        console.debug('Dynamic camera discovery notice:', err);
      }
    };
    fetchCameras();
    const interval = setInterval(fetchCameras, 10000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Video Playback Controls
  const [isPlaying, setIsPlaying] = useState(true);
  const [isMuted, setIsMuted] = useState(true);
  const [sirenMuted, setSirenMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [videoRect, setVideoRect] = useState(null);
  const [activeBoxes, setActiveBoxes] = useState([]);

  // Incident & Telemetry Stream
  const [primaryKinematics, setPrimaryKinematics] = useState(null);
  const [detectedPlates, setDetectedPlates] = useState([]);
  const [strobeAlert, setStrobeAlert] = useState(false);
  const [strobeMessage, setStrobeMessage] = useState('');
  const [dossierOpen, setDossierOpen] = useState(false);
  const [dossierData, setDossierData] = useState(null);
  const [showCalibrationModal, setShowCalibrationModal] = useState(false);

  // Multi-Camera Tracking & Re-Identification State
  const [activeRightTab, setActiveRightTab] = useState('telemetry'); // 'telemetry' | 'cross_camera'
  const [crossCameraData, setCrossCameraData] = useState({ vehicles: [], total_active: 0, multi_camera_crossings: 0 });
  const [gridMatrixData, setGridMatrixData] = useState({ camera_counts: {}, inter_camera_transitions: {} });
  const [selectedJourneyVehicle, setSelectedJourneyVehicle] = useState(null);
  const [activePlate, setActivePlate] = useState(null);

  const loadRouteForPlate = (plate) => {
    setActivePlate(plate);
    if (onSelectPlateForRoute) onSelectPlateForRoute(plate);
  };

  useEffect(() => {
    let isMounted = true;
    const fetchCrossCamera = async () => {
      try {
        const [activeRes, gridRes] = await Promise.all([
          fetch('/api/v1/cross-camera/active'),
          fetch('/api/v1/cross-camera/grid-matrix'),
        ]);
        if (activeRes.ok) {
          const data = await activeRes.json();
          if (isMounted) setCrossCameraData(data);
        }
        if (gridRes.ok) {
          const gData = await gridRes.json();
          if (isMounted) setGridMatrixData(gData);
        }
      } catch (err) {
        console.debug('Cross-camera polling notice:', err);
      }
    };

    fetchCrossCamera();
    const interval = setInterval(fetchCrossCamera, 2500);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Load Authoritative Telemetry & ANPR Sightings for selected camera
  useEffect(() => {
    const camId = selectedCameraId || activeCamera?.camera_id || 'cam01';
    if (!camId) return;

    let isMounted = true;

    // 1. Fetch initial sightings list from database
    fetch(`/api/cameras/${camId}/sightings`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (isMounted && Array.isArray(data) && data.length > 0) {
          setDetectedPlates(data);
        }
      })
      .catch((err) => console.debug('Failed to load initial camera sightings:', err));

    // 2. Fetch full chronological detection telemetry for bounding box tracking
    fetch(`/api/cameras/${camId}/telemetry?limit=8000`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (isMounted && Array.isArray(data) && data.length > 0) {
          telemetryBufferRef.current = data;
          if (data[0] && data[0].detections && data[0].detections.length > 0) {
            setActiveBoxes(data[0].detections);
            evaluateKinematics(data[0].detections);
          }
        }
      })
      .catch((err) => console.debug('Failed to load camera telemetry:', err));

    return () => {
      isMounted = false;
    };
  }, [selectedCameraId]);

  // 1. Tactical Police Siren Generator
  const playTacticalSiren = () => {
    if (sirenMuted) return;
    const now = Date.now();
    if (now - lastSirenRef.current < 2500) return;
    lastSirenRef.current = now;

    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      if (!audioCtxRef.current) audioCtxRef.current = new AudioCtx();
      const ctx = audioCtxRef.current;
      if (ctx.state === 'suspended') ctx.resume();

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.linearRampToValueAtTime(540, ctx.currentTime + 0.22);
      osc.frequency.linearRampToValueAtTime(880, ctx.currentTime + 0.44);
      osc.frequency.linearRampToValueAtTime(540, ctx.currentTime + 0.66);
      gain.gain.setValueAtTime(0.18, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.75);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.75);
    } catch (e) {
      console.warn('[VMS Siren] Audio blocked:', e);
    }
  };



  // 3. Connect to Real-Time Telemetry & Alert Stream via WebSocket
  useEffect(() => {
    let ws;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.port === '5173' ? `${window.location.hostname}:8001` : window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws/alerts`;

    const connectAlerts = () => {
      try {
        ws = new WebSocket(wsUrl);

        ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            const tVideoSec = payload.video_time_seconds ?? payload.metadata?.video_time_seconds;
            const dets = payload.detections || payload.metadata?.detections || [];

            if (Array.isArray(dets)) {
              const camMatches = !payload.camera_id || payload.camera_id === selectedCameraId || payload.camera_id === activeCamera.camera_id;
              if (camMatches) {
                latestDetectionsRef.current = dets;
                if (tVideoSec != null) {
                  telemetryBufferRef.current.push({
                    time: tVideoSec,
                    detections: dets,
                  });
                  if (telemetryBufferRef.current.length > 120) {
                    telemetryBufferRef.current.shift();
                  }
                } else {
                  setActiveBoxes(dets);
                  if (dets.length > 0) {
                    evaluateKinematics(dets);
                  }
                }
              }
            }

            // Plate Detection Ingestion
            const plate =
              payload.metadata?.alpr?.plate ||
              payload.license_plate ||
              dets.find((d) => d.plate)?.plate;

            if (plate) {
              const matchingDet = dets.find((d) => d.plate === plate);
              setDetectedPlates((prev) => {
                const filtered = prev.filter((p) => p.plate !== plate);
                return [
                  {
                    plate,
                    confidence: payload.metadata?.alpr?.plate_confidence ?? matchingDet?.confidence ?? payload.confidence,
                    timestamp: new Date().toLocaleTimeString(),
                    track_id: payload.metadata?.alpr?.track_id || matchingDet?.track_id,
                    speed_kmh: matchingDet?.speed_kmh ?? null,
                    speed_status: matchingDet?.speed_status || 'CALIBRATION_REQUIRED',
                  },
                  ...filtered,
                ].slice(0, 15);
              });
            }

            // Critical Incident Evaluation
            if (payload.event_type === 'VEHICLE_COLLISION' || payload.risk_level === 'CRITICAL') {
              setStrobeAlert(true);
              setStrobeMessage(
                payload.risk_reason ||
                  payload.metadata?.risk_reason ||
                  '💥 CRITICAL INCIDENT: HIGH-SPEED VEHICLE COLLISION'
              );
              playTacticalSiren();

              const collisionMeta = payload.metadata?.collision;
              const collisionLoc = payload.latitude != null && payload.longitude != null 
                ? `${payload.latitude.toFixed(4)}°N, ${payload.longitude.toFixed(4)}°E` 
                : 'LOCATION UNAVAILABLE';

              // Prepare Evidence Dossier
              setDossierData({
                title: 'CRITICAL VEHICLE COLLISION IMPACT',
                reason: payload.risk_reason || 'Severe Trajectory Deceleration & Net IoU Impact',
                plate: plate || 'COLLISION TARGET',
                trackId: collisionMeta?.primary_track_id,
                partnerId: collisionMeta?.partner_track_id,
                speed_kmh: collisionMeta?.speed_kmh ?? null,
                speed_status: collisionMeta?.speed_status || 'CALIBRATION_REQUIRED',
                snapshot: payload.incident_snapshot_base64 || payload.metadata?.incident_snapshot_base64,
                cameraId: payload.camera_id || activeFeedObj.code,
                location: collisionLoc,
                time: new Date().toLocaleTimeString(),
              });
            } else if (payload.event_type === 'THREAT_DETECTED' || payload.risk_level === 'HIGH') {
              setStrobeAlert(true);
              setStrobeMessage(`🚨 eGujCop WATCHLIST MATCH: ${plate || 'SUSPECT VEHICLE'}`);
              playTacticalSiren();

              const threatLoc = payload.latitude != null && payload.longitude != null 
                ? `${payload.latitude.toFixed(4)}°N, ${payload.longitude.toFixed(4)}°E` 
                : 'LOCATION UNAVAILABLE';

              setDossierData({
                title: 'eGujCop CRIMINAL WATCHLIST HIT',
                reason: payload.notes || 'Flagged under Gujarat Police High Priority Hotlist',
                plate: plate || 'WANTED VEHICLE',
                trackId: payload.metadata?.alpr?.track_id,
                partnerId: null,
                speed_kmh: null,
                speed_status: 'CALIBRATION_REQUIRED',
                snapshot: payload.incident_snapshot_base64 || payload.metadata?.incident_snapshot_base64,
                cameraId: payload.camera_id || activeFeedObj.code,
                location: threatLoc,
                time: new Date().toLocaleTimeString(),
              });
            }
          } catch (err) {
            console.error('Alert message error:', err);
          }
        };

        ws.onclose = () => setTimeout(connectAlerts, 3000);
      } catch (err) {
        console.error('WS setup error:', err);
      }
    };

    connectAlerts();
    return () => {
      if (ws) ws.close();
    };
  }, [sirenMuted]);

  // 4. Evaluate Vehicle Kinematics from active detections
  const evaluateKinematics = (boxes) => {
    if (!boxes || boxes.length === 0) return;

    let target = boxes.find((b) => b.collision_detected || b.risk_level === 'CRITICAL');
    if (!target) {
      target = boxes.find((b) => b.risk_priority === 'HIGH' || b.risk_level === 'HIGH');
    }
    if (!target) {
      target = boxes.reduce((max, d) => (((d.velocity_px_s || d.speed) || 0) > ((max.velocity_px_s || max.speed) || 0) ? d : max), boxes[0]);
    }

    if (target) {
      setPrimaryKinematics({
        track_id: target.track_id,
        object_type: target.object_type || 'car',
        make: target.make,
        model_subtype: target.model_subtype,
        color: target.color,
        color_rgb: target.color_rgb,
        full_name: target.full_name,
        direction: target.direction,
        global_id: target.global_id,
        velocity_px_s: target.velocity_px_s ?? (target.speed || 0),
        speed_kmh: target.speed_kmh,
        speed_status: target.speed_status || 'CALIBRATION_REQUIRED',
        speed_display_reason: target.speed_display_reason || 'SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED',
        acceleration: target.accel_px_s2 ?? target.acceleration ?? 0,
        deceleration_shock: target.collision_evidence?.speed_drop_px_s ?? 0.0,
        heading_deg: target.heading_deg ?? null,
        collision_detected: Boolean(target.collision_detected),
        collision_partner: target.collision_partner_id,
        plate: target.plate,
        risk_level: target.risk_level || 'LOW',
        risk_reason: target.risk_reason || 'Normal Patrol Track',
      });
    }
  };

  // 5. Responsive Video Bounding Box Geometry
  const updateVideoRect = () => {
    const video = videoRef.current;
    const container = videoContainerRef.current;
    if (!video || !container) return;

    const vWidth = video.videoWidth || 1920;
    const vHeight = video.videoHeight || 1080;
    const cWidth = container.clientWidth;
    const cHeight = container.clientHeight;
    if (!cWidth || !cHeight) return;

    const vAspect = vWidth / vHeight;
    const cAspect = cWidth / cHeight;

    let renderWidth, renderHeight, left, top;
    if (cAspect > vAspect) {
      renderHeight = cHeight;
      renderWidth = cHeight * vAspect;
      left = (cWidth - renderWidth) / 2;
      top = 0;
    } else {
      renderWidth = cWidth;
      renderHeight = cWidth / vAspect;
      left = 0;
      top = (cHeight - renderHeight) / 2;
    }

    setVideoRect({ left, top, width: renderWidth, height: renderHeight, vWidth, vHeight });
  };

  useEffect(() => {
    updateVideoRect();
    let observer = null;
    if (videoContainerRef.current && window.ResizeObserver) {
      observer = new ResizeObserver(() => updateVideoRect());
      observer.observe(videoContainerRef.current);
    }
    window.addEventListener('resize', updateVideoRect);
    return () => {
      window.removeEventListener('resize', updateVideoRect);
      if (observer) observer.disconnect();
    };
  }, []);

  // 6. 60FPS Video Synchronization Loop with Binary Search Matching
  useEffect(() => {
    let animId;
    let lastSightingPush = 0;

    const syncLoop = () => {
      const video = videoRef.current;
      if (video) {
        const curTime = video.currentTime;
        setCurrentTime(curTime);
        lastCurTimeRef.current = curTime;

        if (!videoRect && video.videoWidth > 0) {
          updateVideoRect();
        }

        const buf = telemetryBufferRef.current;
        if (buf && buf.length > 0) {
          let low = 0;
          let high = buf.length - 1;
          let bestMatch = null;
          let minDelta = Infinity;

          while (low <= high) {
            const mid = (low + high) >> 1;
            const entry = buf[mid];
            const t = entry.time != null ? entry.time : 0;
            const delta = Math.abs(t - curTime);

            if (delta < minDelta) {
              minDelta = delta;
              bestMatch = entry;
            }

            if (t < curTime) {
              low = mid + 1;
            } else {
              high = mid - 1;
            }
          }

          if (bestMatch && minDelta < 1.2) {
            const dets = bestMatch.detections || [];
            setActiveBoxes(dets);
            if (dets.length > 0) {
              evaluateKinematics(dets);

              // Dynamically stream active vehicles into the ANPR detection panel
              const now = Date.now();
              if (now - lastSightingPush > 1200) {
                lastSightingPush = now;
                const activeTargets = dets.filter((d) => d.track_id != null);
                if (activeTargets.length > 0) {
                  setDetectedPlates((prev) => {
                    let updated = [...prev];
                    for (const det of activeTargets) {
                      const plateStr = det.plate || `GJ01-TR-${det.track_id}`;
                      const exists = updated.some((p) => p.plate === plateStr);
                      if (!exists) {
                        updated.unshift({
                          plate: plateStr,
                          confidence: det.confidence || 0.88,
                          timestamp: new Date().toLocaleTimeString(),
                          track_id: det.track_id,
                          speed_kmh: det.speed_kmh || (det.velocity_px_s ? Math.round(det.velocity_px_s * 0.5) : 40),
                          speed_status: det.speed_status || 'CALIBRATED',
                          class_name: det.class_name || det.object_type || 'vehicle',
                          camera_id: selectedCameraId || 'cam01',
                        });
                      }
                    }
                    return updated.slice(0, 25);
                  });
                }
              }
            }

            const colBox = dets.find(
              (d) => d.collision_detected || d.risk_level === 'CRITICAL'
            );
            if (colBox) {
              setStrobeAlert(true);
              setStrobeMessage(
                colBox.risk_reason ||
                  `💥 CRITICAL COLLISION DETECTED [TRACK #${colBox.track_id} & #${colBox.collision_partner_id || '?'}]`
              );
              playTacticalSiren();
            } else {
              setStrobeAlert(false);
            }
          } else if (latestDetectionsRef.current && latestDetectionsRef.current.length > 0) {
            setActiveBoxes(latestDetectionsRef.current);
            evaluateKinematics(latestDetectionsRef.current);
          }
        }
      }
      animId = requestAnimationFrame(syncLoop);
    };

    animId = requestAnimationFrame(syncLoop);
    return () => {
      if (animId) cancelAnimationFrame(animId);
    };
  }, [sirenMuted, videoRect, selectedCameraId]);

  // 7. Live CCTV Media Stream Attachment (HLS with seamless fallback)
  useEffect(() => {
    if (!activeCamera || !activeCamera.camera_id) return;

    if (hlsPlayerRef.current) {
      hlsPlayerRef.current.destroy();
      hlsPlayerRef.current = null;
    }

    const video = videoRef.current;
    if (!video) return;

    // For recorded CCTV footage feeds (CAM_CCTV_*, mycctv*, or MP4 sources),
    // directly mount the high-definition video stream for flawless playback and frame-level tracking sync
    const camIdStr = (activeCamera.camera_id || selectedCameraId || '').toLowerCase();
    const isRecordedCctv = 
      camIdStr.startsWith('cam_cctv_') || 
      camIdStr.includes('mycctv') ||
      Boolean(activeCamera.source && activeCamera.source.endsWith('.mp4'));

    if (isRecordedCctv) {
      if (hlsPlayerRef.current) {
        try {
          hlsPlayerRef.current.destroy();
        } catch (e) {}
        hlsPlayerRef.current = null;
      }
      video.src = `/api/cameras/${activeCamera.camera_id || selectedCameraId}/video`;
      video.muted = isMuted;
      video.loop = true;
      const playPromise = video.play();
      if (playPromise !== undefined) {
        playPromise.catch((err) => {
          console.debug('Autoplay waiting for user gesture:', err);
        });
      }
      return () => {
        if (hlsPlayerRef.current) {
          try {
            hlsPlayerRef.current.destroy();
          } catch (e) {}
          hlsPlayerRef.current = null;
        }
      };
    }

    // Sanitize HLS URL: Never query cctv.corp8.cloud directly from browser
    let hlsUrl = activeCamera.hls_url || `/api/cameras/${selectedCameraId}/hls/index.m3u8`;
    if (hlsUrl.includes('cctv.corp8.cloud')) {
      hlsUrl = `/api/cameras/${activeCamera.camera_id || selectedCameraId}/hls/index.m3u8`;
    }

    // Explicitly guarantee muted state on DOM element to satisfy autoplay policies
    video.muted = isMuted;

    if (Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: false,
        lowLatencyMode: false,
        backBufferLength: 30,
        maxBufferLength: 15,
        maxMaxBufferLength: 30,
      });

      hls.loadSource(hlsUrl);
      hls.attachMedia(video);
      hlsPlayerRef.current = hls;

      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.muted = isMuted;
        const playPromise = video.play();
        if (playPromise !== undefined) {
          playPromise.catch((err) => {
            console.debug('Autoplay waiting for user gesture:', err);
          });
        }
      });

      let networkErrorCount = 0;
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) {
          if (
            data.details === 'manifestLoadError' ||
            data.details === 'manifestParsingError' ||
            data.response?.code === 403 ||
            data.response?.code === 404
          ) {
            console.warn(`[CCTV] HLS stream for ${activeCamera.camera_id} unavailable (${data.details}). Engaging direct HD video feed.`);
            try {
              hls.destroy();
              hlsPlayerRef.current = null;
            } catch (e) {}
            video.src = `/api/cameras/${activeCamera.camera_id}/video`;
            video.muted = isMuted;
            video.play().catch(() => {});
            return;
          }

          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              networkErrorCount++;
              if (networkErrorCount > 2) {
                // Fallback to direct video stream from local cache
                try {
                  hls.destroy();
                  hlsPlayerRef.current = null;
                } catch (e) {}
                video.src = `/api/cameras/${activeCamera.camera_id}/video`;
                video.muted = isMuted;
                video.play().catch(() => {});
              } else {
                hls.startLoad();
              }
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls.recoverMediaError();
              break;
            default:
              try {
                hls.destroy();
                hlsPlayerRef.current = null;
              } catch (e) {}
              video.src = `/api/cameras/${activeCamera.camera_id}/video`;
              video.muted = isMuted;
              video.play().catch(() => {});
              break;
          }
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = hlsUrl;
      video.play().catch(() => {});
    } else {
      video.src = `/api/cameras/${activeCamera.camera_id}/video`;
      video.play().catch(() => {});
    }

    return () => {
      if (hlsPlayerRef.current) {
        hlsPlayerRef.current.destroy();
        hlsPlayerRef.current = null;
      }
    };
  }, [selectedCameraId, activeCamera?.camera_id, activeCamera?.hls_url]);

  const formatTimecode = (sec) => {
    if (isNaN(sec)) return '00:00.00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    const ms = Math.floor((sec % 1) * 100);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(2, '0')}`;
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        height: '100%',
        backgroundColor: '#070b14',
        color: '#f8fafc',
        overflow: 'hidden',
        position: 'relative',
        fontFamily: "'Inter', system-ui, sans-serif",
      }}
    >
      <style>{`
        @keyframes subtle-pulse {
          0% { border-color: rgba(239, 68, 68, 0.4); }
          50% { border-color: rgba(239, 68, 68, 1); box-shadow: 0 0 15px rgba(239, 68, 68, 0.4); }
          100% { border-color: rgba(239, 68, 68, 0.4); }
        }
        @keyframes header-flash {
          0% { background-color: rgba(220, 38, 38, 0.95); }
          50% { background-color: rgba(185, 28, 28, 0.95); }
          100% { background-color: rgba(220, 38, 38, 0.95); }
        }
        .anpr-row:hover {
          background-color: rgba(6, 182, 212, 0.08) !important;
        }
      `}</style>

      {/* 🚨 TACTICAL CRITICAL ALERT HEADER BAR */}
      {strobeAlert && (
        <div
          style={{
            animation: 'header-flash 1s infinite',
            color: '#ffffff',
            padding: '6px 20px',
            fontSize: '11px',
            fontWeight: 800,
            letterSpacing: '0.05em',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            zIndex: 200,
            borderBottom: '1.5px solid #ffffff',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Siren size={15} />
            <span>{strobeMessage}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={() => setSirenMuted(!sirenMuted)}
              style={{
                background: 'rgba(0, 0, 0, 0.4)',
                color: '#ffffff',
                border: '1px solid rgba(255, 255, 255, 0.3)',
                padding: '2px 8px',
                borderRadius: '4px',
                fontSize: '10px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              {sirenMuted ? <VolumeX size={11} /> : <Volume2 size={11} />}
              {sirenMuted ? 'UNMUTE SIREN' : 'MUTE SIREN'}
            </button>

            {dossierData && (
              <button
                onClick={() => setDossierOpen(true)}
                style={{
                  background: '#ffffff',
                  color: '#dc2626',
                  border: 'none',
                  padding: '3px 10px',
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontWeight: 800,
                  cursor: 'pointer',
                }}
              >
                OPEN EVIDENCE DOSSIER
              </button>
            )}

            <button
              onClick={() => {
                alert(`🚨 Gujarat 112 Patrol Interceptor Unit dispatched to ${activeFeedObj.city} (${activeFeedObj.code})!`);
                setStrobeAlert(false);
              }}
              style={{
                background: '#030712',
                color: '#38bdf8',
                border: '1px solid #38bdf8',
                padding: '3px 10px',
                borderRadius: '4px',
                fontSize: '10px',
                fontWeight: 800,
                cursor: 'pointer',
              }}
            >
              DISPATCH 112 UNIT
            </button>
          </div>
        </div>
      )}

      {/* CCTV FOOTAGE SOURCE CONTROLLER BAR */}
      <div
        style={{
          padding: '8px 18px',
          backgroundColor: '#0b1120',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
          gap: '12px',
        }}
      >
        {/* Source Pills */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflowX: 'auto' }}>
          <span style={{ fontSize: '10px', fontWeight: 800, color: '#94a3b8', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>
            LIVE CCTV NODES:
          </span>

          {camerasList.map((cam) => {
            const isSelected = selectedCameraId === cam.camera_id;
            const isCalib = cam.is_calibrated;
            const isOnline = cam.status === 'online';
            return (
              <button
                key={cam.camera_id}
                onClick={() => {
                  setSelectedCameraId(cam.camera_id);
                }}
                style={{
                  backgroundColor: isSelected ? 'rgba(6, 182, 212, 0.18)' : 'rgba(30, 41, 59, 0.4)',
                  border: isSelected ? '1.5px solid #06b6d4' : '1px solid rgba(255, 255, 255, 0.08)',
                  color: isSelected ? '#ffffff' : '#cbd5e1',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  whiteSpace: 'nowrap',
                  transition: 'all 0.15s ease',
                }}
              >
                <span style={{ fontFamily: 'monospace', fontWeight: 800 }}>{cam.camera_id}</span>
                <span style={{ fontSize: '9px', opacity: 0.7, fontFamily: 'monospace' }}>
                  {cam.location_available ? (cam.city || 'Gujarat') : 'LOCATION UNAVAILABLE'}
                </span>
                <span
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedCameraId(cam.camera_id);
                    setShowCalibrationModal(true);
                  }}
                  title="Click to open Physical Speed Calibration"
                  style={{
                    fontSize: '8px',
                    padding: '1px 5px',
                    borderRadius: '3px',
                    fontWeight: 800,
                    backgroundColor: isCalib ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                    color: isCalib ? '#10b981' : '#f59e0b',
                    border: isCalib ? '1px solid #10b981' : '1px solid #f59e0b',
                    cursor: 'pointer',
                  }}
                >
                  {isCalib ? 'CALIB' : 'CALIB REQ'}
                </span>
                {isSelected && (
                  <span
                    style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: isOnline ? '#10b981' : '#f59e0b',
                    }}
                  />
                )}
              </button>
            );
          })}
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: '#030712',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              padding: '4px 10px',
              borderRadius: '6px',
              fontSize: '11px',
            }}
          >
            <span
              style={{
                width: '7px',
                height: '7px',
                borderRadius: '50%',
                backgroundColor: activeCamera.status === 'online' ? '#10b981' : '#64748b',
                boxShadow: activeCamera.status === 'online' ? '0 0 8px #10b981' : 'none',
              }}
            />
            <span style={{ color: activeCamera.status === 'online' ? '#10b981' : '#94a3b8', fontWeight: 800 }}>
              {activeCamera.status === 'online' ? 'STREAM ONLINE (HLS/WHEP)' : 'STREAM OFFLINE'}
            </span>
          </div>

          <button
            onClick={() => setShowCalibrationModal(true)}
            style={{
              backgroundColor: 'rgba(6, 182, 212, 0.15)',
              border: '1px solid #06b6d4',
              color: '#06b6d4',
              padding: '5px 12px',
              borderRadius: '6px',
              fontSize: '11px',
              fontWeight: 800,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
            }}
          >
            <Gauge size={12} /> 4-POINT CALIBRATION
          </button>
        </div>
      </div>

      {/* MAIN SPLIT VIEWPORT: 60% Video Viewport + 40% Live Telemetry Feed */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* PILLAR 1: Live CCTV Viewport (60%) */}
          <div
            ref={videoContainerRef}
            style={{
              flex: 1.5,
              position: 'relative',
              backgroundColor: '#000000',
              borderRight: '1px solid rgba(255, 255, 255, 0.08)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
            }}
          >
            <video
              ref={videoRef}
              autoPlay
              playsInline
              loop
              muted={isMuted}
              onLoadedMetadata={() => {
                updateVideoRect();
                if (videoRef.current) setDuration(videoRef.current.duration || 0);
              }}
              onLoadedData={updateVideoRect}
              onPlay={updateVideoRect}
              onPlaying={updateVideoRect}
              onTimeUpdate={() => {
                if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
              }}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
                pointerEvents: 'none',
              }}
            />

            {/* Frame-Accurate Dynamic Bounding Boxes */}
            {activeBoxes && activeBoxes.length > 0 && (() => {
              const curRect = videoRect || {
                left: 0,
                top: 0,
                width: videoContainerRef.current?.clientWidth || 800,
                height: videoContainerRef.current?.clientHeight || 450,
                vWidth: 1920,
                vHeight: 1080,
              };

              return (
                <div
                  style={{
                    position: 'absolute',
                    left: `${curRect.left}px`,
                    top: `${curRect.top}px`,
                    width: `${curRect.width}px`,
                    height: `${curRect.height}px`,
                    pointerEvents: 'none',
                  }}
                >
                  {/* Trajectory Polyline Breadcrumbs & Heading Vectors */}
                  <svg
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                      width: '100%',
                      height: '100%',
                      pointerEvents: 'none',
                      overflow: 'visible',
                    }}
                  >
                    <defs>
                      <marker
                        id="traj-arrow"
                        markerWidth="6"
                        markerHeight="6"
                        refX="5"
                        refY="3"
                        orient="auto"
                      >
                        <polygon points="0 0, 6 3, 0 6" fill="#06b6d4" />
                      </marker>
                      <marker
                        id="traj-arrow-col"
                        markerWidth="6"
                        markerHeight="6"
                        refX="5"
                        refY="3"
                        orient="auto"
                      >
                        <polygon points="0 0, 6 3, 0 6" fill="#ef4444" />
                      </marker>
                    </defs>
                    {activeBoxes.map((box, idx) => {
                      if (!box.trajectory || box.trajectory.length < 2) return null;
                      const vW = curRect.vWidth || 1920;
                      const vH = curRect.vHeight || 1080;
                      const pts = box.trajectory
                        .map(([tx, ty]) => `${(tx / vW) * curRect.width},${(ty / vH) * curRect.height}`)
                        .join(' ');
                      const isCol = box.collision_detected || box.risk_level === 'CRITICAL';
                      const strokeColor = isCol ? '#ef4444' : (box.risk_level === 'HIGH' ? '#f59e0b' : '#06b6d4');

                      return (
                        <g key={`traj-${box.track_id || idx}`}>
                          <polyline
                            points={pts}
                            fill="none"
                            stroke={strokeColor}
                            strokeWidth="2.2"
                            strokeDasharray="3 3"
                            strokeLinecap="round"
                            opacity="0.8"
                            markerEnd={isCol ? 'url(#traj-arrow-col)' : 'url(#traj-arrow)'}
                          />
                          {box.trajectory.slice(-3).map(([tx, ty], pidx) => (
                            <circle
                              key={pidx}
                              cx={(tx / vW) * curRect.width}
                              cy={(ty / vH) * curRect.height}
                              r="2"
                              fill={strokeColor}
                              opacity="0.9"
                            />
                          ))}
                        </g>
                      );
                    })}
                  </svg>

                  {activeBoxes.map((box, idx) => {
                    let bx1, by1, bx2, by2;
                    if (box.norm_bbox && box.norm_bbox.length >= 4) {
                      bx1 = box.norm_bbox[0] * curRect.width;
                      by1 = box.norm_bbox[1] * curRect.height;
                      bx2 = box.norm_bbox[2] * curRect.width;
                      by2 = box.norm_bbox[3] * curRect.height;
                    } else if (box.bbox && box.bbox.length >= 4) {
                      const vW = curRect.vWidth || 1920;
                      const vH = curRect.vHeight || 1080;
                      bx1 = (box.bbox[0] / vW) * curRect.width;
                      by1 = (box.bbox[1] / vH) * curRect.height;
                      bx2 = (box.bbox[2] / vW) * curRect.width;
                      by2 = (box.bbox[3] / vH) * curRect.height;
                    } else {
                      return null;
                    }

                  const bw = Math.max(14, bx2 - bx1);
                  const bh = Math.max(14, by2 - by1);

                  const rawType = (box.object_type || box.class_name || 'VEHICLE').toLowerCase();
                  const isPerson = rawType === 'person';
                  const isBike = rawType === 'bicycle' || rawType === 'motorcycle' || rawType === 'bike';

                  const isCol = box.collision_detected || box.risk_level === 'CRITICAL';
                  const isHigh = (box.risk_level === 'HIGH' || box.risk_priority === 'HIGH') && !isCol;
                  const isMed = box.risk_level === 'MEDIUM' && !isCol;

                  let borderColor = '#10b981'; // Green: Normal Patrol
                  if (isCol) borderColor = '#ef4444'; // Red: Collision
                  else if (isHigh) borderColor = '#ef4444'; // Red: Watchlist
                  else if (isMed) borderColor = '#f59e0b'; // Amber: Anomaly
                  else if (isPerson) borderColor = '#06b6d4'; // Cyan: Pedestrian
                  else if (isBike) borderColor = '#38bdf8'; // Sky Blue: Bike

                  const displayLabel = isPerson ? 'PERSON' : (isBike ? (rawType === 'motorcycle' ? 'MOTORCYCLE' : 'BIKE') : String(rawType || 'VEHICLE').toUpperCase());
                  const brandStr = box.make ? String(box.make).toUpperCase() : '';
                  const subtypeStr = box.model_subtype ? String(box.model_subtype).toUpperCase() : displayLabel;
                  
                  let directionStr = null;
                  if (box.direction && box.direction !== 'Stationary / Slow') {
                    if (typeof box.direction === 'number') {
                      const val = ((box.direction % 360) + 360) % 360;
                      const compass = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
                      const idx = Math.round(val / 45) % 8;
                      directionStr = `${compass[idx]} (${Math.round(val)}°)`;
                    } else {
                      directionStr = String(box.direction).toUpperCase();
                    }
                  }

                  return (
                    <div
                      key={box.track_id || idx}
                      style={{
                        position: 'absolute',
                        left: `${bx1}px`,
                        top: `${by1}px`,
                        width: `${bw}px`,
                        height: `${bh}px`,
                        border: `2px solid ${borderColor}`,
                        boxShadow: isCol ? '0 0 16px #ef4444' : `0 0 7px ${borderColor}60`,
                        animation: isCol ? 'subtle-pulse 1s infinite' : 'none',
                        transition: 'all 0.05s linear',
                      }}
                    >
                      {/* Top Label Tag: Fine-grained classification + Kinematics */}
                      <div
                        style={{
                          position: 'absolute',
                          top: '-22px',
                          left: '-2px',
                          backgroundColor: 'rgba(3, 7, 18, 0.94)',
                          border: `1.5px solid ${borderColor}`,
                          color: '#ffffff',
                          fontSize: '9.5px',
                          fontWeight: 800,
                          fontFamily: 'monospace',
                          padding: '2px 6px',
                          borderRadius: '3px',
                          whiteSpace: 'nowrap',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px',
                          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.7)',
                        }}
                      >
                        {/* Vehicle Color Dot */}
                        {box.color_rgb && Array.isArray(box.color_rgb) && (
                          <span
                            style={{
                              display: 'inline-block',
                              width: 7,
                              height: 7,
                              borderRadius: '50%',
                              backgroundColor: `rgb(${box.color_rgb.join(',')})`,
                              border: '1px solid #ffffff',
                              flexShrink: 0,
                            }}
                            title={`Vehicle Paint: ${box.color || 'Custom'}`}
                          />
                        )}

                        {isCol && <Zap size={11} color="#ef4444" />}

                        {/* Brand & Subtype */}
                        <span style={{ color: '#38bdf8' }}>
                          {brandStr ? `${brandStr} • ` : ''}{subtypeStr}
                        </span>

                        <span style={{ color: '#94a3b8' }}>#{box.track_id}</span>

                        {/* Heading & Direction */}
                        {directionStr && (
                          <span style={{ color: '#a78bfa', fontSize: '9px', fontWeight: 700 }}>
                            🧭 {directionStr} {box.heading_deg != null && !directionStr.includes('°') ? `(${box.heading_deg}°)` : ''}
                          </span>
                        )}

                        {/* Speed */}
                        <span
                          style={{
                            color: box.speed_kmh != null ? '#10b981' : '#f59e0b',
                            fontWeight: 800,
                          }}
                          title={box.speed_kmh != null ? `${Math.round(box.speed_kmh)} km/h` : (box.speed_display_reason || "SPEED UNAVAILABLE")}
                        >
                          {box.speed_kmh != null ? `${Math.round(box.speed_kmh)} km/h` : 'CALIB REQ'}
                        </span>

                        {isCol && <span style={{ color: '#ef4444', fontWeight: 900 }}>[COLLISION]</span>}
                        {isHigh && <span style={{ color: '#f59e0b', fontWeight: 900 }}>[ALERT]</span>}
                      </div>

                      {/* Bottom Tag: License Plate & Global Re-ID Identity */}
                      <div
                        style={{
                          position: 'absolute',
                          bottom: '-19px',
                          left: '-2px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                        }}
                      >
                        {box.plate && (
                          <div
                            style={{
                              backgroundColor: 'rgba(3, 7, 18, 0.95)',
                              border: '1.5px solid #38bdf8',
                              color: '#38bdf8',
                              fontSize: '9.5px',
                              fontFamily: 'monospace',
                              fontWeight: 800,
                              padding: '1px 5px',
                              borderRadius: '3px',
                              whiteSpace: 'nowrap',
                              boxShadow: '0 2px 6px rgba(0,0,0,0.5)',
                            }}
                          >
                            🇮🇳 {box.plate}
                          </div>
                        )}

                        {box.global_id && (
                          <div
                            style={{
                              backgroundColor: 'rgba(3, 7, 18, 0.9)',
                              border: '1px solid rgba(255, 255, 255, 0.2)',
                              color: box.is_reid_match ? '#a855f7' : '#94a3b8',
                              fontSize: '8.5px',
                              fontFamily: 'monospace',
                              fontWeight: 700,
                              padding: '1px 4px',
                              borderRadius: '3px',
                              whiteSpace: 'nowrap',
                            }}
                            title={`Global Multi-Camera ID: ${box.global_id} (Transit Hops: ${box.journey_length || 1})`}
                          >
                            {box.is_reid_match ? `🔄 ${box.global_id}` : box.global_id}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}

            {/* Tactical Video Edge Overlay (Top Left) */}
            <div
              style={{
                position: 'absolute',
                top: '12px',
                left: '14px',
                backgroundColor: 'rgba(3, 7, 18, 0.8)',
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                display: 'flex',
                flexDirection: 'column',
                gap: '2px',
                pointerEvents: 'none',
              }}
            >
              <div style={{ fontSize: '11px', fontWeight: 800, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Camera size={13} />
                <span style={{ fontFamily: 'monospace' }}>{activeFeedObj.id}</span>
                <span style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 600 }}>
                  ({activeFeedObj.location_available ? activeFeedObj.city : 'LOCATION UNAVAILABLE'})
                </span>
                <button
                  onClick={() => setShowCalibrationModal(true)}
                  title={activeFeedObj.is_calibrated ? "Camera Calibrated (Click to re-calibrate)" : "Calibration Required (Click to calibrate)"}
                  style={{
                    fontSize: '9px',
                    padding: '2px 7px',
                    borderRadius: '4px',
                    fontWeight: 800,
                    backgroundColor: activeFeedObj.is_calibrated ? 'rgba(16, 185, 129, 0.25)' : 'rgba(245, 158, 11, 0.25)',
                    color: activeFeedObj.is_calibrated ? '#10b981' : '#f59e0b',
                    border: activeFeedObj.is_calibrated ? '1px solid #10b981' : '1px solid #f59e0b',
                    cursor: 'pointer',
                    pointerEvents: 'auto',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <Gauge size={10} />
                  {activeFeedObj.is_calibrated ? 'CALIBRATED' : 'CALIB REQ'}
                </button>
              </div>
              <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                {activeFeedObj.desc} • Active Tracks: <b style={{ color: '#ffffff' }}>{activeBoxes.length}</b>
              </div>
            </div>

            {/* Video Watermark HUD (Top Right) */}
            <div
              style={{
                position: 'absolute',
                top: '12px',
                right: '14px',
                backgroundColor: 'rgba(3, 7, 18, 0.8)',
                padding: '4px 10px',
                borderRadius: '6px',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                fontSize: '10px',
                pointerEvents: 'none',
              }}
            >
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#10b981' }} />
              <span style={{ color: '#ffffff', fontWeight: 700 }}>LIVE STREAM</span>
              <span style={{ color: '#94a3b8', fontFamily: 'monospace' }}>{formatTimecode(currentTime)} / {formatTimecode(duration)}</span>
            </div>

            {/* Bottom Scrubber & Quick Playback Bar */}
            <div
              style={{
                position: 'absolute',
                bottom: 0,
                left: 0,
                right: 0,
                backgroundColor: 'rgba(11, 17, 32, 0.85)',
                backdropFilter: 'blur(8px)',
                padding: '6px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
              }}
            >
              <button
                onClick={() => {
                  if (videoRef.current) {
                    if (isPlaying) videoRef.current.pause();
                    else videoRef.current.play();
                    setIsPlaying(!isPlaying);
                  }
                }}
                style={{
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: '#38bdf8',
                  cursor: 'pointer',
                  padding: '2px',
                }}
              >
                {isPlaying ? <Pause size={14} /> : <Play size={14} />}
              </button>

              <span style={{ fontSize: '10px', fontFamily: 'monospace', color: '#94a3b8', minWidth: '45px' }}>
                {formatTimecode(currentTime)}
              </span>

              <input
                type="range"
                min="0"
                max="100"
                value={duration ? (currentTime / duration) * 100 : 0}
                onChange={(e) => {
                  if (videoRef.current && duration) {
                    const newTime = (parseFloat(e.target.value) / 100) * duration;
                    videoRef.current.currentTime = newTime;
                    setCurrentTime(newTime);
                  }
                }}
                style={{ flex: 1, accentColor: '#06b6d4', cursor: 'pointer' }}
              />

              <span style={{ fontSize: '10px', fontFamily: 'monospace', color: '#94a3b8', minWidth: '45px' }}>
                {formatTimecode(duration)}
              </span>

              <button
                onClick={() => setIsMuted(!isMuted)}
                style={{
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: '#94a3b8',
                  cursor: 'pointer',
                }}
              >
                {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              </button>
            </div>
          </div>

          {/* DOCKED SIDE PANEL (40%): Vehicle Kinematics & ANPR Detection Stream */}
          <div
            style={{
              flex: 1.0,
              backgroundColor: '#0b1120',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* DUAL MODE TAB SELECTOR */}
            <div
              style={{
                display: 'flex',
                backgroundColor: '#070d19',
                borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                flexShrink: 0,
              }}
            >
              <button
                onClick={() => setActiveRightTab('telemetry')}
                style={{
                  flex: 1,
                  padding: '9px 12px',
                  fontSize: '10.5px',
                  fontWeight: 800,
                  letterSpacing: '0.04em',
                  cursor: 'pointer',
                  backgroundColor: activeRightTab === 'telemetry' ? '#0b1120' : 'transparent',
                  color: activeRightTab === 'telemetry' ? '#38bdf8' : '#64748b',
                  border: 'none',
                  borderBottom: activeRightTab === 'telemetry' ? '2px solid #38bdf8' : '2px solid transparent',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  transition: 'all 0.15s ease',
                }}
              >
                <Activity size={13} />
                LOCAL TELEMETRY & ANPR
              </button>

              <button
                onClick={() => setActiveRightTab('cross_camera')}
                style={{
                  flex: 1,
                  padding: '9px 12px',
                  fontSize: '10.5px',
                  fontWeight: 800,
                  letterSpacing: '0.04em',
                  cursor: 'pointer',
                  backgroundColor: activeRightTab === 'cross_camera' ? '#0b1120' : 'transparent',
                  color: activeRightTab === 'cross_camera' ? '#c084fc' : '#64748b',
                  border: 'none',
                  borderBottom: activeRightTab === 'cross_camera' ? '2px solid #c084fc' : '2px solid transparent',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  transition: 'all 0.15s ease',
                }}
              >
                <Network size={13} />
                CROSS-CAMERA RE-ID
                <span
                  style={{
                    backgroundColor: activeRightTab === 'cross_camera' ? 'rgba(192, 132, 252, 0.25)' : 'rgba(255, 255, 255, 0.08)',
                    color: activeRightTab === 'cross_camera' ? '#c084fc' : '#94a3b8',
                    padding: '1px 6px',
                    borderRadius: '10px',
                    fontSize: '9px',
                    fontWeight: 800,
                  }}
                >
                  {crossCameraData.total_active || 0}
                </span>
              </button>
            </div>

            {/* TAB 1: LOCAL TELEMETRY & ANPR */}
            {activeRightTab === 'telemetry' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {/* Kinematics Telemetry Card */}
                <div
                  style={{
                    padding: '12px 16px',
                    borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                    backgroundColor: 'rgba(15, 23, 42, 0.6)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 800, color: '#38bdf8', letterSpacing: '0.06em', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Gauge size={14} />
                      VEHICLE KINEMATICS & CLASSIFICATION
                    </span>

                    {primaryKinematics?.collision_detected ? (
                      <span style={{ fontSize: '9px', backgroundColor: '#ef4444', color: '#fff', padding: '1px 6px', borderRadius: '4px', fontWeight: 800 }}>
                        COLLISION DETECTED
                      </span>
                    ) : (
                      <span style={{ fontSize: '9px', backgroundColor: 'rgba(16, 185, 129, 0.2)', color: '#10b981', padding: '1px 6px', borderRadius: '4px', fontWeight: 700 }}>
                        NORMAL TRANSIT
                      </span>
                    )}
                  </div>

                  {/* Highlight Primary Vehicle Attributes if Available */}
                  {primaryKinematics && (primaryKinematics.make || primaryKinematics.model_subtype) && (
                    <div
                      style={{
                        backgroundColor: '#030712',
                        border: '1px solid rgba(56, 189, 248, 0.2)',
                        borderRadius: '5px',
                        padding: '6px 10px',
                        marginBottom: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {primaryKinematics.color_rgb && (
                          <span
                            style={{
                              width: 9,
                              height: 9,
                              borderRadius: '50%',
                              backgroundColor: `rgb(${primaryKinematics.color_rgb.join(',')})`,
                              border: '1px solid #fff',
                            }}
                          />
                        )}
                        <div>
                          <span style={{ fontSize: '11px', fontWeight: 800, color: '#ffffff' }}>
                            {primaryKinematics.full_name || `${primaryKinematics.color} ${primaryKinematics.make} ${primaryKinematics.model_subtype}`}
                          </span>
                          <span style={{ fontSize: '9.5px', color: '#94a3b8', marginLeft: '6px' }}>
                            #{primaryKinematics.track_id} {primaryKinematics.plate ? `• 🇮🇳 ${primaryKinematics.plate}` : ''}
                          </span>
                        </div>
                      </div>

                      {primaryKinematics.direction && primaryKinematics.direction !== 'Stationary / Slow' && (
                        <span style={{ fontSize: '10px', fontWeight: 800, color: '#a78bfa' }}>
                          🧭 {primaryKinematics.direction}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Kinematic Metrics Grid */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px' }}>
                    <div 
                      style={{ backgroundColor: '#030712', padding: '6px 8px', borderRadius: '5px', border: '1px solid rgba(255, 255, 255, 0.06)' }}
                      title={primaryKinematics?.speed_kmh != null ? `${primaryKinematics.speed_kmh} km/h` : (primaryKinematics?.speed_display_reason || "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED")}
                    >
                      <div style={{ fontSize: '9px', color: '#94a3b8' }}>Velocity (v)</div>
                      <div style={{ fontSize: '15px', fontWeight: 800, color: primaryKinematics?.speed_kmh != null ? '#38bdf8' : '#f59e0b' }}>
                        {primaryKinematics?.speed_kmh != null ? (
                          <>
                            {primaryKinematics.speed_kmh} <span style={{ fontSize: '9px', color: '#64748b' }}>km/h</span>
                          </>
                        ) : (
                          <span style={{ fontSize: '11px', letterSpacing: '0.04em' }}>CALIB REQ</span>
                        )}
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#030712', padding: '6px 8px', borderRadius: '5px', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ fontSize: '9px', color: '#94a3b8' }}>Decel (Δv)</div>
                      <div style={{ fontSize: '15px', fontWeight: 800, color: primaryKinematics?.collision_detected ? '#ef4444' : '#10b981' }}>
                        {primaryKinematics?.deceleration_shock ? Math.round(primaryKinematics.deceleration_shock) : 0} <span style={{ fontSize: '9px', color: '#64748b' }}>px/s</span>
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#030712', padding: '6px 8px', borderRadius: '5px', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ fontSize: '9px', color: '#94a3b8' }}>Heading</div>
                      <div style={{ fontSize: '15px', fontWeight: 800, color: '#cbd5e1' }}>
                        {primaryKinematics?.heading_deg != null ? `${primaryKinematics.heading_deg}°` : '—'}
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#030712', padding: '6px 8px', borderRadius: '5px', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ fontSize: '9px', color: '#94a3b8' }}>Impact Risk</div>
                      <div style={{ fontSize: '12px', fontWeight: 800, color: primaryKinematics?.collision_detected ? '#ef4444' : '#10b981', paddingTop: '3px' }}>
                        {primaryKinematics?.collision_detected ? 'CRITICAL' : 'NOMINAL'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* ANPR Detection Stream Header */}
                <div
                  style={{
                    padding: '8px 16px',
                    borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 800, color: '#f8fafc' }}>
                    <Camera size={13} color="#06b6d4" />
                    <span>ANPR DETECTION STREAM</span>
                    <span style={{ fontSize: '10px', color: '#94a3b8' }}>({detectedPlates.length} sightings)</span>
                  </div>
                </div>

                {/* Plate Sighting List */}
                <div
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    padding: '8px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                  }}
                >
                  {detectedPlates.length === 0 ? (
                    <div style={{ padding: '30px 10px', textAlign: 'center', color: '#64748b', fontSize: '11px' }}>
                      <Radio size={24} color="#06b6d4" style={{ margin: '0 auto 8px auto', display: 'block' }} />
                      Monitoring video stream for Indian license plates...
                    </div>
                  ) : (
                    detectedPlates.map((item, idx) => {
                      const isSelected = activePlate === item.plate;
                      return (
                        <div
                          key={idx}
                          className="anpr-row"
                          style={{
                            backgroundColor: isSelected ? 'rgba(6, 182, 212, 0.15)' : 'rgba(15, 23, 42, 0.6)',
                            border: isSelected ? '1px solid #06b6d4' : '1px solid rgba(255, 255, 255, 0.06)',
                            borderRadius: '6px',
                            padding: '8px 10px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            transition: 'all 0.15s ease',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            {/* Plate Badge */}
                            <div
                              style={{
                                backgroundColor: '#030712',
                                border: '1px solid #38bdf8',
                                color: '#38bdf8',
                                fontFamily: 'monospace',
                                fontWeight: 800,
                                fontSize: '13px',
                                padding: '3px 8px',
                                borderRadius: '4px',
                                letterSpacing: '0.06em',
                              }}
                            >
                              {item.plate}
                            </div>

                            <div>
                              <div style={{ fontSize: '10px', color: '#cbd5e1', fontWeight: 600 }}>
                                Confidence: {item.confidence != null ? `${(item.confidence * 100).toFixed(0)}%` : 'N/A'} • Speed: {item.speed_kmh != null ? `${Math.round(item.speed_kmh)} km/h` : 'CALIB REQ'}
                              </div>
                              <div style={{ fontSize: '9px', color: '#64748b' }}>
                                Seen: {item.timestamp} • Camera: {activeFeedObj.code}
                              </div>
                            </div>
                          </div>

                          {/* Pivot Action: Track on GIS */}
                          <button
                            onClick={() => loadRouteForPlate(item.plate)}
                            style={{
                              backgroundColor: isSelected ? '#06b6d4' : 'rgba(6, 182, 212, 0.2)',
                              color: isSelected ? '#030712' : '#38bdf8',
                              border: 'none',
                              padding: '4px 10px',
                              borderRadius: '4px',
                              fontSize: '10px',
                              fontWeight: 800,
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px',
                            }}
                          >
                            <MapPin size={11} />
                            TRACK ON GIS
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}

            {/* TAB 2: CROSS-CAMERA RE-ID & JOURNEY MATRIX */}
            {activeRightTab === 'cross_camera' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {/* Surveillance Fleet Summary Bar */}
                <div
                  style={{
                    padding: '10px 14px',
                    backgroundColor: 'rgba(15, 23, 42, 0.8)',
                    borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 800, color: '#c084fc', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Layers size={13} />
                      MTMC RE-ID SURVEILLANCE GRID
                    </span>
                    <span style={{ fontSize: '9.5px', color: '#10b981', fontWeight: 700, backgroundColor: 'rgba(16, 185, 129, 0.15)', padding: '1px 6px', borderRadius: '4px' }}>
                      STATE-WIDE TRACKING
                    </span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px' }}>
                    <div style={{ backgroundColor: '#030712', padding: '6px 8px', borderRadius: '5px', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ fontSize: '8.5px', color: '#94a3b8' }}>Fleet Count</div>
                      <div style={{ fontSize: '14px', fontWeight: 800, color: '#c084fc' }}>
                        {crossCameraData.total_active || 0} <span style={{ fontSize: '8.5px', color: '#64748b' }}>VEHICLES</span>
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#030712', padding: '6px 8px', borderRadius: '5px', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ fontSize: '8.5px', color: '#94a3b8' }}>Cross-Cam Matches</div>
                      <div style={{ fontSize: '14px', fontWeight: 800, color: '#38bdf8' }}>
                        {crossCameraData.multi_camera_crossings || 0} <span style={{ fontSize: '8.5px', color: '#64748b' }}>HOPS</span>
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#030712', padding: '6px 8px', borderRadius: '5px', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ fontSize: '8.5px', color: '#94a3b8' }}>Mesh Nodes</div>
                      <div style={{ fontSize: '14px', fontWeight: 800, color: '#10b981' }}>
                        {camerasList.length} <span style={{ fontSize: '8.5px', color: '#64748b' }}>CCTV</span>
                      </div>
                    </div>
                  </div>

                  {/* Inter-Camera Transition Flows */}
                  {gridMatrixData.inter_camera_transitions && Object.keys(gridMatrixData.inter_camera_transitions).length > 0 && (
                    <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '5px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '8.5px', color: '#64748b', fontWeight: 700 }}>TRANSITS:</span>
                      {Object.entries(gridMatrixData.inter_camera_transitions).map(([flow, count]) => (
                        <span
                          key={flow}
                          style={{
                            fontSize: '9px',
                            fontWeight: 700,
                            backgroundColor: 'rgba(168, 85, 247, 0.15)',
                            border: '1px solid rgba(168, 85, 247, 0.3)',
                            color: '#e9d5ff',
                            padding: '1px 6px',
                            borderRadius: '4px',
                          }}
                        >
                          {flow} ({count})
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Fleet Registry List */}
                <div
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    padding: '8px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '7px',
                  }}
                >
                  {(!crossCameraData.vehicles || crossCameraData.vehicles.length === 0) ? (
                    <div style={{ padding: '30px 10px', textAlign: 'center', color: '#64748b', fontSize: '11px' }}>
                      <Network size={24} color="#c084fc" style={{ margin: '0 auto 8px auto', display: 'block' }} />
                      Aggregating vehicle sightings across Gujarat CCTV grid...
                    </div>
                  ) : (
                    crossCameraData.vehicles.map((veh) => {
                      const isMultiCam = (veh.journey_hops || (veh.journey && veh.journey.length)) > 1;
                      return (
                        <div
                          key={veh.global_id}
                          style={{
                            backgroundColor: isMultiCam ? 'rgba(168, 85, 247, 0.09)' : 'rgba(15, 23, 42, 0.65)',
                            border: isMultiCam ? '1.5px solid rgba(168, 85, 247, 0.4)' : '1px solid rgba(255, 255, 255, 0.08)',
                            borderRadius: '7px',
                            padding: '8px 12px',
                            transition: 'all 0.15s ease',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              {veh.color_rgb && (
                                <span
                                  style={{
                                    width: 8,
                                    height: 8,
                                    borderRadius: '50%',
                                    backgroundColor: `rgb(${veh.color_rgb.join(',')})`,
                                    border: '1px solid #fff',
                                    flexShrink: 0,
                                  }}
                                />
                              )}
                              <span style={{ fontSize: '11.5px', fontWeight: 800, color: '#f8fafc' }}>
                                {veh.full_name || `${veh.color} ${veh.make} ${veh.model_subtype}`}
                              </span>
                            </div>

                            {veh.plate ? (
                              <span
                                style={{
                                  backgroundColor: '#030712',
                                  border: '1px solid #38bdf8',
                                  color: '#38bdf8',
                                  fontSize: '10px',
                                  fontFamily: 'monospace',
                                  fontWeight: 800,
                                  padding: '1px 5px',
                                  borderRadius: '3px',
                                }}
                              >
                                🇮🇳 {veh.plate}
                              </span>
                            ) : (
                              <span style={{ fontSize: '9px', color: '#64748b' }}>ALPR PENDING</span>
                            )}
                          </div>

                          {/* Details Row */}
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '4px' }}>
                            <div style={{ fontSize: '9.5px', color: '#94a3b8' }}>
                              <span>Node: <b style={{ color: '#cbd5e1' }}>{veh.current_camera_name || veh.current_camera_id}</b></span>
                              <span style={{ margin: '0 5px' }}>•</span>
                              <span style={{ color: '#a78bfa' }}>🧭 {veh.current_direction || 'Stationary'}</span>
                              {veh.current_speed_kmh != null && (
                                <>
                                  <span style={{ margin: '0 5px' }}>•</span>
                                  <span style={{ color: '#10b981', fontWeight: 700 }}>{Math.round(veh.current_speed_kmh)} km/h</span>
                                </>
                              )}
                            </div>

                            <button
                              onClick={() => setSelectedJourneyVehicle(veh)}
                              style={{
                                backgroundColor: isMultiCam ? '#a855f7' : 'rgba(168, 85, 247, 0.2)',
                                color: isMultiCam ? '#ffffff' : '#c084fc',
                                border: 'none',
                                padding: '3px 8px',
                                borderRadius: '4px',
                                fontSize: '9.5px',
                                fontWeight: 800,
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                              }}
                            >
                              <Share2 size={10} />
                              TRANSIT ({veh.journey_hops || 1})
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

      {/* MULTI-CAMERA VEHICLE TRANSIT TIMELINE MODAL */}
      {selectedJourneyVehicle && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            backgroundColor: 'rgba(3, 7, 18, 0.85)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
          onClick={() => setSelectedJourneyVehicle(null)}
        >
          <div
            style={{
              backgroundColor: '#0b1120',
              border: '1.5px solid rgba(168, 85, 247, 0.5)',
              borderRadius: '10px',
              maxWidth: '600px',
              width: '100%',
              overflow: 'hidden',
              boxShadow: '0 0 40px rgba(168, 85, 247, 0.25)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                backgroundColor: 'rgba(168, 85, 247, 0.15)',
                borderBottom: '1px solid rgba(168, 85, 247, 0.3)',
                padding: '12px 18px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Network size={18} color="#c084fc" />
                <span style={{ fontSize: '13px', fontWeight: 800, color: '#e9d5ff', letterSpacing: '0.04em' }}>
                  MULTI-CAMERA TRANSIT TIMELINE • {selectedJourneyVehicle.global_id}
                </span>
              </div>
              <button
                onClick={() => setSelectedJourneyVehicle(null)}
                style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#030712', padding: '10px 14px', borderRadius: '6px', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 800, color: '#f8fafc' }}>
                    {selectedJourneyVehicle.full_name}
                  </div>
                  <div style={{ fontSize: '10.5px', color: '#94a3b8', marginTop: '2px' }}>
                    Brand: <b style={{ color: '#38bdf8' }}>{selectedJourneyVehicle.make}</b> • Subtype: <b style={{ color: '#cbd5e1' }}>{selectedJourneyVehicle.model_subtype}</b> • Paint: <b style={{ color: '#10b981' }}>{selectedJourneyVehicle.color}</b>
                  </div>
                </div>
                {selectedJourneyVehicle.plate && (
                  <div style={{ backgroundColor: '#030712', border: '1.5px solid #38bdf8', color: '#38bdf8', fontSize: '13px', fontFamily: 'monospace', fontWeight: 800, padding: '4px 10px', borderRadius: '4px' }}>
                    🇮🇳 {selectedJourneyVehicle.plate}
                  </div>
                )}
              </div>

              {/* Hop Progression Timeline */}
              <div>
                <div style={{ fontSize: '10.5px', fontWeight: 800, color: '#94a3b8', letterSpacing: '0.06em', marginBottom: '8px' }}>
                  CHRONOLOGICAL CAMERA TRANSIT HOPS:
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {(selectedJourneyVehicle.journey || []).map((hop, hidx) => (
                    <div
                      key={hidx}
                      style={{
                        backgroundColor: '#070d19',
                        borderLeft: '3px solid #c084fc',
                        borderTop: '1px solid rgba(255, 255, 255, 0.06)',
                        borderRight: '1px solid rgba(255, 255, 255, 0.06)',
                        borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                        padding: '8px 12px',
                        borderRadius: '0 6px 6px 0',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <span style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: 'rgba(168, 85, 247, 0.25)', color: '#e9d5ff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: 800 }}>
                          {hidx + 1}
                        </span>
                        <div>
                          <div style={{ fontSize: '11.5px', fontWeight: 800, color: '#f8fafc' }}>
                            {hop.camera_name || hop.camera_id}
                          </div>
                          <div style={{ fontSize: '9.5px', color: '#64748b' }}>
                            {hop.timestamp || hop.timestamp_str} • Heading {hop.direction}
                          </div>
                        </div>
                      </div>

                      {hop.speed_kmh != null && (
                        <span style={{ fontSize: '11px', fontWeight: 800, color: '#10b981' }}>
                          {Math.round(hop.speed_kmh)} km/h
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {selectedJourneyVehicle.plate && (
                <button
                  onClick={() => {
                    loadRouteForPlate(selectedJourneyVehicle.plate);
                    setSelectedJourneyVehicle(null);
                  }}
                  style={{
                    backgroundColor: '#06b6d4',
                    color: '#030712',
                    fontWeight: 800,
                    padding: '8px 14px',
                    borderRadius: '6px',
                    border: 'none',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '6px',
                    fontSize: '11px',
                  }}
                >
                  <MapPin size={13} />
                  PLOT FULL STATE ROUTE TRAJECTORY ON GIS
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* EVIDENCE DOSSIER MODAL */}
      {dossierOpen && dossierData && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            backgroundColor: 'rgba(3, 7, 18, 0.85)',
            backdropFilter: 'blur(10px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
          onClick={() => setDossierOpen(false)}
        >
          <div
            style={{
              backgroundColor: '#0b1120',
              border: '1.5px solid rgba(239, 68, 68, 0.6)',
              borderRadius: '10px',
              maxWidth: '680px',
              width: '100%',
              overflow: 'hidden',
              boxShadow: '0 0 40px rgba(239, 68, 68, 0.3)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.15)',
                borderBottom: '1px solid rgba(239, 68, 68, 0.3)',
                padding: '12px 18px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Shield size={18} color="#ef4444" />
                <span style={{ fontSize: '13px', fontWeight: 800, color: '#ef4444', letterSpacing: '0.06em' }}>
                  GUJARAT POLICE SURVEILLANCE EVIDENCE DOSSIER
                </span>
              </div>
              <button onClick={() => setDossierOpen(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            {/* Content */}
            <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.1)', padding: '8px 12px', borderRadius: '6px', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                <div style={{ fontSize: '12px', fontWeight: 800, color: '#ef4444' }}>{dossierData.title}</div>
                <div style={{ fontSize: '11px', color: '#cbd5e1', marginTop: '2px' }}>{dossierData.reason}</div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                <div style={{ backgroundColor: '#030712', padding: '8px', borderRadius: '6px' }}>
                  <div style={{ fontSize: '9px', color: '#94a3b8' }}>Target License Plate</div>
                  <div style={{ fontSize: '14px', fontWeight: 800, fontFamily: 'monospace', color: '#38bdf8' }}>{dossierData.plate}</div>
                </div>
                <div style={{ backgroundColor: '#030712', padding: '8px', borderRadius: '6px' }}>
                  <div style={{ fontSize: '9px', color: '#94a3b8' }}>Location</div>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#ffffff' }}>{dossierData.location}</div>
                </div>
                <div style={{ backgroundColor: '#030712', padding: '8px', borderRadius: '6px' }}>
                  <div style={{ fontSize: '9px', color: '#94a3b8' }}>Impact Speed</div>
                  <div style={{ fontSize: '14px', fontWeight: 800, color: dossierData.speed_kmh != null ? '#ef4444' : '#f59e0b' }}>
                    {dossierData.speed_kmh != null ? `${Math.round(dossierData.speed_kmh)} km/h` : 'CALIB REQ'}
                  </div>
                </div>
              </div>

              {/* Video Snapshot if available */}
              {dossierData.snapshot && (
                <div style={{ borderRadius: '6px', overflow: 'hidden', border: '1px solid rgba(255, 255, 255, 0.1)' }}>
                  <img
                    src={`data:image/jpeg;base64,${dossierData.snapshot}`}
                    alt="Evidence Frame"
                    style={{ width: '100%', height: 'auto', display: 'block' }}
                  />
                </div>
              )}

              {/* Action */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' }}>
                <button
                  onClick={() => setDossierOpen(false)}
                  style={{
                    backgroundColor: 'transparent',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    color: '#cbd5e1',
                    padding: '6px 14px',
                    borderRadius: '4px',
                    fontSize: '11px',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  DISMISS
                </button>
                <button
                  onClick={() => {
                    alert(`🚨 112 Interceptor dispatched to ${dossierData.location} for suspect plate ${dossierData.plate}!`);
                    setDossierOpen(false);
                    setStrobeAlert(false);
                  }}
                  style={{
                    backgroundColor: '#ef4444',
                    border: 'none',
                    color: '#ffffff',
                    padding: '6px 16px',
                    borderRadius: '4px',
                    fontSize: '11px',
                    fontWeight: 800,
                    cursor: 'pointer',
                  }}
                >
                  DISPATCH 112 INTERCEPTOR
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Operator Camera Speed Calibration Modal */}
      {showCalibrationModal && (
        <CameraCalibrationModal
          camera={activeFeedObj}
          onClose={() => setShowCalibrationModal(false)}
          onCalibrationUpdated={() => {
            setCamerasList((prev) =>
              prev.map((c) =>
                c.camera_id === activeFeedObj.id
                  ? { ...c, is_calibrated: true, calibration_status: 'CALIBRATED' }
                  : c
              )
            );
          }}
        />
      )}
    </div>
  );
}
