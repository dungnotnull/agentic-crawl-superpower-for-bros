<div align="center">

# Crawl-Superpower-for-Bros

**Modular, never-stop web crawler for any site, any country, any scale**

*Built for days-long unattended runs with zero manual intervention*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Proxy Providers](https://img.shields.io/badge/Proxy%20Providers-14-orange?style=for-the-badge)](v2/proxy/fetcher.py)
[![Multi-Site](https://img.shields.io/badge/Multi--Site-YAML%20Driven-9cf?style=for-the-badge)](v2/sites/)
[![Multi-Country](https://img.shields.io/badge/Multi--Country-9%2B%20Regions-blue?style=for-the-badge)](v2/proxy/fetcher.py)
[![LLM Ready](https://img.shields.io/badge/LLM%20Integration-Ready-purple?style=for-the-badge)](v2/llm_config.yaml)
[![CAPTCHA Aware](https://img.shields.io/badge/CAPTCHA-Detection%20%26%20Avoidance-yellow?style=for-the-badge)](v2/crawler.py)

---

</div>

## What It Does

Crawl-Superpower-for-Bros is a **production-grade** web scraper designed to crawl job listing sites (or any structured data site) through **rotating country-specific proxies** with **zero manual intervention**.

> **Core guarantee: The crawl loop never stops prematurely.**

- **Multi-country proxy support**: Vietnam, Japan, China, South Korea, Singapore, Russia, Europe, India, USA — or run without proxy entirely
- **14 free proxy providers** aggregated into one pool
- **Crash-safe checkpointing**: resume exactly where you left off
- **CAPTCHA detection & avoidance**: detects reCAPTCHA, hCaptcha, Cloudflare Turnstile; switches proxies automatically
- **CloakBrowser stealth**: fingerprint randomization, humanized behavior, geoIP matching, Patchright backend for reCAPTCHA v3
- **Optional LLM integration**: enrich every job with AI-extracted structured data (Claude, GPT, Gemini, Groq, Ollama)
- **Optional authentication layer**: auto-login with retry/backoff, session health checks, re-auth on cookie expiry
- **Never-stop loop**: waits for proxies, retries blocked jobs, runs until your target is met

## Quick Start

```bash
cd v2
pip install -r requirements.txt
python -m cloakbrowser install

# Fetch proxies for your target country
python proxy/fetcher.py --country japan

# Start crawling with interactive prompts
python main.py
```

When you run `python main.py`, the terminal will ask:
1. **Which country proxy?** (1-9 + 0 for no proxy)
2. **Does the site require authentication?** (Y/N)
3. **Clean start / Resume / Quit?** (if a previous run exists)

## Detailed Documentation

- **[v2/README.md](v2/README.md)** — Full technical documentation, architecture, configuration reference
- **[v2/FIRST-SIGHT-BY-HAND.md](v2/FIRST-SIGHT-BY-HAND.md)** — Step-by-step beginner guide, no coding required
- **[v2/PROJECT-ENHANCEMENT-SUGGESTION.md](v2/PROJECT-ENHANCEMENT-SUGGESTION.md)** — Roadmap and completed enhancements

## Key Features

| Feature | Status |
|---------|--------|
| Never-stop crawl loop | Ready |
| 14 proxy providers | Ready |
| Multi-country proxy selection (9 regions) | Ready |
| No-proxy bypass mode | Ready |
| Crash-safe checkpointing & resume | Ready |
| Block tracking & retry | Ready |
| YAML-driven multi-site support | Ready |
| Real-time logging & dashboard | Ready |
| CAPTCHA detection & proxy avoidance | Ready |
| Browser backend selection (playwright/patchright) | Ready |
| Bayesian proxy scoring | Ready |
| Rate limiting adaptation | Ready |
| **LLM API integration** | Ready (opt-in via `llm_config.yaml`) |
| **Authentication automation** | Ready (opt-in via `auth_config.yaml`) |

## License

[MIT](LICENSE) — Use freely, modify freely, crawl freely.

---

<div align="center">

**Built for the bros who need data**

</div>
