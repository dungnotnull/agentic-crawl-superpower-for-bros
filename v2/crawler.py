"""
Crawl Engine — The never-stop orchestrator with real-time logging.

Core guarantees:
  - The loop NEVER breaks until TARGET_JOBS or MAX_PAGES is met,
    or all pages are exhausted (when both limits are None).
  - If no proxies are available, it WAITS and keeps searching.
  - Jobs that fail after BLOCK_THRESHOLD attempts are moved to a
    block tracking file for user visibility.
  - Simultaneously outputs raw HTML and structured JSON.
  - Rich real-time logging: every action is visible in the terminal.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from cloakbrowser import launch_async

try:
    from .auth_manager import (
        authenticate,
        ensure_authenticated,
        is_authenticated,
        load_auth_config,
    )
    from .checkpoint import (
        checkpoint_to_jobs,
        find_latest_incomplete_run,
        init_checkpoint,
        load_checkpoint,
        save_checkpoint,
    )
    from .config import CrawlConfig
    from .exporter import dedup, save_results, save_final_json
    from .proxy_tracker import ProxyTracker
    from .site_mappings import SiteMapping
except ImportError:
    from auth_manager import (  # type: ignore[no-redef]
        authenticate,
        ensure_authenticated,
        is_authenticated,
        load_auth_config,
    )
    from checkpoint import (  # type: ignore[no-redef]
        checkpoint_to_jobs,
        find_latest_incomplete_run,
        init_checkpoint,
        load_checkpoint,
        save_checkpoint,
    )
    from config import CrawlConfig  # type: ignore[no-redef]
    from exporter import dedup, save_results, save_final_json  # type: ignore[no-redef]
    from proxy_tracker import ProxyTracker  # type: ignore[no-redef]
    from site_mappings import SiteMapping  # type: ignore[no-redef]


# ── Logging ───────────────────────────────────────────────────────────────

_log_start_time: float = 0


def _elapsed() -> str:
    """Return elapsed time string since crawl started."""
    if _log_start_time == 0:
        return "00:00"
    secs = int(time.time() - _log_start_time)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _log(tag: str, msg: str, end: str = "\n") -> None:
    """Print a tagged log line with elapsed time."""
    line = f"  {_elapsed()} [{tag}] {msg}"
    try:
        print(line, end=end, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            line.encode("utf-8", errors="replace") + end.encode())
        sys.stdout.flush()


def _log_banner(text: str) -> None:
    """Print a prominent banner line."""
    sep = "=" * 72
    line = f"\n{sep}\n  {text}\n{sep}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(line.encode("utf-8", errors="replace") + b"\n")
        sys.stdout.flush()


def _log_progress(current: int, target: int | None, label: str = "jobs") -> str:
    """Build a progress string like '142/240 jobs (59%)' or '142 jobs'."""
    if target is not None and target > 0:
        pct = min(100, int(current / target * 100))
        return f"{current}/{target} {label} ({pct}%)"
    return f"{current} {label}"


# ── Block tracking ────────────────────────────────────────────────────────

BLOCK_KW = [
    "access denied", "forbidden", "403 error", "request blocked",
    "your request could not be satisfied",
    "アクセス制限", "地域制限", "ご利用いただけません",
]


# CAPTCHA detection selectors - used by _detect_captcha()
CAPTCHA_SELECTORS = [
    # reCAPTCHA v2/v3
    'iframe[src*="recaptcha"]',
    'div.g-recaptcha',
    'script[src*="recaptcha"]',
    # hCaptcha
    'iframe[src*="hcaptcha"]',
    'div.h-captcha',
    # Cloudflare Turnstile
    'iframe[src*="challenges.cloudflare.com"]',
    'div.cf-turnstile',
    # Cloudflare challenge page
    'div.cf-browser-verification',
    'div#challenge-running',
]

CAPTCHA_TEXT_INDICATORS = [
    "入力確認",        # input confirmation (Japanese)
    "セキュリティ確認",  # security verification (Japanese)
    "認証してください",  # please authenticate (Japanese)
    "通過するには",    # to proceed (Japanese CAPTCHA prompt)
    "verify you are human",
    "checking your browser",
    "please complete the security check",
    "are you a robot",
]






async def _detect_captcha(page, html: str | None = None) -> str | None:
    """Detect CAPTCHA challenges on the current page.

    Checks for known CAPTCHA iframes/elements and text indicators.
    Returns a description string if CAPTCHA is detected, else None.
    """
    # Check DOM selectors
    for selector in CAPTCHA_SELECTORS:
        try:
            el = await page.query_selector(selector)
            if el:
                return f"CAPTCHA element: {selector}"
        except Exception:
            pass

    # Check text content
    text_to_check = html if html else await page.content()
    text_lower = text_to_check.lower()
    for indicator in CAPTCHA_TEXT_INDICATORS:
        if indicator.lower() in text_lower:
            return f"CAPTCHA text: {indicator}"

    return None

def _record_blocked_job(state: dict, job_id: str | int, detail_url: str,
                        title: str, threshold: int = 20) -> bool:
    """Record a blocked/failed job. Returns True if threshold exceeded."""
    job_id = str(job_id).strip()
    blocked = state.setdefault("blocked_jobs", [])
    for b in blocked:
        if str(b.get("job_id", "")).strip() == job_id:
            b["retries"] = b.get("retries", 0) + 1
            b["last_attempt"] = datetime.now().isoformat()
            if b["retries"] >= threshold:
                b["status"] = "permanently_blocked"
                return True
            return False
    blocked.append({
        "job_id": job_id,
        "detail_url": detail_url,
        "title": title,
        "retries": 1,
        "last_attempt": datetime.now().isoformat(),
        "status": "retrying",
    })
    return False


def _save_block_file(run_dir: Path, state: dict) -> None:
    """Write blocked jobs to a separate tracking file."""
    blocked = state.get("blocked_jobs", [])
    if not blocked:
        return
    perm = [b for b in blocked if b.get("status") == "permanently_blocked"]
    retrying = [b for b in blocked if b.get("status") != "permanently_blocked"]
    out = {
        "updated_at": datetime.now().isoformat(),
        "block_threshold": state.get("block_threshold", 20),
        "permanently_blocked": perm,
        "still_retrying": retrying,
        "total_blocked": len(perm),
        "total_retrying": len(retrying),
    }
    path = run_dir / "blocked_jobs.json"
    tmp = run_dir / "blocked_jobs.json.tmp"
    try:
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception as e:
        _log("WARN", f"Failed to save block file: {e}")


# ── Browser helpers ───────────────────────────────────────────────────────

async def verify_country_ip(page, country_code: str = "JP") -> tuple[bool, str]:
    """Verify that the proxy IP matches the target country.

    Only rejects if we POSITIVELY confirm wrong country. Timeouts and errors
    pass through (the fetcher already verified country via HTTP).
    """
    if country_code.upper() == "DIRECT" or not country_code:
        return True, "direct"
    COUNTRY_ISO = {
        "JAPAN": "JP", "VIETNAM": "VN", "CHINA": "CN", "SOUTH KOREA": "KR",
        "SINGAPORE": "SG", "RUSSIA": "RU", "EUROPE": "EU", "INDIA": "IN", "USA": "US",
    }
    cc = COUNTRY_ISO.get(country_code.upper(), country_code.upper())
    try:
        await page.goto("https://httpbin.org/ip",
                        wait_until="domcontentloaded", timeout=15000)
        content = await page.content()
        # httpbin.org/ip returns {"origin": "x.x.x.x"} — use ip-api for country
        m_ip = re.search(r'"origin"\s*:\s*"([^"]+)"', content)
        ip_str = m_ip.group(1) if m_ip else None
    except Exception:
        # Timeout/error — proxy is slow but not proven wrong. Let it pass.
        return True, "timeout-pass"

    if not ip_str:
        return True, "timeout-pass"

    try:
        await page.goto(f"https://ip-api.com/json/{ip_str}?fields=countryCode",
                        wait_until="domcontentloaded", timeout=10000)
        content2 = await page.content()
        m = re.search(r'"countryCode"\s*:\s*"([A-Z]{2})"', content2)
        verified_cc = m.group(1) if m else None
    except Exception:
        # Can't determine country — let it pass
        return True, ip_str

    if verified_cc:
        if cc == "EU":
            eu_codes = {"AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR",
                        "DE","GR","HU","IE","IT","LV","LT","LU","MT","NL",
                        "PL","PT","RO","SK","SI","ES","SE","GB","NO","CH",
                        "UA","IS","LI"}
            if verified_cc not in eu_codes:
                return False, ip_str
        elif verified_cc != cc:
            return False, ip_str

    return True, ip_str
async def extract_jobs_with_mapping(page, page_num: int, proxy: str,
                                    mapping: SiteMapping) -> list[dict]:
    """Extract job cards using the site mapping's JS extraction code."""
    items = await page.evaluate(mapping.js_extraction_code)
    for it in items:
        it["page"] = page_num
        it["crawled_at"] = datetime.now().isoformat()
        it["proxy_used"] = proxy
        # Normalize job_id to string to prevent dedup mismatches
        if it.get("job_id") is not None:
            it["job_id"] = str(it["job_id"]).strip()
    return items


async def find_next_page(page, mapping: SiteMapping) -> str | None:
    """Find the next page URL using the site mapping's pagination JS."""
    return await page.evaluate(mapping.js_pagination_code)


# ── Detail page fetcher ──────────────────────────────────────────────────

async def fetch_detail_page(page, job_id: str, detail_url: str,
                            detail_dir: Path, config: CrawlConfig,
                            rate_limit: dict | None = None,
                            max_retries: int = 2,
                            latencies: list[float] | None = None,
                            ) -> tuple[bool, str | None]:
    """Fetch one detail page, save HTML. Returns (success, relative_html_path).

    If a ``rate_limit`` dict is provided, it will be updated on:
      - Block detection → step up the multiplier (slow down)
      - Success → increment recovery counter, step down after threshold

    If a ``latencies`` list is provided, elapsed times of successful
    detail-page loads are appended for Bayesian latency modeling.
    """
    for attempt in range(max_retries + 1):
        try:
            t0 = time.time()
            await page.goto(detail_url, wait_until="load", timeout=45000)
            elapsed = time.time() - t0
            await asyncio.sleep(random.uniform(config.detail_delay_min,
                                               config.detail_delay_max) *
                                (rate_limit["current_multiplier"] if rate_limit else 1.0))

            html = await page.content()

            # Check for CAPTCHA on detail page
            captcha = await _detect_captcha(page, html)
            if captcha:
                _log("CAPTCHA", f"CAPTCHA detected on detail page: {captcha}")
                return False, None

            blocked = any(kw in html.lower() for kw in BLOCK_KW)
            if blocked:
                debug_path = detail_dir / f"job_{job_id}_blocked_attempt{attempt}.html"
                try:
                    debug_path.write_text(html, encoding="utf-8")
                except Exception:
                    pass
                matched_kw = [kw for kw in BLOCK_KW if kw in html.lower()]

                # Step up rate limit multiplier
                if rate_limit:
                    old = rate_limit["current_multiplier"]
                    rate_limit["current_multiplier"] = min(
                        config.rate_limit_multiplier_max,
                        old + config.rate_limit_step_up)
                    rate_limit["recovery_counter"] = 0
                    rate_limit["detections_this_session"] += 1
                    _log("RATE", f"Block detected (matched: {matched_kw}), "
                         f"delay multiplier {old}x -> {rate_limit['current_multiplier']}x")

                if attempt < max_retries:
                    backoff = 4 * (2 ** attempt)
                    _log("BLOCK", f"Job {job_id} blocked (matched: {matched_kw}), "
                         f"retry {attempt+1}/{max_retries} after {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                _log("FAIL", f"Job {job_id} BLOCKED by {matched_kw} "
                     f"after {max_retries+1} attempts")
                return False, None

            if "</html>" not in html[:100] and "</html>" not in html[-200:]:
                if attempt < max_retries:
                    _log("WARN", f"Job {job_id} incomplete page, "
                         f"retry {attempt+1}/{max_retries}")
                    await asyncio.sleep(4)
                    continue
                _log("FAIL", f"Job {job_id} incomplete page after "
                     f"{max_retries+1} attempts")
                return False, None

            html_filename = f"job_{job_id}.html"
            html_path = detail_dir / html_filename
            html_path.write_text(html, encoding="utf-8")

            # Step down rate limit on sustained success
            if rate_limit:
                rate_limit["recovery_counter"] += 1
                if rate_limit["recovery_counter"] >= config.rate_limit_recovery_hits:
                    old = rate_limit["current_multiplier"]
                    rate_limit["current_multiplier"] = max(
                        config.rate_limit_multiplier_min,
                        old - config.rate_limit_step_down)
                    rate_limit["recovery_counter"] = 0
                    _log("RATE", f"Sustained recovery, "
                         f"delay multiplier {old}x -> {rate_limit['current_multiplier']}x")

            # Record latency for Bayesian modeling
            if latencies is not None:
                latencies.append(elapsed)

            return True, f"html/detail/{html_filename}"

        except Exception as e:
            # Don't retry on connection errors — proxy is likely dead
            if "ERR_TIMED_OUT" in str(e) or "ERR_CONNECTION" in str(e) or "ERR_PROXY" in str(e):
                _log("DEAD", f"Job {job_id} {type(e).__name__} — proxy appears dead, not retrying")
                return False, None
            if attempt < max_retries:
                backoff = 4 * (2 ** attempt)
                _log("WARN", f"Job {job_id} {type(e).__name__} ({e}), "
                     f"retry {attempt+1}/{max_retries} after {backoff}s")
                await asyncio.sleep(backoff)
                continue
            _log("FAIL", f"Job {job_id} {type(e).__name__} after "
                 f"{max_retries+1} attempts — {e}")
            return False, None

    return False, None


# ── Single-proxy crawl session ────────────────────────────────────────────

async def crawl_with_proxy(proxy: str, needed: int, run_dir: Path,
                           proxy_idx: int, state: dict,
                           mapping: SiteMapping, config: CrawlConfig,
                           start_page: int = 1,
                           resume_detail_only: bool = False,
                           total_so_far: int = 0,
                           tracker: ProxyTracker | None = None,
                           auth_config: dict[str, Any] | None = None,
                           ) -> tuple[list[dict], int, int]:
    """Crawl listing pages + detail pages with full checkpointing.

    Returns (new_items, pages_visited).
    """
    _log_banner(f"PROXY #{proxy_idx}: {proxy}")
    _log("INFO", f"Need ~{needed} more jobs | "
         f"Progress: {_log_progress(total_so_far, config.target_jobs)}")

    detail_dir = run_dir / "html" / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    browser = None
    new_items: list[dict] = []
    fetches_done = 0
    fetches_failed = 0
    blocks_detected = 0
    pages_visited = 0

    # Rate limiter state for this proxy session
    rate_limit = {
        "current_multiplier": config.rate_limit_multiplier_min,
        "recovery_counter": 0,
        "detections_this_session": 0,
    }
    # Latency observations for Bayesian modeling
    latencies: list[float] = []

    try:
        _log("BROWSER", "Launching CloakBrowser (headless, humanized, geoIP)...")
        browser = await launch_async(
            headless=config.headless, proxy=proxy,
            humanize=True, geoip=True, human_preset="careful",
            backend=config.browser_backend,
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
        )
        page = await context.new_page()

        country_code = config.proxy_country.upper() if config.use_proxy else "DIRECT"
        _log("VERIFY", f"Checking if proxy IP is {country_code}...")
        is_target_country, ip_addr = await verify_country_ip(page, country_code)
        if not is_target_country:
            _log("SKIP", f"IP is not {country_code} ({ip_addr}) — skipping this proxy")
            return [], 0, 0
        _log("OK", f"{country_code} IP confirmed: {ip_addr}")

        # CAPTCHA detection at session start
        captcha = await _detect_captcha(page)
        if captcha:
            _log("CAPTCHA", f"CAPTCHA detected on session start: {captcha} - skipping proxy")
            return [], 0, 0

        # Authentication layer (if required)
        if auth_config and config.auth_required:
            _log("AUTH", "Target site requires authentication - logging in...")
            login_ok = await authenticate(page, auth_config)
            if not login_ok:
                _log("AUTH", "Login failed - skipping this proxy")
                return [], 0, 0

        # Warm up with Google Japan
        _log("WARMUP", "Navigating to google.co.jp...")
        await page.goto("https://www.google.co.jp",
                        wait_until="domcontentloaded", timeout=18000)
        await asyncio.sleep(random.uniform(1.5, 3.0))
        _log("WARMUP", "Browser session ready")

        # ── Resume: finish pending detail fetches ──
        if resume_detail_only and state.get("pages"):
            pg = state["pages"][-1]
            if pg and pg.get("status") == "details_pending":
                _log("RESUME", f"Resuming detail fetching for page {pg['page_num']} "
                     f"({len(pg['jobs'])} jobs)")
                listing_url = pg["url"]
                for job_idx, job in enumerate(pg["jobs"], 1):
                    if job.get("detail_fetched"):
                        continue
                    jid = job.get("job_id")
                    durl = job.get("detail_url")
                    title = job.get("title", "?")
                    if not durl:
                        job["detail_fetched"] = True
                        continue

                    _log("CRAWL", f"Fetching job {jid} \"{title[:40]}\" "
                         f"({job_idx}/{len(pg['jobs'])})...")
                    success, detail_path = await fetch_detail_page(
                        page, jid, durl, detail_dir, config,
                        rate_limit=rate_limit, latencies=latencies)
                    job["detail_fetched"] = success
                    job["detail_html"] = detail_path
                    save_checkpoint(run_dir, state)

                    if success:
                        new_items.append({
                            "job_id": jid, "title": job.get("title"),
                            "company": job.get("company"), "salary": job.get("salary"),
                            "location": job.get("location"), "jobType": job.get("jobType"),
                            "detail_url": durl, "detail_html_path": detail_path,
                            "link": durl, "page": pg["page_num"], "page_url": listing_url,
                            "page_html_path": pg.get("list_html_path"),
                            "crawled_at": job.get("crawled_at"), "proxy_used": proxy,
                        })
                        state["total_jobs_extracted"] += 1
                        fetches_done += 1
                        _log("SAVED", f"Job {jid} \"{title[:40]}\" -> "
                             f"{_log_progress(state['total_jobs_extracted'], config.target_jobs)}")
                    else:
                        fetches_failed += 1
                        blocks_detected += 1
                        exceeded = _record_blocked_job(
                            state, jid, durl, job.get("title", ""),
                            threshold=config.block_threshold)
                        if exceeded:
                            _log("BLOCK", f"Job {jid} \"{title[:40]}\" -> "
                                 f"PERMANENTLY BLOCKED after {config.block_threshold} attempts")
                            _save_block_file(run_dir, state)
                        else:
                            _log("BLOCK", f"Job {jid} \"{title[:40]}\" -> "
                                 f"blocked (will retry later)")
                        # Session recovery
                        try:
                            await page.close()
                        except Exception:
                            pass
                        try:
                            page = await context.new_page()
                            await page.goto(listing_url,
                                            wait_until="domcontentloaded", timeout=30000)
                            if auth_config and config.auth_required:
                                if not await ensure_authenticated(page, auth_config):
                                    _log("AUTH", "Session recovery: re-authenticating...")
                                    await authenticate(page, auth_config)
                            await asyncio.sleep(random.uniform(2.0, 4.0))
                        except Exception:
                            pass

                    if config.target_jobs is not None and fetches_done >= needed:
                        break

                pg["status"] = "complete"
                save_checkpoint(run_dir, state)
                start_page = pg["page_num"] + 1

        # ── Normal page loop ──
        current_url = None
        empty_streak = 0

        if state.get("pages") and start_page <= len(state["pages"]):
            pg_entry = state["pages"][start_page - 1]
            if pg_entry:
                current_url = pg_entry.get("url", "")

        if not current_url:
            current_url = mapping.url.listing_url
            if start_page > 1:
                current_url = mapping.url.listing_url_template.format(page=start_page)

        page_num = start_page
        pages_done_this_proxy = 0

        while True:
            if config.max_pages is not None and pages_done_this_proxy >= config.max_pages:
                _log("LIMIT", f"Reached {config.max_pages} pages for this proxy — stopping")
                break
            if config.target_jobs is not None and fetches_done >= needed:
                _log("TARGET", f"Target met for this proxy — stopping")
                break

            _log("PAGE", f"Loading listing page {page_num}: {current_url[:70]}...")
            await page.goto(current_url, wait_until="domcontentloaded", timeout=45000)
            # Session health check for auth-protected sites
            if auth_config and config.auth_required:
                if not await ensure_authenticated(page, auth_config):
                    _log("AUTH", "Session expired - re-authenticating...")
                    login_ok = await authenticate(page, auth_config)
                    if not login_ok:
                        _log("AUTH", "Re-authentication failed - stopping this proxy")
                        break
                    await page.goto(current_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(config.delay_min, config.delay_max) *
                                rate_limit["current_multiplier"])
            pages_visited += 1

            html = await page.content()

            # Save listing HTML
            html_filename = f"list_proxy{proxy_idx}_page{page_num}.html"
            list_html_path = run_dir / "html" / html_filename
            rel_list_path = f"html/{html_filename}"
            try:
                list_html_path.write_text(html, encoding="utf-8")
            except Exception as e:
                _log("WARN", f"Failed to save listing HTML: {e}")

            # Check for CAPTCHA on listing page
            captcha = await _detect_captcha(page, html)
            if captcha:
                _log("CAPTCHA", f"CAPTCHA detected on listing page {page_num}: {captcha}")
                if tracker:
                    tracker.record_captcha(proxy)
                break

            if any(kw in html.lower() for kw in BLOCK_KW):
                # Step up rate limit on listing block
                old = rate_limit["current_multiplier"]
                rate_limit["current_multiplier"] = min(
                    config.rate_limit_multiplier_max,
                    old + config.rate_limit_step_up)
                rate_limit["recovery_counter"] = 0
                rate_limit["detections_this_session"] += 1
                _log("RATE", f"Listing block detected, delay multiplier "
                     f"{old}x -> {rate_limit['current_multiplier']}x")
                _log("BLOCK", f"Blocked at listing page {page_num} — stopping this proxy")
                break
            if not any(kw in html for kw in mapping.success_keywords):
                _log("WARN", f"No JP content at page {page_num}")
                if page_num == start_page:
                    return [], pages_visited, 0
                empty_streak += 1
                if empty_streak >= config.max_empty:
                    _log("EMPTY", f"{empty_streak} consecutive empty pages — stopping")
                    break
                next_url = await find_next_page(page, mapping)
                if not next_url:
                    _log("END", "No next page link found")
                    break
                current_url = next_url
                page_num += 1
                pages_done_this_proxy += 1
                continue

            _log("EXTRACT", f"Extracting job cards from page {page_num}...")
            items = await extract_jobs_with_mapping(page, page_num, proxy, mapping)
            if not items:
                empty_streak += 1
                _log("EMPTY", f"0 jobs extracted (streak: {empty_streak})")
                if empty_streak >= config.max_empty:
                    break
                next_url = await find_next_page(page, mapping)
                if not next_url:
                    break
                current_url = next_url
                page_num += 1
                pages_done_this_proxy += 1
                continue

            empty_streak = 0
            _log("OK", f"{len(items)} jobs found on page {page_num}")

            # Log each discovered job
            for idx, it in enumerate(items, 1):
                jid = mapping.extract_job_id(it.get("detail_url")) or "?"
                title = it.get("title", "?")[:50]
                _log("FOUND", f"Job #{idx}/{len(items)}: ID={jid} \"{title}\"")

            # Build checkpoint page entry
            now = datetime.now().isoformat()
            job_dicts = []
            for it in items:
                job_id = mapping.extract_job_id(it.get("detail_url"))
                job_dicts.append({
                    "job_id": job_id,
                    "title": it.get("title"),
                    "company": it.get("company"),
                    "salary": it.get("salary"),
                    "location": it.get("location"),
                    "jobType": it.get("jobType"),
                    "detail_url": it.get("detail_url"),
                    "detail_fetched": False,
                    "detail_html": None,
                    "retries": 0,
                    "crawled_at": now,
                })

            pg_entry = {
                "page_num": page_num,
                "url": current_url,
                "proxy_used": proxy,
                "status": "details_pending",
                "list_html_path": rel_list_path,
                "jobs": job_dicts,
            }

            page_idx = page_num - 1
            while len(state["pages"]) <= page_idx:
                state["pages"].append(None)
            state["pages"][page_idx] = pg_entry
            save_checkpoint(run_dir, state)

            # Fetch detail pages
            _log("DETAIL", f"Fetching detail pages for {len(pg_entry['jobs'])} jobs...")
            detail_count_in_batch = 0
            consecutive_timeouts = 0
            for job_idx, job in enumerate(pg_entry["jobs"], 1):
                jid = job.get("job_id")
                durl = job.get("detail_url")
                title = job.get("title", "?")[:40]
                if not durl:
                    job["detail_fetched"] = True
                    continue

                if config.target_jobs is not None and fetches_done >= needed:
                    break

                _log("CRAWL", f"Fetching job {jid} \"{title}\" "
                     f"({job_idx}/{len(pg_entry['jobs'])} on page {page_num})...")
                success, detail_path = await fetch_detail_page(
                    page, jid, durl, detail_dir, config,
                    rate_limit=rate_limit, latencies=latencies)
                job["detail_fetched"] = success
                job["detail_html"] = detail_path
                save_checkpoint(run_dir, state)

                if success:
                    consecutive_timeouts = 0
                    new_items.append({
                        "job_id": jid, "title": job.get("title"),
                        "company": job.get("company"), "salary": job.get("salary"),
                        "location": job.get("location"), "jobType": job.get("jobType"),
                        "detail_url": durl, "detail_html_path": detail_path,
                        "link": durl, "page": page_num, "page_url": current_url,
                        "page_html_path": rel_list_path,
                        "crawled_at": job.get("crawled_at"), "proxy_used": proxy,
                    })
                    state["total_jobs_extracted"] += 1
                    fetches_done += 1
                    detail_count_in_batch += 1
                    _log("SAVED", f"Job {jid} \"{title}\" -> "
                         f"{_log_progress(state['total_jobs_extracted'], config.target_jobs)}")
                    if detail_count_in_batch >= config.detail_batch_size:
                        pause = config.detail_batch_pause + random.uniform(0, 3)
                        _log("PAUSE", f"Throttling: {pause:.0f}s after "
                             f"{detail_count_in_batch} detail pages...")
                        await asyncio.sleep(pause)
                        detail_count_in_batch = 0
                else:
                    fetches_failed += 1
                    blocks_detected += 1
                    consecutive_timeouts += 1
                    exceeded = _record_blocked_job(
                        state, jid, durl, job.get("title", ""),
                        threshold=config.block_threshold)
                    if exceeded:
                        _log("BLOCK", f"Job {jid} \"{title}\" -> "
                             f"PERMANENTLY BLOCKED after {config.block_threshold} attempts")
                        _save_block_file(run_dir, state)
                    else:
                        _log("BLOCK", f"Job {jid} \"{title}\" -> blocked (will retry)")
                    # Session recovery
                    try:
                        await page.close()
                    except Exception:
                        pass
                    try:
                        page = await context.new_page()
                        # Re-authenticate if session was lost
                        if auth_config and config.auth_required:
                            if not await ensure_authenticated(page, auth_config):
                                await authenticate(page, auth_config)
                        await page.goto(current_url,
                                        wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(random.uniform(2.0, 4.0))
                    except Exception:
                        pass

            # If broke out due to dead proxy, skip to next page tracking
            if consecutive_timeouts >= 3:
                _log("DEAD", "Proxy confirmed dead — returning partial results")
                break

            pg_entry["status"] = "complete"
            save_checkpoint(run_dir, state)

            if config.target_jobs is not None and fetches_done >= needed:
                _log("TARGET", f"Target met for this proxy — stopping")
                break

            next_url = await find_next_page(page, mapping)
            if not next_url:
                _log("END", f"No more pages (stopped at page {page_num})")
                break
            current_url = next_url
            page_num += 1
            pages_done_this_proxy += 1

        # Report session results to tracker
        if tracker:
            avg_lat = None
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
            tracker.record(
                proxy,
                success_count=len(new_items),
                fail_count=fetches_failed,
                block_count=blocks_detected,
                pages_visited=pages_visited,
                avg_latency=avg_lat,
            )

        # Log rate limiting summary
        if rate_limit["detections_this_session"] > 0:
            _log("RATE", f"Session ended with delay multiplier "
                 f"{rate_limit['current_multiplier']}x "
                 f"({rate_limit['detections_this_session']} detections)")

        return new_items, pages_visited, fetches_done

    except Exception as e:
        _log("ERROR", f"{type(e).__name__}: {e}")
        # Report failure to tracker
        if tracker:
            tracker.record_failure(proxy)
        return new_items, pages_visited, fetches_done
    finally:
        if browser:
            _log("BROWSER", "Closing browser session...")
            await browser.close()


# ── The Never-Stop Engine ─────────────────────────────────────────────────

class CrawlEngine:
    """Orchestrates the never-stop crawl loop.

    Guarantees:
      - Loop NEVER exits until TARGET_JOBS or MAX_PAGES is met,
        or all pages are exhausted.
      - If no proxies are available, WAITS and keeps searching.
      - Blocked jobs tracked separately after BLOCK_THRESHOLD attempts.
    """

    def __init__(self, mapping: SiteMapping, config: CrawlConfig,
                 tracker: ProxyTracker | None = None):
        self.mapping = mapping
        self.config = config
        self.tracker = tracker
        # Load auth config once at engine init (not per-proxy session)
        self.auth_config = load_auth_config() if self.config.auth_required else None

    async def crawl_forever(self, run_dir: Path, state: dict) -> list[dict]:
        """The main crawl loop that never stops until criteria are met."""
        global _log_start_time
        _log_start_time = time.time()

        all_results: list[dict] = checkpoint_to_jobs(state)
        details_since_last_retry = 0
        resume_detail_only = False
        proxy_start_idx = 0

        _log_banner(f"CRAWL STARTED — {self.mapping.display_name}")
        _log("CONFIG", f"Target: {_log_progress(len(all_results), self.config.target_jobs)}")
        _log("CONFIG", f"Max pages/proxy: {self.config.max_pages or 'unlimited'}")
        _log("CONFIG", f"Block threshold: {self.config.block_threshold} attempts")
        _log("CONFIG", f"Headless: {self.config.headless}")
        _log("CONFIG", f"Output: {run_dir}")

        # Log proxy tracker status
        if self.tracker:
            _log("TRACKER", self.tracker.summary())

        # Determine resume state
        if state.get("pages"):
            pages = state["pages"]
            pending = [p for p in pages if p and p.get("status") == "details_pending"]
            if pending:
                resume_detail_only = True
                proxy_start_idx = max(0, state.get("current_proxy_idx", 0))
                _log("RESUME", f"Resuming run {run_dir.name}")
                _log("RESUME", f"{len(pages)} pages in checkpoint, "
                     f"resuming detail fetch for page {pending[0].get('page_num', 1)}")
            else:
                completed = [p for p in pages if p and p.get("status") == "complete"]
                if completed:
                    proxy_start_idx = max(0, state.get("current_proxy_idx", 0))
                    last = max(completed, key=lambda p: p.get("page_num", 0))
                    _log("RESUME", f"Resuming run {run_dir.name}")
                    _log("RESUME", f"{len(pages)} pages complete "
                         f"({state.get('total_jobs_extracted', 0)} jobs), "
                         f"starting from page {last.get('page_num', 0) + 1}")

        start_page = 1
        if state.get("pages"):
            completed = [p for p in state["pages"]
                         if p and p.get("status") == "complete"]
            if completed:
                last = max(completed, key=lambda p: p.get("page_num", 0))
                start_page = last.get("page_num", 0) + 1

        # ── THE NEVER-STOP LOOP ──
        proxy_rotation = proxy_start_idx
        pages_exhausted = False
        consecutive_failed_rotations = 0
        rotation_count = 0
        total_pages_visited = 0

        while True:
            # Check stop criteria
            if self.config.target_jobs is not None:
                needed = self.config.target_jobs - len(dedup(all_results))
                if needed <= 0:
                    _log_banner(f"TARGET REACHED — {_log_progress(len(dedup(all_results)), self.config.target_jobs)}")
                    break

            if pages_exhausted and self.config.target_jobs is None and self.config.max_pages is None:
                _log_banner(f"ALL PAGES EXHAUSTED — {len(dedup(all_results))} jobs crawled")
                break

            # Load proxies — if none available, WAIT and retry
            _log("PROXY", "Loading proxy list...")
            proxies = self._load_proxies()
            if not proxies:
                _log("WAIT", "No proxies available — waiting 60s and retrying...")
                for remaining in range(60, 0, -10):
                    _log("WAIT", f"Retrying in {remaining}s...")
                    await asyncio.sleep(10)
                continue

            _log("PROXY", f"{len(proxies)} proxies available")

            # Cycle through proxies
            proxy_idx = proxy_rotation % len(proxies)
            proxy = proxies[proxy_idx]
            proxy_num = proxy_idx + 1

            needed = ((self.config.target_jobs - len(dedup(all_results)))
                      if self.config.target_jobs is not None else 999999)

            current_start = start_page
            current_resume = resume_detail_only
            if state.get("pages"):
                pend = [p for p in state["pages"]
                        if p and p.get("status") == "details_pending"]
                if pend:
                    current_start = pend[0].get("page_num", start_page)
                    current_resume = True
                else:
                    completed = [p for p in state["pages"]
                                if p and p.get("status") == "complete"]
                    if completed:
                        last = max(completed, key=lambda p: p.get("page_num", 0))
                        current_start = last.get("page_num", 0) + 1
                        current_resume = False

            items, pages_visited, details_fetched = await crawl_with_proxy(
                proxy, needed, run_dir, proxy_num, state,
                self.mapping, self.config,
                start_page=current_start,
                resume_detail_only=current_resume,
                total_so_far=len(dedup(all_results)),
                tracker=self.tracker,
                auth_config=self.auth_config,
            )

            total_pages_visited += pages_visited
            if items:
                state.setdefault("used_proxies", [])
                if proxy not in state["used_proxies"]: state["used_proxies"].append(proxy)
                save_checkpoint(run_dir, state)
                all_results = dedup(all_results + items)
                _log("PROGRESS", f"Proxy #{proxy_num} done: "
                     f"{_log_progress(len(all_results), self.config.target_jobs)}")
                if self.config.target_jobs is not None and len(all_results) >= self.config.target_jobs:
                    _log_banner(f"TARGET REACHED — {_log_progress(len(all_results), self.config.target_jobs)}")
                    break
            elif pages_visited > 0:
                state.setdefault("used_proxies", [])
                if proxy not in state["used_proxies"]: state["used_proxies"].append(proxy)
                save_checkpoint(run_dir, state)
                _log("PROGRESS", f"Proxy #{proxy_num}: {pages_visited} pages visited (all deduped)")
            else:
                wait = random.uniform(4, 9)
                _log("WAIT", f"Proxy #{proxy_num} failed — next proxy in {wait:.1f}s...")
                await asyncio.sleep(wait)


            # ---- Mid-crawl blocked-job retry ----
            details_since_last_retry += details_fetched
            if details_since_last_retry >= self.config.retry_blocked_every_n_jobs:
                _log("RETRY", f"Mid-crawl retry triggered after {details_since_last_retry} detail fetches")
                all_results = await self._retry_blocked_jobs(
                    run_dir, state, all_results,
                    max_attempts_per_job=self.config.mid_crawl_retry_attempts,
                    is_final_phase=False)
                details_since_last_retry = 0
                consecutive_failed_rotations = 0

            # Persist tracker state after each proxy session
            if self.tracker:
                tracker_path = run_dir / "proxy_tracker.json"
                self.tracker.save(tracker_path)
                retired = [p for p, e in self.tracker.proxies.items()
                           if e.get("retired")]
                if len(retired) != getattr(self, '_tracker_retired_count', 0):
                    self._tracker_retired_count = len(retired)
                    if retired:
                        last_retired = retired[-1]
                        reason = self.tracker.proxies[last_retired].get("retired_reason", "")
                        _log("RETIRE", f"Proxy retired: {last_retired[:50]} ({reason})")
                    _log("TRACKER", self.tracker.summary())

            # Update state tracking
            pend = [p for p in state.get("pages", [])
                    if p and p.get("status") == "details_pending"]
            if not pend:
                resume_detail_only = False
                completed = [p for p in state.get("pages", [])
                             if p and p.get("status") == "complete"]
                if completed:
                    last = max(completed, key=lambda p: p.get("page_num", 0))
                    start_page = last.get("page_num", 0) + 1
                state["current_proxy_idx"] = proxy_rotation + 1
                save_checkpoint(run_dir, state)

            proxy_rotation += 1
            rotation_count += 1

            # If we've gone through all proxies without progress, check exhaustion
            if rotation_count % len(proxies) == 0 and rotation_count > 0:
                current_count = len(dedup(all_results))
                if not hasattr(self, '_last_rotation_count'):
                    self._last_rotation_count = current_count
                elif current_count == self._last_rotation_count:
                    consecutive_failed_rotations += 1
                    if consecutive_failed_rotations >= 3:
                        # Require 3 consecutive failed rotations before giving up.
                        # Only set pages_exhausted if we actually visited pages
                        # (meaning the site truly has no more data).
                        # If proxies fail before reaching any page (e.g. bad country IP),
                        # refresh proxies and keep trying.
                        if self.config.target_jobs is None and self.config.max_pages is None:
                            if total_pages_visited > 0:
                                pages_exhausted = True
                            else:
                                _log("REFRESH", "All proxies failed before reaching any page — refreshing proxies...")
                                self._refresh_proxies()
                        else:
                            _log("REFRESH", "No progress after 3+ full proxy rotations — "
                                 "refreshing proxies...")
                            self._refresh_proxies()
                    else:
                        _log("REFRESH", f"No progress in rotation {consecutive_failed_rotations}/3 — "
                             "refreshing proxies...")
                        self._refresh_proxies()
                else:
                    consecutive_failed_rotations = 0
                self._last_rotation_count = current_count

        # --- Blocked job retry phase ---
        all_results = await self._retry_blocked_jobs(
            run_dir, state, all_results,
            max_attempts_per_job=None,
            is_final_phase=True)

        # --- Save final results ---
        _log("SAVE", "Saving final results...")
        save_results(all_results, run_dir, state, self.mapping)
        save_final_json(run_dir, all_results, self.mapping)
        _save_block_file(run_dir, state)

        _log_banner(f"CRAWL COMPLETE — {_log_progress(len(all_results), self.config.target_jobs)} "
                     f"in {_elapsed()}")
        return all_results

    async def _retry_blocked_jobs(self, run_dir: Path, state: dict,
                                    all_results: list[dict],
                                    max_attempts_per_job: int | None = None,
                                    is_final_phase: bool = False) -> list[dict]:
        """Retry blocked/retrying jobs with fresh proxies.

        Args:
            max_attempts_per_job: If set, each job is attempted at most this many
                times in this retry call (e.g. 2 for mid-crawl rounds).
            is_final_phase: If True, loops until all_to_retry is empty and never
                marks jobs as permanently_blocked.
        """
        blocked = state.get("blocked_jobs", [])
        retrying = [b for b in blocked if b.get("status") != "permanently_blocked"]
        permanent = [b for b in blocked if b.get("status") == "permanently_blocked"]

        if not retrying:
            if permanent and not is_final_phase:
                _log("BLOCK", f"{len(permanent)} permanently blocked jobs - "
                     f"see blocked_jobs.json")
            return all_results

        phase_label = "FINAL RETRY PHASE" if is_final_phase else "RETRY PHASE"
        _log_banner(f"{phase_label} - {len(retrying)} blocked/retrying jobs to retry")
        for b in retrying:
            _log("RETRY", f"Job {b['job_id']} '{b.get('title','?')[:40]}' "
                 f"({b['retries']}/{self.config.block_threshold} attempts)")

        # Find all unfetched jobs from checkpoint pages too
        unfetched_from_pages = []
        for pg in state.get("pages", []):
            if not pg:
                continue
            for job in pg.get("jobs", []):
                if not job.get("detail_fetched"):
                    jid = job.get("job_id")
                    already_blocked = any(str(b.get("job_id", "")).strip() == jid for b in blocked)
                    if not already_blocked:
                        unfetched_from_pages.append(job)

        if unfetched_from_pages:
            _log("RETRY", f"Found {len(unfetched_from_pages)} additional unfetched jobs "
                 f"in checkpoint pages")
            for j in unfetched_from_pages:
                _log("RETRY", f"  Job {j['job_id']} '{j.get('title','?')[:40]}' "
                     f"from page {j.get('page','?')}")

        # Build master list of jobs to retry
        all_to_retry = []
        for b in retrying:
            original_job = None
            for pg in state.get("pages", []):
                if not pg:
                    continue
                for job in pg.get("jobs", []):
                    if str(job.get("job_id", "")).strip() == str(b.get("job_id", "")).strip():
                        original_job = job
                        break
                if original_job:
                    break

            if original_job:
                all_to_retry.append(original_job)
            else:
                all_to_retry.append({
                    "job_id": b["job_id"],
                    "title": b.get("title"),
                    "detail_url": b.get("detail_url"),
                    "detail_fetched": False,
                    "detail_html": None,
                    "retries": b.get("retries", 0),
                })

        for job in unfetched_from_pages:
            if job not in all_to_retry:
                all_to_retry.append(job)

        # Deduplicate retry list by normalized job_id
        retry_seen: dict[str, dict] = {}
        for job in all_to_retry:
            jid = str(job.get("job_id", "")).strip() if job.get("job_id") else None
            if jid and jid not in retry_seen:
                retry_seen[jid] = job
        all_to_retry = list(retry_seen.values())

        if not all_to_retry:
            return all_results

        detail_dir = run_dir / "html" / "detail"
        detail_dir.mkdir(parents=True, exist_ok=True)

        # Track per-job attempts in THIS retry call
        call_attempts: dict[str, int] = {j["job_id"]: 0 for j in all_to_retry}

        round_num = 0
        while all_to_retry:
            round_num += 1
            try:
                proxies = self._load_proxies()
            except Exception as e:
                _log("WARN", f"Proxy load error in retry: {type(e).__name__}: {e}")
                proxies = []
            if not proxies:
                wait_msg = "Final retry: no proxies - waiting 60s..." if is_final_phase else f"Retry round {round_num}: no proxies - waiting 60s..."
                _log("WAIT", wait_msg)
                await asyncio.sleep(60)
                continue

            for proxy in proxies:
                if not all_to_retry:
                    break

                jobs_to_try = list(all_to_retry)
                _log("RETRY", f"Round {round_num}: trying {len(jobs_to_try)} jobs "
                     f"with proxy {proxy[:50]}")

                browser = None
                try:
                    from cloakbrowser import launch_async
                    browser = await launch_async(
                        headless=self.config.headless, proxy=proxy,
                        humanize=True, geoip=True, human_preset="careful",
                        backend=self.config.browser_backend,
                    )
                    context = await browser.new_context(
                        viewport={"width": 1366, "height": 768},
                        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
                    )
                    page = await context.new_page()

                    retry_country_code = self.config.proxy_country.upper() if self.config.use_proxy else "DIRECT"
                    is_target_country, ip_addr = await verify_country_ip(page, retry_country_code)
                    if not is_target_country:
                        _log("SKIP", f"Retry: proxy IP is not {retry_country_code} ({ip_addr})")
                        continue

                    _log("OK", f"Retry: {retry_country_code} IP confirmed: {ip_addr}")

                    if self.auth_config and self.config.auth_required:
                        _log("AUTH", "Retry phase: authenticating...")
                        login_ok = await authenticate(page, self.auth_config)
                        if not login_ok:
                            _log("AUTH", "Retry: login failed - trying next proxy")
                            continue

                    for job in jobs_to_try[:]:
                        jid = str(job.get("job_id", "")).strip() if job.get("job_id") else None
                        durl = job.get("detail_url")
                        title = job.get("title", "?")[:40]
                        if not durl:
                            all_to_retry.remove(job)
                            continue

                        # Enforce per-call attempt limit
                        call_attempts[jid] = call_attempts.get(jid, 0) + 1
                        if max_attempts_per_job and call_attempts[jid] > max_attempts_per_job:
                            continue

                        # Total lifetime retries
                        retries = job.get("retries", 0) + 1
                        job["retries"] = retries

                        # In final phase, never mark permanently blocked
                        effective_threshold = 999999 if is_final_phase else self.config.block_threshold
                        if retries >= effective_threshold:
                            _record_blocked_job(state, jid, durl, title, threshold=effective_threshold)
                            for b in state.get("blocked_jobs", []):
                                if str(b.get("job_id", "")).strip() == jid:
                                    b["retries"] = retries
                                    if not is_final_phase:
                                        b["status"] = "permanently_blocked"
                            if not is_final_phase:
                                _log("BLOCK", f"Job {jid} '{title}' -> "
                                     f"PERMANENTLY BLOCKED ({retries} attempts)")
                                _save_block_file(run_dir, state)
                                save_checkpoint(run_dir, state)
                                all_to_retry.remove(job)
                            continue

                        _log("CRAWL", f"Retry job {jid} '{title}' "
                             f"(attempt {retries}/{self.config.block_threshold})...")

                        retry_rate_limit = {
                            "current_multiplier": self.config.rate_limit_multiplier_min,
                            "recovery_counter": 0,
                            "detections_this_session": 0,
                        }
                        success, detail_path = await fetch_detail_page(
                            page, jid, durl, detail_dir, self.config,
                            rate_limit=retry_rate_limit)

                        if success:
                            # Update page job entries
                            listing_url = ""
                            rel_list_path = ""
                            for pg in state.get("pages", []):
                                if not pg:
                                    continue
                                for j in pg.get("jobs", []):
                                    if str(j.get("job_id", "")).strip() == jid:
                                        j["detail_fetched"] = True
                                        j["detail_html"] = detail_path
                                        j["retries"] = retries
                                        listing_url = pg.get("url", "")
                                        rel_list_path = pg.get("list_html_path", "")
                                        break

                            # Remove from blocked list
                            state["blocked_jobs"] = [
                                b for b in state.get("blocked_jobs", [])
                                if str(b.get("job_id", "")).strip() != jid
                            ]

                            new_item = {
                                "job_id": jid,
                                "title": job.get("title"),
                                "company": job.get("company"),
                                "salary": job.get("salary"),
                                "location": job.get("location"),
                                "jobType": job.get("jobType"),
                                "detail_url": durl,
                                "detail_html_path": detail_path,
                                "link": durl,
                                "page_html_path": rel_list_path,
                                "crawled_at": datetime.now().isoformat(),
                                "proxy_used": proxy,
                            }
                            all_results = dedup(all_results + [new_item])
                            state["total_jobs_extracted"] += 1
                            save_checkpoint(run_dir, state)
                            _log("SAVED", f"Retry: Job {jid} '{title}' -> "
                                 f"{_log_progress(len(all_results), self.config.target_jobs)}")
                            all_to_retry.remove(job)

                            if self.tracker:
                                self.tracker.record_success(proxy)

                            for pg in state.get("pages", []):
                                if not pg:
                                    continue
                                for j in pg.get("jobs", []):
                                    if str(j.get("job_id", "")).strip() == jid:
                                        j["detail_fetched"] = True
                                        j["detail_html"] = detail_path
                                        j["retries"] = retries

                        else:
                            if self.tracker:
                                self.tracker.record_failure(proxy)
                            _record_blocked_job(state, jid, durl, title,
                                                threshold=effective_threshold)
                            job["retries"] = retries
                            save_checkpoint(run_dir, state)
                            _save_block_file(run_dir, state)

                            for b in state.get("blocked_jobs", []):
                                if str(b.get("job_id", "")).strip() == jid:
                                    if b.get("retries", 0) >= effective_threshold:
                                        if not is_final_phase:
                                            b["status"] = "permanently_blocked"
                                            _log("BLOCK", f"Job {jid} '{title}' -> "
                                                 f"PERMANENTLY BLOCKED ({b['retries']} attempts)")
                                            all_to_retry.remove(job)
                                        # Update page entries
                                        for pg in state.get("pages", []):
                                            if not pg:
                                                continue
                                            for j in pg.get("jobs", []):
                                                if str(j.get("job_id", "")).strip() == jid:
                                                    j["retries"] = b["retries"]

                        await asyncio.sleep(random.uniform(
                            self.config.detail_delay_min,
                            self.config.detail_delay_max))

                        if not all_to_retry:
                            break

                except Exception as e:
                    _log("ERROR", f"Retry proxy session error: {type(e).__name__}: {e}")
                finally:
                    if browser:
                        await browser.close()

                if not all_to_retry:
                    break
                await asyncio.sleep(random.uniform(3, 7))

        remaining = len(all_to_retry)
        if remaining:
            _log("BLOCK", f"Retry phase complete: {remaining} jobs still blocked")
        else:
            _log("OK", "All blocked jobs retried successfully")

        _save_block_file(run_dir, state)
        return all_results


    def _load_proxies(self) -> list[str]:
        """Load proxies from cache, with auto-refetch if stale."""
        try:
            from .proxy_manager import ProxyManager
        except ImportError:
            from proxy_manager import ProxyManager  # type: ignore[no-redef]
        pm = ProxyManager(self.config, site_name=self.mapping.name, tracker=self.tracker)
        return pm.load_proxies()

    def _refresh_proxies(self) -> None:
        """Force a proxy refresh."""
        try:
            from .proxy_manager import ProxyManager
        except ImportError:
            from proxy_manager import ProxyManager  # type: ignore[no-redef]
        pm = ProxyManager(self.config, site_name=self.mapping.name)
        pm.refetch()
