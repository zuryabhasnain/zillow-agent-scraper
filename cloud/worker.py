#!/usr/bin/env python3
"""
Zillow Cloud Harvester - worker
================================
Runs on GitHub Actions (no Mac needed). Each worker:
  1. Asks the Google Sheet (via the Apps Script web app) for the next city in the Queue.
  2. Scrapes up to 25 Zillow agent-directory pages for that city.
  3. Asks the sheet which agent profiles are NEW (skips agents already scraped -> no duplicates, no wasted requests).
  4. Scrapes each new profile and saves leads to the sheet in small batches.
  5. Marks the city done (or "retry" if Zillow blocked it) and moves to the next city until its time budget runs out.

Environment variables (set as GitHub Secrets / workflow env):
  SHEET_URL     Apps Script web-app URL (required)
  SHEET_TOKEN   secret token shown by setup() in Apps Script (required)
  ROTATE_CMD    optional shell command that switches to a new IP when Zillow blocks (the workflow sets this for Cloudflare WARP)
  PROXY_URL     optional proxy, e.g. http://user:pass@host:port  (several allowed, comma/newline separated)
  WORKER_ID     label for this worker (default: random)
  MAX_RUNTIME_MIN  stop claiming new work after this many minutes (default 320 - GitHub kills jobs at 360)
  DELAY_MIN / DELAY_MAX  seconds between Zillow requests (defaults depend on proxy)
  PAGES         directory pages per city (default 25 = ~375 agents)
"""
import os
import re
import sys
import json
import time
import random
import logging
import urllib.parse
from datetime import datetime, timezone

import requests as plain_requests  # for the Google Sheet API
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests  # browser-like TLS fingerprint for Zillow
except Exception:  # pragma: no cover
    cffi_requests = None


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("harvester")

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SHEET_URL = os.environ.get("SHEET_URL", "").strip()
SHEET_TOKEN = os.environ.get("SHEET_TOKEN", "").strip()
PROXIES = [p.strip() for p in re.split(r"[,\n]", os.environ.get("PROXY_URL", "")) if p.strip()]
WORKER_ID = os.environ.get("WORKER_ID") or f"w{random.randint(1000, 9999)}"
MAX_RUNTIME_MIN = float(os.environ.get("MAX_RUNTIME_MIN", "320"))
PAGES = int(os.environ.get("PAGES", "25"))
if PROXIES:
    DELAY_MIN = float(os.environ.get("DELAY_MIN") or 0.8)
    DELAY_MAX = float(os.environ.get("DELAY_MAX") or 2.0)
else:
    DELAY_MIN = float(os.environ.get("DELAY_MIN") or 2.0)
    DELAY_MAX = float(os.environ.get("DELAY_MAX") or 4.5)

ROTATE_CMD = os.environ.get("ROTATE_CMD", "").strip()   # shell command that gets a new IP (e.g. WARP re-register)
MAX_ROTATIONS = int(os.environ.get("MAX_ROTATIONS", "300"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "8"))
RETRY_SLEEP_MIN = float(os.environ.get("RETRY_SLEEP_MIN", "0.5"))   # Zillow blocks at random, so a quick retry
RETRY_SLEEP_MAX = float(os.environ.get("RETRY_SLEEP_MAX", "2.5"))   # usually gets through - no long back-off
BLOCK_STREAK_LIMIT = 8      # this many failed fetches in a row = we're blocked
SAVE_BATCH = 20             # leads per write to the sheet
START = time.time()

IMPERSONATE = ["chrome124", "chrome120", "chrome119", "safari17_0", "edge101"]
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

EMAIL_FIND_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_RE = re.compile(r"\(?\b[2-9][0-9]{2}\)?[-. ]?[0-9]{3}[-. ]?[0-9]{4}\b")

# Must match the column order in apps_script.gs (LEAD_HEADERS)
LEAD_FIELDS = [
    "name", "business_name", "email", "primary_phone", "phone_cell",
    "phone_business", "address", "city", "state", "zip_code", "rating", "review_count",
    "website_url", "profile_url", "specialties", "years_in_industry", "search_city",
    "search_state", "scraped_at",
]


class Blocked(Exception):
    """Zillow is blocking this worker's IP."""


class OutOfTime(Exception):
    pass


def minutes_used() -> float:
    return (time.time() - START) / 60.0


# ----------------------------------------------------------------------------
# Google Sheet API (Apps Script web app)
# ----------------------------------------------------------------------------
def sheet(action: str, **payload):
    body = {"token": SHEET_TOKEN, "action": action, **payload}
    last_err = None
    for attempt in range(1, 6):
        try:
            # Apps Script answers POST with a 302 to googleusercontent; requests follows it.
            r = plain_requests.post(SHEET_URL, data=json.dumps(body),
                                    headers={"Content-Type": "text/plain"}, timeout=120)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error") or f"sheet error on {action}")
            return data
        except Exception as e:  # network hiccup / lock timeout -> retry
            last_err = e
            if "bad token" in str(e):
                break
            time.sleep(5 * attempt)
    raise RuntimeError(f"Sheet API '{action}' failed: {last_err}")


# ----------------------------------------------------------------------------
# Email cleanup (no verification - just tidy the text)
# ----------------------------------------------------------------------------
def clean_email(raw: str) -> str:
    e = (raw or "").strip().strip(".,;:<>()[]\"'").replace("mailto:", "")
    return e


# ----------------------------------------------------------------------------
# Zillow fetching
# ----------------------------------------------------------------------------
_proxy_i = 0


def _next_proxy():
    global _proxy_i
    if not PROXIES:
        return None
    p = PROXIES[_proxy_i % len(PROXIES)]
    _proxy_i += 1
    return {"http": p, "https": p}


def _headers(referer=None):
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
    }
    if referer:
        h["Referer"] = referer
    return h


def parse_next_data(html: str):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except Exception:
            return None
    return None


class Fetcher:
    def __init__(self):
        self.fail_streak = 0
        self.requests = 0
        self.failures = 0
        self.last_404 = False

    def get_hard(self, url, referer=None):
        """Like get(), but when a page still fails it switches to a new IP and tries once more."""
        html, data = self.get(url, referer)
        if data is None and not self.last_404 and rotate_ip():
            self.fail_streak = max(0, self.fail_streak - 1)
            html, data = self.get(url, referer)
        return html, data

    def get(self, url, referer=None):
        """Returns (html, next_data) or (None, None) after retries. Raises Blocked on a long failure streak."""
        self.last_404 = False
        for attempt in range(1, MAX_RETRIES + 1):
            self.requests += 1
            try:
                r = cffi_requests.get(url, headers=_headers(referer), proxies=_next_proxy(),
                                      impersonate=random.choice(IMPERSONATE), timeout=30)
                status = r.status_code
                text = r.text if status == 200 else ""
            except Exception as e:
                status, text = -1, ""
                log.warning(f"request error {url}: {e}")

            if status == 200:
                data = parse_next_data(text)
                if data is not None:
                    self.fail_streak = 0
                    return text, data
                # 200 without page data = captcha / challenge page
                status = "captcha"
            if status == 404:
                self.last_404 = True
                self.fail_streak = 0
                return None, None
            log.warning(f"HTTP {status} on {url} (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(random.uniform(RETRY_SLEEP_MIN, RETRY_SLEEP_MAX))

        self.failures += 1
        self.fail_streak += 1
        if self.fail_streak >= BLOCK_STREAK_LIMIT:
            raise Blocked(f"{self.fail_streak} failed pages in a row")
        return None, None


def jitter():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def directory_url(city: str, state: str) -> str:
    s = f"{city} {state}".lower().replace("'", "").replace(".", "")
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    slug = "-".join(p for p in re.split(r"[\s-]+", s) if p)
    return f"https://www.zillow.com/professionals/real-estate-agent-reviews/{slug}/"


def normalize_profile_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not u.startswith("http"):
        u = urllib.parse.urljoin("https://www.zillow.com", u)
    u = u.split("?")[0].split("#")[0].rstrip("/")
    return u


def parse_cards(next_data):
    try:
        cards = (next_data["props"]["pageProps"]["displayData"]["agentDirectoryFinderDisplay"]
                 ["searchResults"]["results"]["resultsCards"]) or []
    except (KeyError, TypeError):
        return None  # page structure missing
    out = []
    for c in cards:
        link = c.get("cardActionLink")
        if not link:
            continue
        out.append({
            "profile_url": normalize_profile_url(link),
            "name": c.get("cardTitle") or "",
            "business_name": c.get("secondaryCardTitle") or "",
            "rating": (c.get("reviewInformation") or {}).get("reviewAverage"),
            "review_count": (c.get("reviewInformation") or {}).get("reviewCount") or 0,
        })
    return out


def parse_profile(html, next_data, stub, city, state):
    pp = (next_data or {}).get("props", {}).get("pageProps", {}) or {}
    user = pp.get("displayUser") or {}
    know = pp.get("getToKnowMe") or {}
    addr = user.get("businessAddress") or {}
    phones = user.get("phoneNumbers") or {}
    ratings = user.get("ratings") or {}

    cell = phones.get("cell") or ""
    biz = phones.get("business") or ""
    primary = cell or biz or phones.get("brokerage") or ""
    if not primary and html:
        m = PHONE_RE.findall(html)
        primary = m[0] if m else ""

    email = clean_email(user.get("email") or "")
    if not email and html:
        found = [e for e in EMAIL_FIND_RE.findall(html)
                 if not any(x in e.lower() for x in ("zillow", "sentry", "w3.org", "schema", "example", ".png", ".jpg"))]
        email = clean_email(found[0]) if found else ""

    a_city = addr.get("city") or ""
    a_state = addr.get("state") or ""
    parts = [p for p in [addr.get("address1"), a_city, a_state, addr.get("postalCode")] if p]
    address = ", ".join(parts)
    if not address:
        areas = pp.get("serviceAreas") or []
        if areas and isinstance(areas, list):
            address = (areas[0] or {}).get("text") or ""

    specs = know.get("specialties") or []
    specs = ", ".join(specs) if isinstance(specs, list) else str(specs)
    rating = ratings.get("average") or stub.get("rating")
    reviews = ratings.get("count") or stub.get("review_count") or 0

    return {
        "name": user.get("name") or stub.get("name") or "",
        "business_name": user.get("businessName") or stub.get("business_name") or "",
        "email": email,
        "primary_phone": primary,
        "phone_cell": cell,
        "phone_business": biz,
        "address": address,
        "city": a_city,
        "state": a_state,
        "zip_code": addr.get("postalCode") or "",
        "rating": rating if rating is not None else "",
        "review_count": reviews,
        "website_url": know.get("websiteUrl") or "",
        "profile_url": stub["profile_url"],
        "specialties": specs,
        "years_in_industry": know.get("yearsInIndustry") or "",
        "search_city": city,
        "search_state": state,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    }


# ----------------------------------------------------------------------------
# One city
# ----------------------------------------------------------------------------
def scrape_city(job, fetcher: Fetcher) -> dict:
    city, state = job["city"], job["state"]
    base = directory_url(city, state)
    stats = {"found": 0, "new": 0, "saved": 0, "with_email": 0, "failed_pages": 0,
             "failed_profiles": 0, "status": "done", "note": ""}

    # --- Phase 1: directory pages ---
    stubs, seen = [], set()
    for page in range(1, PAGES + 1):
        if minutes_used() > MAX_RUNTIME_MIN + 15:
            raise OutOfTime()
        url = base if page == 1 else f"{base}?page={page}"
        html, data = fetcher.get_hard(url)
        if data is None:
            stats["failed_pages"] += 1
            if page == 1 and html is None and fetcher.fail_streak == 0:
                stats.update(status="no_results", note=f"Zillow page not found: {base}")
                return stats
            jitter()
            continue
        cards = parse_cards(data)
        if not cards:
            if page == 1:
                stats.update(status="no_results", note=f"No agents listed at {base}")
                return stats
            break  # past the last page
        for c in cards:
            if c["profile_url"] and c["profile_url"].lower() not in seen:
                seen.add(c["profile_url"].lower())
                stubs.append(c)
        log.info(f"[{state}] {city}: page {page} -> {len(cards)} agents (total {len(stubs)})")
        jitter()

    stats["found"] = len(stubs)
    if stats["failed_pages"] > PAGES * 0.4 and len(stubs) < 150:
        stats.update(status="retry", note=f"{stats['failed_pages']} directory pages failed")

    # --- Phase 2: only profiles not already in the sheet ---
    new_urls = set()
    for i in range(0, len(stubs), 200):
        chunk = [s["profile_url"] for s in stubs[i:i + 200]]
        new_urls.update(u.lower() for u in sheet("filter_new", urls=chunk)["new"])
    todo = [s for s in stubs if s["profile_url"].lower() in new_urls]
    stats["new"] = len(todo)
    log.info(f"[{state}] {city}: {len(stubs)} agents found, {len(todo)} new (skipping {len(stubs) - len(todo)} already scraped)")

    buffer = []

    def flush():
        if buffer:
            res = sheet("append_leads", rows=[[r[f] for f in LEAD_FIELDS] for r in buffer])
            stats["saved"] += res.get("added", 0)
            buffer.clear()

    try:
        for idx, stub in enumerate(todo, 1):
            if minutes_used() > MAX_RUNTIME_MIN + 15:
                raise OutOfTime()
            html, data = fetcher.get(stub["profile_url"], referer=base)
            if data is None:
                stats["failed_profiles"] += 1
                jitter()
                continue
            try:
                rec = parse_profile(html, data, stub, city, state)
            except Exception as e:
                log.warning(f"parse error {stub['profile_url']}: {e}")
                stats["failed_profiles"] += 1
                continue
            if rec["email"]:
                stats["with_email"] += 1
            buffer.append(rec)
            if len(buffer) >= SAVE_BATCH:
                flush()
                log.info(f"[{state}] {city}: {idx}/{len(todo)} profiles, {stats['saved']} saved")
            jitter()
    finally:
        flush()  # never lose scraped leads, even when blocked / out of time

    if todo and stats["failed_profiles"] > len(todo) * 0.3:
        stats.update(status="retry", note=f"{stats['failed_profiles']} profiles failed (will resume, saved ones are skipped)")
    return stats


# ----------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------
_rotations = 0


def rotate_ip() -> bool:
    """Runs ROTATE_CMD to get a fresh IP. Returns False when rotation isn't possible."""
    global _rotations
    if not ROTATE_CMD or _rotations >= MAX_ROTATIONS:
        return False
    _rotations += 1
    log.info(f"Rotating IP ({_rotations}/{MAX_ROTATIONS})...")
    rc = os.system(ROTATE_CMD)
    time.sleep(8)
    if rc != 0:
        log.warning(f"rotate command exited with {rc}")
    return True


def main():
    if not SHEET_URL or not SHEET_TOKEN:
        log.error("SHEET_URL and SHEET_TOKEN secrets are not set. See CLOUD_SETUP.md.")
        sys.exit(1)
    if cffi_requests is None:
        log.error("curl_cffi is not installed")
        sys.exit(1)

    log.info(f"Worker {WORKER_ID} starting | proxy: {'yes (' + str(len(PROXIES)) + ')' if PROXIES else 'NO - GitHub IP (expect blocks)'}"
             f" | delay {DELAY_MIN}-{DELAY_MAX}s | budget {MAX_RUNTIME_MIN} min")

    fetcher = Fetcher()
    cities_done = 0
    while minutes_used() < MAX_RUNTIME_MIN:
        job = sheet("claim", worker=WORKER_ID).get("job")
        if not job:
            log.info("Queue is empty - nothing left to scrape. 🎉")
            break
        log.info(f"=== Claimed #{job['row'] - 1}: {job['city']}, {job['state']} ===")
        t0 = time.time()
        try:
            while True:
                try:
                    stats = scrape_city(job, fetcher)
                    break
                except Blocked as b:
                    if not rotate_ip():
                        raise
                    log.warning(f"Blocked ({b}) - new IP, resuming {job['city']} (saved agents are skipped)")
                    fetcher.fail_streak = 0
        except Blocked as b:
            log.error(f"Blocked by Zillow ({b}) and no more IP changes left. Releasing city and stopping this worker - the next run starts fresh.")
            sheet("finish", row=job["row"], worker=WORKER_ID, status="blocked",
                  note=f"Blocked: {b}", stats={})
            break
        except OutOfTime:
            log.info("Time budget reached mid-city; releasing it (saved leads are kept and skipped next time).")
            sheet("finish", row=job["row"], worker=WORKER_ID, status="pending", note="Paused at time limit", stats={})
            break
        except Exception as e:
            log.exception(f"Error on {job['city']}: {e}")
            sheet("finish", row=job["row"], worker=WORKER_ID, status="retry", note=f"Error: {e}"[:200], stats={})
            continue
        stats["minutes"] = round((time.time() - t0) / 60, 1)
        sheet("finish", row=job["row"], worker=WORKER_ID, status=stats.pop("status"),
              note=stats.pop("note"), stats=stats)
        cities_done += 1
        log.info(f"=== {job['city']}, {job['state']} finished: {stats} ===")

    log.info(f"Worker {WORKER_ID} done: {cities_done} cities, {fetcher.requests} requests, {minutes_used():.0f} min")


if __name__ == "__main__":
    main()
