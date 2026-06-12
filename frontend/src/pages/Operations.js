import React from 'react';
import { useNetwork } from '../context/NetworkContext';
import TrainStatusTable from '../components/TrainStatusTable';
import GraphComponent from '../components/GraphComponent';

export default function Operations() {
  const { isLoading, trainStatus } = useNetwork();

  if (isLoading) {
    return <div className="page-loading"><div className="spinner" /><p>Loading operations…</p></div>;
  }

  const onTime = trainStatus.filter(t => t.delay_minutes <= 5).length;
  const delayed = trainStatus.filter(t => t.delay_minutes > 15).length;

  return (
    <div className="operations-page">
      <div className="page-header">
        <div>
          <h2>Operations Hub</h2>
          <p className="page-subtitle">Real-time train telemetry and network overlay</p>
        </div>
        <div className="kpi-row">
          <div className="kpi-card">
            <span className="kpi-value">{trainStatus.length}</span>
            <span className="kpi-label">Active trains</span>
          </div>
          <div className="kpi-card kpi-green">
            <span className="kpi-value">{onTime}</span>
            <span className="kpi-label">On time</span>
          </div>
          <div className="kpi-card kpi-red">
            <span className="kpi-value">{delayed}</span>
            <span className="kpi-label">Delayed 15m+</span>
          </div>
        </div>
      </div>

      <div className="ops-grid">
        <div className="ops-table-col">
          <TrainStatusTable />
        </div>
        <div className="ops-graph-col">
          <div className="panel graph-panel">
            <h3 className="panel-title">Network Overlay</h3>
            <GraphComponent showLegend={false} className="ops-graph" />
          </div>
        </div>
      </div>
    </div>
  );
}
