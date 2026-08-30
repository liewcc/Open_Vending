"""
machine_sales.py — per-machine sales totals over the last N days of data.

Usage:
    python machine_sales.py <vending_db> <machine> <days>

Prints: {"ok": true, "window": {"from":..., "to":...}, "sales": {pid: qty},
         "lanes": {"lane|pid": qty}, "lane_ok": bool, "lane_from": date}
Window is anchored to MAX(sale_date) in daily_sales (manual rebuilds lag
behind today), same convention as replacement_suggest.py. days=1 means the
newest sale day only (daily_sales has no time-of-day granularity).

"sales" is the product total across all lanes; "lanes" splits it per lane so
a product sitting in several lanes shows what each one sold. lane_ok is false
when change_log does not reach back far enough to cover the whole window —
the caller shows no split rather than a number built on partial history.
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(0)


def lane_split(conn, machine, from_date):
    """Per-lane sold from change_log restock deltas.

    Same estimation daily_sales.py uses for its source='est' rows, without the
    group-by-pid collapse that throws the lane away. Returns (lanes, ok, first)
    where lanes is keyed "lane|pid" — keying on pid too keeps a lane that was
    given a replacement product from inheriting the old product's sales.
    """
    first = conn.execute(
        "SELECT MIN(substr(detected_at, 1, 10)) FROM change_log WHERE machine=?",
        (machine,),
    ).fetchone()[0]
    if not first or from_date < first:
        return {}, False, first

    # pid at event time (lane_events), fallback: lane's current product
    event_pid = dict(
        ((lane, t), pid) for lane, t, pid in conn.execute(
            "SELECT lane, detected_at, pid FROM lane_events "
            "WHERE machine=? AND pid IS NOT NULL AND detected_at>=?",
            (machine, from_date),
        )
    )
    current_pid = dict(conn.execute(
        "SELECT lane, pid FROM current_state WHERE machine=? AND pid IS NOT NULL",
        (machine,),
    ))

    # collapse per (lane, detected_at): first old -> last new, which cancels
    # the twin-machine phantom A->B->A pairs written at the same timestamp
    groups = {}
    for lane, t, old, new in conn.execute(
        "SELECT lane, detected_at, old_restock, new_restock FROM change_log "
        "WHERE machine=? AND detected_at>=? ORDER BY id",
        (machine, from_date),
    ):
        groups.setdefault((lane, t), [old, new])[1] = new

    lanes = {}
    for (lane, t), (old, new) in groups.items():
        delta = (new or 0) - (old or 0)
        if delta <= 0:
            continue  # refill or no-op — not a sale
        pid = event_pid.get((lane, t)) or current_pid.get(lane)
        if not pid:
            continue  # unattributable, same as daily_sales
        key = "%s|%s" % (lane, pid)
        lanes[key] = lanes.get(key, 0) + delta
    return lanes, True, first


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
    # daily_sales keys on the canonical name, the caller passes the sheet name
    row = conn.execute(
        "SELECT canonical FROM machines WHERE sheet_alias=?", (machine,)
    ).fetchone()
    sales = dict(conn.execute(
        "SELECT pid, SUM(qty) FROM daily_sales WHERE machine=? AND sale_date>=? GROUP BY pid",
        (row[0] if row else machine, from_date),
    ).fetchall())
    lanes, lane_ok, lane_from = lane_split(conn, machine, from_date)
    conn.close()
    print(json.dumps({"ok": True, "window": {"from": from_date, "to": to_date},
                      "sales": sales, "lanes": lanes,
                      "lane_ok": lane_ok, "lane_from": lane_from}))


if __name__ == "__main__":
    main()
