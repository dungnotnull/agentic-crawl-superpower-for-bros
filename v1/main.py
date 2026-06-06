"""
main.py - Ekaigo Crawler Orchestrator
----------------------------------------
Chay tuan tu: autofetch_ja_servers.py -> cloak_auto_japan.py
Tu dong restart khi het proxy nhung chua du target hoac con blocked jobs.
Hoi nguoi dung co muon xoa output cu khi bat dau.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

# ============================================================
OUTPUT_DIR       = Path("output")
FETCH_SCRIPT     = "autofetch_ja_servers.py"
CRAWL_SCRIPT     = "cloak_auto_japan.py"
MAX_RESTART_LOOP = 3
# ============================================================


def clear_output_dir() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(str(OUTPUT_DIR))
        print("[CLEAN] Da xoa output directory.")
    OUTPUT_DIR.mkdir(exist_ok=True)


def _safe_print_bytes(data: str) -> None:
    """Print string safely, handling encoding errors on Windows console."""
    try:
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.buffer.write(data.encode(enc, errors="replace") + b"\n")
        sys.stdout.buffer.flush()
    except Exception:
        try:
            sys.stdout.buffer.write(data.encode("ascii", errors="replace") + b"\n")
            sys.stdout.buffer.flush()
        except Exception:
            pass


def run_autofetch() -> bool:
    """Run autofetch_ja_servers.py. Returns True if successful (proxies found)."""
    print(f"\n{'='*60}")
    print(f"  [STEP 1] Fetch proxy Nhat...")
    print(f"{'='*60}")
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, FETCH_SCRIPT],
            check=True, capture_output=True, text=True,
            env=env, encoding="utf-8", errors="replace"
        )
        stdout = result.stdout
        if len(stdout) > 500:
            _safe_print_bytes(stdout[-500:])
        else:
            _safe_print_bytes(stdout)
        return True
    except subprocess.CalledProcessError as e:
        stdout = (e.stdout or "")[-500:]
        stderr = (e.stderr or "")[-500:]
        if stdout:
            _safe_print_bytes(stdout)
        if stderr:
            _safe_print_bytes("[STDERR]\n" + stderr)
        return False


def run_crawl() -> dict | None:
    """Run cloak_auto_japan.py. Returns checkpoint state dict or None if failed."""
    print(f"\n{'='*60}")
    print(f"  [STEP 2] Crawl ekaigotenshoku...")
    print(f"{'='*60}")
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, CRAWL_SCRIPT],
            capture_output=True, text=True,
            env=env, encoding="utf-8", errors="replace"
        )
        stdout = result.stdout or ""
        if len(stdout) > 2000:
            _safe_print_bytes(stdout[:1000])
            print(f"\n... ({len(stdout)} bytes total) ...\n")
            _safe_print_bytes(stdout[-1000:])
        else:
            _safe_print_bytes(stdout)
        if result.stderr:
            stderr = result.stderr or ""
            _safe_print_bytes("[STDERR]\n" + (stderr[-500:] if len(stderr) > 500 else stderr))
        if result.returncode != 0:
            print(f"[WARN] Crawl exit code: {result.returncode}")
        return _read_latest_checkpoint()
    except Exception as e:
        print(f"[ERROR] Crawl: {e}")
        return None


def _read_latest_checkpoint() -> dict | None:
    """Read the most recent run's checkpoint."""
    if not OUTPUT_DIR.exists():
        return None
    runs = sorted(
        [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")],
        key=lambda d: d.name, reverse=True
    )
    if not runs:
        return None
    ckpt = runs[0] / "checkpoint.json"
    if ckpt.exists():
        try:
            return json.loads(ckpt.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _load_proxies_from_file() -> list[str]:
    """Load proxies directly from japan_working_proxies.json."""
    proxy_file = Path("japan_working_proxies.json")
    if not proxy_file.exists():
        return []
    try:
        data = json.loads(proxy_file.read_text(encoding="utf-8"))
        raw = data.get("proxies", [])
        raw.sort(key=lambda x: -x.get("real_score", 0))
        return [p["proxy"] for p in raw if p.get("proxy")]
    except Exception:
        return []


def get_blocked_jobs(state: dict) -> list[dict]:
    return state.get("blocked_jobs", [])


def has_blocked_jobs(state: dict) -> bool:
    return len(get_blocked_jobs(state)) > 0


def is_target_reached(state: dict) -> bool:
    target = state.get("target_jobs")
    if target is None:
        return False
    return state.get("total_jobs_extracted", 0) >= target


def prompt_clean_start() -> bool:
    """Ask user whether to clear output. Returns True if clean start."""
    print(f"\n{'='*60}")
    print(f"  Ekaigo Crawler Orchestrator")
    print(f"{'='*60}")

    if OUTPUT_DIR.exists():
        runs = [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")]
        if runs:
            latest = sorted(runs, key=lambda d: d.name)[-1]
            ckpt_file = latest / "checkpoint.json"
            if ckpt_file.exists():
                try:
                    ckpt = json.loads(ckpt_file.read_text(encoding="utf-8"))
                    pages = len(ckpt.get("pages", []))
                    jobs = ckpt.get("total_jobs_extracted", 0)
                    blocked = len(ckpt.get("blocked_jobs", []))
                    target = ckpt.get("target_jobs", "?")
                    print(f"\n  Found run {latest.name}:")
                    print(f"     {pages} pages, {jobs} jobs completed, {blocked} blocked")
                    print(f"     Target: {target}")
                except Exception:
                    print(f"\n  Found run {latest.name} (cannot read checkpoint)")
            else:
                print(f"\n  Found run {latest.name} (no checkpoint)")

    print(f"\n  Choose:")
    print(f"    1. Delete all output and start fresh")
    print(f"    2. Continue with current output (resume)")
    print(f"    3. Exit")

    while True:
        try:
            choice = input("  Enter choice (1/2/3): ").strip()
            if choice == "1":
                return True
            elif choice == "2":
                return False
            elif choice == "3":
                print("  Goodbye.")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            sys.exit(0)
        print("  Enter 1, 2, or 3.")


async def retry_blocked_jobs(proxies: list[str], state: dict, run_dir: Path) -> int:
    """Retry blocked jobs with working proxies. Returns recovered count."""
    blocked = get_blocked_jobs(state)
    if not blocked:
        return 0

    print(f"\n{'='*60}")
    print(f"  [RETRY] {len(blocked)} blocked jobs...")
    print(f"{'='*60}")

    from cloakbrowser import launch_async
    import random as rnd

    detail_dir = run_dir / "html" / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    block_kw = ["access denied", "forbidden", "403 ", "blocked",
                "\u30a2\u30af\u30bb\u30b9\u5236\u9650",
                "\u5730\u57df\u5236\u9650",
                "\u3054\u5229\u7528\u3044\u305f\u3060\u3051\u307e\u305b\u3093"]
    recovered = 0
    recovered_ids = set()

    for job in blocked:
        jid = job.get("job_id")
        durl = job.get("detail_url")
        if not durl:
            continue

        fetched = False
        for pidx, proxy in enumerate(proxies, 1):
            browser = None
            try:
                browser = await launch_async(
                    headless=True, proxy=proxy,
                    humanize=True, geoip=True, human_preset="careful",
                )
                context = await browser.new_context(
                    viewport={"width": 1366, "height": 768},
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"),
                )
                page = await context.new_page()

                print(f"   Retry job {jid} (proxy {pidx}/{len(proxies)})...", end=" ")

                success = False
                for attempt in range(3):
                    try:
                        await page.goto(durl, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(rnd.uniform(2.0, 5.0))
                        html = await page.content()

                        if any(kw in html.lower() for kw in block_kw):
                            if attempt < 2:
                                await asyncio.sleep(4 * (2 ** attempt))
                                continue
                            break

                        html_filename = f"job_{jid}.html"
                        html_path = detail_dir / html_filename
                        html_path.write_text(html, encoding="utf-8")

                        for pg in state.get("pages", []):
                            for j in pg.get("jobs", []):
                                if j.get("job_id") == jid:
                                    j["detail_fetched"] = True
                                    j["detail_html"] = f"html/detail/{html_filename}"
                                    break
                        state["total_jobs_extracted"] += 1
                        recovered += 1
                        recovered_ids.add(jid)
                        success = True
                        print("OK (recovered)")
                        break
                    except Exception:
                        if attempt < 2:
                            await asyncio.sleep(4 * (2 ** attempt))
                        continue

                await browser.close()
                if success:
                    fetched = True
                    break
                print("FAIL")

            except Exception as e:
                print(f"FAIL ({type(e).__name__})")
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                continue

        if not fetched:
            print(f"   [WARN] Job {jid}: could not recover after {len(proxies)} proxies")
            # Increment retries so _discard_blocked_jobs can eventually skip it
            job["retries"] = job.get("retries", 0) + 1

    state["blocked_jobs"] = [b for b in blocked if b.get("job_id") not in recovered_ids]
    _save_checkpoint_atomic(run_dir, state)
    return recovered


def _save_checkpoint_atomic(run_dir: Path, state: dict) -> None:
    ckpt_path = run_dir / "checkpoint.json"
    tmp = run_dir / "checkpoint.json.tmp"
    state["updated_at"] = datetime.now().isoformat()
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(ckpt_path))
    except Exception as ex:
        print(f"[WARN] Checkpoint write: {ex}")


def _discard_blocked_jobs() -> None:
    """Move persistently blocked jobs to a permanent skip list.
    Only discards jobs that have been retried 3+ times.
    Also marks them detail_fetched=True in page entries to prevent re-attempt."""
    state = _read_latest_checkpoint()
    if not state:
        return
    blocked = state.get("blocked_jobs", [])
    if not blocked:
        return

    failed = state.setdefault("permanently_failed", [])
    kept = []
    discarded = 0
    discarded_ids = set()

    for job in blocked:
        retries = job.get("retries", 0)
        if retries >= 3:
            failed.append({
                "job_id": job.get("job_id"),
                "title": job.get("title"),
                "detail_url": job.get("detail_url"),
                "retries": retries,
                "discarded_at": datetime.now().isoformat(),
            })
            discarded_ids.add(job.get("job_id"))
            discarded += 1
        else:
            kept.append(job)

    # Mark discarded jobs as detail_fetched in page entries so crawler skips them
    if discarded_ids:
        for pg in state.get("pages", []):
            for job in pg.get("jobs", []):
                if job.get("job_id") in discarded_ids and not job.get("detail_fetched"):
                    job["detail_fetched"] = True
                    job["detail_html"] = None

    state["blocked_jobs"] = kept
    print(f"  Discarded {discarded} hopeless jobs, {len(kept)} kept for next retry.")

    runs = sorted(
        [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")],
        key=lambda d: d.name, reverse=True
    )
    if runs:
        _save_checkpoint_atomic(runs[0], state)


def _discard_all_blocked(state: dict, run_dir: Path) -> None:
    """Emergency: discard ALL blocked jobs."""
    failed = state.setdefault("permanently_failed", [])
    for job in state.get("blocked_jobs", []):
        failed.append({
            "job_id": job.get("job_id"),
            "title": job.get("title"),
            "detail_url": job.get("detail_url"),
            "retries": job.get("retries", 0),
            "discarded_at": datetime.now().isoformat(),
        })
    state["blocked_jobs"] = []
    # Mark as detail_fetched in pages
    for job in failed:
        for pg in state.get("pages", []):
            for j in pg.get("jobs", []):
                if j.get("job_id") == job["job_id"]:
                    j["detail_fetched"] = True
                    break
    print(f"  Emergency discard: {len(failed)} total blocked jobs cleared.")
    _save_checkpoint_atomic(run_dir, state)


async def main_loop():
    """Main orchestrator loop."""
    clean = prompt_clean_start()

    if clean:
        clear_output_dir()
        print("[OK] Clean start.")
    else:
        print("[OK] Resume mode.")

    restart_count = 0
    stagnation_count = 0
    prev_total_jobs = 0
    total_loops = 0
    MAX_TOTAL_LOOPS = 10
    while True:
        total_loops += 1
        if total_loops > MAX_TOTAL_LOOPS:
            print(f"\n[WARN] Total loops exceeded ({MAX_TOTAL_LOOPS}). Stopping.")
            runs = sorted(
                [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")],
                key=lambda d: d.name, reverse=True
            )
            if runs:
                _discard_all_blocked(state, runs[0])
            return
        restart_count += 1
        if restart_count > 1:
            print(f"\n{'='*60}")
            print(f"  [RESTART LOOP #{restart_count}]")
            print(f"{'='*60}")

        # Step 1: Fetch proxies
        if not run_autofetch():
            print("[FATAL] Cannot fetch proxies. Stopping.")
            return

        # Step 2: Run crawl
        state = run_crawl()
        if state is None:
            print("[FATAL] Crawl produced no checkpoint.")
            return

        # Step 3: Check results
        target_reached = is_target_reached(state)
        blocked_count = len(get_blocked_jobs(state))
        total_jobs = state.get("total_jobs_extracted", 0)
        target = state.get("target_jobs", "?")

        print(f"\n  Result: {total_jobs}/{target} jobs, {blocked_count} blocked")

        # Detect stagnation: no new jobs after a full cycle
        if total_jobs > prev_total_jobs:
            stagnation_count = 0
            prev_total_jobs = total_jobs
        else:
            stagnation_count += 1

        if stagnation_count >= 3 and restart_count > MAX_RESTART_LOOP:
            print(f"\n[WARN] No progress for {stagnation_count} cycles. Discarding all blocked jobs and finishing.")
            state["blocked_jobs"] = []
            runs = sorted(
                [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")],
                key=lambda d: d.name, reverse=True
            )
            if runs:
                _save_checkpoint_atomic(runs[0], state)
            return

        # Step 4: Retry blocked jobs
        if blocked_count > 0:
            proxies = _load_proxies_from_file()
            if proxies:
                runs = sorted(
                    [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")],
                    key=lambda d: d.name, reverse=True
                )
                if runs:
                    recovered = await retry_blocked_jobs(proxies, state, runs[0])
                    print(f"  Recovered: {recovered}/{blocked_count}")
                    state = _read_latest_checkpoint() or state
                    total_jobs = state.get("total_jobs_extracted", 0)
                    blocked_count = len(get_blocked_jobs(state))

        # Step 5: Decide if restart needed
        if target is not None and target != "?" and total_jobs >= target and blocked_count == 0:
            print(f"\n[DONE] Target reached: {total_jobs} jobs, 0 blocked.")
            return

        if target is None:
            if blocked_count == 0:
                print(f"\n[DONE] {total_jobs} jobs (no target limit).")
                return
            # Still have blocked jobs, try restart

        need_restart = blocked_count > 0 or (target is not None and target != "?" and total_jobs < target)

        if need_restart:
            if restart_count < MAX_RESTART_LOOP:
                print(f"\n[WARN] Not done ({total_jobs}/{target}, {blocked_count} blocked).")
                print(f"  Restarting loop {restart_count}/{MAX_RESTART_LOOP}...")
                time.sleep(3)
                continue
            else:
                # Max restarts reached. Discard hopeless blocked jobs and continue.
                print(f"\n[WARN] Max restarts ({MAX_RESTART_LOOP}) reached.")
                if blocked_count > 0:
                    print(f"  Discarding {blocked_count} persistently blocked jobs and continuing...")
                    _discard_blocked_jobs()
                    state = _read_latest_checkpoint() or state
                    blocked_count = len(get_blocked_jobs(state))
                    total_jobs = state.get("total_jobs_extracted", 0)
                    # Reset counter so we can keep crawling
                    restart_count = 0

        # Re-evaluate: still need more jobs or still have retriable blocked jobs?
        still_need_jobs = (target is not None and target != "?" and total_jobs < target)
        still_have_blocked = blocked_count > 0

        if still_need_jobs or still_have_blocked:
            if still_need_jobs:
                print(f"  Still need {target - total_jobs} more jobs — restarting...")
            else:
                print(f"  Still have {blocked_count} retriable blocked jobs — retrying...")
            continue

        if target is not None and target != "?" and total_jobs >= target:
            print(f"\n[DONE] Target reached: {total_jobs} jobs, {blocked_count} blocked.")
            return

        print(f"\n[DONE] {total_jobs} jobs.")
        return


if __name__ == "__main__":
    asyncio.run(main_loop())
