# Rail-Flow AI — Digital Twin Control Tower

A 781-station Indian Railways digital twin network with real-time delay simulation, A* pathfinding, dual-code station lookup, and a Cytoscape.js force-directed graph UI.

---

## Prerequisites

Install these before starting. Verify each one opens without errors.

| Tool | Download | Verify |
|------|----------|--------|
| Python 3.10+ | https://www.python.org/downloads/ | `python --version` |
| Node.js 18+ | https://nodejs.org | `node --version` |
| PostgreSQL Server 18 | https://www.postgresql.org/download/ | `"C:\Program Files\PostgreSQL\18\bin\psql.exe" --version` |
| Git (optional) | https://git-scm.com | `git --version` |

> **Windows note:** Always use **CMD** (not PowerShell) for the commands in this guide.
> Press `Win + R` → type `cmd` → Enter.

---

## Project Structure

```text
rail-flow-ai/
├── backend/
│   ├── app.py              ← Flask server + all API endpoints
│   ├── models.py           ← Database tables (SQLAlchemy)
│   ├── graph_logic.py      ← A* pathfinding engine
│   ├── schema.sql          ← PostgreSQL DDL reference
│   └── requirements.txt    ← Python dependencies
├── frontend/
│   ├── package.json
│   └── src/
│       ├── index.js        ← React entry point
│       ├── App.js          ← Root component
│       └── components/
│           └── GraphComponent.jsx  ← Main graph UI
└── data/
    └── stations_seed.py    ← Seed metadata references
```

---

## Step 1 — PostgreSQL Setup

### 1a. Add PostgreSQL to your PATH (one-time setup)

Open CMD and run:
```cmd
setx PATH "%PATH%;C:\Program Files\PostgreSQL\18\bin"
```
Close CMD and open a fresh one. Now database utilities will work everywhere.

### 1b. Create the Database Container
Run this command to create an empty database container named `rail_digital_twin`:
```cmd
createdb -U postgres rail_digital_twin
```
*(Enter the master password you assigned to the `postgres` superuser during software installation).*

### 1c. Import the Custom Binary Digital Twin Dump
Navigate to the directory where your digital twin backup file (`dump-rail_digital_twin-202606131731.sql`) is stored (e.g., your Desktop):
```cmd
cd C:\Users\YourName\Desktop
```
Execute the native restore processor to initialize schemas and map binary data rows:
```cmd
pg_restore -U postgres -d rail_digital_twin -v dump-rail_digital_twin-202606131731.sql
```

### 1d. Apply Runtime Simulation Engine Patch
Inject the operational dynamic status constraint flag required by the pathfinding algorithms:
```cmd
psql -U postgres -d rail_digital_twin -c "ALTER TABLE public.stations ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'clear';"
```

---

## Step 2 — Backend Setup (Flask)

Open CMD and run these one at a time:

```cmd
cd C:\Users\YourName\Desktop\rail-flow-ai\backend
```

```cmd
python -m venv .venv
```

```cmd
.venv\Scripts\activate
```

You should see `(.venv)` appear at the start of the line. Then:

```cmd
pip install -r requirements.txt
```

```cmd
python app.py
```

**Expected output:**
```
 * Running on [http://127.0.0.1:5000](http://127.0.0.1:5000)
```

The backend is now running. **Leave this CMD window open.**

> **Database Configuration Connection Note:** The application automatically attempts connectivity with standard default user parameters. If your configuration changes, verify your environment settings inside `backend\app.py`:
> ```python
> app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://postgres:YOUR_PASSWORD@localhost:5432/rail_digital_twin"
> ```

---

## Step 3 — Frontend Setup (React)

Open a **second CMD window** (keep the first one running Flask):

```cmd
cd C:\Users\YourName\Desktop\rail-flow-ai\frontend
```

```cmd
npm install
```

```cmd
npm start
```

Your browser will open automatically at `http://localhost:3000`.

---

## Step 4 — Verify Everything Works

Open your browser and test these URLs:

| URL | Expected result |
|-----|----------------|
| `http://localhost:3000` | Graph UI loads with 781 nodes |
| `http://localhost:5000/api/stations` | JSON list of all 781 stations |
| `http://localhost:5000/api/station-lookup/HWH` | Howrah station details |
| `http://localhost:5000/api/trains` | Mock train telemetry mapping layers |
| `http://localhost:5000/api/path?from=C019&to=C022` | A* path parsing dynamic connection costs |

---

## Using the UI

### Station Search
Type either format in the search box:
- **Node ID (Station Code)** — `C019`, `N001`
- **Operational code (Alias)** — `HWH`, `NDLS`, `GHY`

Both return the same station metrics. Click **Toggle Status** to cycle it between Green (Clear) → Yellow (Congestion) → Red (Delayed).

### A* Path Finder
Enter any two station codes in the From/To input forms. The dynamic routing path is highlighted directly on the force graph array layout, calculating dynamic parameters across active delay models in real-time.

---

## Restarting After a Reboot

Every time you restart your computer, run both of these in separate CMD windows:

**Window 1 — Backend:**
```cmd
cd C:\Users\YourName\Desktop\rail-flow-ai\backend
.venv\Scripts\activate
python app.py
```

**Window 2 — Frontend:**
```cmd
cd C:\Users\YourName\Desktop\rail-flow-ai\frontend
npm start
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stations` | All 781 mapped digital twin network stations |
| GET | `/api/station-lookup/<code>` | Single station matching lookup targets across native and alias nodes |
| GET | `/api/trains` | Live real-time active train trajectory mappings |
| GET | `/api/trains/<id>` | Single train track telemetry by identification numbers |
| POST | `/api/station/<id>/status` | Body: `{"status":"clear"}` — Updates node color state and path tracking cost caches |
| GET | `/api/graph` | Full network architecture output mapped for Cytoscape renderer parsing |
| GET | `/api/path?from=X&to=Y` | A* path calculations across complex delay metric configurations |

---

## Troubleshooting

**`'psql' or 'createdb' is not recognized`**
→ PostgreSQL binary utilities are missing from your PATH settings environment profiles. Call your script manually using absolute references:
`"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d rail_digital_twin`

**`The input is a PostgreSQL custom-format dump`**
→ You attempted running a compressed binary backup directly using a standard script utility. You must feed custom-format files to `pg_restore` instead of standard script processors.

**`Access denied for user 'postgres'`**
→ The configuration authentication values inside your engine script strings do not match your database password. Verify credentials inside your local target environment configurations.

**Port 5000 already in use**
→ Another system background process is currently blocking execution channels. Clear execution lines using administrative commands:
`netstat -ano | findstr :5000` then terminate using `taskkill /PID <number> /F`.