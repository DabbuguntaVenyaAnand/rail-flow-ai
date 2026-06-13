# Rail-Flow AI — Digital Twin Control Tower

A 781-station Indian Railways digital twin network with real-time delay simulation, A* pathfinding, dual-code station lookup, a Cytoscape.js force-directed graph UI, and the advanced HSR-RailFlow rescheduling optimization engine.

---

## HSR-RailFlow Rescheduling Engine (Core Algorithmic Logic)

The **Hybrid Shielded Rolling-Horizon Rescheduler (HSR-RailFlow)** is the mathematical core of the digital twin. It resolves headway and ordering conflicts caused by network disruptions using a **7-phase rolling-horizon optimization cycle**:

1. **Phase 1: Operational Schema:** Manages structural data including services date runs (`timetable_runs`), stop timings (`timetable_events`), live delays (`live_train_states`), and auditing metadata.
2. **Phase 2: Digital Twin Simulator:** Evaluates schedule quality using headway/dwell timing calculations and computes a multi-objective cost function scaling total delays, single-train maximum delays, precedence change penalties, and additional hold-seconds.
3. **Phase 3: Alternative Graph Optimization:** Models resource scheduling conflicts as alternative arc pairs. An advanced **6-stage Feasibility Shield** prunes cycles and checks safety rules:
   - *Stage 1:* Cycle detection (DFS)
   - *Stage 2:* Longest-path linear programming (LP) to derive event times
   - *Stage 3:* Commit window freeze checking (tolerance 30 s)
   - *Stage 4:* Running and dwell time bounds
   - *Stage 5:* Disrupted segment blockages (safety blocks)
   - *Stage 6:* Headway safety intervals via the Occupancy Model
4. **Phase 4 & 7: Impact Zone & Rolling Horizons:** Restricts computational scope using an **Impact Zone** headway-cutoff selector (threshold: 20 min). Samples residual timings across 16 scenarios, scores risks using **Conditional Value at Risk (CVaR)**, and runs a continuous warm-started background daemon worker.
5. **Phase 5 & 6: Machine Learning Predictors (Untrained):** Uses a Heterogeneous Graph Neural Network (`SageHetPredictor`) and gymnasium Double-DQN Policy (`MaskedDqnPolicy`).
   - *Note:* Since these are untrained in the source repository, the engine automatically falls back to robust, deterministic rule-based algorithms: **`HistoricalBaselinePredictor`** (historical statistics, peak-hour coefficients, and short-headway adjustments) and **`BeamSearchPolicy`** (search width of 8, max expansion 500).

---

## Project Structure

```text
rail-flow-ai/
├── backend/
│   ├── app.py                  ← Flask server, blueprints, and daemon thread
│   ├── models.py               ← Merged database models (15 SQLAlchemy tables)
│   ├── config.py               ← Environment-driven configurations
│   ├── graph_logic.py          ← A* pathfinding engine
│   ├── disruption_engine.py    ← Ripple propagation model
│   ├── schema.sql              ← Baseline PostgreSQL DDL reference
│   ├── rescheduling/           ← Alternative graph & Feasibility Shield
│   ├── predictors/             ← SAGE-Het GNN and baseline delay forecasts
│   ├── policies/               ← Greedy, Beam Search, and DQN scheduling
│   ├── services/               ← Snapshot, impact zone, and audit services
│   ├── simulator/              ← Occupancy, event timings, and CVaR evaluator
│   ├── fixtures/               ← Timetables and disruption seed data
│   ├── training/               ← GNN/DQN training CLI scripts
│   └── tests/                  ← 160 unit/integration tests
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.js              ← React entry point
│       └── components/
│           ├── GraphComponent.jsx  ← Cytoscape graph UI
│           └── TacticalMapModal.jsx ← Path overlays & detours tactical modal
└── data/
    └── stations_seed.py        ← Seed metadata references
```

---

## Prerequisites

Verify each tool opens without errors:

| Tool | Download | Verify |
|------|----------|--------|
| Python 3.10+ | https://www.python.org/downloads/ | `python --version` |
| Node.js 18+ | https://nodejs.org | `node --version` |
| PostgreSQL Server 17/18 | https://www.postgresql.org/download/ | `"C:\Program Files\PostgreSQL\18\bin\psql.exe" --version` |
| Git | https://git-scm.com | `git --version` |

---

## Step 1 — Database Setup (PostgreSQL)

### 1a. Create the Database Container
Run this command to create an empty database container named `rail_digital_twin`:
```cmd
createdb -U postgres rail_digital_twin
```

### 1b. Import the custom PGDMP Dump
Import the database backup (`dump-rail_digital_twin-202606132123.sql`):
```cmd
pg_restore -U postgres -d rail_digital_twin -v dump-rail_digital_twin-202606132123.sql
```

### 1c. Run Schema Migration
Our PostgreSQL database schema has been successfully migrated to adapt to HSR-RailFlow. It safely preserves the 464 core stations and metadata while updating tables:
* Renamed `trains` to `train_locations` (telemetry) and updated primary key `train_id` to `VARCHAR(20)`.
* Created a new `trains` table (catalog) and backfilled it with all distinct trains.
* Upgraded `station_connections` to include 6 operational columns (`min_headway_seconds`, `is_enabled`, etc.) and backfilled all 16,242 null distances to `60.0` minutes.
* Restored legacy foreign keys `fk_route_train` and `fk_train` pointing to the new catalog table.
* Created the remaining 9 HSR-RailFlow tables.

*(The migration has already been executed on the target environment).*

---

## Step 2 — Backend Setup (Flask)

Open CMD and run these commands one at a time:
```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
**Expected output:**
```text
 * Running on http://127.0.0.1:5000
```
* **Rolling Horizon background Worker (Optional):** To activate the continuous background scheduling optimizer thread, set the environment variable:
  ```cmd
  set ROLLING_HORIZON_ENABLED=true
  ```

---

## Step 3 — Frontend Setup (React)

Open a **second CMD window**:
```cmd
cd frontend
npm install
npm start
```
Your browser will open automatically at `http://localhost:3000`.

---

## Step 4 — Verify & Seed Data

Open your browser or client and verify:

| Action / URL | Expected Result |
|--------------|-----------------|
| `http://localhost:3000` | Graph UI loads with 456 core stations lag-free. |
| `http://localhost:5000/api/graph` | Cytoscape graph payload loads in under **0.15 seconds**. |
| `http://localhost:5000/api/path?from=TMZ&to=ADTP` | A* pathfinder with bypass detour routing. |
| `flask seed-demo` (Run in backend CMD) | Seeds timetable runs, events, states, and active disruptions. |
| `POST http://localhost:5000/api/v1/rescheduling/compute` | Computes rescheduling plan, resolving conflicts, and returning objective functions. |

---

## API Reference

### Legacy Endpoints
* `GET /api/stations` - Mapped digital twin stations. Filter by `?layer=hub` or `?state=Bihar`.
* `GET /api/station-lookup/<code>` - Look up station by ID or operational alias.
* `GET /api/trains` - Real-time train telemetry wrapped in GTFS-realtime format.
* `GET /api/trains/<train_id>` - Telemetry metrics for a single train.
* `POST /api/station/<id>/status` - Updates station status (`clear`, `congestion`, `delayed`).
* `GET /api/graph` - Cytoscape graph representation of the 456 core backbone stations.
* `GET /api/path?from=X&to=Y` - A* shortest path with detour bypass routes if disruptions exist.
* `POST /api/disruption/inject` - Injects active network congestion or delays.

### HSR-RailFlow API
* **`POST /api/v1/rescheduling/compute`** - Triggers a rescheduling run.
  * Body (JSON): `{"policy": "beam_search", "horizon_minutes": 60, "use_predictions": true}`
* **`GET /api/v1/rescheduling/latest`** - Retrieves the last computed rescheduling plan with audit logs, conflict statuses, and actions.

---

## Git Commit Guide

To commit all integrated HSR-RailFlow directories and schema modifications to your repository, follow these steps:

1. **Verify changed files:**
   ```bash
   git status
   ```
2. **Add code changes and new folders:**
   ```bash
   git add backend/app.py backend/models.py backend/config.py backend/pytest.ini backend/rescheduling/ backend/predictors/ backend/policies/ backend/services/ backend/simulator/ backend/fixtures/ backend/training/ backend/tests/ backend/api/ README.md
   ```
3. **Commit changes:**
   ```bash
   git commit -m "feat: integrate HSR-RailFlow rescheduling engine and PostgreSQL schema migration"
   ```