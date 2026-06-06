"""
Authentication Manager - Dynamic login automation for protected websites.

Reads auth_config.yaml and automates the login flow using CloakBrowser.
Supports session validation and automatic re-authentication on disconnect.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

AUTH_CONFIG_PATH = Path(__file__).parent / "auth_config.yaml"


def load_auth_config() -> dict[str, Any] | None:
    """Load authentication configuration from auth_config.yaml."""
    if not AUTH_CONFIG_PATH.exists():
        return None
    if yaml is None:
        print("  [AUTH] PyYAML not installed; cannot load auth_config.yaml")
        return None
    try:
        data = yaml.safe_load(AUTH_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if not data.get("enabled", False):
            return None
        # Validate required fields
        for key in ("login_url", "username", "password",
                    "username_selector", "password_selector", "submit_selector"):
            if not data.get(key):
                print(f"  [AUTH] Missing required field: {key}")
                return None
        return data
    except Exception as e:
        print(f"  [AUTH] Failed to load auth config: {e}")
        return None


def is_auth_configured() -> bool:
    """Return True if auth_config.yaml exists and is enabled."""
    return load_auth_config() is not None


async def _find_element(page, selectors: str, timeout: float = 8.0):
    """Try multiple comma-separated selectors and return the first match."""
    for sel in selectors.split(","):
        sel = sel.strip()
        if not sel:
            continue
        try:
            el = await page.query_selector(sel)
            if el:
                return el
        except Exception:
            pass
    # Fallback: wait for the first selector
    first = selectors.split(",")[0].strip()
    if first:
        try:
            await page.wait_for_selector(first, timeout=int(timeout * 1000))
            return await page.query_selector(first)
        except Exception:
            pass
    return None


async def authenticate(page, auth_config: dict[str, Any]) -> bool:
    """
    Perform automated login on the given page.

    Steps:
      1. Navigate to login_url
      2. Fill username field
      3. Fill password field
      4. Click submit button
      5. Wait for navigation / success indicator
    """
    login_url = auth_config["login_url"]
    username = auth_config["username"]
    password = auth_config["password"]
    post_wait = auth_config.get("post_submit_wait", 5.0)
    success_fragment = auth_config.get("success_url_fragment", "")

    try:
        print(f"  [AUTH] Navigating to login page: {login_url}")
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1.5)

        # Fill username
        user_el = await _find_element(page, auth_config["username_selector"])
        if not user_el:
            print("  [AUTH] Username field not found - check username_selector")
            return False
        await user_el.fill(username)
        print("  [AUTH] Username entered")

        # Fill password
        pass_el = await _find_element(page, auth_config["password_selector"])
        if not pass_el:
            print("  [AUTH] Password field not found - check password_selector")
            return False
        await pass_el.fill(password)
        print("  [AUTH] Password entered")

        # Click submit
        submit_el = await _find_element(page, auth_config["submit_selector"])
        if not submit_el:
            print("  [AUTH] Submit button not found - check submit_selector")
            return False
        await submit_el.click()
        print("  [AUTH] Submit clicked")

        # Wait for result
        await asyncio.sleep(post_wait)
        await page.wait_for_load_state("networkidle", timeout=20000)

        current_url = page.url
        if success_fragment and success_fragment in current_url:
            print(f"  [AUTH] Login success detected (URL contains '{success_fragment}')")
            return True
        if success_fragment:
            print(f"  [AUTH] Warning: success fragment '{success_fragment}' not in URL: {current_url}")
        else:
            print(f"  [AUTH] Login submitted (current URL: {current_url})")
        return True

    except Exception as e:
        print(f"  [AUTH] Login automation error: {type(e).__name__}: {e}")
        return False


async def is_authenticated(page, auth_config: dict[str, Any]) -> bool:
    """
    Check if the current page state indicates an active session.

    Uses logged_in_indicator selector if provided; otherwise falls back
    to checking whether the current URL still contains the login page path.
    """
    indicator = auth_config.get("logged_in_indicator", "")
    login_url = auth_config.get("login_url", "")
    try:
        current_url = page.url
        if login_url and login_url in current_url:
            return False
        if indicator:
            for sel in indicator.split(","):
                sel = sel.strip()
                if not sel:
                    continue
                el = await page.query_selector(sel)
                if el:
                    return True
            return False
        return True
    except Exception:
        return False


async def ensure_authenticated(page, auth_config: dict[str, Any]) -> bool:
    """
    Ensure the page is authenticated. If not, perform login.
    Call this before critical navigations to protected content.
    """
    if await is_authenticated(page, auth_config):
        return True
    print("  [AUTH] Session not detected - re-authenticating...")
    return await authenticate(page, auth_config)
