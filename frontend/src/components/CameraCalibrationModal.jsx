import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Ruler,
  Shield,
  Layers,
  Crosshair,
  Info,
  CheckSquare,
  Square,
} from 'lucide-react';
import Hls from 'hls.js';

const POINT_DEFINITIONS = [
  { label: 'P1: Top-Left (Far-Left curb/lane line)', color: '#10b981' },
  { label: 'P2: Top-Right (Far-Right curb/lane line)', color: '#06b6d4' },
  { label: 'P3: Bottom-Right (Near-Right curb/lane line)', color: '#3b82f6' },
  { label: 'P4: Bottom-Left (Near-Left curb/lane line)', color: '#8b5cf6' },
];

export default function CameraCalibrationModal({ camera, onClose, onCalibrationUpdated }) {
  const videoRef = useRef(null);
  const containerRef = useRef(null);
  const hlsRef = useRef(null);

  const camId = camera?.camera_id || camera?.id || '';
  const camName = camera?.name || (camId ? `Camera ${camId}` : 'Surveillance Feed');

  // State
  const [points, setPoints] = useState([]); // [{u, v}]
  const [realWidth, setRealWidth] = useState(''); // Explicit operator physical measurement (no defaults)
  const [realLength, setRealLength] = useState(''); // Explicit operator physical measurement (no defaults)
  const [activeCalibration, setActiveCalibration] = useState(null);
  const [loading, setLoading] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const [statusMessage, setStatusMessage] = useState(null);
  const [nativeDims, setNativeDims] = useState({ width: 1920, height: 1080 });
  const [operatorConfirmed, setOperatorConfirmed] = useState(false);
  const [checklistOpen, setChecklistOpen] = useState(true);

  // 1. Fetch current calibration if present
  useEffect(() => {
    fetchCalibration();
  }, [camId]);

  const fetchCalibration = async () => {
    try {
      const res = await fetch(`/api/cameras/${camId}/calibration`);
      if (res.ok) {
        const data = await res.json();
        setActiveCalibration(data);
        if (data.ground_plane_points && data.ground_plane_points.length === 4) {
          setPoints(data.ground_plane_points.map(([u, v]) => ({ u, v })));
        }
        if (data.real_width_meters) setRealWidth(String(data.real_width_meters));
        if (data.real_length_meters) setRealLength(String(data.real_length_meters));
      } else {
        setActiveCalibration(null);
      }
    } catch (e) {
      console.warn('[Calibration] Could not load active calibration:', e);
      setActiveCalibration(null);
    }
  };

  // 2. Attach live HLS stream for cam01
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const hlsUrl = camera?.hls_url || `/api/cameras/${camId}/hls/index.m3u8`;

    if (Hls.isSupported()) {
      const hls = new Hls({ enableWorker: false, lowLatencyMode: true });
      hls.loadSource(hlsUrl);
      hls.attachMedia(video);
      hlsRef.current = hls;
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (data.fatal) {
          console.warn('[Calibration HLS] Stream reconnecting:', data.details);
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              hls.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls.recoverMediaError();
              break;
            default:
              break;
          }
        }
      });
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = hlsUrl;
      video.play().catch(() => {});
    }

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [camId, camera?.hls_url]);

  // Handle canvas click to place exactly 4 points in order
  const handleOverlayClick = (e) => {
    if (points.length >= 4) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    // Map client coordinates to dynamic native frame coordinates
    const curW = nativeDims.width > 0 ? nativeDims.width : 1920.0;
    const curH = nativeDims.height > 0 ? nativeDims.height : 1080.0;
    const scaleX = curW / rect.width;
    const scaleY = curH / rect.height;

    const u = Math.round(clickX * scaleX);
    const v = Math.round(clickY * scaleY);

    // Duplicate/Invalid point prevention: minimum distance check (25px)
    for (let i = 0; i < points.length; i++) {
      const dist = Math.hypot(points[i].u - u, points[i].v - v);
      if (dist < 25.0) {
        setStatusMessage({
          type: 'error',
          text: `Point too close to existing Point ${i + 1} (${Math.round(dist)}px distance). Please select distinct road vertices.`,
        });
        return;
      }
    }

    setPoints([...points, { u, v }]);
    setValidationResult(null);
    setOperatorConfirmed(false);
    setStatusMessage(null);
  };

  const handleResetPoints = () => {
    setPoints([]);
    setValidationResult(null);
    setOperatorConfirmed(false);
    setStatusMessage(null);
  };

  // 3. Validate calibration geometry & condition
  const handleValidate = async () => {
    if (points.length !== 4) {
      setStatusMessage({ type: 'error', text: 'Please click exactly 4 corner points on the road surface.' });
      return;
    }
    const w = parseFloat(realWidth);
    const l = parseFloat(realLength);
    if (!realWidth || isNaN(w) || w <= 0 || !realLength || isNaN(l) || l <= 0) {
      setStatusMessage({
        type: 'error',
        text: 'Physical road width and length must be explicitly measured and entered as positive numbers (> 0 meters). Assumed or estimated values are strictly prohibited.',
      });
      return;
    }

    setLoading(true);
    setStatusMessage(null);
    try {
      const payload = {
        ground_plane_points: points.map((p) => [p.u, p.v]),
        real_width_meters: w,
        real_length_meters: l,
        calibrated_by: 'FIELD_OPERATOR',
      };
      const res = await fetch(`/api/cameras/${camId}/calibration/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setValidationResult(data);
      if (data.valid) {
        setStatusMessage({
          type: 'success',
          text: `Valid planar quad. Homography matrix computed (${Math.round(data.polygon_area_px)} px² road deck coverage). Review summary below to confirm.`,
        });
      } else {
        setStatusMessage({ type: 'error', text: data.message || 'Invalid quadrilateral geometry.' });
      }
    } catch (err) {
      setStatusMessage({ type: 'error', text: `Validation request error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // 4. Save and activate calibration after explicit confirmation
  const handleSave = async () => {
    if (points.length !== 4) {
      setStatusMessage({ type: 'error', text: 'Exactly 4 points required before activation.' });
      return;
    }
    const w = parseFloat(realWidth);
    const l = parseFloat(realLength);
    if (!realWidth || isNaN(w) || w <= 0 || !realLength || isNaN(l) || l <= 0) {
      setStatusMessage({
        type: 'error',
        text: 'Physical road width and length must be explicitly measured on-site (> 0 meters).',
      });
      return;
    }
    if (!operatorConfirmed) {
      setStatusMessage({
        type: 'error',
        text: 'You must check the certification box confirming on-site measurement before activating calibration.',
      });
      return;
    }

    setLoading(true);
    try {
      const payload = {
        ground_plane_points: points.map((p) => [p.u, p.v]),
        real_width_meters: w,
        real_length_meters: l,
        calibrated_by: 'FIELD_OPERATOR',
      };
      const res = await fetch(`/api/cameras/${camId}/calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to activate calibration');
      }
      const data = await res.json();
      setActiveCalibration(data);
      setStatusMessage({
        type: 'success',
        text: `Physical speed calibration successfully activated for ${camId.toUpperCase()}. Speed outputs are now calibrated.`,
      });
      if (onCalibrationUpdated) onCalibrationUpdated(camId, true);
    } catch (err) {
      setStatusMessage({ type: 'error', text: `Activation failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // 5. Deactivate calibration
  const handleClear = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/cameras/${camId}/calibration`, { method: 'DELETE' });
      if (res.ok) {
        setActiveCalibration(null);
        setPoints([]);
        setValidationResult(null);
        setOperatorConfirmed(false);
        setStatusMessage({
          type: 'info',
          text: `Calibration for ${camId.toUpperCase()} deactivated. Physical speed output is locked to CALIBRATION_REQUIRED.`,
        });
        if (onCalibrationUpdated) onCalibrationUpdated(camId, false);
      }
    } catch (err) {
      setStatusMessage({ type: 'error', text: `Deactivation failed: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(5, 8, 16, 0.92)',
        backdropFilter: 'blur(12px)',
        zIndex: 2500,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '1150px',
          maxHeight: '94vh',
          display: 'flex',
          flexDirection: 'column',
          background: '#0a0f1d',
          border: '1px solid #1e293b',
          borderRadius: '12px',
          overflow: 'hidden',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.8)',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid #1e293b',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: '#0f172a',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <Crosshair size={22} color="#06b6d4" />
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontWeight: '800', fontSize: '15px', color: '#f8fafc', letterSpacing: '0.5px' }}>
                  FIELD CALIBRATION CONSOLE — {camId.toUpperCase()}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    fontWeight: '800',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    background: activeCalibration?.is_active ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                    color: activeCalibration?.is_active ? '#10b981' : '#f59e0b',
                    border: activeCalibration?.is_active ? '1px solid #10b981' : '1px solid #f59e0b',
                  }}
                >
                  {activeCalibration?.is_active ? 'CALIBRATED' : 'CALIBRATION REQUIRED'}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                {camName} • Live HLS Feed • Planar Homography Metric Ground Calibration
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              padding: '6px',
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: '16px 20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {/* Requirement 10: Mandatory Physical Warning */}
          <div
            style={{
              padding: '10px 14px',
              background: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid rgba(239, 68, 68, 0.35)',
              borderRadius: '6px',
              fontSize: '12px',
              color: '#fca5a5',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              fontWeight: '600',
            }}
          >
            <AlertTriangle size={18} color="#ef4444" style={{ flexShrink: 0 }} />
            <span>
              Enter measurements physically verified at 01 Chiman bhai Bridge. Image-based estimates are not accepted.
            </span>
          </div>

          {/* Operator-Facing Checklist Banner */}
          <div
            style={{
              background: '#0f172a',
              border: '1px solid #1e293b',
              borderRadius: '6px',
              padding: '10px 14px',
              fontSize: '11px',
              color: '#94a3b8',
            }}
          >
            <div
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
              onClick={() => setChecklistOpen(!checklistOpen)}
            >
              <div style={{ fontWeight: '700', color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Info size={14} color="#38bdf8" /> Field Operator On-Site Protocol Checklist
              </div>
              <span style={{ fontSize: '10px', color: '#64748b' }}>{checklistOpen ? '▲ Collapse' : '▼ Expand'}</span>
            </div>
            {checklistOpen && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '8px', marginTop: '8px' }}>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                  <span style={{ color: '#10b981', fontWeight: '800' }}>✓</span>
                  <span><b>Coplanar Deck</b>: Points P1–P4 must lie on the flat asphalt surface (not on parapets or sidewalks).</span>
                </div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                  <span style={{ color: '#10b981', fontWeight: '800' }}>✓</span>
                  <span><b>Ordering Rule</b>: Select in strict clockwise order: P1=Top-Left, P2=Top-Right, P3=Bottom-Right, P4=Bottom-Left.</span>
                </div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                  <span style={{ color: '#10b981', fontWeight: '800' }}>✓</span>
                  <span><b>Transverse Width (W)</b>: Measure physical distance across deck lanes with surveyor wheel or laser meter.</span>
                </div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                  <span style={{ color: '#10b981', fontWeight: '800' }}>✓</span>
                  <span><b>Longitudinal Span (L)</b>: Measure physical distance between fixed bridge landmarks along traffic flow.</span>
                </div>
              </div>
            )}
          </div>

          {/* Interactive Live Video + Canvas Overlay */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
              <span style={{ color: '#cbd5e1', fontWeight: '600' }}>
                {points.length < 4 ? (
                  <span style={{ color: POINT_DEFINITIONS[points.length]?.color }}>
                    Next Action: Click <b>{POINT_DEFINITIONS[points.length]?.label}</b>
                  </span>
                ) : (
                  <span style={{ color: '#10b981' }}>
                    All 4 points placed. Validate geometry below.
                  </span>
                )}
              </span>
              <span style={{ color: '#94a3b8', fontSize: '11px' }}>
                Points Placed: <b style={{ color: '#38bdf8' }}>{points.length} / 4</b>
              </span>
            </div>

            <div
              ref={containerRef}
              onClick={handleOverlayClick}
              style={{
                position: 'relative',
                width: '100%',
                aspectRatio: '16/9',
                background: '#000',
                borderRadius: '8px',
                overflow: 'hidden',
                cursor: points.length < 4 ? 'crosshair' : 'default',
                boxShadow: 'inset 0 0 20px rgba(0,0,0,0.8)',
                border: '1px solid #1e293b',
              }}
            >
              <video
                ref={videoRef}
                muted
                playsInline
                onLoadedMetadata={() => {
                  if (videoRef.current?.videoWidth > 0 && videoRef.current?.videoHeight > 0) {
                    setNativeDims({
                      width: videoRef.current.videoWidth,
                      height: videoRef.current.videoHeight,
                    });
                  }
                }}
                style={{ width: '100%', height: '100%', objectFit: 'contain', pointerEvents: 'none' }}
              />

              {/* SVG Overlay */}
              <svg
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  pointerEvents: 'none',
                }}
                viewBox={`0 0 ${nativeDims.width} ${nativeDims.height}`}
              >
                {/* Connecting Polygon */}
                {points.length >= 2 && (
                  <polygon
                    points={points.map((p) => `${p.u},${p.v}`).join(' ')}
                    fill={points.length === 4 ? 'rgba(16, 185, 129, 0.22)' : 'rgba(56, 189, 248, 0.15)'}
                    stroke={points.length === 4 ? '#10b981' : '#38bdf8'}
                    strokeWidth="3"
                    strokeDasharray={points.length === 4 ? 'none' : '8,5'}
                  />
                )}

                {/* Point Markers */}
                {points.map((pt, idx) => (
                  <g key={idx}>
                    <circle
                      cx={pt.u}
                      cy={pt.v}
                      r="12"
                      fill={POINT_DEFINITIONS[idx]?.color || '#fff'}
                      stroke="#ffffff"
                      strokeWidth="2.5"
                    />
                    <text
                      x={pt.u}
                      y={pt.v + 4}
                      fill="#000000"
                      fontSize="11"
                      fontWeight="900"
                      textAnchor="middle"
                    >
                      {idx + 1}
                    </text>
                    <text
                      x={pt.u + 16}
                      y={pt.v + 5}
                      fill="#ffffff"
                      fontSize="13"
                      fontWeight="700"
                      stroke="#000000"
                      strokeWidth="0.8"
                    >
                      P{idx + 1} ({pt.u}, {pt.v})
                    </text>
                  </g>
                ))}
              </svg>
            </div>
          </div>

          {/* Coordinates Inspection Strip */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '8px',
              background: '#0d131f',
              padding: '8px 12px',
              borderRadius: '6px',
              border: '1px solid #1e293b',
            }}
          >
            {[0, 1, 2, 3].map((idx) => (
              <div key={idx} style={{ fontSize: '11px' }}>
                <span style={{ color: POINT_DEFINITIONS[idx]?.color, fontWeight: '700' }}>P{idx + 1}: </span>
                {points[idx] ? (
                  <span style={{ fontFamily: 'monospace', color: '#f8fafc' }}>
                    ({points[idx].u}, {points[idx].v})
                  </span>
                ) : (
                  <span style={{ color: '#64748b', fontStyle: 'italic' }}>Pending click...</span>
                )}
              </div>
            ))}
          </div>

          {/* Controls & Dimensions Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr auto',
              gap: '12px',
              alignItems: 'end',
            }}
          >
            <div
              style={{
                background: '#111827',
                padding: '12px 14px',
                borderRadius: '8px',
                border: '1px solid #1e293b',
              }}
            >
              <label style={{ fontSize: '12px', fontWeight: '700', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>
                Measured Road Width (Meters)
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Ruler size={16} color="#06b6d4" />
                <input
                  type="number"
                  step="0.01"
                  min="0.5"
                  max="100.0"
                  placeholder="Enter measured width in meters"
                  value={realWidth}
                  onChange={(e) => {
                    setRealWidth(e.target.value);
                    setOperatorConfirmed(false);
                    setValidationResult(null);
                  }}
                  style={{
                    background: '#0a0f1d',
                    border: '1px solid #334155',
                    color: '#f8fafc',
                    padding: '7px 10px',
                    borderRadius: '4px',
                    width: '100%',
                    fontSize: '13px',
                  }}
                />
              </div>
              <span style={{ fontSize: '10px', color: '#f59e0b', fontWeight: '600' }}>* Field measurement across deck lanes</span>
            </div>

            <div
              style={{
                background: '#111827',
                padding: '12px 14px',
                borderRadius: '8px',
                border: '1px solid #1e293b',
              }}
            >
              <label style={{ fontSize: '12px', fontWeight: '700', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>
                Measured Reference Distance (Meters)
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Ruler size={16} color="#3b82f6" />
                <input
                  type="number"
                  step="0.01"
                  min="1.0"
                  max="500.0"
                  placeholder="Enter measured length in meters"
                  value={realLength}
                  onChange={(e) => {
                    setRealLength(e.target.value);
                    setOperatorConfirmed(false);
                    setValidationResult(null);
                  }}
                  style={{
                    background: '#0a0f1d',
                    border: '1px solid #334155',
                    color: '#f8fafc',
                    padding: '7px 10px',
                    borderRadius: '4px',
                    width: '100%',
                    fontSize: '13px',
                  }}
                />
              </div>
              <span style={{ fontSize: '10px', color: '#f59e0b', fontWeight: '600' }}>* Field measurement along traffic flow</span>
            </div>

            <div style={{ display: 'flex', gap: '8px', paddingBottom: '2px' }}>
              <button
                onClick={handleResetPoints}
                disabled={points.length === 0}
                style={{
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#e2e8f0',
                  padding: '9px 14px',
                  borderRadius: '4px',
                  cursor: points.length > 0 ? 'pointer' : 'not-allowed',
                  fontSize: '12px',
                  fontWeight: '700',
                  whiteSpace: 'nowrap',
                }}
              >
                Reset Points
              </button>
              {activeCalibration && (
                <button
                  onClick={handleClear}
                  disabled={loading}
                  style={{
                    background: 'rgba(239, 68, 68, 0.15)',
                    border: '1px solid #ef4444',
                    color: '#ef4444',
                    padding: '9px 14px',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: '700',
                    whiteSpace: 'nowrap',
                  }}
                >
                  Deactivate
                </button>
              )}
            </div>
          </div>

          {/* Requirement 11: Pre-Activation Calibration Summary */}
          {validationResult && validationResult.valid && (
            <div
              style={{
                background: '#0f172a',
                border: '1px solid #10b981',
                borderRadius: '8px',
                padding: '12px 16px',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
              }}
            >
              <div style={{ fontSize: '12px', fontWeight: '800', color: '#10b981', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={16} />
                CALIBRATION SUMMARY (Review Before Activation)
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px', fontSize: '11px', color: '#cbd5e1' }}>
                <div>Camera ID: <b style={{ color: '#ffffff' }}>{camId}</b></div>
                <div>Physical Deck Width: <b style={{ color: '#06b6d4' }}>{realWidth} meters</b></div>
                <div>Physical Longitudinal Span: <b style={{ color: '#3b82f6' }}>{realLength} meters</b></div>
                <div>Image Deck Coverage: <b style={{ color: '#10b981' }}>{Math.round(validationResult.polygon_area_px)} px²</b></div>
              </div>

              {/* Homography Matrix View */}
              {validationResult.homography_matrix && (
                <div style={{ marginTop: '4px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>Calculated Homography Matrix H (3×3):</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px', maxWidth: '420px', fontFamily: 'monospace', fontSize: '10px' }}>
                    {validationResult.homography_matrix.map((row, rIdx) =>
                      row.map((val, cIdx) => (
                        <div key={`${rIdx}-${cIdx}`} style={{ background: '#0a0f1d', padding: '4px', textAlign: 'right', borderRadius: '3px', border: '1px solid #1e293b', color: '#38bdf8' }}>
                          {typeof val === 'number' ? val.toFixed(6) : val}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* Requirement 12: Explicit Operator Confirmation */}
              <div
                onClick={() => setOperatorConfirmed(!operatorConfirmed)}
                style={{
                  marginTop: '8px',
                  padding: '8px 12px',
                  background: operatorConfirmed ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.12)',
                  border: operatorConfirmed ? '1px solid #10b981' : '1px solid #f59e0b',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  cursor: 'pointer',
                  fontSize: '12px',
                  color: '#f8fafc',
                  fontWeight: '600',
                }}
              >
                {operatorConfirmed ? <CheckSquare size={18} color="#10b981" /> : <Square size={18} color="#f59e0b" />}
                <span>
                  I confirm that P1–P4 lie on the flat road deck of 01 Chiman bhai Bridge and that width ({realWidth}m) and length ({realLength}m) were physically measured on-site.
                </span>
              </div>
            </div>
          )}

          {/* Status Alert Banner */}
          {statusMessage && (
            <div
              style={{
                padding: '10px 14px',
                borderRadius: '6px',
                fontSize: '12px',
                fontWeight: '600',
                background:
                  statusMessage.type === 'success'
                    ? 'rgba(16, 185, 129, 0.15)'
                    : statusMessage.type === 'error'
                    ? 'rgba(239, 68, 68, 0.15)'
                    : 'rgba(59, 130, 246, 0.15)',
                color:
                  statusMessage.type === 'success'
                    ? '#10b981'
                    : statusMessage.type === 'error'
                    ? '#ef4444'
                    : '#38bdf8',
                border:
                  statusMessage.type === 'success'
                    ? '1px solid #10b981'
                    : statusMessage.type === 'error'
                    ? '1px solid #ef4444'
                    : '1px solid #38bdf8',
              }}
            >
              {statusMessage.text}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid #1e293b',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '12px',
            background: '#0f172a',
          }}
        >
          <button
            onClick={handleValidate}
            disabled={points.length !== 4 || loading}
            style={{
              background: '#1e293b',
              border: '1px solid #38bdf8',
              color: '#38bdf8',
              padding: '8px 18px',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: '700',
              cursor: points.length === 4 && !loading ? 'pointer' : 'not-allowed',
              opacity: points.length === 4 ? 1 : 0.5,
            }}
          >
            Validate Geometry
          </button>
          <button
            onClick={handleSave}
            disabled={points.length !== 4 || !validationResult?.valid || !operatorConfirmed || loading}
            style={{
              background:
                operatorConfirmed && validationResult?.valid
                  ? 'linear-gradient(135deg, #059669, #10b981)'
                  : '#334155',
              border: 'none',
              color: '#ffffff',
              padding: '8px 22px',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: '800',
              cursor:
                points.length === 4 && validationResult?.valid && operatorConfirmed && !loading
                  ? 'pointer'
                  : 'not-allowed',
              boxShadow:
                operatorConfirmed && validationResult?.valid
                  ? '0 0 15px rgba(16, 185, 129, 0.4)'
                  : 'none',
              opacity: operatorConfirmed && validationResult?.valid ? 1 : 0.5,
            }}
          >
            Save & Activate Calibration
          </button>
        </div>
      </div>
    </div>
  );
}
