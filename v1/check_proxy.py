"""
3_check_proxy.py · Concurrent edition (v2 — TTL aware + re-score)
─────────────────────────────────────────────────────────────────
Kiểm tra lại cache: proxy còn JP-alive không, còn vào target không,
latency hiện tại, và TUỔI của cache. Tự cảnh báo nếu cache quá hạn.

Yêu cầu: pip install requests PySocks
"""

import json
import time
import requests
import concurrent.futures
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

# ════════════════════ CẤU HÌNH ════════════════════
WORKING_FILE = Path("japan_working_proxies.json")
FETCH_SCRIPT = "autofetch_ja_servers.py"
WORKERS      = 15
TIMEOUT      = 10
CACHE_TTL    = timedelta(minutes=30)     # cache quá tuổi này → khuyên re-fetch
TARGET_URL   = "https://www.ekaigotenshoku.com/kyujin/list?z01=1"
SUCCESS_KW   = ["求人", "介護", "給与", "勤務地"]
# ══════════════════════════════════════════════════


def _check_one(proxy_url: str) -> dict:
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
        r2 = requests.get(TARGET_URL, proxies=proxies, timeout=TIMEOUT,
                          headers=headers, allow_redirects=True)
        ms2 = int((time.perf_counter() - t0) * 1000)
        ok = any(kw in r2.text for kw in SUCCESS_KW) and r2.status_code < 400
        result.update(target=ok, ms_tgt=ms2)
    except Exception:
        pass
    return result


def load_proxies() -> tuple[list[str], datetime | None]:
    if not WORKING_FILE.exists():
        print(f"⚠ Không tìm thấy {WORKING_FILE}")
        return [], None
    try:
        data = json.loads(WORKING_FILE.read_text(encoding="utf-8"))
        proxies = [p["proxy"] for p in data.get("proxies", []) if p.get("proxy")]
        updated_raw = data.get("updated_at")
        updated = datetime.fromisoformat(updated_raw) if updated_raw else None
        age_str = updated.strftime("%H:%M") if updated else "?"
        print(f"📋 {len(proxies)} proxy từ {WORKING_FILE}  (cập nhật {age_str})")
        return proxies, updated
    except Exception as e:
        print(f"❌ Đọc file lỗi: {e}")
        return [], None


def check_cache_age(updated: datetime | None) -> None:
    if updated is None:
        return
    age = datetime.now() - updated
    mins = int(age.total_seconds() // 60)
    if age > CACHE_TTL:
        print(f"⏰ Cache đã {mins} phút tuổi (> {int(CACHE_TTL.total_seconds()//60)}p) "
              f"— NÊN chạy lại {FETCH_SCRIPT}")
    else:
        print(f"✓ Cache còn tươi ({mins} phút tuổi)")


def run_checks(proxies: list[str]) -> list[dict]:
    print(f"\n⚡ Checking {len(proxies)} proxy ({WORKERS} luồng)...\n")
    hdr = f"  {'#':>3}  {'Proxy':<40}  {'IP':>15}  {'ms_ip':>6}  {'ms_tgt':>7}  Status"
    print(hdr)
    print(f"  {'─'*len(hdr)}")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_check_one, p): i for i, p in enumerate(proxies, 1)}
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            r = future.result()
            results.append(r)
            if not r["alive"]:
                err = r.get("error", "timeout")[:25]
                print(f"  {idx:>3}.  {'✗':<40}  {'—':>15}  {'—':>6}  {'—':>7}  ✗ {err}")
            elif r["country"] != "JP":
                print(f"  {idx:>3}.  {r['proxy']:<40}  {r['ip']:>15}  {r['ms_ip']:>5}ms"
                      f"  {'—':>7}  [{r['country']}] not JP")
            else:
                tgt = "✅ site" if r["target"] else "⚠ site?"
                ms2 = f"{r['ms_tgt']}ms" if r["ms_tgt"] > 0 else "---"
                print(f"  {idx:>3}.  {r['proxy']:<40}  {r['ip']:>15}  {r['ms_ip']:>5}ms"
                      f"  {ms2:>7}  🇯🇵 {tgt}")
    return results


def print_summary(results: list[dict], updated: datetime | None) -> None:
    jp_ok    = [r for r in results if r.get("country") == "JP" and r.get("target")]
    jp_alive = [r for r in results if r.get("country") == "JP"]
    dead     = [r for r in results if not r.get("alive")]

    print(f"\n{'═'*60}")
    print(f"  📊 Kết quả:")
    print(f"     🇯🇵 JP + vào site được : {len(jp_ok)}")
    print(f"     🇯🇵 JP (IP đúng)       : {len(jp_alive)}")
    print(f"     💀 Dead / timeout      : {len(dead)}")

    if jp_ok:
        best = min(jp_ok, key=lambda x: x.get("ms_tgt", 9999))
        print(f"\n  🏆 Proxy nhanh nhất: {best['proxy']}  →  {best['ms_tgt']}ms")

    if not jp_alive:
        print(f"\n  ❌ Không có proxy JP nào hoạt động!")
        print(f"  → Chạy: python {FETCH_SCRIPT}")
    elif not jp_ok:
        print(f"\n  ⚠ IP Nhật có nhưng site lỗi — có thể rate-limit tạm thời")
    else:
        print(f"\n  👉 Sẵn sàng crawl: python cloak_auto_japan.py")
    check_cache_age(updated)
    print(f"{'═'*60}")


def maybe_refetch() -> bool:
    """Tự chạy fetch script. Trả True nếu thành công."""
    print(f"\n🔁 Tự động chạy {FETCH_SCRIPT} để làm mới cache...")
    try:
        subprocess.run([sys.executable, FETCH_SCRIPT], check=True)
        return True
    except Exception as e:
        print(f"❌ Re-fetch lỗi: {e}")
        return False


# ════════════════════ MAIN ════════════════════
if __name__ == "__main__":
    print(f"{'═'*60}")
    print(f"  Proxy Checker v2 — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'═'*60}\n")

    proxies, updated = load_proxies()

    # Self-healing: không có cache → tự fetch
    if not proxies:
        if maybe_refetch():
            proxies, updated = load_proxies()
        if not proxies:
            raise SystemExit(1)

    results = run_checks(proxies)
    print_summary(results, updated)
