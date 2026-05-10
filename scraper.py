"""
scraper.py — Trustpilot Business Scraper (Entry Point)
======================================================
A production-grade, config-driven scraper for Trustpilot — extracts business
contact data (email, phone, website, postcode, category) from any search query
and saves to a dated Excel file with Data + Summary sheets.

Architecture overview:
  Browser (Selenium)  — reads JS-rendered search result pages from the DOM
  HTTP Session        — fetches profile pages in parallel (10× faster)
  Extractor           — resolves configurable dot-notation JSON paths
  Parser              — cleans and normalises data (phone, postcode, category)
  Output              — writes dated Excel file with Data + Summary sheets
  Checkpoint          — enables pause/resume across sessions
  Controls            — cross-platform keyboard (pynput) + command file

Usage:
  python scraper.py
  python scraper.py --query "restaurants in berlin"
  python scraper.py --config custom.json --threads 5
  python scraper.py --fresh          # discard checkpoint, start from page 1
  python scraper.py --stop-at 22:30  # auto-stop at this 24h time
"""

from __future__ import annotations

# ── tqdm progress bar (graceful no-op shim if not installed) ──────────────────
try:
    from tqdm import tqdm as _TqdmClass
    _TQDM_OK = True
except ImportError:
    _TQDM_OK = False
    class _TqdmClass:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            self.n = 0
        def update(self, n=1): self.n += n
        def set_postfix(self, **kw): pass
        def write(self, s): print(s, flush=True)
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

import argparse
import json
import logging
import os
import shutil
import socket
import sys
import time
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse, parse_qs

# ── Internal modules ──────────────────────────────────────────────────────────
from modules import browser as browser_mod
from modules import checkpoint as cp_mod
from modules import controls as ctrl_mod
from modules import extractor as ext_mod
from modules import fetcher as fetcher_mod
from modules import logger as logger_mod
from modules import output as output_mod
from modules import parser as parser_mod

# ── File path constants ───────────────────────────────────────────────────────
DEFAULT_CONFIG  = "config.json"
CHECKPOINT_FILE = "scraper_checkpoint.json"
CMD_FILE        = "command.txt"


# =============================================================================
# CONFIGURATION
# =============================================================================

def load_config(path: str) -> dict:
    """
    Load and parse the JSON configuration file.

    Exits with a descriptive error message if the file is missing or malformed.

    Args:
        path: Path to the config JSON file.

    Returns:
        Parsed config dict.
    """
    if not os.path.exists(path):
        print(f"[ERROR] Config file not found: {path}", flush=True)
        print("        Copy config.json to the working directory and fill in "
              "YOUR_* placeholders.", flush=True)
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] config.json contains invalid JSON: {exc}", flush=True)
        sys.exit(1)

    # Minimal validation
    required_top_level = ["platform", "query", "data_paths", "scraping",
                          "browser", "output"]
    missing = [k for k in required_top_level if k not in cfg]
    if missing:
        print(f"[ERROR] config.json is missing required sections: {missing}",
              flush=True)
        sys.exit(1)

    return cfg


# =============================================================================
# CLI
# =============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    """
    Define command-line arguments.
    CLI flags override the corresponding config.json values at runtime.
    """
    p = argparse.ArgumentParser(
        description="Generic Next.js directory scraper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scraper.py\n"
            "  python scraper.py --query 'dentists in berlin' --threads 8\n"
            "  python scraper.py --config platforms/yelp.json --fresh\n"
            "  python scraper.py --stop-at 23:00\n"
        ),
    )
    p.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        metavar="FILE",
        help="Path to config JSON (default: config.json)",
    )
    p.add_argument(
        "--query",
        default=None,
        metavar="QUERY",
        help="Search query — overrides config.json query.search_query",
    )
    p.add_argument(
        "--threads",
        default=None,
        type=int,
        metavar="N",
        help="Parallel profile request threads — overrides config.json",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="Clear checkpoint file and start scraping from page 1",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Explicitly continue from last checkpoint (default behaviour)",
    )
    p.add_argument(
        "--stop-at",
        default=None,
        metavar="HH:MM",
        help="Auto-stop at this 24h time (e.g. 23:00) — overrides config.json",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Print record counts from the existing output file and exit — no browser needed.",
    )
    return p


def apply_cli_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    """
    Overwrite config values with any CLI arguments that were explicitly passed.

    Three-tier precedence (highest to lowest):
        CLI arguments → config.json values → built-in defaults

    Args:
        cfg:  Loaded config dict (mutated in place).
        args: Parsed argparse Namespace.

    Returns:
        Updated config dict.
    """
    if args.query:
        cfg["query"]["search_query"] = args.query

    if args.threads:
        cfg["scraping"]["profile_threads"] = args.threads

    if args.stop_at:
        cfg["scraping"]["stop_at"] = args.stop_at

    return cfg


# =============================================================================
# SYSTEM CHECKS
# =============================================================================

def check_internet() -> bool:
    """Verify internet connectivity by attempting a DNS-port TCP connection."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(("8.8.8.8", 53))
        sock.close()
        return True
    except Exception:
        return False


def check_disk(min_mb: int) -> bool:
    """
    Return False and log a warning if free disk space is below the minimum.

    Args:
        min_mb: Minimum required free space in megabytes (from config).

    Returns:
        True if disk space is sufficient, False otherwise.
    """
    try:
        free_mb = shutil.disk_usage(".").free // (1024 * 1024)
        if free_mb < min_mb:
            logging.getLogger("scraper").warning(
                f"Low disk space: {free_mb} MB free "
                f"(config minimum: {min_mb} MB) — pausing scrape"
            )
            return False
    except Exception:
        pass
    return True


def should_stop(state: ctrl_mod.State, stop_at: str) -> bool:
    """
    Return True if either a quit signal has been set or the scheduled
    auto-stop time has been reached.

    Args:
        state:   Shared State object.
        stop_at: 24h time string from config (e.g. "23:00"). Empty = disabled.

    Returns:
        True if the scrape loop should exit.
    """
    if state.stop:
        return True
    if not stop_at:
        return False
    return datetime.now().strftime("%H:%M") >= stop_at


# =============================================================================
# URL BUILDERS
# =============================================================================

def build_search_url(cfg: dict, page: int) -> str:
    """
    Construct a paginated search URL from config settings.

    The query parameter name and any extra params (e.g. experiment flags) are
    all pulled from config so no platform-specific URL logic lives here.

    Args:
        cfg:  Full config dict.
        page: Page number (1-indexed).

    Returns:
        Complete URL string.
    """
    base       = cfg["platform"]["base_url"].rstrip("/")
    path       = cfg["platform"]["search_path"]
    query_key  = cfg["query"].get("search_param", "query")
    query_val  = cfg["query"]["search_query"]
    extra      = cfg["query"].get("extra_params", {})

    params = {query_key: query_val, "page": page}
    params.update(extra)

    return f"{base}{path}?{urlencode(params)}"


# =============================================================================
# URL SYNC
# =============================================================================

def sync_query_from_browser_url(driver, cfg: dict, log) -> None:
    """
    Read the live browser URL after Selenium connects and sync the query
    string — and any extra URL params Trustpilot has injected (e.g.
    ``experiment=semantic_search_enabled``) — back into cfg.

    This is the single fix for the pagination query-switch bug:

    The user may have manually navigated the browser to a different query
    than the one in config.json (e.g. ``property managers manchester`` while
    config has ``accountants in London``).  Without this sync, page 1 is read
    from the live browser URL but pages 2+ are built from cfg — causing a
    mid-scrape query switch that changes the result set entirely.

    Trustpilot also appends ``?experiment=semantic_search_enabled`` to its
    semantic search URLs.  Omitting this on pages 2+ causes Trustpilot to
    serve a completely different (non-semantic, unfiltered) result set.
    Capturing it here ensures build_search_url() carries it on every page.

    Args:
        driver: Active Selenium WebDriver instance.
        cfg:    Full config dict — mutated in place.
        log:    Logger instance.
    """
    try:
        current_url = driver.current_url
        parsed      = urlparse(current_url)
        params      = parse_qs(parsed.query, keep_blank_values=True)

        query_key   = cfg["query"].get("search_param", "query")
        live_values = params.get(query_key, [])

        if not live_values:
            log.warning(
                f"Could not extract '{query_key}' from browser URL: {current_url}"
            )
            return

        live_query = live_values[0]

        # ── Sync the search query ─────────────────────────────────────────────
        config_query = cfg["query"]["search_query"]
        if live_query != config_query:
            log.info(
                f"Query sync: browser has '{live_query}' "
                f"— config had '{config_query}' — using browser value for all pages"
            )
        else:
            log.info(f"Query sync confirmed: '{live_query}'")

        cfg["query"]["search_query"] = live_query

        # ── Capture any extra URL params Trustpilot injected ──────────────────
        # Remove the known standard params (query key + page) — everything
        # else (e.g. experiment=semantic_search_enabled) is an extra param
        # that must be replicated on every paginated request.
        skip_keys  = {query_key, "page"}
        extra      = cfg["query"].get("extra_params", {})
        injected   = {}

        for key, values in params.items():
            if key in skip_keys:
                continue
            injected[key] = values[0]

        if injected:
            merged = {**extra, **injected}
            cfg["query"]["extra_params"] = merged
            log.info(
                f"Extra URL params captured from browser: {injected} "
                f"— will be appended to every page URL"
            )
        else:
            cfg["query"]["extra_params"] = extra

    except Exception as exc:
        log.warning(f"URL sync failed (non-fatal): {exc}")


# =============================================================================
# MAIN SCRAPE LOOP
# =============================================================================

def run(
    driver,
    state: ctrl_mod.State,
    ctx: dict,
    cfg: dict,
    args: argparse.Namespace,
) -> Tuple[List[dict], dict]:
    """
    Core scrape loop: paginate through search results, fetch profiles in
    parallel, clean and deduplicate records, and persist after every page.

    Args:
        driver: Active Selenium WebDriver instance.
        state:  Shared State object (for pause/quit signals).
        ctx:    Mutable progress context dict {"saved": int, "page": int}.
        cfg:    Full config dict.
        args:   Parsed CLI args (for --fresh flag).

    Returns:
        Tuple of (all_row_dicts, run_statistics_dict).
    """
    log            = logging.getLogger("scraper")
    scraping_cfg   = cfg["scraping"]
    listing_paths  = cfg["data_paths"]["listing"]
    profile_paths  = cfg["data_paths"]["profile"]
    output_cfg     = cfg["output"]

    prefix   = output_cfg.get("filename_prefix", cfg["platform"]["name"])
    out_path = output_mod.make_output_path(prefix)

    # ── Load existing data for resume ─────────────────────────────────────────
    existing: List[dict] = output_mod.load_xlsx(out_path)
    seen_ids: set        = set()
    name_col = (output_cfg["columns"][0]
                if output_cfg.get("columns") else "Company Name")

    for row in existing:
        key = (
            row.get(name_col, "").strip().lower() + "|"
            + row.get("Postcode", "").strip().upper()
        )
        seen_ids.add(key)

    # ── Handle --fresh flag ───────────────────────────────────────────────────
    if args.fresh and os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        log.info("--fresh: checkpoint cleared, starting from page 1")

    # ── Load checkpoint ───────────────────────────────────────────────────────
    cp          = cp_mod.load(CHECKPOINT_FILE)
    start_page  = cp.get("last_completed_page", 0) + 1
    seen_slugs  = set(cp.get("seen_slugs", []))
    total_pages: Optional[int] = cp.get("total_pages")

    ctx["saved"] = len(existing)
    log.info(
        f"Starting from page {start_page}  |  "
        f"{len(existing)} rows already in output file"
    )

    # ── Build HTTP session with browser cookies ───────────────────────────────
    log.info("Extracting browser session cookies...")
    cookies = browser_mod.extract_cookies(driver)
    session = fetcher_mod.build_session(cookies, cfg.get("http_headers", {}))

    # ── Timing ────────────────────────────────────────────────────────────────
    loop_start     = time.time()
    start_time_str = datetime.now().strftime("%H:%M:%S")
    total_dupes    = 0
    pages_scraped  = 0

    stop_at     = scraping_cfg.get("stop_at", "")
    http_timeout = (
        scraping_cfg.get("http_timeout_connect", 5),
        scraping_cfg.get("http_timeout_read",    8),
    )
    hard_timeout = scraping_cfg.get("hard_timeout", 12)

    # ── Page loop ─────────────────────────────────────────────────────────────
    bar = _TqdmClass(
        total=1,
        desc="Scraping pages",
        unit="page",
        dynamic_ncols=True,
    )
    try:
        for page in range(start_page, 10_000):

            # Control checks at the top of every iteration
            ctrl_mod.check_command_file(state, CMD_FILE, ctx)
            if should_stop(state, stop_at):
                break
            ctrl_mod.wait_if_paused(state, CMD_FILE, ctx)
            if should_stop(state, stop_at):
                break

            # Disk guard
            if not check_disk(scraping_cfg.get("disk_min_mb", 500)):
                state.set_paused(True)
                ctrl_mod.wait_if_paused(state, CMD_FILE, ctx)

            # ── Read search results from browser DOM ──────────────────────────
            nd = browser_mod.read_next_data(driver)
            if not nd:
                log.warning(f"No __NEXT_DATA__ found on page {page} — stopping.")
                break

            # ── Determine total pages on the first page only ──────────────────
            if total_pages is None:
                raw_results, raw_pages = ext_mod.extract_pagination(nd, listing_paths)

                if 0 < raw_results < 9_000:
                    # Compute pages from result count (assume 10 results/page)
                    results_per_page = 10
                    total_pages = (raw_results + results_per_page - 1) // results_per_page
                    log.info(f"Found {raw_results} results → {total_pages} pages")
                elif raw_pages > 0:
                    total_pages = raw_pages
                    log.info(f"Found {total_pages} pages")
                else:
                    total_pages = 9_999
                    log.warning("Page count unknown — will stop when results are exhausted.")

                # Update tqdm total now that we know it
                if total_pages < 9_999:
                    bar.total = total_pages
                    if hasattr(bar, "refresh"):
                        bar.refresh()

                # Refresh cookies after first page has fully rendered
                cookies = browser_mod.extract_cookies(driver)
                session = fetcher_mod.build_session(cookies, cfg.get("http_headers", {}))
                log.info(f"Session cookies refreshed ({len(cookies)} total)")

            # ── Extract listings ──────────────────────────────────────────────
            listings = ext_mod.extract_listings(nd, listing_paths)
            if not listings:
                log.info(f"Page {page} returned no listings — results exhausted.")
                break

            slug_field = listing_paths.get("slug_field", "identifyingName")
            new_items: List[Tuple[str, dict]] = []

            for listing in listings:
                slug = ext_mod.extract_slug(listing, slug_field)
                if slug and slug not in seen_slugs:
                    new_items.append((slug, listing))
                    seen_slugs.add(slug)

            if not new_items:
                log.info(f"Page {page}: no new slugs — results exhausted.")
                break

            # Cycling detection: very few new slugs from a full page of results
            if len(new_items) < 2 and len(listings) >= 5:
                log.warning(
                    f"Page {page}: cycling detected "
                    f"({len(new_items)} new from {len(listings)} listings) — stopping."
                )
                break

            pages_str = str(total_pages) if total_pages < 9_999 else "?"
            log.info(
                f"Page {page}/{pages_str} — "
                f"{len(new_items)} companies | fetching profiles in parallel..."
            )

            # ── Fetch all profiles in parallel via HTTP ───────────────────────
            profile_base = (
                cfg["platform"]["base_url"].rstrip("/")
                + cfg["platform"]["profile_path"]
            )
            slugs = [slug for slug, _ in new_items]

            profile_html_map = fetcher_mod.fetch_profiles_parallel(
                slugs             = slugs,
                profile_base_url  = profile_base,
                session           = session,
                timeout           = http_timeout,
                hard_timeout      = hard_timeout,
                max_workers       = scraping_cfg.get("profile_threads",   10),
                retry_attempts    = scraping_cfg.get("retry_attempts",     3),
                retry_base_delay  = scraping_cfg.get("retry_base_delay", 2.0),
            )

            # ── Parse profiles and assemble output records ────────────────────
            saved_this_page = 0

            for slug, listing in new_items:
                html    = profile_html_map.get(slug)
                profile = None

                if html:
                    nd_profile = ext_mod.parse_next_data_from_html(html)
                    if nd_profile:
                        profile = ext_mod.extract_profile_fields(
                            nd_profile, profile_paths, cfg["cleaning"]
                        )

                record = parser_mod.build_record(listing, profile, cfg)
                if not record:
                    continue

                # Deduplicate by (normalised name + postcode)
                dedup_key = (
                    record.get(name_col, "").strip().lower() + "|"
                    + record.get("Postcode", "").strip().upper()
                )
                if dedup_key in seen_ids:
                    total_dupes += 1
                    continue

                seen_ids.add(dedup_key)
                existing.append(record)
                saved_this_page += 1
                ctx["saved"] += 1

            ctx["page"] = page
            pages_scraped += 1

            pct = (
                f"{round(page / total_pages * 100)}%"
                if total_pages and total_pages < 9_999
                else "?"
            )
            log.info(
                f"  └─ +{saved_this_page} saved this page | "
                f"total saved: {ctx['saved']} | {pct} complete"
            )

            # ── Update progress bar ───────────────────────────────────────────
            bar.update(1)
            bar.set_postfix(saved=ctx["saved"])

            # ── Persist data and checkpoint after every page ──────────────────
            output_mod.save_xlsx(
                rows        = existing,
                path        = out_path,
                columns     = output_cfg["columns"],
                col_widths  = output_cfg.get(
                    "column_widths", [20] * len(output_cfg["columns"])
                ),
                header_color = output_cfg.get("header_color", "4A90D9"),
            )

            cp_mod.save(
                {
                    "last_completed_page": page,
                    "total_pages":         total_pages,
                    "seen_slugs":          list(seen_slugs),
                },
                CHECKPOINT_FILE,
            )

            # ── Exit condition ────────────────────────────────────────────────
            if total_pages and total_pages < 9_999 and page >= total_pages:
                log.info(f"All {total_pages} pages scraped — complete.")
                break

            # ── Navigate to next page ─────────────────────────────────────────
            next_url = build_search_url(cfg, page + 1)
            log.info(f"Navigating to page {page + 1}...")

            if not browser_mod.navigate(
                driver,
                next_url,
                delay=scraping_cfg.get("page_delay", 2.5),
            ):
                log.warning(f"Navigation to page {page + 1} failed — stopping.")
                break

    finally:
        bar.close()

    # ── Final flush ───────────────────────────────────────────────────────────
    output_mod.save_xlsx(
        rows        = existing,
        path        = out_path,
        columns     = output_cfg["columns"],
        col_widths  = output_cfg.get(
            "column_widths", [20] * len(output_cfg["columns"])
        ),
        header_color = output_cfg.get("header_color", "4A90D9"),
    )

    elapsed_s = int(time.time() - loop_start)
    end_time  = datetime.now().strftime("%H:%M:%S")

    run_stats = {
        "platform":   cfg["platform"]["name"],
        "query":      cfg["query"]["search_query"],
        "date":       date.today().strftime("%Y-%m-%d"),
        "start_time": start_time_str,
        "end_time":   end_time,
        "duration":   f"{elapsed_s // 60}m {elapsed_s % 60:02d}s",
        "pages":      pages_scraped,
        "total":      len(existing),
        "emails":     sum(1 for r in existing if r.get("Email")),
        "phones":     sum(1 for r in existing if r.get("Phone")),
        "websites":   sum(1 for r in existing if r.get("Website")),
        "duplicates": total_dupes,
        "status":     (
            "PARTIAL — re-run to continue"
            if state.stop or should_stop(state, stop_at)
            else "COMPLETE"
        ),
    }

    return existing, run_stats


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # ── Parse CLI ─────────────────────────────────────────────────────────────
    parser = build_arg_parser()
    args   = parser.parse_args()

    # ── Load and apply config ─────────────────────────────────────────────────
    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args)

    # ── Logging (must come after config is loaded for the prefix) ─────────────
    log = logger_mod.setup_logger(
        prefix=cfg["platform"].get("name", "scraper").replace(" ", "_")
    )

    # ── Banner ────────────────────────────────────────────────────────────────
    platform = cfg["platform"]["name"]
    query    = cfg["query"]["search_query"]
    threads  = cfg["scraping"]["profile_threads"]

    print()
    print("=" * 62)
    print("  Trustpilot Business Scraper")
    print(f"  Platform  :  {platform}")
    print(f"  Config Q  :  {query}")
    print(f"  Threads   :  {threads} parallel profile requests per page")
    print("  Controls  :  P=pause  R=resume  Q=quit  S=status")
    print()
    print("  NOTE: The scraper will sync the active query from the")
    print("  browser URL after you press ENTER — config query is only")
    print("  the default. Navigate Chrome to any search before ENTER.")
    print("=" * 62)
    print()

    # ── --stats: print output file summary and exit (no browser needed) ─────────
    if args.stats:
        out_path = output_mod.make_output_path(
            cfg["output"].get("filename_prefix", cfg["platform"]["name"])
        )
        rows = output_mod.load_xlsx(out_path)
        if not rows:
            print(f"No output file found at: {out_path}")
        else:
            emails   = sum(1 for r in rows if r.get("Email"))
            phones   = sum(1 for r in rows if r.get("Phone"))
            websites = sum(1 for r in rows if r.get("Website"))
            print(f"\n  Output  : {out_path}")
            print(f"  Records : {len(rows)}")
            print(f"  Email   : {emails} ({int(emails / max(len(rows), 1) * 100)}%)")
            print(f"  Phone   : {phones} ({int(phones / max(len(rows), 1) * 100)}%)")
            print(f"  Website : {websites} ({int(websites / max(len(rows), 1) * 100)}%)")
        sys.exit(0)

    # ── System checks ─────────────────────────────────────────────────────────
    if not check_internet():
        log.error("No internet connection detected — fix and re-run.")
        return

    # ── Initialise controls ───────────────────────────────────────────────────
    state    = ctrl_mod.State()
    ctx: dict = {"saved": 0, "page": 0}

    keyboard_listener = ctrl_mod.start_keyboard_listener(
        state,
        status_callback=lambda: log.info(
            f"STATUS — saved: {ctx['saved']}  page: {ctx['page']}"
        ),
    )

    # ── Launch browser ────────────────────────────────────────────────────────
    search_url_p1 = build_search_url(cfg, 1)
    debug_port    = cfg["browser"]["debug_port"]

    print("  Launching Chrome with a clean profile...")
    print("  (Clean profile avoids personalised/cached search results)")
    print(f"  Opening: {search_url_p1}")
    print()

    launched = browser_mod.launch_browser(
        chrome_paths = cfg["browser"]["chrome_paths"],
        debug_port   = debug_port,
        search_url   = search_url_p1,
    )

    if not launched:
        log.error("Automatic Chrome launch failed.")
        print()
        print("  Try launching Chrome manually:")
        print(
            f'  chrome --remote-debugging-port={debug_port} '
            f'--user-data-dir=scraper_clean_profile '
            f'"{search_url_p1}"'
        )
        return

    print()
    print("  Chrome should now be open showing the search results page.")
    print("  If you see a cookie consent banner, dismiss it first.")
    print()
    input("  >>> Press ENTER when the results are visible in Chrome... ")
    print()

    # ── Connect Selenium ──────────────────────────────────────────────────────
    log.info("Connecting Selenium to Chrome...")
    time.sleep(2)

    driver = browser_mod.connect_to_browser(debug_port)
    if not driver:
        log.error(
            f"Could not connect to Chrome. "
            f"Ensure it is running with --remote-debugging-port={debug_port}"
        )
        return

    current_url   = driver.current_url
    log.info(f"Connected — current URL: {current_url}")

    if cfg["platform"]["base_url"].replace("https://", "").replace("www.", "") \
            not in current_url:
        log.error(
            f"Browser is not on the expected platform ({cfg['platform']['base_url']}). "
            "Navigate there and re-run."
        )
        driver.quit()
        return

    # ── Sync query + extra params from the live browser URL ───────────────────
    # CRITICAL: must happen before run() so build_search_url() uses the correct
    # query and any Trustpilot-injected params (e.g. experiment=semantic_search_enabled)
    # on ALL pages — not just page 1 which is read directly from the browser DOM.
    # Without this, page 2+ are built from config.json search_query which may
    # differ from what the browser is actually showing, causing a mid-scrape
    # query switch that silently changes the entire result set.
    sync_query_from_browser_url(driver, cfg, log)

    # ── Run scrape ────────────────────────────────────────────────────────────
    rows: List[dict] = []
    run_stats: dict  = {}

    try:
        rows, run_stats = run(driver, state, ctx, cfg, args)

    except KeyboardInterrupt:
        log.warning("KeyboardInterrupt — use Q key for a clean checkpoint save.")

    except Exception as exc:
        log.exception(f"Unexpected error in scrape loop: {exc}")

    finally:
        try:
            driver.quit()
            log.info("Browser closed.")
        except Exception:
            pass
        if keyboard_listener:
            try:
                keyboard_listener.stop()
            except Exception:
                pass

    # ── Post-run cleanup ──────────────────────────────────────────────────────
    fully_complete = (
        not state.stop
        and not should_stop(state, cfg["scraping"].get("stop_at", ""))
    )

    if fully_complete:
        cp_mod.clear(CHECKPOINT_FILE)
        log.info("Checkpoint cleared — run complete.")
        # Audio completion signal — silently skipped on non-Windows
        try:
            import winsound as _ws
            for _f, _d in [(600, 100), (800, 100), (1000, 100), (1200, 300)]:
                _ws.Beep(_f, _d)
        except Exception:
            print("\a", end="", flush=True)
    else:
        log.info("Partial run — checkpoint saved. Re-run anytime to continue.")
        # Short alert tone for partial/interrupted run
        try:
            import winsound as _ws
            _ws.Beep(900, 200)
            _ws.Beep(600, 400)
        except Exception:
            pass

    # Append summary sheet
    if rows:
        out_path = output_mod.make_output_path(
            cfg["output"].get("filename_prefix", cfg["platform"]["name"])
        )
        run_stats["status"] = (
            "COMPLETE" if fully_complete else "PARTIAL — re-run to continue"
        )
        output_mod.write_summary_sheet(
            out_path,
            run_stats,
            cfg["output"].get("header_color", "4A90D9"),
        )

    # ── Print final summary ───────────────────────────────────────────────────
    print()
    print("=" * 62)
    if rows:
        emails   = sum(1 for r in rows if r.get("Email"))
        phones   = sum(1 for r in rows if r.get("Phone"))
        websites = sum(1 for r in rows if r.get("Website"))
        print(f"  Total companies  :  {len(rows):>6}")
        print(f"  With email       :  {emails:>6}")
        print(f"  With phone       :  {phones:>6}")
        print(f"  With website     :  {websites:>6}")
        print(f"  Duration         :  {run_stats.get('duration', 'N/A')}")
        print(f"  Status           :  {'COMPLETE' if fully_complete else 'PARTIAL'}")
    else:
        print("  No rows collected in this run.")
    print("=" * 62)
    print()


if __name__ == "__main__":
    main()