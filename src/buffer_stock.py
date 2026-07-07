"""Buffer Stock — DB operations and suggestion calculation.

Commands:
  init        <data_db>                   Create buffer_stock + buffer_suggestions tables
  get         <data_db>                   Return all buffer settings as JSON
  set         <data_db>                   stdin: [{machine, lane_no, pid, normal_qty, sembreak_qty}, ...]
  suggest     <data_db> <sales_detail_db> [lead_days] [sembreak_factor] [min_oos]
                                          Calculate suggestions, save to DB, return data
  get_suggest <data_db>                   Return saved suggestions from DB
  get_lane_types <data_db>               Return {pid: lane_type} dict from product_lane_type table
"""
import sys, json, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

WINDOW_DAYS = 30  # sales window for the daily average, anchored to newest sale_date


def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_suggestions_table(conn):
    """Create or migrate buffer_suggestions to two-column schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buffer_suggestions (
            machine                 TEXT NOT NULL,
            pid                     TEXT NOT NULL,
            suggestion_normal_qty   INTEGER DEFAULT 0,
            suggestion_sembreak_qty INTEGER DEFAULT 0,
            PRIMARY KEY (machine, pid)
        )
    """)
    # Migrate old single-column schema if needed
    cols = {r[1] for r in conn.execute("PRAGMA table_info(buffer_suggestions)")}
    if 'suggestion_normal_qty' not in cols:
        conn.execute("ALTER TABLE buffer_suggestions ADD COLUMN suggestion_normal_qty INTEGER DEFAULT 0")
    if 'suggestion_sembreak_qty' not in cols:
        conn.execute("ALTER TABLE buffer_suggestions ADD COLUMN suggestion_sembreak_qty INTEGER DEFAULT 0")


def cmd_init(db_path):
    conn = get_conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buffer_stock (
            machine      TEXT NOT NULL,
            lane_no      TEXT NOT NULL,
            pid          TEXT,
            normal_qty   INTEGER DEFAULT 0,
            sembreak_qty INTEGER DEFAULT 0,
            PRIMARY KEY (machine, lane_no)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_lane_type (
            pid          TEXT PRIMARY KEY,
            lane_type    TEXT CHECK(lane_type IN ('cold', 'ambient', 'unknown')),
            product_name TEXT,
            source       TEXT
        )
    """)
    _migrate_suggestions_table(conn)
    conn.commit()
    conn.close()
    print(json.dumps({'ok': True}))


def cmd_get_lane_types(db_path):
    """Return {pid: lane_type} for all classified products."""
    if not Path(db_path).exists():
        print(json.dumps({'ok': True, 'data': {}}))
        return
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT pid, lane_type, product_name FROM product_lane_type"
        ).fetchall()
    except Exception:
        print(json.dumps({'ok': True, 'data': {}}))
        conn.close()
        return
    conn.close()
    data = {r['pid']: {'type': r['lane_type'], 'name': r['product_name'] or ''} for r in rows}
    print(json.dumps({'ok': True, 'data': data}))


def cmd_get(db_path):
    if not Path(db_path).exists():
        print(json.dumps({'ok': True, 'data': {}}))
        return
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            'SELECT machine, lane_no, pid, normal_qty, sembreak_qty FROM buffer_stock'
        ).fetchall()
    except Exception:
        print(json.dumps({'ok': True, 'data': {}}))
        conn.close()
        return
    conn.close()
    data = {}
    for r in rows:
        data.setdefault(r['machine'], {})[r['lane_no']] = {
            'pid': r['pid'] or '',
            'normal_qty': r['normal_qty'] or 0,
            'sembreak_qty': r['sembreak_qty'] or 0,
        }
    print(json.dumps({'ok': True, 'data': data}))


def cmd_set(db_path):
    rows = json.loads(sys.stdin.read())
    if not rows:
        print(json.dumps({'ok': True, 'saved': 0}))
        return
    conn = get_conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buffer_stock (
            machine TEXT NOT NULL, lane_no TEXT NOT NULL, pid TEXT,
            normal_qty INTEGER DEFAULT 0, sembreak_qty INTEGER DEFAULT 0,
            PRIMARY KEY (machine, lane_no)
        )
    """)
    conn.executemany(
        """INSERT INTO buffer_stock (machine, lane_no, pid, normal_qty, sembreak_qty)
           VALUES (:machine, :lane_no, :pid, :normal_qty, :sembreak_qty)
           ON CONFLICT(machine, lane_no) DO UPDATE SET
             pid=excluded.pid,
             normal_qty=excluded.normal_qty,
             sembreak_qty=excluded.sembreak_qty""",
        rows
    )
    conn.commit()
    conn.close()
    print(json.dumps({'ok': True, 'saved': len(rows)}))


def cmd_suggest(data_db, sales_detail_db, lead_days=1.0, sembreak_factor=0.5, min_oos=2):
    """Calculate suggestions from sales history, save to buffer_suggestions, return data.

    The buffer covers units sold between picking (data export) and refill:
      suggestion = true daily average x lead_days, rounded half-up,
      then split across the lanes carrying that pid (ceil division —
      buffer_suggestions has no lane dimension, so every lane of the pid
      gets the same per-lane share).
    True daily average = total qty in the last WINDOW_DAYS / WINDOW_DAYS, so
    zero-sales days count toward the denominator. The window is anchored to
    the newest sale_date in daily_sales (which includes realtime estimates
    from restock scans, so it stays current between CSV imports), not today.
    Sem-break demand is assumed to be sembreak_factor of normal demand.

    A pid only gets a suggestion if it sold out (picking_history.out_of_stock)
    at least min_oos times inside the window — lanes that never run dry are
    already covered by the restock qty itself. While pick history is thinner
    than min_oos picks for a pid, the threshold drops to the pick count, so a
    pid that sold out on its only recorded pick still qualifies.
    """
    if not Path(sales_detail_db).exists():
        print(json.dumps({'ok': False, 'error': 'vending.db not found'}))
        return

    # Calculate suggestions from the unified daily_sales layer
    sales_conn = sqlite3.connect(sales_detail_db)
    cur = sales_conn.cursor()
    newest = cur.execute("SELECT MAX(sale_date) FROM daily_sales").fetchone()[0]
    if not newest:
        sales_conn.close()
        print(json.dumps({'ok': False, 'error': 'no sales data — rebuild daily_sales first'}))
        return
    end = datetime.strptime(newest[:10], '%Y-%m-%d').date()
    start = (end - timedelta(days=WINDOW_DAYS - 1)).isoformat()

    # machine name canonicalization (Excel 31-char sheet truncation) —
    # current_state/picking_history use sheet names, daily_sales uses canonical
    def read_grouped(sql):
        out = {}
        try:
            for m, pid, cnt in cur.execute(sql, (start,)):
                key = (alias.get(m, m), pid)
                out[key] = out.get(key, 0) + (cnt or 0)
        except sqlite3.OperationalError:
            pass  # table missing (fresh DB) — leave empty
        return out

    try:
        alias = dict(cur.execute(
            "SELECT sheet_alias, canonical FROM machines WHERE sheet_alias IS NOT NULL"
        ).fetchall())
    except sqlite3.OperationalError:
        alias = {}

    # lanes per (machine, pid) — current_state rows are never deleted, so only
    # count lanes still updated inside the window (a lane with no bal/restock
    # change all window had zero sales and doesn't need a buffer share anyway)
    lane_counts = read_grouped(
        "SELECT machine, pid, COUNT(*) FROM current_state "
        "WHERE pid IS NOT NULL AND updated_at >= ? GROUP BY machine, pid"
    )
    # sell-out count and pick count per (machine, pid) inside the window
    oos_counts = read_grouped(
        "SELECT machine, product_id, SUM(out_of_stock) FROM picking_history "
        "WHERE pick_date >= ? GROUP BY machine, product_id"
    )
    pick_counts = read_grouped(
        "SELECT machine, product_id, COUNT(*) FROM picking_history "
        "WHERE pick_date >= ? GROUP BY machine, product_id"
    )

    cur.execute("""
        SELECT machine, pid, SUM(qty) AS total_qty
        FROM daily_sales
        WHERE sale_date >= ?
        GROUP BY machine, pid
    """, (start,))
    suggestions = []
    data = {}
    for fname, pid, total_qty in cur.fetchall():
        picks = pick_counts.get((fname, pid), 0)
        eff_min = min(min_oos, picks) if picks else min_oos
        if oos_counts.get((fname, pid), 0) < eff_min:
            sug_normal = sug_sembreak = 0
        else:
            avg_daily = (total_qty or 0) / WINDOW_DAYS
            lanes = lane_counts.get((fname, pid)) or 1
            # per-pid suggestion rounded half-up, then ceil-divided per lane
            sug_normal   = -(-int(avg_daily * lead_days + 0.5) // lanes)
            sug_sembreak = -(-int(avg_daily * lead_days * sembreak_factor + 0.5) // lanes)
        data.setdefault(fname, {})[pid] = {
            'normal': sug_normal,
            'sembreak': sug_sembreak
        }
        suggestions.append({
            'machine': fname, 'pid': pid,
            'suggestion_normal_qty': sug_normal,
            'suggestion_sembreak_qty': sug_sembreak
        })
    sales_conn.close()

    # Save to buffer_suggestions in data_db (full refresh — stale rows for
    # products with no sales in the window must not survive a recalc)
    conn = get_conn(data_db)
    _migrate_suggestions_table(conn)
    conn.execute("DELETE FROM buffer_suggestions")
    conn.executemany(
        """INSERT INTO buffer_suggestions (machine, pid, suggestion_normal_qty, suggestion_sembreak_qty)
           VALUES (:machine, :pid, :suggestion_normal_qty, :suggestion_sembreak_qty)
           ON CONFLICT(machine, pid) DO UPDATE SET
             suggestion_normal_qty=excluded.suggestion_normal_qty,
             suggestion_sembreak_qty=excluded.suggestion_sembreak_qty""",
        suggestions
    )
    conn.commit()
    conn.close()

    print(json.dumps({'ok': True, 'data': data, 'saved': len(suggestions)}))


def cmd_get_suggest(db_path):
    """Return saved suggestions from buffer_suggestions table."""
    if not Path(db_path).exists():
        print(json.dumps({'ok': True, 'data': {}}))
        return
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            'SELECT machine, pid, suggestion_normal_qty, suggestion_sembreak_qty FROM buffer_suggestions'
        ).fetchall()
    except Exception:
        print(json.dumps({'ok': True, 'data': {}}))
        conn.close()
        return
    conn.close()
    data = {}
    for r in rows:
        data.setdefault(r['machine'], {})[r['pid']] = {
            'normal': r['suggestion_normal_qty'] or 0,
            'sembreak': r['suggestion_sembreak_qty'] or 0
        }
    print(json.dumps({'ok': True, 'data': data}))


if __name__ == '__main__':
    try:
        cmd = sys.argv[1]
        if cmd == 'init':
            cmd_init(sys.argv[2])
        elif cmd == 'get':
            cmd_get(sys.argv[2])
        elif cmd == 'set':
            cmd_set(sys.argv[2])
        elif cmd == 'suggest':
            lead = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
            factor = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
            min_oos = int(sys.argv[6]) if len(sys.argv) > 6 else 2
            cmd_suggest(sys.argv[2], sys.argv[3], lead, factor, min_oos)
        elif cmd == 'get_suggest':
            cmd_get_suggest(sys.argv[2])
        elif cmd == 'get_lane_types':
            cmd_get_lane_types(sys.argv[2])
        else:
            print(json.dumps({'ok': False, 'error': f'unknown command: {cmd}'}))
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))
