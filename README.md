# 🏡 Zillow Agent Lead Scraper Pro (Autonomous Cloud Harvester)

An automated, anti-bot-resilient web scraper and real-estate leads dashboard built to extract **Agent Names, Agencies/Brokerages, Direct Phone Numbers, Emails, Addresses, Ratings, and Zillow Profile URLs** across all 25 directory pages (up to 375 leads per city) with **zero-block proxy rotation** and **1-click Google Sheets synchronization**.

---

## ⚡ Quick Start (Local)

### 1. Launch the Server & Dashboard
Run the launch script from the project folder:
```bash
cd /Users/zuryab/Antigravity/zillow-agent-scraper
./run.sh
```
Or directly with Python:
```bash
/Users/zuryab/Antigravity/.venv/bin/python server.py
```

### 2. Open the Web Dashboard
Navigate to:
```
http://localhost:8000
```

---

## 🚀 How It Works

1. **Enter Any US City or Zillow URL**:
   - Type `Austin, TX`, `Miami, FL`, `North Chicago, IL`, or paste any Zillow agent reviews link:
     `https://www.zillow.com/professionals/real-estate-agent-reviews/north-chicago-il/`
2. **Click "Start Automated Scrape"**:
   - The job launches as an **asynchronous background worker**.
   - **You can close your browser tab, turn off your computer, or walk away**—the worker runs autonomously in the background until all 25 pages and up to ~375 leads are extracted.
3. **Real-Time Live Monitor**:
   - View real-time animated progress bars and live streaming logs directly in the terminal console.
   - Pause, resume, or cancel jobs anytime.
4. **Interactive "Google Sheets" Spreadsheet View**:
   - Browse, search, and filter leads in a full spreadsheet view.
   - **1-Click Copy for Google Sheets**: Copies all or selected leads as TSV. Just open Google Sheets and hit `Cmd+V` (or `Ctrl+V`)!
   - **Direct Google Sheets Live Sync**: Paste `=IMPORTDATA("http://YOUR-SERVER:8000/api/leads/export/csv")` into cell A1 for live auto-updating sync.
   - **Instant CSV & Excel (.xlsx) Downloads**.

---

## 🛡️ Anti-Bot & Proxy Rotation System

Zillow uses **PerimeterX (HUMAN Security)** to block scrapers after ~70 requests. This system bypasses it using 4 flexible tiers:

| Mode | Protection Level | Cost | Best For |
| :--- | :--- | :--- | :--- |
| **Stealth Engine** | TLS JA3/JA4 Chrome fingerprinting + delay jitter | Free (Built-in) | Quick searches & initial batches |
| **ScraperAPI Gateway** | Auto-rotates millions of residential IPs & solves CAPTCHAs | Free Tier (5,000 requests/mo) | Continuous automated scraping |
| **ZenRows Gateway** | Rotating residential proxy gateway | Free trial | High concurrency |
| **Custom Proxy Pool** | User-defined HTTP/HTTPS/SOCKS5 proxy list | Depends on provider | Custom proxy fleets (auto-rotates every N requests) |

### Setting up ScraperAPI (Recommended for 100% Reliability):
1. Sign up for a free account at [ScraperAPI](https://www.scraperapi.com) (gives **5,000 free requests**).
2. Go to the **Anti-Bot & Proxy Engine** tab in the dashboard.
3. Select **ScraperAPI Gateway**, paste your API key, and click **Save Proxy Settings**.
4. Click **⚡ Test Connection & Latency** to verify your rotating IP.

---

## ☁️ 24/7 Cloud Deployment (Run Without Your PC)

To let the scraper run 24/7 on the cloud without needing your personal device to stay on:

### Option 1: 1-Click Deploy on Render.com (Free / Cheap)
1. Push this directory to your GitHub repository.
2. Sign up on [Render.com](https://render.com).
3. Click **New +** -> **Web Service** -> Connect your GitHub repo.
4. Choose **Docker** runtime (it uses the included `Dockerfile`).
5. Set Health Check path to `/`. Click **Create Web Service**.
6. Render builds the container and gives you a 24/7 URL: `https://your-app.onrender.com`.

### Option 2: Railway.app (Fastest)
1. Go to [Railway.app](https://railway.app).
2. Click **New Project** -> **Deploy from GitHub Repo**.
3. Railway automatically detects the `Dockerfile` and deploys it in ~60 seconds.

### Option 3: Docker on any VPS (Ubuntu/Debian)
```bash
docker compose up -d --build
```

---

## 📊 Extracted Data Fields

For every single agent lead, the scraper extracts:
- ✅ **Agent Full Name**
- ✅ **Company / Brokerage / Agency Name**
- ✅ **Primary Phone Number** (Direct Cell / Business)
- ✅ **Direct Email Address** (With regex fallback if unlisted)
- ✅ **Office Address, City, State, and Zip Code**
- ✅ **Zillow Profile URL**
- ✅ **Star Rating & Total Review Count**
- ✅ **Website URL**
- ✅ **Specialties & Years in Industry**
- ✅ **Profile Avatar Photo URL**

---

## 🔌 API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/jobs` | POST | Launch a new scraping job (`location`, `total_pages`, etc.) |
| `/api/jobs` | GET | List all past and active jobs |
| `/api/jobs/{id}` | GET | Get real-time job progress & stats |
| `/api/jobs/{id}/stream` | GET | Server-Sent Events (SSE) real-time log stream |
| `/api/jobs/{id}/pause` | POST | Pause active job |
| `/api/jobs/{id}/resume` | POST | Resume paused job |
| `/api/jobs/{id}/cancel` | POST | Cancel active job |
| `/api/leads` | GET | Search & filter leads database (pagination support) |
| `/api/jobs/{id}/export/csv` | GET | Download RFC-4180 CSV (also for `=IMPORTDATA`) |
| `/api/jobs/{id}/export/excel` | GET | Download styled `.xlsx` spreadsheet |
| `/api/settings` | GET/POST | Read or update proxy & anti-bot configuration |
| `/api/proxies/test` | POST | Test current proxy connection & IP echo |
