#!/usr/bin/env python3
"""Telegram bot: links sent from my own chat go into the Shared feed. /now rebuilds the paper.

Appends "YYYY-MM-DD<TAB>url<TAB>title" to data/shared.tsv and writes the newest links to
www/feeds/shared.xml. KOReader's News Downloader fetches each full article from that feed.
"""
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
FEED = HERE / "www" / "feeds" / "shared.xml"
URL = re.compile(r"https?://[^\s<>\"]+")
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
KEEP = 20


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


def title(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 morning-paper"})
        with urllib.request.urlopen(req, timeout=15) as r:
            m = TITLE.search(r.read(500_000).decode("utf-8", "replace"))
    except Exception:
        m = None
    return " ".join(html.unescape(m.group(1)).split()) if m else url


def write_feed():
    rows = [ln.split("\t") for ln in SHARED.read_text().splitlines() if ln.strip()] if SHARED.exists() else []
    items = "".join(
        f"<item><title>{html.escape(r[2] if len(r) > 2 else r[1])}</title><link>{html.escape(r[1])}</link>"
        f"<guid>{html.escape(r[1])}</guid>"
        f"<pubDate>{format_datetime(datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc))}</pubDate></item>"
        for r in reversed(rows[-KEEP:]))
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
    if text.split()[:1] == ["/now"]:
        subprocess.run(["systemctl", "--user", "start", "--no-block", "morning-paper.service"], check=True)
        return "Building the paper now. It is ready in about 10 minutes."
    urls = links(msg)
    if not urls:
        return "Send me an article link. /now rebuilds the paper at once."
    with SHARED.open("a") as f:
        f.writelines(f"{date.today().isoformat()}\t{u}\t{title(u).replace(chr(9), ' ')}\n" for u in urls)
    write_feed()
    return f"Added {len(urls)} link(s) to the Shared feed. Sync News Downloader to read them."


def main():
    os.environ["TZ"] = os.environ.get("PAPER_TZ", "UTC")
    time.tzset()
    chat_id = int(os.environ["PAPER_BOT_CHAT_ID"])
    write_feed()
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
