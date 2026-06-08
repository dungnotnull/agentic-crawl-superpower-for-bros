"""Proxy Fetcher v5.2 - Streaming concurrent verification with HTML scraping support."""
from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import sys
import threading
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    import requests
except ImportError as _exc:
    raise SystemExit("requests is required: pip install requests") from _exc

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import socks
    _HAS_PYSOCKS = True
except ImportError:
    _HAS_PYSOCKS = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

DEFAULT_MIN_GOOD = 4
DEFAULT_VERIFY_WORKERS = min(32, max(10, (os.cpu_count() or 4) * 3))
DEFAULT_FETCH_TIMEOUT = 20
DEFAULT_VERIFY_TIMEOUT_GEO = 10
DEFAULT_VERIFY_TIMEOUT_TGT = 15
DEFAULT_TOP_N_PER_SOURCE = 100
DEFAULT_PROGRESSIVE_FLUSH = 5

IPINFO_URL = "https://ipinfo.io/json"
IPAPI_URL = "http://ip-api.com/json/"

COUNTRY_CODES = {
    "vietnam": "VN", "japan": "JP", "china": "CN",
    "south korea": "KR", "singapore": "SG", "russia": "RU",
    "europe": "EU", "india": "IN", "usa": "US",
}

EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE", "GB", "NO", "CH",
    "UA", "IS", "LI",
}

_ANON_RANK = {"elite": 0, "anonymous": 1, "transparent": 2, "unknown": 3}
_PROTO_RANK = {"socks5": 0, "socks4": 1, "https": 2, "http": 3}


@dataclass
class Source:
    name: str
    url: str
    parser: Callable[[Any, str], list[dict]]
    headers: dict = field(default_factory=dict)
    timeout: int = DEFAULT_FETCH_TIMEOUT


@dataclass
class SourceStats:
    fetched: int = 0
    alive: int = 0
    country_match: int = 0
    target_reachable: int = 0
    target_ok: int = 0


def _parse_proxifly_json(raw: Any, source_name: str) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ip = (item.get("ip") or "").strip()
        if not ip:
            continue
        proxy_url = (item.get("proxy") or "").strip()
        if not proxy_url:
            proto = item.get("protocol", "http")
            port = item.get("port", 0)
            if port:
                proxy_url = f"{proto}://{ip}:{port}"
            else:
                continue
        geo = item.get("geolocation")
        country = ""
        if isinstance(geo, dict):
            country = geo.get("country", "")
        if not country:
            country = item.get("country", "")
        out.append({
            "proxy": proxy_url,
            "protocol": item.get("protocol", "http"),
            "ip": ip,
            "port": item.get("port", 0),
            "anonymity": item.get("anonymity", "unknown"),
            "api_score": item.get("score", 0),
            "source": source_name,
            "source_country_hint": country,
        })
    return out


def _parse_proxyscrape_text(text: str, source_name: str) -> list[dict]:
    out = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(https?|socks4|socks5)://(\d+\.\d+\.\d+\.\d+):(\d+)$", line)
        if m:
            proto, ip, port = m.group(1), m.group(2), int(m.group(3))
            out.append({
                "proxy": f"{proto}://{ip}:{port}",
                "protocol": proto,
                "ip": ip,
                "port": port,
                "anonymity": "unknown",
                "api_score": 0,
                "source": source_name,
                "source_country_hint": "",
            })
            continue
        m2 = re.match(r"^(\d+\.\d+\.\d+\.\d+):(\d+)", line)
        if m2:
            ip, port = m2.group(1), int(m2.group(2))
            out.append({
                "proxy": f"http://{ip}:{port}",
                "protocol": "http",
                "ip": ip,
                "port": port,
                "anonymity": "unknown",
                "api_score": 0,
                "source": source_name,
                "source_country_hint": "",
            })
    return out


def _parse_geonode_json(raw: Any, source_name: str) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    data = raw.get("data", [])
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ip = (item.get("ip") or "").strip()
        port_raw = item.get("port", 0)
        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            continue
        if not ip or not port:
            continue
        protocols = item.get("protocols", [])
        if isinstance(protocols, str):
            protocols = [protocols]
        proto = protocols[0] if protocols else "http"
        proxy_url = f"{proto}://{ip}:{port}"
        out.append({
            "proxy": proxy_url,
            "protocol": proto,
            "ip": ip,
            "port": port,
            "anonymity": item.get("anonymityLevel", "unknown"),
            "api_score": 0,
            "source": source_name,
            "source_country_hint": item.get("country", ""),
        })
    return out


def _parse_proxylistdownload_text(text: str, source_name: str, default_proto: str = "http") -> list[dict]:
    out = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+):(\d+)$", line)
        if m:
            ip, port = m.group(1), int(m.group(2))
            out.append({
                "proxy": f"{default_proto}://{ip}:{port}",
                "protocol": default_proto,
                "ip": ip,
                "port": port,
                "anonymity": "unknown",
                "api_score": 0,
                "source": source_name,
                "source_country_hint": "",
            })
    return out


def _decode_base64_ip(text: str) -> str | None:
    try:
        decoded = base64.b64decode(text).decode("utf-8")
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", decoded):
            return decoded
    except Exception:
        pass
    return None





def _parse_freeproxycz_html(html: str, source_name: str) -> list[dict]:
    if not _HAS_BS4:
        print(f"  [WARN] beautifulsoup4 required for {source_name}: pip install beautifulsoup4")
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for row in soup.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        ip = ""
        port = 0
        for td in tds:
            txt = td.get_text(strip=True)
            if not ip:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", txt)
                if m:
                    ip = m.group(1)
            if not port:
                if re.match(r"^\d+$", txt):
                    p = int(txt)
                    if 1 <= p <= 65535:
                        port = p
        if ip and port:
            out.append({
                "proxy": f"http://{ip}:{port}",
                "protocol": "http",
                "ip": ip,
                "port": port,
                "anonymity": "unknown",
                "api_score": 0,
                "source": source_name,
                "source_country_hint": "",
            })
    return out


def _parse_databay_html(html: str, source_name: str) -> list[dict]:
    if not _HAS_BS4:
        print(f"  [WARN] beautifulsoup4 required for {source_name}: pip install beautifulsoup4")
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    tables = soup.find_all("table")
    for table in tables:
        header_row = table.find("tr")
        if not header_row:
            continue
        header = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        if "ip address" not in header:
            continue
        ip_idx = header.index("ip address")
        port_idx = header.index("port") if "port" in header else 1
        proto_idx = header.index("protocol") if "protocol" in header else 3
        for row in table.find_all("tr")[1:]:
            tds = row.find_all("td")
            if len(tds) <= max(ip_idx, port_idx, proto_idx):
                continue
            ip_text = tds[ip_idx].get_text(strip=True)
            port_text = tds[port_idx].get_text(strip=True)
            proto_text = tds[proto_idx].get_text(strip=True).lower()
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)", ip_text)
            if not m:
                continue
            ip = m.group(1)
            try:
                port = int(port_text)
            except (ValueError, TypeError):
                continue
            if not (1 <= port <= 65535):
                continue
            if "socks5" in proto_text:
                proto = "socks5"
            elif "socks4" in proto_text:
                proto = "socks4"
            elif "https" in proto_text or "http/s" in proto_text:
                proto = "https"
            elif "http" in proto_text:
                proto = "http"
            else:
                proto = "http"
            out.append({
                "proxy": f"{proto}://{ip}:{port}",
                "protocol": proto,
                "ip": ip,
                "port": port,
                "anonymity": "unknown",
                "api_score": 0,
                "source": source_name,
                "source_country_hint": "",
            })
    return out

def _parse_proxynova_html(html: str, source_name: str) -> list[dict]:
    if not _HAS_BS4:
        print(f"  [WARN] beautifulsoup4 required for {source_name}: pip install beautifulsoup4")
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    table = soup.find("table", {"id": "tbl_proxy_list"})
    if not table:
        table = soup.find("table")
    if not table:
        return []
    for row in table.find_all("tr")[1:]:
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        port_text = tds[1].get_text(strip=True)
        scripts = tds[0].find_all("script")
        ip = None
        for s in scripts:
            if s.string:
                ip = _eval_proxynova_js(s.string.strip())
                if ip and re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                    break
        if not ip:
            raw = tds[0].get_text(strip=True)
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)", raw)
            if m:
                ip = m.group(1)
        if not ip:
            continue
        try:
            port = int(port_text)
        except (ValueError, TypeError):
            continue
        if not (1 <= port <= 65535):
            continue
        out.append({
            "proxy": f"http://{ip}:{port}",
            "protocol": "http",
            "ip": ip,
            "port": port,
            "anonymity": "unknown",
            "api_score": 0,
            "source": source_name,
            "source_country_hint": "",
        })
    return out


def _extract_balanced(text: str, start_idx: int):
    if start_idx >= len(text) or text[start_idx] != "(":
        return None, start_idx
    depth = 1
    i = start_idx + 1
    while i < len(text) and depth > 0:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    if depth == 0:
        return text[start_idx+1:i-1], i
    return None, start_idx


def _eval_proxynova_js(js_expr: str) -> str | None:
    m = re.search(r"document\.write\s*\((.+)\)", js_expr)
    if not m:
        return None
    expr = m.group(1)

    def _eval_expr(e: str):
        e = e.strip()
        lit = re.match(r'^(".+"|\'.+\')$', e)
        if lit:
            s = lit.group(1)
            return s[1:-1]
        m2 = re.match(r'^atob\s*\(\s*"([A-Za-z0-9+/=]+)"\s*\)$', e)
        if not m2:
            m2 = re.match(r"^atob\s*\(\s*'([A-Za-z0-9+/=]+)'\s*\)$", e)
        if m2:
            try:
                return base64.b64decode(m2.group(1)).decode("utf-8")
            except Exception:
                return None
        m3 = re.match(r'^\[(\d+(?:,\s*\d+)*)\]\.map\s*\((.+?)\)\.join\s*\(\s*"\s*"\s*\)$', e)
        if not m3:
            m3 = re.match(r"^\[(\d+(?:,\s*\d+)*)\]\.map\s*\((.+?)\)\.join\s*\(\s*'\s*'\s*\)$", e)
        if m3:
            codes = [int(x.strip()) for x in m3.group(1).split(",")]
            m_off = re.search(r'String\.fromCharCode\s*\(\s*\w+\s*-\s*(\d+)\s*\)', m3.group(2))
            if m_off:
                offset = int(m_off.group(1))
                return "".join(chr(c - offset) for c in codes)
            return None
        return None

    def _apply_chain(value: str, rest: str):
        if not rest or not value:
            return value
        rest = rest.strip()
        if not rest:
            return value
        if rest.startswith(".substring"):
            inner, next_idx = _extract_balanced(rest, len(".substring"))
            if inner is None:
                return None
            parts = [p.strip() for p in inner.split(",")]
            try:
                a = eval(parts[0], {"__builtins__": {}})
                b = eval(parts[1], {"__builtins__": {}}) if len(parts) > 1 else None
                result = value[a:b] if b is not None else value[a:]
                return _apply_chain(result, rest[next_idx:])
            except Exception:
                return None
        if rest.startswith(".concat"):
            inner, next_idx = _extract_balanced(rest, len(".concat"))
            if inner is None:
                return None
            arg = _eval_full(inner)
            if arg is None:
                return None
            return _apply_chain(value + arg, rest[next_idx:])
        if rest.startswith(".split"):
            expected = '.split("").reverse().join("")'
            if rest.startswith(expected):
                return _apply_chain(value[::-1], rest[len(expected):])
            return None
        if rest.startswith(".repeat"):
            inner, next_idx = _extract_balanced(rest, len(".repeat"))
            if inner is None:
                return None
            try:
                n = int(inner.strip())
                return _apply_chain(value * n, rest[next_idx:])
            except Exception:
                return None
        return value if not rest else None

    def _eval_full(e: str):
        e = e.strip()
        direct = _eval_expr(e)
        if direct is not None:
            return direct
        m = re.match(r'^("[^"]*"|\'[^\']*\')(.+)$', e)
        if m:
            base = _eval_expr(m.group(1))
            rest = m.group(2)
            return _apply_chain(base, rest)
        m = re.match(r'^(atob\s*\([^)]+\))(.+)$', e)
        if m:
            base = _eval_expr(m.group(1))
            rest = m.group(2)
            return _apply_chain(base, rest)
        m = re.match(r'^(\[\d+(?:,\s*\d+)*\]\.map\s*\(.+?\)\.join\s*\(\s*"\s*"\s*\))(.+)$', e)
        if not m:
            m = re.match(r"^(\[\d+(?:,\s*\d+)*\]\.map\s*\(.+?\)\.join\s*\(\s*'\s*'\s*\))(.+)$", e)
        if m:
            base = _eval_expr(m.group(1))
            rest = m.group(2)
            return _apply_chain(base, rest)
        return None

    return _eval_full(expr)


def _build_sources(target_country: str) -> list[Source]:
    cdn = "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies"
    cc = target_country.upper()
    sources: list[Source] = []

    sources.append(Source(
        name="proxifly_jp",
        url=f"{cdn}/countries/JP/data.json",
        parser=lambda raw, name: _parse_proxifly_json(raw, name),
    ))

    sources.append(Source(
        name="proxyscrape_jp",
        url=(
            "https://api.proxyscrape.com/v4/free-proxy-list/get"
            f"?request=display_proxies&proxy_format=protocolipport"
            f"&format=text&country={cc.lower()}"
        ),
        parser=lambda raw, name: _parse_proxyscrape_text(raw, name),
    ))

    sources.append(Source(
        name="geonode_jp",
        url=(
            "https://proxylist.geonode.com/api/proxy-list"
            f"?country={cc}&limit=300"
            f"&sort_by=lastChecked&sort_type=desc"
        ),
        parser=lambda raw, name: _parse_geonode_json(raw, name),
    ))

    # sources.append(Source(
    #     name="proxylistdownload_http_jp",
    #     url=f"https://www.proxy-list.download/api/v1/get?type=http&country={cc}",
    #     parser=lambda raw, name: _parse_proxylistdownload_text(raw, name, default_proto="http"),
    # ))

    # sources.append(Source(
    #     name="proxylistdownload_socks5_jp",
    #     url=f"https://www.proxy-list.download/api/v1/get?type=socks5&country={cc}",
    #     parser=lambda raw, name: _parse_proxylistdownload_text(raw, name, default_proto="socks5"),
    # ))

    sources.append(Source(
        name="proxynova_jp",
        url=f"https://www.proxynova.com/proxy-server-list/country-{cc.lower()}/",
        parser=lambda raw, name: _parse_proxynova_html(raw, name),
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    ))

    sources.append(Source(
        name="spysone_txt",
        url="http://spys.me/proxy.txt",
        parser=lambda raw, name: _parse_proxyscrape_text(raw, name),
    ))

    sources.append(Source(
        name='databay_jp',
        url=f'https://databay.com/free-proxy-list/{cc.lower()}',
        parser=lambda raw, name: _parse_databay_html(raw, name),
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
    ))

    return sources


def _fetch_one_source(src: Source, q: queue.Queue, stats: SourceStats,
                      stop_event: threading.Event, top_n: int) -> None:
    if stop_event.is_set():
        return
    print(f"  [FETCH] {src.name} ...", end=" ", flush=True)
    try:
        r = requests.get(
            src.url, timeout=src.timeout,
            headers={"User-Agent": "Mozilla/5.0", **src.headers}
        )
        r.raise_for_status()
    except Exception as exc:
        print(f"x fetch error: {exc}")
        return
    ct = r.headers.get("Content-Type", "").lower()
    if "json" in ct or src.url.endswith(".json"):
        try:
            raw = r.json()
        except Exception as exc:
            print(f"x JSON parse error: {exc}")
            return
        proxies = src.parser(raw, src.name)
    else:
        proxies = src.parser(r.text, src.name)
    if not proxies:
        print(f"v 0 proxies")
        return
    seen: set[str] = set()
    deduped = []
    for p in proxies:
        ip = p.get("ip", "")
        if ip and ip in seen:
            continue
        if ip:
            seen.add(ip)
        deduped.append(p)
        if len(deduped) >= top_n:
            break
    print(f"v {len(deduped)} proxies")
    stats.fetched += len(deduped)
    for p in deduped:
        if stop_event.is_set():
            break
        q.put(p)


def _country_matches(verified_country: str, target_country: str) -> bool:
    vc = verified_country.upper()
    tc = target_country.upper()
    if tc == "EU":
        return vc in EU_COUNTRY_CODES
    return vc == tc


def _request_with_ssl_fallback(url: str, proxies: dict, timeout: int,
                                headers: dict, allow_redirects: bool = False):
    t0 = time.perf_counter()
    used_verify_false = False
    try:
        r = requests.get(
            url, proxies=proxies, timeout=timeout,
            headers=headers, allow_redirects=allow_redirects, verify=True,
        )
    except requests.exceptions.SSLError:
        r = requests.get(
            url, proxies=proxies, timeout=timeout,
            headers=headers, allow_redirects=allow_redirects, verify=False,
        )
        used_verify_false = True
    ms = int((time.perf_counter() - t0) * 1000)
    return r, ms, used_verify_false


def _verify_one(proxy_info: dict, target_url: str, success_kw: list[str],
                target_country: str, timeout_geo: int,
                timeout_tgt: int) -> dict:
    result = dict(proxy_info)
    result.update(
        alive=False, country_match=False, target_reachable=False,
        target_ok=False, ms_ip=-1, ms_tgt=-1, real_score=0.0,
        verified_country="?", verified_ip="?", geo_verified=False,
        ssl_bypass=False, error="",
    )
    proxy_url = result["proxy"]
    proxies = {"http": proxy_url, "https": proxy_url}
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ja,en;q=0.9"}

    if proxy_url.startswith(("socks4://", "socks5://")) and not _HAS_PYSOCKS:
        result["error"] = "pysocks_missing"
        return result

    geo_ok = False
    for geo_url in (IPAPI_URL, IPINFO_URL):
        try:
            r, ms, ssl_bypass = _request_with_ssl_fallback(
                geo_url, proxies, timeout_geo, headers,
            )
            if r.status_code == 200:
                data = r.json()
                country = data.get("country", "") or data.get("countryCode", "?")
                ip = data.get("ip") or data.get("query", "?")
                result.update(
                    alive=True, ms_ip=ms, verified_country=country,
                    verified_ip=ip, geo_verified=True,
                )
                if ssl_bypass:
                    result["ssl_bypass"] = True
                geo_ok = True
                break
        except requests.exceptions.InvalidSchema:
            result["error"] = "invalid_schema"
            return result
        except Exception as e:
            result["error"] = str(type(e).__name__)

    target_direct_ok = False
    if not geo_ok:
        for verify in (True, False):
            try:
                t0 = time.perf_counter()
                r = requests.get(
                    target_url, proxies=proxies, timeout=timeout_tgt,
                    headers=headers, allow_redirects=True, verify=verify,
                )
                ms = int((time.perf_counter() - t0) * 1000)
                if r.status_code < 400 and len(r.text) > 100:
                    result.update(
                        alive=True, ms_tgt=ms, target_reachable=True,
                        verified_ip=result.get("ip", "?"),
                    )
                    if not verify:
                        result["ssl_bypass"] = True
                    if any(kw in r.text for kw in success_kw):
                        result["target_ok"] = True
                    target_direct_ok = True
                    break
            except requests.exceptions.SSLError:
                if verify:
                    continue
                break
            except Exception:
                break
        if target_direct_ok:
            result["country_match"] = True
            result["verified_country"] = target_country
            result["geo_verified"] = False
            result["error"] = ""

    if not geo_ok and not target_direct_ok:
        return result

    if geo_ok:
        if _country_matches(result["verified_country"], target_country):
            result["country_match"] = True
        else:
            result["country_match"] = False
            return result
        try:
            r2, ms2, ssl_bypass2 = _request_with_ssl_fallback(
                target_url, proxies, timeout_tgt, headers,
                allow_redirects=True,
            )
            result["ms_tgt"] = ms2
            if ssl_bypass2:
                result["ssl_bypass"] = True
            body_len = len(r2.text)
            if r2.status_code < 400 and body_len > 100:
                result["target_reachable"] = True
                if any(kw in r2.text for kw in success_kw):
                    result["target_ok"] = True
        except Exception:
            pass

    result["real_score"] = _score(result)
    return result


def _score(p: dict) -> float:
    if not p.get("country_match"):
        return 0.0
    score = 0.0
    score += 20.0
    if p.get("geo_verified"):
        score += 10.0
    if p.get("target_ok"):
        score += 100.0
        ms = p.get("ms_tgt", 9999)
        score += max(0, 60 - ms / 80)
    elif p.get("target_reachable"):
        score += 50.0
        ms = p.get("ms_tgt", 9999)
        if ms > 0:
            score += max(0, 30 - ms / 100)
    else:
        ms = p.get("ms_ip", 9999)
        score += max(0, 15 - ms / 150)
    if p.get("ssl_bypass"):
        score *= 0.85
    anon = p.get("anonymity", "unknown")
    score += (3 - _ANON_RANK.get(anon, 3)) * 5
    proto = p.get("protocol", "http")
    score += (3 - _PROTO_RANK.get(proto, 3)) * 3
    api = p.get("api_score", 0)
    if api:
        score += min(api, 20)
    return round(score, 1)


class ResultAggregator:
    def __init__(self, target_country: str, working_file: Path,
                 target_url: str, flush_every: int):
        self.target_country = target_country
        self.working_file = working_file
        self.target_url = target_url
        self.flush_every = flush_every
        self.lock = threading.Lock()
        self.verified: list[dict] = []
        self.seen_ips: set[str] = set()
        self.good_count = 0
        self.stats: dict[str, SourceStats] = {}
        self._flush_counter = 0

    def add(self, result: dict) -> bool:
        with self.lock:
            src = result.get("source", "unknown")
            if src not in self.stats:
                self.stats[src] = SourceStats()
            st = self.stats[src]
            st.fetched += 1
            if result.get("alive"):
                st.alive += 1
            if result.get("country_match"):
                st.country_match += 1
            if result.get("target_reachable"):
                st.target_reachable += 1
            if result.get("target_ok"):
                st.target_ok += 1
            ip = result.get("verified_ip") or result.get("ip", "")
            if ip in self.seen_ips:
                return False
            if ip:
                self.seen_ips.add(ip)
            self.verified.append(result)
            if result.get("country_match"):
                self.good_count += 1
                self._flush_counter += 1
                if self._flush_counter >= self.flush_every:
                    self._flush_counter = 0
                    self._save_now()
            return True

    def _save_now(self) -> None:
        self._write(self.verified)

    def save(self) -> None:
        sorted_proxies = sorted(self.verified, key=lambda x: -x.get("real_score", 0))
        self._write(sorted_proxies)

    def _write(self, proxies: list[dict]) -> None:
        now = datetime.now().isoformat()
        for p in proxies:
            p["verified_at"] = now
        out = {
            "updated_at": now,
            "country": self.target_country.upper(),
            "target": self.target_url,
            "count": len(proxies),
            "proxies": proxies,
        }
        tmp = self.working_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.working_file)
        except Exception as exc:
            print(f"  [WARN] Flush failed: {exc}")

    def summary(self) -> str:
        ok = [p for p in self.verified if p.get("target_ok")]
        reachable = [p for p in self.verified if p.get("target_reachable") and not p.get("target_ok")]
        geo_only = [p for p in self.verified if p.get("country_match") and not p.get("target_reachable")]
        dead = [p for p in self.verified if not p.get("alive")]
        unverified = [p for p in self.verified if p.get("alive") and not p.get("geo_verified") and p.get("country_match")]
        lines = [
            f"  Results:",
            f"     {self.target_country.upper()} + target_ok      : {len(ok)}",
            f"     {self.target_country.upper()} + reachable    : {len(reachable)}",
            f"     {self.target_country.upper()} + geo-only     : {len(geo_only)}",
            f"     Geo-unverified (target OK) : {len(unverified)}",
            f"     Dead / wrong country : {len(dead)}",
        ]
        if ok:
            best = min(ok, key=lambda x: x.get("ms_tgt", 9999))
            lines.append(f"\n  Fastest proxy: {best['proxy']}  ->  {best['ms_tgt']}ms")
        return "\n".join(lines)

    def source_report(self) -> str:
        lines = ["  Source reliability:", "  " + "-" * 55]
        for name, st in sorted(self.stats.items()):
            alive_pct = (st.alive / max(st.fetched, 1)) * 100
            match_pct = (st.country_match / max(st.fetched, 1)) * 100
            ok_pct = (st.target_ok / max(st.fetched, 1)) * 100
            lines.append(
                f"    {name:<25}  fetched={st.fetched:>4}  "
                f"alive={alive_pct:>5.1f}%  match={match_pct:>5.1f}%  "
                f"target_ok={ok_pct:>5.1f}%"
            )
        return "\n".join(lines)


def _load_site_args(site_name: str | None) -> tuple[str, list[str]]:
    target_url = "https://www.ekaigotenshoku.com/kyujin/list?z01=1"
    success_kw = ["求人", "介護", "給与", "勤務地", "施設", "募集", "正社員"]
    if not site_name:
        return target_url, success_kw
    try:
        v2_dir = Path(__file__).parent.parent.resolve()
        if str(v2_dir) not in sys.path:
            sys.path.insert(0, str(v2_dir))
        from site_mappings import load_site_mapping
        mapping = load_site_mapping(site_name)
        target_url = mapping.url.listing_url
        success_kw = mapping.success_keywords
        print(f"  [SITE] {mapping.display_name}: {target_url}")
    except Exception as exc:
        print(f"  [WARN] Failed to load site '{site_name}': {exc}")
    return target_url, success_kw


def _country_to_file(country: str) -> Path:
    cc = country.strip().lower()
    if cc == "eu" or cc == "europe":
        return Path("europe_working_proxies.json")
    mapping = {
        "vietnam": "vietnam_working_proxies.json",
        "japan": "japan_working_proxies.json",
        "china": "china_working_proxies.json",
        "south korea": "south_korea_working_proxies.json",
        "singapore": "singapore_working_proxies.json",
        "russia": "russia_working_proxies.json",
        "india": "india_working_proxies.json",
        "usa": "usa_working_proxies.json",
    }
    return Path(mapping.get(cc, f"{cc}_working_proxies.json"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream-fetch and verify proxies with immediate checking."
    )
    parser.add_argument("--country", default="japan", help="Target country (default: japan)")
    parser.add_argument("--site", default="", help="Site name for target URL / keywords")
    parser.add_argument("--min-good", type=int, default=DEFAULT_MIN_GOOD,
                        help=f"Stop early after N good proxies (default {DEFAULT_MIN_GOOD})")
    parser.add_argument("--workers", type=int, default=DEFAULT_VERIFY_WORKERS,
                        help=f"Verification worker threads (default {DEFAULT_VERIFY_WORKERS})")
    parser.add_argument("--timeout-geo", type=int, default=DEFAULT_VERIFY_TIMEOUT_GEO)
    parser.add_argument("--timeout-tgt", type=int, default=DEFAULT_VERIFY_TIMEOUT_TGT)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N_PER_SOURCE,
                        help="Max proxies to take from each raw source")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output JSON file (default: derived from --country)")
    args = parser.parse_args()

    target_country = COUNTRY_CODES.get(args.country.lower(), args.country.upper())
    working_file = args.output or _country_to_file(args.country)
    target_url, success_kw = _load_site_args(args.site or None)

    print("=" * 72)
    print(f"  Proxy Fetcher v5.2 - Robust SSL/geo + HTML scraping")
    print(f"  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Country : {target_country}")
    print(f"  Target  : {target_url}")
    print(f"  Output  : {working_file}")
    print(f"  Workers : {args.workers} verify threads")
    if not _HAS_PYSOCKS:
        print(f"  [WARN] PySocks not installed - SOCKS proxies will be skipped")
    if not _HAS_BS4:
        print(f"  [WARN] beautifulsoup4 not installed - HTML scrapers disabled")
    print("=" * 72 + "\n")

    sources = _build_sources(target_country)
    if not sources:
        print("[ERROR] No sources configured.")
        raise SystemExit(1)

    q: queue.Queue[dict] = queue.Queue(maxsize=500)
    stop_event = threading.Event()
    agg = ResultAggregator(
        target_country=target_country,
        working_file=working_file,
        target_url=target_url,
        flush_every=DEFAULT_PROGRESSIVE_FLUSH,
    )

    producer_threads = []
    source_stats_map: dict[str, SourceStats] = {}
    for src in sources:
        st = SourceStats()
        source_stats_map[src.name] = st
        t = threading.Thread(
            target=_fetch_one_source,
            args=(src, q, st, stop_event, args.top_n),
            daemon=True,
        )
        t.start()
        producer_threads.append(t)

    print(f"[VERIFY] Starting {args.workers} verification workers ...\n")
    submitted = 0
    completed = 0
    good_target_ok = 0
    lock = threading.Lock()

    def on_done(fut):
        nonlocal completed, good_target_ok
        try:
            result = fut.result()
        except Exception as exc:
            print(f"  [WARN] Verification crashed: {exc}")
            with lock:
                completed += 1
            return
        agg.add(result)
        with lock:
            completed += 1
            if result.get("target_ok"):
                good_target_ok += 1
        if result.get("target_ok"):
            print(f"  OK {result['proxy']:<40}  target_ok  {result['ms_tgt']}ms  score={result['real_score']}")
        elif result.get("country_match"):
            status = "reachable" if result.get("target_reachable") else "geo-only"
            note = " [ssl_bypass]" if result.get("ssl_bypass") else ""
            print(f"  .. {result['proxy']:<40}  {status:<10} {result.get('ms_tgt', result['ms_ip'])}ms  score={result['real_score']}{note}")

    with ThreadPoolExecutor(max_workers=args.workers) as verify_pool:
        producer_alive = True
        while producer_alive or not q.empty():
            with lock:
                if good_target_ok >= args.min_good and not stop_event.is_set():
                    print(f"\n[EARLY STOP] {good_target_ok} target_ok proxies reached. "
                          f"Signalling producers to stop ...")
                    stop_event.set()
            try:
                proxy_info = q.get(timeout=0.5)
            except queue.Empty:
                producer_alive = any(t.is_alive() for t in producer_threads)
                continue
            fut = verify_pool.submit(
                _verify_one, proxy_info, target_url, success_kw,
                target_country, args.timeout_geo, args.timeout_tgt,
            )
            fut.add_done_callback(on_done)
            submitted += 1
        print(f"\n[VERIFY] Draining remaining verification tasks ...")

    agg.save()

    for name, st in source_stats_map.items():
        if name not in agg.stats:
            agg.stats[name] = st

    print("\n" + "=" * 72)
    print(agg.summary())
    print()
    print(agg.source_report())
    print("=" * 72)

    total_verified = len(agg.verified)
    total_good = sum(1 for p in agg.verified if p.get("target_ok"))
    total_reachable = sum(1 for p in agg.verified if p.get("target_reachable"))
    total_geo_only = sum(1 for p in agg.verified if p.get("country_match") and not p.get("target_reachable"))
    if total_good == 0 and total_reachable == 0 and total_geo_only == 0:
        print(f"\n  [ERROR] No working {target_country} proxies found.")
        try:
            empty_data = {
                "updated_at": datetime.now().isoformat(),
                "empty_fetch": True,
                "retry_after": (datetime.now() + timedelta(minutes=3)).isoformat(),
                "country": target_country,
                "proxies": [],
            }
            working_file.write_text(json.dumps(empty_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        raise SystemExit(1)

    print(f"\n  Saved {total_verified} verified proxies to {working_file}")
    print(f"     -> {total_good} target_ok  |  {total_reachable} reachable  |  ready to crawl")
    print("=" * 72)


if __name__ == "__main__":
    main()
