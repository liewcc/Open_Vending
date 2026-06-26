"""Slow-movers analysis: rank active products by total sales ascending."""
import sys
import csv
import json
import sqlite3
from datetime import datetime, date


def is_inactive(name):
    """Products prefixed with zzz/ZXXX/xxxx etc. are already discontinued."""
    first = name.strip().split()[0].lower() if name.strip() else ''
    return len(first) >= 2 and all(c in 'zx' for c in first)


def build_db(product_csv, sales_csv, db_path):
    # Load active products (skip discontinued and system/test entries)
    products = {}
    with open(product_csv, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            pid  = row['PID'].strip()
            name = row['name'].strip()
            if is_inactive(name):
                continue
            try:
                price = float(row['price'])
            except (ValueError, KeyError):
                price = 0
            if price < 0.05:
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
    with open(sales_csv, newline='', encoding='utf-8-sig') as f:
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
        days = (today - datetime.strptime(last, '%Y-%m-%d').date()).days if last else None
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
        'rows':        rows[:top_n],
        'total_active': len(rows),
        'date_range':  f'{min_date} to {max_date}',
    }))


def main():
    product_csv = sys.argv[1]
    sales_csv   = sys.argv[2]
    top_n       = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    # Load active products (skip discontinued and system/test entries)
    products = {}
    with open(product_csv, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            pid  = row['PID'].strip()
            name = row['name'].strip()
            if is_inactive(name):
                continue
            try:
                price = float(row['price'])
            except (ValueError, KeyError):
                price = 0
            if price < 0.05:
                continue
            products[pid] = name

    # Count sales and track last sale date per active product
    counts    = {pid: 0    for pid in products}
    last_sale = {pid: None for pid in products}

    with open(sales_csv, newline='', encoding='utf-8-sig') as f:
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
        days  = (today - datetime.strptime(last, '%Y-%m-%d').date()).days if last else None
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
    with open(sales_csv, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            d = row['transdate'].strip()[:10]
            if not min_date or d < min_date:
                min_date = d
            if not max_date or d > max_date:
                max_date = d

    print(json.dumps({
        'ok':          True,
        'rows':        rows[:top_n],
        'total_active': len(rows),
        'date_range':  f'{min_date} to {max_date}',
    }))


if __name__ == '__main__':
    try:
        if len(sys.argv) > 1 and sys.argv[1] == 'build':
            build_db(sys.argv[2], sys.argv[3], sys.argv[4])
        elif len(sys.argv) > 1 and sys.argv[1] == 'analyze':
            analyze_db(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20)
        else:
            main()
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))

