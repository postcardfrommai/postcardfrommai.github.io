"""Builds the public website for Postcard from Mai.

Runs automatically on GitHub after every post (see .github/workflows/publish.yml):
  1. Reads every entry in content/<type>/*.md
  2. Writes them all into _site/entries.json for the page to show
  3. Copies each photo into _site/media after removing its hidden data
     (GPS location, phone model, time), resizing it for the web,
     and adding the "© Postcard from Mai" watermark.
"""
import datetime as dt
import html
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
FONT = ROOT / "tools" / "LiberationSerif-Italic.ttf"
MARK = "© Postcard from Mai"
MAX_SIDE = 1600
SITE = "https://postcardfrommai.github.io"
VARIANTS = (480, 960)  # smaller copies for phones, named <name>-480.jpg and <name>-960.jpg
DIMS = {}  # public photo path -> (width, height)

TYPES = {"books": "book", "coffee": "coffee", "watched": "watched", "music": "music", "photos": "photo"}
BODY = {"book": "review", "coffee": "note", "watched": "review", "music": "why", "photo": "note"}
IMAGE_FIELDS = ("photo", "cover", "poster", "photos")
SAFE = re.compile(r"^media/[A-Za-z0-9._-]+\.(jpe?g|png|webp)$", re.I)


def read_entry(path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
    return meta, body.strip()


def plain(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items() if x not in (None, "", [])}
    if isinstance(v, list):
        return [plain(x) for x in v if x not in (None, "")]
    return v


def clock(v):
    """Times typed as 19:30 come out of YAML as 1170 (minutes); turn any form back into HH:MM."""
    if isinstance(v, bool) or v is None:
        return ""
    if isinstance(v, int):
        return f"{(v // 60) % 24:02d}:{v % 60:02d}" if 0 <= v < 24 * 60 else ""
    if isinstance(v, (dt.time, dt.datetime)):
        return v.strftime("%H:%M")
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", str(v))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else str(v)[:5]


def media_path(p):
    p = str(p or "").strip().lstrip("/")
    return p if SAFE.match(p) else None


def public_name(p):
    """Neutral file name for the site, so phone names (which carry the date and time) never show."""
    ext = Path(p).suffix.lower().replace(".jpeg", ".jpg")
    return "media/" + hashlib.sha256(p.encode()).hexdigest()[:12] + ext


def save_variants(dst):
    """Phone-sized copies of an already processed photo (watermark scales with it)."""
    img = Image.open(dst)
    DIMS[str(dst.relative_to(OUT))] = img.size
    for w in VARIANTS:
        v = img.copy()
        if v.width > w:
            v.thumbnail((w, w * 10), Image.LANCZOS)
        out = dst.with_name(f"{dst.stem}-{w}{dst.suffix}")
        fmt = "PNG" if dst.suffix.lower() == ".png" else "WEBP" if dst.suffix.lower() == ".webp" else "JPEG"
        v.convert("RGB" if fmt == "JPEG" else v.mode).save(out, fmt, **({"quality": 80, "optimize": True, "progressive": True} if fmt == "JPEG" else {}))
        DIMS[str(out.relative_to(OUT))] = v.size


def watermark(src, dst, mark=True):
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")  # upright, metadata dropped
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    w, h = img.size
    if not mark:  # still upright, resized and stripped of hidden data, just no watermark
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "JPEG" if dst.suffix.lower() in (".jpg", ".jpeg") else dst.suffix.lstrip(".").upper().replace("JPG", "JPEG"), **({"quality": 82, "optimize": True, "progressive": True} if dst.suffix.lower() in (".jpg", ".jpeg") else {}))
        return
    size = max(16, int(min(w, h) * 0.035))
    font = ImageFont.truetype(str(FONT), size)
    box = ImageDraw.Draw(img).textbbox((0, 0), MARK, font=font)
    m = int(size * 0.9)
    x, y = w - (box[2] - box[0]) - m, h - (box[3] - box[1]) - m - box[1]
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((x, y), MARK, font=font, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size // 10)))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((x, y), MARK, font=font, fill=(255, 255, 255, 170))
    out = Image.alpha_composite(Image.alpha_composite(img.convert("RGBA"), shadow), layer).convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    fmt = "PNG" if dst.suffix.lower() == ".png" else "WEBP" if dst.suffix.lower() == ".webp" else "JPEG"
    out.save(dst, fmt, **({"quality": 82, "optimize": True, "progressive": True} if fmt == "JPEG" else {}))


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for f in (ROOT / "site").iterdir():  # the page(s), favicon, share image
        if f.is_file() and f.suffix in (".html", ".svg", ".png", ".ico", ".webmanifest") and not f.name.endswith(".svg.html"):
            shutil.copy(f, OUT / f.name)
    (OUT / ".nojekyll").write_text("")

    entries, used, ids = [], set(), set()
    for folder, kind in TYPES.items():
        for path in sorted((ROOT / "content" / folder).glob("*.md")):
            meta, body = read_entry(path)
            e = plain(meta)
            if e.get("draft"):
                continue
            e["type"] = kind
            if "time" in meta:
                e["time"] = clock(meta["time"])
                if not e["time"]:
                    e.pop("time")
            # web address uses the title only, never the upload date in the file name
            stem = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", path.stem) or "entry"
            base = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", f"{kind}-{stem}".lower())).strip("-")
            e["id"], n = base, 2
            while e["id"] in ids:
                e["id"], n = f"{base}-{n}", n + 1
            ids.add(e["id"])
            if body:
                e[BODY[kind]] = body
            e.pop("body", None)
            for f in IMAGE_FIELDS:
                if f not in e:
                    continue
                if f == "photos":
                    vals = e[f] if isinstance(e[f], list) else [e[f]]
                    found = [p for p in (media_path(v) for v in vals) if p]
                    used.update(found)
                    e[f] = [public_name(p) for p in found]
                else:
                    p = media_path(e[f])
                    if p:
                        e[f] = public_name(p)
                        used.add(p)
                    else:
                        e.pop(f)
            entries.append(e)

    about, unmarked = {}, set()
    about_file = ROOT / "content" / "about.md"
    if about_file.exists():
        meta, body = read_entry(about_file)
        about = plain(meta)
        if body:
            about["text"] = body
        about.pop("body", None)
        p = media_path(about.get("photo"))
        if p:
            about["photo"] = public_name(p)
            used.add(p)
            unmarked.add(p)  # the About photo is often someone else's: never stamp it as Mai's
        else:
            about.pop("photo", None)

    for p in sorted(used):
        src = ROOT / p
        if src.exists():
            try:
                watermark(src, OUT / public_name(p), mark=p not in unmarked)
                save_variants(OUT / public_name(p))
            except Exception as err:  # a broken photo should not stop the whole site
                print(f"Skipped {p}: {err}", file=sys.stderr)
        else:
            print(f"Missing photo {p}", file=sys.stderr)

    (OUT / "entries.json").write_text(json.dumps({"entries": entries, "about": about}, ensure_ascii=False, default=str), encoding="utf-8")
    pages = build_post_pages(entries)
    print(f"Built {len(entries)} entries, {len(used)} photos and {pages} post pages.")


KIND_WORD = {"book": "Book", "coffee": "Coffee postcard", "watched": "Watched", "music": "Music", "photo": "Photo"}


def describe(e):
    text = e.get(BODY.get(e["type"], ""), "") or e.get("summary", "") or ""
    text = re.sub(r"\s+", " ", str(text)).strip()
    t = e["type"]
    lead = {
        "book": f"{e.get('title', '')} by {e.get('author', '')}".strip(" by") + (f", {e['rating']}/5 stars" if e.get("rating") else ""),
        "coffee": f"A postcard from {e.get('title', '')}" + (f", {e['area']}" if e.get("area") else "") + (f" ({e['rating']}/10)" if e.get("rating") not in (None, "") else ""),
        "watched": f"{e.get('title', '')}" + (f", {e['rating']}/5" if e.get("rating") else ""),
        "music": f"{e.get('title', '')}" + (f" by {e['artist']}" if e.get("artist") else ""),
        "photo": e.get("title") or e.get("caption") or "A photo",
    }.get(t, e.get("title", ""))
    out = f"{lead}. {text}" if text else f"{lead}. From Postcard from Mai."
    return out if len(out) <= 160 else out[:157].rsplit(" ", 1)[0] + "…"


def page_title(e):
    name = e.get("title") or e.get("caption") or KIND_WORD.get(e["type"], "Post")
    if e["type"] == "music" and e.get("artist"):
        name = f"{name} by {e['artist']}"
    if e["type"] == "book" and e.get("author"):
        name = f"{name} by {e['author']}"
    return f"{name} · Postcard from Mai"


def prerender(e):
    """Plain readable version of the post for search engines and slow connections; the page script replaces it."""
    esc = lambda v: html.escape(str(v or ""))
    img = e.get("photo") or e.get("cover") or e.get("poster")
    body = e.get(BODY.get(e["type"], ""), "")
    parts = [f'<p class="label">{esc(KIND_WORD.get(e["type"], ""))}</p>', f"<h1>{esc(e.get('title') or e.get('caption'))}</h1>"]
    for k in ("author", "artist", "area"):
        if e.get(k):
            parts.append(f"<p>{esc(e[k])}</p>")
    if img:
        parts.append(f'<img src="/{esc(img.rsplit(".", 1)[0])}-960.{esc(img.rsplit(".", 1)[1])}" alt="{esc(e.get("title") or e.get("caption"))}" style="max-width:100%;height:auto">')
    for para in re.split(r"\n\s*\n", str(body or "")):
        if para.strip():
            parts.append(f"<p>{esc(para.strip())}</p>")
    return '<article style="max-width:720px;margin:0 auto;padding:48px 18px">' + "".join(parts) + "</article>"


def build_post_pages(entries):
    tpl = (OUT / "index.html").read_text(encoding="utf-8")
    urls = [SITE + "/"]
    for e in entries:
        url = f"{SITE}/p/{e['id']}/"
        title, desc = page_title(e), describe(e)
        img = e.get("photo") or e.get("cover") or e.get("poster")
        q = lambda v: html.escape(v, quote=True)
        head = tpl
        head = re.sub(r"<title>.*?</title>", f"<title>{html.escape(title)}</title>", head, count=1)
        head = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{q(desc)}">', head, count=1)
        head = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{q(title)}">', head, count=1)
        head = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{q(desc)}">', head, count=1)
        head = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{q(url)}">', head, count=1)
        head = head.replace('<meta property="og:type" content="website">', '<meta property="og:type" content="article">', 1)
        if img:
            v = img.rsplit(".", 1)[0] + "-960." + img.rsplit(".", 1)[1]
            w, h = DIMS.get(v, (960, 720))
            head = re.sub(r'<meta property="og:image" content="[^"]*">', f'<meta property="og:image" content="{SITE}/{q(v)}">', head, count=1)
            head = re.sub(r'<meta property="og:image:width" content="\d+">', f'<meta property="og:image:width" content="{w}">', head, count=1)
            head = re.sub(r'<meta property="og:image:height" content="\d+">', f'<meta property="og:image:height" content="{h}">', head, count=1)
        head = head.replace("<head>\n", f'<head>\n<base href="/">\n<link rel="canonical" href="{q(url)}">\n', 1)
        head = head.replace("<script>\n{\nconst view", f"<script>window.__ENTRY__ = {json.dumps(e['id'])};</script>\n<script>\n{{\nconst view", 1)
        assert "window.__ENTRY__" in head, "page script marker not found"
        head = re.sub(r'(<main id="view" aria-live="polite">).*?(</main>)', lambda m: m.group(1) + prerender(e) + m.group(2), head, count=1, flags=re.S)
        d = OUT / "p" / e["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(head, encoding="utf-8")
        urls.append(url)
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"<url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    return len(entries)


if __name__ == "__main__":
    main()
