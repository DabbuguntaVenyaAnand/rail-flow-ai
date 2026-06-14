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
    style: { 'border-width': 4, 'border-color': '#fbbf24', 'z-index': 999, opacity: 1 },
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
    style: { width: 3.5, 'line-color': '#fbbf24', opacity: 1, 'z-index': 999 },
  },
  {
    selector: 'node.detour-highlight',
    style: { 'border-width': 4, 'border-color': '#10b981', 'z-index': 999 },
  },
  {
    selector: 'edge.detour-highlight',
    style: { width: 3, 'line-color': '#10b981', opacity: 1, 'z-index': 999 },
  },
  {
    selector: 'node.pruned',
    style: {
      opacity: 0.35,
      'background-color': '#334155',
      'border-color': '#1e293b',
      'text-opacity': 0.4
    }
  },
  {
    selector: 'edge.pruned',
    style: {
      width: 1,
      opacity: 0.1,
      'line-color': '#1e293b',
      'target-arrow-shape': 'none'
    }
  },
  {
    selector: 'node.dimmed',
    style: {
      opacity: 0.1,
      'text-opacity': 0.1
    }
  },
  {
    selector: 'edge.dimmed',
    style: {
      opacity: 0.05
    }
  },
  {
    selector: 'node.xai-highlight',
    style: {
      'border-width': 4,
      'border-color': '#d97706',
      'background-color': '#d97706',
      opacity: 1,
      'z-index': 1000
    }
  },
  {
    selector: 'edge.xai-highlight',
    style: {
      width: 4,
      'line-color': '#d97706',
      opacity: 1,
      'z-index': 1000,
      'target-arrow-color': '#d97706'
    }
  },
  {
    selector: 'node.xai-pulse-small',
    style: {
      'background-color': '#ef4444',
      'border-color': '#fca5a5',
      'border-width': 3,
      width: 18,
      height: 18,
      'z-index': 1001,
      opacity: 1
    }
  },
  {
    selector: 'node.xai-pulse-large',
    style: {
      'background-color': '#ef4444',
      'border-color': '#fee2e2',
      'border-width': 6,
      width: 26,
      height: 26,
      'z-index': 1001,
      opacity: 1
    }
  }
];

export default function GraphComponent({
  highlightPath = null,
  alternativePath = null,
  xaiEvidenceIds = [],
  xaiPulseNodeId = null,
  className = '',
  onNodeSelect = null
}) {
  const cyRef = useRef(null);
  const { graphData, isLoading, error, delayedNodeIds, impactedNodeIds, disruptionRevision, selectedNodeId } = useNetwork();
  const [pulseToggle, setPulseToggle] = React.useState(false);

  useEffect(() => {
    if (!xaiPulseNodeId) return;
    const interval = setInterval(() => {
      setPulseToggle(p => !p);
    }, 500);
    return () => clearInterval(interval);
  }, [xaiPulseNodeId]);

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
      cy.elements().removeClass('disruption-source disruption-impacted highlight detour-highlight pruned dimmed xai-highlight xai-pulse-small xai-pulse-large');
      
      // If XAI Evidence mode is active, apply dimming and specific XAI highlights
      if (xaiEvidenceIds && xaiEvidenceIds.length > 0) {
        const evidenceSet = new Set(xaiEvidenceIds.map(String));
        
        // Step 1: Dim all elements
        cy.elements().addClass('dimmed');
        
        // Step 2: Highlight involved nodes
        cy.nodes().forEach(node => {
          const nid = String(node.id());
          if (evidenceSet.has(nid)) {
            node.removeClass('dimmed');
            node.addClass('xai-highlight');
          }
        });
        
        // Step 3: Highlight involved edges
        cy.edges().forEach(edge => {
          const edgeData = edge.data();
          const edgeId = String(edge.id());
          const edgeIdRaw = edgeId.startsWith('e') ? edgeId.substring(1) : edgeId;
          const isSourceIn = evidenceSet.has(String(edgeData.source));
          const isTargetIn = evidenceSet.has(String(edgeData.target));
          
          if (evidenceSet.has(edgeId) || evidenceSet.has(edgeIdRaw) || (isSourceIn && isTargetIn)) {
            edge.removeClass('dimmed');
            edge.addClass('xai-highlight');
          }
        });
      } else {
        // Apply normal Disruption and highlights
        delayedNodeIds.forEach(id => cy.getElementById(id)?.addClass('disruption-source'));
        impactedNodeIds.forEach(id => cy.getElementById(id)?.addClass('disruption-impacted'));
        
        // Apply Feasibility Shield Pruning (desaturate edges incident on disrupted stations)
        delayedNodeIds.forEach(id => {
          cy.edges().forEach(edge => {
            const edgeData = edge.data();
            if (edgeData.source === id || edgeData.target === id) {
              edge.addClass('pruned');
            }
          });
        });
        
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
      }

      // Apply pulsing to the conflict resolution station
      if (xaiPulseNodeId) {
        const pulseNode = cy.getElementById(xaiPulseNodeId);
        if (pulseNode.length > 0) {
          pulseNode.removeClass('dimmed');
          pulseNode.addClass(pulseToggle ? 'xai-pulse-large' : 'xai-pulse-small');
        }
      }
    });
  }, [delayedNodeIds, impactedNodeIds, disruptionRevision, highlightPath, alternativePath, xaiEvidenceIds, xaiPulseNodeId, pulseToggle]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    
    if (xaiEvidenceIds && xaiEvidenceIds.length > 0) {
      const targetEles = cy.elements('.xai-highlight, .xai-pulse-small, .xai-pulse-large');
      if (targetEles.length > 0) {
        cy.animate({
          fit: { eles: targetEles, padding: 80 },
          duration: 500
        });
      }
    } else if (highlightPath && highlightPath.length > 0) {
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
  }, [xaiEvidenceIds, highlightPath]);

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