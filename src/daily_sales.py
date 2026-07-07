"""daily_sales — unified per-machine per-product per-day sales layer.

    daily_sales(machine, pid, sale_date, qty, source)
      source='txn'  authoritative, aggregated from the `sales` transaction
                    table (CSV snapshot, complete up to sales_meta.max_date)
      source='est'  estimated from restock deltas in change_log, only for
                    dates AFTER sales_meta.max_date

Estimation logic (source='est'):
  A restock increase between two scans means those units were sold in the
  interval. Rows are grouped per (machine, lane, detected_at) keeping the
  net first_old -> last_new value, which cancels the twin-machine phantom
  A->B->A pairs written at the same timestamp. PID attribution prefers the
  lane_events row at the same timestamp (product known at event time) and
  falls back to the lane's current product in current_state. Sheet-name
  truncation is resolved through machines.sheet_alias.

Reconciliation is automatic: every rebuild re-derives txn rows from `sales`
and est rows only for the uncovered tail, so importing a newer CSV snapshot
replaces estimates with authoritative data.

Usage:
  python daily_sales.py rebuild     <db>   full rebuild (txn + est)
  python daily_sales.py refresh_est <db>   refresh est rows only (after a scan)
"""
import json
import sqlite3
import sys


def ensure_table(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_sales (
            machine   TEXT NOT NULL,
            pid       TEXT NOT NULL,
            sale_date TEXT NOT NULL,
            qty       INTEGER NOT NULL,
            source    TEXT NOT NULL CHECK(source IN ('txn', 'est')),
            PRIMARY KEY (machine, pid, sale_date)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_sales_date ON daily_sales (sale_date);
    """)


def _txn_boundary(conn):
    """Newest date covered by authoritative snapshot data ('' if none)."""
    row = conn.execute("SELECT value FROM sales_meta WHERE key='max_date'").fetchone()
    return (row[0] or '')[:10] if row else ''


def refresh_est(conn):
    """Recompute source='est' rows from change_log restock deltas."""
    ensure_table(conn)
    boundary = _txn_boundary(conn)
    conn.execute("DELETE FROM daily_sales WHERE source='est'")

    # machine name canonicalization (Excel 31-char sheet truncation)
    alias = dict(conn.execute(
        "SELECT sheet_alias, canonical FROM machines WHERE sheet_alias IS NOT NULL"
    ).fetchall())

    # pid at event time (lane_events), fallback: lane's current product
    event_pid = {}
    for m, l, t, pid in conn.execute(
        "SELECT machine, lane, detected_at, pid FROM lane_events WHERE pid IS NOT NULL"
    ):
        event_pid[(m, l, t)] = pid
    current_pid = dict(
        ((m, l), pid) for m, l, pid in conn.execute(
            "SELECT machine, lane, pid FROM current_state WHERE pid IS NOT NULL"
        )
    )

    # collapse change_log per (machine, lane, detected_at): first old -> last new
    groups = {}   # (machine, lane, detected_at) -> [first_old, last_new]
    for m, l, t, old, new in conn.execute(
        "SELECT machine, lane, detected_at, old_restock, new_restock "
        "FROM change_log ORDER BY id"
    ):
        key = (m, l, t)
        if key not in groups:
            groups[key] = [old, new]
        else:
            groups[key][1] = new

    daily = {}    # (canonical_machine, pid, date) -> qty
    attributed = 0
    unattributed = 0
    for (m, l, t), (old, new) in groups.items():
        delta = (new or 0) - (old or 0)
        if delta <= 0:
            continue  # refill or no-op — not a sale
        date = t[:10]
        if boundary and date <= boundary:
            continue  # authoritative txn data covers this date
        pid = event_pid.get((m, l, t)) or current_pid.get((m, l))
        if not pid:
            unattributed += delta
            continue
        canon = alias.get(m, m)
        key = (canon, pid, date)
        daily[key] = daily.get(key, 0) + delta
        attributed += delta

    conn.executemany(
        "INSERT INTO daily_sales (machine, pid, sale_date, qty, source) VALUES (?,?,?,?,'est') "
        "ON CONFLICT(machine, pid, sale_date) DO UPDATE SET qty = qty + excluded.qty",
        [(m, p, d, q) for (m, p, d), q in daily.items()]
    )
    return {
        'est_rows': len(daily),
        'est_units': attributed,
        'est_unattributed_units': unattributed,
        'txn_boundary': boundary,
    }


def rebuild(conn):
    """Full rebuild: txn rows from `sales`, then est rows for the tail."""
    ensure_table(conn)
    conn.execute("DELETE FROM daily_sales")
    conn.execute("""
        INSERT INTO daily_sales (machine, pid, sale_date, qty, source)
        SELECT franchisename, pid, transdate, COUNT(*), 'txn'
        FROM sales
        WHERE franchisename IS NOT NULL AND pid IS NOT NULL
          AND transdate IS NOT NULL AND transdate != ''
        GROUP BY franchisename, pid, transdate
    """)
    txn_rows = conn.execute("SELECT COUNT(*) FROM daily_sales WHERE source='txn'").fetchone()[0]
    stats = refresh_est(conn)
    stats['txn_rows'] = txn_rows
    return stats


def main():
    cmd, db_path = sys.argv[1], sys.argv[2]
    conn = sqlite3.connect(db_path)
    try:
        if cmd == 'rebuild':
            stats = rebuild(conn)
        elif cmd == 'refresh_est':
            stats = refresh_est(conn)
        else:
            print(json.dumps({'ok': False, 'error': f'unknown command: {cmd}'}))
            return
        conn.commit()
        stats['ok'] = True
        print(json.dumps(stats))
    finally:
        conn.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        print(json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()}))
