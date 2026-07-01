"""Build sales_forecast.db from sales_detail.db.

avg_qty = total PID appearances for (franchisename, pid, weekday)
        / distinct dates of that weekday where franchisename had ANY sale
"""
import sys
import json
import sqlite3
from datetime import datetime, date as date_cls


def build(detail_db, forecast_db):
    src = sqlite3.connect(detail_db)
    src.row_factory = sqlite3.Row

    # ── Step 1: count per (franchisename, pid, weekday) ──────────────────────
    # weekday: strftime('%w') → 0=Sun … 6=Sat, we remap to 0=Mon … 6=Sun
    src.create_function('wd', 1, lambda d: (datetime.strptime(d, '%Y-%m-%d').weekday()))

    cur = src.cursor()
    cur.execute("""
        SELECT franchisename, pid, wd(transdate) AS weekday, COUNT(*) AS cnt
        FROM sales
        GROUP BY franchisename, pid, weekday
    """)
    counts = cur.fetchall()   # list of (franchisename, pid, weekday, cnt)

    # ── Step 2: active days per (franchisename, weekday) ─────────────────────
    cur.execute("""
        SELECT franchisename, wd(transdate) AS weekday, COUNT(DISTINCT transdate) AS active_days
        FROM sales
        GROUP BY franchisename, weekday
    """)
    active = {}
    for row in cur.fetchall():
        active[(row['franchisename'], row['weekday'])] = row['active_days']

    # ── Step 3: meta from source ──────────────────────────────────────────────
    cur.execute("SELECT key, value FROM meta")
    src_meta = dict(cur.fetchall())
    src.close()

    # ── Step 4: write forecast DB ─────────────────────────────────────────────
    dst = sqlite3.connect(forecast_db)
    dst.executescript("""
        DROP TABLE IF EXISTS forecast;
        DROP TABLE IF EXISTS meta;
        CREATE TABLE forecast (
            franchisename TEXT,
            pid           TEXT,
            weekday       INTEGER,
            avg_qty       REAL,
            PRIMARY KEY (franchisename, pid, weekday)
        );
        CREATE TABLE meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    rows_to_insert = []
    for row in counts:
        fname   = row['franchisename']
        pid     = row['pid']
        weekday = row['weekday']
        cnt     = row['cnt']
        days    = active.get((fname, weekday), 1)
        avg_qty = round(cnt / days, 4)
        rows_to_insert.append((fname, pid, weekday, avg_qty))

    dst.executemany(
        "INSERT INTO forecast (franchisename, pid, weekday, avg_qty) VALUES (?,?,?,?)",
        rows_to_insert
    )

    dst.executemany("INSERT INTO meta (key, value) VALUES (?,?)", [
        ('built_at',        datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ('source_db',       detail_db),
        ('min_date',        src_meta.get('min_date', '')),
        ('max_date',        src_meta.get('max_date', '')),
        ('total_forecasts', str(len(rows_to_insert))),
    ])

    dst.commit()
    dst.close()

    print(json.dumps({
        'ok':              True,
        'total_forecasts': len(rows_to_insert),
        'min_date':        src_meta.get('min_date', ''),
        'max_date':        src_meta.get('max_date', ''),
    }))


def read_meta(forecast_db):
    try:
        conn = sqlite3.connect(forecast_db)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM meta")
        meta = dict(cur.fetchall())
        conn.close()
        meta['ok'] = True
        print(json.dumps(meta))
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}))


def query_weekday(forecast_db, weekday):
    """Return {franchisename: {pid: avg_qty}} for a given weekday (0=Mon…6=Sun)."""
    try:
        conn = sqlite3.connect(forecast_db)
        cur = conn.cursor()
        cur.execute(
            "SELECT franchisename, pid, avg_qty FROM forecast WHERE weekday = ?",
            (int(weekday),)
        )
        result = {}
        for fname, pid, avg_qty in cur.fetchall():
            if fname not in result:
                result[fname] = {}
            result[fname][pid] = avg_qty
        conn.close()
        print(json.dumps({'ok': True, 'data': result}))
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}))


if __name__ == '__main__':
    try:
        cmd = sys.argv[1]
        if cmd == 'meta':
            read_meta(sys.argv[2])
        elif cmd == 'query':
            query_weekday(sys.argv[2], sys.argv[3])
        else:
            build(sys.argv[1], sys.argv[2])
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))
