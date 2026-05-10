# Trustpilot Business Scraper

**Production-grade Python scraper — extracts business contact data (email, phone, website, postcode, category) from any Trustpilot search query and saves to Excel.**

> **⚠️ Not a review scraper.** This tool extracts business *contact data* — email, phone, website, postcode — from Trustpilot *search results* for B2B lead generation. If you need Trustpilot review text, star ratings, or sentiment data, this is the wrong repo.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://claude.ai/chat/LICENSE)
[![CI](https://github.com/FAAQJAVED/trustpilot-business-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/FAAQJAVED/trustpilot-business-scraper/actions)
[![Version](https://img.shields.io/badge/version-1.2.0-brightgreen)](https://claude.ai/chat/CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-121%20passing-brightgreen)](https://claude.ai/chat/tests/test_modules.py)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/FAAQJAVED/trustpilot-business-scraper)

> Found this useful? A ⭐ on GitHub helps other developers find it.

---

## Table of Contents

* [Preview](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#preview)
* [What It Does](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#what-it-does)
* [Use Cases](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#use-cases)
* [How It Works](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#how-it-works)
* [Features](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#features)
* [Performance](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#performance)
* [What Data You Get](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#what-data-you-get)
* [Quick Start](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#quick-start)
* [Configuration](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#configuration)
* [Usage](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#usage)
* [CLI Reference](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#cli-reference)
* [Output](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#output)
* [Tech Stack](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#tech-stack)
* [Project Structure](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#project-structure)
* [Troubleshooting](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#troubleshooting)
* [B2B Lead Toolkit](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#part-of-the-b2b-lead-toolkit)
* [License](https://claude.ai/chat/db5cacdc-a2ff-4268-bb9c-daa595946c1d#license)

---

## Preview

| Terminal — tqdm progress bar                                           | Excel Output                                                    |
| ----------------------------------------------------------------------- | --------------------------------------------------------------- |
| ![Terminal progress](https://claude.ai/chat/Assets/terminal_progress.png) | ![Excel output](https://claude.ai/chat/Assets/output_preview.png) |

---

## What It Does

Point it at any Trustpilot search query — `"accountants in Manchester"`, `"solicitors in London"`, `"estate agents in Leeds"` — and it extracts every matching business's contact details and saves them to a dated Excel file.

It uses a hybrid architecture: **Selenium** reads JavaScript-rendered search result pages directly from the Chrome DOM, while a **parallel HTTP thread pool** fetches individual company profile pages up to 10× faster than browser navigation alone. All field extraction is config-driven — `config.json` is the single source of truth for every path, URL, and cleaning rule. Zero Trustpilot-specific logic exists anywhere in the Python code.

---

## Use Cases

| Who uses it                  | What they do                                                                                                                      |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Sales teams**        | Build targeted outreach lists —`"accountants in Manchester"`→ 200+ verified businesses with email and phone in one Excel file |
| **Marketing agencies** | Deliver fresh, structured prospect data for any UK or EU industry vertical without paying a data provider                         |
| **Market researchers** | Map an entire service category in a city in minutes — trust scores, review counts, and contact data in one sheet                 |
| **CRM admins**         | Enrich and validate existing contact records against live Trustpilot data                                                         |
| **Recruiters**         | Identify hiring employers in a target sector and geography using trust score as a company health signal                           |
| **Freelance lead gen** | Run overnight scrapes for clients and deliver clean Excel files ready to import into any CRM                                      |

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  BROWSER (Selenium + Chrome)                                    │
│                                                                 │
│  search URL ──► Chrome DOM ──► __NEXT_DATA__ JSON              │
│                                ├── listings[] (10 per page)    │
│                                └── pagination.totalResults     │
└──────────────────────────────┬──────────────────────────────────┘
                               │  slugs extracted per page
┌──────────────────────────────▼──────────────────────────────────┐
│  HTTP THREAD POOL (requests + ThreadPoolExecutor)               │
│                                                                 │
│  slug[] ──► 10 parallel HTTP GET ──► profile HTML              │
│                  │ retry + exponential back-off                 │
│                  ▼                                              │
│             __NEXT_DATA__ ──► email, phone, website,           │
│                               postcode, city, score, reviews    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  OUTPUT                                                         │
│  Trustpilot_YYYYMMDD.xlsx  (Data sheet + Summary sheet)        │
│  Trustpilot_YYYYMMDD.log   (rotating, 5 MB max, 3 backups)     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

| Feature                                    | Detail                                                                                                                              |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| **Parallel profile fetching**        | `ThreadPoolExecutor`fetches all profiles on a page concurrently — configurable thread count, hard wall-clock timeout per request |
| **Retry with exponential back-off**  | Failed HTTP requests retried up to N times with doubling delays — handles transient rate limiting gracefully                       |
| **Checkpoint / resume**              | Progress saved to `scraper_checkpoint.json`after every page — re-run anytime to continue. Use `--fresh`to start over           |
| **tqdm progress bar**                | Live page-level progress bar showing total pages, current page, and running record count. Graceful no-op shim if tqdm not installed |
| **Cross-platform keyboard controls** | P=pause · R=resume · Q=quit · S=status via `pynput`. Falls back to `command.txt`polling if pynput is unavailable             |
| **Structured file logging**          | Rotating log file alongside the Excel output — full audit trail for unattended or overnight runs                                   |
| **Excel output + Summary sheet**     | Dated `.xlsx`with styled Data sheet and Summary sheet showing query, duration, record counts, and coverage percentages            |
| **Cycling detection**                | Stops cleanly if duplicate slug loops are detected (< 2 new results from ≥ 5 listings) — not a crash, it's a guard                |
| **Audio completion feedback**        | `winsound`beep sequence on Windows when a run finishes — silently skipped on macOS/Linux                                         |
| **`--stats`flag**                  | Print record counts from an existing output file and exit — no Chrome or Selenium required                                         |
| **Config-driven**                    | Zero Trustpilot-specific strings in Python code — every field path, URL, and cleaning rule lives in `config.json`                |

---

## Performance

Typical figures on a standard UK broadband connection:

| Query size                               | Pages        | Companies          | Time       |
| ---------------------------------------- | ------------ | ------------------ | ---------- |
| Small (`dentists in Leeds`)            | 3–8 pages   | 20–60 companies   | 3–8 min   |
| Medium (`estate agents in Manchester`) | 10–25 pages | 80–200 companies  | 10–25 min |
| Large (`accountants in London`)        | 30–60 pages | 250–500 companies | 30–60 min |

Profile fetching runs in parallel (10 threads by default). The bottleneck is page navigation (~2.5 s per page), not profile fetching.

> **Real run:** `estate agents` — 47 pages,  **418 companies** , 9m 32s. 388 with email (93%), 342 with phone (82%), 418 with website (100%).

---

## What Data You Get

One row per business. Here is a real example from a live Trustpilot search:

| Field        | Example                      |
| ------------ | ---------------------------- |
| Company Name | Ryder & Dutton Estate Agents |
| Email        | enquiries@ryderdutton.co.uk  |
| Phone        | 0161 925 3255                |
| Website      | https://ryderdutton.co.uk    |
| Postcode     | OL2 6HT                      |
| City         | Oldham                       |
| Trust Score  | 4.9                          |
| Reviews      | 4014                         |
| Category     | Real Estate Agency           |
| Source       | Trustpilot                   |

See [`Assets/sample_output.csv`](https://claude.ai/chat/Assets/sample_output.csv) for 10 rows of realistic sample output.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your search query

Open `config.json` and update the `search_query` field:

```json
"query": {
    "search_query": "accountants in Manchester"
}
```

See [docs/finding_your_search_query.md](https://claude.ai/chat/docs/finding_your_search_query.md) for tips on choosing a good query.

### 3. Run

```bash
python scraper.py
```

Chrome will open automatically. Press **Enter** in the terminal when the first search results page has loaded.

---

## Configuration

Only three sections in `config.json` require user attention — everything else is pre-configured for Trustpilot.

### `query.search_query`

The Trustpilot search term to scrape. Override at runtime with `--query` without editing the file.

### `scraping`

| Key                 | Default | Description                                                   |
| ------------------- | ------- | ------------------------------------------------------------- |
| `profile_threads` | `10`  | Parallel HTTP threads per page                                |
| `page_delay`      | `2.5` | Seconds between page loads                                    |
| `stop_at`         | `""`  | Auto-stop time in `HH:MM`format (empty = run to completion) |

### `browser.chrome_paths`

List of Chrome executable paths tried in order. Add your system's path if Chrome is installed in a non-standard location.

---

## Usage

```bash
# Basic run (uses config.json search query)
python scraper.py

# Override search query at runtime
python scraper.py --query "solicitors in Edinburgh"

# Start fresh — discard checkpoint
python scraper.py --fresh

# Run with more threads and an auto-stop time
python scraper.py --threads 15 --stop-at 23:00

# Check existing output file without launching Chrome
python scraper.py --stats
```

### Runtime Controls

While running, use these keys (requires `pynput`) or write commands to `command.txt`:

| Key / Command    | Action                           |
| ---------------- | -------------------------------- |
| `P`/`pause`  | Pause the scrape loop            |
| `R`/`resume` | Resume the scrape loop           |
| `Q`/`stop`   | Quit cleanly and save checkpoint |
| `S`/`status` | Print current progress           |

---

## CLI Reference

| Flag                | Description                                                                     |
| ------------------- | ------------------------------------------------------------------------------- |
| `--query TEXT`    | Override `search_query`from `config.json`for this run                       |
| `--config FILE`   | Use a different config file instead of `config.json`                          |
| `--threads N`     | Override `profile_threads`(parallel HTTP workers)                             |
| `--fresh`         | Discard any existing checkpoint and start from page 1                           |
| `--resume`        | Explicitly resume from checkpoint (default behaviour)                           |
| `--stop-at HH:MM` | Auto-quit at a specific time of day                                             |
| `--stats`         | Print record counts from the existing output file and exit — no browser needed |

---

## Output

**Excel file:** `Trustpilot_YYYYMMDD.xlsx`

* **Data sheet** — one row per company: Company Name, Email, Phone, Website, Postcode, City, Trust Score, Reviews, Category, Source.
* **Summary sheet** — query, duration, total records, contact data coverage percentages, run status.

**Log file:** `Trustpilot_YYYYMMDD.log`

Rotating log file (max 5 MB, 3 backups) recording all INFO and DEBUG events.

---

## Tech Stack

| Library               | Purpose                                                       |
| --------------------- | ------------------------------------------------------------- |
| `selenium`          | Controls Chrome via remote debugging — reads JS-rendered DOM |
| `requests`          | Parallel HTTP fetching of company profile pages               |
| `openpyxl`          | Writes and reads the Excel output file                        |
| `pynput`            | Cross-platform keyboard listener (P/R/Q/S controls)           |
| `webdriver-manager` | Auto-downloads the correct ChromeDriver version               |
| `urllib3`           | HTTP connection pooling (bundled with requests)               |
| `tqdm`              | Page-level progress bar (graceful no-op if not installed)     |

---

## Project Structure

```
trustpilot-business-scraper/
├── scraper.py              # Entry point — CLI, orchestration, main loop
├── config.json             # All platform and scraping settings
├── requirements.txt        # Python dependencies
├── Assets/
│   ├── terminal_progress.png   # Screenshot — tqdm bar in action
│   ├── output_preview.png      # Screenshot — Excel output
│   └── sample_output.csv       # 10 rows of realistic sample data
├── docs/
│   └── finding_your_search_query.md
├── configs/
│   └── README.md                   ← reserved for future query presets
├── tests/
│   └── test_modules.py     # 121 tests — pytest
└── modules/
    ├── browser.py          # Chrome launch, Selenium connection, cookie extraction
    ├── checkpoint.py       # Atomic checkpoint save / load / clear
    ├── controls.py         # Cross-platform keyboard + command file controls
    ├── extractor.py        # __NEXT_DATA__ path resolver and field extractor
    ├── fetcher.py          # Parallel HTTP fetcher with retry and back-off
    ├── logger.py           # Rotating file + stdout logging setup
    ├── output.py           # Excel write / load / summary sheet
    └── parser.py           # Phone normalisation, postcode extraction, record assembly
```

---

## Troubleshooting

**Chrome not found** — Add your Chrome executable path to `browser.chrome_paths` in `config.json`.

**Scraper stops early** — This is the cycling detection guard: if fewer than 2 new slugs are found across 5 or more consecutive listings, the scraper infers it has reached a duplicate loop and stops cleanly. This is correct behaviour on queries with fewer results than expected.

**Rate limited** — Reduce `profile_threads` to `5` and increase `page_delay` to `4.0` in `config.json`.

**Resume not working** — If the search query has changed since the last run, use `--fresh` to clear the old checkpoint.

---

## Part of the B2B Lead Toolkit

| Repo                                                                                                             | What it does                                                |
| ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **[Trustpilot Business Scraper](https://github.com/FAAQJAVED/trustpilot-business-scraper)**←*you are here* | Extracts business listings from Trustpilot search results   |
| **[Google Maps Business Scraper](https://github.com/FAAQJAVED/Google-Maps-Business-Scraper)**                 | Extracts and enriches business listings from Google Maps    |
| **[Email Phone Enrichment Tool](https://github.com/FAAQJAVED/Email-Phone-Number-Enrichment-Tool)**            | Scrapes contact emails and phones from company websites     |
| **[LeadHunter Pro](https://github.com/FAAQJAVED/Leadhunter_Pro)**                                             | Multi-engine search scraper with HOT/WARM/COLD lead scoring |

All four tools share the same Excel output schema (Data + Summary sheets) — results can be combined directly in Excel or imported together into a CRM.

---

## License

MIT © 2026 [FAAQJAVED](https://github.com/FAAQJAVED) — see [LICENSE](https://claude.ai/chat/LICENSE)
