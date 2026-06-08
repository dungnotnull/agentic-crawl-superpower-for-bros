# First Sight by Hand

Welcome! This guide walks you through crawling job listings — no coding required.

---

## What you need

| Thing | Why |
|-------|-----|
| A Windows/Mac/Linux computer | To run the tool |
| Python 3.10 or newer | Download from [python.org](https://python.org) |
| Google Chrome | Browser the tool uses internally |
| Internet connection | To fetch job data |

---

## Step 1 — Install Python

Go to [python.org](https://python.org), download the latest version, and run the installer.

**Important:** Check the box that says **"Add Python to PATH"** during installation.

Verify it worked:

```bash
python --version
```

You should see something like `Python 3.11.x`.

---

## Step 2 — Get the project

You already have the project folder. Open a terminal (Command Prompt, PowerShell, or Terminal) and navigate into it:

```bash
cd path\to\crawl-superpower-for-bros\v2
```

---

## Step 3 — Install dependencies

Run this one command:

```bash
pip install -r requirements.txt
```

Then install the browser engine:

```bash
python -m cloakbrowser install
```

This downloads a stealth Chromium browser with built-in fingerprint protection. It only needs to be done once.

---

## Step 4 — Set up proxies (first time only)

**What is this?** The tool can use IP addresses from different countries to access geo-restricted websites. This step finds free public proxies located in your target country.

```bash
# Recommended: fetch and verify against the target site
python proxy/fetcher.py --country japan --site ekaigotenshoku --min-good 8 --timeout-geo 10 --timeout-tgt 15

# Or just fetch for a country
python proxy/fetcher.py --country japan
```

Wait about 2-5 minutes. You will see it contacting different proxy providers, verifying each one. A successful run looks like:

```
========================================================================
  8 verified JP proxies (sorted by real score)
========================================================================
```

**Supported countries:**
- `vietnam`
- `japan`
- `china`
- `south korea`
- `singapore`
- `russia`
- `europe`
- `india`
- `usa`

If your target website does **not** block your IP, you can skip proxies entirely by selecting **"No need proxy"** in the next step.

> **Proxy cache auto-regeneration:** If you delete `japan_working_proxies.json`, the crawler will automatically recreate it on first startup.

---

## Step 5 — Start crawling

Run the main script:

```bash
python main.py
```

The terminal will ask you three simple questions:

### Question 1: Proxy country

```
  [PROXY] Select proxy country:
    (1) Vietnam
    (2) Japan
    (3) China
    (4) South Korea
    (5) Singapore
    (6) Russia
    (7) Europe
    (8) India
    (9) USA
    (0) No need proxy

  Enter choice [1-9, 0]:
```

- Pick the country where your target website is based, or where you want your IP to appear from.
- Pick `0` if the website does not block your real IP address.

### Question 2: Authentication

```
  [AUTH] Does this website require authentication? [Y/N]:
```

- Answer `Y` only if the site requires a login (like Shopee or LinkedIn).
- If you answer `Y`, the tool will read your login details from `auth_config.yaml` and log in automatically.
- For most public job sites, answer `N`.

### Question 3: Resume (only if you have a previous run)

```
  [START] (C)lean start / (R)esume / (Q)uit? [C/R/Q]:
```

- **C** = delete everything and start fresh
- **R** = continue where you left off
- **Q** = exit

---

### After the questions

The tool starts crawling automatically. You will see real-time progress:

```
  00:15 [FOUND] Job #1/20: ID=299554 "介護スタッフ(正社員)"
  00:19 [SAVED] Job 299554 "介護スタッフ(正社員)" -> 1/100 jobs (1%)
```

### Useful command-line options

| Command | What it does |
|---------|-------------|
| `python main.py --target-jobs 240` | Stop after 240 jobs |
| `python main.py --max-pages 10` | Only crawl 10 listing pages per proxy |
| `python main.py --clean` | Delete all previous results and start fresh |
| `python main.py --no-headless` | Show the browser window (for debugging) |
| `python main.py --bayesian` | Use smart proxy scoring |
| `python main.py --backend patchright` | Use Patchright browser (for sites with reCAPTCHA v3) |

---

## Step 6 — Watch progress

### Terminal

The terminal shows real-time logs with job IDs, progress percentages, and elapsed time.

You may also see these messages — they are normal and handled automatically:

| Message | What it means |
|---------|-------------|
| `No proxies available — waiting 60s` | All proxies are dead. The tool will auto-refetch and retry. **Do not stop it.** |
| `Mid-crawl retry triggered after 30 detail fetches` | The tool is pausing to retry previously blocked jobs. It will resume automatically. |
| `FINAL RETRY PHASE - 5 blocked/retrying jobs to retry` | Main crawl is done. The tool is now doing a final pass to clear all blocked jobs. |
| `All blocked jobs retried successfully` | All jobs are cleared. The tool will save results and exit. |

### Live Dashboard

While the crawl runs, open your browser and go to:

```
http://localhost:3001
```

You will see a dashboard showing crawled jobs, HTML previews, and progress stats. The dashboard starts automatically — no extra commands needed.

---

## Step 7 — Find your results

After the crawl finishes, the results are saved in the `output/` folder:

```
output/
  run_20260606_123000/
    jobs.json              <- All jobs in one file
    jobs.csv               <- Open in Excel/Google Sheets
    output-final-json/     <- One clean JSON file per job
    html/detail/           <- Original saved web pages
    blocked_jobs.json      <- Jobs that could not be fetched (should be empty after final retry)
```

### Opening in Excel

Double-click `jobs.csv` or import it:

1. Open Excel
2. **Data** > **From Text/CSV**
3. Select `output/run_*/jobs.csv`
4. Set encoding to **UTF-8**
5. Click **Load**

---

## What the Tool Does About CAPTCHAs

When crawling, some websites may show a CAPTCHA (a puzzle that asks "are you human?"). The tool handles this automatically:

1. **The built-in stealth browser (CloakBrowser)** makes your browser look like a real person — random fingerprints, human-like mouse movements, matching timezone. This prevents many CAPTCHAs from appearing in the first place.

2. **If a CAPTCHA does appear**, the tool detects it and:
   - Stops using that proxy immediately
   - Moves to the next available proxy
   - Logs the event so you can see it in the terminal

3. **For sites with reCAPTCHA v3** (invisible scoring), you can use the Patchright browser:
   ```bash
   python main.py --backend patchright
   ```

You do not need to do anything else — CAPTCHA handling is fully automatic.

---

## Optional: LLM Integration (Smart Data Enrichment)

If you want the tool to automatically send each crawled page to an AI (like ChatGPT, Claude, or Gemini) and extract extra structured information:

1. Open `llm_config.yaml`
2. Change `enabled: false` to `enabled: true`
3. Paste your API key into `api_key: "YOUR_API_KEY_HERE"`
4. Set `base_url` and `model` to match your provider
5. Customize the `prompt` if you want
6. Run `python main.py` as normal

The AI-extracted data will appear inside each job's JSON file under the key `llm_enhanced`.

> **Your API key stays on your computer.** The tool runs entirely locally.

---

## Optional: Authentication (Protected Websites)

If the website you want to crawl requires a login:

1. Open `auth_config.yaml`
2. Change `enabled: false` to `enabled: true`
3. Fill in:
   - `login_url` — the website's login page address
   - `username` — your email or username
   - `password` — your password
   - `username_selector` — the CSS selector for the username field (use browser DevTools to find it)
   - `password_selector` — the CSS selector for the password field
   - `submit_selector` — the CSS selector for the login button
4. Run `python main.py` and answer **Y** when asked about authentication

The tool will:
- Log in automatically (with up to 3 retry attempts if login fails)
- Check if your session is still active before each page
- Re-log in automatically if your session expires
- Skip the proxy if login fails after all retries

---

## Resuming after a crash

If the tool crashes (power outage, laptop sleep, etc.), just run the same command again:

```bash
python main.py --target-jobs 240
```

The tool will ask:

```
[C]lean start / [R]esume / [Q]uit? [C/R/Q]:
```

Press **R** to continue where you left off. All progress is auto-saved after every job.

---

## When things go wrong

| Problem | Solution |
|---------|----------|
| **"No proxies available"** | The tool auto-refetches after 60 seconds. Just wait. Or run `python proxy/fetcher.py --country {your_country}` first. |
| **"No content at page"** | The proxies are blocked — the tool automatically switches to the next proxy. Just wait. |
| **Crawl seems stuck** | It is not. When proxies run out, the tool waits 60 seconds and tries again. It will never give up. |
| **Japanese text shows as ???** | Use **Windows Terminal** instead of Command Prompt, or type `chcp 65001` before running. |
| **Dashboard shows nothing** | Data appears as jobs are crawled. Wait for the first few jobs to complete. |
| **Blocked jobs** | Some jobs get blocked by the website. The tool retries them every 30 fetches, then clears them all in the final phase. This is normal. |
| **[CAPTCHA] detected** | The website showed a CAPTCHA. The tool will switch to a new proxy. For v3 CAPTCHAs, try `--backend patchright`. |
| **"Does this website require authentication?"** | Answer **N** for public sites. Answer **Y** only for sites with login walls. |
| **Duplicate jobs in output** | Fixed in the latest version — `job_id` is normalized to string everywhere. Update to the latest code if you see this. |

---

## Quick reference card

```bash
# One-time setup
pip install -r requirements.txt
python -m cloakbrowser install
python proxy/fetcher.py --country japan --site ekaigotenshoku --min-good 8 --timeout-geo 10 --timeout-tgt 15

# Start crawling (interactive prompts)
python main.py

# Start crawling with options
python main.py --target-jobs 240

# For sites with reCAPTCHA v3
python main.py --backend patchright --target-jobs 240

# View live dashboard
# Open: http://localhost:3001

# Resume after crash
python main.py --target-jobs 240
# Press R when asked
```

---

## What to fill in

The only things you need to decide are:

- **Which country proxy?** (or `0` for no proxy)
- **Does the site need login?** (Y/N)
- **How many jobs do you want?** (`--target-jobs N`)

Everything else has sensible defaults. You do not need to configure anything unless you want to.

---

## Need help?

- `python main.py --help` — shows all available options
- `python proxy/fetcher.py --help` — shows proxy fetching options
- The dashboard at `http://localhost:3001` shows real-time crawl status
- Check `blocked_jobs.json` after a run to see if any jobs could not be fetched
