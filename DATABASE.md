# Working with the Open Vending database

A guide for anyone who has just installed Open Vending on a new PC and wants to
inspect or change the data — by hand, or with an AI assistant like Claude Code
running in this folder.

Read the **Rules that will bite you** section before you write anything. Most of
it is not obvious from the schema, and every item there comes from something
that actually went wrong.

---

## 1. Where the data lives

Everything is SQLite. There is **one database file per account**:

| Account | File |
|---|---|
| Primary (`dvends`) | `db/vending.db` |
| Any added account | `db/accounts/<id>/vending.db` |

The app resolves this through `dataDir()` in `src/main.js`; Python scripts read
the folder from the `OV_DATA_DIR` environment variable that `main.js` sets for
every child process.

Alongside each database, in the same folder:

- `last_report.xlsx` — the most recent portal scan, what the picking screen renders from
- `last_diffs.json` — restock changes detected in the last scan
- `route_plan.json` — which machines are on which route, and each machine's mode
- `pick_edit_<machine>_<date>.json` — manual edits to a picking list
- `backup/vending_YYYYMMDD.db` — daily rotating snapshots, newest 14 kept
- `archive/sales_detail_*.csv.gz` — raw sales exports, so history is rebuildable

Machine-level settings are **not** in the database. They live in
`%APPDATA%\open-vending\`: `settings.json`, `accounts.json`, and
`credentials.enc` (encrypted with Windows DPAPI — it will not decrypt on another
PC, so portal logins must be re-entered per machine).

---

## 2. Two kinds of table

This distinction drives everything else.

### Local and disposable — rebuilt from portal scans

Each PC keeps its own copy. Nothing syncs them. If they are lost, re-scan.

| Table | Rows (example) | What it is |
|---|---|---|
| `sales` | 1,436,287 | Raw transactions, one row per item sold. `transid, franid, franchisename, transdate, pid` |
| `daily_sales` | 831,934 | Per machine/product/day totals. The query layer everything reads. `machine, pid, sale_date, qty, source` |
| `forecast` | 68,602 | Average qty per weekday. Note: keyed on `franchisename`, not `machine` |
| `current_state` | 4,805 | Latest known lane state. `machine, lane, restock, pid, product_name, bal, lane_size` |
| `change_log` | 127,019 | Restock value changes over time |
| `lane_events` | 98,349 | Fuller lane history including balance and lane size |
| `machines` | 97 | Name mapping — see the identity rule below |
| `product_lane_type` | 388 | `cold` / `ambient` / `unknown` per product. Reference only; nothing in the app writes it |
| `buffer_suggestions` | 4,159 | Calculated buffers. Fully recomputed on demand, never edited by hand |
| `sales_meta`, `forecast_meta` | 5–6 | Build timestamps and row counts |

### Shared and precious — human-entered, cannot be regenerated

| Table | Rows (example) | What it is |
|---|---|---|
| `picking_history` | 38,812 | Every pick: what was taken to which machine, and whether it was done. `machine, lane_no, product_id, product_name, picked_qty, out_of_stock, pick_date, status, created_at, cleared_at` |
| `buffer_stock` | 2,395 | Manually set buffer quantities per lane. `machine, lane_no, pid, normal_qty, sembreak_qty` |

`status` on `picking_history` is one of `pending`, `done`, or `auto_cleared`
(rows older than 36 hours are swept automatically).

**If more than one PC uses this system**, those two tables may be hosted in a
shared libSQL/Turso database instead of the local file — see section 6.

---

## 3. Rules that will bite you

**Never sync `vending.db` through Drive, Dropbox or OneDrive.** The database runs
in WAL mode, so it is really three files (`.db`, `.db-wal`, `.db-shm`). File
sync ships them independently and at different times. Copying the `.db` alone
mid-write silently loses committed rows — measured at 1,000 rows lost in a
straight test. Two PCs editing synced copies lose one side's session entirely.
To move a database, use a proper snapshot:

```bash
python -c "import sqlite3;sqlite3.connect(r'db/vending.db').execute(\"VACUUM INTO 'snapshot.db'\")"
```

That folds the WAL in and produces one self-contained file with no sidecars.

**Machine names are not one thing.** The picking side (`current_state`,
`picking_history`, `route_plan.json`) uses Excel sheet names, truncated to 31
characters. The sales side (`daily_sales`, `sales`) uses canonical names.
Translate through `machines.sheet_alias` → `machines.canonical`. Joining the two
sides without translating silently drops the longest-named machines.

**Product IDs are account-scoped.** The same product has a different `pid` under
a different account. Never carry a PID mapping from one account's database to
another's.

**Sales history has a start date per account.** Data before an account's own
cutover belongs to a previous vendor and will distort forecasts. Check
`SELECT MIN(sale_date) FROM daily_sales` before assuming a window is valid.

**`buffer_suggestions` has a legacy column.** `suggestion_qty` is dead; the live
ones are `suggestion_normal_qty` and `suggestion_sembreak_qty`.

**Sem-break dates differ per college.** There is no global term calendar. Break
and mode logic is per machine, held in `route_plan.json`.

---

## 4. Looking at the data safely

Open read-only. This cannot corrupt anything, and works while the app is running:

```python
import sqlite3
conn = sqlite3.connect("file:db/vending.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
for r in conn.execute("SELECT machine, COUNT(*) n FROM picking_history GROUP BY 1 ORDER BY n DESC LIMIT 10"):
    print(r["machine"], r["n"])
```

Use the bundled interpreter so you match the app's environment:

```bash
./python/python.exe your_script.py
```

**Gotcha for any script you write here:** the bundled Python is an *embeddable*
build. It does **not** put a script's own directory on `sys.path`, so importing
a sibling module fails with `ModuleNotFoundError`. Add this first:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
```

Several scripts in `src/` already do this — copy the pattern.

---

## 5. Changing data

**Prefer the app.** Picks, buffers and route plans all have UI that maintains
invariants the raw tables do not enforce.

**Before any manual write, take a backup:**

```bash
./python/python.exe src/db_backup.py --force
```

That runs `PRAGMA integrity_check` first and refuses to back up a corrupt
database, so it can never rotate a good snapshot out in favour of a bad one.
Snapshots land in `db/backup/`, newest 14 kept.

**Then write in a transaction**, and check what you are about to touch first:

```python
conn = sqlite3.connect("db/vending.db")
cur = conn.execute("SELECT COUNT(*) FROM picking_history WHERE machine=? AND status='pending'", ("KK 11C M5",))
print("about to affect", cur.fetchone()[0], "rows")
# ... then the UPDATE/DELETE, then conn.commit()
```

**Do not hand-edit** `daily_sales`, `forecast`, or `buffer_suggestions`. They are
derived and will be overwritten. Change the inputs instead — import a sales CSV,
or recalculate buffers from Settings.

---

## 6. If this PC shares a database with another

When two or more PCs need to work at the same time, `picking_history` and
`buffer_stock` are hosted remotely rather than kept in the local file. Both PCs
read and write the same rows live — there is no sync and no local copy of those
two tables, so there is nothing to reconcile.

It is switched on by two settings in `%APPDATA%\open-vending\settings.json`:

```json
{ "remoteUrl": "libsql://...", "remoteToken": "..." }
```

Check which mode this PC is in:

```bash
./python/python.exe tools/enable_shared.py --status
```

With those blank, everything is local and behaves exactly as a single-PC install.

**What this changes for you:**

- Querying the local `vending.db` for `picking_history` will show stale rows, or
  no such table at all on a seeded install. Query the shared database instead.
- There is **no offline queue**. If the connection is down, a save fails and the
  app says so. It is never silently queued, so never assume a save succeeded
  because no error appeared in your script — check the return value.
- The local database still holds all the sales history. Only those two tables move.

---

## 7. Using Claude Code in this folder

Claude Code can read this file, the schema, and `src/` to answer questions and
write scripts. Useful things to ask:

- "Which machines sold out most often in the last 30 days?"
- "Show me the picking history for KK 11C M5 this week"
- "Why is this lane's restock coming out as 0?"
- "Write a script that exports last month's sales per machine to CSV"

**Tell it these things**, because they are not inferable from the schema:

- Open the database read-only unless the task genuinely requires writing
- Names must be translated through `machines.sheet_alias` when joining picking
  data to sales data
- Take a backup before any write
- Check whether the shared database is enabled before touching `picking_history`
  or `buffer_stock`

**Ask it not to**: sync or copy `vending.db` to cloud storage, edit derived
tables directly, or delete rows from `picking_history` — that table is the only
record of what was actually restocked.

---

## 8. If something breaks

Check integrity first:

```bash
./python/python.exe -c "import sqlite3;print(sqlite3.connect('db/vending.db').execute('PRAGMA integrity_check').fetchone()[0])"
```

Anything other than `ok` means restore from `db/backup/` — copy the newest good
snapshot over `db/vending.db` with the app closed.

Raw sales history is rebuildable from `db/archive/*.csv.gz` even if the database
and every backup are lost, by re-importing through Settings.
