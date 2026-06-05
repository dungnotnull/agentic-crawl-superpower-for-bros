"""
Proxy checker - Concurrent edition (v3 - Windows-safe)
===========================================================
Re-check cache: is proxy still JP-alive, can it still reach target,
current latency, and cache AGE. Auto-warn if cache is expired.
"""

import json
import sys
import time
import requests
import concurrent.futures
import subprocess
from pathlib import Path
from datetime import datetime, timedelta


def _print(msg: str = "", end: str = "\n", flush: bool = False) -> None:
    try:
        print(msg, end=end, flush=flush)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            msg.encode("utf-8", errors="replace") + end.encode())
        sys.stdout.flush()

def _sep(char: str = "=", width: int = 60) -> str:
    return char * width

# --- Configuration ---
WORKING_FILE = Path("japan_working_proxies.json")
FETCH_SCRIPT = "proxy/fetcher.py"
WORKERS      = 15
TIMEOUT      = 10
CACHE_TTL    = timedelta(minutes=30)
DEFAULT_TARGET_URL = "https://www.ekaigotenshoku.com/kyujin/list?z01=1"
DEFAULT_SUCCESS_KW = ["求人", "介護", "給与", "勤務地"]


def _load_target_from_args() -> tuple[str, list[str], str]:
    """Parse CLI for --site or --url/--keywords."""
    args = sys.argv[1:]
    site_name = None
    target_url = DEFAULT_TARGET_URL
    success_kw = DEFAULT_SUCCESS_KW

    i = 0
    while i < len(args):
        if args[i] == "--site" and i + 1 < len(args):
            site_name = args[i + 1]; i += 2
        elif args[i] == "--url" and i + 1 < len(args):
            target_url = args[i + 1]; i += 2
        elif args[i] == "--keywords" and i + 1 < len(args):
            success_kw = [kw.strip() for kw in args[i + 1].split(",") if kw.strip()]
            i += 2
        elif args[i] in ("--help", "-h"):
            _print("Usage: python proxy/checker.py [--site NAME] [--url URL] [--keywords kw1,kw2,...]")
            import sys as _sys; _sys.exit(0)
        else:
            i += 1

    if site_name:
        try:
            try:
                from site_mappings import load_site_mapping
            except ImportError:
                from .site_mappings import load_site_mapping
            mapping = load_site_mapping(site_name)
            target_url = mapping.url.listing_url
            success_kw = mapping.success_keywords
            _print(f"[SITE] {mapping.display_name}: {target_url}")
        except Exception as e:
            _print(f"[WARN] Failed to load site '{site_name}': {e}")

    return target_url, success_kw, site_name or target_url


def _check_one(proxy_url: str, target_url: str, success_kw: list[str]) -> dict:
    result = {"proxy": proxy_url, "alive": False, "country": "?",
              "ip": "?", "ms_ip": -1, "target": False, "ms_tgt": -1}
    proxies = {"http": proxy_url, "https": proxy_url}
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ja,en;q=0.9"}

    try:
        t0 = time.perf_counter()
        r = requests.get("https://ipinfo.io/json", proxies=proxies,
                         timeout=TIMEOUT, headers=headers)
        ms = int((time.perf_counter() - t0) * 1000)
        data = r.json()
        result.update(alive=True, ip=data.get("ip", "?"),
                      country=data.get("country", "?"), ms_ip=ms)
    except Exception as e:
        result["error"] = str(e)[:50]
        return result

    if result["country"] != "JP":
        return result

    try:
        t0 = time.perf_counter()
        r2 = requests.get(target_url, proxies=proxies, timeout=TIMEOUT,
                          headers=headers, allow_redirects=True)
        ms2 = int((time.perf_counter() - t0) * 1000)
        ok = any(kw in r2.text for kw in success_kw) and r2.status_code < 400
        result.update(target=ok, ms_tgt=ms2)
    except Exception:
        pass
    return result


def load_proxies() -> tuple[list[str], datetime | None]:
    if not WORKING_FILE.exists():
        _print(f"[CHECK] Not found: {WORKING_FILE}")
        return [], None
    try:
        data = json.loads(WORKING_FILE.read_text(encoding="utf-8"))
        proxies = [p["proxy"] for p in data.get("proxies", []) if p.get("proxy")]
        updated_raw = data.get("updated_at")
        updated = datetime.fromisoformat(updated_raw) if updated_raw else None
        age_str = updated.strftime("%H:%M") if updated else "?"
        _print(f"[CHECK] {len(proxies)} proxies from {WORKING_FILE}  (updated {age_str})")
        return proxies, updated
    except Exception as e:
        _print(f"[CHECK] File read error: {e}")
        return [], None


def check_cache_age(updated: datetime | None) -> None:
    if updated is None:
        return
    age = datetime.now() - updated
    mins = int(age.total_seconds() // 60)
    ttl_mins = int(CACHE_TTL.total_seconds() // 60)
    if age > CACHE_TTL:
        _print(f"[CHECK] Cache is {mins} minutes old (> {ttl_mins}min) "
               f"- SHOULD re-run {FETCH_SCRIPT}")
    else:
        _print(f"[CHECK] Cache still fresh ({mins} minutes old)")


def run_checks(proxies: list[str], target_url: str, success_kw: list[str]) -> list[dict]:
    _print(f"\n[CHECK] Checking {len(proxies)} proxies ({WORKERS} threads)...\n")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_check_one, p, target_url, success_kw): i for i, p in enumerate(proxies, 1)}
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            r = future.result()
            results.append(r)
            if not r["alive"]:
                err = r.get("error", "timeout")[:25]
                _print(f"  {idx:>3}. DEAD  {err}")
            elif r["country"] != "JP":
                _print(f"  {idx:>3}. {r['proxy']:<40}  [{r['country']}] not JP")
            else:
                tgt = "site:OK" if r["target"] else "site:?"
                ms2 = f"{r['ms_tgt']}ms" if r["ms_tgt"] > 0 else "---"
                _print(f"  {idx:>3}. {r['proxy']:<40}  JP {tgt}  {ms2}")
    return results


def print_summary(results: list[dict], updated: datetime | None) -> None:
    jp_ok    = [r for r in results if r.get("country") == "JP" and r.get("target")]
    jp_alive = [r for r in results if r.get("country") == "JP"]
    dead     = [r for r in results if not r.get("alive")]

    _print(f"\n{_sep()}")
    _print(f"  Results:")
    _print(f"     JP + can access site : {len(jp_ok)}")
    _print(f"     JP (correct IP)      : {len(jp_alive)}")
    _print(f"     Dead / timeout       : {len(dead)}")

    if jp_ok:
        best = min(jp_ok, key=lambda x: x.get("ms_tgt", 9999))
        _print(f"\n  Fastest proxy: {best['proxy']}  ->  {best['ms_tgt']}ms")

    if not jp_alive:
        _print(f"\n  [ERROR] No working JP proxies!")
        _print(f"  -> Run: python {FETCH_SCRIPT}")
    elif not jp_ok:
        _print(f"\n  [WARN] Japanese IP exists but site error - possibly temporary rate-limit")
    else:
        _print(f"\n  Ready to crawl: python main.py")
    check_cache_age(updated)
    _print(f"{_sep()}")


def maybe_refetch() -> bool:
    _print(f"\n[AUTO] Running {FETCH_SCRIPT} to refresh cache...")
    try:
        subprocess.run([sys.executable, FETCH_SCRIPT], check=True)
        return True
    except Exception as e:
        _print(f"[ERROR] Re-fetch failed: {e}")
        return False


if __name__ == "__main__":
    target_url, success_kw, label = _load_target_from_args()

    _print(f"{_sep()}")
    _print(f"  Proxy Checker v3 - {datetime.now():%Y-%m-%d %H:%M}")
    _print(f"  Target: {label}")
    _print(f"{_sep()}\n")

    proxies, updated = load_proxies()

    if not proxies:
        if maybe_refetch():
            proxies, updated = load_proxies()
        if not proxies:
            raise SystemExit(1)

    results = run_checks(proxies, target_url, success_kw)
    print_summary(results, updated)
