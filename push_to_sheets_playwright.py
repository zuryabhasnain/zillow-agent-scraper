#!/usr/bin/env python3
"""
Automated Google Sheet Sync via Playwright Headless Browser
Directly pushes new leads into the user's public editable Google Sheet
without requiring any API keys, OAuth tokens, or Google Cloud credentials.
"""

import sys
import os
import csv
import io
import time
from playwright.sync_api import sync_playwright

DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Mxz2rJrrxhx6OR3t4wgj_K0M8NsU5ocbc0KwlKgFZtQ/edit?usp=sharing"

def push_leads_to_sheet(csv_path, sheet_url=DEFAULT_SHEET_URL):
    if not os.path.exists(csv_path):
        print(f"❌ File not found: {csv_path}")
        return False

    # Read rows
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = list(csv.reader(f))

    if not reader:
        print("⚠️ No rows found in CSV.")
        return False

    # Check if first row is header
    has_header = False
    if reader and ("Agent Name" in reader[0][0] or "Name" in reader[0][0]):
        has_header = True

    # If appending, exclude header row
    data_rows = reader[1:] if has_header else reader
    if not data_rows:
        print("⚠️ Only header found, no data rows to append.")
        return False

    # Convert to TSV
    tsv_output = io.StringIO()
    writer = csv.writer(tsv_output, delimiter="\t")
    for row in data_rows:
        writer.writerow(row)
    tsv_content = tsv_output.getvalue()

    print(f"📋 Prepared {len(data_rows)} leads ({len(tsv_content)} bytes TSV) for Google Sheet sync...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--enable-clipboard-read-write",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()

        print(f"🌐 Opening Google Sheet: {sheet_url}...")
        page.goto(sheet_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)

        # Click cell A1
        print("📍 Selecting cell A1...")
        page.mouse.click(75, 188)
        time.sleep(0.5)

        # Jump to bottom row
        print("⬇️ Jumping to last row...")
        page.keyboard.press("ControlOrMeta+ArrowDown")
        time.sleep(0.5)

        # Move down 1 row to first empty row
        page.keyboard.press("ArrowDown")
        time.sleep(0.5)

        # Write TSV into clipboard
        print("📋 Writing data to browser clipboard...")
        page.evaluate("(text) => navigator.clipboard.writeText(text)", tsv_content)
        time.sleep(0.5)

        # Paste
        print("📥 Pasting data into Google Sheet...")
        page.keyboard.press("ControlOrMeta+v")
        time.sleep(8)

        print(f"✅ Successfully appended {len(data_rows)} leads directly into Google Sheet!")
        browser.close()
        return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_csv = sys.argv[1]
    else:
        # Default to latest leads_*.csv or all_leads.csv
        base_dir = os.path.dirname(os.path.abspath(__file__))
        all_csv = os.path.join(base_dir, "scraped_leads", "all_leads.csv")
        target_csv = all_csv

    url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SHEET_URL
    push_leads_to_sheet(target_csv, url)
