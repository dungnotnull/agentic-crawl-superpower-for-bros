"""
2_crawl.py · Proxifly + CloakBrowser edition (v4 — detail fetch + checkpoint + resume)
──────────────────────────────────────────────────────────────────────────────────────
v4 improvements:
  - Extract ALL job cards (div.css-1lbxuix) not just table-containing ones
  - Fetch and save each job's detail page HTML
  - Checkpoint after every detail fetch → crash-safe resume
  - Proxy failover resumes from failed page, not page 1

Yêu cầu:
    pip install cloakbrowser[geoip] requests PySocks
    python -m cloakbrowser install
"""

import asyncio
import json
import csv
import os
import re
import random
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

from cloakbrowser import launch_async

# Ghi đè hàm print để tránh lỗi Unicode trên Windows console (CP1258...)
def safe_print(*args, **kwargs):
    msg = " ".join(str(arg) for arg in args)
    enc = sys.stdout.encoding or "utf-8"
    end = kwargs.get("end", "\n")
    try:
        sys.stdout.write(msg.encode(enc, errors="replace").decode(enc) + end)
        sys.stdout.flush()
    except Exception:
        try:
            sys.stdout.write(msg.encode("ascii", errors="replace").decode("ascii") + end)
            sys.stdout.flush()
        except Exception:
            pass

print = safe_print

# ════════════════════════ CẤU HÌNH ════════════════════════
TARGET_URL    = "https://www.ekaigotenshoku.com/kyujin/list?z01=1"
OUTPUT_DIR    = Path("output")
WORKING_FILE  = Path("japan_working_proxies.json")
FETCH_SCRIPT  = "autofetch_ja_servers.py"

HEADLESS           = True
TARGET_JOBS        = 240     # None = chạy đến khi hết trang
MAX_PAGES          = None      # None = không giới hạn số trang mỗi proxy
MAX_EMPTY          = 2
CACHE_TTL          = timedelta(minutes=30)
DELAY_MIN          = 3.5
DELAY_MAX          = 8.0
DETAIL_DELAY_MIN   = 2.0
DETAIL_DELAY_MAX   = 5.0
DETAIL_MAX_RETRIES = 2
DETAIL_BATCH_SIZE  = 8    # nghỉ sau mỗi N detail page liên tiếp
DETAIL_BATCH_PAUSE = 12.0 # nghỉ bao lâu giữa các batch (giây)
AUTO_RESUME        = True

LOCAL_PROXIES = [
    "socks5://127.0.0.1:1080",
    "socks5://127.0.0.1:7891",
    "socks5://127.0.0.1:10808",
    "http://127.0.0.1:7890",
]

SUCCESS_KW = ["求人", "介護", "給与", "勤務地", "施設", "募集", "正社員"]
BLOCK_KW   = ["access denied", "forbidden", "403 error", "request blocked",
              "could not be satisfied",
              "アクセス制限", "地域制限", "ご利用いただけません"]
# ═══════════════════════════════════════════════════════════


# ── Proxy helpers ─────────────────────────────────────────
def _cache_is_stale(data: dict) -> bool:
    updated_raw = data.get("updated_at")
    if not updated_raw:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(updated_raw)) > CACHE_TTL
    except Exception:
        return True


def _refetch() -> None:
    print(f"🔁 Cache cũ/cạn — chạy {FETCH_SCRIPT}...")
    try:
        subprocess.run([sys.executable, FETCH_SCRIPT], check=True)
    except Exception as e:
        print(f"⚠ Re-fetch lỗi: {e}")


def load_proxies(allow_refetch: bool = True) -> list[str]:
    """Trả proxy đã sort theo real_score (tốt nhất trước)."""
    if WORKING_FILE.exists():
        try:
            data = json.loads(WORKING_FILE.read_text(encoding="utf-8"))
            if allow_refetch and _cache_is_stale(data):
                _refetch()
                return load_proxies(allow_refetch=False)
            raw = data.get("proxies", [])
            raw.sort(key=lambda x: -x.get("real_score", 0))
            proxies = [p["proxy"] for p in raw if p.get("proxy")]
            if proxies:
                print(f"📋 {len(proxies)} proxy từ {WORKING_FILE} "
                      f"(top score={raw[0].get('real_score', '?')})")
                return proxies
        except Exception as e:
            print(f"⚠ Đọc {WORKING_FILE} lỗi: {e}")

    if allow_refetch:
        _refetch()
        return load_proxies(allow_refetch=False)

    print(f"⚠ Dùng local proxy fallback")
    return LOCAL_PROXIES


# ── Checkpoint helpers ────────────────────────────────────
def extract_job_id(detail_url: str | None) -> str | None:
    """Extract numeric job ID from /kyujin/detail?id=299554 URL."""
    if not detail_url:
        return None
    m = re.search(r'[?&]id=(\d+)', detail_url)
    return m.group(1) if m else None


def init_checkpoint(run_dir: Path, target_url: str, target_jobs: int) -> dict:
    return {
        "version": 1,
        "target_url": target_url,
        "target_jobs": target_jobs,
        "used_proxies": [],
        "current_proxy_idx": 0,
        "pages": [],
        "blocked_jobs": [],
        "total_jobs_extracted": 0,
        "updated_at": datetime.now().isoformat(),
    }


def load_checkpoint(run_dir: Path) -> dict | None:
    path = run_dir / "checkpoint.json"
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("version") != 1:
            print(f"⚠ checkpoint version mismatch: {state.get('version')}")
            return None
        return state
    except Exception as e:
        print(f"⚠ checkpoint lỗi: {e}")
        return None


def save_checkpoint(run_dir: Path, state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat()
    path = run_dir / "checkpoint.json"
    tmp = run_dir / "checkpoint.json.tmp"
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception as e:
        print(f"⚠ Lỗi ghi checkpoint: {e}")


def checkpoint_to_jobs(state: dict) -> list[dict]:
    """Flatten checkpoint pages into the job list format for save_results.
    Only includes jobs where detail_fetched is True."""
    out = []
    for pg in state.get("pages", []):
        for job in pg.get("jobs", []):
            if not job.get("detail_fetched"):
                continue
            out.append({
                "job_id": job.get("job_id"),
                "title": job.get("title"),
                "company": job.get("company"),
                "salary": job.get("salary"),
                "location": job.get("location"),
                "jobType": job.get("jobType"),
                "detail_url": job.get("detail_url"),
                "detail_html_path": job.get("detail_html"),
                "link": job.get("detail_url"),
                "page": pg.get("page_num"),
                "page_url": pg.get("url"),
                "page_html_path": pg.get("list_html_path"),
                "crawled_at": job.get("crawled_at"),
                "proxy_used": pg.get("proxy_used"),
            })
    return out


def find_latest_incomplete_run(output_dir: Path) -> tuple[Path, dict] | None:
    """Find the most recent run with incomplete checkpoint. Returns (run_dir, state) or None."""
    if not output_dir.exists():
        return None
    best: tuple[Path, dict] | None = None
    best_ts = ""
    for entry in output_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("run_"):
            continue
        ckpt_path = entry / "checkpoint.json"
        if not ckpt_path.exists():
            continue
        ts = entry.name.replace("run_", "")
        if ts > best_ts:
            try:
                state = json.loads(ckpt_path.read_text(encoding="utf-8"))
                target = state.get("target_jobs")
                extracted = state.get("total_jobs_extracted", 0)
                if target is not None and extracted >= target:
                    continue
                has_incomplete = False
                for pg in state.get("pages", []):
                    if pg.get("status") != "complete":
                        has_incomplete = True
                        break
                    for job in pg.get("jobs", []):
                        if not job.get("detail_fetched"):
                            has_incomplete = True
                            break
                not_done = (target is None) or (extracted < target)
                if not_done or has_incomplete:
                    best = (entry, state)
                    best_ts = ts
            except Exception:
                pass
    return best


def _build_page_jobs(items: list[dict], proxy: str) -> list[dict]:
    """Convert extracted items into checkpoint job dicts."""
    now = datetime.now().isoformat()
    out = []
    for it in items:
        job_id = extract_job_id(it.get("detail_url"))
        out.append({
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
    return out


# ── Browser logic ─────────────────────────────────────────
async def verify_japan_ip(page) -> tuple[bool, str]:
    try:
        await page.goto("https://ipinfo.io/json",
                        wait_until="domcontentloaded", timeout=12000)
        content = await page.content()
        is_jp = '"JP"' in content or '"country":"JP"' in content
        m = re.search(r'"ip"\s*:\s*"([^"]+)"', content)
        return is_jp, (m.group(1) if m else "unknown")
    except Exception:
        return False, "unknown"


async def extract_jobs(page, page_num: int, proxy: str) -> list[dict]:
    """Extract ALL job cards using div.css-1lbxuix + detail link heuristic."""
    items = await page.evaluate("""
        () => {
            let cards = [];

            // Phase 1: Target known Chakra UI card class directly
            const chakraCards = document.querySelectorAll('div.css-1lbxuix');
            if (chakraCards.length >= 10) {
                cards = Array.from(chakraCards);
            }

            // Phase 2: Find ALL detail links, walk up to card container
            if (cards.length < 10) {
                const detailLinks = document.querySelectorAll('a[href*="/kyujin/detail"]');
                const seenIds = new Set();
                const dedupedLinks = [];
                detailLinks.forEach(a => {
                    const href = a.getAttribute('href');
                    if (!href) return;
                    const m = href.match(/[?&]id=(\\d+)/);
                    const id = m ? m[1] : href;
                    if (!seenIds.has(id)) {
                        seenIds.add(id);
                        dedupedLinks.push(a);
                    }
                });

                const fallbackCards = [];
                dedupedLinks.forEach(a => {
                    let parent = a.closest('div');
                    while (parent && parent !== document.body) {
                        const tag = parent.tagName.toLowerCase();
                        const cls = parent.className || '';
                        if (tag === 'div' && cls.length > 0) {
                            fallbackCards.push(parent);
                            break;
                        }
                        parent = parent.parentElement;
                    }
                });
                if (fallbackCards.length > cards.length) {
                    cards = fallbackCards;
                }
            }

            // Phase 3: Generic fallback selectors (last resort)
            if (cards.length < 3) {
                const selectors = [
                    '.jobList li', '.job-list-item', '.p-jobList__item',
                    '.kyujin-list li', '[class*="jobList"] > li',
                    '.job-item', '.kyujin-item', '.recruit-item',
                    '[class*="job-list"] > li', '[class*="kyujin"] li',
                    '[class*="recruit"] li', 'article.job',
                    '.search-result-item', '.list-item', '[class*="card"]'
                ];
                for (const sel of selectors) {
                    const found = document.querySelectorAll(sel);
                    if (found.length > 2) { cards = Array.from(found); break; }
                }
            }
            if (!cards.length) {
                cards = Array.from(document.querySelectorAll('main li, article, section li'));
            }

            const out = [];
            const seenOut = new Set();

            cards.forEach(card => {
                const getText = (...sels) => {
                    for (const s of sels) {
                        const el = card.querySelector(s);
                        if (el) {
                            const t = el.textContent.trim();
                            if (t) return t;
                        }
                    }
                    return null;
                };

                const getVisibleText = (...sels) => {
                    for (const s of sels) {
                        const el = card.querySelector(s);
                        if (el) {
                            const t = el.innerText.trim() || el.textContent.trim();
                            if (t) return t;
                        }
                    }
                    return null;
                };

                const title = getVisibleText('h2', 'h3', 'h4', '.title', '[class*="title"]', '[class*="name"]');
                const detailEl = card.querySelector('a[href*="/kyujin/detail"]') || card.querySelector('a');
                const link = detailEl ? detailEl.href : null;

                let idKey = null;
                if (link) {
                    const m = link.match(/[?&]id=(\\d+)/);
                    idKey = m ? m[1] : link;
                }
                if (!idKey) idKey = title;
                if (seenOut.has(idKey)) return;
                seenOut.add(idKey);

                let salary = null;
                let jobType = null;
                card.querySelectorAll('table tr').forEach(tr => {
                    const th = tr.querySelector('th');
                    const td = tr.querySelector('td');
                    if (th && td) {
                        const thText = th.textContent.trim();
                        if (thText.includes('給与')) {
                            salary = td.textContent.trim();
                        } else if (thText.includes('雇用形態') || thText.includes('職種') || thText.includes('サービス')) {
                            jobType = (jobType ? jobType + ' | ' : '') + td.textContent.trim();
                        }
                    }
                });

                if (!salary) salary = getText('[class*="salary"]', '[class*="kyuyo"]', '[class*="wage"]', '[class*="pay"]', '[class*="kyuuyo"]');
                if (!jobType) jobType = getText('[class*="type"]', '[class*="employment"]', '[class*="koyou"]', '[class*="keitai"]');
                const company = getText('.company', '[class*="company"]', '[class*="facility"]', '[class*="office"]', '[class*="shisetsu"]');

                let location = getText('[class*="location"]', '[class*="address"]', '[class*="area"]', '[class*="place"]', '[class*="access"]');
                if (!location) {
                    const locBadge = card.querySelector('span[name]:not([name="おすすめ"]):not([name="派遣"]):not([name="正社員"]):not([name="パート"])');
                    if (locBadge) location = locBadge.textContent.trim();
                }

                if (title) out.push({title, company, salary, location, jobType, link, detail_url: link});
            });
            return out;
        }
    """)
    for it in items:
        it["page"] = page_num
        it["crawled_at"] = datetime.now().isoformat()
        it["proxy_used"] = proxy
    return items


async def find_next(page) -> str | None:
    return await page.evaluate("""
        () => {
            const nextImg = document.querySelector('img[src*="next-button"], img[src*="next_button"], img[src*="arrow-right"]');
            if (nextImg) {
                const a = nextImg.closest('a');
                if (a && a.href) return a.href;
            }
            const sels = ['a[rel="next"]', '.pagination .next a', '.pager-next a',
                          '[aria-label="次のページ"]', '.pager a[class*="next"]',
                          '.pagination a[class*="next"]'];
            for (const s of sels) {
                try {
                    const el = document.querySelector(s);
                    if (el && el.href) return el.href;
                } catch(e) {}
            }
            try {
                const nextLinks = document.querySelectorAll('[class*="next"] a, a[class*="next"]');
                for (const el of nextLinks) {
                    if (el.href && !el.closest('.swiper-slide, .swiper, .carousel, [class*="swiper"], [class*="carousel"]')) {
                        return el.href;
                    }
                }
            } catch(e) {}
            for (const a of document.querySelectorAll('a')) {
                if (/次へ|次のページ/.test(a.innerText) && a.href) return a.href;
            }
            return null;
        }
    """)


def _record_blocked_job(state: dict, job_id: str, detail_url: str, title: str) -> None:
    """Record a blocked/failed job for later retry."""
    blocked = state.setdefault("blocked_jobs", [])
    for b in blocked:
        if b.get("job_id") == job_id:
            b["retries"] = b.get("retries", 0) + 1
            b["last_attempt"] = datetime.now().isoformat()
            return
    blocked.append({
        "job_id": job_id,
        "detail_url": detail_url,
        "title": title,
        "retries": 1,
        "last_attempt": datetime.now().isoformat(),
    })


async def fetch_detail_page(page, job_id: str, detail_url: str,
                            detail_dir: Path) -> tuple[bool, str | None]:
    """Fetch one detail page, save HTML. Returns (success, relative_html_path)."""
    for attempt in range(DETAIL_MAX_RETRIES + 1):
        try:
            await page.goto(detail_url, wait_until="load", timeout=45000)
            await asyncio.sleep(random.uniform(DETAIL_DELAY_MIN, DETAIL_DELAY_MAX))

            html = await page.content()

            blocked = any(kw in html.lower() for kw in BLOCK_KW)
            if blocked:
                # Save FULL blocked HTML for debugging
                debug_path = detail_dir / f"job_{job_id}_blocked_attempt{attempt}.html"
                try: debug_path.write_text(html, encoding="utf-8")
                except: pass
                # Log which keyword triggered the block
                matched_kw = [kw for kw in BLOCK_KW if kw in html.lower()]
                if attempt < DETAIL_MAX_RETRIES:
                    backoff = 4 * (2 ** attempt)
                    print(f"   ⚠ Detail {job_id}: block detected (matched: {matched_kw}), retry {attempt+1}/{DETAIL_MAX_RETRIES} sau {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                print(f"   ✗ Detail {job_id}: BLOCKED by {matched_kw} after {DETAIL_MAX_RETRIES+1} attempts")
                return False, None

            if "</html>" not in html[:100] and "</html>" not in html[-200:]:
                if attempt < DETAIL_MAX_RETRIES:
                    print(f"   ⚠ Detail {job_id}: incomplete page (no </html>), retry {attempt+1}/{DETAIL_MAX_RETRIES}")
                    await asyncio.sleep(4)
                    continue
                print(f"   ✗ Detail {job_id}: incomplete page after {DETAIL_MAX_RETRIES+1} attempts")
                return False, None

            html_filename = f"job_{job_id}.html"
            html_path = detail_dir / html_filename
            html_path.write_text(html, encoding="utf-8")
            return True, f"html/detail/{html_filename}"

        except Exception as e:
            if attempt < DETAIL_MAX_RETRIES:
                backoff = 4 * (2 ** attempt)
                print(f"   ⚠ Detail {job_id}: {type(e).__name__} ({e}), retry {attempt+1}/{DETAIL_MAX_RETRIES} sau {backoff}s")
                await asyncio.sleep(backoff)
                continue
            print(f"   ✗ Detail {job_id}: {type(e).__name__} sau {DETAIL_MAX_RETRIES+1} lần thử — {e}")
            return False, None

    return False, None


# ── Main crawl functions ───────────────────────────────────
async def crawl_with_proxy(proxy: str, needed: int, run_dir: Path, proxy_idx: int,
                           state: dict, start_page: int = 1,
                           resume_detail_only: bool = False) -> tuple[list[dict], int]:
    """Crawl listing pages + detail pages with full checkpointing.
    Returns (new_items, pages_visited). pages_visited counts how many listing pages
    were loaded (even if no new unique jobs resulted)."""
    print(f"\n{'─'*60}")
    print(f"🔄 Proxy: {proxy}  (cần thêm ~{needed} jobs)")

    detail_dir = run_dir / "html" / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    browser = None
    new_items: list[dict] = []
    fetches_done = 0  # detail pages successfully fetched by THIS proxy
    pages_visited = 0  # listing pages loaded by this proxy

    try:
        browser = await launch_async(
            headless=HEADLESS, proxy=proxy,
            humanize=True, geoip=True, human_preset="careful",
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
        )
        page = await context.new_page()

        is_jp, ip_addr = await verify_japan_ip(page)
        if not is_jp:
            print(f"   ✗ IP không phải JP ({ip_addr}) — skip")
            return [], 0
        print(f"   🇯🇵 IP xác nhận: {ip_addr}")

        await page.goto("https://www.google.co.jp",
                        wait_until="domcontentloaded", timeout=18000)
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # ── Resume: finish pending detail fetches ──
        if resume_detail_only and state.get("pages"):
            pg = state["pages"][-1]
            if pg.get("status") == "details_pending":
                print(f"\n   🔄 Resume detail fetching for page {pg['page_num']} ({len(pg['jobs'])} jobs)")
                listing_url = pg["url"]
                for job in pg["jobs"]:
                    if job.get("detail_fetched"):
                        continue
                    jid = job.get("job_id")
                    durl = job.get("detail_url")
                    if not durl:
                        job["detail_fetched"] = True
                        continue

                    print(f"   📄 Detail job {jid}...", end=" ")
                    success, detail_path = await fetch_detail_page(page, jid, durl, detail_dir)
                    job["detail_fetched"] = success
                    job["detail_html"] = detail_path
                    job["retries"] = job.get("retries", 0)
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
                        print(f"✓ ({len(new_items)} from resume)")
                    else:
                        _record_blocked_job(state, jid, durl, job.get("title", ""))
                        print("✗")
                        # Session recovery: close tainted page, open fresh one
                        try:
                            await page.close()
                        except Exception:
                            pass
                        try:
                            page = await context.new_page()
                            await page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(random.uniform(2.0, 4.0))
                        except Exception:
                            pass

                    if TARGET_JOBS is not None and fetches_done >= needed:
                        break

                pg["status"] = "complete"
                save_checkpoint(run_dir, state)
                start_page = pg["page_num"] + 1

        # ── Normal page loop ──
        current_url = None
        empty_streak = 0

        # Figure out current_url for the starting page
        if state.get("pages") and start_page <= len(state["pages"]):
            pg_entry = state["pages"][start_page - 1]
            if pg_entry:
                current_url = pg_entry.get("url", "")

        if not current_url:
            current_url = TARGET_URL
            if start_page > 1:
                current_url = f"https://www.ekaigotenshoku.com/kyujin?page={start_page}&z01=1"

        page_num = start_page
        pages_done_this_proxy = 0

        while True:
            if MAX_PAGES is not None and pages_done_this_proxy >= MAX_PAGES:
                print(f"   ℹ Đạt trần {MAX_PAGES} trang cho proxy này — dừng.")
                break
            if TARGET_JOBS is not None and fetches_done >= needed:
                print(f"   🎯 Đủ target — dừng proxy.")
                break

            print(f"\n   📄 Trang {page_num}: {current_url[:70]}...")
            await page.goto(current_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            pages_visited += 1

            html = await page.content()

            # Save listing HTML
            html_filename = f"list_proxy{proxy_idx}_page{page_num}.html"
            list_html_path = run_dir / "html" / html_filename
            rel_list_path = f"html/{html_filename}"
            try:
                list_html_path.write_text(html, encoding="utf-8")
            except Exception as e:
                print(f"   ⚠ Lỗi khi lưu HTML: {e}")

            if any(kw in html.lower() for kw in BLOCK_KW):
                print(f"   🚫 Bị block tại trang {page_num} — dừng proxy này")
                break
            if not any(kw in html for kw in SUCCESS_KW):
                print(f"   ⚠ Không thấy nội dung JP trang {page_num}")
                if page_num == start_page:
                    return [], pages_visited
                empty_streak += 1
                if empty_streak >= MAX_EMPTY:
                    break
                next_url = await find_next(page)
                if not next_url:
                    break
                current_url = next_url
                page_num += 1
                pages_done_this_proxy += 1
                continue

            items = await extract_jobs(page, page_num, proxy)
            if not items:
                empty_streak += 1
                print(f"   ⚠ 0 jobs (rỗng liên tiếp: {empty_streak})")
                if empty_streak >= MAX_EMPTY:
                    break
                next_url = await find_next(page)
                if not next_url:
                    break
                current_url = next_url
                page_num += 1
                pages_done_this_proxy += 1
                continue

            empty_streak = 0
            print(f"   ✅ {len(items)} jobs extracted")

            # Build checkpoint page entry
            job_dicts = _build_page_jobs(items, proxy)
            pg_entry = {
                "page_num": page_num,
                "url": current_url,
                "proxy_used": proxy,
                "status": "details_pending",
                "list_html_path": rel_list_path,
                "jobs": job_dicts,
            }

            # Add or update pages list
            page_idx = page_num - 1
            while len(state["pages"]) <= page_idx:
                state["pages"].append(None)
            state["pages"][page_idx] = pg_entry
            save_checkpoint(run_dir, state)

            # Fetch detail pages one by one
            detail_count_in_batch = 0
            for job in pg_entry["jobs"]:
                jid = job.get("job_id")
                durl = job.get("detail_url")
                if not durl:
                    job["detail_fetched"] = True
                    continue

                if TARGET_JOBS is not None and fetches_done >= needed:
                    break

                print(f"   📄 Detail job {jid}...", end=" ")
                success, detail_path = await fetch_detail_page(page, jid, durl, detail_dir)
                job["detail_fetched"] = success
                job["detail_html"] = detail_path
                save_checkpoint(run_dir, state)

                if success:
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
                    print(f"✓ (tích lũy: {state['total_jobs_extracted']})")
                    # Throttling: pause after every N successful detail fetches
                    # to avoid triggering rate limiting on the server
                    if detail_count_in_batch >= DETAIL_BATCH_SIZE:
                        pause = DETAIL_BATCH_PAUSE + random.uniform(0, 3)
                        print(f"   ⏸ Pause {pause:.0f}s sau {detail_count_in_batch} detail pages...")
                        await asyncio.sleep(pause)
                        detail_count_in_batch = 0
                else:
                    _record_blocked_job(state, jid, durl, job.get("title", ""))
                    print("✗")
                    # Session recovery: close the tainted page and open a fresh one.
                    # After a block, the server may flag the browser session,
                    # causing subsequent requests to also fail.
                    try:
                        await page.close()
                    except Exception:
                        pass
                    try:
                        page = await context.new_page()
                        # Navigate back to listing page for find_next()
                        await page.goto(current_url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(random.uniform(2.0, 4.0))
                    except Exception:
                        pass

            # Mark page complete
            pg_entry["status"] = "complete"
            save_checkpoint(run_dir, state)

            if TARGET_JOBS is not None and fetches_done >= needed:
                print(f"   🎯 Đủ nhu cầu — dừng proxy.")
                break

            next_url = await find_next(page)
            if not next_url:
                print(f"   ℹ Hết trang (dừng ở {page_num})")
                break
            current_url = next_url
            page_num += 1
            pages_done_this_proxy += 1

        return new_items, pages_visited
    except Exception as e:
        print(f"   ✗ {type(e).__name__}: {e}")
        return new_items, pages_visited
    finally:
        if browser:
            await browser.close()


def dedup(items: list[dict]) -> list[dict]:
    seen = {}
    for it in items:
        key = it.get("job_id") or (it.get("title", ""), it.get("company", ""))
        seen[key] = it
    return list(seen.values())


def save_results(items: list[dict], run_dir: Path, state: dict) -> None:
    if not items:
        print("⚠ Không có dữ liệu để lưu.")
        return
    json_path = run_dir / "jobs.json"
    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    csv_path = run_dir / "jobs.csv"
    fields = ["job_id", "title", "company", "salary", "location", "jobType",
              "detail_url", "detail_html_path", "link", "page", "crawled_at",
              "proxy_used", "page_url", "page_html_path"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)

    pages_crawled = len(state.get("pages", []))
    metadata = {
        "timestamp": run_dir.name.replace("run_", ""),
        "crawled_at": datetime.now().isoformat(),
        "total_jobs": len(items),
        "pages_crawled": pages_crawled,
        "proxies_used": list(state.get("used_proxies", [])),
        "target_url": state.get("target_url", TARGET_URL),
    }
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n💾 Lưu:")
    print(f"   JSON → {json_path}  ({len(items)} records)")
    print(f"   CSV  → {csv_path}")
    print(f"   Meta → {metadata_path}")


async def main():
    print(f"{'═'*60}")
    print(f"  Ekaigo Crawler v4 — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Target: {TARGET_URL}  |  Mục tiêu: {TARGET_JOBS} jobs")
    print(f"{'═'*60}\n")

    proxies = load_proxies()
    if not proxies:
        print("❌ Không có proxy. Chạy python", FETCH_SCRIPT)
        return

    OUTPUT_DIR.mkdir(exist_ok=True)

    # ── Resume or fresh start ──
    run_dir = None
    state = None
    all_results: list[dict] = []
    resume_detail_only = False
    proxy_start_idx = 0

    if AUTO_RESUME:
        result = find_latest_incomplete_run(OUTPUT_DIR)
        if result:
            run_dir, state = result
            pages = state.get("pages", [])
            pending_page = None
            for pg in pages:
                if pg and pg.get("status") == "details_pending":
                    pending_page = pg
                    break
            if pending_page:
                resume_detail_only = True
                proxy_start_idx = max(0, state.get("current_proxy_idx", 0))
                start_at = pending_page.get("page_num", 1)
                print(f"🔄 Resuming run {run_dir.name}")
                print(f"   {len(pages)} pages in checkpoint, resuming detail fetch for page {start_at}")
                all_results = checkpoint_to_jobs(state)
            elif pages:
                # All pages complete but target not yet met
                last_complete = max((p for p in pages if p and p.get("status") == "complete"),
                                    key=lambda p: p.get("page_num", 0), default=None)
                resume_detail_only = False
                proxy_start_idx = max(0, state.get("current_proxy_idx", 0))
                start_at = (last_complete.get("page_num", 0) + 1) if last_complete else 1
                print(f"🔄 Resuming run {run_dir.name}")
                print(f"   {len(pages)} pages complete ({state.get('total_jobs_extracted', 0)} jobs), starting from page {start_at}")
                all_results = checkpoint_to_jobs(state)
                # We'll pass start_at via the loop below
            else:
                run_dir = None
                state = None

    if run_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = OUTPUT_DIR / f"run_{ts}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "html").mkdir(exist_ok=True)
        state = init_checkpoint(run_dir, TARGET_URL, TARGET_JOBS)
        save_checkpoint(run_dir, state)
        all_results = []

    start_page = 1
    if state.get("pages"):
        completed = [p for p in state["pages"] if p and p.get("status") == "complete"]
        if completed:
            last = max(completed, key=lambda p: p.get("page_num", 0))
            start_page = last.get("page_num", 0) + 1

    # ── Proxy loop ──
    for i in range(proxy_start_idx, len(proxies)):
        proxy = proxies[i]
        proxy_idx = i + 1
        needed = (TARGET_JOBS - len(dedup(all_results))) if TARGET_JOBS is not None else 999999
        if TARGET_JOBS is not None and needed <= 0:
            break

        current_start = start_page
        current_resume = resume_detail_only
        if state.get("pages"):
            pend = [p for p in state["pages"] if p and p.get("status") == "details_pending"]
            if pend:
                current_start = pend[0].get("page_num", start_page)
                current_resume = True
            else:
                completed = [p for p in state["pages"] if p and p.get("status") == "complete"]
                if completed:
                    last = max(completed, key=lambda p: p.get("page_num", 0))
                    current_start = last.get("page_num", 0) + 1
                    current_resume = False

        print(f"\n[{proxy_idx}/{len(proxies)}]", end="")
        items, pages_visited = await crawl_with_proxy(
            proxy, needed, run_dir, proxy_idx, state,
            start_page=current_start, resume_detail_only=current_resume
        )

        if items:
            state.setdefault("used_proxies", []).append(proxy)
            save_checkpoint(run_dir, state)
            all_results = dedup(all_results + items)
            print(f"\n🎉 Proxy #{proxy_idx}: tổng tích lũy {len(all_results)} jobs (dedup)")
            if TARGET_JOBS is not None and len(all_results) >= TARGET_JOBS:
                print(f"\n✅ Đã đủ {TARGET_JOBS}+ jobs — dừng.")
                break
        elif pages_visited > 0:
            state.setdefault("used_proxies", []).append(proxy)
            save_checkpoint(run_dir, state)
            print(f"\n📄 Proxy #{proxy_idx}: {pages_visited} pages visited (all deduped)")
        else:
            wait = random.uniform(4, 9)
            print(f"   ⏳ Proxy tiếp theo sau {wait:.1f}s...")
            await asyncio.sleep(wait)

        # Re-check state: if the pending page is now complete, advance.
        # If still details_pending, the next proxy will auto-resume from same page.
        pend = [p for p in state.get("pages", []) if p and p.get("status") == "details_pending"]
        if not pend:
            resume_detail_only = False
            completed = [p for p in state.get("pages", []) if p and p.get("status") == "complete"]
            if completed:
                last = max(completed, key=lambda p: p.get("page_num", 0))
                start_page = last.get("page_num", 0) + 1
            state["current_proxy_idx"] = proxy_idx + 1
            save_checkpoint(run_dir, state)

    if not all_results:
        print(f"\n❌ Không có job nào được crawl — thử re-fetch.")
        try:
            for f in run_dir.glob("*"):
                if f.is_file(): f.unlink()
            if (run_dir / "html").exists():
                for f in (run_dir / "html").glob("*"):
                    f.unlink()
                (run_dir / "html").rmdir()
            run_dir.rmdir()
        except Exception:
            pass
        _refetch()
        return

    save_results(all_results, run_dir, state)
    print(f"\n{'═'*60}")
    print(f"✅ Hoàn thành! {len(all_results)} jobs từ {len(state.get('used_proxies', []))} proxy.")
    print(f"{'═'*60}")


if __name__ == "__main__":
    asyncio.run(main())
