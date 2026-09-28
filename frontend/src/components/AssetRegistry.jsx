import React, { useState, useEffect, useCallback } from 'react';
import {
  Shield,
  Search,
  Filter,
  Plus,
  Upload,
  Download,
  RefreshCw,
  MapPin,
  Video,
  Wrench,
  Clock,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Eye,
  Edit3,
  Layers,
  FileSpreadsheet,
  FileText,
  Sliders,
  ChevronLeft,
  ChevronRight,
  Database,
  Building2,
  Calendar,
  Lock,
  UserCheck,
  Info,
  X
} from 'lucide-react';

const USER_ROLES = [
  { id: 'SUPER_ADMIN', name: 'Super Admin (Statewide)', badgeColor: '#8b5cf6' },
  { id: 'DEPARTMENT_ADMIN', name: 'Department Admin', badgeColor: '#3b82f6' },
  { id: 'OPERATOR', name: 'Operator', badgeColor: '#10b981' },
  { id: 'VIEWER', name: 'Viewer (Read Only)', badgeColor: '#64748b' },
  { id: 'AUDITOR', name: 'Auditor (Vigilance)', badgeColor: '#f59e0b' }
];

export default function AssetRegistry({ onViewLiveCamera, onSelectCameraForGis }) {
  // Current RBAC Role
  const [currentRole, setCurrentRole] = useState('SUPER_ADMIN');
  const [activeTab, setActiveTab] = useState('registry'); // 'registry' | 'coverage' | 'ageing' | 'maintenance' | 'departments' | 'audit'

  // Data states
  const [cameras, setCameras] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [kpis, setKpis] = useState(null);
  const [departments, setDepartments] = useState([]);

  // Search & Filters
  const [search, setSearch] = useState('');
  const [deptFilter, setDeptFilter] = useState('');
  const [districtFilter, setDistrictFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [opStatusFilter, setOpStatusFilter] = useState('');
  const [healthFilter, setHealthFilter] = useState('');
  const [gisFilter, setGisFilter] = useState('all'); // 'all' | 'mapped' | 'unmapped'

  // Modals & Panels
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [showMaintenanceModal, setShowMaintenanceModal] = useState(false);
  const [maintenanceCameraId, setMaintenanceCameraId] = useState('');
  const [feedbackMsg, setFeedbackMsg] = useState(null);

  // Sub-tab Data
  const [maintenanceTickets, setMaintenanceTickets] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [ageingReport, setAgeingReport] = useState(null);
  const [coverageData, setCoverageData] = useState(null);
  const [gapData, setGapData] = useState(null);
  const [ageingYoungYears, setAgeingYoungYears] = useState(3.0);
  const [ageingOldYears, setAgeingOldYears] = useState(5.0);

  const getAuthHeaders = useCallback(() => {
    return {
      'X-User-Role': currentRole,
      'X-User-Name': currentRole === 'SUPER_ADMIN' ? 'admin' : currentRole.toLowerCase(),
      'X-User-Id': `USR_${currentRole}`
    };
  }, [currentRole]);

  // 1. Fetch KPIs
  const fetchKpis = useCallback(async () => {
    try {
      const res = await fetch('/api/registry/analytics/kpis', { headers: getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        setKpis(data);
      }
    } catch (e) {
      console.error('Failed to fetch KPIs', e);
    }
  }, [getAuthHeaders]);

  // 2. Fetch Departments
  const fetchDepartments = useCallback(async () => {
    try {
      const res = await fetch('/api/registry/departments', { headers: getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        setDepartments(data);
      }
    } catch (e) {
      console.error('Failed to fetch departments', e);
    }
  }, [getAuthHeaders]);

  // 3. Fetch Paginated Cameras
  const fetchCameras = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString()
      });
      if (search) params.set('search', search);
      if (deptFilter) params.set('department_id', deptFilter);
      if (districtFilter) params.set('district', districtFilter);
      if (typeFilter) params.set('camera_type', typeFilter);
      if (opStatusFilter) params.set('operational_status', opStatusFilter);
      if (healthFilter) params.set('health_status', healthFilter);
      if (gisFilter === 'mapped') params.set('has_gis', 'true');
      if (gisFilter === 'unmapped') params.set('has_gis', 'false');

      const res = await fetch(`/api/registry/cameras?${params.toString()}`, {
        headers: getAuthHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        setCameras(data.items || []);
        setTotalCount(data.total || 0);
        setTotalPages(data.total_pages || 1);
      }
    } catch (e) {
      console.error('Failed to fetch cameras', e);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, deptFilter, districtFilter, typeFilter, opStatusFilter, healthFilter, gisFilter, getAuthHeaders]);

  // 4. Fetch Sub-tab data
  const fetchMaintenance = useCallback(async () => {
    try {
      const res = await fetch('/api/registry/maintenance', { headers: getAuthHeaders() });
      if (res.ok) setMaintenanceTickets(await res.json());
    } catch (e) {
      console.error(e);
    }
  }, [getAuthHeaders]);

  const fetchAudit = useCallback(async () => {
    try {
      const res = await fetch('/api/registry/audit-log?limit=100', { headers: getAuthHeaders() });
      if (res.ok) setAuditLogs(await res.json());
    } catch (e) {
      console.error(e);
    }
  }, [getAuthHeaders]);

  const fetchAgeing = useCallback(async () => {
    try {
      const res = await fetch(`/api/registry/analytics/ageing?young_years=${ageingYoungYears}&old_years=${ageingOldYears}`, {
        headers: getAuthHeaders()
      });
      if (res.ok) setAgeingReport(await res.json());
    } catch (e) {
      console.error(e);
    }
  }, [ageingYoungYears, ageingOldYears, getAuthHeaders]);

  const fetchCoverageAndGap = useCallback(async () => {
    try {
      const [covRes, gapRes] = await Promise.all([
        fetch('/api/registry/analytics/coverage', { headers: getAuthHeaders() }),
        fetch('/api/registry/analytics/gap-analysis', { headers: getAuthHeaders() })
      ]);
      if (covRes.ok) setCoverageData(await covRes.json());
      if (gapRes.ok) setGapData(await gapRes.json());
    } catch (e) {
      console.error(e);
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    fetchKpis();
    fetchDepartments();
  }, [fetchKpis, fetchDepartments]);

  useEffect(() => {
    fetchCameras();
  }, [fetchCameras]);

  useEffect(() => {
    if (activeTab === 'maintenance') fetchMaintenance();
    if (activeTab === 'audit') fetchAudit();
    if (activeTab === 'ageing') fetchAgeing();
    if (activeTab === 'coverage') fetchCoverageAndGap();
  }, [activeTab, fetchMaintenance, fetchAudit, fetchAgeing, fetchCoverageAndGap]);

  // Toggle Activation
  const handleToggleActive = async (cam) => {
    const isActivating = cam.operational_status !== 'ACTIVE';
    const endpoint = isActivating ? 'activate' : 'deactivate';
    try {
      const res = await fetch(`/api/registry/cameras/${cam.camera_id}/${endpoint}`, {
        method: 'POST',
        headers: getAuthHeaders()
      });
      if (res.ok) {
        setFeedbackMsg({ type: 'success', text: `Camera ${cam.camera_id} ${isActivating ? 'activated' : 'deactivated'} successfully.` });
        fetchCameras();
        fetchKpis();
      } else {
        const err = await res.json();
        setFeedbackMsg({ type: 'error', text: err.detail || 'Action rejected.' });
      }
    } catch (e) {
      setFeedbackMsg({ type: 'error', text: 'Network failure.' });
    }
  };

  // Catalogue Sync
  const handleSyncCatalogue = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/registry/sync-catalogue', {
        method: 'POST',
        headers: getAuthHeaders()
      });
      const data = await res.json();
      if (res.ok) {
        setFeedbackMsg({ type: 'success', text: `Catalogue sync completed: ${data.discovered_new} discovered, ${data.updated_existing} updated.` });
        fetchCameras();
        fetchKpis();
      } else {
        setFeedbackMsg({ type: 'error', text: data.detail || 'Sync failed.' });
      }
    } catch (e) {
      setFeedbackMsg({ type: 'error', text: 'Network failure.' });
    } finally {
      setLoading(false);
    }
  };

  // Export
  const handleExport = (format) => {
    const url = `/api/registry/export?format=${format}`;
    window.open(url, '_blank');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0a0d14', color: '#f8fafc', overflow: 'hidden' }}>
      {/* 1. Header Toolbar & RBAC Control */}
      <div style={{
        padding: '12px 20px',
        borderBottom: '1px solid #1e293b',
        background: 'rgba(15, 23, 42, 0.85)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '12px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Database size={20} color="#06b6d4" />
            <span style={{ fontSize: '15px', fontWeight: 800, letterSpacing: '0.05em', color: '#38bdf8' }}>
              CCTV ASSET REGISTRY & GIS MANAGEMENT
            </span>
          </div>
          <span style={{
            fontSize: '10px',
            padding: '2px 8px',
            borderRadius: '4px',
            background: 'rgba(6, 182, 212, 0.15)',
            border: '1px solid rgba(6, 182, 212, 0.3)',
            color: '#22d3ee',
            fontWeight: 700
          }}>
            MODEL 1 CERTIFIED
          </span>
        </div>

        {/* RBAC Role Switcher */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#94a3b8' }}>
            <Lock size={13} color="#a855f7" />
            <span>Active Role:</span>
          </div>
          <select
            value={currentRole}
            onChange={(e) => {
              setCurrentRole(e.target.value);
              setFeedbackMsg({ type: 'info', text: `Switched active role to ${e.target.value}. RBAC permissions updated.` });
            }}
            style={{
              background: '#1e293b',
              color: USER_ROLES.find(r => r.id === currentRole)?.badgeColor || '#fff',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '5px 10px',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer'
            }}
          >
            {USER_ROLES.map(r => (
              <option key={r.id} value={r.id} style={{ background: '#0f172a', color: '#f8fafc' }}>
                {r.name}
              </option>
            ))}
          </select>

          {/* Action Buttons */}
          {(currentRole === 'SUPER_ADMIN' || currentRole === 'DEPARTMENT_ADMIN') && (
            <>
              <button
                onClick={() => setShowAddModal(true)}
                style={{
                  background: 'linear-gradient(135deg, #06b6d4 0%, #2563eb 100%)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '6px 12px',
                  fontSize: '12px',
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  cursor: 'pointer'
                }}
              >
                <Plus size={14} /> Add Camera
              </button>

              <button
                onClick={() => setShowImportModal(true)}
                style={{
                  background: '#1e293b',
                  color: '#38bdf8',
                  border: '1px solid #334155',
                  borderRadius: '6px',
                  padding: '6px 12px',
                  fontSize: '12px',
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  cursor: 'pointer'
                }}
              >
                <Upload size={14} /> Bulk Import
              </button>
            </>
          )}

          <button
            onClick={handleSyncCatalogue}
            disabled={loading}
            title="Reconciles camera coordinates and statuses with live Gujarat catalogue"
            style={{
              background: '#1e293b',
              color: '#10b981',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              cursor: 'pointer'
            }}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Sync Feeds
          </button>

          {/* Export Dropdown */}
          <div style={{ position: 'relative', display: 'inline-block' }}>
            <button
              onClick={() => handleExport('csv')}
              style={{
                background: '#1e293b',
                color: '#f59e0b',
                border: '1px solid #334155',
                borderRadius: '6px',
                padding: '6px 10px',
                fontSize: '12px',
                fontWeight: 700,
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                cursor: 'pointer'
              }}
            >
              <Download size={14} /> Export CSV
            </button>
          </div>
          <button
            onClick={() => handleExport('excel')}
            style={{
              background: '#1e293b',
              color: '#10b981',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '6px 10px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              cursor: 'pointer'
            }}
          >
            <FileSpreadsheet size={14} /> Excel
          </button>
          <button
            onClick={() => handleExport('geojson')}
            style={{
              background: '#1e293b',
              color: '#06b6d4',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '6px 10px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              cursor: 'pointer'
            }}
          >
            <MapPin size={14} /> GeoJSON
          </button>
        </div>
      </div>

      {/* Feedback Alert Banner */}
      {feedbackMsg && (
        <div style={{
          padding: '8px 20px',
          background: feedbackMsg.type === 'error' ? 'rgba(239, 68, 68, 0.2)' : feedbackMsg.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(56, 189, 248, 0.2)',
          borderBottom: `1px solid ${feedbackMsg.type === 'error' ? '#ef4444' : feedbackMsg.type === 'success' ? '#10b981' : '#38bdf8'}`,
          color: '#f8fafc',
          fontSize: '12px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>{feedbackMsg.text}</span>
          <button onClick={() => setFeedbackMsg(null)} style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* 2. Sub-tab Navigation */}
      <div style={{
        display: 'flex',
        gap: '4px',
        padding: '8px 20px 0',
        background: '#0a0d14',
        borderBottom: '1px solid #1e293b',
        overflowX: 'auto'
      }}>
        {[
          { id: 'registry', label: 'Camera Registry', icon: Database },
          { id: 'coverage', label: 'GIS Coverage & Gaps', icon: MapPin },
          { id: 'ageing', label: 'Ageing Infrastructure', icon: Clock },
          { id: 'maintenance', label: 'Maintenance Tickets', icon: Wrench },
          { id: 'departments', label: 'Department Hierarchy', icon: Building2 },
          { id: 'audit', label: 'Immutable Audit Log', icon: Shield }
        ].map(t => {
          const Icon = t.icon;
          const isActive = activeTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{
                padding: '8px 14px',
                background: isActive ? 'rgba(6, 182, 212, 0.12)' : 'transparent',
                border: 'none',
                borderBottom: isActive ? '2px solid #06b6d4' : '2px solid transparent',
                color: isActive ? '#38bdf8' : '#94a3b8',
                fontSize: '12px',
                fontWeight: isActive ? 700 : 500,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                cursor: 'pointer',
                whiteSpace: 'nowrap'
              }}
            >
              <Icon size={14} />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* 3. Main Tab Contents */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
        {activeTab === 'registry' && (
          <>
            {/* KPI Cards (100% Database Derived) */}
            {kpis && (
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: '12px',
                marginBottom: '16px'
              }}>
                <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>Total Registered</div>
                  <div style={{ fontSize: '22px', fontWeight: 800, color: '#f8fafc', marginTop: '4px' }}>{kpis.total_cameras}</div>
                  <div style={{ fontSize: '10px', color: '#38bdf8', marginTop: '2px' }}>Active surveillance assets</div>
                </div>

                <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>Online Feeds</div>
                  <div style={{ fontSize: '22px', fontWeight: 800, color: '#10b981', marginTop: '4px' }}>{kpis.online_count}</div>
                  <div style={{ fontSize: '10px', color: '#34d399', marginTop: '2px' }}>Telemetry verified</div>
                </div>

                <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>Degraded / Offline</div>
                  <div style={{ fontSize: '22px', fontWeight: 800, color: '#ef4444', marginTop: '4px' }}>{kpis.offline_count + kpis.degraded_count}</div>
                  <div style={{ fontSize: '10px', color: '#f87171', marginTop: '2px' }}>Requiring inspection</div>
                </div>

                <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>Under Maintenance</div>
                  <div style={{ fontSize: '22px', fontWeight: 800, color: '#f59e0b', marginTop: '4px' }}>{kpis.maintenance_count}</div>
                  <div style={{ fontSize: '10px', color: '#fbbf24', marginTop: '2px' }}>Tickets in progress</div>
                </div>

                <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>GIS Mapped</div>
                  <div style={{ fontSize: '22px', fontWeight: 800, color: '#06b6d4', marginTop: '4px' }}>{kpis.gis_mapped_count}</div>
                  <div style={{ fontSize: '10px', color: '#22d3ee', marginTop: '2px' }}>Verified GPS coordinates</div>
                </div>

                <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>Unrecorded Install Date</div>
                  <div style={{ fontSize: '22px', fontWeight: 800, color: '#94a3b8', marginTop: '4px' }}>{kpis.missing_install_date_count}</div>
                  <div style={{ fontSize: '10px', color: '#64748b', marginTop: '2px' }}>Strict integrity (no fake dates)</div>
                </div>
              </div>
            )}

            {/* Filter Bar */}
            <div style={{
              background: '#111827',
              border: '1px solid #1f2937',
              borderRadius: '8px',
              padding: '12px',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '10px',
              alignItems: 'center',
              marginBottom: '16px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#1e293b', borderRadius: '6px', padding: '6px 10px', flex: '1 1 200px' }}>
                <Search size={14} color="#94a3b8" />
                <input
                  type="text"
                  placeholder="Search camera ID, name, district..."
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                  style={{ background: 'transparent', border: 'none', outline: 'none', color: '#fff', fontSize: '12px', width: '100%' }}
                />
              </div>

              {/* Department Dropdown */}
              <select
                value={deptFilter}
                onChange={(e) => { setDeptFilter(e.target.value); setPage(1); }}
                style={{ background: '#1e293b', border: '1px solid #334155', color: '#cbd5e1', borderRadius: '6px', padding: '6px 10px', fontSize: '12px' }}
              >
                <option value="">All Departments</option>
                {departments.map(d => (
                  <option key={d.id} value={d.id}>{d.name} ({d.camera_count || 0})</option>
                ))}
              </select>

              {/* District Filter */}
              <select
                value={districtFilter}
                onChange={(e) => { setDistrictFilter(e.target.value); setPage(1); }}
                style={{ background: '#1e293b', border: '1px solid #334155', color: '#cbd5e1', borderRadius: '6px', padding: '6px 10px', fontSize: '12px' }}
              >
                <option value="">All Districts</option>
                {kpis && Object.keys(kpis.by_district || {}).map(dist => (
                  <option key={dist} value={dist}>{dist} ({kpis.by_district[dist]})</option>
                ))}
              </select>

              {/* Camera Type */}
              <select
                value={typeFilter}
                onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
                style={{ background: '#1e293b', border: '1px solid #334155', color: '#cbd5e1', borderRadius: '6px', padding: '6px 10px', fontSize: '12px' }}
              >
                <option value="">All Camera Types</option>
                <option value="FIXED_BULLET">Fixed Bullet</option>
                <option value="FIXED_DOME">Fixed Dome</option>
                <option value="PTZ">PTZ (Pan-Tilt-Zoom)</option>
                <option value="ANPR">ANPR / LPR</option>
                <option value="PANORAMIC_360">Panoramic 360°</option>
                <option value="THERMAL">Thermal</option>
              </select>

              {/* Health Status */}
              <select
                value={healthFilter}
                onChange={(e) => { setHealthFilter(e.target.value); setPage(1); }}
                style={{ background: '#1e293b', border: '1px solid #334155', color: '#cbd5e1', borderRadius: '6px', padding: '6px 10px', fontSize: '12px' }}
              >
                <option value="">All Health</option>
                <option value="ONLINE">ONLINE</option>
                <option value="OFFLINE">OFFLINE</option>
                <option value="DEGRADED">DEGRADED</option>
                <option value="UNKNOWN">UNKNOWN</option>
              </select>

              {/* GIS Coordinates */}
              <select
                value={gisFilter}
                onChange={(e) => { setGisFilter(e.target.value); setPage(1); }}
                style={{ background: '#1e293b', border: '1px solid #334155', color: '#cbd5e1', borderRadius: '6px', padding: '6px 10px', fontSize: '12px' }}
              >
                <option value="all">GIS: All Assets</option>
                <option value="mapped">Mapped (Verified Coordinates)</option>
                <option value="unmapped">Unmapped (Pending GPS)</option>
              </select>

              {(search || deptFilter || districtFilter || typeFilter || healthFilter || gisFilter !== 'all') && (
                <button
                  onClick={() => {
                    setSearch('');
                    setDeptFilter('');
                    setDistrictFilter('');
                    setTypeFilter('');
                    setHealthFilter('');
                    setGisFilter('all');
                    setPage(1);
                  }}
                  style={{ background: 'transparent', border: 'none', color: '#ef4444', fontSize: '12px', cursor: 'pointer', padding: '4px 8px' }}
                >
                  Reset Filters
                </button>
              )}
            </div>

            {/* Camera Registry Data Table */}
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', overflow: 'hidden' }}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
                  <thead>
                    <tr style={{ background: '#1e293b', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                      <th style={{ padding: '10px 14px' }}>Stream / Status</th>
                      <th style={{ padding: '10px 14px' }}>Camera ID & Name</th>
                      <th style={{ padding: '10px 14px' }}>Department / District</th>
                      <th style={{ padding: '10px 14px' }}>Coordinates (GIS)</th>
                      <th style={{ padding: '10px 14px' }}>Type & Codec</th>
                      <th style={{ padding: '10px 14px' }}>Install Date / Age</th>
                      <th style={{ padding: '10px 14px' }}>Maintenance</th>
                      <th style={{ padding: '10px 14px', textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loading ? (
                      <tr>
                        <td colSpan={8} style={{ padding: '30px', textAlign: 'center', color: '#94a3b8' }}>
                          <RefreshCw size={20} className="animate-spin" style={{ margin: '0 auto 8px' }} />
                          Loading registry assets...
                        </td>
                      </tr>
                    ) : cameras.length === 0 ? (
                      <tr>
                        <td colSpan={8} style={{ padding: '30px', textAlign: 'center', color: '#64748b' }}>
                          No camera assets found matching the criteria.
                        </td>
                      </tr>
                    ) : (
                      cameras.map((cam) => {
                        const isOnline = cam.health_status === 'ONLINE';
                        const isDegraded = cam.health_status === 'DEGRADED';
                        const isOffline = cam.health_status === 'OFFLINE';
                        const statusColor = isOnline ? '#10b981' : isDegraded ? '#f59e0b' : isOffline ? '#ef4444' : '#64748b';

                        return (
                          <tr
                            key={cam.camera_id}
                            style={{
                              borderBottom: '1px solid #1f2937',
                              transition: 'background 0.15s ease',
                              background: cam.operational_status !== 'ACTIVE' ? 'rgba(15, 23, 42, 0.4)' : 'transparent'
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = '#1e293b'}
                            onMouseLeave={(e) => e.currentTarget.style.background = cam.operational_status !== 'ACTIVE' ? 'rgba(15, 23, 42, 0.4)' : 'transparent'}
                          >
                            {/* Health Indicator */}
                            <td style={{ padding: '10px 14px', whiteSpace: 'nowrap' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{
                                  width: '8px',
                                  height: '8px',
                                  borderRadius: '50%',
                                  background: statusColor,
                                  boxShadow: isOnline ? '0 0 8px rgba(16, 185, 129, 0.6)' : 'none'
                                }} />
                                <span style={{ fontSize: '11px', fontWeight: 700, color: statusColor }}>
                                  {cam.health_status}
                                </span>
                              </div>
                            </td>

                            {/* Camera ID & Name */}
                            <td style={{ padding: '10px 14px' }}>
                              <div style={{ fontWeight: 700, color: '#f8fafc' }}>
                                {cam.camera_id}
                              </div>
                              <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                                {cam.display_name || cam.name}
                              </div>
                            </td>

                            {/* Department / District */}
                            <td style={{ padding: '10px 14px' }}>
                              <div style={{ color: '#cbd5e1' }}>{cam.owning_department || 'Gujarat State Police'}</div>
                              <div style={{ fontSize: '11px', color: '#64748b' }}>{cam.district || cam.city || 'Gujarat'}</div>
                            </td>

                            {/* Coordinates */}
                            <td style={{ padding: '10px 14px' }}>
                              {cam.latitude != null && cam.longitude != null ? (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#38bdf8' }}>
                                  <MapPin size={12} />
                                  <span>{cam.latitude.toFixed(4)}, {cam.longitude.toFixed(4)}</span>
                                </div>
                              ) : (
                                <span style={{ color: '#64748b', fontStyle: 'italic' }}>GPS Unavailable</span>
                              )}
                            </td>

                            {/* Camera Type & Codec */}
                            <td style={{ padding: '10px 14px' }}>
                              <span style={{
                                padding: '2px 6px',
                                borderRadius: '4px',
                                background: '#1e293b',
                                color: '#e2e8f0',
                                fontSize: '11px',
                                fontWeight: 600
                              }}>
                                {cam.camera_type}
                              </span>
                              <span style={{ marginLeft: '6px', fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>
                                {cam.codec || 'H.264'}
                              </span>
                            </td>

                            {/* Installation Date / Age */}
                            <td style={{ padding: '10px 14px' }}>
                              {cam.installation_date ? (
                                <div>
                                  <div style={{ color: '#cbd5e1' }}>{cam.installation_date}</div>
                                  <div style={{ fontSize: '10px', color: '#10b981' }}>Recorded</div>
                                </div>
                              ) : (
                                <span style={{ color: '#64748b', fontSize: '11px' }}>UNKNOWN</span>
                              )}
                            </td>

                            {/* Maintenance Status */}
                            <td style={{ padding: '10px 14px' }}>
                              <span style={{
                                padding: '2px 6px',
                                borderRadius: '4px',
                                background: cam.maintenance_status === 'OPERATIONAL' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                                color: cam.maintenance_status === 'OPERATIONAL' ? '#34d399' : '#fbbf24',
                                fontSize: '10px',
                                fontWeight: 700
                              }}>
                                {cam.maintenance_status}
                              </span>
                            </td>

                            {/* Actions */}
                            <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
                                <button
                                  onClick={() => setSelectedAsset(cam)}
                                  title="View full camera asset record"
                                  style={{
                                    background: '#1e293b',
                                    border: '1px solid #334155',
                                    color: '#38bdf8',
                                    borderRadius: '4px',
                                    padding: '4px 8px',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    fontSize: '11px'
                                  }}
                                >
                                  <Eye size={12} /> Detail
                                </button>

                                <button
                                  onClick={() => {
                                    if (onViewLiveCamera) onViewLiveCamera(cam);
                                  }}
                                  title="Open live camera player"
                                  style={{
                                    background: '#1e293b',
                                    border: '1px solid #334155',
                                    color: '#10b981',
                                    borderRadius: '4px',
                                    padding: '4px 8px',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    fontSize: '11px'
                                  }}
                                >
                                  <Video size={12} /> Live
                                </button>

                                {(currentRole === 'SUPER_ADMIN' || currentRole === 'DEPARTMENT_ADMIN' || currentRole === 'OPERATOR') && (
                                  <>
                                    <button
                                      onClick={() => {
                                        setMaintenanceCameraId(cam.camera_id);
                                        setShowMaintenanceModal(true);
                                      }}
                                      title="Report Maintenance Issue"
                                      style={{
                                        background: '#1e293b',
                                        border: '1px solid #334155',
                                        color: '#f59e0b',
                                        borderRadius: '4px',
                                        padding: '4px 8px',
                                        cursor: 'pointer',
                                        fontSize: '11px'
                                      }}
                                    >
                                      <Wrench size={12} />
                                    </button>

                                    <button
                                      onClick={() => handleToggleActive(cam)}
                                      title={cam.operational_status === 'ACTIVE' ? 'Deactivate Camera' : 'Activate Camera'}
                                      style={{
                                        background: '#1e293b',
                                        border: '1px solid #334155',
                                        color: cam.operational_status === 'ACTIVE' ? '#ef4444' : '#10b981',
                                        borderRadius: '4px',
                                        padding: '4px 8px',
                                        cursor: 'pointer',
                                        fontSize: '11px'
                                      }}
                                    >
                                      {cam.operational_status === 'ACTIVE' ? 'Off' : 'On'}
                                    </button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div style={{
                padding: '12px 16px',
                borderTop: '1px solid #1f2937',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '12px',
                color: '#94a3b8'
              }}>
                <div>
                  Showing {cameras.length} of {totalCount} assets (Page {page} of {totalPages})
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage(p => Math.max(p - 1, 1))}
                    style={{
                      background: '#1e293b',
                      border: '1px solid #334155',
                      color: page <= 1 ? '#475569' : '#cbd5e1',
                      borderRadius: '4px',
                      padding: '4px 8px',
                      cursor: page <= 1 ? 'not-allowed' : 'pointer'
                    }}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span style={{ color: '#fff', fontWeight: 700 }}>{page}</span>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage(p => Math.min(p + 1, totalPages))}
                    style={{
                      background: '#1e293b',
                      border: '1px solid #334155',
                      color: page >= totalPages ? '#475569' : '#cbd5e1',
                      borderRadius: '4px',
                      padding: '4px 8px',
                      cursor: page >= totalPages ? 'not-allowed' : 'pointer'
                    }}
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            </div>
          </>
        )}

        {/* 4. GIS Coverage & Gap Analysis Sub-tab */}
        {activeTab === 'coverage' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                <MapPin size={18} color="#06b6d4" />
                <h3 style={{ fontSize: '15px', fontWeight: 700, margin: 0, color: '#38bdf8' }}>
                  GIS Coverage & Optical Visibility Estimates
                </h3>
              </div>
              <p style={{ fontSize: '12px', color: '#94a3b8', margin: '0 0 14px' }}>
                Estimated optical cones for registered cameras with verified coordinates. Clearly distinguishes physical visibility estimates from authoritative administrative police beat coverage.
              </p>

              {coverageData && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '14px' }}>
                  <div style={{ background: '#1e293b', padding: '10px', borderRadius: '6px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>Total Analyzed</div>
                    <div style={{ fontSize: '18px', fontWeight: 800, color: '#f8fafc' }}>{coverageData.total_cameras}</div>
                  </div>
                  <div style={{ background: '#1e293b', padding: '10px', borderRadius: '6px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>Mapped with Coordinates</div>
                    <div style={{ fontSize: '18px', fontWeight: 800, color: '#10b981' }}>{coverageData.mapped_cameras_count}</div>
                  </div>
                  <div style={{ background: '#1e293b', padding: '10px', borderRadius: '6px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>Default Optical Radius</div>
                    <div style={{ fontSize: '18px', fontWeight: 800, color: '#38bdf8' }}>{coverageData.default_radius_meters}m</div>
                  </div>
                </div>
              )}
            </div>

            {/* Gap Analysis Box (Absolute Data Integrity) */}
            <div style={{ background: '#111827', border: '1px solid #f59e0b', borderRadius: '8px', padding: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                <AlertTriangle size={18} color="#f59e0b" />
                <h3 style={{ fontSize: '15px', fontWeight: 700, margin: 0, color: '#fbbf24' }}>
                  Coverage Gap Analysis Framework (Data Integrity Enforced)
                </h3>
              </div>
              {gapData && (
                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                  <div style={{ padding: '10px', background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px', marginBottom: '12px' }}>
                    <strong>Notice:</strong> {gapData.reason}
                  </div>
                  <div style={{ fontWeight: 600, marginBottom: '6px', color: '#f8fafc' }}>
                    Required Authoritative Reference Layers:
                  </div>
                  <ul style={{ paddingLeft: '20px', color: '#94a3b8', margin: '0 0 12px' }}>
                    {gapData.reference_layers_required.map((layer, idx) => (
                      <li key={idx} style={{ marginBottom: '4px' }}>{layer}</li>
                    ))}
                  </ul>
                  <p style={{ margin: 0, color: '#64748b', fontStyle: 'italic' }}>
                    {gapData.message}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 5. Ageing Infrastructure Sub-tab */}
        {activeTab === 'ageing' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
                <div>
                  <h3 style={{ fontSize: '15px', fontWeight: 700, margin: 0, color: '#38bdf8' }}>
                    Ageing Infrastructure Analysis
                  </h3>
                  <p style={{ fontSize: '12px', color: '#94a3b8', margin: '4px 0 0' }}>
                    Calculated strictly from authoritative installation dates. Missing dates are explicitly marked UNKNOWN without fabrication.
                  </p>
                </div>

                {/* Configurable Thresholds */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8' }}>Young (&lt; yrs):</div>
                  <input
                    type="number"
                    step="0.5"
                    value={ageingYoungYears}
                    onChange={(e) => setAgeingYoungYears(parseFloat(e.target.value) || 1)}
                    style={{ width: '60px', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px' }}
                  />
                  <div style={{ fontSize: '11px', color: '#94a3b8' }}>Old (&gt; yrs):</div>
                  <input
                    type="number"
                    step="0.5"
                    value={ageingOldYears}
                    onChange={(e) => setAgeingOldYears(parseFloat(e.target.value) || 3)}
                    style={{ width: '60px', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px' }}
                  />
                </div>
              </div>

              {ageingReport && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', marginBottom: '16px' }}>
                  <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>0 - {ageingYoungYears} Years</div>
                    <div style={{ fontSize: '20px', fontWeight: 800, color: '#10b981' }}>{ageingReport.count_young}</div>
                  </div>
                  <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>{ageingYoungYears} - {ageingOldYears} Years</div>
                    <div style={{ fontSize: '20px', fontWeight: 800, color: '#38bdf8' }}>{ageingReport.count_medium}</div>
                  </div>
                  <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>{ageingOldYears}+ Years (Ageing)</div>
                    <div style={{ fontSize: '20px', fontWeight: 800, color: '#ef4444' }}>{ageingReport.count_old}</div>
                  </div>
                  <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>Date Missing (Unknown)</div>
                    <div style={{ fontSize: '20px', fontWeight: 800, color: '#64748b' }}>{ageingReport.count_unknown}</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 6. Maintenance Tickets Sub-tab */}
        {activeTab === 'maintenance' && (
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
              <h3 style={{ fontSize: '15px', fontWeight: 700, margin: 0, color: '#38bdf8' }}>
                Surveillance Maintenance Tickets
              </h3>
              <button
                onClick={() => { setMaintenanceCameraId(''); setShowMaintenanceModal(true); }}
                style={{
                  background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '6px 12px',
                  fontSize: '12px',
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  cursor: 'pointer'
                }}
              >
                <Plus size={14} /> Open Ticket
              </button>
            </div>

            {maintenanceTickets.length === 0 ? (
              <div style={{ padding: '30px', textAlign: 'center', color: '#64748b', fontSize: '13px' }}>
                No maintenance records currently registered.
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#1e293b', color: '#94a3b8' }}>
                    <th style={{ padding: '8px 12px' }}>Ticket #</th>
                    <th style={{ padding: '8px 12px' }}>Camera</th>
                    <th style={{ padding: '8px 12px' }}>Type</th>
                    <th style={{ padding: '8px 12px' }}>Priority</th>
                    <th style={{ padding: '8px 12px' }}>Status</th>
                    <th style={{ padding: '8px 12px' }}>Reported At</th>
                    <th style={{ padding: '8px 12px' }}>Issue Description</th>
                  </tr>
                </thead>
                <tbody>
                  {maintenanceTickets.map(t => (
                    <tr key={t.id} style={{ borderBottom: '1px solid #1f2937' }}>
                      <td style={{ padding: '8px 12px', fontWeight: 700, color: '#38bdf8' }}>{t.ticket_number}</td>
                      <td style={{ padding: '8px 12px', color: '#f8fafc' }}>{t.camera_id}</td>
                      <td style={{ padding: '8px 12px' }}>{t.maintenance_type}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <span style={{
                          padding: '2px 6px',
                          borderRadius: '4px',
                          background: t.priority === 'CRITICAL' ? '#ef4444' : t.priority === 'HIGH' ? '#f59e0b' : '#3b82f6',
                          color: '#fff',
                          fontSize: '10px',
                          fontWeight: 700
                        }}>
                          {t.priority}
                        </span>
                      </td>
                      <td style={{ padding: '8px 12px' }}>{t.status}</td>
                      <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{new Date(t.reported_at).toLocaleString()}</td>
                      <td style={{ padding: '8px 12px', color: '#cbd5e1' }}>{t.issue_description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* 7. Department Hierarchy Sub-tab */}
        {activeTab === 'departments' && (
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 700, margin: '0 0 14px', color: '#38bdf8' }}>
              Authoritative Gujarat Police Hierarchy
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
              {departments.map(d => (
                <div key={d.id} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 700, color: '#38bdf8', padding: '2px 6px', background: 'rgba(56, 189, 248, 0.1)', borderRadius: '4px' }}>
                      {d.department_type}
                    </span>
                    <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 700 }}>
                      {d.camera_count || 0} Cameras
                    </span>
                  </div>
                  <div style={{ fontWeight: 700, color: '#f8fafc', fontSize: '13px' }}>{d.name}</div>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>Code: {d.code} | District: {d.district || 'Statewide'}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 8. Immutable Audit Log Sub-tab */}
        {activeTab === 'audit' && (
          <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 700, margin: '0 0 14px', color: '#38bdf8' }}>
              Append-Only Security Audit Trail
            </h3>
            {auditLogs.length === 0 ? (
              <div style={{ padding: '30px', textAlign: 'center', color: '#64748b' }}>No audit records.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#1e293b', color: '#94a3b8' }}>
                    <th style={{ padding: '8px 12px' }}>Timestamp</th>
                    <th style={{ padding: '8px 12px' }}>User & Role</th>
                    <th style={{ padding: '8px 12px' }}>Action</th>
                    <th style={{ padding: '8px 12px' }}>Target Entity</th>
                    <th style={{ padding: '8px 12px' }}>Camera ID</th>
                    <th style={{ padding: '8px 12px' }}>Reason / Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map(l => (
                    <tr key={l.id} style={{ borderBottom: '1px solid #1f2937' }}>
                      <td style={{ padding: '8px 12px', color: '#94a3b8', whiteSpace: 'nowrap' }}>{new Date(l.timestamp).toLocaleString()}</td>
                      <td style={{ padding: '8px 12px', color: '#f8fafc' }}>{l.username} ({l.role})</td>
                      <td style={{ padding: '8px 12px' }}>
                        <span style={{
                          padding: '2px 6px',
                          borderRadius: '4px',
                          background: l.action === 'CREATE' ? 'rgba(16, 185, 129, 0.2)' : l.action === 'UPDATE' ? 'rgba(56, 189, 248, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                          color: l.action === 'CREATE' ? '#34d399' : l.action === 'UPDATE' ? '#38bdf8' : '#f87171',
                          fontSize: '10px',
                          fontWeight: 700
                        }}>
                          {l.action}
                        </span>
                      </td>
                      <td style={{ padding: '8px 12px', color: '#cbd5e1' }}>{l.entity_type} ({l.entity_id})</td>
                      <td style={{ padding: '8px 12px', color: '#38bdf8' }}>{l.camera_id || '—'}</td>
                      <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{l.reason || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* MODALS */}

      {/* 1. Add Camera Modal */}
      {showAddModal && (
        <AddCameraModal
          departments={departments}
          getAuthHeaders={getAuthHeaders}
          onClose={() => setShowAddModal(false)}
          onSuccess={() => {
            setShowAddModal(false);
            fetchCameras();
            fetchKpis();
            setFeedbackMsg({ type: 'success', text: 'Camera asset created and onboarded cleanly.' });
          }}
        />
      )}

      {/* 2. Bulk Import Modal */}
      {showImportModal && (
        <BulkImportModal
          getAuthHeaders={getAuthHeaders}
          onClose={() => setShowImportModal(false)}
          onSuccess={(summary) => {
            setShowImportModal(false);
            fetchCameras();
            fetchKpis();
            setFeedbackMsg({
              type: 'success',
              text: `Bulk import completed: ${summary.inserted} inserted, ${summary.updated} updated, ${summary.invalid_rows} invalid.`
            });
          }}
        />
      )}

      {/* 3. Camera Detail Drawer/Modal */}
      {selectedAsset && (
        <CameraDetailModal
          asset={selectedAsset}
          onClose={() => setSelectedAsset(null)}
          onViewLive={() => {
            if (onViewLiveCamera) onViewLiveCamera(selectedAsset);
            setSelectedAsset(null);
          }}
          onReportMaintenance={() => {
            setMaintenanceCameraId(selectedAsset.camera_id);
            setSelectedAsset(null);
            setShowMaintenanceModal(true);
          }}
        />
      )}

      {/* 4. Maintenance Ticket Modal */}
      {showMaintenanceModal && (
        <CreateMaintenanceModal
          cameraId={maintenanceCameraId}
          getAuthHeaders={getAuthHeaders}
          onClose={() => setShowMaintenanceModal(false)}
          onSuccess={() => {
            setShowMaintenanceModal(false);
            fetchMaintenance();
            fetchCameras();
            fetchKpis();
            setFeedbackMsg({ type: 'success', text: 'Maintenance ticket opened successfully.' });
          }}
        />
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------
// SUB-COMPONENTS & MODALS
// ------------------------------------------------------------------------------

function AddCameraModal({ departments, getAuthHeaders, onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    camera_id: '',
    name: '',
    display_name: '',
    department_id: departments[0]?.id || '',
    district: 'Ahmedabad',
    city: 'Ahmedabad',
    latitude: '',
    longitude: '',
    camera_type: 'FIXED_BULLET',
    camera_category: 'TRAFFIC',
    mounting_type: 'POLE',
    manufacturer: '',
    model_number: '',
    serial_number: '',
    installation_date: '',
    commissioning_date: '',
    operational_status: 'ACTIVE'
  });
  const [errorMsg, setErrorMsg] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg(null);
    setSubmitting(true);

    const payload = {
      ...formData,
      department_id: formData.department_id ? parseInt(formData.department_id, 10) : null,
      latitude: formData.latitude !== '' ? parseFloat(formData.latitude) : null,
      longitude: formData.longitude !== '' ? parseFloat(formData.longitude) : null,
      installation_date: formData.installation_date || null,
      commissioning_date: formData.commissioning_date || null
    };

    try {
      const res = await fetch('/api/registry/cameras', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        onSuccess();
      } else {
        setErrorMsg(data.detail || 'Validation failed.');
      }
    } catch (err) {
      setErrorMsg('Network error.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.7)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999
    }}>
      <div style={{
        background: '#0f172a',
        border: '1px solid #334155',
        borderRadius: '10px',
        width: '560px',
        maxHeight: '90vh',
        overflowY: 'auto',
        padding: '24px',
        color: '#f8fafc'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '16px', fontWeight: 800, margin: 0, color: '#38bdf8' }}>
            Manual Camera Onboarding
          </h2>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>
            <X size={18} />
          </button>
        </div>

        {errorMsg && (
          <div style={{ padding: '8px 12px', background: 'rgba(239, 68, 68, 0.2)', border: '1px solid #ef4444', borderRadius: '6px', color: '#f87171', fontSize: '12px', marginBottom: '14px' }}>
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Camera ID *</label>
              <input
                required
                type="text"
                placeholder="e.g. GJ-AHM-CAM-101"
                value={formData.camera_id}
                onChange={e => setFormData({ ...formData, camera_id: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Camera Name *</label>
              <input
                required
                type="text"
                placeholder="e.g. SG Highway Junction South"
                value={formData.name}
                onChange={e => setFormData({ ...formData, name: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Department</label>
              <select
                value={formData.department_id}
                onChange={e => setFormData({ ...formData, department_id: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              >
                {departments.map(d => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>District</label>
              <input
                type="text"
                value={formData.district}
                onChange={e => setFormData({ ...formData, district: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Latitude (-90 to +90)</label>
              <input
                type="number"
                step="any"
                placeholder="e.g. 23.0225"
                value={formData.latitude}
                onChange={e => setFormData({ ...formData, latitude: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Longitude (-180 to +180)</label>
              <input
                type="number"
                step="any"
                placeholder="e.g. 72.5714"
                value={formData.longitude}
                onChange={e => setFormData({ ...formData, longitude: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Camera Type</label>
              <select
                value={formData.camera_type}
                onChange={e => setFormData({ ...formData, camera_type: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              >
                <option value="FIXED_BULLET">Fixed Bullet</option>
                <option value="FIXED_DOME">Fixed Dome</option>
                <option value="PTZ">PTZ</option>
                <option value="ANPR">ANPR / LPR</option>
                <option value="PANORAMIC_360">Panoramic 360°</option>
                <option value="THERMAL">Thermal</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Mounting Type</label>
              <select
                value={formData.mounting_type}
                onChange={e => setFormData({ ...formData, mounting_type: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              >
                <option value="POLE">Pole</option>
                <option value="GANTRY">Overhead Gantry</option>
                <option value="BUILDING_WALL">Building Wall</option>
                <option value="TRAFFIC_LIGHT">Traffic Light</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Installation Date (Optional)</label>
              <input
                type="date"
                value={formData.installation_date}
                onChange={e => setFormData({ ...formData, installation_date: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Commissioning Date (Optional)</label>
              <input
                type="date"
                value={formData.commissioning_date}
                onChange={e => setFormData({ ...formData, commissioning_date: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '14px' }}>
            <button
              type="button"
              onClick={onClose}
              style={{ background: '#1e293b', border: '1px solid #334155', color: '#94a3b8', padding: '6px 14px', borderRadius: '4px', fontSize: '12px', cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              style={{
                background: 'linear-gradient(135deg, #06b6d4 0%, #2563eb 100%)',
                border: 'none',
                color: '#fff',
                padding: '6px 16px',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              {submitting ? 'Validating...' : 'Create & Onboard Asset'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function BulkImportModal({ getAuthHeaders, onClose, onSuccess }) {
  const [file, setFile] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handlePreview = async () => {
    if (!file) return;
    setUploading(true);
    setErrorMsg(null);

    const formData = new FormData();
    formData.append('file', file);

    const isExcel = file.name.endsWith('.xlsx') || file.name.endsWith('.xls');
    const endpoint = isExcel ? '/api/registry/import/excel?commit=false' : '/api/registry/import/csv?commit=false';

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        setPreviewData(data);
      } else {
        setErrorMsg(data.detail || 'Validation preview failed.');
      }
    } catch (e) {
      setErrorMsg('Failed to process upload preview.');
    } finally {
      setUploading(false);
    }
  };

  const handleCommit = async () => {
    if (!file) return;
    setUploading(true);
    setErrorMsg(null);

    const formData = new FormData();
    formData.append('file', file);

    const isExcel = file.name.endsWith('.xlsx') || file.name.endsWith('.xls');
    const endpoint = isExcel ? '/api/registry/import/excel?commit=true' : '/api/registry/import/csv?commit=true';

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        onSuccess(data);
      } else {
        setErrorMsg(data.detail || 'Import commit failed.');
      }
    } catch (e) {
      setErrorMsg('Failed to commit import.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.7)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999
    }}>
      <div style={{
        background: '#0f172a',
        border: '1px solid #334155',
        borderRadius: '10px',
        width: '680px',
        maxHeight: '90vh',
        overflowY: 'auto',
        padding: '24px',
        color: '#f8fafc'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '16px', fontWeight: 800, margin: 0, color: '#38bdf8' }}>
            Bulk CSV / Excel Asset Import
          </h2>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>
            <X size={18} />
          </button>
        </div>

        {errorMsg && (
          <div style={{ padding: '8px 12px', background: 'rgba(239, 68, 68, 0.2)', border: '1px solid #ef4444', borderRadius: '6px', color: '#f87171', fontSize: '12px', marginBottom: '14px' }}>
            {errorMsg}
          </div>
        )}

        <div style={{
          border: '2px dashed #334155',
          borderRadius: '8px',
          padding: '20px',
          textAlign: 'center',
          marginBottom: '16px',
          background: 'rgba(30, 41, 59, 0.4)'
        }}>
          <Upload size={24} color="#38bdf8" style={{ margin: '0 auto 8px' }} />
          <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc', marginBottom: '4px' }}>
            Select CSV or Excel (.xlsx) Spreadsheet
          </div>
          <p style={{ fontSize: '11px', color: '#94a3b8', margin: '0 0 12px' }}>
            Supports camera_id, name, district, city, latitude, longitude, camera_type, etc.
          </p>
          <input
            type="file"
            accept=".csv, .xlsx, .xls"
            onChange={(e) => {
              setFile(e.target.files[0]);
              setPreviewData(null);
            }}
            style={{ fontSize: '12px', color: '#cbd5e1' }}
          />
        </div>

        {file && !previewData && (
          <button
            onClick={handlePreview}
            disabled={uploading}
            style={{
              width: '100%',
              background: '#1e293b',
              border: '1px solid #334155',
              color: '#38bdf8',
              padding: '8px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
              marginBottom: '16px'
            }}
          >
            {uploading ? 'Parsing & Validating Rows...' : 'Run Validation Preview'}
          </button>
        )}

        {/* Preview Results */}
        {previewData && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginBottom: '14px' }}>
              <div style={{ background: '#1e293b', padding: '10px', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Total Rows</div>
                <div style={{ fontSize: '18px', fontWeight: 800, color: '#f8fafc' }}>{previewData.total_rows}</div>
              </div>
              <div style={{ background: '#1e293b', padding: '10px', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Valid Rows</div>
                <div style={{ fontSize: '18px', fontWeight: 800, color: '#10b981' }}>{previewData.valid_rows}</div>
              </div>
              <div style={{ background: '#1e293b', padding: '10px', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Invalid Rows</div>
                <div style={{ fontSize: '18px', fontWeight: 800, color: '#ef4444' }}>{previewData.invalid_rows}</div>
              </div>
            </div>

            {/* Validation Errors Table */}
            {previewData.errors && previewData.errors.length > 0 && (
              <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#f87171', marginBottom: '6px' }}>
                  Row Validation Errors ({previewData.errors.length})
                </div>
                <div style={{ maxHeight: '160px', overflowY: 'auto', background: '#1e293b', borderRadius: '6px', padding: '8px' }}>
                  {previewData.errors.map((err, i) => (
                    <div key={i} style={{ fontSize: '11px', color: '#cbd5e1', padding: '4px 0', borderBottom: '1px solid #334155' }}>
                      <span style={{ color: '#ef4444', fontWeight: 700 }}>Row {err.row_number}</span> (Cam: {err.camera_id || 'N/A'}, Field: {err.field}): {err.error_message}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                onClick={onClose}
                style={{ background: '#1e293b', border: '1px solid #334155', color: '#94a3b8', padding: '6px 14px', borderRadius: '4px', fontSize: '12px', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleCommit}
                disabled={uploading || previewData.valid_rows === 0}
                style={{
                  background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                  border: 'none',
                  color: '#fff',
                  padding: '6px 16px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                {uploading ? 'Importing...' : `Import ${previewData.valid_rows} Valid Rows`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CameraDetailModal({ asset, onClose, onViewLive, onReportMaintenance }) {
  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.7)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999
    }}>
      <div style={{
        background: '#0f172a',
        border: '1px solid #334155',
        borderRadius: '10px',
        width: '640px',
        maxHeight: '90vh',
        overflowY: 'auto',
        padding: '24px',
        color: '#f8fafc'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <div style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 700 }}>CANONICAL ASSET RECORD</div>
            <h2 style={{ fontSize: '18px', fontWeight: 800, margin: '2px 0 0', color: '#f8fafc' }}>
              {asset.camera_id} — {asset.display_name || asset.name}
            </h2>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '12px', marginBottom: '20px' }}>
          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px', fontWeight: 700 }}>IDENTITY & GOVERNANCE</div>
            <div><strong>Department:</strong> {asset.owning_department || 'Gujarat Police StateSurveillance'}</div>
            <div><strong>District / City:</strong> {asset.district || asset.city || 'Gujarat'}</div>
            <div><strong>Ownership:</strong> {asset.ownership_type || 'GOVERNMENT'}</div>
            <div><strong>Operational Status:</strong> {asset.operational_status}</div>
          </div>

          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px', fontWeight: 700 }}>GIS & PHYSICAL SITE</div>
            <div><strong>Latitude:</strong> {asset.latitude != null ? asset.latitude : 'NOT_AVAILABLE'}</div>
            <div><strong>Longitude:</strong> {asset.longitude != null ? asset.longitude : 'NOT_AVAILABLE'}</div>
            <div><strong>GIS Status:</strong> {asset.gis_verification_status}</div>
            <div><strong>Mounting:</strong> {asset.mounting_type || 'POLE'}</div>
          </div>

          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px', fontWeight: 700 }}>TECHNICAL & STREAM</div>
            <div><strong>Codec:</strong> {asset.codec || 'H.264'}</div>
            <div><strong>Manufacturer:</strong> {asset.manufacturer || 'NOT_AVAILABLE'}</div>
            <div><strong>Model / Serial:</strong> {asset.model_number || 'N/A'} / {asset.serial_number || 'N/A'}</div>
            <div><strong>HLS Stream:</strong> {asset.hls_stream_url ? 'Configured' : 'Proxy'}</div>
          </div>

          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px', fontWeight: 700 }}>LIFECYCLE & STORAGE</div>
            <div><strong>Installation Date:</strong> {asset.installation_date || 'UNKNOWN'}</div>
            <div><strong>Commissioning Date:</strong> {asset.commissioning_date || 'UNKNOWN'}</div>
            <div><strong>Storage Architecture:</strong> {asset.storage_type || 'CENTRAL_SAN'}</div>
            <div><strong>Retention Policy:</strong> {asset.retention_days ? `${asset.retention_days} Days` : '30 Days'}</div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button
            onClick={onReportMaintenance}
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              color: '#f59e0b',
              padding: '6px 14px',
              borderRadius: '4px',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <Wrench size={14} /> Report Maintenance
          </button>
          <button
            onClick={onViewLive}
            style={{
              background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
              border: 'none',
              color: '#fff',
              padding: '6px 16px',
              borderRadius: '4px',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <Video size={14} /> View Live Feed
          </button>
        </div>
      </div>
    </div>
  );
}

function CreateMaintenanceModal({ cameraId, getAuthHeaders, onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    camera_id: cameraId || 'cam01',
    issue_description: '',
    maintenance_type: 'CORRECTIVE',
    priority: 'MEDIUM',
    status: 'OPEN',
    assigned_to: 'Field Patrol Inspection Team'
  });
  const [errorMsg, setErrorMsg] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setErrorMsg(null);

    try {
      const res = await fetch('/api/registry/maintenance', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify(formData)
      });
      if (res.ok) {
        onSuccess();
      } else {
        const d = await res.json();
        setErrorMsg(d.detail || 'Failed to submit maintenance ticket.');
      }
    } catch (e) {
      setErrorMsg('Network error.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.7)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999
    }}>
      <div style={{
        background: '#0f172a',
        border: '1px solid #334155',
        borderRadius: '10px',
        width: '500px',
        padding: '24px',
        color: '#f8fafc'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '16px', fontWeight: 800, margin: 0, color: '#f59e0b' }}>
            Open Maintenance Ticket
          </h2>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>
            <X size={18} />
          </button>
        </div>

        {errorMsg && (
          <div style={{ padding: '8px 12px', background: 'rgba(239, 68, 68, 0.2)', border: '1px solid #ef4444', borderRadius: '6px', color: '#f87171', fontSize: '12px', marginBottom: '14px' }}>
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Target Camera ID *</label>
            <input
              required
              type="text"
              value={formData.camera_id}
              onChange={e => setFormData({ ...formData, camera_id: e.target.value })}
              style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
            />
          </div>

          <div>
            <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Issue Description *</label>
            <textarea
              required
              rows={3}
              placeholder="Describe observed hardware fault, dirty lens, power failure..."
              value={formData.issue_description}
              onChange={e => setFormData({ ...formData, issue_description: e.target.value })}
              style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Maintenance Type</label>
              <select
                value={formData.maintenance_type}
                onChange={e => setFormData({ ...formData, maintenance_type: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              >
                <option value="PREVENTIVE">Preventive Inspection</option>
                <option value="CORRECTIVE">Corrective Repair</option>
                <option value="OPTICAL_CLEANING">Optical Lens Cleaning</option>
                <option value="HARDWARE_REPLACEMENT">Hardware Replacement</option>
                <option value="FIRMWARE_UPGRADE">Firmware Upgrade</option>
              </select>
            </div>

            <div>
              <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Priority</label>
              <select
                value={formData.priority}
                onChange={e => setFormData({ ...formData, priority: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
              >
                <option value="LOW">Low</option>
                <option value="MEDIUM">Medium</option>
                <option value="HIGH">High</option>
                <option value="CRITICAL">Critical</option>
              </select>
            </div>
          </div>

          <div>
            <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Assigned Team / Technician</label>
            <input
              type="text"
              value={formData.assigned_to}
              onChange={e => setFormData({ ...formData, assigned_to: e.target.value })}
              style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '12px' }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '14px' }}>
            <button
              type="button"
              onClick={onClose}
              style={{ background: '#1e293b', border: '1px solid #334155', color: '#94a3b8', padding: '6px 14px', borderRadius: '4px', fontSize: '12px', cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              style={{
                background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                border: 'none',
                color: '#fff',
                padding: '6px 16px',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              {submitting ? 'Submitting...' : 'Register Ticket'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
