"""Daily rotating backup of vending.db.

Run at app startup (fire-and-forget). Behavior:
  1. Skip if today's backup already exists.
  2. PRAGMA integrity_check on the live DB first — a corrupt DB is never
     backed up, so it can't rotate out the remaining good backups.
  3. Online backup via the sqlite3 backup API (safe while other
     processes read/write; never copy the file directly).
  4. Keep the newest KEEP backups, delete older ones.

Usage: python db_backup.py [--force]
"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Active account's folder, supplied by main.js; falls back to the legacy db/.
# Each account keeps its own backup/ rotation.
DB_DIR     = Path(os.environ.get("OV_DATA_DIR") or (Path(__file__).parent.parent / "db"))
VENDING_DB = DB_DIR / "vending.db"
BACKUP_DIR = DB_DIR / "backup"
KEEP = 14


def main():
    force = "--force" in sys.argv
    if not VENDING_DB.exists():
        print(json.dumps({"ok": False, "error": "vending.db not found"}))
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    dest = BACKUP_DIR / f"vending_{today}.db"
    if dest.exists() and not force:
        print(json.dumps({"ok": True, "skipped": "already backed up today", "backup": str(dest)}))
        return

    src = sqlite3.connect(str(VENDING_DB))
    integrity = src.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        src.close()
        print(json.dumps({"ok": False, "error": f"integrity_check failed: {integrity} — backup aborted, existing backups preserved"}))
        return

    if dest.exists():
        dest.unlink()
    dst = sqlite3.connect(str(dest))
    src.backup(dst)
    dst.close()
    src.close()

    pruned = []
    backups = sorted(BACKUP_DIR.glob("vending_*.db"), key=lambda p: p.name, reverse=True)
    for old in backups[KEEP:]:
        old.unlink()
        pruned.append(old.name)

    print(json.dumps({
        "ok": True,
        "integrity": integrity,
        "backup": str(dest),
        "size_mb": round(dest.stat().st_size / 1048576, 1),
        "kept": min(len(backups), KEEP),
        "pruned": pruned,
    }))


if __name__ == "__main__":
    main()
