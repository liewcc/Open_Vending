"""One-time migration: consolidate data.db + sales_detail.db + sales_forecast.db
into a single db/vending.db.

Layers:
  raw       — sales, sales_meta, change_log, current_state, lane_events
  dimension — machines, product_lane_type
  derived   — forecast, forecast_meta, buffer_suggestions
  app       — buffer_stock, picking_history

Old DBs are left untouched (read-only fallback). Refuses to run if
vending.db already exists, unless --force is given (then it is replaced).

Usage: python migrate_to_vending.py [--force]
"""
import json
import sqlite3
import sys
from pathlib import Path

DB_DIR      = Path(__file__).parent.parent / "db"
VENDING_DB  = DB_DIR / "vending.db"
DATA_DB     = DB_DIR / "data.db"
DETAIL_DB   = DB_DIR / "sales_detail.db"
FORECAST_DB = DB_DIR / "sales_forecast.db"

SCHEMA_VERSION = 4


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def main():
    force = "--force" in sys.argv
    if VENDING_DB.exists():
        if not force:
            fail(f"{VENDING_DB} already exists — pass --force to replace it")
        VENDING_DB.unlink()
        for suffix in ("-wal", "-shm"):
            p = Path(str(VENDING_DB) + suffix)
            if p.exists():
                p.unlink()

    for p in (DATA_DB, DETAIL_DB, FORECAST_DB):
        if not p.exists():
            fail(f"source db missing: {p}")

    conn = sqlite3.connect(str(VENDING_DB))
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")

    cur.executescript("""
        -- ── raw layer ──────────────────────────────────────────────────────
        CREATE TABLE sales (
            transid       TEXT,
            franid        TEXT,
            franchisename TEXT,
            transdate     TEXT,
            pid           TEXT
        );
        CREATE INDEX idx_sales_main ON sales (franchisename, pid, transdate);
        CREATE TABLE sales_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE change_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at  TEXT NOT NULL,
            machine      TEXT NOT NULL,
            lane         TEXT NOT NULL,
            old_restock  INTEGER,
            new_restock  INTEGER
        );
        CREATE INDEX idx_change_log_ml ON change_log (machine, lane, detected_at);
        CREATE TABLE current_state (
            machine      TEXT NOT NULL,
            lane         TEXT NOT NULL,
            restock      INTEGER,
            updated_at   TEXT,
            pid          TEXT,
            product_name TEXT,
            bal          INTEGER,
            lane_size    INTEGER,
            PRIMARY KEY (machine, lane)
        );
        CREATE TABLE lane_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at  TEXT NOT NULL,
            machine      TEXT NOT NULL,
            lane         TEXT NOT NULL,
            pid          TEXT,
            product_name TEXT,
            old_bal      INTEGER,
            new_bal      INTEGER,
            old_restock  INTEGER,
            new_restock  INTEGER,
            lane_size    INTEGER
        );
        CREATE INDEX idx_lane_events_mpd ON lane_events (machine, pid, detected_at);

        -- ── dimension layer ────────────────────────────────────────────────
        CREATE TABLE machines (
            canonical   TEXT PRIMARY KEY,   -- name as used in sales.franchisename
            franid      TEXT,
            sheet_alias TEXT,               -- Excel sheet name if truncated (31-char limit)
            active      INTEGER DEFAULT 0   -- 1 = currently scanned by open_vending
        );
        CREATE TABLE product_lane_type (
            pid          TEXT PRIMARY KEY,
            lane_type    TEXT CHECK(lane_type IN ("cold", "ambient", "unknown")),
            product_name TEXT,
            source       TEXT
        );

        -- ── derived layer ──────────────────────────────────────────────────
        CREATE TABLE forecast (
            franchisename TEXT,
            pid           TEXT,
            weekday       INTEGER,
            avg_qty       REAL,
            PRIMARY KEY (franchisename, pid, weekday)
        );
        CREATE TABLE forecast_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE buffer_suggestions (
            machine        TEXT NOT NULL,
            pid            TEXT NOT NULL,
            suggestion_qty INTEGER DEFAULT 0,
            suggestion_normal_qty INTEGER DEFAULT 0,
            suggestion_sembreak_qty INTEGER DEFAULT 0,
            PRIMARY KEY (machine, pid)
        );

        -- ── app layer ──────────────────────────────────────────────────────
        CREATE TABLE buffer_stock (
            machine      TEXT NOT NULL,
            lane_no      TEXT NOT NULL,
            pid          TEXT,
            normal_qty   INTEGER DEFAULT 0,
            sembreak_qty INTEGER DEFAULT 0,
            PRIMARY KEY (machine, lane_no)
        );
        CREATE TABLE picking_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            machine      TEXT    NOT NULL,
            lane_no      TEXT    NOT NULL,
            product_id   TEXT,
            product_name TEXT,
            picked_qty   INTEGER NOT NULL,
            out_of_stock INTEGER DEFAULT 0,
            pick_date    TEXT    NOT NULL,
            status       TEXT    DEFAULT 'pending',
            created_at   TEXT    DEFAULT (datetime('now')),
            cleared_at   TEXT,
            UNIQUE(machine, lane_no, pick_date)
        );
    """)

    cur.execute("ATTACH DATABASE ? AS old_data",     (str(DATA_DB),))
    cur.execute("ATTACH DATABASE ? AS old_detail",   (str(DETAIL_DB),))
    cur.execute("ATTACH DATABASE ? AS old_forecast", (str(FORECAST_DB),))

    copies = [
        ("sales",              "INSERT INTO sales SELECT transid, franid, franchisename, transdate, pid FROM old_detail.sales"),
        ("sales_meta",         "INSERT INTO sales_meta SELECT key, value FROM old_detail.meta"),
        ("forecast",           "INSERT INTO forecast SELECT franchisename, pid, weekday, avg_qty FROM old_forecast.forecast"),
        ("forecast_meta",      "INSERT INTO forecast_meta SELECT key, value FROM old_forecast.meta"),
        ("change_log",         "INSERT INTO change_log (id, detected_at, machine, lane, old_restock, new_restock) SELECT id, detected_at, machine, lane, old_restock, new_restock FROM old_data.change_log"),
        ("current_state",      "INSERT INTO current_state (machine, lane, restock, updated_at) SELECT machine, lane, restock, updated_at FROM old_data.current_state"),
        ("product_lane_type",  "INSERT INTO product_lane_type SELECT pid, lane_type, product_name, source FROM old_data.product_lane_type"),
        ("buffer_suggestions", "INSERT INTO buffer_suggestions SELECT machine, pid, suggestion_qty, suggestion_normal_qty, suggestion_sembreak_qty FROM old_data.buffer_suggestions"),
        ("buffer_stock",       "INSERT INTO buffer_stock SELECT machine, lane_no, pid, normal_qty, sembreak_qty FROM old_data.buffer_stock"),
        ("picking_history",    "INSERT INTO picking_history (id, machine, lane_no, product_id, product_name, picked_qty, out_of_stock, pick_date, status, created_at, cleared_at) "
                               "SELECT id, machine, lane_no, product_id, product_name, picked_qty, out_of_stock, pick_date, status, created_at, cleared_at FROM old_data.picking_history"),
    ]
    counts = {}
    for name, sql in copies:
        cur.execute(sql)
        counts[name] = cur.rowcount

    # ── machines dimension: canonical names from sales history ──────────────
    cur.execute("""
        INSERT INTO machines (canonical, franid)
        SELECT franchisename, MAX(franid) FROM old_detail.sales GROUP BY franchisename
    """)
    # Mark machines currently scanned as active; resolve Excel sheet-name
    # truncation (31-char limit) to a canonical alias where possible.
    scanned = [r[0] for r in cur.execute("SELECT DISTINCT machine FROM old_data.current_state")]
    aliases = 0
    unmatched = []
    for m in scanned:
        row = cur.execute("SELECT canonical FROM machines WHERE canonical = ?", (m,)).fetchone()
        if row:
            cur.execute("UPDATE machines SET active = 1 WHERE canonical = ?", (m,))
            continue
        cand = cur.execute(
            "SELECT canonical FROM machines WHERE substr(canonical, 1, ?) = ?",
            (len(m), m)
        ).fetchall()
        if len(cand) == 1:
            cur.execute("UPDATE machines SET active = 1, sheet_alias = ? WHERE canonical = ?", (m, cand[0][0]))
            aliases += 1
        else:
            # unknown machine (new, never in sales history) — keep as its own row
            cur.execute("INSERT INTO machines (canonical, active, sheet_alias) VALUES (?, 1, ?)", (m, m))
            unmatched.append(m)
    counts["machines"] = cur.execute("SELECT COUNT(*) FROM machines").fetchone()[0]

    cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    cur.execute("DETACH DATABASE old_data")
    cur.execute("DETACH DATABASE old_detail")
    cur.execute("DETACH DATABASE old_forecast")

    integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
    journal   = cur.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    print(json.dumps({
        "ok": integrity == "ok",
        "integrity": integrity,
        "journal_mode": journal,
        "rows_copied": counts,
        "sheet_aliases_resolved": aliases,
        "machines_not_in_sales_history": unmatched,
        "db": str(VENDING_DB),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
