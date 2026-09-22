import React, { useEffect, useRef } from 'react';
import L from 'leaflet';

// Gujarat geographical center
const GUJARAT_CENTER = [22.8, 71.8];
const DEFAULT_ZOOM = 7.5;

export default function GisMap({
  cameras = [],
  routeData = null,
  activePlaybackStep = null,
  activeThreat = null,
  onSelectCamera = () => {},
}) {
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersLayerRef = useRef(null);
  const routeLayerRef = useRef(null);
  const playbackMarkerRef = useRef(null);

  // 1. Initialize Map
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: GUJARAT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: false,
      attributionControl: false,
    });

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // High-contrast clean dark law enforcement basemap (Zero watermark)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      subdomains: 'abcd',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);

    // Marker & Route layers
    markersLayerRef.current = L.layerGroup().addTo(map);
    routeLayerRef.current = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // 2. Render Surveillance Cameras (Strictly null-safe for /api/cameras)
  useEffect(() => {
    const map = mapInstanceRef.current;
    const markersLayer = markersLayerRef.current;
    if (!map || !markersLayer) return;

    markersLayer.clearLayers();

    const validCoords = [];

    cameras.forEach((cam) => {
      const props = cam.properties || cam;
      const camId = props.camera_id || props.id;
      const camName = props.name || props.camera_name || camId;
      const city = props.city || 'Gujarat';
      const status = props.status || 'online';
      const isThreatCam = activeThreat && (activeThreat.camera_id === camId);
      const isOnline = status === 'online';

      // Safe coordinate resolution (supports both GeoJSON and /api/cameras models)
      const lat = cam.geometry?.coordinates?.[1] ?? props.latitude;
      const lon = cam.geometry?.coordinates?.[0] ?? props.longitude;

      if (lat == null || lon == null || isNaN(lat) || isNaN(lon)) {
        // Strict integrity: do NOT fabricate coordinates for cameras without GPS
        return;
      }

      validCoords.push([Number(lat), Number(lon)]);

      const customIcon = L.divIcon({
        className: 'custom-camera-icon',
        html: `
          <div class="camera-pulse-marker">
            <div class="camera-pulse-ring ${isThreatCam ? 'threat' : ''}"></div>
            <div class="camera-dot ${isThreatCam ? 'threat' : ''}"></div>
          </div>
        `,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });

      const marker = L.marker([Number(lat), Number(lon)], {
        icon: customIcon,
      });

      marker.bindPopup(`
        <div style="font-size: 13px; line-height: 1.5;">
          <div style="font-weight: 700; color: ${isThreatCam ? '#ef4444' : '#06b6d4'}; font-size: 14px; margin-bottom: 4px;">
            ${isThreatCam ? '🚨 THREAT SIGHTING CAMERA' : 'SURVEILLANCE CAMERA'}
          </div>
          <div style="font-weight: 600; color: #f8fafc;">${camName}</div>
          <div style="color: #94a3b8; font-size: 11px; margin-top: 2px;">
            ID: <span style="font-family: monospace; color: #38bdf8;">${camId}</span> | City: <b>${city}</b>
          </div>
          <div style="margin-top: 6px; padding: 4px 8px; background: rgba(0,0,0,0.4); border-radius: 4px; font-size: 11px; display: flex; justify-content: space-between;">
            <span>Status: <b style="color: ${isOnline ? '#10b981' : '#ef4444'}">${status.toUpperCase()}</b></span>
            <span>Events: <b>${props.events_count ?? 0}</b></span>
          </div>
        </div>
      `);

      marker.on('click', () => onSelectCamera(cam));
      markersLayer.addLayer(marker);
    });

    if (validCoords.length > 0 && !routeData) {
      if (validCoords.length === 1) {
        map.setView(validCoords[0], 12);
      } else {
        const bounds = L.latLngBounds(validCoords);
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
      }
    }
  }, [cameras, activeThreat, routeData, onSelectCamera]);

  // 3. Render Route Trajectory (Polyline & Checkpoint Markers)
  useEffect(() => {
    const map = mapInstanceRef.current;
    const routeLayer = routeLayerRef.current;
    if (!map || !routeLayer) return;

    routeLayer.clearLayers();

    if (!routeData || !routeData.features || routeData.features.length === 0) return;

    const lineFeature = routeData.features.find((f) => f.geometry.type === 'LineString');
    const pointFeatures = routeData.features.filter((f) => f.geometry.type === 'Point');

    const isThreatVehicle = routeData.properties.is_watchlist_match;
    const routeColor = isThreatVehicle ? '#ef4444' : '#06b6d4';

    // A. Draw Traversed Route Polyline
    if (lineFeature && lineFeature.geometry.coordinates.length > 1) {
      const latLngs = lineFeature.geometry.coordinates.map(([lon, lat]) => [lat, lon]);

      // Glow backdrop polyline
      L.polyline(latLngs, {
        color: routeColor,
        weight: 12,
        opacity: 0.30,
        lineCap: 'round',
        lineJoin: 'round',
      }).addTo(routeLayer);

      // Core neon glowing animated polyline
      const mainLine = L.polyline(latLngs, {
        color: isThreatVehicle ? '#f87171' : '#38bdf8',
        weight: 4,
        opacity: 0.95,
        dashArray: '10, 8',
        className: isThreatVehicle ? 'glowing-trajectory-line-threat' : 'glowing-trajectory-line',
      }).addTo(routeLayer);

      mainLine.bindTooltip(`
        <div style="font-size: 12px; font-weight: 700; color: #f8fafc;">
          ⚡ ${routeData.properties.license_plate}: ${lineFeature.properties.total_distance_km} km • Avg ${lineFeature.properties.average_speed_kmh || '0'} km/h • ${lineFeature.properties.duration_minutes} min
        </div>
      `, { sticky: true, className: 'playback-tooltip' });

      // Fit map bounds to show complete trajectory across Gujarat
      map.fitBounds(mainLine.getBounds(), { padding: [60, 60] });
    }

    // B. Draw Sequenced Checkpoint Markers
    pointFeatures.forEach((pt, index) => {
      const [lon, lat] = pt.geometry.coordinates;
      const order = pt.properties.checkpoint_order || index + 1;
      const isLatest = order === pointFeatures.length;

      const checkpointIcon = L.divIcon({
        className: 'checkpoint-icon',
        html: `
          <div style="
            position: relative;
            width: 28px;
            height: 28px;
            background: ${isLatest ? '#ef4444' : '#1e293b'};
            border: 2px solid ${isLatest ? '#ffffff' : routeColor};
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 800;
            color: #ffffff;
            box-shadow: 0 0 14px ${isLatest ? 'rgba(239, 68, 68, 0.9)' : 'rgba(6, 182, 212, 0.7)'};
          ">
            #${order}
          </div>
        `,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      });

      const marker = L.marker([lat, lon], { icon: checkpointIcon });

      const dateStr = pt.properties.first_seen
        ? new Date(pt.properties.first_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        : 'N/A';

      const segSpeed = pt.properties.segment_speed_kmh;
      const segMinutes = pt.properties.transit_time_from_prev_minutes;
      const segDist = pt.properties.distance_from_prev_km;

      marker.bindPopup(`
        <div style="font-size: 13px; line-height: 1.5; min-width: 220px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <span style="font-weight: 800; color: ${routeColor}; font-size: 13px;">CHECKPOINT #${order}</span>
            <span style="background: rgba(6, 182, 212, 0.15); color: #38bdf8; font-size: 11px; padding: 2px 6px; border-radius: 4px; font-family: monospace;">
              ${dateStr}
            </span>
          </div>
          <div style="font-weight: 700; color: #f8fafc;">${pt.properties.camera_name}</div>
          <div style="color: #94a3b8; font-size: 11px; margin-top: 2px;">
            City: <b>${pt.properties.city}</b> | Camera: <span style="font-family: monospace;">${pt.properties.camera_id}</span>
          </div>
          ${segSpeed > 0 ? `
            <div style="margin-top: 6px; padding: 4px 8px; background: rgba(6, 182, 212, 0.1); border-radius: 4px; font-size: 11px; display: flex; justify-content: space-between;">
              <span style="color: #94a3b8;">Transit Speed:</span>
              <span style="color: #38bdf8; font-weight: 800;">${segSpeed} km/h (${segMinutes} min • ${segDist} km)</span>
            </div>
          ` : ''}
          <div style="margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 6px; display: flex; justify-content: space-between; font-size: 11px;">
            <span>Confidence: <b style="color: #10b981">${Math.round(pt.properties.best_confidence * 100)}%</b></span>
            <span>Sightings: <b>${pt.properties.detections_count}</b></span>
          </div>
        </div>
      `);

      routeLayer.addLayer(marker);
    });
  }, [routeData]);

  // 4. Vehicle Playback Marker
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (playbackMarkerRef.current) {
      playbackMarkerRef.current.remove();
      playbackMarkerRef.current = null;
    }

    if (activePlaybackStep && activePlaybackStep.lat && activePlaybackStep.lon) {
      const carIcon = L.divIcon({
        className: 'vehicle-playback-icon',
        html: `
          <div style="
            width: 38px;
            height: 38px;
            background: #ef4444;
            border: 3px solid #ffffff;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 25px #ef4444;
            animation: pulse-ring 1s infinite;
          ">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
              <rect x="2" y="5" width="20" height="14" rx="2"></rect>
              <circle cx="7" cy="15" r="2"></circle>
              <circle cx="17" cy="15" r="2"></circle>
            </svg>
          </div>
        `,
        iconSize: [38, 38],
        iconAnchor: [19, 19],
      });

      const marker = L.marker([activePlaybackStep.lat, activePlaybackStep.lon], { icon: carIcon }).addTo(map);
      marker.bindTooltip(`📍 Traversing: ${activePlaybackStep.city || 'Checkpoint'}`, {
        permanent: true,
        direction: 'top',
        className: 'playback-tooltip',
      });
      playbackMarkerRef.current = marker;
      map.panTo([activePlaybackStep.lat, activePlaybackStep.lon], { animate: true, duration: 0.5 });
    }
  }, [activePlaybackStep]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />

      {/* Map Overlay Badge */}
      <div
        className="glass-panel"
        style={{
          position: 'absolute',
          top: '16px',
          left: '16px',
          zIndex: 999,
          padding: '8px 14px',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}
      >
        <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#10b981', display: 'inline-block', boxShadow: '0 0 8px #10b981' }}></span>
        <span style={{ fontSize: '12px', fontWeight: 600, letterSpacing: '0.05em', color: '#e2e8f0' }}>
          GUJARAT STATEWIDE GIS GRID (1,000 KM)
        </span>
        <span style={{ fontSize: '11px', color: '#06b6d4', background: 'rgba(6, 182, 212, 0.1)', padding: '2px 6px', borderRadius: '4px' }}>
          {cameras.length} NODES ONLINE
        </span>
        {cameras.some(c => (c.geometry?.coordinates?.[0] == null && (c.properties || c).longitude == null)) && (
          <span style={{ fontSize: '11px', color: '#f59e0b', background: 'rgba(245, 158, 11, 0.15)', padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(245, 158, 11, 0.3)', fontWeight: 600 }}>
            {cameras.filter(c => (c.geometry?.coordinates?.[0] == null && (c.properties || c).longitude == null)).length} LOCATION UNAVAILABLE
          </span>
        )}
      </div>

      <style>{`
        @keyframes pulse-dash {
          0% { stroke-dashoffset: 36; }
          100% { stroke-dashoffset: 0; }
        }
        .glowing-trajectory-line {
          animation: pulse-dash 1.4s linear infinite;
          filter: drop-shadow(0 0 6px #38bdf8);
        }
        .glowing-trajectory-line-threat {
          animation: pulse-dash 1.0s linear infinite;
          filter: drop-shadow(0 0 9px #ef4444);
        }
      `}</style>
    </div>
  );
}
