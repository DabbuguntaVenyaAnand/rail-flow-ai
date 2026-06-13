import React, { useState, useMemo } from 'react';
import { useNetwork } from '../context/NetworkContext';
import { STATUS_COLORS } from '../constants/colors';
import TacticalMapModal from './TacticalMapModal';

export default function StationSearchReport() {
  const { searchStation, stationReport, searchLoading, setSelectedNodeId, injectDelay, graphData } = useNetwork();
  const [query, setQuery] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    await searchStation(query);
  };

  const handleInjectFromReport = async () => {
    if (!stationReport?.station) return;
    await injectDelay(stationReport.station.id);
  };

  // Compute local ego-graph for the searched station
  const tacticalElements = useMemo(() => {
    if (!stationReport?.station || !graphData?.elements) return [];
    
    const focusId = stationReport.station.id;
    const neighborIds = new Set();
    
    // Gather all direct neighbors connected to focusId
    graphData.elements.edges.forEach(e => {
      if (e.data.source === focusId) neighborIds.add(e.data.target);
      if (e.data.target === focusId) neighborIds.add(e.data.source);
    });
    
    // Nodes to display: focus station + neighbors
    const filteredNodes = graphData.elements.nodes.filter(
      n => n.data.id === focusId || neighborIds.has(n.data.id)
    );
    
    const nodes = filteredNodes.map(n => {
      const isFocus = n.data.id === focusId;
      const statusColor = STATUS_COLORS[n.data.status] ?? '#94a3b8';
      const layerColor = n.data.layer === 'hub' ? '#f97316' : '#6366f1';
      
      return {
        data: {
          id: n.data.id,
          label: n.data.name || n.data.id,
          statusColor,
          layerColor,
          nodeSize: isFocus ? 16 : 8
        },
        position: n.position || n.data.position,
        classes: isFocus ? 'highlight' : ''
      };
    });
    
    const allVisibleIds = new Set(filteredNodes.map(n => n.data.id));
    
    // Edges connecting focus station to neighbors
    const filteredEdges = graphData.elements.edges.filter(
      e => allVisibleIds.has(e.data.source) && allVisibleIds.has(e.data.target)
    );
    
    const edges = filteredEdges.map(e => ({
      data: e.data,
      classes: (e.data.source === focusId || e.data.target === focusId) ? 'highlight' : ''
    }));
    
    return nodes.concat(edges);
  }, [stationReport, graphData]);

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
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setIsModalOpen(true)}
            >
              🗺️ Open Tactical Map
            </button>
            <button className="btn btn-danger btn-sm" onClick={handleInjectFromReport}>
              Inject delay here
            </button>
          </div>
        </div>
      )}

      {stationReport?.station && (
        <TacticalMapModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title={`🗺️ Tactical Subgraph - ${stationReport.station.name} Local Connections`}
          description="Displaying the selected station (Yellow focus) and its immediate 1-hop connection neighbors. Status colors indicate real-time node delays."
          elements={tacticalElements}
        />
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
