import React, { useState, useEffect, useRef } from 'react';
import { X, Video, Radio, Cpu, Activity, Shield, Maximize2, RefreshCw } from 'lucide-react';
import Hls from 'hls.js';

export default function CameraInspectionModal({ camera, onClose }) {
  const [protocol, setProtocol] = useState('HLS'); // 'HLS' | 'WHEP'
  const [connectionState, setConnectionState] = useState('CONNECTING'); // 'CONNECTING' | 'LIVE' | 'DEGRADED' | 'OFFLINE'
  const [streamFps, setStreamFps] = useState(null);
  const [streamBitrate, setStreamBitrate] = useState(null);
  const [latencyMs, setLatencyMs] = useState(null);

  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const pcRef = useRef(null);

  if (!camera) return null;

  const props = camera.properties || camera || {};
  const coords = camera.geometry?.coordinates || (camera.latitude != null && camera.longitude != null ? [camera.longitude, camera.latitude] : null);
  const camId = props.camera_id || props.id || 'CAM_UNKNOWN';
  const camName = props.name || props.camera_name || 'Gujarat Highway Surveillance Node';
  const city = props.city || (props.location_available ? 'Gujarat' : 'LOCATION UNAVAILABLE');
  const codec = (props.codec || (camId.toLowerCase().includes('ptz') ? 'H.265' : 'H.264')).toUpperCase();

  // Authoritative Gateway stream endpoints (Zero RTSP credentials exposed)
  const whepUrl = props.whep_url || (camId ? `/api/cameras/${camId}/whep` : '');
  const hlsUrl = (props.hls_url && !props.hls_url.includes('cctv.corp8.cloud')) ? props.hls_url : `/api/cameras/${camId}/hls/index.m3u8`;

  // Attach live video playback
  useEffect(() => {
    let isCancelled = false;
    setConnectionState('CONNECTING');

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    if (protocol === 'HLS') {
      if (Hls.isSupported() && hlsUrl && videoRef.current) {
        const hls = new Hls({ enableWorker: true, lowLatencyMode: true });
        hlsRef.current = hls;
        hls.loadSource(hlsUrl);
        hls.attachMedia(videoRef.current);

        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          if (videoRef.current) {
            videoRef.current.play().catch(() => {});
          }
          if (!isCancelled) setConnectionState('LIVE');
        });

        hls.on(Hls.Events.ERROR, (_evt, data) => {
          if (data && (data.details === 'manifestLoadError' || data.response?.code === 403 || data.response?.code === 404)) {
            try {
              hls.destroy();
              hlsRef.current = null;
            } catch (e) {}
            if (videoRef.current) {
              videoRef.current.src = `/api/cameras/${camId}/video`;
              videoRef.current.muted = true;
              videoRef.current.play().catch(() => {});
              if (!isCancelled) setConnectionState('LIVE');
            }
          } else if (!isCancelled) {
            setConnectionState('DEGRADED');
          }
        });
      } else if (videoRef.current && videoRef.current.canPlayType('application/vnd.apple.mpegurl')) {
        videoRef.current.src = hlsUrl;
        videoRef.current.onplaying = () => {
          if (!isCancelled) setConnectionState('LIVE');
        };
        videoRef.current.onerror = () => {
          if (videoRef.current) {
            videoRef.current.src = `/api/cameras/${camId}/video`;
            videoRef.current.muted = true;
            videoRef.current.play().catch(() => {});
            if (!isCancelled) setConnectionState('LIVE');
          } else if (!isCancelled) {
            setConnectionState('DEGRADED');
          }
        };
      } else if (videoRef.current) {
        videoRef.current.src = `/api/cameras/${camId}/video`;
        videoRef.current.muted = true;
        videoRef.current.play().catch(() => {});
        if (!isCancelled) setConnectionState('LIVE');
      }
    } else if (protocol === 'WHEP') {
      async function initWhep() {
        try {
          const pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
          });
          pcRef.current = pc;
          pc.addTransceiver('video', { direction: 'recvonly' });

          pc.ontrack = (event) => {
            if (videoRef.current && event.streams[0]) {
              videoRef.current.srcObject = event.streams[0];
              if (!isCancelled) setConnectionState('LIVE');
            }
          };

          pc.onconnectionstatechange = () => {
            if (isCancelled) return;
            if (pc.connectionState === 'connected') setConnectionState('LIVE');
            else if (pc.connectionState === 'failed') setConnectionState('DEGRADED');
          };

          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);

          const res = await fetch(whepUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/sdp' },
            body: offer.sdp,
          });

          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const answer = await res.text();
          if (!isCancelled && pc.signalingState !== 'closed') {
            await pc.setRemoteDescription(new RTCSessionDescription({ type: 'answer', sdp: answer }));
          }
        } catch (e) {
          console.warn(`[WHEP] Inspection session notice for ${camId}:`, e.message);
          if (!isCancelled) setConnectionState('DEGRADED');
        }
      }
      initWhep();
    }

    return () => {
      isCancelled = true;
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      if (pcRef.current) {
        pcRef.current.close();
        pcRef.current = null;
      }
    };
  }, [camId, protocol, hlsUrl, whepUrl]);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(5, 8, 16, 0.85)',
        backdropFilter: 'blur(12px)',
        zIndex: 2000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
      onClick={onClose}
    >
      <div
        className="glass-panel"
        style={{
          width: '880px',
          maxWidth: '95vw',
          borderRadius: '12px',
          border: '1px solid rgba(6, 182, 212, 0.4)',
          boxShadow: '0 0 40px rgba(6, 182, 212, 0.25)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          background: '#090e17',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'rgba(15, 23, 42, 0.6)',
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
              <div style={{ fontSize: '15px', fontWeight: 800, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
                {camName}
                <span
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: connectionState === 'LIVE' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                    color: connectionState === 'LIVE' ? '#10b981' : '#f59e0b',
                    border: `1px solid ${connectionState === 'LIVE' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(245, 158, 11, 0.4)'}`,
                    fontWeight: 700,
                  }}
                >
                  {connectionState}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: 'rgba(56, 189, 248, 0.2)',
                    color: '#38bdf8',
                  }}
                >
                  {codec}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                ID: <span style={{ fontFamily: 'monospace', color: '#06b6d4' }}>{camId}</span> • District: <b>{city}</b> • Coordinates: {coords ? `[${coords[1].toFixed(4)}, ${coords[0].toFixed(4)}]` : 'LOCATION UNAVAILABLE'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {/* Protocol Switcher */}
            <div style={{ display: 'flex', gap: '4px', background: 'rgba(0,0,0,0.4)', padding: '3px', borderRadius: '6px' }}>
              <button
                onClick={() => setProtocol('HLS')}
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  border: 'none',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  background: protocol === 'HLS' ? '#06b6d4' : 'transparent',
                  color: protocol === 'HLS' ? '#0a0d14' : '#94a3b8',
                }}
              >
                HLS Stream
              </button>
              <button
                onClick={() => setProtocol('WHEP')}
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  border: 'none',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  background: protocol === 'WHEP' ? '#06b6d4' : 'transparent',
                  color: protocol === 'WHEP' ? '#0a0d14' : '#94a3b8',
                }}
              >
                WebRTC (/whep)
              </button>
            </div>

            <button
              onClick={onClose}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '6px',
                color: '#94a3b8',
                padding: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Real Live Video Canvas Container */}
        <div
          style={{
            position: 'relative',
            width: '100%',
            height: '420px',
            background: '#000000',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
          }}
        >
          {/* Actual Video Element */}
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'contain',
            }}
          />

          {/* CRT Scanline Layer */}
          <div className="crt-scanlines pointer-events-none absolute inset-0 opacity-20" />

          {/* Video Stream Feed Metadata Overlay */}
          <div
            style={{
              position: 'absolute',
              top: '16px',
              left: '16px',
              background: 'rgba(0, 0, 0, 0.75)',
              padding: '6px 12px',
              borderRadius: '6px',
              fontFamily: 'monospace',
              fontSize: '11px',
              color: '#38bdf8',
              border: '1px solid rgba(6, 182, 212, 0.3)',
              pointerEvents: 'none',
            }}
          >
            <div>PROTOCOL: <b style={{ color: '#ffffff' }}>{protocol}</b></div>
            <div>ENDPOINT: <b style={{ color: '#10b981' }}>{protocol === 'WHEP' ? whepUrl : hlsUrl}</b></div>
            <div>STATUS: <b style={{ color: connectionState === 'LIVE' ? '#10b981' : '#f59e0b' }}>{connectionState}</b></div>
          </div>

          {/* Top Right Latency Indicator */}
          <div
            style={{
              position: 'absolute',
              top: '16px',
              right: '16px',
              background: 'rgba(0, 0, 0, 0.75)',
              padding: '6px 12px',
              borderRadius: '6px',
              fontFamily: 'monospace',
              fontSize: '11px',
              color: '#10b981',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              pointerEvents: 'none',
            }}
          >
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: connectionState === 'LIVE' ? '#10b981' : '#64748b', boxShadow: connectionState === 'LIVE' ? '0 0 8px #10b981' : 'none' }} />
            <span>GLASS-TO-GLASS: <b>{latencyMs != null ? `${latencyMs} ms` : 'UNAVAILABLE'}</b></span>
          </div>
        </div>

        {/* Bottom Telemetry Footer */}
        <div
          style={{
            padding: '14px 20px',
            background: 'rgba(15, 23, 42, 0.8)',
            borderTop: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '12px',
          }}
        >
          <div style={{ display: 'flex', gap: '20px' }}>
            <span>Framerate: <b style={{ color: '#38bdf8' }}>{streamFps != null ? `${streamFps} FPS` : 'UNAVAILABLE'}</b></span>
            <span>Bitrate: <b style={{ color: '#f59e0b' }}>{streamBitrate || 'UNAVAILABLE'}</b></span>
            <span>Codec Profile: <b style={{ color: '#10b981' }}>{codec}</b></span>
            <span>Ingest Source: <b style={{ color: '#a855f7' }}>cctv.corp8.cloud</b></span>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={onClose}
              style={{
                background: '#06b6d4',
                border: 'none',
                color: '#0a0d14',
                padding: '6px 14px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 800,
                cursor: 'pointer',
              }}
            >
              CLOSE
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
