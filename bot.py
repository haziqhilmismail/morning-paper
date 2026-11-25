#!/usr/bin/env python3
"""Telegram bot: links sent from my own chat go into the next paper. /now rebuilds the paper.

Appends "YYYY-MM-DD<TAB>url" to data/shared.tsv; run.sh turns that file into queue.txt
and pinned.txt entries. The bot never writes queue.txt, because run.sh clears it after a build.
"""
import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE / "data" / "shared.tsv"
URL = re.compile(r"https?://[^\s<>\"]+")


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


def handle(msg):
    text = (msg.get("text") or "").strip()
    if text.split()[:1] == ["/now"]:
        subprocess.run(["systemctl", "--user", "start", "--no-block", "morning-paper.service"], check=True)
        return "Building the paper now. It is ready in about 10 minutes."
    urls = links(msg)
    if not urls:
        return "Send me an article link. /now rebuilds the paper at once."
    with SHARED.open("a") as f:
        f.writelines(f"{date.today().isoformat()}\t{u}\n" for u in urls)
    return f"Added {len(urls)} link(s) to the next paper."


def main():
    # shared.tsv dates must use the same zone as the cutoff in run.sh.
    os.environ["TZ"] = os.environ.get("PAPER_TZ", "UTC")
    time.tzset()
    chat_id = int(os.environ["PAPER_BOT_CHAT_ID"])
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
