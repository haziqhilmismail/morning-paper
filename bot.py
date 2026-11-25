#!/usr/bin/env python3
"""Telegram bot: links sent from my own chat go into the Shared feed. /now rebuilds the paper.

Appends "YYYY-MM-DD<TAB>url<TAB>title" to data/shared.tsv and writes the newest links to
www/feeds/shared.xml with each article's text. The server fetches the articles, so the
e-reader contacts only this server: some sites block KOReader, and News Downloader would
send the paper password to every site that it opens.
"""
import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE / "data" / "shared.tsv"
ARCHIVE = HERE / "data" / "archive.tsv"
FEED = HERE / "www" / "feeds" / "shared.xml"
URL = re.compile(r"https?://[^\s<>\"]+")
ARTICLES = HERE / "data" / "shared"
KEEP = 10
# Runs in the morning-paper image (run.sh builds it), which has trafilatura. Prints the title, then the HTML.
EXTRACT = """
import sys, requests, trafilatura
from trafilatura.utils import decode_file
r = requests.get(sys.argv[1], timeout=30, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml"})
r.raise_for_status()
page = decode_file(r.content)
meta = trafilatura.extract_metadata(page)
print(" ".join(((meta and meta.title) or sys.argv[1]).split()))
print(trafilatura.extract(page, output_format="html", include_images=True, include_links=True) or "")
"""


def api(method, wait=10, **params):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['PAPER_BOT_TOKEN']}/{method}",
        data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=wait) as resp:
        return json.load(resp)["result"]


def links(msg):
    text = msg.get("text") or msg.get("caption") or ""
    entities = msg.get("entities") or msg.get("caption_entities") or []
    found = URL.findall(" ".join([*(e["url"] for e in entities if e.get("type") == "text_link"), text]))
    # Drop sentence punctuation after a link, but keep the ")" of links like /wiki/Foo_(bar).
    found = [u.rstrip(".,;") for u in found]
    found = [u[:-1] if u.endswith(")") and u.count(")") > u.count("(") else u for u in found]
    return list(dict.fromkeys(found))


def page(url):
    return ARTICLES / f"{hashlib.sha1(url.encode()).hexdigest()}.html"


def fetch(url):
    """Save the article text to data/shared/ and return its title. A failed fetch keeps only the link."""
    try:
        out = subprocess.run(["docker", "run", "--rm", "--memory", "512m", "morning-paper", "python", "-c", EXTRACT, url],
                             capture_output=True, text=True, timeout=120, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        print(f"fetch {url} failed: {e}", flush=True)
        return url
    title, _, body = out.partition("\n")
    ARTICLES.mkdir(parents=True, exist_ok=True)
    page(url).write_text(body, encoding="utf-8")
    return title or url


def read(path):
    return [ln.split("\t") for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []


def save(path, rows):
    tmp = path.with_name(f".{path.name}")
    tmp.write_text("".join("\t".join(r) + "\n" for r in rows))
    tmp.replace(path)


def name(row):
    return row[2] if len(row) > 2 else row[1]


def numbered(path, empty):
    """Newest first, so number 1 is the link that you sent last."""
    rows = read(path)[::-1]
    return "\n".join(f"{i}. {name(r)}" for i, r in enumerate(rows, 1)) or empty


def remove(args, archive):
    rows = read(SHARED)[::-1]
    picks = {int(a) for a in args if a.isdigit() and 1 <= int(a) <= len(rows)}
    if not picks:
        return "Send the command with numbers from /list, for example /delete 2 or /archive 1 3."
    gone = [r for i, r in enumerate(rows, 1) if i in picks]
    save(SHARED, [r for i, r in enumerate(rows, 1) if i not in picks][::-1])
    if archive:
        with ARCHIVE.open("a") as f:
            f.writelines("\t".join(r) + "\n" for r in gone[::-1])
    write_feed()
    verb = "Archived" if archive else "Deleted"
    return f"{verb} from the Shared feed:\n" + "\n".join(f"- {name(r)}" for r in gone) + \
        "\nCopies already on the e-reader stay there."


def write_feed():
    rows = read(SHARED)
    for old in ARTICLES.glob("*.html") if ARTICLES.exists() else []:
        if old not in {page(r[1]) for r in rows}:
            old.unlink()

    def body(url):
        text = page(url).read_text(encoding="utf-8") if page(url).exists() else ""
        text = re.sub(r"</?(html|body)\b[^>]*>", "", text)
        text = text.strip() or "<p>The server could not get this article. Open the link on another device.</p>"
        return f'{text}<p><a href="{html.escape(url)}">{html.escape(url)}</a></p>'.replace("]]>", "]]&gt;")

    items = "".join(
        f"<item><title>{html.escape(name(r))}</title><link>{html.escape(r[1])}</link>"
        f"<guid>{html.escape(r[1])}</guid><description><![CDATA[{body(r[1])}]]></description>"
        f"<pubDate>{format_datetime(datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc))}</pubDate></item>"
        for r in reversed(rows))
    # News Downloader rejects a feed with no items.
    items = items or ('<item><title>No shared links yet</title><link>https://github.com/haziqhilmismail/morning-paper</link>'
                      '<pubDate>Sat, 01 Jan 2000 00:00:00 GMT</pubDate></item>')
    FEED.parent.mkdir(parents=True, exist_ok=True)
    tmp = FEED.with_name(".shared.xml")
    tmp.write_text('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Shared</title>'
                   '<link>https://github.com/haziqhilmismail/morning-paper</link>'
                   f'<description>Links sent to the Telegram bot</description>{items}</channel></rss>', encoding="utf-8")
    tmp.replace(FEED)


def handle(msg):
    text = (msg.get("text") or "").strip()
    cmd, *args = text.split() or [""]
    cmd = cmd.split("@")[0]
    if cmd == "/now":
        subprocess.run(["systemctl", "--user", "start", "--no-block", "morning-paper.service"], check=True)
        return "Building the paper now. It is ready in about 10 minutes."
    if cmd == "/list":
        return numbered(SHARED, "The Shared feed is empty.")
    if cmd == "/archived":
        return numbered(ARCHIVE, "The archive is empty.")
    if cmd in ("/archive", "/delete"):
        return remove(args, archive=cmd == "/archive")
    urls = links(msg)
    if not urls:
        return ("Send me an article link to add it to the Shared feed.\n/list shows the feed. /archive N and /delete N "
                "remove link N from it. /archived shows the archive. /now rebuilds the paper.")
    with SHARED.open("a") as f:
        f.writelines(f"{date.today().isoformat()}\t{u}\t{fetch(u).replace(chr(9), ' ')}\n" for u in urls)
    rows = read(SHARED)
    old = rows[:-KEEP]
    if old:
        # Removed links go to the archive, so /archived still finds them.
        save(SHARED, rows[-KEEP:])
        with ARCHIVE.open("a") as f:
            f.writelines("\t".join(r) + "\n" for r in old)
    write_feed()
    note = "".join(f"\nRemoved the oldest, now in /archived: {name(r)}" for r in old)
    return f"Added {len(urls)} link(s) to the Shared feed. Sync News Downloader to read them.{note}"


def main():
    os.environ["TZ"] = os.environ.get("PAPER_TZ", "UTC")
    time.tzset()
    chat_id = int(os.environ["PAPER_BOT_CHAT_ID"])
    write_feed()
    commands = [("list", "Show the Shared feed"), ("archive", "Archive links by number"), ("delete", "Delete links by number"),
                ("archived", "Show the archive"), ("now", "Rebuild the paper")]
    try:
        api("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])
    except OSError as e:
        print(f"setMyCommands failed: {e}", flush=True)
    offset = 0
    while True:
        try:
            updates = api("getUpdates", wait=60, offset=offset, timeout=50, allowed_updates=["message"])
        except (OSError, ValueError) as e:
            print(f"getUpdates failed: {e}", flush=True)
            time.sleep(15)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg or msg["chat"]["id"] != chat_id:
                continue
            try:
                reply = handle(msg)
            except Exception as e:
                reply = f"Error: {e}"
            print(reply, flush=True)
            try:
                api("sendMessage", chat_id=chat_id, text=reply)
            except OSError as e:
                print(f"sendMessage failed: {e}", flush=True)


if __name__ == "__main__":
    main()
