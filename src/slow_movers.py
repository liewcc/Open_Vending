"""Slow-movers analysis: rank active products by total sales ascending."""
import sys
import csv
import json
import sqlite3
from datetime import datetime, date


def _open_csv(path):
    """Open a CSV file, trying utf-8-sig first then cp1252 as fallback."""
    try:
        f = open(path, newline='', encoding='utf-8-sig')
        f.read(1024)
        f.seek(0)
        return f
    except UnicodeDecodeError:
        return open(path, newline='', encoding='cp1252')


def is_inactive(name):
    """Products prefixed with zzz/ZXXX/xxxx etc. are already discontinued."""
    first = name.strip().split()[0].lower() if name.strip() else ''
    return len(first) >= 2 and all(c in 'zx' for c in first)


def build_db(product_csv, sales_csv, db_path):
    # Load active products (skip discontinued and system/test entries)
    products = {}
    with _open_csv(product_csv) as f:
        for row in csv.DictReader(f):
            pid  = row['PID'].strip()
            name = row['Product Name'].strip()
            if is_inactive(name):
                continue
            products[pid] = name

    # Open DB
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS products")
    cursor.execute("DROP TABLE IF EXISTS sales")
    cursor.execute("DROP TABLE IF EXISTS meta")
    cursor.execute("CREATE TABLE products(pid TEXT PRIMARY KEY, name TEXT)")
    cursor.execute("CREATE TABLE sales(transdate TEXT, pid TEXT)")
    cursor.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")

    # Insert products
    cursor.executemany("INSERT INTO products(pid, name) VALUES (?, ?)", products.items())

    # Load sales and track min/max dates
    min_date = None
    max_date = None
    sales_to_insert = []
    with _open_csv(sales_csv) as f:
        for row in csv.DictReader(f):
            date_str = row['transdate'].strip()[:10]  # YYYY-MM-DD
            if date_str:
                if min_date is None or date_str < min_date:
                    min_date = date_str
                if max_date is None or date_str > max_date:
                    max_date = date_str
            pids = [p.strip() for p in row['productids'].split(',') if p.strip().isdigit()]
            for pid in pids:
                if pid in products:
                    sales_to_insert.append((date_str, pid))

    if sales_to_insert:
        cursor.executemany("INSERT INTO sales(transdate, pid) VALUES (?, ?)", sales_to_insert)

    cursor.execute("INSERT INTO meta(key, value) VALUES ('min_date', ?)", (min_date or '',))
    cursor.execute("INSERT INTO meta(key, value) VALUES ('max_date', ?)", (max_date or '',))

    conn.commit()
    conn.close()

    print(json.dumps({'ok': True, 'total_active': len(products)}))


def analyze_db(db_path, top_n):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.pid, p.name, COUNT(s.pid), MAX(s.transdate)
        FROM products p
        LEFT JOIN sales s ON p.pid = s.pid
        GROUP BY p.pid, p.name
    """)
    rows_db = cursor.fetchall()

    today = date.today()
    rows = []
    for pid, name, total, last in rows_db:
        try:
            days = (today - datetime.strptime(last[:10], '%Y-%m-%d').date()).days if last else None
        except (ValueError, TypeError):
            days = None
        rows.append({
            'pid':       pid,
            'name':      name,
            'total':     total,
            'last_sale': last or '',
            'days':      days,
        })

    # Sort: fewest sales first; among ties, longest since last sale (None = never sold = worst)
    rows.sort(key=lambda r: (r['total'], -(r['days'] if r['days'] is not None else 9999)))

    cursor.execute("SELECT value FROM meta WHERE key = 'min_date'")
    res_min = cursor.fetchone()
    min_date = res_min[0] if res_min else ''

    cursor.execute("SELECT value FROM meta WHERE key = 'max_date'")
    res_max = cursor.fetchone()
    max_date = res_max[0] if res_max else ''

    conn.close()

    print(json.dumps({
        'ok':          True,
        'rows':        rows,
        'total_active': len(rows),
        'date_range':  f'{min_date} to {max_date}',
    }))


def analyze_machine(sales_detail_db, machine):
    """Per-machine slow/fast mover ranking, all-time (no window), from daily_sales.

    Unlike analyze_db() (global, uses the separate slow_movers.db built from
    product.csv + a sales CSV), this reads the unified daily_sales layer in
    vending.db — same source Q3's replacement suggestions use. It includes
    realtime estimates, so last_sale stays current between CSV imports. The
    picking-list report supplies which products are currently stocked on the
    machine; this only supplies sales counts.
    """
    from pathlib import Path
    if not Path(sales_detail_db).exists():
        print(json.dumps({'ok': False, 'error': 'vending.db not found — build it in Settings first'}))
        return

    conn = sqlite3.connect(sales_detail_db)
    db_rows = conn.execute(
        "SELECT pid, SUM(qty), MAX(sale_date) FROM daily_sales WHERE machine=? GROUP BY pid",
        (machine,),
    ).fetchall()
    conn.close()

    today = date.today()
    rows = {}
    for pid, total, last in db_rows:
        try:
            days = (today - datetime.strptime(last[:10], '%Y-%m-%d').date()).days if last else None
        except (ValueError, TypeError):
            days = None
        rows[pid] = {'total': total, 'last_sale': (last or '')[:10], 'days': days}

    print(json.dumps({'ok': True, 'rows': rows}))


def main():
    product_csv = sys.argv[1]
    sales_csv   = sys.argv[2]
    top_n       = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    # Load active products (skip discontinued and system/test entries)
    products = {}
    with _open_csv(product_csv) as f:
        for row in csv.DictReader(f):
            pid  = row['PID'].strip()
            name = row['Product Name'].strip()
            if is_inactive(name):
                continue
            products[pid] = name

    # Count sales and track last sale date per active product
    counts    = {pid: 0    for pid in products}
    last_sale = {pid: None for pid in products}

    with _open_csv(sales_csv) as f:
        for row in csv.DictReader(f):
            date_str = row['transdate'].strip()[:10]  # YYYY-MM-DD
            pids = [p.strip() for p in row['productids'].split(',') if p.strip().isdigit()]
            for pid in pids:
                if pid in counts:
                    counts[pid] += 1
                    if last_sale[pid] is None or date_str > last_sale[pid]:
                        last_sale[pid] = date_str

    # Build result rows
    today = date.today()
    rows = []
    for pid, name in products.items():
        total = counts[pid]
        last  = last_sale[pid]
        try:
            days = (today - datetime.strptime(last[:10], '%Y-%m-%d').date()).days if last else None
        except (ValueError, TypeError):
            days = None
        rows.append({
            'pid':       pid,
            'name':      name,
            'total':     total,
            'last_sale': last or '',
            'days':      days,
        })

    # Sort: fewest sales first; among ties, longest since last sale (None = never sold = worst)
    rows.sort(key=lambda r: (r['total'], -(r['days'] if r['days'] is not None else 9999)))

    # Derive date range from sales file for display
    min_date = max_date = ''
    with _open_csv(sales_csv) as f:
        for row in csv.DictReader(f):
            d = row['transdate'].strip()[:10]
            if not min_date or d < min_date:
                min_date = d
            if not max_date or d > max_date:
                max_date = d

    print(json.dumps({
        'ok':          True,
        'rows':        rows,
        'total_active': len(rows),
        'date_range':  f'{min_date} to {max_date}',
    }))


if __name__ == '__main__':
    try:
        if len(sys.argv) > 1 and sys.argv[1] == 'build':
            build_db(sys.argv[2], sys.argv[3], sys.argv[4])
        elif len(sys.argv) > 1 and sys.argv[1] == 'analyze':
            analyze_db(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20)
        elif len(sys.argv) > 1 and sys.argv[1] == 'machine':
            analyze_machine(sys.argv[2], sys.argv[3])
        else:
            main()
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))

