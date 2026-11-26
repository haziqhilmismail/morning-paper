#!/usr/bin/env python3
"""Turn each EPUB in www/editions into web pages in www/read/<edition>/ for a phone browser.

The EPUB pages are XHTML, so the head, the navigation and the footer are inserted as text and
the files stay well-formed. Each run rebuilds www/read/ from www/editions, so a template change
reaches every edition and a removed edition loses its pages.
"""
import hashlib
import html
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EDITIONS, READ = ROOT / "www" / "editions", ROOT / "www" / "read"
# Cloudflare caches .js and .css for hours, so each change to reader/ gets a new ?v= in the page links.
VERSION = hashlib.sha1(b"".join(f.read_bytes() for f in sorted((ROOT / "reader").iterdir()))).hexdigest()[:8]
REPO = "https://github.com/haziqhilmismail/morning-paper"
HEAD = ('<head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>'
        '<meta name="color-scheme" content="light dark"/>'
        '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#fbf8f2"/>'
        '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#161513"/>'
        '<meta name="apple-mobile-web-app-capable" content="yes"/>'
        '<meta name="apple-mobile-web-app-title" content="Paper"/>'
        '<link rel="stylesheet" href="{up}reader.css?v={v}"/>'
        '<link rel="manifest" href="{up}manifest.json" crossorigin="use-credentials"/>'
        '<link rel="apple-touch-icon" href="{up}apple-touch-icon.png?v={v}"/>'
        '<script src="{up}install.js?v={v}" defer="defer"></script>'
        '<script src="{up}progress.js?v={v}" defer="defer"></script>')


def label(name: str) -> str:
    """morning-paper-2026-11-25-no7 -> Wed 25 Nov 2026 · No. 7"""
    day, no = name.removeprefix("morning-paper-").rsplit("-no", 1)
    return f"{date.fromisoformat(day):%a %-d %b %Y} · No. {no}"


def footer(edition: str, links: list[tuple[str, str]]) -> str:
    nav = "".join(f'<a href="{href}">{html.escape(text)}</a>' for href, text in links)
    return (f'<footer><p class="pager">{nav}</p><p class="colophon">Morning Paper · {html.escape(label(edition))}'
            f' · <a href="{REPO}">source code</a></p></footer>')


def page_links(name: str, articles: list[str]) -> list[tuple[str, str]]:
    if name == "frontpage.xhtml":
        return [("../", "All editions"), (articles[0], "First story →")] if articles else [("../", "All editions")]
    i = articles.index(name)
    prev = (articles[i - 1], "← Previous") if i else ("frontpage.xhtml", "← Front page")
    nxt = (articles[i + 1], "Next →") if i + 1 < len(articles) else ("../", "All editions")
    return [prev, ("frontpage.xhtml", "Front page"), nxt]


def unpack(epub: Path, out: Path) -> None:
    with zipfile.ZipFile(epub) as z:
        files = {i.filename.removeprefix("EPUB/"): i for i in z.infolist()
                 if i.filename.startswith("EPUB/") and not i.is_dir()}
        articles = sorted((n for n in files if re.fullmatch(r"art_\d+\.xhtml", n)), key=lambda n: int(n[4:-6]))
        for name, info in files.items():
            if not (name in articles or name == "frontpage.xhtml" or name.startswith(("images/", "fonts/", "style/"))):
                continue
            if ".." in Path(name).parts:
                raise ValueError(f"unsafe path in {epub.name}: {info.filename}")
            data = z.read(info)
            if name.endswith(".xhtml"):
                top = "" if name == "frontpage.xhtml" else (
                    '<nav><a href="frontpage.xhtml">← Front page</a><a href="../">All editions</a></nav>')
                body = '<body class="front">' if name == "frontpage.xhtml" else '<body class="article">'
                head = HEAD.format(up="../", v=VERSION)
                if name == "frontpage.xhtml":
                    head = head.replace('content="#161513"', 'content="#ffffff"').replace('content="#fbf8f2"', 'content="#ffffff"')
                text = data.decode().replace("<head>", head, 1)
                text = text.replace("<body>", body + top + "<main>", 1)
                text = text.replace("</body>", "</main>" + footer(out.name, page_links(name, articles)) + "</body>", 1)
                data = text.encode()
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(data)


def index(names: list[str], totals: dict[str, int]) -> str:
    items = "".join(
        f'<li data-edition="{n}" data-total="{totals[n]}"><a href="{n}/frontpage.xhtml"><img src="../editions/{n}.jpg" alt="" width="84" height="112"/>'
        f'<span>{"<small>Latest</small>" if i == 0 else ""}{html.escape(label(n))}</span></a></li>'
        for i, n in enumerate(names))
    empty = "" if names else "<p>No editions yet. The next run of run.sh makes one.</p>"
    return ('<!doctype html><html lang="en">' + HEAD.format(up="", v=VERSION) + '<meta charset="utf-8"/>'
            '<title>Morning Paper</title></head><body class="home"><main><h1>Morning Paper</h1>'
            f'<ul class="editions">{items}</ul>{empty}</main>'
            f'<footer><p class="colophon">Morning Paper · the 7 newest editions · <a href="{REPO}">source code</a>'
            '</p></footer></body></html>')


def main() -> None:
    names = sorted((p.stem for p in EDITIONS.glob("*.epub")), key=lambda n: int(n.rsplit("-no", 1)[1]), reverse=True)
    tmp = READ.with_name(".read")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(ROOT / "reader", tmp)
    for n in names:
        unpack(EDITIONS / f"{n}.epub", tmp / n)
    totals = {n: len(list((tmp / n).glob("art_*.xhtml"))) for n in names}
    (tmp / "index.html").write_text(index(names, totals), encoding="utf-8")
    shutil.rmtree(READ, ignore_errors=True)
    tmp.rename(READ)


if __name__ == "__main__":
    assert label("morning-paper-2026-11-25-no7") == "Wed 25 Nov 2026 · No. 7"
    assert page_links("art_0.xhtml", ["art_0.xhtml", "art_1.xhtml"])[0] == ("frontpage.xhtml", "← Front page")
    assert page_links("art_1.xhtml", ["art_0.xhtml", "art_1.xhtml"])[2] == ("../", "All editions")
    main()
