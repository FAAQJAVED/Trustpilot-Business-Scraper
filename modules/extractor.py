"""
modules/extractor.py
====================
Generic, config-driven data extractor for Next.js __NEXT_DATA__ JSON.

The central design decision here is that ZERO platform-specific keys are
hardcoded in this module. Every field path — from which key holds the listing
array to which nested key stores the company email — is supplied by the caller
via the config["data_paths"] dict as dot-notation strings.

This makes the extractor reusable across any Next.js directory site without
modification. Adapting to a new platform only requires updating config.json.

Key public API:
    resolve_path()             — generic dot-notation dict walker
    extract_listings()         — listing array from search results page
    extract_pagination()       — total results and page count
    extract_slug()             — unique identifier per listing
    parse_next_data_from_html()— extract __NEXT_DATA__ from raw profile HTML
    extract_profile_fields()   — structured contact data from a profile page
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("scraper")


# ================================================================
# CORE PATH RESOLVER
# ================================================================

def resolve_path(data: dict, path: str, default: Any = None) -> Any:
    """
    Walk a nested dict using a dot-separated key path string.

    This is the engine that makes the entire extractor platform-agnostic.
    Config supplies paths like "props.pageProps.businessUnits" and this
    function walks the dict tree to retrieve the value.

    Args:
        data:    The dict to traverse (typically a parsed __NEXT_DATA__ blob).
        path:    Dot-separated key path, e.g. "props.pageProps.pagination.totalPages".
        default: Value returned if any key in the path is absent or None.

    Returns:
        The value found at the path, or default.

    Examples:
        >>> resolve_path({"a": {"b": 42}}, "a.b")
        42
        >>> resolve_path({"a": {}}, "a.b.c", default="N/A")
        'N/A'
    """
    if not path or not isinstance(data, dict):
        return default

    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default

    return current


# ================================================================
# SEARCH RESULTS PAGE EXTRACTORS
# ================================================================

def extract_listings(next_data: dict, listing_paths: dict) -> List[dict]:
    """
    Extract the list of business/listing objects from a search results page.

    Args:
        next_data:     Parsed __NEXT_DATA__ dict from the search results page.
        listing_paths: Config dict (config["data_paths"]["listing"]).

    Returns:
        List of raw listing dicts — one dict per company shown on the page.
        Returns an empty list if the path is missing or the value is not a list.
    """
    path  = listing_paths.get("business_units", "")
    units = resolve_path(next_data, path, default=[])

    if not isinstance(units, list):
        logger.debug(
            f"Listings path '{path}' returned {type(units).__name__}, expected list."
        )
        return []

    return units


def extract_pagination(
    next_data: dict, listing_paths: dict
) -> Tuple[int, int]:
    """
    Read the total result count and total page count from the search page data.

    Args:
        next_data:     Parsed __NEXT_DATA__ dict.
        listing_paths: Config dict (config["data_paths"]["listing"]).

    Returns:
        Tuple of (total_results, total_pages). Returns (0, 0) on any failure.
    """
    results_path = listing_paths.get("pagination_results", "")
    pages_path   = listing_paths.get("pagination_pages",   "")

    raw_results = resolve_path(next_data, results_path, default=0)
    raw_pages   = resolve_path(next_data, pages_path,   default=0)

    try:
        return int(raw_results or 0), int(raw_pages or 0)
    except (TypeError, ValueError):
        return 0, 0


def extract_slug(listing: dict, slug_field: str) -> str:
    """
    Extract the unique slug or identifier string from a single listing dict.

    Args:
        listing:    A raw listing dict from extract_listings().
        slug_field: The dict key that holds the unique identifier (from config).

    Returns:
        Slug string, or empty string if the key is absent.
    """
    return (listing.get(slug_field) or "").strip()


def extract_display_name(listing: dict, name_field: str) -> str:
    """
    Extract the human-readable name from a listing dict.

    Args:
        listing:    A raw listing dict.
        name_field: Key name for the display name (from config).

    Returns:
        Stripped name string.
    """
    return (listing.get(name_field) or "").strip()


# ================================================================
# PROFILE PAGE EXTRACTORS
# ================================================================

def parse_next_data_from_html(html: str) -> Optional[dict]:
    """
    Locate and parse the __NEXT_DATA__ <script> block from raw HTML.

    Used for profile pages fetched via HTTP (not via the browser). The JSON
    is embedded by Next.js server-side rendering inside a <script> tag,
    making it more reliable than parsing the rendered HTML directly.

    Args:
        html: Full HTML source string of the profile page.

    Returns:
        Parsed dict, or None if the element is absent or JSON is malformed.
    """
    if not html:
        return None

    match = re.search(
        r'<script\s+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        logger.debug("__NEXT_DATA__ script tag not found in HTML.")
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.debug(f"__NEXT_DATA__ JSON parse error: {exc}")
        return None


def extract_profile_fields(
    next_data: dict,
    profile_paths: dict,
    cleaning_cfg: dict,
) -> Optional[Dict[str, Any]]:
    """
    Extract structured contact and rating fields from a profile page's __NEXT_DATA__.

    All field paths are resolved relative to a configurable root object within
    the JSON tree — no platform-specific keys are embedded in this function.
    The caller supplies path strings via profile_paths (from config).

    Args:
        next_data:     Parsed __NEXT_DATA__ dict from the company profile page.
        profile_paths: Config dict (config["data_paths"]["profile"]).
        cleaning_cfg:  Config dict (config["cleaning"]) — reserved for callers
                       that need raw strings before normalisation.

    Returns:
        Dict with standardised keys (email, phone, website, postcode, city,
        trust_score, reviews, categories), or None if the root is not found.
    """
    root_path = profile_paths.get("root", "")
    root      = resolve_path(next_data, root_path)

    if root is None:
        logger.debug(f"Profile root not found at path: '{root_path}'")
        return None

    def _get(field_key: str) -> Any:
        """Resolve a field path relative to the profile root."""
        field_path = profile_paths.get(field_key, "")
        if not field_path:
            return None
        return resolve_path(root, field_path)

    raw_email       = _get("email")       or ""
    raw_phone       = _get("phone")       or ""
    raw_website     = _get("website")     or ""
    raw_postcode    = _get("postcode")    or ""
    raw_city        = _get("city")        or ""
    trust_score     = _get("trust_score")
    reviews         = _get("reviews")     or 0
    categories      = _get("categories")  or []

    # Some platforms nest contact info under a sub-object; try that as a fallback
    contact_root_path = profile_paths.get("contact_info_root", "")
    contact_root: dict = {}
    if contact_root_path:
        contact_root = resolve_path(root, contact_root_path) or {}

    return {
        "email":       (str(raw_email).strip().lower()
                        or str(contact_root.get("email", "")).strip().lower()),
        "phone":       (str(raw_phone).strip()
                        or str(contact_root.get("phone", "")).strip()),
        "website":     str(raw_website).strip(),
        "postcode":    (str(raw_postcode).strip()
                        or str(contact_root.get("zipCode", "")).strip()),
        "city":        (str(raw_city).strip()
                        or str(contact_root.get("city", "")).strip()),
        "trust_score": trust_score,
        "reviews":     reviews,
        "categories":  categories,
    }
