"""
Exporter — saves crawl results in multiple formats.

Outputs:
  - jobs.json   — Full structured data (all fields)
  - jobs.csv    — Tabular format for spreadsheet import
  - metadata.json — Run metadata (timestamp, proxy list, etc.)
  - output-final-json/ — One JSON file per job with mapped fields
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .site_mappings import SiteMapping
except ImportError:
    from site_mappings import SiteMapping  # type: ignore[no-redef]


def dedup(items: list[dict]) -> list[dict]:
    """Remove duplicate jobs by job_id or (title, company) pair."""
    seen: dict[Any, dict] = {}
    for it in items:
        key = it.get("job_id") or (it.get("title", ""), it.get("company", ""))
        seen[key] = it
    return list(seen.values())


def save_results(items: list[dict], run_dir: Path, state: dict,
                 mapping: SiteMapping) -> None:
    """Save raw results as JSON + CSV + metadata."""
    if not items:
        print("[WARN] No data to save.")
        return

    # JSON
    json_path = run_dir / "jobs.json"
    json_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV
    csv_path = run_dir / "jobs.csv"
    fields = ["job_id", "title", "company", "salary", "location", "jobType",
              "detail_url", "detail_html_path", "link", "page", "crawled_at",
              "proxy_used", "page_url", "page_html_path", "llm_enhanced"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)

    # Metadata
    pages_crawled = len([p for p in state.get("pages", []) if p])
    metadata = {
        "timestamp": run_dir.name.replace("run_", ""),
        "crawled_at": datetime.now().isoformat(),
        "site_name": mapping.display_name,
        "total_jobs": len(items),
        "pages_crawled": pages_crawled,
        "proxies_used": list(state.get("used_proxies", [])),
        "target_url": state.get("target_url", ""),
    }
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[SAVE] Results:")
    print(f"   JSON  -> {json_path}  ({len(items)} records)")
    print(f"   CSV   -> {csv_path}")
    print(f"   Meta  -> {metadata_path}")


def save_final_json(run_dir: Path, items: list[dict],
                    mapping: SiteMapping) -> None:
    """Save structured JSON output — one file per job.

    Creates output-final-json/ directory alongside the raw HTML folder.
    Each file is named job_{id}.json and contains the mapped fields
    defined in the site mapping's extraction config.
    """
    final_dir = run_dir / "output-final-json"
    final_dir.mkdir(parents=True, exist_ok=True)

    # Also save a combined file
    all_mapped: list[dict] = []

    for item in items:
        job_id = item.get("job_id", "unknown")
        mapped = {}
        # Preserve LLM-enhanced data if present
        if item.get("llm_enhanced"):
            mapped["llm_enhanced"] = item["llm_enhanced"]
        for field_name, field_def in mapping.fields.items():
            # field_def can be a source field name or a dict with transform
            if isinstance(field_def, str):
                mapped[field_name] = item.get(field_def)
            elif isinstance(field_def, dict):
                src = field_def.get("source", field_name)
                val = item.get(src)
                # Apply transform if specified
                transform = field_def.get("transform")
                if transform == "strip" and val:
                    val = val.strip()
                elif transform == "split_newline" and val:
                    val = val.split("\n")
                mapped[field_name] = val
            else:
                mapped[field_name] = item.get(field_name)

        # Add metadata
        mapped["_source_url"] = item.get("detail_url")
        mapped["_crawled_at"] = item.get("crawled_at")
        mapped["_proxy_used"] = item.get("proxy_used")

        # Save individual file
        out_path = final_dir / f"job_{job_id}.json"
        try:
            out_path.write_text(
                json.dumps(mapped, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            print(f"[WARN] Failed to save final JSON for job {job_id}: {e}")

        all_mapped.append(mapped)

    # Save combined file
    combined_path = final_dir / "all_jobs.json"
    combined_path.write_text(
        json.dumps(all_mapped, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"[SAVE] Final JSON -> {final_dir}  ({len(all_mapped)} files + all_jobs.json)")
