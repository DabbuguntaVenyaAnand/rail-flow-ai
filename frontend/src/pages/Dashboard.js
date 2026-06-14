import React, { useState, useEffect } from 'react';
import { useNetwork } from '../context/NetworkContext';
import GraphComponent from '../components/GraphComponent';
import DisruptionPanel from '../components/DisruptionPanel';
import StationSearchReport from '../components/StationSearchReport';

export default function Dashboard() {
  const {
    isLoading,
    selectedNodeId,
    searchStation,
    delayedNodeIds,
    latestRescheduling,
    fetchLatestRescheduling,
    graphData
  } = useNetwork();
  
  const [clickedNode, setClickedNode] = useState(null);
  
  // XAI Glass Box States
  const [activeXaiEvidenceIds, setActiveXaiEvidenceIds] = useState([]);
  const [activeXaiPulseNodeId, setActiveXaiPulseNodeId] = useState(null);
  const [selectedXaiActionSeq, setSelectedXaiActionSeq] = useState(null);

  // Poll latest rescheduling run on mount and when disruptions exist
  useEffect(() => {
    fetchLatestRescheduling();
    const interval = setInterval(fetchLatestRescheduling, 5000);
    return () => clearInterval(interval);
  }, [fetchLatestRescheduling, delayedNodeIds]);

  // Reset XAI focus when disruptions are cleared
  useEffect(() => {
    if (delayedNodeIds.length === 0) {
      setSelectedXaiActionSeq(null);
      setActiveXaiEvidenceIds([]);
      setActiveXaiPulseNodeId(null);
    }
  }, [delayedNodeIds]);

  const handleNodeSelect = (node) => {
    setClickedNode(node);
    if (node?.id) {
      searchStation(node.id);
    }
  };

  const handleXaiClick = (action) => {
    if (selectedXaiActionSeq === action.sequence) {
      setSelectedXaiActionSeq(null);
      setActiveXaiEvidenceIds([]);
      setActiveXaiPulseNodeId(null);
    } else {
      setSelectedXaiActionSeq(action.sequence);
      const evidence = action.why?.evidence_ids || [];
      setActiveXaiEvidenceIds(evidence);
      
      const stationIds = new Set(graphData?.elements?.nodes?.map(n => n.data.id) || []);
      const pulseNode = action.station_code || evidence.find(id => stationIds.has(id));
      setActiveXaiPulseNodeId(pulseNode || null);
    }
  };

  if (isLoading) {
    return (
      <div className="page-loading">
        <div className="spinner" />
        <p>Loading network graph twin…</p>
      </div>
    );
  }

  const isDisrupted = delayedNodeIds.length > 0;

  return (
    <div className="dashboard-page" style={{ height: 'calc(100vh - 64px)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="page-header" style={{ flexShrink: 0, padding: '12px 24px 8px' }}>
        <div>
          <h2>Control Tower Command Center</h2>
          <p className="page-subtitle">
            HSR-RailFlow Digital Twin · Real-time operational optimization & explainable reasoning traces
          </p>
        </div>
      </div>

      <div className="dashboard-grid" style={{ flex: 1, display: 'grid', gridTemplateColumns: '340px 1fr', overflow: 'hidden' }}>
        <aside className="dashboard-sidebar" style={{ overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          
          {/* Fleet Resilience Monitor */}
          <div className="panel fleet-resilience-monitor" style={{ border: '1px solid var(--border)', background: 'var(--bg-panel)', borderRadius: 'var(--radius)', padding: '16px' }}>
            <h3 className="panel-title" style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
              🛡️ Fleet Resilience Monitor
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Rescheduling Engine</span>
                <span style={{
                  fontSize: '11px',
                  fontWeight: 'bold',
                  color: latestRescheduling ? 'var(--yellow)' : 'var(--success)',
                  background: latestRescheduling ? 'rgba(234, 179, 8, 0.15)' : 'rgba(34, 197, 94, 0.15)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  border: latestRescheduling ? '1px solid var(--yellow)' : '1px solid var(--success)'
                }}>
                  {latestRescheduling ? `Run #${String(latestRescheduling.rescheduling_run_id).substring(0, 8)} Active` : 'System Nominal'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Shield Status</span>
                <span style={{
                  fontSize: '11px',
                  fontWeight: 'bold',
                  color: isDisrupted ? 'var(--success)' : 'var(--text-dim)',
                  background: isDisrupted ? 'rgba(34, 197, 94, 0.15)' : 'rgba(148, 163, 184, 0.05)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  border: isDisrupted ? '1px solid var(--success)' : '1px solid var(--border)'
                }}>
                  {isDisrupted ? 'Active: PASS' : 'Nominal'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Conflict Count</span>
                <span style={{
                  fontSize: '12px',
                  fontWeight: 'bold',
                  color: (latestRescheduling?.actions?.filter(a => a.type === 'set_precedence')?.length || 0) > 0 ? 'var(--danger)' : 'var(--text-muted)'
                }}>
                  {latestRescheduling?.actions?.filter(a => a.type === 'set_precedence')?.length || 0}
                </span>
              </div>
            </div>
          </div>

          <StationSearchReport />
          <DisruptionPanel />

          {(clickedNode || selectedNodeId) && (
            <div className="panel">
              <h3 className="panel-title">📍 Selected Node</h3>
              {clickedNode ? (
                <dl className="report-dl">
                  <dt>Name</dt><dd>{clickedNode.label}</dd>
                  <dt>ID</dt><dd>{clickedNode.id}</dd>
                  <dt>Status</dt><dd>{clickedNode.status}</dd>
                  <dt>Layer</dt><dd>{clickedNode.layer}</dd>
                </dl>
              ) : (
                <p className="panel-hint">Node {selectedNodeId} selected</p>
              )}
            </div>
          )}
        </aside>

        {isDisrupted ? (
          <section className="dashboard-main-area" style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ height: '60%', borderBottom: '1px solid var(--border)', position: 'relative' }}>
              <GraphComponent 
                onNodeSelect={handleNodeSelect} 
                xaiEvidenceIds={activeXaiEvidenceIds}
                xaiPulseNodeId={activeXaiPulseNodeId}
              />
            </div>
            
            {/* Bottom Panel (Rescheduling Hub) */}
            <div style={{ height: '40%', display: 'flex', overflow: 'hidden', background: 'var(--bg-panel)' }}>
              {/* Predictions Table (40%) */}
              <div style={{ width: '40%', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', padding: '16px', overflowY: 'auto' }}>
                <h3 style={{ margin: '0 0 12px 0', fontSize: '13px', color: '#00d4ff', fontWeight: 600 }}>
                  📊 GNN Delay Predictions
                </h3>
                {latestRescheduling?.predictions && latestRescheduling.predictions.length > 0 ? (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                        <th style={{ padding: '6px' }}>Train</th>
                        <th style={{ padding: '6px' }}>Horizon</th>
                        <th style={{ padding: '6px' }}>p50</th>
                        <th style={{ padding: '6px' }}>p90</th>
                        <th style={{ padding: '6px' }}>Model</th>
                      </tr>
                    </thead>
                    <tbody>
                      {latestRescheduling.predictions.map((p, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                          <td style={{ padding: '6px', fontWeight: 'bold' }}>{p.train_number}</td>
                          <td style={{ padding: '6px' }}>{p.horizon_minutes}m</td>
                          <td style={{ padding: '6px', color: 'var(--yellow)' }}>{Math.round(p.p50_delay_seconds / 60)}m</td>
                          <td style={{ padding: '6px', color: 'var(--danger)' }}>{Math.round(p.p90_delay_seconds / 60)}m</td>
                          <td style={{ padding: '6px', color: 'var(--text-dim)' }}>{p.model_version}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p style={{ fontSize: '12px', color: 'var(--text-dim)', fontStyle: 'italic' }}>No active delay predictions.</p>
                )}
              </div>

              {/* XAI Reasoning Trace (60%) */}
              <div style={{ width: '60%', display: 'flex', flexDirection: 'column', padding: '16px', overflowY: 'auto' }}>
                <h3 style={{ margin: '0 0 12px 0', fontSize: '13px', color: '#ef4444', fontWeight: 600 }}>
                  ⚙️ Resolution & Explainability Panel
                </h3>
                {latestRescheduling?.actions && latestRescheduling.actions.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {latestRescheduling.actions.map((action) => {
                      const isSelected = selectedXaiActionSeq === action.sequence;
                      const constraint = action.why?.constraint_violated || action.constraint_violated || 'UNKNOWN';
                      
                      let badgeColor = 'var(--text-muted)';
                      let badgeBg = 'rgba(148, 163, 184, 0.1)';
                      if (constraint === 'PRECEDENCE_CONFLICT') {
                        badgeColor = 'var(--yellow)';
                        badgeBg = 'rgba(234, 179, 8, 0.15)';
                      } else if (constraint === 'BLOCKAGE') {
                        badgeColor = 'var(--danger)';
                        badgeBg = 'rgba(239, 68, 68, 0.15)';
                      } else if (constraint === 'HEADWAY_GAP') {
                        badgeColor = 'var(--accent)';
                        badgeBg = 'rgba(99, 102, 241, 0.15)';
                      }

                      return (
                        <div 
                          key={action.sequence}
                          onClick={() => handleXaiClick(action)}
                          style={{
                            background: isSelected ? 'var(--bg-elevated)' : 'rgba(255,255,255,0.02)',
                            border: isSelected ? '1px solid var(--accent)' : '1px solid rgba(255,255,255,0.05)',
                            borderRadius: '6px',
                            padding: '10px 12px',
                            cursor: 'pointer',
                            transition: 'all 0.2s',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '6px'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '11px', fontWeight: 'bold', color: 'var(--text-muted)' }}>
                              Action #{action.sequence}
                            </span>
                            <span style={{
                              fontSize: '9px',
                              fontWeight: 'bold',
                              color: badgeColor,
                              background: badgeBg,
                              padding: '1px 6px',
                              borderRadius: '4px',
                              textTransform: 'uppercase'
                            }}>
                              {constraint.replace('_', ' ')}
                            </span>
                          </div>
                          <p style={{ margin: 0, fontSize: '12px', color: '#f8fafc', lineHeight: 1.4 }}>
                            {action.why?.explanation || action.explanation}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p style={{ fontSize: '12px', color: 'var(--text-dim)', fontStyle: 'italic' }}>No active rescheduling actions.</p>
                )}
              </div>
            </div>
          </section>
        ) : (
          <section className="dashboard-main-area" style={{ height: '100%', position: 'relative' }}>
            <GraphComponent onNodeSelect={handleNodeSelect} />
          </section>
        )}
      </div>
    </div>
  );
}
