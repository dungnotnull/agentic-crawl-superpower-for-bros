"""
Crawl-Superpower-for-Bros — Main entry point.

Never-stop orchestrator: the loop only exits when TARGET_JOBS or MAX_PAGES
criteria are met, or all pages are exhausted. If no proxies are available,
the script WAITS and keeps searching until a proxy becomes available.

Usage:
    python main.py --site ekaigotenshoku [--target-jobs 240] [--max-pages 10]
                   [--clean] [--no-headless]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from .checkpoint import (
        checkpoint_to_jobs,
        find_latest_incomplete_run,
        init_checkpoint,
        load_checkpoint,
        save_checkpoint,
    )
    from .config import CrawlConfig
    from .crawler import CrawlEngine
    from .exporter import dedup
    from .proxy_manager import ProxyManager
    from .site_mappings import load_site_mapping, list_available_sites
except ImportError:
    from checkpoint import (
        checkpoint_to_jobs,
        find_latest_incomplete_run,
        init_checkpoint,
        load_checkpoint,
        save_checkpoint,
    )
    from config import CrawlConfig
    from crawler import CrawlEngine
    from exporter import dedup
    from proxy_manager import ProxyManager
    from site_mappings import load_site_mapping, list_available_sites


def _safe_print(msg: str) -> None:
    """Print safely on Windows consoles that may not support Unicode."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(msg.encode("utf-8", errors="replace") + b"\n")
        sys.stdout.flush()


def _subprocess_env() -> dict[str, str]:
    """Build environment dict for subprocess calls (UTF-8 safe)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ── CLI ──────────────────────────────────────────────────────────────────

def _parse_args() -> dict:
    """Simple argument parser (no external dependency)."""
    args = sys.argv[1:]
    result = {
        "site": "ekaigotenshoku",
        "target_jobs": None,
        "max_pages": None,
        "clean": False,
        "headless": True,
    }
    i = 0
    while i < len(args):
        if args[i] == "--site" and i + 1 < len(args):
            result["site"] = args[i + 1]; i += 2
        elif args[i] == "--target-jobs" and i + 1 < len(args):
            val = int(args[i + 1])
            result["target_jobs"] = val if val > 0 else None; i += 2
        elif args[i] == "--max-pages" and i + 1 < len(args):
            val = int(args[i + 1])
            result["max_pages"] = val if val > 0 else None; i += 2
        elif args[i] == "--clean":
            result["clean"] = True; i += 1
        elif args[i] == "--no-headless":
            result["headless"] = False; i += 1
        elif args[i] in ("--help", "-h"):
            _print_help(); sys.exit(0)
        else:
            _safe_print(f"Unknown argument: {args[i]}"); i += 1
    return result


def _print_help() -> None:
    sites = list_available_sites()
    print(
        "Usage: python main.py [OPTIONS]\n\n"
        "Options:\n"
        "  --site NAME         Site mapping name (default: ekaigotenshoku)\n"
        f"                      Available: {', '.join(sites)}\n"
        "  --target-jobs N     Stop after N jobs (0 = unlimited)\n"
        "  --max-pages N       Max listing pages per proxy (0 = unlimited)\n"
        "  --clean             Delete previous output before starting\n"
        "  --no-headless       Run browser with visible window\n"
        "  --help, -h          Show this help message\n\n"
        "Examples:\n"
        "  python main.py\n"
        "  python main.py --target-jobs 240\n"
        "  python main.py --site ekaigotenshoku --target-jobs 500\n"
    )


# ── Clean Start / Resume ────────────────────────────────────────────────

def prompt_clean_start() -> bool:
    """Ask the user whether to start fresh or resume."""
    try:
        choice = input(
            "\n  [START] (C)lean start / (R)esume / (Q)uit? [C/R/Q]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return True

    if choice == "q":
        _safe_print("  Exiting.")
        sys.exit(0)
    if choice == "r":
        return False
    return True


def clear_output_dir(output_dir: Path) -> None:
    """Delete and recreate the output directory."""
    import shutil
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _safe_print("  [START] Cleared output directory.")


# ── Main Loop ────────────────────────────────────────────────────────────

async def main() -> None:
    args = _parse_args()
    config = CrawlConfig.from_env()

    # Apply CLI overrides
    if args["target_jobs"] is not None:
        config.target_jobs = args["target_jobs"]
    if args["max_pages"] is not None:
        config.max_pages = args["max_pages"]
    config.headless = args["headless"]

    # --- Startup banner ---
    sep = "=" * 72
    _safe_print(f"\n{sep}")
    _safe_print(f"  Crawl-Superpower-for-Bros v2")
    _safe_print(f"  Never-Stop Orchestrator - {datetime.now():%Y-%m-%d %H:%M:%S}")
    _safe_print(f"{sep}")

    # Load site mapping
    _safe_print(f"  [INIT] Loading site mapping: {args['site']}")
    mapping = load_site_mapping(args["site"])
    _safe_print(f"  [INIT] Site: {mapping.display_name} ({mapping.url.listing_url})")

    # Check proxy availability
    _safe_print(f"  [INIT] Checking proxy cache...")
    pm = ProxyManager(config, site_name=args['site'])
    proxies = pm.load_proxies()
    if proxies:
        _safe_print(f"  [INIT] Found {len(proxies)} cached proxies")
    else:
        _safe_print(f"  [INIT] No cached proxies — will fetch on first crawl cycle")
        _safe_print(f"  [INIT] Run 'python proxy/fetcher.py' first for faster startup")

    # Clean start or resume
    output_dir = config.output_dir
    clean = args["clean"]
    result = None

    if not clean:
        # Check for resumable run
        result = find_latest_incomplete_run(output_dir)
        if result:
            run_dir, existing_state = result
            existing_jobs = existing_state.get('total_jobs_extracted', 0)
            _safe_print(
                f"\n  [RESUME] Found incomplete run: {run_dir.name} "
                f"({existing_jobs} jobs already extracted)"
            )
            clean = prompt_clean_start()

    if clean:
        clear_output_dir(output_dir)

    # Initialize run directory and state
    if not clean and result:
        run_dir, state = result
        _safe_print(f"  [RESUME] Continuing from: {run_dir.name}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = output_dir / f"run_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        state = init_checkpoint(run_dir, mapping.url.listing_url, config.target_jobs)
        _safe_print(f"  [INIT] New run directory: {run_dir.name}")

    # --- Final status before crawl ---
    target_str = f"{config.target_jobs}" if config.target_jobs else "unlimited"
    pages_str = f"{config.max_pages}" if config.max_pages else "unlimited"
    _safe_print(f"\n{sep}")
    _safe_print(f"  Target:     {target_str} jobs")
    _safe_print(f"  Max pages:  {pages_str} per proxy")
    _safe_print(f"  Block:      {config.block_threshold} attempts before permanent block")
    _safe_print(f"  Headless:   {config.headless}")
    _safe_print(f"  Output:     {run_dir}")
    _safe_print(f"{sep}")
    _safe_print(f"\n  [START] The crawl loop will NOT stop until target is met.")
    _safe_print(f"  [START] If no proxies are available, it will wait and keep searching.")

    # --- Start dashboard in background ---
    dashboard_proc = None
    try:
        import subprocess
        log_file = run_dir / "dashboard.log"
        with open(log_file, "w") as log:
            dashboard_proc = subprocess.Popen(
                [sys.executable, "dashboard.py"],
                cwd=str(Path(__file__).parent),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        # Give it a moment to start
        import time
        time.sleep(0.5)
        if dashboard_proc.poll() is not None:
            _safe_print(f"  [DASHBOARD] Failed to start - see {log_file}")
        else:
            _safe_print(f"  [DASHBOARD] Live dashboard at http://localhost:8000")
    except Exception as e:
        _safe_print(f"  [DASHBOARD] Could not auto-start ({e}) - run 'python dashboard.py' manually")
    _safe_print()

    # Create engine and run - THE LOOP NEVER BREAKS
    engine = CrawlEngine(mapping, config)
    try:
        results = await engine.crawl_forever(run_dir, state)
    finally:
        # Stop dashboard on crawl completion
        if dashboard_proc:
            dashboard_proc.terminate()
            dashboard_proc.wait()
            _safe_print(f"  [DASHBOARD] Server stopped.")

    # --- Final summary ---
    _safe_print(f"\n{sep}")
    _safe_print(f"  CRAWL COMPLETE")
    _safe_print(f"{sep}")
    _safe_print(f"  Jobs crawled:  {len(results)}")
    _safe_print(f"  Output dir:    {run_dir}")
    _safe_print(f"  Raw HTML:      {run_dir / 'html' / 'detail'}")
    _safe_print(f"  Final JSON:    {run_dir / 'output-final-json'}")
    _safe_print(f"  Blocked jobs:  {run_dir / 'blocked_jobs.json'}")
    _safe_print(f"{sep}")


if __name__ == "__main__":
    asyncio.run(main())
