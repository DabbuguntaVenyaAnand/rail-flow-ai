import React, { useEffect, useRef, useMemo } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import { useNetwork } from '../context/NetworkContext';
import { STATUS_COLORS, DISRUPTION_COLORS } from '../constants/colors';

const LAYER_BORDER = { corridor: '#6366f1', hub: '#f97316' };

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
      'cursor': 'pointer',
    },
  },
  {
    selector: 'node.disruption-source',
    style: { 'background-color': DISRUPTION_COLORS.source, 'border-color': '#fca5a5', 'border-width': 3 },
  },
  {
    selector: 'node.disruption-impacted',
    style: { 'background-color': DISRUPTION_COLORS.impacted, 'border-color': '#fdba74', 'border-width': 3 },
  },
  {
    selector: 'node.highlight',
    style: { 'border-width': 4, 'border-color': '#fbbf24', 'z-index': 999 },
  },
  {
    selector: 'edge',
    style: {
      width: 1.5,
      'line-color': '#475569',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      opacity: 0.5,
    },
  },
  {
    selector: 'edge.highlight',
    style: { width: 3, 'line-color': '#fbbf24', opacity: 1, 'z-index': 999 },
  },
  {
    selector: 'node.detour-highlight',
    style: { 'border-width': 4, 'border-color': '#10b981', 'z-index': 999 },
  },
  {
    selector: 'edge.detour-highlight',
    style: { width: 3, 'line-color': '#10b981', opacity: 1, 'z-index': 999 },
  },
];

export default function GraphComponent({ highlightPath = null, alternativePath = null, className = '', onNodeSelect = null }) {
  const cyRef = useRef(null);
  const { graphData, isLoading, error, delayedNodeIds, impactedNodeIds, disruptionRevision, selectedNodeId } = useNetwork();

  const elements = useMemo(() => {
    if (!graphData?.elements) return [];
    return graphData.elements.nodes.map(n => ({
      data: { 
        ...n.data, 
        label: n.data.label || n.data.name || n.data.id || '',
        statusColor: STATUS_COLORS[n.data.status] ?? '#94a3b8', 
        layerColor: LAYER_BORDER[n.data.layer] ?? '#94a3b8', 
        nodeSize: n.data.layer === 'hub' ? 16 : 10 
      },
      position: n.position || n.data.position
    })).concat(graphData.elements.edges);
  }, [graphData]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    
    cy.batch(() => {
      // Clear previous styles
      cy.elements().removeClass('disruption-source disruption-impacted highlight detour-highlight');
      
      // Apply Disruption
      delayedNodeIds.forEach(id => cy.getElementById(id)?.addClass('disruption-source'));
      impactedNodeIds.forEach(id => cy.getElementById(id)?.addClass('disruption-impacted'));
      
      // Apply Path Highlight
      if (highlightPath && highlightPath.length > 0) {
        highlightPath.forEach(id => cy.getElementById(id)?.addClass('highlight'));
        for (let i = 0; i < highlightPath.length - 1; i++) {
          const edge = cy.edges(`[source="${highlightPath[i]}"][target="${highlightPath[i+1]}"]`);
          edge.addClass('highlight');
        }
      }

      // Apply Detour Path Highlight
      if (alternativePath && alternativePath.length > 0) {
        alternativePath.forEach(id => cy.getElementById(id)?.addClass('detour-highlight'));
        for (let i = 0; i < alternativePath.length - 1; i++) {
          const edge = cy.edges(`[source="${alternativePath[i]}"][target="${alternativePath[i+1]}"]`);
          edge.addClass('detour-highlight');
        }
      }
    });
  }, [delayedNodeIds, impactedNodeIds, disruptionRevision, highlightPath, alternativePath]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (highlightPath && highlightPath.length > 0) {
      cy.animate({
        fit: { eles: cy.elements('.highlight, .detour-highlight'), padding: 50 },
        duration: 500
      });
    } else {
      cy.animate({
        fit: { eles: cy.elements(), padding: 30 },
        duration: 500
      });
    }
  }, [highlightPath]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !selectedNodeId) return;
    const node = cy.getElementById(selectedNodeId);
    if (node.length > 0) {
      cy.animate({
        center: { eles: node },
        zoom: 2.5,
        duration: 500
      });
      // Apply temporal highlight to focused node
      node.addClass('highlight');
    }
  }, [selectedNodeId]);

  if (isLoading) return <div className="graph-loading">Loading network graph…</div>;
  if (error) return <div className="graph-error">Failed to load graph: {error}</div>;

  return (
    <div className={`graph-container ${className}`}>
      <CytoscapeComponent
        elements={elements}
        style={{ width: '100%', height: '100%' }}
        stylesheet={CY_STYLE}
        layout={{ name: 'preset' }}
        cy={(cy) => {
          cyRef.current = cy;
          cy.off('tap', 'node');
          cy.on('tap', 'node', (evt) => {
            const node = evt.target;
            if (onNodeSelect) {
              onNodeSelect({
                id: node.id(),
                label: node.data('name') || node.id(),
                status: node.data('status'),
                layer: node.data('layer'),
              });
            }
          });
        }}
      />
    </div>
  );
}