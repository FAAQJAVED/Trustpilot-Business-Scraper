"""
modules/browser.py
==================
Manages the Chrome browser lifecycle:

  1. launch_browser()     — spawns Chrome with a clean profile via subprocess
  2. connect_to_browser() — attaches Selenium to the running instance
  3. extract_cookies()    — harvests session cookies for HTTP reuse
  4. read_next_data()     — reads the __NEXT_DATA__ JSON directly from the DOM
  5. navigate()           — navigates to a URL and waits for the page to settle

Design rationale:
  A clean browser profile (no saved cookies or preferences) ensures the search
  results page shows a standard, non-personalised result set. Selenium then
  connects to this already-running instance rather than launching its own, which
  avoids triggering bot-detection patterns associated with automated launches.
  Session cookies are copied into the HTTP requests.Session so that parallel
  profile fetches receive the same server-side treatment as browser visits.
"""

import logging
import os
import shutil
import subprocess
import time
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException

try:
    from webdriver_manager.chrome import ChromeDriverManager

    _USE_MANAGER = True
except ImportError:
    _USE_MANAGER = False

logger = logging.getLogger("scraper")


# ================================================================
# CHROME DISCOVERY & LAUNCH
# ================================================================

def find_chrome(chrome_paths: List[str]) -> Optional[str]:
    """
    Return the first Chrome or Chromium executable found on disk.

    Args:
        chrome_paths: Ordered list of absolute paths to try (from config).

    Returns:
        First existing path, or None if none are found.
    """
    for path in chrome_paths:
        if os.path.exists(path):
            logger.debug(f"Chrome found at: {path}")
            return path
    return None


def launch_browser(
    chrome_paths: List[str],
    debug_port: int,
    search_url: str,
    profile_dir: str = "scraper_clean_profile",
) -> bool:
    """
    Spawn Chrome with a freshly created profile and remote debugging enabled.

    A clean profile is rebuilt on every run to prevent stale cookies or
    personalised settings from influencing which results the site returns.

    Args:
        chrome_paths: Ordered list of Chrome executable paths to try.
        debug_port:   Remote debugging port (must match connect_to_browser).
        search_url:   URL Chrome opens on startup.
        profile_dir:  Name of the temporary profile directory (created in cwd).

    Returns:
        True if Chrome launched successfully, False otherwise.
    """
    chrome_path = find_chrome(chrome_paths)
    if not chrome_path:
        logger.error("Chrome executable not found. Paths tried:")
        for p in chrome_paths:
            logger.error(f"  {p}")
        return False

    # Rebuild the profile directory from scratch every run
    clean_dir = os.path.join(os.getcwd(), profile_dir)
    if os.path.exists(clean_dir):
        try:
            shutil.rmtree(clean_dir)
            logger.debug(f"Removed old clean profile: {clean_dir}")
        except Exception as exc:
            logger.warning(f"Could not remove old profile dir: {exc}")

    os.makedirs(clean_dir, exist_ok=True)

    # Flags that suppress automation signals and background activity
    cmd = [
        chrome_path,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={clean_dir}",
        "--no-default-browser-check",
        "--no-first-run",
        "--disable-extensions",
        "--disable-plugins",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-blink-features=AutomationControlled",
        search_url,
    ]

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Chrome launched on port {debug_port} → {search_url}")
        return True
    except Exception as exc:
        logger.error(f"Failed to launch Chrome: {exc}")
        return False


# ================================================================
# SELENIUM CONNECTION
# ================================================================

def connect_to_browser(debug_port: int) -> Optional[webdriver.Chrome]:
    """
    Attach a Selenium WebDriver to an already-running Chrome instance.

    Uses the remote debugging address rather than launching a new browser,
    which avoids the automated browser fingerprint that triggers bot detection.

    Args:
        debug_port: The --remote-debugging-port value Chrome was started with.

    Returns:
        Connected WebDriver instance, or None on failure.
    """
    options = Options()
    options.add_experimental_option(
        "debuggerAddress", f"127.0.0.1:{debug_port}"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        if _USE_MANAGER:
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options,
            )
        else:
            driver = webdriver.Chrome(options=options)

        driver.set_page_load_timeout(30)
        logger.info(f"Selenium connected on port {debug_port}")
        return driver

    except WebDriverException as exc:
        logger.error(f"Selenium connection failed: {exc}")
        return None


# ================================================================
# COOKIE EXTRACTION
# ================================================================

def extract_cookies(driver: webdriver.Chrome) -> Dict[str, str]:
    """
    Read all cookies from the Selenium session as a flat name→value dict.

    These cookies are injected into the parallel HTTP session so that profile
    page requests carry the same session context as the browser — ensuring
    the target server treats them as genuine browser traffic.

    Args:
        driver: An active Selenium WebDriver instance.

    Returns:
        Dict of {cookie_name: cookie_value}. Empty dict on failure.
    """
    try:
        raw_cookies = driver.get_cookies()
        cookies = {c["name"]: c["value"] for c in raw_cookies}
        logger.debug(f"Extracted {len(cookies)} session cookies")
        return cookies
    except Exception as exc:
        logger.warning(f"Cookie extraction failed: {exc}")
        return {}


# ================================================================
# __NEXT_DATA__ READER
# ================================================================

def read_next_data(driver: webdriver.Chrome) -> Optional[dict]:
    """
    Read and parse the __NEXT_DATA__ JSON injected into the page by Next.js.

    Next.js server-side rendering embeds all page props inside a
    <script id="__NEXT_DATA__"> tag. Reading this directly from the DOM
    gives us structured data without any HTML parsing fragility.

    Args:
        driver: An active Selenium WebDriver instance on the target page.

    Returns:
        Parsed dict, or None if the element is missing or JSON is invalid.
    """
    try:
        result = driver.execute_script("""
            var el = document.querySelector('#__NEXT_DATA__');
            if (!el) return null;
            try { return JSON.parse(el.textContent); }
            catch(e) { return null; }
        """)
        return result
    except Exception as exc:
        logger.debug(f"__NEXT_DATA__ DOM read failed: {exc}")
        return None


# ================================================================
# NAVIGATION
# ================================================================

def navigate(
    driver: webdriver.Chrome,
    url: str,
    delay: float = 2.5,
) -> bool:
    """
    Navigate the browser to a URL and pause to allow client-side JS to render.

    Args:
        driver: An active Selenium WebDriver instance.
        url:    Target URL.
        delay:  Seconds to wait after driver.get() for the page to settle.

    Returns:
        True on success, False if an exception occurs.
    """
    try:
        driver.get(url)
        time.sleep(delay)
        return True
    except Exception as exc:
        logger.warning(f"Navigation failed → {url}: {exc}")
        return False
