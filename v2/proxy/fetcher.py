"""
Proxy Fetcher - Multi-provider, Multi-country edition (v5)
===========================================================================
Pipeline: Fetch from multiple providers -> Dedup -> Verify Country IP ->
          Verify target -> Score -> Save cache (with TTL)

Providers: 14+ free proxy sources aggregated into one pool.
Now supports country-specific proxy scraping for:
  Vietnam, Japan, China, South Korea, Singapore, Russia, Europe, India, USA.

Requirements: pip install requests PySocks
"""

import json
import sys
import time
import requests
import concurrent.futures
from pathlib import Path
from datetime import datetime

# --- Safe print for Windows consoles that can't handle Unicode box chars ---

def _print(msg: str = "", end: str = "\n", flush: bool = False) -> None:
    try:
        print(msg, end=end, flush=flush)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            msg.encode("utf-8", errors="replace") + end.encode())
        sys.stdout.flush()

def _sep(char: str = "=", width: int = 72) -> str:
    return char * width

def _banner(text: str) -> None:
    _print()
    _print(_sep("="))
    _print(f"  {text}")
    _print(_sep("="))

def _sub(text: str) -> None:
    _print()
    _print(_sep("-"))
    _print(f"  {text}")
    _print(_sep("-"))

def _action(tag: str, msg: str) -> None:
    _print(f"   [{tag}] {msg}")


# --- Country Configuration -------------------------------------------------

COUNTRY_CODES = {
    "vietnam": "VN",
    "japan": "JP",
    "china": "CN",
    "south korea": "KR",
    "singapore": "SG",
    "russia": "RU",
    "europe": "EU",
    "india": "IN",
    "usa": "US",
}

# European country codes used for IP verification when region="europe"
EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE", "GB", "NO", "CH",
    "UA", "IS", "LI",
}

# --- Site-aware target detection -----------------------------------------

DEFAULT_TARGET_URL = "https://www.ekaigotenshoku.com/kyujin/list?z01=1"
DEFAULT_SUCCESS_KW = ["??", "??", "??", "???", "??", "??", "???"]

def _load_target_from_args() -> tuple[str, list[str], str, str]:
    """Parse CLI for --site, --country, or --url/--keywords overrides.
    Returns (target_url, success_keywords, site_name_or_url, country_code).
    """
    args = sys.argv[1:]
    site_name = None
    target_url = DEFAULT_TARGET_URL
    success_kw = DEFAULT_SUCCESS_KW
    country = "JP"

    i = 0
    while i < len(args):
        if args[i] == "--site" and i + 1 < len(args):
            site_name = args[i + 1]
            i += 2
        elif args[i] == "--country" and i + 1 < len(args):
            country_input = args[i + 1].strip().lower()
            country = COUNTRY_CODES.get(country_input, country_input.upper())
            i += 2
        elif args[i] == "--url" and i + 1 < len(args):
            target_url = args[i + 1]
            i += 2
        elif args[i] == "--keywords" and i + 1 < len(args):
            success_kw = [kw.strip() for kw in args[i + 1].split(",") if kw.strip()]
            i += 2
        elif args[i] in ("--help", "-h"):
            _print("Usage: python proxy/fetcher.py [--site NAME] [--country COUNTRY] [--url URL] [--keywords kw1,kw2,...]")
            _print("  --site NAME       Load URL and keywords from site mapping (e.g. ekaigotenshoku)")
            _print("  --country NAME    Target country: vietnam, japan, china, south korea, singapore, russia, europe, india, usa")
            _print("  --url URL         Override the target URL to verify against")
            _print("  --keywords ...    Comma-separated keywords to verify on target page")
            _print("  --help, -h        Show this help")
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
            _print(f"[SITE] Keywords: {', '.join(success_kw)}")
        except Exception as e:
            _print(f"[WARN] Failed to load site '{site_name}': {e}")
            _print(f"[WARN] Falling back to default target")

    return target_url, success_kw, site_name or target_url, country


# --- Configuration ---
WORKING_FILE   = Path("japan_working_proxies.json")
TOP_N          = 60
WORKERS        = 25
TEST_TIMEOUT   = 8
MIN_GOOD       = 8
IP_CHECK_URL   = "https://ipinfo.io/json"

ANONYMITY_ORDER = ["transparent", "anonymous", "elite"]
_ANON_RANK  = {"elite": 0, "anonymous": 1, "transparent": 2, "unknown": 3}
_PROTO_RANK = {"socks5": 0, "socks4": 1, "https": 2, "http": 3}


# --- Provider Definitions (country-aware) -------------------------------

def _provider_list(country_code: str) -> list[dict]:
    """Return provider definitions parameterized by country code."""
    cc = country_code.upper()
    # For Europe we fall back to global/unfiltered lists and rely on verification
    geo_cc = cc if cc != "EU" else "all"

    providers = [
        {"name": f"Proxifly {cc}",       "format": "proxifly",   "need_filter": False,
         "url": f"https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/countries/{cc}/data.json"},
        {"name": "Proxifly SOCKS5",      "format": "proxifly",   "need_filter": True,
         "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.json"},
        {"name": "Proxifly SOCKS4",      "format": "proxifly",   "need_filter": True,
         "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.json"},
        {"name": "Proxifly Global",      "format": "proxifly",   "need_filter": True,
         "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/all/data.json"},
        {"name": f"ProxyScrape SOCKS5 {geo_cc}", "format": "plain_text", "need_filter": False, "protocol": "socks5",
         "url": f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country={geo_cc}&ssl=all&anonymity=all"},
        {"name": f"ProxyScrape HTTP {geo_cc}",   "format": "plain_text", "need_filter": False, "protocol": "http",
         "url": f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country={geo_cc}&ssl=all&anonymity=all"},
        {"name": f"ProxyScrape SOCKS4 {geo_cc}","format": "plain_text", "need_filter": False, "protocol": "socks4",
         "url": f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country={geo_cc}&ssl=all&anonymity=all"},
    ]

    # GeoNode supports multi-country codes; for Europe, use a broad EU list
    if cc == "EU":
        eu_codes = ",".join(sorted(EU_COUNTRY_CODES))[:300]  # keep URL reasonably short
        providers.append({
            "name": "GeoNode EU",
            "format": "geonode", "need_filter": False,
            "url": f"https://proxylist.geonode.com/api/proxy-list?countries={eu_codes}&limit=500&page=1&sort_by=lastChecked&sort_type=desc",
        })
    else:
        providers.append({
            "name": f"GeoNode {cc}",
            "format": "geonode", "need_filter": False,
            "url": f"https://proxylist.geonode.com/api/proxy-list?countries={cc}&limit=500&page=1&sort_by=lastChecked&sort_type=desc",
        })

    providers.extend([
        {"name": "FreeProxyList CDN",  "format": "proxifly",   "need_filter": True,
         "url": "https://cdn.jsdelivr.net/gh/themiracleworker/free-proxy-list@main/proxies.json"},
        {"name": "Monosans SOCKS5",    "format": "plain_text", "need_filter": True,  "protocol": "socks5",
         "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"},
        {"name": "Monosans HTTP",      "format": "plain_text", "need_filter": True,  "protocol": "http",
         "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"},
        {"name": "SpeedX SOCKS5",      "format": "plain_text", "need_filter": True,  "protocol": "socks5",
         "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"},
        {"name": "SpeedX HTTP",        "format": "plain_text", "need_filter": True,  "protocol": "http",
         "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"},
        {"name": "ClarkEtM Proxy",     "format": "plain_text", "need_filter": True,  "protocol": "http",
         "url": "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"},
    ])
    return providers


# --- Parsers -------------------------------------------------------------

def _get_country(item: dict) -> str:
    geo = item.get("geolocation")
    if isinstance(geo, dict):
        c = geo.get("country", "")
        if c:
            return c
    return item.get("country", "")


def _parse_proxifly(raw: list, need_filter: bool, target_country: str) -> list[dict]:
    results = []
    tc = target_country.upper()
    for item in raw:
        if need_filter:
            country = _get_country(item)
            if tc == "EU":
                if country not in EU_COUNTRY_CODES:
                    continue
            else:
                if country != tc:
                    continue
        ip = item.get("ip", "").strip()
        if not ip:
            continue
        proxy_url = item.get("proxy", "").strip()
        if not proxy_url:
            proto = item.get("protocol", "http")
            port = item.get("port", 0)
            proxy_url = f"{proto}://{ip}:{port}"
        results.append({
            "proxy": proxy_url, "protocol": item.get("protocol", "http"),
            "ip": ip, "port": item.get("port", 0),
            "anonymity": item.get("anonymity", "unknown"),
            "api_score": item.get("score", 0),
        })
    return results


def _parse_plain_text(raw_text: str, protocol: str, need_filter: bool, target_country: str) -> list[dict]:
    results = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" in line:
            parts = line.split("://", 1)
            proto = parts[0]
            addr = parts[1]
        else:
            proto = protocol
            addr = line
        if ":" in addr:
            ip = addr.rsplit(":", 1)[0]
            try:
                port = int(addr.rsplit(":", 1)[1])
            except ValueError:
                continue
        else:
            continue
        parts_ip = ip.split(".")
        if len(parts_ip) != 4:
            continue
        try:
            if not all(0 <= int(p) <= 255 for p in parts_ip):
                continue
        except ValueError:
            continue
        results.append({
            "proxy": f"{proto}://{ip}:{port}", "protocol": proto,
            "ip": ip, "port": port, "anonymity": "unknown", "api_score": 0,
        })
    return results


def _parse_geonode(data: dict, target_country: str) -> list[dict]:
    results = []
    for item in data.get("data", []):
        ip = item.get("ip", "").strip()
        port = item.get("port", 0)
        if not ip or not port:
            continue
        proto = item.get("protocol", "http").lower().rstrip("h")
        results.append({
            "proxy": f"{proto}://{ip}:{port}", "protocol": proto,
            "ip": ip, "port": port,
            "anonymity": item.get("anonymity", "unknown"), "api_score": 0,
        })
    return results


# --- Fetching ------------------------------------------------------------

def _fetch_provider(provider: dict, target_country: str) -> list[dict]:
    name = provider["name"]
    url = provider["url"]
    fmt = provider["format"]
    need_filter = provider.get("need_filter", False)
    protocol = provider.get("protocol", "http")
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36")

    _print(f"   [FETCH] {name} ...", end=" ", flush=True)
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": ua})
        r.raise_for_status()
    except requests.RequestException as e:
        _print(f"FAILED ({type(e).__name__})")
        return []

    try:
        if fmt == "proxifly":
            raw = r.json()
            if not isinstance(raw, list) or not raw:
                _print("empty payload")
                return []
            parsed = _parse_proxifly(raw, need_filter, target_country)
            _print(f"{len(raw)} items -> {len(parsed)} candidates")
            return parsed
        elif fmt == "plain_text":
            parsed = _parse_plain_text(r.text, protocol, need_filter, target_country)
            _print(f"{len(r.text.splitlines())} lines -> {len(parsed)} candidates")
            return parsed
        elif fmt == "geonode":
            data = r.json()
            total = data.get("total", 0)
            parsed = _parse_geonode(data, target_country)
            _print(f"{total} total -> {len(parsed)} candidates")
            return parsed
        else:
            _print(f"unknown format: {fmt}")
            return []
    except (ValueError, KeyError) as e:
        _print(f"parse error: {e}")
        return []


def _fetch_raw_pool(target_country: str) -> list[dict]:
    providers = _provider_list(target_country)
    _banner(f"[POOL] Fetching proxies from {len(providers)} providers for {target_country}...")

    pool: list[dict] = []
    seen: set[str] = set()
    provider_stats = {}

    for provider in providers:
        parsed = _fetch_provider(provider, target_country)
        name = provider["name"]
        added = 0
        for p in parsed:
            ip = p.get("ip", "")
            if ip and ip not in seen:
                seen.add(ip)
                pool.append(p)
                added += 1
        provider_stats[name] = {"fetched": len(parsed), "new_unique": added}
        if added > 0:
            _print(f"          -> +{added} unique IPs from {name} (pool: {len(pool)})")

    _sub("[POOL] Aggregation summary:")
    for name, stats in provider_stats.items():
        if stats["new_unique"] > 0:
            _print(f"    {name:<25} +{stats['new_unique']:>3} unique")
    _print(f"  [POOL] Total unique candidates: {len(pool)}")

    return pool


# --- Verification ---------------------------------------------------------

def _country_matches(verified_country: str, target_country: str) -> bool:
    vc = verified_country.upper()
    tc = target_country.upper()
    if tc == "EU":
        return vc in EU_COUNTRY_CODES
    return vc == tc


def _verify_one(p: dict, timeout: int, target_url: str, success_kw: list[str], target_country: str) -> dict:
    p = dict(p)
    p.update(alive=False, country_ok=False, target_ok=False,
             ms_ip=-1, ms_tgt=-1, real_score=0, verified_country="?")

    proxies = {"http": p["proxy"], "https": p["proxy"]}
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ja,en;q=0.9"}

    try:
        t0 = time.perf_counter()
        r = requests.get(IP_CHECK_URL, proxies=proxies, timeout=timeout, headers=headers)
        ms_ip = int((time.perf_counter() - t0) * 1000)
        data = r.json()
        country = data.get("country", "?")
        p.update(alive=True, ms_ip=ms_ip, verified_country=country,
                 verified_ip=data.get("ip", p["ip"]))
        if not _country_matches(country, target_country):
            return p
        p["country_ok"] = True
    except Exception:
        return p

    try:
        t0 = time.perf_counter()
        r2 = requests.get(target_url, proxies=proxies, timeout=timeout,
                          headers=headers, allow_redirects=True)
        ms_tgt = int((time.perf_counter() - t0) * 1000)
        ok = (r2.status_code < 400) and any(kw in r2.text for kw in success_kw)
        p.update(target_ok=ok, ms_tgt=ms_tgt)
    except Exception:
        pass

    p["real_score"] = _score(p)
    return p


def _score(p: dict) -> float:
    if not p.get("country_ok"):
        return 0.0
    score = 0.0
    if p.get("target_ok"):
        score += 100
        ms = p.get("ms_tgt", 9999)
        score += max(0, 60 - ms / 100)
    else:
        ms = p.get("ms_ip", 9999)
        score += max(0, 30 - ms / 100)
    score += (3 - _ANON_RANK.get(p.get("anonymity", "unknown"), 3)) * 5
    score += (3 - _PROTO_RANK.get(p.get("protocol", "http"), 3)) * 3
    return round(score, 1)


def _verify_pool(pool: list[dict], target_url: str, success_kw: list[str], target_country: str) -> list[dict]:
    _print()
    _print(f"[VERIFY] Verifying {len(pool)} proxies ({WORKERS} threads) for {target_country}...")
    _print(_sep("-"))
    verified = []
    total = len(pool)
    country_count = 0
    country_site_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool_ex:
        fmap = {pool_ex.submit(_verify_one, p, TEST_TIMEOUT, target_url, success_kw, target_country): i
                for i, p in enumerate(pool, 1)}
        for fut in concurrent.futures.as_completed(fmap):
            idx = fmap[fut]
            r = fut.result()
            verified.append(r)
            if r["country_ok"] and r["target_ok"]:
                country_site_count += 1
                icon = f"{target_country}+site OK {r['ms_tgt']:>5}ms  score={r['real_score']}"
            elif r["country_ok"]:
                country_count += 1
                icon = f"{target_country} (site?) ({r['ms_ip']}ms)"
            elif r["alive"]:
                icon = f"[{r['verified_country']}] not {target_country}"
            else:
                icon = "dead"
            _print(f"  [{idx:>3}/{total}] {r['proxy']:<40} {icon}")
    _print()
    _print(f"[VERIFY] Results: {country_site_count} {target_country}+site, {country_count} {target_country}-only, "
           f"{total - country_site_count - country_count} other/dead")
    return verified


# --- Main flow ------------------------------------------------------------

def fetch_and_verify(target_url: str | None = None,
                     success_kw: list[str] | None = None,
                     target_country: str = "JP") -> list[dict]:
    """Fetch and verify proxies against a specific target and country.

    Args:
        target_url: URL to test proxy access against (defaults to ekaigotenshoku)
        success_kw: Keywords that must appear in target page HTML
        target_country: ISO country code or 'EU' to filter proxies
    """
    if target_url is None:
        target_url = DEFAULT_TARGET_URL
    if success_kw is None:
        success_kw = DEFAULT_SUCCESS_KW

    full_pool = _fetch_raw_pool(target_country)
    if not full_pool:
        _print(f"\n[ERROR] No proxies fetched from any provider for {target_country}. Try again later.")
        return []

    good: list[dict] = []
    tested_ips: set[str] = set()

    for level in ANONYMITY_ORDER:
        cutoff = _ANON_RANK[level]
        batch = [p for p in full_pool
                 if _ANON_RANK.get(p["anonymity"], 9) <= cutoff
                 and p["ip"] not in tested_ips]
        batch.sort(key=lambda x: (-x.get("api_score", 0),
                                  _PROTO_RANK.get(x["protocol"], 9)))
        batch = batch[:TOP_N]
        if not batch:
            continue

        _banner(f"[ROUND] Anonymity: '{level}'  ({len(batch)} candidates)")

        for p in batch:
            tested_ips.add(p["ip"])

        verified = _verify_pool(batch, target_url, success_kw, target_country)
        new_good = [v for v in verified if v["country_ok"] and v["target_ok"]]
        good.extend(new_good)
        _print(f"  [ROUND] '{level}': +{len(new_good)} {target_country} proxies accessing target "
               f"(total good: {len(good)})")

        if len(good) >= MIN_GOOD:
            _print(f"  [OK] Enough {MIN_GOOD}+ good proxies - stopping anonymity rotation.")
            break

    if not good:
        _print(f"\n  [WARN] No proxy can access target - salvaging {target_country}-alive proxies as fallback")
        untested = [p for p in full_pool if p["ip"] not in tested_ips][:TOP_N]
        if untested:
            verified = _verify_pool(untested, target_url, success_kw, target_country)
            good = [v for v in verified if v["country_ok"]]
        else:
            fallback_batch = full_pool[:TOP_N]
            verified = _verify_pool(fallback_batch, target_url, success_kw, target_country)
            good = [v for v in verified if v["country_ok"]]

    good.sort(key=lambda x: -x.get("real_score", 0))
    return good


def save(proxies: list[dict], target_url: str, target_country: str) -> None:
    now = datetime.now().isoformat()
    for p in proxies:
        p["verified_at"] = now
    cc = target_country.lower()
    if cc == "eu":
        filename = "europe_working_proxies.json"
    else:
        # Map ISO back to friendly name for filename consistency
        rev = {v.lower(): k for k, v in COUNTRY_CODES.items()}
        filename = f"{rev.get(cc, cc)}_working_proxies.json"
    working_file = Path(filename)
    out = {
        "updated_at": now,
        "source": "multi-provider (Proxifly + ProxyScrape + GeoNode + Monosans + SpeedX + ClarkEtM)",
        "target": target_url,
        "country": target_country,
        "count": len(proxies),
        "proxies": proxies,
    }
    working_file.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    _print(f"\n  [SAVE] {working_file}  ({len(proxies)} {target_country} proxies)")


if __name__ == "__main__":
    target_url, success_kw, label, country = _load_target_from_args()

    _banner(f"Multi-Country Proxy Fetcher v5 - {datetime.now():%Y-%m-%d %H:%M}")
    _print(f"  Target:  {label}")
    _print(f"  Country: {country}")
    _print(f"  Sources: dynamic provider list")

    good = fetch_and_verify(target_url=target_url, success_kw=success_kw, target_country=country)

    if not good:
        _print(f"\n[ERROR] Could not get any live {country} proxies. Try again in a few minutes.")
        raise SystemExit(1)

    _banner(f"{len(good)} verified {country} proxies (sorted by real score)")
    for i, p in enumerate(good[:15], 1):
        tgt = "site:OK" if p["target_ok"] else "site:?"
        _print(f"  {i:>2}. {p['proxy']:<40} score={p['real_score']:>5}  "
               f"{tgt}  {p.get('ms_tgt', p['ms_ip'])}ms  {p['anonymity']}")
    save(good, target_url=target_url, target_country=country)
    _print(f"  [NEXT] python proxy/checker.py --country {country.lower()}  or  python main.py")
