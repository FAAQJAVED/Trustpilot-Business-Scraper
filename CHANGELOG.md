# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.0] — 2025-05-07

### Fixed
- Removed 8 orphaned root-level Python files (`browser.py`, `checkpoint.py`, `controls.py`,
  `extractor.py`, `fetcher.py`, `logger.py`, `output.py`, `parser.py`) that were exact
  duplicates of their `modules/` counterparts. `scraper.py` imports exclusively from `modules/`
  and never referenced these files — they were dead weight from a prior refactor.
- Removed committed `__pycache__/scraper.cpython-312.pyc` bytecode file. The `.gitignore`
  already excluded `__pycache__/` but this file was committed before that rule was added.
- Browser is now explicitly logged as closed (`"Browser closed."`) in the `finally` block so
  users can confirm Chrome has been shut down after every run (complete or partial).

### Added
- `modules/__init__.py` now exports the full public API of all pure-logic modules, making the
  package importable with a single import line.
- `--stats` CLI flag: prints record counts (total, email%, phone%, website%) from the existing
  output file and exits — no Chrome or Selenium required.
- Page-level tqdm progress bar showing pages scraped, total pages, and running record count.
  Falls back to a no-op shim if tqdm is not installed, so the scraper still runs without it.
- Audio completion feedback via `winsound` (Windows only, silently skipped on other platforms).
- `Assets/sample_output.csv` — 10 rows of realistic sample output for portfolio viewers.

### Changed
- `requirements.txt` and `pyproject.toml` updated to include `tqdm>=4.65.0` as a runtime
  dependency.
- README updated: Performance table added, `--stats` flag documented, Project Structure
  section corrected to match actual file layout, B2B Lead Toolkit table added.
- `pyproject.toml` version bumped to `1.2.0`.

### Tests
- Test suite expanded from 78 to 121 tests.
- New: `TestBuildRecord` — 11 tests covering `parser.build_record()`, previously untested.
- New: `TestBuildSearchUrl` — 6 tests covering `scraper.build_search_url()`.
- New: `TestShouldStop` — 5 tests covering `scraper.should_stop()`.
- New: `TestApplyCliOverrides` — 6 tests covering `scraper.apply_cli_overrides()`.
- New: `TestFetchWithRetry` — 4 mocked tests covering retry logic in `fetcher.fetch_with_retry()`.
- Extended: Additional edge-case tests for `extractor.extract_listings()` and `parser.build_record()`.

---

## [1.1.0] — 2025-05-07

### Changed

- Rebranded from "Next.js Directory Scraper" to "Trustpilot Business Scraper". All user-facing documentation, metadata, and output file naming now reflect the Trustpilot platform specifically.
- `config.json` now ships fully pre-configured with all Trustpilot constants (base URL, search/profile paths, field paths, UK cleaning rules, output styling). Users only need to set `search_query` — no other field requires editing for a standard run.
- `data_paths` updated to match the verified live Trustpilot `__NEXT_DATA__` structure. Listing-level fields (`email`, `phone`, `website`, `postcode`, `city`, `trust_score`, `reviews`, `categories`) are now resolved from within each `businessUnits` entry directly. Profile-level paths updated accordingly.
- `pyproject.toml` updated: package name → `trustpilot-business-scraper`, version → `1.1.0`, description and keywords updated to reflect Trustpilot focus.
- `.gitignore` updated: `config.json` is no longer ignored and is now committed. Since it contains no credentials or secrets (only a search query and Trustpilot constants), it is safe to version.
- `README.md` fully rewritten: Trustpilot branding throughout, "What Data You Get" section with a real example row (Ryder & Dutton Estate Agents), simplified Quick Start (3 steps), removed generic platform adaptation content.

### Added

- `docs/finding_your_search_query.md` — practical guide explaining how to find a Trustpilot search query from the site URL, how to set it in `config.json`, the `--query` flag for one-off runs, and five ready-to-use example queries.
- `configs/README.md` — directory placeholder explaining the active config location and reserving the directory for future query presets.

### Removed

- Generic platform adaptation system retired: `config.example.json`, `configs/yelp.example.json`, and `docs/adapting_to_new_platform.md` deleted. Adapting to arbitrary Next.js platforms is no longer the purpose of this project.

---

## [1.0.0] — 2025-05-01

### Added

#### Core modules (8 files)

- **`scraper.py`** — Entry point and main scrape loop. Handles CLI argument parsing (`--query`, `--threads`, `--fresh`, `--resume`, `--stop-at`, `--config`), config loading and validation, browser launch sequence, checkpoint resume logic, cycling detection, and post-run summary output.

- **`modules/extractor.py`** — The core extraction engine. `resolve_path()` provides a generic dot-notation dict walker used by every field extraction in the codebase. `extract_listings()`, `extract_pagination()`, and `extract_slug()` read search result pages. `parse_next_data_from_html()` and `extract_profile_fields()` process raw HTTP-fetched profile HTML. Zero platform-specific keys hardcoded — all paths supplied from config at runtime.

- **`modules/fetcher.py`** — Parallel HTTP profile page fetcher. `fetch_with_retry()` runs each request in a daemon thread with a hard wall-clock timeout, protecting against TCP-level hangs that `requests` timeouts alone cannot prevent. `fetch_profiles_parallel()` dispatches all slugs from a page to a `ThreadPoolExecutor`, achieving 10–30× throughput versus sequential browser navigation.

- **`modules/browser.py`** — Chrome browser lifecycle management. `launch_browser()` spawns Chrome as a subprocess with a clean profile and remote debugging enabled. `connect_to_browser()` attaches Selenium via CDP. `extract_cookies()` harvests session cookies for transfer to the HTTP session. `read_next_data()` reads the `__NEXT_DATA__` JSON from the live DOM via `driver.execute_script`.

- **`modules/parser.py`** — Config-driven data cleaning and record assembly. `normalise_phone()` strips international dialing prefixes and validates digit counts. `extract_postcode()` applies a configurable regex for any locale. `build_record()` merges listing and profile data into a clean output dict keyed by configured column names.

- **`modules/output.py`** — Excel output management. `save_xlsx()` writes the Data sheet using an atomic write-to-temp-then-rename pattern. `load_xlsx()` reads an existing file for resume runs. `write_summary_sheet()` appends a run statistics sheet after the main loop completes.

- **`modules/checkpoint.py`** — Atomic checkpoint persistence. `save()` writes checkpoint state using `os.replace()` for crash-safe atomicity. `load()` restores state on resume. `clear()` removes the checkpoint after a complete run.

- **`modules/controls.py`** — Cross-platform runtime controls. Keyboard listener (P/R/Q/S via `pynput`) and command file polling (`command.txt`) run as independent control channels — the scraper is controllable in both interactive terminal sessions and headless/scheduled environments.

- **`modules/logger.py`** — Rotating file and stdout logging. Writes `INFO` and above to the console, `DEBUG` and above to a dated rotating log file (max 5 MB, 3 backups).

#### Configuration

- **`config.json`** — Fully populated, ready-to-run Trustpilot configuration with UK cleaning rules and verified `__NEXT_DATA__` paths.
- **`configs/trustpilot.json`** — Initial separate Trustpilot config (superseded by root `config.json` in v1.1.0).
- **`configs/yelp.example.json`** — Example configuration demonstrating the generic architecture on a second Next.js platform (removed in v1.1.0).

#### Tests

- **`tests/test_modules.py`** — 78 pure-function unit tests covering all six testable modules (`extractor`, `parser`, `checkpoint`, `controls`, `output`, `fetcher`). Zero network calls, zero browser processes. Complete suite runs in under 1 second.
- **`tests/__init__.py`** — Package marker for pytest discovery.

#### CI

- **`.github/workflows/ci.yml`** — GitHub Actions workflow. Runs the full test suite against Python 3.10, 3.11, and 3.12 on `ubuntu-latest` on every push and pull request.

#### Documentation

- **`README.md`** — Project documentation covering architecture, quick start, CLI flags, runtime controls, output schema, and troubleshooting.
- **`docs/adapting_to_new_platform.md`** — Step-by-step guide for adapting the scraper to any Next.js site (removed in v1.1.0).
- **`CONTRIBUTING.md`** — Contribution guidelines covering setup, test workflow, and PR checklist.
- **`CHANGELOG.md`** — This file.
- **`LICENSE`** — MIT License.

#### Tooling

- **`pyproject.toml`** — Project metadata, pytest configuration, and Ruff linting settings.
- **`requirements.txt`** — Pinned runtime dependencies.
- **`requirements-dev.txt`** — Dev dependencies: pytest, pytest-cov, ruff.
- **`.gitignore`** — Standard Python ignore rules plus project-specific entries.

### Notes

- Related project: [Google Maps Business Scraper](https://github.com/FAAQJAVED/Google-Maps-Business-Scraper) — part of the same B2B lead generation toolkit.

---

[1.2.0]: https://github.com/FAAQJAVED/trustpilot-business-scraper/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/FAAQJAVED/trustpilot-business-scraper/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/FAAQJAVED/trustpilot-business-scraper/releases/tag/v1.0.0
