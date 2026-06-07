<div align="center">

<br />

<img src="https://img.icons8.com/fluency/96/spider-web.png" width="80" height="80" alt="Logo" />

# 🕷️ Crawl-Superpower-for-Bros

**Modular, never-stop web crawler for any site, any country, any scale**

*Built for days-long unattended runs with zero manual intervention*

<br />

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Proxy Providers](https://img.shields.io/badge/Proxies-14_Free_Providers-orange?style=for-the-badge)](v2/proxy/fetcher.py)
[![Multi-Site](https://img.shields.io/badge/Sites-YAML_Driven-9cf?style=for-the-badge)](v2/sites/)
[![Multi-Country](https://img.shields.io/badge/Countries-9%2B_Regions-blue?style=for-the-badge)](v2/proxy/fetcher.py)
[![LLM Ready](https://img.shields.io/badge/LLM-Integration_Ready-purple?style=for-the-badge)](v2/llm_config.yaml)
[![CAPTCHA Aware](https://img.shields.io/badge/CAPTCHA-Detection_%26_Avoidance-yellow?style=for-the-badge)](v2/crawler.py)

<br />

[🚀 Quick Start](#-quick-start) • [📖 Docs](#-documentation) • [⚙️ Configuration](#️-configuration) • [🤝 Contributing](#-contributing) • [📄 License](#-license)

</div>

---

## ✨ Why This Project?

Web crawling at scale is **hard**. Proxies rotate and die. Sites serve CAPTCHAs. Sessions expire mid-crawl. Most scrapers give up when the going gets tough.

**Crawl-Superpower-for-Bros doesn't give up.**

It's a production-grade, never-stop web crawler built to run for **days unattended** through rotating country-specific proxies. Whether you're scraping job boards, e-commerce catalogs, or any structured data site — this crawler runs until your target is met.

> **Core guarantee:** The crawl loop never stops prematurely.
> Proxies exhausted? It waits and retries. Job blocked? It rotates proxies and tries again. Crashed? It resumes exactly where it left off.

### 🎯 Key Highlights

- 🌍 **Multi-country proxy support** — Vietnam, Japan, China, South Korea, Singapore, Russia, Europe, India, USA, or no proxy
- 🔄 **14 free proxy providers** aggregated into one pool with smart scoring
- 🛡️ **Crash-safe checkpointing** — resume exactly where you left off after any crash
- 🤖 **CAPTCHA detection & avoidance** — reCAPTCHA, hCaptcha, Cloudflare Turnstile detection with automatic proxy switching
- 🥷 **CloakBrowser stealth** — fingerprint randomization, humanized behavior, geoIP matching, Patchright backend
- 🧠 **Optional LLM integration** — enrich data with Claude, GPT, Gemini, Groq, or local Ollama
- 🔐 **Optional authentication layer** — auto-login with retry/backoff, session health checks, re-auth on cookie expiry
- 📊 **Built-in dashboard** — web UI to browse and inspect results in real time
- 🗂️ **YAML-driven multi-site support** — add new sites with zero code changes

---

## 📑 Table of Contents

- [✨ Why This Project?](#-why-this-project)
- [🚀 Quick Start](#-quick-start)
- [🏗️ Architecture](#️-architecture)
- [🌍 Proxy System](#-proxy-system)
- [🛡️ Anti-Detection & CAPTCHA Handling](#️-anti-detection--captcha-handling)
- [🧠 LLM Integration (Optional)](#-llm-integration-optional)
- [🔐 Authentication Layer (Optional)](#-authentication-layer-optional)
- [⚙️ Configuration](#️-configuration)
- [🆕 Adding a New Site](#-adding-a-new-site)
- [🚫 Block Tracking](#-block-tracking)
- [🔄 How the Never-Stop Loop Works](#-how-the-never-stop-loop-works)
- [📊 Dashboard](#-dashboard)
- [📋 Requirements](#-requirements)
- [💻 Windows Notes & Troubleshooting](#-windows-notes--troubleshooting)
- [📖 Documentation](#-documentation)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)

---

## 🚀 Quick Start

### 1. Install Dependencies

``bash
cd v2
pip install -r requirements.txt
python -m cloakbrowser install
``

### 2. Fetch Proxies

``bash
# Fetch proxies for your target country
python proxy/fetcher.py --country japan
python proxy/fetcher.py --country usa
python proxy/fetcher.py --country europe

# Or verify against a specific site
python proxy/fetcher.py --site ekaigotenshoku
``

### 3. Run the Crawler

``bash
# Interactive mode (prompts for country, auth, resume)
python main.py

# Headless automation with CLI flags
python main.py --target-jobs 240 --site ekaigotenshoku

# More options
python main.py --max-pages 10
python main.py --bayesian --target-jobs 500
python main.py --backend patchright     # Use Patchright for reCAPTCHA v3 sites
python main.py --no-headless            # Show browser window
python main.py --clean                  # Delete previous run and start fresh
python main.py --help                   # See all options
``

When you run python main.py interactively, the terminal will ask:

1. **Which country proxy?** (1-9 + 0 for no proxy)
2. **Does the site require authentication?** (Y/N)
3. **Clean start / Resume / Quit?** (if a previous run exists)

### 4. View Results

``bash
python dashboard.py
``

Opens a web UI at http://localhost:3001 to browse jobs, preview HTML, and inspect crawl metadata.

---

## 🏗️ Architecture

``	ext
v2/
├── main.py              # Entry point & CLI with interactive prompts
├── crawler.py           # Never-stop crawl engine + CAPTCHA detection
├── config.py            # Configuration (env vars, CLI, defaults)
├── checkpoint.py        # Crash-safe state persistence (atomic write)
├── exporter.py          # Multi-format output (JSON, CSV, final JSON)
├── proxy_manager.py     # Proxy loading, validation, refresh
├── proxy_tracker.py     # Per-proxy scoring, auto-retirement, Bayesian model
├── site_mappings.py     # YAML-driven site configuration system
├── dashboard.py         # Web UI for browsing results
├── auth_manager.py      # Login automation with retry/backoff
├── llm_integration.py   # LLM API enrichment layer
├── auth_config.yaml     # Template: login credentials & selectors
├── llm_config.yaml      # Template: API key, model, prompt
├── sites/               # Site-specific YAML mappings
│   └── ekaigotenshoku.yaml
├── proxy/               # Proxy tools
│   ├── fetcher.py       # 14-provider multi-country proxy fetcher
│   └── checker.py       # Re-check cached proxies
└── output/              # Crawl results (auto-created)
    └── run_YYYYMMDD_HHMMSS/
        ├── jobs.json
        ├── jobs.csv
        ├── metadata.json
        ├── checkpoint.json
        ├── blocked_jobs.json
        ├── proxy_tracker.json
        ├── html/
        │   ├── detail/          # Raw detail page HTML
        │   └── list_*.html      # Raw listing page HTML
        └── output-final-json/   # Structured JSON per job
            ├── job_12345.json
            └── all_jobs.json
``

---

## 🌍 Proxy System

The crawler aggregates free proxies from **14 providers** across multiple protocols and countries.

<details>
<summary><strong>📋 Full Provider List (14 sources)</strong></summary>

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

**Supported countries:** ietnam · japan · china · south korea · singapore · ussia · europe · india · usa

### Proxy Scoring

| Mode | Description |
|------|-------------|
| **Heuristic** (default) | Score based on success rate, latency, and CAPTCHA penalty |
| **Bayesian** (--bayesian) | Beta-Binomial model + latency + Upper Confidence Bound exploration |

Proxies are auto-retired when they fail too often. CAPTCHA detections apply a 20% score penalty per event.

---

## 🛡️ Anti-Detection & CAPTCHA Handling

### CloakBrowser Stealth Layers

The crawler uses [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) — a patched Chromium binary with source-level fingerprint patches:

| Layer | What It Defeats |
|-------|-----------------|
| **Fingerprint randomization** | Canvas, WebGL, AudioContext, hardware concurrency, device memory, screen size, GPU renderer |
| **Automation suppression** | `navigator.webdriver = true` leak |
| **WebRTC IP leak protection** | Exposes real IP behind proxy via WebRTC |
| **Humanized behavior** | Bezier mouse curves, realistic typing, smooth scrolling, CDP Isolated World |
| **GeoIP auto-detection** | Timezone + locale match proxy country (prevents mismatch detection) |
| **Patchright backend** | Suppresses CDP runtime signals — helps pass reCAPTCHA v3 Enterprise |

### CAPTCHA Detection

Even with CloakBrowser, aggressive crawling can trigger challenges. The crawler detects:

- **reCAPTCHA v2/v3** — iframe/element detection
- **hCaptcha** — iframe/element detection
- **Cloudflare Turnstile** — challenge iframe detection
- **Japanese CAPTCHA pages** — text indicators

**When CAPTCHA is detected:**

1. The current proxy session is stopped immediately
2. The proxy is flagged with a CAPTCHA penalty (20% score reduction)
3. The crawler moves to the next proxy automatically
4. CAPTCHA-flagged proxies are **not** retired — they may work again after cooldown

### Choosing a Browser Backend

``bash
# Default: Playwright (full feature support)
python main.py

# Patchright: for sites using reCAPTCHA v3 Enterprise scoring
python main.py --backend patchright
``

> **Note:** Patchright suppresses CDP signals that reCAPTCHA v3 uses for bot detection. However, it breaks `add_init_script()` and proxy auth. Use only when needed.

---

## 🧠 LLM Integration (Optional)

Enrich every crawled job with AI-extracted structured data.

### Setup

1. Open `v2/llm_config.yaml`
2. Set `enabled: true`
3. Fill in your `api_key`, `base_url`, and `model`
4. Customize the `prompt` template
5. Run `python main.py` as usual

### Supported Providers

| Provider | Base URL | Example Model |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.1-70b-versatile` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | `gemini-1.5-flash` |
| Claude | Via OpenAI-compatible proxy | `claude-3-haiku` |
| Local Ollama | `http://localhost:11434/v1` | Any local model |

### How It Works

When enabled, each detail page's HTML is sent to the LLM after crawling. The returned JSON is injected into the output under the key `llm_enhanced`.

> **Security:** Your API key never leaves your machine. The code runs entirely locally.

---

## 🔐 Authentication Layer (Optional)

For sites that require login (e.g., LinkedIn, Shopee):

### Form-Based Auth

1. Open `v2/auth_config.yaml`
2. Set `enabled: true`
3. Fill in `login_url`, `username`, `password`
4. Provide CSS selectors for the form fields
5. Run `python main.py` and answer **Y** to the authentication prompt

The crawler will:

- Log in automatically before crawling (with retry + backoff, up to 3 attempts)
- Check session health before each listing page load
- Detect session expiry (silent cookie timeout, not just URL redirects)
- Re-authenticate and resume seamlessly
- Skip the proxy if login fails after all retries

### Cookie-Based Auth (Alternative)

``yaml
# auth_config.yaml
enabled: true
auth_type: "cookie"
cookies:
  - name: "session_id"
    value: "your_cookie_value"
    domain: ".example.com"
``

### Session State Persistence

For sites with OAuth/SSO login (LINE, Google), save and reuse browser state:

``python
# After successful login:
await save_auth_state(context, Path("auth_state.json"))

# Before next proxy session:
ctx = await launch_context_async(storage_state="auth_state.json")
``

---

## ⚙️ Configuration

All settings can be configured via **environment variables**, **CLI arguments**, or **direct editing**:

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

### Environment Variable Example

``bash
# .env or shell
export CRAWL_PROXY_COUNTRY=japan
export CRAWL_AUTH_REQUIRED=false
export CRAWL_TARGET_JOBS=240
python main.py
``

---

## 🆕 Adding a New Site

Create a YAML file in `v2/sites/` — **no Python code changes needed**:

``yaml
# sites/my-new-site.yaml
name: my-new-site
display_name: "My New Job Site"

url:
  listing_url: "https://example.com/jobs"
  listing_url_template: "https://example.com/jobs?page={page}"
  detail_url_pattern: "/jobs/detail/(\\d+)"

success_keywords:
  - "keyword1"
  - "keyword2"

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
``

Then run:

``bash
python main.py --site my-new-site
``

> **Tip:** If your YAML doesn't include `js_extraction_code` or `js_pagination_code`, the system falls back to the built-in mapping's JS code (if one exists for that site name).

---

## 🚫 Block Tracking

When a job's detail page is blocked or fails to load, the crawler retries it on subsequent proxy rotations. After **20 attempts** (configurable), the job is moved to `blocked_jobs.json`:

``json
{
  "permanently_blocked": [
    {
      "job_id": "1836924",
      "detail_url": "https://www.ekaigotenshoku.com/kyujin/detail?id=1836924",
      "title": "Staff",
      "retries": 20,
      "status": "permanently_blocked"
    }
  ],
  "still_retrying": [],
  "total_blocked": 1
}
``

---

## 🔄 How the Never-Stop Loop Works

``	ext
┌───────────────────────────────────────────────────────────────────┐
│  Load proxies (14 providers, country-specific)                   │
│  ├── No proxies? Wait 60s, retry ─────────────────────────────┐  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌── Proxy tracker seeds base scores ──────────────────────────┐  │
│  │   Filters retired proxies, sorts by score                   │  │
│  │   (heuristic or Bayesian with UCB bonus)                    │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  For each proxy (best-scored first):                              │
│    ├── Verify target-country IP                                   │
│    ├── Detect CAPTCHA (reCAPTCHA / hCaptcha / Turnstile)         │
│    ├── [Optional] Authenticate if site requires login             │
│    ├── Crawl listing pages                                        │
│    │   ├── Session health check (auth required sites)            │
│    │   └── CAPTCHA detection on listing pages                     │
│    └── For each job on page:                                      │
│        ├── Fetch detail HTML (with latency timing)                │
│        ├── CAPTCHA detection on detail pages                      │
│        ├── [Optional] Send HTML to LLM for enrichment             │
│        ├── Blocked? Step up delay multiplier                      │
│        ├── 20+ fails? → blocked_jobs.json                        │
│        └── Save checkpoint after each fetch                       │
│                                                                   │
│  Record session to tracker (successes / failures / captcha)       │
│  Proxy failed too often? Auto-retire                              │
│  Next proxy                                                       │
│                                                                   │
│  Check stop criteria:                                              │
│    ├── TARGET_JOBS met? → DONE                                    │
│    ├── MAX_PAGES met? → DONE                                      │
│    ├── Both None & pages exhausted? → DONE                        │
│    └── Otherwise → back to top                                     │
└───────────────────────────────────────────────────────────────────┘
``

---

## 📊 Dashboard

The built-in web dashboard lets you browse results visually:

``bash
python dashboard.py
# Opens at http://localhost:3001
``

Features:

- **Browse** all crawled jobs in a table view
- **Preview** saved HTML pages
- **Inspect** crawl metadata and statistics
- **Multi-site** aware

---

## 📋 Requirements

| Package | Version | Purpose |
|---------|---------|---------|
| Python | 3.10+ | Runtime |
| [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) | >=0.5.0 | Anti-detection stealth browser |
| requests | >=2.28.0 | HTTP client for proxy verification |
| PySocks | >=1.7.1 | SOCKS proxy support |
| pyyaml | >=6.0 | YAML site mapping parser |
| beautifulsoup4 | >=4.12.0 | HTML parsing |

Install everything at once:

``bash
pip install -r requirements.txt
python -m cloakbrowser install
``

---

## 💻 Windows Notes & Troubleshooting

### Running from the v2 directory

Always run from inside the `v2/` folder:

``bash
cd v2
python main.py --target-jobs 240
``

### Console Encoding

Windows Command Prompt and PowerShell may not render Japanese characters or special symbols by default. Use **Windows Terminal** (recommended) or run:

``powershell
chcp 65001
python main.py --target-jobs 240
``

All log output uses ASCII-safe separators so there is no crash on any Windows console.

### No-Proxy Mode

If the target site does not block your IP, select option `0` (No proxy needed) at the country prompt. The crawler will run directly without any proxy layer.

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `ImportError: attempted relative import` | Running from wrong directory | `cd v2` then `python main.py` |
| `No proxies available - waiting 60s` | No cached proxy file | Run `python proxy/fetcher.py --country {country}` first |
| `CloakBrowser` or `launch_async` not found | CloakBrowser not installed | `pip install cloakbrowser[geoip]` then `python -m cloakbrowser install` |
| `[CAPTCHA] CAPTCHA detected` | Site shows CAPTCHA challenge | Switch to next proxy; consider `--backend patchright` for v3 sites |

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [v2/README.md](v2/README.md) | Full technical documentation & architecture reference |
| [v2/FIRST-SIGHT-BY-HAND.md](v2/FIRST-SIGHT-BY-HAND.md) | Step-by-step beginner guide (no coding required) |
| [v2/PROJECT-ENHANCEMENT-SUGGESTION.md](v2/PROJECT-ENHANCEMENT-SUGGESTION.md) | Roadmap and completed enhancements |

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/my-feature`
3. **Commit** your changes: `git commit -m "Add my feature"`
4. **Push** to the branch: `git push origin feature/my-feature`
5. **Open** a Pull Request

### Ideas for Contributions

- Add new site YAML mappings for more job boards
- Add new proxy providers to the fetcher
- Add tests and CI
- Improve documentation and examples
- Report bugs via [Issues](https://github.com/dungnotnull/agentic-crawl-superpower-for-bros/issues)

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

> Use freely. Modify freely. Crawl freely.

---

<div align="center">

<br />

**Built for the bros who need data**

</div>