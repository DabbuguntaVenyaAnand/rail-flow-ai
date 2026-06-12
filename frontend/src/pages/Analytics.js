import React, { useState } from 'react';
import { useNetwork } from '../context/NetworkContext';
import { predictRippleOutcome } from '../utils/disruptionPredictor';

export default function Analytics() {
  const {
    isLoading,
    graphData,
    delayedNodeIds,
    impactedNodeIds,
    stationReport,
    searchStation,
    propagationDepth,
  } = useNetwork();

  const [analyzeCode, setAnalyzeCode] = useState('');
  const [localAnalysis, setLocalAnalysis] = useState(null);

  const handleAnalyze = async (e) => {
    e.preventDefault();
    if (!analyzeCode.trim()) return;
    const report = await searchStation(analyzeCode);
    if (report?.station) {
      setLocalAnalysis(predictRippleOutcome(report.station.id, graphData, report.history));
    }
  };

  if (isLoading) {
    return <div className="page-loading"><div className="spinner" /><p>Loading analytics…</p></div>;
  }

  const nodes = graphData?.elements?.nodes ?? [];
  const delayedCount = nodes.filter(n => n.data.status === 'delayed').length;
  const congestionCount = nodes.filter(n => n.data.status === 'congestion').length;

  return (
    <div className="analytics-page">
      <div className="page-header">
        <div>
          <h2>AI Analytics</h2>
          <p className="page-subtitle">Historical delay patterns · ripple prediction · network health scoring</p>
        </div>
      </div>

      <div className="analytics-grid">
        <div className="analytics-kpis">
          <div className="kpi-card">
            <span className="kpi-value">{nodes.length}</span>
            <span className="kpi-label">Network nodes</span>
          </div>
          <div className="kpi-card kpi-red">
            <span className="kpi-value">{delayedCount + delayedNodeIds.length}</span>
            <span className="kpi-label">Delayed stations</span>
          </div>
          <div className="kpi-card kpi-yellow">
            <span className="kpi-value">{congestionCount}</span>
            <span className="kpi-label">Congestion</span>
          </div>
          <div className="kpi-card kpi-orange">
            <span className="kpi-value">{impactedNodeIds.length}</span>
            <span className="kpi-label">Ripple impacted</span>
          </div>
        </div>

        <div className="panel">
          <h3 className="panel-title">Delay Risk Analyzer</h3>
          <form onSubmit={handleAnalyze} className="search-form">
            <input
              className="field-input"
              value={analyzeCode}
              onChange={e => setAnalyzeCode(e.target.value)}
              placeholder="Station code to analyze"
            />
            <button className="btn btn-primary" type="submit">Analyze</button>
          </form>
        </div>

        {stationReport?.history && (
          <div className="panel">
            <h3 className="panel-title">Historical Delays — {stationReport.station.name}</h3>
            <div className="history-chart">
              {stationReport.history.weekly_history?.map(day => (
                <div key={day.date} className="history-bar-col">
                  <div
                    className="history-bar"
                    style={{ height: `${Math.min(100, day.avg_delay_min * 2)}%` }}
                    title={`${day.date}: ${day.avg_delay_min} min avg`}
                  />
                  <span className="history-label">{day.date.slice(5)}</span>
                </div>
              ))}
            </div>
            <div className="mini-stats">
              <div><span>{stationReport.history.incidents_30d}</span> incidents / 30d</div>
              <div><span>{stationReport.history.max_delay_min}</span> max delay min</div>
              <div><span>{Math.round(stationReport.history.resolution_rate * 100)}%</span> resolution rate</div>
            </div>
          </div>
        )}

        {(localAnalysis || stationReport?.prediction) && (
          <div className="panel prediction-panel">
            <h3 className="panel-title">Ripple Prediction</h3>
            <PredictionCard
              prediction={localAnalysis ?? stationReport?.clientPrediction}
              serverPrediction={stationReport?.prediction}
              depth={propagationDepth}
            />
          </div>
        )}

        <div className="panel">
          <h3 className="panel-title">Active Disruption Summary</h3>
          {delayedNodeIds.length === 0 ? (
            <p className="panel-hint">No active injected disruptions. Use Dashboard to simulate.</p>
          ) : (
            <ul className="disruption-list">
              {delayedNodeIds.map(id => (
                <li key={id}>
                  <span className="dot dot-red" /> {id} — source
                </li>
              ))}
              {impactedNodeIds.slice(0, 20).map(id => (
                <li key={id}>
                  <span className="dot dot-orange" /> {id} — ripple impact
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function PredictionCard({ prediction, serverPrediction, depth }) {
  if (!prediction) return null;
  const prob = prediction.rippleProbability ?? Math.round((serverPrediction?.ripple_probability ?? 0) * 100);
  const willRipple = prediction.willRipple ?? serverPrediction?.will_ripple;

  return (
    <div className="prediction-detail">
      <div className={`verdict ${willRipple ? 'verdict-alert' : 'verdict-ok'}`}>
        {willRipple ? '⚠ Cascade likely' : '✓ Likely self-contained'}
      </div>
      <div className="prediction-meter large">
        <div className="prediction-fill" style={{ width: `${prob}%` }} />
      </div>
      <p><strong>{prob}%</strong> ripple probability at depth {depth}</p>
      <p className="prediction-note">{prediction.resolutionEstimate ?? serverPrediction?.resolution_estimate}</p>
      {prediction.factors && (
        <ul className="factor-list">
          {prediction.factors.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
      )}
      {serverPrediction?.impacted_nodes?.length > 0 && (
        <div className="impact-list">
          <h4>Predicted impact ({serverPrediction.predicted_impact_count} stations)</h4>
          <ul>
            {serverPrediction.impacted_nodes.slice(0, 8).map(n => (
              <li key={n.id}><span className="hop-badge">H{n.hop}</span> {n.id}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
