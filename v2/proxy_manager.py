"""
Proxy Manager - loads, validates, and refreshes proxy lists.

If no proxies are available, the manager signals this to the crawl engine,
which will WAIT and keep searching rather than terminating.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from .config import CrawlConfig
except ImportError:
    from config import CrawlConfig  # type: ignore[no-redef]


class ProxyManager:
    """Manages proxy loading, cache validation, and refresh."""

    def __init__(self, config: CrawlConfig, site_name: str = ""):
        self.config = config
        self.site_name = site_name

    def _cache_is_stale(self, data: dict) -> bool:
        """Check if the proxy cache has exceeded its TTL.
        Also checks if the cached target matches the current site."""
        updated_raw = data.get("updated_at")
        if not updated_raw:
            return True
        # If site-aware, check that the cache was built for this site
        if self.site_name:
            cached_target = data.get("target", "")
            # Could do smarter matching here; for now just check TTL
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
        cmd = [sys.executable, self.config.proxy_fetch_script] + site_arg
        print(f"  [PROXY] Fetching fresh proxies from multiple providers...")
        if self.site_name:
            print(f"  [PROXY] Site: {self.site_name}")
        print(f"  [PROXY] Running {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=True)
            print(f"  [PROXY] Proxy fetch completed")
        except Exception as e:
            print(f"  [WARN] Proxy re-fetch failed: {e}")

    def load_proxies(self, allow_refetch: bool = True) -> list[str]:
        """Load proxies sorted by real_score (best first).

        Returns empty list if no proxies available (engine will wait).
        """
        working_file = self.config.proxy_working_file
        if working_file.exists():
            try:
                data = json.loads(working_file.read_text(encoding="utf-8"))
                if allow_refetch and self._cache_is_stale(data):
                    self._refetch()
                    return self.load_proxies(allow_refetch=False)
                raw = data.get("proxies", [])
                raw.sort(key=lambda x: -x.get("real_score", 0))
                proxies = [p["proxy"] for p in raw if p.get("proxy")]
                if proxies:
                    top_score = raw[0].get("real_score", "?")
                    jp_count = sum(1 for p in raw if p.get("is_jp"))
                    site_ok = sum(1 for p in raw if p.get("target_ok"))
                    print(f"  [PROXY] Loaded {len(proxies)} proxies "
                          f"(JP: {jp_count}, site-OK: {site_ok}, "
                          f"top score: {top_score})")
                    return proxies
            except Exception as e:
                print(f"  [WARN] Failed to read {working_file}: {e}")

        if allow_refetch:
            print(f"  [PROXY] No proxy cache found - fetching fresh proxies...")
            self._refetch()
            return self.load_proxies(allow_refetch=False)

        if self.config.local_proxies:
            print(f"  [PROXY] Using {len(self.config.local_proxies)} local proxy fallbacks")
            return self.config.local_proxies

        print(f"  [PROXY] No proxies available - engine will wait and retry")
        return []

    def refetch(self) -> None:
        """Force a proxy refresh regardless of cache state."""
        print(f"  [PROXY] Force-refreshing proxy cache...")
        self._refetch()
