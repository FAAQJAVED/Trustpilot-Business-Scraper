"""
modules — TrustPilot Business Scraper internal package.

Public re-exports for the six pure-logic modules that are unit-tested.
Browser and logger modules are excluded — they require system resources
(Selenium, Chrome, file handles) and are imported directly in scraper.py.
"""

from modules.checkpoint import clear, load, save
from modules.extractor import (
    extract_listings,
    extract_pagination,
    extract_profile_fields,
    extract_slug,
    parse_next_data_from_html,
    resolve_path,
)
from modules.fetcher import build_session, fetch_profiles_parallel, fetch_with_retry
from modules.output import make_output_path
from modules.parser import build_record, extract_category, extract_postcode, normalise_phone

__all__ = [
    "clear", "load", "save",
    "extract_listings", "extract_pagination", "extract_profile_fields",
    "extract_slug", "parse_next_data_from_html", "resolve_path",
    "build_session", "fetch_profiles_parallel", "fetch_with_retry",
    "make_output_path",
    "build_record", "extract_category", "extract_postcode", "normalise_phone",
]
