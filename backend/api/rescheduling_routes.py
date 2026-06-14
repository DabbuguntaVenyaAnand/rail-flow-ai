"""
api/rescheduling_routes.py — Rail-Flow AI

Blueprint for the rescheduling v1 API:

  POST /api/v1/rescheduling/compute
       Trigger a rescheduling cycle and return the best plan found.

  GET  /api/v1/rescheduling/latest
       Return the most recent ReschedulingRun with its actions.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

rescheduling_bp = Blueprint("rescheduling", __name__, url_prefix="/api/v1/rescheduling")


@rescheduling_bp.route("/compute", methods=["POST"])
def compute():
    """
    POST /api/v1/rescheduling/compute

    Body (all fields optional):
      trigger_type      str   "manual" (default)
      trigger_reference str   optional reference string
      t0                str   ISO-8601 UTC datetime (default: now)
      policy            str   "greedy" | "beam_search" (default: "beam_search")
      use_predictions   bool  ignored until Phase 4; accepted for API compat
      horizon_minutes   int   (default: 60)
      commit_window_minutes int (default: 10)

    Returns 200:
      {rescheduling_run_id, status, objective_before, objective_after,
       compute_time_ms, actions, conflicts_detected, conflicts_resolved}
    """
    body = request.get_json(silent=True) or {}

    trigger_type = body.get("trigger_type", "manual")
    trigger_reference = body.get("trigger_reference")
    horizon_minutes = int(body.get("horizon_minutes", 60))
    commit_window_minutes = int(body.get("commit_window_minutes", 10))
    policy_name = body.get("policy", "beam_search")
    use_predictions = bool(body.get("use_predictions", True))

    # Parse t0
    t0_str = body.get("t0")
    if t0_str:
        try:
            t0 = datetime.fromisoformat(t0_str)
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({"error": f"Invalid t0 format: {t0_str!r}"}), 400
    else:
        t0 = datetime.now(timezone.utc)

    start_ns = time.monotonic_ns()

    try:
        result = _run_pipeline(
            t0=t0,
            trigger_type=trigger_type,
            trigger_reference=trigger_reference,
            horizon_minutes=horizon_minutes,
            commit_window_minutes=commit_window_minutes,
            policy_name=policy_name,
            use_predictions=use_predictions,
        )
    except Exception as exc:
        return jsonify({"error": str(exc), "status": "error"}), 500

    compute_ms = (time.monotonic_ns() - start_ns) // 1_000_000
    result["compute_time_ms"] = compute_ms
    return jsonify(result), 200


@rescheduling_bp.route("/latest", methods=["GET"])
def latest():
    """
    GET /api/v1/rescheduling/latest

    Return the most recent ReschedulingRun with its actions array.
    Returns 404 if no run has been executed yet.
    """
    from models import ReschedulingRun, ReschedulingAction

    run = (
        ReschedulingRun.query
        .order_by(ReschedulingRun.created_at.desc())
        .first()
    )
    if run is None:
        return jsonify({"error": "No rescheduling runs found"}), 404

    actions = (
        ReschedulingAction.query
        .filter_by(rescheduling_run_id=run.rescheduling_run_id)
        .order_by(ReschedulingAction.action_sequence)
        .all()
    )

    from models import db, DelayPrediction, TimetableRun
    predictions = (
        DelayPrediction.query
        .filter_by(snapshot_id=run.snapshot_id)
        .order_by(DelayPrediction.horizon_minutes, DelayPrediction.run_id)
        .all()
    )
    
    predictions_data = []
    for p in predictions:
        run_obj = db.session.get(TimetableRun, p.run_id)
        train_num = run_obj.train_number if run_obj else "Unknown"
        predictions_data.append({
            "run_id": p.run_id,
            "train_number": train_num,
            "horizon_minutes": p.horizon_minutes,
            "p50_delay_seconds": p.p50_delay_seconds,
            "p90_delay_seconds": p.p90_delay_seconds,
            "model_version": p.model_version
        })

    from flask import current_app
    actions_data = []
    for a in actions:
        action_dict = {
            "action_sequence": a.action_sequence,
            "action_type": a.action_type,
            "run_id": a.run_id,
            "station_code": a.station_code,
            "connection_id": a.connection_id,
            "payload": a.action_payload,
            "explanation": a.explanation,
            "constraint_violated": a.constraint_violated,
        }
        why_obj = {
            "constraint_violated": "UNKNOWN",
            "explanation": a.explanation,
            "evidence_ids": []
        }
        if hasattr(current_app, 'map_constraint_to_xai'):
            try:
                why_obj = current_app.map_constraint_to_xai(action_dict)
            except Exception as e:
                current_app.logger.error(f"Error mapping constraint to XAI: {e}")
        actions_data.append({
            "sequence": a.action_sequence,
            "type": a.action_type,
            "run_id": a.run_id,
            "station_code": a.station_code,
            "connection_id": a.connection_id,
            "payload": a.action_payload,
            "explanation": a.explanation,
            "why": why_obj
        })

    return jsonify({
        "rescheduling_run_id": run.rescheduling_run_id,
        "status": run.status,
        "policy_name": run.policy_name,
        "objective_before": run.objective_before,
        "objective_after": run.objective_after,
        "compute_time_ms": run.compute_time_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "actions": actions_data,
        "predictions": predictions_data,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Core pipeline (decoupled from HTTP for testability)
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(
    t0: datetime,
    trigger_type: str = "manual",
    trigger_reference=None,
    horizon_minutes: int = 60,
    commit_window_minutes: int = 10,
    policy_name: str = "beam_search",
    use_predictions: bool = True,
) -> dict:
    """
    Execute one rescheduling cycle and persist the result.

    Returns a dict suitable for JSON serialisation.
    """
    from services.snapshot_service import SnapshotService
    from rescheduling.alternative_graph import AlternativeGraph
    from rescheduling.feasibility import FeasibilityShield
    from rescheduling.local_search import LocalSearch
    from policies.greedy_policy import GreedyPolicy
    from policies.beam_search_policy import BeamSearchPolicy
    from services.audit_service import AuditService, ActionRecord, ConflictRecord
    from predictors.historical_baseline import HistoricalBaselinePredictor
    from services.impact_zone_service import ImpactZoneService

    # 1. Build snapshot
    svc = SnapshotService(horizon_minutes=horizon_minutes)
    snapshot = svc.build(t0=t0, trigger_type=trigger_type,
                         trigger_reference=trigger_reference)
    snapshot_json = snapshot.snapshot_json

    all_run_ids = {r["run_id"] for r in snapshot_json.get("runs", [])}
    if not all_run_ids:
        return _empty_result(snapshot.snapshot_id, "no_runs_in_horizon")

    # 2. Delay predictions
    from predictors.sage_het import SageHetPredictor
    predictor = SageHetPredictor()
    predictions = predictor.predict(snapshot_json, horizons=[15, 30, 60]) if use_predictions else []

    from models import db, DelayPrediction
    for p in predictions:
        dp = DelayPrediction(
            snapshot_id=snapshot.snapshot_id,
            run_id=p.run_id,
            horizon_minutes=p.horizon_minutes,
            p50_delay_seconds=p.p50_delay_seconds,
            p90_delay_seconds=p.p90_delay_seconds,
            model_version=p.model_version
        )
        db.session.add(dp)
    db.session.flush()


    # 3. Impact zone (falls back to all runs if zone is empty)
    impact_svc = ImpactZoneService()
    impact_run_ids = impact_svc.select(snapshot_json, predictions)
    if not impact_run_ids:
        impact_run_ids = all_run_ids

    predictor_name = predictor.MODEL_VERSION if use_predictions else "none"

    # 4. Build alternative graph
    alt_graph = AlternativeGraph.build(
        snapshot_json=snapshot_json,
        impact_run_ids=impact_run_ids,
        t0=t0,
        commit_window_minutes=commit_window_minutes,
        horizon_minutes=horizon_minutes,
    )

    # 5. Score baseline (no arc selections yet)
    shield = FeasibilityShield()
    baseline_result = shield.validate_partial(alt_graph)
    objective_before = baseline_result.lower_bound

    # 5. Run policy
    if policy_name == "greedy":
        policy = GreedyPolicy(shield=shield)
    else:
        policy = BeamSearchPolicy(shield=shield)

    plans = policy.propose(alt_graph)
    if not plans:
        return _empty_result(snapshot.snapshot_id, "no_plans_found")

    best_plan = min(plans, key=lambda p: p.lower_bound)

    # 6. Local search improvement
    local_search = LocalSearch(shield=shield)
    best_plan = local_search.improve(best_plan)

    # 7. Final validation
    final_result = shield.validate(best_plan.alt_graph)
    objective_after = final_result.lower_bound if final_result.accepted else best_plan.lower_bound
    status = "success" if final_result.accepted else "partial"

    # 8. Convert arc selections to ActionRecords
    # Map (run_id, stop_sequence) -> station_code
    run_stop_to_station = {}
    for r in snapshot_json.get("runs", []):
        rid = r.get("run_id")
        for ev in r.get("events", []):
            run_stop_to_station[(rid, ev.get("stop_sequence"))] = ev.get("station_code")

    # Query active disrupted stations
    from models import DisruptionEvent
    active_disrupted_stations = {d.station_code for d in DisruptionEvent.query.filter_by(is_active=True).all()}

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
            connection_id=pair.edge_id,
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
            constraint_violated="PRECEDENCE_CONFLICT",
        ))
        seq += 1

        # Record as a resolved conflict
        conflicts.append(ConflictRecord(
            first_run_id=pair.run_i,
            second_run_id=pair.run_j,
            conflict_type="ordering",
            connection_id=pair.edge_id,
            resolved=True,
            resolution_action_sequence=seq - 1,
        ))

    # Hold actions
    for (run_id, stop_seq), hold_s in best_plan.holds.items():
        if hold_s <= 0:
            continue
        st_code = run_stop_to_station.get((run_id, stop_seq))
        constraint = "BLOCKAGE" if st_code in active_disrupted_stations else "HEADWAY_GAP"
        actions.append(ActionRecord(
            action_sequence=seq,
            action_type="hold",
            run_id=run_id,
            station_code=st_code,
            action_payload={"stop_sequence": stop_seq, "hold_seconds": hold_s},
            explanation=f"Hold {hold_s:.0f}s at stop {stop_seq}",
            constraint_violated=constraint,
        ))
        seq += 1


    # 9. Persist audit
    audit = AuditService()
    rr = audit.persist_run(
        snapshot_id=snapshot.snapshot_id,
        policy_name=best_plan.policy_name,
        predictor_name=predictor_name,
        horizon_minutes=horizon_minutes,
        commit_window_minutes=commit_window_minutes,
        objective_before=objective_before,
        objective_after=objective_after,
        actions=actions,
        conflicts=conflicts,
        status=status,
    )

    from flask import current_app
    actions_data = []
    for a in actions:
        action_dict = {
            "action_sequence": a.action_sequence,
            "action_type": a.action_type,
            "run_id": a.run_id,
            "station_code": a.station_code,
            "connection_id": a.connection_id,
            "payload": a.action_payload,
            "explanation": a.explanation,
            "constraint_violated": a.constraint_violated,
        }
        why_obj = {
            "constraint_violated": "UNKNOWN",
            "explanation": a.explanation,
            "evidence_ids": []
        }
        if hasattr(current_app, 'map_constraint_to_xai'):
            try:
                why_obj = current_app.map_constraint_to_xai(action_dict)
            except Exception as e:
                current_app.logger.error(f"Error mapping constraint to XAI: {e}")
        actions_data.append({
            "sequence": a.action_sequence,
            "type": a.action_type,
            "run_id": a.run_id,
            "station_code": a.station_code,
            "connection_id": a.connection_id,
            "payload": a.action_payload,
            "explanation": a.explanation,
            "why": why_obj
        })

    return {
        "rescheduling_run_id": rr.rescheduling_run_id,
        "status": status,
        "objective_before": objective_before,
        "objective_after": objective_after,
        "actions": actions_data,
        "conflicts_detected": len(conflicts),
        "conflicts_resolved": sum(1 for c in conflicts if c.resolved),
    }


def _empty_result(snapshot_id: str, reason: str) -> dict:
    return {
        "rescheduling_run_id": None,
        "status": reason,
        "objective_before": 0.0,
        "objective_after": 0.0,
        "actions": [],
        "conflicts_detected": 0,
        "conflicts_resolved": 0,
    }
