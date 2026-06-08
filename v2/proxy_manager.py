"""
Proxy Manager - loads, validates, and refreshes proxy lists.

If no proxies are available, the manager signals this to the crawl engine,
which will WAIT and keep searching rather than terminating.

Now supports:
  - Country-specific proxy caches (japan_working_proxies.json, usa_working_proxies.json, etc.)
  - No-proxy mode (returns ["direct://"] so the engine runs without proxies)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .config import CrawlConfig
except ImportError:
    from config import CrawlConfig  # type: ignore[no-redef]


class ProxyManager:
    """Manages proxy loading, cache validation, and refresh."""

    def __init__(self, config: CrawlConfig, site_name: str = "",
                 tracker: Any = None):
        self.config = config
        self.site_name = site_name
        self.tracker = tracker

    def _cache_is_stale(self, data: dict) -> bool:
        """Check if the proxy cache has exceeded its TTL.
        Respects empty_fetch cooldown — won't refetch before retry_after."""
        if data.get("empty_fetch"):
            retry_raw = data.get("retry_after")
            if retry_raw:
                try:
                    retry_at = datetime.fromisoformat(retry_raw)
                    if datetime.now() < retry_at:
                        remaining = int((retry_at - datetime.now()).total_seconds() / 60)
                        print(f"  [PROXY] Empty-fetch cooldown active ({remaining} min remaining) — skipping refetch")
                        return False
                    print(f"  [PROXY] Empty-fetch cooldown expired — allowing refetch")
                except Exception:
                    pass
        updated_raw = data.get("updated_at")
        if not updated_raw:
            return True
        try:
            age = datetime.now() - datetime.fromisoformat(updated_raw)
            is_stale = age > self.config.proxy_cache_ttl
            if is_stale:
                mins = int(age.total_seconds() / 60)
                ttl_mins = int(self.config.proxy_cache_ttl.total_seconds() / 60)
                print(f"  [PROXY] Cache is {mins} min old (TTL: {ttl_mins} min) - stale")
            return is_stale
        except Exception:
            return True

    def _refetch(self) -> None:
        """Run the proxy fetch script to refresh the cache."""
        site_arg = ["--site", self.site_name] if self.site_name else []
        country_arg = ["--country", self.config.proxy_country] if self.config.proxy_country else []
        cmd = [sys.executable, self.config.proxy_fetch_script] + site_arg + country_arg
        print(f"  [PROXY] Fetching fresh proxies from multiple providers...")
        if self.site_name:
            print(f"  [PROXY] Site: {self.site_name}")
        if self.config.proxy_country:
            print(f"  [PROXY] Country: {self.config.proxy_country}")
        print(f"  [PROXY] Running {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=True)
            print(f"  [PROXY] Proxy fetch completed")
        except Exception as e:
            print(f"  [WARN] Proxy re-fetch failed: {e}")

    def _is_empty_fetch_cooldown(self) -> bool:
        """Check whether an empty-fetch cooldown is active on the cache file."""
        working_file = self.config.proxy_working_file
        if not working_file.exists():
            return False
        try:
            data = json.loads(working_file.read_text(encoding="utf-8"))
            if data.get("empty_fetch"):
                retry_raw = data.get("retry_after")
                if retry_raw:
                    retry_at = datetime.fromisoformat(retry_raw)
                    if datetime.now() < retry_at:
                        remaining = int((retry_at - datetime.now()).total_seconds() / 60)
                        print(f"  [PROXY] Empty-fetch cooldown active ({remaining} min remaining) — skipping refetch")
                        return True
        except Exception:
            pass
        return False

    def load_proxies(self, allow_refetch: bool = True) -> list[str]:
        """Load proxies sorted by real_score (best first).

        Returns ["direct://"] when use_proxy is False so the crawl engine
        runs a single local session.
        Returns empty list if no proxies available (engine will wait).
        """
        # No-proxy mode: bypass proxy layer entirely
        if not self.config.use_proxy:
            print("  [PROXY] Proxy layer disabled (No need proxy)")
            return ["direct://"]

        working_file = self.config.proxy_working_file
        if working_file.exists():
            try:
                data = json.loads(working_file.read_text(encoding="utf-8"))
                if allow_refetch and self._cache_is_stale(data):
                    self._refetch()
                    return self.load_proxies(allow_refetch=False)
                raw = data.get("proxies", [])
                raw.sort(key=lambda x: -x.get("real_score", 0))
                target_ok = [p for p in raw if p.get("proxy") and p.get("target_ok")]
                fallback = [p for p in raw if p.get("proxy") and not p.get("target_ok")]
                ordered = target_ok + fallback
                proxies = [p["proxy"] for p in ordered]
                if proxies:
                    top_score = raw[0].get("real_score", "?")
                    country = data.get("country", self.config.proxy_country.upper())
                    site_ok = sum(1 for p in raw if p.get("target_ok"))
                    print(f"  [PROXY] Loaded {len(proxies)} proxies "
                          f"({country}: {len(raw)}, site-OK: {site_ok}, "
                          f"top score: {top_score})")

                    # Seed tracker with base scores from fetcher
                    if self.tracker:
                        for p in raw:
                            proxy_url = p.get("proxy", "")
                            if proxy_url:
                                base = p.get("real_score", 50.0)
                                self.tracker.set_base_score(proxy_url, base)

                        # Filter out retired proxies
                        active_before = len(proxies)
                        proxies = [p for p in proxies
                                   if not self.tracker.is_retired(p)]
                        retired_count = active_before - len(proxies)
                        if retired_count:
                            print(f"  [PROXY] Filtered {retired_count} retired proxies")

                        # Sort by tracker's runtime score (descending)
                        proxies.sort(key=lambda p: self.tracker.get_score(p),
                                     reverse=True)
                        if proxies:
                            best_score = self.tracker.get_score(proxies[0])
                            print(f"  [PROXY] Sorted by runtime score "
                                  f"(best: {best_score:.1f})")

                    return proxies
            except Exception as e:
                print(f"  [WARN] Failed to read {working_file}: {e}")

        if allow_refetch and not self._is_empty_fetch_cooldown():
            print(f"  [PROXY] No proxy cache found - fetching fresh proxies...")
            self._refetch()
            return self.load_proxies(allow_refetch=False)

        if self.config.local_proxies:
            print(f"  [PROXY] No working free proxies — using {len(self.config.local_proxies)} local proxy fallbacks")
            return self.config.local_proxies

        print(f"  [PROXY] No proxies available - engine will wait and retry")
        return []

    def refetch(self) -> None:
        """Force a proxy refresh regardless of cache state."""
        print(f"  [PROXY] Force-refreshing proxy cache...")
        self._refetch()
