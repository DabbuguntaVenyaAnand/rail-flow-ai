import React, { useState, useMemo } from 'react';
import { useNetwork } from '../context/NetworkContext';
import { STATUS_COLORS } from '../constants/colors';
import GraphComponent from '../components/GraphComponent';
import TacticalMapModal from '../components/TacticalMapModal';

const API = '/api';

export default function Pathfinder() {
  const { isLoading, setSelectedNodeId, graphData } = useNetwork();
  const [pathFrom, setPathFrom] = useState('');
  const [pathTo, setPathTo] = useState('');
  const [pathInfo, setPathInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [useAlternative, setUseAlternative] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleFindPath = async (e) => {
    e.preventDefault();
    if (!pathFrom.trim() || !pathTo.trim()) return;
    setLoading(true);
    setPathInfo(null);
    setUseAlternative(false);

    try {
      const res = await fetch(
        `${API}/path?from=${encodeURIComponent(pathFrom)}&to=${encodeURIComponent(pathTo)}`
      );
      const data = await res.json();
      if (res.ok) {
        setPathInfo(data);
        const ids = data.path.map(p => p.id);
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

  const activePath = useAlternative && pathInfo?.alternative_path ? pathInfo.alternative_path : pathInfo?.path;
  const activeCost = useAlternative && pathInfo?.alternative_path ? pathInfo.alternative_cost : pathInfo?.total_cost;
  const activeHops = useAlternative && pathInfo?.alternative_path ? (pathInfo.alternative_path.length - 1) : (pathInfo?.hops ?? 0);

  // Compute simplified Tactical Subgraph containing both paths and immediate connections
  const tacticalElements = useMemo(() => {
    if (!pathInfo?.path || !graphData?.elements) return [];
    
    const pathIds = new Set(pathInfo.path.map(p => p.id));
    const alternativePathIds = new Set(pathInfo.alternative_path ? pathInfo.alternative_path.map(p => p.id) : []);
    
    const neighborIds = new Set();
    
    // Gather neighbors for nodes on both paths
    graphData.elements.edges.forEach(e => {
      if (pathIds.has(e.data.source) || alternativePathIds.has(e.data.source)) {
        neighborIds.add(e.data.target);
      }
      if (pathIds.has(e.data.target) || alternativePathIds.has(e.data.target)) {
        neighborIds.add(e.data.source);
      }
    });
    
    const filteredNodes = graphData.elements.nodes.filter(
      n => pathIds.has(n.data.id) || alternativePathIds.has(n.data.id) || neighborIds.has(n.data.id)
    );
    
    const nodes = filteredNodes.map(n => {
      const isPrimary = pathIds.has(n.data.id);
      const isAlternative = alternativePathIds.has(n.data.id);
      const statusColor = STATUS_COLORS[n.data.status] ?? '#94a3b8';
      const layerColor = n.data.layer === 'hub' ? '#f97316' : '#6366f1';
      
      let classes = '';
      if (isPrimary && isAlternative) classes = 'highlight detour-highlight';
      else if (isPrimary) classes = 'highlight';
      else if (isAlternative) classes = 'detour-highlight';
      
      return {
        data: {
          id: n.data.id,
          label: n.data.name || n.data.id,
          statusColor,
          layerColor,
          nodeSize: (isPrimary || isAlternative) ? 16 : 8
        },
        position: n.position || n.data.position,
        classes
      };
    });
    
    const allVisibleIds = new Set(filteredNodes.map(n => n.data.id));
    const filteredEdges = graphData.elements.edges.filter(
      e => allVisibleIds.has(e.data.source) && allVisibleIds.has(e.data.target)
    );
    
    const edges = filteredEdges.map(e => {
      const primaryIdxSource = pathInfo.path.findIndex(p => p.id === e.data.source);
      const primaryIdxTarget = pathInfo.path.findIndex(p => p.id === e.data.target);
      const isPrimaryEdge = primaryIdxSource !== -1 && primaryIdxTarget !== -1 && Math.abs(primaryIdxSource - primaryIdxTarget) === 1;
      
      let isAlternativeEdge = false;
      if (pathInfo.alternative_path) {
        const altIdxSource = pathInfo.alternative_path.findIndex(p => p.id === e.data.source);
        const altIdxTarget = pathInfo.alternative_path.findIndex(p => p.id === e.data.target);
        isAlternativeEdge = altIdxSource !== -1 && altIdxTarget !== -1 && Math.abs(altIdxSource - altIdxTarget) === 1;
      }
      
      let classes = '';
      if (isPrimaryEdge && isAlternativeEdge) classes = 'highlight detour-highlight';
      else if (isPrimaryEdge) classes = 'highlight';
      else if (isAlternativeEdge) classes = 'detour-highlight';
      
      return {
        data: e.data,
        classes
      };
    });
    
    return nodes.concat(edges);
  }, [pathInfo, graphData]);

  if (isLoading) {
    return <div className="page-loading"><div className="spinner" /><p>Loading pathfinder…</p></div>;
  }

  // Node lists for GraphComponent rendering
  const shortestNodeIds = pathInfo?.path ? pathInfo.path.map(p => p.id) : null;
  const detourNodeIds = pathInfo?.alternative_path ? pathInfo.alternative_path.map(p => p.id) : null;

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
                placeholder="From (e.g. TMZ / HWH)"
              />
              <label className="field-label">Destination</label>
              <input
                className="field-input"
                value={pathTo}
                onChange={e => setPathTo(e.target.value)}
                placeholder="To (e.g. NJP / C022)"
              />
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? 'Computing…' : 'Find Path'}
              </button>
            </form>

            {pathInfo?.error && <div className="alert alert-error">{pathInfo.error}</div>}

            {pathInfo?.path && (
              <div className="path-result">
                {pathInfo.alternative_path && (
                  <div className="alert alert-warning" style={{ background: 'rgba(249, 115, 22, 0.15)', border: '1px solid rgba(249, 115, 22, 0.3)', color: '#f97316', margin: '12px 0', borderRadius: '8px', padding: '10px' }}>
                    <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: 4 }}>⚠️ Delays Detected on Route: {pathInfo.disrupted_stations.join(', ')}</div>
                    <p style={{ margin: 0, fontSize: '11px', color: '#cbd5e1' }}>The primary route is affected. Avoid affected stations with our bypass suggestion:</p>
                    <div className="btn-row" style={{ marginTop: 8 }}>
                      <button className={`btn btn-sm ${useAlternative ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setUseAlternative(true)}>
                        Use Detour ({pathInfo.alternative_cost} min)
                      </button>
                      <button className={`btn btn-sm ${!useAlternative ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setUseAlternative(false)}>
                        Keep Shortest ({pathInfo.total_cost} min)
                      </button>
                    </div>
                  </div>
                )}
                
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '12px 0 6px' }}>
                  <div className="path-meta" style={{ margin: 0 }}>
                    <span><strong>{activeHops}</strong> hops</span>
                    <span><strong>{activeCost}</strong> min</span>
                  </div>
                  <button className="btn btn-secondary btn-sm" onClick={() => setIsModalOpen(true)}>
                    🗺️ Open Tactical Map
                  </button>
                </div>
                
                <ol className="path-stops">
                  {activePath.map((p, i) => (
                    <li key={p.id}>
                      <StatusDot status={p.status} />
                      {i + 1}. {p.name || p.id} <code>{p.id}</code>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        </aside>

        <section className="pathfinder-graph">
          <GraphComponent highlightPath={shortestNodeIds} alternativePath={detourNodeIds} />
        </section>
      </div>

      <TacticalMapModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="🗺️ Tactical Subgraph - Route Comparison"
        description="Comparing the primary path (Yellow) and the detour bypass route (Green) side-by-side. Unrelated nodes are hidden for clarity."
        elements={tacticalElements}
      />
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