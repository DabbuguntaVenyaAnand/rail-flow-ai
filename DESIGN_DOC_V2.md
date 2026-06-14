# Rail-Flow AI — Design Document v2

> Revision driven by the technical review PDF (`changes.pdf`), June 2026.
> Previous version: `IMPLEMENTATION_STATUS.md` (all 7 phases complete, 157 tests).

---

## 1. Overview

Rail-Flow AI is a production-grade train-rescheduling engine for High-Speed Rail networks. It models the operational state as a digital twin, detects headway conflicts, and computes optimal hold/precedence actions using an alternative-graph framework with feasibility guarantees.

**What changed in v2:**
- 6 algorithm fixes from the PDF technical review (P0–P3 findings)
- New "Reschedule Schedule" page in the React/Cytoscape frontend
- ML dependencies installed; model artifacts generated (sage_het_v1.pt, dqn_v1.pt)
- 5 new scenario integration tests (PDF §15.3)
- SCENARIO_EVALUATION_ENABLED feature flag added

---

## 2. PDF Fix Summary

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | P0 | `train_schedule` per-stop data missing | **Already Correct** — `timetable_events` table (Phase 1) |
| 2 | P0 | `corridor_edges` missing capacity/direction columns | **Already Correct** — added in Phase 1 |
| 3 | P1 | `LB(z')` undefined | **Already Correct** — implemented as longest-path score in `FeasibilityShield.validate_partial()` |
| 4 | P1 | `MaterializeOccupancies` undefined | **Already Correct** — `OccupancyModel.build_from_events()` in `simulator/occupancy.py` |
| 5 | P1 | Warm start reuses arc weights (cascade errors) | **Already Correct** — `arc_selection()` returns `dict[str, int]` (directions only); weights recomputed from fresh snapshot in each `AlternativeGraph.build()` |
| 6 | P1 | Arc types wrong for platform conflicts | **Fixed** — `ArcType.SEGMENT` / `ArcType.PLATFORM` enum added to `alternative_graph.py` |
| 7 | P1 | Bidirectional single-track uses headway for opposing trains | **Fixed** — opposing trains get `arc_weight = h_min + base_run_seconds` (mutual exclusion) |
| 8 | P2 | Greedy tie-break preserves disrupted order | **Fixed** — hold-time tie-breaking via `_hold_added()` in `greedy_policy.py` |
| 9 | P2 | Greedy uses earliest-scheduled instead of impact score | **Fixed** — replaced with `_highest_impact_pair()` |
| 10 | P2 | Beam width B=8 too narrow | **Fixed** — B=20, E_max=200, time limit 800 ms |
| 11 | P2 | Local search move 4 (RestoreOriginalOrder) wastes budget | **Fixed** — removed from `LocalSearch.improve()` |
| 12 | P3 | ScenarioEvaluator requires historical data | **Fixed** — gated behind `SCENARIO_EVALUATION_ENABLED=false` flag |

---

## 3. Algorithm Details

### 3.1 Alternative Graph (`rescheduling/alternative_graph.py`)

Encodes all train-ordering decisions as selectable arc pairs.

**Arc types:**
```python
class ArcType(Enum):
    SEGMENT = auto()   # running-segment constraint: entry→exit + headway
    PLATFORM = auto()  # platform dwell conflict: arrival→departure
```

**Bidirectional single-track fix:**
When two trains travel in opposite directions on a shared segment (detected by comparing `dep_stop` vs `arr_stop` sequence order), the arc weight is:
```
arc_weight = h_min + base_run_seconds   (mutual exclusion)
```
For same-direction trains:
```
arc_weight = h_min   (minimum headway only)
```

**Warm-start invariant:**
`arc_selection()` returns `dict[pair_id, Optional[int]]` — direction integers only, no arc weights. `apply_warm_start()` seeds these into a freshly built `AlternativeGraph` whose arc weights are computed from the new snapshot. This prevents warm-start cascade errors when telemetry changes between cycles.

### 3.2 Greedy Policy (`policies/greedy_policy.py`)

**Pair ordering (v2):** `_highest_impact_pair()` selects the conflict whose resolution will affect the most downstream trains (counted by DEP times after both trains in the pair).

**Tie-breaking (v2):** When both directions have `|lb_0 - lb_1| < 1.0` seconds, `_hold_added()` is called for each direction; the direction with less total added hold wins.

### 3.3 Beam Search (`policies/beam_search_policy.py`)

| Parameter | v1 | v2 |
|---|---|---|
| Beam width B | 8 | 20 |
| Max expansions E_max | 500 | 200 |
| Time limit | 1000 ms | 800 ms |

### 3.4 Local Search (`rescheduling/local_search.py`)

Three move types (v2 removes RestoreOriginalOrder):
1. **FlipPrecedence** — swap arc direction for one pair
2. **RemoveHold** — zero a release-arc extension
3. **ShortenHold** — reduce hold by {30, 60, 120, 300} seconds

### 3.5 Scenario Evaluator (`simulator/scenario_evaluator.py`)

The K=16 scenario CVaR evaluation is gated behind `SCENARIO_EVALUATION_ENABLED`. When disabled (default), `score()` returns `J_det` directly. Enable only when a populated `ResidualModel` with historical delay residuals exists:

```bash
export SCENARIO_EVALUATION_ENABLED=true
```

---

## 4. Database Schema

**Key tables (Phase 1 additions to the 500-station base schema):**

| Table | Purpose |
|---|---|
| `timetable_runs` | One service-date instance per train number |
| `timetable_events` | Per-stop scheduled/actual arrival/departure times |
| `live_train_states` | Latest observed position + delay per run |
| `disruption_events` | Active disruptions (delay, segment block) |
| `operational_snapshots` | Point-in-time digital twin snapshots |
| `rescheduling_runs` | Audit log for each optimization run |
| `rescheduling_actions` | Individual hold/precedence actions |

`CorridorEdge` extended with: `base_run_seconds`, `min_headway_seconds` (default 300 s), `capacity` (default 1), `direction_group`, `is_enabled`.

---

## 5. Frontend Architecture

**5 pages via React Router:**

| Route | Page | Purpose |
|---|---|---|
| `/` | Dashboard | Cytoscape network twin, disruption injection |
| `/ops` | Operations | Live train telemetry table + network overlay |
| `/pathfinder` | Pathfinder | A* routing |
| `/analytics` | Analytics | Delay history, ripple prediction |
| `/reschedule` | Rescheduling (new) | Rescheduling engine output |

**Reschedule page (`frontend/src/pages/Rescheduling.js`):**
- On mount: `GET /api/v1/rescheduling/latest` (polls every 30 s)
- "Trigger Reschedule" button: `POST /api/v1/rescheduling/compute`
- Displays: status badge, objective before/after with Δ%, compute time, conflicts detected/resolved, actions table (Train | Action Type | Station | Hold (s) | Notes)
- Matches the existing dark theme (`#1a1a2e` / `#00d4ff`)

---

## 6. ML Models

### 6.1 SageHet Predictor (`predictors/sage_het.py`)

GNN-based delay predictor. Architecture: 2-layer HeteroSAGE, hidden_dim=64, dual quantile heads (p50/p90).

**Artifact:** `backend/models/sage_het_v1.pt` (56 KB — initial weights; full training requires historical delay data in `timetable_events`).

**Fallback chain:** `SageHetPredictor` → `HistoricalBaselinePredictor` (if no artifact or `PREDICTOR_BACKEND != "sage_het"`).

**To train with real data:**
```bash
cd backend
python3 -m training.train_sage_het --epochs 100 --output models/sage_het_v1.pt
```

### 6.2 DQN Policy (`policies/dqn_policy.py`)

Double-DQN with dueling network. Trained on simulated disruption scenarios via `ReschedulingEnv` (Gymnasium).

**Artifact:** `backend/models/dqn_v1.pt` (120 KB — initial weights).

**Fallback chain:** `MaskedDqnPolicy` → `BeamSearchPolicy` (if no artifact or `POLICY_BACKEND != "dqn"`).

**To train with real data:**
```bash
cd backend
python3 -m training.train_dqn --episodes 2000 --seed 42 --output models/dqn_v1.pt
```
Requires a seeded PostgreSQL database (`DEMO_MODE=true flask seed-demo`).

---

## 7. Running the System

### Prerequisites

```bash
# Python dependencies
pip install -r backend/requirements.txt
pip install "torch>=2.3.0" "torch-geometric>=2.5.0" "gymnasium>=0.29.0"

# Node dependencies
cd frontend && npm install
```

### Quick start (SQLite demo mode)

```bash
cd backend

# 1. Seed demo data
export DEMO_MODE=true
flask seed-demo

# 2. Start backend
flask run
# → http://localhost:5000

# 3. Start frontend (separate terminal)
cd frontend && npm start
# → http://localhost:3000
```

### Trigger a reschedule

```bash
# Via API
curl -X POST http://localhost:5000/api/v1/rescheduling/compute \
  -H 'Content-Type: application/json' \
  -d '{"policy":"beam_search","horizon_minutes":600}'

# Check result
curl http://localhost:5000/api/v1/rescheduling/latest
```

Or navigate to **http://localhost:3000/reschedule** and click **Trigger Reschedule**.

### Production (PostgreSQL)

```bash
export DATABASE_URL="postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db"
export DEMO_MODE=false
export ROLLING_HORIZON_ENABLED=true  # start background worker
export POLICY_BACKEND=beam_search    # or "dqn" after training
flask db upgrade
flask run
```

---

## 8. Test Coverage

```
backend/tests/
  test_legacy_endpoints.py        — 10 original API endpoints
  test_no_random_in_production.py — determinism regression
  test_snapshot_service.py        — SnapshotService + OccupancyModel
  test_objective_function.py      — ObjectiveFunction weights
  test_alternative_graph.py       — AltPair, ArcType, bidirectional weights
  test_feasibility_shield.py      — 6-stage validation
  test_greedy_policy.py           — impact-score ordering, hold tie-break
  test_beam_search_policy.py      — B=20, beam pruning
  test_delay_predictor.py         — DelayEstimate interface
  test_impact_zone.py             — ImpactZoneService caps
  test_hetero_graph_builder.py    — PyG node/edge counts (requires torch_geometric)
  test_sage_het_predictor.py      — GNN fallback + inference (requires torch)
  test_residual_model.py          — ResidualModel determinism
  test_scenario_evaluator.py      — CVaR computation, feature flag
  test_rolling_horizon.py         — warm-start invariant
  test_rescheduling_api.py        — POST /compute, GET /latest
  test_dqn_policy.py              — ReplayBuffer, MaskedDqnPolicy, ReschedulingEnv
  test_scenario_fixtures.py       — 5 PDF §15.3 scenario tests (NEW in v2)
```

**Test count:** 186 passing, 0 skipped, 0 failures (with torch + torch_geometric + gymnasium installed).

Run with:
```bash
cd backend && python3 -m pytest tests/ -v
```

---

## 9. Configuration Reference

All settings are environment variables with safe defaults in `backend/config.py`:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | PostgreSQL local | SQLAlchemy connection string |
| `DEMO_MODE` | `true` | Use SQLite + deterministic fixtures |
| `BEAM_WIDTH` | `20` | Beam search width (v2: was 8) |
| `MAX_POLICY_EXPANSIONS` | `200` | Max beam expansions (v2: was 500) |
| `POLICY_TIME_LIMIT_MS` | `800` | Beam search wall-clock limit (v2: was 1000) |
| `SCENARIO_EVALUATION_ENABLED` | `false` | Enable K=16 CVaR scoring (requires historical data) |
| `PREDICTOR_BACKEND` | `auto` | `"auto"` / `"sage_het"` / `"baseline"` |
| `POLICY_BACKEND` | `beam_search` | `"beam_search"` / `"greedy"` / `"dqn"` |
| `ROLLING_HORIZON_ENABLED` | `false` | Enable 60-second background refresh worker |
| `MAX_IMPACTED_TRAINS` | `80` | Impact zone train cap |
| `MAX_IMPACTED_STATIONS` | `120` | Impact zone station cap |

---

## 10. Key Invariants

These invariants are tested and must hold at all times:

1. **No `import random`** in any production file
2. **All new endpoints under `/api/v1/`**
3. **TestingConfig (SQLite in-memory) runs all tests** — no PostgreSQL required for CI
4. **Torch-dependent tests use `pytest.importorskip("torch")`**
5. **Warm-start does not change objective when arc selection is identical** — verified by `test_rolling_horizon.py`
6. **No cascade errors from warm start** — arc weights recomputed from fresh snapshot each cycle
