"""
DVends Replenishment Report Exporter
Usage: python open_vending.py [--headless]
"""

import asyncio
import os
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


def status(msg):
    print(f"STATUS: {msg}", flush=True)


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


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        await login(page)
        await export_excel(page)
        await browser.close()

        if not HEADLESS:
            input("\nPress Enter to exit...")


asyncio.run(main())
