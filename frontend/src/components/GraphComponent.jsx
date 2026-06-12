// GraphComponent.jsx — Interactive cytoscape layer driven by NetworkContext
import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import cola from 'cytoscape-cola';
import { useNetwork } from '../context/NetworkContext';

cytoscape.use(cola);

export const STATUS_COLORS = {
  clear: '#22c55e',
  congestion: '#eab308',
  delayed: '#ef4444',
};

export const DISRUPTION_COLORS = {
  source: '#ef4444',
  impacted: '#f97316',
};

const LAYER_BORDER = {
  corridor: '#6366f1',
  hub: '#f97316',
};

const CY_STYLE = [
  {
    selector: 'node',
    style: {
      label: 'data(label)',
      'font-size': 7,
      'text-valign': 'bottom',
      'text-margin-y': 3,
      'background-color': 'data(statusColor)',
      'border-width': 2,
      'border-color': 'data(layerColor)',
      width: 'data(nodeSize)',
      height: 'data(nodeSize)',
      color: '#fff',
      'text-outline-color': '#1e293b',
      'text-outline-width': 1,
      'transition-property': 'background-color, border-color',
      'transition-duration': '0.3s',
    },
  },
  {
    selector: 'node.disruption-source',
    style: {
      'background-color': DISRUPTION_COLORS.source,
      'border-color': '#fca5a5',
      'border-width': 3,
    },
  },
  {
    selector: 'node.disruption-impacted',
    style: {
      'background-color': DISRUPTION_COLORS.impacted,
      'border-color': '#fdba74',
      'border-width': 3,
    },
  },
  {
    selector: 'node:selected',
    style: {
      'border-width': 4,
      'border-color': '#fff',
      'overlay-color': '#fff',
      'overlay-opacity': 0.15,
    },
  },
  {
    selector: 'edge',
    style: {
      width: 1.5,
      'line-color': '#475569',
      'target-arrow-shape': 'triangle',
      'target-arrow-color': '#475569',
      'curve-style': 'bezier',
      opacity: 0.5,
    },
  },
  {
    selector: 'edge.ripple-edge',
    style: {
      width: 2.5,
      'line-color': '#f97316',
      'target-arrow-color': '#f97316',
      opacity: 0.85,
    },
  },
  {
    selector: 'edge.highlighted-path',
    style: {
      width: 3,
      'line-color': '#f59e0b',
      'target-arrow-color': '#f59e0b',
      opacity: 1,
    },
  },
  {
    selector: 'node.on-path',
    style: {
      'border-width': 4,
      'border-color': '#f59e0b',
    },
  },
];

export default function GraphComponent({
  highlightPath = null,
  onNodeSelect,
  className = '',
  showLegend = true,
}) {
  const cyRef = useRef(null);
  const layoutConfig = useRef({
    name: 'cola',
    animate: true,
    animationDuration: 800,
    nodeSpacing: 5,
    edgeLengthVal: 60,
    maxSimulationTime: 3000,
  });

  const {
    graphData,
    isLoading,
    delayedNodeIds,
    impactedNodeIds,
    impactHopMap,
    selectedNodeId,
    setSelectedNodeId,
    disruptionRevision,
  } = useNetwork();

  const [stats, setStats] = useState({ total: 0, delayed: 0, congestion: 0, impacted: 0 });

  const elements = useMemo(() => {
    if (!graphData?.elements) return [];
    const nodes = graphData.elements.nodes.map(n => ({
      data: {
        ...n.data,
        label: n.data.label,
        statusColor: STATUS_COLORS[n.data.status] ?? '#94a3b8',
        layerColor: LAYER_BORDER[n.data.layer] ?? '#94a3b8',
        nodeSize: n.data.layer === 'hub' ? 16 : 10,
      },
    }));
    return [...nodes, ...graphData.elements.edges];
  }, [graphData]);

  // Apply disruption styling when delayed/impacted sets change
  const applyDisruptionStyles = useCallback(() => {
    const cy = cyRef.current;
    if (!cy || !cy.nodes) return;

    cy.batch(() => {
      cy.nodes().removeClass('disruption-source disruption-impacted on-path');
      cy.edges().removeClass('ripple-edge highlighted-path');

      cy.nodes().forEach(node => {
        const id = node.id();
        const baseStatus = node.data('status');
        if (delayedNodeIds.includes(id)) {
          node.addClass('disruption-source');
        } else if (impactedNodeIds.includes(id)) {
          node.addClass('disruption-impacted');
        } else {
          node.data('statusColor', STATUS_COLORS[baseStatus] ?? '#94a3b8');
        }
      });

      // Highlight ripple edges (source → impacted)
      for (const impactedId of impactedNodeIds) {
        for (const sourceId of delayedNodeIds) {
          cy.edges(`[source="${sourceId}"][target="${impactedId}"]`).addClass('ripple-edge');
        }
        const hop = impactHopMap[impactedId];
        if (hop > 1) {
          for (const sourceId of impactedNodeIds) {
            if (impactHopMap[sourceId] === hop - 1) {
              cy.edges(`[source="${sourceId}"][target="${impactedId}"]`).addClass('ripple-edge');
            }
          }
        }
      }

      if (highlightPath?.length) {
        highlightPath.forEach(id => cy.getElementById(id).addClass('on-path'));
        for (let i = 0; i < highlightPath.length - 1; i++) {
          cy.edges(
            `[source="${highlightPath[i]}"][target="${highlightPath[i + 1]}"]`
          ).addClass('highlighted-path');
        }
      }
    });

    setStats({
      total: cy.nodes().length,
      delayed: delayedNodeIds.length,
      congestion: cy.nodes().filter(n => n.data('status') === 'congestion').length,
      impacted: impactedNodeIds.length,
    });
  }, [delayedNodeIds, impactedNodeIds, impactHopMap, highlightPath]);

  useEffect(() => {
    applyDisruptionStyles();
  }, [applyDisruptionStyles, disruptionRevision, elements]);

  // Pan to selected node
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !selectedNodeId) return;
    const node = cy.getElementById(selectedNodeId);
    if (node.length) {
      cy.animate({ center: { eles: node }, zoom: 2.5 }, { duration: 500 });
      cy.elements().unselect();
      node.select();
    }
  }, [selectedNodeId]);

  const onCyReady = useCallback((cy) => {
    cyRef.current = cy;
    cy.on('tap', 'node', (evt) => {
      const data = evt.target.data();
      setSelectedNodeId(data.id);
      onNodeSelect?.(data);
    });
    cy.on('tap', (evt) => {
      if (evt.target === cy) onNodeSelect?.(null);
    });
  }, [setSelectedNodeId, onNodeSelect]);

  if (isLoading) {
    return <div className="graph-loading">Loading network graph…</div>;
  }

  if (!elements.length) {
    return <div className="graph-error">No graph data — is the Flask server running?</div>;
  }

  return (
    <div className={`graph-container ${className}`}>
      {showLegend && (
        <div className="graph-legend">
          <LegendDot color={STATUS_COLORS.clear} label="Clear" />
          <LegendDot color={STATUS_COLORS.congestion} label="Congestion" />
          <LegendDot color={DISRUPTION_COLORS.source} label="Delayed (injected)" />
          <LegendDot color={DISRUPTION_COLORS.impacted} label="Ripple impact" />
        </div>
      )}
      <div className="graph-stats-bar">
        <span>{stats.total} nodes</span>
        <span className="stat-delayed">{stats.delayed} delayed</span>
        <span className="stat-impacted">{stats.impacted} impacted</span>
      </div>
      <CytoscapeComponent
        elements={elements}
        style={{ width: '100%', height: '100%' }}
        stylesheet={CY_STYLE}
        layout={layoutConfig.current}
        cy={onCyReady}
        wheelSensitivity={0.3}
      />
    </div>
  );
}

function LegendDot({ color, label }) {
  return (
    <span className="legend-item">
      <span className="legend-dot" style={{ background: color }} />
      {label}
    </span>
  );
}
