#!/usr/bin/env python3
"""
simulator_cli.py — Rail-Flow AI

Interactive Live Telemetry Simulator for Hackathon Demonstrations.
Simulates real-time train movement, delay updates, and triggers the HSR-RailFlow 
rescheduling loop every 10 seconds.
"""

import sys
import os
import time
from datetime import datetime, timezone, timedelta
import random

# Add backend/ to Python path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

try:
    from app import create_app
    from models import db, LiveTrainState, TimetableRun, TimetableEvent, DisruptionEvent
    from rescheduling.rolling_horizon import RollingHorizonService
except ImportError as e:
    print(f"Error importing app/models: {e}")
    print("Please make sure you have activated the virtual environment:")
    print("  Windows: backend\\.venv\\Scripts\\activate")
    print("  macOS/Linux: source backend/.venv/bin/activate")
    sys.exit(1)

def run_simulation():
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("          RAIL-FLOW AI LIVE TELEMETRY SIMULATOR         ")
        print("=" * 60)
        print("Initializing simulation loop...")
        
        # Check database rows
        run_count = TimetableRun.query.count()
        if run_count == 0:
            print("[Simulator] Warning: No timetable runs in DB. Please run 'flask seed-demo' first.")
            return

        print(f"[Simulator] Found {run_count} timetable runs. Starting telemetry simulation.")
        print("[Simulator] Press Ctrl+C to terminate the simulator loop.")
        print("-" * 60)

        # Baseline timestamp for demo
        t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
        iteration = 1

        try:
            while True:
                # 1. Update train live states (telemetry simulation)
                states = LiveTrainState.query.all()
                print(f"\n[Iteration #{iteration}] Timestamp: {t0.isoformat()}")
                print(f"--- Simulating Telemetry updates for {len(states)} trains ---")
                
                for state in states:
                    run = TimetableRun.query.get(state.run_id)
                    train_num = run.train_number if run else "Unknown"
                    
                    # Randomly fluctuate delay (+/- 60 seconds)
                    delay_fluctuation = random.randint(-45, 90)
                    new_delay = max(0, state.delay_seconds + delay_fluctuation)
                    
                    # Occasionally update station coordinates/progress
                    state.delay_seconds = new_delay
                    
                    print(f"  Train {train_num:5s} | Current Station: {state.current_station:5s} | Speed: {state.speed_kmh:3.0f} km/h | Delay: {new_delay/60:.1f} min")
                
                db.session.commit()
                
                # 2. Trigger HSR-RailFlow rescheduling cycle dynamically
                print("--- Triggering HSR-RailFlow Rescheduling Engine ---")
                start_time = time.time()
                
                svc = RollingHorizonService(
                    horizon_minutes=600,
                    commit_window_minutes=10,
                    policy_name="beam_search",
                )
                
                res_run = svc.run_cycle(t0)
                elapsed_ms = (time.time() - start_time) * 1000
                
                if res_run:
                    print(f"  Rescheduling Run: Success! (ID: {res_run.rescheduling_run_id[:8]}...)")
                    print(f"  Objective Before: {res_run.objective_before:.1f} | Objective After: {res_run.objective_after:.1f}")
                    print(f"  Compute Time: {elapsed_ms:.1f} ms")
                else:
                    print("  Rescheduling Run: No actions needed / Nominal State")
                
                # Advance simulated clock by 5 minutes
                t0 += timedelta(minutes=5)
                iteration += 1
                
                print("Sleeping for 10 seconds before next telemetry update...")
                time.sleep(10)

        except KeyboardInterrupt:
            print("\nSimulation terminated. Shutting down cleanly.")

if __name__ == '__main__':
    run_simulation()
