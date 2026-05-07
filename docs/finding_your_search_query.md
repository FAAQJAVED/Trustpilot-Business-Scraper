# Finding Your Trustpilot Search Query

This guide explains how to find a good search query for the scraper and how to set it in `config.json`.

---

## How Trustpilot Search Works

Trustpilot's search accepts a plain-text query combining a **business type** and a **location**. The scraper passes this query directly to Trustpilot's search endpoint and pages through all results automatically.

---

## Step 1 — Find Your Query on Trustpilot

1. Go to [https://www.trustpilot.com/search](https://www.trustpilot.com/search)
2. Type your business type and location into the search box — for example: `accountants in Manchester`
3. Press Enter and look at the URL in your browser's address bar. It will look like:
   ```
   https://www.trustpilot.com/search?query=accountants+in+Manchester
   ```
4. The value after `query=` (decoded) is your search query: `accountants in Manchester`

---

## Step 2 — Set It in config.json

Open `config.json` and update the `search_query` field:

```json
"query": {
    "search_query": "accountants in Manchester"
}
```

Save the file. That's it — the scraper uses this value on every run.

---

## Step 3 — Or Use the --query Flag (No File Edit Needed)

For a one-off run without editing `config.json`:

```bash
python scraper.py --query "solicitors in London"
```

This overrides `search_query` for that run only. `config.json` is not modified.

---

## Example Queries

These are all valid queries ready to paste into `config.json` or `--query`:

| Query | What it returns |
|---|---|
| `accountants in Manchester` | Accounting firms in Greater Manchester |
| `solicitors in London` | Law firms across London |
| `property managers Birmingham` | Property management companies in Birmingham |
| `electricians in Leeds` | Electrical contractors in Leeds |
| `dentists in Bristol` | Dental practices in Bristol |

---

## Tips for Better Results

- **Be specific with location** — `"accountants in Manchester"` returns more targeted results than `"accountants"` alone.
- **Try the search on Trustpilot first** — check that the results shown in the browser are what you expect before running the scraper.
- **Quotation marks are not needed** — the query goes into the URL as-is; no special quoting required.
- **Pagination is handled automatically** — the scraper pages through all results until no new listings appear.
