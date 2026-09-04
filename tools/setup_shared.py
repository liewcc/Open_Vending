"""Stand up the shared hosted DB: connectivity, schema, data migration, checks.

  python tools/setup_shared.py check     can we reach it, and what version
  python tools/setup_shared.py init      create picking_history + buffer_stock
  python tools/setup_shared.py migrate   copy existing rows up (idempotent)
  python tools/setup_shared.py verify    compare local vs remote row counts
  python tools/setup_shared.py all       check -> init -> migrate -> verify

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
LOCAL = ROOT / "db" / "vending.db"
BATCH = 200

PICK_COLS = ["id", "machine", "lane_no", "product_id", "product_name",
             "picked_qty", "out_of_stock", "pick_date", "status",
             "created_at", "cleared_at"]
BUF_COLS = ["machine", "lane_no", "pid", "normal_qty", "sembreak_qty"]

SCHEMA = {
    "picking_history": """
        CREATE TABLE IF NOT EXISTS picking_history (
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
        )""",
    "buffer_stock": """
        CREATE TABLE IF NOT EXISTS buffer_stock (
            machine      TEXT NOT NULL,
            lane_no      TEXT NOT NULL,
            pid          TEXT,
            normal_qty   INTEGER DEFAULT 0,
            sembreak_qty INTEGER DEFAULT 0,
            PRIMARY KEY (machine, lane_no)
        )""",
}


def head(t):
    print("\n" + "=" * 58 + "\n" + t + "\n" + "=" * 58)


def local():
    if not LOCAL.exists():
        sys.exit("local DB not found: {}".format(LOCAL))
    c = sqlite3.connect("file:" + LOCAL.as_posix() + "?mode=ro", uri=True)
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
    sql = "INSERT OR REPLACE INTO {} ({}) VALUES ({})".format(
        table, ", ".join(cols), ", ".join("?" * len(cols)))
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
    head("MIGRATE  copy existing rows to the shared DB")
    print("Re-runnable: rows are INSERT OR REPLACE'd by primary key.")
    _copy("picking_history", PICK_COLS, "id")
    _copy("buffer_stock", BUF_COLS, "machine, lane_no")
    print("\nVERDICT  PASS")


def verify():
    head("VERIFY  local vs remote row counts")
    src = local()
    ok = True
    for t in SCHEMA:
        l = src.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
        r = int(remote_scalar("SELECT COUNT(*) FROM " + t))
        match = "match" if l == r else "MISMATCH"
        if l != r:
            ok = False
        print("  {:18} local {:>8,}   remote {:>8,}   {}".format(t, l, r, match))
    src.close()
    print("\nVERDICT  {}".format("PASS" if ok else "FAIL"))


CMDS = {"check": check, "init": init, "migrate": migrate, "verify": verify}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    try:
        for name in (CMDS if arg == "all" else [arg]):
            if name not in CMDS:
                sys.exit("unknown: {} (try: {}, all)".format(name, ", ".join(CMDS)))
            CMDS[name]()
    except remote_db.RemoteError as e:
        sys.exit("\nREMOTE ERROR: {}".format(e))
