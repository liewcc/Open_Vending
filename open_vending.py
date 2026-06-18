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

DB_DIR = Path(__file__).parent / "db"
DB_DIR.mkdir(exist_ok=True)

HEADLESS = "--headless" in sys.argv

LOGIN_URL  = "https://vendingportal.azurewebsites.net/SuperAdmin/SPLogin.aspx"
REPORT_URL = "https://vendingportal.azurewebsites.net/SuperAdmin/SPReplenishmentV2.aspx"


SQLITE_DB = DB_DIR / "data.db"


def status(msg):
    print(f"STATUS: {msg}", flush=True)


def import_to_sqlite(xlsx_path):
    from openpyxl import load_workbook

    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    wb.close()

    if len(rows) < 2:
        return []

    headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    data_rows = rows[1:]

    conn = sqlite3.connect(str(SQLITE_DB))
    # ponytail: bump this whenever the schema changes
    SCHEMA_VERSION = 2
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.executescript("""
            DROP TABLE IF EXISTS diffs;
            DROP TABLE IF EXISTS report_rows;
            DROP TABLE IF EXISTS snapshots;
        """)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            downloaded_at TEXT NOT NULL,
            filename TEXT NOT NULL,
            row_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            row_data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS diffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at TEXT NOT NULL,
            new_snapshot_id INTEGER NOT NULL,
            old_snapshot_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            col_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT
        );
    """)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()

    now = datetime.datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO snapshots (downloaded_at, filename, row_count) VALUES (?, ?, ?)",
        (now, xlsx_path.name, len(data_rows))
    )
    new_id = cur.lastrowid

    prev = conn.execute(
        "SELECT id FROM snapshots WHERE id != ? ORDER BY id DESC LIMIT 1",
        (new_id,)
    ).fetchone()
    old_id = prev[0] if prev else None

    new_row_data = {}
    for idx, row in enumerate(data_rows):
        row_dict = {headers[i]: (str(v) if v is not None else '') for i, v in enumerate(row)}
        row_json = json.dumps(row_dict, ensure_ascii=False)
        conn.execute(
            "INSERT INTO report_rows (snapshot_id, row_index, row_data) VALUES (?, ?, ?)",
            (new_id, idx, row_json)
        )
        new_row_data[idx] = row_dict

    diff_list = []
    if old_id:
        old_rows = conn.execute(
            "SELECT row_index, row_data FROM report_rows WHERE snapshot_id = ?",
            (old_id,)
        ).fetchall()
        old_row_data = {r[0]: json.loads(r[1]) for r in old_rows}

        for row_idx, new_vals in new_row_data.items():
            if row_idx not in old_row_data:
                continue
            old_vals = old_row_data[row_idx]
            for col in headers:
                old_v = old_vals.get(col, '')
                new_v = new_vals.get(col, '')
                if old_v != new_v:
                    conn.execute(
                        "INSERT INTO diffs"
                        " (detected_at, new_snapshot_id, old_snapshot_id, row_index, col_name, old_value, new_value)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (now, new_id, old_id, row_idx, col, old_v, new_v)
                    )
                    diff_list.append({'row': row_idx + 1, 'col': col, 'old': old_v, 'new': new_v})

    conn.commit()
    conn.close()

    if old_id:
        status(f"DB: {len(diff_list)} field changes vs previous snapshot")
    else:
        status(f"DB: initialized with {len(data_rows)} rows")

    return diff_list


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

    all_values = await page.eval_on_selector(
        "#checkbox",
        "el => Array.from(el.options).map(o => o.value)"
    )
    await page.select_option("#checkbox", all_values)
    status(f"Selected all {len(all_values)} franchises")

    status("Exporting Excel...")
    async with page.expect_download(timeout=30000) as dl:
        for sel in [
            "input[value='EXPORT EXCEL']", "button:has-text('EXPORT EXCEL')",
            "a:has-text('EXPORT EXCEL')", "input[value*='Excel']",
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

        await login(page)
        xlsx_path = await export_excel(page)
        await browser.close()

        if not HEADLESS:
            input("\nPress Enter to exit...")

    if xlsx_path:
        diffs = import_to_sqlite(xlsx_path)
        if diffs:
            print(f"DIFFS: {json.dumps(diffs, ensure_ascii=False)}", flush=True)


asyncio.run(main())
