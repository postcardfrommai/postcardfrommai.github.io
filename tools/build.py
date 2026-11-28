"""Builds the public website for Postcards from Mai.

Runs automatically on GitHub after every post (see .github/workflows/publish.yml):
  1. Reads every entry in content/<type>/*.md
  2. Writes them all into _site/entries.json for the page to show
  3. Copies each photo into _site/media after removing its hidden data
     (GPS location, phone model, time), resizing it for the web,
     and adding the "© Postcards from Mai" watermark.
"""
import datetime as dt
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
MARK = "© Postcards from Mai"
MAX_SIDE = 1600

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


def media_path(p):
    p = str(p or "").strip().lstrip("/")
    return p if SAFE.match(p) else None


def public_name(p):
    """Neutral file name for the site, so phone names (which carry the date and time) never show."""
    ext = Path(p).suffix.lower().replace(".jpeg", ".jpg")
    return "media/" + hashlib.sha256(p.encode()).hexdigest()[:12] + ext


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
            except Exception as err:  # a broken photo should not stop the whole site
                print(f"Skipped {p}: {err}", file=sys.stderr)
        else:
            print(f"Missing photo {p}", file=sys.stderr)

    (OUT / "entries.json").write_text(json.dumps({"entries": entries, "about": about}, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Built {len(entries)} entries and {len(used)} photos.")


if __name__ == "__main__":
    main()
