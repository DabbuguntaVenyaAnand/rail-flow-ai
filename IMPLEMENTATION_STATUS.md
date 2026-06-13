# Rail-Flow AI — HSR-RailFlow Implementation Status

**Project:** Hybrid Shielded Rolling-Horizon Rescheduler (HSR-RailFlow)
**Stack:** Flask 3.0.3 · Flask-SQLAlchemy 3.1.1 · Flask-Migrate 4.0.7 · PostgreSQL (prod) / SQLite (tests)
**Tests:** 157 passing · 5 skipped (GNN tests — torch/torch_geometric not installed) · 0 failures

---

## Is the Code Complete?

**Functionally: Yes.** All 7 phases of the HSR-RailFlow algorithm are implemented and tested.

**Two components need training before they unlock full capability:**
- `SageHetPredictor` (Phase 5) — falls back to rule-based baseline until trained
- `MaskedDqnPolicy` (Phase 6) — falls back to BeamSearch until trained

Everything else (rescheduling, rolling horizon, API, impact zone, snapshot) is fully operational right now with zero additional setup beyond the DB migration.

---

## Architecture Overview

```
snapshot_json
     │
     ├─► ImpactZoneService ──────────────────────────────► impact_run_ids
     │         │
     │         └─► HistoricalBaselinePredictor  (or SageHetPredictor)
     │                       │
     │                       └─► DelayEstimate list
     │
     └─► AlternativeGraph.build()
               │
               ├─► FeasibilityShield.validate_partial()  ← fast pruning
               │
               ├─► GreedyPolicy  or  BeamSearchPolicy  (or MaskedDqnPolicy)
               │         └─► list[CandidatePlan]
               │
               ├─► ScenarioEvaluator.score()  ← CVaR risk scoring
               │         └─► best CandidatePlan selected
               │
               ├─► LocalSearch.improve()
               │
               └─► AuditService.persist_run()  ──► ReschedulingRun (DB)
```

---

## What Each Phase Implements

### Phase 0 — Baseline Preservation
All 10 original Flask endpoints preserved exactly:
- `GET /api/stations`, `/api/station-lookup/<code>`, `/api/trains`, `/api/trains/<id>`
- `POST /api/station/<id>/status`, `/api/disruption/inject`
- `GET /api/graph`, `/api/path`, `/api/predict/ripple/<code>`, `/api/analytics/delay-history/<code>`

### Phase 1 — Operational Schema
11 new ORM models added to `backend/models.py`:

| Table | Class | Purpose |
|---|---|---|
| `timetable_runs` | `TimetableRun` | One service-date train instance |
| `timetable_events` | `TimetableEvent` | Per-stop scheduled/actual times |
| `live_train_states` | `LiveTrainState` | Latest position + delay |
| `disruption_events` | `DisruptionEvent` | Active disruptions |
| `operational_snapshots` | `OperationalSnapshot` | Point-in-time snapshot |
| `delay_predictions` | `DelayPrediction` | p50/p90 forecasts |
| `rescheduling_runs` | `ReschedulingRun` | Audit record per optimization |
| `rescheduling_actions` | `ReschedulingAction` | Individual recommended actions |
| `detected_conflicts` | `DetectedConflict` | Headway/ordering conflicts |
| `model_versions` | `ModelVersion` | ML artifact registry |

### Phase 2 — Digital Twin
| File | Class | Role |
|---|---|---|
| `services/snapshot_service.py` | `SnapshotService` | Builds `snapshot_json` from live DB state |
| `simulator/occupancy.py` | `OccupancyModel` | Occupancy intervals + headway violation detection |
| `simulator/event_simulator.py` | `EventSimulator` | Materialises event times from schedule + holds |
| `rescheduling/objective.py` | `ObjectiveFunction` | J_det = L_sum + λ_max·L_max + λ_chg·N_chg + λ_hold·H_add |
| `services/audit_service.py` | `AuditService` | Writes ReschedulingRun + actions + conflicts to DB |

**Objective function weights (PDF Table 2):**
```
λ_max  = 0.25  (max single-train delay scaling)
λ_chg  = 60 s  (penalty per changed train)
λ_hold = 10 s  (penalty per additional hold-second)
λ_risk = 0.25  (CVaR risk weight, Phase 7)
```

### Phase 3 — Alternative Graph + Core Rescheduling
| File | Class | Role |
|---|---|---|
| `rescheduling/alternative_graph.py` | `AlternativeGraph` | Ordered pairs as selectable arc pairs |
| `rescheduling/feasibility.py` | `FeasibilityShield` | 6-stage validation (Algorithm 3) |
| `rescheduling/fallback.py` | `HoldFallback` | Adds 300 s hold when both directions fail |
| `rescheduling/local_search.py` | `LocalSearch` · `CandidatePlan` | 4 non-worsening move types |
| `policies/greedy_policy.py` | `GreedyPolicy` | Earliest-conflict-first (Algorithm 4) |
| `policies/beam_search_policy.py` | `BeamSearchPolicy` | B=8, E_max=500 (Algorithm 5) |
| `api/rescheduling_routes.py` | — | REST endpoints (see below) |

**FeasibilityShield stages:**
1. Cycle detection (DFS)
2. Longest-path LP → `event_times`
3. Commit-window check (tolerance 30 s)
4. Dwell / running-time bounds
5. Blocked-resource check (DisruptionEvent)
6. Headway check via OccupancyModel

**REST endpoints added:**
```
POST /api/v1/rescheduling/compute
GET  /api/v1/rescheduling/latest
```

### Phase 4 — Historical Predictor + Impact Zone
| File | Class | Role |
|---|---|---|
| `predictors/base.py` | `DelayPredictor` Protocol · `DelayEstimate` | Predictor interface |
| `predictors/historical_baseline.py` | `HistoricalBaselinePredictor` | Rule-based baseline |
| `services/impact_zone_service.py` | `ImpactZoneService` | Algorithm 1 — selects affected trains |

**HistoricalBaselinePredictor logic:**
- Base delay from `live_states.delay_seconds`
- Peak-hour × 1.3  (IST 07:00–09:00 and 17:00–19:00 = UTC 01:30–03:30 and 11:30–13:30)
- Short-headway × 1.2  (gap < 15 min to preceding train at same station)
- p90 = p50 × 1.6

**ImpactZoneService thresholds:**
```
theta_obs  = 5 min  → include if live delay ≥ threshold
theta_pred = 8 min  → include if p50_predicted ≥ threshold
headway_cutoff = 20 min  → propagate to trains within this headway gap
max_impacted_trains = 80
```

### Phase 7 — Uncertainty + Rolling Refresh
| File | Class | Role |
|---|---|---|
| `predictors/residual_model.py` | `ResidualModel` | Sorted per-bucket residuals, deterministic sampling |
| `simulator/scenario_evaluator.py` | `ScenarioEvaluator` | Algorithm 6 — K=16 CVaR scoring |
| `rescheduling/rolling_horizon.py` | `RollingHorizonService` | Algorithm 2 — full cycle + warm start + background thread |

**ScenarioEvaluator formula:**
```
J_risk = J_det + λ_risk · CVaR_α
CVaR_α = mean of top ceil((1-α)·K) scenario scores
Default: K=16, α=0.90 → tail = top 2 of 16
```

**ResidualModel bucket key:** `(station_code, train_number, horizon_minutes)`

**RollingHorizonService.run_cycle() steps:**
1. SnapshotService.build(t0)
2. HistoricalBaselinePredictor.predict()
3. ImpactZoneService.select()
4. AlternativeGraph.build() + apply_warm_start()
5. Policy.propose()
6. ScenarioEvaluator picks best plan
7. LocalSearch.improve()
8. Store `_warm_arc_selection` for next cycle
9. AuditService.persist_run()

### Phase 5 — SAGE-Het GNN Predictor
| File | Class | Role |
|---|---|---|
| `predictors/hetero_graph_builder.py` | `HeteroGraphBuilder` | Snapshot → PyG HeteroData |
| `predictors/sage_het.py` | `SageHetPredictor` | 2-layer HeteroSAGE, p50+p90 heads |
| `training/train_sage_het.py` | — | CLI training script |

**Node types:**
- `station` (3 features): `[delay_bucket/4, is_disrupted, degree_norm]`
- `running_train` (3 features): `[delay_s/3600, progress, is_delayed]`

**Edge types:**
- `running_train → at_station → station` (last observed location)
- `running_train → scheduled_at → station` (all timetable stops)
- `running_train → follows → running_train` (ordering pairs from AlternativeGraph)
- `station → connects → station` (CorridorEdge from DB)

**Model architecture:**
- Station + train linear projection → hidden_dim=64
- Scatter-mean aggregation (station→train via scheduled_at edges)
- 2-layer MLP per train node
- Dual SoftPlus output heads: p50 and p90 (seconds/3600 scale)

**⚠️ NOT YET TRAINED.** Falls back to `HistoricalBaselinePredictor` automatically.

### Phase 6 — DQN Policy
| File | Class | Role |
|---|---|---|
| `policies/dqn_policy.py` | `ReschedulingEnv` | Gymnasium environment |
| | `ReplayBuffer` | Fixed-capacity circular buffer (numpy, no `import random`) |
| | `DuelingDQN` | V(s) + A(s,a) − mean(A) network |
| | `MaskedDqnPolicy` | Double-DQN with action masking + BeamSearch fallback |
| `training/train_dqn.py` | — | CLI training script |

**Environment specification:**
```
Observation : float32 vector, dim = MAX_PAIRS×3 + 2
              [dep_i_h, dep_j_h, sel_enc] per pair + [unresolved_ratio, t0_hour]
Action      : Discrete(MAX_PAIRS×2)  →  (pair_slot × 2 + direction)
Reward      : -(J_det_after - J_det_before) / 3600.0
Done        : all alternative pairs resolved
```

**Training curriculum (by episode number):**
```
Episodes   0 –  499 : single-train conflicts (1 pair)
Episodes 500 – 1499 : two-train conflicts (2 pairs)
Episodes 1500+      : full multi-train scenarios
```

**⚠️ NOT YET TRAINED.** Falls back to `BeamSearchPolicy` automatically.

---

## Complete File Structure

```
backend/
├── app.py                          # Flask factory, CLI commands, blueprint registration
├── config.py                       # All env-based config (TestingConfig uses SQLite)
├── models.py                       # 4 legacy + 11 new ORM models
├── graph_logic.py                  # Legacy A* pathfinding
├── disruption_engine.py            # Legacy disruption propagation
│
├── api/
│   ├── __init__.py
│   └── rescheduling_routes.py      # POST /compute  GET /latest
│
├── predictors/
│   ├── __init__.py
│   ├── base.py                     # DelayPredictor protocol + DelayEstimate
│   ├── historical_baseline.py      # Rule-based baseline predictor
│   ├── hetero_graph_builder.py     # Snapshot → PyG HeteroData  [Phase 5]
│   ├── residual_model.py           # Per-bucket sorted residuals [Phase 7]
│   └── sage_het.py                 # SAGE-Het GNN predictor      [Phase 5]
│
├── policies/
│   ├── __init__.py
│   ├── greedy_policy.py            # Algorithm 4
│   ├── beam_search_policy.py       # Algorithm 5
│   └── dqn_policy.py              # MaskedDqnPolicy + ReschedulingEnv [Phase 6]
│
├── rescheduling/
│   ├── alternative_graph.py        # AlternativeGraph, EventNode, Arc, AltPair
│   ├── feasibility.py              # FeasibilityShield (Algorithm 3)
│   ├── fallback.py                 # HoldFallback
│   ├── local_search.py             # LocalSearch + CandidatePlan
│   ├── objective.py                # ObjectiveFunction + ScheduleMetrics
│   └── rolling_horizon.py         # RollingHorizonService (Algorithm 2) [Phase 7]
│
├── services/
│   ├── audit_service.py            # AuditService
│   ├── impact_zone_service.py      # ImpactZoneService (Algorithm 1)
│   └── snapshot_service.py         # SnapshotService
│
├── simulator/
│   ├── event_simulator.py          # EventSimulator
│   ├── occupancy.py                # OccupancyModel
│   └── scenario_evaluator.py      # ScenarioEvaluator (Algorithm 6) [Phase 7]
│
├── training/
│   ├── __init__.py
│   ├── train_sage_het.py           # GNN training CLI [Phase 5]
│   └── train_dqn.py               # DQN training CLI [Phase 6]
│
├── fixtures/
│   ├── demo_timetable.py           # 5 deterministic train runs + events
│   └── demo_disruptions.py         # 1 deterministic disruption
│
├── migrations/                     # Alembic migrations via Flask-Migrate
│
└── tests/                          # 157 tests across all phases
    ├── conftest.py                 # Shared fixtures (session-scoped SQLite)
    ├── test_legacy_endpoints.py
    ├── test_no_random_in_production.py
    ├── test_snapshot_service.py
    ├── test_objective_function.py
    ├── test_alternative_graph.py
    ├── test_feasibility_shield.py
    ├── test_greedy_policy.py
    ├── test_beam_search_policy.py
    ├── test_rescheduling_api.py
    ├── test_delay_predictor.py
    ├── test_impact_zone.py
    ├── test_residual_model.py
    ├── test_scenario_evaluator.py
    ├── test_rolling_horizon.py
    ├── test_hetero_graph_builder.py  # skipped without torch_geometric
    ├── test_sage_het_predictor.py    # 3 tests skip without torch
    └── test_dqn_policy.py           # 2 tests skip without torch/gymnasium
```

---

## Has Training Been Done?

**No.** Both ML models (SAGE-Het and DQN) are untrained. The system works fully right now because:

- `SageHetPredictor` → auto-falls back to `HistoricalBaselinePredictor` (no artifact file found)
- `MaskedDqnPolicy` → auto-falls back to `BeamSearchPolicy` (no artifact file found)

The rule-based fallbacks are solid — the system produces valid rescheduling plans without the ML components. Training only improves delay prediction accuracy and policy quality.

---

## How to Train the Models

### Prerequisites

```bash
pip install "torch>=2.3.0" "torch-geometric>=2.5.0" "gymnasium>=0.29.0"
```

### Train SAGE-Het GNN Predictor

Requires a populated PostgreSQL database with real TimetableEvent actuals.

```bash
cd backend

# Step 1: Ensure the DB has historical data (actuals in timetable_events)
# The demo data has synthetic actuals; real data produces a better model.

# Step 2: Train (temporal split: data before 2026-06-01 = train, after = val)
python3 -m training.train_sage_het \
    --split-date 2026-06-01 \
    --epochs 100 \
    --hidden-dim 64 \
    --lr 1e-3 \
    --output models/sage_het_v1.pt

# Step 3: Activate in production
export SAGE_HET_MODEL_PATH=models/sage_het_v1.pt
export PREDICTOR_BACKEND=sage_het
```

The script saves the best-val-loss weights. Training on the demo dataset (5 trains) is too small to be useful — you need at least a few weeks of real service data with recorded actual_arrival timestamps.

### Train DQN Policy

Can train on the demo dataset in simulation mode (no real data needed).

```bash
cd backend

python3 -m training.train_dqn \
    --episodes 2000 \
    --seed 42 \
    --hidden-dim 128 \
    --lr 1e-4 \
    --gamma 0.99 \
    --output models/dqn_v1.pt

# Activate in production
export DQN_MODEL_PATH=models/dqn_v1.pt
export POLICY_BACKEND=dqn
```

2000 episodes takes ~5–15 minutes on CPU depending on graph complexity. Use `--episodes 5000` for a properly converged policy. The curriculum automatically starts with single-conflict scenarios before scaling to multi-train problems.

---

## How to Run the Final Code

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
# Optional ML stack:
# pip install "torch>=2.3.0" "torch-geometric>=2.5.0" "gymnasium>=0.29.0"
```

### 2. Set Up Database

**Option A — Demo mode (SQLite, no PostgreSQL needed):**
```bash
export DEMO_MODE=true
# SQLite is created automatically in demo mode — no setup needed.
```

**Option B — Production PostgreSQL:**
```bash
createdb railflow_db
export DATABASE_URL="postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db"
export DEMO_MODE=false
flask db upgrade          # apply all Alembic migrations
```

### 3. Seed Demo Data

```bash
export DEMO_MODE=true
flask seed-demo
# Loads: 5 train runs, 20 timetable events, 3 live states (delayed), 1 disruption
```

Demo trains seeded:
| Train | Run ID (last 8) | Delay | Notes |
|---|---|---|---|
| 12301 Howrah Rajdhani | `00000001` | 900 s | Delayed |
| 12302 New Delhi Rajdhani | `00000002` | 0 s | On time |
| 12303 Poorva Express | `00000003` | 900 s | Delayed |
| 12304 Poorva Express (ret) | `00000004` | 0 s | On time |
| 12305 Howrah Rajdhani (ret) | `00000005` | 1200 s | Delayed |

### 4. Run the Server

```bash
cd backend
flask run
# Server starts at http://localhost:5000
```

### 5. Test the Rescheduling API

**Trigger a rescheduling cycle (beam search, 60-min horizon):**
```bash
curl -s -X POST http://localhost:5000/api/v1/rescheduling/compute \
  -H "Content-Type: application/json" \
  -d '{
    "policy": "beam_search",
    "horizon_minutes": 600,
    "use_predictions": true
  }' | python3 -m json.tool
```

**Expected response:**
```json
{
  "rescheduling_run_id": "...",
  "status": "success",
  "objective_before": 2700.0,
  "objective_after": 2700.0,
  "compute_time_ms": 45,
  "actions": [
    {
      "sequence": 1,
      "type": "set_precedence",
      "run_id": "...",
      "payload": { "direction": "fwd", "edge_id": 2 }
    }
  ],
  "conflicts_detected": 2,
  "conflicts_resolved": 2
}
```

**Get latest result:**
```bash
curl -s http://localhost:5000/api/v1/rescheduling/latest | python3 -m json.tool
```

**Use greedy policy instead:**
```bash
curl -s -X POST http://localhost:5000/api/v1/rescheduling/compute \
  -H "Content-Type: application/json" \
  -d '{"policy": "greedy", "horizon_minutes": 600}'
```

**Specify a custom t0 (useful for testing historical scenarios):**
```bash
curl -s -X POST http://localhost:5000/api/v1/rescheduling/compute \
  -H "Content-Type: application/json" \
  -d '{"t0": "2026-06-13T05:00:00Z", "horizon_minutes": 600}'
```

### 6. Enable Rolling-Horizon Background Worker (Optional)

The worker continuously re-runs rescheduling every N seconds and updates the latest result.

```bash
export ROLLING_HORIZON_ENABLED=true
export ROLLING_REFRESH_SECONDS=60    # recompute every 60 s
flask run
```

The worker starts automatically when `ROLLING_HORIZON_ENABLED=true`. It stores warm-start arc selections between cycles so each run benefits from the previous solution.

Shut down by stopping the Flask process — the thread is a daemon and exits cleanly.

### 7. Run Tests

```bash
cd backend
python3 -m pytest tests/ -v           # all tests
python3 -m pytest tests/ -q           # quiet summary
python3 -m pytest tests/ -k "api"     # only API tests
python3 -m pytest tests/ -k "rolling" # only rolling-horizon tests
```

Expected output: `157 passed, 5 skipped` (the 5 skips are torch/torch_geometric tests).

---

## Configuration Reference

All settings are environment variables. Set in `.env` (copy from `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | PostgreSQL local | SQLAlchemy URI |
| `DEMO_MODE` | `true` | Auto-create tables + allow fixture loading |
| `HORIZON_MIN` | `60` | Planning horizon in minutes |
| `COMMIT_WINDOW_MIN` | `10` | Frozen commit window width |
| `ROLLING_REFRESH_SECONDS` | `60` | Background worker sleep interval |
| `ROLLING_HORIZON_ENABLED` | `false` | Start background worker |
| `POLICY_BACKEND` | `beam_search` | `beam_search` / `greedy` / `dqn` |
| `PREDICTOR_BACKEND` | `auto` | `auto` / `sage_het` |
| `BEAM_WIDTH` | `8` | Beam search width |
| `MAX_POLICY_EXPANSIONS` | `500` | Beam search expansion limit |
| `SCENARIO_COUNT` | `16` | K scenarios for CVaR |
| `RISK_ALPHA` | `0.90` | CVaR confidence level |
| `RISK_WEIGHT` | `0.25` | λ_risk in J_risk |
| `MAX_IMPACTED_TRAINS` | `80` | Impact zone cap |
| `SAGE_HET_MODEL_PATH` | `models/sage_het_v1.pt` | GNN artifact path |
| `DQN_MODEL_PATH` | `models/dqn_v1.pt` | DQN artifact path |

---

## What Remains Before Production

1. **Train the ML models** with real data (optional — fallbacks work fine)
2. **Run `flask db upgrade`** against a real PostgreSQL instance
3. **Ingest real timetable data** — populate `timetable_runs` and `timetable_events` from your data source (CSV / NTES API / GTFS)
4. **Connect live telemetry** — write to `live_train_states` on each GPS/AIS update
5. **Inject disruptions** via `POST /api/disruption/inject` or your operations feed
6. **Set `ROLLING_HORIZON_ENABLED=true`** in production to activate continuous rescheduling

The frontend (React/Cytoscape) already works unchanged against all the original endpoints. The new `/api/v1/rescheduling/` endpoints are additive.
