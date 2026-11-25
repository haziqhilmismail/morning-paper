#!/usr/bin/env python3
"""Turn each EPUB in www/editions into web pages in www/read/<edition>/ for a phone browser.

The EPUB pages are XHTML, so the head and the navigation are inserted as text and the files
stay well-formed. www/read/ mirrors www/editions: a removed edition loses its pages too.
"""
import html
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EDITIONS, READ = ROOT / "www" / "editions", ROOT / "www" / "read"
HEAD = ('<head><meta name="viewport" content="width=device-width, initial-scale=1"/>'
        '<link rel="stylesheet" href="../reader.css"/>'
        '<link rel="manifest" href="../manifest.json" crossorigin="use-credentials"/>'
        '<link rel="apple-touch-icon" href="../icon-192.png"/>')
NAV = '<nav><a href="frontpage.xhtml">Front page</a><a href="../">All editions</a></nav>'


def unpack(epub: Path, out: Path) -> None:
    tmp = out.with_name("." + out.name)
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(epub) as z:
        for info in z.infolist():
            name = info.filename.removeprefix("EPUB/")
            if info.is_dir() or name == info.filename or not (name.endswith(".xhtml") or name.startswith("images/")):
                continue
            if ".." in Path(name).parts:
                raise ValueError(f"unsafe path in {epub.name}: {info.filename}")
            data = z.read(info)
            if name.endswith(".xhtml"):
                body = '<body class="front">' if name == "frontpage.xhtml" else "<body>" + NAV
                data = data.decode().replace("<head>", HEAD, 1).replace("<body>", body, 1).encode()
            (tmp / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp / name).write_bytes(data)
    tmp.rename(out)


def index(names: list[str]) -> str:
    items = "".join(
        f'<li><a href="{n}/frontpage.xhtml"><img src="../editions/{n}.jpg" alt=""/>'
        f'{html.escape(n.removeprefix("morning-paper-").replace("-no", " · No. "))}</a></li>' for n in names)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
            + HEAD.removeprefix("<head>") + '<title>Morning Paper</title></head>'
            '<body><h1>Morning Paper</h1><ul class="editions">' + items + "</ul></body></html>")


def main() -> None:
    READ.mkdir(exist_ok=True)
    for f in (ROOT / "reader").iterdir():
        shutil.copyfile(f, READ / f.name)
    names = sorted((p.stem for p in EDITIONS.glob("*.epub")), key=lambda n: int(n.rsplit("-no", 1)[1]), reverse=True)
    for n in names:
        if not (READ / n).is_dir():
            unpack(EDITIONS / f"{n}.epub", READ / n)
    for d in READ.iterdir():
        if d.is_dir() and d.name not in names:
            shutil.rmtree(d)
    (READ / "index.html").write_text(index(names), encoding="utf-8")


if __name__ == "__main__":
    main()
