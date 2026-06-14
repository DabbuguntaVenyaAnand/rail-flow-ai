import React, { useState, useEffect, useCallback } from 'react';

const API_V1 = '/api/v1';

const STATUS_COLORS = {
  success: '#00d4ff',
  failed: '#ff4444',
  running: '#ffaa00',
  pending: '#888888',
};

function StatusBadge({ status }) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.pending;
  return (
    <span style={{
      padding: '3px 10px',
      borderRadius: '12px',
      border: `1px solid ${color}`,
      color,
      fontSize: '12px',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
    }}>
      {status || 'unknown'}
    </span>
  );
}

function KpiCard({ label, value, sub, accent }) {
  return (
    <div style={{
      background: '#16213e',
      border: '1px solid #0f3460',
      borderRadius: '8px',
      padding: '16px 20px',
      minWidth: '140px',
    }}>
      <div style={{ color: accent || '#00d4ff', fontSize: '22px', fontWeight: 700 }}>
        {value ?? '—'}
      </div>
      <div style={{ color: '#aaa', fontSize: '12px', marginTop: '4px' }}>{label}</div>
      {sub && <div style={{ color: '#666', fontSize: '11px', marginTop: '2px' }}>{sub}</div>}
    </div>
  );
}

function ActionsTable({ actions }) {
  if (!actions || actions.length === 0) {
    return <p style={{ color: '#666', fontStyle: 'italic' }}>No actions in this run.</p>;
  }
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid #0f3460' }}>
          {['Train', 'Action Type', 'Station', 'Hold (s)', 'Notes'].map(h => (
            <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: '#00d4ff', fontWeight: 600 }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {actions.map((a, i) => (
          <tr key={i} style={{ borderBottom: '1px solid #0d1b2a' }}>
            <td style={{ padding: '8px 12px', color: '#e0e0e0' }}>{a.train_number || a.run_id || '—'}</td>
            <td style={{ padding: '8px 12px', color: '#aaa' }}>{a.action_type || '—'}</td>
            <td style={{ padding: '8px 12px', color: '#aaa' }}>{a.station_code || '—'}</td>
            <td style={{ padding: '8px 12px', color: a.hold_seconds > 0 ? '#ffaa00' : '#666' }}>
              {a.hold_seconds != null ? a.hold_seconds : '—'}
            </td>
            <td style={{ padding: '8px 12px', color: '#666' }}>{a.notes || ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Rescheduling() {
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(false);
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState(null);
  const [lastRefreshed, setLastRefreshed] = useState(null);

  const fetchLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_V1}/rescheduling/latest`);
      if (res.status === 404) {
        setRun(null);
        return;
      }
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setRun(data);
      setLastRefreshed(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLatest();
    const id = setInterval(fetchLatest, 30_000);
    return () => clearInterval(id);
  }, [fetchLatest]);

  const triggerCompute = async () => {
    setComputing(true);
    setError(null);
    try {
      const res = await fetch(`${API_V1}/rescheduling/compute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policy: 'beam_search', horizon_minutes: 600 }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${res.status}`);
      }
      await fetchLatest();
    } catch (e) {
      setError(e.message);
    } finally {
      setComputing(false);
    }
  };

  const objDelta = run
    ? run.objective_before != null && run.objective_after != null
      ? ((run.objective_before - run.objective_after) / Math.max(run.objective_before, 1) * 100).toFixed(1)
      : null
    : null;

  return (
    <div style={{ padding: '24px', color: '#e0e0e0', fontFamily: 'inherit' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
        <div>
          <h2 style={{ margin: 0, color: '#fff', fontSize: '20px' }}>Reschedule Schedule</h2>
          <p style={{ margin: '4px 0 0', color: '#888', fontSize: '13px' }}>
            HSR-RailFlow rescheduling engine output
            {lastRefreshed && ` · Last updated ${lastRefreshed}`}
          </p>
        </div>
        <button
          onClick={triggerCompute}
          disabled={computing}
          style={{
            background: computing ? '#0f3460' : '#00d4ff',
            color: computing ? '#aaa' : '#000',
            border: 'none',
            borderRadius: '6px',
            padding: '10px 20px',
            fontWeight: 600,
            fontSize: '13px',
            cursor: computing ? 'not-allowed' : 'pointer',
            transition: 'background 0.2s',
          }}
        >
          {computing ? 'Computing…' : '⟳ Trigger Reschedule'}
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{ background: '#2a0a0a', border: '1px solid #ff4444', borderRadius: '6px', padding: '12px', marginBottom: '16px', color: '#ff8888' }}>
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && !run && (
        <div style={{ color: '#666', padding: '32px', textAlign: 'center' }}>Loading…</div>
      )}

      {/* No run yet */}
      {!loading && !run && !error && (
        <div style={{
          background: '#16213e',
          border: '1px dashed #0f3460',
          borderRadius: '8px',
          padding: '48px',
          textAlign: 'center',
          color: '#666',
        }}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>⟳</div>
          <p>No rescheduling run yet. Click <strong style={{ color: '#00d4ff' }}>Trigger Reschedule</strong> to compute one.</p>
        </div>
      )}

      {/* Run details */}
      {run && (
        <>
          {/* KPI row */}
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '24px' }}>
            <KpiCard label="Status" value={<StatusBadge status={run.status} />} />
            <KpiCard
              label="Objective Before"
              value={run.objective_before != null ? run.objective_before.toFixed(1) : '—'}
              sub="J_det score"
            />
            <KpiCard
              label="Objective After"
              value={run.objective_after != null ? run.objective_after.toFixed(1) : '—'}
              accent={run.objective_after < run.objective_before ? '#00ff88' : '#ffaa00'}
              sub={objDelta != null ? `${objDelta}% improvement` : undefined}
            />
            <KpiCard
              label="Compute Time"
              value={run.compute_time_ms != null ? `${run.compute_time_ms} ms` : '—'}
              accent="#aaa"
            />
            <KpiCard
              label="Conflicts"
              value={`${run.conflicts_resolved ?? 0} / ${run.conflicts_detected ?? 0}`}
              sub="resolved / detected"
              accent="#ffaa00"
            />
          </div>

          {/* Run metadata */}
          <div style={{
            background: '#16213e',
            border: '1px solid #0f3460',
            borderRadius: '8px',
            padding: '12px 16px',
            marginBottom: '20px',
            fontSize: '12px',
            color: '#888',
            display: 'flex',
            gap: '24px',
            flexWrap: 'wrap',
          }}>
            <span>Run ID: <span style={{ color: '#aaa', fontFamily: 'monospace' }}>{run.rescheduling_run_id}</span></span>
            {run.triggered_at && (
              <span>Triggered: <span style={{ color: '#aaa' }}>{new Date(run.triggered_at).toLocaleString()}</span></span>
            )}
            {run.policy_used && (
              <span>Policy: <span style={{ color: '#00d4ff' }}>{run.policy_used}</span></span>
            )}
          </div>

          {/* Actions table */}
          <div style={{
            background: '#16213e',
            border: '1px solid #0f3460',
            borderRadius: '8px',
            padding: '16px',
          }}>
            <h3 style={{ margin: '0 0 16px', color: '#00d4ff', fontSize: '14px', fontWeight: 600 }}>
              Rescheduling Actions ({(run.actions || []).length})
            </h3>
            <ActionsTable actions={run.actions} />
          </div>
        </>
      )}
    </div>
  );
}
