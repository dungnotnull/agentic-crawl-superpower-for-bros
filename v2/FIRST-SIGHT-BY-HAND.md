# First Sight by Hand

Welcome! This guide walks you through crawling Japanese job listings — no coding required.

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

This downloads Chrome's automation driver. It only needs to be done once.

---

## Step 4 — Set up proxies (first time only)

**What is this?** The tool needs Japanese IP addresses to access Japanese job sites. This step finds free public proxies located in Japan.

```bash
python proxy/fetcher.py
```

Wait about 2-5 minutes. You'll see it contacting different proxy providers, verifying each one. A successful run looks like:

```
========================================================================
  8 verified JP proxies (sorted by real score)
========================================================================
```

If you want proxies for a different site later, run:

```bash
python proxy/fetcher.py --site YOUR_SITE_NAME
```

---

## Step 5 — Start crawling

### Basic crawl (target a number of jobs)

```bash
python main.py --target-jobs 100
```

This crawls until 100 unique jobs are collected. Replace `100` with whatever number you need.

### Crawl without limits

```bash
python main.py
```

This crawls until all available pages are exhausted.

### Other useful options

| Command | What it does |
|---------|-------------|
| `--target-jobs 240` | Stop after 240 jobs |
| `--max-pages 10` | Only crawl 10 listing pages per proxy |
| `--bayesian` | Use smart proxy scoring with Bayesian prediction |
| `--clean` | Delete all previous results and start fresh |
| `--no-headless` | Show the browser window (for debugging) |

---

## Step 6 — Watch progress

Once the crawl starts, the terminal shows real-time progress:

```
  00:15 [FOUND] Job #1/20: ID=299554 "介護職員（正社員）"
  00:19 [SAVED] Job 299554 "介護職員（正社員）" -> 1/100 jobs (1%)
```

### Live Dashboard

While the crawl runs, open your browser and go to:

```
http://localhost:3001
```

You'll see a dashboard showing crawled jobs, HTML previews, and progress stats. The dashboard starts automatically — no extra commands needed.

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
```

### Opening in Excel

Double-click `jobs.csv` or import it:

1. Open Excel
2. **Data** > **From Text/CSV**
3. Select `output/run_*/jobs.csv`
4. Set encoding to **UTF-8**
5. Click **Load**

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
| **"No proxies available"** | Re-run `python proxy/fetcher.py` |
| **"No JP content at page"** | The proxies are blocked — the tool automatically switches to the next proxy. Just wait. |
| **Crawl seems stuck** | It's not. When proxies run out, the tool waits 60 seconds and tries again. It will never give up. |
| **Japanese text shows as ???** | Use **Windows Terminal** instead of Command Prompt, or type `chcp 65001` before running. |
| **Dashboard shows nothing** | Data appears as jobs are crawled. Wait for the first few jobs to complete. |
| **Blocked jobs** | Some jobs get blocked by the website. The tool retries 20 times, then logs them in `blocked_jobs.json`. This is normal. |

---

## Quick reference card

```bash
# One-time setup
pip install -r requirements.txt
python -m cloakbrowser install
python proxy/fetcher.py

# Start crawling (default)
python main.py --target-jobs 240

# Start crawling with Bayesian scoring
python main.py --bayesian --target-jobs 240

# View live dashboard
# Open: http://localhost:3001

# Resume after crash
python main.py --target-jobs 240
# Press R when asked
```

---

## What to fill in

The only things you need to decide are:

- **How many jobs do you want?** (`--target-jobs N`)
- **Use Bayesian scoring?** (`--bayesian`) — optional, for smarter proxy selection on long runs

Everything else has sensible defaults. You don't need to configure anything unless you want to.

---

## Need help?

- `python main.py --help` — shows all available options
- `python proxy/fetcher.py --help` — shows proxy fetching options
- The dashboard at `http://localhost:3001` shows real-time crawl status
