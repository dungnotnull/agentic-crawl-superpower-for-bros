# CLAUDE.md — Project Context for AI Assistants

## Project Overview

Crawl-Superpower-for-Bros is a modular, never-stop web crawler for Japanese job sites. It runs through rotating proxies with crash-safe checkpointing and produces both raw HTML and structured JSON output. All code, comments, and documentation are in **English only**.

## Architecture

The v2 codebase is a complete rewrite of v1, designed for multi-site support and extensibility:

- **`main.py`** — Entry point with CLI argument parsing and startup banner. Never calls `sys.exit()` on proxy exhaustion; always waits.
- **`crawler.py`** — The `CrawlEngine` class with the `crawl_forever()` method. This is the never-stop loop. It only exits when TARGET_JOBS/MAX_PAGES criteria are met or pages are exhausted. Includes rich real-time logging with elapsed time, job IDs, names, and progress percentages.
- **`config.py`** — `CrawlConfig` dataclass. All tunables in one place. Supports env vars and CLI overrides.
- **`checkpoint.py`** — Atomic checkpoint saves (write-to-tmp + rename). Version 2 format with block_threshold field.
- **`exporter.py`** — `save_results()` for JSON/CSV/metadata, `save_final_json()` for per-job structured JSON in `output-final-json/`. Handles both string and dict field definitions from site mappings.
- **`proxy_manager.py`** — `ProxyManager` loads from cache, auto-refetches if stale (30-min TTL), falls back to local proxies. Logs proxy stats (JP count, site-OK count, top score). Integrates with `ProxyTracker` for runtime scoring and retirement filtering.
- **`proxy_tracker.py`** — `ProxyTracker` tracks per-proxy runtime stats (successes, failures, blocks, latency). Two scoring modes: heuristic (`base × success_ratio × block_penalty × time_decay`) and Bayesian (Beta-Binomial posterior + Normal-Gamma latency + UCB exploration). Auto-retires proxies after N consecutive failures. Persists to `proxy_tracker.json` in the run directory.
- **`site_mappings.py`** — `SiteMapping` dataclass + YAML loader. Built-in mapping for ekaigotenshoku with JS extraction/pagination code. New sites via YAML files in `sites/`. If YAML doesn't define JS code, falls back to built-in mapping's JS code.
- **`dashboard.py`** — Embedded SPA web server for browsing results. Multi-site aware.
- **`proxy/fetcher.py`** — Multi-provider proxy fetcher (v4) with 14 free proxy sources: Proxifly (4 endpoints), ProxyScrape (3 endpoints), GeoNode, FreeProxyList CDN, Monosans (2 endpoints), SpeedX (2 endpoints), ClarkEtM. Supports 3 response formats: proxifly JSON, plain text, geonode API.
- **`proxy/checker.py`** — Re-validates cached proxies with TTL awareness. Auto-refetches if no working proxies found.

## Critical Design Decisions

1. **Never-stop loop**: The crawl engine MUST NOT exit when proxies are unavailable. It waits 60s and retries. The only exit conditions are: TARGET_JOBS met, MAX_PAGES met, or pages exhausted when both limits are None.

2. **Block threshold**: Jobs that fail after 20 attempts (configurable) are moved to `blocked_jobs.json` with status "permanently_blocked". The crawler continues with remaining jobs.

3. **Block detection keywords**: Must be specific to avoid false positives. The v1 bug where `"403 "` matched Japanese postal code `861-2403` was fixed by using `"403 error"` instead. Current BLOCK_KW list is in `crawler.py`.

4. **Checkpoint atomicity**: Uses write-to-tmp + `os.replace()` to prevent corruption on crash.

5. **Site mappings via YAML**: New sites require only a YAML file + optional JS extraction code. No Python code changes needed. If YAML doesn't include JS code, built-in mapping's JS code is used as fallback.

6. **Dual output**: Raw HTML in `html/detail/` for cross-referencing, structured JSON in `output-final-json/` for consumption.

7. **14 proxy providers**: Aggregating from multiple free sources dramatically increases the probability of finding active Japanese proxies. The fetcher supports 3 response formats (proxifly JSON, plain text, geonode API) and deduplicates across all providers.

8. **Real-time logging**: Every action is logged with elapsed time, tagged category, and contextual details (job ID, title, progress percentage). Uses `_log()` and `_log_banner()` functions in `crawler.py` with Windows-safe Unicode handling.

9. **YAML field format**: YAML site mappings define fields as dicts with `source` and optional `transform` keys. Built-in mappings use simple string fields. The exporter handles both formats.

10. **Smart proxy scheduling**: `ProxyTracker` replaces round-robin with scored proxy selection. Two modes: heuristic (default, uses `real_score × success_ratio × block_penalty × time_decay`) and Bayesian (`--bayesian`, uses Beta-Binomial P(success) × latency penalty + UCB exploration). Proxies auto-retire after 5 consecutive failures or 3 consecutive blocks. Tracker persists to `proxy_tracker.json` in the run directory for crash-safe resume.

11. **Rate limiting adaptation**: When a block is detected (listing OR detail page), the delay multiplier steps up by 0.5x (max 4.0x). After 20 successful fetches, it steps down by 0.1x. Rate limit state is per-proxy-session — new proxies start fresh. This is independent of the existing block detection and retry system, which still runs underneath.

12. **Latency tracking**: `fetch_detail_page()` timestamps every successful detail fetch via Welford's online algorithm (constant memory). In Bayesian mode, latency variance penalizes proxies with slow/unstable response times. In heuristic mode, latency data is collected but doesn't affect scoring.

13. **CAPTCHA detection**: `_detect_captcha()` checks for reCAPTCHA, hCaptcha, Cloudflare Turnstile iframes/elements and Japanese/English CAPTCHA text indicators. When detected, the proxy session is stopped and the proxy is flagged in `ProxyTracker` with a score penalty. CAPTCHA-flagged proxies are NOT immediately retired ? they may work again after cooldown. This is independent of block detection and runs alongside it.

14. **Browser backend selection**: CloakBrowser supports two Playwright backends: `playwright` (default) and `patchright`. Patchright suppresses CDP runtime signals which helps pass reCAPTCHA v3 Enterprise detection, but breaks `add_init_script()` and proxy auth. Selected via `--backend patchright` CLI flag or `CRAWL_BROWSER_BACKEND=patchright` env var.

15. **Auth config loaded once**: `CrawlEngine.__init__()` loads `auth_config.yaml` once and passes it to all `crawl_with_proxy()` and `_retry_blocked_jobs()` calls. This prevents inconsistent behavior if the file is edited mid-crawl.

16. **Session health checks**: Before loading each listing page on auth-required sites, `ensure_authenticated()` is called. If the session expired (cookie timeout, not just URL redirect), it re-authenticates automatically. This handles sites that silently expire sessions without redirecting to a login page.

17. **CAPTCHA scoring penalty**: In `ProxyTracker`, each CAPTCHA detection reduces the proxy's score by 20% (multiplicative `0.80 ** captcha_count`). This applies in both heuristic and Bayesian modes. The tracker's `summary()` includes CAPTCHA counts when present.

18. **Auth retry with backoff**: `authenticate()` in `auth_manager.py` now retries up to `login_max_attempts` (default 3) with exponential backoff (5s, 10s, 15s). Configurable in `auth_config.yaml`.

19. **Session state persistence**: `auth_manager.py` provides `save_auth_state()` and `has_saved_auth_state()` helpers using Playwright's `storage_state` API. This enables cookie reuse across proxy switches for auth-required sites.

## Language

All code, comments, and documentation are in **English only**. No Vietnamese text anywhere in v2.

## Testing

Run the proxy fetcher first, then the crawler:
```bash
python proxy/fetcher.py    # Get working JP proxies from 14 providers
python main.py --target-jobs 10  # Quick test crawl
python dashboard.py        # View results
```

## Common Gotchas

- CloakBrowser requires Chrome installed via `python -m cloakbrowser install`
- Windows consoles may not support Unicode — `_log()` / `safe_print()` handles this
- Proxy cache has a 30-minute TTL; stale caches trigger automatic re-fetch
- The `output-final-json/` directory is created per run, inside the run directory
- YAML site mappings that don't define JS code will fall back to built-in mapping's JS code
- The `sites/ekaigotenshoku.yaml` file exists but doesn't define JS code — the built-in mapping provides it
- Proxy fetcher v4 supports 3 response formats; adding a new provider requires adding a dict to the `PROVIDERS` list and optionally a new parser function
- `ProxyTracker` is optional everywhere — defaults to `None`. All existing proxy/engine code works without it.
- Bayesian mode is **off by default** — enable with `--bayesian` or `CRAWL_USE_BAYESIAN=true`. It requires more observations to converge, so it's best for long runs (500+ jobs).
- Rate limit multiplier applies to ALL delays (listing page, detail page). Logged as `[RATE]` tags in terminal output.
