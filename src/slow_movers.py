"""Slow-movers analysis: rank active products by total sales ascending."""
import sys
import csv
import json
from datetime import datetime, date


def is_inactive(name):
    """Products prefixed with zzz/ZXXX/xxxx etc. are already discontinued."""
    first = name.strip().split()[0].lower() if name.strip() else ''
    return len(first) >= 2 and all(c in 'zx' for c in first)


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
        main()
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))
