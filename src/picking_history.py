import sqlite3, json, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))  # bundled python is embeddable: script dir is not on sys.path
import remote_db

# Active account's folder, supplied by main.js; falls back to the legacy db/
DB = Path(os.environ.get("OV_DATA_DIR") or (Path(__file__).parent.parent / "db")) / "vending.db"

# picking_history is shared between PCs, so it lives in the hosted DB when one
# is configured. Unconfigured, this is the local file exactly as before.
def get_conn():
    return remote_db.connect(DB)

# A write that never reached the shared DB must not look like it succeeded —
# there is no offline queue by design, so the UI has to be told.
def _report_remote_failure(exc_type, exc, tb):
    if isinstance(exc, remote_db.RemoteError):
        print(json.dumps({"ok": False, "error": str(exc)}))
    else:
        sys.__excepthook__(exc_type, exc, tb)

sys.excepthook = _report_remote_failure

# The hosted DB holds every account's picks in one table, so every statement
# below is scoped to the active account — without it a second profile with the
# same machine name would collide on UNIQUE(machine, lane_no, pick_date).
ACCOUNT = remote_db.ACCOUNT

DDL = """CREATE TABLE IF NOT EXISTS picking_history (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        account      TEXT    NOT NULL DEFAULT 'dvends',
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
        UNIQUE(account, machine, lane_no, pick_date)
    )"""
COLS = ["id", "machine", "lane_no", "product_id", "product_name", "picked_qty",
        "out_of_stock", "pick_date", "status", "created_at", "cleared_at"]

cmd = sys.argv[1] if len(sys.argv) > 1 else ''

if cmd == 'init':
    conn = get_conn()
    conn.execute(DDL)
    conn.commit()
    remote_db.ensure_account_column(conn, "picking_history", DDL, COLS)
    conn.close()
    print(json.dumps({"ok": True}))

elif cmd == 'auto-clear':
    conn = get_conn()
    cur = conn.execute(
        "UPDATE picking_history SET status='auto_cleared', cleared_at=datetime('now') "
        "WHERE status='pending' AND created_at < datetime('now', '-36 hours') "
        "AND account=?", (ACCOUNT,)
    )
    conn.commit(); conn.close()
    print(json.dumps({"cleared": cur.rowcount}))

elif cmd == 'get-pending':
    if not (remote_db.enabled() or DB.exists()):
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT machine, lane_no, picked_qty FROM picking_history "
        "WHERE status='pending' AND account=?", (ACCOUNT,)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], {})[r['lane_no']] = r['picked_qty']
    print(json.dumps(result))

elif cmd == 'get-pending-detail':
    # Full pending rows (incl. product names as saved at queue/edit time) so
    # queue exports render exactly what is in the queue, not the raw report.
    if not (remote_db.enabled() or DB.exists()):
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT machine, lane_no, product_id, product_name, picked_qty "
        "FROM picking_history WHERE status='pending' AND account=? "
        "ORDER BY machine, CAST(lane_no AS INTEGER)", (ACCOUNT,)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], []).append({
            'lane_no': r['lane_no'],
            'product_id': r['product_id'],
            'product_name': r['product_name'],
            'picked_qty': r['picked_qty'],
        })
    print(json.dumps(result))

elif cmd == 'get-oos-counts':
    if not (remote_db.enabled() or DB.exists()):
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT machine, lane_no, COUNT(*) as cnt FROM picking_history "
        "WHERE out_of_stock=1 AND pick_date >= date('now', '-7 days') AND account=? "
        "GROUP BY machine, lane_no", (ACCOUNT,)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], {})[r['lane_no']] = r['cnt']
    print(json.dumps(result))

elif cmd == 'save-picks':
    # Payload is either a plain list of picks (legacy) or a dict
    # {picks: [...], replace_machines: [...]}: replace_machines' pending rows
    # are wiped first so the queue mirrors the caller's row set exactly
    # (lanes edited down to restock 0 leave the queue).
    data = json.loads(sys.stdin.read())
    if isinstance(data, dict):
        picks = data.get('picks') or []
        replace_machines = data.get('replace_machines') or []
    else:
        picks = data or []
        replace_machines = []
    if not picks and not replace_machines:
        print(json.dumps({"saved": 0})); sys.exit(0)
    conn = get_conn()
    if replace_machines:
        placeholders = ','.join('?' * len(replace_machines))
        conn.execute(
            f"DELETE FROM picking_history WHERE machine IN ({placeholders}) "
            f"AND status='pending' AND account=?",
            replace_machines + [ACCOUNT]
        )
    saved = 0
    for p in picks:
        # Clear stale pending if product changed in this lane
        conn.execute(
            "DELETE FROM picking_history WHERE machine=? AND lane_no=? "
            "AND status='pending' AND product_id != ? AND account=?",
            (p['machine'], p['lane_no'], p.get('product_id', ''), ACCOUNT)
        )
        conn.execute(
            "INSERT OR REPLACE INTO picking_history "
            "(account, machine, lane_no, product_id, product_name, picked_qty, out_of_stock, pick_date, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (ACCOUNT, p['machine'], p['lane_no'], p.get('product_id',''), p.get('product_name',''),
             p['picked_qty'], p.get('out_of_stock', 0), p['pick_date'])
        )
        saved += 1
    conn.commit(); conn.close()
    print(json.dumps({"saved": saved}))

elif cmd == 'get-history-dates':
    if not (remote_db.enabled() or DB.exists()):
        print(json.dumps([])); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT pick_date FROM picking_history WHERE account=? "
        "ORDER BY pick_date DESC", (ACCOUNT,)
    ).fetchall()
    conn.close()
    print(json.dumps([r['pick_date'] for r in rows]))

elif cmd == 'get-history-by-date':
    date = sys.argv[2] if len(sys.argv) > 2 else ''
    if not (remote_db.enabled() or DB.exists()) or not date:
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT machine, lane_no, product_id, product_name, picked_qty, out_of_stock, status "
        "FROM picking_history WHERE pick_date=? AND account=? "
        "ORDER BY machine, CAST(lane_no AS INTEGER)",
        (date, ACCOUNT)
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

elif cmd == 'get-week-summary':
    # {machine: [pick_date, ...]} within [from, to]. Any status counts:
    # a row means "a list was made" (auto_cleared/done rows are UPDATEd,
    # never deleted; wholesale re-queue within 36h can drop an earlier
    # day's pending row — accepted, rare).
    d_from = sys.argv[2] if len(sys.argv) > 2 else ''
    d_to   = sys.argv[3] if len(sys.argv) > 3 else ''
    if not (remote_db.enabled() or DB.exists()) or not d_from or not d_to:
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT machine, pick_date FROM picking_history "
        "WHERE pick_date BETWEEN ? AND ? AND account=? ORDER BY machine, pick_date",
        (d_from, d_to, ACCOUNT)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], []).append(r['pick_date'])
    print(json.dumps(result))

elif cmd == 'mark-done':
    machines = json.loads(sys.stdin.read())
    if not machines:
        print(json.dumps({"done": 0})); sys.exit(0)
    conn = get_conn()
    placeholders = ','.join('?' * len(machines))
    cur = conn.execute(
        f"UPDATE picking_history SET status='done', cleared_at=datetime('now') "
        f"WHERE machine IN ({placeholders}) AND status='pending' AND account=?",
        machines + [ACCOUNT]
    )
    conn.commit(); conn.close()
    print(json.dumps({"done": cur.rowcount}))

else:
    print(json.dumps({"error": f"unknown command: {cmd}"}))
