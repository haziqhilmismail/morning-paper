#!/usr/bin/env python3
"""Move stored articles under MIN_WORDS (paywall previews, stubs) from data/articles to
data/rejected, except links I pinned. Prints one line per pruned article, so run.sh knows to rebuild."""
import json
import re
import sys
from pathlib import Path

MIN_WORDS = 400
articles = Path(sys.argv[1])
rejected = articles.parent / "rejected"
rejected.mkdir(exist_ok=True)
pinned_file = articles.parent / "pinned.txt"
pinned = set(pinned_file.read_text().split()) if pinned_file.exists() else set()
for p in articles.glob("*.json"):
    a = json.loads(p.read_text())
    words = len(re.sub(r"<[^>]+>", " ", a.get("html", "")).split())
    if words < MIN_WORDS and a.get("url") not in pinned:
        p.replace(rejected / p.name)
        print(f"pruned ({words} words): {a.get('title', '')[:60]}")
