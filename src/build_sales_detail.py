"""Import the sales_detail CSV into the sales table (raw exploded by PID).

Incremental merge into the unified vending.db: rows are staged, then the
CSV's date range is deleted from `sales` and replaced — so a partial
export (e.g. just the last month) tops up history without losing older
data, and re-importing an overlapping range never duplicates rows.
Everything runs in one transaction; a failed import leaves `sales` as it
was. After the merge the derived daily_sales table is rebuilt, which
replaces realtime estimates with authoritative data for the covered dates.

After a successful import the source CSV is gzip-archived into db/archive/
so the raw transaction history can always be rebuilt even if the DB and
its backups are lost.
"""
import sys
import csv
import gzip
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


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
        CREATE TABLE IF NOT EXISTS sales (
            transid       TEXT,
            franid        TEXT,
            franchisename TEXT,
            transdate     TEXT,
            pid           TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sales_main ON sales (franchisename, pid, transdate);
        CREATE TABLE IF NOT EXISTS sales_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TEMP TABLE staging (
            transid       TEXT,
            franid        TEXT,
            franchisename TEXT,
            transdate     TEXT,
            pid           TEXT
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
                    "INSERT INTO staging (transid, franid, franchisename, transdate, pid) VALUES (?,?,?,?,?)",
                    rows_to_insert
                )
                rows_to_insert.clear()

    if rows_to_insert:
        cur.executemany(
            "INSERT INTO staging (transid, franid, franchisename, transdate, pid) VALUES (?,?,?,?,?)",
            rows_to_insert
        )

    if not min_date:
        conn.close()
        print(json.dumps({'ok': False, 'error': 'CSV contains no usable rows'}))
        return

    # Incremental merge: replace the CSV's date range, keep everything else
    cur.execute("DELETE FROM sales WHERE transdate >= ? AND transdate <= ?", (min_date, max_date))
    replaced = cur.rowcount
    cur.execute("INSERT INTO sales SELECT transid, franid, franchisename, transdate, pid FROM staging")
    cur.execute("DROP TABLE staging")

    # Meta reflects the merged table, not just this import
    db_min, db_max, db_rows = cur.execute(
        "SELECT MIN(transdate), MAX(transdate), COUNT(*) FROM sales"
    ).fetchone()
    db_trans = cur.execute("SELECT COUNT(DISTINCT transid) FROM sales").fetchone()[0]
    cur.executemany("INSERT OR REPLACE INTO sales_meta (key, value) VALUES (?, ?)", [
        ('min_date',           db_min or ''),
        ('max_date',           db_max or ''),
        ('built_at',           datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ('source_file',        csv_path),
        ('total_transactions', str(db_trans)),
        ('total_rows',         str(db_rows)),
        ('last_import_range',  f'{min_date}..{max_date}'),
        ('last_import_rows',   str(total_rows)),
    ])

    # Reconcile the derived layer: authoritative rows replace estimates
    import daily_sales
    ds_stats = daily_sales.rebuild(conn)

    conn.commit()
    conn.close()

    # Archive the source CSV (gzip) so raw history is rebuildable from disk
    archived = ''
    try:
        archive_dir = Path(db_path).parent / 'archive'
        archive_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest = archive_dir / f'sales_detail_{stamp}.csv.gz'
        with open(csv_path, 'rb') as src, gzip.open(dest, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        archived = str(dest)
    except Exception:
        pass  # archiving must never fail the import itself

    print(json.dumps({
        'ok':                 True,
        'total_transactions': db_trans,
        'total_rows':         db_rows,
        'min_date':           db_min or '',
        'max_date':           db_max or '',
        'import_range':       f'{min_date}..{max_date}',
        'import_rows':        total_rows,
        'replaced_rows':      replaced,
        'daily_sales':        ds_stats,
        'archived_csv':       archived,
    }))


def read_meta(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM sales_meta")
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
