import os
import random
import time
import logging
import urllib.parse
from typing import Optional, Tuple, Dict, Any, List

logger = logging.getLogger("zillow_scraper.proxy")

# High-entropy modern desktop user agents
DESKTOP_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

CHROME_IMPERSONATE_VERSIONS = ["chrome124", "chrome120", "chrome119", "safari17_0", "edge101"]

class ProxyManager:
    def __init__(self, settings: Dict[str, str] = None):
        self.settings = settings or {}
        self.mode = self.settings.get("anti_bot_mode", "stealth")
        self.scraperapi_key = self.settings.get("scraperapi_key", "").strip()
        self.zenrows_key = self.settings.get("zenrows_key", "").strip()
        self.raw_custom_proxies = self.settings.get("custom_proxies", "").strip()
        self.rotate_every = int(self.settings.get("rotate_proxy_every", "3") or 3)

        self.proxies_list: List[str] = []
        self._parse_custom_proxies()

        self.current_proxy_index = 0
        self.request_counter = 0

    def _parse_custom_proxies(self):
        lines = [line.strip() for line in self.raw_custom_proxies.splitlines() if line.strip()]
        valid = []
        for l in lines:
            if not l.startswith("http://") and not l.startswith("https://") and not l.startswith("socks5://"):
                l = "http://" + l
            valid.append(l)
        self.proxies_list = valid

    def update_settings(self, settings: Dict[str, str]):
        self.settings = settings
        self.mode = self.settings.get("anti_bot_mode", "stealth")
        self.scraperapi_key = self.settings.get("scraperapi_key", "").strip()
        self.zenrows_key = self.settings.get("zenrows_key", "").strip()
        self.raw_custom_proxies = self.settings.get("custom_proxies", "").strip()
        self.rotate_every = int(self.settings.get("rotate_proxy_every", "3") or 3)
        self._parse_custom_proxies()

    def get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        ua = random.choice(DESKTOP_USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Dnt": "1",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if referer else "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def get_request_params(self, target_url: str) -> Tuple[str, Optional[Dict[str, str]], Optional[str], str]:
        """
        Returns:
            (effective_url, proxies_dict, impersonate_version, proxy_info_label)
        """
        impersonate = random.choice(CHROME_IMPERSONATE_VERSIONS)
        self.request_counter += 1

        # Mode 1: ScraperAPI Gateway
        if self.mode == "scraperapi" and self.scraperapi_key:
            encoded = urllib.parse.quote_plus(target_url)
            # ScraperAPI url
            # Note: ScraperAPI auto-rotates millions of residential and datacenter IPs
            api_url = f"https://api.scraperapi.com?api_key={self.scraperapi_key}&url={encoded}&keep_headers=true"
            return api_url, None, impersonate, "ScraperAPI (Auto-Rotating Residential IPs)"

        # Mode 2: ZenRows Gateway
        if self.mode == "zenrows" and self.zenrows_key:
            encoded = urllib.parse.quote_plus(target_url)
            api_url = f"https://api.zenrows.com/v1/?apikey={self.zenrows_key}&url={encoded}&antibot=true"
            return api_url, None, impersonate, "ZenRows (Auto-Rotating Anti-Bot Gateway)"

        # Mode 3: Custom Proxy Pool
        if self.mode == "custom_pool" and self.proxies_list:
            if self.request_counter % self.rotate_every == 0:
                self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies_list)

            active_proxy = self.proxies_list[self.current_proxy_index]
            proxy_dict = {
                "http": active_proxy,
                "https": active_proxy
            }
            # Mask credentials in label
            safe_label = active_proxy.split("@")[-1] if "@" in active_proxy else active_proxy
            return target_url, proxy_dict, impersonate, f"Custom Proxy [{self.current_proxy_index + 1}/{len(self.proxies_list)}]: {safe_label}"

        # Mode 4: Stealth Direct (TLS browser impersonation)
        return target_url, None, impersonate, f"Stealth Engine (TLS {impersonate})"

    def rotate_on_failure(self):
        """Force switch to next proxy immediately on 403 / captcha challenge"""
        if self.mode == "custom_pool" and self.proxies_list:
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies_list)
            logger.warning("Forced proxy rotation to index %s due to challenge", self.current_proxy_index)

    def test_connection(self) -> Dict[str, Any]:
        """Test proxy or direct connection against an IP echo service or Zillow test endpoint"""
        from curl_cffi import requests
        test_url = "https://httpbin.org/ip"
        eff_url, proxies, imp, label = self.get_request_params(test_url)
        headers = self.get_headers()

        start = time.time()
        try:
            r = requests.get(eff_url, proxies=proxies, headers=headers, impersonate=imp, timeout=12)
            elapsed = round((time.time() - start) * 1000)
            if r.status_code == 200:
                ip_data = r.json().get("origin", "Unknown IP")
                return {
                    "success": True,
                    "status_code": r.status_code,
                    "latency_ms": elapsed,
                    "detected_ip": ip_data,
                    "mode": self.mode,
                    "engine_label": label,
                    "message": f"Successfully connected via {label}! Detected IP: {ip_data} ({elapsed}ms)"
                }
            else:
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "latency_ms": elapsed,
                    "mode": self.mode,
                    "message": f"Received non-200 status code: {r.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "mode": self.mode,
                "message": f"Connection failed: {str(e)}"
            }
