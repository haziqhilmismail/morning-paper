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
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse

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
    try:
        with urllib.request.urlopen(req, timeout=wait) as resp:
            return json.load(resp)["result"]
    except urllib.error.HTTPError as e:
        raise OSError(f"{method}: {json.load(e).get('description', e)}") from e


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


def lid(url):
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def view(archived=False):
    """The feed (or the archive), newest first, with a row of buttons for each link."""
    # Telegram allows 100 buttons in one message, so the archive view shows the 20 newest.
    rows = read(ARCHIVE if archived else SHARED)[::-1][:20]
    if not rows:
        return {"text": "The archive is empty." if archived else "The Shared feed is empty. Send me a link."}
    head = "Archive" if archived else f"Shared feed ({len(rows)} of {KEEP})"
    acts = [("♻️ Restore", "r")] if archived else [("🗄 Archive", "a"), ("🗑 Delete", "d")]
    items = "\n\n".join(
        f'{i}. <a href="{html.escape(r[1])}">{html.escape(name(r))}</a>\n'
        f"🌐 {html.escape(urlparse(r[1]).netloc.removeprefix('www.'))} · 📅 added {date.fromisoformat(r[0]):%a %-d %b %Y}"
        for i, r in enumerate(rows, 1))
    return {"text": f"<b>{head}</b>\n\n{items}", "parse_mode": "HTML", "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": [
                [{"text": f"{label} {i}", "callback_data": f"{c}:{lid(r[1])}"} for label, c in acts] for i, r in enumerate(rows, 1)]}}


def add(rows):
    """Add rows to the feed. Above KEEP links, the oldest go to the archive. Returns the moved rows."""
    rows = read(SHARED) + rows
    old = rows[:-KEEP]
    save(SHARED, rows[-KEEP:])
    with ARCHIVE.open("a") as f:
        f.writelines("\t".join(r) + "\n" for r in old)
    write_feed()
    return old


def press(data):
    """A button: a (archive), d (delete) or r (restore), then a link id. Returns a note and the view to show."""
    act, _, key = data.partition(":")
    if act not in ("a", "d", "r"):
        return "Unknown button.", view()
    src = ARCHIVE if act == "r" else SHARED
    rows = read(src)
    hit = [r for r in rows if lid(r[1]) == key]
    if not hit:
        return "That link is gone already.", view(act == "r")
    save(src, [r for r in rows if lid(r[1]) != key])
    if act == "a":
        with ARCHIVE.open("a") as f:
            f.write("\t".join(hit[0]) + "\n")
    if act == "r":
        fetch(hit[0][1])
        add(hit)
    else:
        write_feed()
    return {"a": "Archived", "d": "Deleted", "r": "Restored"}[act] + f": {name(hit[0])}", view(act == "r")


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


KEYBOARD = {"keyboard": [[{"text": "📋 Feed"}, {"text": "🗄 Archive"}], [{"text": "🗞 Rebuild paper"}]],
            "resize_keyboard": True, "is_persistent": True}
HELP = ("Send me an article link. I add it to the Shared feed, and News Downloader gets it at the next sync.\n"
        f"The feed keeps the {KEEP} newest links. Older links move to the archive. Links already on the e-reader stay there.")


def handle(msg):
    text = (msg.get("text") or "").strip()
    cmd = (text.split() or [""])[0].split("@")[0]
    if cmd in ("/now", "🗞"):
        subprocess.run(["systemctl", "--user", "start", "--no-block", "morning-paper.service"], check=True)
        return {"text": "Building the paper now. It is ready in about 10 minutes."}
    if cmd == "/synckey":
        key = os.environ.get("READER_SYNC_KEY", "")
        if not key:
            return {"text": "No sync key is set. Put READER_SYNC_KEY in .env on the server."}
        return {"text": f"Sync key for the Morning Paper reader (keep it private):\n\n{key}\n\n"
                        "In the reader, tap \"Turn on sync\" at the bottom of the editions list and paste it. "
                        f"In a browser, you can also open this link once:\n{os.environ.get('PAPER_URL', '')}/read/#sync={key}",
                "link_preview_options": {"is_disabled": True}}
    if cmd in ("/list", "📋"):
        return view()
    if cmd in ("/archived", "🗄"):
        return view(archived=True)
    urls = links(msg)
    if not urls:
        return {"text": HELP, "reply_markup": KEYBOARD}
    new = [[date.today().isoformat(), u, fetch(u).replace("\t", " ")] for u in urls]
    old = add(new)
    note = "".join(f"\nMoved the oldest link to the archive: {name(r)}" for r in old)
    reply = view()
    reply["text"] = html.escape("Added: " + ", ".join(name(r) for r in new) + note) + "\n\n" + reply["text"]
    return reply


def main():
    os.environ["TZ"] = os.environ.get("PAPER_TZ", "UTC")
    time.tzset()
    chat_id = int(os.environ["PAPER_BOT_CHAT_ID"])
    write_feed()
    commands = [("list", "Show the Shared feed"), ("archived", "Show the archive"), ("now", "Rebuild the paper"),
                ("synckey", "Get the reader sync key")]
    try:
        api("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])
    except OSError as e:
        print(f"setMyCommands failed: {e}", flush=True)
    offset = 0
    while True:
        try:
            updates = api("getUpdates", wait=60, offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
        except (OSError, ValueError) as e:
            print(f"getUpdates failed: {e}", flush=True)
            time.sleep(15)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    if cq["from"]["id"] != chat_id or cq.get("message", {}).get("chat", {}).get("id") != chat_id:
                        continue
                    note, reply = press(cq.get("data", ""))
                    api("answerCallbackQuery", callback_query_id=cq["id"], text=note)
                    try:
                        api("editMessageText", chat_id=chat_id, message_id=cq["message"]["message_id"],
                            **{"reply_markup": {"inline_keyboard": []}, **reply})
                    except OSError as e:
                        # A second tap on a link that is gone leaves the list as it is.
                        if "message is not modified" not in str(e):
                            raise
                    continue
                msg = upd.get("message")
                if not msg or msg["chat"]["id"] != chat_id:
                    continue
                reply = handle(msg)
            except Exception as e:
                reply = {"text": f"Error: {e}"}
            print(reply["text"].splitlines()[0], flush=True)
            try:
                api("sendMessage", chat_id=chat_id, **reply)
            except OSError as e:
                print(f"sendMessage failed: {e}", flush=True)

if __name__ == "__main__":
    main()
