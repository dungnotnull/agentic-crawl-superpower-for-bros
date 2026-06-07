"""
LLM API Integration Layer - Boilerplate / Skeleton

Purpose:
  Enable automated smart mapping or intelligent querying to generate
  structured output directly from raw HTML crawled by the system.

How to use:
  1. Open llm_config.yaml in this directory.
  2. Set enabled: true
  3. Fill in your api_key, base_url, and model.
  4. Customize the prompt template to suit your extraction needs.
  5. Run main.py as usual. If the LLM config is valid, each crawled
     HTML dataset will be transparently enhanced with LLM output.

Security note:
  Since the entire codebase runs locally, your API key never leaves
  your machine except when calling the LLM endpoint you specify.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

LLM_CONFIG_PATH = Path(__file__).parent / "llm_config.yaml"


def _safe_print(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(msg.encode("utf-8", errors="replace") + b"\n")
        sys.stdout.flush()


def load_llm_config() -> dict[str, Any]:
    """Load LLM configuration from llm_config.yaml."""
    if not LLM_CONFIG_PATH.exists():
        return {}
    if yaml is None:
        _safe_print("  [LLM] PyYAML not installed; cannot load llm_config.yaml")
        return {}
    try:
        data = yaml.safe_load(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        _safe_print(f"  [LLM] Failed to load LLM config: {e}")
        return {}


def is_configured() -> bool:
    """
    Return True only if the user has explicitly enabled the LLM layer
    AND provided all required fields (api_key, base_url, prompt).
    """
    cfg = load_llm_config()
    if not cfg.get("enabled", False):
        return False
    required = ("api_key", "base_url", "prompt")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        _safe_print(f"  [LLM] Config missing fields: {', '.join(missing)} - skipping LLM layer")
        return False
    # Prevent boilerplate placeholders from accidentally triggering calls
    api_key = cfg.get("api_key", "")
    if api_key in ("YOUR_API_KEY_HERE", "YOUR-API-KEY", ""):
        _safe_print("  [LLM] API key is still the placeholder - skipping LLM layer")
        return False
    return True


def _call_llm_api(payload: dict, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """
    Synchronous helper to call the LLM API.
    Users can replace this method with their own SDK (Anthropic, Google, etc.)
    or keep the generic OpenAI-compatible REST approach below.
    """
    import requests  # requests is already used by the proxy fetcher

    base_url = cfg["base_url"].rstrip("/")
    api_key = cfg["api_key"]
    model = cfg.get("model", "gpt-4o-mini")
    max_tokens = cfg.get("max_tokens", 2048)
    temperature = cfg.get("temperature", 0.2)

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You extract structured data from HTML and return only valid JSON."},
            {"role": "user", "content": payload["prompt"]},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        return json.loads(content)
    except requests.RequestException as e:
        _safe_print(f"  [LLM] API request failed: {type(e).__name__}: {e}")
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        _safe_print(f"  [LLM] Failed to parse API response: {e}")
        return None


async def process_html(html_content: str, job: dict[str, Any]) -> dict[str, Any] | None:
    """
    Send raw HTML to the configured LLM API and return structured data.

    Args:
        html_content: Raw HTML string from the crawled detail page.
        job: Dictionary of already-extracted job fields (title, company, etc.).

    Returns:
        Parsed JSON dict from the LLM, or None if disabled / failed.
    """
    cfg = load_llm_config()
    if not cfg.get("enabled", False):
        return None

    prompt_template = cfg.get("prompt", "")
    max_html_chars = cfg.get("max_html_chars", 8000)

    # Truncate HTML to stay within token limits
    truncated_html = html_content[:max_html_chars]
    if len(html_content) > max_html_chars:
        truncated_html += "\n...[truncated]"

    fields_json = json.dumps(job, ensure_ascii=False, default=str)

    prompt = prompt_template.format(
        html=truncated_html,
        job_title=job.get("title", ""),
        job_url=job.get("detail_url", ""),
        fields=fields_json,
    )

    payload = {"prompt": prompt}

    # Run the blocking HTTP call in a thread so we don't block the event loop
    import asyncio
    result = await asyncio.to_thread(_call_llm_api, payload, cfg)
    return result
