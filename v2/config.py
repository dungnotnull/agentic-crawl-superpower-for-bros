"""
Configuration — environment variables, CLI overrides, and defaults.

All tunable parameters live here. Users can override via:
  - Environment variables (CRAWL_TARGET_JOBS, CRAWL_MAX_PAGES, etc.)
  - CLI arguments (--target-jobs, --max-pages, etc.)
  - Direct editing of this file's defaults
"""

from __future__ import annotations

import os
import subprocess
import sys
import json
from datetime import timedelta
from pathlib import Path


class CrawlConfig:
    """Central configuration for the crawl engine."""

    # ── Stop criteria ──
    target_jobs: int | None       # Stop after N jobs (None = unlimited)
    max_pages: int | None        # Max listing pages per proxy (None = unlimited)

    # ── Block tracking ──
    block_threshold: int         # Move to block file after N failed attempts

    # ── Timing ──
    delay_min: float             # Min delay between listing page loads (seconds)
    delay_max: float             # Max delay between listing page loads
    detail_delay_min: float      # Min delay between detail page loads
    detail_delay_max: float      # Max delay between detail page loads
    detail_batch_size: int       # Pause after N consecutive detail fetches
    detail_batch_pause: float    # How long to pause between batches (seconds)
    max_empty: int               # Consecutive empty pages before giving up on proxy

    # ── Browser ──
    headless: bool               # Run browser in headless mode

    # ── Proxy ──
    proxy_cache_ttl: timedelta   # How long before proxy cache is considered stale
    proxy_working_file: Path     # Path to proxy cache JSON
    proxy_fetch_script: str      # Script to run for proxy refresh

    # ── Output ──
    output_dir: Path             # Root output directory

    # ── Proxy scoring & retirement ──
    proxy_retire_consecutive_failures: int   # Retire after N consecutive failures
    proxy_retire_consecutive_blocks: int     # Retire after N consecutive blocks
    proxy_score_decay_hours: float           # Score drops 95%/period

    # ── Bayesian scoring toggle ──
    use_bayesian_scoring: bool               # Use Beta-Binomial + latency model
    bayesian_exploration_factor: float       # UCB exploration bonus multiplier

    # ── Rate limiting detection & adaptation ──
    rate_limit_multiplier_min: float         # Normal delay multiplier (1.0 = no change)
    rate_limit_multiplier_max: float         # Max slowdown when rate-limited
    rate_limit_step_up: float                # Increase multiplier by this on detection
    rate_limit_step_down: float              # Decrease multiplier by this on recovery
    rate_limit_recovery_hits: int            # Successful fetches before stepping down

    # ── Local fallback proxies ──
    local_proxies: list[str]

    def __init__(self, **kwargs):
        # Defaults
        self.target_jobs = None
        self.max_pages = None
        self.block_threshold = 20
        self.delay_min = 3.5
        self.delay_max = 8.0
        self.detail_delay_min = 2.0
        self.detail_delay_max = 5.0
        self.detail_batch_size = 8
        self.detail_batch_pause = 12.0
        self.max_empty = 2
        self.headless = True
        self.proxy_cache_ttl = timedelta(minutes=30)
        self.proxy_working_file = Path("japan_working_proxies.json")
        self.proxy_fetch_script = "proxy/fetcher.py"
        self.output_dir = Path("output")
        # Proxy scoring & retirement
        self.proxy_retire_consecutive_failures = 5
        self.proxy_retire_consecutive_blocks = 3
        self.proxy_score_decay_hours = 1.0
        # Bayesian scoring
        self.use_bayesian_scoring = False
        self.bayesian_exploration_factor = 1.0
        # Rate limiting
        self.rate_limit_multiplier_min = 1.0
        self.rate_limit_multiplier_max = 4.0
        self.rate_limit_step_up = 0.5
        self.rate_limit_step_down = 0.1
        self.rate_limit_recovery_hits = 20
        # Local fallbacks
        self.local_proxies = [
            "socks5://127.0.0.1:1080",
            "socks5://127.0.0.1:7891",
            "socks5://127.0.0.1:10808",
            "http://127.0.0.1:7890",
        ]
        # Apply overrides
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    @classmethod
    def from_env(cls) -> "CrawlConfig":
        """Build config from environment variables."""
        cfg = cls()

        if v := os.environ.get("CRAWL_TARGET_JOBS"):
            cfg.target_jobs = int(v) if int(v) > 0 else None
        if v := os.environ.get("CRAWL_MAX_PAGES"):
            cfg.max_pages = int(v) if int(v) > 0 else None
        if v := os.environ.get("CRAWL_BLOCK_THRESHOLD"):
            cfg.block_threshold = int(v)
        if v := os.environ.get("CRAWL_HEADLESS"):
            cfg.headless = v.lower() in ("1", "true", "yes")
        if v := os.environ.get("CRAWL_OUTPUT_DIR"):
            cfg.output_dir = Path(v)
        if v := os.environ.get("CRAWL_PROXY_RETIRE_FAILURES"):
            cfg.proxy_retire_consecutive_failures = int(v)
        if v := os.environ.get("CRAWL_PROXY_RETIRE_BLOCKS"):
            cfg.proxy_retire_consecutive_blocks = int(v)
        if v := os.environ.get("CRAWL_PROXY_SCORE_DECAY_HOURS"):
            cfg.proxy_score_decay_hours = float(v)
        if v := os.environ.get("CRAWL_USE_BAYESIAN"):
            cfg.use_bayesian_scoring = v.lower() in ("1", "true", "yes")
        if v := os.environ.get("CRAWL_BAYESIAN_EXPLORATION"):
            cfg.bayesian_exploration_factor = float(v)
        if v := os.environ.get("CRAWL_RATE_LIMIT_MAX"):
            cfg.rate_limit_multiplier_max = float(v)
        if v := os.environ.get("CRAWL_RATE_LIMIT_STEP_UP"):
            cfg.rate_limit_step_up = float(v)
        if v := os.environ.get("CRAWL_RATE_LIMIT_STEP_DOWN"):
            cfg.rate_limit_step_down = float(v)
        if v := os.environ.get("CRAWL_RATE_LIMIT_RECOVERY"):
            cfg.rate_limit_recovery_hits = int(v)

        return cfg
