"""Convert sales_detail CSV to sales_detail.db (raw exploded by PID)."""
import sys
import csv
import json
import sqlite3
from datetime import datetime


def _open_csv(path):
    try:
        f = open(path, newline='', encoding='utf-8-sig')
        f.read(1024)
        f.seek(0)
        return f
    except UnicodeDecodeError:
        return open(path, newline='', encoding='cp1252')


def build(csv_path, db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
        DROP TABLE IF EXISTS sales;
        DROP TABLE IF EXISTS meta;
        CREATE TABLE sales (
            transid       TEXT,
            franid        TEXT,
            franchisename TEXT,
            transdate     TEXT,
            pid           TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sales_main ON sales (franchisename, pid, transdate);
        CREATE TABLE meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    rows_to_insert = []
    min_date = None
    max_date = None
    total_transactions = 0
    total_rows = 0

    with _open_csv(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            transid       = row['transid'].strip()
            franid        = row['franid'].strip()
            franchisename = row['franchisename'].strip()
            transdate     = row['transdate'].strip()[:10]  # YYYY-MM-DD
            pids_raw      = row['productids']

            pids = [p.strip() for p in pids_raw.split(',') if p.strip().isdigit()]
            if not pids:
                continue

            total_transactions += 1
            if transdate:
                if min_date is None or transdate < min_date:
                    min_date = transdate
                if max_date is None or transdate > max_date:
                    max_date = transdate

            for pid in pids:
                rows_to_insert.append((transid, franid, franchisename, transdate, pid))
                total_rows += 1

            if len(rows_to_insert) >= 50000:
                cur.executemany(
                    "INSERT INTO sales (transid, franid, franchisename, transdate, pid) VALUES (?,?,?,?,?)",
                    rows_to_insert
                )
                rows_to_insert.clear()

    if rows_to_insert:
        cur.executemany(
            "INSERT INTO sales (transid, franid, franchisename, transdate, pid) VALUES (?,?,?,?,?)",
            rows_to_insert
        )

    cur.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [
        ('min_date',           min_date or ''),
        ('max_date',           max_date or ''),
        ('built_at',           datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ('source_file',        csv_path),
        ('total_transactions', str(total_transactions)),
        ('total_rows',         str(total_rows)),
    ])

    conn.commit()
    conn.close()

    print(json.dumps({
        'ok':                 True,
        'total_transactions': total_transactions,
        'total_rows':         total_rows,
        'min_date':           min_date or '',
        'max_date':           max_date or '',
    }))


def read_meta(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM meta")
        meta = dict(cur.fetchall())
        conn.close()
        meta['ok'] = True
        print(json.dumps(meta))
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}))


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'meta':
            read_meta(sys.argv[2])
        else:
            build(sys.argv[1], sys.argv[2])
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))
