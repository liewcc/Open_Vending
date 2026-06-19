"""
DVends Replenishment Report Exporter
Usage: python open_vending.py [--headless]
"""

import asyncio
import datetime
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from playwright.async_api import async_playwright

USERNAME = os.environ.get('OV_USERNAME', '')
PASSWORD = os.environ.get('OV_PASSWORD', '')

DB_DIR  = Path(__file__).parent / "db"
LOG_DIR = Path(__file__).parent / "log"
DB_DIR.mkdir(exist_ok=True)

HEADLESS   = "--headless" in sys.argv
LOGIN_ONLY = "--login-only" in sys.argv

BROWSER_STOP = DB_DIR / ".browser_stop"

_DEFAULT_LOGIN_URL = "https://vendingportal.azurewebsites.net/SuperAdmin/SPLogin.aspx"
LOGIN_URL  = os.environ.get('OV_LANDING_URL') or _DEFAULT_LOGIN_URL
REPORT_URL = "https://vendingportal.azurewebsites.net/SuperAdmin/SPReplenishmentV2.aspx"


SQLITE_DB = DB_DIR / "data.db"


def status(msg):
    print(f"STATUS: {msg}", flush=True)


def import_to_sqlite(xlsx_path):
    import shutil
    from openpyxl import load_workbook

    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    now = datetime.datetime.now().isoformat()

    conn = sqlite3.connect(str(SQLITE_DB))
    SCHEMA_VERSION = 3
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.executescript("""
            DROP TABLE IF EXISTS diffs;
            DROP TABLE IF EXISTS report_rows;
            DROP TABLE IF EXISTS snapshots;
            DROP TABLE IF EXISTS current_state;
            DROP TABLE IF EXISTS change_log;
            CREATE TABLE current_state (
                machine TEXT NOT NULL,
                lane    TEXT NOT NULL,
                restock INTEGER,
                updated_at TEXT,
                PRIMARY KEY (machine, lane)
            );
            CREATE TABLE change_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at  TEXT NOT NULL,
                machine      TEXT NOT NULL,
                lane         TEXT NOT NULL,
                old_restock  INTEGER,
                new_restock  INTEGER
            );
        """)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    changes = []
    for ws in wb.worksheets:
        machine = ws.title
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            continue
        # locate Restock column from header row
        header = rows[0]
        try:
            restock_idx = next(i for i, h in enumerate(header) if h and str(h).strip().lower() == 'restock')
        except StopIteration:
            continue
        for row in rows[1:]:
            if not row or row[0] is None:
                continue
            lane = str(row[0])
            restock = row[restock_idx] if restock_idx < len(row) else None
            if restock is None:
                continue
            restock = int(restock) if isinstance(restock, float) else restock

            existing = conn.execute(
                "SELECT restock FROM current_state WHERE machine=? AND lane=?",
                (machine, lane)
            ).fetchone()

            if existing is None:
                conn.execute(
                    "INSERT INTO current_state (machine, lane, restock, updated_at) VALUES (?,?,?,?)",
                    (machine, lane, restock, now)
                )
            elif existing[0] != restock:
                conn.execute(
                    "INSERT INTO change_log (detected_at, machine, lane, old_restock, new_restock) VALUES (?,?,?,?,?)",
                    (now, machine, lane, existing[0], restock)
                )
                conn.execute(
                    "UPDATE current_state SET restock=?, updated_at=? WHERE machine=? AND lane=?",
                    (restock, now, machine, lane)
                )
                changes.append({'machine': machine, 'lane': lane, 'old': existing[0], 'new': restock})

    wb.close()
    conn.commit()
    conn.close()

    # keep a persistent copy for next startup, then archive
    shutil.copy2(str(xlsx_path), str(DB_DIR / "last_report.xlsx"))
    tmp_dir = DB_DIR / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    for f in DB_DIR.glob("*.xlsx"):
        shutil.move(str(f), str(tmp_dir / f.name))

    status(f"DB: {len(changes)} restock change(s) detected")
    return changes


async def watch_f9(page, stop_event):
    trigger = DB_DIR / ".f9_trigger"
    LOG_DIR.mkdir(exist_ok=True)
    while not stop_event.is_set():
        if trigger.exists():
            try:
                trigger.unlink()
                html = await page.content()
                out = LOG_DIR / "dom_debug.html"
                out.write_text(html, encoding='utf-8')
                status(f"F9: DOM saved -> {out}")
            except Exception as e:
                status(f"F9: capture failed: {e}")
        await asyncio.sleep(0.3)


async def login(page):
    status("Navigating to login page...")
    await page.goto(LOGIN_URL)
    await page.wait_for_load_state("domcontentloaded")

    for sel in ["#txtUsername", "input[name='txtUsername']", "input[type='text']"]:
        loc = page.locator(sel).first
        if await loc.count() > 0:
            await loc.fill(USERNAME)
            break

    for sel in ["#txtPassword", "input[name='txtPassword']", "input[type='password']"]:
        loc = page.locator(sel).first
        if await loc.count() > 0:
            await loc.fill(PASSWORD)
            break

    for sel in ["#btnLogin", "input[value='Login']", "input[type='submit']", "button[type='submit']"]:
        loc = page.locator(sel).first
        if await loc.count() > 0:
            await loc.click()
            break

    await page.wait_for_url("**/SPDashboard.aspx", timeout=15000)
    status("Login successful")


async def export_excel(page):
    status("Loading replenishment report...")
    await page.goto(REPORT_URL)
    await page.wait_for_load_state("networkidle")

    status("Exporting Excel...")
    async with page.expect_download(timeout=30000) as dl:
        for sel in [
            "input[value='Export Excel']", "#Exporttoexcel",
            "input[value*='Excel']",
        ]:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click()
                break

    download = await dl.value
    filename = download.suggested_filename or "replenishment_report.xlsx"
    save_path = DB_DIR / filename
    await download.save_as(str(save_path))

    status(f"Saved to {save_path}")
    print(f"FILE: {save_path}", flush=True)
    return save_path


async def main():
    xlsx_path = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        stop_event = asyncio.Event()
        f9_task = None
        if not HEADLESS:
            f9_task = asyncio.create_task(watch_f9(page, stop_event))

        await login(page)

        if LOGIN_ONLY:
            status("Browser ready — waiting")
            while not BROWSER_STOP.exists():
                await asyncio.sleep(0.5)
            try: BROWSER_STOP.unlink()
            except: pass
        else:
            xlsx_path = await export_excel(page)

        stop_event.set()
        if f9_task:
            await f9_task

        await browser.close()

        if not HEADLESS and not LOGIN_ONLY:
            input("\nPress Enter to exit...")

    if xlsx_path:
        diffs = import_to_sqlite(xlsx_path)
        if diffs:
            print(f"DIFFS: {json.dumps(diffs, ensure_ascii=False)}", flush=True)


asyncio.run(main())
