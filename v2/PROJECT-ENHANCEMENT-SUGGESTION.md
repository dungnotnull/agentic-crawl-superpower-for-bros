# Project Enhancement Suggestions

Ideas for future development of Crawl-Superpower-for-Bros, ordered by impact and feasibility.

---

## Completed Enhancements (v2.1)

### 1. Multi-Country Proxy Selection
**Status:** Completed  
**What changed:** The proxy fetcher now supports 9 regions (Vietnam, Japan, China, South Korea, Singapore, Russia, Europe, India, USA). On startup, `main.py` prompts the user to select a country. The fetcher dynamically parameterizes all 14 providers for the chosen country. A "No need proxy" option bypasses the proxy layer entirely for sites that do not perform IP blocking.  
**Files added/modified:** `proxy/fetcher.py`, `proxy/checker.py`, `config.py`, `proxy_manager.py`, `main.py`

### 2. LLM API Integration Layer
**Status:** Completed  
**What changed:** Added an opt-in boilerplate layer (`llm_config.yaml` + `llm_integration.py`) that allows users to connect any LLM API (Claude, GPT, Gemini, Groq, local Ollama). If enabled, each successfully crawled HTML detail page is transparently sent to the LLM for smart structured-data extraction. The returned JSON is merged into the final output under `llm_enhanced`. If the config is missing or disabled, the layer is silently skipped.  
**Files added:** `llm_config.yaml`, `llm_integration.py`  
**Files modified:** `crawler.py`, `exporter.py`

### 3. Dynamic Authentication Layer
**Status:** Completed  
**What changed:** Added an opt-in authentication system (`auth_config.yaml` + `auth_manager.py`) for protected websites. On startup, `main.py` asks whether the target site requires authentication. If yes, the crawler injects an automated login flow before crawling. It detects session expiry (redirects to the login page) and re-authenticates automatically throughout the run.  
**Files added:** `auth_config.yaml`, `auth_manager.py`  
**Files modified:** `crawler.py`, `main.py`, `config.py`

---

## High Impact

### 1. Headless Proxy Fetcher (No Browser Dependency for Proxy Validation)
**Current state:** Proxy fetcher uses `requests` (good), but the crawler requires CloakBrowser which depends on a local Chrome installation.
**Enhancement:** Add a lightweight mode that uses `requests` + `PySocks` for sites that do not require JavaScript rendering. This would allow running on headless servers without Chrome.
**Impact:** Enables deployment on VPS/cloud without GUI.

### 2. Distributed Crawling
**Current state:** Single-process, single-machine.
**Enhancement:** Add a Redis-based task queue so multiple machines can crawl the same site concurrently. Each worker claims a page range, fetches details, and reports results back.
**Impact:** 5-10x throughput for large crawls. Essential for sites with 10,000+ listings.

### 3. Smart Proxy Scheduling
**Current state:** Round-robin proxy rotation with score-based ordering + Bayesian scoring already implemented.
**Enhancement:** Extend the existing Bayesian + heuristic tracker to learn per-country and per-site success patterns. Build predictive models that choose the best country proxy pool for a given target site automatically.
**Impact:** Fewer wasted requests, faster completion, less IP blocking.

### 4. Incremental Crawls (Delta Mode)
**Current state:** Each run starts from scratch or resumes an incomplete run.
**Enhancement:** Add `--delta` mode that compares the current listing page against the last run's checkpoint. Only fetch detail pages for new or changed jobs.
**Impact:** Dramatic reduction in bandwidth and time for recurring crawls (e.g., daily monitoring).

---

## Medium Impact

### 5. Extraction Playground
**Current state:** JS extraction code is written in YAML or Python strings. Testing requires a full crawl run.
**Enhancement:** Add an interactive tool that opens a browser to a listing page, lets you write/test JS extraction code in real-time, and shows the extracted results immediately.
**Impact:** Much faster site mapping development. Non-programmers could create mappings.

### 6. Notification System
**Current state:** Silent completion (or crash).
**Enhancement:** Add webhook/Slack/Discord notifications for: crawl completion, block threshold exceeded, proxy exhaustion, and error rates.
**Impact:** Peace of mind for multi-day unattended runs.

### 7. Rate Limiting Detection & Adaptation
**Current state:** Fixed delay ranges between requests. Basic rate-limit detection already implemented (steps up delay multiplier on block detection).
**Enhancement:** Detect additional signals (429 responses, CAPTCHA pages, fingerprint-based blocking) and adapt browser fingerprints per proxy.
**Impact:** Fewer blocks, more reliable long-running crawls.

### 8. Structured Output Schema Validation
**Current state:** Output JSON fields are whatever the JS extraction code returns.
**Enhancement:** Define JSON Schema for each site mapping. Validate extracted data against the schema. Flag records that do not conform.
**Impact:** Data quality assurance, especially important when aggregating across multiple sites.

### 9. Multi-Site Aggregation
**Current state:** Each site is crawled independently.
**Enhancement:** Add an aggregation mode that crawls multiple sites and merges results into a unified schema. Deduplicate across sites by fuzzy matching on title + company + location.
**Impact:** Comprehensive job market coverage from a single tool.

---

## Lower Impact / Quality of Life

### 10. Progress Bar & ETA
**Current state:** Text-based logging with job counts.
**Enhancement:** Add a `rich` progress bar showing: jobs found / target, current proxy, pages crawled, estimated time remaining.
**Impact:** Better visibility during long runs.

### 11. Docker Support
**Current state:** Requires local Python + Chrome installation.
**Enhancement:** Dockerfile with Chrome, CloakBrowser, and all dependencies pre-installed. Docker Compose for running crawler + dashboard.
**Impact:** One-command deployment on any platform.

### 12. API Server Mode
**Current state:** CLI-only interaction.
**Enhancement:** Add a FastAPI server that exposes crawl status, starts/stops crawls, and serves results via REST API.
**Impact:** Enables integration with other tools and dashboards.

### 13. Export to Databases
**Current state:** JSON and CSV output only.
**Enhancement:** Add optional export to PostgreSQL, MongoDB, or Elasticsearch with configurable schema mapping.
**Impact:** Direct integration with data pipelines.

### 14. Captcha Solving Integration
**Current state:** No CAPTCHA handling — blocked pages are retried with different proxies.
**Enhancement:** Integrate with CAPTCHA solving services (2captcha, anticaptcha) for sites that use them.
**Impact:** Access to sites that use CAPTCHA as their primary anti-bot measure.

### 15. Proxy Pool Health Dashboard
**Current state:** Proxy health is checked via CLI tools.
**Enhancement:** Add a proxy health section to the web dashboard showing: active proxies, their scores, success rates, and geographic distribution on a map.
**Impact:** Better operational visibility.

---

## Implementation Priority

If implementing these, the recommended order is:

1. **Distributed Crawling** (#2) — unlocks scale
2. **Incremental Crawls** (#4) — unlocks recurring use
3. **Smart Proxy Scheduling** (#3) — improves reliability
4. **Notification System** (#6) — enables unattended operation
5. **Extraction Playground** (#5) — accelerates site onboarding
6. Everything else in any order

---

*This document is a living roadmap. Update it as enhancements are implemented or priorities change.*
