import React, { useState } from 'react';
import { useNetwork } from '../context/NetworkContext';
import { STATUS_COLORS } from './GraphComponent';

export default function StationSearchReport() {
  const { searchStation, stationReport, searchLoading, setSelectedNodeId, injectDelay } = useNetwork();
  const [query, setQuery] = useState('');

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    await searchStation(query);
  };

  const handleInjectFromReport = async () => {
    if (!stationReport?.station) return;
    await injectDelay(stationReport.station.id);
  };

  if (!stationReport && !searchLoading) {
    return (
      <div className="panel">
        <h3 className="panel-title">🔍 Station Report</h3>
        <form onSubmit={handleSearch} className="search-form">
          <input
            className="field-input"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Node ID or alias (e.g. C019 / HWH)"
          />
          <button className="btn btn-primary" type="submit">Search</button>
        </form>
        <p className="panel-hint">Search any station for status, history, and ripple risk.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h3 className="panel-title">🔍 Station Report</h3>
      <form onSubmit={handleSearch} className="search-form">
        <input
          className="field-input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Node ID or alias"
        />
        <button className="btn btn-primary" type="submit" disabled={searchLoading}>
          {searchLoading ? 'Searching…' : 'Search'}
        </button>
      </form>

      {stationReport?.error && (
        <div className="alert alert-error">{stationReport.error}</div>
      )}

      {stationReport?.station && (
        <div className="report-card">
          <div className="report-header">
            <h4>{stationReport.station.name}</h4>
            <StatusBadge status={stationReport.station.status} />
          </div>
          <dl className="report-dl">
            <dt>ID</dt><dd>{stationReport.station.id}</dd>
            <dt>State</dt><dd>{stationReport.station.state}</dd>
            <dt>Zone</dt><dd>{stationReport.station.zone ?? '—'}</dd>
            <dt>Layer</dt><dd>{stationReport.station.layer}</dd>
            <dt>Priority</dt><dd>{stationReport.station.priority}</dd>
          </dl>

          {stationReport.history && (
            <div className="report-section">
              <h5>30-Day History</h5>
              <div className="mini-stats">
                <div><span>{stationReport.history.incidents_30d}</span> incidents</div>
                <div><span>{stationReport.history.avg_delay_min}</span> avg min</div>
                <div><span>{Math.round(stationReport.history.resolution_rate * 100)}%</span> resolved</div>
              </div>
            </div>
          )}

          {stationReport.clientPrediction && (
            <div className="report-section">
              <h5>Ripple Risk Assessment</h5>
              <p className={`risk-label ${stationReport.clientPrediction.willRipple ? 'risk-high' : 'risk-low'}`}>
                {stationReport.clientPrediction.willRipple ? 'Likely to ripple' : 'Likely self-contained'}
                {' '}({stationReport.clientPrediction.rippleProbability}%)
              </p>
              <ul className="factor-list">
                {stationReport.clientPrediction.factors.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="btn-row">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setSelectedNodeId(stationReport.station.id)}
            >
              Focus on map
            </button>
            <button className="btn btn-danger btn-sm" onClick={handleInjectFromReport}>
              Inject delay here
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const color = STATUS_COLORS[status] ?? '#94a3b8';
  return (
    <span className="status-badge" style={{ borderColor: color, color, background: `${color}22` }}>
      {status.toUpperCase()}
    </span>
  );
}
