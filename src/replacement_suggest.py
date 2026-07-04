"""
replacement_suggest.py — Q3 data provider.

Usage:
    python replacement_suggest.py <sales_detail_db> <product_csv> <machine>

Prints one JSON object to stdout:
    { "ok": true,
      "window":       {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
      "catalog":      {pid: {"name": str, "tray": str, "size": int}},
      "machineSales": {pid: count},   # this machine, last 30 days of data
      "globalSales":  {pid: count} }  # all machines, same window

The 30-day window is anchored to the newest transdate in the DB
(meta.max_date), not to today — the DB is rebuilt manually and may lag.
Suggestion/slow-mover logic itself lives in picking.js (pure, testable);
this script only supplies data.
"""
import csv
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(0)


def main():
    if len(sys.argv) < 4:
        fail("usage: replacement_suggest.py <sales_detail_db> <product_csv> <machine>")
    db_path, csv_path, machine = sys.argv[1], sys.argv[2], sys.argv[3]

    if not csv_path or not Path(csv_path).exists():
        fail("product.csv not found — set the path in the Slow Mover panel")
    if not Path(db_path).exists():
        fail("sales_detail.db not found — build it in the Slow Mover panel first")

    catalog = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pid = (row.get("PID") or "").strip()
            tray = (row.get("TRAY") or "").strip()
            if not pid or not tray:
                continue
            try:
                size = int((row.get("LANE SIZE") or "0").strip())
            except ValueError:
                size = 0
            catalog[pid] = {
                "name": (row.get("Product Name") or "").strip(),
                "tray": tray,
                "size": size,
            }
    if not catalog:
        fail("product.csv has no usable rows (need PID + TRAY columns)")

    conn = sqlite3.connect(db_path)
    max_date = conn.execute(
        "SELECT value FROM meta WHERE key='max_date'"
    ).fetchone()
    if not max_date or not max_date[0]:
        conn.close()
        fail("sales_detail.db has no max_date meta — rebuild it")
    to_date = max_date[0][:10]
    from_date = (datetime.strptime(to_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")

    machine_sales = dict(conn.execute(
        "SELECT pid, COUNT(*) FROM sales "
        "WHERE franchisename=? AND transdate>=? GROUP BY pid",
        (machine, from_date),
    ).fetchall())
    global_sales = dict(conn.execute(
        "SELECT pid, COUNT(*) FROM sales WHERE transdate>=? GROUP BY pid",
        (from_date,),
    ).fetchall())
    conn.close()

    print(json.dumps({
        "ok": True,
        "window": {"from": from_date, "to": to_date},
        "catalog": catalog,
        "machineSales": machine_sales,
        "globalSales": global_sales,
    }))


if __name__ == "__main__":
    main()
