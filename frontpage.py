#!/usr/bin/env python3
"""Run the upstream build with a text front page in place of its image front page.

Upstream draws its front page as JPEG blocks with gray text, which is hard to read on e-ink and
which KOReader cannot restyle. This page is XHTML with all text black, the edition's own fonts
and grayscale photos at their own aspect ratio. The lead is the story Claude ranked first in the
newest curation, and the sections are its topics (curate.sh writes both to DATA/topics.tsv).
If this page fails, upstream's own front page goes in the EPUB.
Usage: frontpage.py [upstream build arguments]. run.sh runs it in the morning-paper image,
where upstream is at /app.
"""
import html
import importlib.util
import io
import re
import sys
import textwrap
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

MAX_ITEMS = 6  # stories under the lead; the rest stay in the contents
MIN_PHOTO_WIDTH = 300  # smaller images are icons and logos
LEAD_BOX, ITEM_BOX = (1000, 560), (500, 180)
# Screen 1 at the Kindle's KOReader settings (1072 x 1448, 300 dpi, font size 20, margins 30/15/15,
# status bar on), measured in the KOReader emulator. The lead photo gets the height that is left,
# so screen 1 is full. A table row never splits, so if screen 1 overflows, both stories move to screen 2.
SCREEN_1_END = 1375  # text area bottom (about 1398) less a safety band for a wrong line estimate
FIXED_PX = 485  # masthead, dateline, kicker, meta lines and rules
LEAD_LINE_PX, DEK_LINE_PX, ITEM_LINE_PX = 58, 40, 28
LEAD_CHARS, DEK_CHARS, ITEM_CHARS = 36, 66, 42  # characters on one line
LEAD_SCALE, ITEM_SCALE = 0.962, 0.93  # rendered width / photo box width
FALLBACK_TOPIC = "More reads"

CSS = """
body { margin: 0; color: #000; }
.paper { font-family: "PT Serif", serif; color: #000; text-align: left; }
.paper a { color: #000; text-decoration: none; }
.paper table { display: table; }
.paper td { border-bottom: 0; }
.paper h1, .paper h2, .paper h3, .paper p { margin: 0; color: #000; text-indent: 0; text-align: left; }
.paper .mast { font-family: "Masthead", serif; font-weight: normal; font-size: 2.6em; line-height: 1.1;
  text-align: center; border-bottom: 3px double #000; }
.paper .tag { text-align: center; font-style: italic; font-size: 0.85em; padding: 0.15em 0; border-bottom: 1px solid #000; }
.dateline { width: 100%; border-collapse: collapse; border-bottom: 2px solid #000; font-size: 0.66em;
  font-weight: bold; text-transform: uppercase; letter-spacing: 0.04em; }
.dateline td { width: 28%; padding: 0.3em 0; }
.dateline td.mid { width: 44%; }
.paper .kicker { font-size: 0.62em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.14em; }
.lead { padding: 0.4em 0; border-bottom: 2px solid #000; }
.paper .lead h2 { font-size: 1.45em; line-height: 1.1; margin: 0.1em 0 0.25em; }
.paper .lead.text h2 { font-size: 1.9em; }
.paper .lead p.dek { font-size: 0.85em; line-height: 1.3; margin: 0.3em 0 0.2em; }
.paper .lead.text p.dek { font-size: 0.95em; }
.paper .photo { text-align: center; margin: 0; }
.meta { width: 100%; border-collapse: collapse; font-size: 0.68em; }
.meta td { padding: 0; font-style: italic; }
.meta td.r { text-align: right; font-style: normal; font-weight: bold; white-space: nowrap; }
.cols { width: 100%; border-collapse: collapse; margin-top: 0.3em; }
.cols td.col { width: 50%; vertical-align: top; padding: 0; }
.cols td.left { padding-right: 0.5em; }
.cols td.right { padding-left: 0.5em; border-left: 1px solid #000; }
.cols.next { page-break-before: always; margin-top: 0; }
.sec { margin-bottom: 0.4em; }
.sec .kicker { border-bottom: 1px solid #000; padding-bottom: 0.15em; }
.count { float: right; }
.item { padding: 0.3em 0; border-bottom: 1px dotted #000; }
.item.last { border-bottom: 0; }
.paper .item .photo { margin: 0.2em 0; }
.paper .item h3 { font-size: 0.85em; line-height: 1.2; margin-bottom: 0.1em; }
.paper .foot { border-top: 1px solid #000; padding-top: 0.25em; margin-top: 0.3em; font-size: 0.66em;
  text-align: center; font-style: italic; }
"""


def dek(html_text: str, sentences: int, max_chars: int) -> str:
    """Opening sentences of the first real paragraph. Upstream's _fp_summary starts at the byline."""
    paras = [html.unescape(re.sub(r"<[^>]+>", " ", p)) for p in re.findall(r"<p[^>]*>(.*?)</p>", html_text or "", re.S)]
    text = next((" ".join(p.split()) for p in paras if len(p.split()) >= 20), "")
    out = ""
    for s in re.split(r"(?<=[.!?”])\s+", text)[:sentences]:
        if out and len(out) + len(s) > max_chars:
            break
        out = f"{out} {s}".strip()
    return out if len(out) <= max_chars else out[:max_chars].rsplit(" ", 1)[0] + " …"


def total_time(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def load_topics(path: Path) -> dict[str, tuple[str, int, int]]:
    """url -> (topic, curation run, rank in that run). A URL picked again keeps its newest line."""
    topics = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                url, topic, run, rank = line.split("\t")
                topics[url] = (" ".join(re.sub(r"[^\w &'/-]", " ", topic).split())[:30], int(run), int(rank))
            except ValueError:
                continue
    return topics


def by_importance(stories: list[dict]) -> list[dict]:
    """The newest curation first, in Claude's rank order. Stories with no rank keep their order after."""
    return sorted(stories, key=lambda s: (0, -s["run"], s["rank"]) if s["run"] else (1, 0, 0))


def pick(stories: list[dict]) -> list[dict]:
    """Each topic's first story, then each topic's second, and so on, in importance order."""
    seen = Counter()
    ranked = []
    for s in stories:
        seen[s["topic"]] += 1
        ranked.append((seen[s["topic"]], s))
    return [s for _, s in sorted(ranked, key=lambda p: p[0])][:MAX_ITEMS]


def columns(picked: list[dict]) -> list[list[tuple[str, list[dict]]]]:
    """Sections in importance order, each to the column with fewer lines so far."""
    sections: dict[str, list[dict]] = {}
    for s in picked:
        sections.setdefault(s["topic"], []).append(s)
    cols: list[list] = [[], []]
    weight = [0, 0]
    for topic, items in sections.items():
        i = weight.index(min(weight))
        cols[i].append((topic, items))
        weight[i] += len(items) + 1
    return cols


def lead_photo_height(lead: dict, first: list[dict]) -> int:
    """Photo box height for the lead, in image px, that fills screen 1 under these headlines."""
    def lines(text: str, width: int) -> int:
        return len(textwrap.wrap(text, width))

    column = max((ITEM_LINE_PX * lines(s["title"], ITEM_CHARS) + ITEM_SCALE * (s["photo"][2] if s.get("photo") else 0)
                  for s in first), default=0)
    left = (SCREEN_1_END - FIXED_PX - LEAD_LINE_PX * lines(lead["title"], LEAD_CHARS)
            - DEK_LINE_PX * lines(lead["dek"], DEK_CHARS) - column)
    return max(200, min(LEAD_BOX[1], int(left / LEAD_SCALE)))


def photo(url: str | None, box: tuple[int, int], user_agent: str) -> "Image.Image | None":
    """Grayscale on white, scaled down to fit inside box with its own aspect ratio: no crop, no upscale."""
    if not url:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": user_agent}), timeout=20) as r:
            im = Image.open(io.BytesIO(r.read(10_000_000)))
            im.draft("RGB", box)  # a JPEG decodes at a smaller size: a big photo stays far below the 1 GB limit
            im.load()
    except Exception as e:  # a missing photo only drops the photo
        print(f"front page: no photo ({type(e).__name__}): {url[:80]}")
        return None
    if im.width < MIN_PHOTO_WIDTH:
        return None
    if im.mode not in ("RGB", "RGBA", "L", "LA"):
        im = im.convert("RGBA")
    im.thumbnail(box, Image.LANCZOS)
    rgba = im.convert("RGBA")
    flat = Image.new("RGB", im.size, "white")
    flat.paste(rgba, mask=rgba)
    return ImageOps.grayscale(flat)


def render(stories: list[dict], lead: dict, screens: list[list], more: int, paper: tuple[str, str, str], today: datetime) -> str:
    title, tagline, edition = paper
    e = html.escape
    count = Counter(s["topic"] for s in stories)

    def img(s: dict) -> str:
        return (f'<p class="photo"><a href="{s["href"]}"><img src="{s["photo"][0]}" alt=""'
                f' style="width:{s["photo"][1]}%"/></a></p>') if s.get("photo") else ""

    def item(s: dict, last: bool) -> str:
        return (f'<div class="item{" last" if last else ""}"><h3><a href="{s["href"]}">{e(s["title"])}</a></h3>'
                f'{img(s)}<table class="meta"><tr>'
                f'<td>{e(s["domain"])}</td><td class="r">{s["minutes"]} min</td></tr></table></div>')

    def column(sections: list) -> str:
        return "".join(
            f'<div class="sec"><p class="kicker"><span class="count">{count[t]} read{"s" * (count[t] > 1)}</span>{e(t)}</p>'
            + "".join(item(s, i == len(items) - 1) for i, s in enumerate(items)) + "</div>"
            for t, items in sections)

    more_text = f" · {more} more read{'s' * (more > 1)} in the contents" if more > 0 else ""
    return f"""<html><head></head><body><div class="paper">
<h1 class="mast">{e(title)}</h1>
<p class="tag">{e(tagline)}</p>
<table class="dateline"><tr><td>Vol. I · No. {e(edition)}</td>
<td class="mid" style="text-align:center">{today:%A %-d %B %Y}</td>
<td style="text-align:right">{len(stories)} reads · {total_time(sum(s["minutes"] for s in stories))}</td></tr></table>
<div class="lead{"" if lead.get("photo") else " text"}">
{f'<p class="kicker">{e(lead["topic"])}</p>' if lead["run"] else ""}
<h2><a href="{lead["href"]}">{e(lead["title"])}</a></h2>
{img(lead)}
<p class="dek">{e(lead["dek"])}</p>
<table class="meta"><tr><td>{e(lead["domain"])}</td><td class="r">{lead["minutes"]} min · p. {lead["page"]}</td></tr></table>
</div>
{"".join(f'<table class="cols{" next" * (i > 0)}"><tr><td class="col left">{column(c[0])}</td>'
         f'<td class="col right">{column(c[1])}</td></tr></table>' for i, c in enumerate(screens) if c[0] or c[1])}
<p class="foot">Tap a headline to open it{more_text}</p>
</div></body></html>"""


def text_front_page(kdb, book, articles: list[dict]):
    """A drop-in for upstream's build_front_page(book, articles): articles[i] is art_i.xhtml."""
    epub = kdb.epub
    topics = load_topics(kdb.BASE / "topics.tsv")
    stories, running = [], 0
    for i, a in enumerate(articles):
        words = kdb._text_words(a["html"])
        topic, run, rank = topics.get(a["url"], ("", 0, 0))
        stories.append({**a, "href": f"art_{i}.xhtml", "minutes": kdb.reading_minutes(words),
                        "page": 2 + running // 300,  # upstream's page estimate
                        "topic": topic or FALLBACK_TOPIC, "run": run, "rank": rank})
        running += words
    ranked = by_importance(stories)
    lead = ranked[0]
    picked = pick(ranked[1:])
    # The first screen has the lead and one story in each column; the others start on the next screen.
    first = [[(s["topic"], [s])] for s in picked[:2]]
    screens = [first + [[]] * (2 - len(first)), columns(picked[2:])]

    images = {}

    def add_photo(s: dict, box: tuple[int, int]) -> bool:
        im = photo(s.get("image"), box, kdb.ARTICLE_USER_AGENT)
        if im:
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
            s["photo"] = (f"images/front_{len(images)}.jpg", round(im.width / box[0] * 100), im.height)
            images[s["photo"][0]] = buf.getvalue()
        return bool(im)

    for col in screens[0] + screens[1]:  # one photo per column on each screen
        next((s for _, items in col for s in items if add_photo(s, ITEM_BOX)), None)
    lead["dek"] = dek(lead["html"], 2, 220)
    if not add_photo(lead, (LEAD_BOX[0], lead_photo_height(lead, picked[:2]))):
        lead["dek"] = dek(lead["html"], 4, 420)
    paper = (kdb.PAPER_TITLE, kdb.PAPER_TAGLINE, kdb.EDITION_FILE.read_text().strip())
    page_html = render(stories, lead, screens, len(stories) - 1 - len(picked), paper, datetime.now())

    faces = [("Masthead", "normal", kdb.MAST_FONT), ("PT Serif", "normal", kdb.SERIF_R), ("PT Serif", "bold", kdb.SERIF_B)]
    fonts = [(family, weight, Path(p)) for family, weight, p in faces if Path(p).exists()]
    css = "".join(f'@font-face {{ font-family: "{f}"; font-weight: {w}; src: url(../fonts/{p.name}); }}\n'
                  for f, w, p in fonts) + CSS
    for name, body in images.items():
        book.add_item(epub.EpubItem(uid=Path(name).stem, file_name=name, media_type="image/jpeg", content=body))
    for i, (_, _, p) in enumerate(fonts):
        book.add_item(epub.EpubItem(uid=f"font_{i}", file_name=f"fonts/{p.name}", media_type="font/ttf",
                                    content=p.read_bytes()))
    book.add_item(epub.EpubItem(uid="front_css", file_name="style/front.css", media_type="text/css", content=css))
    fp = epub.EpubHtml(title=kdb.PAPER_TITLE, file_name="frontpage.xhtml", lang="en")
    fp.content = page_html
    fp.add_link(href="style/front.css", rel="stylesheet", type="text/css")
    book.add_item(fp)
    kdb.log(f"text front page: lead {lead['title'][:50]}, {len(picked)} more stories, {len(images)} photos")
    return fp


def main() -> int:
    sys.path.insert(0, "/app/scripts")  # upstream imports kobo_config from its own folder
    spec = importlib.util.spec_from_file_location("kobo_digest_build", "/app/scripts/kobo-digest-build.py")
    kdb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kdb)
    image_front_page = kdb.build_front_page

    def build_front_page(book, articles):
        try:
            return text_front_page(kdb, book, articles)
        except Exception as e:
            kdb.log(f"text front page failed ({type(e).__name__}: {e}); using the image front page")
            return image_front_page(book, articles)

    kdb.build_front_page = build_front_page
    return kdb.main(sys.argv[1:])


if __name__ == "__main__":
    assert total_time(104) == "1 h 44 min" and total_time(9) == "9 min"
    assert dek("<p>By X</p><p>" + "One two three four five six seven eight nine ten. " * 3 + "</p>", 2, 220).count(".") == 2
    s = [{"topic": t, "run": r, "rank": k} for t, r, k in [("A", 1, 1), ("A", 2, 2), ("A", 0, 0), ("B", 2, 1), ("C", 1, 2)]]
    assert [(x["topic"], x["rank"]) for x in by_importance(s)] == [("B", 1), ("A", 2), ("A", 1), ("C", 2), ("A", 0)]
    assert [x["topic"] for x in pick(by_importance(s))] == ["B", "A", "C", "A", "A"]
    assert [[t for t, _ in c] for c in columns(pick(by_importance(s)))] == [["B", "C"], ["A"]]
    lead = {"title": "Cards on the table: The good and bad of Anwar's 4 years in power", "dek": "x " * 95}
    first = [{"title": "Are mental illnesses universal, or are they culturally specific?", "photo": ("", 0, 180)}]
    assert lead_photo_height(lead, first) == 447
    assert lead_photo_height({"title": "x " * 200, "dek": ""}, first) == 200
    sys.exit(main())
