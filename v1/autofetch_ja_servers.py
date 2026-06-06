"""
1_fetch_proxies.py · Proxifly edition (v3 — auto-rotate anonymity + real scoring)
─────────────────────────────────────────────────────────────────────────────
Pipeline: Fetch → Verify JP IP → Verify target → Score → Save cache (có TTL)

Cải tiến chính:
  - Không cố định MIN_ANONYMITY: tự xoay transparent → anonymous → elite
    cho đến khi đủ MIN_GOOD proxy JP sống.
  - Chấm điểm THỰC TẾ: latency target + vào được site + anonymity + protocol.
  - Verify IP Nhật ngay trong fetch (ipinfo.io) → cache toàn proxy đã kiểm chứng.
  - Mỗi proxy có verified_at → script sau biết tuổi proxy.

Yêu cầu: pip install requests PySocks
"""

import json
import time
import requests
import concurrent.futures
from pathlib import Path
from datetime import datetime

# ════════════════════════ CẤU HÌNH ════════════════════════
WORKING_FILE   = Path("japan_working_proxies.json")
TOP_N          = 60          # số candidate tối đa đem đi test mỗi vòng anonymity
WORKERS        = 25
TEST_TIMEOUT   = 8
MIN_GOOD       = 8           # đủ bao nhiêu proxy JP-sống thì dừng xoay anonymity
IP_CHECK_URL   = "https://ipinfo.io/json"
TARGET_URL     = "https://www.ekaigotenshoku.com/kyujin/list?z01=1"
SUCCESS_KW     = ["求人", "介護", "給与", "勤務地", "施設", "募集", "正社員"]

# Vòng xoay anonymity: lỏng → chặt (nhiều proxy → ít nhưng sạch)
ANONYMITY_ORDER = ["transparent", "anonymous", "elite"]

_CDN = "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies"

FETCH_ENDPOINTS = [
    (f"{_CDN}/countries/JP/data.json",     False),
    (f"{_CDN}/protocols/socks5/data.json", True),
    (f"{_CDN}/protocols/socks4/data.json", True),
    (f"{_CDN}/all/data.json",              True),
]

_ANON_RANK  = {"elite": 0, "anonymous": 1, "transparent": 2, "unknown": 3}
_PROTO_RANK = {"socks5": 0, "socks4": 1, "https": 2, "http": 3}
# ═══════════════════════════════════════════════════════════


def _get_country(item: dict) -> str:
    geo = item.get("geolocation")
    if isinstance(geo, dict):
        c = geo.get("country", "")
        if c:
            return c
    return item.get("country", "")


def _fetch_raw_pool() -> list[dict]:
    """Tải toàn bộ proxy (mọi anonymity) về 1 lần, dedup theo IP. Lọc JP."""
    pool: list[dict] = []
    seen: set[str] = set()

    for url, need_filter in FETCH_ENDPOINTS:
        short = "/".join(url.split("/")[-3:])
        print(f"   ↓ {short} ...", end=" ", flush=True)
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"✗ HTTP error: {e}")
            continue

        try:
            raw = r.json()
        except ValueError as e:
            print(f"✗ JSON parse error: {e}")
            continue

        if not isinstance(raw, list) or not raw:
            print("✗ Empty / unexpected payload")
            continue

        print(f"✓ {len(raw)} items")
        added = 0
        for item in raw:
            if need_filter and _get_country(item) != "JP":
                continue
            ip = item.get("ip", "").strip()
            if not ip or ip in seen:
                continue
            seen.add(ip)

            proxy_url = item.get("proxy", "").strip()
            if not proxy_url:
                proto = item.get("protocol", "http")
                port  = item.get("port", 0)
                proxy_url = f"{proto}://{ip}:{port}"

            pool.append({
                "proxy":     proxy_url,
                "protocol":  item.get("protocol", "http"),
                "ip":        ip,
                "port":      item.get("port", 0),
                "anonymity": item.get("anonymity", "unknown"),
                "api_score": item.get("score", 0),
            })
            added += 1
        print(f"   → +{added} JP proxy (pool: {len(pool)})")

    return pool


def _verify_one(p: dict, timeout: int) -> dict:
    """
    Verify đầy đủ 1 proxy: IP JP? + vào target được? + latency thật.
    Trả về dict đã enrich (alive, is_jp, target_ok, ms_ip, ms_tgt, real_score).
    """
    p = dict(p)
    p.update(alive=False, is_jp=False, target_ok=False,
             ms_ip=-1, ms_tgt=-1, real_score=0, verified_country="?")

    proxies = {"http": p["proxy"], "https": p["proxy"]}
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ja,en;q=0.9"}

    # ── Test 1: IP check ──
    try:
        t0 = time.perf_counter()
        r = requests.get(IP_CHECK_URL, proxies=proxies, timeout=timeout, headers=headers)
        ms_ip = int((time.perf_counter() - t0) * 1000)
        data = r.json()
        country = data.get("country", "?")
        p.update(alive=True, ms_ip=ms_ip, verified_country=country,
                 verified_ip=data.get("ip", p["ip"]))
        if country != "JP":
            return p
        p["is_jp"] = True
    except Exception:
        return p

    # ── Test 2: Target site ──
    try:
        t0 = time.perf_counter()
        r2 = requests.get(TARGET_URL, proxies=proxies, timeout=timeout,
                          headers=headers, allow_redirects=True)
        ms_tgt = int((time.perf_counter() - t0) * 1000)
        ok = (r2.status_code < 400) and any(kw in r2.text for kw in SUCCESS_KW)
        p.update(target_ok=ok, ms_tgt=ms_tgt)
    except Exception:
        pass

    p["real_score"] = _score(p)
    return p


def _score(p: dict) -> float:
    """
    Chấm điểm thực tế, càng cao càng tốt.
      + 100 nếu vào được target
      + thưởng theo tốc độ (latency thấp)
      + thưởng anonymity (elite > anonymous > transparent)
      + thưởng protocol (socks5 > socks4 > https > http)
    """
    if not p.get("is_jp"):
        return 0.0
    score = 0.0
    if p.get("target_ok"):
        score += 100
        ms = p.get("ms_tgt", 9999)
        score += max(0, 60 - ms / 100)          # nhanh hơn → nhiều điểm hơn
    else:
        ms = p.get("ms_ip", 9999)
        score += max(0, 30 - ms / 100)
    score += (3 - _ANON_RANK.get(p.get("anonymity", "unknown"), 3)) * 5
    score += (3 - _PROTO_RANK.get(p.get("protocol", "http"), 3)) * 3
    return round(score, 1)


def verify_pool(pool: list[dict]) -> list[dict]:
    """Verify song song toàn bộ candidate, in tiến trình."""
    print(f"\n⚡ Verifying {len(pool)} proxy ({WORKERS} luồng)...")
    print(f"{'─'*72}")
    verified = []
    total = len(pool)
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool_ex:
        fmap = {pool_ex.submit(_verify_one, p, TEST_TIMEOUT): i
                for i, p in enumerate(pool, 1)}
        for fut in concurrent.futures.as_completed(fmap):
            idx = fmap[fut]
            r = fut.result()
            verified.append(r)
            if r["is_jp"] and r["target_ok"]:
                icon = f"🇯🇵✅ {r['ms_tgt']:>5}ms  score={r['real_score']}"
            elif r["is_jp"]:
                icon = f"🇯🇵⚠  site? ({r['ms_ip']}ms)"
            elif r["alive"]:
                icon = f"✗ [{r['verified_country']}] not JP"
            else:
                icon = "✗ dead"
            print(f"  [{idx:>3}/{total}] {r['proxy']:<40} {icon}")
    return verified


def fetch_and_verify() -> list[dict]:
    """
    Vòng xoay anonymity: bắt đầu transparent, nếu chưa đủ MIN_GOOD proxy
    JP-target-ok thì nới sang anonymous, rồi elite (gộp tất cả).
    """
    full_pool = _fetch_raw_pool()
    if not full_pool:
        return []

    good: list[dict] = []
    tested_ips: set[str] = set()

    for level in ANONYMITY_ORDER:
        cutoff = _ANON_RANK[level]
        # lấy proxy có anonymity <= level (chặt hơn hoặc bằng), chưa test
        batch = [p for p in full_pool
                 if _ANON_RANK.get(p["anonymity"], 9) <= cutoff
                 and p["ip"] not in tested_ips]
        # sort sơ bộ theo api_score để test cái hứa hẹn trước
        batch.sort(key=lambda x: (-x.get("api_score", 0),
                                  _PROTO_RANK.get(x["protocol"], 9)))
        batch = batch[:TOP_N]
        if not batch:
            continue

        print(f"\n{'═'*72}")
        print(f"  🔄 Vòng anonymity = '{level}'  ({len(batch)} candidate)")
        print(f"{'═'*72}")

        for p in batch:
            tested_ips.add(p["ip"])

        verified = verify_pool(batch)
        new_good = [v for v in verified if v["is_jp"] and v["target_ok"]]
        good.extend(new_good)
        print(f"\n  → Vòng '{level}': +{len(new_good)} proxy JP vào-được-target "
              f"(tổng tốt: {len(good)})")

        if len(good) >= MIN_GOOD:
            print(f"  ✅ Đủ {MIN_GOOD}+ proxy tốt — dừng xoay anonymity.")
            break

    # Nếu không có proxy nào vào được target, vớt proxy JP-alive làm dự phòng
    if not good:
        print("\n  ⚠ Không proxy nào vào được target — vớt proxy JP-alive làm fallback")
        fallback_batch = [p for p in full_pool][:TOP_N]
        verified = verify_pool(fallback_batch)
        good = [v for v in verified if v["is_jp"]]

    good.sort(key=lambda x: -x.get("real_score", 0))
    return good


def save(proxies: list[dict]) -> None:
    now = datetime.now().isoformat()
    for p in proxies:
        p["verified_at"] = now
    out = {
        "updated_at": now,
        "source":     "github.com/proxifly/free-proxy-list",
        "target":     TARGET_URL,
        "count":      len(proxies),
        "proxies":    proxies,
    }
    WORKING_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                            encoding="utf-8")


# ════════════════════════ MAIN ════════════════════════
if __name__ == "__main__":
    print(f"{'═'*72}")
    print(f"  Proxifly JP Fetcher v3 — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'═'*72}\n")

    good = fetch_and_verify()

    if not good:
        print("\n❌ Không lấy được proxy JP nào sống. Thử lại sau vài phút.")
        raise SystemExit(1)

    print(f"\n{'═'*72}")
    print(f"  ✅ {len(good)} proxy JP đã verify (sort theo điểm thực tế)\n")
    for i, p in enumerate(good[:12], 1):
        tgt = "site✅" if p["target_ok"] else "site⚠"
        print(f"  {i:>2}. {p['proxy']:<40} score={p['real_score']:>5}  "
              f"{tgt}  {p.get('ms_tgt', p['ms_ip'])}ms  {p['anonymity']}")
    save(good)
    print(f"\n  💾 {WORKING_FILE}  ({len(good)} proxy)")
    print(f"  👉 python check_proxy.py  hoặc  python cloak_auto_japan.py")
    print(f"{'═'*72}")
