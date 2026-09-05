"""Stand up the shared hosted DB: connectivity, schema, data migration, checks.

  python tools/setup_shared.py check              can we reach it, and what version
  python tools/setup_shared.py init               create picking_history + buffer_stock
  python tools/setup_shared.py attribute           re-assign pre-scoping rows by owner
  python tools/setup_shared.py migrate [account]  copy that account's rows up
  python tools/setup_shared.py verify  [account]  compare local vs remote row counts
  python tools/setup_shared.py all     [account]  check -> init -> migrate -> verify

`account` is an id from accounts.json (default: the primary, "dvends"). Each
account has its own local vending.db, and the shared tables keep the rows apart
by an `account` column — migrating one account never touches another's rows.

Credentials come from tools/turso.json (see turso_env.py). Reads the local
vending.db read-only; never writes to it.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # embeddable python: script dir is not on sys.path
import turso_env

turso_env.load()
import remote_db  # noqa: E402  (needs the env + sys.path from load())

ROOT = Path(__file__).resolve().parent.parent
PRIMARY = "dvends"
ACCOUNT = PRIMARY          # overridden by the optional argv account id
BATCH = 200

# `id` is deliberately not copied: it is a per-file autoincrement, so two
# accounts' local DBs reuse the same numbers. The shared table assigns its own
# and dedupes on UNIQUE(account, machine, lane_no, pick_date) instead.
PICK_COLS = ["machine", "lane_no", "product_id", "product_name",
             "picked_qty", "out_of_stock", "pick_date", "status",
             "created_at", "cleared_at"]
BUF_COLS = ["machine", "lane_no", "pid", "normal_qty", "sembreak_qty"]


def local_db(account):
    """The primary account keeps the original db/ folder; the rest live under
    db/accounts/<id>/ (mirrors dataDir() in main.js)."""
    return ROOT / "db" / "vending.db" if account == PRIMARY         else ROOT / "db" / "accounts" / account / "vending.db"

SCHEMA = {
    "picking_history": """
        CREATE TABLE IF NOT EXISTS picking_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            account      TEXT    NOT NULL DEFAULT 'dvends',
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
            UNIQUE(account, machine, lane_no, pick_date)
        )""",
    "buffer_stock": """
        CREATE TABLE IF NOT EXISTS buffer_stock (
            account      TEXT NOT NULL DEFAULT 'dvends',
            machine      TEXT NOT NULL,
            lane_no      TEXT NOT NULL,
            pid          TEXT,
            normal_qty   INTEGER DEFAULT 0,
            sembreak_qty INTEGER DEFAULT 0,
            PRIMARY KEY (account, machine, lane_no)
        )""",
}


def head(t):
    print("\n" + "=" * 58 + "\n" + t + "\n" + "=" * 58)


def local():
    db = local_db(ACCOUNT)
    if not db.exists():
        sys.exit("local DB not found: {}".format(db))
    c = sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def remote_scalar(sql):
    return remote_db._pipeline([{"sql": sql}])[0]["rows"][0][0]["value"]


def check():
    head("CHECK  can we reach the shared database")
    print("host          " + turso_env.describe())
    ver = remote_scalar("SELECT sqlite_version()")
    print("sqlite_version {}".format(ver))
    names = [r["rows"] for r in remote_db._pipeline(
        [{"sql": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"}])]
    tables = [c[0]["value"] for c in names[0]] if names and names[0] else []
    print("tables         {}".format(tables or "(none yet)"))
    print("\nVERDICT  PASS — connection works")


def init():
    head("INIT  create the shared tables")
    for name, ddl in SCHEMA.items():
        remote_db._pipeline([{"sql": ddl}])
        print("  ensured {}".format(name))
    print("\nVERDICT  PASS")


def _copy(table, cols, order):
    src = local()
    rows = src.execute("SELECT {} FROM {} ORDER BY {}".format(
        ", ".join(cols), table, order)).fetchall()
    src.close()
    total = len(rows)
    if not total:
        print("  {} — nothing to copy".format(table))
        return 0
    sql = "INSERT OR REPLACE INTO {} (account, {}) VALUES (?{})".format(
        table, ", ".join(cols), ", ?" * len(cols))
    rows = [(ACCOUNT,) + tuple(r) for r in rows]
    sent = 0
    for i in range(0, total, BATCH):
        chunk = rows[i:i + BATCH]
        stmts = [{"sql": "BEGIN"}]
        stmts += [remote_db._stmt(sql, tuple(r)) for r in chunk]
        stmts += [{"sql": "COMMIT"}]
        remote_db._pipeline(stmts)
        sent += len(chunk)
        print("  {} {:>7,} / {:,}".format(table, sent, total))
    return sent


def migrate():
    head("MIGRATE  copy account '{}' to the shared DB".format(ACCOUNT))
    print("source   {}".format(local_db(ACCOUNT)))
    print("Re-runnable: rows are INSERT OR REPLACE'd by their unique key.")
    _copy("picking_history", PICK_COLS, "id")
    _copy("buffer_stock", BUF_COLS, "machine, lane_no")
    print("\nVERDICT  PASS")


def attribute():
    """Assign pre-scoping shared rows to the account that owns the machine.

    Rows written before the `account` column existed all backfill to the
    primary account, but some were in fact written by another profile. Machine
    names are unique across accounts (each profile scans a different portal
    account), so current_state in each local DB says who owns what.
    """
    head("ATTRIBUTE  re-assign shared rows to their owning account")
    owners = {}
    for folder in sorted((ROOT / "db" / "accounts").glob("*")):
        db = folder / "vending.db"
        if not db.exists():
            continue
        c = sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)
        try:
            for (m,) in c.execute("SELECT DISTINCT machine FROM current_state"):
                owners.setdefault(folder.name, []).append(m)
        except sqlite3.OperationalError:
            pass       # fresh account, nothing scanned yet
        c.close()

    if not owners:
        print("  no secondary accounts — nothing to re-assign")
        print("\nVERDICT  PASS")
        return
    moved = 0
    for acct, machines in owners.items():
        ph = ",".join("?" * len(machines))
        for t in SCHEMA:
            n = int(remote_scalar(
                "SELECT COUNT(*) FROM {} WHERE account!='{}' AND machine IN ({})".format(
                    t, acct, ",".join("'" + m.replace("'", "''") + "'" for m in machines))))
            if n:
                remote_db._pipeline([remote_db._stmt(
                    "UPDATE {} SET account=? WHERE machine IN ({})".format(t, ph),
                    [acct] + machines)])
                moved += n
            print("  {:10} {:18} {:>6} row(s)".format(acct, t, n))
    print("\nVERDICT  PASS — {} row(s) re-assigned".format(moved))


def verify():
    head("VERIFY  local vs remote row counts for account '{}'".format(ACCOUNT))
    src = local()
    ok = True
    for t in SCHEMA:
        l = src.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
        r = int(remote_scalar(
            "SELECT COUNT(*) FROM {} WHERE account='{}'".format(t, ACCOUNT)))
        match = "match" if l == r else "MISMATCH"
        if l != r:
            ok = False
        print("  {:18} local {:>8,}   remote {:>8,}   {}".format(t, l, r, match))
    src.close()
    print("\nVERDICT  {}".format("PASS" if ok else "FAIL"))


CMDS = {"check": check, "init": init, "attribute": attribute,
        "migrate": migrate, "verify": verify}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if len(sys.argv) > 2:
        ACCOUNT = sys.argv[2]
    try:
        for name in (CMDS if arg == "all" else [arg]):
            if name not in CMDS:
                sys.exit("unknown: {} (try: {}, all)".format(name, ", ".join(CMDS)))
            CMDS[name]()
    except remote_db.RemoteError as e:
        sys.exit("\nREMOTE ERROR: {}".format(e))
