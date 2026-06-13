/**
 * Downstream ripple propagation — BFS over directed edges (source → target).
 * Used by the Disruption Management Engine when a node is marked delayed.
 */

/** Build adjacency list from cytoscape-style edge elements. */
export function buildAdjacency(edges = []) {
  const adj = new Map();
  for (const edge of edges) {
    const { source, target } = edge.data;
    if (!adj.has(source)) adj.set(source, []);
    adj.get(source).push(target);
    if (!adj.has(target)) adj.set(target, []);
    adj.get(target).push(source);
  }
  return adj;
}

/**
 * Traverse downstream from startNodeId up to maxDepth hops.
 * Returns { impacted: Set<string>, hopMap: Map<string, number> }
 */
export function propagateRipple(adjacency, startNodeId, maxDepth = 3) {
  const impacted = new Set();
  const hopMap = new Map();
  const queue = [{ id: startNodeId, depth: 0 }];
  const visited = new Set([startNodeId]);

  while (queue.length > 0) {
    const { id, depth } = queue.shift();
    if (depth >= maxDepth) continue;

    for (const neighbor of adjacency.get(id) || []) {
      if (visited.has(neighbor)) continue;
      visited.add(neighbor);
      impacted.add(neighbor);
      hopMap.set(neighbor, depth + 1);
      queue.push({ id: neighbor, depth: depth + 1 });
    }
  }

  return { impacted, hopMap };
}

/** Multi-source ripple from several delayed nodes. */
export function propagateFromMultiple(adjacency, sourceIds, maxDepth = 3) {
  const allImpacted = new Set();
  const allHopMap = new Map();

  for (const sourceId of sourceIds) {
    const { impacted, hopMap } = propagateRipple(adjacency, sourceId, maxDepth);
    for (const id of impacted) {
      allImpacted.add(id);
      const existing = allHopMap.get(id);
      const hop = hopMap.get(id);
      if (existing === undefined || hop < existing) {
        allHopMap.set(id, hop);
      }
    }
  }

  // Remove sources from impacted set
  for (const id of sourceIds) allImpacted.delete(id);

  return { impacted: allImpacted, hopMap: allHopMap };
}
