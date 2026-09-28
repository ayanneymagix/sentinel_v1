import React, { useState, useEffect } from 'react';
import { Video, RefreshCw, Radio, Shield, Filter, Eye, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react';
import GridPlayer from './GridPlayer.jsx';
import FocusPlayer from './FocusPlayer.jsx';

/**
 * CCTVGrid: Main Dashboard View for Sentinel CCTV Video Ingestion
 * 
 * Directives:
 * 1. Fetches camera array from authoritative registry (/api/cameras).
 * 2. Renders 3x3 grid with pagination supporting all 30 statewide cameras.
 * 3. On click, launches FocusPlayer modal with ultra-low latency WebRTC (WHEP).
 * 4. Zero hardcoding: dynamically constructs stream URLs using authoritative backend descriptors.
 */
export default function CCTVGrid() {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [focusedCamera, setFocusedCamera] = useState(null);
  const [selectedDistrict, setSelectedDistrict] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 9;

  // 1. Fetch camera topology dynamically from authoritative registry API
  const fetchCameras = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/cameras');
      if (!response.ok) {
        throw new Error(`Camera registry returned HTTP ${response.status}`);
      }
      const data = await response.json();
      const cameraList = Array.isArray(data) ? data : data.cameras || [];
      setCameras(cameraList);
    } catch (err) {
      console.error('[CCTVGrid] Failed to fetch cameras from registry:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCameras();
  }, []);

  // Filter cameras by district if selected
  const filteredCameras = selectedDistrict === 'ALL'
    ? cameras
    : cameras.filter((c) => c.location?.city === selectedDistrict || c.city === selectedDistrict);

  // Pagination for all 30 cameras
  const totalPages = Math.max(1, Math.ceil(filteredCameras.length / pageSize));
  const effectivePage = Math.min(currentPage, totalPages);
  const startIndex = (effectivePage - 1) * pageSize;
  const activeCameras = filteredCameras.slice(startIndex, startIndex + pageSize);

  const handleDistrictChange = (district) => {
    setSelectedDistrict(district);
    setCurrentPage(1);
  };

  // Extract unique districts for filtering
  const districtList = ['ALL', ...new Set(cameras.map((c) => c.location?.city || c.city || 'Gujarat').filter(Boolean))];


  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        width: '100%',
        backgroundColor: '#060911',
        overflow: 'hidden',
        color: '#f8fafc',
      }}
    >
      {/* Top Controls Header */}
      <div
        className="glass-panel"
        style={{
          padding: '12px 24px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '6px',
              background: 'rgba(6, 182, 212, 0.15)',
              border: '1px solid #06b6d4',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Video size={18} color="#06b6d4" />
          </div>

          <div>
            <h2 style={{ fontSize: '15px', fontWeight: 800, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              STATEWIDE SURVEILLANCE MATRIX
              <span
                style={{
                  fontSize: '11px',
                  background: 'rgba(6, 182, 212, 0.2)',
                  color: '#38bdf8',
                  border: '1px solid rgba(6, 182, 212, 0.4)',
                  padding: '1px 8px',
                  borderRadius: '4px',
                  fontWeight: 700,
                }}
              >
                {cameras.length} cameras
              </span>
              <span
                style={{
                  fontSize: '10px',
                  background: 'rgba(16, 185, 129, 0.2)',
                  color: '#10b981',
                  border: '1px solid rgba(16, 185, 129, 0.4)',
                  padding: '1px 6px',
                  borderRadius: '4px',
                }}
              >
                CATALOGUE LIVE
              </span>
            </h2>
            <p style={{ fontSize: '11px', color: '#94a3b8', margin: '2px 0 0 0' }}>
              Authoritative Dynamic CCTV Gateway • {cameras.length} cameras discovered
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* District Filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Filter size={14} color="#94a3b8" />
            <select
              value={selectedDistrict}
              onChange={(e) => handleDistrictChange(e.target.value)}
              style={{
                background: 'rgba(15, 23, 42, 0.8)',
                border: '1px solid rgba(6, 182, 212, 0.3)',
                color: '#f8fafc',
                padding: '6px 12px',
                borderRadius: '6px',
                fontSize: '12px',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              {districtList.map((d) => (
                <option key={d} value={d}>
                  {d === 'ALL' ? 'All Gujarat Districts' : `${d} District`}
                </option>
              ))}
            </select>
          </div>

          {/* Stream Telemetry Counter */}
          <div
            className="glass-panel"
            style={{
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '11px',
              display: 'flex',
              gap: '12px',
            }}
          >
            <span>Feeds Ingested: <b style={{ color: '#10b981' }}>{filteredCameras.length} Active ({activeCameras.length} on page)</b></span>
            <span>Page: <b style={{ color: '#06b6d4' }}>{effectivePage} / {totalPages}</b></span>
            <span>WAN Bandwidth: <b style={{ color: '#f59e0b' }}>{(activeCameras.length * 2.8).toFixed(1)} Mbps</b></span>
          </div>


          {/* Refresh Button */}
          <button
            onClick={fetchCameras}
            disabled={loading}
            style={{
              background: 'rgba(6, 182, 212, 0.15)',
              border: '1px solid #06b6d4',
              color: '#06b6d4',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '11px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            SYNC TOPOLOGY
          </button>
        </div>
      </div>

      {/* Main 3x3 Video Grid */}
      <div
        style={{
          flex: 1,
          padding: '16px',
          overflowY: 'auto',
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gridTemplateRows: 'repeat(3, 1fr)',
          gap: '12px',
          minHeight: 0,
        }}
      >
        {activeCameras.map((cam) => {
          const camId = cam.id || cam.camera_id;
          const camName = cam.name || `Camera ${camId}`;
          const city = cam.location?.city || cam.city || 'Gujarat';
          const codec = (cam.codec || 'H.264').toUpperCase();

          // Construct Dynamic HLS Endpoint from gateway proxy
          const hlsUrl = (cam.hls_url && !cam.hls_url.includes('cctv.corp8.cloud')) ? cam.hls_url : `/api/cameras/${camId}/hls/index.m3u8`;

          return (
            <div
              key={camId}
              style={{
                position: 'relative',
                borderRadius: '8px',
                overflow: 'hidden',
                boxShadow: '0 4px 16px rgba(0, 0, 0, 0.5)',
                transition: 'transform 0.15s, box-shadow 0.15s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = '0 0 20px rgba(6, 182, 212, 0.4)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = '0 4px 16px rgba(0, 0, 0, 0.5)';
              }}
            >
              <GridPlayer
                streamUrl={hlsUrl}
                cameraId={camId}
                cameraName={camName}
                city={city}
                codec={codec}
                resolution={cam.resolution}
                liveStatus={cam.live_status || (cam.status === 'online' ? 'LIVE' : 'UNKNOWN')}
                streamHealth={cam.stream_health}
                locationAvailable={cam.location_available ?? (cam.latitude != null && cam.longitude != null)}
                onClick={() => setFocusedCamera(cam)}
              />

              {/* Click-to-Inspect Hint Badge */}
              <div
                onClick={() => setFocusedCamera(cam)}
                style={{
                  position: 'absolute',
                  top: '8px',
                  right: '8px',
                  background: 'rgba(0, 0, 0, 0.6)',
                  borderRadius: '4px',
                  padding: '3px 6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontSize: '9px',
                  fontWeight: 700,
                  color: '#38bdf8',
                  cursor: 'pointer',
                  border: '1px solid rgba(6, 182, 212, 0.3)',
                  zIndex: 2,
                }}
              >
                <Eye size={10} />
                INSPECT (WHEP)
              </div>
            </div>
          );
        })}

        {/* Empty State / Loading State */}
        {activeCameras.length === 0 && !loading && (
          <div
            style={{
              gridColumn: '1 / -1',
              gridRow: '1 / -1',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'rgba(15, 23, 42, 0.4)',
              borderRadius: '8px',
              border: '1px dashed rgba(255, 255, 255, 0.15)',
              padding: '32px',
            }}
          >
            <AlertCircle size={32} color="#f59e0b" />
            <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '12px' }}>
              No Active Camera Feeds Discovered
            </div>
            <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
              Verify connectivity to /api/cameras
            </div>
            <button
              onClick={fetchCameras}
              style={{
                marginTop: '16px',
                background: '#06b6d4',
                border: 'none',
                color: '#090d16',
                padding: '8px 16px',
                borderRadius: '6px',
                fontWeight: 700,
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              Retry Discovery
            </button>
          </div>
        )}
      </div>

      {/* Pagination Controls Bar */}
      {totalPages > 1 && (
        <div
          className="glass-panel"
          style={{
            padding: '10px 24px',
            borderTop: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexShrink: 0,
            background: 'rgba(10, 14, 20, 0.95)',
          }}
        >
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>
            Showing feeds <b style={{ color: '#f8fafc' }}>{startIndex + 1} - {Math.min(startIndex + pageSize, filteredCameras.length)}</b> of <b style={{ color: '#06b6d4' }}>{filteredCameras.length}</b> total cameras
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={effectivePage <= 1}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 14px',
                borderRadius: '6px',
                background: effectivePage <= 1 ? 'rgba(255, 255, 255, 0.04)' : 'rgba(6, 182, 212, 0.15)',
                border: '1px solid',
                borderColor: effectivePage <= 1 ? 'rgba(255, 255, 255, 0.1)' : '#06b6d4',
                color: effectivePage <= 1 ? '#64748b' : '#06b6d4',
                fontSize: '12px',
                fontWeight: 700,
                cursor: effectivePage <= 1 ? 'not-allowed' : 'pointer',
              }}
            >
              <ChevronLeft size={14} />
              PREVIOUS
            </button>

            {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
              <button
                key={page}
                onClick={() => setCurrentPage(page)}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '6px',
                  background: effectivePage === page ? '#06b6d4' : 'rgba(15, 23, 42, 0.8)',
                  border: '1px solid',
                  borderColor: effectivePage === page ? '#06b6d4' : 'rgba(255, 255, 255, 0.15)',
                  color: effectivePage === page ? '#04101e' : '#f8fafc',
                  fontSize: '12px',
                  fontWeight: 800,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {page}
              </button>
            ))}

            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={effectivePage >= totalPages}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 14px',
                borderRadius: '6px',
                background: effectivePage >= totalPages ? 'rgba(255, 255, 255, 0.04)' : 'rgba(6, 182, 212, 0.15)',
                border: '1px solid',
                borderColor: effectivePage >= totalPages ? 'rgba(255, 255, 255, 0.1)' : '#06b6d4',
                color: effectivePage >= totalPages ? '#64748b' : '#06b6d4',
                fontSize: '12px',
                fontWeight: 700,
                cursor: effectivePage >= totalPages ? 'not-allowed' : 'pointer',
              }}
            >
              NEXT
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Focus Inspection Modal: Low-Latency WebRTC (WHEP) Feed */}
      {focusedCamera && (
        <FocusPlayer
          camera={focusedCamera}
          onClose={() => setFocusedCamera(null)}
        />
      )}
    </div>
  );
}

