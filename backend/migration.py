import sys
import os
import psycopg2

def run_migration():
    conn = psycopg2.connect('postgresql://postgres:201810@localhost:5432/rail_digital_twin')
    cur = conn.cursor()
    
    print("Altering table public.stations...")
    cur.execute("ALTER TABLE public.stations ADD COLUMN IF NOT EXISTS state VARCHAR(60);")
    cur.execute("ALTER TABLE public.stations ADD COLUMN IF NOT EXISTS division VARCHAR(30);")
    cur.execute("ALTER TABLE public.stations ADD COLUMN IF NOT EXISTS zone VARCHAR(30);")
    cur.execute("ALTER TABLE public.stations ADD COLUMN IF NOT EXISTS category VARCHAR(20);")
    cur.execute("ALTER TABLE public.stations ADD COLUMN IF NOT EXISTS layer VARCHAR(20) DEFAULT 'corridor';")
    conn.commit()
    print("Table altered successfully.")
    
    # Add parent to path to import stations_seed
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    try:
        from data.stations_seed import CORRIDOR_STATIONS, HUB_STATIONS
        print(f"Loaded {len(CORRIDOR_STATIONS)} corridor stations and {len(HUB_STATIONS)} hub stations from seed.")
    except Exception as e:
        print("Failed to import stations_seed:", e)
        return
        
    print("Backfilling metadata...")
    updated_count = 0
    
    for row in CORRIDOR_STATIONS:
        if len(row) >= 6:
            node_id, alias_code, name, state, division, zone = row[:6]
            category = row[6] if len(row) > 6 else "Standard"
            cur.execute(
                "UPDATE public.stations SET state = %s, division = %s, zone = %s, category = %s, layer = 'corridor' WHERE station_code = %s",
                (state, division, zone, category, alias_code)
            )
            updated_count += cur.rowcount
            
    for row in HUB_STATIONS:
        if len(row) >= 4:
            node_id, alias_code, name, state = row[:4]
            cur.execute(
                "UPDATE public.stations SET state = %s, division = 'HQ', zone = 'HQ', category = 'Hub', layer = 'hub' WHERE station_code = %s",
                (state, alias_code)
            )
            updated_count += cur.rowcount
            
    conn.commit()
    print(f"Migration complete! Updated {updated_count} station records.")
    
    cur.close()
    conn.close()

if __name__ == '__main__':
    run_migration()
