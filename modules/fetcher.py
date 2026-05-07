"""
modules/fetcher.py
==================
Parallel HTTP profile page fetcher with retry logic and exponential back-off.

Design decisions:
  - A shared requests.Session (with browser cookies) is reused across all
    requests for connection pooling and consistent cookie handling.
  - Each HTTP call runs inside a daemon thread with a hard wall-clock timeout.
    This guards against TCP-level hangs that can stall a thread pool indefinitely
    when a server accepts the connection but never sends a response.
  - Failed attempts are retried with exponential back-off (configurable base
    delay that doubles on each retry). This handles transient rate limiting
    or flaky connections without hammering the server.
  - SSL verification is attempted first; if it fails the request is retried
    with verify=False and the degradation is logged at DEBUG level.
  - A ThreadPoolExecutor dispatches all slug fetches concurrently, giving
    10–30× throughput versus sequential HTTP requests.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("scraper")


# ================================================================
# SESSION BUILDER
# ================================================================

def build_session(cookies: Dict[str, str], headers: Dict[str, str]) -> requests.Session:
    """
    Create a persistent requests.Session pre-loaded with browser cookies
    and the HTTP headers defined in config.

    Reusing a single session across all profile requests provides:
      - Connection pooling (fewer TCP handshakes)
      - Consistent cookie handling
      - Shared header state

    Args:
        cookies: Browser session cookies from browser.extract_cookies().
        headers: HTTP headers dict from config["http_headers"].

    Returns:
        A configured requests.Session instance.
    """
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update(headers)
    logger.debug(f"HTTP session built with {len(cookies)} cookies")
    return session


# ================================================================
# SINGLE-URL FETCH WITH RETRY
# ================================================================

def fetch_with_retry(
    url: str,
    session: requests.Session,
    timeout: Tuple[int, int],
    hard_timeout: int,
    retry_attempts: int = 3,
    retry_base_delay: float = 2.0,
) -> Tuple[Optional[str], int]:
    """
    Fetch a single URL with retry logic and exponential back-off.

    Each attempt runs inside a daemon thread so a hard wall-clock timeout
    can be enforced regardless of whether the TCP layer ever times out.
    This prevents threads from hanging indefinitely on unresponsive servers.

    Back-off schedule (with default retry_base_delay=2.0):
        Attempt 1 → immediate
        Attempt 2 → wait 2 s
        Attempt 3 → wait 4 s

    Args:
        url:              Target URL.
        session:          Shared requests.Session (with browser cookies).
        timeout:          (connect_timeout, read_timeout) in seconds.
        hard_timeout:     Max wall-clock seconds before a thread is abandoned.
        retry_attempts:   Number of attempts before giving up (default 3).
        retry_base_delay: Base seconds for exponential back-off (default 2.0).

    Returns:
        Tuple of (html_text, http_status_code).
        html_text is None on failure; status is -1 for network-level errors.
    """
    last_status = -1

    for attempt in range(1, retry_attempts + 1):
        result: Dict = {"html": None, "status": 0}

        def _fetch() -> None:
            """Inner closure executed in a daemon thread."""
            try:
                resp = session.get(
                    url,
                    timeout=timeout,
                    verify=True,
                    allow_redirects=True,
                )
                result["html"]   = resp.text
                result["status"] = resp.status_code

            except requests.exceptions.SSLError:
                # Graceful SSL fallback — log at DEBUG, not WARNING, to avoid noise
                logger.debug(f"SSL error on {url} — retrying without SSL verification")
                try:
                    resp = session.get(
                        url,
                        timeout=timeout,
                        verify=False,
                        allow_redirects=True,
                    )
                    result["html"]   = resp.text
                    result["status"] = resp.status_code
                except Exception:
                    result["status"] = -1

            except Exception:
                result["status"] = -1

        thread = threading.Thread(target=_fetch, daemon=True)
        thread.start()
        thread.join(timeout=hard_timeout)
        # If thread is still alive, the hard timeout fired — abandon it
        if thread.is_alive():
            logger.debug(f"Hard timeout ({hard_timeout}s) exceeded for: {url}")
            result["status"] = -1

        last_status = result["status"]

        if result["status"] == 200 and result["html"]:
            return result["html"], 200

        # Retry logic
        if attempt < retry_attempts:
            delay = retry_base_delay * (2 ** (attempt - 1))
            logger.debug(
                f"Attempt {attempt}/{retry_attempts} failed "
                f"(HTTP {result['status']}) for {url} — retrying in {delay:.1f}s"
            )
            time.sleep(delay)
        else:
            logger.debug(
                f"All {retry_attempts} attempts exhausted for {url} "
                f"(last HTTP status: {result['status']})"
            )

    return None, last_status


# ================================================================
# PARALLEL BATCH FETCHER
# ================================================================

def fetch_profiles_parallel(
    slugs: List[str],
    profile_base_url: str,
    session: requests.Session,
    timeout: Tuple[int, int],
    hard_timeout: int,
    max_workers: int,
    retry_attempts: int,
    retry_base_delay: float,
) -> Dict[str, Optional[str]]:
    """
    Fetch multiple profile pages concurrently using a thread pool.

    Dispatches one fetch_with_retry() call per slug. All futures are collected
    with a combined timeout of (hard_timeout × 3) to prevent a single stuck
    worker from blocking the entire page's results.

    Args:
        slugs:            List of company/listing slug strings.
        profile_base_url: URL prefix for profile pages (e.g. "https://site.com/review").
        session:          Shared requests.Session with browser cookies.
        timeout:          (connect_timeout, read_timeout) in seconds.
        hard_timeout:     Per-request hard wall-clock limit in seconds.
        max_workers:      Thread pool size (from config["scraping"]["profile_threads"]).
        retry_attempts:   Retries per slug before giving up.
        retry_base_delay: Base seconds for exponential back-off per retry.

    Returns:
        Dict mapping each slug → HTML string (or None if all retries failed).
    """
    if not slugs:
        return {}

    results: Dict[str, Optional[str]] = {}
    pool_size = min(max_workers, len(slugs))

    with ThreadPoolExecutor(max_workers=pool_size) as executor:
        future_to_slug = {
            executor.submit(
                fetch_with_retry,
                f"{profile_base_url}/{slug}",
                session,
                timeout,
                hard_timeout,
                retry_attempts,
                retry_base_delay,
            ): slug
            for slug in slugs
        }

        combined_timeout = hard_timeout * 3
        try:
            for future in as_completed(future_to_slug, timeout=combined_timeout):
                slug = future_to_slug[future]
                try:
                    html, _status = future.result()
                    results[slug] = html
                    if html is None:
                        logger.debug(
                            f"Profile unavailable for slug '{slug}' — "
                            "will fall back to listing-level data"
                        )
                except Exception as exc:
                    results[slug] = None
                    logger.debug(f"Future error for '{slug}': {exc}")

        except Exception as exc:
            # Thread pool timed out — fill missing slugs with None
            logger.warning(f"Thread pool exceeded combined timeout: {exc}")
            for slug in slugs:
                if slug not in results:
                    results[slug] = None

    fetched = sum(1 for v in results.values() if v is not None)
    logger.debug(f"Parallel fetch: {fetched}/{len(slugs)} profiles retrieved")
    return results
