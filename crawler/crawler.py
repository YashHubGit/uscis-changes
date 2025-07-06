import hashlib, json, os, requests, difflib, datetime as dt
from bs4 import BeautifulSoup

SOURCES = {
    "news":  "https://www.uscis.gov/newsroom/all-news",
    "alert": "https://www.uscis.gov/newsroom/alerts",
    "policy": "https://www.uscis.gov/policy-manual/updates"
}

def fetch(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def extract_items(html):
    soup = BeautifulSoup(html, "html.parser")
    return [
        {
            "title": a.get_text(strip=True),
            "url": a["href"],
            "date": dt.datetime.utcnow().isoformat()  # USCIS already prints a date; parse if you prefer
        }
        for a in soup.select("a.uscis-card__title, a.card-title")  # tweak per page
    ]

def save_snapshot(src, html):
    today = dt.date.today().isoformat()
    os.makedirs(f"snapshots/{src}", exist_ok=True)
    with open(f"snapshots/{src}/{today}.html", "w", encoding="utf-8") as f:
        f.write(html)

def diff(old, new):
    return difflib.HtmlDiff().make_file(old.splitlines(), new.splitlines(),
                                        fromdesc="previous", todesc="current")

if __name__ == "__main__":
    index = json.load(open("index.json")) if os.path.exists("index.json") else {}
    for name, url in SOURCES.items():
        html = fetch(url)
        digest = hashlib.sha256(html.encode()).hexdigest()
        if index.get(name) != digest:
            # new content detected
            old_html = open(f"snapshots/{name}.last.html", "r", encoding="utf-8").read() if os.path.exists(f"snapshots/{name}.last.html") else ""
            with open(f"snapshots/{name}.last.html", "w", encoding="utf-8") as f:
                f.write(html)
            change_html = diff(old_html, html)
            path = f"site/changes/{name}-{dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", encoding="utf-8").write(change_html)
            index[name] = digest
    json.dump(index, open("index.json", "w"), indent=2)
