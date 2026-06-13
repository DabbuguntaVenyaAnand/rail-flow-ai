"""
rescheduling/rolling_horizon.py — Rail-Flow AI

RollingHorizonService implements Algorithm 2 from the HSR-RailFlow report:

    run_cycle(t0):
        snapshot  ← SnapshotService.build(t0)
        zone      ← ImpactZoneService.select(snapshot, predictions)
        alt_graph ← AlternativeGraph.build(zone, snapshot) + warm_start
        plans     ← policy.propose(alt_graph)
        best      ← ScenarioEvaluator picks lowest J_risk
        best      ← LocalSearch.improve(best)
        _warm_arc_selection ← best.arc_selection()
        return AuditService.persist_run(...)

Background worker: a daemon thread calls run_cycle every ROLLING_REFRESH_SECONDS.
Enable via ROLLING_HORIZON_ENABLED=true in config.

Usage::

    svc = RollingHorizonService(horizon_minutes=60)
    rr  = svc.run_cycle(datetime.now(timezone.utc))   # synchronous

    # Background mode:
    svc.start_background_worker(app)   # starts daemon thread
    # ... on shutdown:
    svc.stop()

Warm-start invariant: applying the previous cycle's arc_selection to a newly
built AlternativeGraph must not change the objective when the network state is
identical.  (It may change if new conflicts appeared or resolved.)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional


class RollingHorizonService:
    """
    Synchronous rescheduling cycle with warm-start across calls.

    :param horizon_minutes: Planning horizon forwarded to SnapshotService.
    :param commit_window_minutes: Commit-window width forwarded to
        AlternativeGraph.build().
    :param policy_name: ``"greedy"`` or ``"beam_search"`` (default).
    :param use_predictions: Whether to call HistoricalBaselinePredictor.
    :param refresh_seconds: Background worker sleep interval.
    """

    def __init__(
        self,
        horizon_minutes: int = 60,
        commit_window_minutes: int = 10,
        policy_name: str = "beam_search",
        use_predictions: bool = True,
        refresh_seconds: int = 60,
    ) -> None:
        self.horizon_minutes = horizon_minutes
        self.commit_window_minutes = commit_window_minutes
        self.policy_name = policy_name
        self.use_predictions = use_predictions
        self.refresh_seconds = refresh_seconds

        self._warm_arc_selection: Optional[dict] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ─────────────────────────────────────────────────────────────────────────
    # Core cycle (Algorithm 2)
    # ─────────────────────────────────────────────────────────────────────────

    def run_cycle(self, t0: datetime) -> Optional[object]:
        """
        Execute one rescheduling cycle synchronously.

        Must be called inside a Flask application context (db queries are used).

        :param t0: Reference time for the snapshot.
        :returns: The newly inserted :class:`~models.ReschedulingRun` ORM row,
            or None if there are no runs in the horizon.
        """
        from services.snapshot_service import SnapshotService
        from predictors.historical_baseline import HistoricalBaselinePredictor
        from predictors.residual_model import ResidualModel
        from services.impact_zone_service import ImpactZoneService
        from rescheduling.alternative_graph import AlternativeGraph
        from rescheduling.feasibility import FeasibilityShield
        from rescheduling.local_search import LocalSearch
        from policies.greedy_policy import GreedyPolicy
        from policies.beam_search_policy import BeamSearchPolicy
        from services.audit_service import AuditService, ActionRecord, ConflictRecord
        from simulator.scenario_evaluator import ScenarioEvaluator

        # ── 1. Snapshot ───────────────────────────────────────────────────────
        svc = SnapshotService(horizon_minutes=self.horizon_minutes)
        snapshot = svc.build(t0=t0, trigger_type="scheduled")
        snap_json = snapshot.snapshot_json

        all_run_ids = {r["run_id"] for r in snap_json.get("runs", [])}
        if not all_run_ids:
            return None

        # ── 2. Predictions ────────────────────────────────────────────────────
        predictor = HistoricalBaselinePredictor()
        predictions = (
            predictor.predict(snap_json, horizons=[15, 30, 60])
            if self.use_predictions
            else []
        )

        # ── 3. Impact zone ────────────────────────────────────────────────────
        impact_svc = ImpactZoneService()
        impact_run_ids = impact_svc.select(snap_json, predictions)
        if not impact_run_ids:
            impact_run_ids = all_run_ids

        predictor_name = (
            HistoricalBaselinePredictor.MODEL_VERSION
            if self.use_predictions
            else "none"
        )

        # ── 4. Alternative graph + warm start ─────────────────────────────────
        alt_graph = AlternativeGraph.build(
            snapshot_json=snap_json,
            impact_run_ids=impact_run_ids,
            t0=t0,
            commit_window_minutes=self.commit_window_minutes,
            horizon_minutes=self.horizon_minutes,
        )
        with self._lock:
            warm = self._warm_arc_selection
        if warm:
            alt_graph.apply_warm_start(warm)

        # ── 5. Policy ─────────────────────────────────────────────────────────
        shield = FeasibilityShield()
        if self.policy_name == "greedy":
            policy = GreedyPolicy(shield=shield)
        else:
            policy = BeamSearchPolicy(shield=shield)

        plans = policy.propose(alt_graph, warm_start=warm)
        if not plans:
            return None

        # ── 6. ScenarioEvaluator plan selection ───────────────────────────────
        residual_model = ResidualModel.build_from_snapshot(snap_json, predictions)
        evaluator = ScenarioEvaluator(
            residual_model=residual_model,
            snapshot_json=snap_json,
        )

        def _risk_key(plan):
            try:
                return evaluator.score(plan, horizon_minutes=30)
            except Exception:
                return plan.lower_bound

        best_plan = min(plans, key=_risk_key)

        # ── 7. Local search improvement ───────────────────────────────────────
        local_search = LocalSearch(shield=shield)
        best_plan = local_search.improve(best_plan)

        # ── 8. Store warm start for next cycle ────────────────────────────────
        with self._lock:
            self._warm_arc_selection = best_plan.alt_graph.arc_selection()

        # ── 9. Final validation ───────────────────────────────────────────────
        baseline_result = shield.validate_partial(alt_graph)
        objective_before = baseline_result.lower_bound

        final_result = shield.validate(best_plan.alt_graph)
        objective_after = (
            final_result.lower_bound if final_result.accepted else best_plan.lower_bound
        )
        status = "success" if final_result.accepted else "partial"

        # ── 10. Build action/conflict records ─────────────────────────────────
        actions: list[ActionRecord] = []
        conflicts: list[ConflictRecord] = []
        seq = 1

        for pair_id, pair in best_plan.alt_graph.alt_pairs.items():
            sel = best_plan.alt_graph.selections.get(pair_id)
            if sel is None:
                continue
            direction_str = "fwd" if sel == 0 else "bwd"
            first_run = pair.run_i if sel == 0 else pair.run_j
            second_run = pair.run_j if sel == 0 else pair.run_i
            actions.append(ActionRecord(
                action_sequence=seq,
                action_type="set_precedence",
                run_id=first_run,
                action_payload={
                    "pair_id": pair_id,
                    "direction": direction_str,
                    "first_run_id": first_run,
                    "second_run_id": second_run,
                    "edge_id": pair.edge_id,
                },
                explanation=(
                    f"Train {first_run[-8:]} ordered before {second_run[-8:]} "
                    f"on edge {pair.edge_id}"
                ),
            ))
            conflicts.append(ConflictRecord(
                first_run_id=pair.run_i,
                second_run_id=pair.run_j,
                conflict_type="ordering",
                connection_id=pair.edge_id,
                resolved=True,
                resolution_action_sequence=seq,
            ))
            seq += 1

        for (run_id, stop_seq), hold_s in best_plan.holds.items():
            if hold_s <= 0:
                continue
            actions.append(ActionRecord(
                action_sequence=seq,
                action_type="hold",
                run_id=run_id,
                action_payload={"stop_sequence": stop_seq, "hold_seconds": hold_s},
                explanation=f"Hold {hold_s:.0f}s at stop {stop_seq}",
            ))
            seq += 1

        # ── 11. Persist audit ─────────────────────────────────────────────────
        audit = AuditService()
        rr = audit.persist_run(
            snapshot_id=snapshot.snapshot_id,
            policy_name=best_plan.policy_name,
            predictor_name=predictor_name,
            horizon_minutes=self.horizon_minutes,
            commit_window_minutes=self.commit_window_minutes,
            objective_before=objective_before,
            objective_after=objective_after,
            actions=actions,
            conflicts=conflicts,
            status=status,
        )
        return rr

    # ─────────────────────────────────────────────────────────────────────────
    # Background worker management
    # ─────────────────────────────────────────────────────────────────────────

    def start_background_worker(self, app) -> None:
        """
        Start the rolling-horizon daemon thread.

        Safe to call once per app instance.  The thread stops when
        :meth:`stop` is called or the process exits (daemon=True).

        :param app: Flask application instance.
        """
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()

        def _worker():
            import time
            while not self._stop_event.is_set():
                try:
                    with app.app_context():
                        self.run_cycle(datetime.now(timezone.utc))
                except Exception:
                    pass   # individual cycle failures don't stop the worker
                self._stop_event.wait(timeout=self.refresh_seconds)

        self._thread = threading.Thread(
            target=_worker,
            daemon=True,
            name="rolling-horizon-worker",
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the background worker to stop after its current cycle."""
        self._stop_event.set()
