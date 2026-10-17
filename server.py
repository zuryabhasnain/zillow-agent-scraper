import os
import uuid
import asyncio
import threading
import io
import csv
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd

from database import (
    init_db, create_job, get_job, get_all_jobs, update_job_progress,
    add_log, get_job_logs, get_leads, get_leads_count, get_global_metrics,
    get_all_settings, set_all_settings, set_setting, get_setting
)
from scraper_engine import ZillowScraperEngine, normalize_location_to_url
from proxy_manager import ProxyManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("zillow_scraper.server")

# Initialize database tables
init_db()

app = FastAPI(title="Zillow Agent Lead Scraper Pro", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active background worker threads registry
active_threads: Dict[str, threading.Thread] = {}

class CreateJobRequest(BaseModel):
    location: str
    total_pages: Optional[int] = 25
    anti_bot_mode: Optional[str] = None
    delay_min: Optional[float] = None
    delay_max: Optional[float] = None

class SettingsUpdateRequest(BaseModel):
    anti_bot_mode: Optional[str] = "stealth"
    scraperapi_key: Optional[str] = ""
    zenrows_key: Optional[str] = ""
    custom_proxies: Optional[str] = ""
    rotate_proxy_every: Optional[str] = "3"
    delay_min: Optional[str] = "1.5"
    delay_max: Optional[str] = "3.5"
    max_retries: Optional[str] = "3"

def _run_scraper_worker(job_id: str):
    """Background worker executed in dedicated daemon thread"""
    try:
        engine = ZillowScraperEngine(job_id)
        engine.run()
    except Exception as e:
        logger.exception(f"Worker exception for job {job_id}: {e}")
        update_job_progress(job_id, status="failed", error_message=str(e))
        add_log(job_id, "ERROR", f"Worker crashed: {str(e)}")
    finally:
        active_threads.pop(job_id, None)

@app.post("/api/jobs")
def create_scraping_job(payload: CreateJobRequest):
    location = payload.location.strip()
    if not location:
        raise HTTPException(status_code=400, detail="Location or Zillow URL is required")

    total_pages = max(1, min(payload.total_pages or 25, 50))
    zillow_url = normalize_location_to_url(location)
    job_id = f"job_{uuid.uuid4().hex[:8]}"

    config = {}
    if payload.anti_bot_mode:
        config["anti_bot_mode"] = payload.anti_bot_mode
    if payload.delay_min:
        config["delay_min"] = payload.delay_min
    if payload.delay_max:
        config["delay_max"] = payload.delay_max

    job = create_job(job_id, location, zillow_url, total_pages=total_pages, config=config)
    add_log(job_id, "INFO", f"Job created for target: {location} -> {zillow_url}")

    # Launch in background thread so caller can disconnect immediately
    worker_thread = threading.Thread(target=_run_scraper_worker, args=(job_id,), daemon=True)
    active_threads[job_id] = worker_thread
    worker_thread.start()

    return job

@app.get("/api/jobs")
def list_jobs():
    jobs = get_all_jobs()
    # Calculate progress percentage for each job
    for j in jobs:
        total_found = j.get("total_found", 0)
        scraped = j.get("scraped_count", 0)
        j["percent"] = round((scraped / total_found * 100), 1) if total_found > 0 else 0
        j["is_active"] = j["id"] in active_threads
    return jobs

@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    total_found = job.get("total_found", 0)
    scraped = job.get("scraped_count", 0)
    job["percent"] = round((scraped / total_found * 100), 1) if total_found > 0 else 0
    job["is_active"] = job_id in active_threads
    return job

@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    update_job_progress(job_id, status="paused")
    add_log(job_id, "WARNING", "Job paused by user.")
    return {"status": "paused"}

@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    update_job_progress(job_id, status="running")
    add_log(job_id, "INFO", "Job resumed by user.")

    # If thread was not alive, restart worker thread
    if job_id not in active_threads or not active_threads[job_id].is_alive():
        worker_thread = threading.Thread(target=_run_scraper_worker, args=(job_id,), daemon=True)
        active_threads[job_id] = worker_thread
        worker_thread.start()

    return {"status": "running"}

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    update_job_progress(job_id, status="cancelled")
    add_log(job_id, "WARNING", "Job cancelled by user.")
    return {"status": "cancelled"}

@app.get("/api/jobs/{job_id}/logs")
def get_logs(job_id: str, limit: int = 100):
    return get_job_logs(job_id, limit=limit)

@app.get("/api/jobs/{job_id}/stream")
async def stream_job_updates(job_id: str, request: Request):
    """Server-Sent Events (SSE) stream for real-time progress and logs"""
    async def event_generator():
        last_log_id = 0
        while True:
            if await request.is_disconnected():
                break

            job = get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break

            total_found = job.get("total_found", 0)
            scraped = job.get("scraped_count", 0)
            percent = round((scraped / total_found * 100), 1) if total_found > 0 else 0

            logs = get_job_logs(job_id, limit=30)
            new_logs = [l for l in logs if l["id"] > last_log_id]
            if new_logs:
                last_log_id = max(l["id"] for l in new_logs)

            payload = {
                "job": {
                    "id": job["id"],
                    "status": job["status"],
                    "current_page": job["current_page"],
                    "total_pages": job["total_pages"],
                    "total_found": total_found,
                    "scraped_count": scraped,
                    "error_count": job["error_count"],
                    "percent": percent
                },
                "logs": new_logs
            }
            yield f"data: {json.dumps(payload)}\n\n"

            if job["status"] in ["completed", "failed", "cancelled"] and not new_logs:
                # Still keep sending heartbeat every 4 seconds or end
                pass

            await asyncio.sleep(1.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/leads")
def list_leads(
    job_id: Optional[str] = None,
    search: Optional[str] = None,
    has_email: Optional[bool] = None,
    has_phone: Optional[bool] = None,
    page: int = 1,
    limit: int = 50
):
    offset = (page - 1) * limit
    leads = get_leads(job_id=job_id, search=search, has_email=has_email, has_phone=has_phone, limit=limit, offset=offset)
    total_count = get_leads_count(job_id=job_id, search=search, has_email=has_email, has_phone=has_phone)
    return {
        "leads": leads,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1
    }

@app.get("/api/metrics")
def get_metrics():
    return get_global_metrics()

@app.get("/api/settings")
def get_settings():
    return get_all_settings()

@app.post("/api/settings")
def save_settings(settings: SettingsUpdateRequest):
    set_all_settings(settings.dict())
    return {"status": "saved", "settings": get_all_settings()}

@app.post("/api/proxies/test")
def test_proxy():
    settings = get_all_settings()
    pm = ProxyManager(settings)
    return pm.test_connection()

# ----------------------------------------------------------------------
# Export Endpoints (CSV, Excel, Google Sheets Direct Feed)
# ----------------------------------------------------------------------
@app.get("/api/jobs/{job_id}/export/csv")
def export_job_csv(job_id: str):
    job = get_job(job_id)
    leads = get_leads(job_id=job_id, limit=10000)

    output = io.StringIO()
    # Add UTF-8 BOM so Excel & Google Sheets correctly decode characters
    output.write("\ufeff")
    writer = csv.writer(output)

    headers = [
        "Agent Name", "Company / Agency", "Primary Phone", "Cell Phone", "Business Phone",
        "Email", "Full Address", "City", "State", "Zip Code", "Rating", "Review Count",
        "Website", "Zillow Profile URL", "Specialties", "Years in Industry"
    ]
    writer.writerow(headers)

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
            l.get("specialties") or "",
            l.get("years_in_industry") or ""
        ])

    output.seek(0)
    filename = f"zillow_leads_{job_id}_{job.get('target_location', 'export').replace(' ', '_')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/jobs/{job_id}/export/excel")
def export_job_excel(job_id: str):
    job = get_job(job_id)
    leads = get_leads(job_id=job_id, limit=10000)

    rows = []
    for l in leads:
        rows.append({
            "Agent Name": l.get("name") or "",
            "Company / Agency": l.get("business_name") or "",
            "Primary Phone": l.get("primary_phone") or "",
            "Cell Phone": l.get("phone_cell") or "",
            "Business Phone": l.get("phone_business") or "",
            "Email": l.get("email") or "",
            "Full Address": l.get("address") or "",
            "City": l.get("city") or "",
            "State": l.get("state") or "",
            "Zip Code": l.get("zip_code") or "",
            "Rating": l.get("rating"),
            "Review Count": l.get("review_count") or 0,
            "Website": l.get("website_url") or "",
            "Zillow Profile URL": l.get("profile_url") or "",
            "Specialties": l.get("specialties") or "",
            "Years Active": l.get("years_in_industry")
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Zillow Leads")
        # Auto-adjust column widths
        worksheet = writer.sheets["Zillow Leads"]
        for col in worksheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = col[0].column_letter
            worksheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

    output.seek(0)
    filename = f"zillow_leads_{job_id}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/leads/export/csv")
def export_all_leads_csv():
    leads = get_leads(limit=50000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "Agent Name", "Company / Agency", "Primary Phone", "Email",
        "Full Address", "City", "State", "Rating", "Review Count",
        "Website", "Zillow Profile URL"
    ])
    for l in leads:
        writer.writerow([
            l.get("name") or "",
            l.get("business_name") or "",
            l.get("primary_phone") or "",
            l.get("email") or "",
            l.get("address") or "",
            l.get("city") or "",
            l.get("state") or "",
            l.get("rating") or "",
            l.get("review_count") or 0,
            l.get("website_url") or "",
            l.get("profile_url") or ""
        ])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=zillow_all_leads.csv"}
    )

# Static files directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
@app.head("/")
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Zillow Lead Scraper Pro</h1><p>Dashboard UI initializing...</p>")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
