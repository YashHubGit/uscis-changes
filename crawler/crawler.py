#!/usr/bin/env python3
"""
USCIS-Changes crawler + GPT summaries
-------------------------------------

* Checks key USCIS pages for updates.
* Saves raw snapshots in /snapshots/{source}/YYYY-MM-DD.html
* Generates HTML diffs in docs/changes/
* Summarises each diff with GPT-4o-mini (needs OPENAI_API_KEY in env/secret).
* Logs title/summary/path in changes_log.json
* Rewrites docs/index.html with the 50 newest entries.

Run manually or inside GitHub Actions.
"""

from __future__ import annotations
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List

import requests
import openai

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

openai.api_key = os.getenv("OPENAI_API_KEY")

SOURCES: Dict[str, str] = {
    "news":   "https://www.uscis.gov/newsroom/all-news",
    "alerts": "https://www.uscis.gov/newsroom/alerts",
    "policy": "https://www.uscis.gov/policy-manual/updates",
}

OUTPUT_DIR       = Path("docs")              # GitHub Pages serves /docs
CHANGES_DIR      = OUTPUT_DIR / "changes"    # where diffs live
SNAP_DIR         = Path("snapshots")         # raw HTML archive
HASH_INDEX_PATH  = Path("index.json")        # last-seen SHA256 per source
CHANGE_LOG_PATH  = Path("changes_log.json")  # running list with summaries

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def fetch(url: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def diff_html(old: str, new: str) -> str:
    return difflib.HtmlDiff().make_file(
        old.splitlines(), new.splitlines(),
        fromdesc="previous", todesc="current",
        context=True, numlines=2
    )

def summarize(diff_html_text: str) -> str:
    """
    Ask GPT-4o-mini for a concise, max-3-bullet summary of this diff.
    Falls back to a placeholder on failure.
    """
    if not openai.api_key:
        return "OpenAI API key not configured."

    # crude text extraction to keep tokens low
    plain = re.sub(r"<[^>]+>", " ", diff_html_text)
    plain = re.sub(r"\s+", " ", html.unescape(plain))[:4000]

    messages = [
        {"role": "system",
         "content": "You track U.S. immigration (USCIS) policy updates."},
        {"role": "user",
         "content": (
             "Summarize the following USCIS website change in **at most three concise bullet points**. "
             "Return **only** the bullet list:\n\n" + plain)}
    ]

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # noqa: BLE001
        print("⚠️  GPT summary failed:", exc, file=sys.stderr)
        return "Summary unavailable."

def write_home(entries: List[dict]) -> None:
    """
    Build docs/index.html from `entries`, newest first.
    Each entry: {ts, title, path, summary}
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: List[str] = []
    for e in entries[:50]:
        date = e["ts"][:10]
        rows.append(
            f"<li>{date} – <a href='changes/{e['path']}'>{html.escape(e['title'])}</a>"
            f"<br><em>{html.escape(e['summary'])}</em></li>"
        )

    (OUTPUT_DIR / "index.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>USCIS Changes</title></head><body>"
        "<h1>Latest USCIS Updates</h1><ul>\n"
        + "\n".join(rows) +
        "\n</ul></body></html>",
        encoding="utf-8",
    )

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(debug: bool = False) -> None:
    CHANGES_DIR.mkdir(parents=True, exist_ok=True)

    # Load per-source hash index
    hash_index: Dict[str, str] = {}
    if HASH_INDEX_PATH.exists():
        hash_index = json.loads(HASH_INDEX_PATH.read_text())

    # Load change log (list of dicts, newest first)
    change_log: List[dict] = []
    if CHANGE_LOG_PATH.exists():
        change_log = json.loads(CHANGE_LOG_PATH.read_text())

    for name, url in SOURCES.items():
        html_cur = fetch(url)
        digest    = sha256(html_cur)

        if debug:
            print(f"[{name}] digest={digest} previous={hash_index.get(name)}")

        if hash_index.get(name) == digest:
            continue  # no change detected

        # ------- generate diff ------------------------------------------------
        last_snap = SNAP_DIR / name / "latest.html"
        old_html  = last_snap.read_text(encoding="utf-8") if last_snap.exists() else ""

        diff_text = diff_html(old_html, html_cur)

        ts_str     = utc_now().strftime("%Y%m%dT%H%M%S")
        diff_file  = CHANGES_DIR / f"{name}-{ts_str}.html"
        diff_file.write_text(diff_text, encoding="utf-8")

        # ------- GPT summary --------------------------------------------------
        summary = summarize(diff_text)

        # ------- save snapshot ------------------------------------------------
        date_stamp = utc_now().date().isoformat()
        daily_snap = SNAP_DIR / name / f"{date_stamp}.html"
        daily_snap.parent.mkdir(parents=True, exist_ok=True)
        daily_snap.write_text(html_cur, encoding="utf-8")
        last_snap.write_text(html_cur, encoding="utf-8")

        # ------- update bookkeeping ------------------------------------------
        hash_index[name] = digest
        change_log.insert(0, {          # newest first
            "ts": utc_now().isoformat(timespec="seconds"),
            "title": f"{name} page updated",
            "path": diff_file.name,
            "summary": summary,
        })

        if debug:
            print(f"  ➜ saved diff {diff_file.name}")

    # persist indices
    HASH_INDEX_PATH.write_text(json.dumps(hash_index, indent=2))
    CHANGE_LOG_PATH.write_text(json.dumps(change_log[:200], indent=2))  # keep log bounded

    # rewrite homepage
    write_home(change_log)

    if debug:
        print("✓ run complete – homepage rebuilt")

if __name__ == "__main__":
    main(debug="--debug" in sys.argv)
