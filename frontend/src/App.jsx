import React, { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Activity,
  MapPin,
  Video,
  AlertTriangle,
  Radio,
  Sliders,
  Bell,
  Cpu,
  Tv,
} from 'lucide-react';
import GisMap from './components/GisMap.jsx';
import RoutePanel from './components/RoutePanel.jsx';
import ThreatAlertModal from './components/ThreatAlertModal.jsx';
import WatchlistManager from './components/WatchlistManager.jsx';
import CCTVGrid from './components/CCTVGrid.jsx';
import UnifiedCommandCenter from './components/UnifiedCommandCenter.jsx';
import CameraInspectionModal from './components/CameraInspectionModal.jsx';

export default function App() {
  const [activeTab, setActiveTab] = useState('command_center'); // 'command_center' | 'gis' | 'watchlist' | 'matrix'
  const [cameras, setCameras] = useState([]);
  const [selectedPlate, setSelectedPlate] = useState('');
  const [routeData, setRouteData] = useState(null);
  const [loadingRoute, setLoadingRoute] = useState(false);
  const [inspectedCamera, setInspectedCamera] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);

  // Playback state
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackIndex, setPlaybackIndex] = useState(-1);
  const playbackTimerRef = useRef(null);

  // WebSocket & Alerts state
  const [wsConnected, setWsConnected] = useState(false);
  const [activeThreat, setActiveThreat] = useState(null);
  const [currentDetections, setCurrentDetections] = useState([]);
  const wsRef = useRef(null);

  // 1. Fetch Cameras from authoritative /api/cameras endpoint
  useEffect(() => {
    fetch('/api/cameras')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setCameras(data);
        } else if (data.features) {
          setCameras(data.features);
        }
      })
      .catch((e) => console.error('Failed to load cameras', e));
  }, []);

  // 2. Fetch Recent Real-time CCTV Detection Events
  const fetchRecentEvents = async () => {
    try {
      const res = await fetch('/api/v1/events/recent');
      if (res.ok) {
        const data = await res.json();
        setLiveEvents(data);
        if (data.length > 0 && !selectedPlate) {
          const firstPlate = data.find((e) => e.license_plate)?.license_plate;
          if (firstPlate) {
            setSelectedPlate(firstPlate);
          }
        }
      }
    } catch (e) {
      console.error('Failed to load recent events', e);
    }
  };

  useEffect(() => {
    fetchRecentEvents();
  }, []);

  // 3. Fetch Route Reconstruction for a Specific Plate
  const fetchRoute = async (plate) => {
    if (!plate) return;
    setLoadingRoute(true);
    try {
      const res = await fetch(`/api/v1/tracking/route/${plate}`);
      const data = await res.json();
      setRouteData(data);
      setSelectedPlate(plate);
      setIsPlaying(false);
      setPlaybackIndex(-1);

      // Only trigger alert if plate is an actual watchlist hit
      if (data.properties?.is_watchlist_match && data.properties?.watchlist_details) {
        const firstPoint = data.features.find((f) => f.geometry.type === 'Point');
        setActiveThreat({
          license_plate: plate,
          category: data.properties.watchlist_details.category,
          severity: data.properties.watchlist_details.severity,
          owner_name: data.properties.watchlist_details.owner_name,
          vehicle_info: `${data.properties.watchlist_details.vehicle_make} ${data.properties.watchlist_details.vehicle_model}`,
          notes: data.properties.watchlist_details.notes,
          camera_id: firstPoint?.properties?.camera_id || cameras[0]?.camera_id || cameras[0]?.properties?.camera_id || '',
          camera_name: firstPoint?.properties?.camera_name || cameras[0]?.name || cameras[0]?.properties?.name || 'Surveillance Camera',
          city: firstPoint?.properties?.city || 'Gujarat',
        });
      }
    } catch (e) {
      console.error('Failed to load route', e);
    } finally {
      setLoadingRoute(false);
    }
  };

  // 4. Connect to WebSocket Live Ingestion & Threat Feed
  useEffect(() => {
    let ws;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.port === '5173' ? `${window.location.hostname}:8001` : window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws/alerts`;

    const connectWs = () => {
      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log('[Sentinel WS] Connected to live threat and ingestion stream');
          setWsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);

            if (payload.event_type === 'THREAT_DETECTED') {
              console.log('[Sentinel WS] Threat alert received:', payload);
              setActiveThreat(payload);
              if (payload.license_plate) {
                fetchRoute(payload.license_plate);
              }
            } else if (payload.event_type === 'LIVE_DETECTION' || payload.event_type === 'ALPR_DETECTED') {
              const meta = payload.metadata || {};
              const alpr = meta.alpr || {};
              const plate = alpr.plate || meta.license_plate || meta.plate;
              const dets = payload.detections || meta.detections;
              if (dets && dets.length > 0) {
                setCurrentDetections(dets);
              }

              if (plate) {
                const newEvent = {
                  event_id: payload.event_id || `evt_${Date.now()}`,
                  camera_id: payload.camera_id || cameras[0]?.camera_id || cameras[0]?.properties?.camera_id || '',
                  event_type: payload.event_type,
                  confidence: payload.confidence || 0.95,
                  timestamp: payload.timestamp || new Date().toISOString(),
                  city: meta.city || 'Gujarat',
                  license_plate: plate,
                  track_id: alpr.track_id,
                  latency_ms: payload.inference_latency_ms || 35.0,
                  metadata: meta,
                };

                setLiveEvents((prev) => [newEvent, ...prev.slice(0, 99)]);
              }
            }
          } catch (err) {
            console.error('[Sentinel WS] Message parse error:', err);
          }
        };

        ws.onclose = () => {
          console.warn('[Sentinel WS] Connection closed. Reconnecting in 3s...');
          setWsConnected(false);
          setTimeout(connectWs, 3000);
        };

        ws.onerror = (e) => {
          console.error('[Sentinel WS] Error:', e);
          ws.close();
        };

        wsRef.current = ws;
      } catch (e) {
        console.error('[Sentinel WS] Setup error:', e);
      }
    };

    connectWs();

    return () => {
      if (ws) ws.close();
    };
  }, []);

  // 5. Route Playback Logic
  const pointFeatures = routeData?.features?.filter((f) => f.geometry.type === 'Point') || [];

  const handleStartPlayback = () => {
    if (pointFeatures.length === 0) return;
    setIsPlaying(true);
    setPlaybackIndex(0);
  };

  const handleStopPlayback = () => {
    setIsPlaying(false);
    setPlaybackIndex(-1);
    if (playbackTimerRef.current) clearInterval(playbackTimerRef.current);
  };

  useEffect(() => {
    if (!isPlaying) return;

    playbackTimerRef.current = setInterval(() => {
      setPlaybackIndex((prev) => {
        if (prev + 1 >= pointFeatures.length) {
          setIsPlaying(false);
          return 0;
        }
        return prev + 1;
      });
    }, 1800);

    return () => {
      if (playbackTimerRef.current) clearInterval(playbackTimerRef.current);
    };
  }, [isPlaying, pointFeatures.length]);

  const activePlaybackStep =
    playbackIndex >= 0 && pointFeatures[playbackIndex]
      ? {
          lat: pointFeatures[playbackIndex].geometry.coordinates[1],
          lon: pointFeatures[playbackIndex].geometry.coordinates[0],
          city: pointFeatures[playbackIndex].properties.city,
          camera: pointFeatures[playbackIndex].properties.camera_name,
        }
      : null;



  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* High Visibility Threat Alert Strobe & Modal */}
      <ThreatAlertModal
        alert={activeThreat}
        onDismiss={() => setActiveThreat(null)}
        onDispatch={(threat) => {
          alert(`🚨 112 Interceptor Unit Dispatched to ${threat.camera_name || threat.camera_id} (${threat.city})! Intercepting target vehicle ${threat.license_plate}.`);
          setActiveThreat(null);
        }}
      />

      {/* Navigation Header */}
      <header
        className="glass-panel"
        style={{
          height: '62px',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border-color)',
          zIndex: 1000,
          flexShrink: 0,
        }}
      >
        {/* Brand & Gujarat Police Department Seal */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '38px',
              height: '38px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 16px rgba(6, 182, 212, 0.45)',
            }}
          >
            <Shield size={22} color="#ffffff" />
          </div>

          <div>
            <div style={{ fontSize: '15px', fontWeight: 800, letterSpacing: '0.08em', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
              SENTINEL
              <span style={{ fontSize: '10px', background: 'rgba(6, 182, 212, 0.15)', color: '#38bdf8', padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(6, 182, 212, 0.35)', fontWeight: 800, letterSpacing: '0.05em' }}>
                GUJARAT POLICE COMMAND CENTER
              </span>
            </div>
            <div style={{ fontSize: '10px', color: '#94a3b8' }}>
              Law Enforcement Video Management & Statewide Intelligence Grid • 1,000 km Corridor
            </div>
          </div>
        </div>

        {/* Clean Unified Navigation Switcher */}
        <div style={{ display: 'flex', gap: '6px', background: 'rgba(15, 23, 42, 0.75)', padding: '4px', borderRadius: '8px', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
          <button
            onClick={() => setActiveTab('command_center')}
            style={{
              background: activeTab === 'command_center' ? 'linear-gradient(135deg, #06b6d4 0%, #2563eb 100%)' : 'transparent',
              color: activeTab === 'command_center' ? '#ffffff' : '#cbd5e1',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 800,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              boxShadow: activeTab === 'command_center' ? '0 0 14px rgba(6, 182, 212, 0.5)' : 'none',
            }}
          >
            <Sliders size={14} /> ★ COMMAND CENTER
          </button>

          <button
            onClick={() => {
              setActiveTab('gis');
              if (!routeData && selectedPlate) {
                fetchRoute(selectedPlate);
              }
            }}
            style={{
              background: activeTab === 'gis' ? '#06b6d4' : 'transparent',
              color: activeTab === 'gis' ? '#0a0d14' : '#cbd5e1',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <MapPin size={14} /> GIS RE-ID
          </button>

          <button
            onClick={() => setActiveTab('watchlist')}
            style={{
              background: activeTab === 'watchlist' ? '#ef4444' : 'transparent',
              color: activeTab === 'watchlist' ? '#ffffff' : '#cbd5e1',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <AlertTriangle size={14} /> eGujCop WATCHLIST
          </button>

          <button
            onClick={() => setActiveTab('matrix')}
            style={{
              background: activeTab === 'matrix' ? '#06b6d4' : 'transparent',
              color: activeTab === 'matrix' ? '#0a0d14' : '#cbd5e1',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <Video size={14} /> TACTICAL MOSAIC
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {activeTab === 'command_center' && (
          <UnifiedCommandCenter
            cameras={cameras}
            onSelectPlateForRoute={(plate) => {
              setSelectedPlate(plate);
              fetchRoute(plate);
              setActiveTab('gis');
            }}
          />
        )}

        {activeTab === 'gis' && (
          <div style={{ display: 'flex', width: '100%', height: '100%' }}>
            <RoutePanel
              routeData={routeData}
              selectedPlate={selectedPlate}
              onSearchPlate={(plate) => fetchRoute(plate)}
              onStartPlayback={handleStartPlayback}
              onStopPlayback={handleStopPlayback}
              isPlaying={isPlaying}
              playbackIndex={playbackIndex}
              popularPlates={Array.from(new Set(liveEvents.map((e) => e.license_plate).filter(Boolean)))}
            />

            <div style={{ flex: 1, position: 'relative', height: '100%' }}>
              <GisMap
                cameras={cameras}
                routeData={routeData}
                activePlaybackStep={activePlaybackStep}
                activeThreat={activeThreat}
                onSelectCamera={(cam) => setInspectedCamera(cam)}
              />
            </div>
          </div>
        )}

        {activeTab === 'matrix' && <CCTVGrid />}

        {activeTab === 'watchlist' && (
          <WatchlistManager />
        )}

        {/* WebRTC / WHEP Live Camera Inspection Modal */}
        {inspectedCamera && (
          <CameraInspectionModal
            camera={inspectedCamera}
            onClose={() => setInspectedCamera(null)}
          />
        )}
      </main>
    </div>
  );
}
