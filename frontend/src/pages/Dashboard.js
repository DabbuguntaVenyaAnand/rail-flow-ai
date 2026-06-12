import React, { useState } from 'react';
import { useNetwork } from '../context/NetworkContext';
import GraphComponent from '../components/GraphComponent';
import DisruptionPanel from '../components/DisruptionPanel';
import StationSearchReport from '../components/StationSearchReport';

export default function Dashboard() {
  const { isLoading, selectedNodeId } = useNetwork();
  const [clickedNode, setClickedNode] = useState(null);

  if (isLoading) {
    return (
      <div className="page-loading">
        <div className="spinner" />
        <p>Loading network graph…</p>
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div>
          <h2>Command Center</h2>
          <p className="page-subtitle">
            Interactive network twin · click nodes to inspect · inject delays to test ripple propagation
          </p>
        </div>
      </div>

      <div className="dashboard-grid">
        <aside className="dashboard-sidebar">
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

        <section className="dashboard-graph">
          <GraphComponent onNodeSelect={setClickedNode} />
        </section>
      </div>
    </div>
  );
}
