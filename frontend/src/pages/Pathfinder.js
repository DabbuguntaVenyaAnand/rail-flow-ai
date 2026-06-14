import React, { useState, useEffect, useMemo } from 'react';
import { useNetwork } from '../context/NetworkContext';
import { STATUS_COLORS } from '../constants/colors';
import GraphComponent from '../components/GraphComponent';
import TacticalMapModal from '../components/TacticalMapModal';

const API = '/api';

export default function Pathfinder() {
  const {
    isLoading,
    setSelectedNodeId,
    graphData,
    latestRescheduling,
    fetchLatestRescheduling,
    delayedNodeIds,
    injectDelay,
    clearDisruptions,
    propagationDepth,
    setPropagationDepth,
  } = useNetwork();

  // Route calculation state
  const [pathFrom, setPathFrom] = useState('');
  const [pathTo, setPathTo] = useState('');
  const [pathInfo, setPathInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [useAlternative, setUseAlternative] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Disruption state
  const [injectTarget, setInjectTarget] = useState(delayedNodeIds[0] || 'C019');
  const [injecting, setInjecting] = useState(false);
  const [disruptionMessage, setDisruptionMessage] = useState(null);

  // XAI highlight state
  const [xaiEvidenceIds, setXaiEvidenceIds] = useState([]);
  const [activeXaiSeq, setActiveXaiSeq] = useState(null);

  // Auto-refresh rescheduling run details when disruptions or path changes
  useEffect(() => {
    fetchLatestRescheduling();
  }, [fetchLatestRescheduling, delayedNodeIds]);

  const handleFindPath = async (e) => {
    if (e) e.preventDefault();
    if (!pathFrom.trim() || !pathTo.trim()) return;
    setLoading(true);
    setPathInfo(null);
    setUseAlternative(false);
    setXaiEvidenceIds([]);
    setActiveXaiSeq(null);

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

  // Trigger search automatically when origin and destination are filled by clicking
  useEffect(() => {
    if (pathFrom.trim() && pathTo.trim()) {
      handleFindPath();
    }
  }, [pathFrom, pathTo]);

  const handleNodeSelect = (node) => {
    if (!node?.id) return;
    if (!pathFrom) {
      setPathFrom(node.id);
    } else if (!pathTo && node.id !== pathFrom) {
      setPathTo(node.id);
    } else {
      setPathFrom(node.id);
      setPathTo('');
      setPathInfo(null);
    }
  };

  const handleInject = async () => {
    setInjecting(true);
    setDisruptionMessage(null);
    const result = await injectDelay(injectTarget, propagationDepth);
    if (result.ok) {
      setDisruptionMessage({ type: 'success', text: `Delay injected at ${result.station?.name || injectTarget}. Rescheduling cycle completed.` });
      // If a route was already loaded, refresh it to show detours
      if (pathFrom.trim() && pathTo.trim()) {
        const res = await fetch(
          `${API}/path?from=${encodeURIComponent(pathFrom)}&to=${encodeURIComponent(pathTo)}`
        );
        const data = await res.json();
        if (res.ok) setPathInfo(data);
      }
    } else {
      setDisruptionMessage({ type: 'error', text: result.error });
    }
    setInjecting(false);
  };

  const handleClear = async () => {
    setDisruptionMessage(null);
    await clearDisruptions();
    setDisruptionMessage({ type: 'success', text: 'All disruptions cleared. Network returned to baseline.' });
    setXaiEvidenceIds([]);
    setActiveXaiSeq(null);
    if (pathFrom.trim() && pathTo.trim()) {
      const res = await fetch(
        `${API}/path?from=${encodeURIComponent(pathFrom)}&to=${encodeURIComponent(pathTo)}`
      );
      const data = await res.json();
      if (res.ok) {
        setPathInfo(data);
        setUseAlternative(false);
      }
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
    return <div className="page-loading"><div className="spinner" /><p>Loading routing engine…</p></div>;
  }

  const shortestNodeIds = pathInfo?.path ? pathInfo.path.map(p => p.id) : null;
  const detourNodeIds = pathInfo?.alternative_path ? pathInfo.alternative_path.map(p => p.id) : null;

  return (
    <div className="pathfinder-page" style={{ height: 'calc(100vh - 64px)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="page-header" style={{ flexShrink: 0, padding: '12px 24px 8px' }}>
        <div>
          <h2>⚡ Rerouting & Rescheduling Hub</h2>
          <p className="page-subtitle">
            HSR-RailFlow Explainable Route Detours · assessing and solving operational conflicts on demand
          </p>
        </div>
      </div>

      <div className="pathfinder-grid" style={{ flex: 1, display: 'grid', gridTemplateColumns: '350px 1fr', overflow: 'hidden' }}>
        <aside className="pathfinder-sidebar" style={{ overflowY: 'auto', padding: '12px 16px', background: 'var(--bg-panel)', borderRight: '1px solid var(--border)' }}>
          {/* Route Calculator */}
          <div className="panel">
            <h3 className="panel-title">🗺️ Route Calculator</h3>
            <p className="panel-desc" style={{ fontSize: '11px', margin: '4px 0 10px' }}>
              💡 Click nodes on the map to set Origin and Destination.
            </p>
            <form onSubmit={handleFindPath} className="search-form">
              <label className="field-label">Origin</label>
              <input
                className="field-input"
                value={pathFrom}
                onChange={e => setPathFrom(e.target.value.toUpperCase())}
                placeholder="Click map or type (e.g. C019)"
              />
              <label className="field-label">Destination</label>
              <input
                className="field-input"
                value={pathTo}
                onChange={e => setPathTo(e.target.value.toUpperCase())}
                placeholder="Click map or type (e.g. C022)"
              />
              <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                <button className="btn btn-primary" type="submit" disabled={loading} style={{ flex: 2 }}>
                  {loading ? 'Computing…' : 'Find Route'}
                </button>
                {(pathFrom || pathTo) && (
                  <button className="btn btn-secondary" type="button" onClick={() => { setPathFrom(''); setPathTo(''); setPathInfo(null); }} style={{ flex: 1 }}>
                    Reset
                  </button>
                )}
              </div>
            </form>

            {pathInfo?.error && <div className="alert alert-error" style={{ marginTop: '12px' }}>{pathInfo.error}</div>}

            {pathInfo?.path && (
              <div className="path-result" style={{ marginTop: '16px' }}>
                {pathInfo.alternative_path && (
                  <div className="detour-glow-card">
                    <div style={{ fontWeight: 700, fontSize: '12px', color: 'var(--warning)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                      ⚠️ Delay Detected on Primary Route
                    </div>
                    <p style={{ margin: '0 0 10px', fontSize: '11px', color: 'var(--text-muted)', lineHeight: '1.4' }}>
                      Primary path intersects congested station(s): <strong>{pathInfo.disrupted_stations?.join(', ')}</strong>. Suggesting detour bypass:
                    </p>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button className={`btn btn-sm ${useAlternative ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setUseAlternative(true)} style={{ flex: 1, fontSize: '11px', padding: '6px' }}>
                        Detour ({pathInfo.alternative_cost}m)
                      </button>
                      <button className={`btn btn-sm ${!useAlternative ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setUseAlternative(false)} style={{ flex: 1, fontSize: '11px', padding: '6px' }}>
                        Shortest ({pathInfo.total_cost}m)
                      </button>
                    </div>
                  </div>
                )}
                
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '12px 0 8px', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>
                  <div className="path-meta" style={{ margin: 0, fontSize: '12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span>🚏 <strong>{activeHops}</strong> stops</span>
                    <span style={{ color: 'var(--border)' }}>|</span>
                    <span style={{ color: useAlternative ? 'var(--success)' : 'var(--text)' }}>⏱️ <strong>{activeCost}</strong> mins</span>
                  </div>
                  <button className="btn btn-secondary btn-sm" onClick={() => setIsModalOpen(true)} style={{ padding: '4px 8px', fontSize: '11px' }}>
                    🗺️ Tactical Map
                  </button>
                </div>
                
                {/* Dotted Vertical Route Timeline */}
                <div className="timeline-stops">
                  {activePath.map((p, i) => (
                    <div key={p.id} className={`timeline-item status-${p.status}`}>
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontWeight: '500', color: p.status !== 'clear' ? 'var(--text)' : 'var(--text-muted)' }}>
                          {p.name || p.id}
                        </span>
                        <span style={{ fontSize: '9px', color: 'var(--text-dim)' }}>Stop #{i + 1}</span>
                      </div>
                      <code style={{ fontSize: '10px', color: 'var(--text-dim)', padding: '2px 4px', background: '#0f172a', borderRadius: '4px' }}>
                        {p.id}
                      </code>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Disruption Panel */}
          <div className="panel" style={{ marginTop: '12px' }}>
            <h3 className="panel-title">⚡ Disruption Injection</h3>
            <p className="panel-desc" style={{ fontSize: '11px' }}>Simulate a delay to observe how the A* model dynamically routes traffic.</p>
            <input
              className="field-input"
              value={injectTarget}
              onChange={e => setInjectTarget(e.target.value.toUpperCase())}
              placeholder="e.g. C019 / HWH"
            />
            <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
              <button className="btn btn-danger btn-sm" onClick={handleInject} disabled={injecting} style={{ flex: 1 }}>
                {injecting ? 'Injecting…' : 'Inject Delay'}
              </button>
              {delayedNodeIds.length > 0 && (
                <button className="btn btn-secondary btn-sm" onClick={handleClear} style={{ flex: 1 }}>
                  Clear
                </button>
              )}
            </div>
            {disruptionMessage && (
              <div className={`alert alert-${disruptionMessage.type}`} style={{ fontSize: '11px', marginTop: '8px', padding: '6px 8px' }}>
                {disruptionMessage.text}
              </div>
            )}
          </div>
        </aside>

        <section className="dashboard-main-area" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <div style={{ flex: 0.5, position: 'relative', minHeight: '300px' }}>
            <GraphComponent 
              highlightPath={shortestNodeIds} 
              alternativePath={detourNodeIds}
              xaiEvidenceIds={xaiEvidenceIds}
              onNodeSelect={handleNodeSelect}
            />
          </div>

          <div className="rescheduling-insights-center" style={{ flex: 0.5, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', padding: '16px 20px', borderTop: '1px solid var(--border)', background: 'var(--bg-panel)', overflowY: 'auto' }}>
            {/* Left Column: Predictions Table */}
            <div className="predictions-column" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <h3 className="panel-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: 0 }}>
                <span>🔮 HSR-RailFlow Delay Predictions</span>
                {latestRescheduling && (
                  <span style={{ fontSize: '11px', textTransform: 'none', color: 'var(--text-muted)' }}>
                    Policy: <code>{latestRescheduling.policy_name}</code> ({latestRescheduling.compute_time_ms} ms)
                  </span>
                )}
              </h3>
              
              {latestRescheduling && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
                  <div className="kpi-card" style={{ padding: '6px 8px', borderRadius: '6px' }}>
                    <span className="kpi-label" style={{ fontSize: '9px', margin: 0 }}>Delay Before</span>
                    <span className="kpi-value" style={{ fontSize: '13px', margin: '2px 0 0' }}>{latestRescheduling.objective_before?.toFixed(1)}m</span>
                  </div>
                  <div className="kpi-card" style={{ padding: '6px 8px', borderRadius: '6px' }}>
                    <span className="kpi-label" style={{ fontSize: '9px', margin: 0 }}>Delay After</span>
                    <span className="kpi-value" style={{ fontSize: '13px', margin: '2px 0 0', color: 'var(--success)' }}>{latestRescheduling.objective_after?.toFixed(1)}m</span>
                  </div>
                  <div className="kpi-card" style={{ padding: '6px 8px', borderRadius: '6px' }}>
                    <span className="kpi-label" style={{ fontSize: '9px', margin: 0 }}>Shield Status</span>
                    <span className="delay-badge delay-ok" style={{ fontSize: '10px', padding: '2px 4px', marginTop: '2px' }}>
                      {latestRescheduling.status?.toUpperCase()}
                    </span>
                  </div>
                </div>
              )}

              <div className="table-wrap" style={{ flex: 1, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: '6px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Train</th>
                      <th>Horizon</th>
                      <th>Expected (p50)</th>
                      <th>Worst-case (p90)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!latestRescheduling?.predictions || latestRescheduling.predictions.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="empty-row" style={{ padding: '15px', textAlign: 'center' }}>
                          No active delay predictions. Inject a delay to run the rescheduler.
                        </td>
                      </tr>
                    ) : (
                      latestRescheduling.predictions.map((p, idx) => (
                        <tr key={idx}>
                          <td><strong>{p.train_number}</strong></td>
                          <td>{p.horizon_minutes}m</td>
                          <td>
                            <span className={`delay-badge ${p.p50_delay_seconds > 600 ? 'delay-high' : p.p50_delay_seconds > 0 ? 'delay-med' : 'delay-ok'}`}>
                              {(p.p50_delay_seconds / 60.0).toFixed(1)}m
                            </span>
                          </td>
                          <td>
                            <span className={`delay-badge ${p.p90_delay_seconds > 900 ? 'delay-high' : p.p90_delay_seconds > 0 ? 'delay-med' : 'delay-ok'}`} style={{ opacity: 0.8 }}>
                              {(p.p90_delay_seconds / 60.0).toFixed(1)}m
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Right Column: Rescheduling Insights / XAI Reasoning Trace */}
            <div className="xai-column" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <h3 className="panel-title" style={{ margin: 0 }}>🛡️ Rescheduling Insights & XAI</h3>
              <p className="panel-desc" style={{ margin: 0, fontSize: '11px' }}>
                Click decisions to highlight conflicting trains or stations on the map.
              </p>

              <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                {!latestRescheduling?.actions || latestRescheduling.actions.length === 0 ? (
                  <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-dim)', border: '1px dashed var(--border)', borderRadius: '6px', margin: 'auto' }}>
                    Network nominal. No conflict resolution actions required.
                  </div>
                ) : (
                  latestRescheduling.actions.map((act) => {
                    const isActive = activeXaiSeq === act.sequence;
                    const constraintColor = act.why?.constraint_violated === 'BLOCKAGE' ? '#ef4444' : 
                                            act.why?.constraint_violated === 'PRECEDENCE_CONFLICT' ? '#3b82f6' : '#f59e0b';
                    
                    return (
                      <div
                        key={act.sequence}
                        onClick={() => {
                          if (isActive) {
                            setXaiEvidenceIds([]);
                            setActiveXaiSeq(null);
                          } else {
                            setXaiEvidenceIds(act.why?.evidence_ids || []);
                            setActiveXaiSeq(act.sequence);
                          }
                        }}
                        style={{ borderLeftColor: constraintColor }}
                        className={`xai-item-card ${isActive ? 'active' : ''}`}
                      >
                        <span style={{
                          background: '#070a13',
                          color: 'var(--text-muted)',
                          width: '18px',
                          height: '18px',
                          borderRadius: '50%',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '10px',
                          fontWeight: 'bold',
                          marginTop: '2px'
                        }}>
                          {act.sequence}
                        </span>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                            <span style={{
                              fontSize: '9px',
                              textTransform: 'uppercase',
                              fontWeight: 'bold',
                              padding: '1px 4px',
                              borderRadius: '3px',
                              background: `${constraintColor}22`,
                              color: constraintColor,
                            }}>
                              {act.why?.constraint_violated || 'CONSTRAINT'}
                            </span>
                            <span style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
                              Type: {act.type}
                            </span>
                          </div>
                          <span style={{ fontSize: '11px', color: '#f8fafc', lineHeight: '1.3' }}>
                            {act.why?.explanation || act.explanation}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
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