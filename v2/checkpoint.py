"""
Checkpoint management — crash-safe state persistence.

The checkpoint file tracks:
  - Which pages have been crawled
  - Which detail pages have been fetched
  - Blocked jobs and retry counts
  - Proxy usage history

This enables resume-from-crash: if the process dies mid-crawl,
the next run picks up exactly where it left off.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path


def extract_job_id(detail_url: str | None) -> str | None:
    """Extract numeric job ID from a detail URL like /kyujin/detail?id=299554."""
    if not detail_url:
        return None
    m = re.search(r'[?&]id=(\d+)', detail_url)
    return m.group(1) if m else None


def init_checkpoint(run_dir: Path, target_url: str, target_jobs: int | None,
                    block_threshold: int = 20) -> dict:
    """Create a fresh checkpoint state."""
    return {
        "version": 2,
        "target_url": target_url,
        "target_jobs": target_jobs,
        "block_threshold": block_threshold,
        "used_proxies": [],
        "current_proxy_idx": 0,
        "pages": [],
        "blocked_jobs": [],
        "total_jobs_extracted": 0,
        "updated_at": datetime.now().isoformat(),
    }


def load_checkpoint(run_dir: Path) -> dict | None:
    """Load checkpoint from disk. Returns None if not found or invalid."""
    path = run_dir / "checkpoint.json"
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("version") not in (1, 2):
            print(f"[WARN] Checkpoint version mismatch: {state.get('version')}")
            return None
        # Upgrade v1 -> v2
        if state.get("version") == 1:
            state["version"] = 2
            state.setdefault("block_threshold", 20)
        return state
    except Exception as e:
        print(f"[WARN] Checkpoint load error: {e}")
        return None


def save_checkpoint(run_dir: Path, state: dict) -> None:
    """Atomically save checkpoint (write to tmp, then rename)."""
    state["updated_at"] = datetime.now().isoformat()
    path = run_dir / "checkpoint.json"
    tmp = run_dir / "checkpoint.json.tmp"
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception as e:
        print(f"[WARN] Checkpoint save error: {e}")


def checkpoint_to_jobs(state: dict) -> list[dict]:
    """Flatten checkpoint pages into the job list format.

    Only includes jobs where detail_fetched is True.
    """
    out = []
    for pg in state.get("pages", []):
        if not pg:
            continue
        for job in pg.get("jobs", []):
            if not job.get("detail_fetched"):
                continue
            out.append({
                "job_id": job.get("job_id"),
                "title": job.get("title"),
                "company": job.get("company"),
                "salary": job.get("salary"),
                "location": job.get("location"),
                "jobType": job.get("jobType"),
                "detail_url": job.get("detail_url"),
                "detail_html_path": job.get("detail_html"),
                "link": job.get("detail_url"),
                "page": pg.get("page_num"),
                "page_url": pg.get("url"),
                "page_html_path": pg.get("list_html_path"),
                "crawled_at": job.get("crawled_at"),
                "proxy_used": pg.get("proxy_used"),
            })
    return out


def find_latest_incomplete_run(output_dir: Path) -> tuple[Path, dict] | None:
    """Find the most recent run with an incomplete checkpoint.

    Returns (run_dir, state) or None.
    """
    if not output_dir.exists():
        return None
    best: tuple[Path, dict] | None = None
    best_ts = ""
    for entry in output_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("run_"):
            continue
        ckpt_path = entry / "checkpoint.json"
        if not ckpt_path.exists():
            continue
        ts = entry.name.replace("run_", "")
        if ts > best_ts:
            try:
                state = json.loads(ckpt_path.read_text(encoding="utf-8"))
                target = state.get("target_jobs")
                extracted = state.get("total_jobs_extracted", 0)
                if target is not None and extracted >= target:
                    continue
                has_incomplete = False
                for pg in state.get("pages", []):
                    if not pg:
                        continue
                    if pg.get("status") != "complete":
                        has_incomplete = True
                        break
                    for job in pg.get("jobs", []):
                        if not job.get("detail_fetched"):
                            has_incomplete = True
                            break
                not_done = (target is None) or (extracted < target)
                if not_done or has_incomplete:
                    best = (entry, state)
                    best_ts = ts
            except Exception:
                pass
    return best
