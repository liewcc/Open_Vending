"""
machine_sales.py — per-machine sales totals over the last N days of data.

Usage:
    python machine_sales.py <vending_db> <machine> <days>

Prints: {"ok": true, "window": {"from":..., "to":...}, "sales": {pid: qty}}
Window is anchored to MAX(sale_date) in daily_sales (manual rebuilds lag
behind today), same convention as replacement_suggest.py. days=1 means the
newest sale day only (daily_sales has no time-of-day granularity).
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from daily_sales import canonical_machine


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(0)


def main():
    if len(sys.argv) < 4:
        fail("usage: machine_sales.py <vending_db> <machine> <days>")
    db_path, machine = sys.argv[1], sys.argv[2]
    try:
        days = max(1, int(sys.argv[3]))
    except ValueError:
        days = 1
    if not Path(db_path).exists():
        fail("vending.db not found")
    conn = sqlite3.connect(db_path)
    max_date = conn.execute("SELECT MAX(sale_date) FROM daily_sales").fetchone()
    if not max_date or not max_date[0]:
        conn.close()
        fail("daily_sales is empty — rebuild it (import sales CSV)")
    to_date = max_date[0][:10]
    from_date = (datetime.strptime(to_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    machine = canonical_machine(conn, machine)
    sales = dict(conn.execute(
        "SELECT pid, SUM(qty) FROM daily_sales WHERE machine=? AND sale_date>=? GROUP BY pid",
        (machine, from_date),
    ).fetchall())
    conn.close()
    print(json.dumps({"ok": True, "window": {"from": from_date, "to": to_date}, "sales": sales}))


if __name__ == "__main__":
    main()
