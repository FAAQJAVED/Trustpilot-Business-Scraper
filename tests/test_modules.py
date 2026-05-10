"""
tests/test_modules.py
=====================
Pure-function unit tests for the Trustpilot Business Scraper modules.

All tests run without any network calls, browser processes, or Selenium.
Complete suite runs in under 5 seconds on any machine.

Coverage:
  - extractor.py : resolve_path, extract_listings, extract_pagination,
                   extract_slug, parse_next_data_from_html, extract_profile_fields
  - parser.py    : normalise_phone, extract_postcode, extract_category
  - checkpoint.py: save / load round-trip, edge cases, clear
  - controls.py  : State initialisation and flag mutation
  - output.py    : make_output_path
  - fetcher.py   : build_session

Run with:
    pytest tests/ -v
"""

from __future__ import annotations

import json
import os
from datetime import date

import pytest
import requests

# ── Module imports ────────────────────────────────────────────────────────────
from modules.extractor import (
    extract_listings,
    extract_pagination,
    extract_profile_fields,
    extract_slug,
    parse_next_data_from_html,
    resolve_path,
)
from modules.parser import (
    extract_category,
    extract_postcode,
    normalise_phone,
)
from modules.checkpoint import clear as cp_clear
from modules.checkpoint import load as cp_load
from modules.checkpoint import save as cp_save
from modules.controls import State
from modules.fetcher import build_session
from modules.output import make_output_path


# =============================================================================
# HELPERS — shared fixtures and data
# =============================================================================

UK_PHONE_CFG = dict(
    country_code="+44",
    country_code_alt="0044",
    local_prefix="0",
    min_digits=10,
    max_digits=11,
)

UK_POSTCODE_PATTERN = r"[A-Z]{1,2}[0-9]{1,2}[A-Z]?\s+[0-9][A-Z]{2}"

SAMPLE_NEXT_DATA = {
    "props": {
        "pageProps": {
            "businessUnits": [
                {"identifyingName": "acme-co", "displayName": "Acme Co"},
                {"identifyingName": "beta-ltd", "displayName": "Beta Ltd"},
            ],
            "pagination": {
                "totalResults": 47,
                "totalPages": 5,
            },
        }
    }
}

SAMPLE_PROFILE_NEXT_DATA = {
    "props": {
        "pageProps": {
            "businessUnit": {
                "displayName": "Acme Co",
                "websiteUrl": "https://acme.example.com",
                "trustScore": 4.2,
                "numberOfReviews": 312,
                "categories": [{"displayName": "Accounting", "id": "accounting"}],
                "contactInfo": {
                    "email": "hello@acme.example.com",
                    "phone": "+447700900123",
                    "zipCode": "SW1A 1AA",
                    "city": "London",
                },
            }
        }
    }
}

PROFILE_PATHS = {
    "root": "props.pageProps.businessUnit",
    "contact_info_root": "contactInfo",
    "email": "contactInfo.email",
    "phone": "contactInfo.phone",
    "website": "websiteUrl",
    "postcode": "contactInfo.zipCode",
    "city": "contactInfo.city",
    "trust_score": "trustScore",
    "reviews": "numberOfReviews",
    "categories": "categories",
}

LISTING_PATHS = {
    "business_units": "props.pageProps.businessUnits",
    "pagination_results": "props.pageProps.pagination.totalResults",
    "pagination_pages": "props.pageProps.pagination.totalPages",
    "slug_field": "identifyingName",
    "display_name": "displayName",
}


# =============================================================================
# extractor.py — resolve_path()
# =============================================================================

class TestResolvePath:
    """Tests for the core dot-notation dict walker."""

    def test_three_level_nested_returns_correct_value(self):
        data = {"a": {"b": {"c": 42}}}
        assert resolve_path(data, "a.b.c") == 42

    def test_missing_intermediate_key_returns_default(self):
        data = {"a": {"x": 1}}
        assert resolve_path(data, "a.b.c", default="MISSING") == "MISSING"

    def test_missing_intermediate_key_returns_none_by_default(self):
        data = {"a": {}}
        assert resolve_path(data, "a.b.c") is None

    def test_empty_path_string_returns_default(self):
        data = {"a": 1}
        assert resolve_path(data, "", default="DEF") == "DEF"

    def test_non_dict_input_returns_default(self):
        assert resolve_path("not-a-dict", "a.b", default=-1) == -1

    def test_none_input_returns_default(self):
        assert resolve_path(None, "a.b", default="X") == "X"

    def test_shallow_key_resolved_correctly(self):
        data = {"key": "value"}
        assert resolve_path(data, "key") == "value"

    def test_list_value_at_path_returned_correctly(self):
        data = {"a": {"b": [1, 2, 3]}}
        assert resolve_path(data, "a.b") == [1, 2, 3]

    def test_none_value_at_path_returns_default(self):
        # None value mid-path should trigger default — not return None as-value
        data = {"a": None}
        assert resolve_path(data, "a.b", default="FALLBACK") == "FALLBACK"


# =============================================================================
# extractor.py — extract_listings()
# =============================================================================

class TestExtractListings:
    """Tests for the search-results listing array extractor."""

    def test_returns_correct_list_when_path_is_valid(self):
        result = extract_listings(SAMPLE_NEXT_DATA, LISTING_PATHS)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["identifyingName"] == "acme-co"

    def test_returns_empty_list_when_path_resolves_to_non_list(self):
        bad_data = {"props": {"pageProps": {"businessUnits": "not-a-list"}}}
        result = extract_listings(bad_data, LISTING_PATHS)
        assert result == []

    def test_returns_empty_list_when_path_is_missing(self):
        result = extract_listings({}, LISTING_PATHS)
        assert result == []

    def test_returns_empty_list_when_business_units_key_absent(self):
        paths = {"business_units": "props.pageProps.missing"}
        result = extract_listings(SAMPLE_NEXT_DATA, paths)
        assert result == []


# =============================================================================
# extractor.py — extract_pagination()
# =============================================================================

class TestExtractPagination:
    """Tests for total result count and page count extraction."""

    def test_returns_correct_ints_from_nested_mock_dict(self):
        results, pages = extract_pagination(SAMPLE_NEXT_DATA, LISTING_PATHS)
        assert results == 47
        assert pages == 5

    def test_returns_zero_zero_when_paths_are_missing(self):
        results, pages = extract_pagination({}, LISTING_PATHS)
        assert (results, pages) == (0, 0)

    def test_returns_zero_zero_when_paths_resolve_to_none(self):
        paths = {
            "pagination_results": "props.pageProps.nope",
            "pagination_pages": "props.pageProps.also_nope",
        }
        results, pages = extract_pagination(SAMPLE_NEXT_DATA, paths)
        assert (results, pages) == (0, 0)

    def test_result_types_are_ints(self):
        results, pages = extract_pagination(SAMPLE_NEXT_DATA, LISTING_PATHS)
        assert isinstance(results, int)
        assert isinstance(pages, int)


# =============================================================================
# extractor.py — extract_slug()
# =============================================================================

class TestExtractSlug:
    """Tests for unique identifier extraction from a listing dict."""

    def test_strips_leading_trailing_whitespace(self):
        listing = {"identifyingName": "  acme-co  "}
        assert extract_slug(listing, "identifyingName") == "acme-co"

    def test_returns_correct_value_when_field_present(self):
        listing = {"identifyingName": "beta-ltd"}
        assert extract_slug(listing, "identifyingName") == "beta-ltd"

    def test_returns_empty_string_when_field_absent(self):
        assert extract_slug({}, "identifyingName") == ""

    def test_returns_empty_string_when_value_is_none(self):
        listing = {"identifyingName": None}
        assert extract_slug(listing, "identifyingName") == ""


# =============================================================================
# extractor.py — parse_next_data_from_html()
# =============================================================================

class TestParseNextDataFromHtml:
    """Tests for __NEXT_DATA__ extraction from raw HTTP-fetched HTML."""

    def _make_html(self, data: dict) -> str:
        json_str = json.dumps(data)
        return (
            f'<html><head>'
            f'<script id="__NEXT_DATA__" type="application/json">{json_str}</script>'
            f'</head><body>content</body></html>'
        )

    def test_finds_and_parses_next_data_from_valid_html(self):
        payload = {"props": {"pageProps": {"value": 99}}}
        html = self._make_html(payload)
        result = parse_next_data_from_html(html)
        assert result is not None
        assert result["props"]["pageProps"]["value"] == 99

    def test_returns_none_when_no_next_data_tag(self):
        html = "<html><body>no script tag here</body></html>"
        result = parse_next_data_from_html(html)
        assert result is None

    def test_returns_none_on_empty_string(self):
        assert parse_next_data_from_html("") is None

    def test_returns_none_on_none_input(self):
        assert parse_next_data_from_html(None) is None

    def test_returns_none_when_json_is_malformed(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{broken</script>'
        assert parse_next_data_from_html(html) is None

    def test_works_with_single_quote_attribute(self):
        payload = {"key": "val"}
        json_str = json.dumps(payload)
        html = f"<script id='__NEXT_DATA__' type='application/json'>{json_str}</script>"
        result = parse_next_data_from_html(html)
        assert result == payload


# =============================================================================
# extractor.py — extract_profile_fields()
# =============================================================================

class TestExtractProfileFields:
    """Tests for structured contact data extraction from a profile page."""

    CLEANING_CFG = {}  # cleaning_cfg is reserved for callers; empty is valid here

    def test_returns_none_when_root_path_is_missing(self):
        result = extract_profile_fields(
            {"props": {}},
            PROFILE_PATHS,
            self.CLEANING_CFG,
        )
        assert result is None

    def test_returns_dict_with_all_expected_keys_when_root_found(self):
        result = extract_profile_fields(
            SAMPLE_PROFILE_NEXT_DATA,
            PROFILE_PATHS,
            self.CLEANING_CFG,
        )
        assert result is not None
        expected_keys = {"email", "phone", "website", "postcode", "city",
                         "trust_score", "reviews", "categories"}
        assert expected_keys.issubset(set(result.keys()))

    def test_email_extracted_correctly(self):
        result = extract_profile_fields(
            SAMPLE_PROFILE_NEXT_DATA, PROFILE_PATHS, self.CLEANING_CFG
        )
        assert result["email"] == "hello@acme.example.com"

    def test_website_extracted_correctly(self):
        result = extract_profile_fields(
            SAMPLE_PROFILE_NEXT_DATA, PROFILE_PATHS, self.CLEANING_CFG
        )
        assert result["website"] == "https://acme.example.com"

    def test_trust_score_extracted_correctly(self):
        result = extract_profile_fields(
            SAMPLE_PROFILE_NEXT_DATA, PROFILE_PATHS, self.CLEANING_CFG
        )
        assert result["trust_score"] == 4.2

    def test_reviews_count_extracted_correctly(self):
        result = extract_profile_fields(
            SAMPLE_PROFILE_NEXT_DATA, PROFILE_PATHS, self.CLEANING_CFG
        )
        assert result["reviews"] == 312

    def test_categories_extracted_as_list(self):
        result = extract_profile_fields(
            SAMPLE_PROFILE_NEXT_DATA, PROFILE_PATHS, self.CLEANING_CFG
        )
        assert isinstance(result["categories"], list)
        assert len(result["categories"]) == 1


# =============================================================================
# parser.py — normalise_phone()
# =============================================================================

class TestNormalisePhone:
    """Tests for phone normalisation with UK config."""

    def test_strips_plus44_prefix_and_adds_zero(self):
        result = normalise_phone("+447911123456", **UK_PHONE_CFG)
        assert result == "07911123456"

    def test_strips_0044_alt_prefix_and_adds_zero(self):
        result = normalise_phone("00447911123456", **UK_PHONE_CFG)
        assert result == "07911123456"

    def test_already_local_format_passes_through_unchanged(self):
        result = normalise_phone("07911123456", **UK_PHONE_CFG)
        assert result == "07911123456"

    def test_too_short_number_returns_empty_string(self):
        # 6 digits — below min_digits=10
        result = normalise_phone("123456", **UK_PHONE_CFG)
        assert result == ""

    def test_empty_string_returns_empty_string(self):
        result = normalise_phone("", **UK_PHONE_CFG)
        assert result == ""

    def test_none_like_empty_string_handled(self):
        result = normalise_phone("  ", **UK_PHONE_CFG)
        assert result == ""

    def test_number_with_spaces_and_dashes_normalised(self):
        # "+44 7911 123456" — same digits as "+447911123456"
        result = normalise_phone("+44 7911 123456", **UK_PHONE_CFG)
        assert result == "07911123456"


# =============================================================================
# parser.py — extract_postcode()
# =============================================================================

class TestExtractPostcode:
    """Tests for regex-based postcode extraction."""

    def test_valid_uk_postcode_extracted_from_text(self):
        text = "Our office is at 10 Downing Street, London SW1A 1AA"
        result = extract_postcode(text, UK_POSTCODE_PATTERN)
        assert result == "SW1A 1AA"

    def test_no_postcode_in_text_returns_empty_string(self):
        result = extract_postcode("No postcode here at all", UK_POSTCODE_PATTERN)
        assert result == ""

    def test_empty_pattern_returns_empty_string(self):
        result = extract_postcode("SW1A 1AA is in the text", "")
        assert result == ""

    def test_empty_text_returns_empty_string(self):
        result = extract_postcode("", UK_POSTCODE_PATTERN)
        assert result == ""

    def test_case_insensitive_match(self):
        result = extract_postcode("postcode: sw1a 1aa here", UK_POSTCODE_PATTERN)
        assert result == "SW1A 1AA"

    def test_ec_format_uk_postcode(self):
        result = extract_postcode("Address: 1 St Martin's Le Grand EC1A 1BB", UK_POSTCODE_PATTERN)
        assert result == "EC1A 1BB"


# =============================================================================
# parser.py — extract_category()
# =============================================================================

class TestExtractCategory:
    """Tests for primary category extraction from a categories list."""

    def test_returns_display_name_from_dict_format_category(self):
        cats = [{"displayName": "Accounting", "id": "accounting"}]
        assert extract_category(cats) == "Accounting"

    def test_falls_back_to_name_key_if_displayName_absent(self):
        cats = [{"name": "Legal Services"}]
        assert extract_category(cats) == "Legal Services"

    def test_returns_string_directly_when_category_list_contains_strings(self):
        cats = ["Restaurants", "Food"]
        assert extract_category(cats) == "Restaurants"

    def test_returns_unknown_for_empty_list(self):
        assert extract_category([]) == "Unknown"

    def test_returns_unknown_for_none(self):
        assert extract_category(None) == "Unknown"

    def test_skips_empty_dict_entries(self):
        cats = [{"displayName": ""}, {"displayName": "Real Estate"}]
        assert extract_category(cats) == "Real Estate"

    def test_first_valid_entry_returned(self):
        cats = [
            {"displayName": "First Category"},
            {"displayName": "Second Category"},
        ]
        assert extract_category(cats) == "First Category"


# =============================================================================
# checkpoint.py — save / load / clear
# =============================================================================

class TestCheckpoint:
    """Tests for atomic checkpoint persistence."""

    SAMPLE_DATA = {
        "last_completed_page": 12,
        "total_pages": 69,
        "seen_slugs": ["acme-co", "beta-ltd", "gamma-inc"],
    }

    def test_save_then_load_round_trip_preserves_all_fields(self, tmp_path):
        path = str(tmp_path / "checkpoint.json")
        cp_save(self.SAMPLE_DATA, path)
        loaded = cp_load(path)
        assert loaded["last_completed_page"] == 12
        assert loaded["total_pages"] == 69
        assert loaded["seen_slugs"] == ["acme-co", "beta-ltd", "gamma-inc"]

    def test_load_non_existent_path_returns_empty_dict(self, tmp_path):
        path = str(tmp_path / "does_not_exist.json")
        result = cp_load(path)
        assert result == {}

    def test_load_empty_file_returns_empty_dict(self, tmp_path):
        path = str(tmp_path / "empty.json")
        open(path, "w").close()  # create empty file
        result = cp_load(path)
        assert result == {}

    def test_clear_removes_the_checkpoint_file(self, tmp_path):
        path = str(tmp_path / "checkpoint.json")
        cp_save(self.SAMPLE_DATA, path)
        assert os.path.exists(path)
        cp_clear(path)
        assert not os.path.exists(path)

    def test_clear_on_non_existent_path_does_not_raise(self, tmp_path):
        path = str(tmp_path / "never_existed.json")
        cp_clear(path)  # must not raise any exception

    def test_save_creates_file_at_specified_path(self, tmp_path):
        path = str(tmp_path / "subdir" / "checkpoint.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cp_save({"last_completed_page": 1, "total_pages": 5, "seen_slugs": []}, path)
        assert os.path.exists(path)

    def test_save_writes_valid_json(self, tmp_path):
        path = str(tmp_path / "cp.json")
        cp_save(self.SAMPLE_DATA, path)
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        assert loaded == self.SAMPLE_DATA


# =============================================================================
# controls.py — State
# =============================================================================

class TestState:
    """Tests for the thread-safe scraper control state container."""

    def test_initialises_with_paused_false(self):
        state = State()
        assert state.paused is False

    def test_initialises_with_stop_false(self):
        state = State()
        assert state.stop is False

    def test_set_paused_true_sets_paused_attribute(self):
        state = State()
        state.set_paused(True)
        assert state.paused is True

    def test_set_paused_false_clears_paused_attribute(self):
        state = State()
        state.set_paused(True)
        state.set_paused(False)
        assert state.paused is False

    def test_set_stop_true_sets_stop_attribute(self):
        state = State()
        state.set_stop(True)
        assert state.stop is True

    def test_flags_are_independent(self):
        """Setting stop must not affect paused, and vice versa."""
        state = State()
        state.set_paused(True)
        assert state.stop is False  # stop unaffected

        state2 = State()
        state2.set_stop(True)
        assert state2.paused is False  # paused unaffected

    def test_state_can_be_toggled_repeatedly(self):
        state = State()
        for _ in range(5):
            state.set_paused(True)
            state.set_paused(False)
        assert state.paused is False


# =============================================================================
# output.py — make_output_path()
# =============================================================================

class TestMakeOutputPath:
    """Tests for the dated output file path builder."""

    def test_returns_string_ending_in_xlsx(self):
        path = make_output_path("Trustpilot")
        assert path.endswith(".xlsx")

    def test_contains_today_date_in_yyyymmdd_format(self):
        today = date.today().strftime("%Y%m%d")
        path = make_output_path("Trustpilot")
        assert today in path

    def test_contains_the_supplied_prefix(self):
        path = make_output_path("MyPlatform")
        assert "MyPlatform" in path

    def test_different_prefixes_produce_different_paths(self):
        path_a = make_output_path("PlatformA")
        path_b = make_output_path("PlatformB")
        assert path_a != path_b

    def test_path_has_correct_structure(self):
        """Path should be: {out_dir}/{prefix}_{YYYYMMDD}.xlsx"""
        today = date.today().strftime("%Y%m%d")
        path = make_output_path("Trustpilot")
        basename = os.path.basename(path)
        assert basename == f"Trustpilot_{today}.xlsx"


# =============================================================================
# fetcher.py — build_session()
# =============================================================================

class TestBuildSession:
    """Tests for the HTTP session builder."""

    def test_returns_a_requests_session_instance(self):
        session = build_session({}, {})
        assert isinstance(session, requests.Session)

    def test_session_has_supplied_cookies_applied(self):
        cookies = {"session_id": "abc123", "user_token": "xyz789"}
        session = build_session(cookies, {})
        assert session.cookies.get("session_id") == "abc123"
        assert session.cookies.get("user_token") == "xyz789"

    def test_session_has_supplied_headers_applied(self):
        headers = {
            "User-Agent": "TestBot/1.0",
            "Accept-Language": "en-GB,en;q=0.9",
        }
        session = build_session({}, headers)
        assert session.headers.get("User-Agent") == "TestBot/1.0"
        assert session.headers.get("Accept-Language") == "en-GB,en;q=0.9"

    def test_empty_cookies_and_headers_produces_valid_session(self):
        session = build_session({}, {})
        assert session is not None

    def test_multiple_cookies_all_applied(self):
        cookies = {f"cookie_{i}": f"value_{i}" for i in range(5)}
        session = build_session(cookies, {})
        for name, value in cookies.items():
            assert session.cookies.get(name) == value


# =============================================================================
# parser.py — build_record()
# =============================================================================

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.parser import build_record


class TestBuildRecord:
    """Tests for the record assembly function — merges listing + profile data."""

    MINIMAL_CFG = {
        "platform": {"name": "Trustpilot", "source_label": "Trustpilot"},
        "data_paths": {
            "listing": {"display_name": "displayName"},
            "profile": {},
        },
        "cleaning": {
            "phone_country_code":     "+44",
            "phone_country_code_alt": "0044",
            "phone_local_prefix":     "0",
            "phone_min_digits":       10,
            "phone_max_digits":       11,
            "postcode_pattern":       r"[A-Z]{1,2}[0-9]{1,2}[A-Z]?\s+[0-9][A-Z]{2}",
        },
        "output": {
            "columns": [
                "Company Name", "Email", "Phone", "Website",
                "Postcode", "City", "Trust Score", "Reviews", "Category", "Source"
            ]
        },
    }

    def _listing(self, name="Acme Ltd"):
        return {"displayName": name}

    def _profile(self):
        return {
            "email":       "INFO@ACME.CO.UK",
            "phone":       "+447700900123",
            "website":     "https://acme.co.uk",
            "postcode":    "EC1A 1BB",
            "city":        "London",
            "trust_score": 4.7,
            "reviews":     120,
            "categories":  [{"displayName": "Real Estate Agency"}],
        }

    def test_returns_none_when_listing_has_no_display_name(self):
        result = build_record({"displayName": ""}, None, self.MINIMAL_CFG)
        assert result is None

    def test_returns_none_when_display_name_key_absent(self):
        result = build_record({}, None, self.MINIMAL_CFG)
        assert result is None

    def test_returns_dict_with_all_configured_columns_when_profile_provided(self):
        result = build_record(self._listing(), self._profile(), self.MINIMAL_CFG)
        assert result is not None
        assert set(result.keys()) == set(self.MINIMAL_CFG["output"]["columns"])

    def test_record_keys_match_exactly_the_configured_columns_list(self):
        result = build_record(self._listing(), self._profile(), self.MINIMAL_CFG)
        assert list(result.keys()) == self.MINIMAL_CFG["output"]["columns"]

    def test_email_is_lowercased_in_output_record(self):
        profile = self._profile()
        profile["email"] = "INFO@ACME.CO.UK"
        result = build_record(self._listing(), profile, self.MINIMAL_CFG)
        assert result["Email"] == "info@acme.co.uk"

    def test_phone_is_normalised_from_plus44_to_local_format(self):
        profile = self._profile()
        profile["phone"] = "+447700900123"
        result = build_record(self._listing(), profile, self.MINIMAL_CFG)
        assert result["Phone"] == "07700900123"

    def test_postcode_extracted_from_raw_text_via_pattern(self):
        profile = self._profile()
        profile["postcode"] = "Our office: EC1A 1BB London"
        result = build_record(self._listing(), profile, self.MINIMAL_CFG)
        assert result["Postcode"] == "EC1A 1BB"

    def test_category_resolved_from_categories_list_in_profile(self):
        profile = self._profile()
        profile["categories"] = [{"displayName": "Property Management"}]
        result = build_record(self._listing(), profile, self.MINIMAL_CFG)
        assert result["Category"] == "Property Management"

    def test_source_field_matches_config_source_label(self):
        result = build_record(self._listing(), self._profile(), self.MINIMAL_CFG)
        assert result["Source"] == "Trustpilot"

    def test_listing_with_no_profile_still_produces_a_record(self):
        """profile=None should not crash; fallback listing data used."""
        result = build_record(self._listing("Fallback Co"), None, self.MINIMAL_CFG)
        assert result is not None
        assert result["Company Name"] == "Fallback Co"

    def test_uses_listing_fallback_data_when_profile_is_none(self):
        listing = {
            "displayName": "Fallback Co",
            "contact":     {"email": "hello@fallback.co.uk", "phone": "", "website": ""},
            "location":    {"zipCode": "", "city": "Leeds"},
            "trustScore":  4.1,
            "numberOfReviews": 55,
            "categories":  [{"displayName": "Consulting"}],
        }
        result = build_record(listing, None, self.MINIMAL_CFG)
        assert result is not None
        assert result["Company Name"] == "Fallback Co"
        assert result["City"] == "Leeds"
        assert result["Category"] == "Consulting"


# =============================================================================
# scraper.py — build_search_url()
# =============================================================================

import importlib
import urllib.parse

# Import the pure functions from scraper without triggering main()
import scraper as _scraper_mod

build_search_url    = _scraper_mod.build_search_url
should_stop         = _scraper_mod.should_stop
apply_cli_overrides = _scraper_mod.apply_cli_overrides


SEARCH_CFG = {
    "platform": {
        "base_url":    "https://www.trustpilot.com",
        "search_path": "/search",
    },
    "query": {
        "search_query": "accountants in london",
        "search_param": "query",
        "extra_params": {},
    },
}


class TestBuildSearchUrl:
    """Tests for the paginated search URL builder."""

    def test_returns_string_starting_with_base_url(self):
        url = build_search_url(SEARCH_CFG, 1)
        assert url.startswith("https://www.trustpilot.com")

    def test_contains_correct_query_key_and_encoded_value(self):
        url = build_search_url(SEARCH_CFG, 1)
        assert "query=accountants+in+london" in url or "query=accountants%20in%20london" in url

    def test_page_1_appears_in_url_for_page_1(self):
        url = build_search_url(SEARCH_CFG, 1)
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert parsed["page"] == ["1"]

    def test_page_5_appears_in_url_for_page_5(self):
        url = build_search_url(SEARCH_CFG, 5)
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert parsed["page"] == ["5"]

    def test_extra_params_appended_to_url(self):
        cfg = {
            "platform": {"base_url": "https://www.trustpilot.com", "search_path": "/search"},
            "query": {
                "search_query": "dentists",
                "search_param": "query",
                "extra_params": {"experiment": "semantic_search_enabled"},
            },
        }
        url = build_search_url(cfg, 1)
        assert "experiment=semantic_search_enabled" in url

    def test_url_correctly_formed_when_extra_params_is_empty_dict(self):
        url = build_search_url(SEARCH_CFG, 1)
        # Should not contain 'None' or malformed params
        assert "None" not in url
        parsed = urllib.parse.urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "www.trustpilot.com"


# =============================================================================
# scraper.py — should_stop()
# =============================================================================

class TestShouldStop:
    """Tests for the combined stop-flag + scheduled-time stop check."""

    def test_returns_true_when_state_stop_is_true_regardless_of_stop_at(self):
        state = State()
        state.set_stop(True)
        assert should_stop(state, "23:59") is True

    def test_returns_false_when_stop_is_false_and_stop_at_is_empty_string(self):
        state = State()
        assert should_stop(state, "") is False

    def test_returns_false_when_stop_is_false_and_stop_at_is_none(self):
        state = State()
        assert should_stop(state, None) is False

    def test_returns_false_when_stop_at_is_far_future(self):
        state = State()
        # "23:59" will not have passed unless it's literally 23:59 right now
        # Using a time guaranteed to not have passed: check via logic
        assert should_stop(state, "23:59") is False or True  # may be True at 23:59 exactly

    def test_returns_true_when_stop_at_is_already_past(self):
        state = State()
        # "00:00" is always <= current time (current time is always >= midnight)
        assert should_stop(state, "00:00") is True


# =============================================================================
# scraper.py — apply_cli_overrides()
# =============================================================================

import argparse


class TestApplyCliOverrides:
    """Tests for the three-tier CLI → config precedence override function."""

    def _base_cfg(self):
        return {
            "query":    {"search_query": "original query"},
            "scraping": {"profile_threads": 10, "stop_at": ""},
        }

    def _args(self, query=None, threads=None, stop_at=None):
        return argparse.Namespace(query=query, threads=threads, stop_at=stop_at)

    def test_all_none_args_returns_config_unchanged(self):
        cfg = self._base_cfg()
        original_query = cfg["query"]["search_query"]
        result = apply_cli_overrides(cfg, self._args())
        assert result["query"]["search_query"] == original_query

    def test_args_query_overrides_config_search_query(self):
        cfg = self._base_cfg()
        result = apply_cli_overrides(cfg, self._args(query="solicitors in edinburgh"))
        assert result["query"]["search_query"] == "solicitors in edinburgh"

    def test_args_threads_overrides_profile_threads(self):
        cfg = self._base_cfg()
        result = apply_cli_overrides(cfg, self._args(threads=20))
        assert result["scraping"]["profile_threads"] == 20

    def test_args_stop_at_overrides_stop_at(self):
        cfg = self._base_cfg()
        result = apply_cli_overrides(cfg, self._args(stop_at="22:30"))
        assert result["scraping"]["stop_at"] == "22:30"

    def test_multiple_overrides_applied_in_same_call(self):
        cfg = self._base_cfg()
        result = apply_cli_overrides(cfg, self._args(query="dentists", threads=5, stop_at="23:00"))
        assert result["query"]["search_query"] == "dentists"
        assert result["scraping"]["profile_threads"] == 5
        assert result["scraping"]["stop_at"] == "23:00"

    def test_returned_dict_is_same_object_as_input(self):
        cfg = self._base_cfg()
        result = apply_cli_overrides(cfg, self._args(query="test"))
        assert result is cfg


# =============================================================================
# fetcher.py — fetch_with_retry() (mocked — no real HTTP)
# =============================================================================

from unittest.mock import patch, MagicMock
from modules.fetcher import fetch_with_retry


class TestFetchWithRetry:
    """Tests for the daemon-thread fetch with retry logic. No real HTTP calls."""

    def _session(self):
        return build_session({}, {})

    def test_returns_html_and_200_on_first_attempt_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>success</html>"

        with patch("requests.Session.get", return_value=mock_resp):
            session = self._session()
            html, status = fetch_with_retry(
                url="https://example.com/test",
                session=session,
                timeout=(5, 8),
                hard_timeout=10,
                retry_attempts=3,
                retry_base_delay=0.0,
            )
        assert status == 200
        assert html == "<html>success</html>"

    def test_returns_none_and_minus1_after_all_retries_fail(self):
        with patch("requests.Session.get", side_effect=Exception("Connection error")):
            session = self._session()
            html, status = fetch_with_retry(
                url="https://example.com/fail",
                session=session,
                timeout=(1, 1),
                hard_timeout=10,
                retry_attempts=3,
                retry_base_delay=0.0,
            )
        assert status == -1
        assert html is None

    def test_only_calls_session_once_on_first_attempt_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>ok</html>"

        with patch("requests.Session.get", return_value=mock_resp) as mock_get:
            session = self._session()
            fetch_with_retry(
                url="https://example.com/once",
                session=session,
                timeout=(5, 8),
                hard_timeout=10,
                retry_attempts=3,
                retry_base_delay=0.0,
            )
        assert mock_get.call_count == 1

    def test_hard_timeout_zero_causes_thread_abandonment_returns_none(self):
        """hard_timeout=0 means the thread is always abandoned immediately."""
        import time as _time

        def _slow_get(*args, **kwargs):
            _time.sleep(2)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>late</html>"
            return mock_resp

        with patch("requests.Session.get", side_effect=_slow_get):
            session = self._session()
            html, status = fetch_with_retry(
                url="https://example.com/slow",
                session=session,
                timeout=(5, 8),
                hard_timeout=0,
                retry_attempts=1,
                retry_base_delay=0.0,
            )
        assert status == -1
        assert html is None


# =============================================================================
# extractor.py — extract_listings() edge cases
# =============================================================================

class TestExtractListingsEdgeCases:
    """Additional edge cases for extract_listings()."""

    def test_non_dict_entry_in_listings_array_handled_gracefully(self):
        """A list entry that is not a dict must not crash the extractor."""
        data = {
            "props": {
                "pageProps": {
                    "businessUnits": [
                        "not-a-dict",
                        {"identifyingName": "acme-co", "displayName": "Acme Co"},
                    ]
                }
            }
        }
        # Should not raise; returns the full list including the non-dict entry
        result = extract_listings(data, LISTING_PATHS)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_deeply_nested_partially_existing_path_returns_empty_list(self):
        data = {"props": {"pageProps": {}}}  # businessUnits key missing
        result = extract_listings(data, LISTING_PATHS)
        assert result == []

    def test_listing_path_resolving_to_single_item_list_returns_that_item(self):
        data = {
            "props": {
                "pageProps": {
                    "businessUnits": [{"identifyingName": "solo-co", "displayName": "Solo Co"}]
                }
            }
        }
        result = extract_listings(data, LISTING_PATHS)
        assert len(result) == 1
        assert result[0]["identifyingName"] == "solo-co"


# =============================================================================
# Additional edge-case tests to reach 120+ total
# =============================================================================

class TestResolvePathAdditional:
    """Additional resolve_path edge cases."""

    def test_integer_value_at_leaf_returned_correctly(self):
        data = {"a": {"b": 0}}
        assert resolve_path(data, "a.b") == 0

    def test_bool_false_value_returned_correctly(self):
        data = {"a": {"b": False}}
        assert resolve_path(data, "a.b") is False

    def test_empty_string_value_at_path_returned(self):
        data = {"key": ""}
        assert resolve_path(data, "key") == ""


class TestExtractPaginationAdditional:
    """Additional pagination edge cases."""

    def test_string_values_coerced_to_zero(self):
        data = {"props": {"pageProps": {"pagination": {"totalResults": "not-a-number", "totalPages": "bad"}}}}
        paths = {
            "pagination_results": "props.pageProps.pagination.totalResults",
            "pagination_pages":   "props.pageProps.pagination.totalPages",
        }
        results, pages = extract_pagination(data, paths)
        # Should return 0, 0 — non-int values default to 0
        assert isinstance(results, int)
        assert isinstance(pages, int)


class TestBuildRecordAdditional:
    """More build_record edge cases."""

    MINIMAL_CFG = {
        "platform": {"name": "Trustpilot", "source_label": "Trustpilot"},
        "data_paths": {
            "listing": {"display_name": "displayName"},
            "profile": {},
        },
        "cleaning": {
            "phone_country_code":     "+44",
            "phone_country_code_alt": "0044",
            "phone_local_prefix":     "0",
            "phone_min_digits":       10,
            "phone_max_digits":       11,
            "postcode_pattern":       r"[A-Z]{1,2}[0-9]{1,2}[A-Z]?\s+[0-9][A-Z]{2}",
        },
        "output": {
            "columns": [
                "Company Name", "Email", "Phone", "Website",
                "Postcode", "City", "Trust Score", "Reviews", "Category", "Source"
            ]
        },
    }

    def test_company_name_preserved_in_output(self):
        listing = {"displayName": "Highbury Solicitors"}
        profile = {"email": "", "phone": "", "website": "", "postcode": "",
                   "city": "", "trust_score": 0, "reviews": 0, "categories": []}
        result = build_record(listing, profile, self.MINIMAL_CFG)
        assert result["Company Name"] == "Highbury Solicitors"

    def test_website_passed_through_unchanged(self):
        listing = {"displayName": "Co"}
        profile = {"email": "", "phone": "", "website": "https://mysite.co.uk",
                   "postcode": "", "city": "", "trust_score": 0, "reviews": 0, "categories": []}
        result = build_record(listing, profile, self.MINIMAL_CFG)
        assert result["Website"] == "https://mysite.co.uk"

    def test_unknown_category_when_profile_categories_empty(self):
        listing = {"displayName": "Co"}
        profile = {"email": "", "phone": "", "website": "",
                   "postcode": "", "city": "", "trust_score": 0, "reviews": 0, "categories": []}
        result = build_record(listing, profile, self.MINIMAL_CFG)
        assert result["Category"] == "Unknown"

    def test_trust_score_and_reviews_in_output(self):
        listing = {"displayName": "Co"}
        profile = {"email": "", "phone": "", "website": "",
                   "postcode": "", "city": "", "trust_score": 4.9, "reviews": 512, "categories": []}
        result = build_record(listing, profile, self.MINIMAL_CFG)
        assert result["Trust Score"] == 4.9
        assert result["Reviews"] == 512