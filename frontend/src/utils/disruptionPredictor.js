/**
 * Client-side heuristics for ripple prediction based on graph topology
 * and optional historical delay data from the API.
 */

const STATUS_WEIGHT = { clear: 0, congestion: 0.35, delayed: 0.75 };

/**
 * Estimate whether a disruption at nodeId will ripple or self-resolve.
 * @returns {{ rippleProbability: number, willRipple: boolean, confidence: string, factors: string[] }}
 */
export function predictRippleOutcome(nodeId, graphData, historical = null) {
  const nodes = graphData?.elements?.nodes ?? [];
  const edges = graphData?.elements?.edges ?? [];
  const node = nodes.find(n => n.data.id === nodeId);
  const factors = [];

  if (!node) {
    return { rippleProbability: 0, willRipple: false, confidence: 'low', factors: ['Node not found'] };
  }

  const outDegree = edges.filter(e => e.data.source === nodeId).length;
  const inDegree = edges.filter(e => e.data.target === nodeId).length;
  const connectivity = outDegree + inDegree;

  let score = 0.2;

  if (connectivity >= 4) {
    score += 0.35;
    factors.push(`High connectivity (${connectivity} edges)`);
  } else if (connectivity >= 2) {
    score += 0.2;
    factors.push(`Moderate connectivity (${connectivity} edges)`);
  } else {
    score += 0.05;
    factors.push(`Low connectivity (${connectivity} edges) — likely isolated`);
  }

  if (node.data.layer === 'hub') {
    score += 0.25;
    factors.push('Hub station — delays tend to cascade');
  }

  if (node.data.priority <= 2) {
    score += 0.15;
    factors.push('Priority corridor — high traffic volume');
  }

  // Downstream neighbor stress
  const downstreamIds = edges
    .filter(e => e.data.source === nodeId || e.data.target === nodeId)
    .map(e => e.data.source === nodeId ? e.data.target : e.data.source);
  let stressed = 0;
  for (const id of downstreamIds) {
    const n = nodes.find(x => x.data.id === id);
    if (n && n.data.status !== 'clear') stressed++;
  }
  if (stressed > 0) {
    score += Math.min(0.2, stressed * 0.08);
    factors.push(`${stressed} downstream station(s) already stressed`);
  }

  if (historical) {
    const histBoost = (historical.incidents_30d ?? 0) > 8 ? 0.15 : 0.05;
    score += histBoost;
    if (historical.avg_delay_min > 20) {
      score += 0.1;
      factors.push(`Historical avg delay ${historical.avg_delay_min} min`);
    }
    if (historical.ripple_probability) {
      score = score * 0.6 + historical.ripple_probability * 0.4;
      factors.push('Blended with 30-day historical pattern');
    }
  }

  score = Math.min(0.98, Math.max(0.02, score));
  const willRipple = score >= 0.5;
  const confidence = score > 0.75 || score < 0.25 ? 'high' : 'medium';

  return {
    rippleProbability: Math.round(score * 100),
    willRipple,
    confidence,
    factors,
    resolutionEstimate: willRipple ? 'Expect cascade — dispatch reroutes' : 'Likely contained within 1–2 hops',
  };
}

/** Aggregate network health from node statuses. */
export function computeNetworkHealth(nodes = []) {
  if (!nodes.length) return 'unknown';
  const delayed = nodes.filter(n => n.data.status === 'delayed').length;
  const congestion = nodes.filter(n => n.data.status === 'congestion').length;
  const ratio = (delayed * 2 + congestion) / nodes.length;
  if (ratio > 0.15) return 'critical';
  if (ratio > 0.05) return 'degraded';
  return 'healthy';
}

export { STATUS_WEIGHT };
