import React, { useState } from 'react';
import { useNetwork } from '../context/NetworkContext';
import GraphComponent, { STATUS_COLORS } from '../components/GraphComponent';

const API = '/api';

export default function Pathfinder() {
  const { isLoading, setSelectedNodeId } = useNetwork();
  const [pathFrom, setPathFrom] = useState('');
  const [pathTo, setPathTo] = useState('');
  const [pathInfo, setPathInfo] = useState(null);
  const [highlightPath, setHighlightPath] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleFindPath = async (e) => {
    e.preventDefault();
    if (!pathFrom.trim() || !pathTo.trim()) return;
    setLoading(true);
    setPathInfo(null);
    setHighlightPath(null);

    try {
      const res = await fetch(
        `${API}/path?from=${encodeURIComponent(pathFrom)}&to=${encodeURIComponent(pathTo)}`
      );
      const data = await res.json();
      if (res.ok) {
        setPathInfo(data);
        const ids = data.path.map(p => p.id);
        setHighlightPath(ids);
        if (ids[0]) setSelectedNodeId(ids[0]);
      } else {
        setPathInfo({ error: data.error });
      }
    } catch {
      setPathInfo({ error: 'Network error.' });
    } finally {
      setLoading(false);
    }
  };

  if (isLoading) {
    return <div className="page-loading"><div className="spinner" /><p>Loading pathfinder…</p></div>;
  }

  return (
    <div className="pathfinder-page">
      <div className="page-header">
        <div>
          <h2>Tactical Pathfinder</h2>
          <p className="page-subtitle">A* routing with dynamic edge costs · assess route impact during disruptions</p>
        </div>
      </div>

      <div className="pathfinder-grid">
        <aside className="pathfinder-sidebar">
          <div className="panel">
            <h3 className="panel-title">🗺️ Route Calculator</h3>
            <form onSubmit={handleFindPath} className="search-form">
              <label className="field-label">Origin</label>
              <input
                className="field-input"
                value={pathFrom}
                onChange={e => setPathFrom(e.target.value)}
                placeholder="From (e.g. C019 / HWH)"
              />
              <label className="field-label">Destination</label>
              <input
                className="field-input"
                value={pathTo}
                onChange={e => setPathTo(e.target.value)}
                placeholder="To (e.g. C022 / NJP)"
              />
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? 'Computing…' : 'Find Path'}
              </button>
            </form>

            {pathInfo?.error && <div className="alert alert-error">{pathInfo.error}</div>}

            {pathInfo?.path && (
              <div className="path-result">
                <div className="path-meta">
                  <span><strong>{pathInfo.hops}</strong> hops</span>
                  <span><strong>{pathInfo.total_cost}</strong> min (dynamic)</span>
                </div>
                <ol className="path-stops">
                  {pathInfo.path.map((p, i) => (
                    <li key={p.id}>
                      <StatusDot status={p.status} />
                      {i + 1}. {p.name} <code>{p.id}</code>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        </aside>

        <section className="pathfinder-graph">
          <GraphComponent highlightPath={highlightPath} />
        </section>
      </div>
    </div>
  );
}

function StatusDot({ status }) {
  return (
    <span
      className="status-dot-inline"
      style={{ background: STATUS_COLORS[status] ?? '#94a3b8' }}
    />
  );
}
