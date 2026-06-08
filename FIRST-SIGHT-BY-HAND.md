# First Sight by Hand

Welcome! This guide walks you through crawling job listings — no coding required.

The full step-by-step guide with screenshots and detailed explanations is inside the `v2/` folder:

## [v2/FIRST-SIGHT-BY-HAND.md](v2/FIRST-SIGHT-BY-HAND.md)

---

## Quick Start (5 minutes)

### 1. Install Python 3.10+
Download from [python.org](https://python.org) and check **"Add Python to PATH"**.

### 2. Navigate to the v2 folder
```bash
cd crawl-superpower-for-bros\v2
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
python -m cloakbrowser install
```

### 4. Fetch proxies (pick your country)
```bash
# Recommended: fetch and verify against your target site
python proxy/fetcher.py --country japan --site ekaigotenshoku --min-good 8 --timeout-geo 10 --timeout-tgt 15

# Or just fetch for a country
python proxy/fetcher.py --country japan
```

Supported: `vietnam`, `japan`, `china`, `south korea`, `singapore`, `russia`, `europe`, `india`, `usa`

> The fetcher auto-regenerates the cache if deleted. The crawler will also auto-fetch on first startup if no cache exists.

### 5. Start crawling
```bash
python main.py
```

You will be asked:
1. **Which country proxy?** (1-9, or 0 for no proxy)
2. **Does the site require authentication?** (Y/N)
3. **Clean start / Resume / Quit?** (C/R/Q — only if previous run exists)

---

## How the Agentic Crawl Works (Zero Manual Intervention)

Once started, the crawler runs **completely unattended**:

1. **Proxies die?** The crawler waits 60 seconds and auto-refetches fresh ones.
2. **Jobs get blocked?** They are retried automatically. Every 30 successful fetches, the crawler pauses to retry blocked jobs.
3. **Main crawl finishes?** A final infinite retry phase kicks in and loops until **all** blocked jobs are cleared.
4. **Power goes out?** Run the same command again and press **R** to resume exactly where you left off.
5. **Target reached?** The crawler saves results, prints a success message, and exits cleanly.

You can close your laptop and go to sleep — the tool will keep working.

---

## Optional Features

| Feature | How to enable |
|---------|---------------|
| **LLM smart enrichment** | Edit `v2/llm_config.yaml` — set `enabled: true` — fill API key |
| **Login automation** | Edit `v2/auth_config.yaml` — set `enabled: true` — fill credentials |
| **CAPTCHA avoidance** | Built-in automatic detection; for v3 sites use `--backend patchright` |
| **No proxy** | Select `0` at the country prompt |

---

## Full Documentation

- **Technical docs:** [v2/README.md](v2/README.md)
- **Beginner guide:** [v2/FIRST-SIGHT-BY-HAND.md](v2/FIRST-SIGHT-BY-HAND.md)
- **Roadmap:** [v2/PROJECT-ENHANCEMENT-SUGGESTION.md](v2/PROJECT-ENHANCEMENT-SUGGESTION.md)
