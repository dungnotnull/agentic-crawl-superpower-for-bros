"""
ProxyTracker — per-proxy runtime scoring, auto-retirement, and persistence.

Tracks each proxy's real-world performance during a crawl run:
  - Success/failure counts per proxy
  - Block detection frequency
  - Consecutive failure streaks → auto-retirement
  - Time-decayed scoring so stale proxies are deprioritised

Persists to the checkpoint directory so scoring survives crashes.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .config import CrawlConfig
except ImportError:
    from config import CrawlConfig  # type: ignore[no-redef]


class ProxyTracker:
    """Tracks per-proxy metrics and computes runtime scores.

    Two scoring modes — selectable via ``CrawlConfig.use_bayesian_scoring``:

    **Heuristic (default):**::
        base × success_ratio × block_penalty × time_decay

    **Bayesian (Beta-Binomial + Normal-Gamma + UCB):**::
        P(success) = alpha / (alpha + beta)          ← Beta posterior
        expected_latency = sqrt(variance / n)         ← from Normal-Gamma
        exploration_bonus = sqrt(2·ln(N) / (α+β))    ← UCB1
        score = P(success) / expected_latency · time_decay + exploration_bonus

    Proxies are auto-retired after N consecutive failures or blocks.
    """

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.proxies: dict[str, dict[str, Any]] = {}
        self._start_time = datetime.now()
        self._global_total_trials = 0

    # ── Public API ──────────────────────────────────────────────────────

    def record_success(self, proxy: str, latency: float | None = None) -> None:
        """Record a successful crawl session for a proxy.

        Args:
            proxy: The proxy URL.
            latency: Response time in seconds (used in Bayesian mode).
        """
        entry = self._ensure(proxy)
        entry["successes"] += 1
        entry["consecutive_failures"] = 0
        entry["consecutive_blocks"] = 0
        entry["last_used"] = datetime.now().isoformat()
        if self.config.use_bayesian_scoring:
            entry["alpha"] += 1
            self._global_total_trials += 1
            if latency is not None:
                self._record_latency(entry, latency)
        self._recalc_score(proxy)

    def record_failure(self, proxy: str) -> None:
        """Record a failed crawl session (no pages fetched)."""
        entry = self._ensure(proxy)
        entry["failures"] += 1
        entry["consecutive_failures"] += 1
        entry["last_used"] = datetime.now().isoformat()
        if self.config.use_bayesian_scoring:
            entry["beta"] += 1
            self._global_total_trials += 1
        self._recalc_score(proxy)
        self._check_retire(proxy)

    def record_block(self, proxy: str) -> None:
        """Record that a block was detected while using this proxy."""
        entry = self._ensure(proxy)
        entry["blocks"] += 1
        entry["consecutive_blocks"] += 1
        entry["last_used"] = datetime.now().isoformat()
        if self.config.use_bayesian_scoring:
            entry["beta"] += 1
            self._global_total_trials += 1
        self._recalc_score(proxy)
        self._check_retire(proxy)

    def record_latency(self, proxy: str, elapsed: float) -> None:
        """Record a response-time observation for Bayesian latency model.

        Uses Welford's online algorithm so we don't store every sample.
        """
        entry = self._ensure(proxy)
        # Welford's online variance update
        n = entry.get("latency_n", 0)
        old_mean = entry.get("latency_mean", 0.0)
        old_m2 = entry.get("latency_m2", 0.0)

        n += 1
        delta = elapsed - old_mean
        new_mean = old_mean + delta / n
        delta2 = elapsed - new_mean
        new_m2 = old_m2 + delta * delta2

        entry["latency_n"] = n
        entry["latency_mean"] = new_mean
        entry["latency_m2"] = new_m2

    def record(self, proxy: str, success_count: int | None = None,
               fail_count: int | None = None,
               block_count: int | None = None,
               pages_visited: int = 0,
               avg_latency: float | None = None) -> None:
        """Record a batch summary after a proxy session.

        Args:
            proxy: The proxy URL.
            success_count: How many jobs were successfully fetched.
            fail_count:   How many job fetches failed/blocked.
            block_count:  How many blocks were detected.
            pages_visited: How many listing pages were loaded.
            avg_latency: Average response time in seconds (Bayesian mode).
        """
        entry = self._ensure(proxy)

        if success_count is not None:
            entry["successes"] += success_count
        if fail_count is not None:
            entry["failures"] += fail_count
            entry["consecutive_failures"] += fail_count
        if block_count is not None:
            entry["blocks"] += block_count
            entry["consecutive_blocks"] += block_count

        # Bayesian posterior updates
        if self.config.use_bayesian_scoring:
            if success_count is not None and success_count > 0:
                entry["alpha"] += success_count
                self._global_total_trials += success_count
            if fail_count is not None:
                entry["beta"] += fail_count
                self._global_total_trials += fail_count
            if avg_latency is not None:
                self.record_latency(proxy, avg_latency)

        entry["pages_visited"] += pages_visited
        entry["last_used"] = datetime.now().isoformat()

        # If there was at least one success, reset consecutive counters
        if success_count and success_count > 0:
            entry["consecutive_failures"] = 0
            entry["consecutive_blocks"] = 0

        self._recalc_score(proxy)
        self._check_retire(proxy)

    def set_base_score(self, proxy: str, base_score: float) -> None:
        """Set or update the base score for a proxy (from fetcher cache)."""
        entry = self._ensure(proxy)
        entry["base_score"] = base_score
        self._recalc_score(proxy)

    def get_score(self, proxy: str) -> float:
        """Return the current runtime score for a proxy.

        **Heuristic mode:** current_score from ``_recalc_score``.
        **Bayesian mode:** P(success) / sqrt(latency_variance) · time_decay + UCB bonus.

        Returns -inf for retired proxies so they sort last.
        """
        entry = self.proxies.get(proxy)
        if not entry:
            return 0.0
        if entry.get("retired"):
            return float("-inf")

        score = entry.get("current_score", 0.0)

        # Add UCB exploration bonus in Bayesian mode
        if self.config.use_bayesian_scoring:
            alpha = entry.get("alpha", 1)
            beta = entry.get("beta", 1)
            total = alpha + beta - 2  # total trials (excluding prior)
            if total > 0:
                exploration = math.sqrt(
                    (2 * math.log(max(self._global_total_trials, 1))) / total
                )
                score += exploration * self.config.bayesian_exploration_factor

        return score

    def is_retired(self, proxy: str) -> bool:
        """Check whether a proxy has been retired."""
        entry = self.proxies.get(proxy)
        return bool(entry and entry.get("retired"))

    def should_retire(self, proxy: str) -> bool:
        """Check if a proxy meets retirement criteria."""
        entry = self.proxies.get(proxy)
        if not entry:
            return False

        cfg = self.config
        if (entry["consecutive_failures"] >= cfg.proxy_retire_consecutive_failures
                or entry["consecutive_blocks"] >= cfg.proxy_retire_consecutive_blocks):
            return True
        return False

    def retire_proxy(self, proxy: str, reason: str = "") -> None:
        """Explicitly retire a proxy."""
        entry = self._ensure(proxy)
        if entry.get("retired"):
            return
        entry["retired"] = True
        entry["retired_reason"] = reason or "manual"
        entry["current_score"] = float("-inf")

    def get_active_proxies(self) -> list[str]:
        """Return non-retired proxies sorted by score descending."""
        active = [
            p for p, e in self.proxies.items()
            if not e.get("retired")
        ]
        active.sort(key=lambda p: self.get_score(p), reverse=True)
        return active

    def get_stats(self, proxy: str) -> dict[str, Any] | None:
        """Return full stats dict for a proxy."""
        return self.proxies.get(proxy)

    def summary(self) -> str:
        """Return a one-line summary string for logging."""
        active = len([e for e in self.proxies.values() if not e.get("retired")])
        retired = len([e for e in self.proxies.values() if e.get("retired")])
        total_success = sum(e.get("successes", 0) for e in self.proxies.values())
        total_fail = sum(e.get("failures", 0) for e in self.proxies.values())
        return (f"{len(self.proxies)} tracked, {active} active, "
                f"{retired} retired, {total_success} ok, {total_fail} fail")

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """Atomically save tracker state to a JSON file."""
        path = Path(path)
        data = {
            "proxies": self.proxies,
            "updated_at": datetime.now().isoformat(),
        }
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(str(tmp), str(path))
        except Exception as e:
            print(f"[WARN] ProxyTracker save error: {e}")

    def load(self, path: Path) -> None:
        """Load tracker state from a JSON file."""
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            loaded = data.get("proxies", {})
            # Merge: incoming data overrides existing entries
            for proxy, entry in loaded.items():
                self.proxies[proxy] = entry
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass

    # ── Internal helpers ────────────────────────────────────────────────

    def _ensure(self, proxy: str) -> dict[str, Any]:
        """Get or create a stats entry for a proxy."""
        if proxy not in self.proxies:
            self.proxies[proxy] = {
                "proxy": proxy,
                "base_score": 50.0,
                "current_score": 50.0,
                "successes": 0,
                "failures": 0,
                "blocks": 0,
                "consecutive_failures": 0,
                "consecutive_blocks": 0,
                "pages_visited": 0,
                "last_used": None,
                "retired": False,
                "retired_reason": None,
                # Bayesian posterior (Beta-Binomial with flat prior)
                "alpha": 1,
                "beta": 1,
                # Latency variance (Welford online algorithm)
                "latency_n": 0,
                "latency_mean": 0.0,
                "latency_m2": 0.0,
            }
        return self.proxies[proxy]

    def _record_latency(self, entry: dict[str, Any], elapsed: float) -> None:
        """Online variance update (Welford)."""
        n = entry.get("latency_n", 0)
        old_mean = entry.get("latency_mean", 0.0)
        old_m2 = entry.get("latency_m2", 0.0)
        n += 1
        delta = elapsed - old_mean
        new_mean = old_mean + delta / n
        delta2 = elapsed - new_mean
        new_m2 = old_m2 + delta * delta2
        entry["latency_n"] = n
        entry["latency_mean"] = new_mean
        entry["latency_m2"] = new_m2

    def _recalc_score(self, proxy: str) -> None:
        """Recompute the current_score for a proxy.

        **Heuristic mode** (default)::

            base × success_ratio × block_penalty × time_decay

        **Bayesian mode**::

            P(success) = alpha / (alpha + beta)           ← Beta posterior mean
            expected_latency = sqrt(variance / n)          ← Normal-Gamma std err
            score = P(success) / expected_latency · time_decay
        """
        entry = self.proxies.get(proxy)
        if not entry or entry.get("retired"):
            return

        base = entry.get("base_score", 50.0)
        successes = entry.get("successes", 0)
        failures = entry.get("failures", 0)
        blocks = entry.get("blocks", 0)
        total = successes + failures

        # ── Time decay (shared by both modes) ──
        time_decay = 1.0
        last_used = entry.get("last_used")
        if last_used:
            try:
                elapsed = datetime.now() - datetime.fromisoformat(last_used)
                hours = elapsed.total_seconds() / 3600
                if hours > 0:
                    decay_period = self.config.proxy_score_decay_hours
                    if decay_period > 0:
                        time_decay = 0.95 ** (hours / decay_period)
            except (ValueError, TypeError):
                pass

        if self.config.use_bayesian_scoring:
            # ── Bayesian: Beta-Binomial posterior ──
            alpha = entry.get("alpha", 1)
            beta = entry.get("beta", 1)
            p_success = alpha / (alpha + beta)

            # ── Latency penalty: std err of the mean ──
            latency_n = entry.get("latency_n", 0)
            latency_penalty = 1.0
            if latency_n >= 2:
                variance = entry["latency_m2"] / (latency_n - 1)
                if variance > 0:
                    std_err = math.sqrt(variance / latency_n)
                    # Scale so that 10s latency halves the score
                    latency_penalty = max(0.1, 1.0 / (1.0 + std_err))

            score = p_success * latency_penalty * time_decay * 100.0
            entry["current_score"] = round(score, 1)
        else:
            # ── Heuristic: original formula ──
            # No data yet → keep base
            if total == 0:
                entry["current_score"] = base
                return

            # Success ratio
            success_ratio = successes / total

            # Block penalty: each block reduces score by 15% (multiplicative)
            block_penalty = 0.85 ** blocks

            score = base * success_ratio * block_penalty * time_decay
            entry["current_score"] = round(score, 1)

    def _check_retire(self, proxy: str) -> None:
        """Auto-retire a proxy if consecutive thresholds are exceeded."""
        entry = self.proxies.get(proxy)
        if not entry or entry.get("retired"):
            return

        cfg = self.config
        if (entry["consecutive_failures"] >= cfg.proxy_retire_consecutive_failures
                and cfg.proxy_retire_consecutive_failures > 0):
            entry["retired"] = True
            entry["retired_reason"] = (
                f"{entry['consecutive_failures']} consecutive failures")
            entry["current_score"] = float("-inf")

        elif (entry["consecutive_blocks"] >= cfg.proxy_retire_consecutive_blocks
              and cfg.proxy_retire_consecutive_blocks > 0):
            entry["retired"] = True
            entry["retired_reason"] = (
                f"{entry['consecutive_blocks']} consecutive blocks")
            entry["current_score"] = float("-inf")
