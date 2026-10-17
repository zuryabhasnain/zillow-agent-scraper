import sqlite3
import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "leads.db"))

logger = logging.getLogger("zillow_scraper.database")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Table for Scraping Jobs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        target_location TEXT NOT NULL,
        zillow_url TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued', -- queued, running, paused, completed, cancelled, failed
        total_pages INTEGER DEFAULT 25,
        current_page INTEGER DEFAULT 0,
        total_found INTEGER DEFAULT 0,
        scraped_count INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        config_json TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
    """)

    # Table for Scraped Agent Leads
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        zuid TEXT,
        name TEXT NOT NULL,
        business_name TEXT,
        phone_cell TEXT,
        phone_business TEXT,
        phone_brokerage TEXT,
        primary_phone TEXT,
        email TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        zip_code TEXT,
        rating REAL,
        review_count INTEGER DEFAULT 0,
        website_url TEXT,
        profile_url TEXT NOT NULL UNIQUE,
        photo_url TEXT,
        specialties TEXT,
        service_areas TEXT,
        years_in_industry INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs (id)
    )
    """)

    # Index on profile_url and job_id for fast lookups
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_job_id ON leads(job_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_profile_url ON leads(profile_url)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city)")

    # Table for Global Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

    # Table for Job Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        level TEXT NOT NULL, -- INFO, SUCCESS, WARNING, ERROR, PROXY
        message TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs (id)
    )
    """)

    # Seed default settings if empty
    defaults = {
        "anti_bot_mode": "stealth", # stealth, scraperapi, zenrows, custom_pool
        "scraperapi_key": "",
        "zenrows_key": "",
        "custom_proxies": "",
        "rotate_proxy_every": "3",
        "delay_min": "1.5",
        "delay_max": "3.5",
        "max_retries": "3"
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully at %s", DB_PATH)

def create_job(job_id: str, location: str, zillow_url: str, total_pages: int = 25, config: dict = None) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    config_json = json.dumps(config or {})
    cursor.execute("""
        INSERT INTO jobs (id, target_location, zillow_url, total_pages, config_json, status)
        VALUES (?, ?, ?, ?, ?, 'queued')
    """, (job_id, location, zillow_url, total_pages, config_json))
    conn.commit()
    conn.close()
    return get_job(job_id)

def get_job(job_id: str) -> Optional[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("config_json"):
        try:
            d["config"] = json.loads(d["config_json"])
        except Exception:
            d["config"] = {}
    return d

def get_all_jobs() -> List[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("config_json"):
            try:
                d["config"] = json.loads(d["config_json"])
            except Exception:
                d["config"] = {}
        result.append(d)
    return result

def update_job_progress(job_id: str, **kwargs):
    conn = get_db()
    cursor = conn.cursor()
    fields = []
    values = []
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        values.append(v)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(job_id)
    query = f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?"
    cursor.execute(query, values)
    conn.commit()
    conn.close()

def add_log(job_id: str, level: str, message: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO logs (job_id, level, message) VALUES (?, ?, ?)", (job_id, level, message))
    conn.commit()
    conn.close()

def get_job_logs(job_id: str, limit: int = 150) -> List[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs WHERE job_id = ? ORDER BY id DESC LIMIT ?", (job_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

def save_lead(lead_data: dict) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO leads (
                job_id, zuid, name, business_name, phone_cell, phone_business,
                phone_brokerage, primary_phone, email, address, city, state, zip_code,
                rating, review_count, website_url, profile_url, photo_url, specialties,
                service_areas, years_in_industry
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_url) DO UPDATE SET
                job_id=excluded.job_id,
                name=excluded.name,
                business_name=excluded.business_name,
                phone_cell=COALESCE(excluded.phone_cell, leads.phone_cell),
                phone_business=COALESCE(excluded.phone_business, leads.phone_business),
                phone_brokerage=COALESCE(excluded.phone_brokerage, leads.phone_brokerage),
                primary_phone=COALESCE(excluded.primary_phone, leads.primary_phone),
                email=COALESCE(excluded.email, leads.email),
                address=COALESCE(excluded.address, leads.address),
                city=COALESCE(excluded.city, leads.city),
                state=COALESCE(excluded.state, leads.state),
                zip_code=COALESCE(excluded.zip_code, leads.zip_code),
                rating=COALESCE(excluded.rating, leads.rating),
                review_count=COALESCE(excluded.review_count, leads.review_count),
                website_url=COALESCE(excluded.website_url, leads.website_url),
                photo_url=COALESCE(excluded.photo_url, leads.photo_url),
                specialties=COALESCE(excluded.specialties, leads.specialties),
                service_areas=COALESCE(excluded.service_areas, leads.service_areas),
                years_in_industry=COALESCE(excluded.years_in_industry, leads.years_in_industry)
        """, (
            lead_data.get("job_id"),
            lead_data.get("zuid"),
            lead_data.get("name"),
            lead_data.get("business_name"),
            lead_data.get("phone_cell"),
            lead_data.get("phone_business"),
            lead_data.get("phone_brokerage"),
            lead_data.get("primary_phone"),
            lead_data.get("email"),
            lead_data.get("address"),
            lead_data.get("city"),
            lead_data.get("state"),
            lead_data.get("zip_code"),
            lead_data.get("rating"),
            lead_data.get("review_count", 0),
            lead_data.get("website_url"),
            lead_data.get("profile_url"),
            lead_data.get("photo_url"),
            lead_data.get("specialties"),
            lead_data.get("service_areas"),
            lead_data.get("years_in_industry")
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error("Failed to save lead: %s", e)
        return False
    finally:
        conn.close()

def get_leads(job_id: Optional[str] = None, search: Optional[str] = None, has_email: Optional[bool] = None,
              has_phone: Optional[bool] = None, limit: int = 1000, offset: int = 0) -> List[dict]:
    conn = get_db()
    cursor = conn.cursor()
    conditions = []
    params = []

    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)

    if search:
        s = f"%{search.strip()}%"
        conditions.append("(name LIKE ? OR business_name LIKE ? OR city LIKE ? OR state LIKE ? OR email LIKE ? OR primary_phone LIKE ?)")
        params.extend([s, s, s, s, s, s])

    if has_email:
        conditions.append("email IS NOT NULL AND email != ''")

    if has_phone:
        conditions.append("primary_phone IS NOT NULL AND primary_phone != ''")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"SELECT * FROM leads {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_leads_count(job_id: Optional[str] = None, search: Optional[str] = None, has_email: Optional[bool] = None,
                    has_phone: Optional[bool] = None) -> int:
    conn = get_db()
    cursor = conn.cursor()
    conditions = []
    params = []

    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)

    if search:
        s = f"%{search.strip()}%"
        conditions.append("(name LIKE ? OR business_name LIKE ? OR city LIKE ? OR state LIKE ? OR email LIKE ? OR primary_phone LIKE ?)")
        params.extend([s, s, s, s, s, s])

    if has_email:
        conditions.append("email IS NOT NULL AND email != ''")

    if has_phone:
        conditions.append("primary_phone IS NOT NULL AND primary_phone != ''")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"SELECT COUNT(*) FROM leads {where_clause}"
    cursor.execute(query, params)
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_global_metrics() -> dict:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM leads")
    total_leads = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM leads WHERE email IS NOT NULL AND email != ''")
    emails_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM leads WHERE primary_phone IS NOT NULL AND primary_phone != ''")
    phones_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'")
    active_jobs = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM jobs")
    total_jobs = cursor.fetchone()[0]

    conn.close()
    return {
        "total_leads": total_leads,
        "emails_count": emails_count,
        "phones_count": phones_count,
        "active_jobs": active_jobs,
        "total_jobs": total_jobs
    }

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def get_all_settings() -> dict:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()
    conn.close()

def set_all_settings(settings_dict: dict):
    conn = get_db()
    cursor = conn.cursor()
    for k, v in settings_dict.items():
        cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))
    conn.commit()
    conn.close()
