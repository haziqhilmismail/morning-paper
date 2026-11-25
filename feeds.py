#!/usr/bin/env python3
"""Copy feed N in feeds.txt to www/feeds/N.xml (slots 1-6) without Substack paid-only previews.

KOReader's feed_config.lua lists the fixed slot URLs, so feeds.txt can change without a new
file on the reader. News Downloader names each folder from the feed's own title, not the URL.

A paid preview's content:encoded ends with a "Read more" link to the post. The feed is
edited as text, not re-serialized, so KOReader still finds its literal content:encoded tag.
"""
import re
import sys
import urllib.request
from pathlib import Path

ITEM = re.compile(r"<item>.*?</item>", re.S)
PAID = re.compile(r"Read more\s*</a>\s*</p>\s*\]\]></content:encoded>")
SLOTS = 6
# News Downloader rejects a feed with no items, so empty slots share one fixed placeholder
# item; it saves one file, once, in an "Empty feed slots" folder.
EMPTY = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
         '<title>Empty feed slots</title><link>https://github.com/haziqhilmismail/morning-paper</link>'
         '<description>No feed in this slot</description><item><title>No feed in this slot</title>'
         '<link>https://github.com/haziqhilmismail/morning-paper</link><pubDate>Sat, 01 Jan 2000 00:00:00 GMT</pubDate>'
         '<description>Add a feed to feeds.txt on the server.</description></item></channel></rss>')


def strip_paid(feed: str) -> tuple[str, int]:
    return ITEM.subn(lambda m: "" if PAID.search(m.group(0)) else m.group(0), feed)[0], \
        sum(1 for m in ITEM.finditer(feed) if PAID.search(m.group(0)))


def main(root: Path) -> int:
    out = root / "www" / "feeds"
    out.mkdir(exist_ok=True)
    failed = 0
    feeds = [ln.split() for ln in (root / "feeds.txt").read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    for name, _ in feeds[SLOTS:]:
        print(f"feed {name}: skipped, only {SLOTS} slots (add one to koreader/feed_config.lua)")
    for slot in range(1, SLOTS + 1):
        if slot > len(feeds):
            (out / f"{slot}.xml").write_text(EMPTY, encoding="utf-8")
            continue
        name, url = feeds[slot - 1]
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "morning-paper"})
            with urllib.request.urlopen(req, timeout=30) as r:
                feed = r.read().decode("utf-8")
        except Exception as e:
            print(f"feed {name}: {e}")
            failed += 1
            continue
        kept, dropped = strip_paid(feed)
        tmp = out / f".{slot}.xml"
        tmp.write_text(kept, encoding="utf-8")
        tmp.replace(out / f"{slot}.xml")
        print(f"feed {name} (slot {slot}): dropped {dropped} paid preview(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(__file__).resolve().parent))
