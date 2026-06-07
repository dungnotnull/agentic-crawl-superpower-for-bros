<div align="center">

# Crawl-Superpower-for-Bros

**Modular, never-stop web crawler for any site, any country, any scale**

*Built for days-long unattended runs with zero manual intervention*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Proxy Providers](https://img.shields.io/badge/Proxy%20Providers-14-orange?style=for-the-badge)](v2/proxy/fetcher.py)
[![Multi-Site](https://img.shields.io/badge/Multi--Site-YAML%20Driven-9cf?style=for-the-badge)](v2/sites/)
[![Multi-Country](https://img.shields.io/badge/Multi--Country-9%2B%20Regions-blue?style=for-the-badge)](v2/proxy/fetcher.py)
[![LLM Ready](https://img.shields.io/badge/LLM%20Integration-Ready-purple?style=for-the-badge)](v2/llm_config.yaml)
[![CAPTCHA Aware](https://img.shields.io/badge/CAPTCHA-Detection%20%26%20Avoidance-yellow?style=for-the-badge)](v2/crawler.py)

---

</div>

## What It Does

Crawl-Superpower-for-Bros is a **production-grade** web scraper designed to crawl job listing sites (or any structured data site) through **rotating country-specific proxies** with **zero manual intervention**. It runs until it meets your exact target — whether that is a specific number of jobs, a page limit, or crawling until every page is exhausted.

> **Core guarantee: The crawl loop never stops prematurely.**
> If proxies run out, it waits and keeps searching. If a job is blocked, it retries up to 20 times before moving it to a tracking file. The only way the loop exits is when your criteria are met.

---

## Features

| Feature | Description |
|---------|-------------|
| **Never-stop loop** | Crawl runs continuously until `TARGET_JOBS` or `MAX_PAGES` is reached, or all pages are exhausted |
| **14 proxy providers** | Aggregates from Proxifly, ProxyScrape, GeoNode, Monosans, SpeedX, ClarkEtM, and more |
| **Multi-country proxies** | Choose from Vietnam, Japan, China, South Korea, Singapore, Russia, Europe, India, USA, or run without proxy |
| **Proxy rotation** | Automatically fetches, scores, and rotates proxies; waits for new proxies if none are available |
| **Crash-safe checkpointing** | Every detail page fetch is checkpointed; resume exactly where you left off after a crash |
| **Block tracking** | Jobs that fail after 20+ attempts are moved to `blocked_jobs.json` for visibility |
| **Multi-site support** | Add new sites via YAML mapping files — no code changes needed |
| **Dual output** | Raw HTML preserved for cross-referencing + structured JSON in `output-final-json/` |
| **Live dashboard** | Built-in web UI to browse crawled jobs and preview saved HTML pages |
| **Real-time logging** | Every action logged to terminal with job IDs, names, progress, and elapsed time |
| **Anti-detection** | Uses CloakBrowser with humanized behavior, geoIP, fingerprint randomization, and careful throttling |
| **CAPTCHA detection** | Detects reCAPTCHA, hCaptcha, Cloudflare Turnstile; flags proxies, adapts scoring |
| **Browser backend choice** | `playwright` (default) or `patchright` (helps reCAPTCHA v3 Enterprise) via `--backend` |
| **Smart proxy scheduling** | Tracks per-proxy success/failure/captcha rates; auto-retires bad proxies; scores by runtime performance |
| **Rate limiting adaptation** | Detects blocks and automatically increases delays; recovers back to baseline on sustained success |
| **Bayesian scoring** | Optional Beta-Binomial + latency model with UCB exploration for probabilistic proxy prediction |
| **LLM integration** | Optional API layer that sends raw HTML to any LLM (Claude, GPT, Gemini, Groq, Ollama) for smart data enrichment |
| **Authentication automation** | Login automation with retry/backoff for protected sites; session health checks; re-auth on cookie expiry |

---

## Architecture

```
v2/
|-- main.py              # Entry point & CLI with interactive prompts
|-- crawler.py           # Never-stop crawl engine + CAPTCHA detection + real-time logging
|-- config.py            # Configuration (env vars, CLI, defaults, backend selection)
|-- checkpoint.py        # Crash-safe state persistence
|-- exporter.py          # Multi-format output (JSON, CSV, final JSON)
|-- proxy_manager.py     # Proxy loading, validation, refresh
|-- proxy_tracker.py     # Per-proxy scoring, auto-retirement, CAPTCHA penalty, Bayesian model
|-- site_mappings.py     # YAML-driven site configuration system
|-- dashboard.py         # Web UI for browsing results
|-- auth_manager.py      # Login automation with retry/backoff + session state persistence
|-- llm_integration.py   # LLM API enrichment layer
|-- auth_config.yaml     # Template: login credentials, selectors, retry config
|-- llm_config.yaml      # Template: API key, model, prompt
|-- sites/               # Site-specific YAML mappings
|   `-- ekaigotenshoku.yaml
|-- proxy/               # Proxy tools
|   |-- fetcher.py       # 14-provider multi-country proxy fetcher
|   `-- checker.py       # Re-check cached proxies
`-- output/              # Crawl results (auto-created)
    `-- run_YYYYMMDD_HHMMSS/
        |-- jobs.json
        |-- jobs.csv
        |-- metadata.json
        |-- checkpoint.json
        |-- blocked_jobs.json
        |-- proxy_tracker.json
        |-- html/
        |   |-- detail/          # Raw detail page HTML
        |   `-- list_*.html      # Raw listing page HTML
        `-- output-final-json/   # Structured JSON per job
            |-- job_12345.json
            `-- all_jobs.json
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install cloakbrowser[geoip] requests PySocks pyyaml beautifulsoup4
python -m cloakbrowser install
```

### 2. Fetch Proxies (site-aware + country-aware)

```bash
cd v2

# Fetch proxies for a specific country
python proxy/fetcher.py --country japan
python proxy/fetcher.py --country usa
python proxy/fetcher.py --country europe

# Fetch proxies verified against a specific site
python proxy/fetcher.py --site ekaigotenshoku

# Or specify URL + keywords manually for any site
python proxy/fetcher.py --url "https://example.com/jobs" --keywords "求人,介護"
```

This contacts **14 free proxy providers**, downloads proxy lists for your chosen country, verifies each one against your target site, and saves working proxies to `{country}_working_proxies.json`.

**Supported countries:** `vietnam`, `japan`, `china`, `south korea`, `singapore`, `russia`, `europe`, `india`, `usa`

<details>
<summary>Proxy Providers (14 sources)</summary>

| # | Provider | Type | Filter |
|---|----------|------|--------|
| 1 | Proxifly Country | JSON API | Pre-filtered |
| 2 | Proxifly SOCKS5 | JSON API | Client-side |
| 3 | Proxifly SOCKS4 | JSON API | Client-side |
| 4 | Proxifly Global | JSON API | Client-side |
| 5 | ProxyScrape SOCKS5 | Plain text | Pre-filtered |
| 6 | ProxyScrape HTTP | Plain text | Pre-filtered |
| 7 | ProxyScrape SOCKS4 | Plain text | Pre-filtered |
| 8 | GeoNode | REST API | Pre-filtered |
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

# Crawl with interactive prompts (country + auth)
python main.py

# Or override via environment variables for automation
set CRAWL_PROXY_COUNTRY=japan
set CRAWL_AUTH_REQUIRED=false
python main.py --target-jobs 240

# Other options
python main.py --max-pages 10
python main.py --site ekaigotenshoku --target-jobs 500
python main.py --bayesian --target-jobs 500
python main.py --backend patchright       # Use Patchright for reCAPTCHA v3 sites
python main.py --clean
python main.py --no-headless
python main.py --help
```

When you run `python main.py`, the terminal will ask:
1. **Which country proxy?** (1-9 + 0 for no proxy)
2. **Does the site require authentication?** (Y/N)
3. **Clean start / Resume / Quit?** (if a previous run exists)

### 4. View Results

```bash
python dashboard.py
```

Opens a web UI at `http://localhost:3001` where you can browse jobs, preview HTML, and inspect crawl metadata.

---

## Anti-Detection & CAPTCHA Handling

### CloakBrowser Stealth Layers

The crawler uses [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) — a patched Chromium binary with source-level fingerprint patches:

| Layer | What It Defeats |
|-------|-----------------|
| **Fingerprint randomization** (`--fingerprint=SEED`) | Canvas, WebGL, AudioContext, hardware concurrency, device memory, screen size, GPU renderer |
| **Automation suppression** (strips `--enable-automation`) | `navigator.webdriver = true` leak |
| **WebRTC IP leak protection** (`--fingerprint-webrtc-ip`) | Exposes real IP behind proxy via WebRTC |
| **Humanized behavior** (`humanize=True, human_preset="careful"`) | Bezier mouse curves, realistic typing, smooth scrolling, CDP Isolated World |
| **GeoIP auto-detection** (`geoip=True`) | Timezone + locale match proxy country (prevents mismatch detection) |
| **Patchright backend** (`backend="patchright"`) | Suppresses CDP runtime signals — helps pass reCAPTCHA v3 Enterprise |

### CAPTCHA Detection

Even with CloakBrowser, aggressive crawling or flagged proxy IPs can trigger CAPTCHA challenges. The crawler now includes built-in CAPTCHA detection:

- **reCAPTCHA v2/v3** — iframe/element detection
- **hCaptcha** — iframe/element detection
- **Cloudflare Turnstile** — challenge iframe detection
- **Japanese CAPTCHA pages** — text indicators (入力確認, セキュリティ確認, etc.)

**When CAPTCHA is detected:**
1. The current proxy session is stopped immediately
2. The proxy is flagged in `ProxyTracker` with a CAPTCHA penalty (20% score reduction per detection)
3. The crawler moves to the next proxy automatically
4. CAPTCHA-flagged proxies are **not** retired — they may work again after cooldown

### Choosing a Browser Backend

```bash
# Default: Playwright (full feature support)
python main.py

# Patchright: for sites using reCAPTCHA v3 Enterprise scoring
python main.py --backend patchright
```

> **Note:** Patchright suppresses CDP signals that reCAPTCHA v3 uses for bot detection. However, it breaks `add_init_script()` and proxy auth. Use only when needed.

---

## Optional: LLM Integration

To enrich every crawled job with AI-extracted structured data:

1. Open `llm_config.yaml`
2. Set `enabled: true`
3. Fill in your `api_key`, `base_url`, and `model`
4. Customize the `prompt` template
5. Run `python main.py` as usual

Supported APIs: OpenAI, Groq, Gemini, Claude (via OpenAI-compatible endpoints), local Ollama.

> **Security note:** Your API key never leaves your machine. The code runs entirely locally.

When enabled, each detail page's HTML is sent to the LLM after crawling. The returned JSON is injected into the output under the key `llm_enhanced`.

---

## Optional: Authentication Layer

For sites that require login (e.g., Shopee, LinkedIn):

1. Open `auth_config.yaml`
2. Set `enabled: true`
3. Fill in `login_url`, `username`, `password`
4. Provide CSS selectors for the username field, password field, and submit button
5. Run `python main.py` and answer **Y** to the authentication prompt

The crawler will:
- Log in automatically before crawling (with retry + backoff, up to 3 attempts)
- Check session health before each listing page load
- Detect session expiry (silent cookie timeout, not just URL redirects)
- Re-authenticate and resume seamlessly
- Skip the proxy if login fails after all retries

### Session State Persistence

For sites with OAuth/SSO login (LINE, Google), you can save browser state and reuse it:

```python
# After successful login:
await save_auth_state(context, Path("auth_state.json"))

# Before next proxy session:
ctx = await launch_context_async(storage_state="auth_state.json")
```

### Cookie-Based Auth (Alternative)

If your site uses session cookies instead of form login:

```yaml
# auth_config.yaml
enabled: true
auth_type: "cookie"
cookies:
  - name: "session_id"
    value: "your_cookie_value"
    domain: ".example.com"
```

---

## Configuration

All settings can be configured via environment variables, CLI arguments, or direct editing:

| Setting | Env Variable | CLI Flag | Default | Description |
|---------|-------------|----------|---------|-------------|
| Target jobs | `CRAWL_TARGET_JOBS` | `--target-jobs N` | None (unlimited) | Stop after N jobs |
| Max pages | `CRAWL_MAX_PAGES` | `--max-pages N` | None (unlimited) | Max listing pages per proxy |
| Block threshold | `CRAWL_BLOCK_THRESHOLD` | — | 20 | Attempts before moving to block file |
| Headless | `CRAWL_HEADLESS` | `--no-headless` | True | Run browser without UI |
| Output dir | `CRAWL_OUTPUT_DIR` | — | `output` | Root output directory |
| Proxy country | `CRAWL_PROXY_COUNTRY` | — | `japan` | Country code or `none` |
| Use proxy | `CRAWL_USE_PROXY` | — | true | Set `false` to bypass proxy layer |
| Auth required | `CRAWL_AUTH_REQUIRED` | — | false | Enable login automation |
| Browser backend | `CRAWL_BROWSER_BACKEND` | `--backend` | playwright | `playwright` or `patchright` |
| Bayesian scoring | `CRAWL_USE_BAYESIAN` | `--bayesian` | False | Beta-Binomial + latency + UCB scoring |
| Bayesian exploration | `CRAWL_BAYESIAN_EXPLORATION` | — | 1.0 | UCB exploration bonus multiplier |

---

## Adding a New Site

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
  - "介護"

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

> If your YAML does not include `js_extraction_code` or `js_pagination_code`, the system falls back to the built-in mapping's JS code (if one exists for that site name).

---

## Block Tracking

When a job's detail page is blocked or fails to load, the crawler retries it on subsequent proxy rotations. After **20 attempts** (configurable), the job is moved to `blocked_jobs.json`:

```json
{
  "permanently_blocked": [
    {
      "job_id": "1836924",
      "detail_url": "https://www.ekaigotenshoku.com/kyujin/detail?id=1836924",
      "title": "介護スタッフ",
      "retries": 20,
      "status": "permanently_blocked"
    }
  ],
  "still_retrying": [],
  "total_blocked": 1
}
```

---

## How the Never-Stop Loop Works

```
+---------------------------------------------------------------+
|  Load proxies (14 providers, country-specific)                |
|  +-- No proxies? Wait 60s, retry ----------------------------+ |
|  +----------------------------------------------------------+ |
|                                                                |
|  +-- Proxy tracker seeds base scores -----------------------+ |
|  |  Filters retired proxies, sorts by score                | |
|  |  (heuristic or Bayesian with UCB bonus)                | |
|  +----------------------------------------------------------+ |
|                                                                |
|  For each proxy (best-scored first):                           |
|    |-- Verify target-country IP                               |
|    |-- Detect CAPTCHA (reCAPTCHA/hCaptcha/Turnstile)         |
|    |-- [Optional] Authenticate if site requires login         |
|    |-- Crawl listing pages                                    |
|    |   |-- Session health check (auth required sites)       |
|    |   |-- CAPTCHA detection on listing pages                |
|    |-- For each job on page:                                 |
|    |   |-- Fetch detail HTML (with latency timing)           |
|    |   |-- CAPTCHA detection on detail pages                 |
|    |   |-- [Optional] Send HTML to LLM for enrichment        |
|    |   |-- Blocked? Step up delay multiplier                 |
|    |   |-- 20+ fails? -> blocked_jobs.json                  |
|    |   |-- Save checkpoint after each fetch                  |
|    |-- Record session to tracker (successes/failures/captcha)|
|    |-- Proxy failed too often? Auto-retire                   |
|    |-- Next proxy                                            |
|                                                                |
|  Check stop criteria:                                          |
|    |-- TARGET_JOBS met? -> DONE                               |
|    |-- MAX_PAGES met? -> DONE                                |
|    |-- Both None & pages exhausted? -> DONE                  |
|    |-- Otherwise -> back to top                              |
+---------------------------------------------------------------+
```

---

## Requirements

| Package | Version | Purpose |
|---------|---------|---------|
| Python | 3.10+ | Runtime |
| CloakBrowser | >=0.5.0 | Anti-detection stealth browser |
| requests | >=2.28.0 | HTTP client for proxy verification |
| PySocks | >=1.7.1 | SOCKS proxy support |
| pyyaml | >=6.0 | YAML site mapping parser |
| beautifulsoup4 | >=4.12.0 | HTML parsing |

---

## Windows Notes & Troubleshooting

### Running from the v2 directory

Always run from inside the `v2/` folder:

```bash
cd v2
python main.py --target-jobs 240
```

### Console encoding

Windows Command Prompt and PowerShell may not render Japanese characters or special symbols by default. Use **Windows Terminal** (recommended) or run:

```powershell
chcp 65001
python main.py --target-jobs 240
```

All log output uses ASCII-safe separators (`=` instead of Unicode box-drawing) so there is no crash on any Windows console.

### Proxy fetcher on Windows

```bash
python proxy/fetcher.py --country japan
```

This contacts 14 providers; some will fail (rate limits, geo-blocks) which is expected. As long as 2-3 providers return data, you will get a usable proxy pool.

### No-proxy mode

If the target site does not block your IP, select option `0` (No need proxy) at the country prompt. The crawler will run directly without any proxy layer.

### Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `ImportError: attempted relative import` | Running from wrong directory | `cd v2` then `python main.py` |
| `No proxies available - waiting 60s` | No cached proxy file | Run `python proxy/fetcher.py --country {country}` first |
| `CloakBrowser` or `launch_async` not found | CloakBrowser not installed | `pip install cloakbrowser[geoip]` then `python -m cloakbrowser install` |
| `[CAPTCHA] CAPTCHA detected` | Site shows CAPTCHA challenge | Switch to next proxy; consider `--backend patchright` for v3 sites |

---

## License

[MIT](LICENSE) — Use freely, modify freely, crawl freely.

---

<div align="center">

**Built for the bros who need data**

</div>
