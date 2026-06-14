import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useNetwork } from '../context/NetworkContext';
import { STATUS_COLORS, DISRUPTION_COLORS } from '../constants/colors';

function getRipplePercent(prediction) {
  if (!prediction) return 0;
  if (prediction.rippleProbability != null) return prediction.rippleProbability;
  if (prediction.ripple_probability != null) {
    return prediction.ripple_probability <= 1
      ? Math.round(prediction.ripple_probability * 100)
      : Math.round(prediction.ripple_probability);
  }
  return 0;
}

export default function DisruptionPanel() {
  const navigate = useNavigate();
  const {
    injectDelay,
    clearDisruptions,
    propagationDepth,
    setPropagationDepth,
    delayedNodeIds,
    impactedNodeIds,
    impactHopMap,
    selectedNodeId,
    fetchRipplePrediction,
    ripplePrediction,
  } = useNetwork();

  const [injectTarget, setInjectTarget] = useState(selectedNodeId ?? '');
  const [injecting, setInjecting] = useState(false);
  const [message, setMessage] = useState(null);

  React.useEffect(() => {
    if (selectedNodeId) setInjectTarget(selectedNodeId);
  }, [selectedNodeId]);

  const handleInject = async () => {
    setInjecting(true);
    setMessage(null);
    const result = await injectDelay(injectTarget, propagationDepth);
    if (result.ok) {
      setMessage({ type: 'success', text: `Delay injected at ${result.station?.name ?? injectTarget}` });
      await fetchRipplePrediction(result.station?.id ?? injectTarget);
    } else {
      setMessage({ type: 'error', text: result.error });
    }
    setInjecting(false);
  };


  const handlePredict = async () => {
    if (!injectTarget.trim()) return;
    await fetchRipplePrediction(injectTarget.trim());
  };

  return (
    <div className="panel disruption-panel">
      <h3 className="panel-title">⚡ Disruption Engine</h3>
      <p className="panel-desc">Inject delays and simulate downstream ripple propagation.</p>

      <label className="field-label">Target station</label>
      <input
        className="field-input"
        value={injectTarget}
        onChange={e => setInjectTarget(e.target.value.toUpperCase())}
        placeholder="e.g. C019 / HWH"
      />

      <label className="field-label">Propagation depth (hops)</label>
      <div className="depth-control">
        <input
          type="range"
          min={1}
          max={5}
          value={propagationDepth}
          onChange={e => setPropagationDepth(Number(e.target.value))}
        />
        <span className="depth-value">{propagationDepth}</span>
      </div>

      <div className="btn-row">
        <button
          className="btn btn-danger"
          onClick={handleInject}
          disabled={injecting || !injectTarget.trim()}
        >
          {injecting ? 'Injecting…' : 'Inject Delay'}
        </button>
        <button className="btn btn-secondary" onClick={handlePredict} disabled={!injectTarget.trim()}>
          Predict
        </button>
      </div>

      {message && (
        <div className={`alert alert-${message.type}`}>{message.text}</div>
      )}

      {(delayedNodeIds.length > 0 || impactedNodeIds.length > 0) && (
        <div className="disruption-summary">
          <div className="summary-row">
            <span className="dot" style={{ background: DISRUPTION_COLORS.source }} />
            <strong>{delayedNodeIds.length}</strong> source(s)
          </div>
          <div className="summary-row">
            <span className="dot" style={{ background: DISRUPTION_COLORS.impacted }} />
            <strong>{impactedNodeIds.length}</strong> impacted (≤{propagationDepth} hops)
          </div>
          <button className="btn btn-ghost btn-sm" onClick={clearDisruptions}>
            Clear all disruptions
          </button>
        </div>
      )}

      {ripplePrediction && (
        <div className="prediction-card">
          <h4>Ripple Forecast</h4>
          <div className="prediction-meter">
            <div
              className="prediction-fill"
              style={{ width: `${getRipplePercent(ripplePrediction)}%` }}
            />
          </div>
          <p className="prediction-value">
            {getRipplePercent(ripplePrediction)}% chance of cascade
          </p>
          <p className="prediction-note">
            {ripplePrediction.resolution_estimate ?? ripplePrediction.resolutionEstimate}
          </p>
          {ripplePrediction.predicted_impact_count != null && (
            <p className="prediction-note">
              Predicted impact: <strong>{ripplePrediction.predicted_impact_count}</strong> stations
            </p>
          )}
        </div>
      )}

      {impactedNodeIds.length > 0 && (
        <div className="impact-list">
          <h4>Impacted nodes</h4>
          <ul>
            {impactedNodeIds.slice(0, 12).map(id => (
              <li key={id}>
                <span className="hop-badge">H{impactHopMap[id]}</span> {id}
              </li>
            ))}
            {impactedNodeIds.length > 12 && (
              <li className="more">+{impactedNodeIds.length - 12} more</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
