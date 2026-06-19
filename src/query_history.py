import sqlite3, json, sys
from pathlib import Path

DB = Path(__file__).parent.parent / "db" / "data.db"

if not DB.exists():
    print("[]"); sys.exit(0)

machine, lane = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(str(DB))

rows = conn.execute(
    "SELECT detected_at, old_restock, new_restock FROM change_log "
    "WHERE machine=? AND lane=? ORDER BY detected_at", (machine, lane)
).fetchall()
cur = conn.execute(
    "SELECT restock, updated_at FROM current_state WHERE machine=? AND lane=?",
    (machine, lane)
).fetchone()
conn.close()

pts = []
if rows:
    pts.append({"t": rows[0][0], "v": rows[0][1]})
    for r in rows:
        pts.append({"t": r[0], "v": r[2]})
elif cur:
    pts.append({"t": cur[1], "v": cur[0]})

print(json.dumps(pts))
