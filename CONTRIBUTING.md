# Contributing

Thank you for your interest in contributing to the Next.js Directory Scraper. Contributions are welcome and appreciated — especially new platform configs, bug fixes, and additional test cases. This document explains how to get set up and what is open for contribution.

---

## Setting Up Your Development Environment

```bash
# 1. Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/nextjs-directory-scraper.git
cd nextjs-directory-scraper

# 2. Install dev dependencies (pytest, ruff, pytest-cov)
pip install -r requirements-dev.txt

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Verify everything works
pytest tests/ -v
```

All 78 tests should pass in under 5 seconds with no browser or internet required.

---

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=modules --cov-report=term-missing

# Run a single test class
pytest tests/test_modules.py::TestResolvePath -v
```

Tests are pure-function only. They do not start a browser, make network calls, or write to disk outside pytest's `tmp_path` fixture. If you add a test that requires either, it must be clearly marked and isolated so the CI suite continues to run without credentials.

---

## What Contributions Are Welcome

**New platform configs** in `configs/` are the most valuable contribution. If you have verified `__NEXT_DATA__` paths for a Next.js business directory that is not yet included, add a `configs/yourplatform.json` file. Follow the structure of `configs/trustpilot.json` and add `_comment` fields explaining any platform-specific choices. See [docs/adapting_to_new_platform.md](docs/adapting_to_new_platform.md) for the full guide.

**Bug fixes** are welcome for any of the Python modules. If you find a case where `resolve_path()`, phone normalisation, or checkpoint handling behaves unexpectedly, open an issue first describing the input and expected output, then submit a fix with a corresponding regression test.

**New test cases** are always welcome. If you find an edge case that is not currently covered in `tests/test_modules.py`, add it. Follow the existing test class structure (one class per function, one method per case with a descriptive name).

**Documentation improvements** — corrections, clarifications, and additional troubleshooting entries in `docs/adapting_to_new_platform.md` or `README.md` are welcome.

---

## What NOT to Change

**The existing 8 module files are architecturally frozen.** The design — config-driven path resolution, the hybrid browser+HTTP architecture, the daemon thread hard-kill timeout, cookie transfer — represents deliberate decisions that are interdependent. Refactoring one piece in isolation tends to silently break another. If you believe a structural change is necessary, open an issue first to discuss it before writing any code.

In particular:
- Do not modify `resolve_path()` in `modules/extractor.py` — every extraction in the codebase depends on its exact `None`-handling contract.
- Do not simplify the daemon thread timeout in `modules/fetcher.py` — a plain `requests` timeout is not sufficient for TCP-level hangs.
- Do not rename or move any of the 8 module files.
- Do not convert `config.json` to YAML.

---

## How to Add a Platform Config

1. Read [docs/adapting_to_new_platform.md](docs/adapting_to_new_platform.md) in full.
2. Create `configs/yourplatform.json` — copy `config.example.json` as your starting point.
3. Replace all `YOUR_*` placeholders with real values.
4. Add `_comment` fields where the config makes platform-specific choices.
5. Add `"_note"` if any paths require manual verification before running (as in `configs/yelp.example.json`).
6. Test locally: `python scraper.py --config configs/yourplatform.json --fresh`
7. Submit a PR with only the new config file. Do not modify any Python modules or existing configs.

---

## Pull Request Checklist

Before submitting a PR, confirm:

- [ ] `pytest tests/ -v` passes with no failures or warnings.
- [ ] No new dependencies have been added to `requirements.txt` without prior discussion in an issue.
- [ ] If you have added new config fields, `config.example.json` has been updated with the new keys and `_comment` documentation.
- [ ] Your code is formatted to line length 120 (`ruff check . --line-length 120`).
- [ ] The PR description explains what changed and why.

---

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting. Line length is 120. Run before committing:

```bash
ruff check modules/ scraper.py tests/
```

No strict type-checking enforcement, but type hints are encouraged for all public function signatures, consistent with the existing codebase.
