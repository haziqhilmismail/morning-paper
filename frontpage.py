#!/usr/bin/env python3
"""Replace the image front page of DATA/read-later.epub with a text front page.

Upstream draws its front page as JPEG blocks with gray text, which is hard to read on e-ink and
which KOReader cannot restyle. This page is XHTML with all text black, the edition's own fonts
and grayscale photos at their own aspect ratio. Sections come from DATA/topics.tsv (curate.sh).
Usage: frontpage.py DATA (run.sh runs it in the morning-paper image, after the last build).
"""
import hashlib
import html
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

MAX_ITEMS = 6  # stories under the lead; the rest stay in the contents
FALLBACK_TOPIC = "More reads"
FONTS = ("UnifrakturMaguntia-Book.ttf", "PT_Serif-Web-Regular.ttf", "PT_Serif-Web-Bold.ttf")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

CSS = """
@font-face { font-family: "Masthead"; src: url(fonts/UnifrakturMaguntia-Book.ttf); }
@font-face { font-family: "PT Serif"; src: url(fonts/PT_Serif-Web-Regular.ttf); }
@font-face { font-family: "PT Serif"; font-weight: bold; src: url(fonts/PT_Serif-Web-Bold.ttf); }
body { margin: 0; color: #000; }
.paper { font-family: "PT Serif", serif; color: #000; padding: 0 0.6em; }
.paper a { color: #000; text-decoration: none; }
h1, h2, h3, p { margin: 0; color: #000; }
.mast { font-family: "Masthead", serif; font-weight: normal; font-size: 2.9em; line-height: 1.1;
  text-align: center; border-bottom: 3px double #000; }
.tag { text-align: center; font-style: italic; font-size: 0.9em; padding: 0.2em 0; border-bottom: 1px solid #000; }
.dateline { width: 100%; border-collapse: collapse; border-bottom: 2px solid #000; font-size: 0.72em;
  font-weight: bold; text-transform: uppercase; letter-spacing: 0.05em; }
.dateline td { padding: 0.3em 0; }
.kicker { font-size: 0.68em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.14em; }
.lead { padding: 0.5em 0; border-bottom: 2px solid #000; }
.lead h2 { font-size: 1.75em; line-height: 1.1; margin: 0.15em 0 0.3em; }
.lead p.dek { font-size: 0.95em; line-height: 1.35; margin: 0.35em 0 0.25em; }
.photo { text-align: center; margin: 0; }
.photo img { border: 1px solid #000; }
.meta { width: 100%; border-collapse: collapse; font-size: 0.75em; }
.meta td { padding: 0; font-style: italic; }
.meta td.r { text-align: right; font-style: normal; font-weight: bold; white-space: nowrap; }
.cols { width: 100%; border-collapse: collapse; margin-top: 0.4em; }
.cols td.col { width: 50%; vertical-align: top; padding: 0; }
.cols td.left { padding-right: 0.6em; border-right: 1px solid #000; }
.cols td.right { padding-left: 0.6em; }
.sec { margin-bottom: 0.5em; }
.sec .kicker { border-bottom: 1px solid #000; padding-bottom: 0.2em; }
.count { float: right; }
.item { padding: 0.35em 0; border-bottom: 1px dotted #000; }
.item.last { border-bottom: 0; }
.item .photo { margin-bottom: 0.3em; }
.item h3 { font-size: 0.95em; line-height: 1.2; margin-bottom: 0.1em; }
.foot { border-top: 1px solid #000; padding-top: 0.25em; margin-top: 0.3em; font-size: 0.72em;
  text-align: center; font-style: italic; }
"""


def words(html_text: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", html_text or "").split())


def dek(html_text: str, max_chars: int = 220) -> str:
    """The first two sentences of the first real paragraph (skips bylines and captions)."""
    paras = [html.unescape(re.sub(r"<[^>]+>", " ", p)) for p in re.findall(r"<p[^>]*>(.*?)</p>", html_text or "", re.S)]
    text = next((" ".join(p.split()) for p in paras if len(p.split()) >= 20), "")
    out = ""
    for s in re.split(r"(?<=[.!?”])\s+", text)[:2]:
        if out and len(out) + len(s) > max_chars:
            break
        out = f"{out} {s}".strip()
    return out if len(out) <= max_chars else out[:max_chars].rsplit(" ", 1)[0] + " …"


def total_time(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def photo(url: str | None, box: tuple[int, int]) -> "Image.Image | None":
    """Grayscale, scaled to fit inside box with its own aspect ratio: no crop."""
    if not url:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            im = Image.open(io.BytesIO(r.read(10_000_000)))
            im.load()
    except Exception as e:  # a missing photo only drops the photo
        print(f"front page: no photo ({type(e).__name__}): {url[:80]}")
        return None
    return ImageOps.contain(ImageOps.grayscale(im), box, Image.LANCZOS)


def load_stories(z: zipfile.ZipFile, data: Path) -> list[dict]:
    """One story per art_N.xhtml, in spine order; the source link finds its stored JSON."""
    topics = {}
    if (data / "topics.tsv").exists():
        for line in (data / "topics.tsv").read_text().splitlines():
            url, _, topic = line.partition("\t")
            topic = " ".join(re.sub(r"[^\w &'/-]", " ", topic).split())[:30]
            if topic:
                topics[url] = topic
    names = sorted((n for n in z.namelist() if re.fullmatch(r"EPUB/art_\d+\.xhtml", n)), key=lambda n: int(n[9:-6]))
    stories, page = [], 2
    for n in names:
        x = z.read(n).decode()
        url = html.unescape(re.search(r"<a href=['\"]([^'\"]+)['\"]>source</a>", x).group(1))
        a = json.loads((data / "articles" / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.json").read_text())
        stories.append({"href": n.removeprefix("EPUB/"), "title": a["title"], "domain": a["domain"],
                        "minutes": int(re.search(r"\((\d+) min\)</title>", x).group(1)), "page": page,
                        "dek": dek(a["html"]), "image": a.get("image"), "topic": topics.get(url, FALLBACK_TOPIC)})
        page += words(a["html"]) // 300  # upstream's page estimate: 300 words a page
    return stories


def pick(stories: list[dict]) -> tuple[list[dict], list[dict]]:
    """Round-robin over the topics, so each topic gets a place before one topic gets a second."""
    by_topic: dict[str, list[dict]] = {}
    for s in stories:
        by_topic.setdefault(s["topic"], []).append(s)
    picked = []
    while len(picked) < min(MAX_ITEMS, len(stories)):
        for group in by_topic.values():
            if group and len(picked) < MAX_ITEMS:
                picked.append(group.pop(0))
    sections = {}
    for s in picked:
        sections.setdefault(s["topic"], []).append(s)
    cols: list[list[str]] = [[], []]
    weight = [0, 0]
    for topic in sorted(sections, key=lambda t: -len(sections[t])):
        i = weight.index(min(weight))
        cols[i].append(topic)
        weight[i] += len(sections[topic]) + 1
    return picked, [[(t, sections[t]) for t in c] for c in cols]


def build(data: Path) -> None:
    epub = data / "read-later.epub"
    with zipfile.ZipFile(epub) as z:
        stories = load_stories(z, data)
        entries = [(i, z.read(i)) for i in z.infolist()
                   if not re.fullmatch(r"EPUB/images/fp_\d+\.jpg|EPUB/frontpage\.xhtml", i.filename)]
    if not stories:
        return
    edition = (data / "edition.txt").read_text().strip()
    count = {}
    for s in stories:
        count[s["topic"]] = count.get(s["topic"], 0) + 1

    images: dict[str, bytes] = {}

    def img(s: dict, box: tuple[int, int]) -> str:
        im = photo(s["image"], box)
        if not im:
            return ""
        name = f"images/front_{len(images)}.jpg"
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        images[name] = buf.getvalue()
        return (f'<p class="photo"><a href="{s["href"]}"><img src="{name}" alt=""'
                f' style="width:{im.width / box[0] * 100:.0f}%"/></a></p>')

    e = html.escape
    lead, lead_img = stories[0], ""
    for s in stories:  # newest story with a photo that downloads
        if s["image"] and (lead_img := img(s, (1000, 560))):
            lead = s
            break
    picked, cols = pick([s for s in stories if s is not lead])

    def item(s: dict, with_photo: bool, last: bool) -> str:
        return (f'<div class="item{" last" if last else ""}">{img(s, (500, 340)) if with_photo else ""}'
                f'<h3><a href="{s["href"]}">{e(s["title"])}</a></h3><table class="meta"><tr>'
                f'<td>{e(s["domain"])}</td><td class="r">{s["minutes"]} min</td></tr></table></div>')

    def column(sections: list) -> str:
        return "".join(
            f'<div class="sec"><p class="kicker"><span class="count">{count[t]} read{"s" * (count[t] > 1)}</span>{e(t)}</p>'
            + "".join(item(s, i == 0, i == len(items) - 1) for i, s in enumerate(items)) + "</div>"
            for t, items in sections)

    now = datetime.now()
    more = len(stories) - 1 - len(picked)
    page = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
<head>
<title>The Morning Paper</title>
<style>{CSS}</style>
</head>
<body>
<div class="paper">
<h1 class="mast">The Morning Paper</h1>
<p class="tag">All the Reads Worth Your Time</p>
<table class="dateline"><tr><td>Vol. I · No. {e(edition)}</td>
<td style="text-align:center">{now:%A %-d %B %Y}</td>
<td style="text-align:right">{len(stories)} reads · {total_time(sum(s["minutes"] for s in stories))}</td></tr></table>
<div class="lead">
<p class="kicker">{e(lead["topic"])}</p>
<h2><a href="{lead["href"]}">{e(lead["title"])}</a></h2>
{lead_img}
<p class="dek">{e(lead["dek"])}</p>
<table class="meta"><tr><td>{e(lead["domain"])}</td><td class="r">{lead["minutes"]} min · p. {lead["page"]}</td></tr></table>
</div>
<table class="cols"><tr><td class="col left">{column(cols[0])}</td><td class="col right">{column(cols[1])}</td></tr></table>
<p class="foot">Tap a headline to open it{f" · {more} more read{'s' * (more > 1)} in the contents" if more > 0 else ""}</p>
</div>
</body>
</html>
"""
    fonts = {f: (data / "fonts" / f).read_bytes() for f in FONTS if (data / "fonts" / f).exists()}
    manifest = "".join(f'<item href="{n}" id="front_{i}" media-type="image/jpeg"/>' for i, n in enumerate(images))
    manifest += "".join(f'<item href="fonts/{f}" id="font_{i}" media-type="font/ttf"/>' for i, f in enumerate(fonts))
    tmp = epub.with_name(".read-later.epub")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for info, body in entries:  # mimetype stays first and stored, as upstream wrote it
            if info.filename == "EPUB/content.opf":
                opf = re.sub(r'\s*<item href="images/fp_\d+\.jpg"[^>]*/>', "", body.decode())
                body = opf.replace("</manifest>", manifest + "</manifest>", 1).encode()
            out.writestr(info, body)
        out.writestr("EPUB/frontpage.xhtml", page)
        for name, body in images.items():
            out.writestr(f"EPUB/{name}", body)
        for f, body in fonts.items():
            out.writestr(f"EPUB/fonts/{f}", body)
    tmp.replace(epub)
    print(f"front page: {len(picked) + 1} of {len(stories)} stories, {len(images)} photos, {len(fonts)} fonts")


if __name__ == "__main__":
    assert total_time(104) == "1 h 44 min" and total_time(9) == "9 min"
    assert dek("<p>By X</p><p>" + "One two three four five six seven eight nine ten. " * 3 + "</p>").count(".") == 2
    by = [{"topic": t} for t in ["A", "A", "A", "B", "C"]]
    assert [s["topic"] for s in pick(by)[0]] == ["A", "B", "C", "A", "A"]
    build(Path(sys.argv[1]))
