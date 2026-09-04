"""Spike for the split-database plan. Proves (or kills) three claims before any
real change is made. Nothing here writes to the live DB — it is opened read-only.

  python cloud_test/prove.py seed      a bootstrap snapshot for a new PC
  python cloud_test/prove.py wal       what a mid-sync file copy loses
  python cloud_test/prove.py writers   two PCs at once: file copy vs one shared store
  python cloud_test/prove.py all

Scratch files land in cloud_test/work/ and are rebuilt on every run.
"""
import gzip
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
LIVE   = ROOT / "db" / "vending.db"
WORK   = Path(__file__).resolve().parent / "work"
SHARED = ("picking_history", "buffer_stock", "product_lane_type")

SCHEMA = """
CREATE TABLE picking_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, machine TEXT NOT NULL, lane_no TEXT NOT NULL,
    product_id TEXT, product_name TEXT, picked_qty INTEGER NOT NULL,
    out_of_stock INTEGER DEFAULT 0, pick_date TEXT NOT NULL, status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')), cleared_at TEXT,
    UNIQUE(machine, lane_no, pick_date));
CREATE TABLE buffer_stock (
    machine TEXT NOT NULL, lane_no TEXT NOT NULL, pid TEXT,
    normal_qty INTEGER DEFAULT 0, sembreak_qty INTEGER DEFAULT 0,
    PRIMARY KEY (machine, lane_no));
CREATE TABLE product_lane_type (
    pid TEXT PRIMARY KEY, lane_type TEXT, product_name TEXT, source TEXT);
"""

TODAY = date.today().isoformat()


def mb(p):
    return round(Path(p).stat().st_size / 1048576, 2)


def head(title):
    print("\n" + "=" * 62 + "\n" + title + "\n" + "=" * 62)


def fresh_work():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)


# ── claim 1: a seed snapshot can bootstrap a new PC ───────────────────────────

def seed():
    head("CLAIM 1  a seed snapshot bootstraps a new install")
    if not LIVE.exists():
        print("SKIP  " + str(LIVE) + " not found")
        return
    out = WORK / "seed.db"
    src = sqlite3.connect("file:" + LIVE.as_posix() + "?mode=ro", uri=True)
    src.execute("VACUUM INTO ?", (str(out),))
    live_tables = {r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    src.close()

    dst = sqlite3.connect(out)
    for t in SHARED:
        dst.execute("DROP TABLE IF EXISTS " + t)
    dst.commit()
    dst.execute("VACUUM")
    left = {r[0] for r in dst.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
    rows = {t: dst.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
            for t in ("sales", "daily_sales", "forecast") if t in left}
    dst.close()

    gz = WORK / "seed.db.gz"
    with open(out, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)

    sidecars = sorted(p.name for p in WORK.glob("seed.db-*"))
    print("live DB          {} MB  ({} tables)".format(mb(LIVE), len(live_tables)))
    print("seed             {} MB  ({} tables)".format(mb(out), len(left)))
    print("seed gzipped     {} MB   <- what actually goes to Drive".format(mb(gz)))
    print("integrity_check  " + integrity)
    print("shared tables    " + ("stripped" if not (set(SHARED) & left) else "STILL PRESENT"))
    print("wal/shm sidecars " + (str(sidecars) if sidecars else "none — self-contained, safe to sync"))
    for t, n in rows.items():
        print("  carried {:12} {:>9,} rows".format(t, n))
    ok = integrity == "ok" and not (set(SHARED) & left) and not sidecars
    print("\nVERDICT  {} — a new PC can start from this file".format("PASS" if ok else "FAIL"))


# ── claim 2: syncing the DB file itself is unsafe ─────────────────────────────

def wal():
    head("CLAIM 2  copying the DB mid-write loses committed data")
    db = WORK / "wal_demo.db"
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    c.executemany(
        "INSERT INTO picking_history (machine, lane_no, picked_qty, pick_date) VALUES (?,?,?,?)",
        [("M{:03}".format(i), "1", 5, TODAY) for i in range(1000)])
    c.commit()

    committed = c.execute("SELECT COUNT(*) FROM picking_history").fetchone()[0]
    wal_size = (WORK / "wal_demo.db-wal").stat().st_size

    # Drive uploads whole files independently; the .db can ship without its -wal
    copy = WORK / "wal_copy.db"
    shutil.copyfile(db, copy)
    c.close()

    c2 = sqlite3.connect(copy)
    arrived = c2.execute("SELECT COUNT(*) FROM picking_history").fetchone()[0]
    c2.close()

    print("rows committed on this PC   {:,}".format(committed))
    print("sitting in -wal, not .db    {:,} bytes".format(wal_size))
    print("rows in the copied .db      {:,}".format(arrived))
    print("rows silently lost          {:,}".format(committed - arrived))
    print("\nVERDICT  {} — the .db alone is not the database; "
          "syncing it drops committed work".format(
              "PASS" if arrived < committed else "INCONCLUSIVE"))


# ── claim 3: file copies lose a writer, one shared store does not ─────────────

def _seed_rows(conn):
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO picking_history (machine, lane_no, picked_qty, pick_date, status) "
        "VALUES (?,?,?,?,'pending')",
        [("ROUTE-{:02}".format(i), "1", 4, TODAY) for i in range(10)])
    conn.commit()


def _office_writes(conn):
    """Office preps tomorrow: 20 new picks."""
    conn.executemany(
        "INSERT OR REPLACE INTO picking_history (machine, lane_no, picked_qty, pick_date, status) "
        "VALUES (?,?,?,?,'pending')",
        [("OFFICE-{:02}".format(i), "1", 6, TODAY) for i in range(20)])
    conn.commit()


def _transit_writes(conn):
    """Team on the road marks the 10 existing routes done."""
    conn.execute(
        "UPDATE picking_history SET status='done', cleared_at=datetime('now') "
        "WHERE machine LIKE 'ROUTE-%' AND status='pending'")
    conn.commit()


def _count(path):
    c = sqlite3.connect(path)
    office = c.execute(
        "SELECT COUNT(*) FROM picking_history WHERE machine LIKE 'OFFICE-%'").fetchone()[0]
    done = c.execute(
        "SELECT COUNT(*) FROM picking_history WHERE status='done'").fetchone()[0]
    c.close()
    return office, done


def writers():
    head("CLAIM 3  two PCs at once — file copy vs one shared store")
    base = WORK / "base.db"
    c = sqlite3.connect(base)
    _seed_rows(c)
    c.close()

    # model A: each PC holds its own copy, Drive picks one winner
    a, b = WORK / "pc_a.db", WORK / "pc_b.db"
    shutil.copyfile(base, a)
    shutil.copyfile(base, b)
    ca, cb = sqlite3.connect(a), sqlite3.connect(b)
    _office_writes(ca)
    _transit_writes(cb)
    ca.close()
    cb.close()
    winner = WORK / "drive_head.db"
    shutil.copyfile(b, winner)          # B uploaded last, so B becomes head
    fa_office, fa_done = _count(winner)

    # model B: one store, both writing rows into it
    shared = WORK / "shared.db"
    c = sqlite3.connect(shared)
    _seed_rows(c)
    c.close()
    sa, sb = sqlite3.connect(shared), sqlite3.connect(shared)
    _office_writes(sa)
    _transit_writes(sb)
    sa.close()
    sb.close()
    sh_office, sh_done = _count(shared)

    print("{:22} {:>13} {:>14}".format("", "office picks", "machines done"))
    print("{:22} {:>13} {:>14}".format("expected", 20, 10))
    print("{:22} {:>13} {:>14}".format("file copy (Drive)", fa_office, fa_done))
    print("{:22} {:>13} {:>14}".format("one shared store", sh_office, sh_done))
    lost = (20 - fa_office) + (10 - fa_done)
    print("\nfile copy lost {} of 30 writes — one PC's whole session".format(lost))
    ok = lost > 0 and (sh_office, sh_done) == (20, 10)
    print("\nVERDICT  {} — row-level writes survive, file-level ones do not".format(
        "PASS" if ok else "FAIL"))
    print("NOTE     the shared store here is a local file standing in for the hosted DB;"
          "\n         it proves row-vs-file semantics, not network behaviour")


CMDS = {"seed": seed, "wal": wal, "writers": writers}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    fresh_work()
    for name in (CMDS if arg == "all" else [arg]):
        if name not in CMDS:
            sys.exit("unknown: {} (try: {}, all)".format(name, ", ".join(CMDS)))
        CMDS[name]()
    print("\nscratch files: " + str(WORK))
