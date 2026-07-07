import sqlite3, json, sys
from pathlib import Path

DB = Path(__file__).parent.parent / "db" / "vending.db"

def get_conn():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn

cmd = sys.argv[1] if len(sys.argv) > 1 else ''

if cmd == 'init':
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS picking_history (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        machine      TEXT    NOT NULL,
        lane_no      TEXT    NOT NULL,
        product_id   TEXT,
        product_name TEXT,
        picked_qty   INTEGER NOT NULL,
        out_of_stock INTEGER DEFAULT 0,
        pick_date    TEXT    NOT NULL,
        status       TEXT    DEFAULT 'pending',
        created_at   TEXT    DEFAULT (datetime('now')),
        cleared_at   TEXT,
        UNIQUE(machine, lane_no, pick_date)
    )""")
    conn.commit(); conn.close()
    print(json.dumps({"ok": True}))

elif cmd == 'auto-clear':
    conn = get_conn()
    cur = conn.execute(
        "UPDATE picking_history SET status='auto_cleared', cleared_at=datetime('now') "
        "WHERE status='pending' AND created_at < datetime('now', '-36 hours')"
    )
    conn.commit(); conn.close()
    print(json.dumps({"cleared": cur.rowcount}))

elif cmd == 'get-pending':
    if not DB.exists():
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT machine, lane_no, picked_qty FROM picking_history WHERE status='pending'"
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], {})[r['lane_no']] = r['picked_qty']
    print(json.dumps(result))

elif cmd == 'get-oos-counts':
    if not DB.exists():
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT machine, lane_no, COUNT(*) as cnt FROM picking_history "
        "WHERE out_of_stock=1 AND pick_date >= date('now', '-7 days') "
        "GROUP BY machine, lane_no"
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], {})[r['lane_no']] = r['cnt']
    print(json.dumps(result))

elif cmd == 'save-picks':
    picks = json.loads(sys.stdin.read())
    if not picks:
        print(json.dumps({"saved": 0})); sys.exit(0)
    conn = get_conn()
    saved = 0
    for p in picks:
        # Clear stale pending if product changed in this lane
        conn.execute(
            "DELETE FROM picking_history WHERE machine=? AND lane_no=? "
            "AND status='pending' AND product_id != ?",
            (p['machine'], p['lane_no'], p.get('product_id', ''))
        )
        conn.execute(
            "INSERT OR REPLACE INTO picking_history "
            "(machine, lane_no, product_id, product_name, picked_qty, out_of_stock, pick_date, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            (p['machine'], p['lane_no'], p.get('product_id',''), p.get('product_name',''),
             p['picked_qty'], p.get('out_of_stock', 0), p['pick_date'])
        )
        saved += 1
    conn.commit(); conn.close()
    print(json.dumps({"saved": saved}))

elif cmd == 'get-history-dates':
    if not DB.exists():
        print(json.dumps([])); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT pick_date FROM picking_history ORDER BY pick_date DESC"
    ).fetchall()
    conn.close()
    print(json.dumps([r['pick_date'] for r in rows]))

elif cmd == 'get-history-by-date':
    date = sys.argv[2] if len(sys.argv) > 2 else ''
    if not DB.exists() or not date:
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT machine, lane_no, product_id, product_name, picked_qty, out_of_stock, status "
        "FROM picking_history WHERE pick_date=? ORDER BY machine, CAST(lane_no AS INTEGER)",
        (date,)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], []).append({
            'lane_no': r['lane_no'],
            'product_id': r['product_id'],
            'product_name': r['product_name'],
            'picked_qty': r['picked_qty'],
            'out_of_stock': r['out_of_stock'],
            'status': r['status'],
        })
    print(json.dumps(result))

elif cmd == 'mark-done':
    machines = json.loads(sys.stdin.read())
    if not machines:
        print(json.dumps({"done": 0})); sys.exit(0)
    conn = get_conn()
    placeholders = ','.join('?' * len(machines))
    cur = conn.execute(
        f"UPDATE picking_history SET status='done', cleared_at=datetime('now') "
        f"WHERE machine IN ({placeholders}) AND status='pending'",
        machines
    )
    conn.commit(); conn.close()
    print(json.dumps({"done": cur.rowcount}))

else:
    print(json.dumps({"error": f"unknown command: {cmd}"}))
