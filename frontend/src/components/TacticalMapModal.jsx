import React from 'react';
import CytoscapeComponent from 'react-cytoscapejs';

export default function TacticalMapModal({ isOpen, onClose, title, description, elements }) {
  if (!isOpen) return null;

  return (
    <div className="tactical-modal-overlay" style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(11, 17, 32, 0.85)',
      zIndex: 10000,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '24px',
      backdropFilter: 'blur(8px)'
    }}>
      <div className="panel" style={{
        width: '90%',
        height: '90%',
        maxWidth: '1200px',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        boxShadow: 'var(--shadow)',
        margin: 0
      }}>
        <div className="panel-header-row" style={{ marginBottom: 16 }}>
          <h3 className="panel-title" style={{ fontSize: '16px', margin: 0 }}>
            {title}
          </h3>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Close Window
          </button>
        </div>
        <p className="panel-desc" style={{ marginBottom: 16 }}>
          {description}
        </p>
        <div style={{ flex: 1, position: 'relative', border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: '#0b1120' }}>
          <CytoscapeComponent
            elements={elements}
            style={{ width: '100%', height: '100%' }}
            stylesheet={[
              {
                selector: 'node',
                style: {
                  label: 'data(label)',
                  'font-size': 9,
                  'text-valign': 'bottom',
                  'text-margin-y': 4,
                  'background-color': 'data(statusColor)',
                  'border-width': 2,
                  'border-color': 'data(layerColor)',
                  width: 'data(nodeSize)',
                  height: 'data(nodeSize)',
                  color: '#fff',
                  'text-outline-color': '#1e293b',
                  'text-outline-width': 1.5,
                }
              },
              {
                selector: 'node.highlight',
                style: { 'border-width': 4, 'border-color': '#fbbf24', 'z-index': 999 }
              },
              {
                selector: 'node.detour-highlight',
                style: { 'border-width': 4, 'border-color': '#10b981', 'z-index': 999 }
              },
              {
                selector: 'edge',
                style: {
                  width: 2.5,
                  'line-color': '#475569',
                  'target-arrow-shape': 'none',
                  'curve-style': 'bezier',
                  opacity: 0.4
                }
              },
              {
                selector: 'edge.highlight',
                style: { width: 4, 'line-color': '#fbbf24', opacity: 1, 'z-index': 999 }
              },
              {
                selector: 'edge.detour-highlight',
                style: { width: 4, 'line-color': '#10b981', opacity: 1, 'z-index': 999 }
              }
            ]}
            layout={{ name: 'preset' }}
            cy={(cy) => {
              setTimeout(() => cy.fit(undefined, 45), 150);
            }}
          />
        </div>
      </div>
    </div>
  );
}
