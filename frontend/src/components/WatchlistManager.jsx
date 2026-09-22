import React, { useState, useEffect } from 'react';
import { ShieldAlert, Plus, Trash2, CheckCircle, RefreshCw, Radio } from 'lucide-react';

export default function WatchlistManager() {
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newPlate, setNewPlate] = useState('');
  const [newCategory, setNewCategory] = useState('STOLEN');
  const [newSeverity, setNewSeverity] = useState('CRITICAL');
  const [newNotes, setNewNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  const fetchWatchlist = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/watchlist');
      const data = await res.json();
      setWatchlist(data.watchlist || []);
    } catch (e) {
      console.error('Failed to load watchlist', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWatchlist();
  }, []);

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!newPlate.trim()) return;

    setSubmitting(true);
    try {
      const res = await fetch('/api/v1/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          license_plate: newPlate.trim().toUpperCase(),
          category: newCategory,
          severity: newSeverity,
          notes: newNotes,
        }),
      });
      if (res.ok) {
        setStatusMsg(`Target vehicle ${newPlate.toUpperCase()} registered for state-level monitoring.`);
        setNewPlate('');
        setNewNotes('');
        fetchWatchlist();
        setTimeout(() => setStatusMsg(''), 3500);
      }
    } catch (e) {
      console.error('Failed to add plate', e);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (plate) => {
    if (!confirm(`Remove vehicle ${plate} from the active watchlist?`)) return;
    try {
      const res = await fetch(`/api/v1/watchlist/${encodeURIComponent(plate)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setStatusMsg(`Vehicle ${plate} removed from active watchlist.`);
        fetchWatchlist();
        setTimeout(() => setStatusMsg(''), 3000);
      }
    } catch (e) {
      console.error('Failed to remove plate', e);
    }
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%', backgroundColor: '#060911', color: '#f8fafc' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert color="#ef4444" size={22} />
            eGujCop Hotlist & Watchlist Registry
          </h2>
          <p style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Live vehicle registration database synced with statewide edge CCTV grid & Redis O(1) matching
          </p>
        </div>

        <button
          onClick={fetchWatchlist}
          style={{
            background: 'rgba(255, 255, 255, 0.05)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            color: '#cbd5e1',
            borderRadius: '6px',
            padding: '6px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '12px',
            cursor: 'pointer',
          }}
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh Watchlist
        </button>
      </div>

      {statusMsg && (
        <div style={{ background: 'rgba(16, 185, 129, 0.2)', border: '1px solid #10b981', color: '#6ee7b7', padding: '10px 14px', borderRadius: '6px', marginBottom: '16px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CheckCircle size={16} /> {statusMsg}
        </div>
      )}

      {/* Add Entry Card */}
      <div className="glass-panel" style={{ padding: '16px', borderRadius: '8px', marginBottom: '24px' }}>
        <h3 style={{ fontSize: '13px', fontWeight: 700, marginBottom: '12px', color: '#38bdf8' }}>
          + REGISTER TARGET VEHICLE TO HOTLIST
        </h3>
        <form onSubmit={handleAdd} style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <input
            type="text"
            placeholder="License Plate (e.g. GJ01AB9999)"
            value={newPlate}
            onChange={(e) => setNewPlate(e.target.value.toUpperCase())}
            style={{
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid rgba(6, 182, 212, 0.4)',
              color: '#ffffff',
              padding: '8px 12px',
              borderRadius: '6px',
              fontFamily: 'monospace',
              fontSize: '13px',
              fontWeight: 600,
              minWidth: '220px',
              outline: 'none',
            }}
          />

          <select
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            style={{
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              color: '#ffffff',
              padding: '8px 12px',
              borderRadius: '6px',
              fontSize: '13px',
              outline: 'none',
            }}
          >
            <option value="STOLEN">STOLEN</option>
            <option value="WANTED">WANTED</option>
            <option value="SUSPECT">SUSPECT</option>
            <option value="HIT_AND_RUN">HIT & RUN</option>
          </select>

          <select
            value={newSeverity}
            onChange={(e) => setNewSeverity(e.target.value)}
            style={{
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              color: '#ffffff',
              padding: '8px 12px',
              borderRadius: '6px',
              fontSize: '13px',
              outline: 'none',
            }}
          >
            <option value="CRITICAL">CRITICAL</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
          </select>

          <input
            type="text"
            placeholder="FIR Case details / Notes"
            value={newNotes}
            onChange={(e) => setNewNotes(e.target.value)}
            style={{
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              color: '#ffffff',
              padding: '8px 12px',
              borderRadius: '6px',
              fontSize: '13px',
              flex: 1,
              minWidth: '200px',
              outline: 'none',
            }}
          />

          <button
            type="submit"
            disabled={submitting}
            style={{
              background: '#06b6d4',
              color: '#0a0d14',
              fontWeight: 700,
              padding: '8px 20px',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <Plus size={16} /> Add Target
          </button>
        </form>
      </div>

      {/* Active Watchlist Table */}
      <div className="glass-panel" style={{ borderRadius: '8px', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
          <thead>
            <tr style={{ background: 'rgba(0,0,0,0.5)', borderBottom: '1px solid rgba(255, 255, 255, 0.1)', color: '#94a3b8' }}>
              <th style={{ padding: '12px 16px' }}>LICENSE PLATE</th>
              <th style={{ padding: '12px 16px' }}>CATEGORY</th>
              <th style={{ padding: '12px 16px' }}>SEVERITY</th>
              <th style={{ padding: '12px 16px' }}>CASE / OFFENSE NOTES</th>
              <th style={{ padding: '12px 16px' }}>STATUS</th>
              <th style={{ padding: '12px 16px', textAlign: 'right' }}>ACTION</th>
            </tr>
          </thead>
          <tbody>
            {watchlist.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: '36px 16px', textAlign: 'center', color: '#64748b' }}>
                  <Radio size={28} color="#06b6d4" style={{ margin: '0 auto 10px auto', display: 'block' }} />
                  <div>No target vehicles currently hotlisted.</div>
                  <div style={{ fontSize: '11px', color: '#475569', marginTop: '4px' }}>
                    Register wanted or stolen vehicle plates above to monitor live CCTV feeds across the state grid.
                  </div>
                </td>
              </tr>
            ) : (
              watchlist.map((item) => (
                <tr key={item.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '12px 16px', fontFamily: 'monospace', fontWeight: 800, fontSize: '14px', color: '#f87171' }}>
                    {item.license_plate}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', padding: '2px 8px', borderRadius: '4px', fontWeight: 700, fontSize: '11px' }}>
                      {item.category}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{ color: item.severity === 'CRITICAL' ? '#ef4444' : '#f59e0b', fontWeight: 700 }}>
                      {item.severity}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px', color: '#cbd5e1', maxWidth: '300px' }}>
                    {item.notes || 'Registered in state hotlist'}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: '#10b981', fontSize: '11px', fontWeight: 700 }}>
                      <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#10b981', boxShadow: '0 0 8px #10b981' }} />
                      ACTIVE MONITORING
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                    <button
                      onClick={() => handleDelete(item.license_plate)}
                      style={{
                        background: 'rgba(239, 68, 68, 0.15)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        color: '#fca5a5',
                        borderRadius: '6px',
                        padding: '4px 10px',
                        fontSize: '11px',
                        fontWeight: 700,
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                      }}
                    >
                      <Trash2 size={12} /> Remove
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
