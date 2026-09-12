"""Build the forecast table from the daily_sales layer (both live in vending.db).

avg_qty = total qty for (machine, pid, weekday)
        / distinct dates of that weekday where the machine had ANY sale

daily_sales includes realtime estimates for dates after the last CSV
snapshot, so the forecast reflects the freshest data available.
"""
import sys
import json
import sqlite3
from datetime import datetime, date as date_cls


def build(detail_db, forecast_db):
    src = sqlite3.connect(detail_db)
    src.row_factory = sqlite3.Row

    # ── Step 1: count per (franchisename, pid, weekday) ──────────────────────
    # weekday: strftime('%w') → 0=Sun … 6=Sat, we remap to 0=Mon … 6=Sun.
    # Kept in SQL rather than a Python UDF: the UDF fired once per row over the
    # whole daily_sales table, which is too slow to run after every scan.
    WD = "(CAST(strftime('%w', sale_date) AS INTEGER) + 6) % 7"

    cur = src.cursor()
    cur.execute(f"""
        SELECT machine AS franchisename, pid, {WD} AS weekday, SUM(qty) AS cnt
        FROM daily_sales
        GROUP BY machine, pid, weekday
    """)
    counts = cur.fetchall()   # list of (franchisename, pid, weekday, cnt)

    # ── Step 2: active days per (machine, weekday) ───────────────────────────
    cur.execute(f"""
        SELECT machine AS franchisename, {WD} AS weekday, COUNT(DISTINCT sale_date) AS active_days
        FROM daily_sales
        GROUP BY machine, weekday
    """)
    active = {}
    for row in cur.fetchall():
        active[(row['franchisename'], row['weekday'])] = row['active_days']

    # ── Step 3: meta — actual data range of the derived layer ────────────────
    rng = cur.execute("SELECT MIN(sale_date), MAX(sale_date) FROM daily_sales").fetchone()
    src_meta = {'min_date': rng[0] or '', 'max_date': rng[1] or ''}
    src.close()

    # ── Step 4: write forecast DB ─────────────────────────────────────────────
    # Staged into _new tables and swapped in one transaction at the end. Writing
    # the live tables in place left them committed-but-empty for the duration of
    # the load, and a pick list rendered in that window silently showed no
    # forecast at all — the exact failure this table exists to avoid.
    dst = sqlite3.connect(forecast_db)
    dst.executescript("""
        DROP TABLE IF EXISTS forecast_new;
        DROP TABLE IF EXISTS forecast_meta_new;
        CREATE TABLE forecast_new (
            franchisename TEXT,
            pid           TEXT,
            weekday       INTEGER,
            avg_qty       REAL,
            PRIMARY KEY (franchisename, pid, weekday)
        );
        CREATE TABLE forecast_meta_new (
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
        "INSERT INTO forecast_new (franchisename, pid, weekday, avg_qty) VALUES (?,?,?,?)",
        rows_to_insert
    )

    dst.executemany("INSERT INTO forecast_meta_new (key, value) VALUES (?,?)", [
        ('built_at',        datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ('source_db',       detail_db),
        ('min_date',        src_meta.get('min_date', '')),
        ('max_date',        src_meta.get('max_date', '')),
        ('total_forecasts', str(len(rows_to_insert))),
    ])

    dst.commit()
    dst.executescript("""
        BEGIN;
        DROP TABLE IF EXISTS forecast;
        DROP TABLE IF EXISTS forecast_meta;
        ALTER TABLE forecast_new      RENAME TO forecast;
        ALTER TABLE forecast_meta_new RENAME TO forecast_meta;
        COMMIT;
    """)
    dst.close()

    return {
        'ok':              True,
        'total_forecasts': len(rows_to_insert),
        'min_date':        src_meta.get('min_date', ''),
        'max_date':        src_meta.get('max_date', ''),
    }


def read_meta(forecast_db):
    try:
        conn = sqlite3.connect(forecast_db)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM forecast_meta")
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
            print(json.dumps(build(sys.argv[1], sys.argv[2])))
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))
