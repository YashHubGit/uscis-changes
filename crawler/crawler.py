#!/usr/bin/env python3
"""
USCIS-Changes crawler
---------------------

*   Checks a small set of USCIS pages for changes
*   Saves raw HTML snapshots in /snapshots/{source}/YYYY-MM-DD.html
*   Generates side-by-side HTML diffs in docs/changes/
*   Re-writes docs/index.html with the 50 most recent diffs

Run manually or on a schedule inside GitHub Actions.
"""

from __future__ import annotations
import difflib
import hashlib
import json
import os
import sys
import datetime as dt
from pathlib import Path
from typing import Dict, List

import requests
from bs4 import BeautifulSoup   # only needed if you later parse titles

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SOURCES: Dict[str, str] = {
    "news":   "https://www.uscis.gov/newsroom/all-news",
    "alerts": "https://www.uscis.gov/newsroom/alerts",
    "policy": "https://www.uscis.gov/policy-manual/updates",
}

OUTPUT_DIR  = Path("docs")           # GitHub Pages serves /docs
CHANGES_DIR = OUTPUT_DIR / "changes" # HTML diffs live here
SNAP_DIR    = Path("snapshots")      # Raw HTML archive
INDEX_PATH  = Path("index.json")     # Stores last hashes per source

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def fetch(url: str) -> str:
    """Return raw HTML from a page, raising for non-200."""
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def diff_html(old: str, new: str, fromdesc: str, todesc: str) -> str:
    """Return an HTML side-by-side diff."""
    return difflib.HtmlDiff().make_file(
        old.splitlines(), new.splitlines(),
        fromdesc=fromdesc, todesc=todesc, context=True, numlines=2
    )

def write_home():
    """Rebuild docs/index.html from files currently in docs/changes/."""
    rows: List[str] = []
    for html_file in sorted(CHANGES_DIR.glob("*.html"), key=os.path.getmtime, reverse=True)[:50]:
        mtime = dt.datetime.fromtimestamp(html_file.stat().st_mtime, dt.timezone.utc)
        label = html_file.stem.replace("-", " ", 1)   # e.g. 'news-20250615T123456'
        rows.append(f"<li>{mtime.date()} – <a href='changes/{html_file.name}'>{label}</a></li>")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index_html = OUTPUT_DIR / "index.html"
    index_html.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>USCIS Changes</title></head><body>"
        "<h1>Latest USCIS Changes</h1><ul>"
        + "\n".join(rows) +
        "</ul></body></html>",
        encoding="utf-8"
    )

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(debug: bool = False) -> None:
    CHANGES_DIR.mkdir(parents=True, exist_ok=True)

    # Load last hashes (if any)
    if INDEX_PATH.exists():
        with INDEX_PATH.open() as f:
            index: Dict[str, str] = json.load(f)
    else:
        index = {}

    changed_this_run = False

    for name, url in SOURCES.items():
        html = fetch(url)
        digest = sha256(html)

        if debug:
            print(f"[{name}] digest {digest} (prev {index.get(name)})")

        if index.get(name) == digest:
            continue  # no update

        # New content detected -------------------------------------------------
        changed_this_run = True

        # Load previous snapshot (if any) to generate diff
        last_snap_path = SNAP_DIR / name / "latest.html"
        old_html = last_snap_path.read_text(encoding="utf-8") if last_snap_path.exists() else ""

        # Save new snapshot
        date_stamp = utc_now().date().isoformat()
        daily_snap = SNAP_DIR / name / f"{date_stamp}.html"
        daily_snap.parent.mkdir(parents=True, exist_ok=True)
        daily_snap.write_text(html, encoding="utf-8")
        last_snap_path.write_text(html, encoding="utf-8")

        # Build & save diff page
        ts = utc_now().strftime("%Y%m%dT%H%M%S")
        diff_path = CHANGES_DIR / f"{name}-{ts}.html"
        diff_path.write_text(diff_html(old_html, html, "previous", "current"), encoding="utf-8")

        if debug:
            print(f"  → change saved to {diff_path}")

        # Update hash
        index[name] = digest

    # Write updated index.json (even if no change so Git hash tracks history)
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    # Rebuild the landing page every run
    write_home()

    if debug:
        print("Done. Any changes:", changed_this_run)

if __name__ == "__main__":
    main(debug="--debug" in sys.argv)
