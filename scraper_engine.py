import re
import json
import time
import random
import logging
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from bs4 import BeautifulSoup
from curl_cffi import requests

from database import (
    get_job, update_job_progress, add_log, save_lead,
    get_all_settings
)
from proxy_manager import ProxyManager

logger = logging.getLogger("zillow_scraper.engine")

US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc"
}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"\(?\b[2-9][0-9]{2}\)?[-. ]?[0-9]{3}[-. ]?[0-9]{4}\b")

def normalize_location_to_url(location_input: str) -> str:
    s = location_input.strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s

    # 5 digit zip code
    if re.match(r"^\d{5}$", s):
        return f"https://www.zillow.com/professionals/real-estate-agent-reviews/{s}/"

    # Normalize state names (e.g. "Austin, Texas" -> "Austin, TX")
    lower = s.lower()
    for full_state, abbr in US_STATES.items():
        if full_state in lower:
            lower = re.sub(r"\b" + re.escape(full_state) + r"\b", abbr, lower)
            break

    # Clean characters and convert to slug
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", lower).strip()
    slug_parts = [p.strip() for p in cleaned.replace("-", " ").split() if p.strip()]
    slug = "-".join(slug_parts)
    return f"https://www.zillow.com/professionals/real-estate-agent-reviews/{slug}/"

class ZillowScraperEngine:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.job = get_job(job_id)
        if not self.job:
            raise ValueError(f"Job {job_id} not found in database")

        self.settings = get_all_settings()
        # Merge job-specific config overrides if provided
        job_config = self.job.get("config", {})
        self.settings.update({k: str(v) for k, v in job_config.items() if v is not None})

        self.proxy_manager = ProxyManager(self.settings)

        self.delay_min = float(self.settings.get("delay_min", 1.5))
        self.delay_max = float(self.settings.get("delay_max", 3.5))
        self.max_retries = int(self.settings.get("max_retries", 3))

    def _sleep_jitter(self):
        duration = random.uniform(self.delay_min, self.delay_max)
        time.sleep(duration)

    def _fetch_page(self, url: str, referer: Optional[str] = None) -> Tuple[Optional[str], Optional[dict]]:
        """Fetches page content with proxy rotation and anti-bot retry logic"""
        for attempt in range(1, self.max_retries + 1):
            # Check if job was cancelled or paused
            job_state = get_job(self.job_id)
            if not job_state or job_state["status"] in ["cancelled", "paused"]:
                return None, None

            eff_url, proxies, impersonate, proxy_label = self.proxy_manager.get_request_params(url)
            headers = self.proxy_manager.get_headers(referer=referer)

            try:
                r = requests.get(
                    eff_url,
                    proxies=proxies,
                    headers=headers,
                    impersonate=impersonate,
                    timeout=25
                )

                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    next_script = soup.find("script", id="__NEXT_DATA__")
                    if next_script and next_script.string:
                        try:
                            data = json.loads(next_script.string)
                            return r.text, data
                        except Exception as e:
                            logger.warning(f"Failed to parse __NEXT_DATA__ on attempt {attempt}: {e}")
                    # If HTML exists but no NEXT_DATA (unusual)
                    return r.text, None

                elif r.status_code in [403, 429, 503]:
                    add_log(self.job_id, "WARNING", f"Anti-bot challenge/rate-limit (HTTP {r.status_code}) on {url}. Attempt {attempt}/{self.max_retries} via {proxy_label}.")
                    self.proxy_manager.rotate_on_failure()
                    time.sleep(2 ** attempt)
                else:
                    add_log(self.job_id, "WARNING", f"HTTP {r.status_code} fetching {url}. Attempt {attempt}/{self.max_retries}")
                    time.sleep(2)

            except Exception as e:
                add_log(self.job_id, "WARNING", f"Request exception: {str(e)} on attempt {attempt}/{self.max_retries} via {proxy_label}")
                self.proxy_manager.rotate_on_failure()
                time.sleep(2)

        add_log(self.job_id, "ERROR", f"Failed to fetch {url} after {self.max_retries} attempts.")
        return None, None

    def run(self):
        """Main execution loop for the scraping job"""
        try:
            update_job_progress(self.job_id, status="running")
            add_log(self.job_id, "INFO", f"Starting scraping job for '{self.job['target_location']}' (Total Pages: {self.job['total_pages']})")

            base_dir_url = self.job["zillow_url"]
            total_pages = self.job["total_pages"] or 25
            discovered_agents: List[Dict[str, Any]] = []

            # ------------------------------------------------------------------
            # Phase 1: Directory Traversal across pages (up to 25 pages = 375 leads)
            # ------------------------------------------------------------------
            for page_num in range(1, total_pages + 1):
                # Check status (e.g. user requested pause or cancel)
                curr_job = get_job(self.job_id)
                if not curr_job or curr_job["status"] == "cancelled":
                    add_log(self.job_id, "WARNING", "Job was cancelled by user.")
                    return
                while curr_job and curr_job["status"] == "paused":
                    time.sleep(3)
                    curr_job = get_job(self.job_id)

                page_url = f"{base_dir_url.rstrip('/')}/?page={page_num}" if page_num > 1 else base_dir_url
                add_log(self.job_id, "INFO", f"Scraping directory Page {page_num} of {total_pages} ({page_url})...")

                html_text, next_data = self._fetch_page(page_url)
                if not next_data:
                    add_log(self.job_id, "WARNING", f"Could not extract __NEXT_DATA__ for Page {page_num}. Trying next page...")
                    update_job_progress(self.job_id, current_page=page_num, error_count=self.job.get("error_count", 0) + 1)
                    continue

                # Extract agent cards from searchResults
                try:
                    display_data = next_data["props"]["pageProps"]["displayData"]["agentDirectoryFinderDisplay"]
                    search_results = display_data.get("searchResults", {})
                    results_obj = search_results.get("results", {})
                    cards = results_obj.get("resultsCards", [])
                except KeyError:
                    cards = []

                if not cards:
                    add_log(self.job_id, "WARNING", f"No agent cards found on Page {page_num}. May have reached the end of results.")
                    break

                page_agent_count = 0
                for c in cards:
                    action_link = c.get("cardActionLink")
                    if not action_link:
                        continue
                    if not action_link.startswith("http"):
                        action_link = urllib.parse.urljoin("https://www.zillow.com", action_link)

                    agent_stub = {
                        "cardTitle": c.get("cardTitle"),
                        "secondaryCardTitle": c.get("secondaryCardTitle"),
                        "encodedZuid": c.get("encodedZuid"),
                        "imageUrl": c.get("imageUrl"),
                        "profileUrl": action_link,
                        "rating": (c.get("reviewInformation") or {}).get("reviewAverage"),
                        "reviewCount": (c.get("reviewInformation") or {}).get("reviewCount", 0),
                        "page_found": page_num
                    }
                    discovered_agents.append(agent_stub)
                    page_agent_count += 1

                total_found = len(discovered_agents)
                update_job_progress(self.job_id, current_page=page_num, total_found=total_found)
                add_log(self.job_id, "SUCCESS", f"Page {page_num}: Discovered {page_agent_count} agents (Total Found: {total_found})")

                # Jitter delay between directory pages
                self._sleep_jitter()

            add_log(self.job_id, "INFO", f"Phase 1 Complete: Found {len(discovered_agents)} agent profiles to scrape.")

            # ------------------------------------------------------------------
            # Phase 2: Full Profile Details Extraction
            # ------------------------------------------------------------------
            scraped_count = 0
            error_count = 0

            for idx, agent_stub in enumerate(discovered_agents, start=1):
                # Check status
                curr_job = get_job(self.job_id)
                if not curr_job or curr_job["status"] == "cancelled":
                    add_log(self.job_id, "WARNING", "Job was cancelled by user during profile scraping.")
                    return
                while curr_job and curr_job["status"] == "paused":
                    time.sleep(3)
                    curr_job = get_job(self.job_id)

                profile_url = agent_stub["profileUrl"]
                agent_name_preview = agent_stub.get("cardTitle") or f"Agent #{idx}"
                add_log(self.job_id, "INFO", f"[{idx}/{len(discovered_agents)}] Scraping profile: {agent_name_preview}...")

                p_html, p_next = self._fetch_page(profile_url, referer=base_dir_url)

                if not p_next:
                    add_log(self.job_id, "WARNING", f"Could not load profile details for {profile_url}")
                    error_count += 1
                    update_job_progress(self.job_id, error_count=error_count)
                    continue

                # Parse detailed agent fields from pageProps
                try:
                    page_props = p_next.get("props", {}).get("pageProps", {})
                    display_user = page_props.get("displayUser") or {}
                    know_me = page_props.get("getToKnowMe") or {}
                    addr_dict = display_user.get("businessAddress") or {}
                    phone_dict = display_user.get("phoneNumbers") or {}
                    ratings_dict = display_user.get("ratings") or {}

                    # 1. Name
                    name = display_user.get("name") or agent_stub.get("cardTitle") or ""

                    # 2. Company / Agency / Brokerage
                    business_name = display_user.get("businessName") or agent_stub.get("secondaryCardTitle") or ""

                    # 3. Phones
                    cell = phone_dict.get("cell") or ""
                    biz = phone_dict.get("business") or ""
                    brokerage = phone_dict.get("brokerage") or ""
                    primary_phone = cell or biz or brokerage or ""

                    # Fallback phone regex if phone_dict empty
                    if not primary_phone and p_html:
                        phone_matches = PHONE_REGEX.findall(p_html)
                        if phone_matches:
                            primary_phone = phone_matches[0]

                    # 4. Email
                    email = display_user.get("email") or ""
                    # Fallback email regex in bio or text
                    if not email and p_html:
                        # exclude generic zillow emails
                        email_matches = [
                            e for e in EMAIL_REGEX.findall(p_html)
                            if not any(x in e.lower() for x in ["zillow", "sentry", "w3.org", "schema", "example"])
                        ]
                        if email_matches:
                            email = email_matches[0]

                    # 5. Address / Location
                    a1 = addr_dict.get("address1") or ""
                    city = addr_dict.get("city") or ""
                    state = addr_dict.get("state") or ""
                    zip_code = addr_dict.get("postalCode") or ""
                    address_parts = [p for p in [a1, city, state, zip_code] if p]
                    formatted_address = ", ".join(address_parts) if address_parts else ""

                    # Fallback city/state from serviceAreas if address empty
                    if not formatted_address:
                        service_areas = page_props.get("serviceAreas") or []
                        if service_areas and isinstance(service_areas, list):
                            first_area = service_areas[0].get("text") or ""
                            formatted_address = first_area
                            if ", " in first_area:
                                city = first_area.split(", ")[0]
                                state = first_area.split(", ")[-1]

                    # 6. Ratings & Reviews
                    rating_avg = ratings_dict.get("average") or agent_stub.get("rating")
                    review_count = ratings_dict.get("count") or agent_stub.get("reviewCount") or 0

                    # 7. Website & Extras
                    website_url = know_me.get("websiteUrl") or ""
                    photo_url = display_user.get("profilePhotoSrc") or agent_stub.get("imageUrl") or ""
                    specialties_list = know_me.get("specialties") or []
                    specialties_str = ", ".join(specialties_list) if isinstance(specialties_list, list) else str(specialties_list)
                    years_in_industry = know_me.get("yearsInIndustry")

                    service_areas_list = [sa.get("text") for sa in (page_props.get("serviceAreas") or []) if sa.get("text")]
                    service_areas_str = ", ".join(service_areas_list)

                    lead_record = {
                        "job_id": self.job_id,
                        "zuid": display_user.get("encodedZuid") or agent_stub.get("encodedZuid"),
                        "name": name,
                        "business_name": business_name,
                        "phone_cell": cell,
                        "phone_business": biz,
                        "phone_brokerage": brokerage,
                        "primary_phone": primary_phone,
                        "email": email,
                        "address": formatted_address,
                        "city": city,
                        "state": state,
                        "zip_code": zip_code,
                        "rating": float(rating_avg) if rating_avg is not None else None,
                        "review_count": int(review_count),
                        "website_url": website_url,
                        "profile_url": profile_url,
                        "photo_url": photo_url,
                        "specialties": specialties_str,
                        "service_areas": service_areas_str,
                        "years_in_industry": years_in_industry
                    }

                    save_lead(lead_record)
                    scraped_count += 1
                    update_job_progress(self.job_id, scraped_count=scraped_count)

                    contact_info_summary = f"Phone: {primary_phone or 'N/A'} | Email: {email or 'N/A'}"
                    add_log(self.job_id, "SUCCESS", f"[{scraped_count}/{len(discovered_agents)}] Extracted: {name} ({business_name}) | {contact_info_summary}")

                except Exception as ex:
                    logger.exception(f"Error parsing profile {profile_url}: {ex}")
                    error_count += 1
                    update_job_progress(self.job_id, error_count=error_count)
                    add_log(self.job_id, "WARNING", f"Error parsing profile {profile_url}: {str(ex)}")

                # Delay between profiles to maintain stealth
                self._sleep_jitter()

            # Mark Job Completed
            update_job_progress(
                self.job_id,
                status="completed",
                completed_at=datetime.utcnow().isoformat()
            )
            add_log(self.job_id, "SUCCESS", f"Scraping Job Complete! Successfully scraped {scraped_count} leads with {error_count} errors.")

        except Exception as e:
            logger.exception(f"Fatal error in job {self.job_id}: {e}")
            update_job_progress(self.job_id, status="failed", error_message=str(e))
            add_log(self.job_id, "ERROR", f"Job failed with exception: {str(e)}")
