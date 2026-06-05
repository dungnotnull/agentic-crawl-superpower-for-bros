<div align="center">

# 🕷️ Crawl-Superpower-for-Bros

**Modular, never-stop web crawler for Japanese job sites**

*Built for days-long unattended runs with zero manual intervention*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Proxy Providers](https://img.shields.io/badge/Proxy%20Providers-14-orange?style=for-the-badge)](v2/proxy/fetcher.py)
[![Multi-Site](https://img.shields.io/badge/Multi--Site-YAML%20Driven-9cf?style=for-the-badge)](v2/sites/)

---

</div>

## ✨ What It Does

Crawl-Superpower-for-Bros is a **production-grade** web scraper designed to crawl Japanese job listing sites through rotating proxies with **zero manual intervention**. It runs until it meets your exact target — whether that's a specific number of jobs, a page limit, or crawling until every page is exhausted.

> 🔒 **Core guarantee: The crawl loop never stops prematurely.**  
> If proxies run out, it waits and keeps searching. If a job is blocked, it retries up to 20 times before moving it to a tracking file. The only way the loop exits is when your criteria are met.

---

## 🚀 Features

| Feature | Description |
|---------|-------------|
| 🔄 **Never-stop loop** | Crawl runs continuously until `TARGET_JOBS` or `MAX_PAGES` is reached, or all pages are exhausted |
| 🌐 **14 proxy providers** | Aggregates from Proxifly, ProxyScrape, GeoNode, Monosans, SpeedX, ClarkEtM, and more |
| 🔄 **Proxy rotation** | Automatically fetches, scores, and rotates Japanese proxies; waits for new proxies if none are available |
| 💾 **Crash-safe checkpointing** | Every detail page fetch is checkpointed; resume exactly where you left off after a crash |
| 🚫 **Block tracking** | Jobs that fail after 20+ attempts are moved to `blocked_jobs.json` for visibility |
| 🗺️ **Multi-site support** | Add new sites via YAML mapping files — no code changes needed |
| 📊 **Dual output** | Raw HTML preserved for cross-referencing + structured JSON in `output-final-json/` |
| 📺 **Live dashboard** | Built-in web UI to browse crawled jobs and preview saved HTML pages |
| 📝 **Real-time logging** | Every action logged to terminal with job IDs, names, progress, and elapsed time |
| 🛡️ **Anti-detection** | Uses CloakBrowser with humanized behavior, geoIP, and careful throttling |

---

## 🏗️ Architecture

```
v2/
├── 📄 main.py              # Entry point & CLI
├── 🕷️ crawler.py           # Never-stop crawl engine + real-time logging
├── ⚙️ config.py            # Configuration (env vars, CLI, defaults)
├── 💾 checkpoint.py        # Crash-safe state persistence
├── 📦 exporter.py          # Multi-format output (JSON, CSV, final JSON)
├── 🌐 proxy_manager.py     # Proxy loading, validation, refresh
├── 🗺️ site_mappings.py     # YAML-driven site configuration system
├── 📺 dashboard.py         # Web UI for browsing results
├── 📁 sites/               # Site-specific YAML mappings
│   └── ekaigotenshoku.yaml
├── 📁 proxy/               # Proxy tools
│   ├── 🔄 fetcher.py       # 14-provider proxy fetcher & verifier
│   └── ✅ checker.py       # Re-check cached proxies
└── 📁 output/              # Crawl results (auto-created)
    └── run_YYYYMMDD_HHMMSS/
        ├── jobs.json
        ├── jobs.csv
        ├── metadata.json
        ├── checkpoint.json
        ├── blocked_jobs.json
        ├── 📁 html/
        │   ├── detail/          # Raw detail page HTML
        │   └── list_*.html      # Raw listing page HTML
        └── 📁 output-final-json/   # Structured JSON per job
            ├── job_12345.json
            └── all_jobs.json
```

---

## ⚡ Quick Start

### 1. Install Dependencies

```bash
pip install cloakbrowser[geoip] requests PySocks pyyaml beautifulsoup4
python -m cloakbrowser install
```

### 2. Fetch Proxies (site-aware)

```bash
cd v2

# Fetch proxies verified against the default site (ekaigotenshoku)
python proxy/fetcher.py

# Fetch proxies for a specific site (uses the site's URL + keywords)
python proxy/fetcher.py --site ekaigotenshoku

# Or specify URL + keywords manually for any site
python proxy/fetcher.py --url "https://example.com/jobs" --keywords "求人,募集"
```

This contacts **14 free proxy providers**, downloads Japanese proxy lists, verifies each one against your target site, and saves working proxies to `japan_working_proxies.json`.

<details>
<summary>📋 Proxy Providers (14 sources)</summary>

| # | Provider | Type | JP Filter |
|---|----------|------|-----------|
| 1 | Proxifly JP | JSON API | Pre-filtered |
| 2 | Proxifly SOCKS5 | JSON API | Client-side |
| 3 | Proxifly SOCKS4 | JSON API | Client-side |
| 4 | Proxifly Global | JSON API | Client-side |
| 5 | ProxyScrape SOCKS5 | Plain text | Pre-filtered |
| 6 | ProxyScrape HTTP | Plain text | Pre-filtered |
| 7 | ProxyScrape SOCKS4 | Plain text | Pre-filtered |
| 8 | GeoNode JP | REST API | Pre-filtered |
| 9 | FreeProxyList CDN | JSON API | Client-side |
| 10 | Monosans SOCKS5 | Plain text | Client-side |
| 11 | Monosans HTTP | Plain text | Client-side |
| 12 | SpeedX SOCKS5 | Plain text | Client-side |
| 13 | SpeedX HTTP | Plain text | Client-side |
| 14 | ClarkEtM Proxy | Plain text | Client-side |

</details>

### 3. Run the Crawler

```bash
cd v2

# Crawl with defaults (auto-starts dashboard at localhost:3001)
python main.py

# Crawl until 240 jobs
python main.py --target-jobs 240

# Crawl with a page limit per proxy
python main.py --max-pages 10

# Crawl a specific site with a target
python main.py --site ekaigotenshoku --target-jobs 500

# Clean start (delete previous output)
python main.py --clean

# Visible browser (for debugging)
python main.py --no-headless

# Show all options
python main.py --help
```

### 4. View Results

```bash
python dashboard.py
```

Opens a web UI at `http://localhost:3001` where you can browse jobs, preview HTML, and inspect crawl metadata.

---

## 📝 Real-Time Logging

Every action is logged to the terminal with timestamps, job IDs, and progress:

```
========================================================================
  CRAWL STARTED - Ekaigo Tenshoku
========================================================================
  00:00 [CONFIG] Target: 0/240 jobs (0%)
  00:00 [CONFIG] Max pages/proxy: unlimited
  00:00 [CONFIG] Block threshold: 20 attempts

========================================================================
  PROXY #1: socks5://103.152.112.166:4145
========================================================================
  00:03 [BROWSER] Launching CloakBrowser (headless, humanized, geoIP)...
  00:05 [VERIFY] Checking if proxy IP is Japanese...
  00:07 [OK] JP IP confirmed: 103.152.112.166
  00:08 [WARMUP] Navigating to google.co.jp...
  00:10 [WARMUP] Browser session ready
  00:11 [PAGE] Loading listing page 1: https://www.ekaigotenshoku.com/kyujin...
  00:14 [EXTRACT] Extracting job cards from page 1...
  00:15 [OK] 20 jobs found on page 1
  00:15 [FOUND] Job #1/20: ID=299554 "介護職員（正社員）"
  00:15 [FOUND] Job #2/20: ID=299553 "ヘルパー（パート）"
  00:15 [DETAIL] Fetching detail pages for 20 jobs...
  00:16 [CRAWL] Fetching job 299554 "介護職員（正社員）" (1/20 on page 1)...
  00:19 [SAVED] Job 299554 "介護職員（正社員）" -> 1/240 jobs (0%)
  00:20 [CRAWL] Fetching job 299553 "ヘルパー（パート）" (2/20 on page 1)...
  00:23 [SAVED] Job 299553 "ヘルパー（パート）" -> 2/240 jobs (0%)
  ...
  00:55 [PAUSE] Throttling: 15s after 8 detail pages...
  ...
  12:30 [SAVED] Job 183692 "特別養護老人ホーム" -> 240/240 jobs (100%)

========================================================================
  TARGET REACHED - 240/240 jobs (100%)
========================================================================
```

---

## ⚙️ Configuration

All settings can be configured via environment variables, CLI arguments, or direct editing:

| Setting | Env Variable | CLI Flag | Default | Description |
|---------|-------------|----------|---------|-------------|
| 🎯 Target jobs | `CRAWL_TARGET_JOBS` | `--target-jobs N` | None (unlimited) | Stop after N jobs |
| 📄 Max pages | `CRAWL_MAX_PAGES` | `--max-pages N` | None (unlimited) | Max listing pages per proxy |
| 🚫 Block threshold | `CRAWL_BLOCK_THRESHOLD` | — | 20 | Attempts before moving to block file |
| 👁️ Headless | `CRAWL_HEADLESS` | `--no-headless` | True | Run browser without UI |
| 📁 Output dir | `CRAWL_OUTPUT_DIR` | — | `output` | Root output directory |

---

## 🗺️ Adding a New Site

Create a YAML file in `sites/` with the site's configuration:

```yaml
# sites/my-new-site.yaml
name: my-new-site
display_name: "My New Job Site"

url:
  listing_url: "https://example.com/jobs"
  listing_url_template: "https://example.com/jobs?page={page}"
  detail_url_pattern: "/jobs/detail/(\\d+)"

success_keywords:
  - "求人"
  - "募集"

fields:
  job_id:
    source: job_id
  title:
    source: title
    transform: strip
  company:
    source: company
  salary:
    source: salary
  location:
    source: location

# JS extraction code (inline or from file)
js_extraction_code: |
  () => {
    const cards = document.querySelectorAll('.job-card');
    return Array.from(cards).map(card => ({
      title: card.querySelector('h3')?.textContent?.trim(),
      company: card.querySelector('.company')?.textContent?.trim(),
      salary: card.querySelector('.salary')?.textContent?.trim(),
      location: card.querySelector('.location')?.textContent?.trim(),
      detail_url: card.querySelector('a')?.href,
    })).filter(j => j.title);
  }

js_pagination_code: |
  () => {
    const next = document.querySelector('a.next');
    return next ? next.href : null;
  }
```

Then run:

```bash
python main.py --site my-new-site
```

> 💡 If your YAML doesn't include `js_extraction_code` or `js_pagination_code`, the system falls back to the built-in mapping's JS code (if one exists for that site name).

---

## 🚫 Block Tracking

When a job's detail page is blocked or fails to load, the crawler retries it on subsequent proxy rotations. After **20 attempts** (configurable), the job is moved to `blocked_jobs.json`:

```json
{
  "permanently_blocked": [
    {
      "job_id": "1836924",
      "detail_url": "https://www.ekaigotenshoku.com/kyujin/detail?id=1836924",
      "title": "介護職員",
      "retries": 20,
      "status": "permanently_blocked"
    }
  ],
  "still_retrying": [],
  "total_blocked": 1
}
```

---

## 📦 Output Formats

### 📄 Raw HTML (`html/detail/`)
Original HTML of each job's detail page, saved as `job_{id}.html`. Useful for:
- Re-parsing with different extraction rules
- Cross-referencing with structured JSON
- Debugging extraction issues

### 📊 Structured JSON (`output-final-json/`)
One JSON file per job with mapped fields:

```json
{
  "job_id": "299554",
  "title": "介護職員（正社員）",
  "company": "特別養護老人ホーム サンプル",
  "salary": "月給 180,000円〜220,000円",
  "location": "東京都新宿区",
  "employment_type": "正社員 | 介護",
  "detail_url": "https://www.ekaigotenshoku.com/kyujin/detail?id=299554",
  "_source_url": "https://www.ekaigotenshoku.com/kyujin/detail?id=299554",
  "_crawled_at": "2025-01-15T10:30:00",
  "_proxy_used": "socks5://..."
}
```

Plus `all_jobs.json` combining all jobs into a single file.

### 📈 CSV (`jobs.csv`)
Standard tabular format for spreadsheet import, with columns: job_id, title, company, salary, location, jobType, detail_url, etc.

---

## 🔄 How the Never-Stop Loop Works

```
┌─────────────────────────────────────────────────────┐
│  🔄 Load proxies (14 providers)                     │
│  ┌─ No proxies? Wait 60s, retry ──────────────┐    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  For each proxy:                                     │
│    ├─ ✅ Verify JP IP                                │
│    ├─ 📄 Crawl listing pages                         │
│    ├─ For each job on page:                          │
│    │   ├─ 🕷️ Fetch detail HTML                       │
│    │   ├─ 🚫 Blocked? Record + retry later           │
│    │   ├─ ❌ 20+ fails? → blocked_jobs.json          │
│    │   └─ 💾 Save checkpoint after each fetch         │
│    └─ ➡️ Next proxy                                  │
│                                                      │
│  Check stop criteria:                                │
│    ├─ 🎯 TARGET_JOBS met? → DONE                     │
│    ├─ 📄 MAX_PAGES met? → DONE                       │
│    ├─ 🏁 Both None & pages exhausted? → DONE         │
│    └─ 🔄 Otherwise → back to top                     │
└─────────────────────────────────────────────────────┘
```

---

## 📋 Requirements

| Package | Version | Purpose |
|---------|---------|---------|
| ![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python) | 3.10+ | Runtime |
| [CloakBrowser](https://github.com/nicholasgasior/cloakbrowser) | ≥0.5.0 | Anti-detection browser |
| requests | ≥2.28.0 | HTTP client for proxy verification |
| PySocks | ≥1.7.1 | SOCKS proxy support |
| pyyaml | ≥6.0 | YAML site mapping parser |
| beautifulsoup4 | ≥4.12.0 | HTML parsing |

---

## 🪟 Windows Notes & Troubleshooting

### Running from the v2 directory

Always run from inside the `v2/` folder:

```bash
cd v2
python main.py --target-jobs 240
```

The project supports both `python main.py` (direct) and `python -m v2.main` (from parent directory).

### Console encoding

Windows Command Prompt and PowerShell may not render Japanese characters or special symbols by default. Use **Windows Terminal** (recommended) or run:

```powershell
chcp 65001
python main.py --target-jobs 240
```

All log output uses ASCII-safe separators (`=` instead of Unicode box-drawing) so there's no crash on any Windows console.

### Proxy fetcher on Windows

```bash
python proxy/fetcher.py
```

This contacts 14 providers; some will fail (rate limits, geo-blocks) which is expected. As long as 2-3 providers return data, you'll get a usable proxy pool.

### Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `ImportError: attempted relative import` | Running from wrong directory | `cd v2` then `python main.py` |
| `No proxies available - waiting 60s` | No cached proxy file | Run `python proxy/fetcher.py` first |
| `CloakBrowser` or `launch_async` not found | CloakBrowser not installed | `pip install cloakbrowser[geoip]` then `python -m cloakbrowser install` |

---

## 📜 License

[MIT](LICENSE) — Use freely, modify freely, crawl freely.

---

<div align="center">

**Built with 🕷️ for the bros who need data**

</div>
