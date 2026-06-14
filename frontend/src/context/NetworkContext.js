import React, {
  createContext,
  useState,
  useEffect,
  useContext,
  useCallback,
  useMemo,
  useRef,
} from 'react';
import {
  buildAdjacency,
  propagateFromMultiple,
} from '../utils/ripplePropagation';
import { computeNetworkHealth, predictRippleOutcome } from '../utils/disruptionPredictor';

const NetworkContext = createContext(null);

const API = '/api';

export const NetworkProvider = ({ children }) => {
  const [graphData, setGraphData] = useState(null);
  const [trainStatus, setTrainStatus] = useState([]);
  const [networkHealth, setNetworkHealth] = useState('healthy');
  const [isLoading, setIsLoading] = useState(true);
  const [selectedNodeId, setSelectedNodeId] = useState(null);

  // Disruption engine state
  const [delayedNodes, setDelayedNodes] = useState(() => new Set());
  const [impactedNodes, setImpactedNodes] = useState(() => new Set());
  const [impactHopMap, setImpactHopMap] = useState({});
  const [propagationDepth, setPropagationDepth] = useState(3);
  const [disruptionRevision, setDisruptionRevision] = useState(0);

  const [stationReport, setStationReport] = useState(null);
  const [ripplePrediction, setRipplePrediction] = useState(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [error, setError] = useState(null);
  const [latestRescheduling, setLatestRescheduling] = useState(null);

  const adjacencyRef = useRef(new Map());

  const bumpDisruption = useCallback(() => {
    setDisruptionRevision(r => r + 1);
  }, []);

  const fetchGraph = useCallback(async () => {
    setError(null);
    const response = await fetch(`${API}/graph`);
    if (!response.ok) throw new Error('Failed to fetch graph');
    const data = await response.json();
    setGraphData(data);
    adjacencyRef.current = buildAdjacency(data.elements?.edges ?? []);
    const health = computeNetworkHealth(data.elements?.nodes ?? []);
    setNetworkHealth(health);
    return data;
  }, []);

  const fetchTrains = useCallback(async () => {
    try {
      const response = await fetch(`${API}/trains`);
      if (!response.ok) return;
      const data = await response.json();
      setTrainStatus(data.entity ?? []);
    } catch (err) {
      console.error('Train status fetch failed:', err);
    }
  }, []);

  const fetchLatestRescheduling = useCallback(async () => {
    try {
      const res = await fetch(`${API}/v1/rescheduling/latest`);
      if (res.ok) {
        const data = await res.json();
        setLatestRescheduling(data);
        return data;
      }
    } catch (err) {
      console.error('Failed to fetch latest rescheduling run:', err);
    }
    return null;
  }, []);

  useEffect(() => {
    const init = async () => {
      try {
        await fetchGraph();
        await fetchTrains();
        await fetchLatestRescheduling();
      } catch (err) {
        console.error('Failed to fetch network data:', err);
        setError(err.message || 'Failed to connect to backend server');
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, [fetchGraph, fetchTrains, fetchLatestRescheduling]);

  // Real-time train status polling
  useEffect(() => {
    const interval = setInterval(fetchTrains, 15000);
    return () => clearInterval(interval);
  }, [fetchTrains]);

  /** Recompute impacted nodes whenever delayed set or depth changes. */
  const recomputeRipple = useCallback((delayedSet, depth) => {
    const adj = adjacencyRef.current;
    if (!adj.size || delayedSet.size === 0) {
      setImpactedNodes(new Set());
      setImpactHopMap({});
      return;
    }
    const { impacted, hopMap } = propagateFromMultiple(adj, delayedSet, depth);
    setImpactedNodes(impacted);
    setImpactHopMap(Object.fromEntries(hopMap));
  }, []);

  useEffect(() => {
    recomputeRipple(delayedNodes, propagationDepth);
  }, [delayedNodes, propagationDepth, disruptionRevision, recomputeRipple]);

  /**
   * Inject a delay at nodeId — marks node delayed and triggers ripple propagation.
   */
  const injectDelay = useCallback(async (nodeId, depth = propagationDepth) => {
    const id = nodeId?.trim?.()?.toUpperCase?.() ?? nodeId;
    if (!id) return { ok: false, error: 'Node ID required' };

    try {
      const res = await fetch(`${API}/station/${id}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'delayed' }),
      });
      const body = await res.json();
      if (!res.ok) return { ok: false, error: body.error ?? 'Injection failed' };

      setDelayedNodes(prev => {
        const next = new Set(prev);
        next.add(body.updated?.id ?? id);
        return next;
      });

      // Refresh graph statuses from server
      await fetchGraph();
      await fetchLatestRescheduling();
      bumpDisruption();

      return { ok: true, station: body.updated };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  }, [propagationDepth, fetchGraph, bumpDisruption, fetchLatestRescheduling]);

  const clearDisruptions = useCallback(async () => {
    const ids = [...delayedNodes];
    for (const id of ids) {
      await fetch(`${API}/station/${id}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'clear' }),
      });
    }
    setDelayedNodes(new Set());
    setImpactedNodes(new Set());
    setImpactHopMap({});
    setRipplePrediction(null);
    await fetchGraph();
    await fetchLatestRescheduling();
    bumpDisruption();
  }, [delayedNodes, fetchGraph, bumpDisruption, fetchLatestRescheduling]);

  /** Station lookup with report generation. */
  const searchStation = useCallback(async (code) => {
    const q = code?.trim();
    if (!q) return null;
    setSearchLoading(true);
    try {
      const [lookupRes, historyRes, predictRes] = await Promise.all([
        fetch(`${API}/station-lookup/${encodeURIComponent(q)}`),
        fetch(`${API}/analytics/delay-history/${encodeURIComponent(q)}`),
        fetch(`${API}/predict/ripple/${encodeURIComponent(q)}?depth=${propagationDepth}`),
      ]);

      const lookup = await lookupRes.json();
      if (!lookupRes.ok) {
        setStationReport({ error: lookup.error });
        return null;
      }

      const history = historyRes.ok ? await historyRes.json() : null;
      const serverPredict = predictRes.ok ? await predictRes.json() : null;

      const clientPredict = predictRippleOutcome(
        lookup.id,
        graphData,
        history,
      );

      const report = {
        station: lookup,
        history,
        prediction: serverPredict ?? clientPredict,
        clientPrediction: clientPredict,
        searchedAt: new Date().toISOString(),
      };
      setStationReport(report);
      setSelectedNodeId(lookup.id);
      return report;
    } catch (err) {
      setStationReport({ error: 'Network error during lookup.' });
      return null;
    } finally {
      setSearchLoading(false);
    }
  }, [graphData, propagationDepth]);

  const fetchRipplePrediction = useCallback(async (nodeId) => {
    if (!nodeId) return null;
    try {
      const res = await fetch(
        `${API}/predict/ripple/${encodeURIComponent(nodeId)}?depth=${propagationDepth}`
      );
      const data = res.ok ? await res.json() : null;
      if (data) {
        setRipplePrediction(data);
        return data;
      }
      const fallback = predictRippleOutcome(nodeId, graphData);
      setRipplePrediction(fallback);
      return fallback;
    } catch {
      const fallback = predictRippleOutcome(nodeId, graphData);
      setRipplePrediction(fallback);
      return fallback;
    }
  }, [graphData, propagationDepth]);

  const delayedNodeIds = useMemo(() => [...delayedNodes], [delayedNodes, disruptionRevision]);
  const impactedNodeIds = useMemo(() => [...impactedNodes], [impactedNodes, disruptionRevision]);

  const value = {
    graphData,
    trainStatus,
    networkHealth,
    isLoading,
    error,
    selectedNodeId,
    setSelectedNodeId,
    fetchGraph,
    fetchTrains,
    // Disruption engine
    delayedNodes,
    delayedNodeIds,
    impactedNodes,
    impactedNodeIds,
    impactHopMap,
    propagationDepth,
    setPropagationDepth,
    injectDelay,
    clearDisruptions,
    disruptionRevision,
    // Search & prediction
    stationReport,
    searchStation,
    searchLoading,
    ripplePrediction,
    fetchRipplePrediction,
    latestRescheduling,
    fetchLatestRescheduling,
  };

  return (
    <NetworkContext.Provider value={value}>
      {children}
    </NetworkContext.Provider>
  );
};

export const useNetwork = () => {
  const context = useContext(NetworkContext);
  if (!context) {
    throw new Error('useNetwork must be used within a NetworkProvider');
  }
  return context;
};
