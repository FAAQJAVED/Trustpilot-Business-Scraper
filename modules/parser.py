"""
modules/parser.py
=================
Data cleaning and output record assembly.

All cleaning rules (phone normalisation, postcode extraction, digit bounds)
are supplied via the config["cleaning"] dict — no country-specific logic is
hardcoded here. This means the same code handles UK postcodes, US ZIP codes,
German PLZs, or any other format simply by changing config.json.

Public API:
    normalise_phone()  — strip international prefix, validate digit count
    extract_postcode() — regex-based postcode/ZIP extraction
    extract_category() — first valid category name from a categories list
    build_record()     — merge listing + profile data into a clean output dict
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scraper")


# ================================================================
# PHONE NORMALISATION
# ================================================================

def normalise_phone(
    raw: str,
    country_code: str,
    country_code_alt: str,
    local_prefix: str,
    min_digits: int,
    max_digits: int,
) -> str:
    """
    Normalise a raw phone string to a local-format digit sequence.

    Strips the international dialing prefix (if present) and replaces it
    with the configured local prefix. The result is validated by digit count.

    Examples (using UK config: country_code="+44", local_prefix="0"):
        "+447911123456" → "07911123456"
        "00447911123456" → "07911123456"
        "07911123456"    → "07911123456"
        "555-1234"       → "" (too short, < min_digits)

    Args:
        raw:              Raw phone string from the data source.
        country_code:     International prefix to strip (e.g. "+44", "+1").
        country_code_alt: Alternate prefix form (e.g. "0044").
        local_prefix:     Prefix to prepend after stripping (e.g. "0", "1").
        min_digits:       Minimum digit count for a valid number (inclusive).
        max_digits:       Maximum digit count for a valid number (inclusive).

    Returns:
        Normalised digit string, or empty string if the input is invalid.
    """
    if not raw:
        return ""

    cleaned = str(raw).strip()

    # Strip international dialing prefix and replace with local prefix
    if country_code and cleaned.startswith(country_code):
        cleaned = local_prefix + cleaned[len(country_code):]
    elif country_code_alt and cleaned.startswith(country_code_alt):
        cleaned = local_prefix + cleaned[len(country_code_alt):]

    # Remove all non-digit characters to count and validate
    digits = re.sub(r"\D", "", cleaned)

    if min_digits <= len(digits) <= max_digits:
        return digits
    return ""


# ================================================================
# POSTCODE / ZIP EXTRACTION
# ================================================================

def extract_postcode(text: str, pattern: str) -> str:
    """
    Extract a postcode or ZIP code from a text string using a configurable regex.

    The pattern is supplied by config["cleaning"]["postcode_pattern"], making
    this function locale-agnostic. Any valid Python regex works.

    Example patterns:
        UK:  r"[A-Z]{1,2}[0-9]{1,2}[A-Z]?\\s+[0-9][A-Z]{2}"
        US:  r"\\b[0-9]{5}(?:-[0-9]{4})?\\b"
        DE:  r"\\b[0-9]{5}\\b"

    Args:
        text:    Raw text that may contain a postcode (searched case-insensitively).
        pattern: Regex pattern from config. Empty string disables extraction.

    Returns:
        Matched string with normalised whitespace, or empty string.
    """
    if not text or not pattern:
        return ""

    try:
        match = re.search(pattern, str(text).upper())
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()
    except re.error as exc:
        logger.warning(f"Invalid postcode_pattern in config: {exc}")

    return ""


# ================================================================
# CATEGORY EXTRACTION
# ================================================================

def extract_category(categories: List[Any]) -> str:
    """
    Return the primary category name from a categories list.

    Handles both dict-format categories (with a "displayName" or "name" key)
    and plain string categories. Returns "Unknown" if the list is empty or
    all entries are malformed.

    Args:
        categories: List of category objects (dicts or strings).

    Returns:
        First valid category name string, or "Unknown".
    """
    for cat in (categories or []):
        if isinstance(cat, dict):
            name = (
                cat.get("displayName")
                or cat.get("name")
                or cat.get("categoryName")
                or ""
            ).strip()
            if name:
                return name
        elif isinstance(cat, str) and cat.strip():
            return cat.strip()

    return "Unknown"


# ================================================================
# RECORD ASSEMBLY
# ================================================================

def build_record(
    listing: dict,
    profile: Optional[dict],
    config: dict,
) -> Optional[dict]:
    """
    Merge listing-level and profile-level data into a single, clean output record.

    Falls back gracefully to listing data if the profile HTTP fetch failed —
    listing data typically has less contact detail but is always available.

    The output dict keys match exactly the column names in config["output"]["columns"],
    so the record can be written to Excel without any further transformation.

    Args:
        listing: Raw listing dict from the search results page.
        profile: Parsed profile dict from extractor.extract_profile_fields(),
                 or None if the profile fetch/parse failed.
        config:  Full config dict (for cleaning rules, paths, output columns,
                 and platform source label).

    Returns:
        Populated record dict, or None if no company name could be extracted.
    """
    listing_paths = config["data_paths"]["listing"]
    cleaning      = config["cleaning"]
    output_cfg    = config["output"]

    # Company name is mandatory — skip records without it
    name_field = listing_paths.get("display_name", "displayName")
    name = (listing.get(name_field) or "").strip()
    if not name:
        logger.debug("Skipping listing with no display name.")
        return None

    # ── Choose data source ────────────────────────────────────────
    if profile is not None:
        raw_email    = profile.get("email",       "")
        raw_phone    = profile.get("phone",       "")
        website      = profile.get("website",     "")
        raw_postcode = profile.get("postcode",    "")
        city         = profile.get("city",        "")
        trust_score  = profile.get("trust_score", "")
        reviews      = profile.get("reviews",     0)
        categories   = profile.get("categories",  [])
    else:
        # Fallback: listing-level data (less detail, always present)
        contact  = listing.get("contact")  or {}
        location = listing.get("location") or {}
        raw_email    = (contact.get("email")   or "").strip().lower()
        raw_phone    = contact.get("phone")    or ""
        website      = (contact.get("website") or "").strip()
        raw_postcode = location.get("zipCode") or ""
        city         = (location.get("city")   or "").strip()
        trust_score  = listing.get("trustScore",       "")
        reviews      = listing.get("numberOfReviews",  0)
        categories   = listing.get("categories") or []

    # ── Apply cleaning rules ──────────────────────────────────────
    phone = normalise_phone(
        raw=str(raw_phone),
        country_code=cleaning.get("phone_country_code",     ""),
        country_code_alt=cleaning.get("phone_country_code_alt", ""),
        local_prefix=cleaning.get("phone_local_prefix",     ""),
        min_digits=cleaning.get("phone_min_digits",         7),
        max_digits=cleaning.get("phone_max_digits",         15),
    )

    postcode_pattern = cleaning.get("postcode_pattern", "")
    postcode = (
        extract_postcode(raw_postcode, postcode_pattern)
        if postcode_pattern
        else str(raw_postcode).strip()
    )

    category     = extract_category(categories)
    source_label = (
        config["platform"].get("source_label")
        or config["platform"].get("name", "")
    )

    # ── Build output record keyed by configured column names ──────
    field_map: Dict[str, Any] = {
        "Company Name": name,
        "Email":        str(raw_email).strip().lower(),
        "Phone":        phone,
        "Website":      str(website).strip(),
        "Postcode":     postcode,
        "City":         str(city).strip(),
        "Trust Score":  trust_score,
        "Reviews":      reviews,
        "Category":     category,
        "Source":       source_label,
    }

    record: dict = {}
    for col in output_cfg.get("columns", list(field_map.keys())):
        record[col] = field_map.get(col, "")

    return record
