# Rail-Flow AI — Digital Twin Control Tower

A 500-station Indian Railways demo network with real-time delay simulation,
A* pathfinding, dual-code station lookup, and a Cytoscape.js force-directed graph UI.

---

## Prerequisites

Install these before starting. Verify each one opens without errors.

| Tool | Download | Verify |
|------|----------|--------|
| Python 3.10+ | https://www.python.org/downloads/ | `python --version` |
| Node.js 18+ | https://nodejs.org | `node --version` |
| MySQL Server 8.0 | https://dev.mysql.com/downloads/installer/ | `mysql --version` |
| MySQL Workbench | Included in MySQL installer above | Open from Start Menu |
| Git (optional) | https://git-scm.com | `git --version` |

> **Windows note:** Always use **CMD** (not PowerShell) for the commands in this guide.
> Press `Win + R` → type `cmd` → Enter.

---

## Project Structure

```
rail-flow-ai/
├── backend/
│   ├── app.py              ← Flask server + all API endpoints
│   ├── models.py           ← Database tables (SQLAlchemy)
│   ├── graph_logic.py      ← A* pathfinding engine
│   ├── schema.sql          ← Optional raw MySQL DDL
│   └── requirements.txt    ← Python dependencies
├── frontend/
│   ├── package.json
│   └── src/
│       ├── index.js        ← React entry point
│       ├── App.js          ← Root component
│       └── components/
│           └── GraphComponent.jsx  ← Main graph UI
└── data/
    └── stations_seed.py    ← All 500 station records
```

---

## Step 1 — MySQL Setup

### 1a. Add MySQL to your PATH (one-time setup)

Open CMD and run:
```cmd
setx PATH "%PATH%;C:\Program Files\MySQL\MySQL Server 8.0\bin"
```
Close CMD and open a fresh one. Now `mysql` will work everywhere.

### 1b. Create the database

```cmd
mysql -u root -p201810 -e "CREATE DATABASE IF NOT EXISTS railflow_db;"
```

Replace `201810` with your MySQL root password if different.

> **Alternative:** Open MySQL Workbench → connect → run this in a query tab:
> ```sql
> CREATE DATABASE IF NOT EXISTS railflow_db;
> ```

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
[Rail-Flow] Database seeded with 500 stations.
 * Running on http://127.0.0.1:5000
```

The backend is now running. **Leave this CMD window open.**

> If you see `Access denied for user 'root'`, open `backend\app.py` and update
> this line with your correct MySQL password:
> ```python
> "mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/railflow_db"
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
| `http://localhost:3000` | Graph UI loads with 500 nodes |
| `http://localhost:5000/api/stations` | JSON list of all 500 stations |
| `http://localhost:5000/api/station-lookup/HWH` | Howrah station details |
| `http://localhost:5000/api/station-lookup/C019` | Same station via Node ID |
| `http://localhost:5000/api/trains` | Mock train telemetry |
| `http://localhost:5000/api/path?from=C019&to=C022` | A* path from Howrah to NJP |

---

## Using the UI

### Station Search
Type either format in the search box:
- **Node ID** — `C019`, `N001`
- **Operational code** — `HWH`, `NDLS`, `GHY`

Both return the same station. Click **Toggle Status** to cycle it between
Green (Clear) → Yellow (Congestion) → Red (Delayed).

### A* Path Finder
Enter any two station codes (Node ID or alias) in the From/To boxes.
The shortest path is highlighted on the graph with dynamic cost shown in minutes.

### Node Click
Click any node on the graph to see its full details in the sidebar.
Click **Cycle Status** to change its state live.

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
| GET | `/api/stations` | All 500 stations. Filter with `?layer=corridor` or `?state=Bihar` |
| GET | `/api/station-lookup/<code>` | Single station by Node ID or alias |
| GET | `/api/trains` | All trains, GTFS-structured mock telemetry |
| GET | `/api/trains/<id>` | Single train by ID |
| POST | `/api/station/<id>/status` | Body: `{"status":"clear"}` — updates node color |
| GET | `/api/graph` | Full graph payload for Cytoscape.js |
| GET | `/api/path?from=X&to=Y` | A* shortest path with dynamic cost |

---

## Troubleshooting

**`'mysql' is not recognized`**
→ MySQL is not in PATH. Run the `setx` command in Step 1a, then reopen CMD.

**`Access denied for user 'root'`**
→ Wrong password in `app.py`. Update the connection string with your actual MySQL password.

**`Could not find a required file: index.html`**
→ Create `frontend\public\index.html` — see the HTML content in Step 3 above,
or copy it from the project zip.

**`'source' is not recognized`**
→ You are in PowerShell. Switch to CMD (`Win + R` → `cmd`).

**`UnboundLocalError: cannot access local variable`**
→ Replace `backend\app.py` with the latest version from the project zip.

**Port 5000 already in use**
→ Another process is using the port. Run `netstat -ano | findstr :5000` in CMD
to find it, then `taskkill /PID <number> /F` to stop it.

**Frontend shows "Cannot reach API"**
→ Make sure the Flask backend is running in the other CMD window on port 5000.

---

## Dataset Notes

- Station data sourced from the RailTel Region 1 North+East annexure + curated hub overlay.
- This is a **modelling dataset** — not an official delay or priority ranking.
- Some historical station codes may need verification against current IR operational systems before production use.
- The companion `data/stations_seed.py` contains all 500 records and can be edited to add or correct entries.
