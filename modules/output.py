"""
modules/output.py
=================
Excel output management: writing the data sheet, loading for resume runs,
and appending a Summary sheet at the end of each run.

Design decisions:
  - Atomic write pattern (write to .tmp → rename) prevents corrupt output
    files if the process is interrupted mid-write. The existing output is
    never removed until the new file is fully written.
  - A 'Summary' sheet is appended after the main scrape loop completes,
    transforming the raw data file into a self-contained deliverable that
    reports key statistics alongside the data.
  - Header colour is config-driven (hex string) so the tool is not visually
    tied to any specific platform's brand colours.
  - Column names and widths are both config-driven, allowing the output
    schema to be adjusted without touching any Python code.
"""

import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

logger = logging.getLogger("scraper")


# ================================================================
# HELPERS
# ================================================================

def _header_fill(hex_color: str) -> PatternFill:
    """Convert a hex colour string to an openpyxl PatternFill."""
    color = hex_color.lstrip("#").upper()
    return PatternFill("solid", fgColor=color)


def make_output_path(prefix: str, out_dir: str = ".") -> str:
    """
    Build a dated output file path.

    Args:
        prefix:  Filename prefix (e.g. platform name from config).
        out_dir: Output directory (default: working directory).

    Returns:
        Absolute path string, e.g. "./MyPlatform_20250101.xlsx"
    """
    today = date.today().strftime("%Y%m%d")
    return os.path.join(out_dir, f"{prefix}_{today}.xlsx")


# ================================================================
# SAVE
# ================================================================

def save_xlsx(
    rows: List[dict],
    path: str,
    columns: List[str],
    col_widths: List[int],
    header_color: str = "4A90D9",
) -> None:
    """
    Write all rows to an Excel file (Data sheet only) using an atomic write.

    The 'Data' sheet is always rebuilt from scratch on each call — this is
    intentional, as it means the file is always a complete, valid snapshot
    rather than an append-only log that could grow inconsistently.

    Args:
        rows:         List of record dicts (keys must match columns).
        path:         Target .xlsx file path.
        columns:      Ordered column names (from config["output"]["columns"]).
        col_widths:   Column widths corresponding to columns list.
        header_color: Hex colour for the header row background.
    """
    if not rows:
        return

    tmp_path     = path + ".tmp"
    fill         = _header_fill(header_color)
    header_font  = Font(bold=True, color="FFFFFF", name="Segoe UI", size=10)
    center       = Alignment(horizontal="center", vertical="center")

    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Data"

        # ── Header row ────────────────────────────────────────────
        for col_idx, header in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font      = header_font
            cell.fill      = fill
            cell.alignment = center

        # ── Data rows ─────────────────────────────────────────────
        for row_idx, record in enumerate(rows, start=2):
            for col_idx, col_name in enumerate(columns, start=1):
                value = record.get(col_name, "")
                # openpyxl only accepts scalar types
                if not isinstance(value, (str, int, float, bool, type(None))):
                    value = str(value)
                ws.cell(row=row_idx, column=col_idx, value=value)

        # ── Column widths ─────────────────────────────────────────
        for col_idx, width in enumerate(col_widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        ws.freeze_panes    = "A2"
        ws.row_dimensions[1].height = 22

        # ── Atomic write ──────────────────────────────────────────
        wb.save(tmp_path)

        os.replace(tmp_path, path)  # atomic on POSIX and Windows

        logger.debug(f"Saved {len(rows)} rows → {os.path.basename(path)}")

    except Exception as exc:
        logger.error(f"Excel save error: {exc}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ================================================================
# LOAD (for resume runs)
# ================================================================

def load_xlsx(path: str) -> List[dict]:
    """
    Load an existing Excel output file for continuation runs.

    Reads the 'Data' sheet (first sheet) and returns rows as dicts.
    Non-existent or corrupt files return an empty list without raising.

    Args:
        path: Path to the .xlsx file.

    Returns:
        List of record dicts, or empty list.
    """
    if not os.path.exists(path):
        return []

    try:
        wb      = load_workbook(path, read_only=True, data_only=True)
        ws      = wb.active
        headers: Optional[List[str]] = None
        rows:    List[dict] = []

        for row in ws.iter_rows(values_only=True):
            if headers is None:
                headers = [str(h) if h is not None else "" for h in row]
                continue
            record = {
                headers[i]: (row[i] if row[i] is not None else "")
                for i in range(min(len(headers), len(row)))
                if headers[i]
            }
            rows.append(record)

        wb.close()
        logger.info(f"Loaded {len(rows)} existing rows from {os.path.basename(path)}")
        return rows

    except Exception as exc:
        logger.warning(f"Could not load existing output file: {exc}")
        return []


# ================================================================
# SUMMARY SHEET
# ================================================================

def write_summary_sheet(
    path: str,
    stats: Dict,
    header_color: str = "4A90D9",
) -> None:
    """
    Append a 'Summary' worksheet to the existing Excel output file.

    The summary sheet contains key run statistics (query, duration, record
    counts, contact data coverage) and makes the output file a standalone
    deliverable rather than a raw data dump.

    Args:
        path:         Path to the existing .xlsx output file.
        stats:        Dict of run statistics built in the main scrape loop.
        header_color: Hex colour for the title cell background.
    """
    if not os.path.exists(path):
        logger.warning("Cannot write summary — output file does not exist.")
        return

    try:
        wb = load_workbook(path)

        # Remove stale summary from a previous partial run
        if "Summary" in wb.sheetnames:
            del wb["Summary"]

        ws = wb.create_sheet("Summary")

        fill        = _header_fill(header_color)
        title_font  = Font(bold=True, color="FFFFFF", name="Segoe UI", size=13)
        label_font  = Font(bold=True, name="Segoe UI", size=10)
        value_font  = Font(name="Segoe UI", size=10)
        center      = Alignment(horizontal="center", vertical="center")
        left        = Alignment(horizontal="left",   vertical="center")

        # ── Title cell ────────────────────────────────────────────
        ws.merge_cells("A1:B1")
        title               = ws["A1"]
        title.value         = "Scrape Run Summary"
        title.font          = title_font
        title.fill          = fill
        title.alignment     = center
        ws.row_dimensions[1].height = 28

        # ── Summary rows ─────────────────────────────────────────
        summary_rows = [
            ("Platform",             stats.get("platform",   "—")),
            ("Search Query",         stats.get("query",      "—")),
            ("Run Date",             stats.get("date",       "—")),
            ("Start Time",           stats.get("start_time", "—")),
            ("End Time",             stats.get("end_time",   "—")),
            ("Duration",             stats.get("duration",   "—")),
            ("Pages Scraped",        stats.get("pages",      0)),
            ("Total Companies",      stats.get("total",      0)),
            ("With Email",           stats.get("emails",     0)),
            ("With Phone",           stats.get("phones",     0)),
            ("With Website",         stats.get("websites",   0)),
            ("Duplicates Skipped",   stats.get("duplicates", 0)),
            ("Run Status",           stats.get("status",     "—")),
        ]

        for row_idx, (label, value) in enumerate(summary_rows, start=2):
            label_cell           = ws.cell(row=row_idx, column=1, value=label)
            label_cell.font      = label_font
            label_cell.alignment = left

            value_cell           = ws.cell(row=row_idx, column=2, value=str(value))
            value_cell.font      = value_font
            value_cell.alignment = left

        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 40

        wb.save(path)
        logger.info("Summary sheet written to output file.")

    except Exception as exc:
        logger.error(f"Failed to write summary sheet: {exc}")
