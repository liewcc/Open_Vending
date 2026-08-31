import sqlite3, json, sys, os
from pathlib import Path

# Active account's folder, supplied by main.js; falls back to the legacy db/
DB = Path(os.environ.get("OV_DATA_DIR") or (Path(__file__).parent.parent / "db")) / "vending.db"

if not DB.exists():
    print("[]"); sys.exit(0)

machine, lane = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(str(DB))

rows = conn.execute(
    # GROUP BY detected_at keeps only the net (last) value per scan cycle,
    # collapsing twin-machine phantom A→B→A pairs at the same timestamp.
    "SELECT detected_at, old_restock, new_restock FROM change_log "
    "WHERE machine=? AND lane=? ORDER BY detected_at, id",
    (machine, lane)
).fetchall()
cur = conn.execute(
    "SELECT restock, updated_at FROM current_state WHERE machine=? AND lane=?",
    (machine, lane)
).fetchone()
conn.close()

# Collapse same-timestamp records: keep only the net final value per timestamp.
seen = {}
for detected_at, old_restock, new_restock in rows:
    if detected_at not in seen:
        seen[detected_at] = (old_restock, new_restock)
    else:
        seen[detected_at] = (seen[detected_at][0], new_restock)

pts = []
if seen:
    prev_v = None
    for t, (old_v, new_v) in sorted(seen.items()):
        # Skip no-op: net result same as net result of previous scan
        if new_v != prev_v:
            pts.append({"t": t, "v": new_v})
            prev_v = new_v
elif cur:
    pts.append({"t": cur[1], "v": cur[0]})

print(json.dumps(pts))
