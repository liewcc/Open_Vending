"""Buffer Stock — DB operations and suggestion calculation.

Commands:
  init        <data_db>                   Create buffer_stock + buffer_suggestions tables
  get         <data_db>                   Return all buffer settings as JSON
  set         <data_db>                   stdin: [{machine, lane_no, pid, normal_qty, sembreak_qty}, ...]
  suggest     <data_db> <sales_detail_db> Calculate suggestions, save to DB, return data
  get_suggest <data_db>                   Return saved suggestions from DB
"""
import sys, json, sqlite3
from pathlib import Path


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
    _migrate_suggestions_table(conn)
    conn.commit()
    conn.close()
    print(json.dumps({'ok': True}))


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


def cmd_suggest(data_db, sales_detail_db):
    """Calculate suggestions from sales history, save to buffer_suggestions, return data."""
    if not Path(sales_detail_db).exists():
        print(json.dumps({'ok': False, 'error': 'sales_detail.db not found'}))
        return

    # Calculate suggestions from sales
    sales_conn = sqlite3.connect(sales_detail_db)
    cur = sales_conn.cursor()
    cur.execute("""
        SELECT franchisename, pid,
               AVG(daily_cnt) AS avg_qty,
               MAX(daily_cnt) AS max_qty,
               MIN(daily_cnt) AS min_qty
        FROM (
            SELECT franchisename, pid, transdate, COUNT(*) AS daily_cnt
            FROM sales
            GROUP BY franchisename, pid, transdate
        )
        GROUP BY franchisename, pid
    """)
    suggestions = []
    data = {}
    for fname, pid, avg_qty, max_qty, min_qty in cur.fetchall():
        sug_normal   = max(0, round((max_qty or 0) - (avg_qty or 0)))
        sug_sembreak = min(0, round((min_qty or 0) - (avg_qty or 0)))
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

    # Save to buffer_suggestions in data_db
    conn = get_conn(data_db)
    _migrate_suggestions_table(conn)
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
            cmd_suggest(sys.argv[2], sys.argv[3])
        elif cmd == 'get_suggest':
            cmd_get_suggest(sys.argv[2])
        else:
            print(json.dumps({'ok': False, 'error': f'unknown command: {cmd}'}))
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))
