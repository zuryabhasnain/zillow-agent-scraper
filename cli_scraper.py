#!/usr/bin/env bash
import sys
import os
import argparse
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cli_scraper")

from database import init_db, create_job, get_job, get_leads, get_job_logs
from scraper_engine import ZillowScraperEngine, normalize_location_to_url

def run_cli_scrape(location: str, total_pages: int = 25, sheet_webhook: str = ""):
    init_db()
    zillow_url = normalize_location_to_url(location)
    job_id = f"job_cli_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    config = {}
    if sheet_webhook:
        config["google_sheet_webhook_url"] = sheet_webhook

    print("================================================================")
    print(f"🏡 Launching Autonomous Cloud Scraper for: {location}")
    print(f"🔗 Target Directory URL: {zillow_url}")
    print(f"📑 Pages to scrape: {total_pages} (up to ~{total_pages * 15} agent leads)")
    print("================================================================")

    create_job(job_id, location, zillow_url, total_pages=total_pages, config=config)

    engine = ZillowScraperEngine(job_id)
    engine.run()

    job = get_job(job_id)
    leads = get_leads(job_id=job_id, limit=5000)

    print("\n================================================================")
    print(f"✅ Scraping Complete!")
    print(f"📊 Status: {job.get('status')}")
    print(f"👥 Leads Extracted: {len(leads)}")
    print(f"📧 Verified Emails: {sum(1 for l in leads if l.get('email'))}")
    print(f"📞 Verified Phones: {sum(1 for l in leads if l.get('primary_phone'))}")
    print("================================================================\n")

    # Export to individual city CSV
    csv_filename = f"leads_{location.replace(' ', '_').replace(',', '')}.csv"
    import csv
    with open(csv_filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Agent Name", "Company / Agency", "Primary Phone", "Cell Phone", "Business Phone",
            "Email", "Full Address", "City", "State", "Zip Code", "Rating", "Review Count",
            "Website", "Zillow Profile URL", "Specialties"
        ])
        for l in leads:
            writer.writerow([
                l.get("name") or "",
                l.get("business_name") or "",
                l.get("primary_phone") or "",
                l.get("phone_cell") or "",
                l.get("phone_business") or "",
                l.get("email") or "",
                l.get("address") or "",
                l.get("city") or "",
                l.get("state") or "",
                l.get("zip_code") or "",
                l.get("rating") or "",
                l.get("review_count") or 0,
                l.get("website_url") or "",
                l.get("profile_url") or "",
                l.get("specialties") or ""
            ])
    print(f"📁 Leads saved to: {csv_filename}")

    # Master all_leads.csv (deduplicated by profile_url)
    os.makedirs("scraped_leads", exist_ok=True)
    master_csv = "scraped_leads/all_leads.csv"
    existing_urls = set()
    if os.path.exists(master_csv):
        with open(master_csv, "r", encoding="utf-8-sig") as mf:
            reader = csv.reader(mf)
            for row in reader:
                if len(row) > 13:
                    existing_urls.add(row[13])

    is_new_master = not os.path.exists(master_csv)
    with open(master_csv, "a", newline="", encoding="utf-8-sig") as mf:
        writer = csv.writer(mf)
        if is_new_master:
            writer.writerow([
                "Agent Name", "Company / Agency", "Primary Phone", "Cell Phone", "Business Phone",
                "Email", "Full Address", "City", "State", "Zip Code", "Rating", "Review Count",
                "Website", "Zillow Profile URL", "Specialties"
            ])
        for l in leads:
            p_url = l.get("profile_url") or ""
            if p_url and p_url in existing_urls:
                continue
            writer.writerow([
                l.get("name") or "",
                l.get("business_name") or "",
                l.get("primary_phone") or "",
                l.get("phone_cell") or "",
                l.get("phone_business") or "",
                l.get("email") or "",
                l.get("address") or "",
                l.get("city") or "",
                l.get("state") or "",
                l.get("zip_code") or "",
                l.get("rating") or "",
                l.get("review_count") or 0,
                l.get("website_url") or "",
                p_url,
                l.get("specialties") or ""
            ])
            existing_urls.add(p_url)
    print(f"📁 Master leads database updated: {master_csv}")
    return csv_filename

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zillow Agent CLI Cloud Scraper")
    parser.add_argument("location", help="City and State, e.g. 'Austin, TX' or Zillow URL")
    parser.add_argument("--pages", type=int, default=25, help="Number of pages to scrape (default: 25)")
    parser.add_argument("--sheet-webhook", default="", help="Google Sheet Apps Script Webhook URL")

    args = parser.parse_args()
    run_cli_scrape(args.location, total_pages=args.pages, sheet_webhook=args.sheet_webhook)
